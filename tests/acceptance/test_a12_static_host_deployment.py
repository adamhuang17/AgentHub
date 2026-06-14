import json
import os
from urllib import request

from services.api.app.artifacts.repository import append_artifact_version
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


def test_a12_static_host_deploys_current_artifact_version_and_serves_url(api_request, unique_id):
    conversation = create_conversation(api_request, f"{unique_id} static host deployment")
    first_content = "<!doctype html><h1>Old static host content</h1>"
    latest_content = f"<!doctype html><h1>{unique_id} Static Host Published</h1>"
    source = _create_artifact(
        api_request,
        conversation["id"],
        "web_preview",
        "index.html",
        "text/html",
        first_content,
    )
    latest_version = append_artifact_version(
        str(source["id"]),
        content=latest_content,
        parent_version_id=str(source["version_id"]),
        test_run_id=os.getenv("AGENTHUB_TEST_RUN_ID", "local"),
    )

    _, release, _ = api_request(
        "POST",
        f"/api/artifacts/{source['id']}/deploy",
        {"provider": "static_host"},
        expected=201,
    )

    assert release["provider"] == "static_host"
    assert release["status"] == "published"
    assert release["url"]
    assert release["error_code"] is None
    assert release["published_at"]
    assert release["artifact_version_id"] == latest_version["version_id"]

    with request.urlopen(request.Request(release["url"], method="GET"), timeout=15) as response:
        assert response.status == 200
        served = response.read().decode("utf-8")
    assert latest_content in served
    assert first_content not in served

    release_artifacts = _deployment_release_artifacts(api_request, conversation["id"])
    published_artifacts = [artifact for artifact in release_artifacts if artifact["status"] == "available"]
    assert published_artifacts
    _, release_artifact_content, _ = api_request(
        "GET",
        f"/api/artifacts/{published_artifacts[-1]['id']}/content",
        expected=200,
    )
    payload = json.loads(release_artifact_content["content"])
    assert payload["provider"] == "static_host"
    assert payload["url"] == release["url"]
    assert payload["status"] == "published"
    assert payload["source_artifact"]["id"] == source["id"]
    assert payload["source_version"]["id"] == latest_version["version_id"]
    assert payload["source_version"]["version"] == latest_version["version"]
    assert payload["source_version"]["checksum"] == latest_version["checksum"]
