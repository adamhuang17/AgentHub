from tests.schema_assertions import assert_keys, assert_list


def test_message_card_schema(api_request):
    _, schema, _ = api_request("GET", "/api/schemas/message-card", expected=200)
    assert_keys(schema, ["supported_types", "required_fields"])
    supported = schema["supported_types"]
    assert_list(supported, "supported_types")
    for card_type in ["code_block", "file_card", "image_card", "webpage_card", "diff_card", "deployment_card"]:
        assert card_type in supported, schema
        assert card_type in schema["required_fields"], schema
