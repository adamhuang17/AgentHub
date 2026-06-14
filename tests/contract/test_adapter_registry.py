from services.api.app.agents.adapter_registry import AdapterRegistry
from services.api.app.agents.adapters.disabled import DisabledAdapter


def _agent(**overrides):
    payload = {
        "id": "agent-contract",
        "provider": "codex",
        "enabled": True,
        "configured": False,
        "execution_enabled": False,
        "health_status": "profile_only",
    }
    payload.update(overrides)
    return payload


_A7_PROVIDER_ENVS = {
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


_A7_PROVIDER_ALIAS_ENVS = {
    "qwen_turbo": (
        "AGENTHUB_PROVIDER_QWEN_API_BASE",
        "AGENTHUB_QWEN_TURBO_API_BASE",
        "AGENTHUB_QWEN_API_BASE",
        "AGENTHUB_CUSTOM_OPENAI_API_BASE",
        "AGENTHUB_PROVIDER_QWEN_MODEL",
        "AGENTHUB_QWEN_TURBO_MODEL",
        "AGENTHUB_QWEN_MODEL",
        "AGENTHUB_CUSTOM_OPENAI_MODEL",
        "AGENTHUB_PROVIDER_QWEN_API_KEY",
        "AGENTHUB_QWEN_TURBO_API_KEY",
        "AGENTHUB_QWEN_API_KEY",
        "AGENTHUB_CUSTOM_OPENAI_API_KEY",
    ),
    "volc_deepseek_flash": (
        "AGENTHUB_PROVIDER_VOLC_DEEPSEEK_API_BASE",
        "AGENTHUB_VOLC_DEEPSEEK_FLASH_API_BASE",
        "AGENTHUB_CUSTOM_OPENAI_API_BASE",
        "AGENTHUB_PROVIDER_VOLC_DEEPSEEK_FLASH_MODEL",
        "AGENTHUB_VOLC_DEEPSEEK_FLASH_MODEL",
        "AGENTHUB_CUSTOM_OPENAI_MODEL",
        "AGENTHUB_PROVIDER_VOLC_DEEPSEEK_API_KEY",
        "AGENTHUB_VOLC_DEEPSEEK_FLASH_API_KEY",
        "AGENTHUB_CUSTOM_OPENAI_API_KEY",
    ),
    "volc_deepseek_pro": (
        "AGENTHUB_PROVIDER_VOLC_DEEPSEEK_API_BASE",
        "AGENTHUB_VOLC_DEEPSEEK_PRO_API_BASE",
        "AGENTHUB_CUSTOM_OPENAI_API_BASE",
        "AGENTHUB_PROVIDER_VOLC_DEEPSEEK_PRO_MODEL",
        "AGENTHUB_VOLC_DEEPSEEK_PRO_MODEL",
        "AGENTHUB_CUSTOM_OPENAI_MODEL",
        "AGENTHUB_PROVIDER_VOLC_DEEPSEEK_API_KEY",
        "AGENTHUB_VOLC_DEEPSEEK_PRO_API_KEY",
        "AGENTHUB_CUSTOM_OPENAI_API_KEY",
    ),
    "deepseek_official": (
        "AGENTHUB_PROVIDER_DEEPSEEK_API_BASE",
        "AGENTHUB_DEEPSEEK_API_BASE",
        "DEEPSEEK_API_BASE",
        "AGENTHUB_CUSTOM_OPENAI_API_BASE",
        "AGENTHUB_PROVIDER_DEEPSEEK_MODEL",
        "AGENTHUB_DEEPSEEK_MODEL",
        "DEEPSEEK_MODEL",
        "AGENTHUB_CUSTOM_OPENAI_MODEL",
        "AGENTHUB_PROVIDER_DEEPSEEK_API_KEY",
        "AGENTHUB_DEEPSEEK_API_KEY",
        "DEEPSEEK_API_KEY",
        "AGENTHUB_CUSTOM_OPENAI_API_KEY",
    ),
}


def _clear_provider_aliases(monkeypatch, provider: str) -> None:
    for env_name in _A7_PROVIDER_ALIAS_ENVS[provider]:
        monkeypatch.setenv(env_name, "")


def test_adapter_registry_returns_disabled_adapter_for_unconfigured_agent():
    registry = AdapterRegistry()
    adapter = registry.adapter_for_agent(_agent(configured=False))
    health = adapter.health()
    registry_health = registry.health_for_agent(_agent(configured=False))

    assert isinstance(adapter, DisabledAdapter)
    assert health.configured is False
    assert health.status == "not_configured"
    assert health.provider == "codex"
    assert registry_health.configured is False
    assert registry_health.status == "not_configured"
    assert registry_health.error_code == "provider_not_configured"


def test_adapter_registry_does_not_fallback_to_default_success_adapter():
    registry = AdapterRegistry()
    adapter = registry.adapter_for_agent(_agent(configured=True, provider="missing-provider"))
    health = registry.health_for_agent(_agent(configured=True, provider="missing-provider"))

    assert isinstance(adapter, DisabledAdapter)
    assert adapter.health().configured is False
    assert health.configured is False
    assert health.status == "unsupported_provider"
    assert health.error_code == "unsupported_provider"


def test_adapter_registry_returns_disabled_adapter_when_provider_missing():
    registry = AdapterRegistry()
    adapter = registry.adapter_for_agent(_agent(provider=""))
    health = registry.health_for_agent(_agent(provider=""))

    assert isinstance(adapter, DisabledAdapter)
    assert adapter.health().provider is None
    assert health.status == "not_configured"
    assert health.error_code == "provider_not_configured"


def test_adapter_registry_reports_missing_credentials_for_executable_unconfigured_profile():
    health = AdapterRegistry().health_for_agent(
        _agent(configured=False, execution_enabled=True, health_status="missing_credentials")
    )

    assert health.configured is False
    assert health.status == "missing_credentials"
    assert health.error_code == "credential_missing"
    assert health.recovery_hint


def test_adapter_registry_reports_unavailable_when_real_cli_executable_is_missing():
    health = AdapterRegistry().health_for_agent(
        _agent(
            configured=True,
            execution_enabled=True,
            health_status="configured",
            executable_path="Z:/definitely/missing/codex.exe",
        )
    )

    assert health.configured is False
    assert health.status == "unavailable"
    assert health.error_code == "adapter_executable_not_found"


def test_adapter_registry_supports_a7_multi_provider_custom_openai_missing_credentials(monkeypatch):
    registry = AdapterRegistry()

    for provider, (api_base_env, model_env, credential_env) in _A7_PROVIDER_ENVS.items():
        _clear_provider_aliases(monkeypatch, provider)
        monkeypatch.setenv(api_base_env, f"https://{provider}.example.test/v1")
        monkeypatch.setenv(model_env, f"{provider}-model")
        monkeypatch.setenv(credential_env, "")

        health = registry.health_for_agent(
            _agent(
                provider=provider,
                configured=True,
                execution_enabled=True,
                health_status="configured",
            )
        )

        assert health.provider == provider
        assert health.adapter_kind == "custom_openai"
        assert health.configured is False
        assert health.status == "missing_credentials"
        assert health.error_code == "missing_credentials"
        assert health.capabilities == []


def test_adapter_registry_does_not_share_readiness_between_custom_openai_providers(monkeypatch):
    _clear_provider_aliases(monkeypatch, "qwen_turbo")
    _clear_provider_aliases(monkeypatch, "deepseek_official")
    qwen_api_base, qwen_model, qwen_key = _A7_PROVIDER_ENVS["qwen_turbo"]
    deepseek_api_base, deepseek_model, deepseek_key = _A7_PROVIDER_ENVS["deepseek_official"]
    monkeypatch.setenv(qwen_api_base, "https://qwen.example.test/v1")
    monkeypatch.setenv(qwen_model, "qwen-model")
    monkeypatch.setenv(qwen_key, "")
    monkeypatch.setenv(deepseek_api_base, "")
    monkeypatch.setenv(deepseek_model, "")
    monkeypatch.setenv(deepseek_key, "")

    registry = AdapterRegistry()
    qwen_health = registry.health_for_agent(
        _agent(provider="qwen_turbo", configured=True, execution_enabled=True, health_status="configured")
    )
    deepseek_health = registry.health_for_agent(
        _agent(provider="deepseek_official", configured=True, execution_enabled=True, health_status="configured")
    )

    assert qwen_health.status == "missing_credentials"
    assert deepseek_health.status == "not_configured"
    assert deepseek_health.error_code == "provider_not_configured"


def test_adapter_registry_summary_contains_no_ready_adapter_in_current_phase():
    summary = AdapterRegistry().adapter_readiness_summary()

    assert summary
    assert all(health.status != "ready" for health in summary)
    assert all(health.configured is False for health in summary)
