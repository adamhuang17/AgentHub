from __future__ import annotations

from dataclasses import dataclass


CAPABILITY_TAGS_BY_KIND = {
    "analysis": ("analysis", "reasoning", "research", "planning", "document", "documents", "model", "chat", "direct_response"),
    "implementation": ("implementation", "code", "workspace", "frontend", "backend"),
    "review": ("review", "code", "workspace", "test", "qa", "security"),
    "deploy": ("deploy", "deployment", "release", "static_host", "workspace"),
}
READY_HEALTH_STATUSES = {"configured", "healthy", "ready"}


@dataclass(frozen=True)
class CapabilityMatch:
    assigned_agent_id: str | None
    blocked_reason: str | None
    dispatch_source: str
    dispatch_reason: str
    matched_tags: list[str]

    def to_dict(self) -> dict[str, object]:
        return {
            "assigned_agent_id": self.assigned_agent_id,
            "blocked_reason": self.blocked_reason,
            "dispatch_source": self.dispatch_source,
            "dispatch_reason": self.dispatch_reason,
            "matched_tags": self.matched_tags,
        }


def match_capability(
    step_kind: str,
    agents: list[dict[str, object]],
    *,
    required_capabilities: list[str] | None = None,
    preferred_agent_id: str | None = None,
) -> CapabilityMatch:
    enabled_agents = sorted(
        [agent for agent in agents if agent.get("enabled") is True],
        key=lambda agent: str(agent["id"]),
    )
    mapped_tags = CAPABILITY_TAGS_BY_KIND.get(step_kind, (step_kind,))
    required_tags = list(required_capabilities or [])
    exact = _matching_agents(step_kind, enabled_agents, [step_kind])
    required = _matching_agents(step_kind, enabled_agents, required_tags) if required_tags else []
    candidates = exact or required or _matching_agents(step_kind, enabled_agents, mapped_tags)
    if not candidates:
        return _blocked_no_capability_match(step_kind, required_tags, mapped_tags)

    executable = sorted(
        [(agent, matched_tags) for agent, matched_tags in candidates if _is_executable(agent)],
        key=lambda item: _agent_kind_rank(step_kind, item[0]),
    )
    if not executable:
        return _blocked_non_executable(step_kind, candidates[0])

    preferred = _preferred_executable(executable, preferred_agent_id)
    agent, matched_tags = preferred or executable[0]
    source = "explicit_agent" if preferred is not None else "capability"
    return CapabilityMatch(
        assigned_agent_id=str(agent["id"]),
        blocked_reason=None,
        dispatch_source=source,
        dispatch_reason=(
            f"{source}:{agent['id']}: matched step kind {step_kind} using capability tags {','.join(matched_tags)}; "
            f"execution_enabled={_bool_text(agent.get('execution_enabled'))}; "
            f"configured={_bool_text(agent.get('configured'))}; "
            f"health_status={agent.get('health_status')}; "
            "ready_for_execution=true"
        ),
        matched_tags=matched_tags,
    )


def _matching_agents(
    step_kind: str,
    agents: list[dict[str, object]],
    allowed_tags: tuple[str, ...] | list[str],
) -> list[tuple[dict[str, object], list[str]]]:
    del step_kind
    allowed = set(allowed_tags)
    matches: list[tuple[dict[str, object], list[str]]] = []
    for agent in agents:
        tags = [str(tag) for tag in agent.get("capability_tags", [])]
        matched = [tag for tag in tags if tag in allowed]
        if matched:
            matches.append((agent, matched))
    return matches


def _preferred_executable(
    executable: list[tuple[dict[str, object], list[str]]],
    preferred_agent_id: str | None,
) -> tuple[dict[str, object], list[str]] | None:
    if not preferred_agent_id:
        return None
    for agent, matched_tags in executable:
        if agent.get("id") == preferred_agent_id:
            return agent, matched_tags
    return None


def _agent_kind_rank(step_kind: str, agent: dict[str, object]) -> tuple[int, str]:
    provider = str(agent.get("provider") or "").strip().lower()
    agent_id = str(agent.get("id") or "")
    provider_rankings = {
        "analysis": {"anthropic": 0, "custom_openai": 1, "openai": 1, "codex": 2},
        "implementation": {"codex": 0, "anthropic": 1, "custom_openai": 2, "openai": 2},
        "review": {"codex": 0, "anthropic": 1, "custom_openai": 2, "openai": 2},
        "deploy": {"opencode": 0, "codex": 1, "anthropic": 2},
    }
    agent_id_rankings = {
        "implementation": {"agent-codex-profile": 0, "agent-claude-profile": 1, "agent-demo-model": 2},
        "review": {"agent-codex-profile": 0, "agent-claude-profile": 1, "agent-demo-model": 2},
        "analysis": {"agent-claude-profile": 0, "agent-demo-model": 1, "agent-codex-profile": 2},
        "deploy": {"demo_seed-opencode-profile": 0, "agent-codex-profile": 1},
    }
    id_rank = agent_id_rankings.get(step_kind, {}).get(agent_id)
    if id_rank is not None:
        return (id_rank, agent_id)
    return (provider_rankings.get(step_kind, {}).get(provider, 50), agent_id)


def _bool_text(value: object) -> str:
    return "true" if bool(value) else "false"


def _is_executable(agent: dict[str, object]) -> bool:
    return (
        agent.get("enabled") is True
        and agent.get("configured") is True
        and agent.get("execution_enabled") is True
        and str(agent.get("health_status")) in READY_HEALTH_STATUSES
    )


def _blocked_non_executable(
    step_kind: str,
    candidate: tuple[dict[str, object], list[str]],
) -> CapabilityMatch:
    agent, matched_tags = candidate
    reason = _blocked_reason_for_agent(agent)
    return CapabilityMatch(
        assigned_agent_id=None,
        blocked_reason=reason,
        dispatch_source="blocked",
        dispatch_reason=(
            f"blocked:{reason}: matched agent {agent['id']} for step kind {step_kind} "
            f"using capability tags {','.join(matched_tags)} but agent is not executable; "
            f"execution_enabled={_bool_text(agent.get('execution_enabled'))}; "
            f"configured={_bool_text(agent.get('configured'))}; "
            f"health_status={agent.get('health_status')}"
        ),
        matched_tags=matched_tags,
    )


def _blocked_reason_for_agent(agent: dict[str, object]) -> str:
    if agent.get("configured") is not True:
        return "agent_not_configured"
    if agent.get("execution_enabled") is not True:
        return "agent_execution_disabled"
    if str(agent.get("health_status")) not in READY_HEALTH_STATUSES:
        return "agent_unavailable"
    return "no_capability_match"


def _blocked_no_capability_match(
    step_kind: str,
    required_tags: list[str],
    mapped_tags: tuple[str, ...],
) -> CapabilityMatch:
    candidate_tags = ",".join(dict.fromkeys([step_kind, *required_tags, *mapped_tags]))
    return CapabilityMatch(
        assigned_agent_id=None,
        blocked_reason="no_capability_match",
        dispatch_source="blocked",
        dispatch_reason=(
            f"blocked:no_capability_match: no enabled executable agent matched step kind {step_kind} "
            f"using capability tags {candidate_tags}"
        ),
        matched_tags=[],
    )
