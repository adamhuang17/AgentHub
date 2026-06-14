from __future__ import annotations

from services.api.app.agents.repository import list_agent_profiles
from services.api.app.memory.context_builder import build_context_bundle
from services.api.app.orchestration.turn_prompt import AVAILABLE_ARTIFACT_TYPES
from services.api.app.orchestration.turn_backends.base import TurnRequest, TurnRouterBackend
from services.api.app.orchestration.turn_backends.disabled import DisabledTurnRouterBackend
from services.api.app.orchestration.turn_backends.openai_compatible import OpenAICompatibleTurnRouterBackend
from services.api.app.orchestration.turn_backends.test_backend import TestTurnRouterBackend
from services.api.app.orchestration.turn_schema import TurnDecision
from services.api.app.shared.settings import get_settings


REAL_BACKENDS = {"openai", "openai_compatible", "real"}
RECENT_MESSAGES_LIMIT_ENV = "AGENTHUB_TURN_ROUTER_RECENT_MESSAGES_LIMIT"


class TurnRouterGateway:
    def __init__(self, backend: TurnRouterBackend) -> None:
        self.backend = backend

    def decide_for_message(
        self,
        message: dict[str, object],
        *,
        conversation_mode: str,
        private_agent_id: str | None,
        auto_orchestrate: bool,
        test_run_id: str | None = None,
    ) -> TurnDecision:
        context_bundle = (
            build_context_bundle(str(message["conversation_id"]), test_run_id=test_run_id)
            if test_run_id is not None
            else {"recent_messages": [], "pinned_context": []}
        )
        request = TurnRequest(
            message_id=str(message["id"]),
            conversation_id=str(message["conversation_id"]),
            message_text=_message_text(message),
            sender_type=str(message.get("sender_type") or "user"),
            sender_id=str(message.get("sender_id") or "user"),
            conversation_mode=conversation_mode,
            content=dict(message.get("content") or {}),
            references=_object_list(message.get("references") or []),
            mentions=_object_list(message.get("mentions") or []),
            available_agents=list_agent_profiles(enabled=True),
            available_artifact_types=list(AVAILABLE_ARTIFACT_TYPES),
            private_agent_id=private_agent_id,
            auto_orchestrate=auto_orchestrate,
            pinned_context=_object_list(context_bundle.get("pinned_context") or []),
            recent_messages=_object_list(context_bundle.get("recent_messages") or []),
            test_run_id=test_run_id,
        )
        return self.backend.decide(request)


def gateway_from_environment(raw_test_decision: dict[str, object] | None = None) -> TurnRouterGateway:
    backend_name = get_settings().turn_router_backend
    if backend_name == "test":
        return TurnRouterGateway(TestTurnRouterBackend(raw_test_decision))
    if backend_name in REAL_BACKENDS:
        return TurnRouterGateway(OpenAICompatibleTurnRouterBackend())
    return TurnRouterGateway(DisabledTurnRouterBackend())


def turn_router_backend_configured() -> bool:
    settings = get_settings()
    return settings.turn_router_backend in REAL_BACKENDS and settings.turn_router_configured()


def _object_list(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _message_text(message: dict[str, object]) -> str:
    content = message.get("content")
    if isinstance(content, dict) and isinstance(content.get("text"), str):
        return content["text"]
    return ""
