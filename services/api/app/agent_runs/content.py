from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


FINAL_CONTENT_EMPTY = "final_content_empty"
INCOMPLETE = "incomplete"
SUCCEEDED = "succeeded"


@dataclass(frozen=True)
class SplitAgentContent:
    final_content: str
    thinking_content: str
    raw_content: str
    cleanup_method: str
    cleanup_applied: bool


@dataclass(frozen=True)
class ContentValidation:
    status: str
    error_code: str | None
    missing: list[str]
    required: bool


_THINKING_BLOCK_RE = re.compile(r"<thinking\b[^>]*>(.*?)</thinking>", re.IGNORECASE | re.DOTALL)
_FINAL_BLOCK_RE = re.compile(r"<final\b[^>]*>(.*?)</final>", re.IGNORECASE | re.DOTALL)

_DRAFT_MARKERS = (
    "let me think",
    "actually",
    "wait",
    "i should",
    "let me reconsider",
    "candidate",
    "maybe",
    "i want to make sure",
    "hmm",
    "great, so",
)


def split_agent_content(raw_content: str, *, explicit_thinking_content: str | None = None) -> SplitAgentContent:
    raw = raw_content or ""
    explicit_thinking = _clean(explicit_thinking_content or "")
    raw_for_storage = raw
    raw_lower = raw.lower()
    if explicit_thinking and raw.strip() and "<thinking" not in raw_lower and "<final" not in raw_lower:
        raw_for_storage = f"<thinking>\n{explicit_thinking}\n</thinking>\n<final>\n{raw.strip()}\n</final>"
    elif explicit_thinking and raw.strip() and "<thinking" not in raw_lower:
        raw_for_storage = f"<thinking>\n{explicit_thinking}\n</thinking>\n{raw}"
    final_blocks = [_clean(match) for match in _FINAL_BLOCK_RE.findall(raw)]
    thinking_blocks = [_clean(match) for match in _THINKING_BLOCK_RE.findall(raw)]

    if final_blocks or thinking_blocks:
        final_content = _join_blocks(final_blocks)
        if not final_content and final_blocks:
            final_content = ""
        if not final_blocks:
            remainder = _clean(_THINKING_BLOCK_RE.sub("", raw))
            final_content = remainder if remainder != raw.strip() else ""
        thinking_content = _join_blocks([explicit_thinking, *thinking_blocks])
        return SplitAgentContent(
            final_content=final_content,
            thinking_content=thinking_content,
            raw_content=raw_for_storage,
            cleanup_method="explicit_tags",
            cleanup_applied=True,
        )

    blocks = _paragraph_blocks(raw)
    thinking: list[str] = []
    final: list[str] = []
    for block in blocks:
        if _is_draft_block(block):
            thinking.append(block)
        else:
            final.append(block)

    thinking_content = _join_blocks([explicit_thinking, *thinking])
    final_content = _join_blocks(final) if thinking else raw.strip()
    cleanup_applied = bool(thinking or explicit_thinking)
    return SplitAgentContent(
        final_content=final_content,
        thinking_content=thinking_content,
        raw_content=raw_for_storage,
        cleanup_method="heuristic" if thinking else ("provider_thinking" if explicit_thinking else "none"),
        cleanup_applied=cleanup_applied,
    )


def validate_final_content(
    split: SplitAgentContent,
    *,
    request_instruction: str,
    context_bundle: dict[str, object],
    target_agent: dict[str, object],
) -> ContentValidation:
    final = split.final_content.strip()
    if not final:
        return ContentValidation(
            status=FINAL_CONTENT_EMPTY,
            error_code=FINAL_CONTENT_EMPTY,
            missing=["final_content"],
            required=_requires_solution_validation(request_instruction, context_bundle, target_agent, final),
        )

    required = _requires_solution_validation(request_instruction, context_bundle, target_agent, final)
    if not required:
        return ContentValidation(status=SUCCEEDED, error_code=None, missing=[], required=False)

    missing = _missing_solution_requirements(final)
    if missing:
        return ContentValidation(status=INCOMPLETE, error_code=INCOMPLETE, missing=missing, required=True)
    return ContentValidation(status=SUCCEEDED, error_code=None, missing=[], required=True)


def content_payload(
    split: SplitAgentContent,
    validation: ContentValidation,
    *,
    run_id: str,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "text": split.final_content,
        "final_content": split.final_content,
        "thinking_content": split.thinking_content,
        "raw_content": split.raw_content,
        "run_id": run_id,
        "content_state": validation.status,
        "cleanup_method": split.cleanup_method,
        "cleanup_applied": split.cleanup_applied,
        "output_validation": {
            "status": validation.status,
            "required": validation.required,
            "missing": validation.missing,
        },
    }
    if validation.error_code:
        payload["error_code"] = validation.error_code
    return payload


def run_content_error_payload(
    split: SplitAgentContent,
    validation: ContentValidation,
    *,
    run: dict[str, object],
) -> dict[str, object]:
    error_code = validation.error_code or INCOMPLETE
    if error_code == FINAL_CONTENT_EMPTY:
        message = "Agent output did not contain final_content."
        recovery_hint = "Inspect raw_content, then retry with an Agent that emits <final>...</final>."
    else:
        missing = ", ".join(validation.missing) if validation.missing else "required final answer fields"
        message = f"Agent final_content is incomplete: {missing}."
        recovery_hint = "Completeness checks use final_content only; ask the Agent to provide the missing final answer sections."
    return {
        "error_code": error_code,
        "message": message,
        "provider": None,
        "target_agent_id": str(run["target_agent_id"]),
        "recovery_hint": recovery_hint,
        "content_state": validation.status,
        "missing": validation.missing,
    }


def _requires_solution_validation(
    instruction: str,
    context_bundle: dict[str, object],
    target_agent: dict[str, object],
    final_content: str,
) -> bool:
    final_lower = final_content.lower()
    if "## math problem solution" in final_lower or "## leetcode solution" in final_lower:
        return True

    combined = f"{instruction}\n{_context_text(context_bundle)}".lower()
    has_math = "math" in combined or "数学" in combined
    has_leetcode = "leetcode" in combined or "力扣" in combined
    has_solve_intent = any(
        marker in combined
        for marker in (
            "solve",
            "solution",
            "answer",
            "解答",
            "答案",
            "负责解答",
            "负责解决",
        )
    )
    agent_id = str(target_agent.get("id") or "").lower()
    agent_name = str(target_agent.get("name") or "").lower()
    is_answer_agent = agent_id == "agent-demo-model" or "demo model" in agent_name
    return bool(is_answer_agent and has_math and has_leetcode and has_solve_intent)


def _missing_solution_requirements(final_content: str) -> list[str]:
    missing: list[str] = []
    lower = final_content.lower()
    if "## math problem solution" not in lower:
        missing.append("## Math Problem Solution")
    if "## leetcode solution" not in lower:
        missing.append("## LeetCode Solution")

    math_section = _section_between(final_content, "## Math Problem Solution", "## LeetCode Solution")
    if not _has_math_final_answer(math_section):
        missing.append("math_final_answer")

    leetcode_section = _section_from(final_content, "## LeetCode Solution")
    if not _has_code(leetcode_section):
        missing.append("leetcode_code")
    if not _has_complexity(leetcode_section):
        missing.append("leetcode_complexity")
    return missing


def _has_math_final_answer(section: str) -> bool:
    lower = section.lower()
    return bool(
        section.strip()
        and (
            "final answer" in lower
            or "answer:" in lower
            or "最终答案" in section
            or "答案" in section
            or "\\boxed" in section
            or re.search(r"(?m)^\s*(therefore|so)\b", lower)
        )
    )


def _has_code(section: str) -> bool:
    lower = section.lower()
    return bool(
        "```" in section
        or "class solution" in lower
        or re.search(r"\bdef\s+\w+\s*\(", section)
        or re.search(r"\bfunction\s+\w*\s*\(", section)
        or re.search(r"\bpublic\s+\w+[\w<>\[\]]*\s+\w+\s*\(", section)
    )


def _has_complexity(section: str) -> bool:
    lower = section.lower()
    has_time = "time complexity" in lower or "时间复杂度" in section
    has_space = "space complexity" in lower or "空间复杂度" in section
    if has_time and has_space:
        return True
    return "complexity" in lower and ("o(" in lower or "o（" in lower)


def _section_between(text: str, start_heading: str, end_heading: str) -> str:
    start = _heading_index(text, start_heading)
    if start < 0:
        return ""
    start += len(start_heading)
    end = _heading_index(text, end_heading, start=start)
    return text[start:] if end < 0 else text[start:end]


def _section_from(text: str, heading: str) -> str:
    start = _heading_index(text, heading)
    return "" if start < 0 else text[start + len(heading) :]


def _heading_index(text: str, heading: str, *, start: int = 0) -> int:
    return text.lower().find(heading.lower(), start)


def _context_text(context_bundle: dict[str, object]) -> str:
    chunks: list[str] = []
    recent = context_bundle.get("recent_messages")
    if isinstance(recent, list):
        for item in recent:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                chunks.append(item["text"])
    return "\n".join(chunks)


def _paragraph_blocks(text: str) -> list[str]:
    blocks = [block.strip() for block in re.split(r"\n\s*\n", text.strip()) if block.strip()]
    if len(blocks) > 1:
        return blocks
    return [line.strip() for line in text.splitlines() if line.strip()]


def _is_draft_block(block: str) -> bool:
    lower = block.strip().lower()
    return any(marker in lower for marker in _DRAFT_MARKERS)


def _join_blocks(blocks: list[str]) -> str:
    return "\n\n".join(block.strip() for block in blocks if isinstance(block, str) and block.strip()).strip()


def _clean(value: str) -> str:
    return value.strip()
