"""Pinned EGRET UC formulations, adapted to the timed schedule snapshot contract.

EGRET source revision: 28c324f9bf4fb3913b0a60dba3dd732b46084c3b.
The trusted reference runner supplies Python instead of the original Julia entry.
All imports, parsing, formulation construction and snapshot writes share the
original 300-second wall clock. The independent checker remains authoritative.
"""
from __future__ import annotations

import time

IMPORT_STARTED = time.monotonic()

import json
import math
import os
from pathlib import Path
import sys

from egret.models import unit_commitment as uc
from egret.parsers.pglib_uc_parser import create_ModelData
from pyomo.contrib.appsi.solvers.highs import Highs
from pyomo.repn import generate_standard_repn

DEFAULT_FORMULATION = "tight"
FORMULATIONS = {
    "tight": uc.create_tight_unit_commitment_model,
    "compact": uc.create_compact_unit_commitment_model,
    "random1": uc.create_random1_unit_commitment_model,
}


def build_model(instance: Path, formulation: str):
    """Use the author parser and formulation with hard balance and reserves."""
    model_data = create_ModelData(str(instance))
    model = FORMULATIONS[formulation](
        model_data, network_constraints="copperplate_power_flow",
        slack_type=uc.SlackType.NONE,
    )
    # The pinned author bus helper treats the presence of relax_balance=False
    # as True. Bind the task's exact demand equality explicitly after creation;
    # otherwise free renewable generation may exceed demand without a penalty.
    if len(model.TransmissionBlock) != int(json.loads(instance.read_text())["time_periods"]):
        raise ValueError("EGRET transmission period count differs")
    for block in model.TransmissionBlock.values():
        balance = block.eq_p_balance
        if (balance.lower is None or float(balance.lower) != 0.0
                or (balance.upper is not None and float(balance.upper) != 0.0)):
            raise ValueError("Unexpected EGRET demand balance structure")
        balance.set_value((0.0, balance.body, 0.0))
        if not balance.equality or float(balance.lower) != 0.0:
            raise ValueError("Exact demand balance was not bound")
    # SlackType.NONE disables demand slack but EGRET still creates this reserve
    # slack. The original task requires the entire spinning reserve physically.
    for shortfall in model.ReserveShortfall.values():
        if hasattr(shortfall, "fix"):
            shortfall.fix(0.0)
        elif float(shortfall) != 0.0:
            raise ValueError("Nonzero reserve shortfall parameter")
    return model


def linear_reader(expression, variable_columns: dict[int, int]):
    """Compile physical expressions once; callbacks read their solver columns."""
    repn = generate_standard_repn(expression, compute_values=True)
    if not repn.is_linear():
        raise ValueError("Physical schedule expression is nonlinear")
    terms = tuple((variable_columns[id(var)], float(coef))
                  for var, coef in zip(repn.linear_vars, repn.linear_coefs))
    constant = float(repn.constant or 0.0)
    return lambda values: constant + sum(coef * values[index] for index, coef in terms)


def schedule_reader(model, data: dict, variable_columns: dict[int, int]):
    times = list(model.TimePeriods)
    thermal, renewable = {}, {}
    thermal_names, renewable_names = set(), set()
    for original, gen in data["thermal_generators"].items():
        name = gen["name"] + "_T"
        if name in thermal_names:
            raise ValueError("EGRET thermal name collision")
        thermal_names.add(name)
        thermal[original] = {
            "on": [linear_reader(model.UnitOn[name, t], variable_columns) for t in times],
            "power": [linear_reader(model.PowerGenerated[name, t], variable_columns) for t in times],
            "reserve": [linear_reader(model.ReserveProvided[name, t], variable_columns) for t in times],
        }
    for original, gen in data["renewable_generators"].items():
        name = gen["name"] + "_R"
        if name in renewable_names:
            raise ValueError("EGRET renewable name collision")
        renewable_names.add(name)
        renewable[original] = [linear_reader(model.NondispatchablePowerUsed[name, t], variable_columns)
                               for t in times]

    def read(values) -> dict:
        result = {"schema": "uc-schedule-v1", "thermal": {}, "renewable": {}}
        for original, fields in thermal.items():
            result["thermal"][original] = {
                key: [int(round(f(values))) if key == "on" else float(f(values)) for f in readers]
                for key, readers in fields.items()
            }
        result["renewable"] = {name: [float(f(values)) for f in readers]
                               for name, readers in renewable.items()}
        return result

    return read


def solve(instance: Path, output: Path, seconds: float, seed: int,
          formulation: str = DEFAULT_FORMULATION, *, started: float = IMPORT_STARTED) -> dict:
    data = json.loads(instance.read_text())
    model = build_model(instance, formulation)
    solver = Highs()
    solver.set_instance(model)
    highs = solver._solver_model
    if highs.version() != "1.15.1":
        raise RuntimeError("The reference run requires HiGHS 1.15.1")
    options = {"threads": 1, "random_seed": seed, "mip_rel_gap": 0.0,
               "mip_abs_gap": 0.0, "output_flag": False, "log_to_console": False}
    for key, value in options.items():
        if str(highs.setOptionValue(key, value)) != "HighsStatus.kOk":
            raise RuntimeError("Unsupported pinned HiGHS option: " + key)
    read = schedule_reader(model, data, solver._pyomo_var_to_solver_var_map)
    count = 0

    def publish(values) -> None:
        nonlocal count
        if count >= 64 or time.monotonic() - started >= seconds - 0.25:
            return
        schedule = read(values)
        encoded = json.dumps(schedule, separators=(",", ":"), allow_nan=False)
        temporary = output / f"snapshot-{count:02d}.tmp"
        target = output / f"snapshot-{count:02d}.json"
        with temporary.open("x") as stream:
            stream.write(encoded)
        os.rename(temporary, target)
        count += 1

    def improving(event) -> None:
        # Reserve the final slot for the terminal incumbent. Receipt time is
        # measured outside the candidate by the original trusted supervisor.
        if count < 63:
            publish(event.data_out.mip_solution)

    highs.cbMipImprovingSolution.subscribe(improving)
    remaining = seconds - (time.monotonic() - started) - 2.0
    if remaining <= 0:
        return {"snapshots": count, "termination": "build-budget-exhausted"}
    highs.setOptionValue("time_limit", remaining)
    highs.run()
    solution = highs.getSolution()
    if solution.value_valid:
        publish(solution.col_value)
    info = highs.getInfo()
    return {"snapshots": count, "termination": str(highs.getModelStatus()),
            "objective": float(info.objective_function_value),
            "wall_seconds": time.monotonic() - started}


def main() -> None:
    if len(sys.argv) != 5:
        raise ValueError("Expected instance, output directory, seconds and seed")
    instance, output = Path(sys.argv[1]), Path(sys.argv[2])
    seconds, seed = float(sys.argv[3]), int(sys.argv[4])
    if not 0 < seconds <= 1200 or not math.isfinite(seconds) or seed not in (0, 1, 2):
        raise ValueError("Invalid fixed reference execution contract")
    solve(instance, output, seconds, seed)


if __name__ == "__main__":
    main()
