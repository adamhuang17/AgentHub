import os

from tests.support import assert_explicit_failure


def _assert_feishu_result(status, payload):
    if status in {200, 201, 202}:
        assert payload.get("provider") in {"feishu", "lark"}, payload
        assert payload.get("external_id") or payload.get("message_id") or payload.get("document_id"), payload
        return
    assert status in {400, 401, 403, 409, 424, 503}, payload
    assert payload.get("provider") in {"feishu", "lark"}, payload
    assert_explicit_failure(payload)


def test_a19_feishu_message_bot_card_and_cloud_doc_paths_are_real(api_request, unique_id):
    _, status_payload, _ = api_request("GET", "/api/integrations/feishu/status", expected=200)
    assert status_payload.get("provider") in {"feishu", "lark"}, status_payload
    capabilities = set(status_payload.get("capabilities", []))
    for capability in {"message.send", "bot.card", "cloud_doc.range_patch"}:
        assert capability in capabilities, status_payload

    chat_id = os.getenv("AGENTHUB_FEISHU_ACCEPTANCE_CHAT_ID", "oc_acceptance_not_configured")
    document_id = os.getenv("AGENTHUB_FEISHU_ACCEPTANCE_DOC_ID", "docx_acceptance_not_configured")

    status, message_payload, _ = api_request(
        "POST",
        "/api/integrations/feishu/messages",
        {
            "receive_id_type": "chat_id",
            "receive_id": chat_id,
            "msg_type": "text",
            "content": {"text": f"AgentHub acceptance message {unique_id}"},
            "idempotency_key": f"{unique_id}-feishu-message",
        },
        expected={200, 201, 202, 400, 401, 403, 409, 424, 503},
    )
    _assert_feishu_result(status, message_payload)

    status, card_payload, _ = api_request(
        "POST",
        "/api/integrations/feishu/cards",
        {
            "receive_id_type": "chat_id",
            "receive_id": chat_id,
            "template": "agenthub_task_status",
            "data": {"title": "AgentHub Acceptance", "status": "running", "task_id": unique_id},
            "idempotency_key": f"{unique_id}-feishu-card",
        },
        expected={200, 201, 202, 400, 401, 403, 409, 424, 503},
    )
    _assert_feishu_result(status, card_payload)

    status, doc_payload, _ = api_request(
        "POST",
        "/api/integrations/feishu/cloud-docs/range-patches",
        {
            "document_id": document_id,
            "range": {"kind": "heading", "heading": "AgentHub Acceptance"},
            "patch": {"operation": "replace_text", "text": f"Updated by AgentHub acceptance {unique_id}"},
            "idempotency_key": f"{unique_id}-feishu-doc",
        },
        expected={200, 201, 202, 400, 401, 403, 409, 424, 503},
    )
    _assert_feishu_result(status, doc_payload)
