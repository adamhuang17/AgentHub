from __future__ import annotations

import json

from services.api.app.orchestration.planner_trace import record_planner_trace
from services.api.app.orchestration.turn_backends.base import TurnRequest, TurnRouterBackendError
from services.api.app.orchestration.turn_schema import (
    TurnDecision,
    normalize_turn_decision_defaults,
    validate_turn_decision,
)
from services.api.app.shared.settings import get_settings


class TestTurnRouterBackend:
    __test__ = False

    def __init__(self, raw_decision: dict[str, object] | None) -> None:
        settings = get_settings()
        if (
            settings.agenthub_env != "test"
            or not settings.enable_test_turn_router_backend
            or settings.turn_router_backend != "test"
        ):
            raise TurnRouterBackendError(
                "turn_router_not_configured",
                "Test turn router backend is disabled.",
                recovery_hint="Set AGENTHUB_ENV=test and enable the test turn router backend only in tests.",
            )
        self.raw_decision = raw_decision

    def decide(self, request: TurnRequest) -> TurnDecision:
        if self.raw_decision is None:
            record_planner_trace(
                conversation_id=_request_field(request, "conversation_id"),
                message_id=_request_field(request, "message_id"),
                backend="test",
                model=None,
                decision_type=None,
                raw_output=None,
                error_code="turn_router_not_configured",
                test_run_id=_request_test_run_id(request),
            )
            raise TurnRouterBackendError(
                "turn_router_not_configured",
                "Test turn decision was not provided.",
                recovery_hint="Provide turn_decision in the test request body.",
            )
        raw_output = json.dumps(self.raw_decision, ensure_ascii=False, separators=(",", ":"))
        normalized = normalize_turn_decision_defaults(
            self.raw_decision,
            conversation_mode=request.conversation_mode,
            private_agent_id=request.private_agent_id,
            mentioned_agent_ids=_mentioned_agent_ids(request),
        )
        decision = validate_turn_decision(normalized)
        record_planner_trace(
            conversation_id=_request_field(request, "conversation_id"),
            message_id=_request_field(request, "message_id"),
            backend="test",
            model=None,
            decision_type=decision.decision_type,
            raw_output=raw_output,
            error_code=None,
            test_run_id=_request_test_run_id(request),
        )
        return decision


def _request_field(request: TurnRequest | None, field: str) -> str:
    value = getattr(request, field, None)
    return value if isinstance(value, str) and value else "unknown"


def _request_test_run_id(request: TurnRequest | None) -> str | None:
    value = getattr(request, "test_run_id", None)
    return value if isinstance(value, str) and value else None


def _mentioned_agent_ids(request: TurnRequest | None) -> list[str]:
    if request is None:
        return []
    agent_ids: list[str] = []
    for mention in request.mentions:
        if isinstance(mention, dict) and isinstance(mention.get("agent_id"), str) and mention["agent_id"].strip():
            agent_ids.append(mention["agent_id"].strip())
    return agent_ids
