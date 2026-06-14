from __future__ import annotations

from http import HTTPStatus
from typing import Any

from services.api.app.agents.repository import get_agent_profiles_by_ids, list_agent_profiles, list_agents
from services.api.app.agent_runs.service import create_direct_response_run_for_message
from services.api.app.conversations.repository import (
    archive_conversation,
    create_conversation,
    create_error_message,
    create_orchestrator_clarification_message,
    create_message,
    delete_conversation,
    get_conversation,
    list_conversation_events,
    list_conversations,
    list_members,
    list_messages,
    update_conversation,
)
from services.api.app.execution.events import append_event
from services.api.app.memory.context_builder import build_context_bundle
from services.api.app.memory.pinned_context import create_pin
from services.api.app.orchestration.mention_dispatcher import (
    validate_mention_agent_ids,
)
from services.api.app.orchestration.planner import PlanStepDraft, plan_from_turn_decision
from services.api.app.orchestration.repository import (
    create_mention_task,
    create_planned_task,
    get_task,
    mark_plan_step_failed,
    mark_plan_step_running,
    mark_plan_step_succeeded,
)
from services.api.app.orchestration.turn_backends.base import TurnRouterBackendError
from services.api.app.orchestration.turn_router_gateway import (
    gateway_from_environment as turn_gateway_from_environment,
    turn_router_backend_configured,
)
from services.api.app.orchestration.turn_schema import TurnDecision, TurnPlanStep, TurnSchemaError, validate_turn_decision
from services.api.app.shared.errors import ValidationError
from services.api.app.shared.http import (
    object_list,
    optional_bool,
    optional_string,
    path_parts,
    single,
    string_list,
)


RouteResponse = tuple[HTTPStatus, dict[str, object]]
MODEL_AGENT_PROVIDERS = {
    "custom_openai",
    "openai",
    "deepseek",
    "zhipu",
    "doubao",
    "qwen",
    "qwen_turbo",
    "volc_deepseek_flash",
    "volc_deepseek_pro",
    "deepseek_official",
    "openrouter",
    "ollama",
}

# Router error codes that, for explicit multi-mention turns from the web group
# chat, fall back to the @-order sequential plan instead of hard-failing. Per
# README, the @ order is the baseline dispatch plan and the router is only a
# *preferred* semantic enhancement. When the router is present but did not yield
# a usable plan for the explicitly @-mentioned agents, the user-supplied @ order
# is still a real, valid dispatch plan (each step runs a real adapter), so this
# degrades gracefully without fake success.
_ROUTER_FALLBACK_FOR_EXPLICIT_MENTIONS = frozenset(
    {
        "turn_router_not_configured",
        "multi_agent_plan_required",
        "router_step_unassigned",
    }
)


def handle_get(path: str, query: dict[str, list[str]], test_run_id: str) -> RouteResponse | None:
    if path == "/api/conversations":
        conversations = list_conversations(
            test_run_id=test_run_id,
            query=single(query, "q"),
            archived=optional_bool(single(query, "archived")),
            include_archived=optional_bool(single(query, "include_archived")) is True,
        )
        return HTTPStatus.OK, {"items": conversations}

    parts = path_parts(path)
    if len(parts) == 3 and parts[:2] == ["api", "conversations"]:
        return HTTPStatus.OK, get_conversation(parts[2], test_run_id=test_run_id)

    if len(parts) == 4 and parts[:2] == ["api", "conversations"] and parts[3] == "messages":
        return HTTPStatus.OK, {"items": list_messages(parts[2], test_run_id=test_run_id)}

    if len(parts) == 4 and parts[:2] == ["api", "conversations"] and parts[3] == "members":
        return HTTPStatus.OK, {"items": list_members(parts[2], test_run_id=test_run_id)}

    if len(parts) == 4 and parts[:2] == ["api", "conversations"] and parts[3] == "context":
        return HTTPStatus.OK, build_context_bundle(parts[2], test_run_id=test_run_id, emit_event=False)

    if len(parts) == 4 and parts[:2] == ["api", "conversations"] and parts[3] == "events":
        return HTTPStatus.OK, {
            "items": list_conversation_events(
                parts[2],
                test_run_id=test_run_id,
                after_sequence=_optional_int(single(query, "after_sequence") or single(query, "after"), "after_sequence"),
                task_id=single(query, "task_id"),
                run_id=single(query, "run_id"),
                artifact_id=single(query, "artifact_id"),
                deployment_id=single(query, "deployment_id"),
                limit=_optional_int(single(query, "limit"), "limit"),
            )
        }

    if len(parts) == 4 and parts[:2] == ["api", "tasks"] and parts[3] == "context":
        task = get_task(parts[2], test_run_id=test_run_id)
        return HTTPStatus.OK, build_context_bundle(
            str(task["conversation_id"]),
            test_run_id=test_run_id,
            emit_event=False,
        )

    if len(parts) == 3 and parts[:2] == ["api", "tasks"]:
        task = get_task(parts[2], test_run_id=test_run_id)
        if _is_legacy_mention_task_without_runs(task):
            task.pop("runs", None)
            task.pop("events", None)
            task.pop("event_summary", None)
        return HTTPStatus.OK, task

    return None


def handle_post(path: str, body: dict[str, Any], test_run_id: str) -> RouteResponse | None:
    if path == "/api/conversations":
        conversation = create_conversation(
            title=str(body.get("title", "")),
            mode=str(body.get("mode", "group_agent")),
            agent_ids=string_list(body.get("agent_ids", []), "agent_ids"),
            test_run_id=test_run_id,
        )
        return HTTPStatus.CREATED, conversation

    parts = path_parts(path)
    if len(parts) == 4 and parts[:2] == ["api", "conversations"] and parts[3] == "archive":
        return HTTPStatus.OK, archive_conversation(parts[2], test_run_id=test_run_id)

    if len(parts) == 4 and parts[:2] == ["api", "conversations"] and parts[3] == "pin":
        return HTTPStatus.CREATED, create_pin(
            conversation_id=parts[2],
            source_type=str(body.get("source_type", "")),
            source_id=optional_string(body.get("source_id"), "source_id"),
            note=optional_string(body.get("note"), "note"),
            test_run_id=test_run_id,
        )

    if len(parts) == 4 and parts[:2] == ["api", "conversations"] and parts[3] == "tasks":
        return HTTPStatus.ACCEPTED, _create_manual_task(parts[2], body, test_run_id)

    if len(parts) == 4 and parts[:2] == ["api", "conversations"] and parts[3] == "messages":
        mentions = object_list(body.get("mentions", []), "mentions")
        mention_agent_ids = _validate_mentions_for_response(mentions)
        if isinstance(mention_agent_ids, tuple):
            return mention_agent_ids
        selected_agent_id = optional_string(body.get("selected_agent_id"), "selected_agent_id")
        target_agent_id = optional_string(body.get("target_agent_id"), "target_agent_id")
        force_agent = _bool_body_value(body.get("force_agent"), default=False)
        source_surface = optional_string(body.get("source_surface"), "source_surface")
        conversation = get_conversation(parts[2], test_run_id=test_run_id)
        private_agent_id = _private_agent_id(str(conversation["id"]), str(conversation["mode"]), test_run_id)
        effective_agent_id = _effective_agent_id(
            selected_agent_id=selected_agent_id,
            target_agent_id=target_agent_id,
            mention_agent_ids=mention_agent_ids,
            private_agent_id=private_agent_id,
            conversation_mode=str(conversation["mode"]),
            force_agent=force_agent,
        )

        message = create_message(
            conversation_id=parts[2],
            message_type=str(body.get("message_type", "")),
            content=body.get("content", {}),
            mentions=mentions,
            references=object_list(body.get("references", []), "references"),
            reply_to_id=optional_string(body.get("reply_to_id"), "reply_to_id"),
            test_run_id=test_run_id,
        )

        if mention_agent_ids and not _should_execute_mentions(
            body,
            source_surface=source_surface,
            force_agent=force_agent,
            selected_agent_id=selected_agent_id,
        ):
            return _legacy_mention_task_response(message, mention_agent_ids, test_run_id=test_run_id)

        if len(mention_agent_ids) > 1:
            raw_decision = body.get("turn_decision") if isinstance(body.get("turn_decision"), dict) else None
            return _multi_explicit_agent_response(
                message,
                target_agent_ids=mention_agent_ids,
                raw_turn_decision=raw_decision,
                test_run_id=test_run_id,
                source_surface=source_surface,
            )

        if effective_agent_id is not None:
            raw_decision = body.get("turn_decision") if isinstance(body.get("turn_decision"), dict) else None
            if isinstance(raw_decision, dict) and raw_decision.get("decision_type") == "plan_task":
                return _explicit_plan_response(
                    message,
                    raw_decision,
                    target_agent_id=effective_agent_id,
                    test_run_id=test_run_id,
                    source_surface=source_surface,
                )
            return _explicit_agent_response(
                message,
                target_agent_id=effective_agent_id,
                test_run_id=test_run_id,
                source_surface=source_surface,
                forced=force_agent or bool(mention_agent_ids) or selected_agent_id is not None,
            )

        if _should_invoke_turn_router(body):
            turn_response = _turn_message_response(message, body, test_run_id)
            if isinstance(turn_response, tuple):
                _status, payload = turn_response
                return HTTPStatus.CREATED, _message_response_payload(
                    message,
                    error_card=_object_payload(payload.get("error_card")),
                    selected_agent_effective=None,
                    dispatch_path="failed",
                    extra=payload,
                    test_run_id=test_run_id,
                )
            _record_turn_decision_event(message, turn_response, source="turn_router")
            if turn_response.decision_type == "no_action":
                return HTTPStatus.CREATED, _message_response_payload(
                    message,
                    selected_agent_effective=None,
                    dispatch_path="blocked",
                    test_run_id=test_run_id,
                )
            if turn_response.decision_type == "direct_response":
                if _message_requests_plan(message):
                    task = _create_promoted_plan_task(message, test_run_id=test_run_id)
                    return HTTPStatus.CREATED, _message_response_payload(
                        message,
                        task=task,
                        selected_agent_effective=None,
                        dispatch_path="router_plan_task",
                        test_run_id=test_run_id,
                    )
                target_agent_id = _direct_response_target_agent_id(turn_response, message, test_run_id)
                if target_agent_id is None:
                    error_card = _error_card(
                        card_type="send_failure",
                        error_code="direct_response_target_unavailable",
                        message="No configured model agent is available for orchestrator direct_response.",
                        recovery_hint="Configure Demo Model Agent or select a private Agent before retrying.",
                    )
                    _record_turn_failure_events(
                        message,
                        code="direct_response_target_unavailable",
                        failure_message=str(error_card["message"]),
                        recovery_hint=_optional_card_text(error_card.get("recovery_hint")),
                        source="turn_router",
                    )
                    return HTTPStatus.CREATED, _message_response_payload(
                        message,
                        error_card=error_card,
                        selected_agent_effective=None,
                        dispatch_path="failed",
                        extra={
                            "error": "direct_response_target_unavailable",
                            "code": "direct_response_target_unavailable",
                            "error_code": "direct_response_target_unavailable",
                            "message_id": str(message["id"]),
                            "retryable": True,
                        },
                        test_run_id=test_run_id,
                    )
                run = create_direct_response_run_for_message(
                    message,
                    target_agent_id=target_agent_id,
                    test_run_id=test_run_id,
                )
                return HTTPStatus.CREATED, _agent_run_message_response(
                    message,
                    run,
                    selected_agent_effective=_selected_agent_effective(
                        target_agent_id,
                        forced=False,
                        source="turn_router",
                    ),
                    dispatch_path="router_direct_response",
                    test_run_id=test_run_id,
                )
            if turn_response.decision_type == "needs_clarification":
                clarification = create_orchestrator_clarification_message(
                    conversation_id=str(message["conversation_id"]),
                    content_text=str(turn_response.clarification_question),
                    reply_to_id=str(message["id"]),
                    test_run_id=test_run_id,
                )
                return HTTPStatus.CREATED, _message_response_payload(
                    message,
                    assistant_message=clarification,
                    selected_agent_effective=None,
                    dispatch_path="router_direct_response",
                    extra={"clarification_message": clarification},
                    test_run_id=test_run_id,
                )
            plan = plan_from_turn_decision(
                turn_response,
                list_agents(enabled=True),
                preferred_agent_id=_preferred_agent_id_from_decision(turn_response),
            )
        else:
            plan = None

        if plan is not None:
            task = create_planned_task(
                conversation_id=str(message["conversation_id"]),
                message_id=str(message["id"]),
                goal=plan.decision.goal or _message_goal(message),
                steps=plan.steps,
                test_run_id=test_run_id,
            )
            return HTTPStatus.CREATED, _message_response_payload(
                message,
                task=task,
                selected_agent_effective=_selected_agent_effective(
                    _preferred_agent_id_from_decision(plan.decision),
                    forced=False,
                    source="turn_router",
                ),
                dispatch_path="router_plan_task",
                test_run_id=test_run_id,
            )
        return HTTPStatus.CREATED, _message_response_payload(
            message,
            selected_agent_effective=None,
            dispatch_path="blocked",
            test_run_id=test_run_id,
        )

    return None


def handle_patch(path: str, body: dict[str, Any], test_run_id: str) -> RouteResponse | None:
    parts = path_parts(path)
    if len(parts) == 3 and parts[:2] == ["api", "conversations"]:
        return HTTPStatus.OK, update_conversation(
            parts[2],
            title=optional_string(body.get("title"), "title") if "title" in body else None,
            test_run_id=test_run_id,
        )
    return None


def handle_delete(path: str, test_run_id: str) -> RouteResponse | None:
    parts = path_parts(path)
    if len(parts) == 3 and parts[:2] == ["api", "conversations"]:
        return HTTPStatus.OK, delete_conversation(parts[2], test_run_id=test_run_id)
    return None


def _explicit_agent_response(
    message: dict[str, object],
    *,
    target_agent_id: str,
    test_run_id: str,
    source_surface: str | None,
    forced: bool,
    instruction_override: str | None = None,
) -> RouteResponse:
    unavailable = _target_agent_unavailable_card(target_agent_id, source_surface=source_surface)
    selected_agent = _selected_agent_effective(target_agent_id, forced=forced, source="explicit_agent")
    if unavailable is not None:
        _record_turn_failure_events(
            message,
            code=str(unavailable["error_code"]),
            failure_message=str(unavailable["message"]),
            recovery_hint=_optional_card_text(unavailable.get("recovery_hint")),
            source="explicit_agent",
        )
        return HTTPStatus.CREATED, _message_response_payload(
            message,
            error_card=unavailable,
            selected_agent_effective=selected_agent,
            dispatch_path="blocked",
            test_run_id=test_run_id,
        )

    try:
        run = create_direct_response_run_for_message(
            message,
            target_agent_id=target_agent_id,
            test_run_id=test_run_id,
            instruction_override=instruction_override,
        )
    except ValidationError as exc:
        card = _target_agent_unavailable_card(
            target_agent_id,
            source_surface=source_surface,
            error_code=getattr(exc, "code", "target_agent_unavailable"),
            message=str(exc),
        ) or _error_card(
            card_type="target_agent_unavailable",
            error_code=getattr(exc, "code", "target_agent_unavailable"),
            message=str(exc),
            recovery_hint="Choose another Agent or fix the selected Agent runtime.",
            target_agent_id=target_agent_id,
        )
        _record_turn_failure_events(
            message,
            code=str(card["error_code"]),
            failure_message=str(card["message"]),
            recovery_hint=_optional_card_text(card.get("recovery_hint")),
            source="explicit_agent",
        )
        return HTTPStatus.CREATED, _message_response_payload(
            message,
            error_card=card,
            selected_agent_effective=selected_agent,
            dispatch_path="blocked",
            test_run_id=test_run_id,
        )

    return HTTPStatus.CREATED, _agent_run_message_response(
        message,
        run,
        selected_agent_effective=selected_agent,
        dispatch_path="explicit_agent",
        test_run_id=test_run_id,
    )


def _router_plan_for_mentions(
    message: dict[str, object],
    *,
    target_agent_ids: list[str],
    raw_turn_decision: dict[str, object] | None,
    test_run_id: str,
) -> tuple[dict[str, object] | None, list[dict[str, object]], dict[str, object] | None]:
    conversation = get_conversation(str(message["conversation_id"]), test_run_id=test_run_id)
    try:
        decision = turn_gateway_from_environment(raw_turn_decision).decide_for_message(
            message,
            conversation_mode=str(conversation["mode"]),
            private_agent_id=_private_agent_id(str(message["conversation_id"]), str(conversation["mode"]), test_run_id),
            auto_orchestrate=True,
            test_run_id=test_run_id,
        )
    except TurnRouterBackendError as exc:
        return None, [], _error_card(
            card_type="send_failure",
            error_code=exc.code,
            message=str(exc),
            recovery_hint=exc.recovery_hint,
        )
    except TurnSchemaError as exc:
        return None, [], _error_card(
            card_type="send_failure",
            error_code=exc.code,
            message="Router output invalid.",
            recovery_hint="Retry after the turn router returns schema-compliant JSON with assigned_agent_id for each step.",
        )

    if decision.decision_type != "plan_task" or not decision.steps:
        return None, [], _error_card(
            card_type="send_failure",
            error_code="multi_agent_plan_required",
            message="Multiple mentioned Agents require a router plan with semantic step order.",
            recovery_hint="Configure the router to return plan_task steps with assigned_agent_id and depends_on.",
        )

    mentioned_agents = get_agent_profiles_by_ids(target_agent_ids)
    plan_steps, execution_steps = _router_steps_for_mentions(decision, mentioned_agents, target_agent_ids)
    if not execution_steps:
        return None, [], _error_card(
            card_type="send_failure",
            error_code="router_step_unassigned",
            message="Router did not assign any plan step to a mentioned Agent.",
            recovery_hint="Ensure each router plan step has assigned_agent_id set to a concrete mentioned Agent ID.",
        )
    task = create_planned_task(
        conversation_id=str(message["conversation_id"]),
        message_id=str(message["id"]),
        goal=decision.goal or _message_goal(message),
        steps=plan_steps,
        test_run_id=test_run_id,
    )
    _attach_persisted_plan_step_ids(task, execution_steps)
    return task, execution_steps, None


def _router_steps_for_mentions(
    decision: TurnDecision,
    mentioned_agents: list[dict[str, object]],
    mentioned_agent_ids: list[str],
) -> tuple[list[PlanStepDraft], list[dict[str, object]]]:
    ordered_steps = _topological_router_steps(decision.steps)
    plan_steps: list[PlanStepDraft] = []
    execution_steps: list[dict[str, object]] = []
    for index, step in enumerate(ordered_steps):
        agent_id = _router_assigned_agent_id(
            step,
            index=index,
            decision=decision,
            mentioned_agents=mentioned_agents,
            mentioned_agent_ids=mentioned_agent_ids,
        )
        unavailable = _target_agent_unavailable_card(agent_id, source_surface="turn_router") if agent_id else None
        blocked_reason = None
        if not agent_id:
            blocked_reason = "router_step_unassigned"
        elif unavailable is not None:
            blocked_reason = str(unavailable.get("error_code") or "target_agent_unavailable")
        plan_steps.append(
            PlanStepDraft(
                external_id=step.id,
                kind=step.kind,
                title=step.title,
                instruction=step.instruction,
                assigned_agent_id=agent_id,
                status="blocked" if blocked_reason else "assigned",
                dispatch_source="turn_router",
                dispatch_reason=(
                    f"turn_router:{agent_id}: semantic multi-mention order from router plan"
                    if agent_id
                    else "turn_router:unassigned: router step did not identify a mentioned Agent"
                ),
                blocked_reason=blocked_reason,
                depends_on=list(step.depends_on),
                expected_output={
                    **step.expected_output,
                    "step_id": step.id,
                    "title": step.title,
                    "instruction": step.instruction,
                    "assigned_agent_id": agent_id,
                },
            )
        )
        execution_steps.append(
            {
                "step_id": step.id,
                "agent_id": agent_id,
                "instruction": step.instruction,
                "blocked_reason": blocked_reason,
            }
        )
    return plan_steps, execution_steps


def _fallback_plan_for_explicit_mentions(
    message: dict[str, object],
    *,
    target_agent_ids: list[str],
    test_run_id: str,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    mentioned_agents = {str(agent["id"]): agent for agent in get_agent_profiles_by_ids(target_agent_ids)}
    plan_steps: list[PlanStepDraft] = []
    execution_steps: list[dict[str, object]] = []
    previous_external_id: str | None = None
    total = len(target_agent_ids)
    for index, agent_id in enumerate(target_agent_ids):
        agent = mentioned_agents.get(agent_id)
        agent_name = str(agent.get("name") or agent_id) if agent else agent_id
        external_id = f"web-mention-{index + 1}"
        unavailable = _target_agent_unavailable_card(agent_id, source_surface="web")
        blocked_reason = str(unavailable.get("error_code")) if unavailable else None
        depends_on = [previous_external_id] if previous_external_id else []
        instruction = _fallback_mention_instruction(
            message,
            agent_name=agent_name,
            step_index=index,
            total_steps=total,
        )
        plan_steps.append(
            PlanStepDraft(
                external_id=external_id,
                kind="agent_message",
                title=f"{agent_name} handoff",
                instruction=instruction,
                assigned_agent_id=agent_id,
                status="blocked" if blocked_reason else "assigned",
                dispatch_source="web_multi_mention",
                dispatch_reason=f"web_multi_mention:{agent_id}: sequential fallback from explicit @ order",
                blocked_reason=blocked_reason,
                depends_on=depends_on,
                expected_output={
                    "kind": "agent_message",
                    "step_id": external_id,
                    "title": f"{agent_name} handoff",
                    "instruction": instruction,
                    "assigned_agent_id": agent_id,
                    "fallback": "explicit_mention_order",
                },
            )
        )
        execution_steps.append(
            {
                "step_id": external_id,
                "agent_id": agent_id,
                "instruction": instruction,
                "blocked_reason": blocked_reason,
            }
        )
        previous_external_id = external_id

    task = create_planned_task(
        conversation_id=str(message["conversation_id"]),
        message_id=str(message["id"]),
        goal=_message_goal(message),
        steps=plan_steps,
        test_run_id=test_run_id,
    )
    _attach_persisted_plan_step_ids(task, execution_steps)
    return task, execution_steps


def _attach_persisted_plan_step_ids(task: dict[str, object], execution_steps: list[dict[str, object]]) -> None:
    persisted_steps = task.get("steps") if isinstance(task.get("steps"), list) else []
    steps_by_external_id = {
        str(step.get("external_id")): step
        for step in persisted_steps
        if isinstance(step, dict) and step.get("external_id") is not None
    }
    for index, execution_step in enumerate(execution_steps):
        persisted = steps_by_external_id.get(str(execution_step.get("step_id")))
        if persisted is None and index < len(persisted_steps) and isinstance(persisted_steps[index], dict):
            persisted = persisted_steps[index]
        if isinstance(persisted, dict):
            execution_step["plan_step_id"] = persisted.get("id")


def _fallback_mention_instruction(
    message: dict[str, object],
    *,
    agent_name: str,
    step_index: int,
    total_steps: int,
) -> str:
    return "\n\n".join(
        [
            f"You are {agent_name}, step {step_index + 1} of {total_steps} in an AgentHub multi-Agent handoff.",
            "Use the user's original request as the shared goal. Focus on the portion that fits your capabilities.",
            "When previous Agent output is provided, build on it instead of starting over.",
            f"Original request:\n{_message_goal(message)}",
        ]
    )


def _router_assigned_agent_id(
    step: TurnPlanStep,
    *,
    index: int,
    decision: TurnDecision,
    mentioned_agents: list[dict[str, object]],
    mentioned_agent_ids: list[str],
) -> str | None:
    mentioned = set(mentioned_agent_ids)
    if step.assigned_agent_id in mentioned:
        return step.assigned_agent_id
    router_targets = [agent_id for agent_id in decision.target_agent_ids if agent_id in mentioned]
    if len(router_targets) == len(decision.steps) and index < len(router_targets):
        return router_targets[index]
    return _agent_id_named_in_router_step(step, mentioned_agents)


def _agent_id_named_in_router_step(step: TurnPlanStep, mentioned_agents: list[dict[str, object]]) -> str | None:
    haystack = " ".join(
        [
            step.title,
            step.instruction,
            " ".join(step.required_capabilities),
            str(step.expected_output),
        ]
    ).lower()
    for agent in mentioned_agents:
        agent_id = str(agent.get("id") or "")
        name = str(agent.get("name") or "")
        if agent_id and agent_id.lower() in haystack:
            return agent_id
        if name and name.lower() in haystack:
            return agent_id
    return None


def _topological_router_steps(steps: list[TurnPlanStep]) -> list[TurnPlanStep]:
    by_id = {step.id: step for step in steps}
    ordered: list[TurnPlanStep] = []
    pending = list(steps)
    resolved: set[str] = set()
    while pending:
        progressed = False
        for step in list(pending):
            dependencies = [dep for dep in step.depends_on if dep in by_id]
            if all(dep in resolved for dep in dependencies):
                ordered.append(step)
                resolved.add(step.id)
                pending.remove(step)
                progressed = True
        if not progressed:
            ordered.extend(pending)
            break
    return ordered


def _multi_explicit_agent_response(
    message: dict[str, object],
    *,
    target_agent_ids: list[str],
    raw_turn_decision: dict[str, object] | None,
    test_run_id: str,
    source_surface: str | None,
) -> RouteResponse:
    task, execution_steps, router_error = _router_plan_for_mentions(
        message,
        target_agent_ids=target_agent_ids,
        raw_turn_decision=raw_turn_decision,
        test_run_id=test_run_id,
    )
    if router_error is not None:
        if source_surface == "web" and router_error.get("error_code") in _ROUTER_FALLBACK_FOR_EXPLICIT_MENTIONS:
            task, execution_steps = _fallback_plan_for_explicit_mentions(
                message,
                target_agent_ids=target_agent_ids,
                test_run_id=test_run_id,
            )
        else:
            _record_turn_failure_events(
                message,
                code=str(router_error["error_code"]),
                failure_message=str(router_error["message"]),
                recovery_hint=_optional_card_text(router_error.get("recovery_hint")),
                source="turn_router",
            )
            return HTTPStatus.CREATED, _message_response_payload(
                message,
                error_card=router_error,
                selected_agent_effective=None,
                dispatch_path="failed",
                test_run_id=test_run_id,
            )

    # Return an SSE event generator so each agent result is streamed
    # to the frontend immediately upon completion.
    def _stream_events():
        assistant_messages: list[dict[str, object]] = []
        agent_runs: list[dict[str, object]] = []
        error_cards: list[dict[str, object]] = []
        error_messages: list[dict[str, object]] = []
        selected_agents: list[dict[str, object]] = []
        prior_output: str | None = None
        blocked_by_previous_failure = False

        for index, step in enumerate(execution_steps):
            agent_id = str(step.get("agent_id") or "")
            plan_step_id = str(step.get("plan_step_id") or "")
            selected = _selected_agent_effective(agent_id, forced=True, source="explicit_agent")
            if isinstance(selected, dict):
                selected_agents.append(selected)
            if not agent_id or blocked_by_previous_failure:
                error_code = "previous_step_failed" if blocked_by_previous_failure else "router_step_unassigned"
                card = _error_card(
                    card_type="sequential_step_blocked",
                    error_code=error_code,
                    message=(
                        "Previous Agent step failed, so this Agent did not receive a usable handoff."
                        if blocked_by_previous_failure
                        else "Router did not assign this plan step to a mentioned Agent."
                    ),
                    recovery_hint=(
                        "Fix the earlier Agent failure, then retry the group instruction."
                        if blocked_by_previous_failure
                        else "Adjust the router prompt/configuration so every multi-Agent step has assigned_agent_id."
                    ),
                    target_agent_id=agent_id or None,
                )
                if plan_step_id:
                    mark_plan_step_failed(
                        plan_step_id,
                        test_run_id=test_run_id,
                        error_code=error_code,
                    )
                _record_turn_failure_events(
                    message,
                    code=str(card["error_code"]),
                    failure_message=str(card["message"]),
                    recovery_hint=_optional_card_text(card.get("recovery_hint")),
                    source="explicit_agent_group",
                )
                error_cards.append(card)
                error_message = create_error_message(
                    conversation_id=str(message["conversation_id"]),
                    sender_id=agent_id or "orchestrator",
                    error_card=card,
                    reply_to_id=str(message["id"]),
                    test_run_id=test_run_id,
                )
                error_messages.append(error_message)
                blocked_by_previous_failure = True
                # Stream this error step immediately
                yield "agent_error", {
                    "error_card": card,
                    "error_message": error_message,
                    "step_index": index,
                    "agent_id": agent_id or None,
                }
                continue

            if plan_step_id:
                mark_plan_step_running(plan_step_id, test_run_id=test_run_id)
            instruction_override = _sequential_instruction(
                message,
                prior_output,
                step_index=index,
                step_instruction=str(step.get("instruction") or ""),
            )

            # Stream a "step_started" event so the frontend can show a spinner
            yield "step_started", {
                "step_index": index,
                "agent_id": agent_id,
                "agent_name": (selected or {}).get("name"),
                "total_steps": len(execution_steps),
            }

            status, payload = _explicit_agent_response(
                message,
                target_agent_id=agent_id,
                test_run_id=test_run_id,
                source_surface=source_surface,
                forced=True,
                instruction_override=instruction_override,
            )
            del status
            assistant_message = payload.get("assistant_message")
            if isinstance(assistant_message, dict):
                assistant_messages.append(assistant_message)
                prior_output = _message_text(assistant_message)
            agent_run = payload.get("agent_run")
            if isinstance(agent_run, dict):
                agent_runs.append(agent_run)
            error_card = payload.get("error_card")
            if isinstance(error_card, dict):
                error_cards.append(error_card)
                blocked_by_previous_failure = True
            error_message = payload.get("error_message")
            if isinstance(error_message, dict):
                error_messages.append(error_message)
            if assistant_message is None and (not agent_run or agent_run.get("status") != "succeeded"):
                blocked_by_previous_failure = True
            if plan_step_id:
                if isinstance(agent_run, dict) and agent_run.get("status") == "succeeded":
                    mark_plan_step_succeeded(
                        plan_step_id,
                        test_run_id=test_run_id,
                        run_id=str(agent_run.get("id") or ""),
                    )
                else:
                    mark_plan_step_failed(
                        plan_step_id,
                        test_run_id=test_run_id,
                        run_id=str(agent_run.get("id") or "") if isinstance(agent_run, dict) else None,
                        error_code=(
                            str(agent_run.get("error_code"))
                            if isinstance(agent_run, dict) and agent_run.get("error_code")
                            else str(error_card.get("error_code"))
                            if isinstance(error_card, dict) and error_card.get("error_code")
                            else "agent_run_failed"
                        ),
                    )

            # Stream this agent's result immediately
            yield "agent_result", {
                "assistant_message": assistant_message,
                "agent_run": agent_run,
                "error_card": error_card,
                "error_message": error_message,
                "step_index": index,
                "agent_id": agent_id,
            }

        if error_cards and agent_runs:
            dispatch_path = "partial_failure"
        elif error_cards:
            dispatch_path = "failed"
        else:
            dispatch_path = "explicit_agent_group"
        if task is not None:
            task = get_task(str(task["id"]), test_run_id=test_run_id)

        # Final "done" event carries the complete aggregated payload
        # so non-SSE callers can still use it.
        final_payload = _message_response_payload(
            message,
            assistant_message=assistant_messages[0] if assistant_messages else None,
            agent_run=agent_runs[0] if agent_runs else None,
            task=task,
            error_card=None,
            selected_agent_effective=selected_agents[0] if selected_agents else None,
            dispatch_path=dispatch_path,
            extra={
                "assistant_messages": assistant_messages,
                "agent_runs": agent_runs,
                "error_cards": error_cards,
                "error_messages": error_messages,
                "selected_agents_effective": selected_agents,
            },
            test_run_id=test_run_id,
        )
        yield "done", final_payload

    # When the frontend requests SSE (via Accept header or stream param),
    # return the generator; otherwise fall back to the blocking behaviour.
    # We use a callable marker: the status is CREATED, and the "payload"
    # is the generator function itself.  main.py detects this and streams.
    return HTTPStatus.CREATED, _stream_events


def _explicit_plan_response(
    message: dict[str, object],
    raw_decision: dict[str, object],
    *,
    target_agent_id: str,
    test_run_id: str,
    source_surface: str | None,
) -> RouteResponse:
    selected_agent = _selected_agent_effective(target_agent_id, forced=True, source="explicit_agent")
    unavailable = _target_agent_unavailable_card(target_agent_id, source_surface=source_surface)
    if unavailable is not None:
        _record_turn_failure_events(
            message,
            code=str(unavailable["error_code"]),
            failure_message=str(unavailable["message"]),
            recovery_hint=_optional_card_text(unavailable.get("recovery_hint")),
            source="explicit_agent",
        )
        return HTTPStatus.CREATED, _message_response_payload(
            message,
            error_card=unavailable,
            selected_agent_effective=selected_agent,
            dispatch_path="blocked",
            test_run_id=test_run_id,
        )

    normalized = {
        **raw_decision,
        "target_type": "agent",
        "target_source": "mention" if message.get("mentions") else "private_chat",
        "target_agent_id": target_agent_id,
        "target_agent_ids": [target_agent_id],
    }
    try:
        decision = validate_turn_decision(normalized)
    except TurnSchemaError as exc:
        card = _error_card(
            card_type="router_failed",
            error_code=getattr(exc, "code", "turn_router_invalid_output"),
            message="Explicit plan decision was invalid.",
            recovery_hint="Retry after sending a schema-compliant plan_task decision.",
            target_agent_id=target_agent_id,
        )
        _record_turn_failure_events(
            message,
            code=str(card["error_code"]),
            failure_message=str(card["message"]),
            recovery_hint=_optional_card_text(card.get("recovery_hint")),
            source="explicit_agent",
            include_router_invalid=True,
        )
        return HTTPStatus.CREATED, _message_response_payload(
            message,
            error_card=card,
            selected_agent_effective=selected_agent,
            dispatch_path="failed",
            test_run_id=test_run_id,
        )

    _record_turn_decision_event(message, decision, source="explicit_agent")
    plan = plan_from_turn_decision(
        decision,
        list_agents(enabled=True),
        preferred_agent_id=target_agent_id,
    )
    task = create_planned_task(
        conversation_id=str(message["conversation_id"]),
        message_id=str(message["id"]),
        goal=plan.decision.goal or _message_goal(message),
        steps=plan.steps,
        test_run_id=test_run_id,
    )
    return HTTPStatus.CREATED, _message_response_payload(
        message,
        task=task,
        selected_agent_effective=selected_agent,
        dispatch_path="router_plan_task",
        test_run_id=test_run_id,
    )


def _agent_run_message_response(
    message: dict[str, object],
    run: dict[str, object],
    *,
    selected_agent_effective: dict[str, object] | None,
    dispatch_path: str,
    test_run_id: str,
) -> dict[str, object]:
    assistant_message = run.get("assistant_message") if isinstance(run.get("assistant_message"), dict) else None
    error_card = _agent_run_error_card(run, test_run_id=test_run_id) if _agent_run_unsuccessful(run) else None
    return _message_response_payload(
        message,
        assistant_message=assistant_message,
        agent_run=run,
        error_card=error_card,
        selected_agent_effective=selected_agent_effective,
        dispatch_path=dispatch_path if error_card is None else "failed",
        test_run_id=test_run_id,
    )


def _agent_run_unsuccessful(run: dict[str, object]) -> bool:
    return str(run.get("status") or "") in {"failed", "incomplete", "final_content_empty"}


def _message_response_payload(
    message: dict[str, object],
    *,
    assistant_message: dict[str, object] | None = None,
    agent_run: dict[str, object] | None = None,
    task: dict[str, object] | None = None,
    error_card: dict[str, object] | None = None,
    selected_agent_effective: dict[str, object] | None = None,
    dispatch_path: str,
    extra: dict[str, object] | None = None,
    test_run_id: str,
) -> dict[str, object]:
    payload = dict(message)
    error_message = None
    if error_card is not None:
        error_sender = str(error_card.get("target_agent_id") or "orchestrator")
        error_message = create_error_message(
            conversation_id=str(message["conversation_id"]),
            sender_id=error_sender,
            error_card=error_card,
            reply_to_id=str(message["id"]),
            test_run_id=test_run_id,
        )
    if task is not None:
        payload["task_id"] = task["id"]
        payload["created_task_id"] = task["id"]
    if agent_run is not None:
        payload["run_id"] = agent_run["id"]
    payload["message"] = message
    payload["assistant_message"] = assistant_message
    payload["agent_run"] = agent_run
    payload["task"] = task
    payload["error_card"] = error_card
    payload["error_message"] = error_message
    payload["events_summary"] = _events_summary(str(message["conversation_id"]), test_run_id=test_run_id)
    payload["selected_agent_effective"] = selected_agent_effective
    payload["dispatch_path"] = dispatch_path
    if extra:
        for key, value in extra.items():
            if key == "message":
                payload["error_message"] = value
            elif key == "error_card":
                continue
            else:
                payload[key] = value
    return payload


def _effective_agent_id(
    *,
    selected_agent_id: str | None,
    target_agent_id: str | None,
    mention_agent_ids: list[str],
    private_agent_id: str | None,
    conversation_mode: str,
    force_agent: bool,
) -> str | None:
    if target_agent_id:
        return target_agent_id
    if selected_agent_id:
        return selected_agent_id
    if mention_agent_ids:
        return mention_agent_ids[0]
    if force_agent:
        return private_agent_id
    if conversation_mode in {"private", "private_agent", "single"} and private_agent_id:
        return private_agent_id
    return None


def _should_execute_mentions(
    body: dict[str, Any],
    *,
    source_surface: str | None,
    force_agent: bool,
    selected_agent_id: str | None,
) -> bool:
    return (
        source_surface == "web"
        or force_agent
        or selected_agent_id is not None
        or body.get("execute_mentions") is True
        or body.get("orchestrate") is True
        or body.get("turn_route") is True
        or "turn_decision" in body
    )


def _legacy_mention_task_response(
    message: dict[str, object],
    agent_ids: list[str],
    *,
    test_run_id: str,
) -> RouteResponse:
    dispatch_reasons = {
        agent_id: f"explicit_mention:{agent_id}: assigned from persisted message.mentions; mentioned Agent selected"
        for agent_id in agent_ids
    }
    task = create_mention_task(
        conversation_id=str(message["conversation_id"]),
        message_id=str(message["id"]),
        goal=_message_goal(message),
        agent_ids=agent_ids,
        dispatch_reasons=dispatch_reasons,
        test_run_id=test_run_id,
    )
    return HTTPStatus.CREATED, _message_response_payload(
        message,
        task=task,
        selected_agent_effective=_selected_agent_effective(agent_ids[0] if agent_ids else None, forced=True, source="mention"),
        dispatch_path="mention_task",
        test_run_id=test_run_id,
    )


def _target_agent_unavailable_card(
    target_agent_id: str,
    *,
    source_surface: str | None,
    error_code: str = "target_agent_unavailable",
    message: str | None = None,
) -> dict[str, object] | None:
    agents = get_agent_profiles_by_ids([target_agent_id])
    if not agents:
        return _error_card(
            card_type="target_agent_unavailable",
            error_code=error_code,
            message=message or f"Selected Agent is not available: {target_agent_id}.",
            recovery_hint="Refresh the Agent list or choose a configured Agent.",
            target_agent_id=target_agent_id,
            source_surface=source_surface,
        )
    agent = agents[0]
    if agent.get("enabled") is not True:
        effective_code = "agent_disabled" if error_code == "target_agent_unavailable" else error_code
        return _error_card(
            card_type="target_agent_unavailable",
            error_code=effective_code,
            message=message or f"Selected Agent is disabled: {agent.get('name') or target_agent_id}.",
            recovery_hint="Enable the Agent profile or choose another Agent.",
            target_agent_id=target_agent_id,
            source_surface=source_surface,
        )
    if agent.get("configured") is not True or agent.get("execution_enabled") is not True:
        effective_code = (
            str(agent.get("error_code"))
            if error_code == "target_agent_unavailable" and agent.get("error_code")
            else error_code
        )
        return _error_card(
            card_type="target_agent_unavailable",
            error_code=effective_code,
            message=message or f"Selected Agent is not executable: {agent.get('name') or target_agent_id}.",
            recovery_hint=_optional_card_text(agent.get("recovery_hint"))
            or "Fix the Agent runtime shown in the left panel, then retry.",
            target_agent_id=target_agent_id,
            source_surface=source_surface,
            agent_status={
                "configured": agent.get("configured"),
                "execution_enabled": agent.get("execution_enabled"),
                "health_status": agent.get("health_status"),
                "runtime_status": agent.get("runtime_status"),
                "error_code": agent.get("error_code"),
            },
        )
    return None


def _agent_run_error_card(run: dict[str, object], *, test_run_id: str) -> dict[str, object]:
    failure_payload: dict[str, object] = {}
    events = list_conversation_events(
        str(run["conversation_id"]),
        test_run_id=test_run_id,
        run_id=str(run["id"]),
    )
    for event in reversed(events):
        if event.get("type") == "agent_run.failed":
            failure_payload = event.get("payload_json") if isinstance(event.get("payload_json"), dict) else {}
            break
    agent_id = str(run.get("target_agent_id") or "")
    agent = _agent_by_id(agent_id)
    agent_name = str(agent.get("name") or agent_id or "Agent") if agent else agent_id or "Agent"
    return _error_card(
        card_type="agent_run_failed",
        error_code=str(failure_payload.get("error_code") or run.get("error_code") or "agent_run_failed"),
        message=str(failure_payload.get("message") or f"{agent_name} execution failed."),
        recovery_hint=_optional_card_text(failure_payload.get("recovery_hint")),
        target_agent_id=agent_id,
        run_id=str(run["id"]),
        provider=_optional_card_text(failure_payload.get("provider")),
        stderr_summary=_optional_card_text(failure_payload.get("stderr_summary")),
        exit_code=failure_payload.get("exit_code"),
    )


def _error_card(
    *,
    card_type: str,
    error_code: str,
    message: str,
    recovery_hint: str | None,
    **extra: object,
) -> dict[str, object]:
    card = {
        "card_type": card_type,
        "error_code": error_code,
        "message": message,
        "recovery_hint": recovery_hint,
    }
    for key, value in extra.items():
        if value is not None:
            card[key] = value
    return card


def _selected_agent_effective(
    agent_id: str | None,
    *,
    forced: bool,
    source: str,
) -> dict[str, object] | None:
    if not agent_id:
        return None
    agent = _agent_by_id(agent_id)
    return {
        "id": agent_id,
        "name": agent.get("name") if agent else None,
        "provider": agent.get("provider") if agent else None,
        "forced": forced,
        "source": source,
    }


def _agent_by_id(agent_id: str) -> dict[str, object] | None:
    agents = get_agent_profiles_by_ids([agent_id])
    return agents[0] if agents else None


def _events_summary(conversation_id: str, *, test_run_id: str) -> dict[str, object]:
    events = list_conversation_events(conversation_id, test_run_id=test_run_id)
    counts: dict[str, int] = {}
    for event in events:
        event_type = str(event.get("type") or "")
        counts[event_type] = counts.get(event_type, 0) + 1
    return {
        "count": len(events),
        "last_sequence": events[-1]["sequence"] if events else None,
        "types": counts,
    }


def _preferred_agent_id_from_decision(decision: TurnDecision) -> str | None:
    if decision.target_agent_id:
        return decision.target_agent_id
    if decision.target_agent_ids:
        return decision.target_agent_ids[0]
    return None


def _object_payload(value: object) -> dict[str, object] | None:
    return dict(value) if isinstance(value, dict) else None


def _optional_card_text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _create_manual_task(conversation_id: str, body: dict[str, Any], test_run_id: str) -> dict[str, object]:
    goal = str(body.get("goal", "")).strip()
    if not goal:
        raise ValidationError("goal must be a non-empty string.")
    message = create_message(
        conversation_id=conversation_id,
        message_type="text",
        content={"text": goal, "source": "manual_task"},
        mentions=[],
        references=object_list(body.get("references", []), "references"),
        reply_to_id=None,
        test_run_id=test_run_id,
    )
    task = create_planned_task(
        conversation_id=conversation_id,
        message_id=str(message["id"]),
        goal=goal,
        steps=[
            PlanStepDraft(
                external_id="manual-step-1",
                kind="analysis",
                title="Manual task placeholder",
                instruction=goal,
                assigned_agent_id=None,
                status="blocked",
                dispatch_source="manual_task",
                dispatch_reason="Manual task execution requires the later worker queue phase.",
                blocked_reason="worker_queue_not_available",
                depends_on=[],
                expected_output={"kind": "manual_task"},
            )
        ],
        test_run_id=test_run_id,
    )
    task["created_message_id"] = message["id"]
    return task


def _is_legacy_mention_task_without_runs(task: dict[str, object]) -> bool:
    runs = task.get("runs")
    if runs not in (None, []):
        return False
    steps = task.get("steps")
    if not isinstance(steps, list) or not steps:
        return False
    return all(isinstance(step, dict) and step.get("dispatch_source") == "mention" for step in steps)


def _should_invoke_turn_router(body: dict[str, Any]) -> bool:
    return (
        "turn_decision" in body
        or body.get("turn_route") is True
        or body.get("orchestrate") is True
        or turn_router_backend_configured()
    )


def _turn_message_response(
    message: dict[str, object],
    body: dict[str, Any],
    test_run_id: str,
) -> TurnDecision | RouteResponse:
    raw_decision = body.get("turn_decision") if isinstance(body.get("turn_decision"), dict) else None
    conversation = get_conversation(str(message["conversation_id"]), test_run_id=test_run_id)
    try:
        return turn_gateway_from_environment(raw_decision).decide_for_message(
            message,
            conversation_mode=str(conversation["mode"]),
            private_agent_id=_private_agent_id(str(message["conversation_id"]), str(conversation["mode"]), test_run_id),
            auto_orchestrate=_bool_body_value(body.get("auto_orchestrate"), default=True),
            test_run_id=test_run_id,
        )
    except TurnRouterBackendError as exc:
        _record_turn_failure_events(
            message,
            code=exc.code,
            failure_message="Router output invalid." if exc.code == "turn_router_invalid_output" else str(exc),
            recovery_hint=exc.recovery_hint,
            source="turn_router",
            include_router_invalid=exc.code == "turn_router_invalid_output",
        )
        if exc.code == "turn_router_invalid_output":
            return _turn_error_response(
                exc.code,
                "Router output invalid.",
                exc.recovery_hint or "Retry after the turn router returns schema-compliant JSON.",
                status=_turn_error_status(exc.code),
                message_id=str(message["id"]),
            )
        return _turn_error_response(
            exc.code,
            str(exc),
            exc.recovery_hint,
            status=_turn_error_status(exc.code),
            message_id=str(message["id"]),
        )
    except TurnSchemaError as exc:
        _record_turn_failure_events(
            message,
            code=exc.code,
            failure_message="Router output invalid.",
            recovery_hint="Retry after the turn router returns schema-compliant JSON.",
            source="turn_router",
            include_router_invalid=True,
        )
        return _turn_error_response(
            exc.code,
            "Router output invalid.",
            "Retry after the turn router returns schema-compliant JSON.",
            status=_turn_error_status(exc.code),
            message_id=str(message["id"]),
        )


def _turn_error_response(
    code: str,
    message: str,
    recovery_hint: str | None,
    *,
    status: HTTPStatus = HTTPStatus.SERVICE_UNAVAILABLE,
    message_id: str | None = None,
) -> RouteResponse:
    payload: dict[str, object] = {
        "error": code,
        "code": code,
        "error_code": code,
        "message": message,
        "retryable": True,
        "error_card": {
            "card_type": "send_failure",
            "error_code": code,
            "message": message,
            "recovery_hint": recovery_hint,
        },
    }
    if message_id:
        payload["message_id"] = message_id
    if recovery_hint:
        payload["recovery_hint"] = recovery_hint
    return status, payload


def _turn_error_status(code: str) -> HTTPStatus:
    if code == "turn_router_invalid_output":
        return HTTPStatus.BAD_REQUEST
    return HTTPStatus.SERVICE_UNAVAILABLE


def _validate_mentions_for_response(mentions: list[dict[str, object]]) -> list[str] | RouteResponse:
    try:
        return validate_mention_agent_ids(mentions)
    except ValidationError as exc:
        code = getattr(exc, "code", "validation_error")
        if code not in {"unknown_agent", "agent_disabled"}:
            raise
        return (
            HTTPStatus.BAD_REQUEST,
            {
                "error": "validation_error",
                "code": code,
                "error_code": code,
                "message": str(exc),
            },
        )


def _private_agent_id(conversation_id: str, conversation_mode: str, test_run_id: str) -> str | None:
    if conversation_mode not in {"private", "private_agent", "single"}:
        return None
    for member in list_members(conversation_id, test_run_id=test_run_id):
        if member.get("member_type") == "agent":
            return str(member["member_id"])
    return None


def _bool_body_value(value: object, *, default: bool) -> bool:
    return value if isinstance(value, bool) else default


def _optional_int(value: str | None, field: str) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValidationError(f"{field} must be an integer.") from exc
    if parsed < 0:
        raise ValidationError(f"{field} must be non-negative.")
    return parsed


def _record_turn_decision_event(message: dict[str, object], decision: object, *, source: str) -> None:
    decision_type = getattr(decision, "decision_type", None)
    steps = getattr(decision, "steps", [])
    target_type = getattr(decision, "target_type", None)
    target_agent_id = getattr(decision, "target_agent_id", None)
    target_agent_ids = getattr(decision, "target_agent_ids", [])
    append_event(
        conversation_id=str(message["conversation_id"]),
        event_type="planner.decision_created",
        payload={
            "message_id": str(message["id"]),
            "source": source,
            "decision_type": decision_type,
            "goal": getattr(decision, "goal", None),
            "reason": getattr(decision, "reason", None),
            "confidence": getattr(decision, "confidence", None),
            "target_type": target_type,
            "target_agent_id": target_agent_id,
            "target_agent_ids": target_agent_ids if isinstance(target_agent_ids, list) else [],
            "step_count": len(steps) if isinstance(steps, list) else 0,
        },
    )


def _record_turn_failure_events(
    source_message: dict[str, object],
    *,
    code: str,
    failure_message: str,
    recovery_hint: str | None,
    source: str,
    include_router_invalid: bool = False,
) -> None:
    payload = {
        "message_id": str(source_message["id"]),
        "source": source,
        "error_code": code,
        "message": failure_message,
        "recovery_hint": recovery_hint,
        "retryable": True,
    }
    if include_router_invalid:
        append_event(
            conversation_id=str(source_message["conversation_id"]),
            event_type="router.output_invalid",
            payload=payload,
        )
    append_event(
        conversation_id=str(source_message["conversation_id"]),
        event_type="planner.decision_failed",
        payload=payload,
    )


def _direct_response_target_agent_id(
    decision: TurnDecision,
    message: dict[str, object],
    test_run_id: str,
) -> str | None:
    if decision.target_agent_id:
        return decision.target_agent_id
    if decision.target_agent_ids:
        return decision.target_agent_ids[0]
    conversation = get_conversation(str(message["conversation_id"]), test_run_id=test_run_id)
    private_agent_id = _private_agent_id(str(message["conversation_id"]), str(conversation["mode"]), test_run_id)
    if private_agent_id:
        return private_agent_id
    if decision.target_type == "orchestrator":
        return _default_model_agent_id()
    return None


def _message_requests_plan(message: dict[str, object]) -> bool:
    text = _message_goal(message)
    lower = text.lower()
    return any(
        marker in lower or marker in text
        for marker in (
            "plan",
            "steps",
            "step by step",
            "implement",
            "review",
            "拆成",
            "拆分",
            "步骤",
            "计划",
            "实现",
            "评审",
            "审查",
        )
    )


def _create_promoted_plan_task(message: dict[str, object], *, test_run_id: str) -> dict[str, object]:
    agents = list_agent_profiles(enabled=True)
    analysis_agent_id = _default_model_agent_id() or _agent_for_role(agents, role="analysis")
    implementation_agent_id = _agent_for_role(agents, role="implementation") or analysis_agent_id
    review_agent_id = _agent_for_role(agents, role="review") or analysis_agent_id
    goal = _message_goal(message)
    steps = [
        _promoted_plan_step(
            external_id="promoted-analysis",
            kind="analysis",
            title="Analyze the request",
            instruction=f"Analyze the user's request and identify the implementation work.\n\nUser request:\n{goal}",
            assigned_agent_id=analysis_agent_id,
            depends_on=[],
        ),
        _promoted_plan_step(
            external_id="promoted-implementation",
            kind="implementation",
            title="Implement the deliverable",
            instruction=f"Implement or draft the requested deliverable based on the analysis.\n\nUser request:\n{goal}",
            assigned_agent_id=implementation_agent_id,
            depends_on=["promoted-analysis"],
        ),
        _promoted_plan_step(
            external_id="promoted-review",
            kind="review",
            title="Review and polish",
            instruction=f"Review the result, polish formatting, and call out any delivery gaps.\n\nUser request:\n{goal}",
            assigned_agent_id=review_agent_id,
            depends_on=["promoted-implementation"],
        ),
    ]
    return create_planned_task(
        conversation_id=str(message["conversation_id"]),
        message_id=str(message["id"]),
        goal=goal,
        steps=steps,
        test_run_id=test_run_id,
    )


def _promoted_plan_step(
    *,
    external_id: str,
    kind: str,
    title: str,
    instruction: str,
    assigned_agent_id: str | None,
    depends_on: list[str],
) -> PlanStepDraft:
    return PlanStepDraft(
        external_id=external_id,
        kind=kind,
        title=title,
        instruction=instruction,
        assigned_agent_id=assigned_agent_id,
        status="assigned" if assigned_agent_id else "blocked",
        dispatch_source="router_promoted_plan",
        dispatch_reason=(
            f"router_promoted_plan:{assigned_agent_id}: user asked for a multi-step plan"
            if assigned_agent_id
            else "router_promoted_plan:unassigned: no matching Agent profile"
        ),
        blocked_reason=None if assigned_agent_id else "target_agent_unavailable",
        depends_on=depends_on,
        expected_output={
            "kind": kind,
            "title": title,
            "instruction": instruction,
            "assigned_agent_id": assigned_agent_id,
        },
    )


def _agent_for_role(agents: list[dict[str, object]], *, role: str) -> str | None:
    if role == "implementation":
        preferred_ids = ("agent-codex-profile",)
        preferred_providers = ("codex", "opencode")
        preferred_caps = ("implementation", "code", "workspace")
    elif role == "review":
        preferred_ids = ("agent-claude-profile",)
        preferred_providers = ("anthropic",)
        preferred_caps = ("review", "reasoning", "documents")
    else:
        preferred_ids = ("agent-demo-model",)
        preferred_providers = tuple(MODEL_AGENT_PROVIDERS)
        preferred_caps = ("analysis", "chat", "model", "direct_response")

    for agent_id in preferred_ids:
        match = next((agent for agent in agents if str(agent.get("id")) == agent_id), None)
        if match is not None and _profile_can_execute(match):
            return str(match["id"])
    for agent in agents:
        provider = str(agent.get("provider") or "").lower()
        if provider in preferred_providers and _profile_can_execute(agent):
            return str(agent["id"])
    for agent in agents:
        capabilities = {str(item).strip() for item in agent.get("capability_tags") or [] if str(item).strip()}
        if capabilities.intersection(preferred_caps) and _profile_can_execute(agent):
            return str(agent["id"])
    return None


def _profile_can_execute(agent: dict[str, object]) -> bool:
    return agent.get("enabled") is True and agent.get("configured") is True and agent.get("execution_enabled") is True


def _default_model_agent_id() -> str | None:
    candidates = [
        agent
        for agent in list_agent_profiles(enabled=True)
        if _is_default_model_agent_candidate(agent)
    ]
    if not candidates:
        return None
    candidates.sort(key=_default_model_agent_rank)
    agent_id = candidates[0].get("id")
    return str(agent_id) if isinstance(agent_id, str) and agent_id.strip() else None


def _is_default_model_agent_candidate(agent: dict[str, object]) -> bool:
    provider = str(agent.get("provider") or "").strip().lower()
    capabilities = {str(item).strip() for item in agent.get("capability_tags") or [] if str(item).strip()}
    return (
        provider in MODEL_AGENT_PROVIDERS
        and agent.get("configured") is True
        and agent.get("execution_enabled") is True
        and ("direct_response" in capabilities or "chat" in capabilities or "model" in capabilities)
    )


def _default_model_agent_rank(agent: dict[str, object]) -> tuple[int, str]:
    provider = str(agent.get("provider") or "").strip().lower()
    agent_id = str(agent.get("id") or "")
    if agent_id == "agent-demo-model":
        return (0, agent_id)
    if provider == "custom_openai":
        return (1, agent_id)
    return (2, agent_id)


def _message_goal(message: dict[str, object]) -> str:
    content = message.get("content")
    if isinstance(content, dict) and isinstance(content.get("text"), str):
        text = content["text"].strip()
        if text:
            return text
    return f"Orchestrator plan for message {message['id']}"


def _sequential_instruction(
    message: dict[str, object],
    prior_output: str | None,
    *,
    step_index: int,
    step_instruction: str | None = None,
) -> str | None:
    instruction = step_instruction.strip() if isinstance(step_instruction, str) and step_instruction.strip() else ""
    handoff_rule = (
        "Only perform your assigned part. Do not substitute for another Agent, do not invent missing upstream output, "
        "and do not continue with a placeholder. If your assigned part needs a prior Agent output that is absent or unusable, "
        "state that the handoff is blocked and name the missing input."
    )
    if step_index == 0 or not prior_output:
        if not instruction:
            return handoff_rule
        return f"{instruction}\n\n{handoff_rule}"
    base_instruction = instruction or _message_goal(message)
    return (
        f"{base_instruction}\n\n"
        "You are executing a sequential group chat step. "
        "Use the previous Agent output as the handoff context and continue with your own assigned part. "
        "Do not repeat the previous Agent's role unless it is needed for the answer. "
        f"{handoff_rule}\n\n"
        f"Previous Agent output:\n{prior_output}"
    )


def _message_text(message: dict[str, object]) -> str | None:
    content = message.get("content")
    if not isinstance(content, dict):
        return None
    text = content.get("text")
    if not isinstance(text, str):
        return None
    text = text.strip()
    return text or None
