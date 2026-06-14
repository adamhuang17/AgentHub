from tests.support import create_conversation, item_list


def _create_artifact(api_request, conversation_id, artifact_type, title, mime_type, content):
    _, artifact, _ = api_request(
        "POST",
        "/api/artifacts",
        {
            "conversation_id": conversation_id,
            "type": artifact_type,
            "title": title,
            "mime_type": mime_type,
            "content": content,
        },
        expected={200, 201},
    )
    return artifact


def _deployment_release_artifacts(api_request, conversation_id):
    _, payload, _ = api_request(
        "GET",
        f"/api/artifacts?conversation_id={conversation_id}&type=deployment_release",
        expected=200,
    )
    return item_list(payload)


def _assert_failed_release(payload, *, error_code):
    assert set(payload) == {
        "id",
        "artifact_id",
        "artifact_version_id",
        "provider",
        "status",
        "url",
        "error_code",
        "created_at",
        "published_at",
    }
    assert payload["id"]
    assert payload["artifact_id"]
    assert payload["artifact_version_id"]
    assert payload["status"] == "failed"
    assert payload["error_code"] == error_code
    assert payload["url"] is None
    assert payload["published_at"] is None


def test_a12_deploy_supported_artifact_fails_when_provider_not_configured(api_request, unique_id):
    conversation = create_conversation(api_request, f"{unique_id} deployment provider disabled")
    source = _create_artifact(
        api_request,
        conversation["id"],
        "web_preview",
        "index.html",
        "text/html",
        "<!doctype html><h1>A12</h1>",
    )

    _, release, _ = api_request(
        "POST",
        f"/api/artifacts/{source['id']}/deploy",
        {"provider": "vercel"},
        expected=201,
    )

    _assert_failed_release(release, error_code="deployment_provider_not_configured")
    _, fetched, _ = api_request("GET", f"/api/deployments/{release['id']}", expected=200)
    assert fetched == release
    _, source_after, _ = api_request("GET", f"/api/artifacts/{source['id']}", expected=200)
    assert source_after["status"] == "available"

    release_artifacts = _deployment_release_artifacts(api_request, conversation["id"])
    assert release_artifacts
    assert {artifact["status"] for artifact in release_artifacts} == {"failed"}
    assert all(artifact["type"] == "deployment_release" for artifact in release_artifacts)


def test_a12_deploy_unsupported_artifact_fails_without_fake_url(api_request, unique_id):
    conversation = create_conversation(api_request, f"{unique_id} deployment unsupported")
    source = _create_artifact(
        api_request,
        conversation["id"],
        "document",
        "notes.md",
        "text/markdown",
        "# Notes\n\nDocuments are not deployable in A12-0.\n",
    )

    _, release, _ = api_request(
        "POST",
        f"/api/artifacts/{source['id']}/deploy",
        {"provider": "vercel"},
        expected=201,
    )

    _assert_failed_release(release, error_code="deployment_artifact_unsupported")
    assert not release.get("url")
    release_artifacts = _deployment_release_artifacts(api_request, conversation["id"])
    assert release_artifacts
    assert {artifact["status"] for artifact in release_artifacts} == {"failed"}


def test_a12_public_artifact_api_cannot_forge_deployment_release(api_request, unique_id):
    conversation = create_conversation(api_request, f"{unique_id} deployment release forge")

    _, payload, _ = api_request(
        "POST",
        "/api/artifacts",
        {
            "conversation_id": conversation["id"],
            "type": "deployment_release",
            "title": "fake release",
            "mime_type": "application/json",
            "content": "{}",
        },
        expected=400,
    )

    assert payload["error_code"] == "artifact_type_not_supported"
    assert _deployment_release_artifacts(api_request, conversation["id"]) == []
