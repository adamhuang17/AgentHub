from __future__ import annotations

import argparse
import json
import os
import uuid
from collections import Counter
from http import HTTPStatus
from typing import Any

from services.api.app.agent_runs.service import create_run_from_body
from services.api.app.artifacts.repository import create_artifact
from services.api.app.conversations.repository import list_conversation_events
from services.api.app.conversations.routes import handle_post
from services.api.app.demo.seed import CODEX_AGENT_ID, MODEL_AGENT_ID, ensure_demo_agents
from services.api.app.memory.context_builder import build_context_bundle
from services.api.app.memory.pinned_context import create_pin
from services.api.app.orchestration.repository import get_task
from services.api.app.shared.env_loader import load_environment
from services.api.app.shared.errors import ValidationError
from services.api.app.shared.settings import get_settings


def run_simulation(*, profile: str = "demo") -> dict[str, object]:
    load_environment(profile=profile)
    _ensure_router_for_simulation()
    settings = get_settings(profile=profile)
    seeded = ensure_demo_agents(settings)
    test_run_id = f"{settings.test_run_id}-simulation-{uuid.uuid4().hex[:8]}"
    report: dict[str, object] = {
        "profile": profile,
        "api_base_url": settings.api_base_url,
        "router_mode": _router_mode(),
        "model_provider_case": {},
        "codex_case": {},
        "blocked_case": {},
        "context_case": {},
        "event_counts": {},
        "warnings": [],
    }
    conversations: list[str] = []

    model_case = _model_provider_case(test_run_id=test_run_id)
    report["model_provider_case"] = model_case
    conversations.append(str(model_case["conversation_id"]))
    if not seeded["model"]["configured"]:
        report["warnings"].append("model_provider_not_configured")

    codex_case = _codex_case(test_run_id=test_run_id)
    report["codex_case"] = codex_case
    conversations.append(str(codex_case["conversation_id"]))
    if not seeded["codex"]["configured"]:
        report["warnings"].append("codex_cli_not_configured")

    blocked_case = _blocked_case(test_run_id=test_run_id)
    report["blocked_case"] = blocked_case
    conversations.append(str(blocked_case["conversation_id"]))

    context_case = _context_case(test_run_id=test_run_id)
    report["context_case"] = context_case
    conversations.append(str(context_case["conversation_id"]))

    report["event_counts"] = _event_counts(conversations, test_run_id=test_run_id)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the AgentHub pre-Lark local simulation.")
    parser.add_argument("--profile", choices=["demo", "test", "real"], default="demo")
    args = parser.parse_args()
    print(json.dumps(run_simulation(profile=args.profile), ensure_ascii=False, indent=2))


def _model_provider_case(*, test_run_id: str) -> dict[str, object]:
    conversation = _post(
        "/api/conversations",
        {"title": "Simulation A model provider direct response", "mode": "private_agent", "agent_ids": [MODEL_AGENT_ID]},
        test_run_id=test_run_id,
        expected=HTTPStatus.CREATED,
    )
    message = _post(
        f"/api/conversations/{conversation['id']}/messages",
        {
            "message_type": "text",
            "content": {"text": "请用一句话说明 AgentHub 当前模拟是否能创建真实 AgentRun。"},
            "turn_decision": _direct_response_decision(MODEL_AGENT_ID, reason="Simulation A direct response"),
        },
        test_run_id=test_run_id,
        expected=HTTPStatus.CREATED,
    )
    run = dict(message.get("agent_run") or {})
    return {
        "conversation_id": conversation["id"],
        "message_id": message["id"],
        "run_id": run.get("id") or message.get("run_id"),
        "status": run.get("status", "failed"),
        "error_code": run.get("error_code"),
    }


def _codex_case(*, test_run_id: str) -> dict[str, object]:
    conversation = _post(
        "/api/conversations",
        {"title": "Simulation B Codex complex task", "mode": "group_agent", "agent_ids": [CODEX_AGENT_ID]},
        test_run_id=test_run_id,
        expected=HTTPStatus.CREATED,
    )
    message = _post(
        f"/api/conversations/{conversation['id']}/messages",
        {
            "message_type": "text",
            "content": {"text": "请创建一个简单说明文档或分析一个小函数，并给出实现步骤。"},
            "turn_decision": _plan_task_decision(
                goal="Create a short implementation note or analyze a small function.",
                step_kind="implementation",
                required_capabilities=["implementation", "code"],
                reason="Simulation B Codex plan task",
            ),
            "content": {
                "text": "Create a short implementation note or analyze a small function, then give implementation steps."
            },
        },
        test_run_id=test_run_id,
        expected=HTTPStatus.CREATED,
    )
    if not message.get("task_id"):
        run = dict(message.get("agent_run") or {})
        return {
            "conversation_id": conversation["id"],
            "task_id": None,
            "step_id": None,
            "run_id": run.get("id") or message.get("run_id"),
            "status": run.get("status") or message.get("dispatch_path") or "failed",
            "error_code": run.get("error_code") or message.get("error_code"),
            "dispatch_path": message.get("dispatch_path"),
        }
    task = get_task(str(message["task_id"]), test_run_id=test_run_id)
    step = task["steps"][0]
    base = {
        "conversation_id": conversation["id"],
        "task_id": task["id"],
        "step_id": step["id"],
        "run_id": None,
        "status": step["status"],
        "error_code": step.get("blocked_reason"),
    }
    if step["status"] == "blocked":
        return base
    try:
        run = create_run_from_body(
            {
                "source_type": "plan_step",
                "plan_step_id": step["id"],
                "run_mode": "planned_step",
                "instruction": "Execute the simulation implementation step without modifying the workspace.",
                "workspace_ref": None,
                "allowed_tools": [],
                "expected_artifacts": [],
            },
            test_run_id=test_run_id,
        )
    except ValidationError as exc:
        return {**base, "status": "failed", "error_code": exc.code}
    return {**base, "run_id": run["id"], "status": run["status"], "error_code": run.get("error_code")}


def _blocked_case(*, test_run_id: str) -> dict[str, object]:
    conversation = _post(
        "/api/conversations",
        {"title": "Simulation C planned task assignment", "mode": "group_agent", "agent_ids": []},
        test_run_id=test_run_id,
        expected=HTTPStatus.CREATED,
    )
    message = _post(
        f"/api/conversations/{conversation['id']}/messages",
        {
            "message_type": "text",
            "content": {"text": "请执行一个本地没有能力标签的复杂任务。"},
            "turn_decision": _plan_task_decision(
                goal="Plan an AgentHub demo flow analysis without creating a fake run.",
                step_kind="analysis",
                required_capabilities=["reasoning"],
                reason="Simulation C planned task assignment",
            ),
            "content": {
                "text": "Please analyze the AgentHub demo flow and break it into analysis, implementation, and review steps."
            },
        },
        test_run_id=test_run_id,
        expected=HTTPStatus.CREATED,
    )
    if not message.get("task_id"):
        run = dict(message.get("agent_run") or {})
        return {
            "conversation_id": conversation["id"],
            "task_id": None,
            "step_id": None,
            "status": run.get("status") or message.get("dispatch_path") or "failed",
            "blocked_reason": message.get("error_code"),
            "run_created": bool(run),
            "dispatch_path": message.get("dispatch_path"),
        }
    task = get_task(str(message["task_id"]), test_run_id=test_run_id)
    step = task["steps"][0]
    return {
        "conversation_id": conversation["id"],
        "task_id": task["id"],
        "step_id": step["id"],
        "status": step["status"],
        "blocked_reason": step.get("blocked_reason"),
        "run_created": bool(task.get("runs")),
    }


def _context_case(*, test_run_id: str) -> dict[str, object]:
    conversation = _post(
        "/api/conversations",
        {"title": "Simulation D context and pin", "mode": "private_agent", "agent_ids": [MODEL_AGENT_ID]},
        test_run_id=test_run_id,
        expected=HTTPStatus.CREATED,
    )
    pinned_message = _post(
        f"/api/conversations/{conversation['id']}/messages",
        {"message_type": "text", "content": {"text": "Pinned simulation requirement: preserve real timeline events."}},
        test_run_id=test_run_id,
        expected=HTTPStatus.CREATED,
    )
    artifact = create_artifact(
        conversation_id=str(conversation["id"]),
        artifact_type="document",
        title="simulation-context.md",
        mime_type="text/markdown",
        content="# Simulation Context\n\nThis is a real local artifact for context pinning.",
        test_run_id=test_run_id,
    )
    create_pin(
        conversation_id=str(conversation["id"]),
        source_type="message",
        source_id=str(pinned_message["id"]),
        note="simulation message pin",
        test_run_id=test_run_id,
    )
    create_pin(
        conversation_id=str(conversation["id"]),
        source_type="artifact",
        source_id=str(artifact["id"]),
        note="simulation artifact pin",
        test_run_id=test_run_id,
    )
    context = build_context_bundle(str(conversation["id"]), test_run_id=test_run_id)
    message = _post(
        f"/api/conversations/{conversation['id']}/messages",
        {
            "message_type": "text",
            "content": {"text": "请基于 pinned context 做一次简短 direct response。"},
            "turn_decision": _direct_response_decision(MODEL_AGENT_ID, reason="Simulation D context direct response"),
        },
        test_run_id=test_run_id,
        expected=HTTPStatus.CREATED,
    )
    run = dict(message.get("agent_run") or {})
    summary = dict(run.get("context_summary") or {})
    return {
        "conversation_id": conversation["id"],
        "pinned_count": context["context_summary"]["pinned_count"],
        "artifact_ref_count": context["context_summary"]["artifact_ref_count"],
        "context_built": True,
        "run_id": run.get("id") or message.get("run_id"),
        "run_status": run.get("status"),
        "run_context_summary": summary,
    }


def _direct_response_decision(agent_id: str, *, reason: str) -> dict[str, object]:
    return {
        "decision_type": "direct_response",
        "target_type": "agent",
        "target_source": "private_chat",
        "target_agent_id": agent_id,
        "target_agent_ids": [agent_id],
        "goal": None,
        "steps": [],
        "reason": reason,
        "confidence": "high",
        "clarification_question": None,
    }


def _plan_task_decision(
    *,
    goal: str,
    step_kind: str,
    required_capabilities: list[str],
    reason: str,
) -> dict[str, object]:
    return {
        "decision_type": "plan_task",
        "target_type": "orchestrator",
        "target_source": "auto_orchestrate",
        "target_agent_id": None,
        "target_agent_ids": [],
        "goal": goal,
        "steps": [
            {
                "kind": step_kind,
                "objective": goal,
                "required_capabilities": required_capabilities,
                "depends_on": [],
                "expected_output": {"kind": step_kind},
            }
        ],
        "reason": reason,
        "confidence": "high",
        "clarification_question": None,
    }


def _post(path: str, body: dict[str, Any], *, test_run_id: str, expected: HTTPStatus) -> dict[str, object]:
    response = handle_post(path, body, test_run_id)
    if response is None:
        raise AssertionError(f"No route handled {path}")
    status, payload = response
    if status != expected:
        raise AssertionError(f"{path} returned {status}, expected {expected}, payload={payload}")
    return payload


def _event_counts(conversation_ids: list[str], *, test_run_id: str) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for conversation_id in conversation_ids:
        for event in list_conversation_events(conversation_id, test_run_id=test_run_id):
            counts[str(event["type"])] += 1
    return dict(sorted(counts.items()))


def _ensure_router_for_simulation() -> None:
    settings = get_settings()
    if settings.turn_router_configured():
        return
    os.environ["AGENTHUB_PROFILE"] = settings.env_profile
    os.environ["AGENTHUB_ENV"] = "test"
    os.environ["AGENTHUB_ENABLE_TEST_TURN_ROUTER_BACKEND"] = "1"
    os.environ["AGENTHUB_TURN_ROUTER_BACKEND"] = "test"


def _router_mode() -> str:
    settings = get_settings()
    if settings.turn_router_backend == "test":
        return "test"
    if settings.turn_router_backend in {"openai", "openai_compatible", "real"}:
        return "openai_compatible"
    return settings.turn_router_backend


if __name__ == "__main__":
    main()
