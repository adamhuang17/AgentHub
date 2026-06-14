from services.api.app.orchestration.capability_matcher import match_capability


def _agent(agent_id, tags, enabled=True, execution_enabled=True, configured=True, health_status="ready"):
    return {
        "id": agent_id,
        "enabled": enabled,
        "capability_tags": tags,
        "execution_enabled": execution_enabled,
        "configured": configured,
        "health_status": health_status,
    }


def test_exact_step_kind_tag_wins_before_mapped_tags():
    result = match_capability(
        "implementation",
        [
            _agent("agent-b", ["code"]),
            _agent("agent-a", ["implementation"]),
        ],
    )
    assert result.assigned_agent_id == "agent-a"
    assert result.dispatch_source == "capability"
    assert result.matched_tags == ["implementation"]


def test_mapped_tag_match_is_stably_sorted_by_agent_id():
    result = match_capability(
        "implementation",
        [
            _agent("agent-z", ["code"]),
            _agent("agent-a", ["backend"]),
        ],
    )
    assert result.assigned_agent_id == "agent-a"
    assert "ready_for_execution=true" in result.dispatch_reason


def test_structured_required_capability_is_used_without_message_text():
    result = match_capability(
        "analysis",
        [
            _agent("agent-doc", ["document"]),
            _agent("agent-code", ["workspace"]),
        ],
        required_capabilities=["workspace"],
    )
    assert result.assigned_agent_id == "agent-code"
    assert result.matched_tags == ["workspace"]


def test_implementation_prefers_codex_profile_over_claude_when_both_match():
    result = match_capability(
        "implementation",
        [
            _agent("agent-claude-profile", ["code"]),
            _agent("agent-codex-profile", ["code"]),
        ],
    )

    assert result.assigned_agent_id == "agent-codex-profile"


def test_analysis_prefers_claude_profile_over_codex_when_both_match():
    result = match_capability(
        "analysis",
        [
            _agent("agent-codex-profile", ["reasoning"]),
            _agent("agent-claude-profile", ["reasoning"]),
        ],
    )

    assert result.assigned_agent_id == "agent-claude-profile"


def test_disabled_agents_are_ignored_and_unmatched_steps_are_blocked():
    result = match_capability("analysis", [_agent("agent-disabled", ["analysis"], enabled=False)])
    assert result.assigned_agent_id is None
    assert result.blocked_reason == "no_capability_match"
    assert result.dispatch_source == "blocked"
    assert result.dispatch_reason.startswith("blocked:no_capability_match:")


def test_configured_false_is_not_dispatched():
    result = match_capability("implementation", [_agent("agent-code", ["code"], configured=False)])

    assert result.assigned_agent_id is None
    assert result.blocked_reason == "agent_not_configured"
    assert result.dispatch_source == "blocked"
    assert "configured=false" in result.dispatch_reason


def test_execution_disabled_is_not_dispatched():
    result = match_capability("implementation", [_agent("agent-code", ["code"], execution_enabled=False)])

    assert result.assigned_agent_id is None
    assert result.blocked_reason == "agent_execution_disabled"
    assert result.dispatch_source == "blocked"
    assert "execution_enabled=false" in result.dispatch_reason


def test_profile_only_health_is_not_dispatched():
    result = match_capability("implementation", [_agent("agent-code", ["code"], health_status="profile_only")])

    assert result.assigned_agent_id is None
    assert result.blocked_reason == "agent_unavailable"
    assert result.dispatch_source == "blocked"
    assert "health_status=profile_only" in result.dispatch_reason


def test_executable_matching_agent_is_assigned():
    result = match_capability("implementation", [_agent("agent-code", ["code"], health_status="configured")])

    assert result.assigned_agent_id == "agent-code"
    assert result.blocked_reason is None
    assert result.dispatch_source == "capability"
    assert "ready_for_execution=true" in result.dispatch_reason
