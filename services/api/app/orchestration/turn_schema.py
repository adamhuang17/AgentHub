from __future__ import annotations

from dataclasses import dataclass
from typing import Any


TURN_TYPES = {"no_action", "direct_response", "plan_task", "needs_clarification"}
CONFIDENCE_LEVELS = {"low", "medium", "high"}
TARGET_TYPES = {"agent", "orchestrator", "none"}
TARGET_SOURCES = {"private_chat", "mention", "auto_orchestrate", "none"}
STEP_KINDS = {"analysis", "implementation", "review", "deploy"}
TURN_FIELDS = {
    "decision_type",
    "target_type",
    "target_source",
    "target_agent_id",
    "target_agent_ids",
    "goal",
    "steps",
    "reason",
    "confidence",
    "clarification_question",
}
STEP_FIELDS = {
    "id",
    "kind",
    "title",
    "instruction",
    "objective",
    "assigned_agent_id",
    "required_capabilities",
    "depends_on",
    "expected_output",
}


class TurnSchemaError(ValueError):
    code = "turn_router_invalid_output"


@dataclass(frozen=True)
class TurnPlanStep:
    id: str
    kind: str
    title: str
    instruction: str
    objective: str
    assigned_agent_id: str | None
    required_capabilities: list[str]
    depends_on: list[str]
    expected_output: dict[str, object]


@dataclass(frozen=True)
class TurnDecision:
    decision_type: str
    target_type: str
    target_source: str
    target_agent_id: str | None
    target_agent_ids: list[str]
    goal: str | None
    steps: list[TurnPlanStep]
    reason: str
    confidence: str
    clarification_question: str | None


def validate_turn_decision(raw: dict[str, Any]) -> TurnDecision:
    if not isinstance(raw, dict):
        raise TurnSchemaError("Turn router output must be an object.")
    _reject_unknown_fields(raw, TURN_FIELDS, "turn decision")

    decision_type = _required_string(raw, "decision_type")
    if decision_type not in TURN_TYPES:
        raise TurnSchemaError(f"Unsupported decision_type: {decision_type}")

    target_type = _required_string(raw, "target_type")
    if target_type not in TARGET_TYPES:
        raise TurnSchemaError(f"Unsupported target_type: {target_type}")

    target_source = _required_string(raw, "target_source")
    if target_source not in TARGET_SOURCES:
        raise TurnSchemaError(f"Unsupported target_source: {target_source}")

    target_agent_id = raw.get("target_agent_id")
    if target_agent_id is not None and not isinstance(target_agent_id, str):
        raise TurnSchemaError("target_agent_id must be string or null.")

    target_agent_ids = _string_list(raw.get("target_agent_ids"), "target_agent_ids")
    if target_agent_id is not None and target_agent_id not in target_agent_ids:
        raise TurnSchemaError("target_agent_id must be included in target_agent_ids.")

    goal = raw.get("goal")
    if goal is not None and not isinstance(goal, str):
        raise TurnSchemaError("goal must be string or null.")

    raw_steps = raw.get("steps")
    if not isinstance(raw_steps, list):
        raise TurnSchemaError("steps must be a list.")
    steps = [_validate_step(step, index) for index, step in enumerate(raw_steps, start=1)]
    _validate_depends_on(steps)

    reason = _required_string(raw, "reason")
    confidence = _required_string(raw, "confidence")
    if confidence not in CONFIDENCE_LEVELS:
        raise TurnSchemaError(f"Unsupported confidence: {confidence}")

    clarification_question = raw.get("clarification_question")
    if clarification_question is not None and not isinstance(clarification_question, str):
        raise TurnSchemaError("clarification_question must be string or null.")

    _validate_shape(
        decision_type=decision_type,
        target_type=target_type,
        target_source=target_source,
        target_agent_id=target_agent_id,
        target_agent_ids=target_agent_ids,
        goal=goal,
        steps=steps,
        clarification_question=clarification_question,
    )
    return TurnDecision(
        decision_type=decision_type,
        target_type=target_type,
        target_source=target_source,
        target_agent_id=target_agent_id,
        target_agent_ids=target_agent_ids,
        goal=goal,
        steps=steps,
        reason=reason,
        confidence=confidence,
        clarification_question=clarification_question,
    )


def normalize_turn_decision_defaults(
    raw: dict[str, Any],
    *,
    conversation_mode: str,
    private_agent_id: str | None = None,
    mentioned_agent_ids: list[str] | None = None,
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return raw
    if raw.get("decision_type") != "direct_response":
        return raw

    normalized = dict(raw)
    target_type = _clean_string(normalized.get("target_type"))
    target_source = _clean_string(normalized.get("target_source"))
    existing_agent_id = _clean_string(normalized.get("target_agent_id"))
    existing_agent_ids = normalized.get("target_agent_ids")
    valid_agent_ids = _clean_string_list(existing_agent_ids) if isinstance(existing_agent_ids, list) else []
    private_target = _clean_string(private_agent_id)
    mention_targets = _clean_string_list(mentioned_agent_ids or [])
    target_agent_id = existing_agent_id or (valid_agent_ids[0] if valid_agent_ids else None)
    if target_agent_id is None:
        target_agent_id = mention_targets[0] if mention_targets else private_target

    if not target_type:
        target_type = "agent" if target_agent_id else "orchestrator" if conversation_mode in {"group", "group_agent"} else ""

    if target_type == "agent":
        normalized["target_type"] = "agent"
        if target_agent_id:
            if not isinstance(normalized.get("target_agent_id"), str) or not normalized["target_agent_id"].strip():
                normalized["target_agent_id"] = target_agent_id
            if "target_agent_ids" not in normalized or (
                isinstance(existing_agent_ids, list) and not valid_agent_ids
            ):
                normalized["target_agent_ids"] = [target_agent_id]
            inferred_source = _target_source_for_agent(
                target_agent_id,
                private_agent_id=private_target,
                mentioned_agent_ids=mention_targets,
            )
            if not target_source or target_source == "none" or inferred_source in {"private_chat", "mention"}:
                normalized["target_source"] = inferred_source
        return normalized

    if target_type == "orchestrator":
        normalized["target_type"] = "orchestrator"
        if not target_source or target_source == "none":
            normalized["target_source"] = "auto_orchestrate"
        if "target_agent_id" not in normalized:
            normalized["target_agent_id"] = None
        if "target_agent_ids" not in normalized:
            normalized["target_agent_ids"] = []
    return normalized


def _clean_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    clean = value.strip()
    return clean or None


def _clean_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _target_source_for_agent(
    target_agent_id: str,
    *,
    private_agent_id: str | None,
    mentioned_agent_ids: list[str],
) -> str:
    if target_agent_id in mentioned_agent_ids:
        return "mention"
    if private_agent_id and target_agent_id == private_agent_id:
        return "private_chat"
    return "auto_orchestrate"


def _validate_step(raw: object, index: int) -> TurnPlanStep:
    if not isinstance(raw, dict):
        raise TurnSchemaError(f"steps[{index}] must be an object.")
    _reject_unknown_fields(raw, STEP_FIELDS, f"steps[{index}]")

    kind = _required_string(raw, "kind")
    if kind not in STEP_KINDS:
        raise TurnSchemaError(f"Unsupported step kind: {kind}")
    step_id = _optional_string(raw.get("id"), "id") or f"step-{index}"
    instruction = (
        _optional_string(raw.get("instruction"), "instruction")
        or _optional_string(raw.get("objective"), "objective")
    )
    if instruction is None:
        raise TurnSchemaError(f"steps[{index}].instruction must be a non-empty string.")
    title = _optional_string(raw.get("title"), "title") or instruction[:80]
    return TurnPlanStep(
        id=step_id,
        kind=kind,
        title=title,
        instruction=instruction,
        objective=instruction,
        assigned_agent_id=_optional_string(raw.get("assigned_agent_id"), "assigned_agent_id"),
        required_capabilities=_string_list(raw.get("required_capabilities"), "required_capabilities"),
        depends_on=_string_list(raw.get("depends_on"), "depends_on"),
        expected_output=_expected_output(raw.get("expected_output"), title=title, instruction=instruction),
    )


def _validate_shape(
    *,
    decision_type: str,
    target_type: str,
    target_source: str,
    target_agent_id: str | None,
    target_agent_ids: list[str],
    goal: str | None,
    steps: list[TurnPlanStep],
    clarification_question: str | None,
) -> None:
    if decision_type == "no_action":
        if target_type != "none" or target_source != "none":
            raise TurnSchemaError("no_action requires target_type=none and target_source=none.")
        if target_agent_id is not None or target_agent_ids:
            raise TurnSchemaError("no_action must not target agents.")
        if goal is not None or steps or clarification_question is not None:
            raise TurnSchemaError("no_action must not include goal, steps, or clarification_question.")
        return

    if decision_type == "direct_response":
        if target_type not in {"agent", "orchestrator"}:
            raise TurnSchemaError("direct_response requires target_type agent or orchestrator.")
        if target_source == "none":
            raise TurnSchemaError("direct_response requires a target_source.")
        if target_type == "agent" and not target_agent_ids:
            raise TurnSchemaError("direct_response to an agent requires target_agent_ids.")
        if goal is not None or steps or clarification_question is not None:
            raise TurnSchemaError("direct_response must not include goal, steps, or clarification_question.")
        return

    if decision_type == "plan_task":
        if target_type not in {"agent", "orchestrator"}:
            raise TurnSchemaError("plan_task requires target_type agent or orchestrator.")
        if target_source == "none":
            raise TurnSchemaError("plan_task requires a target_source.")
        if target_type == "agent" and not target_agent_ids:
            raise TurnSchemaError("plan_task targeting an agent requires target_agent_ids.")
        if not isinstance(goal, str) or not goal.strip():
            raise TurnSchemaError("plan_task requires a non-empty goal.")
        if not (1 <= len(steps) <= 3):
            raise TurnSchemaError("plan_task decisions must include 1-3 steps.")
        if clarification_question is not None:
            raise TurnSchemaError("plan_task must not include clarification_question.")
        return

    if decision_type == "needs_clarification":
        if steps:
            raise TurnSchemaError("needs_clarification decisions must not include steps.")
        if not isinstance(clarification_question, str) or not clarification_question.strip():
            raise TurnSchemaError("needs_clarification requires a clarification_question.")


def _required_string(raw: dict[str, Any], field: str) -> str:
    value = raw.get(field)
    if not isinstance(value, str) or not value.strip():
        raise TurnSchemaError(f"{field} must be a non-empty string.")
    return value


def _string_list(value: object, field: str) -> list[str]:
    if not isinstance(value, list):
        raise TurnSchemaError(f"{field} must be a list.")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise TurnSchemaError(f"{field} must contain non-empty strings.")
    return list(value)


def _optional_string(value: object, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise TurnSchemaError(f"{field} must be a non-empty string when provided.")
    return value.strip()


def _expected_output(value: object, *, title: str, instruction: str) -> dict[str, object]:
    if value is None:
        return {"title": title, "instruction": instruction}
    if not isinstance(value, dict):
        raise TurnSchemaError("expected_output must be an object.")
    return {**value, "title": value.get("title") or title, "instruction": value.get("instruction") or instruction}


def _validate_depends_on(steps: list[TurnPlanStep]) -> None:
    for index, step in enumerate(steps, start=1):
        allowed = {f"step-{previous}" for previous in range(1, index)}
        allowed.update(previous.id for previous in steps[: index - 1])
        for dependency in step.depends_on:
            if dependency not in allowed:
                raise TurnSchemaError(
                    f"steps[{index}].depends_on contains invalid dependency: {dependency}"
                )


def _reject_unknown_fields(raw: dict[str, Any], allowed: set[str], label: str) -> None:
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise TurnSchemaError(f"{label} contains unsupported fields: {unknown}")
