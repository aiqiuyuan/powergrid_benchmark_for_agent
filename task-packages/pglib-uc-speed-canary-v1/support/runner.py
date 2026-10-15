"""Supervise source execution and copy timestamped snapshots before validation."""

from __future__ import annotations

import json
import math
import os
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from json_io import load
from scoring import aggregate, replay

MAX_BYTES = 16 << 20
MAX_SNAPSHOTS = 64
MAX_SOURCE_BYTES = 2 << 20
CHILD_ENV = {
    "PATH": "/usr/local/julia/bin:/usr/local/bin:/usr/bin:/bin",
    "LANG": "C.UTF-8",
    "HOME": "/nonexistent",
    "JULIA_PROJECT": "/opt/uc-runtime",
    "JULIA_DEPOT_PATH": "/opt/julia-depot",
    "JULIA_NUM_THREADS": "1",
    "JULIA_NUM_GC_THREADS": "1",
    "JULIA_PKG_PRECOMPILE_AUTO": "0",
    "OPENBLAS_NUM_THREADS": "1",
    "OMP_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
}


def regular_bytes(path: Path, maximum: int) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or not 0 < info.st_size <= maximum:
            raise ValueError("Bounded regular file required")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            content = stream.read(maximum + 1)
        after = os.fstat(descriptor)
        if (
            len(content) != info.st_size
            or after.st_size != info.st_size
            or after.st_mtime_ns != info.st_mtime_ns
        ):
            raise ValueError("Snapshot changed during receipt")
        return content
    finally:
        os.close(descriptor)


def stage_source(source: Path, destination: Path) -> None:
    if source.is_symlink() or not source.is_dir():
        raise ValueError("Ordinary source directory required")
    destination.mkdir(mode=0o755)
    total = 0
    files = list(source.iterdir())
    if not 1 <= len(files) <= 32:
        raise ValueError("Source file count exceeded")
    for path in files:
        if path.suffix not in {".jl", ".md", ".txt"} and not path.name.startswith("LICENSE"):
            raise ValueError("Only flat Julia source and documentation are accepted")
        content = regular_bytes(path, MAX_SOURCE_BYTES)
        total += len(content)
        if total > MAX_SOURCE_BYTES:
            raise ValueError("Source size exceeded")
        target = destination / path.name
        target.write_bytes(content)
        target.chmod(0o444)
    if not (destination / "solver.jl").is_file():
        raise ValueError("solver.jl is required")
    destination.chmod(0o555)


def secure_prefix(seconds: float, output: Path) -> list[str]:
    if (
        sys.platform != "linux"
        or os.geteuid() != 0
        or not all(shutil.which(x) for x in ("setpriv", "taskset", "uc-exec", "prlimit"))
    ):
        raise RuntimeError("Secure grading requires the certified Linux runtime")
    # The dedicated candidate/verifier container supplies the 8 GiB cgroup cap.
    # Julia reserves a large virtual address space, so RLIMIT_AS is inappropriate.
    prefix = [
        "setpriv",
        "--no-new-privs",
        "--reuid=65534",
        "--regid=65534",
        "--clear-groups",
        "prlimit",
        f"--cpu={math.ceil(seconds) + 1}",
        f"--fsize={MAX_BYTES}",
        "--nofile=128",
        "--core=0",
        "--",
        "taskset",
        "-c",
        str(min(os.sched_getaffinity(0))),
        "uc-exec",
        "--write-root",
        str(output),
        "--",
    ]
    ready = subprocess.run(
        prefix + ["/usr/bin/true"],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=5,
        env=CHILD_ENV,
    )
    if ready.returncode:
        raise RuntimeError("Sandbox readiness failed")
    return prefix


def memory_events() -> tuple[Path, int]:
    """Require the dedicated container limit and observe kernel OOM events."""
    root = Path("/sys/fs/cgroup")
    maximum = root / "memory.max"
    events = root / "memory.events"
    if maximum.is_file() and events.is_file():
        limit = maximum.read_text().strip()
        if limit == "max" or int(limit) > 8192 * 1024 * 1024:
            raise RuntimeError("Candidate container memory limit is missing or too large")
        return events, read_oom_events(events)
    maximum = root / "memory/memory.limit_in_bytes"
    events = root / "memory/memory.failcnt"
    if maximum.is_file() and events.is_file() and int(maximum.read_text()) <= 8192 * 1024 * 1024:
        return events, read_oom_events(events)
    raise RuntimeError("Candidate memory accounting is unavailable")


def read_oom_events(path: Path) -> int:
    value = path.read_text().strip()
    if path.name == "memory.failcnt":
        return int(value)
    return int(dict(line.split() for line in value.splitlines())["oom_kill"])


def execute(
    source: Path,
    instance: Path,
    scratch: Path,
    received: Path,
    *,
    seconds: float,
    seed: int,
    secure: bool = True,
    interpreter: list[str] | None = None,
) -> dict:
    """interpreter overrides are for trusted local fixtures, never Harbor grading."""
    scratch.chmod(0o755)
    stage_source(source, scratch / "code")
    staged = scratch / "instance.json"
    staged.write_bytes(regular_bytes(instance, MAX_BYTES))
    staged.chmod(0o444)
    output = scratch / "output"
    output.mkdir(mode=0o700)
    received.mkdir(mode=0o700)
    if secure:
        if interpreter is not None:
            raise ValueError("Interpreter override is forbidden in secure grading")
        os.chown(output, 65534, 65534)
    prefix = secure_prefix(seconds, output) if secure else []
    memory = memory_events() if secure else None
    executable = interpreter or ["julia", "--startup-file=no", "--threads=1"]
    command = (
        prefix
        + executable
        + [str(scratch / "code/solver.jl"), str(staged), str(output), str(seconds), str(seed)]
    )
    environment = CHILD_ENV if secure else dict(os.environ)
    if not secure:
        environment.update(
            {
                key: CHILD_ENV[key]
                for key in (
                    "JULIA_NUM_THREADS",
                    "JULIA_NUM_GC_THREADS",
                    "OPENBLAS_NUM_THREADS",
                    "OMP_NUM_THREADS",
                    "MKL_NUM_THREADS",
                    "JULIA_PKG_PRECOMPILE_AUTO",
                )
            }
        )
    start = time.monotonic()
    copies, seen = [], set()
    violation = False
    timed_out = False
    # Discard raw candidate logs: they are neither trusted measurements nor feedback.
    process = subprocess.Popen(
        command,
        cwd=scratch,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        while True:
            exited_before_scan = process.poll() is not None
            if time.monotonic() - start >= seconds:
                timed_out = not exited_before_scan
                break
            entries = []
            with os.scandir(output) as directory:
                for entry in directory:
                    entries.append(Path(entry.path))
                    if len(entries) > MAX_SNAPSHOTS + 1:
                        violation = True
                        break
            for path in sorted(p for p in entries if p.suffix == ".json"):
                if path.name in seen:
                    continue
                seen.add(path.name)
                if len(seen) > MAX_SNAPSHOTS:
                    violation = True
                    break
                try:
                    data = regular_bytes(path, MAX_BYTES)
                except (OSError, ValueError):
                    violation = True
                    break
                elapsed = time.monotonic() - start
                if elapsed > seconds:
                    continue
                target = received / f"{len(copies):04d}.json"
                target.write_bytes(data)
                target.chmod(0o400)
                # Receipt completes only once the trusted immutable copy exists.
                elapsed = time.monotonic() - start
                if elapsed <= seconds:
                    copies.append((elapsed, target))
            if violation or exited_before_scan:
                break
            time.sleep(0.005)
    finally:
        if process.poll() is not None:
            timed_out = False
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()
    oom = bool(memory and read_oom_events(memory[0]) > memory[1])
    normal_deadline = timed_out and process.returncode == -signal.SIGKILL
    status = (
        "RESOURCE"
        if violation or oom
        else "DEADLINE"
        if normal_deadline
        else "OK"
        if process.returncode == 0
        else "CRASH"
    )
    return {
        "status": status,
        "snapshots": copies,
        "candidate_wall_seconds": time.monotonic() - start,
    }


def evaluate(
    source: Path,
    manifest_path: Path,
    *,
    seeds: list[int],
    secure: bool = True,
    interpreter: list[str] | None = None,
) -> dict:
    manifest_path = manifest_path.resolve()
    manifest = load(manifest_path)
    import hashlib

    instance = manifest_path.parent / manifest["instance"]
    if hashlib.sha256(instance.read_bytes()).hexdigest() != manifest["instance_sha256"]:
        raise RuntimeError("Frozen input hash differs")
    seconds = float(manifest["execution_seconds"])
    if not 0 < seconds <= 1200 or not seeds:
        raise ValueError("Invalid replay budget")
    rows, execution = [], []
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="uc-receipts-") as private:
        frozen = Path(private) / "frozen-source"
        try:
            stage_source(source, frozen)
        except (OSError, ValueError):
            rows = [
                replay(
                    [],
                    status="INVALID_SOURCE",
                    seconds=seconds,
                    upper=manifest["reference_upper"],
                    lower=manifest["reference_lower"],
                    epsilon=manifest["target_gap_ratio"],
                )
                for _ in seeds
            ]
            return {
                "feedback": aggregate(rows, seconds),
                "ranking": aggregate(rows, seconds, delivered=False),
                "replays": rows,
                "execution": [],
                "total_wall_seconds": time.monotonic() - started,
            }
        for index, seed in enumerate(seeds):
            with tempfile.TemporaryDirectory(prefix="uc-candidate-") as work:
                try:
                    run = execute(
                        frozen,
                        instance,
                        Path(work),
                        Path(private) / str(index),
                        seconds=seconds,
                        seed=seed,
                        secure=secure,
                        interpreter=interpreter,
                    )
                except ValueError:
                    run = {"status": "INVALID_SOURCE", "snapshots": [], "candidate_wall_seconds": 0}
                checked = []
                check_started = time.monotonic()
                for received_time, path in run["snapshots"]:
                    remaining = 120 - (time.monotonic() - check_started)
                    if remaining <= 0:
                        raise RuntimeError("Trusted checker exhausted its total budget")
                    try:
                        check = subprocess.run(
                            [
                                sys.executable,
                                str(Path(__file__).with_name("check_snapshot.py")),
                                str(instance),
                                str(path),
                            ],
                            capture_output=True,
                            timeout=remaining,
                            text=True,
                            check=False,
                        )
                    except subprocess.TimeoutExpired as exc:
                        raise RuntimeError("Trusted checker timed out") from exc
                    if check.returncode not in {0, 2}:
                        raise RuntimeError("Trusted checker failed")
                    if check.returncode == 0:
                        checked.append((received_time, json.loads(check.stdout)["cost"]))
                rows.append(
                    replay(
                        checked,
                        status=run["status"],
                        seconds=seconds,
                        upper=manifest["reference_upper"],
                        lower=manifest["reference_lower"],
                        epsilon=manifest["target_gap_ratio"],
                    )
                )
                execution.append(
                    {
                        "candidate_wall_seconds": run["candidate_wall_seconds"],
                        "checker_seconds": time.monotonic() - check_started,
                        "snapshots_received": len(run["snapshots"]),
                        "status": run["status"],
                    }
                )
    return {
        "feedback": aggregate(rows, seconds),
        "ranking": aggregate(rows, seconds, delivered=False),
        "replays": rows,
        "execution": execution,
        "total_wall_seconds": time.monotonic() - started,
    }
