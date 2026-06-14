import pytest

from services.api.app.deployment.providers.base import (
    DeploymentProviderRequest,
    DeploymentProviderResult,
)
from services.api.app.deployment.providers.disabled import DisabledDeploymentProvider
from services.api.app.shared.errors import ValidationError


def _request(provider="vercel"):
    return DeploymentProviderRequest(
        release_id="depl_contract",
        artifact_id="art_contract",
        artifact_version_id="artv_contract",
        artifact_type="web_preview",
        title="Contract Web Preview",
        mime_type="text/html",
        provider=provider,
        test_run_id="contract",
    )


def test_disabled_provider_returns_not_configured_without_url():
    provider = DisabledDeploymentProvider(provider="vercel")
    result = provider.deploy(_request("vercel"))

    assert result.status == "failed"
    assert result.error_code == "deployment_provider_not_configured"
    assert result.url is None
    assert result.message
    assert result.recovery_hint


def test_provider_contract_can_report_missing_credentials_without_reading_secrets():
    provider = DisabledDeploymentProvider.credentials_missing(provider="vercel")
    result = provider.deploy(_request("vercel"))

    assert result.status == "failed"
    assert result.error_code == "deployment_credentials_missing"
    assert result.url is None


def test_provider_result_rejects_fake_success_without_url():
    with pytest.raises(ValidationError) as exc_info:
        DeploymentProviderResult(status="published", url=None, error_code=None)

    assert exc_info.value.code == "deployment_provider_invalid"


def test_provider_result_rejects_failure_with_url():
    with pytest.raises(ValidationError) as exc_info:
        DeploymentProviderResult(
            status="failed",
            url="https://example.invalid/fake",
            error_code="deployment_provider_not_configured",
        )

    assert exc_info.value.code == "deployment_provider_invalid"
