from services.api.app.artifacts.store import write_content
from services.api.app.deployment.providers.base import DeploymentProviderRequest
from services.api.app.deployment.providers.static_host import StaticHostDeploymentProvider


def _request(**overrides):
    payload = {
        "release_id": "depl_static_contract",
        "artifact_id": "art_static_contract",
        "artifact_version_id": "artv_static_contract",
        "artifact_version": 1,
        "storage_key": "contract/conversation/artifact/v1.bin",
        "checksum": "sha256:missing",
        "artifact_type": "web_preview",
        "title": "index.html",
        "mime_type": "text/html",
        "provider": "static_host",
        "test_run_id": "contract",
    }
    payload.update(overrides)
    return DeploymentProviderRequest(**payload)


def test_static_host_provider_publishes_artifact_store_bytes(monkeypatch, tmp_path):
    store_dir = tmp_path / "store"
    deploy_dir = tmp_path / "deploy"
    monkeypatch.setenv("AGENTHUB_ARTIFACT_STORE_DIR", str(store_dir))
    monkeypatch.setenv("AGENTHUB_STATIC_DEPLOY_DIR", str(deploy_dir))
    monkeypatch.setenv("AGENTHUB_PUBLIC_BASE_URL", "http://127.0.0.1:19099")
    storage_key = "contract/conversation/artifact/v1.bin"
    content = b"<!doctype html><h1>Static Host</h1>"
    checksum = write_content(storage_key, content)

    result = StaticHostDeploymentProvider().deploy(_request(storage_key=storage_key, checksum=checksum))

    assert result.status == "published"
    assert result.error_code is None
    assert result.url == "http://127.0.0.1:19099/static-deployments/depl_static_contract/index.html"
    assert (deploy_dir / "depl_static_contract" / "index.html").read_bytes() == content


def test_static_host_provider_fails_when_static_dir_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENTHUB_ARTIFACT_STORE_DIR", str(tmp_path / "store"))
    monkeypatch.delenv("AGENTHUB_STATIC_DEPLOY_DIR", raising=False)

    result = StaticHostDeploymentProvider().deploy(_request())

    assert result.status == "failed"
    assert result.error_code == "deployment_provider_not_configured"
    assert result.url is None


def test_static_host_provider_rejects_unsupported_artifact(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENTHUB_STATIC_DEPLOY_DIR", str(tmp_path / "deploy"))

    result = StaticHostDeploymentProvider().deploy(_request(artifact_type="document"))

    assert result.status == "failed"
    assert result.error_code == "deployment_artifact_unsupported"
    assert result.url is None


def test_static_host_provider_maps_checksum_mismatch(monkeypatch, tmp_path):
    store_dir = tmp_path / "store"
    monkeypatch.setenv("AGENTHUB_ARTIFACT_STORE_DIR", str(store_dir))
    monkeypatch.setenv("AGENTHUB_STATIC_DEPLOY_DIR", str(tmp_path / "deploy"))
    storage_key = "contract/conversation/artifact/v1.bin"
    write_content(storage_key, "<!doctype html><h1>Original</h1>")

    result = StaticHostDeploymentProvider().deploy(_request(storage_key=storage_key, checksum="sha256:not-matching"))

    assert result.status == "failed"
    assert result.error_code == "deployment_artifact_checksum_mismatch"
    assert result.url is None


def test_static_host_provider_maps_write_failure(monkeypatch, tmp_path):
    store_dir = tmp_path / "store"
    deploy_file = tmp_path / "deploy-file"
    deploy_file.write_text("not a directory", encoding="utf-8")
    monkeypatch.setenv("AGENTHUB_ARTIFACT_STORE_DIR", str(store_dir))
    monkeypatch.setenv("AGENTHUB_STATIC_DEPLOY_DIR", str(deploy_file))
    storage_key = "contract/conversation/artifact/v1.bin"
    checksum = write_content(storage_key, "<!doctype html><h1>Write Failure</h1>")

    result = StaticHostDeploymentProvider().deploy(_request(storage_key=storage_key, checksum=checksum))

    assert result.status == "failed"
    assert result.error_code == "deployment_publish_failed"
    assert result.url is None
