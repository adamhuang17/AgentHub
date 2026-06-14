from __future__ import annotations

import json
from typing import Any

from services.api.app.agent_runs.schema import AgentRunEventDraft


_AUTH_MARKERS = ("401", "unauthorized", "missing bearer", "invalid api key", "authentication")


def parse_codex_jsonl_line(line: str) -> AgentRunEventDraft:
    try:
        payload = json.loads(line)
    except json.JSONDecodeError as exc:
        return AgentRunEventDraft(
            type="raw_backend_event",
            payload={
                "raw_line": line,
                "error_code": "adapter_invalid_json",
                "message": f"Codex JSONL line is not valid JSON: {exc.msg}",
            },
        )

    if not isinstance(payload, dict):
        return _raw(payload)

    codex_type = str(payload.get("type") or "")
    if codex_type == "thread.started":
        return AgentRunEventDraft(
            type="backend_session_started",
            payload={
                "backend": "codex_cli",
                "thread_id": payload.get("thread_id"),
                "raw_event": payload,
            },
        )

    if codex_type == "turn.started":
        return _raw(payload)

    if codex_type == "error":
        text = _event_text(payload)
        if _is_auth_error(text):
            return AgentRunEventDraft(
                type="adapter_error",
                payload={
                    "error_code": "backend_auth_failed",
                    "message": text or "Codex CLI authentication failed.",
                    "provider": "codex",
                    "recovery_hint": "Run codex login or configure Codex credentials before starting AgentHub runs.",
                    "raw_event": payload,
                },
            )
        return AgentRunEventDraft(
            type="backend_retry",
            payload={
                "backend": "codex_cli",
                "message": text or "Codex CLI reported an error event.",
                "raw_event": payload,
            },
        )

    if codex_type == "turn.failed":
        text = _event_text(payload)
        error_code = "backend_auth_failed" if _is_auth_error(text) else "adapter_process_failed"
        return AgentRunEventDraft(
            type="run_failed",
            payload={
                "error_code": error_code,
                "message": text or "Codex CLI turn failed before producing final assistant output.",
                "provider": "codex",
                "recovery_hint": "Inspect Codex CLI authentication and network availability.",
                "raw_event": payload,
            },
        )

    final_text = _assistant_final_text(payload)
    if final_text:
        return AgentRunEventDraft(
            type="assistant_message_completed",
            payload={
                "message_role": "assistant",
                "content_text": final_text,
                "backend": "codex_cli",
                "raw_event": payload,
            },
        )

    return _raw(payload)


def parse_codex_jsonl_lines(lines: list[str]) -> list[AgentRunEventDraft]:
    return [parse_codex_jsonl_line(line) for line in lines]


def codex_event_has_auth_failure(event: AgentRunEventDraft) -> bool:
    return str(event.payload.get("error_code") or "") in {"backend_auth_failed", "adapter_auth_missing"}


def codex_text_has_auth_failure(text: str) -> bool:
    return _is_auth_error(text)


def _raw(payload: Any) -> AgentRunEventDraft:
    return AgentRunEventDraft(
        type="raw_backend_event",
        payload={"backend": "codex_cli", "raw_event": payload},
    )


def _event_text(payload: dict[str, Any]) -> str:
    message = payload.get("message")
    if isinstance(message, str):
        return message
    error = payload.get("error")
    if isinstance(error, dict):
        for field in ("message", "error", "details"):
            value = error.get(field)
            if isinstance(value, str):
                return value
    if isinstance(error, str):
        return error
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _is_auth_error(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in _AUTH_MARKERS)


def _assistant_final_text(payload: dict[str, Any]) -> str | None:
    codex_type = str(payload.get("type") or "")
    if codex_type in {"assistant_message.completed", "assistant.completed", "message.completed"}:
        return _content_text(payload)

    if codex_type == "item.completed":
        item = payload.get("item")
        if isinstance(item, dict) and item.get("role") == "assistant":
            return _content_text(item)
        if isinstance(item, dict) and item.get("type") == "agent_message":
            return _content_text(item)

    if codex_type in {"turn.completed", "response.completed"}:
        return _content_text(payload)

    return None


def _content_text(payload: dict[str, Any]) -> str | None:
    for field in ("content_text", "text", "output_text", "final_output", "assistant_message", "output"):
        value = payload.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()

    content = payload.get("content")
    if isinstance(content, str) and content.strip():
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str) and item.strip():
                parts.append(item.strip())
            if isinstance(item, dict):
                value = item.get("text") or item.get("content") or item.get("output_text")
                if isinstance(value, str) and value.strip():
                    parts.append(value.strip())
        if parts:
            return "".join(parts)

    message = payload.get("message")
    if isinstance(message, dict):
        return _content_text(message)
    return None
