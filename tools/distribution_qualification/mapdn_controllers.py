"""Known local MAPDN policies, without network or trajectory access."""

from __future__ import annotations

import math


def source_curve(voltage: float, bound: float) -> float:
    """Port the source slope before clipping to the benchmark's stricter bound."""
    if not math.isfinite(voltage) or not 0 < bound <= 1:
        raise ValueError("invalid voltage or normalized action bound")
    raw = max(-1.0, min(1.0, 20.0 * (1.0 - voltage)))
    return max(-bound, min(bound, raw))


class MemoryController:
    """One causal action per interval, using the locally observed previous Q."""

    def __init__(self, metadata: dict, policy: dict):
        self.bound = float(metadata["action_bound"])
        self.capacity = float(metadata["apparent_power_mva"][0])
        self.name = policy["name"]
        self.gain = float(policy.get("gain", 1.0))
        self.relaxation = float(policy.get("relaxation", 0.1))
        if (
            self.name not in ("one_step_relaxed", "one_step_integral")
            or not 0 < self.bound <= 1
            or self.capacity <= 0
            or not math.isfinite(self.gain)
            or self.gain <= 0
            or not 0 < self.relaxation <= 1
        ):
            raise ValueError("unsupported local controller parameters")

    def act(self, observation: dict) -> list[float]:
        voltage = float(observation["pv_voltage_pu"][0])
        active = float(observation["pv_active_mw"][0])
        reactive = float(observation["pv_reactive_mvar"][0])
        if not all(map(math.isfinite, (voltage, active, reactive))):
            raise ValueError("nonfinite local observation")
        if not 0 <= active <= self.capacity:
            raise ValueError("local active power exceeds inverter capacity")
        capability = math.sqrt(max(0.0, self.capacity**2 - active**2))
        if capability == 0:
            return [0.0]
        previous = max(-self.bound, min(self.bound, reactive / capability))
        if self.name == "one_step_relaxed":
            target = source_curve(voltage, self.bound)
            action = (1 - self.relaxation) * previous + self.relaxation * target
        else:
            action = previous + self.gain * (1.0 - voltage)
        return [max(-self.bound, min(self.bound, action))]
