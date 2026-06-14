from tests.support import create_conversation, enabled_agents, item_list, wait_task


def test_a17_multi_agent_same_file_conflict_creates_reviewable_artifact(api_request, unique_id):
    agents = enabled_agents(api_request, minimum=2)[:2]
    conversation = create_conversation(
        api_request,
        f"{unique_id} conflict handling",
        agent_ids=[agent["id"] for agent in agents],
    )
    _, source, _ = api_request(
        "POST",
        "/api/artifacts",
        {
            "conversation_id": conversation["id"],
            "type": "source_code",
            "title": "conflict-source",
            "mime_type": "application/vnd.agenthub.source+json",
            "content": {"files": {"src/app.py": "VALUE = 'base'\n"}},
        },
        expected={200, 201},
    )
    base_version = source.get("current_version_id") or source.get("version")

    _, task, _ = api_request(
        "POST",
        f"/api/conversations/{conversation['id']}/tasks",
        {
            "goal": "Run two agents in parallel. Both must edit src/app.py differently so conflict handling is exercised.",
            "artifact_id": source["id"],
            "parallel_steps": [
                {"agent_id": agents[0]["id"], "path": "src/app.py", "change": "VALUE = 'agent-a'"},
                {"agent_id": agents[1]["id"], "path": "src/app.py", "change": "VALUE = 'agent-b'"},
            ],
        },
        expected={200, 201, 202},
    )
    task_id = task.get("id") or task.get("task_id")
    final = wait_task(
        api_request,
        task_id,
        terminal=("succeeded", "failed", "blocked", "waiting_review"),
        timeout=180,
    )
    assert final.get("status") in {"blocked", "waiting_review", "failed"}, final

    _, latest_source, _ = api_request("GET", f"/api/artifacts/{source['id']}", expected=200)
    latest_version = latest_source.get("current_version_id") or latest_source.get("version")
    assert latest_version == base_version, "Conflicting agent writes must not mutate the main artifact version"

    _, conflicts_payload, _ = api_request(
        "GET",
        f"/api/conflicts?conversation_id={conversation['id']}&artifact_id={source['id']}",
        expected=200,
    )
    conflicts = item_list(conflicts_payload)
    assert conflicts, conflicts_payload
    conflict = conflicts[0]
    assert conflict.get("target_artifact_id") == source["id"]
    assert set(conflict.get("agent_ids", [])) >= {agents[0]["id"], agents[1]["id"]}
    assert conflict.get("status") in {"open", "waiting_review", "needs_resolution"}
