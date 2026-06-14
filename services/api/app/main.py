from __future__ import annotations

import json
import mimetypes
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from services.api.app import __version__
from services.api.app.agents.repository import list_agents
from services.api.app.agent_runs.routes import (
    handle_get as handle_agent_runs_get,
    handle_post as handle_agent_runs_post,
)
from services.api.app.agents.routes import (
    handle_delete as handle_agents_delete,
    handle_get as handle_agents_get,
    handle_patch as handle_agents_patch,
    handle_post as handle_agents_post,
)
from services.api.app.artifacts.routes import (
    handle_get as handle_artifacts_get,
    handle_post as handle_artifacts_post,
)
from services.api.app.conversations.routes import (
    handle_delete as handle_conversations_delete,
    handle_get as handle_conversations_get,
    handle_patch as handle_conversations_patch,
    handle_post as handle_conversations_post,
)
from services.api.app.deployment.routes import (
    handle_get as handle_deployment_get,
    handle_post as handle_deployment_post,
)
from services.api.app.orchestration.routes import handle_get as handle_orchestration_get
from services.api.app.orchestration.turn_router_gateway import turn_router_backend_configured
from services.api.app.preview.routes import (
    handle_get as handle_preview_get,
    handle_post as handle_preview_post,
)
from services.api.app.shared.errors import NotFoundError, ValidationError
from services.api.app.shared.env_loader import load_environment
from services.api.app.shared.runtime_diagnostics import runtime_diagnostics
from services.api.app.shared.settings import get_settings


RouteResponse = tuple[HTTPStatus, dict[str, object]]


class AgentHubAPIHandler(BaseHTTPRequestHandler):
    server_version = "AgentHubAPI/0.0.0"

    def do_GET(self) -> None:
        try:
            self._handle_get()
        except (NotFoundError, ValidationError) as exc:
            self._send_domain_error(exc)

    def do_HEAD(self) -> None:
        path = urlparse(self.path).path
        if path.startswith("/static-deployments/"):
            self._send_static_deployment(path, head_only=True)
            return
        self.send_response(HTTPStatus.NOT_FOUND.value)
        self._send_cors_headers()
        self.end_headers()

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT.value)
        self._send_cors_headers()
        self.end_headers()

    def _handle_get(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        if path == "/health":
            settings = get_settings()
            self._send_json(
                HTTPStatus.OK,
                {
                    "status": "ok",
                    "version": settings.env_value("AGENTHUB_VERSION", __version__),
                    "local_demo": _local_demo_status(),
                },
            )
            return

        if path == "/api/runtime/doctor":
            self._send_json(HTTPStatus.OK, runtime_diagnostics())
            return

        if path.startswith("/static-deployments/"):
            self._send_static_deployment(path)
            return

        route_response = self._route_get(path, query)
        if route_response:
            self._send_route_response(route_response)
            return

        self._send_json(
            HTTPStatus.NOT_FOUND,
            {
                "error": "not_found",
                "message": "Endpoint is not implemented in the current AgentHub phase.",
            },
        )

    def do_POST(self) -> None:
        try:
            self._handle_post()
        except (NotFoundError, ValidationError) as exc:
            self._send_domain_error(exc)

    def _handle_post(self) -> None:
        path = urlparse(self.path).path
        body = self._read_json_body()
        # Check if the route wants to stream SSE events instead of returning
        # a single JSON payload.  Routes opt-in by returning a generator.
        route_response = self._route_post(path, body)
        if route_response:
            status, payload = route_response
            if callable(payload):
                if self._wants_sse():
                    self._send_sse_stream(payload)
                else:
                    self._send_json(status, self._consume_sse_payload(payload))
            else:
                self._send_route_response(route_response)
            return

        self._send_json(
            HTTPStatus.NOT_FOUND,
            {
                "error": "not_found",
                "message": "Endpoint is not implemented in the current AgentHub phase.",
            },
        )

    def do_PATCH(self) -> None:
        try:
            self._handle_patch()
        except (NotFoundError, ValidationError) as exc:
            self._send_domain_error(exc)

    def _handle_patch(self) -> None:
        path = urlparse(self.path).path
        body = self._read_json_body()
        route_response = self._route_patch(path, body)
        if route_response:
            self._send_route_response(route_response)
            return

        self._send_json(
            HTTPStatus.NOT_FOUND,
            {
                "error": "not_found",
                "message": "Endpoint is not implemented in the current AgentHub phase.",
            },
        )

    def do_DELETE(self) -> None:
        try:
            self._handle_delete()
        except (NotFoundError, ValidationError) as exc:
            self._send_domain_error(exc)

    def _handle_delete(self) -> None:
        path = urlparse(self.path).path
        route_response = self._route_delete(path)
        if route_response:
            self._send_route_response(route_response)
            return

        self._send_json(
            HTTPStatus.NOT_FOUND,
            {
                "error": "not_found",
                "message": "Endpoint is not implemented in the current AgentHub phase.",
            },
        )

    def _route_get(self, path: str, query: dict[str, list[str]]) -> RouteResponse | None:
        return (
            handle_agents_get(path, query, self._test_run_id())
            or handle_artifacts_get(path, query, self._test_run_id())
            or handle_deployment_get(path, query, self._test_run_id())
            or handle_preview_get(path, query, self._test_run_id())
            or handle_agent_runs_get(path, query, self._test_run_id())
            or handle_conversations_get(path, query, self._test_run_id())
            or handle_orchestration_get(path, query, self._test_run_id())
        )

    def _route_post(self, path: str, body: dict[str, Any]) -> RouteResponse | None:
        return (
            handle_agents_post(path, body, self._test_run_id())
            or handle_artifacts_post(path, body, self._test_run_id())
            or handle_deployment_post(path, body, self._test_run_id())
            or handle_preview_post(path, body, self._test_run_id())
            or handle_agent_runs_post(path, body, self._test_run_id())
            or handle_conversations_post(path, body, self._test_run_id())
        )

    def _route_patch(self, path: str, body: dict[str, Any]) -> RouteResponse | None:
        return (
            handle_agents_patch(path, body, self._test_run_id())
            or handle_conversations_patch(path, body, self._test_run_id())
        )

    def _route_delete(self, path: str) -> RouteResponse | None:
        return (
            handle_agents_delete(path, self._test_run_id())
            or handle_conversations_delete(path, self._test_run_id())
        )

    def _send_route_response(self, response: RouteResponse) -> None:
        status, payload = response
        self._send_json(status, payload)

    def _send_sse_stream(self, event_generator) -> None:
        """Send a Server-Sent Events stream to the client.

        *event_generator* is an iterable of ``(event_type, data_dict)`` tuples.
        The last item must have event_type ``"done"``; its data is sent as a
        final JSON payload so non-SSE callers still get a complete response.
        """
        self.send_response(HTTPStatus.OK.value)
        self._send_cors_headers()
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        try:
            for event_type, data in self._event_iter(event_generator):
                payload = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
                chunk = f"event: {event_type}\ndata: {payload}\n\n"
                self.wfile.write(chunk.encode("utf-8"))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            return

    def _consume_sse_payload(self, event_generator) -> dict[str, Any]:
        final_payload: dict[str, Any] | None = None
        for event_type, data in self._event_iter(event_generator):
            if event_type == "done" and isinstance(data, dict):
                final_payload = data
        return final_payload or {
            "error": "stream_without_done",
            "error_code": "stream_without_done",
            "message": "Streaming route finished without a final done event.",
        }

    def _event_iter(self, event_generator):
        return event_generator() if callable(event_generator) else event_generator

    def _wants_sse(self) -> bool:
        return "text/event-stream" in self.headers.get("Accept", "").lower()

    def _send_domain_error(self, exc: Exception) -> None:
        if isinstance(exc, ValidationError):
            code = getattr(exc, "code", "validation_error")
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {
                    "error": "validation_error",
                    "code": code,
                    "error_code": code,
                    "message": str(exc),
                },
            )
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found", "message": str(exc)})

    def _read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ValidationError(f"Invalid JSON body: {exc.msg}") from exc
        if not isinstance(payload, dict):
            raise ValidationError("JSON body must be an object.")
        return payload

    def _send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status.value)
        self._send_cors_headers()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            return

    def _send_static_deployment(self, path: str, *, head_only: bool = False) -> None:
        root = _static_deploy_root()
        if root is None:
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found", "message": "Static deployment host is not configured."})
            return

        relative = path.removeprefix("/static-deployments/")
        segments = [unquote(segment) for segment in relative.split("/") if segment]
        if not segments:
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found", "message": "Static deployment file was not found."})
            return
        if any(_unsafe_static_segment(segment) for segment in segments):
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "validation_error", "error_code": "static_deployment_path_invalid"})
            return

        release_id = segments[0]
        file_segments = segments[1:] or ["index.html"]
        file_path = (root / release_id / Path(*file_segments)).resolve()
        try:
            file_path.relative_to(root)
        except ValueError:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "validation_error", "error_code": "static_deployment_path_invalid"})
            return
        if file_path.is_dir():
            file_path = file_path / "index.html"
        if not file_path.exists() or not file_path.is_file():
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found", "message": "Static deployment file was not found."})
            return

        body = file_path.read_bytes()
        content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK.value)
        self._send_cors_headers()
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if not head_only:
            self.wfile.write(body)

    def _send_cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,PATCH,DELETE,HEAD,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type,Accept,X-AgentHub-Test-Run")
        self.send_header("Access-Control-Max-Age", "600")

    def _test_run_id(self) -> str:
        return self.headers.get("X-AgentHub-Test-Run", "local")

    def log_message(self, format: str, *args: object) -> None:
        if (get_settings().env_value("AGENTHUB_API_LOGS", "") or "").lower() in {"1", "true", "yes"}:
            super().log_message(format, *args)


def create_server(host: str | None = None, port: int | None = None) -> ThreadingHTTPServer:
    load_environment()
    settings = get_settings()
    bind_host = host or settings.host
    bind_port = port or settings.port
    return ThreadingHTTPServer((bind_host, bind_port), AgentHubAPIHandler)


def _static_deploy_root() -> Path | None:
    configured = get_settings().static_deploy_dir
    if configured is None:
        return None
    return configured.expanduser().resolve()


def _unsafe_static_segment(segment: str) -> bool:
    return not segment or segment in {".", ".."} or "/" in segment or "\\" in segment


def _local_demo_status() -> dict[str, object]:
    agents = list_agents(enabled=True)
    return {
        "turn_router_backend_configured": _turn_router_demo_configured(),
        "agents_configured_count": sum(1 for agent in agents if agent.get("configured") is True),
        "agents_enabled_count": len(agents),
    }


def _turn_router_demo_configured() -> bool:
    if turn_router_backend_configured():
        return True
    settings = get_settings()
    return settings.turn_router_backend == "test" and settings.turn_router_configured()


def main() -> None:
    load_environment()
    with create_server() as server:
        server.serve_forever()


if __name__ == "__main__":
    main()
