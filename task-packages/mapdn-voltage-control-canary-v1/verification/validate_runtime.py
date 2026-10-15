#!/usr/bin/env python3
"""Trusted Linux acceptance; emitted receipt contains booleans, never target scores."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "support"))
from runner import evaluate, secure_readiness  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    receipt = {
        "status": "failed",
        "secure_execution": True,
        "container_entrypoint_pid": os.getpid(),
        "checks": {},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt) + "\n")
    with tempfile.TemporaryDirectory(prefix="mapdn-acceptance-") as temporary:
        temporary = Path(temporary)
        probe = subprocess.run(
            [
                sys.executable,
                str(ROOT / "probe_sandbox.py"),
                "--output",
                str(temporary / "sandbox.json"),
            ],
            capture_output=True,
            timeout=30,
        )
        if probe.returncode:
            raise RuntimeError("Linux filesystem/IPC negative probes did not pass")
        receipt["checks"]["filesystem_ipc_and_network_isolation"] = True
        secure_readiness()
        receipt["checks"]["sandbox_readiness_from_native_entrypoint"] = True
        droop = evaluate(args.candidate, args.case, secure=True)
        replay = evaluate(args.candidate, args.case, secure=True)
        zero_path = temporary / "zero.py"
        zero_path.write_text(
            "class Controller:\n def __init__(self, metadata): pass\n"
            " def act(self, observation): return [0.0]\n"
        )
        zero = evaluate(zero_path, args.case, secure=True)
        for result in (droop, replay, zero):
            assert result["valid"] and result["completed_intervals"] == 480
            assert result["pf_calls"] == 960 and result["secure_execution"]
            assert result["metrics"]["max_power_balance_residual_mw"] <= 1e-7
        receipt["checks"]["complete_480_interval_960_pf_valid"] = True
        receipt["checks"]["active_loss_energy_balance"] = True
        assert droop["steps"] == replay["steps"]
        receipt["checks"]["deterministic_independent_replay"] = True
        assert droop["metrics"] != zero["metrics"]
        receipt["checks"]["physical_metrics_respond_to_controller"] = True
        invalid_path = temporary / "invalid.py"
        invalid_path.write_text(
            "class Controller:\n def __init__(self, metadata): pass\n"
            " def act(self, observation): return [float('nan')]\n"
        )
        invalid = evaluate(invalid_path, args.case, secure=True)
        assert not invalid["valid"] and invalid["reward"] == 0
        receipt["checks"]["candidate_failure_zero_complete_episode_reward"] = True
        oversized_path = temporary / "oversized.py"
        oversized_path.write_text(
            "class Controller:\n"
            " def __init__(self, metadata): self.buffer = bytearray(512 * 1024 * 1024)\n"
            " def act(self, observation): return [0.0]\n"
        )
        oversized = evaluate(oversized_path, args.case, secure=True)
        assert not oversized["valid"] and oversized["reward"] == 0
        assert oversized["completed_intervals"] == 0
        receipt["checks"]["actor_memory_excess_rejected_without_scorer_oom"] = True
    receipt["status"] = "passed"
    args.output.write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
