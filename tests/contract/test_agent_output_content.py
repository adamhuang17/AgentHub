import json

import services.api.app.agent_runs.service as agent_run_service
from services.api.app.agent_runs.content import split_agent_content
from services.api.app.agent_runs.repository import list_run_events
from services.api.app.agent_runs.schema import AgentRunEventDraft
from services.api.app.agents.adapter_health import adapter_health
from services.api.app.conversations.repository import create_conversation, create_message, list_messages
from services.api.app.shared.database import connect
from services.api.app.shared.time import utc_now


def _env(monkeypatch, tmp_path, name="agent-output-content"):
    monkeypatch.setenv("AGENTHUB_PROFILE", "test")
    monkeypatch.setenv("AGENTHUB_ENV", "test")
    monkeypatch.setenv("AGENTHUB_DB_PATH", str(tmp_path / f"{name}.sqlite3"))
    monkeypatch.setenv("AGENTHUB_MODEL_PROVIDER", "custom_openai")
    monkeypatch.setenv("AGENTHUB_CUSTOM_OPENAI_API_BASE", "https://model.example/v1")
    monkeypatch.setenv("AGENTHUB_CUSTOM_OPENAI_MODEL", "fixture-model")
    monkeypatch.setenv("AGENTHUB_CUSTOM_OPENAI_API_KEY", "fixture-key")


def _ready_demo_model():
    now = utc_now()
    with connect() as connection:
        connection.execute(
            """
            INSERT INTO agents (
                id, name, provider, avatar, initials, capability_tags_json,
                execution_enabled, configured, health_status,
                enabled, created_at, updated_at
            )
            VALUES (?, ?, 'custom_openai', NULL, 'AI', ?, 1, 1, 'ready', 1, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                execution_enabled = 1,
                configured = 1,
                health_status = 'ready',
                enabled = 1,
                updated_at = excluded.updated_at
            """,
            (
                "agent-demo-model",
                "Demo Model Agent",
                json.dumps(["direct_response", "chat", "model"], separators=(",", ":")),
                now,
                now,
            ),
        )


def _conversation_and_message(test_run_id, text):
    conversation = create_conversation(
        title=f"{test_run_id} conversation",
        mode="private_agent",
        agent_ids=["agent-demo-model"],
        test_run_id=test_run_id,
    )
    message = create_message(
        conversation_id=str(conversation["id"]),
        message_type="text",
        content={"text": text},
        mentions=[],
        references=[],
        reply_to_id=None,
        test_run_id=test_run_id,
    )
    return conversation, message


def _patch_registry(monkeypatch, content_text):
    class FakeAdapter:
        def invoke(self, request):
            del request
            return [
                AgentRunEventDraft(type="assistant_message_completed", payload={"content_text": content_text}),
                AgentRunEventDraft(type="run_succeeded", payload={"status": "succeeded"}),
            ]

        def cancel(self, run_id):
            return {"run_id": run_id, "cancel_requested": False}

    class FakeRegistry:
        def adapter_for_agent(self, agent):
            del agent
            return FakeAdapter()

        def health_for_agent(self, agent):
            return adapter_health(
                provider=str(agent["provider"]),
                adapter_kind="custom_openai",
                configured=True,
                status="ready",
                error_code=None,
                recovery_hint=None,
                capabilities=["direct_response"],
            )

    monkeypatch.setattr(agent_run_service, "AdapterRegistry", FakeRegistry)


def _run_payload(message, instruction):
    return {
        "source_type": "message",
        "source_message_id": message["id"],
        "target_agent_id": "agent-demo-model",
        "run_mode": "direct_response",
        "instruction": instruction,
        "context_bundle": {"recent_messages": [], "artifact_refs": []},
        "workspace_ref": None,
        "allowed_tools": [],
        "expected_artifacts": [],
    }


def test_split_agent_content_uses_tags_and_preserves_raw():
    raw = "<thinking>Let me think about candidates.</thinking>\n<final>Final problem statement.</final>"

    split = split_agent_content(raw)

    assert split.final_content == "Final problem statement."
    assert split.thinking_content == "Let me think about candidates."
    assert split.raw_content == raw


def test_split_agent_content_heuristically_moves_draft_blocks():
    raw = "Let me think about candidate problems.\n\n## Final Problem\nUse two pointers."

    split = split_agent_content(raw)

    assert split.final_content == "## Final Problem\nUse two pointers."
    assert "candidate problems" in split.thinking_content
    assert split.raw_content == raw


def test_incomplete_solution_never_succeeds_and_keeps_structured_content(monkeypatch, tmp_path):
    test_run_id = "agent-output-incomplete"
    _env(monkeypatch, tmp_path, test_run_id)
    _ready_demo_model()
    conversation, message = _conversation_and_message(
        test_run_id,
        "@AgentHub Coding Agent creates a math problem and a LeetCode medium problem; Demo Model Agent solves both.",
    )
    output = """<thinking>Maybe I should draft the LeetCode part first.
## LeetCode Solution
```python
class Solution:
    pass
```
Time Complexity: O(1)
Space Complexity: O(1)</thinking>
<final>
## Math Problem Solution
Final Answer: 42

The LeetCode explanation is omitted.
</final>"""
    _patch_registry(monkeypatch, output)

    run = agent_run_service.create_run_from_body(
        _run_payload(message, "Solve the math and LeetCode problems with complete final answers."),
        test_run_id=test_run_id,
    )

    assert run["status"] == "incomplete"
    assert run["error_code"] == "incomplete"
    assert run["assistant_message"]["content"]["final_content"].startswith("## Math Problem Solution")
    assert "Maybe I should" in run["assistant_message"]["content"]["thinking_content"]
    assert "## LeetCode Solution" in run["assistant_message"]["content"]["thinking_content"]
    assert run["assistant_message"]["content"]["raw_content"] == output
    events = list_run_events(str(run["id"]), test_run_id=test_run_id)
    assert "run_succeeded" not in [event["type"] for event in events]
    assert events[-1]["type"] == "run_failed"

    stored = [item for item in list_messages(str(conversation["id"]), test_run_id=test_run_id) if item["sender_type"] == "assistant"][0]
    assert stored["content"]["raw_content"] == output


def test_only_thinking_without_final_becomes_final_content_empty(monkeypatch, tmp_path):
    test_run_id = "agent-output-empty-final"
    _env(monkeypatch, tmp_path, test_run_id)
    _ready_demo_model()
    _, message = _conversation_and_message(test_run_id, "Give a concise answer.")
    output = "<thinking>Let me think. Maybe the answer is short.</thinking>"
    _patch_registry(monkeypatch, output)

    run = agent_run_service.create_run_from_body(
        _run_payload(message, "Give a concise answer."),
        test_run_id=test_run_id,
    )

    assert run["status"] == "final_content_empty"
    assert run["error_code"] == "final_content_empty"
    assert run["assistant_message"]["content"]["final_content"] == ""
    assert run["assistant_message"]["content"]["raw_content"] == output
    events = list_run_events(str(run["id"]), test_run_id=test_run_id)
    assert "run_succeeded" not in [event["type"] for event in events]
