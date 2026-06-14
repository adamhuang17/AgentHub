from __future__ import annotations

from services.api.app.orchestration.planner_trace import record_planner_trace
from services.api.app.orchestration.turn_backends.base import TurnRequest, TurnRouterBackendError


class DisabledTurnRouterBackend:
    def decide(self, request: TurnRequest):
        record_planner_trace(
            conversation_id=request.conversation_id,
            message_id=request.message_id,
            backend="disabled",
            model=None,
            decision_type=None,
            raw_output=None,
            error_code="turn_router_not_configured",
            test_run_id=request.test_run_id,
        )
        raise TurnRouterBackendError(
            "turn_router_not_configured",
            "Turn router backend is not configured.",
            recovery_hint="Configure a real turn router backend or enable the test backend only in tests.",
        )
