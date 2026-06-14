from tests.support import create_conversation, item_list


def test_a1_conversation_persistence(api_request, unique_id):
    conversation = create_conversation(api_request, f"{unique_id} conversation persistence")
    conversation_id = conversation["id"]

    _, fetched, _ = api_request("GET", f"/api/conversations/{conversation_id}", expected=200)
    assert fetched["id"] == conversation_id
    assert fetched["title"] == conversation["title"]
    assert fetched["mode"] == conversation["mode"]
    assert fetched.get("last_active_at")

    _, listing, _ = api_request("GET", "/api/conversations", expected=200)
    ids = {item["id"] for item in item_list(listing)}
    assert conversation_id in ids
