from __future__ import annotations

from http import HTTPStatus
from typing import Any

from services.api.app.agents.adapter_health import adapter_health_to_response
from services.api.app.agents.adapter_registry import AdapterRegistry
from services.api.app.agents.repository import (
    create_agent_profile,
    delete_agent_profile,
    get_agents_by_ids,
    list_agents,
    update_agent_profile,
)
from services.api.app.shared.errors import NotFoundError
from services.api.app.shared.http import optional_bool, optional_string, path_parts, single


RouteResponse = tuple[HTTPStatus, dict[str, object]]


def handle_get(path: str, query: dict[str, list[str]], test_run_id: str) -> RouteResponse | None:
    del test_run_id
    if path == "/api/adapters":
        registry = AdapterRegistry()
        return HTTPStatus.OK, {
            "items": [adapter_health_to_response(health) for health in registry.adapter_readiness_summary()]
        }

    parts = path_parts(path)
    if len(parts) == 4 and parts[:2] == ["api", "agents"] and parts[3] == "adapter-health":
        agents = get_agents_by_ids([parts[2]])
        if not agents:
            raise NotFoundError("Agent not found.")
        health = AdapterRegistry().health_for_agent(agents[0])
        return HTTPStatus.OK, adapter_health_to_response(health)

    if path != "/api/agents":
        return None

    enabled = optional_bool(single(query, "enabled"))
    kind = optional_string(single(query, "kind"), "kind")
    return HTTPStatus.OK, {"items": list_agents(enabled=enabled, kind=kind)}


def handle_post(path: str, body: dict[str, Any], test_run_id: str) -> RouteResponse | None:
    del test_run_id
    if path == "/api/agents":
        return HTTPStatus.CREATED, create_agent_profile(body)
    return None


def handle_patch(path: str, body: dict[str, Any], test_run_id: str) -> RouteResponse | None:
    del test_run_id
    parts = path_parts(path)
    if len(parts) == 3 and parts[:2] == ["api", "agents"]:
        return HTTPStatus.OK, update_agent_profile(parts[2], body)
    return None


def handle_delete(path: str, test_run_id: str) -> RouteResponse | None:
    del test_run_id
    parts = path_parts(path)
    if len(parts) == 3 and parts[:2] == ["api", "agents"]:
        return HTTPStatus.OK, delete_agent_profile(parts[2])
    return None
