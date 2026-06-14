from __future__ import annotations

from dataclasses import dataclass

from services.api.app.shared.settings import get_settings


PIN_SOURCE_TYPES = {"message", "artifact", "artifact_version", "text_note"}

RECENT_MESSAGES_LIMIT_ENV = "AGENTHUB_CONTEXT_RECENT_MESSAGES"
MAX_MESSAGE_CHARS_ENV = "AGENTHUB_CONTEXT_MAX_MESSAGE_CHARS"
MAX_TOTAL_CHARS_ENV = "AGENTHUB_CONTEXT_MAX_TOTAL_CHARS"


@dataclass(frozen=True)
class ContextConstraints:
    max_recent_messages: int
    max_message_chars: int
    max_total_chars: int

    def to_response(self) -> dict[str, int]:
        return {
            "max_recent_messages": self.max_recent_messages,
            "max_message_chars": self.max_message_chars,
            "max_total_chars": self.max_total_chars,
        }


def context_constraints() -> ContextConstraints:
    settings = get_settings()
    return ContextConstraints(
        max_recent_messages=settings.context_recent_messages,
        max_message_chars=settings.context_max_message_chars,
        max_total_chars=settings.context_max_total_chars,
    )


def context_summary(bundle: dict[str, object]) -> dict[str, object]:
    recent_messages = bundle.get("recent_messages") if isinstance(bundle.get("recent_messages"), list) else []
    pinned_context = bundle.get("pinned_context") if isinstance(bundle.get("pinned_context"), list) else []
    artifact_refs = bundle.get("artifact_refs") if isinstance(bundle.get("artifact_refs"), list) else []
    truncated = any(_item_truncated(item) for item in [*recent_messages, *pinned_context])
    return {
        "recent_message_count": len(recent_messages),
        "pinned_count": len(pinned_context),
        "artifact_ref_count": len(artifact_refs),
        "truncated": truncated,
    }


def context_ref(bundle: dict[str, object]) -> dict[str, object]:
    return {
        "conversation_id": bundle.get("conversation_id"),
        "context_summary": dict(bundle.get("context_summary") or {}),
    }


def _item_truncated(item: object) -> bool:
    if not isinstance(item, dict):
        return False
    if item.get("truncated") is True:
        return True
    resolved = item.get("resolved")
    return isinstance(resolved, dict) and resolved.get("truncated") is True

