from tests.support import create_conversation


def test_permission_policy_requires_review_for_high_risk_actions(api_request, unique_id):
    conversation = create_conversation(api_request, f"{unique_id} permission policy")
    _, payload, _ = api_request(
        "POST",
        "/api/review-requests/evaluate",
        {
            "conversation_id": conversation["id"],
            "action_type": "apply_patch",
            "risk_level": "write",
            "target": {"type": "artifact", "id": "contract-placeholder"},
        },
        expected=200,
    )
    assert payload.get("requires_review") is True
    assert payload.get("policy_id")
