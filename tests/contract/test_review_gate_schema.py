import pytest

from services.api.app.artifacts.schema import (
    PATCH_APPLICATION_STATUSES,
    REVIEW_DECISIONS,
    REVIEW_REQUEST_STATUSES,
    validate_review_decision_input,
)
from services.api.app.shared.errors import ValidationError


def test_review_gate_status_sets_are_explicit():
    assert REVIEW_REQUEST_STATUSES == {"pending", "approved", "rejected"}
    assert REVIEW_DECISIONS == {"approved", "rejected"}
    assert PATCH_APPLICATION_STATUSES == {"review_required", "applied", "rejected", "failed", "conflict"}


def test_review_decision_schema_accepts_comment_and_default_actor():
    decision = validate_review_decision_input({"decision": "approved", "comment": "Looks good."})

    assert decision == {
        "decision": "approved",
        "decided_by": "human",
        "comment": "Looks good.",
    }


def test_review_decision_schema_rejects_unknown_decision():
    with pytest.raises(ValidationError) as exc_info:
        validate_review_decision_input({"decision": "maybe"})

    assert exc_info.value.code == "artifact_invalid"
