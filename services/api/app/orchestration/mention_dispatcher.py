from __future__ import annotations

from services.api.app.agents.repository import get_agent_profiles_by_ids
from services.api.app.orchestration.models import MentionDispatch
from services.api.app.orchestration.repository import create_mention_task
from services.api.app.shared.errors import ValidationError


EXPLICIT_MENTION_REASON = "explicit_mention: assigned from persisted message.mentions; mentioned agent selected"


def validate_mention_agent_ids(mentions: list[object]) -> list[str]:
    if not mentions:
        return []
    if not isinstance(mentions, list):
        raise ValidationError("message.mentions must be a list.")

    agent_ids = _mentioned_agent_ids(mentions)
    agents = get_agent_profiles_by_ids(agent_ids)
    known_agents = {str(agent["id"]): agent for agent in agents}

    missing = [agent_id for agent_id in agent_ids if agent_id not in known_agents]
    if missing:
        raise ValidationError(f"Unknown mentioned agent ids: {missing}", code="unknown_agent")

    disabled = [agent_id for agent_id in agent_ids if not known_agents[agent_id].get("enabled")]
    if disabled:
        raise ValidationError(f"Disabled mentioned agent ids: {disabled}", code="agent_disabled")

    return agent_ids


def dispatch_mentions_for_message(
    message: dict[str, object],
    *,
    test_run_id: str,
    agent_ids: list[str] | None = None,
) -> MentionDispatch | None:
    mentions = message.get("mentions") or []
    if not mentions:
        return None

    if agent_ids is None:
        agent_ids = validate_mention_agent_ids(mentions)

    dispatch_reasons = {agent_id: EXPLICIT_MENTION_REASON for agent_id in agent_ids}
    task = create_mention_task(
        conversation_id=str(message["conversation_id"]),
        message_id=str(message["id"]),
        goal=_message_goal(message),
        agent_ids=agent_ids,
        dispatch_reasons=dispatch_reasons,
        test_run_id=test_run_id,
    )
    plan = task.get("plan") or {}
    steps = plan.get("steps") if isinstance(plan, dict) else []
    return MentionDispatch(
        task_id=str(task["id"]),
        plan_id=str(plan["id"]),
        step_ids=[str(step["id"]) for step in steps],
    )


def _mentioned_agent_ids(mentions: list[object]) -> list[str]:
    agent_ids: list[str] = []
    for mention in mentions:
        if not isinstance(mention, dict):
            raise ValidationError("message.mentions must contain objects.")
        agent_id = mention.get("agent_id")
        if not isinstance(agent_id, str) or not agent_id:
            raise ValidationError("Each mention must include a non-empty agent_id.")
        if agent_id not in agent_ids:
            agent_ids.append(agent_id)
    return agent_ids


def _message_goal(message: dict[str, object]) -> str:
    content = message.get("content")
    if isinstance(content, dict) and isinstance(content.get("text"), str):
        text = content["text"].strip()
        if text:
            return text
    return f"Mention dispatch for message {message['id']}"
