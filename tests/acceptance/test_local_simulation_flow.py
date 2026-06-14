from services.api.app.demo.simulate import run_simulation


def test_local_simulation_report_shape_and_missing_config_paths(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENTHUB_PROFILE", "demo")
    monkeypatch.setenv("AGENTHUB_ENV", "demo")
    monkeypatch.setenv("AGENTHUB_DB_PATH", str(tmp_path / "simulation.sqlite3"))
    monkeypatch.setenv("AGENTHUB_ARTIFACT_STORE_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("AGENTHUB_STATIC_DEPLOY_DIR", str(tmp_path / "static"))
    monkeypatch.setenv("AGENTHUB_TURN_ROUTER_BACKEND", "disabled")
    monkeypatch.setenv("AGENTHUB_CUSTOM_OPENAI_API_BASE", "")
    monkeypatch.setenv("AGENTHUB_CUSTOM_OPENAI_MODEL", "")
    monkeypatch.setenv("AGENTHUB_CUSTOM_OPENAI_API_KEY", "")
    monkeypatch.setenv("AGENTHUB_CODEX_EXECUTABLE", str(tmp_path / "missing-codex.exe"))

    report = run_simulation(profile="demo")

    assert report["profile"] == "demo"
    assert report["router_mode"] == "test"
    assert report["model_provider_case"]["conversation_id"]
    assert report["model_provider_case"]["message_id"]
    assert report["model_provider_case"]["run_id"]
    assert report["model_provider_case"]["status"] == "failed"
    assert report["model_provider_case"]["error_code"] in {
        "provider_not_configured",
        "credential_missing",
        "missing_credentials",
    }
    assert report["codex_case"]["status"] in {"failed", "blocked"}
    assert report["codex_case"]["error_code"]
    assert report["blocked_case"]["status"] == "blocked"
    assert report["blocked_case"]["run_created"] is False
    assert report["context_case"]["context_built"] is True
    assert report["context_case"]["pinned_count"] == 2
    assert report["context_case"]["artifact_ref_count"] == 1
    assert report["context_case"]["run_context_summary"]["pinned_count"] == 2
    assert report["event_counts"]["message.created"] >= 4
    assert report["event_counts"]["planner.decision_created"] >= 3
    assert report["event_counts"]["agent_run.created"] >= 1
    assert "model_provider_not_configured" in report["warnings"]
    assert "codex_cli_not_configured" in report["warnings"]
