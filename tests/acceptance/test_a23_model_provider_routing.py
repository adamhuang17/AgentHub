from tests.support import assert_explicit_failure, item_list


def test_a23_mainstream_model_provider_registry_and_resolution(api_request, unique_id):
    _, providers_payload, _ = api_request("GET", "/api/model-providers", expected=200)
    providers = item_list(providers_payload)
    provider_ids = {provider.get("id") for provider in providers}
    for required in {"openai", "anthropic", "gemini", "openrouter", "ollama"}:
        assert required in provider_ids, providers

    for provider in providers:
        assert provider.get("id")
        assert provider.get("display_name")
        assert provider.get("api_format") in {"openai", "claude", "gemini", "ollama", "responses", "custom"}, provider
        assert "credential_status" in provider or "configured" in provider, provider
        assert isinstance(provider.get("models", []), list), provider

    _, resolved, _ = api_request(
        "POST",
        "/api/model-router/resolve",
        {
            "purpose": "agent_run",
            "requested_model": "default",
            "required_capabilities": ["chat", "tool_use"],
            "trace_id": f"{unique_id}-model-router",
        },
        expected=200,
    )
    assert resolved.get("provider") in provider_ids, resolved
    assert resolved.get("model"), resolved
    assert resolved.get("api_format") in {"openai", "claude", "gemini", "ollama", "responses", "custom"}, resolved
    assert resolved.get("credential_status") in {"configured", "provider_not_configured", "missing", "invalid"}, resolved
    if resolved.get("credential_status") != "configured":
        assert resolved.get("error_code") in {"provider_not_configured", "credential_missing", "credential_invalid"}, resolved

    status, unsupported, _ = api_request(
        "POST",
        "/api/model-router/resolve",
        {
            "purpose": "agent_run",
            "requested_model": "__agenthub_acceptance_unknown_model__",
            "trace_id": f"{unique_id}-unsupported-model",
        },
        expected={400, 404, 422},
    )
    assert status in {400, 404, 422}
    assert_explicit_failure(unsupported)
    assert unsupported.get("provider") != "openai" or unsupported.get("model") != "default"
