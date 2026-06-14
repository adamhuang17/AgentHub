from tests.schema_assertions import assert_keys


def test_sse_event_stream_contract(api_request):
    _, schema, _ = api_request("GET", "/api/schemas/execution-event-stream", expected=200)
    assert_keys(schema, ["endpoint", "content_type", "event_required", "cursor"])
    assert schema["content_type"] == "text/event-stream"
    assert "{conversation_id}" in schema["endpoint"]
    for key in ["id", "conversation_id", "type", "sequence", "payload", "created_at"]:
        assert key in schema["event_required"], schema
    assert schema["cursor"].get("field") == "sequence", schema
    assert schema["cursor"].get("query_param") == "after", schema
