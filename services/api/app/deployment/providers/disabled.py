from __future__ import annotations

from services.api.app.deployment.providers.base import (
    DeploymentProviderRequest,
    DeploymentProviderResult,
)


class DisabledDeploymentProvider:
    def __init__(
        self,
        *,
        provider: str = "disabled",
        error_code: str = "deployment_provider_not_configured",
        message: str = "Deployment provider is not configured.",
        recovery_hint: str = "Configure a real deployment provider before publishing artifacts.",
    ) -> None:
        self.provider = provider
        self.error_code = error_code
        self.message = message
        self.recovery_hint = recovery_hint

    @classmethod
    def credentials_missing(cls, *, provider: str) -> "DisabledDeploymentProvider":
        return cls(
            provider=provider,
            error_code="deployment_credentials_missing",
            message="Deployment provider credentials are missing.",
            recovery_hint="Configure provider credentials before publishing artifacts.",
        )

    def deploy(self, request: DeploymentProviderRequest) -> DeploymentProviderResult:
        return DeploymentProviderResult(
            status="failed",
            url=None,
            error_code=self.error_code,
            message=self.message,
            recovery_hint=self.recovery_hint,
        )
