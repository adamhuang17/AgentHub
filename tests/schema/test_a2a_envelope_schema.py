from tests.schema_assertions import assert_keys


def test_a2a_envelope_schema(api_request):
    _, schema, _ = api_request("GET", "/api/schemas/a2a-envelope", expected=200)
    assert_keys(schema, ["required", "message_types", "delivery_states"])
    for key in [
        "id",
        "conversation_id",
        "from_agent_id",
        "to_agent_id",
        "message_type",
        "correlation_id",
        "payload",
        "created_at",
    ]:
        assert key in schema["required"], schema
    for message_type in ["delegation", "review_request", "result", "question", "handoff"]:
        assert message_type in schema["message_types"], schema
    for state in ["queued", "delivered", "read", "failed"]:
        assert state in schema["delivery_states"], schema
