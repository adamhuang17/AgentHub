from services.api.app.shared.database import connect
from services.api.app.shared.time import utc_now
from tests.support import (
    assert_no_run_succeeded,
    conversation_messages,
    create_conversation,
    enabled_agents,
    item_list,
    post_message,
)


def _create_unsupported_enabled_agent(unique_id):
    agent_id = f"unsupported-{unique_id}"
    now = utc_now()
    with connect() as connection:
        connection.execute(
            """
            INSERT INTO agents (
                id, name, provider, avatar, initials, capability_tags_json,
                execution_enabled, configured, health_status,
                enabled, created_at, updated_at
            )
            VALUES (?, ?, 'unsupported-provider', NULL, 'UP', '["code"]', 1, 1, 'configured', 1, ?, ?)
            """,
            (agent_id, f"{unique_id} Unsupported Provider", now, now),
        )
    return agent_id


def _run_events(api_request, run_id):
    _, payload, _ = api_request("GET", f"/api/runs/{run_id}/events", expected=200)
    return item_list(payload)


def test_get_adapters_returns_readiness_summary(api_request):
    _, payload, _ = api_request("GET", "/api/adapters", expected=200)
    items = item_list(payload)

    assert items
    statuses = {item["status"] for item in items}
    assert "not_configured" in statuses
    assert all("provider" in item for item in items)
    assert all("adapter_kind" in item for item in items)
    assert all("configured" in item for item in items)
    assert all("checked_at" in item for item in items)
    assert all(isinstance(item.get("capabilities"), list) for item in items)
    assert all(item["status"] != "ready" for item in items)


def test_agent_adapter_health_returns_not_configured_for_profile_only_agent(api_request):
    agent = enabled_agents(api_request, minimum=1)[0]

    _, health, _ = api_request("GET", f"/api/agents/{agent['id']}/adapter-health", expected=200)

    assert health["provider"] == agent["provider"]
    assert health["configured"] is False
    assert health["status"] == "not_configured"
    assert health["error_code"] == "provider_not_configured"
    assert health["recovery_hint"]
    assert health["capabilities"] == []


def test_agent_adapter_health_returns_unsupported_provider(api_request, unique_id):
    agent_id = _create_unsupported_enabled_agent(unique_id)

    _, health, _ = api_request("GET", f"/api/agents/{agent_id}/adapter-health", expected=200)

    assert health["provider"] == "unsupported-provider"
    assert health["configured"] is False
    assert health["status"] == "unsupported_provider"
    assert health["error_code"] == "unsupported_provider"
    assert health["recovery_hint"]


def test_run_provider_not_configured_matches_adapter_health(api_request, unique_id):
    agent = enabled_agents(api_request, minimum=1)[0]
    conversation = create_conversation(api_request, f"{unique_id} adapter readiness")
    message = post_message(api_request, conversation["id"], "Run readiness must match adapter health.")

    _, health, _ = api_request("GET", f"/api/agents/{agent['id']}/adapter-health", expected=200)
    assert health["configured"] is False

    _, run, _ = api_request(
        "POST",
        "/api/runs",
        {
            "source_type": "message",
            "source_message_id": message["id"],
            "target_agent_id": agent["id"],
            "run_mode": "direct_response",
            "instruction": "Contract check for readiness failure.",
            "context_bundle": {},
            "workspace_ref": None,
            "allowed_tools": [],
            "expected_artifacts": [],
        },
        expected=201,
    )
    events = _run_events(api_request, run["id"])
    event_types = [event["type"] for event in events]

    assert run["status"] == "failed"
    assert run["error_code"] == "provider_not_configured"
    assert "provider_not_configured" in event_types
    assert "run_failed" in event_types
    assert "run_succeeded" not in event_types
    assert_no_run_succeeded(run)
    assert_no_run_succeeded(events)
    assert len(conversation_messages(api_request, conversation["id"])) == 1
