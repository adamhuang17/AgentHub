import pytest

from tests.support import create_conversation, post_message, task_from_message, wait_artifacts, wait_task


@pytest.mark.xfail(
    reason="Future A9.5/A10 patch artifact flow; A9 is sealed by test_a9_diff_artifact_preview.py.",
    strict=False,
)
def test_a9_diff_artifact_flow(api_request, unique_id):
    conversation = create_conversation(api_request, f"{unique_id} diff flow")
    _, source, _ = api_request(
        "POST",
        "/api/artifacts",
        {
            "conversation_id": conversation["id"],
            "type": "source_file",
            "title": "calculator.py",
            "mime_type": "text/x-python",
            "content": "def add(a, b):\n    return a + b\n",
        },
        expected={200, 201},
    )
    base_version = source.get("current_version_id") or source.get("version")

    message = post_message(
        api_request,
        conversation["id"],
        "Change calculator.py so add validates numeric input. Produce a diff artifact and do not apply it yet.",
        references=[{"target_type": "artifact", "target_id": source["id"], "version": base_version}],
    )
    wait_task(api_request, task_from_message(message))

    patches = wait_artifacts(api_request, conversation["id"], artifact_type="patch", minimum=1)
    related = [patch for patch in patches if patch.get("target_artifact_id") == source["id"]]
    assert related, f"Expected patch artifact targeting source {source['id']}: {patches}"
    assert related[0].get("base_version_id") == base_version

    _, current_source, _ = api_request("GET", f"/api/artifacts/{source['id']}", expected=200)
    current_version = current_source.get("current_version_id") or current_source.get("version")
    assert current_version == base_version, "Main source artifact must not change before patch apply"
