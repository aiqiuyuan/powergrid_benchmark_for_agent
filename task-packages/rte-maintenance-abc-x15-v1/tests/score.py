#!/usr/bin/env python3
"""Trusted whole-X15 feedback entry; only aggregate diagnostics leave the judge."""
from collections import Counter
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "support"))
from runner import evaluate_manifest

METRIC_NAME = "rte_x15_quality_900"
METRIC_DIRECTION = "higher"


def aggregate_feedback(result: dict) -> str:
    counts = Counter(row["status"] for row in result["cases"])
    violations = Counter()
    for row in result["cases"]:
        violations.update(row.get("constraint_errors", {}))
    feedback = (f"normalized_score={result['combined_score']:.12g}; "
                f"feasible_fraction={result['metric']['feasible_fraction']:.3f}; "
                f"verdicts={dict(sorted(counts.items()))}; "
                f"constraint_errors={dict(sorted(violations.items()))}")
    if result["validity"]:
        cases = result["cases"]
        feedback += (f"; mean_official_objective={result['metric']['mean_official_objective']:.12g}"
                     f"; mean_risk={sum(c['mean_risk'] for c in cases)/len(cases):.12g}"
                     f"; mean_excess={sum(c['expected_excess'] for c in cases)/len(cases):.12g}")
    return feedback


def write(reward: float, *, result: dict | None = None, error: str | None = None,
          metric_name: str = METRIC_NAME, metric_direction: str = METRIC_DIRECTION) -> None:
    if (metric_name, metric_direction) != (METRIC_NAME, METRIC_DIRECTION):
        raise ValueError("feedback metric differs from the locked task metric")
    log_dir = Path(os.environ.get("LOG_DIR", "/logs/verifier"))
    log_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    log_dir.chmod(0o700)
    details = {"reward": reward, "metric": reward if result else None,
               "metric_name": metric_name, "metric_direction": metric_direction,
               "valid": bool(result and result.get("validity") and all(c.get("valid") for c in result["cases"])),
               "evaluation_completed": error is None, "error": error,
               "feedback": aggregate_feedback(result) if result else "",
               "details": result or {}}
    # A completed evaluation can still contain an infeasible candidate panel.
    (log_dir / "reward.json").write_text(json.dumps({"reward": reward}, allow_nan=False) + "\n")
    (log_dir / "reward-details.json").write_text(json.dumps(details, indent=2, allow_nan=False) + "\n")


def main() -> None:
    write(0.0, error="evaluation did not finish")
    try:
        manifest = json.loads((ROOT / "data/manifest.json").read_text())
        expected = [f"X_{n:02d}" for n in range(1, 16)]
        if (manifest["split"] != "protected_x15_feedback"
                or manifest["seconds_per_case"] != 900 or manifest["workers"] != 15
                or [c["id"] for c in manifest["cases"]] != expected):
            raise ValueError("feedback manifest must be the locked X15/900-second panel")
        result = evaluate_manifest(Path(os.environ.get("APP_DIR", "/app")) / "submission/solver.py",
                                   ROOT / "data/manifest.json", support=ROOT / "support",
                                   secure=True, timeout=1500, workers=15)
        write(result["combined_score"], result=result,
              metric_name="rte_x15_quality_900", metric_direction="higher")
        print("RTE whole-panel evaluation complete")
    except Exception as exc:
        # Detailed private errors are retained only in trusted verifier logs.
        write(0.0, error=f"{type(exc).__name__}: {exc}")
        raise


if __name__ == "__main__":
    main()
