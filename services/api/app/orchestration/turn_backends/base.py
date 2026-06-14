from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from services.api.app.orchestration.turn_schema import TurnDecision


@dataclass(frozen=True)
class TurnRequest:
    message_id: str
    conversation_id: str
    message_text: str
    sender_type: str
    sender_id: str
    conversation_mode: str
    content: dict[str, object]
    references: list[dict[str, object]]
    mentions: list[dict[str, object]]
    available_agents: list[dict[str, object]]
    available_artifact_types: list[str]
    private_agent_id: str | None
    auto_orchestrate: bool
    pinned_context: list[dict[str, object]]
    recent_messages: list[dict[str, object]]
    test_run_id: str | None = None


class TurnRouterBackendError(Exception):
    def __init__(self, code: str, message: str, *, recovery_hint: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.error_code = code
        self.recovery_hint = recovery_hint


class TurnRouterBackend(Protocol):
    def decide(self, request: TurnRequest) -> TurnDecision:
        ...
