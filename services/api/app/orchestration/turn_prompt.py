from __future__ import annotations

import json

from services.api.app.orchestration.turn_schema import STEP_KINDS, TURN_TYPES
from services.api.app.orchestration.turn_backends.base import TurnRequest


AVAILABLE_ARTIFACT_TYPES = [
    "document",
    "source_file",
    "binary_file",
    "web_preview",
    "web_app",
    "static_site",
    "diff_preview",
    "source_diff",
    "deployment_release",
    "patch",
    "diff_patch",
    "document_patch",
]


def turn_router_system_prompt() -> str:
    decision_types = ", ".join(sorted(TURN_TYPES))
    step_kinds = ", ".join(sorted(STEP_KINDS))
    return (
        "You are AgentHub Orchestrator.\n"
        "Return only one valid JSON object; no markdown or prose.\n"
        "Always include: decision_type,target_type,target_source,target_agent_id,target_agent_ids,goal,steps,reason,confidence,clarification_question.\n"
        f"decision_type must be one of: {decision_types}.\n"
        f"plan_task steps.kind must be one of: {step_kinds}.\n"
        "Use only agent IDs from enabled_agents; never invent IDs.\n"
        "Every plan_task step needs id, kind, title, instruction, required_capabilities, and depends_on.\n"
        "Use step-1, step-2, step-3 and dependencies in depends_on.\n"
        "For group turns that mention multiple Agents and contain a concrete request, always use plan_task. "
        "Role words such as 负责, 出题, 解答, 优化, solve, answer, optimize, review, or diff are enough input; "
        "do not return needs_clarification/direct_response/no_action for that case.\n"
        "Infer the semantic work order from the user's intent, not from the textual order of @mentions. "
        "Use one step per intended Agent action, assigned_agent_id set to the concrete mentioned Agent ID, "
        "target_agent_ids in execution order, and depends_on for handoffs.\n"
        "Use direct_response for simple one-Agent answers, plan_task for multi-step or artifact work, no_action for idle turns, "
        "and needs_clarification only when required input is missing.\n"
        "Never include an assistant answer. direct_response only selects target_type, target_source, and target_agent_id(s).\n"
        "Private chats target private_agent_id. Unmentioned group simple answers target orchestrator.\n"
        "Never include unsupported fields."
    )


def turn_router_user_payload(request: TurnRequest) -> str:
    payload = {
        "conversation_id": request.conversation_id,
        "message_id": request.message_id,
        "message_text": request.message_text,
        "sender": {
            "type": request.sender_type,
            "id": request.sender_id,
        },
        "conversation_mode": request.conversation_mode,
        "mentions": request.mentions,
        "recent_messages": request.recent_messages[-2:],
        "artifact_references": request.references,
        "enabled_agents": [_agent_context(agent) for agent in request.available_agents],
        "private_agent_id": request.private_agent_id,
        "auto_orchestrate": request.auto_orchestrate,
        "available_artifact_types": request.available_artifact_types,
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def turn_decision_json_schema() -> dict[str, object]:
    step_schema = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "id",
            "kind",
            "title",
            "instruction",
            "required_capabilities",
            "depends_on",
        ],
        "properties": {
            "id": {"type": "string", "minLength": 1},
            "kind": {"type": "string", "enum": sorted(STEP_KINDS)},
            "title": {"type": "string", "minLength": 1},
            "instruction": {"type": "string", "minLength": 1},
            "objective": {"type": "string", "minLength": 1},
            "assigned_agent_id": {"type": ["string", "null"]},
            "required_capabilities": {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
            },
            "depends_on": {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
            },
            "expected_output": {"type": "object"},
        },
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
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
        ],
        "properties": {
            "decision_type": {"type": "string", "enum": sorted(TURN_TYPES)},
            "target_type": {"type": "string", "enum": ["agent", "orchestrator", "none"]},
            "target_source": {
                "type": "string",
                "enum": ["private_chat", "mention", "auto_orchestrate", "none"],
            },
            "target_agent_id": {"type": ["string", "null"]},
            "target_agent_ids": {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
            },
            "goal": {"type": ["string", "null"]},
            "steps": {
                "type": "array",
                "minItems": 0,
                "maxItems": 3,
                "items": step_schema,
            },
            "reason": {"type": "string", "minLength": 1},
            "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
            "clarification_question": {"type": ["string", "null"]},
        },
    }


def _agent_context(agent: dict[str, object]) -> dict[str, object]:
    return {
        "id": agent.get("id"),
        "name": agent.get("name"),
        "provider": agent.get("provider"),
        "capability_tags": list(agent.get("capability_tags") or []),
        "enabled": agent.get("enabled"),
        "configured": agent.get("configured"),
        "execution_enabled": agent.get("execution_enabled"),
    }
