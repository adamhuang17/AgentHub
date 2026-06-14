import json
import os
import socket
import time
import uuid
from urllib import error, parse, request

import pytest


API_BASE_URL = os.getenv("AGENTHUB_API_BASE_URL", "http://127.0.0.1:8080").rstrip("/")
WEB_BASE_URL = os.getenv("AGENTHUB_WEB_BASE_URL", "http://127.0.0.1:3000").rstrip("/")
TEST_TIMEOUT = float(os.getenv("AGENTHUB_TEST_TIMEOUT_SECONDS", "90"))


def _json_or_text(raw: bytes):
    if not raw:
        return {}
    text = raw.decode("utf-8", errors="replace")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"raw": text}


def api_call(method, path, body=None, expected=None, headers=None, timeout=15):
    url = f"{API_BASE_URL}{path}"
    data = None
    request_headers = {
        "Accept": "application/json",
        "X-AgentHub-Test-Run": os.getenv("AGENTHUB_TEST_RUN_ID", "local"),
    }
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    if headers:
        request_headers.update(headers)
    req = request.Request(url, data=data, method=method, headers=request_headers)
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            status = resp.status
            payload = _json_or_text(resp.read())
            response_headers = dict(resp.headers.items())
    except error.HTTPError as exc:
        status = exc.code
        payload = _json_or_text(exc.read())
        response_headers = dict(exc.headers.items())
    except error.URLError as exc:
        raise AssertionError(f"Cannot reach AgentHub API at {API_BASE_URL}: {exc}") from exc

    if expected is not None:
        allowed = expected if isinstance(expected, (set, tuple, list)) else {expected}
        assert status in allowed, f"{method} {path} returned {status}, expected {allowed}, payload={payload}"
    return status, payload, response_headers


def _sse_url(path):
    if path.startswith("http://") or path.startswith("https://"):
        return path
    return f"{API_BASE_URL}{path}"


def read_sse_events(path, min_events=1, timeout=30, headers=None):
    req_headers = {
        "Accept": "text/event-stream",
        "Cache-Control": "no-cache",
        "X-AgentHub-Test-Run": os.getenv("AGENTHUB_TEST_RUN_ID", "local"),
    }
    if headers:
        req_headers.update(headers)
    req = request.Request(_sse_url(path), method="GET", headers=req_headers)
    events = []
    event_type = None
    event_id = None
    data_lines = []
    started = time.time()
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            content_type = resp.headers.get("Content-Type", "")
            assert "text/event-stream" in content_type, (
                f"SSE endpoint must return text/event-stream, got {content_type}"
            )
            while len(events) < min_events and time.time() - started < timeout:
                raw = resp.readline()
                if not raw:
                    break
                line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                if line.startswith(":"):
                    continue
                if line.startswith("event:"):
                    event_type = line.split(":", 1)[1].strip()
                    continue
                if line.startswith("id:"):
                    event_id = line.split(":", 1)[1].strip()
                    continue
                if line.startswith("data:"):
                    data_lines.append(line.split(":", 1)[1].lstrip())
                    continue
                if line == "" and data_lines:
                    text = "\n".join(data_lines)
                    try:
                        payload = json.loads(text)
                    except json.JSONDecodeError:
                        payload = {"raw": text}
                    if isinstance(payload, dict):
                        if event_type and "_sse_event" not in payload:
                            payload["_sse_event"] = event_type
                        if event_id and "_sse_id" not in payload:
                            payload["_sse_id"] = event_id
                    events.append(payload)
                    event_type = None
                    event_id = None
                    data_lines = []
    except error.HTTPError as exc:
        payload = _json_or_text(exc.read())
        raise AssertionError(f"SSE {path} returned {exc.code}, payload={payload}") from exc
    except (error.URLError, socket.timeout, TimeoutError) as exc:
        raise AssertionError(f"Cannot read SSE events from {_sse_url(path)}: {exc}") from exc

    assert len(events) >= min_events, f"Expected at least {min_events} SSE events from {path}, got {events}"
    return events


@pytest.fixture
def api_request():
    return api_call


@pytest.fixture
def unique_id():
    return f"accept-{uuid.uuid4().hex[:10]}"


def item_list(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("items", "data", "conversations", "messages", "artifacts", "members"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    raise AssertionError(f"Expected list-like payload, got {payload}")


def create_conversation(api_request, title, mode="group_agent", agent_ids=None):
    body = {"title": title, "mode": mode}
    if agent_ids is not None:
        body["agent_ids"] = agent_ids
    _, payload, _ = api_request("POST", "/api/conversations", body, expected={200, 201})
    assert payload.get("id"), f"Conversation response must include id: {payload}"
    return payload


def post_message(api_request, conversation_id, content, mentions=None, references=None, turn_decision=None):
    body = {
        "message_type": "text",
        "content": {"text": content},
    }
    if mentions is not None:
        body["mentions"] = mentions
    if references is not None:
        body["references"] = references
    if turn_decision is not None:
        body["turn_decision"] = turn_decision
    _, payload, _ = api_request("POST", f"/api/conversations/{conversation_id}/messages", body, expected={200, 201, 202})
    assert payload.get("id"), f"Message response must include id: {payload}"
    return payload


def enabled_agents(api_request, minimum=1):
    _, payload, _ = api_request("GET", "/api/agents?enabled=true", expected=200)
    agents = item_list(payload)
    agents = [agent for agent in agents if agent.get("enabled", True)]
    assert len(agents) >= minimum, f"Need at least {minimum} enabled real agents, got {agents}"
    for agent in agents:
        assert agent.get("id")
        assert agent.get("name")
        assert agent.get("provider")
        assert isinstance(agent.get("capability_tags", []), list)
    return agents


def create_disabled_agent_profile(unique_id):
    from services.api.app.shared.database import connect
    from services.api.app.shared.time import utc_now

    agent_id = f"disabled-{unique_id}-{uuid.uuid4().hex[:8]}"
    name = f"{unique_id} Disabled Agent"
    now = utc_now()
    with connect() as connection:
        connection.execute(
            """
            INSERT INTO agents (
                id, name, provider, avatar, initials, capability_tags_json,
                execution_enabled, configured, health_status,
                enabled, created_at, updated_at
            )
            VALUES (?, ?, 'test', NULL, 'DA', '["test"]', 0, 0, 'profile_only', 0, ?, ?)
            """,
            (agent_id, name, now, now),
        )
    return {
        "id": agent_id,
        "name": name,
        "provider": "test",
        "enabled": False,
        "execution_enabled": False,
        "configured": False,
        "health_status": "profile_only",
        "capability_tags": ["test"],
    }


def conversation_messages(api_request, conversation_id):
    _, payload, _ = api_request("GET", f"/api/conversations/{conversation_id}/messages", expected=200)
    return item_list(payload)


def conversation_tasks(api_request, conversation_id):
    _, payload, _ = api_request("GET", f"/api/conversations/{conversation_id}/tasks", expected=200)
    return item_list(payload)


def assert_no_run_succeeded(value):
    if isinstance(value, dict):
        assert value.get("type") != "run_succeeded", value
        assert value.get("run_status") != "succeeded", value
        assert "run_succeeded" not in value, value
        for item in value.values():
            assert_no_run_succeeded(item)
        return
    if isinstance(value, list):
        for item in value:
            assert_no_run_succeeded(item)
        return
    if isinstance(value, str):
        assert "run_succeeded" not in value, value


def wait_until(probe, timeout=TEST_TIMEOUT, interval=1.0, label="condition"):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = probe()
        if last:
            return last
        time.sleep(interval)
    raise AssertionError(f"Timed out waiting for {label}; last={last}")


def task_from_message(message_payload):
    task_id = message_payload.get("task_id") or message_payload.get("created_task_id")
    if not task_id and isinstance(message_payload.get("task"), dict):
        task_id = message_payload["task"].get("id")
    assert task_id, f"Message response must expose created task id: {message_payload}"
    return task_id


def wait_task(api_request, task_id, terminal=("succeeded", "failed"), timeout=TEST_TIMEOUT):
    def probe():
        _, payload, _ = api_request("GET", f"/api/tasks/{task_id}", expected=200)
        if payload.get("status") in terminal:
            return payload
        return None

    return wait_until(probe, timeout=timeout, label=f"task {task_id} terminal state")


def wait_artifacts(api_request, conversation_id, artifact_type=None, minimum=1):
    query = f"?conversation_id={parse.quote(conversation_id)}"
    if artifact_type:
        query += f"&type={parse.quote(artifact_type)}"

    def probe():
        _, payload, _ = api_request("GET", f"/api/artifacts{query}", expected=200)
        artifacts = item_list(payload)
        if len(artifacts) >= minimum:
            return artifacts
        return None

    return wait_until(probe, label=f"{minimum} artifacts of type {artifact_type or '*'}")


def wait_deployment(api_request, release_id, timeout=120):
    def probe():
        _, payload, _ = api_request("GET", f"/api/deployments/{release_id}", expected=200)
        return payload if payload.get("status") in {"published", "failed"} else None

    return wait_until(probe, timeout=timeout, label=f"deployment {release_id}")


def assert_explicit_failure(payload):
    assert payload.get("status") in {"failed", "provider_not_configured", "credential_invalid", "timeout"}, payload
    assert payload.get("error_code"), payload
    assert payload.get("message"), payload
    assert payload.get("recovery_hint"), payload


def assert_card_message(message, card_type):
    assert message.get("message_type") in {"card", card_type}, message
    content = message.get("content") or {}
    assert content.get("card_type") == card_type or message.get("message_type") == card_type, message
    assert content.get("id") or content.get("artifact_id") or content.get("release_id") or content.get("url"), message
    return content


def assert_real_url(url):
    parsed = parse.urlparse(url)
    assert parsed.scheme in {"http", "https"}, f"URL must be http(s): {url}"
    assert parsed.netloc, f"URL must include host: {url}"
    try:
        req = request.Request(url, method="HEAD")
        with request.urlopen(req, timeout=15) as resp:
            assert 200 <= resp.status < 500, f"URL returned unexpected status {resp.status}: {url}"
    except error.HTTPError as exc:
        assert 200 <= exc.code < 500, f"URL returned unexpected status {exc.code}: {url}"
    except error.URLError as exc:
        raise AssertionError(f"Published URL is not reachable: {url}: {exc}") from exc
