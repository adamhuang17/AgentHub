from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from services.api.app.deployment.schema import DEPLOYMENT_RELEASE_STATUSES
from services.api.app.shared.errors import ValidationError


@dataclass(frozen=True)
class DeploymentProviderRequest:
    release_id: str
    artifact_id: str
    artifact_version_id: str
    artifact_type: str
    title: str
    mime_type: str
    provider: str
    test_run_id: str
    artifact_version: int = 1
    storage_key: str = ""
    checksum: str = ""


@dataclass(frozen=True)
class DeploymentProviderResult:
    status: str
    url: str | None
    error_code: str | None
    message: str | None = None
    recovery_hint: str | None = None

    def __post_init__(self) -> None:
        if self.status not in DEPLOYMENT_RELEASE_STATUSES:
            raise ValidationError("Unsupported deployment provider result status.", code="deployment_provider_invalid")
        if self.status == "published":
            if not self.url:
                raise ValidationError("Published deployment provider result must include a URL.", code="deployment_provider_invalid")
            if self.error_code is not None:
                raise ValidationError(
                    "Published deployment provider result must not include an error code.",
                    code="deployment_provider_invalid",
                )
            return
        if self.status == "failed":
            if self.url is not None:
                raise ValidationError("Failed deployment provider result must not include a URL.", code="deployment_provider_invalid")
            if not self.error_code:
                raise ValidationError(
                    "Failed deployment provider result must include an error code.",
                    code="deployment_provider_invalid",
                )


class DeploymentProvider(Protocol):
    provider: str

    def deploy(self, request: DeploymentProviderRequest) -> DeploymentProviderResult:
        """Deploy a persisted artifact version through a configured provider."""
