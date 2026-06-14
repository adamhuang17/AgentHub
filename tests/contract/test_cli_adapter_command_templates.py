import sys
from pathlib import Path

from services.api.app.agents.adapters.claude_code_cli import build_claude_direct_response_command
from services.api.app.agents.adapters.cli_process import run_cli_process
from services.api.app.agents.adapters.codex_cli import build_codex_direct_response_command, build_codex_version_command


def test_codex_direct_response_uses_read_only_sandbox(monkeypatch):
    monkeypatch.setenv("AGENTHUB_CODEX_IGNORE_USER_CONFIG", "1")
    monkeypatch.setenv("AGENTHUB_CODEX_DISABLE_FEATURES", "plugins,apps")
    command = build_codex_direct_response_command(
        executable_path="codex",
        workspace_dir="D:/AgentHub",
        prompt="hello; still one argv",
    )

    assert command[:4] == ["codex", "-a", "never", "exec"]
    assert command[4:8] == ["--disable", "plugins", "--disable", "apps"]
    assert "--ignore-user-config" in command
    assert command.index("--ignore-user-config") < command.index("--json")
    assert "--sandbox" in command
    assert command[command.index("--sandbox") + 1] == "read-only"
    assert "danger-full-access" not in command
    assert "workspace-write" not in command
    assert command[-1] == "hello; still one argv"


def test_codex_direct_response_can_load_full_user_config_when_requested(monkeypatch):
    monkeypatch.setenv("AGENTHUB_CODEX_IGNORE_USER_CONFIG", "0")
    monkeypatch.setenv("AGENTHUB_CODEX_DISABLE_FEATURES", "")
    command = build_codex_direct_response_command(
        executable_path="codex",
        workspace_dir="D:/AgentHub",
        prompt="hello",
    )

    assert "--ignore-user-config" not in command


def test_codex_direct_response_can_read_prompt_from_stdin(monkeypatch):
    monkeypatch.setenv("AGENTHUB_CODEX_IGNORE_USER_CONFIG", "1")
    monkeypatch.setenv("AGENTHUB_CODEX_DISABLE_FEATURES", "plugins,apps")
    command = build_codex_direct_response_command(
        executable_path="codex",
        workspace_dir="D:/AgentHub",
        prompt="你好",
        prompt_via_stdin=True,
    )

    assert command[-1] == "-"
    assert "你好" not in command


def test_codex_health_uses_version_command_template():
    assert build_codex_version_command(executable_path="codex") == ["codex", "--version"]


def test_claude_direct_response_disables_tools_and_mcp():
    command = build_claude_direct_response_command(executable_path="claude", prompt="hello")

    assert command[:2] == ["claude", "-p"]
    assert "--tools=" in command
    assert "--strict-mcp-config" in command
    assert "--dangerously-skip-permissions" not in command
    assert "Edit" not in command
    assert "Write" not in command
    assert "Bash" not in command


def test_cli_process_uses_argv_without_shell():
    result = run_cli_process(
        [sys.executable, "-c", "print('ok')"],
        cwd=Path.cwd(),
        timeout_seconds=5,
    )

    assert result.shell_used is False
    assert result.exit_code == 0
    assert result.stdout_lines == ["ok"]


def test_cli_process_can_stop_after_terminal_line():
    result = run_cli_process(
        [
            sys.executable,
            "-c",
            "import time; print('start', flush=True); print('done', flush=True); time.sleep(10)",
        ],
        cwd=Path.cwd(),
        timeout_seconds=30,
        stop_after_line=lambda raw: raw.stream == "stdout" and raw.line == "done",
    )

    assert result.terminated_early is True
    assert result.timed_out is False
    assert result.stdout_lines == ["start", "done"]
    assert result.duration_seconds < 10


def test_cli_process_writes_stdin_text():
    result = run_cli_process(
        [sys.executable, "-c", "import sys; print(sys.stdin.read())"],
        cwd=Path.cwd(),
        timeout_seconds=5,
        stdin_text="你好",
    )

    assert result.exit_code == 0
    assert result.stdout_lines == ["你好"]
