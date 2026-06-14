from __future__ import annotations

from http import HTTPStatus
from typing import Any

from services.api.app.deployment.service import deploy_artifact, get_release, list_releases
from services.api.app.shared.http import path_parts, single


RouteResponse = tuple[HTTPStatus, dict[str, object]]


def handle_get(path: str, query: dict[str, list[str]], test_run_id: str) -> RouteResponse | None:
    parts = path_parts(path)
    if parts == ["api", "deployments"]:
        return HTTPStatus.OK, {
            "items": list_releases(
                test_run_id=test_run_id,
                conversation_id=single(query, "conversation_id"),
                artifact_id=single(query, "artifact_id"),
            )
        }
    if len(parts) == 3 and parts[:2] == ["api", "deployments"]:
        return HTTPStatus.OK, get_release(parts[2], test_run_id=test_run_id)
    return None


def handle_post(path: str, body: dict[str, Any], test_run_id: str) -> RouteResponse | None:
    parts = path_parts(path)
    if len(parts) == 4 and parts[:2] == ["api", "artifacts"] and parts[3] == "deploy":
        release = deploy_artifact(parts[2], body, test_run_id=test_run_id)
        return HTTPStatus.CREATED, release
    return None
