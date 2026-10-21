#!/usr/bin/env python3
"""RTE mean-risk and feasibility MILP baselines, without quantile local search.

Each run builds the complete original start-time model. The objective is either
the linear mean risk or zero; the original checker remains the score authority.
This is an independent simple baseline, not a competition-code reproduction.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import time
import warnings
from pathlib import Path

IMPORT_STARTED = time.monotonic()

for _name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[_name] = "1"

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_matrix

DEFAULT_OBJECTIVE = "mean"


def solve(instance: dict, seconds: float, seed: int, objective: str) -> dict[str, int]:
    """Solve one complete linear mean-risk or zero-objective start-time MILP."""
    if objective not in {"mean", "feasibility"}:
        raise ValueError("unsupported baseline objective")
    deadline = time.monotonic() + seconds - 2.0
    horizon = int(instance["T"])
    names = list(instance["Interventions"])
    resources = list(instance["Resources"])
    resource_rows = {name: len(names) + k * horizon for k, name in enumerate(resources)}
    lower = [1.0] * len(names)
    upper = [1.0] * len(names)
    for name in resources:
        lower.extend(float(v) for v in instance["Resources"][name]["min"])
        upper.extend(float(v) for v in instance["Resources"][name]["max"])
    rows, columns, values = [], [], []
    choices, costs = [], []
    active: dict[tuple[str, int], list[int]] = {}
    for job_row, name in enumerate(names):
        job = instance["Interventions"][name]
        count = 0
        for start in range(1, min(int(job["tmax"]), horizon) + 1):
            if time.monotonic() >= deadline:
                raise TimeoutError("MILP construction exhausted the candidate budget")
            duration = int(job["Delta"][start - 1])
            if duration <= 0 or start + duration > horizon + 1:
                continue
            col = len(choices)
            choices.append((name, start))
            rows.append(job_row)
            columns.append(col)
            values.append(1.0)
            count += 1
            cost = 0.0
            for period in range(start, start + duration):
                active.setdefault((name, period), []).append(col)
                if objective == "mean":
                    risk = job["risk"].get(str(period), {}).get(str(start), [])
                    # Missing suffix values are zeros under the official checker.
                    cost += math.fsum(risk) / int(instance["Scenarios_number"][period - 1])
                for resource, workload in job["workload"].items():
                    value = float(workload.get(str(period), {}).get(str(start), 0.0))
                    if value:
                        rows.append(resource_rows[resource] + period - 1)
                        columns.append(col)
                        values.append(value)
            costs.append(cost / horizon)
        if not count:
            raise ValueError(f"no legal start for intervention {name}")
    for left, right, season in instance["Exclusions"].values():
        for raw_period in instance["Seasons"][season]:
            period = int(raw_period)
            left_cols = active.get((left, period), [])
            right_cols = active.get((right, period), [])
            if not left_cols or not right_cols:
                continue
            row = len(lower)
            lower.append(-np.inf)
            upper.append(1.0)
            for col in left_cols + right_cols:
                rows.append(row)
                columns.append(col)
                values.append(1.0)
    matrix = coo_matrix((values, (rows, columns)), shape=(len(lower), len(choices))).tocsc()
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("MILP assembly exhausted the candidate budget")
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Unrecognized options detected")
        result = milp(
            np.asarray(costs), integrality=np.ones(len(choices)),
            bounds=Bounds(np.zeros(len(choices)), np.ones(len(choices))),
            constraints=LinearConstraint(matrix, np.asarray(lower), np.asarray(upper)),
            options={"time_limit": remaining, "mip_rel_gap": 0.0, "threads": 1,
                     "random_seed": int(seed) % (2 ** 31),
                     "mip_feasibility_tolerance": 1e-7},
        )
    if result.x is None:
        raise RuntimeError("MILP returned no feasible incumbent")
    selected = np.rint(result.x)
    if np.max(np.abs(selected - result.x), initial=0.0) > 1e-5:
        raise RuntimeError("MILP incumbent is not integral")
    activity = matrix @ selected
    if (np.any(activity < np.asarray(lower) - 1e-5)
            or np.any(activity > np.asarray(upper) + 1e-5)):
        raise RuntimeError("MILP incumbent violates original linear constraints")
    schedule = {name: start for (name, start), take in zip(choices, selected) if take}
    if set(schedule) != set(names) or int(np.sum(selected)) != len(names):
        raise RuntimeError("MILP incumbent does not schedule every intervention once")
    return schedule


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instance", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--time-limit", type=float, required=True)
    parser.add_argument("--seed", type=int, default=2020)
    parser.add_argument("--objective", choices=("mean", "feasibility"), default=DEFAULT_OBJECTIVE)
    args = parser.parse_args()
    instance = json.loads(args.instance.read_text())
    remaining = args.time_limit - (time.monotonic() - IMPORT_STARTED)
    schedule = solve(instance, remaining, args.seed, args.objective)
    args.output.write_text("".join(f"{name} {start}\n" for name, start in schedule.items()))


if __name__ == "__main__":
    main()
