import json

from services.api.app.shared.env_loader import build_effective_environ
from services.api.app.shared.settings import get_settings


MODEL_PROVIDER_ENV_NAMES = [
    "AGENTHUB_MODEL_PROVIDER",
    "AGENTHUB_DEMO_MODEL_PROVIDER",
    "AGENTHUB_PROVIDER_QWEN_API_BASE",
    "AGENTHUB_PROVIDER_QWEN_MODEL",
    "AGENTHUB_PROVIDER_QWEN_API_KEY",
    "AGENTHUB_QWEN_TURBO_API_BASE",
    "AGENTHUB_QWEN_TURBO_MODEL",
    "AGENTHUB_QWEN_TURBO_API_KEY",
    "AGENTHUB_QWEN_API_BASE",
    "AGENTHUB_QWEN_MODEL",
    "AGENTHUB_QWEN_API_KEY",
    "AGENTHUB_CUSTOM_OPENAI_API_BASE",
    "AGENTHUB_CUSTOM_OPENAI_MODEL",
    "AGENTHUB_CUSTOM_OPENAI_API_KEY",
]


def _clear_model_provider_env(monkeypatch):
    for name in MODEL_PROVIDER_ENV_NAMES:
        monkeypatch.setenv(name, "")


# ---------------------------------------------------------------------------
# Core loading tests (preserved)
# ---------------------------------------------------------------------------

def test_demo_env_file_loads(tmp_path):
    config = tmp_path / "config"
    config.mkdir()
    (config / "agenthub.demo.env").write_text(
        "AGENTHUB_ENV=demo\nAGENTHUB_DB_PATH=var/from-demo.sqlite3\nPORT=19001\n",
        encoding="utf-8",
    )

    environ, loaded = build_effective_environ(profile="demo", environ={}, root=tmp_path)

    assert loaded.profile == "demo"
    assert environ["AGENTHUB_DB_PATH"] == "var/from-demo.sqlite3"
    assert environ["PORT"] == "19001"


def test_os_env_overrides_env_file(tmp_path):
    config = tmp_path / "config"
    config.mkdir()
    (config / "agenthub.demo.env").write_text("PORT=19001\nAGENTHUB_DB_PATH=var/file.sqlite3\n", encoding="utf-8")

    environ, _ = build_effective_environ(
        profile="demo",
        environ={"PORT": "19002", "AGENTHUB_DB_PATH": "var/os.sqlite3"},
        root=tmp_path,
    )

    assert environ["PORT"] == "19002"
    assert environ["AGENTHUB_DB_PATH"] == "var/os.sqlite3"


def test_explicit_env_file_overrides_profile_file(tmp_path):
    config = tmp_path / "config"
    config.mkdir()
    explicit = tmp_path / "local.env"
    (config / "agenthub.demo.env").write_text("PORT=19001\n", encoding="utf-8")
    explicit.write_text("PORT=19003\n", encoding="utf-8")

    environ, loaded = build_effective_environ(profile="demo", env_file=str(explicit), environ={}, root=tmp_path)

    assert environ["PORT"] == "19003"
    assert str(explicit) in loaded.files_loaded


def test_settings_public_dict_redacts_secret_values(monkeypatch, tmp_path):
    secret = "sk-test-secret-value"
    monkeypatch.setenv("AGENTHUB_PROFILE", "demo")
    monkeypatch.setenv("AGENTHUB_DB_PATH", str(tmp_path / "agenthub.sqlite3"))
    monkeypatch.setenv("AGENTHUB_TURN_ROUTER_API_KEY", secret)
    monkeypatch.setenv("AGENTHUB_TURN_ROUTER_BASE_URL", "https://router.example.test/v1")
    monkeypatch.setenv("AGENTHUB_TURN_ROUTER_MODEL", "router-model")

    public = get_settings().public_dict()
    blob = json.dumps(public)

    assert secret not in blob
    assert "turn_router_configured" in public


def test_qwen_provider_alias_configures_qwen_turbo(monkeypatch, tmp_path):
    _clear_model_provider_env(monkeypatch)
    secret = "sk-qwen-provider-secret"
    monkeypatch.setenv("AGENTHUB_PROFILE", "demo")
    monkeypatch.setenv("AGENTHUB_DB_PATH", str(tmp_path / "qwen-provider.sqlite3"))
    monkeypatch.setenv("AGENTHUB_MODEL_PROVIDER", "qwen_turbo")
    monkeypatch.setenv("AGENTHUB_PROVIDER_QWEN_API_BASE", "https://qwen-provider.example.test/v1")
    monkeypatch.setenv("AGENTHUB_PROVIDER_QWEN_MODEL", "qwen-turbo")
    monkeypatch.setenv("AGENTHUB_PROVIDER_QWEN_API_KEY", secret)

    settings = get_settings()
    public = settings.public_dict()
    blob = json.dumps(public)

    assert settings.model_agent_provider == "qwen_turbo"
    assert settings.model_agent_configured() is True
    assert settings.model_agent_api_base_alias == "AGENTHUB_PROVIDER_QWEN_API_BASE"
    assert settings.model_agent_model_alias == "AGENTHUB_PROVIDER_QWEN_MODEL"
    assert settings.model_agent_api_key_alias == "AGENTHUB_PROVIDER_QWEN_API_KEY"
    assert secret not in blob


def test_qwen_turbo_alias_configures_qwen_turbo(monkeypatch, tmp_path):
    _clear_model_provider_env(monkeypatch)
    monkeypatch.setenv("AGENTHUB_PROFILE", "demo")
    monkeypatch.setenv("AGENTHUB_DB_PATH", str(tmp_path / "qwen-turbo.sqlite3"))
    monkeypatch.setenv("AGENTHUB_MODEL_PROVIDER", "qwen_turbo")
    monkeypatch.setenv("AGENTHUB_QWEN_TURBO_API_BASE", "https://qwen-turbo.example.test/v1")
    monkeypatch.setenv("AGENTHUB_QWEN_TURBO_MODEL", "qwen-turbo")
    monkeypatch.setenv("AGENTHUB_QWEN_TURBO_API_KEY", "sk-qwen-turbo-secret")

    settings = get_settings()

    assert settings.model_agent_configured() is True
    assert settings.model_agent_api_base_alias == "AGENTHUB_QWEN_TURBO_API_BASE"
    assert settings.model_agent_model_alias == "AGENTHUB_QWEN_TURBO_MODEL"
    assert settings.model_agent_api_key_alias == "AGENTHUB_QWEN_TURBO_API_KEY"


def test_custom_openai_alias_can_configure_model_provider(monkeypatch, tmp_path):
    _clear_model_provider_env(monkeypatch)
    monkeypatch.setenv("AGENTHUB_PROFILE", "demo")
    monkeypatch.setenv("AGENTHUB_DB_PATH", str(tmp_path / "custom-openai-fallback.sqlite3"))
    monkeypatch.setenv("AGENTHUB_MODEL_PROVIDER", "qwen_turbo")
    monkeypatch.setenv("AGENTHUB_CUSTOM_OPENAI_API_BASE", "https://fallback.example.test/v1")
    monkeypatch.setenv("AGENTHUB_CUSTOM_OPENAI_MODEL", "fallback-model")
    monkeypatch.setenv("AGENTHUB_CUSTOM_OPENAI_API_KEY", "sk-fallback-secret")

    settings = get_settings()

    assert settings.model_agent_configured() is True
    assert settings.model_agent_api_base_alias == "AGENTHUB_CUSTOM_OPENAI_API_BASE"
    assert settings.model_agent_model_alias == "AGENTHUB_CUSTOM_OPENAI_MODEL"
    assert settings.model_agent_api_key_alias == "AGENTHUB_CUSTOM_OPENAI_API_KEY"


# ---------------------------------------------------------------------------
# Root .env auto-loading
# ---------------------------------------------------------------------------

def test_root_dot_env_auto_loaded(tmp_path):
    """Root .env is automatically loaded when it exists."""
    config = tmp_path / "config"
    config.mkdir()
    (config / "agenthub.demo.env").write_text("PORT=19001\n", encoding="utf-8")
    (tmp_path / ".env").write_text("PORT=19099\nAGENTHUB_DB_PATH=var/from-dotenv.sqlite3\n", encoding="utf-8")

    environ, loaded = build_effective_environ(profile="demo", environ={}, root=tmp_path)

    assert environ["PORT"] == "19099"
    assert environ["AGENTHUB_DB_PATH"] == "var/from-dotenv.sqlite3"
    assert any(p.endswith(".env") and "config" not in p for p in loaded.files_loaded)


def test_root_dot_env_missing_no_error(tmp_path):
    """When root .env does not exist, no error is raised."""
    config = tmp_path / "config"
    config.mkdir()
    (config / "agenthub.demo.env").write_text("PORT=19001\n", encoding="utf-8")

    environ, loaded = build_effective_environ(profile="demo", environ={}, root=tmp_path)

    assert environ["PORT"] == "19001"
    assert loaded.profile == "demo"


def test_explicit_env_file_overrides_root_dot_env(tmp_path):
    """AGENTHUB_ENV_FILE takes priority over root .env."""
    config = tmp_path / "config"
    config.mkdir()
    (config / "agenthub.demo.env").write_text("PORT=19001\n", encoding="utf-8")
    (tmp_path / ".env").write_text("PORT=19050\n", encoding="utf-8")
    explicit = tmp_path / "override.env"
    explicit.write_text("PORT=19099\n", encoding="utf-8")

    environ, loaded = build_effective_environ(
        profile="demo", env_file=str(explicit), environ={}, root=tmp_path,
    )

    assert environ["PORT"] == "19099"
    assert loaded.explicit_env_file_used is True


def test_os_env_overrides_root_dot_env(tmp_path):
    """OS environment variables override root .env values."""
    config = tmp_path / "config"
    config.mkdir()
    (config / "agenthub.demo.env").write_text("PORT=19001\n", encoding="utf-8")
    (tmp_path / ".env").write_text("PORT=19050\nAGENTHUB_DB_PATH=var/dotenv.sqlite3\n", encoding="utf-8")

    environ, _ = build_effective_environ(
        profile="demo",
        environ={"PORT": "19999", "AGENTHUB_DB_PATH": "var/os.sqlite3"},
        root=tmp_path,
    )

    assert environ["PORT"] == "19999"
    assert environ["AGENTHUB_DB_PATH"] == "var/os.sqlite3"


# ---------------------------------------------------------------------------
# AGENTHUB_ENV_FILE via OS env
# ---------------------------------------------------------------------------

def test_agenthub_env_file_from_os_env(tmp_path):
    """AGENTHUB_ENV_FILE in OS env is resolved and loaded."""
    config = tmp_path / "config"
    config.mkdir()
    (config / "agenthub.demo.env").write_text("PORT=19001\n", encoding="utf-8")
    explicit = tmp_path / "extra.env"
    explicit.write_text("PORT=19077\n", encoding="utf-8")

    environ, loaded = build_effective_environ(
        profile="demo",
        environ={"AGENTHUB_ENV_FILE": str(explicit)},
        root=tmp_path,
    )

    assert environ["PORT"] == "19077"
    assert loaded.explicit_env_file_configured is True
    assert loaded.explicit_env_file_used is True
    assert str(explicit) in loaded.files_loaded


def test_agenthub_env_file_relative_path(tmp_path):
    """AGENTHUB_ENV_FILE with relative path resolves against project root."""
    config = tmp_path / "config"
    config.mkdir()
    (config / "agenthub.demo.env").write_text("PORT=19001\n", encoding="utf-8")
    (tmp_path / "custom.env").write_text("PORT=19088\n", encoding="utf-8")

    environ, loaded = build_effective_environ(
        profile="demo",
        environ={"AGENTHUB_ENV_FILE": "custom.env"},
        root=tmp_path,
    )

    assert environ["PORT"] == "19088"
    assert loaded.explicit_env_file_used is True


def test_agenthub_env_file_missing_explicit_used_is_false(tmp_path):
    """explicit_env_file_used is False when AGENTHUB_ENV_FILE points to missing file."""
    config = tmp_path / "config"
    config.mkdir()
    (config / "agenthub.demo.env").write_text("PORT=19001\n", encoding="utf-8")

    _, loaded = build_effective_environ(
        profile="demo",
        env_file=str(tmp_path / "nonexistent.env"),
        environ={},
        root=tmp_path,
    )

    assert loaded.explicit_env_file_configured is True
    assert loaded.explicit_env_file_used is False


def test_agenthub_env_file_dot_env_no_duplicate(tmp_path):
    """AGENTHUB_ENV_FILE=.env does not duplicate root .env in loaded files."""
    config = tmp_path / "config"
    config.mkdir()
    (config / "agenthub.demo.env").write_text("PORT=1\n", encoding="utf-8")
    (tmp_path / ".env").write_text("PORT=2\n", encoding="utf-8")

    _, loaded = build_effective_environ(
        profile="demo",
        environ={"AGENTHUB_ENV_FILE": ".env"},
        root=tmp_path,
    )

    # Root .env appears exactly once despite both auto-load and AGENTHUB_ENV_FILE
    dot_env_count = sum(1 for p in loaded.files_loaded if p.endswith(".env") and "config" not in p)
    assert dot_env_count == 1
    assert loaded.explicit_env_file_used is True


# ---------------------------------------------------------------------------
# Profile resolution
# ---------------------------------------------------------------------------

def test_explicit_profile_not_overridden_by_dot_env(tmp_path):
    """Explicit profile=demo wins over .env AGENTHUB_PROFILE=real."""
    config = tmp_path / "config"
    config.mkdir()
    (config / "agenthub.demo.env").write_text("PORT=19001\n", encoding="utf-8")
    (config / "agenthub.real.env").write_text("PORT=19002\n", encoding="utf-8")
    (tmp_path / ".env").write_text("AGENTHUB_PROFILE=real\nPORT=19050\n", encoding="utf-8")

    environ, loaded = build_effective_environ(profile="demo", environ={}, root=tmp_path)

    assert loaded.profile == "demo"
    assert environ["PORT"] == "19050"


def test_os_env_profile_not_overridden_by_dot_env(tmp_path):
    """OS env AGENTHUB_PROFILE=demo is not overridden by .env AGENTHUB_PROFILE=real."""
    config = tmp_path / "config"
    config.mkdir()
    (config / "agenthub.demo.env").write_text("PORT=19001\n", encoding="utf-8")
    (config / "agenthub.real.env").write_text("PORT=19002\n", encoding="utf-8")
    (tmp_path / ".env").write_text("AGENTHUB_PROFILE=real\nPORT=19050\n", encoding="utf-8")

    environ, loaded = build_effective_environ(
        profile=None,
        environ={"AGENTHUB_PROFILE": "demo"},
        root=tmp_path,
    )

    assert loaded.profile == "demo"


def test_dot_env_profile_used_when_no_explicit_or_os_env(tmp_path):
    """When no explicit profile or OS env, .env AGENTHUB_PROFILE is used."""
    config = tmp_path / "config"
    config.mkdir()
    (config / "agenthub.demo.env").write_text("PORT=19001\n", encoding="utf-8")
    (config / "agenthub.real.env").write_text("PORT=19002\n", encoding="utf-8")
    (tmp_path / ".env").write_text("AGENTHUB_PROFILE=real\n", encoding="utf-8")

    environ, loaded = build_effective_environ(profile=None, environ={}, root=tmp_path)

    assert loaded.profile == "real"
    assert environ["PORT"] == "19002"


def test_default_profile_when_no_dot_env_profile(tmp_path):
    """Default profile is 'demo' when .env has no AGENTHUB_PROFILE."""
    config = tmp_path / "config"
    config.mkdir()
    (config / "agenthub.demo.env").write_text("PORT=19001\n", encoding="utf-8")
    (tmp_path / ".env").write_text("PORT=19050\n", encoding="utf-8")

    environ, loaded = build_effective_environ(profile=None, environ={}, root=tmp_path)

    assert loaded.profile == "demo"


# ---------------------------------------------------------------------------
# loaded_env_files diagnostics
# ---------------------------------------------------------------------------

def test_loaded_env_files_excludes_secret_values(tmp_path):
    """loaded_env_files contains paths but never secret values."""
    config = tmp_path / "config"
    config.mkdir()
    (config / "agenthub.demo.env").write_text("PORT=19001\n", encoding="utf-8")
    (tmp_path / ".env").write_text(
        "AGENTHUB_TURN_ROUTER_API_KEY=sk-secret-key-12345\nPORT=19050\n",
        encoding="utf-8",
    )

    _, loaded = build_effective_environ(profile="demo", environ={}, root=tmp_path)

    blob = json.dumps(loaded.files_loaded)
    assert "sk-secret-key-12345" not in blob
    assert all(isinstance(p, str) for p in loaded.files_loaded)


def test_explicit_env_file_used_flag(tmp_path):
    """explicit_env_file_used is True only when file actually loaded."""
    config = tmp_path / "config"
    config.mkdir()
    (config / "agenthub.demo.env").write_text("PORT=19001\n", encoding="utf-8")
    explicit = tmp_path / "override.env"
    explicit.write_text("PORT=19099\n", encoding="utf-8")

    _, loaded = build_effective_environ(
        profile="demo", env_file=str(explicit), environ={}, root=tmp_path,
    )
    assert loaded.explicit_env_file_configured is True
    assert loaded.explicit_env_file_used is True

    _, loaded2 = build_effective_environ(profile="demo", environ={}, root=tmp_path)
    assert loaded2.explicit_env_file_configured is False
    assert loaded2.explicit_env_file_used is False


def test_load_order_is_demo_then_profile_then_dotenv_then_explicit(tmp_path):
    """Verify the exact load order of env files."""
    config = tmp_path / "config"
    config.mkdir()
    (config / "agenthub.demo.env").write_text("PORT=1\n", encoding="utf-8")
    (config / "agenthub.real.env").write_text("PORT=2\n", encoding="utf-8")
    (tmp_path / ".env").write_text("PORT=3\n", encoding="utf-8")
    explicit = tmp_path / "override.env"
    explicit.write_text("PORT=4\n", encoding="utf-8")

    _, loaded = build_effective_environ(
        profile="real", env_file=str(explicit), environ={}, root=tmp_path,
    )

    assert len(loaded.files_loaded) == 4
    names = [p.replace("\\", "/").split("/")[-1] for p in loaded.files_loaded]
    assert names == ["agenthub.demo.env", "agenthub.real.env", ".env", "override.env"]
    assert loaded.values_loaded >= 1
