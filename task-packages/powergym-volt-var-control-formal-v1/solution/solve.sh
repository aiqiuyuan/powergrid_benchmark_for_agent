#!/bin/sh
set -eu
mkdir -p /app/submission
cat > /app/submission/controller.py <<'PY'
"""Same-information, untrained coordinated voltage reference; battery idle."""


class Controller:
    def __init__(self, metadata):
        self.batteries = metadata["battery_count"]

    def act(self, observation: dict) -> list[int]:
        """Coordinate a bounded tap shift using the visible voltage envelope.

        This is an untrained heuristic, not a claim of superiority. It sees the
        same lagged voltages as the canary, never the next load row or model.
        At most one capacitor changes in a step; batteries remain idle.
        """
        values = [v for row in observation["bus_voltages"].values() for v in row]
        low, high = min(values), max(values)
        caps = list(observation["capacitor_states"])
        if high <= 1.045 and low >= 0.955:
            shift = 0
        else:
            center = (low + high) / 2
            shift = max(-4, min(4, round((1.0 - center) / 0.00625)))
            if high > 1.055 and low >= 0.955:
                shift = min(-1, shift)
            elif low < 0.945 and high <= 1.045:
                shift = max(1, shift)
        taps = [max(0, min(32, tap + shift)) for tap in observation["regulator_taps"]]
        if high > 1.055 and low >= 0.955 and 1 in caps:
            caps[caps.index(1)] = 0
        elif low < 0.945 and high <= 1.045 and 0 in caps:
            caps[caps.index(0)] = 1
        return caps + taps + [16] * len(observation["battery_soc"])
PY
