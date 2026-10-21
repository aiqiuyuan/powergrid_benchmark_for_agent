#!/usr/bin/env python3
"""Trusted-only action-plan replays; outputs summaries and hashes, never plans."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, os.environ.get("POWERGYM_TESTS_DIR", str(ROOT / "tests")))
from runner import evaluate  # noqa: E402


def replay(data: Path, references: Path, secure: bool) -> dict:
    records = []
    expected_names = {
        "hold_idle",
        "canary_hysteresis",
        "coordinated_voltage",
        "full_information_snapshot",
        "static_day_idle",
        "strong_current_idle",
        "oracle_day_idle",
        "oracle_day_storage",
        "best_active_storage",
    }
    files = sorted(references.glob("*.json"))
    if {p.stem for p in files} != expected_names:
        raise ValueError("all nine preregistered qualified references are required")
    for path in files:
        content = path.read_bytes()
        expected = json.loads(content)
        if hashlib.sha256(content).hexdigest() != path.with_suffix(".sha256").read_text().strip():
            raise ValueError("reference identity mismatch")
        if expected["case_id"] != "123Bus-stress-p000-s2.5":
            raise ValueError("reference case differs from formal case")
        plan = [row["action"] for row in expected["trajectory"]]
        with tempfile.TemporaryDirectory(prefix="powergym-trusted-plan-") as temporary:
            controller = Path(temporary) / "controller.py"
            controller.write_text(
                "class Controller:\n"
                "    def __init__(self, metadata):\n"
                f"        self.plan = {plan!r}\n"
                "    def act(self, observation):\n"
                '        return self.plan[observation["step"]]\n'
            )
            actual = evaluate(controller, data, secure=secure)
        for old, new in zip(expected["trajectory"], actual["trajectory"], strict=True):
            for key in old:
                if actual["trajectory"] and old[key] != new[key]:
                    raise ValueError(f"exact row mismatch: {path.stem}, {old['step']}, {key}")
        for key in (
            "active_loss_kwh",
            "voltage_violation_pu_hours",
            "actual_net_energy_kwh",
            "terminal_energy_error_kwh",
            "capacitor_switches",
            "tap_moves",
        ):
            if actual[key] != expected[key]:
                raise ValueError(f"aggregate mismatch: {path.stem}, {key}")
        if (
            actual["valid"] != expected["qualification_valid"]
            or actual["reward"] != expected["canary_quality"]
        ):
            raise ValueError("formal hard gates or quality differ from qualified reference")
        records.append(
            {
                "baseline": path.stem,
                "reference_sha256": hashlib.sha256(content).hexdigest(),
                "permissions": expected["permissions"],
                "interpretation": (
                    "trusted recorded-plan numerical parity; "
                    "not a legal observation-only controller"
                ),
                "all_24_rows_exact": True,
                **{
                    key: actual[key]
                    for key in (
                        "valid",
                        "reward",
                        "completed_steps",
                        "active_loss_kwh",
                        "voltage_violation_pu_hours",
                        "phase_time_compliance",
                        "actual_net_energy_kwh",
                        "terminal_energy_error_kwh",
                        "wall_seconds",
                        "pf_calls",
                        "candidate_sha256",
                    )
                },
            }
        )
    legal = evaluate(
        Path(__file__).resolve().with_name("observation_reference.py"), data, secure=secure
    )
    reference = json.loads((references / "coordinated_voltage.json").read_text())
    for actual_row, expected_row in zip(legal["trajectory"], reference["trajectory"], strict=True):
        for key in expected_row:
            if actual_row[key] != expected_row[key]:
                raise ValueError("observation-only controller differs from qualified reference")
    return {
        "same_information_coordinated_reference": {
            "complete_legal_controller_replay_exact": True,
            "source_sha256": legal["candidate_sha256"],
            "valid": legal["valid"],
            "reward": legal["reward"],
            "wall_seconds": legal["wall_seconds"],
        },
        "schema_version": "powergym-formal-reference-parity-v1",
        "status": "passed",
        "sandbox_validated": secure,
        "records": records,
        "all_candidate_episodes_below_30_seconds": all(r["wall_seconds"] < 30 for r in records),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--references", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--secure", action="store_true")
    args = parser.parse_args()
    result = replay(args.data.resolve(), args.references.resolve(), args.secure)
    with args.output.open("x") as stream:
        stream.write(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"status": result["status"], "records": len(result["records"])}))
