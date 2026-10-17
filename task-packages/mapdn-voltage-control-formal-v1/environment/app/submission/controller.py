"""Qualified one-step local relaxed droop; no global information or extra queries."""

import math


class Controller:
    def __init__(self, metadata):
        self.bound = float(metadata["action_bound"])
        self.capacity = float(metadata["apparent_power_mva"][0])

    def act(self, observation):
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
        raw = max(-1.0, min(1.0, 20.0 * (1.0 - voltage)))
        target = max(-self.bound, min(self.bound, raw))
        action = 0.9 * previous + 0.1 * target
        return [max(-self.bound, min(self.bound, action))]
