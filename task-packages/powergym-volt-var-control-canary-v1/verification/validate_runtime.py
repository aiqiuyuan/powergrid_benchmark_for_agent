#!/usr/bin/env python3
"""Run real OpenDSS acceptance checks; local mode cannot certify the sandbox."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import math
import os
import platform
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, os.environ.get("POWERGYM_TESTS_DIR", str(ROOT / "tests")))
from backend import Backend, validate_action  # noqa: E402
from runner import evaluate  # noqa: E402
from score import write as write_feedback  # noqa: E402

RULE = """class Controller:
    def __init__(self, metadata):
        pass
    def act(self, observation):
        values = [v for row in observation['bus_voltages'].values() for v in row]
        direction = -1 if max(values) > 1.06 else (1 if min(values) < .94 else 0)
        taps = [max(0, min(32, tap+direction)) for tap in observation['regulator_taps']]
        return list(observation['capacitor_states']) + taps + [16,16]
"""
DISCHARGE = """class Controller:
    def __init__(self, metadata): pass
    def act(self, observation):
        return list(observation['capacitor_states']) + list(observation['regulator_taps']) + [32,32]
"""
INVALID = """class Controller:
    def __init__(self, metadata): pass
    def act(self, observation): return [0.0]*10
"""
HOLD = """class Controller:
    def __init__(self, metadata): pass
    def act(self, observation):
        return list(observation['capacitor_states']) + list(observation['regulator_taps']) + [16,16]
"""
TIMEOUT = """import time
class Controller:
    def __init__(self, metadata): pass
    def act(self, observation): time.sleep(60)
"""
CRASH = """import os
class Controller:
    def __init__(self, metadata): pass
    def act(self, observation): os._exit(7)
"""
MALFORMED = """import os
class Controller:
    def __init__(self, metadata): pass
    def act(self, observation):
        os.write(1, b'not-json\\n')
        return [1,1]+[16]*8
"""


def compact(result: dict) -> dict:
    return {key: value for key, value in result.items() if key != "trajectory"}


def run_one(controller: Path, data: Path, secure: bool) -> dict:
    return compact(evaluate(controller, data, secure=secure))


def acceptance(data: Path, secure: bool) -> dict:
    starter = Path(
        os.environ.get("POWERGYM_STARTER", str(ROOT / "environment/app/submission/controller.py"))
    )
    starter_result = run_one(starter, data, secure)
    assert starter_result["valid"] and starter_result["completed_steps"] == 24
    assert starter_result["battery_throughput_kwh"] == 0
    assert starter_result["final_soc"] == [1.0, 1.0]
    with tempfile.TemporaryDirectory(prefix="powergym-controls-") as directory:
        path = Path(directory)
        rule, discharge, invalid, hold = [
            path / f"{name}.py" for name in ("rule", "discharge", "invalid", "hold")
        ]
        rule.write_text(RULE)
        discharge.write_text(DISCHARGE)
        invalid.write_text(INVALID)
        hold.write_text(HOLD)
        baseline = run_one(hold, data, secure)
        changed = run_one(rule, data, secure)
        drained = run_one(discharge, data, secure)
        assert changed["valid"] and changed["completed_steps"] == 24
        assert changed["final_soc"] == [1.0, 1.0]
        assert abs(changed["reward"] - baseline["reward"]) > 1e-8
        assert drained["reward"] == 0 and not drained["valid"]
        assert max(drained["terminal_energy_error_kwh"]) > 1
        rejected = run_one(invalid, data, secure)
        assert not rejected["valid"] and rejected["reward"] == 0
        assert rejected["evaluation_completed"] and rejected["error"] == "invalid_action"
        invalid_rejected = True
        failures = {}
        for name, source, expected_error in (
            ("timeout", TIMEOUT, "candidate_timeout"),
            ("crash", CRASH, "candidate_exit"),
            ("malformed_json", MALFORMED, "candidate_malformed_json"),
            ("import_crash", "raise RuntimeError('candidate import failed')\n", "candidate_exit"),
        ):
            file = path / f"{name}.py"
            file.write_text(source)
            result = run_one(file, data, secure)
            assert result["reward"] == 0 and not result["valid"]
            assert result["evaluation_completed"] and result["error"] == expected_error
            assert result["completed_steps"] == 0 and result["candidate_sha256"]
            log = path / f"{name}-feedback"
            with patch.dict(os.environ, {"LOG_DIR": str(log)}):
                write_feedback(result)
            feedback = json.loads((log / "reward-details.json").read_text())
            assert feedback["evaluation_completed"] is True
            assert feedback["reward"] == 0 and feedback["valid"] is False
            assert feedback["error"] == expected_error
            failures[name] = {
                "evaluation_completed": True,
                "reward": 0,
                "error": expected_error,
                "candidate_sha256": result["candidate_sha256"],
            }
    for action in ([True] + [16] * 9, [0] * 9, [2, 0] + [16] * 8, [0, 0] + [33] * 8):
        try:
            validate_action(action)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid action was accepted")

    # Independent OS processes each copy the complete trusted circuit directory.
    def independently():
        command = [
            sys.executable,
            str(Path(__file__).resolve()),
            "--data",
            str(data),
            "--one",
            str(starter),
        ]
        if secure:
            command.append("--secure")
        result = subprocess.run(command, capture_output=True, text=True, check=True, timeout=120)
        return json.loads(result.stdout)

    with ThreadPoolExecutor(max_workers=2) as pool:
        parallel = list(pool.map(lambda _: independently(), range(2)))
    numerical = (
        "reward",
        "active_loss_kwh",
        "voltage_violation_pu_hours",
        "phase_time_compliance",
        "min_voltage_pu",
        "max_voltage_pu",
    )
    for repeated in parallel:
        assert all(
            math.isclose(repeated[key], starter_result[key], rel_tol=1e-12, abs_tol=1e-12)
            for key in numerical
        )
    # Explicit load rows and actual tap winding agree with the frozen commands.
    backend = Backend(data)
    for step in range(24):
        tap = [0, 16, 32][step % 3]
        backend.advance([1, 1] + [tap] * 6 + [16, 16])
        for index, name in enumerate(backend.loads):
            backend.circuit.Loads.Name = name
            expected = backend.nominal[index][0] * backend.case["multipliers"][index][step]
            assert math.isclose(backend.circuit.Loads.kW, expected, abs_tol=1e-10)
        for name in backend.regulators:
            backend.circuit.Transformers.Name = name
            backend.circuit.Transformers.Wdg = 2
            assert backend.circuit.Transformers.NumTaps == 32
            assert math.isclose(
                backend.circuit.Transformers.Tap, 0.9 + tap * 0.2 / 32, abs_tol=1e-10
            )
    return {
        "status": "passed",
        "platform": platform.platform(),
        "python": platform.python_version(),
        "dependencies": {
            name: importlib.metadata.version(name)
            for name in (
                "dss-python",
                "dss-python-backend",
                "numpy",
                "cffi",
                "pycparser",
                "typing_extensions",
            )
        },
        "sandbox_validated": secure,
        "starter": starter_result,
        "hold_idle": baseline,
        "voltage_rule": changed,
        "drain_battery_rejected": compact(drained),
        "invalid_action_rejected": invalid_rejected,
        "candidate_failure_feedback": failures,
        "parallel_replays_equal": True,
        "explicit_load_row_and_tap_checks": True,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--secure", action="store_true")
    parser.add_argument("--one", type=Path)
    args = parser.parse_args()
    result = (
        run_one(args.one, args.data.resolve(), args.secure)
        if args.one
        else acceptance(args.data.resolve(), args.secure)
    )
    output = json.dumps(result, indent=2, allow_nan=False) + "\n"
    if args.output:
        args.output.write_text(output)
    print(output)
