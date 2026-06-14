from services.api.app.permissions import audit_repository


def test_audit_log_schema_stores_required_fields_and_payload_hash(unique_id):
    test_run_id = f"{unique_id}-audit-schema"
    payload = {"target_artifact_id": "art_target", "base_version_id": "artv_base"}

    audit_log = audit_repository.create_audit_log(
        actor_type="system",
        actor_id="agenthub",
        action_type="review_request.created",
        target_type="review_request",
        target_id="revreq_schema",
        payload=payload,
        test_run_id=test_run_id,
    )
    logs = audit_repository.list_audit_logs(test_run_id=test_run_id)

    assert logs == [audit_log]
    assert set(["id", "actor_type", "actor_id", "action_type", "target_type", "target_id", "payload_hash", "created_at"]).issubset(
        audit_log
    )
    assert audit_log["payload_hash"] == audit_repository.payload_hash(payload)
    assert audit_log["payload_hash"].startswith("sha256:")
    assert "target_artifact_id" not in audit_log
