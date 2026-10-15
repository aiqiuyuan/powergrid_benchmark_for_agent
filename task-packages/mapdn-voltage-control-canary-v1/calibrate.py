#!/usr/bin/env python3
"""Trusted preparation-only real-backend baselines; never install in development."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "support"))
from runner import evaluate  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True, mode=0o700)
    records = {}
    starter = ROOT / "environment/app/submission/controller.py"
    zero = (
        "class Controller:\n def __init__(self, metadata): pass\n"
        " def act(self, obs): return [0.0]\n"
    )
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "controller.py"
        for name, code in (
            ("zero_q", zero.encode()),
            ("droop", starter.read_bytes()),
            ("droop_replay", starter.read_bytes()),
        ):
            path.write_bytes(code)
            result = evaluate(path, args.case, secure=False)
            (args.output / (name + ".json")).write_text(
                json.dumps(result, indent=2, allow_nan=False) + "\n"
            )
            summary = {key: value for key, value in result.items() if key != "steps"}
            summary["step_metrics_sha256"] = hashlib.sha256(
                json.dumps(result["steps"], sort_keys=True, allow_nan=False).encode()
            ).hexdigest()
            records[name] = summary
            print(json.dumps({"baseline": name, **summary}, allow_nan=False), flush=True)
    if not all(
        record["valid"] and record["completed_intervals"] == 480 for record in records.values()
    ):
        raise RuntimeError("a complete-day baseline did not finish validly")
    if records["droop"]["step_metrics_sha256"] != records["droop_replay"]["step_metrics_sha256"]:
        raise RuntimeError("identical controller and frozen case did not replay exactly")
    if records["zero_q"]["metrics"] == records["droop"]["metrics"]:
        raise RuntimeError("real metrics did not respond to different legal controllers")
    (args.output / "summary.json").write_text(json.dumps(records, indent=2, allow_nan=False) + "\n")


if __name__ == "__main__":
    main()
