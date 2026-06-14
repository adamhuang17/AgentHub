from __future__ import annotations

from dataclasses import dataclass

from services.api.app.orchestration.capability_matcher import CapabilityMatch, match_capability
from services.api.app.orchestration.turn_schema import TurnDecision, TurnPlanStep


@dataclass(frozen=True)
class PlanStepDraft:
    external_id: str
    kind: str
    title: str
    instruction: str
    assigned_agent_id: str | None
    status: str
    dispatch_source: str
    dispatch_reason: str
    blocked_reason: str | None
    depends_on: list[str]
    expected_output: dict[str, object]


@dataclass(frozen=True)
class PlanDraft:
    decision: TurnDecision
    steps: list[PlanStepDraft]


def draft_turn_step(decision_step: TurnPlanStep, match: CapabilityMatch) -> PlanStepDraft:
    return _draft_step(
        kind=decision_step.kind,
        external_id=decision_step.id,
        title=decision_step.title,
        instruction=decision_step.instruction,
        depends_on=decision_step.depends_on,
        expected_output={
            **decision_step.expected_output,
            "step_id": decision_step.id,
            "title": decision_step.title,
            "instruction": decision_step.instruction,
        },
        match=match,
    )


def plan_from_turn_decision(
    decision: TurnDecision,
    agents: list[dict[str, object]],
    *,
    preferred_agent_id: str | None = None,
) -> PlanDraft:
    steps = []
    for step in decision.steps:
        step_preferred_agent_id = step.assigned_agent_id or preferred_agent_id
        match = match_capability(
            step.kind,
            agents,
            required_capabilities=step.required_capabilities,
            preferred_agent_id=step_preferred_agent_id,
        )
        steps.append(draft_turn_step(step, match))
    return PlanDraft(decision=decision, steps=steps)


def _draft_step(
    *,
    external_id: str,
    kind: str,
    title: str,
    instruction: str,
    depends_on: list[str],
    expected_output: dict[str, object],
    match: CapabilityMatch,
) -> PlanStepDraft:
    return PlanStepDraft(
        external_id=external_id,
        kind=kind,
        title=title,
        instruction=instruction,
        assigned_agent_id=match.assigned_agent_id,
        status="assigned" if match.assigned_agent_id else "blocked",
        dispatch_source=match.dispatch_source,
        dispatch_reason=match.dispatch_reason,
        blocked_reason=match.blocked_reason,
        depends_on=depends_on,
        expected_output=expected_output,
    )
