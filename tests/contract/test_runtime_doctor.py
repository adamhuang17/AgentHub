import json
from http import HTTPStatus

import pytest

from services.api.app.agents.adapters.custom_openai import CustomOpenAIAdapter, _CompletionResult
from services.api.app.agents.adapters.cli_process import CliProcessResult
from services.api.app.agents.routes import handle_get
from services.api.app.agents import runtime_status as runtime_status_module
from services.api.app.shared.runtime_diagnostics import runtime_diagnostics


MODEL_PROVIDER_ENV_NAMES = [
    "AGENTHUB_MODEL_PROVIDER",
    "AGENTHUB_DEMO_MODEL_PROVIDER",
    "AGENTHUB_PROVIDER_QWEN_API_BASE",
    "AGENTHUB_PROVIDER_QWEN_MODEL",
    "AGENTHUB_PROVIDER_QWEN_API_KEY",
    "AGENTHUB_QWEN_TURBO_API_BASE",
    "AGENTHUB_QWEN_TURBO_MODEL",
    "AGENTHUB_QWEN_TURBO_API_KEY",
    "AGENTHUB_QWEN_API_BASE",
    "AGENTHUB_QWEN_MODEL",
    "AGENTHUB_QWEN_API_KEY",
    "AGENTHUB_CUSTOM_OPENAI_API_BASE",
    "AGENTHUB_CUSTOM_OPENAI_MODEL",
    "AGENTHUB_CUSTOM_OPENAI_API_KEY",
]

CODEX_EXECUTABLE_ENV_NAMES = [
    "AGENTHUB_CODEX_EXECUTABLE",
    "CODEX_EXECUTABLE",
    "AGENTHUB_CODEX_CLI_EXECUTABLE",
]


def _clear_model_provider_env(monkeypatch):
    for name in MODEL_PROVIDER_ENV_NAMES:
        monkeypatch.setenv(name, "")


def _clear_codex_executable_env(monkeypatch):
    for name in CODEX_EXECUTABLE_ENV_NAMES:
        monkeypatch.setenv(name, "")


def _configure_missing_claude(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENTHUB_CLAUDE_CODE_EXECUTABLE", str(tmp_path / "missing-claude.exe"))
    monkeypatch.setenv("AGENTHUB_CLAUDE_EXECUTABLE", "")
    monkeypatch.setenv("CLAUDE_CODE_EXECUTABLE", "")


def _stub_custom_openai_probe(monkeypatch):
    def fake_chat_completion(self, prompt, *, timeout_seconds, max_tokens):
        return _CompletionResult(
            content_text="OK",
            usage=None,
            raw_response={"choices": [{"message": {"content": "OK"}}]},
        )

    monkeypatch.setattr(CustomOpenAIAdapter, "_chat_completion", fake_chat_completion)


def test_runtime_doctor_reports_non_sensitive_status(monkeypatch, tmp_path):
    secret = "sk-doctor-secret-value"
    _clear_model_provider_env(monkeypatch)
    monkeypatch.setenv("AGENTHUB_PROFILE", "demo")
    monkeypatch.setenv("AGENTHUB_ENV", "demo")
    monkeypatch.setenv("AGENTHUB_DB_PATH", str(tmp_path / "doctor.sqlite3"))
    monkeypatch.setenv("AGENTHUB_ARTIFACT_STORE_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("AGENTHUB_STATIC_DEPLOY_DIR", str(tmp_path / "static"))
    monkeypatch.setenv("AGENTHUB_TURN_ROUTER_BACKEND", "openai_compatible")
    monkeypatch.setenv("AGENTHUB_TURN_ROUTER_BASE_URL", "https://router.example.test/v1")
    monkeypatch.setenv("AGENTHUB_TURN_ROUTER_API_KEY", secret)
    monkeypatch.setenv("AGENTHUB_TURN_ROUTER_MODEL", "router-model")
    monkeypatch.setenv("AGENTHUB_CUSTOM_OPENAI_API_BASE", "")
    monkeypatch.setenv("AGENTHUB_CUSTOM_OPENAI_MODEL", "")
    monkeypatch.setenv("AGENTHUB_CUSTOM_OPENAI_API_KEY", "")

    payload = runtime_diagnostics(check_writable=True)
    blob = json.dumps(payload)

    assert payload["api_status"] == "ok"
    assert payload["env_profile"] == "demo"
    assert payload["turn_router_backend"] == "openai_compatible"
    assert payload["turn_router_configured"] is True
    assert payload["custom_openai_configured"] is False
    assert "custom_openai_not_configured" in payload["warnings"]
    assert secret not in blob


def test_doctor_payload_shape(monkeypatch, tmp_path):
    _clear_model_provider_env(monkeypatch)
    monkeypatch.setenv("AGENTHUB_PROFILE", "demo")
    monkeypatch.setenv("AGENTHUB_DB_PATH", str(tmp_path / "shape.sqlite3"))
    monkeypatch.setenv("AGENTHUB_ARTIFACT_STORE_DIR", str(tmp_path / "shape-artifacts"))

    payload = runtime_diagnostics()

    for key in {
        "api_status",
        "env_profile",
        "loaded_env_files",
        "explicit_env_file_configured",
        "explicit_env_file_used",
        "db_configured",
        "artifact_store_configured",
        "turn_router_backend",
        "turn_router_configured",
        "agents_enabled_count",
        "agents_configured_count",
        "codex_cli_configured",
        "custom_openai_configured",
        "static_deploy_configured",
        "warnings",
    }:
        assert key in payload
    assert "sk-" not in json.dumps(payload).lower()


def test_doctor_loaded_env_files_contains_paths_not_values(monkeypatch, tmp_path):
    """loaded_env_files contains file paths but never secret values."""
    secret = "sk-super-secret-abc123"
    monkeypatch.setenv("AGENTHUB_PROFILE", "demo")
    monkeypatch.setenv("AGENTHUB_DB_PATH", str(tmp_path / "secret-test.sqlite3"))
    monkeypatch.setenv("AGENTHUB_CUSTOM_OPENAI_API_KEY", secret)

    payload = runtime_diagnostics()

    blob = json.dumps(payload)
    assert "loaded_env_files" in payload
    assert isinstance(payload["loaded_env_files"], list)
    assert secret not in blob


def test_doctor_explicit_env_file_not_configured(monkeypatch, tmp_path):
    """explicit_env_file flags are False when AGENTHUB_ENV_FILE is not set."""
    monkeypatch.setenv("AGENTHUB_PROFILE", "demo")
    monkeypatch.setenv("AGENTHUB_DB_PATH", str(tmp_path / "explicit.sqlite3"))

    payload = runtime_diagnostics()
    assert payload["explicit_env_file_configured"] is False
    assert payload["explicit_env_file_used"] is False


def test_doctor_env_file_not_found_warning(monkeypatch, tmp_path):
    """env_file_not_found warning when AGENTHUB_ENV_FILE points to missing file."""
    monkeypatch.setenv("AGENTHUB_PROFILE", "demo")
    monkeypatch.setenv("AGENTHUB_DB_PATH", str(tmp_path / "missing.sqlite3"))
    monkeypatch.setenv("AGENTHUB_ENV_FILE", str(tmp_path / "does_not_exist.env"))

    payload = runtime_diagnostics()

    assert payload["explicit_env_file_configured"] is True
    assert payload["explicit_env_file_used"] is False
    assert "env_file_not_found" in payload["warnings"]


def test_doctor_no_env_file_not_found_when_file_exists(monkeypatch, tmp_path):
    """No env_file_not_found warning when AGENTHUB_ENV_FILE points to existing file."""
    env_file = tmp_path / "real.env"
    env_file.write_text("PORT=9999\n", encoding="utf-8")
    monkeypatch.setenv("AGENTHUB_PROFILE", "demo")
    monkeypatch.setenv("AGENTHUB_DB_PATH", str(tmp_path / "exists.sqlite3"))
    monkeypatch.setenv("AGENTHUB_ENV_FILE", str(env_file))

    payload = runtime_diagnostics()

    assert payload["explicit_env_file_configured"] is True
    assert payload["explicit_env_file_used"] is True
    assert "env_file_not_found" not in payload["warnings"]


def test_doctor_shows_profile_and_provider_status(monkeypatch, tmp_path):
    """Doctor reports profile, turn_router, provider, and codex status."""
    monkeypatch.setenv("AGENTHUB_PROFILE", "demo")
    monkeypatch.setenv("AGENTHUB_DB_PATH", str(tmp_path / "status.sqlite3"))

    payload = runtime_diagnostics()

    assert payload["env_profile"] == "demo"
    assert "turn_router_configured" in payload
    assert "codex_cli_configured" in payload
    assert "custom_openai_configured" in payload
    assert isinstance(payload["loaded_env_files"], list)


def test_doctor_no_secret_in_output(monkeypatch, tmp_path):
    """Doctor output never contains API keys or tokens."""
    secret_key = "sk-very-secret-api-key-12345"
    monkeypatch.setenv("AGENTHUB_PROFILE", "demo")
    monkeypatch.setenv("AGENTHUB_DB_PATH", str(tmp_path / "nosecret.sqlite3"))
    monkeypatch.setenv("AGENTHUB_TURN_ROUTER_API_KEY", secret_key)
    monkeypatch.setenv("AGENTHUB_CUSTOM_OPENAI_API_KEY", secret_key)

    payload = runtime_diagnostics()
    blob = json.dumps(payload)

    assert secret_key not in blob


def test_codex_executable_missing_reports_not_configured_no_exec(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENTHUB_PROFILE", "demo")
    monkeypatch.setenv("AGENTHUB_DB_PATH", str(tmp_path / "codex-missing.sqlite3"))
    _clear_codex_executable_env(monkeypatch)
    monkeypatch.setenv("AGENTHUB_CODEX_EXECUTABLE", str(tmp_path / "missing-codex.exe"))
    _configure_missing_claude(monkeypatch, tmp_path)
    monkeypatch.setenv("AGENTHUB_CUSTOM_OPENAI_API_BASE", "")
    monkeypatch.setenv("AGENTHUB_CUSTOM_OPENAI_MODEL", "")
    monkeypatch.setenv("AGENTHUB_CUSTOM_OPENAI_API_KEY", "")

    payload = runtime_diagnostics()
    codex = next(agent for agent in payload["agents"] if agent["provider"] == "codex")

    assert payload["codex_cli_configured"] is False
    assert payload["codex_cli_error_code"] == "codex_executable_missing"
    assert codex["configured"] is False
    assert codex["execution_enabled"] is False
    assert codex["runtime_status"] == "not_configured"
    assert codex["executable_path_configured"] is False
    assert codex["credentials_configured"] is False
    assert payload["codex_executable_detected_path"] is None
    assert payload["codex_preflight_command"].endswith("--version")


def test_codex_executable_exists_but_preflight_fails_reports_configured_path(monkeypatch, tmp_path):
    codex_path = tmp_path / "codex-not-runnable.txt"
    codex_path.write_text("not an executable", encoding="utf-8")
    monkeypatch.setenv("AGENTHUB_PROFILE", "demo")
    monkeypatch.setenv("AGENTHUB_DB_PATH", str(tmp_path / "codex-preflight.sqlite3"))
    _clear_codex_executable_env(monkeypatch)
    monkeypatch.setenv("AGENTHUB_CODEX_EXECUTABLE", str(codex_path))
    _configure_missing_claude(monkeypatch, tmp_path)
    monkeypatch.setenv("AGENTHUB_CUSTOM_OPENAI_API_BASE", "")
    monkeypatch.setenv("AGENTHUB_CUSTOM_OPENAI_MODEL", "")
    monkeypatch.setenv("AGENTHUB_CUSTOM_OPENAI_API_KEY", "")

    payload = runtime_diagnostics()
    codex = next(agent for agent in payload["agents"] if agent["provider"] == "codex")

    assert payload["codex_cli_configured"] is True
    assert payload["codex_cli_error_code"] == "codex_preflight_failed"
    assert payload["codex_executable_detected_path"] == str(codex_path)
    assert codex["configured"] is True
    assert codex["runtime_status"] == "preflight_failed"
    assert codex["error_code"] == "codex_preflight_failed"
    assert codex["executable_path_configured"] is True


@pytest.mark.parametrize(
    "env_name",
    ["AGENTHUB_CODEX_EXECUTABLE", "CODEX_EXECUTABLE", "AGENTHUB_CODEX_CLI_EXECUTABLE"],
)
def test_codex_executable_aliases_existing_path_are_not_missing(monkeypatch, tmp_path, env_name):
    codex_path = tmp_path / f"{env_name.lower()}.txt"
    codex_path.write_text("present but not runnable", encoding="utf-8")
    monkeypatch.setenv("AGENTHUB_PROFILE", "demo")
    monkeypatch.setenv("AGENTHUB_DB_PATH", str(tmp_path / f"{env_name.lower()}.sqlite3"))
    _clear_codex_executable_env(monkeypatch)
    monkeypatch.setenv(env_name, str(codex_path))
    _configure_missing_claude(monkeypatch, tmp_path)
    monkeypatch.setenv("AGENTHUB_CUSTOM_OPENAI_API_BASE", "")
    monkeypatch.setenv("AGENTHUB_CUSTOM_OPENAI_MODEL", "")
    monkeypatch.setenv("AGENTHUB_CUSTOM_OPENAI_API_KEY", "")

    payload = runtime_diagnostics()
    codex = next(agent for agent in payload["agents"] if agent["provider"] == "codex")

    assert payload["codex_cli_configured"] is True
    assert payload["codex_cli_error_code"] != "codex_executable_missing"
    assert codex["error_code"] != "codex_executable_missing"
    assert codex["executable_path_configured"] is True
    assert payload["codex_executable_detected_path"] == str(codex_path)


def test_codex_executable_alias_skips_earlier_missing_value(monkeypatch, tmp_path):
    missing_path = tmp_path / "missing-codex.exe"
    codex_path = tmp_path / "codex-present.txt"
    codex_path.write_text("present but not runnable", encoding="utf-8")
    monkeypatch.setenv("AGENTHUB_PROFILE", "demo")
    monkeypatch.setenv("AGENTHUB_DB_PATH", str(tmp_path / "codex-alias-fallback.sqlite3"))
    _clear_codex_executable_env(monkeypatch)
    monkeypatch.setenv("AGENTHUB_CODEX_EXECUTABLE", str(missing_path))
    monkeypatch.setenv("CODEX_EXECUTABLE", str(codex_path))
    _configure_missing_claude(monkeypatch, tmp_path)
    monkeypatch.setenv("AGENTHUB_CUSTOM_OPENAI_API_BASE", "")
    monkeypatch.setenv("AGENTHUB_CUSTOM_OPENAI_MODEL", "")
    monkeypatch.setenv("AGENTHUB_CUSTOM_OPENAI_API_KEY", "")

    payload = runtime_diagnostics()
    codex = next(agent for agent in payload["agents"] if agent["provider"] == "codex")

    assert payload["codex_cli_configured"] is True
    assert payload["codex_cli_error_code"] == "codex_preflight_failed"
    assert codex["error_code"] == "codex_preflight_failed"
    assert payload["codex_executable_detected_path"] == str(codex_path)


def test_codex_version_success_marks_ready(monkeypatch, tmp_path):
    codex_path = tmp_path / "codex.exe"
    codex_path.write_text("fake executable", encoding="utf-8")
    captured: dict[str, object] = {}

    def fake_run_cli_process(argv, *, cwd, timeout_seconds):
        captured["argv"] = list(argv)
        captured["cwd"] = str(cwd)
        captured["timeout_seconds"] = timeout_seconds
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
    monkeypatch.setenv("AGENTHUB_PROFILE", "demo")
    monkeypatch.setenv("AGENTHUB_DB_PATH", str(tmp_path / "codex-ready.sqlite3"))
    _clear_codex_executable_env(monkeypatch)
    monkeypatch.setenv("AGENTHUB_CODEX_EXECUTABLE", str(codex_path))
    _configure_missing_claude(monkeypatch, tmp_path)
    monkeypatch.setenv("AGENTHUB_CUSTOM_OPENAI_API_BASE", "")
    monkeypatch.setenv("AGENTHUB_CUSTOM_OPENAI_MODEL", "")
    monkeypatch.setenv("AGENTHUB_CUSTOM_OPENAI_API_KEY", "")

    payload = runtime_diagnostics()
    codex = next(agent for agent in payload["agents"] if agent["provider"] == "codex")

    assert captured["argv"] == [str(codex_path), "--version"]
    assert "exec" not in captured["argv"]
    assert "workspace-write" not in captured["argv"]
    assert "danger-full-access" not in captured["argv"]
    assert payload["codex_cli_configured"] is True
    assert payload["codex_cli_runtime_status"] == "ready"
    assert payload["codex_cli_error_code"] is None
    assert codex["configured"] is True
    assert codex["execution_enabled"] is True
    assert codex["health_status"] == "ready"
    assert codex["runtime_status"] == "ready"
    assert codex["error_code"] is None


def test_custom_openai_env_configured_marks_demo_model_configured(monkeypatch, tmp_path):
    _stub_custom_openai_probe(monkeypatch)
    monkeypatch.setenv("AGENTHUB_PROFILE", "demo")
    monkeypatch.setenv("AGENTHUB_DB_PATH", str(tmp_path / "custom-openai.sqlite3"))
    monkeypatch.setenv("AGENTHUB_MODEL_PROVIDER", "custom_openai")
    monkeypatch.setenv("AGENTHUB_CUSTOM_OPENAI_API_BASE", "https://model.example.test/v1")
    monkeypatch.setenv("AGENTHUB_CUSTOM_OPENAI_MODEL", "demo-model")
    monkeypatch.setenv("AGENTHUB_CUSTOM_OPENAI_API_KEY", "sk-test-runtime-doctor")
    _clear_codex_executable_env(monkeypatch)
    monkeypatch.setenv("AGENTHUB_CODEX_EXECUTABLE", str(tmp_path / "missing-codex.exe"))
    _configure_missing_claude(monkeypatch, tmp_path)

    payload = runtime_diagnostics()
    model_agent = next(agent for agent in payload["agents"] if agent["id"] == "agent-demo-model")
    blob = json.dumps(payload)

    assert payload["custom_openai_configured"] is True
    assert model_agent["configured"] is True
    assert model_agent["execution_enabled"] is True
    assert model_agent["health_status"] == "ready"
    assert model_agent["runtime_status"] == "ready"
    assert model_agent["credentials_configured"] is True
    assert "sk-test-runtime-doctor" not in blob


def test_qwen_provider_alias_marks_demo_model_ready_and_reports_aliases(monkeypatch, tmp_path):
    _stub_custom_openai_probe(monkeypatch)
    _clear_model_provider_env(monkeypatch)
    _clear_codex_executable_env(monkeypatch)
    secret = "sk-qwen-runtime-secret"
    monkeypatch.setenv("AGENTHUB_PROFILE", "demo")
    monkeypatch.setenv("AGENTHUB_DB_PATH", str(tmp_path / "qwen-runtime.sqlite3"))
    monkeypatch.setenv("AGENTHUB_MODEL_PROVIDER", "qwen_turbo")
    monkeypatch.setenv("AGENTHUB_PROVIDER_QWEN_API_BASE", "https://qwen-runtime.example.test/v1")
    monkeypatch.setenv("AGENTHUB_PROVIDER_QWEN_MODEL", "qwen-turbo")
    monkeypatch.setenv("AGENTHUB_PROVIDER_QWEN_API_KEY", secret)
    monkeypatch.setenv("AGENTHUB_CODEX_EXECUTABLE", str(tmp_path / "missing-codex.exe"))
    _configure_missing_claude(monkeypatch, tmp_path)

    payload = runtime_diagnostics()
    model_agent = next(agent for agent in payload["agents"] if agent["id"] == "agent-demo-model")
    blob = json.dumps(payload)

    assert payload["custom_openai_configured"] is True
    assert payload["custom_openai_runtime_status"] == "ready"
    assert payload["provider_alias_used"] == "AGENTHUB_PROVIDER_QWEN_API_BASE"
    assert payload["model_alias_used"] == "AGENTHUB_PROVIDER_QWEN_MODEL"
    assert payload["key_alias_used"] == "AGENTHUB_PROVIDER_QWEN_API_KEY"
    assert model_agent["provider"] == "qwen_turbo"
    assert model_agent["configured"] is True
    assert model_agent["execution_enabled"] is True
    assert model_agent["health_status"] == "ready"
    assert model_agent["runtime_status"] == "ready"
    assert model_agent["credentials_configured"] is True
    assert secret not in blob


def test_doctor_configured_count_matches_api_agents(monkeypatch, tmp_path):
    _stub_custom_openai_probe(monkeypatch)
    _clear_model_provider_env(monkeypatch)
    _clear_codex_executable_env(monkeypatch)
    monkeypatch.setenv("AGENTHUB_PROFILE", "demo")
    monkeypatch.setenv("AGENTHUB_DB_PATH", str(tmp_path / "count-match.sqlite3"))
    monkeypatch.setenv("AGENTHUB_MODEL_PROVIDER", "qwen_turbo")
    monkeypatch.setenv("AGENTHUB_QWEN_TURBO_API_BASE", "https://qwen-count.example.test/v1")
    monkeypatch.setenv("AGENTHUB_QWEN_TURBO_MODEL", "qwen-turbo")
    monkeypatch.setenv("AGENTHUB_QWEN_TURBO_API_KEY", "sk-count-secret")
    monkeypatch.setenv("AGENTHUB_CODEX_EXECUTABLE", str(tmp_path / "missing-codex.exe"))
    _configure_missing_claude(monkeypatch, tmp_path)

    doctor = runtime_diagnostics()
    status, agents_payload = handle_get("/api/agents", {}, "count-match")
    assert status == HTTPStatus.OK
    api_agents = agents_payload["items"]

    assert doctor["agents_configured_count"] == sum(1 for agent in api_agents if agent["configured"] is True)
