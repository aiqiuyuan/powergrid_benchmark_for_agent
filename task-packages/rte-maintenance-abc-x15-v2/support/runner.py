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
STDERR_TAIL_LIMIT = 8 << 10
MEMORY_LIMIT = 16 << 30  # RLIMIT_AS, not a measured resident-memory requirement.
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


def _stderr_tail(path: Path) -> str:
    """Retain bounded private diagnostics before temporary scratch cleanup."""
    with path.open("rb") as stream:
        stream.seek(0, os.SEEK_END)
        stream.seek(max(0, stream.tell() - STDERR_TAIL_LIMIT))
        tail = stream.read(STDERR_TAIL_LIMIT).decode("utf-8", errors="replace")
    # Replacement characters may expand malformed bytes; bound encoded UTF-8 too.
    return tail.encode("utf-8")[-STDERR_TAIL_LIMIT:].decode("utf-8", errors="ignore")


def execute(candidate: Path | bytes, instance: Path, scratch: Path, *, seconds: float,
            seed: int, secure: bool, cpu: int | None = None, uid: int = 64000,
            address_space_bytes: int = MEMORY_LIMIT,
            extra_args: tuple[str, ...] = ()) -> dict:
    """One candidate process; its wall budget includes imports, parsing and output."""
    global _ACTIVE_CHILD
    staging_start = time.monotonic()
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
    staging_wall_seconds = start - staging_start
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
    candidate_wall_seconds = time.monotonic() - start
    return {"status": "TLE" if timed_out else ("RE" if process.returncode else "OK"),
            "wall_seconds": candidate_wall_seconds, "returncode": process.returncode,
            "staging_wall_seconds": staging_wall_seconds,
            "candidate_stderr_tail": _stderr_tail(scratch / "stderr.log"),
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
        hash_start = time.monotonic()
        if file_sha256(instance) != case["sha256"]:
            raise RuntimeError("instance checksum differs from frozen manifest")
        hash_wall_seconds = time.monotonic() - hash_start
        with tempfile.TemporaryDirectory(prefix="rte-x15-") as temp:
            execution = execute(code, instance, Path(temp), seconds=seconds, seed=seed,
                                secure=secure, cpu=cpu, uid=uid,
                                address_space_bytes=address_space_bytes, extra_args=extra_args)
            record = {"case": case["id"], "status": execution["status"], "valid": False,
                      "wall_seconds": execution["wall_seconds"], "score": 0.0,
                      "constraint_errors": {}, "cpu": cpu, "cpu_id": cpu,
                      "worker_pid": os.getpid(),
                      "candidate_returncode": execution["returncode"],
                      "candidate_stderr_tail": execution["candidate_stderr_tail"],
                      "staging_wall_seconds": hash_wall_seconds + execution["staging_wall_seconds"],
                      "candidate_wall_seconds": execution["wall_seconds"],
                      "checker_wall_seconds": 0.0,
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
        if (isinstance(case["scale"], bool) or not isinstance(case["scale"], (int, float))
                or not math.isfinite(case["scale"]) or case["scale"] <= 0):
            raise ValueError("input-only normalization scale must be positive and finite")


def aggregate(records: list[dict], *, elapsed: float, manifest: dict, secure: bool,
              candidate_sha256: str | None, manifest_sha256: str) -> dict:
    """Coverage first, then fixed-panel quality; never hide partial valid objectives."""
    cases = manifest["cases"]
    records = [dict(row) for row in records]
    expected = [case["id"] for case in cases]
    if (not expected or len(set(expected)) != len(expected)
            or [row.get("case") for row in records] != expected):
        raise ValueError("evaluation records must cover the complete ordered unique panel")
    for row, case in zip(records, cases):
        if (isinstance(case.get("scale"), bool)
                or not isinstance(case.get("scale"), (int, float))
                or not math.isfinite(case["scale"]) or case["scale"] <= 0):
            raise ValueError("input-only normalization scale must be positive and finite")
        if type(row.get("valid")) is not bool:
            raise ValueError("case validity must be boolean")
        if row.get("status") not in {"AC", "WA", "RE", "TLE", "INVALID_SUBMISSION"}:
            raise ValueError("unknown candidate status")
        if row["valid"] != (row["status"] == "AC"):
            raise ValueError("case status and validity disagree")
        quality = row.get("score")
        if (not isinstance(quality, (int, float)) or isinstance(quality, bool)
                or not math.isfinite(quality) or not 0 <= quality <= 1):
            raise ValueError("case quality must be a finite value in [0,1]")
        if row["valid"]:
            if any(not isinstance(row.get(key), (int, float))
                   or isinstance(row.get(key), bool) or not math.isfinite(row[key])
                   for key in ("objective", "mean_risk", "expected_excess")):
                raise ValueError("valid cases require finite official objective components")
            if not math.isclose(quality, normalized_score(row["objective"], case["scale"]),
                                rel_tol=1e-12, abs_tol=1e-15):
                raise ValueError("case quality differs from fixed official-objective mapping")
        elif quality != 0:
            raise ValueError("invalid cases must contribute zero quality")
        else:
            for key in ("objective", "mean_risk", "expected_excess"):
                row[key] = None
    count = len(records)
    feasible = sum(row["valid"] for row in records)
    quality = math.fsum(row["score"] for row in records) / count
    all_feasible = feasible == count
    failures = Counter(row["status"] for row in records if not row["valid"])
    return {"validity": float(all_feasible), "all_cases_feasible": all_feasible,
            "evaluation_completed": True, "panel_size": count,
            "seconds_per_case": manifest["seconds_per_case"],
            "combined_score": (feasible + quality) / (count + 1),
            "cost_time": elapsed,
            "error_info": "" if all_feasible else json.dumps(dict(failures), sort_keys=True),
            "metric": {"feasible_count": feasible, "feasible_fraction": feasible / count,
                       "quality": quality,
                       "mean_official_objective": math.fsum(row["objective"] for row in records
                                                            if row["valid"]) / feasible if feasible else None},
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
