from tests.support import (
    assert_explicit_failure,
    assert_real_url,
    create_conversation,
    item_list,
    post_message,
    task_from_message,
    wait_deployment,
    wait_task,
    wait_until,
)


def test_a11_deployment_release_flow(api_request, unique_id):
    conversation = create_conversation(api_request, f"{unique_id} deployment release")
    _, artifact, _ = api_request(
        "POST",
        "/api/artifacts",
        {
            "conversation_id": conversation["id"],
            "type": "web_preview",
            "title": "acceptance-web-release",
            "mime_type": "application/vnd.agenthub.web",
            "content": {
                "files": {
                    "index.html": "<!doctype html><html><body><h1>AgentHub Acceptance</h1></body></html>"
                }
            },
        },
        expected={200, 201},
    )

    message = post_message(
        api_request,
        conversation["id"],
        f"部署 artifact {artifact['id']} 到默认生产环境。部署完成后在聊天流里生成部署卡片。",
        references=[{"type": "artifact", "artifact_id": artifact["id"]}],
    )
    task = wait_task(api_request, task_from_message(message), terminal=("succeeded", "failed"), timeout=180)

    def probe():
        _, payload, _ = api_request(
            "GET",
            f"/api/deployments?conversation_id={conversation['id']}&artifact_id={artifact['id']}",
            expected=200,
        )
        releases = item_list(payload)
        return releases if releases else None

    releases = wait_until(probe, timeout=120, label="deployment release created from chat")
    release = releases[0]
    release_id = release.get("id") or release.get("deployment_id")
    assert release_id, release

    _, messages_payload, _ = api_request("GET", f"/api/conversations/{conversation['id']}/messages", expected=200)
    messages = item_list(messages_payload)
    deployment_cards = [
        msg
        for msg in messages
        if msg.get("message_type") in {"deployment_card", "card"}
        and (
            msg.get("content", {}).get("release_id") == release_id
            or msg.get("content", {}).get("deployment_id") == release_id
        )
    ]
    assert deployment_cards, f"Chat-triggered deployment must create a deployment card. task={task}, messages={messages}"

    final = wait_deployment(api_request, release_id, timeout=180)
    if final["status"] == "published":
        assert final.get("url")
        assert_real_url(final["url"])
    else:
        assert final.get("provider")
        assert_explicit_failure(final)
        assert not final.get("url"), "Failed deployment must not expose a fake URL"
