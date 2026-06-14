from __future__ import annotations

import os
import time
from typing import Any

from services.api.app.agent_runs.events import (
    PROVIDER_NOT_CONFIGURED,
    adapter_error_payload,
    provider_not_configured_payload,
    run_failed_payload,
)
from services.api.app.agent_runs.repository import (
    append_run_event,
    create_message_run,
    create_plan_step_run,
    fail_run,
    get_run,
    mark_run_content_issue,
    mark_run_started,
    prepare_plan_step_retry,
    succeed_run,
)
from services.api.app.agent_runs.schema import AgentRunRequest, run_to_response, validate_agent_run_request
from services.api.app.agent_runs.content import (
    FINAL_CONTENT_EMPTY,
    SUCCEEDED,
    content_payload,
    run_content_error_payload,
    split_agent_content,
    validate_final_content,
)
from services.api.app.agents.adapter_health import AdapterHealth, adapter_health
from services.api.app.agents.adapter_registry import AdapterRegistry
from services.api.app.agents.repository import get_agent_profiles_by_ids
from services.api.app.artifacts.diff_service import create_diff_artifact_from_request
from services.api.app.artifacts.office import DOCX_MIME_TYPE, PPTX_MIME_TYPE
from services.api.app.artifacts.repository import create_artifact, create_artifact_from_agent_output, list_artifacts
from services.api.app.conversations.repository import create_assistant_message, get_message
from services.api.app.memory.context_builder import (
    build_context_bundle_for_message,
    build_context_bundle_for_plan_step,
    ref_for_context_bundle,
    summarize_context_bundle,
)
from services.api.app.shared.errors import ValidationError


_TRANSIENT_RETRYABLE_CODES = {
    "adapter_process_failed",
    "adapter_timeout",
    "backend_network_failed",
    "backend_rate_limited",
    "opencode_server_unavailable",
    "run_timed_out",
}
_NON_RETRYABLE_CODES = {
    "adapter_auth_missing",
    "adapter_auth_unusable",
    "adapter_executable_not_found",
    "adapter_invalid_response",
    "adapter_unsupported_run_mode",
    "adapter_workspace_missing",
    "backend_auth_failed",
    "credential_invalid",
    "missing_credentials",
    "provider_not_configured",
}
_ARTIFACT_ACTION_MARKERS = (
    "attach",
    "create",
    "deliver",
    "download",
    "draft",
    "export",
    "generate",
    "build",
    "make",
    "produce",
    "return",
    "send",
    "write",
    "下载",
    "创建",
    "导出",
    "发我",
    "给我",
    "交付",
    "生成",
    "输出",
    "返回",
    "提供",
    "写",
    "做",
    "制作",
    "准备",
    "产出",
)
_MARKDOWN_ARTIFACT_MARKERS = ("markdown", "readme", ".md", "md 文件", "md文档")
_PRESENTATION_ARTIFACT_MARKERS = (
    "ppt",
    "pptx",
    "powerpoint",
    "slide deck",
    "slides",
    "幻灯片",
    "演示稿",
    "演示文稿",
    "演示文档",
)
_WORD_ARTIFACT_MARKERS = (
    "word",
    "docx",
    ".docx",
    "doc 文档",
    "docx 文件",
    "docx文档",
    "office 文档",
    "word 文件",
    "word文档",
    "word 文档",
)
_GENERIC_DOCUMENT_ARTIFACT_MARKERS = ("报告", "方案", "简报", "说明书", "文档")


def create_run_from_body(body: dict[str, Any], *, test_run_id: str) -> dict[str, object]:
    source_type = _required_string(body, "source_type")
    if source_type == "message":
        _require_run_mode(body, "direct_response")
        if body.get("plan_step_id") is not None:
            raise ValidationError("source_type=message requires plan_step_id to be null.")
        source_message_id = _required_string(body, "source_message_id")
        instruction = _instruction(body)
        expected_artifacts = _expected_artifacts_from_body_or_instruction(body, instruction)
        context_bundle = _without_source_message(
            build_context_bundle_for_message(source_message_id, test_run_id=test_run_id),
            source_message_id,
        )
        context_summary = summarize_context_bundle(context_bundle)
        run = create_message_run(
            source_message_id=source_message_id,
            target_agent_id=_required_string(body, "target_agent_id"),
            instruction=instruction,
            context_bundle=context_bundle,
            workspace_ref=_optional_object(body.get("workspace_ref")),
            allowed_tools=_string_list_or_default(body.get("allowed_tools")),
            expected_artifacts=expected_artifacts,
            test_run_id=test_run_id,
            context_summary=context_summary,
            context_ref=ref_for_context_bundle(context_bundle),
        )
        response = _invoke_adapter_contract(
            run,
            instruction,
            _body_with_expected_artifacts(body, expected_artifacts),
            context_bundle=context_bundle,
            test_run_id=test_run_id,
        )
        response["context_summary"] = context_summary
        response["context_ref"] = ref_for_context_bundle(context_bundle)
        return response

    if source_type == "plan_step":
        _require_run_mode(body, "planned_step")
        plan_step_id = _required_string(body, "plan_step_id")
        instruction = _instruction(body)
        expected_artifacts = _expected_artifacts_from_body_or_instruction(body, instruction)
        context_bundle = build_context_bundle_for_plan_step(plan_step_id, test_run_id=test_run_id)
        context_summary = summarize_context_bundle(context_bundle)
        run = create_plan_step_run(
            plan_step_id=plan_step_id,
            target_agent_id=_optional_string(body.get("target_agent_id"), "target_agent_id"),
            source_message_id=_optional_string(body.get("source_message_id"), "source_message_id"),
            instruction=instruction,
            context_bundle=context_bundle,
            workspace_ref=_optional_object(body.get("workspace_ref")),
            allowed_tools=_string_list_or_default(body.get("allowed_tools")),
            expected_artifacts=expected_artifacts,
            test_run_id=test_run_id,
            context_summary=context_summary,
            context_ref=ref_for_context_bundle(context_bundle),
        )
        response = _invoke_adapter_contract(
            run,
            instruction,
            _body_with_expected_artifacts(body, expected_artifacts),
            context_bundle=context_bundle,
            test_run_id=test_run_id,
        )
        response["context_summary"] = context_summary
        response["context_ref"] = ref_for_context_bundle(context_bundle)
        return response

    raise ValidationError(f"Unsupported source_type: {source_type}")


def create_direct_response_run_for_message(
    message: dict[str, object],
    *,
    target_agent_id: str,
    test_run_id: str,
    instruction_override: str | None = None,
) -> dict[str, object]:
    instruction = instruction_override.strip() if isinstance(instruction_override, str) else ""
    if not instruction:
        content = message.get("content")
        if isinstance(content, dict) and isinstance(content.get("text"), str):
            instruction = content["text"].strip()
    if not instruction:
        instruction = f"Direct response for message {message['id']}"

    context_bundle = _without_source_message(
        build_context_bundle_for_message(str(message["id"]), test_run_id=test_run_id),
        str(message["id"]),
    )
    context_summary = summarize_context_bundle(context_bundle)
    expected_artifacts = _expected_artifacts_for_instruction(instruction)
    run = create_message_run(
        source_message_id=str(message["id"]),
        target_agent_id=target_agent_id,
        instruction=instruction,
        context_bundle=context_bundle,
        workspace_ref=None,
        allowed_tools=[],
        expected_artifacts=expected_artifacts,
        test_run_id=test_run_id,
        context_summary=context_summary,
        context_ref=ref_for_context_bundle(context_bundle),
    )
    response = _invoke_adapter_contract(
        run,
        instruction,
        {"expected_artifacts": expected_artifacts},
        context_bundle=context_bundle,
        test_run_id=test_run_id,
    )
    response["context_summary"] = context_summary
    response["context_ref"] = ref_for_context_bundle(context_bundle)
    return response


def retry_run_from_body(run_id: str, body: dict[str, Any], *, test_run_id: str) -> dict[str, object]:
    del body
    original = get_run(run_id, test_run_id=test_run_id)
    if original["status"] not in {"failed", "incomplete", "final_content_empty"}:
        raise ValidationError("Only failed or incomplete AgentRuns can be retried.", code="agent_run_not_retryable")

    if original["source_type"] == "message":
        source_message_id = str(original.get("source_message_id") or "")
        if not source_message_id:
            raise ValidationError("Original AgentRun is missing source_message_id.", code="agent_run_not_retryable")
        retry = create_run_from_body(
            {
                "source_type": "message",
                "source_message_id": source_message_id,
                "target_agent_id": str(original["target_agent_id"]),
                "run_mode": "direct_response",
                "instruction": _message_instruction(source_message_id, test_run_id=test_run_id),
            },
            test_run_id=test_run_id,
        )
        retry["retry_of_run_id"] = run_id
        return retry

    if original["source_type"] == "plan_step":
        plan_step_id = str(original.get("plan_step_id") or "")
        if not plan_step_id:
            raise ValidationError("Original AgentRun is missing plan_step_id.", code="agent_run_not_retryable")
        prepare_plan_step_retry(plan_step_id, test_run_id=test_run_id)
        retry = create_run_from_body(
            {
                "source_type": "plan_step",
                "plan_step_id": plan_step_id,
                "source_message_id": original.get("source_message_id"),
                "target_agent_id": str(original["target_agent_id"]),
                "run_mode": "planned_step",
                "instruction": f"Retry plan step {plan_step_id}.",
            },
            test_run_id=test_run_id,
        )
        retry["retry_of_run_id"] = run_id
        return retry

    raise ValidationError("Unsupported AgentRun source_type for retry.", code="agent_run_not_retryable")


def _message_instruction(message_id: str, *, test_run_id: str) -> str:
    message = get_message(message_id, test_run_id=test_run_id)
    content = message.get("content")
    if isinstance(content, dict) and isinstance(content.get("text"), str) and content["text"].strip():
        return content["text"].strip()
    return f"Retry direct response for message {message_id}."


def _without_source_message(context_bundle: dict[str, object], message_id: str) -> dict[str, object]:
    recent = context_bundle.get("recent_messages")
    if not isinstance(recent, list):
        return context_bundle
    trimmed = [
        item
        for item in recent
        if not (isinstance(item, dict) and str(item.get("id") or "") == message_id)
    ]
    if len(trimmed) == len(recent):
        return context_bundle
    next_bundle = dict(context_bundle)
    next_bundle["recent_messages"] = trimmed
    next_bundle["context_summary"] = summarize_context_bundle(next_bundle)
    return next_bundle


def _invoke_adapter_contract(
    run: dict[str, object],
    instruction: str,
    body: dict[str, Any],
    *,
    context_bundle: dict[str, object],
    test_run_id: str,
) -> dict[str, object]:
    mark_run_started(str(run["id"]), test_run_id=test_run_id)
    run = get_run(str(run["id"]), test_run_id=test_run_id)
    request = _adapter_request(run, instruction, body, context_bundle=context_bundle)
    registry = AdapterRegistry()
    agent = _agent(str(run["target_agent_id"]))
    adapter = registry.adapter_for_agent(agent)
    health = _run_preflight_health(registry, agent, adapter)
    if not health.configured and not (
        _should_invoke_cli_after_health_failure(request, agent, health)
        or _should_invoke_after_transient_health_failure(agent, health)
    ):
        return _fail_from_health(run, health, test_run_id=test_run_id)

    max_retries = _max_transient_stage_retries()
    attempt = 1
    while True:
        completed_text: str | None = None
        completed_content: dict[str, object] | None = None
        completed_content_status = SUCCEEDED
        completed_content_error: dict[str, object] | None = None
        last_error_payload: dict[str, object] | None = None
        produced_artifacts: list[dict[str, object]] = []
        artifact_references: list[dict[str, object]] = []
        retry_requested = False

        for event in adapter.invoke(request):
            if event.type == "run_started":
                continue
            if event.type == "assistant_message_completed":
                content_text = event.payload.get("content_text")
                explicit_thinking = _explicit_thinking_from_payload(event.payload)
                if isinstance(content_text, str) and (content_text.strip() or explicit_thinking):
                    split = split_agent_content(
                        content_text,
                        explicit_thinking_content=explicit_thinking,
                    )
                    validation = validate_final_content(
                        split,
                        request_instruction=request.instruction,
                        context_bundle=request.context_bundle,
                        target_agent=agent,
                    )
                    completed_text = split.final_content
                    completed_content = content_payload(split, validation, run_id=str(run["id"]))
                    completed_content_status = validation.status
                    if validation.error_code:
                        completed_content_error = run_content_error_payload(split, validation, run=run)
                append_run_event(
                    str(run["id"]),
                    event_type=event.type,
                    payload={
                        **event.payload,
                        **(completed_content or {}),
                        "content_text": completed_text if completed_text is not None else event.payload.get("content_text"),
                    },
                    test_run_id=test_run_id,
                )
                continue
            if event.type == "artifact_created":
                try:
                    artifact = _create_artifact_from_adapter_event(
                        event.payload,
                        run,
                        test_run_id=test_run_id,
                    )
                except ValidationError as exc:
                    payload = _failure_payload_from_event(
                        {
                            "error_code": getattr(exc, "code", "adapter_artifact_failed"),
                            "message": str(exc),
                            "recovery_hint": "Inspect adapter artifact_created payload and Artifact protocol.",
                        },
                        run,
                        default_error_code="adapter_artifact_failed",
                    )
                    append_run_event(
                        str(run["id"]),
                        event_type="adapter_error",
                        payload=payload,
                        test_run_id=test_run_id,
                    )
                    failed = fail_run(
                        str(run["id"]),
                        error_code=str(payload["error_code"]),
                        payload=payload,
                        test_run_id=test_run_id,
                    )
                    return run_to_response(failed)
                produced_artifacts.append(artifact)
                reference = {
                    "type": "artifact",
                    "artifact_id": artifact["id"],
                    "version": artifact.get("version"),
                    "title": artifact.get("title"),
                }
                artifact_references.append(reference)
                append_run_event(
                    str(run["id"]),
                    event_type=event.type,
                    payload={**event.payload, "artifact_id": artifact["id"]},
                    test_run_id=test_run_id,
                )
                continue
            if event.type == PROVIDER_NOT_CONFIGURED:
                append_run_event(
                    str(run["id"]),
                    event_type=event.type,
                    payload=event.payload,
                    test_run_id=test_run_id,
                )
                payload = _failure_payload_from_event(event.payload, run)
                failed = fail_run(
                    str(run["id"]),
                    error_code=str(payload["error_code"]),
                    payload=payload,
                    test_run_id=test_run_id,
                )
                return run_to_response(failed)
            if event.type == "adapter_error":
                last_error_payload = _failure_payload_from_event(event.payload, run)
                append_run_event(
                    str(run["id"]),
                    event_type=event.type,
                    payload=event.payload,
                    test_run_id=test_run_id,
                )
                continue
            if event.type == "run_timed_out":
                payload = _failure_payload_from_event(event.payload, run, default_error_code="run_timed_out")
                if _should_retry_stage_failure(payload, attempt=attempt, max_retries=max_retries, produced_artifacts=produced_artifacts):
                    _append_stage_retry_event(run, payload, attempt=attempt, max_retries=max_retries, test_run_id=test_run_id)
                    retry_requested = True
                    break
                append_run_event(
                    str(run["id"]),
                    event_type=event.type,
                    payload=event.payload,
                    test_run_id=test_run_id,
                )
                failed = fail_run(
                    str(run["id"]),
                    error_code=str(payload["error_code"]),
                    payload=payload,
                    test_run_id=test_run_id,
                )
                return run_to_response(failed)
            if event.type == "run_failed":
                payload = _failure_payload_from_event(event.payload, run)
                if last_error_payload is not None and payload["error_code"] == "adapter_process_failed":
                    payload = {**payload, "error_code": last_error_payload["error_code"]}
                if _should_retry_stage_failure(payload, attempt=attempt, max_retries=max_retries, produced_artifacts=produced_artifacts):
                    _append_stage_retry_event(run, payload, attempt=attempt, max_retries=max_retries, test_run_id=test_run_id)
                    retry_requested = True
                    break
                failed = fail_run(
                    str(run["id"]),
                    error_code=str(payload["error_code"]),
                    payload=payload,
                    test_run_id=test_run_id,
                )
                return run_to_response(failed)
            if event.type == "run_succeeded":
                if request.run_mode == "direct_response" and completed_content is None:
                    return _fail_invalid_success_without_message(run, test_run_id=test_run_id)
                if (
                    request.run_mode == "direct_response"
                    and completed_content is not None
                    and completed_content_status != SUCCEEDED
                ):
                    assistant_message = create_assistant_message(
                        conversation_id=str(run["conversation_id"]),
                        sender_id=str(run["target_agent_id"]),
                        content_text=str(completed_content.get("final_content") or ""),
                        created_by_run_id=str(run["id"]),
                        reply_to_id=run["source_message_id"] if isinstance(run.get("source_message_id"), str) else None,
                        test_run_id=test_run_id,
                        artifact_references=artifact_references,
                        structured_content=completed_content,
                    )
                    payload = completed_content_error or {
                        "error_code": completed_content_status,
                        "message": "Agent final_content did not pass validation.",
                        "target_agent_id": str(run["target_agent_id"]),
                    }
                    marked = mark_run_content_issue(
                        str(run["id"]),
                        status=FINAL_CONTENT_EMPTY if completed_content_status == FINAL_CONTENT_EMPTY else "incomplete",
                        error_code=str(payload["error_code"]),
                        payload=payload,
                        test_run_id=test_run_id,
                    )
                    response = run_to_response(marked)
                    response["assistant_message"] = assistant_message
                    return response
                succeeded = succeed_run(
                    str(run["id"]),
                    payload=event.payload,
                    test_run_id=test_run_id,
                )
                response = run_to_response(succeeded)
                if request.run_mode == "direct_response" and completed_text:
                    artifact = _create_artifact_for_direct_response_success(
                        succeeded,
                        completed_text,
                        request.expected_artifacts,
                        test_run_id=test_run_id,
                    )
                    if artifact is not None:
                        produced_artifacts.append(artifact)
                        artifact_references.append(
                            {
                                "type": "artifact",
                                "artifact_id": artifact["id"],
                                "version": artifact.get("version"),
                                "title": artifact.get("title"),
                            }
                        )
                    diff_artifact = _try_create_diff_for_artifact(
                        artifact,
                        conversation_id=str(run["conversation_id"]),
                        created_by_run_id=str(run["id"]),
                        test_run_id=test_run_id,
                    )
                    if diff_artifact is not None:
                        artifact_references.append(
                            {
                                "type": "artifact",
                                "artifact_id": diff_artifact["id"],
                                "version": diff_artifact.get("version"),
                                "title": diff_artifact.get("title"),
                            }
                        )
                    assistant_message = create_assistant_message(
                        conversation_id=str(run["conversation_id"]),
                        sender_id=str(run["target_agent_id"]),
                        content_text=completed_text,
                        created_by_run_id=str(run["id"]),
                        reply_to_id=run["source_message_id"] if isinstance(run.get("source_message_id"), str) else None,
                        test_run_id=test_run_id,
                        artifact_references=artifact_references,
                        structured_content=completed_content,
                    )
                    response["assistant_message"] = assistant_message
                    if produced_artifacts:
                        response["artifacts"] = produced_artifacts
                    if artifact is not None:
                        response["artifact"] = artifact
                    if diff_artifact is not None:
                        response["diff_artifact"] = diff_artifact
                        produced_artifacts.append(diff_artifact)
                return response
            append_run_event(
                str(run["id"]),
                event_type=event.type,
                payload=event.payload,
                test_run_id=test_run_id,
            )

        if retry_requested:
            _sleep_before_stage_retry(attempt)
            attempt += 1
            continue

        if last_error_payload is not None:
            if _should_retry_stage_failure(
                last_error_payload,
                attempt=attempt,
                max_retries=max_retries,
                produced_artifacts=produced_artifacts,
            ):
                _append_stage_retry_event(run, last_error_payload, attempt=attempt, max_retries=max_retries, test_run_id=test_run_id)
                _sleep_before_stage_retry(attempt)
                attempt += 1
                continue
            failed = fail_run(
                str(run["id"]),
                error_code=str(last_error_payload["error_code"]),
                payload=last_error_payload,
                test_run_id=test_run_id,
            )
            return run_to_response(failed)
        return _fail_invalid_success_without_message(run, test_run_id=test_run_id)


def _create_artifact_for_direct_response_success(
    run: dict[str, object],
    completed_text: str,
    expected_artifacts: list[dict[str, object]],
    *,
    test_run_id: str,
) -> dict[str, object] | None:
    if not completed_text.strip() or not expected_artifacts:
        return None
    try:
        return create_artifact_from_agent_output(
            run=run,
            content_text=completed_text,
            expected_artifacts=expected_artifacts,
            test_run_id=test_run_id,
        )
    except ValidationError as exc:
        if getattr(exc, "code", None) in {"artifact_secret_forbidden", "artifact_type_not_supported"}:
            return None
        raise


def _create_artifact_from_adapter_event(
    payload: dict[str, object],
    run: dict[str, object],
    *,
    test_run_id: str,
) -> dict[str, object]:
    artifact_type = _payload_string(payload, "artifact_type") or _payload_string(payload, "type")
    title = _payload_string(payload, "title")
    mime_type = _payload_string(payload, "mime_type") or "text/plain"
    content = _payload_string(payload, "content")
    if artifact_type is None or title is None or content is None:
        raise ValidationError(
            "artifact_created event must include artifact_type, title, mime_type, and content.",
            code="adapter_artifact_event_invalid",
        )
    return create_artifact(
        conversation_id=str(run["conversation_id"]),
        artifact_type=artifact_type,
        title=title,
        mime_type=mime_type,
        content=content,
        task_id=None,
        created_by_run_id=str(run["id"]),
        test_run_id=test_run_id,
    )


def _payload_string(payload: dict[str, object], key: str) -> str | None:
    value = payload.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _explicit_thinking_from_payload(payload: dict[str, object]) -> str | None:
    for key in ("thinking_content", "reasoning_content", "reasoning"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _should_invoke_cli_after_health_failure(
    request: AgentRunRequest,
    agent: dict[str, object],
    health: AdapterHealth,
) -> bool:
    if request.run_mode != "direct_response":
        return False
    if agent.get("configured") is not True or agent.get("execution_enabled") is not True:
        return False
    if health.adapter_kind not in {"codex_cli", "claude_code_cli"}:
        return False
    return health.error_code in {
        "backend_auth_failed",
        "adapter_auth_missing",
        "adapter_auth_unusable",
        "adapter_timeout",
    }


def _should_invoke_after_transient_health_failure(agent: dict[str, object], health: AdapterHealth) -> bool:
    if agent.get("configured") is not True or agent.get("execution_enabled") is not True:
        return False
    return _is_retryable_error_code(health.error_code)


def _run_preflight_health(registry: AdapterRegistry, agent: dict[str, object], adapter: object) -> AdapterHealth:
    if agent.get("configured") is True and agent.get("execution_enabled") is True:
        return adapter_health(
            provider=_optional_text(agent.get("provider")),
            adapter_kind=str(getattr(adapter, "adapter_id", None) or agent.get("adapter_kind") or "custom_openai"),
            configured=True,
            status="ready",
            error_code=None,
            recovery_hint=None,
            capabilities=_safe_string_list(agent.get("capability_tags")),
            message="Using cached Agent profile readiness for run preflight.",
        )
    return registry.health_for_agent(agent)


def _optional_text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _safe_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item.strip()]


def _max_transient_stage_retries() -> int:
    raw = os.getenv("AGENTHUB_STAGE_RETRY_ATTEMPTS")
    try:
        value = int(raw) if raw is not None else 2
    except ValueError:
        value = 2
    return max(0, min(value, 5))


def _retry_backoff_seconds(attempt: int) -> float:
    raw = os.getenv("AGENTHUB_STAGE_RETRY_BACKOFF_SECONDS")
    try:
        base = float(raw) if raw is not None else 0.75
    except ValueError:
        base = 0.75
    return max(0.0, min(base * attempt, 5.0))


def _sleep_before_stage_retry(attempt: int) -> None:
    delay = _retry_backoff_seconds(attempt)
    if delay > 0:
        time.sleep(delay)


def _should_retry_stage_failure(
    payload: dict[str, object],
    *,
    attempt: int,
    max_retries: int,
    produced_artifacts: list[dict[str, object]],
) -> bool:
    if attempt > max_retries or produced_artifacts:
        return False
    error_code = payload.get("error_code") if isinstance(payload.get("error_code"), str) else None
    if error_code in _NON_RETRYABLE_CODES:
        return False
    if _is_retryable_error_code(error_code):
        return True
    message = str(payload.get("message") or "").lower()
    retry_markers = (
        "connection",
        "disconnect",
        "network",
        "rate limit",
        "temporar",
        "timeout",
        "timed out",
        "unreachable",
        "429",
    )
    return bool(message and any(marker in message for marker in retry_markers))


def _is_retryable_error_code(error_code: str | None) -> bool:
    if not error_code or error_code in _NON_RETRYABLE_CODES:
        return False
    return error_code in _TRANSIENT_RETRYABLE_CODES


def _append_stage_retry_event(
    run: dict[str, object],
    payload: dict[str, object],
    *,
    attempt: int,
    max_retries: int,
    test_run_id: str,
) -> None:
    append_run_event(
        str(run["id"]),
        event_type="backend_retry",
        payload={
            "backend": payload.get("provider") or run.get("target_agent_id"),
            "retry_scope": "stage",
            "run_id": run["id"],
            "attempt": attempt,
            "next_attempt": attempt + 1,
            "max_retries": max_retries,
            "error_code": payload.get("error_code"),
            "message": payload.get("message") or "Transient stage failure; retrying.",
            "recovery_hint": payload.get("recovery_hint"),
        },
        test_run_id=test_run_id,
    )


def _adapter_request(
    run: dict[str, object],
    instruction: str,
    body: dict[str, Any],
    *,
    context_bundle: dict[str, object],
) -> AgentRunRequest:
    return validate_agent_run_request(
        {
            "run_id": run["id"],
            "conversation_id": run["conversation_id"],
            "source_type": run["source_type"],
            "source_message_id": run["source_message_id"],
            "plan_step_id": run["plan_step_id"],
            "target_agent_id": run["target_agent_id"],
            "run_mode": run["run_mode"],
            "instruction": instruction,
            "context_bundle": context_bundle,
            "workspace_ref": _optional_object(body.get("workspace_ref")),
            "allowed_tools": _string_list_or_default(body.get("allowed_tools")),
            "expected_artifacts": _expected_artifacts_from_body_or_instruction(body, instruction),
        }
    )


def _agent(agent_id: str) -> dict[str, object]:
    agents = get_agent_profiles_by_ids([agent_id])
    if not agents:
        raise ValidationError(f"Unknown target agent: {agent_id}", code="unknown_agent")
    return agents[0]


def _fail_from_health(
    run: dict[str, object],
    health: AdapterHealth,
    *,
    test_run_id: str,
) -> dict[str, object]:
    if health.status == "not_configured" or health.error_code == PROVIDER_NOT_CONFIGURED:
        failure_payload = provider_not_configured_payload(
            target_agent_id=str(run["target_agent_id"]),
            provider=health.provider,
        )
        append_run_event(
            str(run["id"]),
            event_type=PROVIDER_NOT_CONFIGURED,
            payload=failure_payload,
            test_run_id=test_run_id,
        )
        failed = fail_run(
            str(run["id"]),
            error_code=PROVIDER_NOT_CONFIGURED,
            payload=failure_payload,
            test_run_id=test_run_id,
        )
        return run_to_response(failed)

    payload = adapter_error_payload(
        error_code=health.error_code or health.status,
        message=health.message or "Adapter is not ready for real provider work.",
        provider=health.provider,
        target_agent_id=str(run["target_agent_id"]),
        recovery_hint=health.recovery_hint,
    )
    append_run_event(
        str(run["id"]),
        event_type="adapter_error",
        payload=payload,
        test_run_id=test_run_id,
    )
    failed = fail_run(
        str(run["id"]),
        error_code=str(payload["error_code"]),
        payload=payload,
        test_run_id=test_run_id,
    )
    return run_to_response(failed)


def _failure_payload_from_event(
    payload: dict[str, object],
    run: dict[str, object],
    *,
    default_error_code: str = "adapter_process_failed",
) -> dict[str, object]:
    error_code = payload.get("error_code") if isinstance(payload.get("error_code"), str) else default_error_code
    message = payload.get("message") if isinstance(payload.get("message"), str) else "Adapter run failed."
    provider = payload.get("provider") if isinstance(payload.get("provider"), str) else None
    recovery_hint = payload.get("recovery_hint") if isinstance(payload.get("recovery_hint"), str) else None
    failure = run_failed_payload(
        error_code=error_code,
        message=message,
        provider=provider,
        target_agent_id=str(run["target_agent_id"]),
        recovery_hint=recovery_hint,
    )
    for key in ("exit_code", "stderr_summary", "stdout_summary", "backend_retry_seen", "manual_retry_env"):
        if key in payload:
            failure[key] = payload[key]
    return failure


def _fail_invalid_success_without_message(
    run: dict[str, object],
    *,
    test_run_id: str,
) -> dict[str, object]:
    payload = run_failed_payload(
        error_code="adapter_invalid_response",
        message="Adapter did not produce a completed assistant message before terminal success.",
        provider=None,
        target_agent_id=str(run["target_agent_id"]),
        recovery_hint="Require assistant_message_completed before run_succeeded for direct_response.",
    )
    append_run_event(str(run["id"]), event_type="adapter_error", payload=payload, test_run_id=test_run_id)
    failed = fail_run(
        str(run["id"]),
        error_code="adapter_invalid_response",
        payload=payload,
        test_run_id=test_run_id,
    )
    return run_to_response(failed)


def _required_string(body: dict[str, Any], field: str) -> str:
    value = body.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field} must be a non-empty string.")
    return value


def _require_run_mode(body: dict[str, Any], expected: str) -> None:
    run_mode = _required_string(body, "run_mode")
    if run_mode != expected:
        raise ValidationError(f"source_type={body.get('source_type')} requires run_mode={expected}.")


def _optional_string(value: object, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field} must be a non-empty string when provided.")
    return value


def _instruction(body: dict[str, Any]) -> str:
    value = body.get("instruction")
    if isinstance(value, str) and value.strip():
        return value.strip()
    if body.get("source_type") == "plan_step":
        return f"Execute plan step {body.get('plan_step_id')}"
    return "Run direct response."


def _object_or_default(value: object) -> dict[str, object]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValidationError("context_bundle must be an object.")
    return dict(value)


def _optional_object(value: object) -> dict[str, object] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValidationError("workspace_ref must be an object when provided.")
    return dict(value)


def _string_list_or_default(value: object) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValidationError("allowed_tools must be a list of non-empty strings.")
    return list(value)


def _object_list_or_default(value: object) -> list[dict[str, object]]:
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ValidationError("expected_artifacts must be a list of objects.")
    return [dict(item) for item in value]


def _expected_artifacts_from_body_or_instruction(body: dict[str, Any], instruction: str) -> list[dict[str, object]]:
    explicit = _object_list_or_default(body.get("expected_artifacts"))
    if explicit:
        return explicit
    return _expected_artifacts_for_instruction(instruction)


def _body_with_expected_artifacts(body: dict[str, Any], expected_artifacts: list[dict[str, object]]) -> dict[str, Any]:
    next_body = dict(body)
    next_body["expected_artifacts"] = [dict(item) for item in expected_artifacts]
    return next_body


def _try_create_diff_for_artifact(
    artifact: dict[str, object] | None,
    *,
    conversation_id: str,
    created_by_run_id: str,
    test_run_id: str,
) -> dict[str, object] | None:
    if artifact is None:
        return None
    artifact_id = str(artifact.get("id", ""))
    artifact_title = str(artifact.get("title", ""))
    artifact_type = str(artifact.get("type", ""))
    if not artifact_id or not artifact_title:
        return None
    existing = list_artifacts(
        test_run_id=test_run_id,
        conversation_id=conversation_id,
        artifact_type=artifact_type,
    )
    base_candidates = [
        a for a in existing
        if str(a.get("id")) != artifact_id
        and str(a.get("title")) == artifact_title
        and a.get("current_version_id")
    ]
    if not base_candidates:
        return None
    base = base_candidates[-1]
    current_version_id = artifact.get("current_version_id")
    base_version_id = base.get("current_version_id")
    if not current_version_id or not base_version_id:
        return None
    try:
        return create_diff_artifact_from_request(
            {
                "base_artifact_id": str(base["id"]),
                "base_version_id": str(base_version_id),
                "target_artifact_id": artifact_id,
                "target_version_id": str(current_version_id),
                "title": f"Diff: {artifact_title}",
                "type": "source_diff",
                "path": artifact_title,
            },
            test_run_id=test_run_id,
        )
    except ValidationError:
        return None
    except Exception:
        return None


def _expected_artifacts_for_instruction(instruction: str) -> list[dict[str, object]]:
    normalized = instruction.lower()
    if not _has_artifact_delivery_intent(instruction, normalized):
        return []
    if _contains_any(normalized, _PRESENTATION_ARTIFACT_MARKERS):
        return [
            {
                "type": "presentation",
                "title": _artifact_title_from_instruction(instruction, default="AgentHub Presentation.pptx", extension=".pptx"),
                "mime_type": PPTX_MIME_TYPE,
            }
        ]
    if _contains_any(normalized, _MARKDOWN_ARTIFACT_MARKERS):
        return [
            {
                "type": "markdown_doc",
                "title": _artifact_title_from_instruction(instruction, default="AgentHub Notes.md", extension=".md"),
                "mime_type": "text/markdown",
            }
        ]
    if _contains_any(normalized, _WORD_ARTIFACT_MARKERS) or _contains_any(instruction, _GENERIC_DOCUMENT_ARTIFACT_MARKERS):
        return [
            {
                "type": "word_doc",
                "title": _artifact_title_from_instruction(instruction, default="AgentHub Document.docx", extension=".docx"),
                "mime_type": DOCX_MIME_TYPE,
            }
        ]
    return []


def _has_artifact_delivery_intent(instruction: str, normalized: str) -> bool:
    if _contains_any(normalized, (".docx", ".pptx", ".md")):
        return True
    return _contains_any(normalized, _ARTIFACT_ACTION_MARKERS) or _contains_any(instruction, _ARTIFACT_ACTION_MARKERS)


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)


def _artifact_title_from_instruction(instruction: str, *, default: str, extension: str) -> str:
    clean = " ".join(instruction.replace("@", " ").split())
    if not clean:
        return default
    clean = clean[:60].strip(" ._-")
    if not clean:
        return default
    return clean if clean.lower().endswith(extension) else f"{clean}{extension}"
