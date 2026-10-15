"""Bounded, process-isolated RTE evaluation with deterministic panel reduction."""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import math
import multiprocessing as mp
from multiprocessing.connection import wait
import os
from pathlib import Path
import resource
import shutil
import signal
import subprocess
import sys
import tempfile
import time

from official import check_solution, normalized_score, regular_bytes

OUTPUT_LIMIT = 4 << 20
CANDIDATE_LIMIT = 1 << 20
MEMORY_LIMIT = 8 << 30  # RLIMIT_AS, not a measured resident-memory requirement.
CHILD_ENV = {"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8",
             "HOME": "/nonexistent", "OPENBLAS_NUM_THREADS": "1",
             "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
             "PYTHONDONTWRITEBYTECODE": "1", "PYTHONHASHSEED": "2020"}
_ACTIVE_CHILD: int | None = None


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _kill_child() -> None:
    if _ACTIVE_CHILD is not None:
        try:
            os.killpg(_ACTIVE_CHILD, signal.SIGKILL)
        except ProcessLookupError:
            pass


def _stop_worker(signum: int, frame: object) -> None:
    _kill_child()
    raise SystemExit(128 + signum)


def check_sandbox(prefix: list[str]) -> None:
    probe = subprocess.run(prefix + ["/usr/bin/true"], env=CHILD_ENV,
                           stdin=subprocess.DEVNULL, capture_output=True,
                           timeout=5, start_new_session=True)
    if probe.returncode:
        raise RuntimeError("candidate sandbox readiness probe failed")


def execute(candidate: Path | bytes, instance: Path, scratch: Path, *, seconds: float,
            seed: int, secure: bool, cpu: int | None = None, uid: int = 64000,
            address_space_bytes: int = MEMORY_LIMIT,
            extra_args: tuple[str, ...] = ()) -> dict:
    """One candidate process; its wall budget includes imports, parsing and output."""
    global _ACTIVE_CHILD
    source = scratch / "candidate.py"
    source.write_bytes(candidate if isinstance(candidate, bytes) else regular_bytes(candidate, CANDIDATE_LIMIT))
    source.chmod(0o444)
    staged_input = scratch / "instance.json"
    # Never chmod/chown linked input inodes: original data remain read-only sources.
    shutil.copyfile(instance, staged_input)
    staged_input.chmod(0o444)
    output_dir = scratch / "output"
    output_dir.mkdir(mode=0o700)
    output = output_dir / "schedule.txt"
    prefix: list[str] = []
    if secure:
        if (sys.platform != "linux" or os.geteuid() != 0 or cpu is None
                or not all(shutil.which(t) for t in ("rte-exec", "setpriv", "prlimit", "taskset"))):
            raise RuntimeError("secure evaluation requires Linux root and installed sandbox tools")
        # The candidate may traverse, but cannot replace root-anchored entries.
        # Owning this parent would permit swapping output/ for a symlink before
        # privileged cleanup chown/chmod, even though output itself has mode 700.
        os.chown(scratch, 0, uid)
        scratch.chmod(0o710)
        os.chown(output_dir, uid, uid)
        prefix = ["setpriv", "--no-new-privs", f"--reuid={uid}", f"--regid={uid}", "--clear-groups",
                  "prlimit", f"--as={address_space_bytes}", f"--cpu={math.ceil(seconds) + 2}",
                  f"--fsize={OUTPUT_LIMIT}", "--nofile=64", "--nproc=32", "--core=0", "--",
                  "taskset", "-c", str(cpu), "rte-exec"]
        check_sandbox(prefix)
    command = prefix + [sys.executable, "-I", str(source), "--instance", str(staged_input),
                        "--output", str(output), "--time-limit", str(max(0.1, seconds - 2)),
                        "--seed", str(seed), *extra_args]
    start = time.monotonic()
    timed_out = False
    try:
        with (scratch / "stdout.log").open("wb") as stdout, (scratch / "stderr.log").open("wb") as stderr:
            process = subprocess.Popen(command, cwd=Path(__file__).resolve().parent,
                                       env=CHILD_ENV, stdin=subprocess.DEVNULL,
                                       stdout=stdout, stderr=stderr, start_new_session=True)
            _ACTIVE_CHILD = process.pid
            try:
                process.wait(timeout=seconds)
            except subprocess.TimeoutExpired:
                timed_out = True
            finally:
                _kill_child()
                process.wait()
    finally:
        _ACTIVE_CHILD = None
        if secure:
            os.chown(scratch, 0, 0)
            scratch.chmod(0o700)
            os.chown(output_dir, 0, 0)
            output_dir.chmod(0o700)
    return {"status": "TLE" if timed_out else ("RE" if process.returncode else "OK"),
            "wall_seconds": time.monotonic() - start, "returncode": process.returncode,
            "candidate_peak_rss": resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss,
            "output": output}


def _worker(connection: object, code: bytes, case: dict, instance: Path, *, support: Path,
            seconds: float, seed: int, secure: bool, cpu: int | None, uid: int,
            address_space_bytes: int, extra_args: tuple[str, ...]) -> None:
    """The official checker's stdout redirection stays in an independent process."""
    if hasattr(os, "setsid"):
        os.setsid()
    signal.signal(signal.SIGTERM, _stop_worker)
    try:
        if file_sha256(instance) != case["sha256"]:
            raise RuntimeError("instance checksum differs from frozen manifest")
        with tempfile.TemporaryDirectory(prefix="rte-x15-") as temp:
            execution = execute(code, instance, Path(temp), seconds=seconds, seed=seed,
                                secure=secure, cpu=cpu, uid=uid,
                                address_space_bytes=address_space_bytes, extra_args=extra_args)
            record = {"case": case["id"], "status": execution["status"], "valid": False,
                      "wall_seconds": execution["wall_seconds"], "score": 0.0,
                      "constraint_errors": {}, "cpu": cpu, "cpu_id": cpu,
                      "worker_pid": os.getpid(),
                      "candidate_peak_rss": execution["candidate_peak_rss"],
                      "peak_rss_unit": "KiB" if sys.platform == "linux" else "bytes"}
            if execution["status"] == "OK":
                check_start = time.monotonic()
                checked = check_solution(instance, execution["output"], support)
                record.update(checked)
                record["checker_wall_seconds"] = time.monotonic() - check_start
                record["status"] = "AC" if checked["valid"] else "WA"
                if checked["valid"]:
                    record["score"] = normalized_score(checked["objective"], case["scale"])
            else:
                record["error"] = execution["status"]
            record["worker_peak_rss_including_checker"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            connection.send({"record": record})
    except Exception as exc:
        connection.send({"infrastructure_error": f"{type(exc).__name__}: {exc}"})
    finally:
        _kill_child()
        connection.close()


def validate_manifest(manifest: dict) -> None:
    cases = manifest.get("cases", [])
    seconds = float(manifest.get("seconds_per_case", 0))
    if not cases or not 0 < seconds <= 5400:
        raise ValueError("nonempty cases and a solve budget in (0,5400] required")
    ids = [case["id"] for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate case IDs")
    for case in cases:
        if Path(case["path"]).is_absolute() or ".." in Path(case["path"]).parts:
            raise ValueError("manifest paths must stay inside the dataset directory")
        if not math.isfinite(case["scale"]) or case["scale"] <= 0:
            raise ValueError("input-only normalization scale must be positive and finite")


def aggregate(records: list[dict], *, elapsed: float, manifest: dict, secure: bool,
              candidate_sha256: str | None, manifest_sha256: str) -> dict:
    valid = all(row["valid"] for row in records)
    failures = Counter(row["status"] for row in records if not row["valid"])
    return {"validity": float(valid),
            "combined_score": sum(r["score"] for r in records) / len(records) if valid else 0.0,
            "cost_time": elapsed, "error_info": "" if valid else json.dumps(dict(failures), sort_keys=True),
            "metric": {"feasible_fraction": sum(bool(r["valid"]) for r in records) / len(records),
                       "mean_official_objective": sum(r["objective"] for r in records) / len(records) if valid else None},
            "cases": records, "split": manifest["split"], "protocol": manifest["protocol"],
            "secure_execution": secure, "candidate_sha256": candidate_sha256,
            "manifest_sha256": manifest_sha256}


def evaluate_manifest(candidate: Path, manifest_path: Path, *, support: Path,
                      secure: bool = True, timeout: float = 1500,
                      workers: int | None = None, extra_args: tuple[str, ...] = ()) -> dict:
    """Evaluate one accepted panel call; the external runtime owns its call ledger."""
    start = time.monotonic()
    manifest_path = manifest_path.resolve()
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    validate_manifest(manifest)
    cases = manifest["cases"]
    workers = int(manifest.get("workers", 15) if workers is None else workers)
    if workers <= 0 or workers > 15:
        raise ValueError("workers must be in [1,15]")
    workers = min(workers, len(cases))
    seconds = float(manifest["seconds_per_case"])
    checker_allowance = float(manifest.get("checker_timeout_seconds", 0))
    staging_allowance = float(manifest.get("staging_timeout_seconds", 0))
    if checker_allowance < 0 or staging_allowance < 0:
        raise ValueError("negative checker/staging allowance")
    per_worker_budget = seconds + checker_allowance + staging_allowance
    if timeout < math.ceil(len(cases) / workers) * per_worker_budget:
        raise ValueError("outer timeout cannot cover all solve/check/staging budgets")
    cpus = sorted(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else list(range(os.cpu_count() or 1))
    if secure:
        if len(cpus) < workers:
            raise RuntimeError("fewer distinct usable CPUs than requested workers")
        quota = Path("/sys/fs/cgroup/cpu.max")
        if quota.exists():
            amount, period = quota.read_text().split()
            if amount != "max" and int(amount) / int(period) + 1e-6 < workers:
                raise RuntimeError("container CPU quota is below requested worker count")
    manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
    try:
        code = regular_bytes(candidate.absolute(), CANDIDATE_LIMIT)
    except (OSError, ValueError):
        records = [{"case": c["id"], "status": "INVALID_SUBMISSION", "valid": False,
                    "score": 0.0, "constraint_errors": {}} for c in cases]
        return aggregate(records, elapsed=time.monotonic() - start, manifest=manifest,
                         secure=secure, candidate_sha256=None, manifest_sha256=manifest_hash)
    context = mp.get_context("spawn")
    pending = list(enumerate(cases))
    active: dict = {}
    records: dict[int, dict] = {}
    free_slots = list(range(workers))
    try:
        while pending or active:
            while pending and free_slots:
                index, case = pending.pop(0)
                slot = free_slots.pop(0)
                receiver, sender = context.Pipe(duplex=False)
                process = context.Process(target=_worker,
                    args=(sender, code, case, manifest_path.parent / case["path"]),
                    kwargs={"support": support.resolve(), "seconds": seconds,
                            "seed": int(manifest["seed"]), "secure": secure,
                            "cpu": cpus[slot] if secure else None, "uid": 64000 + slot,
                            "address_space_bytes": int(manifest.get("address_space_bytes", MEMORY_LIMIT)),
                            "extra_args": extra_args})
                process.start()
                sender.close()
                active[receiver] = (process, index, slot, time.monotonic())
            for receiver in wait(list(active), timeout=0.2):
                process, index, slot, _ = active[receiver]
                try:
                    message = receiver.recv()
                except EOFError as exc:
                    raise RuntimeError("evaluation worker exited without a result") from exc
                if "infrastructure_error" in message:
                    raise RuntimeError(message["infrastructure_error"])
                records[index] = message["record"]
                process.join(timeout=5)
                if process.is_alive():
                    raise RuntimeError("evaluation worker failed to stop")
                receiver.close()
                del active[receiver]
                free_slots.append(slot)
                free_slots.sort()
            now = time.monotonic()
            if now - start > timeout or any(now - row[3] > per_worker_budget for row in active.values()):
                raise TimeoutError("evaluation infrastructure exceeded solve/check/staging budget")
    finally:
        for receiver, (process, _, _, _) in active.items():
            if process.is_alive():
                process.terminate()
        for receiver, (process, _, _, _) in active.items():
            process.join(timeout=5)
            if process.is_alive():
                process.kill()
                process.join(timeout=5)
            receiver.close()
    ordered = [records[i] for i in range(len(cases))]
    return aggregate(ordered, elapsed=time.monotonic() - start, manifest=manifest,
                     secure=secure, candidate_sha256=hashlib.sha256(code).hexdigest(),
                     manifest_sha256=manifest_hash)
