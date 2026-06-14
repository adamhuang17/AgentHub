from tests.schema_assertions import assert_keys


def test_feishu_connector_contract(api_request):
    _, status, _ = api_request("GET", "/api/integrations/feishu/status", expected=200)
    assert_keys(status, ["provider", "configured", "capabilities"])
    assert status["provider"] in {"feishu", "lark"}
    for capability in ["message.send", "bot.card", "cloud_doc.range_patch"]:
        assert capability in status["capabilities"], status
    assert "credential_status" in status
    if status["configured"] is False:
        assert status["credential_status"] in {"missing", "provider_not_configured"}, status
