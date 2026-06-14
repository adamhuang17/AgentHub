from tests.schema_assertions import assert_keys


def test_task_intervention_schema(api_request):
    _, schema, _ = api_request("GET", "/api/schemas/task-intervention", expected=200)
    assert_keys(schema, ["required", "kinds", "states", "apply_modes"])
    for key in ["id", "task_id", "kind", "content", "apply_at", "state", "created_at"]:
        assert key in schema["required"], schema
    for kind in ["supplemental_context", "correction", "constraint", "user_answer"]:
        assert kind in schema["kinds"], schema
    for state in ["queued", "waiting_interrupt_point", "waiting_user_context", "applied", "rejected"]:
        assert state in schema["states"], schema
    assert "next_interrupt_point" in schema["apply_modes"], schema
