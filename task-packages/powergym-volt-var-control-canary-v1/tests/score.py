#!/usr/bin/env python3
"""Native counted-feedback and final-replay entry for the same full-day case."""

import json
import os
from pathlib import Path

from runner import evaluate


def write(
    result=None,
    error=None,
    *,
    metric_name="powergym_canary_quality",
    metric_direction="higher",
):
    if (metric_name, metric_direction) != ("powergym_canary_quality", "higher"):
        raise ValueError("The frozen metric contract cannot be changed")
    log = Path(os.environ.get("LOG_DIR", "/logs/verifier"))
    log.mkdir(parents=True, exist_ok=True, mode=0o700)
    log.chmod(0o700)
    reward = result["reward"] if result else 0.0
    fields = [
        "reward",
        "valid",
        "completed_steps",
        "active_loss_kwh",
        "voltage_violation_pu_hours",
        "phase_time_compliance",
        "capacitor_switches",
        "tap_moves",
        "final_soc",
        "terminal_energy_error_kwh",
        "candidate_sha256",
        "error",
    ]
    summary = {name: result[name] for name in fields} if result else {}
    details = {
        "reward": reward,
        "metric": reward if result else None,
        "metric_name": metric_name,
        "metric_direction": metric_direction,
        "valid": bool(result and result["valid"]),
        "evaluation_completed": bool(result and result["evaluation_completed"]),
        "error": error if error is not None else (result.get("error") if result else None),
        "feedback": json.dumps(summary, separators=(",", ":")),
        # No full voltage/actions/profile trajectory in feedback details.
        "details": summary,
    }
    (log / "reward.json").write_text(json.dumps({"reward": reward}, allow_nan=False) + "\n")
    (log / "reward-details.json").write_text(json.dumps(details, indent=2, allow_nan=False) + "\n")


def main():
    write(error="evaluation did not finish")
    root = Path(__file__).resolve().parent
    try:
        result = evaluate(
            Path(os.environ.get("APP_DIR", "/app")) / "submission/controller.py",
            root / "data",
            secure=True,
        )
        write(result)
        print("PowerGym evaluation completed")
    except Exception as exc:
        write(error=type(exc).__name__)
        raise


if __name__ == "__main__":
    main()
