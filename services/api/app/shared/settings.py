from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from services.api.app.shared.env_loader import LoadedEnvironment, build_effective_environ


@dataclass(frozen=True)
class EnvAliasResolution:
    value: str | None
    alias: str | None


@dataclass(frozen=True)
class Settings:
    env_profile: str
    agenthub_env: str
    host: str
    port: int
    db_path: Path
    artifact_store_dir: Path
    static_deploy_dir: Path | None
    public_base_url: str | None
    api_base_url: str
    web_base_url: str
    test_run_id: str
    turn_router_backend: str
    enable_test_turn_router_backend: bool
    turn_router_base_url: str | None
    turn_router_api_key_present: bool
    turn_router_model: str | None
    turn_router_response_format: str
    turn_router_timeout_seconds: float
    context_recent_messages: int
    context_max_message_chars: int
    context_max_total_chars: int
    codex_executable: str | None
    codex_executable_alias: str | None
    claude_executable: str | None
    claude_executable_alias: str | None
    codex_timeout_seconds: int
    opencode_api_base: str | None
    opencode_api_base_alias: str | None
    opencode_timeout_seconds: int
    model_agent_provider: str
    model_agent_api_base: str | None
    model_agent_api_base_alias: str | None
    model_agent_model: str | None
    model_agent_model_alias: str | None
    model_agent_api_key_present: bool
    model_agent_api_key_alias: str | None
    loaded_environment: LoadedEnvironment
    _environ: dict[str, str] = field(repr=False)

    def env_value(self, name: str, default: str | None = None) -> str | None:
        value = self._environ.get(name)
        if value is None or not value.strip():
            return default
        return value

    def public_dict(self) -> dict[str, object]:
        return {
            "env_profile": self.env_profile,
            "agenthub_env": self.agenthub_env,
            "host": self.host,
            "port": self.port,
            "db_path": str(self.db_path),
            "artifact_store_dir": str(self.artifact_store_dir),
            "static_deploy_dir": str(self.static_deploy_dir) if self.static_deploy_dir else None,
            "public_base_url": self.public_base_url,
            "api_base_url": self.api_base_url,
            "web_base_url": self.web_base_url,
            "test_run_id": self.test_run_id,
            "turn_router_backend": self.turn_router_backend,
            "turn_router_configured": self.turn_router_configured(),
            "turn_router_response_format": self.turn_router_response_format,
            "context_recent_messages": self.context_recent_messages,
            "context_max_message_chars": self.context_max_message_chars,
            "context_max_total_chars": self.context_max_total_chars,
            "codex_cli_configured": bool(self.codex_executable),
            "opencode_api_base_alias": self.opencode_api_base_alias,
            "opencode_configured": bool(self.opencode_api_base),
            "model_agent_provider": self.model_agent_provider,
            "model_agent_configured": self.model_agent_configured(),
            "model_agent_api_base_alias": self.model_agent_api_base_alias,
            "model_agent_model_alias": self.model_agent_model_alias,
            "model_agent_api_key_alias": self.model_agent_api_key_alias,
        }

    def turn_router_configured(self) -> bool:
        if self.turn_router_backend == "test":
            return self.agenthub_env == "test" and self.enable_test_turn_router_backend
        if self.turn_router_backend in {"openai", "openai_compatible", "real"}:
            return bool(self.turn_router_base_url and self.turn_router_api_key_present and self.turn_router_model)
        return False

    def model_agent_configured(self) -> bool:
        return bool(self.model_agent_api_base and self.model_agent_model and self.model_agent_api_key_present)


def get_settings(*, profile: str | None = None, env_file: str | None = None) -> Settings:
    environ, loaded = build_effective_environ(profile=profile, env_file=env_file)
    selected_profile = loaded.profile
    host = _string(environ, "HOST", "127.0.0.1")
    port = _int(environ, "PORT", 8080, minimum=1, maximum=65535)
    db_path = _path(_string(environ, "AGENTHUB_DB_PATH", "var/agenthub.sqlite3"))
    artifact_store = environ.get("AGENTHUB_ARTIFACT_STORE_DIR")
    artifact_store_dir = _path(artifact_store) if artifact_store else db_path.parent / "artifacts"
    static_dir = _optional_path(environ.get("AGENTHUB_STATIC_DEPLOY_DIR"))
    provider = _first_string(environ, ["AGENTHUB_MODEL_PROVIDER", "AGENTHUB_DEMO_MODEL_PROVIDER"], "custom_openai")
    provider_key = _provider_env_key(provider)
    codex_executable = _first_executable_alias(
        environ,
        ["AGENTHUB_CODEX_EXECUTABLE", "CODEX_EXECUTABLE", "AGENTHUB_CODEX_CLI_EXECUTABLE"],
    )
    claude_executable = _first_executable_alias(
        environ,
        ["AGENTHUB_CLAUDE_CODE_EXECUTABLE", "AGENTHUB_CLAUDE_EXECUTABLE", "CLAUDE_CODE_EXECUTABLE"],
    )
    model_api_base = _provider_api_base(environ, provider, provider_key)
    model_name = _provider_model(environ, provider, provider_key)
    model_api_key = _provider_api_key(environ, provider, provider_key)
    opencode_api_base = _first_optional_alias(environ, ["OPENCODE_API_BASE", "AGENTHUB_OPENCODE_API_BASE"])
    return Settings(
        env_profile=selected_profile,
        agenthub_env=_string(environ, "AGENTHUB_ENV", selected_profile),
        host=host,
        port=port,
        db_path=db_path,
        artifact_store_dir=artifact_store_dir,
        static_deploy_dir=static_dir,
        public_base_url=_optional_string(environ.get("AGENTHUB_PUBLIC_BASE_URL")),
        api_base_url=_string(environ, "AGENTHUB_API_BASE_URL", f"http://{host}:{port}"),
        web_base_url=_string(environ, "AGENTHUB_WEB_BASE_URL", "http://127.0.0.1:3000"),
        test_run_id=_string(environ, "AGENTHUB_TEST_RUN_ID", "local"),
        turn_router_backend=_string(environ, "AGENTHUB_TURN_ROUTER_BACKEND", "disabled").lower(),
        enable_test_turn_router_backend=_bool(environ, "AGENTHUB_ENABLE_TEST_TURN_ROUTER_BACKEND", False),
        turn_router_base_url=_optional_string(environ.get("AGENTHUB_TURN_ROUTER_BASE_URL")),
        turn_router_api_key_present=bool(_optional_string(environ.get("AGENTHUB_TURN_ROUTER_API_KEY"))),
        turn_router_model=_optional_string(environ.get("AGENTHUB_TURN_ROUTER_MODEL")),
        turn_router_response_format=_string(environ, "AGENTHUB_TURN_ROUTER_RESPONSE_FORMAT", "json_schema").lower(),
        turn_router_timeout_seconds=_float(environ, "AGENTHUB_TURN_ROUTER_TIMEOUT_SECONDS", 30.0, minimum=0.1),
        context_recent_messages=_int(environ, "AGENTHUB_CONTEXT_RECENT_MESSAGES", 20, minimum=0, maximum=100),
        context_max_message_chars=_int(environ, "AGENTHUB_CONTEXT_MAX_MESSAGE_CHARS", 4000, minimum=1, maximum=20000),
        context_max_total_chars=_int(environ, "AGENTHUB_CONTEXT_MAX_TOTAL_CHARS", 16000, minimum=1000, maximum=200000),
        codex_executable=codex_executable.value,
        codex_executable_alias=codex_executable.alias,
        claude_executable=claude_executable.value,
        claude_executable_alias=claude_executable.alias,
        codex_timeout_seconds=_int(environ, "AGENTHUB_CODEX_TIMEOUT_SECONDS", 30, minimum=1, maximum=3600),
        opencode_api_base=opencode_api_base.value,
        opencode_api_base_alias=opencode_api_base.alias,
        opencode_timeout_seconds=_int(environ, "AGENTHUB_OPENCODE_TIMEOUT_SECONDS", 60, minimum=1, maximum=3600),
        model_agent_provider=provider,
        model_agent_api_base=model_api_base.value,
        model_agent_api_base_alias=model_api_base.alias,
        model_agent_model=model_name.value,
        model_agent_model_alias=model_name.alias,
        model_agent_api_key_present=model_api_key.value is not None,
        model_agent_api_key_alias=model_api_key.alias,
        loaded_environment=loaded,
        _environ=environ,
    )


def _string(environ: dict[str, str], name: str, default: str) -> str:
    value = environ.get(name)
    return value.strip() if isinstance(value, str) and value.strip() else default


def _optional_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    clean = value.strip()
    return clean or None


def _first_string(environ: dict[str, str], names: list[str], default: str) -> str:
    return _first_optional_string(environ, names) or default


def _first_optional_string(environ: dict[str, str], names: list[str]) -> str | None:
    return _first_optional_alias(environ, names).value


def _first_optional_alias(environ: dict[str, str], names: list[str]) -> EnvAliasResolution:
    for name in names:
        value = _optional_string(environ.get(name))
        if value:
            return EnvAliasResolution(value=value, alias=name)
    return EnvAliasResolution(value=None, alias=None)


def _first_executable_alias(environ: dict[str, str], names: list[str]) -> EnvAliasResolution:
    first_configured = EnvAliasResolution(value=None, alias=None)
    for name in names:
        value = _optional_string(environ.get(name))
        if not value:
            continue
        if first_configured.value is None:
            first_configured = EnvAliasResolution(value=value, alias=name)
        if _executable_candidate_exists(value):
            return EnvAliasResolution(value=value, alias=name)
    return first_configured


def _bool(environ: dict[str, str], name: str, default: bool) -> bool:
    value = environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int(environ: dict[str, str], name: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        parsed = int(str(environ.get(name, default)).strip())
    except ValueError:
        parsed = default
    return max(minimum, min(parsed, maximum))


def _float(environ: dict[str, str], name: str, default: float, *, minimum: float) -> float:
    try:
        parsed = float(str(environ.get(name, default)).strip())
    except ValueError:
        parsed = default
    return parsed if parsed >= minimum else default


def _path(value: str | None) -> Path:
    raw = value.strip() if isinstance(value, str) and value.strip() else "var"
    return Path(raw).expanduser()


def _optional_path(value: str | None) -> Path | None:
    clean = _optional_string(value)
    return _path(clean) if clean else None


def _provider_api_base(environ: dict[str, str], provider: str, provider_key: str) -> EnvAliasResolution:
    return _first_optional_alias(environ, _provider_api_base_aliases(provider, provider_key))


def _provider_model(environ: dict[str, str], provider: str, provider_key: str) -> EnvAliasResolution:
    return _first_optional_alias(environ, _provider_model_aliases(provider, provider_key))


def _provider_api_key(environ: dict[str, str], provider: str, provider_key: str) -> EnvAliasResolution:
    return _first_optional_alias(environ, _provider_api_key_aliases(provider, provider_key))


def _provider_env_key(provider: str) -> str:
    return "".join(char if char.isalnum() else "_" for char in provider.upper()).strip("_") or "CUSTOM_OPENAI"


def _provider_api_base_aliases(provider: str, provider_key: str) -> list[str]:
    clean = provider.strip().lower()
    if clean in {"qwen", "qwen_turbo"}:
        return [
            "AGENTHUB_PROVIDER_QWEN_API_BASE",
            "AGENTHUB_QWEN_TURBO_API_BASE",
            "AGENTHUB_QWEN_API_BASE",
            "AGENTHUB_CUSTOM_OPENAI_API_BASE",
        ]
    if clean in {"deepseek", "deepseek_official"}:
        return [
            "AGENTHUB_PROVIDER_DEEPSEEK_API_BASE",
            "AGENTHUB_DEEPSEEK_API_BASE",
            "DEEPSEEK_API_BASE",
            "AGENTHUB_CUSTOM_OPENAI_API_BASE",
        ]
    if clean == "volc_deepseek_flash":
        return [
            "AGENTHUB_PROVIDER_VOLC_DEEPSEEK_API_BASE",
            "AGENTHUB_VOLC_DEEPSEEK_FLASH_API_BASE",
            "AGENTHUB_CUSTOM_OPENAI_API_BASE",
        ]
    if clean == "volc_deepseek_pro":
        return [
            "AGENTHUB_PROVIDER_VOLC_DEEPSEEK_API_BASE",
            "AGENTHUB_VOLC_DEEPSEEK_PRO_API_BASE",
            "AGENTHUB_CUSTOM_OPENAI_API_BASE",
        ]
    return [
        f"AGENTHUB_{provider_key}_API_BASE",
        f"{provider_key}_API_BASE",
        "AGENTHUB_CUSTOM_OPENAI_API_BASE",
        "CUSTOM_OPENAI_API_BASE",
    ]


def _provider_model_aliases(provider: str, provider_key: str) -> list[str]:
    clean = provider.strip().lower()
    if clean in {"qwen", "qwen_turbo"}:
        return [
            "AGENTHUB_PROVIDER_QWEN_MODEL",
            "AGENTHUB_QWEN_TURBO_MODEL",
            "AGENTHUB_QWEN_MODEL",
            "AGENTHUB_CUSTOM_OPENAI_MODEL",
        ]
    if clean in {"deepseek", "deepseek_official"}:
        return [
            "AGENTHUB_PROVIDER_DEEPSEEK_MODEL",
            "AGENTHUB_DEEPSEEK_MODEL",
            "DEEPSEEK_MODEL",
            "AGENTHUB_CUSTOM_OPENAI_MODEL",
        ]
    if clean == "volc_deepseek_flash":
        return [
            "AGENTHUB_PROVIDER_VOLC_DEEPSEEK_FLASH_MODEL",
            "AGENTHUB_VOLC_DEEPSEEK_FLASH_MODEL",
            "AGENTHUB_CUSTOM_OPENAI_MODEL",
        ]
    if clean == "volc_deepseek_pro":
        return [
            "AGENTHUB_PROVIDER_VOLC_DEEPSEEK_PRO_MODEL",
            "AGENTHUB_VOLC_DEEPSEEK_PRO_MODEL",
            "AGENTHUB_CUSTOM_OPENAI_MODEL",
        ]
    return [
        f"AGENTHUB_{provider_key}_MODEL",
        f"{provider_key}_MODEL",
        "AGENTHUB_CUSTOM_OPENAI_MODEL",
        "CUSTOM_OPENAI_MODEL",
    ]


def _provider_api_key_aliases(provider: str, provider_key: str) -> list[str]:
    clean = provider.strip().lower()
    if clean in {"qwen", "qwen_turbo"}:
        return [
            "AGENTHUB_PROVIDER_QWEN_API_KEY",
            "AGENTHUB_QWEN_TURBO_API_KEY",
            "AGENTHUB_QWEN_API_KEY",
            "AGENTHUB_CUSTOM_OPENAI_API_KEY",
        ]
    if clean in {"deepseek", "deepseek_official"}:
        return [
            "AGENTHUB_PROVIDER_DEEPSEEK_API_KEY",
            "AGENTHUB_DEEPSEEK_API_KEY",
            "DEEPSEEK_API_KEY",
            "AGENTHUB_CUSTOM_OPENAI_API_KEY",
        ]
    if clean == "volc_deepseek_flash":
        return [
            "AGENTHUB_PROVIDER_VOLC_DEEPSEEK_API_KEY",
            "AGENTHUB_VOLC_DEEPSEEK_FLASH_API_KEY",
            "AGENTHUB_CUSTOM_OPENAI_API_KEY",
        ]
    if clean == "volc_deepseek_pro":
        return [
            "AGENTHUB_PROVIDER_VOLC_DEEPSEEK_API_KEY",
            "AGENTHUB_VOLC_DEEPSEEK_PRO_API_KEY",
            "AGENTHUB_CUSTOM_OPENAI_API_KEY",
        ]
    names = [
        f"AGENTHUB_{provider_key}_API_KEY",
        f"{provider_key}_API_KEY",
        "CUSTOM_OPENAI_API_KEY",
    ]
    if clean == "custom_openai":
        names.insert(0, "AGENTHUB_CUSTOM_OPENAI_API_KEY")
    return names


def _executable_candidate_exists(value: str) -> bool:
    clean = value.strip().strip('"').strip("'")
    if any(separator in clean for separator in ("/", "\\")):
        return Path(clean).expanduser().exists()
    return shutil.which(clean) is not None
