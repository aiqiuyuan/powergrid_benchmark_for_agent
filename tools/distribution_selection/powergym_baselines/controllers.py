"""Causal observation-only policies and a separately labelled model reference."""

from __future__ import annotations

import math
from collections.abc import Callable


def idle(observation: dict) -> list[int]:
    """Hold the observed devices and disconnect batteries."""
    return (list(observation["capacitor_states"]) + list(observation["regulator_taps"])
            + [16] * len(observation["battery_soc"]))


def hysteresis(observation: dict) -> list[int]:
    """Replay the historical canary starter without changing its thresholds."""
    values = [v for row in observation["bus_voltages"].values() for v in row]
    direction = -1 if max(values) > 1.06 else (1 if min(values) < .94 else 0)
    caps = list(observation["capacitor_states"])
    taps = [max(0, min(32, tap + direction)) for tap in observation["regulator_taps"]]
    return caps + taps + [16] * len(observation["battery_soc"])


def coordinated_voltage(observation: dict) -> list[int]:
    """Coordinate a bounded tap shift using the visible voltage envelope.

    This is an untrained heuristic, not a claim of superiority. It sees the
    same lagged voltages as the canary, never the next load row or model.
    At most one capacitor changes in a step; batteries remain idle.
    """
    values = [v for row in observation["bus_voltages"].values() for v in row]
    low, high = min(values), max(values)
    caps = list(observation["capacitor_states"])
    if high <= 1.045 and low >= .955:
        shift = 0
    else:
        center = (low + high) / 2
        shift = max(-4, min(4, round((1.0 - center) / .00625)))
        if high > 1.055 and low >= .955:
            shift = min(-1, shift)
        elif low < .945 and high <= 1.045:
            shift = max(1, shift)
    taps = [max(0, min(32, tap + shift)) for tap in observation["regulator_taps"]]
    if high > 1.055 and low >= .955 and 1 in caps:
        caps[caps.index(1)] = 0
    elif low < .945 and high <= 1.045 and 0 in caps:
        caps[caps.index(0)] = 1
    return caps + taps + [16] * len(observation["battery_soc"])


POLICIES: dict[str, Callable[[dict], list[int]]] = {
    "hold_idle": idle,
    "canary_hysteresis": hysteresis,
    "coordinated_voltage": coordinated_voltage,
}


def snapshot_search(backend: object, passes: int = 2) -> list[int]:
    """Greedy current-load model queries: full-information reference only.

    The reference knows the current exogenous load (unavailable to the lagged
    policy) and the full circuit. It has no future-load access. Each query
    solves the current snapshot without advancing time or the energy ledger.
    All battery commands are idle. This is a feasible reference, not an OPF
    optimum or an observation-only controller.
    """
    original = idle(backend.observation())
    chosen = list(original)
    cap_count = len(backend.capacitors)
    device_count = cap_count + len(backend.regulators)

    def cost(action: list[int]) -> float:
        try:
            row = backend.preview(action)
        except ValueError:
            return math.inf
        movement = sum(abs(a - b) for a, b in zip(action[:device_count], original)) / 33
        return row["voltage_violation_pu_hours"] + row["active_loss_kw"] / 1000 + movement

    best = cost(chosen)
    # Coarse global shifts escape the slow one-tap canary warmup. Each is
    # measured, not assumed beneficial. Tie handling preserves first choice.
    for offset in (-16, -8, -4, 4, 8, 16):
        trial = original[:cap_count] + [
            max(0, min(32, tap + offset)) for tap in original[cap_count:device_count]
        ] + original[device_count:]
        value = cost(trial)
        if value < best - 1e-12:
            chosen, best = trial, value
    for _ in range(passes):
        changed = False
        for index in range(device_count):
            options = [1 - chosen[index]] if index < cap_count else [
                chosen[index] + delta for delta in (-4, -1, 1, 4)
                if 0 <= chosen[index] + delta <= 32
            ]
            winner, winner_cost = chosen, best
            for value in options:
                trial = list(chosen)
                trial[index] = value
                measured = cost(trial)
                if measured < winner_cost - 1e-12:
                    winner, winner_cost = trial, measured
            if winner is not chosen:
                chosen, best, changed = winner, winner_cost, True
        if not changed:
            break
    return chosen
