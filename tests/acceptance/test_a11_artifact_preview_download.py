import json
import os
from urllib import error, request

from services.api.app.artifacts.repository import append_artifact_version
from services.api.app.artifacts.store import artifact_store_root
from tests.support import API_BASE_URL, create_conversation, item_list


def _create_artifact(api_request, conversation_id, artifact_type, title, mime_type, content, extra=None):
    body = {
        "conversation_id": conversation_id,
        "type": artifact_type,
        "title": title,
        "mime_type": mime_type,
        "content": content,
    }
    if extra:
        body.update(extra)
    _, artifact, _ = api_request("POST", "/api/artifacts", body, expected={200, 201})
    return artifact


def _download_request(path, expected):
    req = request.Request(
        f"{API_BASE_URL}{path}",
        method="GET",
        headers={
            "Accept": "application/octet-stream, application/json",
            "X-AgentHub-Test-Run": os.getenv("AGENTHUB_TEST_RUN_ID", "local"),
        },
    )
    try:
        with request.urlopen(req, timeout=15) as resp:
            status = resp.status
            body = resp.read()
            headers = dict(resp.headers.items())
    except error.HTTPError as exc:
        status = exc.code
        body = exc.read()
        headers = dict(exc.headers.items())
    allowed = expected if isinstance(expected, (set, tuple, list)) else {expected}
    assert status in allowed, f"GET {path} returned {status}, expected {allowed}, body={body!r}"
    return status, body, headers


def _store_path(storage_key):
    return artifact_store_root().joinpath(*str(storage_key).split("/"))


def test_a11_artifact_detail_download_and_read_only_preview(api_request, unique_id):
    conversation = create_conversation(api_request, f"{unique_id} artifact preview")
    source = _create_artifact(
        api_request,
        conversation["id"],
        "source_file",
        "app.py",
        "text/x-python",
        "print('hello')\n",
    )

    _, detail, _ = api_request("GET", f"/api/artifacts/{source['id']}", expected=200)
    for field in ("current_version_id", "version", "checksum", "created_by_run_id", "type", "mime_type", "status"):
        assert field in detail
    assert detail["type"] == "source_file"
    assert detail["mime_type"] == "text/x-python"
    assert detail["status"] == "available"

    _, versions_payload, _ = api_request("GET", f"/api/artifacts/{source['id']}/versions", expected=200)
    versions = item_list(versions_payload)
    assert versions[0]["id"] == source["current_version_id"]
    assert versions[0]["checksum"] == source["checksum"]
    assert "parent_version_id" in versions[0]

    _, content, _ = api_request("GET", f"/api/artifacts/{source['id']}/content", expected=200)
    assert content["artifact_id"] == source["id"]
    assert content["version_id"] == source["current_version_id"]
    assert content["content"] == "print('hello')\n"
    assert content["checksum"] == source["checksum"]

    _, source_download, source_headers = _download_request(
        f"/api/artifacts/{source['id']}/download",
        expected=200,
    )
    assert source_download == b"print('hello')\n"
    assert source_headers["Content-Type"] == "text/x-python"
    assert "attachment;" in source_headers["Content-Disposition"]
    assert "app.py" in source_headers["Content-Disposition"]

    document = _create_artifact(
        api_request,
        conversation["id"],
        "document",
        "notes.md",
        "text/markdown",
        "# Notes\n\nPreview only.\n",
    )
    _, preview, _ = api_request("GET", f"/api/artifacts/{document['id']}/preview", expected=200)
    assert preview["preview_type"] == "text"
    assert preview["read_only"] is True
    assert preview["source"] == "artifact_store"
    assert preview["content"] == "# Notes\n\nPreview only.\n"
    assert "url" not in preview
    assert "external_url" not in preview
    assert preview["status"] != "published"

    _, document_download, document_headers = _download_request(
        f"/api/artifacts/{document['id']}/download",
        expected=200,
    )
    assert document_download == b"# Notes\n\nPreview only.\n"
    assert document_headers["Content-Type"] == "text/markdown"
    assert "notes.md" in document_headers["Content-Disposition"]

    target = _create_artifact(
        api_request,
        conversation["id"],
        "source_file",
        "app.py",
        "text/x-python",
        "print('hello world')\n",
    )
    _, diff, _ = api_request(
        "POST",
        "/api/artifacts/diff",
        {
            "base_artifact_id": source["id"],
            "base_version_id": source["current_version_id"],
            "target_artifact_id": target["id"],
            "target_version_id": target["current_version_id"],
            "path": "app.py",
            "type": "diff_preview",
        },
        expected={200, 201},
    )
    _, diff_preview, _ = api_request("POST", f"/api/artifacts/{diff['diff_artifact_id']}/preview", {}, expected=200)
    assert diff_preview["preview_type"] == "structured_diff"
    assert diff_preview["read_only"] is True
    assert diff_preview["base_artifact_id"] == source["id"]
    assert diff_preview["target_artifact_id"] == target["id"]
    assert diff_preview["files"][0]["path"] == "app.py"
    assert diff_preview["additions"] == 1
    assert diff_preview["deletions"] == 1
    assert "url" not in diff_preview
    assert "external_url" not in diff_preview

    binary = _create_artifact(
        api_request,
        conversation["id"],
        "binary_file",
        "blob.bin",
        "application/octet-stream",
        "abc\u0000def",
    )
    _, unsupported, _ = api_request("GET", f"/api/artifacts/{binary['id']}/preview", expected=400)
    assert unsupported["error_code"] == "artifact_preview_unsupported"

    _, binary_download, binary_headers = _download_request(
        f"/api/artifacts/{binary['id']}/download",
        expected=200,
    )
    assert binary_download == b"abc\x00def"
    assert binary_headers["Content-Type"] == "application/octet-stream"
    assert "blob.bin" in binary_headers["Content-Disposition"]

    _, artifacts_payload, _ = api_request("GET", f"/api/artifacts?conversation_id={conversation['id']}", expected=200)
    artifact_types = {artifact["type"] for artifact in item_list(artifacts_payload)}
    assert "deployment" not in artifact_types
    assert "deployment_release" not in artifact_types


def test_a11_version_specific_download_reads_selected_artifact_version(api_request, unique_id):
    conversation = create_conversation(api_request, f"{unique_id} artifact version lineage")
    source = _create_artifact(
        api_request,
        conversation["id"],
        "source_file",
        "hello.txt",
        "text/plain",
        "hello\n",
    )
    base_version_id = source["current_version_id"]
    append_artifact_version(
        source["id"],
        content="hello world\n",
        parent_version_id=base_version_id,
        test_run_id=os.getenv("AGENTHUB_TEST_RUN_ID", "local"),
    )

    _, versions_payload, _ = api_request("GET", f"/api/artifacts/{source['id']}/versions", expected=200)
    versions = item_list(versions_payload)
    assert len(versions) == 2
    assert versions[-1]["parent_version_id"] == base_version_id

    _, current_content, _ = api_request("GET", f"/api/artifacts/{source['id']}/content", expected=200)
    assert current_content["content"] == "hello world\n"

    _, version_one_download, version_one_headers = _download_request(
        f"/api/artifacts/{source['id']}/download?version=1",
        expected=200,
    )
    assert version_one_download == b"hello\n"
    assert version_one_headers["Content-Type"] == "text/plain"

    _, current_download, _ = _download_request(
        f"/api/artifacts/{source['id']}/download",
        expected=200,
    )
    assert current_download == b"hello world\n"


def test_a11_download_checksum_mismatch_returns_explicit_error_code(api_request, unique_id):
    conversation = create_conversation(api_request, f"{unique_id} artifact checksum download")
    source = _create_artifact(
        api_request,
        conversation["id"],
        "source_file",
        "tampered.py",
        "text/x-python",
        "print('before')\n",
    )

    _store_path(source["storage_key"]).write_bytes(b"print('after')\n")

    _, body, headers = _download_request(
        f"/api/artifacts/{source['id']}/download",
        expected=400,
    )
    assert headers["Content-Type"] == "application/json"
    payload = json.loads(body.decode("utf-8"))
    assert payload["error_code"] == "artifact_checksum_mismatch"
