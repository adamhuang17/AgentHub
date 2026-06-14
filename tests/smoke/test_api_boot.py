def test_api_boot(api_request):
    _, payload, _ = api_request("GET", "/health", expected=200)
    assert payload.get("status") in {"ok", "healthy"}
    assert "version" in payload
