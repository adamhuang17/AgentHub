import pytest

from services.api.app.deployment.schema import (
    DEFAULT_DEPLOYMENT_PROVIDER,
    deployment_release_to_response,
    validate_deploy_request,
    validate_deployment_release,
)
from services.api.app.shared.errors import ValidationError


def _release(**overrides):
    payload = {
        "id": "depl_schema",
        "artifact_id": "art_schema",
        "artifact_version_id": "artv_schema",
        "provider": "disabled",
        "status": "failed",
        "url": None,
        "error_code": "deployment_provider_not_configured",
        "created_at": "2026-06-12T00:00:00.000000Z",
        "published_at": None,
    }
    payload.update(overrides)
    return payload


def test_deployment_release_schema_freezes_a12_required_fields():
    release = validate_deployment_release(_release())
    response = deployment_release_to_response(release)

    assert response == {
        "id": "depl_schema",
        "artifact_id": "art_schema",
        "artifact_version_id": "artv_schema",
        "provider": "disabled",
        "status": "failed",
        "url": None,
        "error_code": "deployment_provider_not_configured",
        "created_at": "2026-06-12T00:00:00.000000Z",
        "published_at": None,
    }


def test_deploy_request_defaults_to_disabled_provider_without_fake_fallback():
    assert validate_deploy_request({})["provider"] == DEFAULT_DEPLOYMENT_PROVIDER
    assert validate_deploy_request({"provider": " vercel "})["provider"] == "vercel"


def test_deployment_release_rejects_failed_release_with_url():
    with pytest.raises(ValidationError) as exc_info:
        validate_deployment_release(_release(url="https://example.invalid/fake"))

    assert exc_info.value.code == "deployment_release_invalid"


def test_deployment_release_rejects_published_release_without_url():
    with pytest.raises(ValidationError) as exc_info:
        validate_deployment_release(
            _release(
                status="published",
                error_code=None,
                url=None,
                published_at="2026-06-12T00:01:00.000000Z",
            )
        )

    assert exc_info.value.code == "deployment_release_invalid"
