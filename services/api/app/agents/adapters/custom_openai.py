from __future__ import annotations

import json
import socket
from dataclasses import dataclass
from typing import Any
from urllib import error, request

from services.api.app.agent_runs.schema import AgentRunEventDraft, AgentRunRequest
from services.api.app.agents.adapter_health import AdapterHealth, adapter_health
from services.api.app.agents.provider_config import (
    ProviderConfig,
    credential_env_name,
    credential_value_from_environment,
)
from services.api.app.memory.prompt_context import (
    build_openai_messages as _build_contextual_prompt,
    context_summary_for_log as _context_summary_for_log,
)


class AdapterCallError(Exception):
    def __init__(self, code: str, message: str, *, recovery_hint: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.recovery_hint = recovery_hint


@dataclass(frozen=True)
class _CompletionResult:
    content_text: str
    usage: dict[str, object] | None
    raw_response: dict[str, object]
    thinking_content: str | None = None


class CustomOpenAIAdapter:
    adapter_id = "custom_openai"

    def __init__(
        self,
        *,
        config: ProviderConfig,
        target_agent_id: str | None = None,
        api_key_override: str | None = None,
    ) -> None:
        self.config = config
        self.target_agent_id = target_agent_id
        self.api_key_override = api_key_override.strip() if isinstance(api_key_override, str) and api_key_override.strip() else None

    def health(self) -> AdapterHealth:
        if not self.config.api_base or not self.config.model:
            return adapter_health(
                provider=self.config.provider,
                adapter_kind=self.adapter_id,
                configured=False,
                status="not_configured",
                error_code="provider_not_configured",
                recovery_hint="Configure api_base and model for the custom_openai adapter.",
                capabilities=[],
                message="custom_openai requires api_base and model.",
            )

        if self._api_key() is None:
            return adapter_health(
                provider=self.config.provider,
                adapter_kind=self.adapter_id,
                configured=False,
                status="missing_credentials",
                error_code="missing_credentials",
                recovery_hint=f"Set {credential_env_name(self.config) or 'a CredentialRef'} before starting runs.",
                capabilities=[],
                message="custom_openai API key is missing.",
            )

        if self.config.health_check_strategy == "none":
            return adapter_health(
                provider=self.config.provider,
                adapter_kind=self.adapter_id,
                configured=False,
                status="unavailable",
                error_code="adapter_health_check_disabled",
                recovery_hint="Enable a real health_check_strategy before treating this adapter as ready.",
                capabilities=[],
                message="Adapter readiness requires a real probe.",
            )

        try:
            self._chat_completion("Reply with OK.", timeout_seconds=min(self.config.timeout_seconds, 10), max_tokens=1)
        except AdapterCallError as exc:
            if exc.code in {"credential_invalid", "missing_credentials"}:
                return adapter_health(
                    provider=self.config.provider,
                    adapter_kind=self.adapter_id,
                    configured=False,
                    status="missing_credentials",
                    error_code=exc.code,
                    recovery_hint=exc.recovery_hint,
                    capabilities=[],
                    message=str(exc),
                )
            return adapter_health(
                provider=self.config.provider,
                adapter_kind=self.adapter_id,
                configured=False,
                status="unavailable",
                error_code=exc.code,
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
            capabilities=["direct_response"],
            message="custom_openai direct_response probe succeeded.",
        )

    def invoke(self, request_payload: AgentRunRequest) -> list[AgentRunEventDraft]:
        if request_payload.run_mode != "direct_response":
            return self._failure_events("adapter_unsupported_run_mode", "custom_openai only supports direct_response.")

        events = [
            AgentRunEventDraft(
                type="adapter_preflight_started",
                payload={"adapter_kind": self.adapter_id, "provider": self.config.provider},
            )
        ]
        preflight_error = self._local_preflight_error()
        if preflight_error is not None:
            error_code, message, recovery_hint = preflight_error
            events.append(
                AgentRunEventDraft(
                    type="adapter_preflight_failed",
                    payload={
                        "error_code": error_code,
                        "message": message,
                        "provider": self.config.provider,
                        "target_agent_id": request_payload.target_agent_id,
                        "recovery_hint": recovery_hint,
                    },
                )
            )
            events.extend(
                self._failure_events(
                    error_code,
                    message,
                    recovery_hint=recovery_hint,
                )
            )
            return events

        events.append(
            AgentRunEventDraft(
                type="adapter_preflight_succeeded",
                payload={"adapter_kind": self.adapter_id, "provider": self.config.provider},
            )
        )

        context_summary = _context_summary_for_log(request_payload.context_bundle)
        prompt_text = _build_contextual_prompt(request_payload.instruction, request_payload.context_bundle)
        try:
            result = self._chat_completion_messages(
                prompt_text,
                timeout_seconds=self.config.timeout_seconds,
                max_tokens=self.config.max_output_tokens,
            )
        except AdapterCallError as exc:
            events.extend(self._failure_events(exc.code, str(exc), recovery_hint=exc.recovery_hint))
            return events

        if not result.content_text.strip() and not (result.thinking_content and result.thinking_content.strip()):
            events.extend(
                self._failure_events(
                    "adapter_invalid_response",
                    "custom_openai response did not contain assistant content.",
                    recovery_hint="Inspect provider response shape and model compatibility. If using a reasoning model, consider increasing max_output_tokens.",
                )
            )
            return events

        events.append(
            AgentRunEventDraft(
                type="assistant_message_completed",
                payload={
                    "message_role": "assistant",
                    "content_text": result.content_text,
                    "thinking_content": result.thinking_content,
                    "provider": self.config.provider,
                    "model": self.config.model,
                    "context_used": context_summary,
                },
            )
        )
        if result.usage is not None:
            events.append(
                AgentRunEventDraft(
                    type="usage_reported",
                    payload={"provider": self.config.provider, "model": self.config.model, "usage": result.usage},
                )
            )
        events.append(
            AgentRunEventDraft(
                type="run_succeeded",
                payload={
                    "run_id": request_payload.run_id,
                    "provider": self.config.provider,
                    "adapter_kind": self.adapter_id,
                    "model": self.config.model,
                },
            )
        )
        return events

    def cancel(self, run_id: str) -> dict[str, object]:
        return {"run_id": run_id, "cancel_requested": False, "message": "custom_openai runs are synchronous."}

    def _chat_completion_messages(self, messages: list[dict[str, str]], *, timeout_seconds: int, max_tokens: int) -> _CompletionResult:
        api_key = self._api_key()
        if api_key is None:
            raise AdapterCallError(
                "missing_credentials",
                "custom_openai API key is missing.",
                recovery_hint=f"Set {credential_env_name(self.config) or 'the configured CredentialRef'}.",
            )
        if not self.config.api_base or not self.config.model:
            raise AdapterCallError(
                "provider_not_configured",
                "custom_openai api_base or model is missing.",
                recovery_hint="Configure api_base and model for this provider.",
            )

        body = {
            "model": self.config.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": self.config.temperature,
        }
        req = request.Request(
            _chat_completions_url(self.config.api_base),
            data=json.dumps(body).encode("utf-8"),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
        )
        try:
            with request.urlopen(req, timeout=timeout_seconds) as response:
                raw = response.read().decode("utf-8", errors="replace")
        except error.HTTPError as exc:
            detail = _redact_secret(exc.read().decode("utf-8", errors="replace"), api_key)
            if exc.code in {401, 403}:
                raise AdapterCallError(
                    "credential_invalid",
                    f"custom_openai authentication failed with HTTP {exc.code}.",
                    recovery_hint="Verify the configured API key and provider account access.",
                ) from exc
            if exc.code == 429:
                raise AdapterCallError(
                    "backend_rate_limited",
                    "custom_openai provider rate limited the request.",
                    recovery_hint="Retry later or adjust provider quota.",
                ) from exc
            raise AdapterCallError(
                "backend_network_failed",
                f"custom_openai provider returned HTTP {exc.code}: {detail[:200]}",
                recovery_hint="Inspect provider endpoint, model name, and network availability.",
            ) from exc
        except (TimeoutError, socket.timeout) as exc:
            raise AdapterCallError(
                "adapter_timeout",
                "custom_openai request timed out.",
                recovery_hint="Increase timeout_seconds or inspect provider availability.",
            ) from exc
        except error.URLError as exc:
            raise AdapterCallError(
                "backend_network_failed",
                f"custom_openai network request failed: {_redact_secret(str(exc.reason), api_key)}",
                recovery_hint="Inspect provider endpoint and network availability.",
            ) from exc

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise AdapterCallError(
                "adapter_invalid_response",
                "custom_openai response was not valid JSON.",
                recovery_hint="Inspect provider compatibility with OpenAI chat completions.",
            ) from exc
        if not isinstance(payload, dict):
            raise AdapterCallError(
                "adapter_invalid_response",
                "custom_openai response JSON was not an object.",
                recovery_hint="Inspect provider compatibility with OpenAI chat completions.",
            )
        content, thinking = _assistant_parts(payload)
        if content is None:
            raise AdapterCallError(
                "adapter_invalid_response",
                "custom_openai response did not include choices[0].message.content.",
                recovery_hint="Inspect provider compatibility with OpenAI chat completions.",
            )
        usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else None
        return _CompletionResult(content_text=content, usage=usage, raw_response=payload, thinking_content=thinking)

    def _chat_completion(self, prompt: str, *, timeout_seconds: int, max_tokens: int) -> _CompletionResult:
        api_key = self._api_key()
        if api_key is None:
            raise AdapterCallError(
                "missing_credentials",
                "custom_openai API key is missing.",
                recovery_hint=f"Set {credential_env_name(self.config) or 'the configured CredentialRef'}.",
            )
        if not self.config.api_base or not self.config.model:
            raise AdapterCallError(
                "provider_not_configured",
                "custom_openai api_base or model is missing.",
                recovery_hint="Configure api_base and model for this provider.",
            )

        body = {
            "model": self.config.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": self.config.temperature,
        }
        req = request.Request(
            _chat_completions_url(self.config.api_base),
            data=json.dumps(body).encode("utf-8"),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
        )
        try:
            with request.urlopen(req, timeout=timeout_seconds) as response:
                raw = response.read().decode("utf-8", errors="replace")
        except error.HTTPError as exc:
            detail = _redact_secret(exc.read().decode("utf-8", errors="replace"), api_key)
            if exc.code in {401, 403}:
                raise AdapterCallError(
                    "credential_invalid",
                    f"custom_openai authentication failed with HTTP {exc.code}.",
                    recovery_hint="Verify the configured API key and provider account access.",
                ) from exc
            if exc.code == 429:
                raise AdapterCallError(
                    "backend_rate_limited",
                    "custom_openai provider rate limited the request.",
                    recovery_hint="Retry later or adjust provider quota.",
                ) from exc
            raise AdapterCallError(
                "backend_network_failed",
                f"custom_openai provider returned HTTP {exc.code}: {detail[:200]}",
                recovery_hint="Inspect provider endpoint, model name, and network availability.",
            ) from exc
        except (TimeoutError, socket.timeout) as exc:
            raise AdapterCallError(
                "adapter_timeout",
                "custom_openai request timed out.",
                recovery_hint="Increase timeout_seconds or inspect provider availability.",
            ) from exc
        except error.URLError as exc:
            raise AdapterCallError(
                "backend_network_failed",
                f"custom_openai network request failed: {_redact_secret(str(exc.reason), api_key)}",
                recovery_hint="Inspect provider endpoint and network availability.",
            ) from exc

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise AdapterCallError(
                "adapter_invalid_response",
                "custom_openai response was not valid JSON.",
                recovery_hint="Inspect provider compatibility with OpenAI chat completions.",
            ) from exc
        if not isinstance(payload, dict):
            raise AdapterCallError(
                "adapter_invalid_response",
                "custom_openai response JSON was not an object.",
                recovery_hint="Inspect provider compatibility with OpenAI chat completions.",
            )
        content, thinking = _assistant_parts(payload)
        if content is None:
            raise AdapterCallError(
                "adapter_invalid_response",
                "custom_openai response did not include choices[0].message.content.",
                recovery_hint="Inspect provider compatibility with OpenAI chat completions.",
            )
        usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else None
        return _CompletionResult(content_text=content, usage=usage, raw_response=payload, thinking_content=thinking)

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

    def _local_preflight_error(self) -> tuple[str, str, str] | None:
        if not self.config.api_base or not self.config.model:
            return (
                "provider_not_configured",
                "custom_openai api_base or model is missing.",
                "Configure api_base and model for this provider.",
            )
        if self._api_key() is None:
            return (
                "missing_credentials",
                "custom_openai API key is missing.",
                f"Set {credential_env_name(self.config) or 'the configured CredentialRef'}.",
            )
        return None

    def _api_key(self) -> str | None:
        return self.api_key_override or credential_value_from_environment(self.config)


def _chat_completions_url(api_base: str) -> str:
    clean = api_base.rstrip("/")
    if clean.endswith("/chat/completions"):
        return clean
    return f"{clean}/chat/completions"


def _assistant_parts(payload: dict[str, Any]) -> tuple[str | None, str | None]:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return None, None
    first = choices[0]
    if not isinstance(first, dict):
        return None, None
    message = first.get("message")
    thinking: str | None = None
    if isinstance(message, dict) and isinstance(message.get("content"), str):
        for key in ("thinking_content", "reasoning_content", "reasoning"):
            value = message.get(key)
            if isinstance(value, str) and value.strip():
                thinking = value
                break
        return message["content"], thinking
    if isinstance(first.get("text"), str):
        return first["text"], thinking
    return None, thinking


def _redact_secret(text: str, secret: str | None) -> str:
    if secret:
        return text.replace(secret, "[redacted]")
    return text
