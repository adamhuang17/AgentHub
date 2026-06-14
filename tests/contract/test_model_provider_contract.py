from tests.support import item_list


def test_model_provider_contract(api_request):
    _, payload, _ = api_request("GET", "/api/model-providers", expected=200)
    providers = item_list(payload)
    assert providers, payload
    for provider in providers:
        assert provider.get("id"), provider
        assert provider.get("display_name"), provider
        assert provider.get("api_format"), provider
        assert "configured" in provider or "credential_status" in provider, provider
        assert isinstance(provider.get("models", []), list), provider
        if provider.get("id") in {"openai", "anthropic", "gemini", "ollama"}:
            assert provider.get("api_format") in {"openai", "claude", "gemini", "ollama", "responses"}, provider
