#!/usr/bin/env python3
"""Trusted X15 evaluator; only versioned whitelist diagnostics leave the judge."""
from collections import Counter
import json
import math
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "support"))
from runner import evaluate_manifest

METRIC_NAME = "rte_x15_coverage_quality_900_v2"
METRIC_DIRECTION = "higher"
FEEDBACK_LIMIT = 16 << 10
PROTOCOL = "rte2020-abc-x15-v2"
CASE_IDS = [f"X_{n:02d}" for n in range(1, 16)]
CONSTRAINT_KINDS = {"format_or_schedule", "resource_upper", "resource_lower", "exclusion", "schedule"}


def bounded_number(value: object, *, optional: bool = False, integer: bool = False,
                   nonnegative: bool = False) -> float | int | None:
    if value is None and optional:
        return None
    if (isinstance(value, bool) or not isinstance(value, int if integer else (int, float))
            or not math.isfinite(value) or (nonnegative and value < 0)):
        raise ValueError("feedback requires finite numeric diagnostics")
    if integer and abs(value) > (1 << 63) - 1:
        raise ValueError("integer diagnostic outside supported range")
    return value


def encode_feedback(value: dict) -> str:
    encoded = json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > FEEDBACK_LIMIT:
        raise ValueError("structured feedback exceeds the 16 KiB limit")
    return encoded


def aggregate_feedback(result: dict) -> str:
    if (result.get("protocol") != PROTOCOL or result.get("seconds_per_case") != 900
            or result.get("split") != "protected_x15_feedback"
            or result.get("evaluation_completed") is not True
            or result.get("panel_size") != 15
            or [row.get("case") for row in result["cases"]] != CASE_IDS):
        raise ValueError("feedback requires the complete ordered v2 X15/900-second panel")
    digest = result.get("candidate_sha256")
    if digest is not None and (not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)):
        raise ValueError("invalid candidate digest")
    rows = []
    counts = Counter()
    violations = Counter()
    for row in result["cases"]:
        private_status = row["status"]
        status = "RE" if private_status == "INVALID_SUBMISSION" else private_status
        if (status not in {"AC", "WA", "RE", "TLE"}
                or type(row.get("valid")) is not bool or row["valid"] != (status == "AC")):
            raise ValueError("unknown or inconsistent feedback case status")
        constraint_errors = row.get("constraint_errors", {})
        if not isinstance(constraint_errors, dict) or not set(constraint_errors) <= CONSTRAINT_KINDS:
            raise ValueError("unknown constraint diagnostic category")
        constraints = {key: bounded_number(value, integer=True, nonnegative=True)
                       for key, value in sorted(constraint_errors.items())}
        counts[status] += 1
        violations.update(constraints)
        valid = row["valid"]
        unit = row.get("peak_rss_unit")
        if unit not in {None, "KiB", "bytes"}:
            raise ValueError("unknown peak RSS unit")
        rss = bounded_number(row.get("candidate_peak_rss"), optional=True,
                             integer=True, nonnegative=True)
        if (rss is None) != (unit is None):
            raise ValueError("peak RSS and its unit must be supplied together")
        rows.append({"id": row["case"], "status": status,
                     "failure_kind": "invalid_submission" if private_status == "INVALID_SUBMISSION" else None,
                     "F": bounded_number(row.get("objective")) if valid else None,
                     "mean_risk": bounded_number(row.get("mean_risk")) if valid else None,
                     "expected_excess": bounded_number(row.get("expected_excess")) if valid else None,
                     "q": bounded_number(row["score"], nonnegative=True) if valid else None,
                     "constraint_errors": constraints,
                     "candidate_returncode": bounded_number(row.get("candidate_returncode"),
                                                              optional=True, integer=True),
                     "candidate_wall_seconds": bounded_number(row.get("candidate_wall_seconds"),
                                                                 optional=True, nonnegative=True),
                     "candidate_peak_rss": rss, "candidate_peak_rss_unit": unit})
    feasible = counts["AC"]
    if digest is None and any(row["failure_kind"] != "invalid_submission" for row in rows):
        raise ValueError("a readable candidate requires a SHA256 digest")
    quality = math.fsum(row["q"] for row in rows if row["q"] is not None) / 15
    reward = (feasible + quality) / 16
    if (result.get("all_cases_feasible") is not (feasible == 15)
            or result.get("validity") != float(feasible == 15)
            or any(row["q"] is not None and not 0 <= row["q"] <= 1 for row in rows)
            or result["metric"]["feasible_count"] != feasible
            or not math.isclose(result["metric"]["quality"], quality, rel_tol=1e-12, abs_tol=1e-15)
            or not math.isclose(result["combined_score"], reward, rel_tol=1e-12, abs_tol=1e-15)):
        raise ValueError("feedback summary and case records disagree")
    return encode_feedback({"schema_version": "rte-feedback-v2", "candidate_sha256": digest,
                            "seconds_per_case": 900, "panel_size": 15,
                            "evaluation_completed": True,
                            "summary": {"feasible_count": feasible, "feasible_fraction": feasible / 15,
                                        "quality": quality, "reward": reward,
                                        "all_cases_feasible": feasible == 15,
                                        "statuses": dict(sorted(counts.items())),
                                        "constraint_errors": dict(sorted(violations.items()))},
                            "cases": rows})


def write(reward: float, *, result: dict | None = None, error: str | None = None,
          metric_name: str = METRIC_NAME, metric_direction: str = METRIC_DIRECTION) -> None:
    if (metric_name, metric_direction) != (METRIC_NAME, METRIC_DIRECTION):
        raise ValueError("feedback metric differs from the locked task metric")
    if result is not None and error is not None:
        raise ValueError("completed result and infrastructure error are mutually exclusive")
    if result is not None:
        feedback = aggregate_feedback(result)
        if not math.isclose(reward, result["combined_score"], rel_tol=1e-12, abs_tol=1e-15):
            raise ValueError("reward differs from completed panel")
    else:
        if error is None:
            raise ValueError("an incomplete evaluation requires an infrastructure error")
        feedback = encode_feedback({"schema_version": "rte-feedback-v2", "candidate_sha256": None,
                                    "seconds_per_case": 900, "panel_size": 15,
                                    "evaluation_completed": False,
                                    "error": "evaluation_infrastructure_failure",
                                    "summary": None, "cases": []})
    log_dir = Path(os.environ.get("LOG_DIR", "/logs/verifier"))
    log_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    log_dir.chmod(0o700)
    details = {"reward": reward, "metric": reward if result is not None else None,
               "metric_name": metric_name, "metric_direction": metric_direction,
               "valid": bool(result and result["all_cases_feasible"]),
               "all_cases_feasible": bool(result and result["all_cases_feasible"]),
               "evaluation_completed": result is not None, "error": error,
               "feedback": feedback, "details": result or {}}
    (log_dir / "reward.json").write_text(json.dumps({"reward": reward}, allow_nan=False) + "\n")
    (log_dir / "reward-details.json").write_text(json.dumps(details, indent=2, allow_nan=False) + "\n")


def main() -> None:
    write(0.0, error="evaluation did not finish")
    try:
        manifest = json.loads((ROOT / "data/manifest.json").read_text())
        if (manifest["split"] != "protected_x15_feedback" or manifest["protocol"] != PROTOCOL
                or manifest["seconds_per_case"] != 900 or manifest["workers"] != 15
                or [case["id"] for case in manifest["cases"]] != CASE_IDS):
            raise ValueError("feedback manifest must be the locked v2 X15/900-second panel")
        result = evaluate_manifest(Path(os.environ.get("APP_DIR", "/app")) / "submission/solver.py",
                                   ROOT / "data/manifest.json", support=ROOT / "support",
                                   secure=True, timeout=1500, workers=15)
        write(result["combined_score"], result=result)
        print("RTE whole-panel evaluation complete")
    except Exception as exc:
        write(0.0, error=f"{type(exc).__name__}: {exc}")
        raise


if __name__ == "__main__":
    main()
