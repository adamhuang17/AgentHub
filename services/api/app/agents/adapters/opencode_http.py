from __future__ import annotations

import json
import socket
import time
from dataclasses import dataclass
from urllib import error, parse, request

from services.api.app.agent_runs.schema import AgentRunEventDraft, AgentRunRequest
from services.api.app.agents.adapter_health import AdapterHealth, adapter_health
from services.api.app.agents.provider_config import ProviderConfig
from services.api.app.memory.prompt_context import enrich_cli_prompt as _enrich_prompt_with_context


@dataclass(frozen=True)
class _HttpResult:
    status: int
    text: str
    json_payload: object | None


class OpenCodeHttpAdapter:
    adapter_id = "opencode_http"

    def __init__(self, *, config: ProviderConfig, target_agent_id: str | None = None) -> None:
        self.config = config
        self.target_agent_id = target_agent_id

    def health(self) -> AdapterHealth:
        api_base = self._api_base()
        if api_base is None:
            return adapter_health(
                provider=self.config.provider,
                adapter_kind=self.adapter_id,
                configured=False,
                status="not_configured",
                error_code="provider_not_configured",
                recovery_hint="Set OPENCODE_API_BASE to the running AgentHub coding runtime.",
                capabilities=[],
                message="AgentHub coding runtime API base is missing.",
            )
        try:
            self._probe()
        except _OpenCodeHttpError as exc:
            return adapter_health(
                provider=self.config.provider,
                adapter_kind=self.adapter_id,
                configured=False,
                status="unavailable",
                error_code="opencode_server_unavailable",
                recovery_hint=exc.recovery_hint,
                capabilities=[],
                message=str(exc),
            )
        return adapter_health(
            provider=self.config.provider,
            adapter_kind=self.adapter_id,
            configured=True,
            status="ready",
            error_code=None,
            recovery_hint=None,
            capabilities=["direct_response", "planned_step", "diff"],
            message="AgentHub coding runtime probe succeeded.",
        )

    def invoke(self, request_payload: AgentRunRequest) -> list[AgentRunEventDraft]:
        if request_payload.run_mode not in {"direct_response", "planned_step"}:
            return self._failure_events(
                "adapter_unsupported_run_mode",
                "opencode_http only supports direct_response and planned_step.",
            )

        events = [
            AgentRunEventDraft(
                type="adapter_preflight_started",
                payload={"adapter_kind": self.adapter_id, "provider": self.config.provider},
            )
        ]
        health = self.health()
        if not health.configured:
            payload = {
                "error_code": health.error_code or "opencode_server_unavailable",
                "message": health.message or "AgentHub coding runtime is unavailable.",
                "provider": self.config.provider,
                "target_agent_id": self.target_agent_id,
                "recovery_hint": health.recovery_hint,
            }
            events.append(AgentRunEventDraft(type="adapter_preflight_failed", payload=payload))
            events.extend(self._failure_events(str(payload["error_code"]), str(payload["message"]), recovery_hint=health.recovery_hint))
            return events

        events.append(
            AgentRunEventDraft(
                type="adapter_preflight_succeeded",
                payload={"adapter_kind": self.adapter_id, "provider": self.config.provider},
            )
        )
        events.append(
            AgentRunEventDraft(
                type="adapter_process_started",
                payload={"adapter_kind": self.adapter_id, "provider": self.config.provider, "api_base": self._api_base()},
            )
        )

        try:
            session = self._create_session()
            session_id = _required_id(session, "AgentHub coding runtime session create response")
            events.append(
                AgentRunEventDraft(
                    type="backend_session_started",
                    payload={"backend": "opencode_http", "session_id": session_id},
                )
            )
            self._send_prompt(session_id, request_payload)
            assistant_text = self._wait_for_assistant(session_id)
        except _OpenCodeHttpError as exc:
            events.extend(self._failure_events(exc.code, str(exc), recovery_hint=exc.recovery_hint))
            return events

        if not assistant_text.strip():
            events.extend(
                self._failure_events(
                    "opencode_no_assistant_message",
                    "AgentHub coding runtime did not produce a completed assistant message.",
                    recovery_hint="Inspect AgentHub coding runtime messages and provider/runtime configuration.",
                )
            )
            return events

        events.append(
            AgentRunEventDraft(
                type="assistant_message_completed",
                payload={
                    "message_role": "assistant",
                    "content_text": assistant_text,
                    "provider": self.config.provider,
                    "adapter_kind": self.adapter_id,
                },
            )
        )

        diff_text = self._read_diff()
        if diff_text:
            changed_paths = _changed_paths_from_diff(diff_text)
            events.append(
                AgentRunEventDraft(
                    type="artifact_created",
                    payload={
                        "artifact_type": "source_diff",
                        "title": "AgentHub coding runtime source diff",
                        "mime_type": "application/vnd.agenthub.diff+json",
                        "content": json.dumps(_structured_diff(diff_text), ensure_ascii=False, indent=2, sort_keys=True),
                    },
                )
            )
            for artifact_event in self._file_artifact_events(changed_paths):
                events.append(artifact_event)

        events.append(
            AgentRunEventDraft(
                type="run_succeeded",
                payload={
                    "run_id": request_payload.run_id,
                    "provider": self.config.provider,
                    "adapter_kind": self.adapter_id,
                },
            )
        )
        return events

    def cancel(self, run_id: str) -> dict[str, object]:
        return {"run_id": run_id, "cancel_requested": False, "message": "opencode_http runs are synchronous."}

    def _probe(self) -> None:
        last_error: _OpenCodeHttpError | None = None
        for path in ("/session?limit=1", "/session/status"):
            try:
                self._json("GET", path, timeout_seconds=min(self.config.timeout_seconds, 5))
                return
            except _OpenCodeHttpError as exc:
                last_error = exc
        if last_error is not None:
            raise last_error

    def _create_session(self) -> dict[str, object]:
        result = self._json("POST", "/session", body={})
        if not isinstance(result.json_payload, dict):
            raise _OpenCodeHttpError(
                "opencode_invalid_response",
                "AgentHub coding runtime session create response was not a JSON object.",
                recovery_hint="Verify AgentHub coding runtime /session API compatibility.",
            )
        return dict(result.json_payload)

    def _send_prompt(self, session_id: str, request_payload: AgentRunRequest) -> None:
        prompt_text = _enrich_prompt_with_context(request_payload.instruction, request_payload.context_bundle)
        body: dict[str, object] = {
            "parts": [{"type": "text", "text": prompt_text}],
        }
        model = _model_ref(self.config.model)
        if model is not None:
            body["model"] = model
        result = self._json("POST", f"/session/{parse.quote(session_id, safe='')}/message", body=body)
        if result.status < 200 or result.status >= 300:
            raise _OpenCodeHttpError(
                "opencode_prompt_failed",
                f"AgentHub coding runtime prompt returned HTTP {result.status}.",
                recovery_hint="Inspect AgentHub coding runtime provider/model/session configuration.",
            )

    def _wait_for_assistant(self, session_id: str) -> str:
        deadline = time.monotonic() + max(1, self.config.timeout_seconds)
        last_messages: object | None = None
        while time.monotonic() <= deadline:
            result = self._json("GET", f"/session/{parse.quote(session_id, safe='')}/message")
            last_messages = result.json_payload
            assistant = _last_assistant_text(result.json_payload)
            if assistant:
                return assistant
            time.sleep(1)
        raise _OpenCodeHttpError(
            "opencode_no_assistant_message",
            "AgentHub coding runtime messages did not include assistant content before timeout.",
            recovery_hint="Check pending permissions, model credentials, and AgentHub coding runtime state.",
            payload=last_messages,
        )

    def _read_diff(self) -> str | None:
        try:
            result = self._json("GET", "/vcs/diff/raw", accept="text/plain")
        except _OpenCodeHttpError:
            return None
        text = result.text.strip()
        return text or None

    def _file_artifact_events(self, paths: list[str]) -> list[AgentRunEventDraft]:
        events: list[AgentRunEventDraft] = []
        seen: set[str] = set()
        for path in paths:
            clean_path = path.strip().replace("\\", "/")
            if not clean_path or clean_path in seen:
                continue
            seen.add(clean_path)
            artifact_type = _artifact_type_for_path(clean_path)
            if artifact_type is None:
                continue
            content = self._read_text_file(clean_path)
            if content is None or content == "":
                continue
            events.append(
                AgentRunEventDraft(
                    type="artifact_created",
                    payload={
                        "artifact_type": artifact_type,
                        "title": clean_path,
                        "mime_type": _mime_type_for_artifact(artifact_type, clean_path),
                        "content": content,
                    },
                )
            )
        return events

    def _read_text_file(self, path: str) -> str | None:
        try:
            result = self._json("GET", f"/file/content?path={parse.quote(path, safe='')}")
        except _OpenCodeHttpError:
            return None
        payload = result.json_payload
        if not isinstance(payload, dict):
            return None
        if payload.get("type") != "text":
            return None
        content = payload.get("content")
        return content if isinstance(content, str) else None

    def _json(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, object] | None = None,
        timeout_seconds: int | None = None,
        accept: str = "application/json",
    ) -> _HttpResult:
        api_base = self._api_base()
        if api_base is None:
            raise _OpenCodeHttpError(
                "provider_not_configured",
                "AgentHub coding runtime API base is missing.",
                recovery_hint="Set OPENCODE_API_BASE.",
            )
        data = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8") if body is not None else None
        headers = {"Accept": accept}
        if data is not None:
            headers["Content-Type"] = "application/json"
        req = request.Request(f"{api_base}{path}", data=data, method=method, headers=headers)
        try:
            with _urlopen_without_proxy(req, timeout_seconds=timeout_seconds or self.config.timeout_seconds) as response:
                raw = response.read().decode("utf-8", errors="replace")
                return _HttpResult(status=int(response.status), text=raw, json_payload=_parse_json_or_none(raw))
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise _OpenCodeHttpError(
                "opencode_server_unavailable",
                f"AgentHub coding runtime returned HTTP {exc.code}: {detail[:200]}",
                recovery_hint="Verify OPENCODE_API_BASE and AgentHub coding runtime readiness.",
            ) from exc
        except (error.URLError, TimeoutError, socket.timeout) as exc:
            raise _OpenCodeHttpError(
                "opencode_server_unavailable",
                f"AgentHub coding runtime HTTP request failed: {exc}",
                recovery_hint="Start AgentHub coding runtime and verify OPENCODE_API_BASE.",
            ) from exc

    def _api_base(self) -> str | None:
        if not self.config.api_base:
            return None
        return self.config.api_base.rstrip("/")

    def _failure_events(
        self,
        error_code: str,
        message: str,
        *,
        recovery_hint: str | None = None,
    ) -> list[AgentRunEventDraft]:
        payload = {
            "error_code": error_code,
            "message": message,
            "provider": self.config.provider,
            "target_agent_id": self.target_agent_id,
            "recovery_hint": recovery_hint,
        }
        return [
            AgentRunEventDraft(type="adapter_error", payload=payload),
            AgentRunEventDraft(type="run_failed", payload=payload),
        ]


class _OpenCodeHttpError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        recovery_hint: str | None = None,
        payload: object | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.recovery_hint = recovery_hint
        self.payload = payload


def _required_id(payload: dict[str, object], label: str) -> str:
    value = payload.get("id")
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise _OpenCodeHttpError(
        "opencode_invalid_response",
        f"{label} did not include id.",
        recovery_hint="Verify AgentHub coding runtime /session response shape.",
    )


def _urlopen_without_proxy(req: request.Request, *, timeout_seconds: int):
    opener = request.build_opener(request.ProxyHandler({}))
    return opener.open(req, timeout=timeout_seconds)


def _parse_json_or_none(raw: str) -> object | None:
    if not raw.strip():
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _last_assistant_text(payload: object | None) -> str | None:
    if not isinstance(payload, list):
        return None
    texts: list[str] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        info = item.get("info")
        role = info.get("role") if isinstance(info, dict) else item.get("role")
        if role != "assistant":
            continue
        text = _parts_text(item.get("parts"))
        if text:
            texts.append(text)
    return texts[-1] if texts else None


def _parts_text(parts: object) -> str | None:
    if not isinstance(parts, list):
        return None
    chunks: list[str] = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        value = part.get("text") or part.get("content")
        if isinstance(value, str) and value:
            chunks.append(value)
    text = "\n".join(chunks).strip()
    return text or None


def _model_ref(model: str | None) -> dict[str, str] | None:
    if not model or "/" not in model:
        return None
    provider_id, model_id = model.split("/", 1)
    if not provider_id.strip() or not model_id.strip():
        return None
    return {"providerID": provider_id.strip(), "modelID": model_id.strip()}


def _structured_diff(diff_text: str) -> dict[str, object]:
    additions = 0
    deletions = 0
    paths = _changed_paths_from_diff(diff_text)
    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            continue
        elif line.startswith("+") and not line.startswith("+++"):
            additions += 1
        elif line.startswith("-") and not line.startswith("---"):
            deletions += 1
    return {
        "files": [
            {
                "path": path,
                "old_path": path,
                "new_path": path,
                "status": "modified",
                "additions": additions,
                "deletions": deletions,
                "hunks": [],
                "unified_diff": diff_text,
            }
            for path in (paths or ["workspace.diff"])
        ],
        "hunks": [],
        "additions": additions,
        "deletions": deletions,
    }


def _changed_paths_from_diff(diff_text: str) -> list[str]:
    paths: list[str] = []
    for line in diff_text.splitlines():
        if not line.startswith("diff --git "):
            continue
        parts = line.split()
        if len(parts) < 4:
            continue
        candidate = parts[3].removeprefix("b/").strip()
        if candidate and candidate != "/dev/null" and candidate not in paths:
            paths.append(candidate)
    return paths


def _artifact_type_for_path(path: str) -> str | None:
    clean = path.strip().replace("\\", "/").lower()
    if clean in {"index.html", "dist/index.html"}:
        return "web_preview"
    if clean.endswith((".md", ".markdown")):
        return "markdown_doc"
    if "." in clean:
        return "code_file"
    return None


def _mime_type_for_artifact(artifact_type: str, path: str) -> str:
    if artifact_type == "web_preview":
        return "text/html"
    if artifact_type == "markdown_doc":
        return "text/markdown"
    if path.lower().endswith((".ts", ".tsx", ".js", ".jsx", ".json", ".css", ".html", ".py", ".md")):
        return "text/plain"
    return "text/plain"
