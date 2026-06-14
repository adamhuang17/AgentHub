from __future__ import annotations

import mimetypes
import re
import socket
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

from services.api.app.artifacts.store import checksum_bytes, read_content
from services.api.app.deployment.providers.base import (
    DeploymentProviderRequest,
    DeploymentProviderResult,
)
from services.api.app.deployment.schema import DEPLOYABLE_ARTIFACT_TYPES
from services.api.app.shared.errors import ValidationError
from services.api.app.shared.settings import get_settings


_FILENAME_SANITIZE_RE = re.compile(r"[\x00-\x1f\x7f<>:\"/\\|?*]+")


class StaticHostDeploymentProvider:
    provider = "static_host"

    def deploy(self, request: DeploymentProviderRequest) -> DeploymentProviderResult:
        if request.artifact_type not in DEPLOYABLE_ARTIFACT_TYPES:
            return _failed(
                "deployment_artifact_unsupported",
                message="Artifact type is not supported by the static host provider.",
                recovery_hint="Deploy a web_preview, web_app, or static_site artifact.",
            )

        deploy_root = _configured_deploy_root()
        if deploy_root is None:
            return _failed(
                "deployment_provider_not_configured",
                message="Static deployment directory is not configured.",
                recovery_hint="Set AGENTHUB_STATIC_DEPLOY_DIR to a writable directory outside the workspace.",
            )

        try:
            raw = read_content(request.storage_key, expected_checksum=request.checksum)
        except ValidationError as exc:
            if getattr(exc, "code", None) == "artifact_checksum_mismatch":
                return _failed(
                    "deployment_artifact_checksum_mismatch",
                    message="Source artifact checksum did not match the stored ArtifactVersion.",
                    recovery_hint="Create a new artifact version and retry the deployment.",
                )
            return _failed(
                "deployment_publish_failed",
                message="Source artifact content could not be read from Artifact Store.",
                recovery_hint="Verify the artifact content exists and retry the deployment.",
            )

        filename = _deployment_filename(request.title, request.mime_type, request.artifact_type)
        try:
            target = _target_path(deploy_root, request.release_id, filename)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
            if checksum_bytes(target.read_bytes()) != request.checksum:
                return _failed(
                    "deployment_artifact_checksum_mismatch",
                    message="Published bytes did not match the source ArtifactVersion checksum.",
                    recovery_hint="Retry the deployment from the same artifact version.",
                )
        except OSError:
            return _failed(
                "deployment_publish_failed",
                message="Static deployment files could not be written.",
                recovery_hint="Verify AGENTHUB_STATIC_DEPLOY_DIR is writable and retry the deployment.",
            )

        url = _deployment_url(request.release_id, filename)
        if not _url_accessible(url) and not _local_static_route_verified(url, target):
            return _failed(
                "deployment_failed",
                message="Static deployment URL was not reachable after publishing files.",
                recovery_hint="Check AGENTHUB_PUBLIC_BASE_URL and the API server static deployment route.",
            )

        return DeploymentProviderResult(
            status="published",
            url=url,
            error_code=None,
        )


def _failed(error_code: str, *, message: str, recovery_hint: str) -> DeploymentProviderResult:
    return DeploymentProviderResult(
        status="failed",
        url=None,
        error_code=error_code,
        message=message,
        recovery_hint=recovery_hint,
    )


def _configured_deploy_root() -> Path | None:
    configured = get_settings().static_deploy_dir
    if configured is None:
        return None
    root = configured.expanduser().resolve()
    if _is_inside_workspace(root):
        return None
    return root


def _is_inside_workspace(path: Path) -> bool:
    workspace = Path.cwd().resolve()
    try:
        path.relative_to(workspace)
    except ValueError:
        return False
    return True


def _target_path(root: Path, release_id: str, filename: str) -> Path:
    release_segment = _safe_segment(release_id)
    target = (root / release_segment / filename).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise OSError("Static deployment target escapes deploy root.") from exc
    return target


def _deployment_filename(title: str, mime_type: str, artifact_type: str) -> str:
    candidate = title.strip().replace("\\", "/").rsplit("/", 1)[-1]
    candidate = _FILENAME_SANITIZE_RE.sub("_", candidate).strip(" .")
    suffix = Path(candidate).suffix
    if candidate and suffix:
        return candidate
    if mime_type == "text/html" or artifact_type in {"web_preview", "web_app", "static_site"}:
        return "index.html"
    guessed = mimetypes.guess_extension(mime_type) or ".bin"
    stem = candidate or "artifact"
    return f"{stem}{guessed}"


def _deployment_url(release_id: str, filename: str) -> str:
    settings = get_settings()
    base_url = settings.public_base_url
    if not base_url:
        host = settings.host
        if host in {"0.0.0.0", "::"}:
            host = "127.0.0.1"
        port = str(settings.port)
        base_url = f"http://{host}:{port}"
    return (
        f"{base_url.rstrip('/')}/static-deployments/"
        f"{quote(_safe_segment(release_id), safe='')}/{quote(filename, safe='')}"
    )


def _url_accessible(url: str) -> bool:
    request = urllib.request.Request(url, method="GET", headers={"Accept": "*/*"})
    for _ in range(5):
        try:
            with urllib.request.urlopen(request, timeout=3) as response:
                return 200 <= int(response.status) < 300
        except (urllib.error.URLError, socket.timeout, TimeoutError):
            time.sleep(0.2)
    return False


def _local_static_route_verified(url: str, target: Path) -> bool:
    settings = get_settings()
    if settings.public_base_url:
        return False
    parsed = urlparse(url)
    segments = [unquote(segment) for segment in parsed.path.split("/") if segment]
    if len(segments) < 3 or segments[0] != "static-deployments":
        return False
    if segments[1] != target.parent.name or segments[-1] != target.name:
        return False
    return target.exists() and target.is_file()


def _safe_segment(value: str) -> str:
    clean = _FILENAME_SANITIZE_RE.sub("_", value.strip()).strip(" .")
    if not clean or clean in {".", ".."}:
        raise OSError("Invalid static deployment path segment.")
    return clean
