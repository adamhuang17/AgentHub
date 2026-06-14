from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


SUPPORTED_PROFILES = {"demo", "test", "real"}
_ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class LoadedEnvironment:
    profile: str
    files_loaded: list[str]
    files_missing: list[str]
    values_loaded: int
    explicit_env_file_configured: bool = False
    explicit_env_file_used: bool = False


def repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def parse_env_file(path: str | Path) -> dict[str, str]:
    env_path = Path(path)
    values: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        parsed = _parse_env_line(raw_line)
        if parsed is None:
            continue
        key, value = parsed
        values[key] = value
    return values


def build_effective_environ(
    *,
    profile: str | None = None,
    env_file: str | None = None,
    environ: Mapping[str, str] | None = None,
    root: Path | None = None,
) -> tuple[dict[str, str], LoadedEnvironment]:
    base = dict(os.environ if environ is None else environ)
    resolved_root = root or repo_root()
    selected_profile = _resolve_profile(profile, base, resolved_root)
    configured_env_file = env_file or _clean(base.get("AGENTHUB_ENV_FILE"))
    explicit_configured = bool(configured_env_file)

    merged: dict[str, str] = {}
    loaded: list[str] = []
    missing: list[str] = []

    candidates = _candidate_files(selected_profile, configured_env_file, resolved_root)
    for path in candidates:
        if path.exists():
            merged.update(parse_env_file(path))
            loaded.append(str(path))
        else:
            missing.append(str(path))

    # explicit_env_file_used: True only if the configured file was actually found and loaded
    explicit_loaded = False
    if configured_env_file:
        configured = Path(configured_env_file)
        resolved_explicit = (configured if configured.is_absolute() else resolved_root / configured).resolve()
        loaded_resolved = {Path(p).resolve() for p in loaded}
        explicit_loaded = resolved_explicit in loaded_resolved

    effective = dict(merged)
    effective.update(base)
    effective.setdefault("AGENTHUB_PROFILE", selected_profile)
    return effective, LoadedEnvironment(
        profile=selected_profile,
        files_loaded=loaded,
        files_missing=missing,
        values_loaded=len(merged),
        explicit_env_file_configured=explicit_configured,
        explicit_env_file_used=explicit_loaded,
    )


def load_environment(
    *,
    profile: str | None = None,
    env_file: str | None = None,
    root: Path | None = None,
) -> LoadedEnvironment:
    initial = dict(os.environ)
    effective, loaded = build_effective_environ(
        profile=profile,
        env_file=env_file,
        environ=initial,
        root=root,
    )
    for key, value in effective.items():
        if key not in initial:
            os.environ[key] = value
    return loaded


# ---------------------------------------------------------------------------
# Profile resolution
# ---------------------------------------------------------------------------

def _resolve_profile(profile: str | None, environ: Mapping[str, str], root: Path) -> str:
    """Resolve profile with priority: explicit param > OS env > .env > default."""
    # 1. Explicit parameter wins
    clean_profile = _clean(profile)
    if clean_profile:
        return _normalize_profile(clean_profile)
    # 2. OS env wins
    env_profile = _clean(environ.get("AGENTHUB_PROFILE"))
    if env_profile:
        return _normalize_profile(env_profile)
    # 3. Peek at root .env
    dot_env = root / ".env"
    if dot_env.exists():
        try:
            dot_env_values = parse_env_file(dot_env)
            env_profile = _clean(dot_env_values.get("AGENTHUB_PROFILE"))
            if env_profile:
                return _normalize_profile(env_profile)
        except Exception:
            pass
    # 4. Default
    return "demo"


def _normalize_profile(raw: str) -> str:
    selected = raw.lower()
    return selected if selected in SUPPORTED_PROFILES else "demo"


# ---------------------------------------------------------------------------
# Candidate files
# ---------------------------------------------------------------------------

def _candidate_files(profile: str, env_file: str | None, root: Path) -> list[Path]:
    """Return env files in load order: demo → profile → root .env → explicit.

    Deduplicates by resolved path so AGENTHUB_ENV_FILE=.env does not cause
    root .env to appear twice.
    """
    config_dir = root / "config"
    paths: list[Path] = [config_dir / "agenthub.demo.env"]
    profile_path = config_dir / f"agenthub.{profile}.env"
    if profile_path not in paths:
        paths.append(profile_path)
    # Root .env — auto-loaded
    paths.append(root / ".env")
    if env_file:
        configured = Path(env_file)
        paths.append(configured if configured.is_absolute() else root / configured)

    # Deduplicate by resolved path
    seen: set[Path] = set()
    unique: list[Path] = []
    for p in paths:
        r = p.resolve()
        if r not in seen:
            seen.add(r)
            unique.append(p)
    return unique


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _parse_env_line(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    if stripped.startswith("export "):
        stripped = stripped[len("export ") :].lstrip()
    if "=" not in stripped:
        return None
    key, raw_value = stripped.split("=", 1)
    key = key.strip()
    if not _ENV_KEY_RE.match(key):
        return None
    return key, _parse_value(raw_value.strip())


def _parse_value(raw: str) -> str:
    if not raw:
        return ""
    if (raw.startswith('"') and raw.endswith('"')) or (raw.startswith("'") and raw.endswith("'")):
        inner = raw[1:-1]
        if raw.startswith('"'):
            return inner.replace("\\n", "\n").replace('\\"', '"').replace("\\\\", "\\")
        return inner
    return _strip_inline_comment(raw).strip()


def _strip_inline_comment(value: str) -> str:
    for index, char in enumerate(value):
        if char == "#" and (index == 0 or value[index - 1].isspace()):
            return value[:index]
    return value


def _clean(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    clean = value.strip()
    return clean or None
