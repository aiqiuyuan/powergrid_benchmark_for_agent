#!/usr/bin/env python3
"""Trusted complete-day scorer; expose only aggregate counted feedback."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(
    0, str(ROOT.parent / "support" if (ROOT.parent / "support").is_dir() else ROOT / "support")
)
from runner import METRIC, evaluate  # noqa: E402


def write(
    reward: float,
    *,
    result: dict | None = None,
    error: str | None = None,
    metric_name="mapdn33_formal_quality_v1",
    metric_direction="higher",
) -> None:
    if (metric_name, metric_direction) != (METRIC, "higher"):
        raise ValueError("The frozen metric contract cannot be changed")
    logs = Path(os.environ.get("LOG_DIR", "/logs/verifier"))
    logs.mkdir(parents=True, exist_ok=True, mode=0o700)
    logs.chmod(0o700)
    aggregates = {key: value for key, value in (result or {}).items() if key != "steps"}
    valid = bool(result and result["valid"])
    feedback = (
        (
            f"reward={reward:.12g}; completed={result['completed_intervals']}/480; "
            + json.dumps(result["metrics"], sort_keys=True)
        )
        if result
        else ""
    )
    details = {
        "reward": reward,
        "metric": reward if result else None,
        "metric_name": metric_name,
        "metric_direction": metric_direction,
        "valid": valid,
        "evaluation_completed": error is None,
        "error": error or (result or {}).get("error"),
        "feedback": feedback,
        "details": aggregates,
    }
    (logs / "reward.json").write_text(json.dumps({"reward": reward}, allow_nan=False) + "\n")
    (logs / "reward-details.json").write_text(json.dumps(details, indent=2, allow_nan=False) + "\n")


def main() -> None:
    write(0, error="evaluation has not completed")
    try:
        case = Path(os.environ.get("CASE_DIR", str(ROOT / "data")))
        app = Path(os.environ.get("APP_DIR", "/app"))
        result = evaluate(app / "submission/controller.py", case, secure=True)
        write(result["reward"], result=result)
        print("MAPDN complete-day evaluation complete")
    except Exception as exc:
        write(0, error=f"{type(exc).__name__}: {exc}")
        raise


if __name__ == "__main__":
    main()
