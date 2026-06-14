"""Shared prompt-context building for all adapters.

Every adapter (codex_cli, claude_code_cli, custom_openai) uses the same
logic to turn a ``context_bundle`` dict into prompt parts.  This module
is the single source of truth for that logic.
"""

from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

AGENT_OUTPUT_FORMAT_INSTRUCTIONS = """AgentHub output format:
- Put user-visible, complete content inside <final>...</final>.
- Put optional private drafts or reasoning inside <thinking>...</thinking>.
- Keep <final> free of hidden reasoning, rejected drafts, and self-corrections."""

AGENT_SYSTEM_IDENTITY = (
    "You are an AI assistant on the AgentHub collaboration platform. "
    "Answer the user's questions helpfully and directly. "
    "Respond in Chinese by default unless the user explicitly uses another language."
)


def build_context_parts(context_bundle: dict[str, Any]) -> list[str]:
    """Return ordered text parts extracted from *context_bundle*.

    The returned list is guaranteed to contain only non-empty strings.
    """
    parts: list[str] = []

    # -- pinned context ---------------------------------------------------
    pinned_context = context_bundle.get("pinned_context")
    if isinstance(pinned_context, list) and pinned_context:
        pin_texts: list[str] = []
        for pin in pinned_context:
            if not isinstance(pin, dict):
                continue
            resolved = pin.get("resolved")
            if isinstance(resolved, dict) and resolved.get("text"):
                pin_texts.append(f"- {resolved['text']}")
        if pin_texts:
            parts.append("[Pinned context - user marked as important]\n" + "\n".join(pin_texts))

    # -- artifact refs ----------------------------------------------------
    artifact_refs = context_bundle.get("artifact_refs")
    if isinstance(artifact_refs, list) and artifact_refs:
        ref_texts: list[str] = []
        for ref in artifact_refs:
            if not isinstance(ref, dict):
                continue
            ref_texts.append(
                f"- {ref.get('title', 'artifact')} "
                f"(type={ref.get('type', '-')}, id={ref.get('artifact_id', '-')})"
            )
        if ref_texts:
            parts.append("[Related artifacts]\n" + "\n".join(ref_texts))

    # -- recent messages --------------------------------------------------
    recent_messages = context_bundle.get("recent_messages")
    if isinstance(recent_messages, list) and recent_messages:
        msg_lines: list[str] = []
        for msg in recent_messages[-4:]:
            if not isinstance(msg, dict):
                continue
            role = msg.get("sender_type", "unknown")
            text = msg.get("text", "")
            if text:
                msg_lines.append(f"[{role}]: {text}")
        if msg_lines:
            parts.append("[Recent conversation]\n" + "\n".join(msg_lines))

    return parts


def enrich_cli_prompt(instruction: str, context_bundle: dict[str, Any]) -> str:
    """Build a single enriched prompt string for CLI adapters.

    Always includes AgentHub output-format constraints.
    """
    parts = build_context_parts(context_bundle)
    blocks = [f"[AgentHub output format]\n{AGENT_OUTPUT_FORMAT_INSTRUCTIONS}"]
    if parts:
        blocks.append("\n\n".join(parts))
    blocks.append(f"[User instruction]\n{instruction}")
    return "\n\n".join(blocks)


def apply_output_format_instruction(instruction: str) -> str:
    """Append AgentHub output-format constraints without adding conversation context."""
    return f"[AgentHub output format]\n{AGENT_OUTPUT_FORMAT_INSTRUCTIONS}\n\n[User instruction]\n{instruction}"


def build_openai_messages(
    instruction: str,
    context_bundle: dict[str, Any],
) -> list[dict[str, str]]:
    """Build an OpenAI-compatible messages list for *custom_openai*.

    Always returns at least a system message and a user message.
    """
    parts = build_context_parts(context_bundle)
    messages: list[dict[str, str]] = []
    if parts:
        system_body = (
            AGENT_SYSTEM_IDENTITY
            + "\n\nUse the context below to inform your response.\n\n"
            + AGENT_OUTPUT_FORMAT_INSTRUCTIONS
            + "\n\n"
            + "\n\n".join(parts)
        )
    else:
        system_body = (
            AGENT_SYSTEM_IDENTITY
            + "\n\n"
            + AGENT_OUTPUT_FORMAT_INSTRUCTIONS
        )
    messages.append({"role": "system", "content": system_body})
    messages.append({"role": "user", "content": instruction})
    return messages


def context_summary_for_log(context_bundle: dict[str, Any]) -> dict[str, Any]:
    """Return a safe summary dict suitable for logging.

    Never includes full message text or raw JSON dumps.
    """
    pinned = context_bundle.get("pinned_context")
    recent = context_bundle.get("recent_messages")
    artifacts = context_bundle.get("artifact_refs")
    return {
        "pinned_count": len(pinned) if isinstance(pinned, list) else 0,
        "recent_message_count": len(recent) if isinstance(recent, list) else 0,
        "artifact_ref_count": len(artifacts) if isinstance(artifacts, list) else 0,
        "truncated": bool(
            isinstance(context_bundle.get("context_summary"), dict)
            and context_bundle["context_summary"].get("truncated", False)
        ),
    }
