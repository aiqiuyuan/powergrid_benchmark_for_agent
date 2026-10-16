#!/usr/bin/env python3
"""Free synthetic interface check; this does not import or score the real case."""

import importlib.util
import math
from pathlib import Path

path = Path(__file__).parent / "submission/controller.py"
spec = importlib.util.spec_from_file_location("candidate", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
controller = module.Controller(
    {
        "actor_id": 0,
        "pv_count": 1,
        "pv_bus_id": 12,
        "region_bus_ids": [12],
        "action_bound": 0.8,
        "apparent_power_mva": [1.0],
        "interval_hours": 0.05,
        "voltage_bounds_pu": [0.95, 1.05],
    }
)
for step, voltage in enumerate((0.96, 1.02, 1.0)):
    action = controller.act(
        {
            "interval_index": step,
            "timestamp": f"2000-01-01T00:0{step * 3}:00",
            "pv_voltage_pu": [voltage],
            "pv_active_mw": [0.4],
            "pv_reactive_mvar": [0],
            "region_bus_ids": [12],
            "region_demand_p_mw": [0.5],
            "region_demand_q_mvar": [0.2],
            "region_voltage_pu": [voltage],
            "region_angle_degree": [0],
        }
    )
    assert isinstance(action, list) and len(action) == 1
    assert type(action[0]) in (int, float) and math.isfinite(action[0]) and abs(action[0]) <= 0.8
print("synthetic local controller interface passed; no target score was computed")
