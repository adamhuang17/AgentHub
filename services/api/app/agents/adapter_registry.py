from __future__ import annotations

from services.api.app.agents.adapter_health import AdapterHealth, adapter_health
from services.api.app.agents.adapters.base import BaseAdapter
from services.api.app.agents.adapters.claude_code_cli import ClaudeCodeCliAdapter
from services.api.app.agents.adapters.codex_cli import CodexCliAdapter
from services.api.app.agents.adapters.custom_openai import CustomOpenAIAdapter
from services.api.app.agents.adapters.disabled import DisabledAdapter
from services.api.app.agents.adapters.opencode_http import OpenCodeHttpAdapter
from services.api.app.agents.provider_config import provider_config_from_agent


SUPPORTED_ADAPTERS: dict[str, dict[str, object]] = {
    "custom_openai": {"adapter_kind": "custom_openai", "capabilities": ["direct_response", "chat", "model"]},
    "openai": {"adapter_kind": "custom_openai", "capabilities": ["direct_response", "chat", "model"]},
    "deepseek": {"adapter_kind": "custom_openai", "capabilities": ["direct_response", "chat", "model"]},
    "深度求索": {"adapter_kind": "custom_openai", "capabilities": ["direct_response", "chat", "model"]},
    "zhipu": {"adapter_kind": "custom_openai", "capabilities": ["direct_response", "chat", "model"]},
    "智谱": {"adapter_kind": "custom_openai", "capabilities": ["direct_response", "chat", "model"]},
    "doubao": {"adapter_kind": "custom_openai", "capabilities": ["direct_response", "chat", "model"]},
    "豆包": {"adapter_kind": "custom_openai", "capabilities": ["direct_response", "chat", "model"]},
    "qwen": {"adapter_kind": "custom_openai", "capabilities": ["direct_response", "chat", "model"]},
    "qwen_turbo": {"adapter_kind": "custom_openai", "capabilities": ["direct_response", "chat", "model"]},
    "阿里千问": {"adapter_kind": "custom_openai", "capabilities": ["direct_response", "chat", "model"]},
    "千问": {"adapter_kind": "custom_openai", "capabilities": ["direct_response", "chat", "model"]},
    "volc_deepseek_flash": {"adapter_kind": "custom_openai", "capabilities": ["direct_response", "chat", "model"]},
    "volc_deepseek_pro": {"adapter_kind": "custom_openai", "capabilities": ["direct_response", "chat", "model"]},
    "deepseek_official": {"adapter_kind": "custom_openai", "capabilities": ["direct_response", "chat", "model"]},
    "openrouter": {"adapter_kind": "custom_openai", "capabilities": ["direct_response", "chat", "model"]},
    "ollama": {"adapter_kind": "custom_openai", "capabilities": ["direct_response", "chat", "model"]},
    "codex": {"adapter_kind": "codex_cli", "capabilities": ["direct_response", "planned_step"]},
    "anthropic": {"adapter_kind": "claude_code_cli", "capabilities": ["direct_response"]},
    "opencode": {"adapter_kind": "opencode_http", "capabilities": ["direct_response", "planned_step", "diff"]},
}

IMPLEMENTED_ADAPTER_KINDS: set[str] = {"custom_openai", "codex_cli", "claude_code_cli", "opencode_http"}


class AdapterRegistry:
    def adapter_for_agent(self, agent_profile: dict[str, object]) -> BaseAdapter:
        provider = _provider_id(agent_profile)
        adapter_kind = _adapter_kind(agent_profile, provider)
        if provider is None and adapter_kind is None:
            return DisabledAdapter(provider=None, target_agent_id=_string_or_none(agent_profile.get("id")))
        if not _supported(provider, adapter_kind):
            return DisabledAdapter(provider=provider, target_agent_id=_string_or_none(agent_profile.get("id")))
        if agent_profile.get("configured") is not True or _profile_only(agent_profile):
            return DisabledAdapter(
                provider=provider,
                target_agent_id=_string_or_none(agent_profile.get("id")),
            )
        config = provider_config_from_agent(agent_profile)
        if config.adapter_kind == "custom_openai":
            return CustomOpenAIAdapter(config=config, target_agent_id=_string_or_none(agent_profile.get("id")))
        if config.adapter_kind == "codex_cli":
            return CodexCliAdapter(config=config, target_agent_id=_string_or_none(agent_profile.get("id")))
        if config.adapter_kind == "claude_code_cli":
            return ClaudeCodeCliAdapter(config=config, target_agent_id=_string_or_none(agent_profile.get("id")))
        if config.adapter_kind == "opencode_http":
            return OpenCodeHttpAdapter(config=config, target_agent_id=_string_or_none(agent_profile.get("id")))
        return DisabledAdapter(
            provider=provider,
            target_agent_id=_string_or_none(agent_profile.get("id")),
        )

    def health_for_agent(self, agent_profile: dict[str, object]) -> AdapterHealth:
        provider = _provider_id(agent_profile)
        adapter_kind = _adapter_kind(agent_profile, provider)

        if provider is None and adapter_kind is None:
            return _not_configured_health(
                provider=None,
                adapter_kind="disabled",
                message="Agent provider is not configured.",
            )

        if not _supported(provider, adapter_kind):
            return adapter_health(
                provider=provider,
                adapter_kind=adapter_kind or "unsupported",
                configured=False,
                status="unsupported_provider",
                error_code="unsupported_provider",
                recovery_hint="Choose a supported provider or register a real adapter before starting runs.",
                capabilities=[],
                message="Agent provider is not supported by the adapter registry.",
            )

        resolved_kind = adapter_kind or _adapter_kind_for_provider(provider) or "disabled"
        if agent_profile.get("configured") is not True:
            if _profile_only(agent_profile):
                return _not_configured_health(
                    provider=provider,
                    adapter_kind=resolved_kind,
                    message="Agent profile is not configured for execution.",
                )
            return adapter_health(
                provider=provider,
                adapter_kind=resolved_kind,
                configured=False,
                status="missing_credentials",
                error_code="credential_missing",
                recovery_hint="Configure provider credentials before starting a real run.",
                capabilities=[],
                message="Agent provider credentials are missing.",
            )

        if resolved_kind not in IMPLEMENTED_ADAPTER_KINDS:
            return adapter_health(
                provider=provider,
                adapter_kind=resolved_kind,
                configured=False,
                status="unavailable",
                error_code="adapter_unavailable",
                recovery_hint="Register a real adapter implementation before starting provider work.",
                capabilities=[],
                message="No real adapter implementation is available in this phase.",
            )

        return self.adapter_for_agent(agent_profile).health()

    def adapter_readiness_summary(self) -> list[AdapterHealth]:
        disabled = DisabledAdapter(provider=None).health()
        registered = [
            adapter_health(
                provider=provider,
                adapter_kind=str(metadata["adapter_kind"]),
                configured=False,
                status="unavailable",
                error_code="adapter_unavailable",
                recovery_hint="Register a real adapter implementation before starting provider work.",
                capabilities=list(metadata.get("capabilities") or []),
                message="Provider adapter slot is registered but no real adapter is enabled in this phase.",
            )
            for provider, metadata in sorted(SUPPORTED_ADAPTERS.items())
        ]
        return [disabled, *registered]


def _not_configured_health(*, provider: str | None, adapter_kind: str, message: str) -> AdapterHealth:
    return adapter_health(
        provider=provider,
        adapter_kind=adapter_kind,
        configured=False,
        status="not_configured",
        error_code="provider_not_configured",
        recovery_hint="Configure provider credentials and a real adapter before starting runs.",
        capabilities=[],
        message=message,
    )


def _provider_id(agent_profile: dict[str, object]) -> str | None:
    value = agent_profile.get("provider")
    return value.strip().lower() if isinstance(value, str) and value.strip() else None


def _adapter_kind(agent_profile: dict[str, object], provider: str | None) -> str | None:
    value = agent_profile.get("adapter_kind")
    if isinstance(value, str) and value.strip():
        return value.strip().lower()
    return _adapter_kind_for_provider(provider)


def _adapter_kind_for_provider(provider: str | None) -> str | None:
    if provider is None:
        return None
    metadata = SUPPORTED_ADAPTERS.get(provider)
    if metadata is None:
        return None
    return str(metadata["adapter_kind"])


def _supported(provider: str | None, adapter_kind: str | None) -> bool:
    if provider in SUPPORTED_ADAPTERS:
        return True
    supported_kinds = {str(metadata["adapter_kind"]) for metadata in SUPPORTED_ADAPTERS.values()}
    return adapter_kind in supported_kinds


def _profile_only(agent_profile: dict[str, object]) -> bool:
    if agent_profile.get("adapter_kind") == "opencode_http" or agent_profile.get("provider") == "opencode":
        return False
    return agent_profile.get("execution_enabled") is not True or agent_profile.get("health_status") == "profile_only"


def _capabilities_for_provider(provider: str | None) -> list[str]:
    if provider is None:
        return []
    metadata = SUPPORTED_ADAPTERS.get(provider)
    if metadata is None:
        return []
    return list(metadata.get("capabilities") or [])


def _string_or_none(value: object) -> str | None:
    return value if isinstance(value, str) else None
