from __future__ import annotations

import os
import queue
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable


@dataclass(frozen=True)
class CliRawLine:
    stream: str
    line: str


@dataclass(frozen=True)
class CliProcessResult:
    argv: list[str]
    cwd: str
    exit_code: int | None
    stdout_lines: list[str]
    stderr_lines: list[str]
    raw_lines: list[CliRawLine]
    timed_out: bool
    duration_seconds: float
    shell_used: bool = False
    terminated_early: bool = False


def run_cli_process(
    argv: Iterable[str],
    *,
    cwd: str | Path,
    timeout_seconds: int,
    env: dict[str, str] | None = None,
    stop_after_line: Callable[[CliRawLine], bool] | None = None,
    stdin_text: str | None = None,
) -> CliProcessResult:
    command = [str(part) for part in argv]
    if not command:
        raise ValueError("argv must contain at least one executable.")
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive.")

    cwd_text = str(cwd)
    stdout_lines: list[str] = []
    stderr_lines: list[str] = []
    raw_lines: list[CliRawLine] = []
    line_queue: queue.Queue[CliRawLine] = queue.Queue()
    start = time.monotonic()

    process = subprocess.Popen(
        command,
        cwd=cwd_text,
        stdin=subprocess.PIPE if stdin_text is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        shell=False,
        env=env,
    )
    readers = [
        threading.Thread(target=_read_stream, args=("stdout", process.stdout, line_queue), daemon=True),
        threading.Thread(target=_read_stream, args=("stderr", process.stderr, line_queue), daemon=True),
    ]
    for reader in readers:
        reader.start()
    stdin_writer = None
    if stdin_text is not None and process.stdin is not None:
        stdin_writer = threading.Thread(target=_write_stdin, args=(process.stdin, stdin_text), daemon=True)
        stdin_writer.start()

    timed_out = False
    terminated_early = False
    while process.poll() is None:
        if _drain_lines(line_queue, stdout_lines, stderr_lines, raw_lines, stop_after_line=stop_after_line):
            terminated_early = True
            _kill_process(process)
            break
        if time.monotonic() - start >= timeout_seconds:
            timed_out = True
            _kill_process(process)
            break
        time.sleep(0.02)

    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        _kill_process(process)
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass

    for reader in readers:
        reader.join(timeout=1)
    if stdin_writer is not None:
        stdin_writer.join(timeout=1)
    _drain_lines(line_queue, stdout_lines, stderr_lines, raw_lines)

    return CliProcessResult(
        argv=command,
        cwd=cwd_text,
        exit_code=process.returncode,
        stdout_lines=stdout_lines,
        stderr_lines=stderr_lines,
        raw_lines=raw_lines,
        timed_out=timed_out,
        duration_seconds=time.monotonic() - start,
        shell_used=False,
        terminated_early=terminated_early,
    )


def _read_stream(
    stream_name: str,
    stream,
    line_queue: queue.Queue[CliRawLine],
) -> None:
    if stream is None:
        return
    for line in stream:
        line_queue.put(CliRawLine(stream=stream_name, line=line.rstrip("\r\n")))


def _write_stdin(stream, text: str) -> None:
    try:
        stream.write(text)
        stream.close()
    except (BrokenPipeError, OSError, ValueError):
        try:
            stream.close()
        except (OSError, ValueError):
            pass


def _drain_lines(
    line_queue: queue.Queue[CliRawLine],
    stdout_lines: list[str],
    stderr_lines: list[str],
    raw_lines: list[CliRawLine],
    *,
    stop_after_line: Callable[[CliRawLine], bool] | None = None,
) -> bool:
    should_stop = False
    while True:
        try:
            raw = line_queue.get_nowait()
        except queue.Empty:
            return should_stop
        raw_lines.append(raw)
        if raw.stream == "stdout":
            stdout_lines.append(raw.line)
        else:
            stderr_lines.append(raw.line)
        if stop_after_line is not None and stop_after_line(raw):
            should_stop = True


def _kill_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=5,
                shell=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            process.kill()
        if process.poll() is None:
            try:
                process.kill()
            except OSError:
                pass
        return
    process.kill()
