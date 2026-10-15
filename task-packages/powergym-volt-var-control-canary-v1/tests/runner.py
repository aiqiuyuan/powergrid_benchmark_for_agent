"""Complete-day trusted evaluation; no trajectory is returned to development."""

from __future__ import annotations

import hashlib
import json
import math
import shutil
import tempfile
import time
from pathlib import Path

from backend import Backend, validate_action
from candidate import Candidate, CandidateError

EXPECTED_CASE_SHA256 = "3b76c39e38dddb552ae4d53fd06838e5b5caa35cce5309f3ca611fa12cb2791f"


def verify_data(directory: Path) -> None:
    if hashlib.sha256((directory / "case.json").read_bytes()).hexdigest() != EXPECTED_CASE_SHA256:
        raise ValueError("case differs from the frozen canary release")
    receipt = json.loads((directory / "data-lock.json").read_text())
    for name, expected in receipt["files"].items():
        target = (directory / name).resolve(strict=True)
        if not target.is_relative_to(directory.resolve()):
            raise ValueError("data lock escaped case directory")
        if hashlib.sha256(target.read_bytes()).hexdigest() != expected:
            raise ValueError("trusted data hash mismatch")


def evaluate(controller: Path, data: Path, *, secure: bool = True) -> dict:
    start = time.monotonic()
    verify_data(data)
    candidate = None
    with tempfile.TemporaryDirectory(prefix="powergym-case-") as directory:
        private = Path(directory) / "case"
        shutil.copytree(data, private)
        private.chmod(0o700)
        backend = Backend(private)
        rows = []
        failure = None
        try:
            candidate = Candidate(controller, backend.metadata, secure=secure)
            for _ in range(24):
                action = candidate.act(backend.observation())
                try:
                    validate_action(action)
                except ValueError as exc:
                    raise CandidateError("invalid_action", candidate.source_sha256) from exc
                try:
                    rows.append(backend.advance(action))
                except ValueError as exc:
                    raise CandidateError("invalid_trajectory", candidate.source_sha256) from exc
        except CandidateError as exc:
            failure = exc
        finally:
            if candidate is not None:
                candidate.close()
        initial_energy = [4000.0, 4000.0]
        terminal_error = [abs(a - b) for a, b in zip(initial_energy, backend.energy)]
        valid = (
            failure is None
            and len(rows) == 24
            and max(terminal_error) <= backend.case["terminal_energy_tolerance_kwh"]
        )
        loss = math.fsum(row["active_loss_kw"] for row in rows)
        violation = math.fsum(row["voltage_violation_pu_hours"] for row in rows)
        control_cost = (backend.cap_switches + backend.tap_moves) / 33.0
        cost = violation + loss / 1000.0 + control_cost
        reward = 1.0 / (1.0 + cost) if valid else 0.0
        return {
            "case_id": backend.case["id"],
            "track": backend.case["track"],
            "valid": valid,
            "evaluation_completed": True,
            "error": failure.code if failure else (None if valid else "terminal_energy_violation"),
            "reward": reward,
            "cost": cost,
            "active_loss_kwh": loss,
            "voltage_violation_pu_hours": violation,
            "phase_time_compliance": (
                sum(row["compliant_phases"] for row in rows) / sum(row["phases"] for row in rows)
            )
            if rows
            else None,
            "min_voltage_pu": min((row["min_voltage_pu"] for row in rows), default=None),
            "max_voltage_pu": max((row["max_voltage_pu"] for row in rows), default=None),
            "capacitor_switches": backend.cap_switches,
            "tap_moves": backend.tap_moves,
            "battery_throughput_kwh": backend.throughput_kwh,
            "initial_soc": [1.0, 1.0],
            "final_soc": [value / 4000 for value in backend.energy],
            "terminal_energy_error_kwh": terminal_error,
            "completed_steps": len(rows),
            "all_power_flows_converged": not (failure and failure.code == "invalid_trajectory"),
            "wall_seconds": time.monotonic() - start,
            "candidate_sha256": candidate.source_sha256 if candidate else failure.source_sha256,
            "sandbox": "linux-uid-seccomp" if secure else "local-numerical-only",
            "trajectory": rows,
        }
