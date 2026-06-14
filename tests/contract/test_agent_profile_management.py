from http import HTTPStatus

import pytest

from services.api.app.agents.adapters.cli_process import CliProcessResult
from services.api.app.agents.adapters.custom_openai import CustomOpenAIAdapter, _CompletionResult
from services.api.app.agents import runtime_status as runtime_status_module
from services.api.app.agents.routes import handle_delete, handle_get, handle_patch, handle_post
from services.api.app.shared.errors import ValidationError


def _stub_custom_openai_probe(monkeypatch):
    def fake_chat_completion(self, prompt, *, timeout_seconds, max_tokens):
        return _CompletionResult(
            content_text="OK",
            usage=None,
            raw_response={"choices": [{"message": {"content": "OK"}}]},
        )

    monkeypatch.setattr(CustomOpenAIAdapter, "_chat_completion", fake_chat_completion)


def _isolated_db(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENTHUB_PROFILE", "demo")
    monkeypatch.setenv("AGENTHUB_DB_PATH", str(tmp_path / "agent-profile-management.sqlite3"))


def test_custom_cloud_agent_requires_connection_test_and_supports_edit_delete(monkeypatch, tmp_path):
    _isolated_db(monkeypatch, tmp_path)
    _stub_custom_openai_probe(monkeypatch)

    status, created = handle_post(
        "/api/agents",
        {
            "id": "agent-custom-cloud-contract",
            "name": "Contract Cloud Agent",
            "provider": "custom_openai",
            "agent_type": "custom_cloud",
            "api_base": "https://model.example.test/v1",
            "model": "contract-model",
            "api_key": "sk-contract-secret",
            "capability_tags": ["direct-response"],
            "connection_test_required": True,
        },
        "agent-profile-management",
    )

    assert status == HTTPStatus.CREATED
    assert created["kind"] == "custom"
    assert created["configured"] is True
    assert created["execution_enabled"] is True
    assert created["runtime_status"] == "ready"
    assert created["api_base"] == "https://model.example.test/v1"
    assert created["credential_source"] == "credential_ref:agent:agent-custom-cloud-contract:api_key"
    assert "api_key" not in created

    status, updated = handle_patch(
        "/api/agents/agent-custom-cloud-contract",
        {
            "name": "Edited Cloud Agent",
            "model": "edited-model",
            "api_key": "sk-edited-contract-secret",
            "connection_test_required": True,
        },
        "agent-profile-management",
    )

    assert status == HTTPStatus.OK
    assert updated["name"] == "Edited Cloud Agent"
    assert updated["model"] == "edited-model"
    assert updated["configured"] is True

    status, deleted = handle_delete("/api/agents/agent-custom-cloud-contract", "agent-profile-management")
    assert status == HTTPStatus.OK
    assert deleted == {"id": "agent-custom-cloud-contract", "deleted": True}

    status, payload = handle_get("/api/agents", {"kind": ["custom"]}, "agent-profile-management")
    assert status == HTTPStatus.OK
    assert all(agent["id"] != "agent-custom-cloud-contract" for agent in payload["items"])


def test_custom_cloud_agent_rejects_missing_connection_fields(monkeypatch, tmp_path):
    _isolated_db(monkeypatch, tmp_path)

    with pytest.raises(ValidationError) as exc_info:
        handle_post(
            "/api/agents",
            {
                "id": "agent-custom-cloud-invalid",
                "name": "Invalid Cloud Agent",
                "provider": "custom_openai",
                "agent_type": "custom_cloud",
                "api_base": "https://model.example.test/v1",
                "model": "contract-model",
                "connection_test_required": True,
            },
            "agent-profile-management",
        )

    assert exc_info.value.code == "provider_not_configured"


def test_local_cli_agent_requires_executable_path_and_preflight(monkeypatch, tmp_path):
    _isolated_db(monkeypatch, tmp_path)
    codex_path = tmp_path / "codex.exe"
    codex_path.write_text("fake executable", encoding="utf-8")

    def fake_run_cli_process(argv, *, cwd, timeout_seconds):
        return CliProcessResult(
            argv=list(argv),
            cwd=str(cwd),
            exit_code=0,
            stdout_lines=["codex-cli 0.137.0-alpha.4"],
            stderr_lines=[],
            raw_lines=[],
            timed_out=False,
            duration_seconds=0.01,
        )

    monkeypatch.setattr(runtime_status_module, "run_cli_process", fake_run_cli_process)

    status, created = handle_post(
        "/api/agents",
        {
            "id": "agent-local-cli-contract",
            "name": "Contract Local Agent",
            "provider": "codex",
            "agent_type": "local_cli",
            "executable_path": str(codex_path),
            "capability_tags": ["code"],
            "connection_test_required": True,
        },
        "agent-profile-management",
    )

    assert status == HTTPStatus.CREATED
    assert created["kind"] == "local"
    assert created["configured"] is True
    assert created["execution_enabled"] is True
    assert created["runtime_status"] == "ready"
    assert created["executable_path"] == str(codex_path)

    with pytest.raises(ValidationError) as exc_info:
        handle_post(
            "/api/agents",
            {
                "id": "agent-local-cli-invalid",
                "name": "Invalid Local Agent",
                "provider": "codex",
                "agent_type": "local_cli",
                "connection_test_required": True,
            },
            "agent-profile-management",
        )

    assert exc_info.value.code == "adapter_executable_not_found"
