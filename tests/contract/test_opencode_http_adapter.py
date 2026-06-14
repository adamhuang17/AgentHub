from services.api.app.agents import runtime_status as runtime_status_module
from services.api.app.agents.adapters.opencode_http import OpenCodeHttpAdapter
from services.api.app.agents.provider_config import validate_provider_config


class _FakeResponse:
    status = 200

    def __init__(self, body: bytes = b"[]") -> None:
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def read(self) -> bytes:
        return self.body


class _FakeOpener:
    def __init__(self, captured: dict[str, object], body: bytes = b"[]") -> None:
        self.captured = captured
        self.body = body

    def open(self, req, *, timeout):
        self.captured["url"] = req.full_url
        self.captured["timeout"] = timeout
        return _FakeResponse(self.body)


def _opencode_config():
    return validate_provider_config(
        {
            "provider": "opencode",
            "adapter_kind": "opencode_http",
            "backend_type": "coding_agent_backend",
            "api_base": "http://127.0.0.1:4096",
            "model": None,
            "credential_source": None,
            "executable_path": None,
            "timeout_seconds": 30,
            "max_output_tokens": 128,
            "temperature": 0.2,
            "workspace_mode": "none",
            "allowed_tools": [],
            "health_check_strategy": "direct_probe",
        }
    )


def test_opencode_adapter_probe_uses_no_proxy_opener(monkeypatch):
    captured: dict[str, object] = {}

    def fail_urlopen(*args, **kwargs):
        raise AssertionError("AgentHub coding adapter must not use default proxy-aware urlopen")

    def fake_build_opener(*handlers):
        captured["handlers"] = handlers
        return _FakeOpener(captured, body=b"[]")

    monkeypatch.setattr("services.api.app.agents.adapters.opencode_http.request.urlopen", fail_urlopen)
    monkeypatch.setattr("services.api.app.agents.adapters.opencode_http.request.build_opener", fake_build_opener)

    health = OpenCodeHttpAdapter(config=_opencode_config()).health()

    assert health.configured is True
    assert health.status == "ready"
    assert captured["url"] == "http://127.0.0.1:4096/session?limit=1"
    assert captured["timeout"] == 5
    assert captured["handlers"]


def test_opencode_runtime_probe_uses_no_proxy_opener(monkeypatch):
    captured: dict[str, object] = {}

    def fail_urlopen(*args, **kwargs):
        raise AssertionError("AgentHub runtime probe must not use default proxy-aware urlopen")

    def fake_build_opener(*handlers):
        captured["handlers"] = handlers
        return _FakeOpener(captured, body=b"{}")

    monkeypatch.setattr(runtime_status_module.request, "urlopen", fail_urlopen)
    monkeypatch.setattr(runtime_status_module.request, "build_opener", fake_build_opener)

    ok, message = runtime_status_module._probe_opencode("http://127.0.0.1:4096", timeout_seconds=5)

    assert ok is True
    assert message == "AgentHub coding runtime is reachable."
    assert captured["url"] == "http://127.0.0.1:4096/session?limit=1"
    assert captured["timeout"] == 5
    assert captured["handlers"]
