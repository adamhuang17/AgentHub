from __future__ import annotations

from http import HTTPStatus

from services.api.app.orchestration.repository import (
    get_plan,
    get_plan_for_task,
    get_task,
    list_tasks_for_conversation,
)
from services.api.app.shared.http import path_parts


RouteResponse = tuple[HTTPStatus, dict[str, object]]


def handle_get(path: str, query: dict[str, list[str]], test_run_id: str) -> RouteResponse | None:
    del query
    parts = path_parts(path)

    if len(parts) == 4 and parts[:2] == ["api", "conversations"] and parts[3] == "tasks":
        return HTTPStatus.OK, {"items": list_tasks_for_conversation(parts[2], test_run_id=test_run_id)}

    if len(parts) == 3 and parts[:2] == ["api", "tasks"]:
        return HTTPStatus.OK, get_task(parts[2], test_run_id=test_run_id)

    if len(parts) == 4 and parts[:2] == ["api", "tasks"] and parts[3] == "plan":
        return HTTPStatus.OK, get_plan_for_task(parts[2], test_run_id=test_run_id)

    if len(parts) == 3 and parts[:2] == ["api", "plans"]:
        return HTTPStatus.OK, get_plan(parts[2], test_run_id=test_run_id)

    return None
