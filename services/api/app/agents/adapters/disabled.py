from __future__ import annotations

from services.api.app.agent_runs.events import provider_not_configured_payload
from services.api.app.agent_runs.schema import AgentRunEventDraft, AgentRunRequest
from services.api.app.agents.adapter_health import AdapterHealth, adapter_health


class DisabledAdapter:
    adapter_id = "disabled"

    def __init__(self, *, provider: str | None, target_agent_id: str | None = None) -> None:
        self.provider = provider
        self.target_agent_id = target_agent_id

    def health(self) -> AdapterHealth:
        return adapter_health(
            provider=self.provider,
            adapter_kind=self.adapter_id,
            configured=False,
            status="not_configured",
            error_code="provider_not_configured",
            recovery_hint="Configure provider credentials and a real adapter before starting runs.",
            capabilities=[],
            message="Agent adapter is not configured for provider execution.",
        )

    def invoke(self, request: AgentRunRequest) -> list[AgentRunEventDraft]:
        return [
            AgentRunEventDraft(
                type="provider_not_configured",
                payload=provider_not_configured_payload(
                    target_agent_id=request.target_agent_id,
                    provider=self.provider,
                ),
            )
        ]

    def cancel(self, run_id: str) -> dict[str, object]:
        return {
            "run_id": run_id,
            "cancel_requested": False,
            "error_code": "provider_not_configured",
            "message": "DisabledAdapter has no running provider work to cancel.",
        }
