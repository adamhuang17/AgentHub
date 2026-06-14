from http import HTTPStatus

from services.api.app.agents.adapters.custom_openai import CustomOpenAIAdapter, _CompletionResult
from services.api.app.agents.adapters.cli_process import CliProcessResult
from services.api.app.agents.routes import handle_get
from services.api.app.agents import runtime_status as runtime_status_module


CODEX_EXECUTABLE_ENV_NAMES = [
    "AGENTHUB_CODEX_EXECUTABLE",
    "CODEX_EXECUTABLE",
    "AGENTHUB_CODEX_CLI_EXECUTABLE",
]


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


def _clear_codex_executable_env(monkeypatch):
    for name in CODEX_EXECUTABLE_ENV_NAMES:
        monkeypatch.setenv(name, "")


def _clear_model_provider_env(monkeypatch):
    for name in MODEL_PROVIDER_ENV_NAMES:
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


def _agents(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENTHUB_PROFILE", "demo")
    monkeypatch.setenv("AGENTHUB_DB_PATH", str(tmp_path / "agents.sqlite3"))
    _clear_codex_executable_env(monkeypatch)
    monkeypatch.setenv("AGENTHUB_CODEX_EXECUTABLE", str(tmp_path / "missing-codex.exe"))
    _configure_missing_claude(monkeypatch, tmp_path)
    monkeypatch.setenv("AGENTHUB_CUSTOM_OPENAI_API_BASE", "")
    monkeypatch.setenv("AGENTHUB_CUSTOM_OPENAI_MODEL", "")
    monkeypatch.setenv("AGENTHUB_CUSTOM_OPENAI_API_KEY", "")
    status, payload = handle_get("/api/agents", {}, "runtime-status")
    assert status == HTTPStatus.OK
    return payload["items"]


def test_api_agents_includes_runtime_status_fields(monkeypatch, tmp_path):
    agents = _agents(monkeypatch, tmp_path)

    for agent in agents:
        assert {
            "enabled",
            "configured",
            "execution_enabled",
            "health_status",
            "runtime_status",
            "error_code",
            "executable_path_configured",
            "credentials_configured",
        }.issubset(agent)


def test_codex_missing_executable_is_not_configured_no_exec(monkeypatch, tmp_path):
    agents = _agents(monkeypatch, tmp_path)
    codex = next(agent for agent in agents if agent["provider"] == "codex")

    assert codex["configured"] is False
    assert codex["execution_enabled"] is False
    assert codex["runtime_status"] == "not_configured"
    assert codex["error_code"] == "codex_executable_missing"
    assert codex["executable_path_configured"] is False


def test_codex_preflight_failure_keeps_configured_path_visible(monkeypatch, tmp_path):
    codex_path = tmp_path / "codex-present-not-runnable.txt"
    codex_path.write_text("present", encoding="utf-8")
    monkeypatch.setenv("AGENTHUB_PROFILE", "demo")
    monkeypatch.setenv("AGENTHUB_DB_PATH", str(tmp_path / "agents-preflight.sqlite3"))
    _clear_codex_executable_env(monkeypatch)
    monkeypatch.setenv("AGENTHUB_CODEX_EXECUTABLE", str(codex_path))
    _configure_missing_claude(monkeypatch, tmp_path)
    monkeypatch.setenv("AGENTHUB_CUSTOM_OPENAI_API_BASE", "")
    monkeypatch.setenv("AGENTHUB_CUSTOM_OPENAI_MODEL", "")
    monkeypatch.setenv("AGENTHUB_CUSTOM_OPENAI_API_KEY", "")

    status, payload = handle_get("/api/agents", {}, "runtime-status")
    assert status == HTTPStatus.OK
    codex = next(agent for agent in payload["items"] if agent["provider"] == "codex")

    assert codex["configured"] is True
    assert codex["runtime_status"] == "preflight_failed"
    assert codex["error_code"] == "codex_preflight_failed"
    assert codex["executable_path_configured"] is True


def test_codex_version_success_marks_api_agent_ready(monkeypatch, tmp_path):
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
    monkeypatch.setenv("AGENTHUB_PROFILE", "demo")
    monkeypatch.setenv("AGENTHUB_DB_PATH", str(tmp_path / "agents-ready.sqlite3"))
    _clear_codex_executable_env(monkeypatch)
    monkeypatch.setenv("AGENTHUB_CODEX_EXECUTABLE", str(codex_path))
    _configure_missing_claude(monkeypatch, tmp_path)
    monkeypatch.setenv("AGENTHUB_CUSTOM_OPENAI_API_BASE", "")
    monkeypatch.setenv("AGENTHUB_CUSTOM_OPENAI_MODEL", "")
    monkeypatch.setenv("AGENTHUB_CUSTOM_OPENAI_API_KEY", "")

    status, payload = handle_get("/api/agents", {}, "runtime-status")
    assert status == HTTPStatus.OK
    codex = next(agent for agent in payload["items"] if agent["provider"] == "codex")

    assert codex["configured"] is True
    assert codex["execution_enabled"] is True
    assert codex["health_status"] == "ready"
    assert codex["runtime_status"] == "ready"
    assert codex["error_code"] is None


def test_custom_openai_env_configures_demo_model_agent(monkeypatch, tmp_path):
    _stub_custom_openai_probe(monkeypatch)
    _clear_model_provider_env(monkeypatch)
    monkeypatch.setenv("AGENTHUB_PROFILE", "demo")
    monkeypatch.setenv("AGENTHUB_DB_PATH", str(tmp_path / "agents-custom.sqlite3"))
    monkeypatch.setenv("AGENTHUB_MODEL_PROVIDER", "custom_openai")
    monkeypatch.setenv("AGENTHUB_CUSTOM_OPENAI_API_BASE", "https://model.example.test/v1")
    monkeypatch.setenv("AGENTHUB_CUSTOM_OPENAI_MODEL", "demo-model")
    monkeypatch.setenv("AGENTHUB_CUSTOM_OPENAI_API_KEY", "sk-test-agent-status")
    _clear_codex_executable_env(monkeypatch)
    monkeypatch.setenv("AGENTHUB_CODEX_EXECUTABLE", str(tmp_path / "missing-codex.exe"))
    _configure_missing_claude(monkeypatch, tmp_path)

    status, payload = handle_get("/api/agents", {}, "runtime-status")
    assert status == HTTPStatus.OK
    model_agent = next(agent for agent in payload["items"] if agent["id"] == "agent-demo-model")

    assert model_agent["configured"] is True
    assert model_agent["execution_enabled"] is True
    assert model_agent["health_status"] == "ready"
    assert model_agent["runtime_status"] == "ready"
    assert model_agent["credentials_configured"] is True


def test_qwen_provider_alias_configures_demo_model_agent(monkeypatch, tmp_path):
    _stub_custom_openai_probe(monkeypatch)
    _clear_model_provider_env(monkeypatch)
    monkeypatch.setenv("AGENTHUB_PROFILE", "demo")
    monkeypatch.setenv("AGENTHUB_DB_PATH", str(tmp_path / "agents-qwen.sqlite3"))
    monkeypatch.setenv("AGENTHUB_MODEL_PROVIDER", "qwen_turbo")
    monkeypatch.setenv("AGENTHUB_PROVIDER_QWEN_API_BASE", "https://qwen-agent.example.test/v1")
    monkeypatch.setenv("AGENTHUB_PROVIDER_QWEN_MODEL", "qwen-turbo")
    monkeypatch.setenv("AGENTHUB_PROVIDER_QWEN_API_KEY", "sk-test-qwen-agent-status")
    _clear_codex_executable_env(monkeypatch)
    monkeypatch.setenv("AGENTHUB_CODEX_EXECUTABLE", str(tmp_path / "missing-codex.exe"))
    _configure_missing_claude(monkeypatch, tmp_path)

    status, payload = handle_get("/api/agents", {}, "runtime-status")
    assert status == HTTPStatus.OK
    model_agent = next(agent for agent in payload["items"] if agent["id"] == "agent-demo-model")

    assert model_agent["provider"] == "qwen_turbo"
    assert model_agent["configured"] is True
    assert model_agent["execution_enabled"] is True
    assert model_agent["health_status"] == "ready"
    assert model_agent["runtime_status"] == "ready"
    assert model_agent["credentials_configured"] is True
