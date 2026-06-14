import pytest

from services.api.app.artifacts.schema import (
    artifact_to_response,
    artifact_version_to_response,
    validate_artifact_input,
)
from services.api.app.shared.errors import ValidationError


def test_artifact_schema_accepts_a8_required_fields():
    artifact = validate_artifact_input(
        {
            "conversation_id": "conv_schema",
            "task_id": None,
            "created_by_run_id": None,
            "type": "document",
            "title": "Schema Artifact",
            "status": "available",
            "mime_type": "text/markdown",
        }
    )

    assert artifact == {
        "conversation_id": "conv_schema",
        "task_id": None,
        "created_by_run_id": None,
        "type": "document",
        "title": "Schema Artifact",
        "status": "available",
        "mime_type": "text/markdown",
    }


def test_artifact_schema_accepts_patch_as_review_gated_input():
    artifact = validate_artifact_input(
        {
            "conversation_id": "conv_schema",
            "type": "patch",
            "title": "Review gated patch",
            "mime_type": "text/x-diff",
        }
    )

    assert artifact["type"] == "patch"


def test_artifact_schema_rejects_diff_deploy_types():
    for artifact_type in ("diff", "deployment"):
        with pytest.raises(ValidationError) as exc_info:
            validate_artifact_input(
                {
                    "conversation_id": "conv_schema",
                    "type": artifact_type,
                    "title": "Out of Scope",
                    "mime_type": "text/plain",
                }
            )
        assert exc_info.value.code == "artifact_type_not_supported"


def test_artifact_and_version_response_shapes_include_uri_and_storage_key():
    artifact = artifact_to_response(
        {
            "id": "art_schema",
            "conversation_id": "conv_schema",
            "task_id": None,
            "created_by_run_id": "run_schema",
            "type": "document",
            "title": "Schema Artifact",
            "status": "available",
            "mime_type": "text/markdown",
            "storage_key": "run/conv/art/v1.bin",
            "current_version_id": "artv_schema",
            "version": 1,
            "checksum": "sha256:abc",
            "created_at": "2026-06-11T00:00:00.000000Z",
        }
    )
    version = artifact_version_to_response(
        {
            "id": "artv_schema",
            "artifact_id": "art_schema",
            "version": 1,
            "storage_key": "run/conv/art/v1.bin",
            "checksum": "sha256:abc",
            "parent_version_id": None,
            "created_at": "2026-06-11T00:00:00.000000Z",
        }
    )

    for key in (
        "id",
        "conversation_id",
        "task_id",
        "created_by_run_id",
        "type",
        "title",
        "status",
        "mime_type",
        "storage_key",
        "created_at",
    ):
        assert key in artifact
    for key in ("artifact_id", "version", "storage_key", "checksum", "parent_version_id", "created_at"):
        assert key in version
    assert artifact["uri"] == "artifact://art_schema"
    assert version["uri"] == "artifact://art_schema/versions/1"
