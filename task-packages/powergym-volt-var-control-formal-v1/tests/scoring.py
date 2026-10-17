"""Formal soft voltage cost with per-battery ledger and actual-energy hard gates."""

from __future__ import annotations

import math


def summarize(
    rows: list[dict], initial: list[float], capacity: list[float], *, failure: str | None = None
) -> dict:
    batteries = len(initial)
    if batteries != 4 or len(capacity) != batteries:
        raise ValueError("expected four formal batteries")
    final = rows[-1]["battery_energy_kwh"] if rows else list(initial)
    terminal = [abs(a - b) for a, b in zip(initial, final, strict=True)]
    actual_net = [math.fsum(row["battery_actual_kw"][i] for row in rows) for i in range(batteries)]
    actual_throughput = [
        math.fsum(abs(row["battery_actual_kw"][i]) for row in rows) for i in range(batteries)
    ]
    complete = len(rows) == 24 and [row["step"] for row in rows] == list(range(24))
    ledger_valid = max(terminal) <= 1.0
    actual_valid = max(abs(value) for value in actual_net) <= 1.0
    valid = failure is None and complete and ledger_valid and actual_valid
    error = failure
    if error is None and not complete:
        error = "incomplete_horizon"
    if error is None and not ledger_valid:
        error = "terminal_energy_violation"
    if error is None and not actual_valid:
        error = "actual_terminal_energy_violation"
    loss = math.fsum(row["active_loss_kw"] for row in rows)
    violation = math.fsum(row["voltage_violation_pu_hours"] for row in rows)
    switches = sum(row["capacitor_switches"] for row in rows)
    moves = sum(row["tap_moves"] for row in rows)
    cost = violation + loss / 1000.0 + (switches + moves) / 33.0
    if not math.isfinite(cost) or cost < 0:
        raise ValueError("nonfinite or negative trajectory cost")
    return {
        "valid": valid,
        "evaluation_completed": True,
        "error": error,
        "reward": 1.0 / (1.0 + cost) if valid else 0.0,
        "cost": cost,
        "completed_steps": len(rows),
        "all_power_flows_converged": failure != "invalid_trajectory",
        "active_loss_kwh": loss,
        "voltage_violation_pu_hours": violation,
        "phase_time_compliance": (
            sum(row["compliant_phases"] for row in rows) / sum(row["phases"] for row in rows)
        )
        if rows
        else None,
        "simultaneous_compliance": sum(row["all_phases_compliant"] for row in rows) / 24,
        "physical_voltage_feasible": complete and all(row["all_phases_compliant"] for row in rows),
        "min_voltage_pu": min((row["min_voltage_pu"] for row in rows), default=None),
        "max_voltage_pu": max((row["max_voltage_pu"] for row in rows), default=None),
        "capacitor_switches": switches,
        "tap_moves": moves,
        "initial_energy_kwh": list(initial),
        "final_energy_kwh": list(final),
        "initial_soc": [e / c for e, c in zip(initial, capacity)],
        "final_soc": [e / c for e, c in zip(final, capacity)],
        "terminal_energy_error_kwh": terminal,
        "ledger_terminal_energy_valid": ledger_valid,
        "actual_terminal_energy_valid": actual_valid,
        "actual_net_energy_kwh": actual_net,
        "actual_throughput_kwh": actual_throughput,
        "battery_throughput_kwh": math.fsum(actual_throughput),
        "commanded_net_energy_kwh": [
            math.fsum(row["battery_command_kw"][i] for row in rows) for i in range(batteries)
        ],
        "rounding_residual_kwh": [
            math.fsum(row["rounding_residual_kwh"][i] for row in rows) for i in range(batteries)
        ],
        "clipping_residual_kwh": [
            math.fsum(row["clipping_residual_kwh"][i] for row in rows) for i in range(batteries)
        ],
    }
