from tests.support import create_conversation, item_list, post_message


def test_a3_conversation_list_ui_contract(api_request, unique_id):
    older = create_conversation(api_request, f"{unique_id} older searchable")
    newer = create_conversation(api_request, f"{unique_id} newer searchable")
    post_message(api_request, older["id"], f"{unique_id} bumps older to top")

    _, payload, _ = api_request("GET", "/api/conversations", expected=200)
    conversations = item_list(payload)
    ordered_ids = [item["id"] for item in conversations]
    assert ordered_ids.index(older["id"]) < ordered_ids.index(newer["id"])

    _, search_payload, _ = api_request("GET", f"/api/conversations?q={unique_id}%20older", expected=200)
    search_ids = {item["id"] for item in item_list(search_payload)}
    assert older["id"] in search_ids
    assert newer["id"] not in search_ids

    api_request("POST", f"/api/conversations/{older['id']}/archive", {}, expected={200, 202})
    _, active_payload, _ = api_request("GET", "/api/conversations?include_archived=false", expected=200)
    active_ids = {item["id"] for item in item_list(active_payload)}
    assert older["id"] not in active_ids

    _, archived_payload, _ = api_request("GET", "/api/conversations?archived=true", expected=200)
    archived_ids = {item["id"] for item in item_list(archived_payload)}
    assert older["id"] in archived_ids
