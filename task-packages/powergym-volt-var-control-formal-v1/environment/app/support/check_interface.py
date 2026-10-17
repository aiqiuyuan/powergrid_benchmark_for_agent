#!/usr/bin/env python3
"""Public synthetic interface check, never a target score or simulation."""

import importlib.util
import json
from pathlib import Path

path = Path(__file__).resolve().parents[1] / "submission/controller.py"
spec = importlib.util.spec_from_file_location("candidate", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
controller = module.Controller(
    {
        "capacitor_count": 4,
        "regulator_count": 7,
        "battery_count": 4,
        "continuous_batteries": False,
        "battery_max": 32,
        "tap_max": 32,
        "horizon": 24,
        "step_hours": 1.0,
        "capacitor_names": [f"toy_cap{i}" for i in range(4)],
        "regulator_names": [f"toy_reg{i}" for i in range(7)],
        "battery_names": [f"toy_bat{i}" for i in range(4)],
        "battery_capacity_kwh": [1000.0] * 4,
        "battery_max_kw": [100.0] * 4,
        "terminal_soc": [1.0] * 4,
        "terminal_energy_tolerance_kwh": 1.0,
        "track": "toy-interface-only",
    }
)
action = controller.act(
    {
        "step": 0,
        "capacitor_states": [1] * 4,
        "regulator_taps": [16] * 7,
        "battery_soc": [1.0] * 4,
        "battery_actual_kw": [0.0] * 4,
        "bus_voltages": {"toy_bus": [1.0] * 3},
    }
)
limits = [1] * 4 + [32] * 11
assert isinstance(action, list) and len(action) == 15
assert all(type(value) is int and 0 <= value <= limit for value, limit in zip(action, limits))
print(json.dumps({"interface_valid": True, "target_evaluation": False}))
