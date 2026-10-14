"""Bounded subprocess supervision for trusted local fixtures only.

Process groups are a timeout cleanup mechanism, not an adversarial sandbox.
Candidates that detach sessions, hostile code, CPU/memory/network quotas and
production containers require a validated external execution backend.
"""

import math
import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ProcessResult:
    status: str
    returncode: int | None
    stdout: str
    stderr: str
    elapsed_seconds: float
    output_truncated: bool


def run_process(
    argv: list[str],
    *,
    cwd: str | Path | None = None,
    timeout_seconds: float,
    max_output_bytes: int = 1_000_000,
    env: dict[str, str] | None = None,
) -> ProcessResult:
    if (
        not argv
        or isinstance(argv, str)
        or not all(isinstance(value, str) for value in argv)
        or isinstance(timeout_seconds, bool)
        or not math.isfinite(timeout_seconds)
        or timeout_seconds <= 0
        or max_output_bytes <= 0
    ):
        raise ValueError("Argument vector, finite positive timeout and output bound required")
    started = time.monotonic()
    try:
        process = subprocess.Popen(
            argv,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=(os.name == "posix"),
            shell=False,
        )
    except OSError as error:
        return ProcessResult(
            "infrastructure_error", None, "", str(error), time.monotonic() - started, False
        )
    buffers = [bytearray(), bytearray()]
    truncated = [False, False]

    def consume(stream, index: int) -> None:
        try:
            while True:
                chunk = stream.read(8192)
                if not chunk:
                    return
                remaining = max_output_bytes - len(buffers[index])
                buffers[index].extend(chunk[:remaining])
                if len(chunk) > remaining:
                    truncated[index] = True
        finally:
            stream.close()

    readers = [
        threading.Thread(target=consume, args=(stream, index), daemon=True)
        for index, stream in enumerate((process.stdout, process.stderr))
    ]
    for reader in readers:
        reader.start()
    timed_out = False
    try:
        process.wait(timeout=timeout_seconds)
        remaining = max(0.0, timeout_seconds - (time.monotonic() - started))
        for reader in readers:
            reader.join(timeout=remaining)
            remaining = max(0.0, timeout_seconds - (time.monotonic() - started))
        timed_out = any(reader.is_alive() for reader in readers)
    except subprocess.TimeoutExpired:
        timed_out = True
    finally:
        if timed_out or os.name == "posix":
            try:
                if os.name == "posix":
                    os.killpg(process.pid, signal.SIGKILL)
                elif process.poll() is None:
                    process.kill()
            except ProcessLookupError:
                pass
        process.wait()
        for reader in readers:
            reader.join(timeout=1)
    status = (
        "timeout" if timed_out else ("succeeded" if process.returncode == 0 else "candidate_error")
    )
    return ProcessResult(
        status,
        process.returncode,
        buffers[0].decode("utf-8", errors="replace"),
        buffers[1].decode("utf-8", errors="replace"),
        time.monotonic() - started,
        any(truncated),
    )
