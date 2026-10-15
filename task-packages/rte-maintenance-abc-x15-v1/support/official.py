"""Strict output validation followed by the unmodified, pinned RTE checker."""
from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import math
import os
from pathlib import Path
import stat
import tempfile



def regular_bytes(path: Path, limit: int) -> bytes:
    """Do not follow candidate symlinks, FIFOs, or oversized output files."""
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise ValueError("output must be a bounded regular file")
        content = stream.read(limit + 1)
    if len(content) > limit:
        raise ValueError("output exceeds size limit")
    return content


def check_solution(instance_path: Path, solution_path: Path, support: Path) -> dict:
    """Keep upstream feasibility and quantile semantics; never score invalid output."""
    import numpy as np

    vendor = support / "vendor"
    lock = json.loads((support / "source-lock.json").read_text())
    checker_path = vendor / "RTE_ChallengeROADEF2020_checker.py"
    expected = lock["files"][checker_path.name]["sha256"]
    if hashlib.sha256(checker_path.read_bytes()).hexdigest() != expected:
        raise RuntimeError("official checker hash mismatch")
    instance = json.loads(instance_path.read_text())
    try:
        text = regular_bytes(solution_path, 4 << 20).decode("utf-8")
        schedule: dict[str, int] = {}
        for line in text.splitlines():
            parts = line.split()
            if len(parts) != 2:
                raise ValueError("each output line must contain an intervention and integer start")
            name, token = parts
            if name not in instance["Interventions"] or name in schedule:
                raise ValueError("unknown or duplicate intervention")
            start = int(token)
            job = instance["Interventions"][name]
            if not 1 <= start <= min(instance["T"], int(job["tmax"])):
                raise ValueError("start outside its admissible range")
            duration = int(job["Delta"][start - 1])
            if duration <= 0 or start + duration > instance["T"] + 1:
                raise ValueError("intervention does not finish within the horizon")
            schedule[name] = start
        if set(schedule) != set(instance["Interventions"]):
            raise ValueError("missing interventions")
    except (OSError, UnicodeError, ValueError) as exc:
        return {"valid": False, "error": str(exc), "constraint_errors": {"format_or_schedule": 1}}
    spec = importlib.util.spec_from_file_location("rte_official_checker", checker_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    capture = io.StringIO()
    with tempfile.TemporaryDirectory(prefix="rte-check-") as temp:
        canonical = Path(temp) / "solution.txt"
        canonical.write_text("".join(f"{name} {start}\n" for name, start in schedule.items()))
        with contextlib.redirect_stdout(capture):
            module.read_solution_from_txt(instance, str(canonical))
            module.check_all_constraints(instance)
            # The official CLI otherwise continues to compute invalid objectives.
            errors = [line for line in capture.getvalue().splitlines() if "ERROR:" in line]
            if not errors:
                mean, quantile = module.compute_objective(instance)
    if errors:
        counts: dict[str, int] = {}
        for error in errors:
            kind = "resource_upper" if "upper bound" in error else (
                "resource_lower" if "lower bound" in error else (
                    "exclusion" if "Exclusions" in error else "schedule"))
            counts[kind] = counts.get(kind, 0) + 1
        return {"valid": False, "error": "official constraint check failed", "constraint_errors": counts}
    mean_risk = float(np.mean(mean))
    excess = float(np.mean(np.maximum(quantile - mean, 0)))
    objective = float(instance["Alpha"] * mean_risk + (1 - instance["Alpha"]) * excess)
    if not all(math.isfinite(value) for value in (mean_risk, excess, objective)):
        raise RuntimeError("official checker produced a non-finite objective")
    return {"valid": True, "objective": objective, "mean_risk": mean_risk,
            "expected_excess": excess, "error": "", "constraint_errors": {}}


def normalized_score(objective: float, scale: float) -> float:
    """Strictly decreasing for signed costs, bounded in (0, 1). Not a contest rank."""
    if not math.isfinite(objective) or not math.isfinite(scale) or scale <= 0:
        raise ValueError("finite objective and positive finite scale required")
    ratio = objective / scale
    # Equivalent to 0.5 - atan(ratio)/pi, without cancellation at large costs.
    if ratio > 0:
        return math.atan(1.0 / ratio) / math.pi
    if ratio < 0:
        return 1.0 - math.atan(-1.0 / ratio) / math.pi
    return 0.5
