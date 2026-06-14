from __future__ import annotations

from http import HTTPStatus
from typing import Any

from services.api.app.agent_runs.repository import get_run, list_run_events
from services.api.app.agent_runs.schema import run_to_response
from services.api.app.agent_runs.service import create_run_from_body, retry_run_from_body
from services.api.app.shared.http import path_parts


RouteResponse = tuple[HTTPStatus, dict[str, object]]


def handle_get(path: str, query: dict[str, list[str]], test_run_id: str) -> RouteResponse | None:
    del query
    parts = path_parts(path)

    if len(parts) == 3 and parts[:2] == ["api", "runs"]:
        return HTTPStatus.OK, run_to_response(get_run(parts[2], test_run_id=test_run_id))

    if len(parts) == 4 and parts[:2] == ["api", "runs"] and parts[3] == "events":
        return HTTPStatus.OK, {"items": list_run_events(parts[2], test_run_id=test_run_id)}

    if len(parts) == 4 and parts[:2] == ["api", "agent-runs"] and parts[3] == "events":
        return HTTPStatus.OK, {"items": list_run_events(parts[2], test_run_id=test_run_id)}

    return None


def handle_post(path: str, body: dict[str, Any], test_run_id: str) -> RouteResponse | None:
    parts = path_parts(path)
    if parts == ["api", "runs"]:
        return HTTPStatus.CREATED, create_run_from_body(body, test_run_id=test_run_id)
    if len(parts) == 4 and parts[:2] == ["api", "runs"] and parts[3] == "retry":
        return HTTPStatus.CREATED, retry_run_from_body(parts[2], body, test_run_id=test_run_id)
    if len(parts) == 4 and parts[:2] == ["api", "agent-runs"] and parts[3] == "retry":
        return HTTPStatus.CREATED, retry_run_from_body(parts[2], body, test_run_id=test_run_id)
    return None
