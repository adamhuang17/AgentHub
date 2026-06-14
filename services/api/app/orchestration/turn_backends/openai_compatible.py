from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request

from services.api.app.orchestration.planner_trace import record_planner_trace
from services.api.app.orchestration.turn_backends.base import TurnRequest, TurnRouterBackendError
from services.api.app.orchestration.turn_prompt import (
    turn_decision_json_schema,
    turn_router_system_prompt,
    turn_router_user_payload,
)
from services.api.app.orchestration.turn_schema import (
    TurnDecision,
    TurnSchemaError,
    normalize_turn_decision_defaults,
    validate_turn_decision,
)
from services.api.app.shared.settings import get_settings


BACKEND_NAME = "openai_compatible"


class OpenAICompatibleTurnRouterBackend:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout_seconds: float | None = None,
        response_format: str | None = None,
    ) -> None:
        settings = get_settings()
        self.base_url = (base_url if base_url is not None else settings.turn_router_base_url or "").strip()
        self.api_key = (api_key if api_key is not None else settings.env_value("AGENTHUB_TURN_ROUTER_API_KEY", "") or "").strip()
        self.model = (model if model is not None else settings.turn_router_model or "").strip()
        self.timeout_seconds = timeout_seconds if timeout_seconds is not None else settings.turn_router_timeout_seconds
        configured_format = response_format or settings.turn_router_response_format
        self.response_format = configured_format.strip().lower()

    def decide(self, request: TurnRequest) -> TurnDecision:
        self._require_configured(request)
        payload = self._request_payload(request)
        provider_response = self._post_chat_completions(payload, request)
        raw_output = self._extract_message_content(provider_response, request)
        try:
            parsed = _parse_turn_decision_json(raw_output)
        except json.JSONDecodeError as exc:
            self._trace(request, decision_type=None, raw_output=raw_output, error_code="turn_router_invalid_output")
            raise TurnRouterBackendError(
                "turn_router_invalid_output",
                f"Turn router provider returned invalid JSON: {exc.msg}.",
                recovery_hint="Require the turn router model to return exactly one JSON object.",
            ) from exc

        try:
            normalized = normalize_turn_decision_defaults(
                _coerce_provider_decision(parsed, request=request),
                conversation_mode=request.conversation_mode,
                private_agent_id=request.private_agent_id,
                mentioned_agent_ids=_mentioned_agent_ids(request),
            )
            decision = validate_turn_decision(normalized)
        except TurnSchemaError as exc:
            self._trace(request, decision_type=None, raw_output=raw_output, error_code=exc.code)
            raise TurnRouterBackendError(
                exc.code,
                str(exc),
                recovery_hint="Fix the turn router prompt or provider JSON schema output.",
            ) from exc

        self._trace(request, decision_type=decision.decision_type, raw_output=raw_output, error_code=None)
        return decision

    def _require_configured(self, request: TurnRequest) -> None:
        missing = []
        if not self.base_url:
            missing.append("AGENTHUB_TURN_ROUTER_BASE_URL")
        if not self.api_key:
            missing.append("AGENTHUB_TURN_ROUTER_API_KEY")
        if not self.model:
            missing.append("AGENTHUB_TURN_ROUTER_MODEL")
        if missing:
            self._trace(request, decision_type=None, raw_output=None, error_code="turn_router_not_configured")
            raise TurnRouterBackendError(
                "turn_router_not_configured",
                "Turn router backend is not configured.",
                recovery_hint=f"Configure {', '.join(missing)} before routing unmentioned turns.",
            )

    def _request_payload(self, request: TurnRequest) -> dict[str, object]:
        payload: dict[str, object] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": turn_router_system_prompt()},
                {"role": "user", "content": turn_router_user_payload(request)},
            ],
            "temperature": 0,
        }
        payload["response_format"] = self._response_format_payload()
        return payload

    def _response_format_payload(self) -> dict[str, object]:
        if self._effective_response_format() == "json_object":
            return {"type": "json_object"}
        return {
            "type": "json_schema",
            "json_schema": {
                "name": "agenthub_turn_decision",
                "strict": True,
                "schema": turn_decision_json_schema(),
            },
        }

    def _effective_response_format(self) -> str:
        if self.response_format != "json_schema":
            return self.response_format
        base = self.base_url.lower()
        model = self.model.lower()
        if "dashscope.aliyuncs.com" in base or model.startswith("qwen"):
            return "json_object"
        return self.response_format

    def _post_chat_completions(self, payload: dict[str, object], request: TurnRequest) -> dict[str, object]:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        http_request = urllib.request.Request(
            _chat_completions_url(self.base_url),
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(http_request, timeout=self.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
        except (socket.timeout, TimeoutError) as exc:
            self._trace(request, decision_type=None, raw_output=None, error_code="turn_router_provider_timeout")
            raise TurnRouterBackendError(
                "turn_router_provider_timeout",
                "Turn router provider request timed out.",
                recovery_hint="Increase AGENTHUB_TURN_ROUTER_TIMEOUT_SECONDS or use a responsive router model.",
            ) from exc
        except urllib.error.HTTPError as exc:
            self._trace(request, decision_type=None, raw_output=None, error_code="turn_router_provider_failed")
            raise TurnRouterBackendError(
                "turn_router_provider_failed",
                f"Turn router provider returned HTTP {exc.code}.",
                recovery_hint="Check the router provider URL, model, credentials, and response_format support.",
            ) from exc
        except urllib.error.URLError as exc:
            if _is_timeout_error(exc):
                self._trace(request, decision_type=None, raw_output=None, error_code="turn_router_provider_timeout")
                raise TurnRouterBackendError(
                    "turn_router_provider_timeout",
                    "Turn router provider request timed out.",
                    recovery_hint="Increase AGENTHUB_TURN_ROUTER_TIMEOUT_SECONDS or use a responsive router model.",
                ) from exc
            self._trace(request, decision_type=None, raw_output=None, error_code="turn_router_provider_failed")
            raise TurnRouterBackendError(
                "turn_router_provider_failed",
                "Turn router provider request failed.",
                recovery_hint="Check the router provider URL, model, credentials, and network reachability.",
            ) from exc

        try:
            decoded = json.loads(raw)
        except json.JSONDecodeError as exc:
            self._trace(request, decision_type=None, raw_output=None, error_code="turn_router_provider_failed")
            raise TurnRouterBackendError(
                "turn_router_provider_failed",
                "Turn router provider returned a non-JSON HTTP response.",
                recovery_hint="Use an OpenAI-compatible /chat/completions endpoint.",
            ) from exc
        if not isinstance(decoded, dict):
            self._trace(request, decision_type=None, raw_output=None, error_code="turn_router_provider_failed")
            raise TurnRouterBackendError(
                "turn_router_provider_failed",
                "Turn router provider response must be a JSON object.",
                recovery_hint="Use an OpenAI-compatible /chat/completions endpoint.",
            )
        return decoded

    def _extract_message_content(self, response: dict[str, object], request: TurnRequest) -> str:
        choices = response.get("choices")
        if not isinstance(choices, list) or not choices:
            return self._invalid_provider_output(request, "Turn router provider response has no choices.")
        first = choices[0]
        if not isinstance(first, dict):
            return self._invalid_provider_output(request, "Turn router provider choice must be an object.")
        message = first.get("message")
        if not isinstance(message, dict):
            return self._invalid_provider_output(request, "Turn router provider choice has no message object.")
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            return self._invalid_provider_output(request, "Turn router provider message content is empty.")
        return content.strip()

    def _invalid_provider_output(self, request: TurnRequest, message: str) -> str:
        self._trace(request, decision_type=None, raw_output=None, error_code="turn_router_invalid_output")
        raise TurnRouterBackendError(
            "turn_router_invalid_output",
            message,
            recovery_hint="Require the provider to return choices[0].message.content as a JSON string.",
        )

    def _trace(
        self,
        request: TurnRequest,
        *,
        decision_type: str | None,
        raw_output: str | None,
        error_code: str | None,
    ) -> None:
        record_planner_trace(
            conversation_id=request.conversation_id,
            message_id=request.message_id,
            backend=BACKEND_NAME,
            model=self.model or None,
            decision_type=decision_type,
            raw_output=raw_output,
            error_code=error_code,
            test_run_id=request.test_run_id,
        )


def _timeout_from_env() -> float:
    return get_settings().turn_router_timeout_seconds


def _chat_completions_url(base_url: str) -> str:
    clean = base_url.rstrip("/")
    if clean.endswith("/chat/completions"):
        return clean
    return f"{clean}/chat/completions"


def _mentioned_agent_ids(request: TurnRequest) -> list[str]:
    agent_ids: list[str] = []
    for mention in request.mentions:
        if isinstance(mention, dict) and isinstance(mention.get("agent_id"), str) and mention["agent_id"].strip():
            agent_ids.append(mention["agent_id"].strip())
    return agent_ids


def _parse_turn_decision_json(raw_output: str) -> dict[str, object]:
    try:
        parsed = json.loads(raw_output)
    except json.JSONDecodeError:
        parsed = json.loads(_extract_json_object_text(raw_output))
    if not isinstance(parsed, dict):
        raise json.JSONDecodeError("Turn router output must be a JSON object.", raw_output, 0)
    return parsed


def _coerce_provider_decision(parsed: dict[str, object], *, request: TurnRequest) -> dict[str, object]:
    allowed = {
        "decision_type",
        "target_type",
        "target_source",
        "target_agent_id",
        "target_agent_ids",
        "goal",
        "steps",
        "reason",
        "confidence",
        "clarification_question",
    }
    decision = {key: value for key, value in parsed.items() if key in allowed}
    mentioned_agent_ids = _mentioned_agent_ids(request)
    explicit_multi_agent_request = _is_explicit_multi_agent_request(request)
    decision_type = _decision_type_alias(decision.get("decision_type"))
    if decision_type is not None:
        decision["decision_type"] = decision_type
    elif _has_provider_steps(decision.get("steps")) or len(mentioned_agent_ids) > 1:
        decision["decision_type"] = "plan_task"
    if not isinstance(decision.get("target_agent_id"), str):
        decision["target_agent_id"] = None
    if not isinstance(decision.get("target_agent_ids"), list):
        decision["target_agent_ids"] = []
    else:
        decision["target_agent_ids"] = _string_list(decision.get("target_agent_ids"))
    target_type = _target_type_alias(decision.get("target_type"))
    if target_type:
        decision["target_type"] = target_type
    target_source = _target_source_alias(decision.get("target_source"))
    if target_source:
        decision["target_source"] = target_source
    if explicit_multi_agent_request and decision.get("decision_type") in {
        "direct_response",
        "needs_clarification",
        "no_action",
    }:
        decision.update(
            {
                "decision_type": "plan_task",
                "target_type": "orchestrator",
                "target_source": "mention",
                "target_agent_id": None,
                "goal": request.message_text.strip() or "Plan requested multi-Agent work.",
                "clarification_question": None,
            }
        )
    if decision.get("decision_type") == "direct_response" and _has_provider_steps(decision.get("steps")):
        decision["decision_type"] = "plan_task"
    if decision.get("decision_type") == "plan_task":
        if decision.get("target_type") not in {"agent", "orchestrator"}:
            decision["target_type"] = "orchestrator"
        if decision.get("target_source") in {None, "", "none"}:
            decision["target_source"] = "mention" if mentioned_agent_ids else "auto_orchestrate"
        decision["target_agent_id"] = None
        if mentioned_agent_ids:
            valid_targets = [agent_id for agent_id in decision["target_agent_ids"] if agent_id in mentioned_agent_ids]
            decision["target_agent_ids"] = valid_targets or mentioned_agent_ids[:3]
        if not isinstance(decision.get("goal"), str) or not str(decision.get("goal")).strip():
            decision["goal"] = request.message_text.strip() or "Plan requested AgentHub work."
        decision["clarification_question"] = None
    if decision.get("decision_type") == "no_action":
        decision.update(
            {
                "target_type": "none",
                "target_source": "none",
                "target_agent_id": None,
                "target_agent_ids": [],
                "goal": None,
                "steps": [],
                "clarification_question": None,
            }
        )
    if decision.get("decision_type") == "direct_response":
        if decision.get("target_type") not in {"agent", "orchestrator"}:
            decision["target_type"] = "agent" if mentioned_agent_ids or request.private_agent_id else "orchestrator"
        if decision.get("target_source") in {None, "", "none"}:
            decision["target_source"] = "mention" if mentioned_agent_ids else "private_chat" if request.private_agent_id else "auto_orchestrate"
        decision["goal"] = None
        decision["steps"] = []
        decision["clarification_question"] = None
    if decision.get("decision_type") == "needs_clarification":
        if decision.get("target_type") not in {"agent", "orchestrator", "none"}:
            decision["target_type"] = "none"
        if decision.get("target_source") in {None, ""}:
            decision["target_source"] = "none"
        decision["target_agent_id"] = None
        decision["target_agent_ids"] = []
        decision["goal"] = None
        decision["steps"] = []
    if not isinstance(decision.get("steps"), list):
        decision["steps"] = []
    else:
        decision["steps"] = [
            _coerce_step(step, index, request=request)
            for index, step in enumerate(decision["steps"][:3], start=1)
        ]
    if decision.get("decision_type") == "plan_task" and not decision["steps"] and mentioned_agent_ids:
        fallback_agent_ids = [
            agent_id for agent_id in decision["target_agent_ids"] if agent_id in mentioned_agent_ids
        ] or mentioned_agent_ids[:3]
        decision["steps"] = _fallback_steps_for_explicit_mentions(request, fallback_agent_ids[:3])
    if not isinstance(decision.get("reason"), str) or not str(decision.get("reason")).strip():
        decision["reason"] = "Provider decision normalized by AgentHub."
    if decision.get("confidence") not in {"low", "medium", "high"}:
        decision["confidence"] = "medium"
    if "clarification_question" not in decision:
        decision["clarification_question"] = None
    if decision.get("decision_type") == "needs_clarification" and not isinstance(decision.get("clarification_question"), str):
        decision["clarification_question"] = "请补充完成该请求所需的信息。"
    return decision


def _has_provider_steps(value: object) -> bool:
    return isinstance(value, list) and any(isinstance(item, dict) for item in value)


def _is_explicit_multi_agent_request(request: TurnRequest) -> bool:
    if len(_mentioned_agent_ids(request)) <= 1:
        return False
    if not request.message_text.strip():
        return False
    remaining = request.message_text
    for mention in request.mentions:
        if not isinstance(mention, dict):
            continue
        for token in _mention_tokens(mention):
            remaining = remaining.replace(token, " ")
    return _has_instruction_text(remaining)


def _fallback_steps_for_explicit_mentions(
    request: TurnRequest,
    mentioned_agent_ids: list[str],
) -> list[dict[str, object]]:
    steps: list[dict[str, object]] = []
    for index, agent_id in enumerate(mentioned_agent_ids, start=1):
        instruction = _instruction_for_agent(agent_id, request)
        steps.append(
            _coerce_step(
                {
                    "id": f"step-{index}",
                    "kind": _step_kind_from_instruction(instruction),
                    "title": _step_title(agent_id, instruction, request),
                    "instruction": instruction,
                    "assigned_agent_id": agent_id,
                    "depends_on": [f"step-{index - 1}"] if index > 1 else [],
                },
                index,
                request=request,
            )
        )
    return steps


def _instruction_for_agent(agent_id: str, request: TurnRequest) -> str:
    text = request.message_text.strip()
    if not text:
        return "Execute your assigned part of the multi-Agent request."
    start = _mention_start(agent_id, request, text)
    if start is None:
        return text
    next_start = _next_mention_start_after(agent_id, request, text, start)
    clause = text[start:next_start].strip() if next_start is not None else text[start:].strip()
    for token in _mention_tokens_for_agent(agent_id, request):
        clause = clause.replace(token, " ")
    clause = _squash_spaces(clause)
    return clause or text


def _mention_start(agent_id: str, request: TurnRequest, text: str) -> int | None:
    positions = [
        position
        for token in _mention_tokens_for_agent(agent_id, request)
        for position in [_find_mention_token(text, token)]
        if position >= 0
    ]
    return min(positions) if positions else None


def _next_mention_start_after(
    agent_id: str,
    request: TurnRequest,
    text: str,
    start: int,
) -> int | None:
    positions: list[int] = []
    for mention in request.mentions:
        if not isinstance(mention, dict) or mention.get("agent_id") == agent_id:
            continue
        for token in _mention_tokens(mention):
            position = _find_mention_token(text, token)
            if position > start:
                positions.append(position)
    return min(positions) if positions else None


def _mention_tokens_for_agent(agent_id: str, request: TurnRequest) -> list[str]:
    for mention in request.mentions:
        if isinstance(mention, dict) and mention.get("agent_id") == agent_id:
            return _mention_tokens(mention)
    return [f"@{agent_id}", agent_id]


def _mention_tokens(mention: dict[str, object]) -> list[str]:
    values = [
        str(mention.get("display") or "").strip(),
        str(mention.get("agent_id") or "").strip(),
    ]
    tokens: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not value:
            continue
        for token in (f"@{value}", value):
            if token not in seen:
                tokens.append(token)
                seen.add(token)
    return sorted(tokens, key=len, reverse=True)


def _find_mention_token(text: str, token: str) -> int:
    start = 0
    while True:
        position = text.find(token, start)
        if position < 0:
            return -1
        before = text[position - 1] if position > 0 else ""
        after_index = position + len(token)
        after = text[after_index] if after_index < len(text) else ""
        if _token_boundary_ok(token, before=before, after=after):
            return position
        start = position + 1


def _token_boundary_ok(token: str, *, before: str, after: str) -> bool:
    if not token.startswith("@") and _is_ascii_name_char(before):
        return False
    if _is_asciiish_token(token) and _is_ascii_name_char(after):
        return False
    return True


def _is_asciiish_token(token: str) -> bool:
    clean = token.lstrip("@")
    return bool(clean) and all(character.isascii() for character in clean)


def _is_ascii_name_char(character: str) -> bool:
    return bool(character) and character.isascii() and (character.isalnum() or character in {"-", "_", "."})


def _has_instruction_text(value: str) -> bool:
    return any(character.isalnum() or "\u4e00" <= character <= "\u9fff" for character in value)


def _step_kind_from_instruction(instruction: str) -> str:
    text = instruction.lower()
    if any(marker in text for marker in ["优化", "审查", "review", "diff", "optimize", "improve"]):
        return "review"
    if any(marker in text for marker in ["解答", "代码", "实现", "solve", "answer", "code", "implement"]):
        return "implementation"
    return "analysis"


def _step_title(agent_id: str, instruction: str, request: TurnRequest) -> str:
    label = _agent_label(agent_id, request)
    brief = _squash_spaces(instruction)[:48] or "Agent step"
    return f"{label}: {brief}"


def _agent_label(agent_id: str, request: TurnRequest) -> str:
    for mention in request.mentions:
        if not isinstance(mention, dict) or mention.get("agent_id") != agent_id:
            continue
        display = _clean_text(mention.get("display"))
        if display:
            return display
    return agent_id


def _squash_spaces(value: str) -> str:
    return " ".join(value.split())


def _coerce_step(raw: object, index: int, *, request: TurnRequest) -> dict[str, object]:
    step = raw if isinstance(raw, dict) else {}
    kind = _step_kind_alias(step.get("kind")) or "analysis"
    step_id = _clean_text(step.get("id")) or f"step-{index}"
    instruction = (
        _clean_text(step.get("instruction"))
        or _clean_text(step.get("objective"))
        or f"Execute {kind} step {index}."
    )
    title = _clean_text(step.get("title")) or instruction[:80]
    assigned_agent_id = _clean_text(step.get("assigned_agent_id"))
    mentioned = _mentioned_agent_ids(request)
    if assigned_agent_id not in set(mentioned):
        assigned_agent_id = _agent_id_from_text(" ".join([title, instruction]), request)
    return {
        "id": step_id,
        "kind": kind,
        "title": title,
        "instruction": instruction,
        "assigned_agent_id": assigned_agent_id,
        "required_capabilities": _string_list(step.get("required_capabilities")) or _default_capabilities(kind),
        "depends_on": [
            item
            for item in _string_list(step.get("depends_on"))
            if item in {f"step-{previous}" for previous in range(1, index)}
        ],
        "expected_output": step.get("expected_output") if isinstance(step.get("expected_output"), dict) else {"kind": kind},
    }


def _decision_type_alias(value: object) -> str | None:
    clean = _clean_string(value)
    if clean in {"no_action", "direct_response", "plan_task", "needs_clarification"}:
        return clean
    aliases = {
        "plan": "plan_task",
        "task": "plan_task",
        "direct": "direct_response",
        "answer": "direct_response",
        "clarify": "needs_clarification",
    }
    return aliases.get(clean or "")


def _target_type_alias(value: object) -> str | None:
    clean = _clean_string(value)
    if clean in {"agent", "orchestrator", "none"}:
        return clean
    aliases = {
        "agents": "agent",
        "assistant": "agent",
        "router": "orchestrator",
        "system": "orchestrator",
    }
    return aliases.get(clean or "")


def _target_source_alias(value: object) -> str | None:
    clean = _clean_string(value)
    if clean in {"private_chat", "mention", "auto_orchestrate", "none"}:
        return clean
    aliases = {
        "mentions": "mention",
        "mentioned": "mention",
        "user": "mention",
        "message": "mention",
        "request": "mention",
        "input": "mention",
        "explicit": "mention",
        "explicit_mention": "mention",
        "private": "private_chat",
        "auto": "auto_orchestrate",
        "router": "auto_orchestrate",
        "orchestrator": "auto_orchestrate",
    }
    return aliases.get(clean or "")


def _step_kind_alias(value: object) -> str | None:
    clean = _clean_string(value)
    if clean in {"analysis", "implementation", "review", "deploy"}:
        return clean
    aliases = {
        "planning": "analysis",
        "research": "analysis",
        "reasoning": "analysis",
        "analyze": "analysis",
        "problem": "analysis",
        "problem_setting": "analysis",
        "question": "analysis",
        "question_setting": "analysis",
        "leetcode_problem": "analysis",
        "code": "implementation",
        "coding": "implementation",
        "implement": "implementation",
        "solve": "implementation",
        "solution": "implementation",
        "answer": "implementation",
        "frontend": "implementation",
        "backend": "implementation",
        "test": "review",
        "testing": "review",
        "qa": "review",
        "optimize": "review",
        "optimization": "review",
        "security": "review",
        "code_review": "review",
        "deployment": "deploy",
        "release": "deploy",
        "publish": "deploy",
    }
    return aliases.get(clean or "")


def _default_capabilities(kind: str) -> list[str]:
    return {
        "analysis": ["reasoning"],
        "implementation": ["code"],
        "review": ["review"],
        "deploy": ["deploy"],
    }.get(kind, [kind])


def _clean_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    clean = value.strip().lower()
    return clean or None


def _clean_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    clean = value.strip()
    return clean or None


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _agent_id_from_text(text: str, request: TurnRequest) -> str | None:
    haystack = text.lower()
    mentioned = set(_mentioned_agent_ids(request))
    for agent in request.available_agents:
        agent_id = str(agent.get("id") or "")
        if agent_id not in mentioned:
            continue
        name = str(agent.get("name") or "")
        if agent_id and agent_id.lower() in haystack:
            return agent_id
        if name and name.lower() in haystack:
            return agent_id
    return None


def _extract_json_object_text(raw_output: str) -> str:
    text = raw_output.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        raise json.JSONDecodeError("No JSON object found.", raw_output, 0)
    return text[start : end + 1]


def _is_timeout_error(exc: urllib.error.URLError) -> bool:
    reason = getattr(exc, "reason", None)
    if isinstance(reason, TimeoutError):
        return True
    if isinstance(reason, socket.timeout):
        return True
    return "timed out" in str(reason).lower()
