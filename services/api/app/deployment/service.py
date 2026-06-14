from __future__ import annotations

import json

from services.api.app.artifacts.repository import (
    create_deployment_release_artifact,
    get_artifact,
    get_current_artifact_version_record,
)
from services.api.app.deployment.providers.base import (
    DeploymentProvider,
    DeploymentProviderRequest,
    DeploymentProviderResult,
)
from services.api.app.deployment.providers.disabled import DisabledDeploymentProvider
from services.api.app.deployment.providers.static_host import StaticHostDeploymentProvider
from services.api.app.deployment.repository import (
    create_deployment_release,
    get_deployment_release,
    list_deployment_releases,
    update_deployment_release,
)
from services.api.app.deployment.schema import (
    DEPLOYABLE_ARTIFACT_TYPES,
    validate_deploy_request,
)


def deploy_artifact(artifact_id: str, raw: dict[str, object], *, test_run_id: str) -> dict[str, object]:
    request = validate_deploy_request(raw)
    source = get_artifact(artifact_id, test_run_id=test_run_id)
    version = get_current_artifact_version_record(artifact_id, test_run_id=test_run_id)
    provider_name = str(request["provider"])
    release = create_deployment_release(
        artifact_id=artifact_id,
        artifact_version_id=str(version["version_id"]),
        provider=provider_name,
        test_run_id=test_run_id,
    )

    if str(source["type"]) not in DEPLOYABLE_ARTIFACT_TYPES:
        return _fail_release(
            release,
            source=source,
            error_code="deployment_artifact_unsupported",
            test_run_id=test_run_id,
        )

    release = update_deployment_release(
        str(release["id"]),
        status="publishing",
        url=None,
        error_code=None,
        test_run_id=test_run_id,
    )
    provider = _provider_for(provider_name)
    result = provider.deploy(
        DeploymentProviderRequest(
            release_id=str(release["id"]),
            artifact_id=artifact_id,
            artifact_version_id=str(version["version_id"]),
            artifact_version=int(version["version"]),
            storage_key=str(version["storage_key"]),
            checksum=str(version["checksum"]),
            artifact_type=str(source["type"]),
            title=str(source["title"]),
            mime_type=str(source["mime_type"]),
            provider=provider_name,
            test_run_id=test_run_id,
        )
    )
    return _apply_provider_result(
        release,
        source=source,
        source_version=version,
        result=result,
        test_run_id=test_run_id,
    )


def get_release(release_id: str, *, test_run_id: str) -> dict[str, object]:
    return get_deployment_release(release_id, test_run_id=test_run_id)


def list_releases(
    *,
    test_run_id: str,
    conversation_id: str | None = None,
    artifact_id: str | None = None,
) -> list[dict[str, object]]:
    return list_deployment_releases(
        test_run_id=test_run_id,
        conversation_id=conversation_id,
        artifact_id=artifact_id,
    )


def _provider_for(provider_name: str) -> DeploymentProvider:
    if provider_name == "static_host":
        return StaticHostDeploymentProvider()
    return DisabledDeploymentProvider(provider=provider_name)


def _apply_provider_result(
    release: dict[str, object],
    *,
    source: dict[str, object],
    source_version: dict[str, object],
    result: DeploymentProviderResult,
    test_run_id: str,
) -> dict[str, object]:
    if result.status == "published":
        published = update_deployment_release(
            str(release["id"]),
            status="published",
            url=result.url,
            error_code=None,
            test_run_id=test_run_id,
        )
        _write_release_artifact(
            published,
            source=source,
            source_version=source_version,
            artifact_status="available",
            test_run_id=test_run_id,
        )
        return published
    error_code = result.error_code or "deployment_provider_failed"
    return _fail_release(
        release,
        source=source,
        source_version=source_version,
        error_code=error_code,
        test_run_id=test_run_id,
    )


def _fail_release(
    release: dict[str, object],
    *,
    source: dict[str, object],
    source_version: dict[str, object] | None = None,
    error_code: str,
    test_run_id: str,
) -> dict[str, object]:
    failed = update_deployment_release(
        str(release["id"]),
        status="failed",
        url=None,
        error_code=error_code,
        test_run_id=test_run_id,
    )
    _write_release_artifact(
        failed,
        source=source,
        source_version=source_version,
        artifact_status="failed",
        test_run_id=test_run_id,
    )
    return failed


def _write_release_artifact(
    release: dict[str, object],
    *,
    source: dict[str, object],
    source_version: dict[str, object] | None,
    artifact_status: str,
    test_run_id: str,
) -> dict[str, object]:
    content = json.dumps(
        {
            "release": release,
            "provider": release["provider"],
            "url": release["url"],
            "status": release["status"],
            "error_code": release["error_code"],
            "source_artifact": {
                "id": source["id"],
                "type": source["type"],
                "title": source["title"],
                "mime_type": source["mime_type"],
            },
            "source_version": _source_version_payload(source, source_version),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return create_deployment_release_artifact(
        conversation_id=str(source["conversation_id"]),
        title=f"Deployment release {release['id']}",
        content=content,
        status=artifact_status,
        test_run_id=test_run_id,
    )


def _source_version_payload(
    source: dict[str, object],
    source_version: dict[str, object] | None,
) -> dict[str, object]:
    if source_version is not None:
        return {
            "id": source_version["version_id"],
            "version": source_version["version"],
            "checksum": source_version["checksum"],
        }
    return {
        "id": source.get("version_id") or source.get("current_version_id"),
        "version": source.get("version"),
        "checksum": source.get("checksum"),
    }
