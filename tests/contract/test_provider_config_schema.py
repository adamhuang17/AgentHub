import pytest

from services.api.app.agent_runs.schema import validate_agent_run_request
from services.api.app.agents.provider_config import validate_provider_config
from services.api.app.agents.provider_config import (
    CUSTOM_OPENAI_PROVIDER_KEYS,
    custom_openai_provider_configs_from_environment,
)
from services.api.app.shared.errors import ValidationError


def _config(**overrides):
    payload = {
        "provider": "openai",
        "adapter_kind": "custom_openai",
        "backend_type": "model_agent_backend",
        "api_base": "https://api.example.test/v1",
        "model": "example-model",
        "credential_source": "OPENAI_API_KEY",
        "executable_path": None,
        "timeout_seconds": 30,
        "max_output_tokens": 256,
        "temperature": 0.2,
        "workspace_mode": "none",
        "allowed_tools": [],
        "health_check_strategy": "direct_probe",
    }
    payload.update(overrides)
    return payload


def test_provider_config_validates_custom_openai():
    config = validate_provider_config(_config())

    assert config.provider == "openai"
    assert config.adapter_kind == "custom_openai"
    assert config.backend_type == "model_agent_backend"
    assert config.credential_source == "OPENAI_API_KEY"


def test_provider_config_builds_a7_3_1_custom_openai_providers_from_env(monkeypatch):
    provider_envs = {
        "qwen_turbo": (
            "AGENTHUB_PROVIDER_QWEN_API_BASE",
            "AGENTHUB_PROVIDER_QWEN_MODEL",
            "AGENTHUB_PROVIDER_QWEN_API_KEY",
        ),
        "volc_deepseek_flash": (
            "AGENTHUB_PROVIDER_VOLC_DEEPSEEK_API_BASE",
            "AGENTHUB_PROVIDER_VOLC_DEEPSEEK_FLASH_MODEL",
            "AGENTHUB_PROVIDER_VOLC_DEEPSEEK_API_KEY",
        ),
        "volc_deepseek_pro": (
            "AGENTHUB_PROVIDER_VOLC_DEEPSEEK_API_BASE",
            "AGENTHUB_PROVIDER_VOLC_DEEPSEEK_PRO_MODEL",
            "AGENTHUB_PROVIDER_VOLC_DEEPSEEK_API_KEY",
        ),
        "deepseek_official": (
            "AGENTHUB_PROVIDER_DEEPSEEK_API_BASE",
            "AGENTHUB_PROVIDER_DEEPSEEK_MODEL",
            "AGENTHUB_PROVIDER_DEEPSEEK_API_KEY",
        ),
    }
    api_base_values = {
        "qwen_turbo": "https://qwen.example.test/v1",
        "volc_deepseek_flash": "https://volc.example.test/api/v3",
        "volc_deepseek_pro": "https://volc.example.test/api/v3",
        "deepseek_official": "https://deepseek.example.test",
    }
    model_values = {provider_key: f"{provider_key}-model" for provider_key in provider_envs}
    for provider_key, (api_base_env, model_env, credential_env) in provider_envs.items():
        monkeypatch.setenv(api_base_env, api_base_values[provider_key])
        monkeypatch.setenv(model_env, model_values[provider_key])
        monkeypatch.delenv(credential_env, raising=False)

    configs = custom_openai_provider_configs_from_environment()

    assert set(configs) == set(CUSTOM_OPENAI_PROVIDER_KEYS)
    for provider_key, config in configs.items():
        api_base_env, model_env, credential_env = provider_envs[provider_key]
        assert config.provider == provider_key
        assert config.adapter_kind == "custom_openai"
        assert config.backend_type == "model_agent_backend"
        assert config.api_base == api_base_values[provider_key]
        assert config.model == model_values[provider_key]
        assert config.credential_source == credential_env
        assert config.workspace_mode == "readonly_chat"
        assert config.allowed_tools == []
        assert api_base_env
        assert model_env


def test_provider_config_validates_codex_and_claude_code_cli():
    codex = validate_provider_config(
        _config(
            provider="codex",
            adapter_kind="codex_cli",
            backend_type="coding_agent_backend",
            api_base=None,
            model=None,
            credential_source=None,
            executable_path="codex",
            workspace_mode="read_only",
        )
    )
    claude = validate_provider_config(
        _config(
            provider="anthropic",
            adapter_kind="claude_code_cli",
            backend_type="coding_agent_backend",
            api_base=None,
            model=None,
            credential_source=None,
            executable_path="claude",
            workspace_mode="read_only",
        )
    )

    assert codex.adapter_kind == "codex_cli"
    assert claude.adapter_kind == "claude_code_cli"


def test_provider_config_rejects_unsupported_backend_type_and_adapter_kind():
    with pytest.raises(ValidationError):
        validate_provider_config(_config(backend_type="local_mock_backend"))

    with pytest.raises(ValidationError):
        validate_provider_config(_config(adapter_kind="lark_cli"))


def test_provider_config_rejects_adapter_backend_mismatch():
    with pytest.raises(ValidationError) as exc_info:
        validate_provider_config(_config(adapter_kind="custom_openai", backend_type="coding_agent_backend"))

    assert exc_info.value.code == "provider_config_adapter_backend_mismatch"


def test_provider_config_does_not_allow_raw_secret_values():
    with pytest.raises(ValidationError) as exc_info:
        validate_provider_config(_config(credential_source="sk-proj-secret"))

    assert exc_info.value.code == "provider_config_invalid_credential_source"

    with pytest.raises(ValidationError) as dict_exc:
        validate_provider_config(_config(credential_source={"type": "credential_ref", "ref": "openai", "value": "sk-x"}))

    assert dict_exc.value.code == "provider_config_secret_value_forbidden"


def test_agent_run_request_does_not_carry_provider_specific_fields():
    request = validate_agent_run_request(
        {
            "run_id": "run_contract",
            "conversation_id": "conv_contract",
            "source_type": "message",
            "source_message_id": "msg_contract",
            "plan_step_id": None,
            "target_agent_id": "qwen_turbo_agent",
            "run_mode": "direct_response",
            "instruction": "hello",
            "context_bundle": {},
            "workspace_ref": None,
            "allowed_tools": [],
            "expected_artifacts": [],
            "provider": "qwen_turbo",
            "api_base": "https://provider.example.test/v1",
            "model": "provider-model",
            "credential_source": "AGENTHUB_PROVIDER_QWEN_API_KEY",
        }
    )

    request_fields = set(request.__dict__)
    assert "provider" not in request_fields
    assert "api_base" not in request_fields
    assert "model" not in request_fields
    assert "credential_source" not in request_fields
