from __future__ import annotations

import json
from typing import Any

from services.api.app.agent_runs.schema import AgentRunEventDraft


def parse_claude_stream_json_line(line: str) -> AgentRunEventDraft:
    try:
        payload = json.loads(line)
    except json.JSONDecodeError as exc:
        return AgentRunEventDraft(
            type="raw_backend_event",
            payload={
                "raw_line": line,
                "error_code": "adapter_invalid_json",
                "message": f"Claude stream-json line is not valid JSON: {exc.msg}",
            },
        )

    if not isinstance(payload, dict):
        return _raw(payload)

    event_type = str(payload.get("type") or "")
    subtype = str(payload.get("subtype") or "")

    if event_type == "system" and subtype == "init":
        return AgentRunEventDraft(
            type="backend_session_started",
            payload={
                "backend": "claude_code_cli",
                "cwd": payload.get("cwd"),
                "session_id": payload.get("session_id"),
                "model": payload.get("model"),
                "tools": payload.get("tools") if isinstance(payload.get("tools"), list) else [],
                "mcp_servers": payload.get("mcp_servers") if isinstance(payload.get("mcp_servers"), list) else [],
                "apiKeySource": payload.get("apiKeySource"),
                "claude_code_version": payload.get("claude_code_version"),
                "raw_event": payload,
            },
        )

    if event_type == "system" and subtype == "api_retry":
        return AgentRunEventDraft(
            type="backend_retry",
            payload={
                "backend": "claude_code_cli",
                "message": _event_text(payload) or "Claude Code API retry.",
                "raw_event": payload,
            },
        )

    if event_type == "assistant":
        text = _assistant_delta_text(payload)
        if text:
            return AgentRunEventDraft(
                type="assistant_message_delta",
                payload={
                    "message_role": "assistant",
                    "content_text": text,
                    "backend": "claude_code_cli",
                    "raw_event": payload,
                },
            )
        return _raw(payload)

    if event_type in {"content_block_delta", "message_delta"}:
        text = _assistant_delta_text(payload)
        if text:
            return AgentRunEventDraft(
                type="assistant_message_delta",
                payload={
                    "message_role": "assistant",
                    "content_text": text,
                    "backend": "claude_code_cli",
                    "raw_event": payload,
                },
            )
        return _raw(payload)

    if event_type == "result":
        if subtype and subtype not in {"success", "done"}:
            return AgentRunEventDraft(
                type="run_failed",
                payload={
                    "error_code": "adapter_process_failed",
                    "message": _event_text(payload) or "Claude Code result was not successful.",
                    "provider": "anthropic",
                    "recovery_hint": "Inspect Claude Code authentication, network status, and CLI output.",
                    "raw_event": payload,
                },
            )
        final_text = _result_text(payload)
        if final_text:
            return AgentRunEventDraft(
                type="assistant_message_completed",
                payload={
                    "message_role": "assistant",
                    "content_text": final_text,
                    "backend": "claude_code_cli",
                    "raw_event": payload,
                },
            )
        return _raw(payload)

    return _raw(payload)


def parse_claude_stream_json_lines(lines: list[str]) -> list[AgentRunEventDraft]:
    return [parse_claude_stream_json_line(line) for line in lines]


def _raw(payload: Any) -> AgentRunEventDraft:
    return AgentRunEventDraft(
        type="raw_backend_event",
        payload={"backend": "claude_code_cli", "raw_event": payload},
    )


def _event_text(payload: dict[str, Any]) -> str:
    for field in ("message", "error", "details", "result"):
        value = payload.get(field)
        if isinstance(value, str):
            return value
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _assistant_delta_text(payload: dict[str, Any]) -> str | None:
    message = payload.get("message")
    if isinstance(message, dict):
        text = _content_text(message.get("content"))
        if text:
            return text

    delta = payload.get("delta")
    if isinstance(delta, dict):
        for field in ("text", "content"):
            value = delta.get(field)
            if isinstance(value, str) and value:
                return value
        text = _content_text(delta.get("content"))
        if text:
            return text

    return _content_text(payload.get("content"))


def _result_text(payload: dict[str, Any]) -> str | None:
    for field in ("result", "content_text", "text", "output"):
        value = payload.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return _content_text(payload.get("content"))


def _content_text(content: object) -> str | None:
    if isinstance(content, str) and content.strip():
        return content.strip()
    if not isinstance(content, list):
        return None
    parts: list[str] = []
    for item in content:
        if isinstance(item, str) and item.strip():
            parts.append(item)
            continue
        if isinstance(item, dict):
            value = item.get("text") or item.get("content")
            if isinstance(value, str) and value:
                parts.append(value)
    return "".join(parts) if parts else None
