import pytest

from services.api.app.artifacts.schema import (
    validate_artifact_input,
    validate_diff_artifact_type,
    validate_diff_request,
)
from services.api.app.shared.errors import ValidationError


def test_diff_schema_accepts_preview_artifact_types():
    assert validate_diff_artifact_type(None) == "diff_preview"
    assert validate_diff_artifact_type("source_diff") == "source_diff"
    artifact = validate_artifact_input(
        {
            "conversation_id": "conv_diff_schema",
            "type": "diff_preview",
            "title": "Preview",
            "mime_type": "application/vnd.agenthub.diff+json",
        }
    )

    assert artifact["type"] == "diff_preview"


def test_diff_schema_accepts_patch_apply_artifact_types_as_review_gated_inputs():
    for artifact_type in ("patch", "diff_patch"):
        artifact = validate_artifact_input(
            {
                "conversation_id": "conv_diff_schema",
                "type": artifact_type,
                "title": "Patch Input",
                "mime_type": "text/x-diff",
            }
        )
        assert artifact["type"] == artifact_type


def test_diff_schema_rejects_deployment_artifact_types():
    for artifact_type in ("deployment", "deployment_release"):
        with pytest.raises(ValidationError) as exc_info:
            validate_artifact_input(
                {
                    "conversation_id": "conv_diff_schema",
                    "type": artifact_type,
                    "title": "Out of Scope",
                    "mime_type": "text/plain",
                }
            )
        assert exc_info.value.code == "artifact_type_not_supported"


def test_diff_request_schema_requires_base_and_target_versions():
    request = validate_diff_request(
        {
            "base_artifact_id": "art_base",
            "base_version_id": "artv_base",
            "target_artifact_id": "art_target",
            "target_version_id": "artv_target",
            "title": "Source diff",
            "path": "app.py",
            "base_checksum": "sha256:base",
            "target_checksum": "sha256:target",
        }
    )

    assert request == {
        "base_artifact_id": "art_base",
        "base_version_id": "artv_base",
        "target_artifact_id": "art_target",
        "target_version_id": "artv_target",
        "type": "diff_preview",
        "title": "Source diff",
        "path": "app.py",
        "base_checksum": "sha256:base",
        "target_checksum": "sha256:target",
    }


def test_diff_request_schema_rejects_unsupported_type():
    with pytest.raises(ValidationError) as exc_info:
        validate_diff_request(
            {
                "base_artifact_id": "art_base",
                "base_version_id": "artv_base",
                "target_artifact_id": "art_target",
                "target_version_id": "artv_target",
                "type": "patch",
            }
        )

    assert exc_info.value.code == "artifact_diff_type_not_supported"
