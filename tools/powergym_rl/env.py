"""Observation-only episodic adapter for the unchanged frozen numerical contract."""

from __future__ import annotations

import json
import math
import random
import sys
import time
from pathlib import Path

import numpy as np
from data import digest, verify_pool

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/distribution_qualification"))
from powergym_backend import QualificationBackend  # noqa: E402
from powergym_search import DayEvaluator  # noqa: E402


def native_vanilla_reward(row: dict, network: str, max_kw: list[float]) -> float:
    """Rebuild native vanilla reward without editing historical diagnostics.

    NumPy scalar division plus the original Python clamp is deliberate. Physical
    inputs must be finite; an intermediate infinity/NaN at a zero source follows
    that clamp, without an epsilon or an altered physical loss measurement.
    Vanilla SOC weight is zero for both supported feeder configurations.
    """
    loss, source = float(row["active_loss_kw"]), float(row["source_active_kw"])
    violation = float(row["voltage_violation_pu_hours"])
    caps, taps = float(row["capacitor_switches"]), float(row["tap_moves"])
    commands = [float(value) for value in row["battery_command_kw"]]
    if (
        not all(
            math.isfinite(value)
            for value in [loss, source, violation, caps, taps, *commands, *max_kw]
        )
        or min(loss, violation, caps, taps) < 0
        or not max_kw
        or any(value <= 0 for value in max_kw)
        or len(commands) != len(max_kw)
    ):
        raise ValueError("native reward requires finite physical values and valid device ratings")
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = max(0.0, min(1.0, np.divide(np.float64(loss), np.float64(source))))
    power_weight, discharge_weight = {"34Bus": (1.0, 10 / 33), "123Bus": (10.0, 7 / 33)}[network]
    discharge = sum(
        max(0.0, power) / maximum for power, maximum in zip(commands, max_kw, strict=True)
    )
    reward = -(violation + power_weight * ratio + (caps + taps) / 33 + discharge_weight * discharge)
    if not math.isfinite(reward):
        raise ValueError("native reward is nonfinite after original clipping")
    return float(reward)


class PowerGymEnv:
    """One action per hour; no model preview, future load, or oracle feature.

    Training independently reconstructs the native vanilla reward. Hard terminal energy
    validity is evaluated independently and never replaced by training reward.
    """

    def __init__(self, pool_dir: Path, network: str, *, split: str, seed: int):
        self.pool_dir = pool_dir.resolve(strict=True)
        self.pool = verify_pool(self.pool_dir)
        if split not in ("train", "heldout"):
            raise ValueError("RL split must be explicit")
        self.cases = [
            row for row in self.pool["cases"] if row["network"] == network and row["split"] == split
        ]
        if len(self.cases) != 8:
            raise ValueError("each RL split must contain exactly eight complete profiles")
        self.random = random.Random(seed)
        self.backend = None
        self.evaluation_only = split == "heldout"
        caps, regs, batteries = {"34Bus": (2, 6, 2), "123Bus": (4, 7, 4)}[network]
        self.action_sizes = [2] * caps + [33] * (regs + batteries)
        self.rows: list[dict] = []
        self.environment_steps = 0
        self.reset_calls = 0
        self.pf_calls = self.replay_pf_calls = self.verification_pf_calls = 0

    def reset(self, *, case_id: str | None = None) -> np.ndarray:
        item = (
            next((row for row in self.cases if row["id"] == case_id), None)
            if case_id
            else (self.random.choice(self.cases))
        )
        if item is None:
            raise ValueError("reset case belongs to a different data split")
        path = self.pool_dir / item["path"]
        if digest(path) != item["sha256"]:
            raise ValueError("RL case changed after pool verification")
        self.case = json.loads(path.read_text())
        self.assets = self.pool_dir / "assets" / self.case["network"]
        self.backend = QualificationBackend(self.case, self.assets)
        self.rows = []
        self.last_activity_ns = time.monotonic_ns()
        self.pf_calls += self.backend.pf_calls
        self.reset_calls += 1
        return self.observation()

    def observation(self) -> np.ndarray:
        if self.backend is None:
            raise ValueError("environment must be reset before observation")
        obs = self.backend.observation()
        voltages = [value for row in obs["bus_voltages"].values() for value in row]
        batteries = [
            value
            for soc, power, maximum in zip(
                obs["battery_soc"], obs["battery_actual_kw"], self.backend.max_kw, strict=True
            )
            for value in (soc, power / maximum)
        ]
        return np.asarray(
            voltages
            + obs["capacitor_states"]
            + [tap / 32.0 for tap in obs["regulator_taps"]]
            + batteries,
            dtype=np.float32,
        )

    def step(self, action: list[int]) -> tuple[np.ndarray, float, bool, dict]:
        if self.backend is None:
            raise ValueError("environment must be reset before stepping")
        self.last_activity_ns = time.monotonic_ns()
        before_pf = self.backend.pf_calls
        try:
            row = self.backend.advance(action)
        finally:
            self.pf_calls += self.backend.pf_calls - before_pf
        self.rows.append(row)
        self.environment_steps += 1
        reward = native_vanilla_reward(row, self.case["network"], self.backend.max_kw)
        row["rl_paper_vanilla_reward"] = reward
        return self.observation(), reward, self.backend.step == 24, {"physical_row": row}

    def final_evaluation(self, label: str) -> dict:
        if len(self.rows) != 24:
            raise ValueError("only full episodes can receive an evaluation result")
        evaluator = DayEvaluator(self.case, self.assets)
        result = evaluator.replay([row["action"] for row in self.rows], label)
        self.replay_pf_calls += result["replay_pf_calls"]
        self.verification_pf_calls += evaluator.pf_calls
        if any(
            row[field] != expected[field]
            for row, expected in zip(self.rows, result["trajectory"], strict=True)
            for field in (
                "active_loss_kw",
                "voltage_violation_pu_hours",
                "battery_actual_kw",
                "battery_energy_kwh",
            )
        ):
            raise ValueError("independent evaluation replay differs from RL physical rows")
        if result["final_energy_kwh"] != self.backend.energy:
            raise ValueError("independent evaluation replay differs from RL rollout energy")
        for row in result["trajectory"]:
            row["rl_paper_vanilla_reward"] = native_vanilla_reward(
                row, self.case["network"], self.backend.max_kw
            )
        if any(
            row["rl_paper_vanilla_reward"] != expected["rl_paper_vanilla_reward"]
            for row, expected in zip(self.rows, result["trajectory"], strict=True)
        ):
            raise ValueError("independent native reward reconstruction differs from RL rollout")
        result.update(
            case_id=self.case["id"],
            profile_index=self.case["profile_index"],
            paper_vanilla_return=result["paper_vanilla_reward_diagnostic"],
            rl_paper_vanilla_return=math.fsum(
                row["rl_paper_vanilla_reward"] for row in result["trajectory"]
            ),
        )
        return result
