"""Known local policies receive current regional observations, never the network."""

from __future__ import annotations

import importlib.util
import math
from pathlib import Path


class ControllerContractError(ValueError):
    """A trusted controller returned an action outside the local contract."""


class ZeroQ:
    def __init__(self, metadata: dict):
        self.bound = metadata["action_bound"]

    def act(self, observation: dict) -> list[float]:
        return [0.0]


class GridDroop:
    """One simultaneous causal action, with an explicitly fixed normalized gain."""

    def __init__(self, metadata: dict, gain: float):
        self.bound = metadata["action_bound"]
        self.gain = gain

    def act(self, observation: dict) -> list[float]:
        voltage = observation["pv_voltage_pu"][0]
        return [max(-self.bound, min(self.bound, self.gain * (1.0 - voltage)))]


def starter_path() -> Path:
    return (Path(__file__).resolve().parents[3]
            / "task-packages/mapdn-voltage-control-canary-v1"
            / "environment/app/submission/controller.py")


def make_controller(metadata: dict, name: str, gain: float = 1.0):
    if name == "zero_q":
        return ZeroQ(metadata)
    if name == "original_starter":
        spec = importlib.util.spec_from_file_location("selection_original_starter", starter_path())
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.Controller(metadata)
    if name == "grid_droop":
        return GridDroop(metadata, gain)
    raise ValueError(f"unknown trusted local controller: {name}")


def validate_action(value: object, bound: float) -> float:
    if not isinstance(value, list) or len(value) != 1:
        raise ControllerContractError("local controller must return one normalized action")
    action = value[0]
    if (isinstance(action, bool) or not isinstance(action, (int, float))
            or not math.isfinite(action) or abs(action) > bound):
        raise ControllerContractError("normalized action is nonfinite or outside the action limit")
    return float(action)
