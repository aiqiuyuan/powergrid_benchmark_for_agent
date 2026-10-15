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
        "capacitor_count": 2,
        "regulator_count": 6,
        "battery_count": 2,
        "continuous_batteries": False,
        "battery_max": 32,
        "tap_max": 32,
        "horizon": 24,
        "step_hours": 1.0,
        "capacitor_names": ["toy_cap1", "toy_cap2"],
        "regulator_names": [f"toy_reg{i}" for i in range(6)],
        "battery_names": ["toy_bat1", "toy_bat2"],
        "battery_capacity_kwh": [4000.0] * 2,
        "battery_max_kw": [500.0] * 2,
        "terminal_soc": [1.0] * 2,
        "terminal_energy_tolerance_kwh": 1.0,
        "track": "toy-interface-only",
    }
)
action = controller.act(
    {
        "step": 0,
        "capacitor_states": [1, 1],
        "regulator_taps": [16] * 6,
        "battery_soc": [1.0, 1.0],
        "battery_actual_kw": [0.0, 0.0],
        "bus_voltages": {"toy_bus": [1.0] * 3},
    }
)
limits = [1, 1] + [32] * 8
assert isinstance(action, list) and len(action) == 10
assert all(type(value) is int and 0 <= value <= limit for value, limit in zip(action, limits))
print(json.dumps({"interface_valid": True, "target_evaluation": False}))
