from __future__ import annotations

from typing import Protocol

from services.api.app.agent_runs.schema import AgentRunEventDraft, AgentRunRequest
from services.api.app.agents.adapter_health import AdapterHealth


class BaseAdapter(Protocol):
    adapter_id: str

    def health(self) -> AdapterHealth:
        ...

    def invoke(self, request: AgentRunRequest) -> list[AgentRunEventDraft]:
        ...

    def cancel(self, run_id: str) -> dict[str, object]:
        ...
