#!/usr/bin/env python3
"""RTE maintenance scheduler using mean-risk and exact-quantile MILP models."""
from __future__ import annotations

import argparse
import heapq
import itertools
import json
import math
import os
import random
import time
import warnings
from pathlib import Path

for _name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[_name] = "1"

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_matrix, diags, hstack, vstack


def solve(instance: dict, seconds: float, seed: int, refine: bool = True) -> dict[str, int]:
    """Return a feasible schedule, improving it against the exact official objective."""
    reserve = min(0.25, max(0.0, 0.05 * seconds))
    deadline = time.monotonic() + max(0.0, seconds - reserve)
    # Match the official resource tolerance exactly.  HiGHS is asked for a much
    # tighter primal tolerance below, so no separate outward numerical slack is
    # needed when independently reconstructing an incumbent.
    checker_margin = 1e-5
    numerical_slack = 0.0
    names = list(instance["Interventions"])
    jobs = instance["Interventions"]
    alpha = float(instance["Alpha"])
    highs_seed = int(seed) % (2 ** 31)
    solver_coefficient_floor = 1e-9

    def has_small_nonzero(array) -> bool:
        values_array = np.asarray(array, dtype=float)
        return bool(np.any(
            (values_array != 0.0)
            & np.isfinite(values_array)
            & (np.abs(values_array) <= solver_coefficient_floor)
        ))

    if not names:
        for specification in instance["Resources"].values():
            if (any(float(bound) > checker_margin for bound in specification["min"])
                    or any(float(bound) < -checker_margin
                           for bound in specification["max"])):
                raise RuntimeError("empty schedule violates a resource bound")
        if instance["Exclusions"]:
            raise ValueError("exclusions reference an empty intervention set")
        return {}

    horizon = int(instance["T"])
    resources = list(instance["Resources"])
    resource_index = {name: k for k, name in enumerate(resources)}
    scenario_counts = np.asarray(instance["Scenarios_number"], dtype=int)
    offsets = np.r_[0, np.cumsum(scenario_counts)]
    total_scenarios = int(offsets[-1])

    choices: list[tuple[str, int]] = []
    choice_risks: list[list[tuple[int, np.ndarray]]] = []
    choice_raw_risks: list[list[tuple[int, list | None]]] = []
    by_job: dict[str, list[int]] = {}
    mean_costs: list[float] = []
    objective_mean_costs: list[np.longdouble] = []
    risk_entry_count = 0
    max_abs_risk = 0.0
    min_abs_nonzero_risk = math.inf
    max_abs_integer_risk = 0
    minimum_risk = 0.0
    choice_max_abs_risks: list[float] = []
    choice_min_abs_nonzero_risks: list[float] = []
    choice_max_abs_integer_risks: list[int] = []
    rows: list[int] = []
    columns: list[int] = []
    values: list[float] = []
    lower: list[float] = []
    upper: list[float] = []
    resource_base = len(names)
    resource_row_count = len(resources) * horizon

    for i, name in enumerate(names):
        if time.monotonic() >= deadline:
            raise TimeoutError("model construction exhausted the budget")
        lower.append(1.0)
        upper.append(1.0)
        by_job[name] = []
        job = jobs[name]
        for start in range(1, min(int(job["tmax"]), horizon) + 1):
            if time.monotonic() >= deadline:
                raise TimeoutError("model construction exhausted the budget")
            duration = int(job["Delta"][start - 1])
            if duration <= 0 or start + duration > horizon + 1:
                continue
            col = len(choices)
            choices.append((name, start))
            by_job[name].append(col)
            rows.append(i)
            columns.append(col)
            values.append(1.0)
            pieces: list[tuple[int, np.ndarray]] = []
            raw_pieces: list[tuple[int, list | None]] = []
            choice_max_abs_risk = 0.0
            choice_min_abs_nonzero_risk = math.inf
            choice_max_abs_integer_risk = 0
            for t in range(start - 1, start - 1 + duration):
                if time.monotonic() >= deadline:
                    raise TimeoutError("model construction exhausted the budget")
                raw = job["risk"].get(str(t + 1), {}).get(str(start))
                if raw is not None:
                    for raw_index, raw_value in enumerate(raw):
                        if ((raw_index & 65535) == 0
                                and time.monotonic() >= deadline):
                            raise TimeoutError("risk scanning exhausted the budget")
                        if type(raw_value) is int:
                            integer_magnitude = abs(raw_value)
                            max_abs_integer_risk = max(
                                max_abs_integer_risk, integer_magnitude
                            )
                            choice_max_abs_integer_risk = max(
                                choice_max_abs_integer_risk, integer_magnitude
                            )
                scenario_count = int(scenario_counts[t])
                if raw is not None and len(raw) > scenario_count:
                    raise ValueError("risk row exceeds the declared scenario count")
                try:
                    converted_risk = np.array(
                        raw if raw is not None else np.zeros(scenario_count),
                        dtype=float,
                        copy=True,
                    )
                except OverflowError:
                    # Native JSON integers are unbounded.  Keep their exact values
                    # for checker-order scoring, while giving the float surrogate a
                    # finite saturated row that can still steer away from them.
                    maximum_float = np.finfo(float).max
                    converted_risk = np.fromiter((
                        maximum_float if type(value) is int and value > 0
                        else -maximum_float if type(value) is int and value < 0
                        else float(value)
                        for value in raw
                    ), dtype=float, count=len(raw))
                if converted_risk.size == scenario_count:
                    risk = converted_risk
                else:
                    # The pinned checker starts with the declared-width zero row and
                    # adds only the supplied prefix; a length-one list is not a
                    # scalar broadcast.
                    risk = np.zeros(scenario_count)
                    risk[:converted_risk.size] = converted_risk
                # Scan wide scenario rows in bounded chunks.  Materializing all
                # nonzeros and then their absolute values can otherwise require
                # more memory than the retained risk row itself.
                for chunk_start in range(0, risk.size, 1_000_000):
                    if time.monotonic() >= deadline:
                        raise TimeoutError("risk scanning exhausted the budget")
                    chunk = risk[chunk_start:chunk_start + 1_000_000]
                    risk_minimum = float(np.min(chunk))
                    risk_maximum = float(np.max(chunk))
                    if not (math.isfinite(risk_minimum)
                            and math.isfinite(risk_maximum)):
                        raise ValueError("risk values must be finite")
                    chunk_max_abs = max(abs(risk_minimum), abs(risk_maximum))
                    max_abs_risk = max(max_abs_risk, chunk_max_abs)
                    choice_max_abs_risk = max(
                        choice_max_abs_risk, chunk_max_abs
                    )
                    minimum_risk = min(minimum_risk, risk_minimum)
                    absolute = np.abs(chunk)
                    nonzero = absolute[absolute != 0.0]
                    if nonzero.size:
                        chunk_min_nonzero = float(np.min(nonzero))
                        min_abs_nonzero_risk = min(
                            min_abs_nonzero_risk, chunk_min_nonzero
                        )
                        choice_min_abs_nonzero_risk = min(
                            choice_min_abs_nonzero_risk, chunk_min_nonzero
                        )
                risk_entry_count += risk.size
                pieces.append((t, risk))
                raw_pieces.append((t, raw))
            choice_risks.append(pieces)
            choice_raw_risks.append(raw_pieces)
            choice_max_abs_risks.append(choice_max_abs_risk)
            choice_min_abs_nonzero_risks.append(choice_min_abs_nonzero_risk)
            choice_max_abs_integer_risks.append(choice_max_abs_integer_risk)
            for resource, periods in job["workload"].items():
                base_row = resource_base + resource_index[resource] * horizon
                for t in range(start - 1, start - 1 + duration):
                    value = periods.get(str(t + 1), {}).get(str(start), 0.0)
                    if value:
                        workload = float(value)
                        if not math.isfinite(workload):
                            raise ValueError("workload values must be finite")
                        rows.append(base_row + t)
                        columns.append(col)
                        values.append(workload)
        if not by_job[name]:
            raise ValueError(f"no admissible start for {name}")

    integer_checker_required = (
        max_abs_integer_risk
        * max(1, len(names))
        * max(1, int(np.max(scenario_counts)))
        > 2 ** 53
    )
    if not integer_checker_required:
        choice_raw_risks = []

    # A single positive power-of-two scale normally preserves schedule ordering
    # while keeping aggregate risks and exact-model big-M values in HiGHS' range.
    # An input can, however, span almost the entire binary64 exponent range.  If
    # dividing would erase a nonzero risk, retain the original arrays for exact
    # local scoring and normalize only the scalar mean surrogate passed to HiGHS.
    risk_model_limit = 1e8
    risk_entry_limit = risk_model_limit / (2.0 * max(1, len(names)))
    risk_scale = 1.0
    if max_abs_risk > risk_entry_limit:
        max_exponent = math.frexp(max_abs_risk)[1]
        limit_exponent = math.frexp(risk_entry_limit)[1]
        risk_scale = math.ldexp(1.0, max_exponent - limit_exponent)
        if max_abs_risk / risk_scale > risk_entry_limit:
            risk_scale = math.ldexp(risk_scale, 1)
    smallest_contribution_divisor = max(
        1, horizon * int(np.max(scenario_counts))
    )
    risk_precision_lost = (
        min_abs_nonzero_risk < math.inf
        and np.longdouble(min_abs_nonzero_risk)
        / (np.longdouble(risk_scale) * smallest_contribution_divisor)
        < np.longdouble(np.finfo(float).tiny)
    )
    risk_scale_shift = math.frexp(risk_scale)[1] - 1
    checker_overflow_factor = max(
        1,
        len(names) * max(
            2 * int(np.max(scenario_counts)), 2 * horizon,
        ),
    )
    checker_nonfinite_possible = (
        max_abs_risk
        > np.finfo(float).max / checker_overflow_factor
    )
    # Unscaled reconstruction is mandatory when a reduction can overflow or
    # normalization can erase a contribution.  Ordinary power-of-two scaling is
    # still used as a fast ranking surrogate, but accepted candidates are rescored
    # in checker order below because binary64 reductions are not homogeneous at
    # subnormal boundaries.
    checker_rescore_required = risk_precision_lost or checker_nonfinite_possible
    checker_authoritative_required = checker_rescore_required or risk_scale != 1.0
    positive_objective_weights = [
        weight for weight in (alpha, 1.0 - alpha) if weight > 0.0
    ]
    objective_longdouble = risk_precision_lost
    if (not objective_longdouble and positive_objective_weights
            and min_abs_nonzero_risk < math.inf):
        normalized_objective_unit = (
            np.longdouble(min_abs_nonzero_risk)
            * np.longdouble(min(positive_objective_weights))
            / (np.longdouble(risk_scale) * smallest_contribution_divisor)
        )
        objective_longdouble = (
            normalized_objective_unit < np.longdouble(np.finfo(float).tiny)
        )

    def safe_mean(array: np.ndarray):
        """Stable mean used by normalized surrogate search models."""
        if risk_precision_lost:
            return np.mean(array, dtype=np.longdouble)
        if risk_scale == 1.0 or array.size == 0:
            return float(np.mean(array, dtype=np.float64))
        magnitude = max(
            abs(float(np.min(array))), abs(float(np.max(array)))
        )
        if magnitude == 0.0:
            return 0.0
        return magnitude * float(np.mean(array / magnitude))

    # Keep a scale reference for model tolerances and ambiguity detection, but
    # never impose a fixed absolute floor on a verified objective improvement.
    if risk_precision_lost:
        objective_unit = (
            np.longdouble(min_abs_nonzero_risk)
            / np.longdouble(max(1, horizon * int(np.max(scenario_counts))))
        )
    else:
        objective_unit = 1.0 / risk_scale
    aggregate_risk_scale = max(
        1.0, max_abs_risk * max(1, len(names)) / risk_scale
    )
    checker_rounding_guard = 64.0 * float(np.spacing(aggregate_risk_scale))

    for pieces in choice_risks:
        if time.monotonic() >= deadline:
            raise TimeoutError("risk normalization exhausted the budget")
        mean_cost = 0.0
        objective_mean_cost = (
            np.longdouble(0.0) if risk_precision_lost else None
        )
        for _, risk in pieces:
            if time.monotonic() >= deadline:
                raise TimeoutError("risk normalization exhausted the budget")
            if risk_precision_lost:
                raw_mean = np.mean(risk, dtype=np.longdouble)
                objective_mean_cost += raw_mean / horizon
                scaled_mean = float(
                    raw_mean / np.longdouble(risk_scale)
                ) / horizon
                mean_cost += scaled_mean
            else:
                if risk_scale != 1.0:
                    np.divide(risk, risk_scale, out=risk)
                period_mean = safe_mean(risk)
                mean_cost += period_mean / horizon
        mean_costs.append(mean_cost)
        if risk_precision_lost:
            objective_mean_costs.append(objective_mean_cost)

    for resource in resources:
        if time.monotonic() >= deadline:
            raise TimeoutError("model construction exhausted the budget")
        specification = instance["Resources"][resource]
        lower.extend(float(value) - checker_margin for value in specification["min"])
        upper.extend(float(value) + checker_margin for value in specification["max"])
    for first, second, season in instance["Exclusions"].values():
        if time.monotonic() >= deadline:
            raise TimeoutError("model construction exhausted the budget")
        for t in map(int, instance["Seasons"][season]):
            row = len(lower)
            lower.append(-np.inf)
            upper.append(1.0)
            for name in (first, second):
                for col in by_job[name]:
                    start = choices[col][1]
                    if start <= t < start + int(jobs[name]["Delta"][start - 1]):
                        rows.append(row)
                        columns.append(col)
                        values.append(1.0)

    choice_count = len(choices)
    base_matrix = coo_matrix(
        (values, (rows, columns)), shape=(len(lower), choice_count)
    ).tocsc()
    del rows, columns, values
    lo = np.asarray(lower, dtype=float)
    hi = np.asarray(upper, dtype=float)

    # Remove choices that a nonnegative resource row proves impossible by
    # themselves.  Besides shrinking the model, this lets an extreme but already
    # forbidden coefficient stop dictating the scale for the remaining row.
    choice_upper = np.ones(choice_count)
    resource_matrix = base_matrix[
        resource_base:resource_base + resource_row_count, :
    ].tocsr()
    nonempty_resource_rows = np.flatnonzero(np.diff(resource_matrix.indptr))
    for scan_index, local_row in enumerate(nonempty_resource_rows):
        if ((scan_index & 255) == 0 and time.monotonic() >= deadline):
            raise TimeoutError("resource preprocessing exhausted the budget")
        begin, end = resource_matrix.indptr[local_row:local_row + 2]
        row_data = resource_matrix.data[begin:end]
        if (row_data.size and np.all(row_data >= 0.0)
                and math.isfinite(hi[resource_base + local_row])):
            row_columns = resource_matrix.indices[begin:end]
            choice_upper[row_columns[
                row_data > hi[resource_base + local_row]
            ]] = 0.0
    if any(not np.any(choice_upper[by_job[name]] > 0.0) for name in names):
        raise RuntimeError("resource bounds eliminate every start of an intervention")

    column_job = np.empty(choice_count, dtype=np.int32)
    for job_index, name in enumerate(names):
        column_job[by_job[name]] = job_index

    # When a resource-period row is controlled by one intervention only, each
    # start can be checked exactly before any affine regrouping.  This preserves a
    # tiny feasible coefficient even when enormous alternatives would otherwise
    # round it together with an absent zero in the transformed model.
    for scan_index, local_row in enumerate(nonempty_resource_rows):
        if ((scan_index & 255) == 0 and time.monotonic() >= deadline):
            raise TimeoutError("resource preprocessing exhausted the budget")
        begin, end = resource_matrix.indptr[local_row:local_row + 2]
        row_columns = resource_matrix.indices[begin:end]
        viable = choice_upper[row_columns] > 0.0
        viable_columns = row_columns[viable]
        if viable_columns.size == 0:
            continue
        touched_jobs = np.unique(column_job[viable_columns])
        if touched_jobs.size != 1:
            continue
        job_index = int(touched_jobs[0])
        contributions = {
            int(col): float(value)
            for col, value in zip(row_columns, resource_matrix.data[begin:end])
        }
        row = resource_base + int(local_row)
        for col in by_job[names[job_index]]:
            if choice_upper[col] == 0.0:
                continue
            contribution = contributions.get(col, 0.0)
            if contribution < lo[row] or contribution > hi[row]:
                choice_upper[col] = 0.0

    if any(not np.any(choice_upper[by_job[name]] > 0.0) for name in names):
        raise RuntimeError("resource bounds eliminate every start of an intervention")
    # Fixed-zero columns no longer belong to any search or extraction domain.
    # Leaving them in these lists wasted most local-search slices on starts already
    # proved impossible and let malformed solver incumbents win an argmax at zero.
    for name in names:
        by_job[name] = [col for col in by_job[name] if choice_upper[col] > 0.0]

    all_viable_columns = np.flatnonzero(choice_upper > 0.0)
    viable_max_abs_risk = max(
        (choice_max_abs_risks[col] for col in all_viable_columns), default=0.0
    )
    viable_min_abs_nonzero_risk = min(
        (choice_min_abs_nonzero_risks[col] for col in all_viable_columns),
        default=math.inf,
    )
    viable_max_abs_integer_risk = max(
        (choice_max_abs_integer_risks[col] for col in all_viable_columns), default=0
    )
    integer_checker_required = (
        viable_max_abs_integer_risk
        * max(1, len(names))
        * max(1, int(np.max(scenario_counts)))
        > 2 ** 53
    )
    if not integer_checker_required:
        choice_raw_risks = []
    checker_nonfinite_possible = (
        viable_max_abs_risk
        > np.finfo(float).max / checker_overflow_factor
    )
    checker_rescore_required = risk_precision_lost or checker_nonfinite_possible
    checker_authoritative_required = checker_rescore_required or risk_scale != 1.0
    if (not risk_precision_lost and positive_objective_weights
            and viable_min_abs_nonzero_risk < math.inf):
        normalized_objective_unit = (
            np.longdouble(viable_min_abs_nonzero_risk)
            * np.longdouble(min(positive_objective_weights))
            / (np.longdouble(risk_scale) * smallest_contribution_divisor)
        )
        objective_longdouble = (
            normalized_objective_unit < np.longdouble(np.finfo(float).tiny)
        )
    elif not risk_precision_lost:
        objective_longdouble = False

    # Extreme signed cancellation can put a checker-significant coefficient below
    # every HiGHS matrix floor.  On only those rows, subtract each intervention's
    # minimum feasible contribution.  Assignment equalities make this an exact
    # affine transformation and fixed +/- huge terms disappear from the matrix.
    transformed_rows: dict[int, tuple[list[int], list[float], float]] = {}
    transform_expansion_budget = min(
        500_000, max(50_000, 2 * int(resource_matrix.nnz))
    )
    transformed_expansion_count = 0
    viable_domains: dict[int, np.ndarray] = {}
    domain_scan_count = 0
    for scan_index, local_row in enumerate(nonempty_resource_rows):
        if ((scan_index & 255) == 0 and time.monotonic() >= deadline):
            raise TimeoutError("resource preprocessing exhausted the budget")
        begin, end = resource_matrix.indptr[local_row:local_row + 2]
        row_columns = resource_matrix.indices[begin:end]
        row_data = resource_matrix.data[begin:end]
        viable = choice_upper[row_columns] > 0.0
        viable_columns = row_columns[viable]
        viable_values = row_data[viable]
        magnitudes = np.abs(viable_values[viable_values != 0.0])
        if (magnitudes.size < 2 or not np.any(viable_values < 0.0)
                or math.frexp(float(np.max(magnitudes)))[1]
                - math.frexp(float(np.min(magnitudes)))[1] <= 50):
            continue

        # Estimate the transformed row before materializing a Python dictionary.
        # A large row can be highly compressible when most entries equal the
        # intervention baseline, so cap only net fill-in rather than row width.
        row_jobs = column_job[viable_columns]
        touched_jobs, group_starts, group_counts = np.unique(
            row_jobs, return_index=True, return_counts=True
        )
        groups = []
        projected_entries = 0
        baseline_total = 0.0
        for job_index, group_start, group_count in zip(
                touched_jobs, group_starts, group_counts):
            group_end = int(group_start + group_count)
            group_columns = viable_columns[group_start:group_end]
            group_values = viable_values[group_start:group_end]
            integer_job = int(job_index)
            domain = viable_domains.get(integer_job)
            if domain is None:
                domain_values = []
                for col in by_job[names[integer_job]]:
                    if ((domain_scan_count & 4095) == 0
                            and time.monotonic() >= deadline):
                        raise TimeoutError(
                            "resource preprocessing exhausted the budget"
                        )
                    domain_scan_count += 1
                    if choice_upper[col] > 0.0:
                        domain_values.append(col)
                domain = np.asarray(domain_values, dtype=np.int32)
                viable_domains[integer_job] = domain
            baseline = float(np.min(group_values))
            if group_count < domain.size:
                baseline = min(0.0, baseline)
            adjusted = group_values - baseline
            retained_existing = int(np.count_nonzero(adjusted))
            absent_count = int(domain.size - group_count) if baseline else 0
            projected_entries += retained_existing + absent_count
            baseline_total += baseline
            groups.append((domain, group_columns, adjusted, baseline))
        expansion = max(0, projected_entries - viable_columns.size)
        if (not math.isfinite(baseline_total)
                or transformed_expansion_count + expansion
                > transform_expansion_budget):
            continue

        transformed_columns: list[int] = []
        transformed_values: list[float] = []
        finite = True
        for domain, group_columns, adjusted, baseline in groups:
            retained = adjusted != 0.0
            retained_values = adjusted[retained]
            if not np.all(np.isfinite(retained_values)):
                finite = False
                break
            transformed_columns.extend(group_columns[retained].tolist())
            transformed_values.extend(retained_values.tolist())
            if baseline:
                absent = np.setdiff1d(
                    domain, group_columns, assume_unique=True
                )
                transformed_columns.extend(absent.tolist())
                transformed_values.extend([-baseline] * absent.size)
        if not finite:
            continue
        transformed_rows[local_row] = (
            transformed_columns, transformed_values, baseline_total
        )
        transformed_expansion_count += expansion

    groups = viable_domains = domain_values = None
    affine_transformed = bool(transformed_rows)
    eliminated_columns = np.flatnonzero(choice_upper == 0.0)
    if transformed_rows:
        solver_resource_matrix = resource_matrix.tolil(copy=True)
        solver_lo = lo.copy()
        solver_hi = hi.copy()
        for local_row, (row_columns, row_values, baseline) in transformed_rows.items():
            solver_resource_matrix.rows[local_row] = row_columns
            solver_resource_matrix.data[local_row] = row_values
            row = resource_base + local_row
            solver_lo[row] -= baseline
            solver_hi[row] -= baseline
        solver_base_matrix = vstack([
            base_matrix[:resource_base, :],
            solver_resource_matrix.tocsc(),
            base_matrix[resource_base + resource_row_count:, :],
        ]).tocsc()
        del solver_resource_matrix
    else:
        solver_lo = lo
        solver_hi = hi
        solver_base_matrix = (
            base_matrix.copy() if eliminated_columns.size else base_matrix
        )
    if eliminated_columns.size:
        if solver_base_matrix is base_matrix:
            solver_base_matrix = base_matrix.copy()
        for col in eliminated_columns:
            begin, end = solver_base_matrix.indptr[col:col + 2]
            column_rows = solver_base_matrix.indices[begin:end]
            resource_entries = ((column_rows >= resource_base)
                                & (column_rows < resource_base + resource_row_count))
            solver_base_matrix.data[begin:end][resource_entries] = 0.0
        solver_base_matrix.eliminate_zeros()
    resource_matrix = solver_base_matrix[
        resource_base:resource_base + resource_row_count, :
    ].tocsr()
    del column_job, eliminated_columns, transformed_rows

    def preferred_shifts(row_minimum, row_maximum):
        minimum_exponent = math.frexp(row_minimum)[1]
        maximum_exponent = math.frexp(row_maximum)[1]
        return (-20 - minimum_exponent + 1,
                30 - maximum_exponent)

    # A nonnegative lower-bound row has an exact capped form:
    # sum(a*x) >= L iff sum(min(a,L)*x) >= L.  Add that form only
    # when the original dynamic range cannot keep its smallest coefficient in
    # HiGHS' useful window.  This preserves tiny required work beside 1e308 terms.
    lower_row_parts: list[np.ndarray] = []
    lower_column_parts: list[np.ndarray] = []
    lower_value_parts: list[np.ndarray] = []
    lower_bounds: list[float] = []
    resource_rows_changed = False
    lower_entry_budget = 500_000
    lower_entry_count = 0
    for scan_index, local_row in enumerate(nonempty_resource_rows):
        if ((scan_index & 255) == 0 and time.monotonic() >= deadline):
            raise TimeoutError("resource preprocessing exhausted the budget")
        begin, end = resource_matrix.indptr[local_row:local_row + 2]
        row_columns = resource_matrix.indices[begin:end]
        row_data = resource_matrix.data[begin:end]
        if row_data.size == 0 or np.any(row_data < 0.0):
            continue
        row = resource_base + local_row
        lower_bound = float(solver_lo[row])
        if not math.isfinite(lower_bound) or lower_bound <= 0.0:
            continue
        upperless = not math.isfinite(float(solver_hi[row]))
        if (not upperless
                and lower_entry_count + row_data.size > lower_entry_budget):
            continue
        matrix_minimum = float(np.min(row_data))
        matrix_maximum = float(np.max(row_data))
        lift_shift, cap_shift = preferred_shifts(
            min(matrix_minimum, lower_bound),
            max(matrix_maximum, lower_bound),
        )
        if lift_shift <= cap_shift:
            continue
        capped = np.minimum(row_data, lower_bound)
        capped_minimum = float(np.min(capped))
        capped_maximum = float(np.max(capped))
        capped_lift, capped_cap = preferred_shifts(
            min(capped_minimum, lower_bound),
            max(capped_maximum, lower_bound),
        )
        shift = (
            min(max(0, capped_lift), capped_cap)
            if capped_lift <= capped_cap else capped_cap
        )
        shift = max(-1022, min(1023, shift))
        scaled_values = np.ldexp(capped, shift)
        scaled_lower = math.ldexp(lower_bound, shift)
        if upperless:
            # This row has no upper role, so replace it directly with the exact
            # capped form rather than appending a duplicate sparse row.
            resource_matrix.data[begin:end] = scaled_values
            if solver_lo is lo:
                solver_lo = solver_lo.copy()
            solver_lo[row] = scaled_lower
            resource_rows_changed = True
            continue
        extra_row = len(lower_bounds)
        lower_row_parts.append(np.full(
            row_columns.size, extra_row, dtype=row_columns.dtype
        ))
        lower_column_parts.append(row_columns.copy())
        lower_value_parts.append(scaled_values)
        lower_entry_count += row_columns.size
        lower_bounds.append(scaled_lower)
        if solver_lo is lo:
            solver_lo = solver_lo.copy()
        solver_lo[row] = -np.inf

    row_columns = row_data = capped = scaled_values = None
    if lower_bounds:
        lower_row_array = np.concatenate(lower_row_parts)
        lower_column_array = np.concatenate(lower_column_parts)
        lower_value_array = np.concatenate(lower_value_parts)
        lower_matrix = coo_matrix(
            (lower_value_array, (lower_row_array, lower_column_array)),
            shape=(len(lower_bounds), choice_count),
        ).tocsc()
        del (lower_row_array, lower_column_array, lower_value_array,
             lower_row_parts, lower_column_parts, lower_value_parts)
    else:
        lower_matrix = None
        del lower_row_parts, lower_column_parts, lower_value_parts
    if resource_rows_changed:
        if time.monotonic() >= deadline:
            raise TimeoutError("resource preprocessing exhausted the budget")
        matrix_parts = [
            solver_base_matrix[:resource_base, :],
            resource_matrix,
            solver_base_matrix[resource_base + resource_row_count:, :],
        ]
        if lower_matrix is not None:
            matrix_parts.append(lower_matrix)
        solver_base_matrix = vstack(matrix_parts).tocsc()
        del matrix_parts
    elif lower_matrix is not None:
        solver_base_matrix = vstack([
            solver_base_matrix, lower_matrix
        ]).tocsc()
    if lower_matrix is not None:
        solver_lo = np.r_[solver_lo, np.asarray(lower_bounds)]
        solver_hi = np.r_[solver_hi, np.full(len(lower_bounds), np.inf)]
        del lower_matrix
    del lower_bounds, resource_rows_changed, lower_entry_count

    # HiGHS rejects huge matrix values and removes tiny ones before its own row
    # scaling.  Apply an exact power-of-two scale to each resource-period row,
    # keeping the original matrix and bounds for checker-scale reconstruction.
    # Whenever the row's dynamic range permits it, this places every nonzero in
    # [2^-20, 2^30), comfortably inside HiGHS' useful coefficient range.
    # Only resource rows are eligible for scaling.  Keeping a diagonal entry for
    # every assignment and exclusion row can add hundreds of megabytes on broad
    # exclusion models, so store and apply this compact resource-only vector.
    model_row_scales = np.ones(resource_row_count)
    for scan_index, local_row in enumerate(nonempty_resource_rows):
        if ((scan_index & 255) == 0 and time.monotonic() >= deadline):
            raise TimeoutError("resource preprocessing exhausted the budget")
        begin, end = resource_matrix.indptr[local_row:local_row + 2]
        row_columns = resource_matrix.indices[begin:end]
        row_data = resource_matrix.data[begin:end]
        viable_data = np.abs(row_data[choice_upper[row_columns] > 0.0])
        viable_data = viable_data[viable_data != 0.0]
        if viable_data.size == 0:
            continue
        matrix_minimum = float(np.min(viable_data))
        matrix_maximum = float(np.max(viable_data))
        row = resource_base + local_row
        finite_endpoints = [
            abs(endpoint) for endpoint in (solver_lo[row], solver_hi[row])
            if math.isfinite(endpoint) and endpoint != 0.0
        ]
        minimum = min([matrix_minimum, *finite_endpoints])
        maximum = max([matrix_maximum, *finite_endpoints])

        lift_shift, cap_shift = preferred_shifts(minimum, maximum)
        if lift_shift <= cap_shift:
            # Scale finite bounds together with coefficients when their combined
            # range fits the solver's useful window.
            shift = min(max(0, lift_shift), cap_shift)
        else:
            coefficient_lift, coefficient_cap = preferred_shifts(
                matrix_minimum, matrix_maximum
            )
            if coefficient_lift <= coefficient_cap:
                # An effectively unbounded endpoint must not force otherwise
                # representable matrix entries below HiGHS' coefficient floor.
                shift = min(max(0, coefficient_lift), coefficient_cap)
            else:
                # No single row scale can represent this coefficient range.  Keep
                # the largest entry legal; strict feasibility extraction and the
                # robust retry remain authoritative for the checker-scale row.
                shift = coefficient_cap
        shift = max(-1022, min(1023, shift))
        model_row_scales[local_row] = math.ldexp(1.0, shift)
    row_columns = row_data = viable_data = None
    if np.any(model_row_scales != 1.0):
        scaled_resource = (
            diags(model_row_scales) @ solver_base_matrix[
                resource_base:resource_base + resource_row_count, :
            ]
        ).tocsc()
        model_base_matrix = vstack([
            solver_base_matrix[:resource_base, :],
            scaled_resource,
            solver_base_matrix[resource_base + resource_row_count:, :],
        ]).tocsc()
        model_lo = solver_lo.copy()
        model_hi = solver_hi.copy()
        resource_slice = slice(resource_base, resource_base + resource_row_count)
        with np.errstate(over="ignore", invalid="ignore"):
            model_lo[resource_slice] *= model_row_scales
            model_hi[resource_slice] *= model_row_scales
        del scaled_resource
    else:
        model_base_matrix = solver_base_matrix
        model_lo = solver_lo
        model_hi = solver_hi
    small_base_coefficient_seen = has_small_nonzero(model_base_matrix.data)
    del (resource_matrix, nonempty_resource_rows, solver_base_matrix,
         solver_lo, solver_hi)

    mean_costs_array = np.asarray(mean_costs)
    if risk_precision_lost:
        local_mean_costs_array = np.asarray(
            objective_mean_costs, dtype=np.longdouble
        )
    else:
        local_mean_costs_array = mean_costs_array
    del mean_costs, objective_mean_costs

    def run_milp(cost, integrality, bounds, constraints, limit, gap=1e-5,
                 robust=False, presolve=True, small_coefficients=None):
        # Callers may have spent time assembling a sparse model after computing
        # their nominal allowance.  Never give HiGHS a stale limit that extends
        # beyond this solve's own deadline.
        limit = min(float(limit), deadline - time.monotonic())
        if limit <= 0.02:
            return None
        try:
            options = {
                "time_limit": limit,
                "mip_rel_gap": gap,
                "threads": 1,
                "random_seed": highs_seed,
                "presolve": bool(presolve),
            }
            if robust:
                options.update({
                    "primal_feasibility_tolerance": 1e-9,
                    "mip_feasibility_tolerance": 1e-9,
                })
                # Retaining sub-floor values is important when many tiny
                # workload coefficients aggregate into a checker-visible total.
                if (small_base_coefficient_seen
                        if small_coefficients is None else small_coefficients):
                    options["small_matrix_value"] = 1e-12
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", message="Unrecognized options detected")
                return milp(
                    cost,
                    integrality=integrality,
                    bounds=bounds,
                    constraints=constraints,
                    options=options,
                )
        except (MemoryError, OverflowError, RuntimeError, ValueError):
            return None

    def reconstruct_activity(state_selected: dict[str, int]) -> np.ndarray:
        """Rebuild hard constraints in the official intervention order."""
        indicator = np.zeros(choice_count)
        indicator[list(state_selected.values())] = 1.0
        activity = np.asarray(base_matrix @ indicator).ravel()
        if resource_row_count:
            resource_stop = resource_base + resource_row_count
            activity[resource_base:resource_stop] = 0.0
            # Sparse multiplication is free to choose a reduction order.  The
            # checker instead adds one intervention at a time into float64 rows.
            for name in names:
                col = state_selected[name]
                begin, end = base_matrix.indptr[col:col + 2]
                for pointer in range(begin, end):
                    row = base_matrix.indices[pointer]
                    if resource_base <= row < resource_stop:
                        activity[row] += base_matrix.data[pointer]
        return activity

    def extract(result):
        if result is None or result.x is None:
            return None
        selected = {name: max(by_job[name], key=lambda c: result.x[c]) for name in names}
        activity = reconstruct_activity(selected)
        if np.any(activity < lo - numerical_slack) or np.any(activity > hi + numerical_slack):
            return None
        return selected, activity

    def build_original_resource_model():
        """Build a checker-scale fallback when a conditioned model rejects its incumbent."""
        original_model = base_matrix.copy()
        for col in np.flatnonzero(choice_upper == 0.0):
            begin, end = original_model.indptr[col:col + 2]
            column_rows = original_model.indices[begin:end]
            resource_entries = (
                (column_rows >= resource_base)
                & (column_rows < resource_base + resource_row_count)
            )
            original_model.data[begin:end][resource_entries] = 0.0
        original_model.eliminate_zeros()
        original_resource = original_model[
            resource_base:resource_base + resource_row_count, :
        ].tocsr()
        scales = np.ones(resource_row_count)
        nonempty_rows = np.flatnonzero(np.diff(original_resource.indptr))
        for scan_index, local_row in enumerate(nonempty_rows):
            if ((scan_index & 255) == 0 and time.monotonic() >= deadline):
                raise TimeoutError
            begin, end = original_resource.indptr[local_row:local_row + 2]
            row_columns = original_resource.indices[begin:end]
            row_data = original_resource.data[begin:end]
            viable_data = np.abs(row_data[choice_upper[row_columns] > 0.0])
            viable_data = viable_data[viable_data != 0.0]
            if viable_data.size == 0:
                continue
            matrix_minimum = float(np.min(viable_data))
            matrix_maximum = float(np.max(viable_data))
            row = resource_base + int(local_row)
            finite_endpoints = [
                abs(endpoint) for endpoint in (lo[row], hi[row])
                if math.isfinite(endpoint) and endpoint != 0.0
            ]
            minimum = min([matrix_minimum, *finite_endpoints])
            maximum = max([matrix_maximum, *finite_endpoints])
            if (matrix_minimum > 1e-12
                    and matrix_maximum < 1e15):
                # This is the checker-row fallback: when HiGHS can ingest every
                # original coefficient, do not recreate the conditioning that just
                # produced an invalid incumbent.  Rows outside HiGHS' accepted
                # matrix range still need a secondary power-of-two representation.
                shift = 0
            else:
                lift_shift, cap_shift = preferred_shifts(minimum, maximum)
                if lift_shift <= cap_shift:
                    shift = min(max(0, lift_shift), cap_shift)
                else:
                    coefficient_lift, coefficient_cap = preferred_shifts(
                        matrix_minimum, matrix_maximum
                    )
                    shift = (
                        min(max(0, coefficient_lift), coefficient_cap)
                        if coefficient_lift <= coefficient_cap else coefficient_cap
                    )
            # Do not shrink a checker-width equality or narrow interval below its
            # original absolute resolution.  HiGHS can otherwise merge the sole
            # valid activity with a neighboring assignment during presolve.
            if (shift < 0 and math.isfinite(lo[row]) and math.isfinite(hi[row])
                    and hi[row] > lo[row]):
                width = hi[row] - lo[row]
                minimum_width = 2.0 * checker_margin
                if width < minimum_width or math.ldexp(width, shift) < minimum_width:
                    shift = max(shift, math.ceil(math.log2(minimum_width / width)))
            shift = max(-1022, min(1023, shift))
            scales[local_row] = math.ldexp(1.0, shift)
        if np.any(scales != 1.0):
            scaled_resource = (diags(scales) @ original_resource).tocsc()
            original_model = vstack([
                original_model[:resource_base, :],
                scaled_resource,
                original_model[resource_base + resource_row_count:, :],
            ]).tocsc()
            original_lo = lo.copy()
            original_hi = hi.copy()
            resource_slice = slice(resource_base, resource_base + resource_row_count)
            with np.errstate(over="ignore", invalid="ignore"):
                original_lo[resource_slice] *= scales
                original_hi[resource_slice] *= scales
            del scaled_resource
        else:
            original_lo = lo
            original_hi = hi
        return original_model, original_lo, original_hi, scales

    def coloring_fallback(until: float):
        """Find a feasible full-horizon exclusion schedule with tabu coloring.

        With no resources and full-horizon exclusions, starts aligned to a
        shared slot width form a conservative list-coloring subproblem: distinct
        colors cannot overlap.  HiGHS can spend the whole budget proving a dense
        model infeasible without exposing an incumbent, so this bounded primal
        heuristic searches that subproblem before a pure-feasibility retry.
        """
        if (instance["Resources"] or len(names) == 0
                or time.monotonic() >= until):
            return None
        adjacency = [set() for _ in names]
        name_index = {name: i for i, name in enumerate(names)}
        full_season_cache: dict[str, bool] = {}

        def season_is_full(season: str) -> bool:
            cached = full_season_cache.get(season)
            if cached is not None:
                return cached
            periods: set[int] = set()
            in_range = True
            for index, raw_period in enumerate(instance["Seasons"][season]):
                if (index & 4095) == 0 and time.monotonic() >= until:
                    return False
                period = int(raw_period)
                in_range = in_range and 1 <= period <= horizon
                periods.add(period)
            result = in_range and len(periods) == horizon
            full_season_cache[season] = result
            return result

        for exclusion_index, (first, second, season) in enumerate(
                instance["Exclusions"].values()):
            if ((exclusion_index & 255) == 0
                    and time.monotonic() >= until):
                return None
            if first == second or not season_is_full(season):
                return None
            i, j = name_index[first], name_index[second]
            adjacency[i].add(j)
            adjacency[j].add(i)
        minimum_durations = []
        scanned_columns = 0
        for name in names:
            minimum_duration = horizon + 1
            for col in by_job[name]:
                if ((scanned_columns & 1023) == 0
                        and time.monotonic() >= until):
                    return None
                scanned_columns += 1
                start = choices[col][1]
                minimum_duration = min(
                    minimum_duration, int(jobs[name]["Delta"][start - 1])
                )
            minimum_durations.append(minimum_duration)
        slot_width = max(minimum_durations)

        domains = []
        columns_by_color = []
        for name in names:
            mapping = {}
            for col in by_job[name]:
                if ((scanned_columns & 1023) == 0
                        and time.monotonic() >= until):
                    return None
                scanned_columns += 1
                start = choices[col][1]
                duration = int(jobs[name]["Delta"][start - 1])
                if duration <= slot_width and (start - 1) % slot_width == 0:
                    mapping[(start - 1) // slot_width] = col
            if not mapping:
                return None
            domains.append(tuple(mapping))
            columns_by_color.append(mapping)

        # A fixed primal-search stream makes fallback reliability independent of
        # HiGHS' seed while the optimization stages still honor the CLI seed.
        rng = random.Random(2020)
        vertex_count = len(names)

        def candidate_from_colors(colors):
            selected = {
                name: columns_by_color[i][colors[i]]
                for i, name in enumerate(names)
            }
            activity = reconstruct_activity(selected)
            if (np.any(activity < lo - numerical_slack)
                    or np.any(activity > hi + numerical_slack)):
                return None
            return selected, activity

        while time.monotonic() < until:
            colors = [rng.choice(domain) for domain in domains]
            neighbor_colors: list[dict[int, int]] = [{} for _ in names]
            incidence_count = 0
            for vertex in range(vertex_count):
                counts = neighbor_colors[vertex]
                for neighbor in adjacency[vertex]:
                    if ((incidence_count & 4095) == 0
                            and time.monotonic() >= until):
                        return None
                    incidence_count += 1
                    color = colors[neighbor]
                    counts[color] = counts.get(color, 0) + 1
            conflicts = sum(
                neighbor_colors[v].get(colors[v], 0)
                for v in range(vertex_count)
            ) // 2
            best_conflicts = conflicts
            tabu_until: list[dict[int, int]] = [{} for _ in names]
            last_improvement = 0
            iteration = 0
            while conflicts and time.monotonic() < until:
                best_delta = vertex_count * vertex_count + 1
                best_move = None
                tie_count = 0
                color_probes = 0
                for vertex in range(vertex_count):
                    old_color = colors[vertex]
                    old_conflicts = neighbor_colors[vertex].get(old_color, 0)
                    if old_conflicts == 0:
                        continue
                    for color in domains[vertex]:
                        if ((color_probes & 1023) == 0
                                and time.monotonic() >= until):
                            return None
                        color_probes += 1
                        if color == old_color:
                            continue
                        delta = (neighbor_colors[vertex].get(color, 0)
                                 - old_conflicts)
                        if (tabu_until[vertex].get(color, 0) > iteration
                                and conflicts + delta >= best_conflicts):
                            continue
                        if delta < best_delta:
                            best_delta = delta
                            best_move = (vertex, color)
                            tie_count = 1
                        elif delta == best_delta:
                            tie_count += 1
                            if rng.randrange(tie_count) == 0:
                                best_move = (vertex, color)
                if best_move is None:
                    break
                vertex, color = best_move
                old_color = colors[vertex]
                colors[vertex] = color
                conflicts += best_delta
                tenure = 5 + rng.randrange(6) + conflicts // 20
                tabu_until[vertex][old_color] = iteration + tenure
                for neighbor in adjacency[vertex]:
                    counts = neighbor_colors[neighbor]
                    old_count = counts.get(old_color, 0) - 1
                    if old_count:
                        counts[old_color] = old_count
                    else:
                        counts.pop(old_color, None)
                    counts[color] = counts.get(color, 0) + 1
                iteration += 1
                if conflicts < best_conflicts:
                    best_conflicts = conflicts
                    last_improvement = iteration
                elif iteration - last_improvement > 10_000:
                    break
            if conflicts == 0:
                return candidate_from_colors(colors)
        return None

    remaining = deadline - time.monotonic()
    if remaining <= 0.05:
        raise TimeoutError("model construction exhausted the budget")
    mean_result = run_milp(
        mean_costs_array,
        np.ones(choice_count),
        Bounds(np.zeros(choice_count), choice_upper),
        LinearConstraint(model_base_matrix, model_lo, model_hi),
        max(0.05, remaining * (0.30 if refine else 0.95)),
        1e-5,
    )
    extracted = extract(mean_result)
    repair_result = mean_result
    repair_model = model_base_matrix
    repair_lo, repair_hi = model_lo, model_hi
    repair_scales = model_row_scales
    repair_small = small_base_coefficient_seen
    feasibility_model = repair_model
    feasibility_lo, feasibility_hi = repair_lo, repair_hi
    feasibility_small = repair_small
    original_model = original_lo = original_hi = original_scales = None
    original_result = repaired_model = repaired_lo = repaired_hi = cut_matrix = None

    # HiGHS presolve can occasionally postsolve an assignment-incomplete vector
    # after fixed-zero columns were stripped.  Retry the same model without
    # presolve before changing its mathematically valid constraints.
    if extracted is None:
        retry_remaining = deadline - time.monotonic()
        no_presolve_result = run_milp(
            mean_costs_array,
            np.ones(choice_count),
            Bounds(np.zeros(choice_count), choice_upper),
            LinearConstraint(repair_model, repair_lo, repair_hi),
            min(2.0, max(0.05, 0.12 * retry_remaining)),
            1e-4,
            robust=True,
            presolve=False,
            small_coefficients=repair_small,
        )
        no_presolve_extracted = extract(no_presolve_result)
        if no_presolve_result is not None and no_presolve_result.x is not None:
            repair_result = no_presolve_result
        if no_presolve_extracted is not None:
            extracted = no_presolve_extracted

    if extracted is None and resource_row_count:
        # Affine and capped lower-row rewrites are exact over real arithmetic but
        # can change binary64 summation or presolve behavior.  Retry the original
        # checker rows before declaring a feasible instance dead.
        try:
            (original_model, original_lo, original_hi,
             original_scales) = build_original_resource_model()
        except TimeoutError:
            original_model = None
        if original_model is not None:
            original_small = has_small_nonzero(original_model.data)
            fallback_remaining = deadline - time.monotonic()
            original_result = run_milp(
                mean_costs_array,
                np.ones(choice_count),
                Bounds(np.zeros(choice_count), choice_upper),
                LinearConstraint(original_model, original_lo, original_hi),
                min(5.0, max(0.05, 0.20 * fallback_remaining)),
                1e-4,
                robust=True,
                small_coefficients=original_small,
            )
            original_extracted = extract(original_result)
            if original_extracted is None:
                fallback_remaining = deadline - time.monotonic()
                unpresolved_result = run_milp(
                    mean_costs_array,
                    np.ones(choice_count),
                    Bounds(np.zeros(choice_count), choice_upper),
                    LinearConstraint(original_model, original_lo, original_hi),
                    min(2.0, max(0.05, 0.12 * fallback_remaining)),
                    1e-4,
                    robust=True,
                    presolve=False,
                    small_coefficients=original_small,
                )
                unpresolved_extracted = extract(unpresolved_result)
                if (unpresolved_result is not None
                        and unpresolved_result.x is not None):
                    original_result = unpresolved_result
                if unpresolved_extracted is not None:
                    original_extracted = unpresolved_extracted
            if original_result is not None and original_result.x is not None:
                repair_result = original_result
                repair_model = original_model
                repair_lo, repair_hi = original_lo, original_hi
                repair_scales = original_scales
                repair_small = original_small
                feasibility_model = repair_model
                feasibility_lo, feasibility_hi = repair_lo, repair_hi
                feasibility_small = repair_small
            if original_extracted is not None:
                extracted = original_extracted
                model_base_matrix = original_model
                model_lo, model_hi = original_lo, original_hi
                model_row_scales = original_scales
                small_base_coefficient_seen = original_small

    if extracted is None and repair_result is not None and repair_result.x is not None:
        # A numerically conditioned model may expose an incumbent that fails the
        # source-order checker.  Exclude only that complete assignment and ask for
        # another incumbent; a handful of lazy no-good cuts repairs common cases
        # where sub-floor upper-row terms were ignored by HiGHS.
        cut_columns: list[int] = []
        cut_rows: list[int] = []
        for attempt in range(8):
            if time.monotonic() >= deadline - 0.10:
                break
            invalid_columns = [
                max(by_job[name], key=lambda col: repair_result.x[col])
                for name in names
            ]
            cut_columns.extend(invalid_columns)
            cut_rows.extend([attempt] * len(invalid_columns))
            cut_matrix = coo_matrix(
                (np.ones(len(cut_columns)), (cut_rows, cut_columns)),
                shape=(attempt + 1, choice_count),
            ).tocsc()
            repaired_model = vstack([repair_model, cut_matrix]).tocsc()
            repaired_lo = np.r_[repair_lo, np.full(attempt + 1, -np.inf)]
            repaired_hi = np.r_[repair_hi, np.full(
                attempt + 1, len(names)) - 1.0
            ]
            feasibility_model = repaired_model
            feasibility_lo, feasibility_hi = repaired_lo, repaired_hi
            feasibility_small = repair_small
            repair_remaining = deadline - time.monotonic()
            next_result = run_milp(
                mean_costs_array,
                np.ones(choice_count),
                Bounds(np.zeros(choice_count), choice_upper),
                LinearConstraint(repaired_model, repaired_lo, repaired_hi),
                min(1.0, max(0.05, 0.12 * repair_remaining)),
                1e-3,
                robust=True,
                small_coefficients=repair_small,
            )
            if next_result is None or next_result.x is None:
                break
            repair_result = next_result
            extracted = extract(repair_result)
            if extracted is not None:
                model_base_matrix = repaired_model
                model_lo, model_hi = repaired_lo, repaired_hi
                model_row_scales = repair_scales
                small_base_coefficient_seen = has_small_nonzero(
                    model_base_matrix.data
                )
                break
    if extracted is None:
        heuristic_time = min(
            deadline - 0.15,
            time.monotonic() + min(8.0, max(5.0, 0.14 * seconds)),
        )
        extracted = coloring_fallback(heuristic_time)
    if extracted is None:
        # Preserve every accumulated cut and disable the presolve layer that may
        # have produced the invalid incumbent in the final feasibility retry.
        remaining = deadline - time.monotonic()
        feasibility_result = run_milp(
            np.zeros(choice_count),
            np.ones(choice_count),
            Bounds(np.zeros(choice_count), choice_upper),
            LinearConstraint(feasibility_model, feasibility_lo, feasibility_hi),
            max(0.05, remaining - 0.10),
            1e-3,
            robust=True,
            presolve=False,
            small_coefficients=feasibility_small,
        )
        extracted = extract(feasibility_result)
    if extracted is None:
        raise RuntimeError("HiGHS did not find a feasible incumbent")
    selected, activity = extracted
    hard_feasible_selected = selected.copy()
    selected_max_abs_risk = max(
        (choice_max_abs_risks[col] for col in selected.values()), default=0.0
    )
    hard_finite_proven = (
        selected_max_abs_risk
        <= np.finfo(float).max / checker_overflow_factor
        or (len(names) == 1 and horizon == 1
            and int(scenario_counts[0]) == 1)
    )
    # Drop lazy-repair aliases; model_base_matrix remains the sole matrix owner for
    # any later MILP refinement stage.
    repair_model = original_model = repaired_model = cut_matrix = None
    feasibility_model = feasibility_lo = feasibility_hi = feasibility_result = None
    repair_lo = repair_hi = repair_scales = repair_result = None
    original_lo = original_hi = original_scales = original_result = None
    no_presolve_result = no_presolve_extracted = None
    unpresolved_result = unpresolved_extracted = None
    repaired_lo = repaired_hi = None
    if not refine and not checker_nonfinite_possible:
        # The conservative aggregation bound above proves every checker reduction
        # finite, so a mean-only call need not build quantile state merely to repeat
        # that proof.  Overflow-capable incumbents continue through authoritative
        # source-order scoring and finite-basin recovery below.
        return {name: choices[col][1] for name, col in selected.items()}

    # The MILP uses NumPy means while the official checker uses Python's
    # compensated sum.  Even an optimal mean-model proof can reverse at one ULP,
    # so authoritative schedule comparisons below use checker-order reduction.

    quantile = float(instance["Quantile"])
    kth_indices = np.ceil(scenario_counts * quantile).astype(int) - 1
    # The pinned checker indexes -1 when Quantile is zero, i.e. it uses the
    # maximum scenario rather than an empty order-statistic selection.
    selected_counts = np.where(
        kth_indices < 0, scenario_counts + kth_indices + 1, kth_indices + 1
    )
    all_scenarios_selected = bool(np.all(selected_counts == scenario_counts))

    objective_zero = np.longdouble(0.0) if objective_longdouble else 0.0

    def positive_retained(value):
        retained = value if objective_longdouble else float(value)
        return max(objective_zero, retained)

    scoring_timed_out = False

    def score_timeout() -> float:
        """Mark an interrupted traversal separately from genuine nonfiniteness."""
        nonlocal scoring_timed_out
        scoring_timed_out = True
        return math.inf

    def ordered_float_sum(risks: np.ndarray) -> float:
        """Feed one compensated sum in order while polling between wide chunks."""
        def mapped_chunks():
            for begin in range(0, risks.size, 65536):
                if time.monotonic() >= deadline:
                    raise TimeoutError
                yield map(float, risks[begin:begin + 65536])

        return sum(itertools.chain.from_iterable(mapped_chunks()))

    def reduce_period_statistics(period_means: np.ndarray,
                                 period_quantiles: np.ndarray,
                                 result_scale_shift: int = 0):
        """Match the official binary64 horizon reduction and objective blend."""
        with np.errstate(over="ignore", invalid="ignore", under="ignore"):
            mean_risk = float(np.mean(period_means, dtype=np.float64))
            excess = float(np.mean(
                np.maximum(period_quantiles - period_means, 0.0),
                dtype=np.float64,
            ))
            checker_value = alpha * mean_risk + (1.0 - alpha) * excess
        if not all(map(math.isfinite, (mean_risk, excess, checker_value))):
            return math.inf
        # The official blend above stays binary64.  Convert only afterward so a
        # normalized comparison key cannot underflow two distinct official values
        # to the same zero.
        if result_scale_shift or objective_longdouble:
            return np.ldexp(
                np.longdouble(checker_value), -result_scale_shift
            )
        return checker_value

    def checker_vector_value(checker_risk: np.ndarray,
                             result_scale_shift: int = 0):
        """Reduce one aggregated vector in the official checker's order."""
        period_means = np.empty(horizon, dtype=np.float64)
        period_quantiles = np.empty(horizon, dtype=np.float64)
        with np.errstate(over="ignore", invalid="ignore", under="ignore"):
            for t in range(horizon):
                if ((t & 1023) == 0 and time.monotonic() >= deadline):
                    return score_timeout()
                risks = checker_risk[offsets[t]:offsets[t + 1]]
                try:
                    summed = ordered_float_sum(risks)
                except TimeoutError:
                    return score_timeout()
                period_means[t] = summed / int(scenario_counts[t])
                period_quantiles[t] = float(
                    np.partition(risks, kth_indices[t])[kth_indices[t]]
                )
        return reduce_period_statistics(
            period_means, period_quantiles, result_scale_shift
        )

    raw_score_cache: dict[tuple[int, ...], float] = {}

    def raw_checker_schedule_value(state_selected: dict[str, int]) -> float:
        """Score native JSON numbers before any binary64 integer coercion."""
        signature = tuple(state_selected[name] for name in names)
        cached = raw_score_cache.get(signature)
        if cached is not None:
            return cached
        period_pieces: list[list[list]] = [[] for _ in range(horizon)]
        for name_index, name in enumerate(names):
            if ((name_index & 31) == 0
                    and time.monotonic() >= deadline):
                return score_timeout()
            for t, raw in choice_raw_risks[state_selected[name]]:
                if raw is not None:
                    period_pieces[t].append(raw)
        period_means = np.empty(horizon, dtype=np.float64)
        period_quantiles = np.empty(horizon, dtype=np.float64)
        try:
            for t, pieces in enumerate(period_pieces):
                if ((t & 1023) == 0 and time.monotonic() >= deadline):
                    return score_timeout()
                values = [0] * int(scenario_counts[t])
                additions = 0
                for raw in pieces:
                    for scenario_index, additional_risk in enumerate(raw):
                        if ((additions & 65535) == 0
                                and time.monotonic() >= deadline):
                            return score_timeout()
                        additions += 1
                        values[scenario_index] += additional_risk
                period_means[t] = sum(values) / int(scenario_counts[t])
                values.sort()
                period_quantiles[t] = values[kth_indices[t]]
        except (MemoryError, OverflowError, ValueError):
            return math.inf
        result_shift = 0 if risk_precision_lost else risk_scale_shift
        value = reduce_period_statistics(
            period_means, period_quantiles, result_shift
        )
        if len(raw_score_cache) >= 256:
            raw_score_cache.clear()
        raw_score_cache[signature] = value
        return value

    def checker_schedule_value(
            state_selected: dict[str, int],
            workspace: np.ndarray | None = None,
            *,
            restore_internal: bool = False,
    ):
        """Reproduce aggregation on the official checker's unscaled values."""
        if integer_checker_required:
            return raw_checker_schedule_value(state_selected)
        reusable = (
            workspace is not None
            and workspace.dtype == np.float64
            and workspace.size == total_scenarios
        )
        checker_risk = (
            workspace if reusable else np.empty(total_scenarios, dtype=np.float64)
        )
        checker_risk.fill(0.0)
        with np.errstate(over="ignore", invalid="ignore", under="ignore"):
            for name_index, name in enumerate(names):
                if ((name_index & 31) == 0
                        and time.monotonic() >= deadline):
                    return score_timeout()
                col = state_selected[name]
                for piece_index, (t, risk) in enumerate(choice_risks[col]):
                    if ((piece_index & 255) == 0
                            and time.monotonic() >= deadline):
                        return score_timeout()
                    raw_risk = (
                        risk if risk_precision_lost or risk_scale_shift == 0
                        else np.ldexp(risk, risk_scale_shift)
                    )
                    checker_risk[offsets[t]:offsets[t + 1]] += raw_risk
        result_shift = 0 if risk_precision_lost else risk_scale_shift
        value = checker_vector_value(checker_risk, result_shift)
        if restore_internal and reusable and not scoring_timed_out:
            try:
                aggregate_risk(
                    (state_selected[name] for name in names),
                    until=deadline,
                    out=workspace,
                )
            except TimeoutError:
                return score_timeout()
        return value

    def schedule_value(state_selected: dict[str, int],
                       internal_risk: np.ndarray):
        if integer_checker_required or checker_authoritative_required:
            return checker_schedule_value(
                state_selected, internal_risk, restore_internal=True
            )
        return checker_vector_value(internal_risk)

    def aggregate_risk(
            selected_columns,
            *,
            until: float | None = None,
            out: np.ndarray | None = None,
    ) -> np.ndarray:
        """Accumulate each choice's active-period scenario pieces in source order."""
        if out is None:
            vector = np.zeros(
                total_scenarios,
                dtype=np.longdouble if risk_precision_lost else float,
            )
        else:
            vector = out
            vector.fill(0.0)
        for col_index, col in enumerate(selected_columns):
            if (until is not None and (col_index & 31) == 0
                    and time.monotonic() >= until):
                raise TimeoutError
            for piece_index, (t, risk) in enumerate(choice_risks[col]):
                if (until is not None and (piece_index & 255) == 0
                        and time.monotonic() >= until):
                    raise TimeoutError
                vector[offsets[t]:offsets[t + 1]] += risk
        return vector

    try:
        total_risk = aggregate_risk(
            (selected[name] for name in names), until=deadline - 0.05
        )
    except TimeoutError:
        if hard_finite_proven:
            return {name: choices[col][1] for name, col in selected.items()}
        raise TimeoutError("risk aggregation exhausted the budget")
    current = schedule_value(selected, total_risk)
    # Every accepted move checkpoints its independently reconstructed resources,
    # so finalization only needs a small control-flow reserve.
    validation_reserve = 0.05

    # A checker-overflowing incumbent cannot be improved through an infinity
    # plateau by strict local moves.  First minimize a conservative per-choice risk
    # magnitude.  Unlike bounded substitutions, this can move any number of jobs at
    # once and often finds a finite basin directly.
    if not math.isfinite(float(current)) and not scoring_timed_out:
        magnitude_scale = viable_max_abs_risk
        if magnitude_scale > 0.0:
            magnitude_cost = np.asarray([
                choice_max_abs_risks[col] / magnitude_scale
                for col in range(choice_count)
            ])
            magnitude_remaining = deadline - time.monotonic()
            magnitude_result = run_milp(
                magnitude_cost,
                np.ones(choice_count),
                Bounds(np.zeros(choice_count), choice_upper),
                LinearConstraint(model_base_matrix, model_lo, model_hi),
                min(3.0, max(0.05, 0.15 * magnitude_remaining)),
                1e-4,
                robust=small_base_coefficient_seen,
            )
            magnitude_extracted = extract(magnitude_result)
            if magnitude_extracted is not None:
                candidate_selected, candidate_activity = magnitude_extracted
                try:
                    candidate_risk = aggregate_risk(
                        (candidate_selected[name] for name in names),
                        until=deadline - 0.05,
                    )
                except TimeoutError:
                    scoring_timed_out = True
                else:
                    candidate_value = schedule_value(
                        candidate_selected, candidate_risk
                    )
                    if math.isfinite(float(candidate_value)):
                        selected, activity = candidate_selected, candidate_activity
                        total_risk, current = candidate_risk, candidate_value
        magnitude_cost = magnitude_result = magnitude_extracted = None

    # If magnitude minimization is inconclusive, ask for cyclically dispersed starts;
    # this cheaply samples different feasible basins while preserving every hard
    # resource and exclusion constraint.
    if not math.isfinite(float(current)) and not scoring_timed_out:
        spread_rng = random.Random((int(seed) << 1) ^ 0x5EED5EED)
        spread_order = list(names)
        for attempt in range(4):
            remaining = deadline - time.monotonic()
            if remaining <= 0.20:
                break
            if attempt:
                spread_rng.shuffle(spread_order)
            spread_rank = {
                name: index for index, name in enumerate(spread_order)
            }
            spread_cost = np.empty(choice_count)
            for col, (name, start) in enumerate(choices):
                preferred = 1 + (spread_rank[name] % horizon)
                spread_cost[col] = abs(start - preferred)
            spread_result = run_milp(
                spread_cost,
                np.ones(choice_count),
                Bounds(np.zeros(choice_count), choice_upper),
                LinearConstraint(model_base_matrix, model_lo, model_hi),
                min(1.0, max(0.05, 0.12 * remaining)),
                1e-3,
                robust=small_base_coefficient_seen,
            )
            spread_extracted = extract(spread_result)
            if spread_extracted is None:
                continue
            candidate_selected, candidate_activity = spread_extracted
            try:
                candidate_risk = aggregate_risk(
                    (candidate_selected[name] for name in names),
                    until=deadline - 0.05,
                )
            except TimeoutError:
                scoring_timed_out = True
                break
            candidate_value = schedule_value(
                candidate_selected, candidate_risk
            )
            if math.isfinite(float(candidate_value)):
                selected, activity = candidate_selected, candidate_activity
                total_risk, current = candidate_risk, candidate_value
                break

    if not math.isfinite(float(current)) and not scoring_timed_out:
        # Dispersion is only a heuristic.  Explicitly test feasible one-start
        # alternatives as well, allowing the first finite point to cross an
        # otherwise incomparable inf-to-inf objective plateau.
        finite_escape = None
        for name in names:
            if time.monotonic() >= deadline - 0.10:
                break
            old = selected[name]
            for col in by_job[name]:
                if time.monotonic() >= deadline - 0.10:
                    break
                if col == old:
                    continue
                candidate_selected = selected.copy()
                candidate_selected[name] = col
                candidate_activity = reconstruct_activity(candidate_selected)
                if (np.any(candidate_activity < lo - numerical_slack)
                        or np.any(candidate_activity > hi + numerical_slack)):
                    continue
                try:
                    candidate_risk = aggregate_risk(
                        (candidate_selected[job_name] for job_name in names),
                        until=deadline - 0.05,
                    )
                except TimeoutError:
                    scoring_timed_out = True
                    break
                candidate_value = schedule_value(
                    candidate_selected, candidate_risk
                )
                if math.isfinite(float(candidate_value)):
                    finite_escape = (
                        candidate_selected, candidate_activity,
                        candidate_risk, candidate_value,
                    )
                    break
                if scoring_timed_out:
                    break
            if finite_escape is not None or scoring_timed_out:
                break
        if finite_escape is not None:
            selected, activity, total_risk, current = finite_escape

    if not math.isfinite(float(current)) and not scoring_timed_out:
        # Some overflow plateaus require coordinated changes: every component move
        # remains infinite although the pair or triple cancels to a finite checker
        # value.  Search a tightly bounded product of the lowest-magnitude viable
        # alternatives before giving up on an otherwise hard-feasible instance.
        escape_names = [
            name for name in names
            if any(col != selected[name] for col in by_job[name])
        ]
        escape_names.sort(
            key=lambda name: choice_max_abs_risks[selected[name]], reverse=True
        )
        escape_names = escape_names[:24]
        escape_alternatives = {
            name: sorted(
                (col for col in by_job[name] if col != selected[name]),
                key=lambda col: (choice_max_abs_risks[col], choices[col][1]),
            )[:4]
            for name in escape_names
        }
        attempt_limit = max(
            8, min(256, 2_000_000 // max(1, total_scenarios))
        )
        attempts = 0
        coordinated_escape = None
        for move_count in (2, 3):
            for changed_names in itertools.combinations(escape_names, move_count):
                alternatives = [escape_alternatives[name] for name in changed_names]
                for changed_columns in itertools.product(*alternatives):
                    if attempts >= attempt_limit or time.monotonic() >= deadline - 0.05:
                        break
                    attempts += 1
                    candidate_selected = selected.copy()
                    candidate_selected.update(zip(changed_names, changed_columns))
                    candidate_activity = reconstruct_activity(candidate_selected)
                    if (np.any(candidate_activity < lo - numerical_slack)
                            or np.any(candidate_activity > hi + numerical_slack)):
                        continue
                    try:
                        candidate_risk = aggregate_risk(
                            (candidate_selected[name] for name in names),
                            until=deadline - 0.05,
                        )
                    except TimeoutError:
                        scoring_timed_out = True
                        break
                    candidate_value = schedule_value(
                        candidate_selected, candidate_risk
                    )
                    if math.isfinite(float(candidate_value)):
                        coordinated_escape = (
                            candidate_selected, candidate_activity,
                            candidate_risk, candidate_value,
                        )
                        break
                    if scoring_timed_out:
                        break
                if (coordinated_escape is not None or scoring_timed_out
                        or attempts >= attempt_limit
                        or time.monotonic() >= deadline - 0.05):
                    break
            if (coordinated_escape is not None or scoring_timed_out
                    or attempts >= attempt_limit
                    or time.monotonic() >= deadline - 0.05):
                break
        if coordinated_escape is not None:
            selected, activity, total_risk, current = coordinated_escape

    validated_selected: dict[str, int] | None = None
    validated_value = math.inf

    def retain_validated(state_selected: dict[str, int],
                         state_activity: np.ndarray, value) -> bool:
        """Checkpoint a fully scored, checker-feasible schedule."""
        nonlocal validated_selected, validated_value
        finite_value = math.isfinite(float(value))
        feasible = (
            finite_value
            and not np.any(state_activity < lo - numerical_slack)
            and not np.any(state_activity > hi + numerical_slack)
        )
        if not feasible:
            return False
        if validated_selected is None or value < validated_value:
            validated_selected = state_selected.copy()
            validated_value = value
        return True

    def validated_output() -> dict[str, int]:
        if validated_selected is None:
            if scoring_timed_out and hard_finite_proven:
                # The selected-choice magnitude bound proves every official
                # aggregation and horizon reduction finite even though optional
                # exact scoring exhausted its polling deadline.
                return {
                    name: choices[hard_feasible_selected[name]][1]
                    for name in names
                }
            raise RuntimeError("no finite-objective incumbent")
        return {
            name: choices[validated_selected[name]][1]
            for name in names
        }

    retain_validated(selected, activity, current)
    if minimum_risk >= 0.0 and current == 0.0:
        # Both objective components are nonnegative, so a checker-validated zero
        # is a representation-independent global certificate.
        return validated_output()
    if not refine:
        return validated_output()

    # Keep the genuinely different MILP incumbents.  A surrogate winner can be
    # worse before local search yet lead to a better exact-objective basin.
    elites: list[tuple[str, dict[str, int], np.ndarray, np.ndarray, float]] = []
    elite_signatures: set[tuple[int, ...]] = set()

    def remember_elite(label: str, elite_selected: dict[str, int],
                       elite_activity: np.ndarray, elite_risk: np.ndarray,
                       elite_value: float) -> None:
        if not retain_validated(elite_selected, elite_activity, elite_value):
            return
        signature = tuple(elite_selected[name] for name in names)
        if signature in elite_signatures:
            return
        elite_signatures.add(signature)
        retained_value = (
            np.longdouble(elite_value) if objective_longdouble
            else float(elite_value)
        )
        elites.append((label, elite_selected.copy(), elite_activity.copy(),
                       elite_risk.copy(), retained_value))

    remember_elite("mean", selected, activity, total_risk, current)

    # D[t,s,c] is each choice's scenario risk minus its period mean.  For a
    # fixed schedule, the excess is max(0, the kth-smallest row of D x).
    # The selector formulation below adds one binary per scenario, whereas the
    # all-scenario order statistic (Quantile 1, plus the checker's Quantile 0
    # edge case) is only a continuous epigraph.  Keep the conservative selector
    # cap, but do not needlessly exclude larger scenario sets from that much
    # smaller exact model.  The common risk-entry cap bounds sparse nonzeros and
    # Python triplet memory independently of the number of empty matrix rows.
    selector_scale_ok = (
        total_scenarios <= 50_000
        and choice_count + total_scenarios <= 100_000
    )
    epigraph_scale_ok = (
        all_scenarios_selected
        and total_scenarios <= 250_000
        and choice_count + total_scenarios <= 350_000
    )
    exact_preprocess_remaining = deadline - time.monotonic()
    big_m_preprocess_work = (
        risk_entry_count + len(names) * (horizon + total_scenarios)
    )
    big_m_work_budget = min(
        20_000_000,
        max(0, int((exact_preprocess_remaining - 2.0) * 2_000_000)),
    )
    selector_exact_eligible = (
        selector_scale_ok
        and risk_entry_count <= 2_000_000
        # job_max and active_counts are dense per intervention even when risks
        # are sparse.  Gate their true preprocessing width as well as nonzeros.
        and big_m_preprocess_work <= big_m_work_budget
    )
    # At the endpoint order statistic every scenario is constrained directly;
    # no selector binaries or per-job big-M scan is needed.  Keep a tighter
    # triplet cap because the Python COO staging lists are comparatively large.
    epigraph_exact_eligible = (
        epigraph_scale_ok and risk_entry_count <= 750_000
    )
    use_epigraph_exact = all_scenarios_selected and epigraph_exact_eligible
    use_selector_exact = (
        not all_scenarios_selected and selector_exact_eligible
    )
    exact_eligible = (
        not risk_precision_lost
        and not integer_checker_required
        and not checker_rescore_required
        # Scaling itself is exact, but a large scaled-risk MILP can consume the
        # local search budget for no gain; retain exact refinement for compact
        # scaled models where it fixes the mean surrogate's quantile blind spot.
        and (risk_scale == 1.0 or risk_entry_count <= 100_000)
        and 1.0 - alpha > 1e-12
        and (use_selector_exact or use_epigraph_exact)
        # Sparse triplet construction is not sensible when less than two
        # seconds remain.  Preserve the feasible incumbent instead.
        and exact_preprocess_remaining > 2.0
    )
    deviation_matrix = None
    big_m = None
    if exact_eligible:
        d_rows: list[int] = []
        d_cols: list[int] = []
        d_values: list[float] = []
        build_big_m = use_selector_exact
        big_m = np.zeros(total_scenarios) if build_big_m else None
        for name in names:
            if time.monotonic() >= deadline - 0.25:
                return validated_output()
            if build_big_m:
                # Zero is available only when some start is inactive in the
                # period; otherwise retain a negative active-choice maximum.
                active_counts = np.zeros(horizon, dtype=int)
                for col in by_job[name]:
                    for t, _ in choice_risks[col]:
                        active_counts[t] += 1
                job_max = np.zeros(total_scenarios)
                for t in np.flatnonzero(active_counts == len(by_job[name])):
                    job_max[offsets[t]:offsets[t + 1]] = -np.inf
            for col in by_job[name]:
                if time.monotonic() >= deadline - 0.25:
                    return validated_output()
                for t, risk in choice_risks[col]:
                    if time.monotonic() >= deadline - 0.25:
                        return validated_output()
                    deviation = risk - safe_mean(risk)
                    if build_big_m:
                        sl = slice(offsets[t], offsets[t + 1])
                        np.maximum(job_max[sl], deviation, out=job_max[sl])
                    nz = np.flatnonzero(deviation)
                    d_rows.extend((offsets[t] + nz).tolist())
                    d_cols.extend([col] * len(nz))
                    d_values.extend(deviation[nz].tolist())
            if build_big_m:
                big_m += job_max
        if time.monotonic() >= deadline - 0.25:
            return validated_output()
        deviation_matrix = coo_matrix(
            (d_values, (d_rows, d_cols)), shape=(total_scenarios, choice_count)
        ).tocsc()
        del d_rows, d_cols, d_values
        if time.monotonic() >= deadline - 0.25:
            return validated_output()
        if build_big_m:
            # Componentwise D(x) <= U implies kth(D(x)) <= kth(U).
            exact_excess_upper = np.asarray([
                max(0.0, float(np.partition(
                    big_m[offsets[t]:offsets[t + 1]],
                    kth_indices[t],
                )[kth_indices[t]]))
                for t in range(horizon)
            ])
        else:
            # Endpoint epigraph variables need no finite big-M upper bound.
            exact_excess_upper = np.full(horizon, np.inf)

        # First optimize a tight upper model using the currently lowest k
        # scenarios.  It matches the exact objective at the incumbent and any
        # solution it improves is guaranteed to improve the real objective.
        remaining = deadline - time.monotonic()
        if remaining > 2.0:
            selected_rows = []
            selected_periods = []
            fixed_excess_upper = []
            for t in range(horizon):
                risks = total_risk[offsets[t]:offsets[t + 1]]
                k = int(selected_counts[t])
                local = np.argpartition(risks, k - 1)[:k]
                global_rows = offsets[t] + local
                selected_rows.extend(global_rows.tolist())
                selected_periods.extend([t] * k)
                # Selector models use a finite maximum; endpoint epigraphs do
                # not require an artificial upper bound on the auxiliary value.
                fixed_excess_upper.append(
                    max(0.0, float(np.max(big_m[global_rows])))
                    if build_big_m else np.inf
                )
            selected_rows_array = np.asarray(selected_rows, dtype=int)
            fixed_d = deviation_matrix[selected_rows_array, :]
            y_part = coo_matrix(
                (-np.ones(len(selected_rows)),
                 (np.arange(len(selected_rows)), np.asarray(selected_periods))),
                shape=(len(selected_rows), horizon),
            ).tocsc()
            fixed_matrix = vstack([
                hstack([
                    model_base_matrix,
                    coo_matrix((model_base_matrix.shape[0], horizon)),
                ]),
                hstack([fixed_d, y_part]),
            ]).tocsc()
            fixed_lo = np.r_[model_lo, np.full(len(selected_rows), -np.inf)]
            fixed_hi = np.r_[model_hi, np.zeros(len(selected_rows))]
            fixed_cost = np.r_[alpha * mean_costs_array,
                               np.full(horizon, (1.0 - alpha) / horizon)]
            fixed_remaining = deadline - time.monotonic()
            if fixed_remaining <= 0.25:
                return validated_output()
            fixed_result = run_milp(
                fixed_cost,
                np.r_[np.ones(choice_count), np.zeros(horizon)],
                Bounds(np.r_[np.zeros(choice_count + horizon)],
                       np.r_[choice_upper, fixed_excess_upper]),
                LinearConstraint(fixed_matrix, fixed_lo, fixed_hi),
                min(8.0, max(0.05, fixed_remaining * 0.20)),
                1e-5,
            )
            candidate = extract(fixed_result)
            if candidate is not None:
                candidate_selected, candidate_activity = candidate
                try:
                    candidate_risk = aggregate_risk(
                        (candidate_selected[name] for name in names),
                        until=deadline - 0.05,
                    )
                except TimeoutError:
                    return validated_output()
                candidate_value = schedule_value(
                    candidate_selected, candidate_risk
                )
                remember_elite("fixed", candidate_selected, candidate_activity,
                               candidate_risk, candidate_value)
                if candidate_value < current:
                    selected, activity = candidate_selected, candidate_activity
                    total_risk, current = candidate_risk, candidate_value

            # When every scenario is selected, this epigraph is already the exact
            # max-deviation model.  Re-solve it with an incumbent cutoff rather
            # than building equivalent scenario binaries that presolve to one.
            all_scenario_reserve = min(10.0, max(1.5, 0.20 * seconds))
            all_remaining = deadline - time.monotonic()
            if (all_scenarios_selected
                    and all_remaining > all_scenario_reserve + 0.05):
                cutoff_matrix = vstack([
                    fixed_matrix, coo_matrix(fixed_cost.reshape(1, -1))
                ]).tocsc()
                cutoff_lo = np.r_[fixed_lo, -np.inf]
                cutoff_hi = np.r_[
                    fixed_hi,
                    current + 1e-8 * max(objective_unit, abs(current))
                ]
                # Sparse stacking above consumes part of the exact allowance;
                # recompute it so the reserved local-search slice remains intact.
                all_remaining = deadline - time.monotonic()
                all_result = run_milp(
                    fixed_cost,
                    np.r_[np.ones(choice_count), np.zeros(horizon)],
                    Bounds(np.r_[np.zeros(choice_count + horizon)],
                           np.r_[choice_upper, fixed_excess_upper]),
                    LinearConstraint(cutoff_matrix, cutoff_lo, cutoff_hi),
                    min(30.0, max(0.0, all_remaining - all_scenario_reserve)),
                    1e-7,
                )
                candidate = extract(all_result)
                if candidate is not None:
                    candidate_selected, candidate_activity = candidate
                    try:
                        candidate_risk = aggregate_risk(
                            (candidate_selected[name] for name in names),
                            until=deadline - 0.05,
                        )
                    except TimeoutError:
                        return validated_output()
                    candidate_value = schedule_value(
                        candidate_selected, candidate_risk
                    )
                    remember_elite(
                        "all-scenario", candidate_selected, candidate_activity,
                        candidate_risk, candidate_value
                    )
                    if candidate_value < current:
                        selected, activity = candidate_selected, candidate_activity
                        total_risk, current = candidate_risk, candidate_value
                del cutoff_matrix, cutoff_lo, cutoff_hi, all_result
            # These sparse model blocks are not used by the exact model or local
            # search; release them before allocating another model.
            del (selected_rows, selected_periods, fixed_excess_upper,
                 selected_rows_array, fixed_d, y_part, fixed_matrix,
                 fixed_lo, fixed_hi, fixed_cost, fixed_result, candidate)

        # Globally exact model: choose k scenarios per period, and constrain y
        # above their deviations.  Minimizing y chooses the k smallest.
        remaining = deadline - time.monotonic()
        exact_solve_reserve = min(10.0, max(1.5, 0.20 * seconds))
        # Under the eligibility caps, two seconds is a conservative allowance
        # for the sparse hstack/vstack copies.  Do not assemble a model when no
        # useful HiGHS allowance can remain afterwards.
        exact_assembly_reserve = 2.0
        if (not all_scenarios_selected
                and remaining > exact_solve_reserve + exact_assembly_reserve):
            period_of_scenario = np.repeat(np.arange(horizon), scenario_counts)
            y_part = coo_matrix(
                (-np.ones(total_scenarios),
                 (np.arange(total_scenarios), period_of_scenario)),
                shape=(total_scenarios, horizon),
            ).tocsc()
            z_sum = coo_matrix(
                (np.ones(total_scenarios),
                 (period_of_scenario, np.arange(total_scenarios))),
                shape=(horizon, total_scenarios),
            ).tocsc()
            dev_block = hstack([deviation_matrix, y_part, diags(big_m)]).tocsc()
            if time.monotonic() >= deadline - 0.25:
                return validated_output()
            base_block = hstack([
                model_base_matrix,
                coo_matrix((
                    model_base_matrix.shape[0], horizon + total_scenarios
                )),
            ]).tocsc()
            if time.monotonic() >= deadline - 0.25:
                return validated_output()
            z_block = hstack([
                coo_matrix((horizon, choice_count + horizon)), z_sum
            ]).tocsc()
            if time.monotonic() >= deadline - 0.25:
                return validated_output()
            exact_matrix = vstack([base_block, z_block, dev_block]).tocsc()
            if time.monotonic() >= deadline - 0.25:
                return validated_output()
            exact_lo = np.r_[model_lo, selected_counts,
                             np.full(total_scenarios, -np.inf)]
            exact_hi = np.r_[model_hi, selected_counts, big_m]
            exact_cost = np.r_[
                alpha * mean_costs_array,
                np.full(horizon, (1.0 - alpha) / horizon),
                np.zeros(total_scenarios),
            ]
            exact_integrality = np.r_[
                np.ones(choice_count), np.zeros(horizon), np.ones(total_scenarios)
            ]
            exact_bounds = Bounds(
                np.zeros(choice_count + horizon + total_scenarios),
                np.r_[choice_upper, exact_excess_upper,
                      np.ones(total_scenarios)],
            )
            exact_remaining = deadline - time.monotonic()
            exact_result = run_milp(
                exact_cost,
                exact_integrality,
                exact_bounds,
                LinearConstraint(exact_matrix, exact_lo, exact_hi),
                min(30.0, max(0.0, exact_remaining - exact_solve_reserve)),
                1e-7,
            )
            candidate = extract(exact_result)
            if candidate is not None:
                candidate_selected, candidate_activity = candidate
                try:
                    candidate_risk = aggregate_risk(
                        (candidate_selected[name] for name in names),
                        until=deadline - 0.05,
                    )
                except TimeoutError:
                    return validated_output()
                candidate_value = schedule_value(
                    candidate_selected, candidate_risk
                )
                remember_elite("exact", candidate_selected, candidate_activity,
                               candidate_risk, candidate_value)
                # Retain every measured improvement; checker-order arithmetic
                # can distinguish candidates that the model objective ties.
                if candidate_value < current:
                    selected, activity = candidate_selected, candidate_activity
                    total_risk, current = candidate_risk, candidate_value
            del (period_of_scenario, y_part, z_sum, dev_block, base_block,
                 z_block, exact_matrix, exact_lo, exact_hi, exact_cost,
                 exact_integrality, exact_bounds, exact_result, candidate)

    # MILP-only matrices are dead before the dense local-search cache.  Release
    # them before potentially materializing base_matrix as a dense array.
    deviation_matrix = None
    big_m = None
    model_base_matrix = None
    model_row_scales = model_lo = model_hi = None

    # Incremental exact-objective local search.  Candidate moves touch only the
    # periods and sparse feasibility rows covered by their old/new starts.  A
    # dense column cache accelerates broad instances when it is inexpensive,
    # but none of the core neighborhoods depends on it for correctness.
    if time.monotonic() >= deadline - 0.05:
        return validated_output()
    dense_columns = None
    if base_matrix.shape[0] * choice_count <= 8_000_000:
        try:
            dense_columns = base_matrix.toarray()
        except (MemoryError, ValueError):
            dense_columns = None
    if time.monotonic() >= deadline - 0.05:
        return validated_output()

    choice_period_risks: list[dict[int, np.ndarray]] = []
    choice_period_means: list[dict[int, float]] = []
    choice_periods: list[tuple[int, ...]] = []
    # Store one scalar mean per active choice-period rather than a second copy
    # of every scenario-risk vector.  Poll while building the cache so optional
    # local-search setup can never suppress an already validated MILP incumbent.
    for col, pieces in enumerate(choice_risks):
        if ((col & 63) == 0 and time.monotonic() >= deadline - 0.05):
            return validated_output()
        period_risks = dict(pieces)
        period_means: dict[int, float] = {}
        for piece_index, (t, risk) in enumerate(pieces):
            if ((piece_index & 63) == 0
                    and time.monotonic() >= deadline - 0.05):
                return validated_output()
            period_means[t] = safe_mean(risk)
        choice_period_risks.append(period_risks)
        choice_period_means.append(period_means)
        choice_periods.append(tuple(period_risks))
    start_col = {(name, start): col for col, (name, start) in enumerate(choices)}
    if time.monotonic() >= deadline - 0.05:
        return validated_output()

    # Caches are deliberately bounded and are reset between elite basins.  On a
    # large sparse model, checking only the union of changed rows is much cheaper
    # than materializing and scanning a complete constraint vector per move.
    replacement_period_cache: dict[tuple[int, int], tuple[int, ...]] = {}
    replacement_activity_cache: dict[
        tuple[int, int], tuple[np.ndarray, np.ndarray]
    ] = {}
    period_cache_limit = 8_192
    period_cache_max_width = 512
    activity_cache_limit = max(4_096, min(40_000, 4 * choice_count))
    activity_cache_byte_limit = 32 * 1024 * 1024
    activity_cache_bytes = 0

    def replacement_periods(old: int, new: int) -> tuple[int, ...]:
        key = (old, new)
        cached = replacement_period_cache.get(key)
        if cached is None:
            cached = tuple(sorted(
                set(choice_periods[old]).union(choice_periods[new])
            ))
            if len(cached) <= period_cache_max_width:
                if len(replacement_period_cache) >= period_cache_limit:
                    replacement_period_cache.clear()
                replacement_period_cache[key] = cached
        return cached

    def replacement_activity_delta(
            old: int, new: int) -> tuple[np.ndarray, np.ndarray]:
        nonlocal activity_cache_bytes
        key = (old, new)
        cached = replacement_activity_cache.get(key)
        if cached is not None:
            return cached
        old_begin, old_end = base_matrix.indptr[old:old + 2]
        new_begin, new_end = base_matrix.indptr[new:new + 2]
        old_rows = base_matrix.indices[old_begin:old_end]
        new_rows = base_matrix.indices[new_begin:new_end]
        changed_rows = np.union1d(old_rows, new_rows)
        changed_values = np.zeros(changed_rows.size, dtype=float)
        if old_rows.size:
            changed_values[np.searchsorted(changed_rows, old_rows)] -= (
                base_matrix.data[old_begin:old_end]
            )
        if new_rows.size:
            changed_values[np.searchsorted(changed_rows, new_rows)] += (
                base_matrix.data[new_begin:new_end]
            )
        nonzero = changed_values != 0.0
        result = (changed_rows[nonzero], changed_values[nonzero])
        entry_bytes = result[0].nbytes + result[1].nbytes
        # Do not replicate a very wide selected column once per alternative.
        # Such deltas remain usable for the current candidate but are not retained.
        if entry_bytes <= activity_cache_byte_limit // 8:
            if (len(replacement_activity_cache) >= activity_cache_limit
                    or activity_cache_bytes + entry_bytes
                    > activity_cache_byte_limit):
                replacement_activity_cache.clear()
                activity_cache_bytes = 0
            replacement_activity_cache[key] = result
            activity_cache_bytes += entry_bytes
        return result

    def combined_activity_delta(
            replacements: list[tuple[int, int]]) -> tuple[np.ndarray, np.ndarray]:
        if len(replacements) == 1:
            return replacement_activity_delta(*replacements[0])
        pieces = [replacement_activity_delta(old, new)
                  for old, new in replacements]
        nonempty = [piece for piece in pieces if piece[0].size]
        if not nonempty:
            return np.empty(0, dtype=np.int32), np.empty(0, dtype=float)
        all_rows = np.concatenate([piece[0] for piece in nonempty])
        changed_rows, inverse = np.unique(all_rows, return_inverse=True)
        changed_values = np.zeros(changed_rows.size, dtype=float)
        cursor = 0
        for rows_piece, values_piece in nonempty:
            count = rows_piece.size
            np.add.at(changed_values, inverse[cursor:cursor + count], values_piece)
            cursor += count
        nonzero = changed_values != 0.0
        return changed_rows[nonzero], changed_values[nonzero]

    def authoritative_activity_change(
            replacements: list[tuple[int, int]]) -> np.ndarray | None:
        """Rebuild a candidate in checker column order and test its bounds."""
        replacement_by_old = dict(replacements)
        candidate_selected = {
            name: replacement_by_old.get(selected[name], selected[name])
            for name in names
        }
        candidate_activity = reconstruct_activity(candidate_selected)
        if (np.any(candidate_activity < lo - numerical_slack)
                or np.any(candidate_activity > hi + numerical_slack)):
            return None
        return candidate_activity

    def feasible_activity_change(
            replacements: list[tuple[int, int]],
            dense_base_activity: np.ndarray | None = None,
    ) -> np.ndarray | tuple[np.ndarray, np.ndarray] | None:
        # Dense vector arithmetic remains faster on compact models.  A one-move
        # scan can reuse activity-old once for every alternative of the same job.
        if dense_columns is not None:
            if dense_base_activity is not None and len(replacements) == 1:
                candidate_activity = (
                    dense_base_activity + dense_columns[:, replacements[0][1]]
                )
            else:
                candidate_activity = activity.copy()
                for old, new in replacements:
                    candidate_activity -= dense_columns[:, old]
                    candidate_activity += dense_columns[:, new]
            candidate_lo = lo - numerical_slack
            candidate_hi = hi + numerical_slack
            low_violation = candidate_lo - candidate_activity
            high_violation = candidate_activity - candidate_hi
            invalid = ((low_violation > 0.0) | (high_violation > 0.0))
            if np.any(invalid):
                finite_bounds = np.maximum(
                    np.where(np.isfinite(candidate_lo), np.abs(candidate_lo), 0.0),
                    np.where(np.isfinite(candidate_hi), np.abs(candidate_hi), 0.0),
                )
                scale = np.maximum(np.abs(candidate_activity), finite_bounds)
                violation = np.maximum(low_violation, high_violation)
                borderline = (
                    np.isfinite(violation)
                    & (violation <= 8.0 * np.spacing(scale))
                )
                if not np.any(invalid & borderline):
                    return None
                candidate_activity = authoritative_activity_change(replacements)
                if candidate_activity is None:
                    return None
            return candidate_activity
        changed_rows, changed_values = combined_activity_delta(replacements)
        if changed_rows.size == 0:
            return changed_rows, changed_values
        changed_activity = activity[changed_rows] + changed_values
        changed_lo = lo[changed_rows] - numerical_slack
        changed_hi = hi[changed_rows] + numerical_slack
        low_violation = changed_lo - changed_activity
        high_violation = changed_activity - changed_hi
        invalid = ((low_violation > 0.0) | (high_violation > 0.0))
        if np.any(invalid):
            # Sparse delta regrouping can differ by an ULP from the checker's
            # fresh column-ordered sum.  Reconstruct only borderline rejections;
            # clear violations remain cheap in the compensating-pair scans.
            finite_bounds = np.maximum(
                np.where(np.isfinite(changed_lo), np.abs(changed_lo), 0.0),
                np.where(np.isfinite(changed_hi), np.abs(changed_hi), 0.0),
            )
            scale = np.maximum.reduce((
                np.abs(activity[changed_rows]), np.abs(changed_values),
                finite_bounds,
            ))
            rounding_guard = 8.0 * np.spacing(scale)
            violation = np.maximum(low_violation, high_violation)
            borderline = (
                np.isfinite(violation) & (violation <= rounding_guard)
            )
            if not np.any(invalid & borderline):
                return None
            candidate_activity = authoritative_activity_change(replacements)
            if candidate_activity is None:
                return None
            return candidate_activity
        return changed_rows, changed_values

    def build_period_state(vector: np.ndarray, *, until: float | None = None):
        deviations = []
        excesses = []
        for t in range(horizon):
            if (until is not None and (t & 63) == 0
                    and time.monotonic() >= until):
                raise TimeoutError
            period_slice = slice(offsets[t], offsets[t + 1])
            deviation = vector[period_slice].copy()
            period_mean = safe_mean(deviation)
            deviation -= period_mean
            deviation.partition(kth_indices[t])
            excesses.append(positive_retained(deviation[kth_indices[t]]))
            # Local deltas require original scenario order.  Rebuild that order
            # from the aggregate after the in-place selection instead of keeping
            # a second full-period partition copy alive.
            np.subtract(vector[period_slice], period_mean, out=deviation)
            deviations.append(deviation)
        return deviations, np.asarray(
            excesses,
            dtype=np.longdouble if risk_precision_lost else float,
        )

    try:
        period_deviations, period_excesses = build_period_state(
            total_risk, until=deadline - 0.05
        )
    except TimeoutError:
        return validated_output()

    def affected_periods(replacements: list[tuple[int, int]]) -> tuple[int, ...]:
        if len(replacements) == 1:
            return replacement_periods(*replacements[0])
        affected: set[int] = set()
        for old, new in replacements:
            affected.update(replacement_periods(old, new))
        return tuple(sorted(affected))

    def source_order_replacement_value(
            replacements: list[tuple[int, int]]):
        """Score a candidate from a fresh intervention-order aggregate."""
        replacement_by_old = dict(replacements)
        candidate_selected = {
            name: replacement_by_old.get(selected[name], selected[name])
            for name in names
        }
        try:
            candidate_risk = aggregate_risk(
                (candidate_selected[name] for name in names),
                until=deadline - 0.05,
            )
        except TimeoutError:
            return score_timeout()
        return schedule_value(candidate_selected, candidate_risk)

    def evaluate_replacements(replacements: list[tuple[int, int]]):
        """Evaluate column changes from mean deltas and affected deviations."""
        if checker_rescore_required:
            replacement_by_old = dict(replacements)
            candidate_selected = {
                name: replacement_by_old.get(selected[name], selected[name])
                for name in names
            }
            return checker_schedule_value(candidate_selected)
        mean_delta = sum((
            local_mean_costs_array[new] - local_mean_costs_array[old]
            for old, new in replacements
        ), objective_zero)
        excess_delta = objective_zero
        for t in affected_periods(replacements):
            deviation = period_deviations[t].copy()
            for old, new in replacements:
                old_risk = choice_period_risks[old].get(t)
                if old_risk is not None:
                    deviation -= old_risk
                    deviation += choice_period_means[old][t]
                new_risk = choice_period_risks[new].get(t)
                if new_risk is not None:
                    deviation += new_risk
                    deviation -= choice_period_means[new][t]
            # This array is disposable.  Partitioning it in place avoids the
            # second full scenario-vector copy made by np.partition().
            deviation.partition(kth_indices[t])
            excess = positive_retained(deviation[kth_indices[t]])
            excess_delta += excess - period_excesses[t]
        if objective_longdouble:
            value = (
                current + np.longdouble(alpha) * np.longdouble(mean_delta)
                + np.longdouble(1.0 - alpha)
                * np.longdouble(excess_delta) / horizon
            )
        else:
            value = (current + alpha * mean_delta
                     + (1.0 - alpha) * excess_delta / horizon)
            value = float(value)
        if value <= current + checker_rounding_guard:
            # Approximate deltas are a ranking filter only near the incumbent.
            # Rebuild in intervention order so every accepted normal-scale move
            # has the same aggregation and reduction order as the checker.
            return source_order_replacement_value(replacements)
        return value

    def apply_move(
            columns: list[tuple[str, int]], replacements: list[tuple[int, int]],
            candidate_activity: np.ndarray | tuple[np.ndarray, np.ndarray],
            value: float) -> bool:
        nonlocal activity, current, total_risk
        nonlocal period_deviations, period_excesses
        checkpoint_activity = None
        if value < validated_value:
            candidate_selected = selected.copy()
            candidate_selected.update(columns)
            checkpoint_activity = reconstruct_activity(candidate_selected)
            if (np.any(checkpoint_activity < lo - numerical_slack)
                    or np.any(checkpoint_activity > hi + numerical_slack)):
                return False
        selected.update(columns)
        if checkpoint_activity is not None:
            activity = checkpoint_activity
        elif isinstance(candidate_activity, tuple):
            changed_rows, changed_values = candidate_activity
            activity[changed_rows] += changed_values
        else:
            activity = candidate_activity

        # Every accepted value passed a fresh source-order objective score.  Check
        # resources before optional cache rebuilding so a deadline cannot suppress
        # a new globally best incumbent.  Borderline feasibility paths already use
        # authoritative reconstruction above; keep cheap deltas inside worse elite
        # basins where no output checkpoint can be promoted.
        if checkpoint_activity is not None:
            retain_validated(selected, activity, value)
        current = value
        if time.monotonic() >= deadline - 0.05:
            return True

        if checker_rescore_required:
            # The accepted schedule is already checkpointed.  Release the old
            # deviation cache and reuse its aggregate buffer before constructing
            # the new cache, avoiding simultaneous complete old/new risk states.
            period_deviations = []
            period_excesses = np.empty(
                0, dtype=np.longdouble if risk_precision_lost else float
            )
            try:
                total_risk = aggregate_risk(
                    (selected[name] for name in names),
                    until=deadline - 0.05,
                    out=total_risk,
                )
                period_deviations, period_excesses = build_period_state(
                    total_risk, until=deadline - 0.05
                )
            except TimeoutError:
                return True
        else:
            for t in affected_periods(replacements):
                if time.monotonic() >= deadline - 0.05:
                    return True
                sl = slice(offsets[t], offsets[t + 1])
                risks = total_risk[sl]
                risks.fill(0.0)
                # Rebuild changed periods in intervention order.  This prevents
                # subtract/add drift from invalidating later near-tie comparisons.
                for name_index, name in enumerate(names):
                    if ((name_index & 31) == 0
                            and time.monotonic() >= deadline - 0.05):
                        return True
                    chosen_risk = choice_period_risks[selected[name]].get(t)
                    if chosen_risk is not None:
                        risks += chosen_risk
                deviation = risks - safe_mean(risks)
                period_deviations[t] = deviation
                period_excesses[t] = positive_retained(
                    np.partition(deviation, kth_indices[t])[kth_indices[t]]
                )
        return True

    def steepest_one(until: float, max_passes: int = 20) -> None:
        """Apply each job's steepest feasible one-start move in scan order."""
        for pass_number in range(max_passes):
            changed = False
            order = names if pass_number % 2 == 0 else reversed(names)
            for name in order:
                old = selected[name]
                dense_base_activity = (
                    activity - dense_columns[:, old]
                    if dense_columns is not None else None
                )
                best = None
                interrupted = False
                for col in by_job[name]:
                    if time.monotonic() >= until:
                        interrupted = True
                        break
                    if col == old:
                        continue
                    replacements = [(old, col)]
                    candidate_change = feasible_activity_change(
                        replacements, dense_base_activity
                    )
                    if candidate_change is None:
                        continue
                    value = evaluate_replacements(replacements)
                    if (value < current
                            and (best is None or value < best[0])):
                        best = (value, col, candidate_change)
                    if time.monotonic() >= until:
                        interrupted = True
                        break
                if best is not None:
                    value, col, candidate_change = best
                    replacements = [(old, col)]
                    changed = apply_move(
                        [(name, col)], replacements, candidate_change, value
                    ) or changed
                if interrupted:
                    return
            if not changed:
                return

    def improving_start_swaps(until: float, max_passes: int = 3) -> None:
        """Quickly apply improving exchanges while scanning the neighborhood."""
        for _ in range(max_passes):
            changed = False
            for i, first in enumerate(names):
                old_first = selected[first]
                first_start = choices[old_first][1]
                for second in names[i + 1:]:
                    if time.monotonic() >= until:
                        return
                    old_second = selected[second]
                    second_start = choices[old_second][1]
                    new_first = start_col.get((first, second_start))
                    new_second = start_col.get((second, first_start))
                    if (new_first is None or new_second is None
                            or (new_first == old_first and new_second == old_second)):
                        continue
                    replacements = [
                        (old_first, new_first), (old_second, new_second)
                    ]
                    candidate_change = feasible_activity_change(replacements)
                    if candidate_change is None:
                        continue
                    value = evaluate_replacements(replacements)
                    if value < current:
                        committed = apply_move(
                            [(first, new_first), (second, new_second)],
                            replacements, candidate_change, value,
                        )
                        if committed:
                            changed = True
                            old_first = new_first
                            first_start = choices[old_first][1]
                    if time.monotonic() >= until:
                        return
            if not changed:
                return

    def steepest_start_swaps(until: float, max_passes: int = 12) -> None:
        """Use the best current-start exchange for each first job in turn."""
        for _ in range(max_passes):
            changed = False
            for i, first in enumerate(names):
                best = None
                interrupted = False
                old_first = selected[first]
                first_start = choices[old_first][1]
                for second in names[i + 1:]:
                    if time.monotonic() >= until:
                        interrupted = True
                        break
                    old_second = selected[second]
                    second_start = choices[old_second][1]
                    new_first = start_col.get((first, second_start))
                    new_second = start_col.get((second, first_start))
                    if (new_first is None or new_second is None
                            or (new_first == old_first and new_second == old_second)):
                        continue
                    replacements = [
                        (old_first, new_first), (old_second, new_second)
                    ]
                    candidate_change = feasible_activity_change(replacements)
                    if candidate_change is None:
                        continue
                    value = evaluate_replacements(replacements)
                    if (value < current
                            and (best is None or value < best[0])):
                        best = (value, old_first, new_first, second,
                                old_second, new_second, candidate_change)
                    if time.monotonic() >= until:
                        interrupted = True
                        break
                if best is not None:
                    (value, old_first, new_first, second, old_second,
                     new_second, candidate_activity) = best
                    replacements = [
                        (old_first, new_first), (old_second, new_second)
                    ]
                    committed = apply_move(
                        [(first, new_first), (second, new_second)],
                        replacements, candidate_activity, value,
                    )
                    changed = committed or changed
                if interrupted or time.monotonic() >= until:
                    return
            if not changed:
                return

    def sparse_compensating_pairs(until: float, max_passes: int = 8) -> None:
        """Find feasibility-compensating pairs without a dense constraint matrix.

        Alternative moves are indexed only on rows that some one-job move
        violates.  A violated-row intersection then exposes the few moves that
        can restore every crossed bound.  This preserves the useful ejection
        neighborhood on broad sparse instances where an R-by-C dense cache is
        unsafe.
        """
        max_indexed_moves = 80_000
        max_delta_entries = 1_200_000
        max_needed_rows = 20_000

        def alternatives_for(name: str, old: int, limit: int) -> list[int]:
            columns_for_job = by_job[name]
            alternative_count = len(columns_for_job) - 1
            if alternative_count <= limit:
                return [col for col in columns_for_job if col != old]
            # Blend objective-promising, nearby, and horizon-spanning starts.
            # Scan objective candidates with a bounded heap so a flexible job
            # never allocates and sorts its entire alternative domain.
            chosen: list[int] = []
            seen: set[int] = set()

            def add(columns_to_add) -> None:
                for col in columns_to_add:
                    if col != old and col not in seen and len(chosen) < limit:
                        seen.add(col)
                        chosen.append(col)

            objective_count = max(4, limit // 2)
            objective_heap: list[tuple[float, int, int]] = []
            for index, col in enumerate(columns_for_job):
                if col == old:
                    continue
                if (index & 1023) == 0 and time.monotonic() >= until:
                    return chosen
                cost = float(mean_costs_array[col])
                start = int(choices[col][1])
                entry = (-cost, -start, col)
                if len(objective_heap) < objective_count:
                    heapq.heappush(objective_heap, entry)
                else:
                    worst_cost, worst_start = (-objective_heap[0][0],
                                               -objective_heap[0][1])
                    if (cost, start) < (worst_cost, worst_start):
                        heapq.heapreplace(objective_heap, entry)
            add(col for _, _, col in sorted(
                objective_heap,
                key=lambda entry: (-entry[0], -entry[1]),
            ))

            # Choice columns of one intervention are contiguous and ordered by
            # start, so nearest and horizon-spanning samples need no sorting.
            old_position = old - columns_for_job[0]
            nearby: list[int] = []
            radius = 1
            nearby_target = max(4, limit // 4)
            while len(nearby) < nearby_target and (
                    old_position - radius >= 0
                    or old_position + radius < len(columns_for_job)):
                if old_position - radius >= 0:
                    nearby.append(columns_for_job[old_position - radius])
                if (len(nearby) < nearby_target
                        and old_position + radius < len(columns_for_job)):
                    nearby.append(columns_for_job[old_position + radius])
                radius += 1
            add(nearby)
            room = limit - len(chosen)
            if room > 0 and time.monotonic() < until:
                # Preserve both domain extremes before filling the remaining
                # horizon-spanning sample; a full quota must not hide the last
                # endpoint merely because linspace emitted one extra position.
                add((columns_for_job[0], columns_for_job[-1]))
                room = limit - len(chosen)
                if room > 0:
                    interior = np.linspace(
                        0, len(columns_for_job) - 1, room + 2, dtype=int
                    )[1:-1]
                    add(columns_for_job[int(index)] for index in interior)
            return chosen

        for _ in range(max_passes):
            if time.monotonic() >= until:
                return
            alternative_counts = [
                len(by_job[name]) - 1 for name in names
                if len(by_job[name]) > 1
            ]
            flexible_job_count = len(alternative_counts)
            if flexible_job_count < 2:
                return
            total_alternatives = sum(alternative_counts)
            if total_alternatives <= max_indexed_moves:
                # Narrow domains should return their unused quota to broad jobs.
                # When the whole neighborhood fits, index it without sampling.
                per_job_limit = max(alternative_counts)
            else:
                per_job_limit = max(
                    12, max_indexed_moves // flexible_job_count
                )
            moves: list[tuple[int, int, int, tuple[np.ndarray, np.ndarray],
                              np.ndarray]] = []
            needed_rows: set[int] = set()
            delta_entry_count = 0
            per_job_entry_limit = max(
                1_024, max_delta_entries // max(1, flexible_job_count)
            )
            indexing_full = False
            for job_index, name in enumerate(names):
                if time.monotonic() >= until:
                    return
                old = selected[name]
                job_delta_entries = 0
                for new in alternatives_for(name, old, per_job_limit):
                    if time.monotonic() >= until:
                        return
                    change = replacement_activity_delta(old, new)
                    rows_changed, values_changed = change
                    # The old/new column widths can grossly overestimate the true
                    # delta after overlap and cancellation.  Budget the computed
                    # sparse delta, and keep scanning after one wide alternative.
                    if (job_delta_entries + rows_changed.size
                            > per_job_entry_limit):
                        continue
                    if (delta_entry_count + rows_changed.size
                            > max_delta_entries):
                        continue
                    changed_activity = activity[rows_changed] + values_changed
                    bad_mask = ((changed_activity < lo[rows_changed] - numerical_slack)
                                | (changed_activity
                                   > hi[rows_changed] + numerical_slack))
                    bad_rows = rows_changed[bad_mask]
                    moves.append((job_index, old, new, change, bad_rows))
                    if bad_rows.size:
                        needed_rows.update(map(int, bad_rows))
                        if len(needed_rows) > max_needed_rows:
                            return
                    delta_entry_count += rows_changed.size
                    job_delta_entries += rows_changed.size
                    if (len(moves) >= max_indexed_moves
                            or delta_entry_count >= max_delta_entries):
                        indexing_full = True
                        break
                if (indexing_full or len(moves) >= max_indexed_moves
                        or time.monotonic() >= until):
                    break
            if time.monotonic() >= until or not needed_rows or not moves:
                return

            # Build compact NumPy posting lists only for potentially binding rows.
            row_move_lists = {row: [] for row in needed_rows}
            row_value_lists = {row: [] for row in needed_rows}
            for move_index, (_, _, _, change, _) in enumerate(moves):
                if (move_index & 127) == 0 and time.monotonic() >= until:
                    return
                rows_changed, values_changed = change
                for row_index, (row, delta) in enumerate(
                        zip(rows_changed, values_changed)):
                    if ((row_index & 4095) == 0
                            and time.monotonic() >= until):
                        return
                    row_int = int(row)
                    if row_int in row_move_lists:
                        row_move_lists[row_int].append(move_index)
                        row_value_lists[row_int].append(float(delta))
            row_postings = {}
            for posting_index, row in enumerate(needed_rows):
                if ((posting_index & 127) == 0
                        and time.monotonic() >= until):
                    return
                row_postings[row] = (
                    np.asarray(row_move_lists[row], dtype=np.int32),
                    np.asarray(row_value_lists[row], dtype=float),
                )
            del row_move_lists, row_value_lists

            def qualifying(row: int, after_value: float) -> np.ndarray:
                move_ids, deltas = row_postings[row]
                if after_value < lo[row] - numerical_slack:
                    need = lo[row] - numerical_slack - after_value
                    return move_ids[deltas >= need]
                need = hi[row] + numerical_slack - after_value
                return move_ids[deltas <= need]

            best = None
            pair_evaluation_limit = 250_000
            pair_evaluations = 0
            interrupted = False
            infeasible_order = sorted(
                (index for index, move in enumerate(moves) if move[4].size),
                key=lambda index: (
                    moves[index][4].size,
                    mean_costs_array[moves[index][2]]
                    - mean_costs_array[moves[index][1]],
                ),
            )
            for scan_count, first_index in enumerate(infeasible_order):
                if ((scan_count & 31) == 0 and time.monotonic() >= until):
                    interrupted = True
                    break
                first_job, first_old, first_new, first_change, bad_rows = (
                    moves[first_index]
                )
                first_rows, first_values = first_change
                bad_positions = np.searchsorted(first_rows, bad_rows)
                bad_after = activity[bad_rows] + first_values[bad_positions]
                shortlist = None
                for bad_offset, (row_value, after_value) in enumerate(
                        zip(bad_rows, bad_after)):
                    if ((bad_offset & 31) == 0
                            and time.monotonic() >= until):
                        interrupted = True
                        break
                    row = int(row_value)
                    candidates = qualifying(row, float(after_value))
                    if shortlist is None or candidates.size < shortlist.size:
                        shortlist = candidates
                if interrupted:
                    break
                if shortlist is None or shortlist.size == 0:
                    continue
                for bad_offset, (row_value, after_value) in enumerate(
                        zip(bad_rows, bad_after)):
                    if ((bad_offset & 31) == 0
                            and time.monotonic() >= until):
                        interrupted = True
                        break
                    row = int(row_value)
                    candidates = qualifying(row, float(after_value))
                    shortlist = np.intersect1d(
                        shortlist, candidates, assume_unique=True
                    )
                    if shortlist.size == 0:
                        break
                if interrupted:
                    break
                if shortlist.size == 0:
                    continue
                for shortlist_offset, second_index_value in enumerate(shortlist):
                    if ((shortlist_offset & 31) == 0
                            and time.monotonic() >= until):
                        interrupted = True
                        break
                    second_index = int(second_index_value)
                    second_job, second_old, second_new, _, second_bad = (
                        moves[second_index]
                    )
                    if second_job == first_job:
                        continue
                    # Feasible second moves can only be reached from the
                    # infeasible leader.  For two infeasible moves, retain one
                    # canonical direction without a quadratic history set.
                    if second_bad.size and second_index < first_index:
                        continue
                    if pair_evaluations >= pair_evaluation_limit:
                        interrupted = True
                        break
                    pair_evaluations += 1
                    replacements = [
                        (first_old, first_new), (second_old, second_new)
                    ]
                    candidate_change = feasible_activity_change(replacements)
                    if candidate_change is None:
                        continue
                    value = evaluate_replacements(replacements)
                    if (value < current
                            and (best is None
                                 or value < best[0])):
                        best = (value, first_job, first_new, second_job,
                                second_new, candidate_change, replacements)
                if interrupted:
                    break

            if best is None:
                return
            (value, first_job, first_new, second_job, second_new,
             candidate_change, replacements) = best
            committed = apply_move(
                [(names[first_job], first_new), (names[second_job], second_new)],
                replacements, candidate_change, value,
            )
            if not committed:
                return
            if interrupted:
                return

    def compensating_pairs(until: float, max_passes: int = 12) -> None:
        """Search arbitrary two-job starts, keyed by a violated binding row.

        A one-job move that crosses a resource or exclusion bound can only belong
        to a feasible pair if the other move compensates every crossed row.  For
        each such first move, use its most selective violated row to shortlist
        second moves, then check the complete activity vector in vectorized
        batches.  Exact objective work is therefore spent only on feasible pairs.
        """
        nonlocal activity
        if time.monotonic() >= until:
            return
        row_count = base_matrix.shape[0]
        # Keep dense vectorization for compact models and fall back to changed-row
        # postings everywhere else instead of silently losing this neighborhood.
        move_count = choice_count - len(names)
        if move_count <= 0:
            return
        if dense_columns is None or row_count * move_count > 12_000_000:
            sparse_compensating_pairs(until, max_passes=min(8, max_passes))
            return
        candidate_lo = lo - numerical_slack
        candidate_hi = hi + numerical_slack
        resource_stop = resource_base + resource_row_count
        finite_bound_scale = np.maximum(
            np.where(np.isfinite(candidate_lo), np.abs(candidate_lo), 0.0),
            np.where(np.isfinite(candidate_hi), np.abs(candidate_hi), 0.0),
        )

        for _ in range(max_passes):
            if time.monotonic() >= until:
                return
            move_jobs: list[int] = []
            move_old: list[int] = []
            move_new: list[int] = []
            for job_index, name in enumerate(names):
                old = selected[name]
                for new in by_job[name]:
                    if new != old:
                        move_jobs.append(job_index)
                        move_old.append(old)
                        move_new.append(new)
            if not move_new:
                return
            move_jobs_array = np.asarray(move_jobs, dtype=np.int32)
            move_old_array = np.asarray(move_old, dtype=np.int32)
            move_new_array = np.asarray(move_new, dtype=np.int32)
            # Shape is constraints x candidate moves.  This costs no more than
            # the already-bounded dense column cache plus a modest temporary.
            move_deltas = (
                dense_columns[:, move_new_array] - dense_columns[:, move_old_array]
            )
            after_moves = activity[:, None] + move_deltas
            move_feasible = ~np.any(
                (after_moves < candidate_lo[:, None])
                | (after_moves > candidate_hi[:, None]),
                axis=0,
            )
            del after_moves

            def compatible_on_row(
                    row: int, columns: np.ndarray | None, *, lower: bool,
                    after_first: np.ndarray) -> np.ndarray:
                """Admit ULP-borderline sums for authoritative pair checking."""
                deltas = (
                    move_deltas[row, :]
                    if columns is None else move_deltas[row, columns]
                )
                scale = np.maximum(
                    np.maximum(abs(after_first[row]), np.abs(deltas)),
                    finite_bound_scale[row],
                )
                guard = 8.0 * np.spacing(scale)
                guard = np.where(np.isfinite(guard), guard, 0.0)
                values = after_first[row] + deltas
                if lower:
                    return ~(values < candidate_lo[row] - guard)
                return ~(values > candidate_hi[row] + guard)

            best = None
            interrupted = False
            for first_move in range(len(move_new)):
                if time.monotonic() >= until:
                    interrupted = True
                    break
                # Feasible moves were exhausted by steepest_one.  They still
                # occur as second moves when compensating an infeasible move.
                if move_feasible[first_move]:
                    continue
                first_job_index = int(move_jobs_array[first_move])
                delta_first = move_deltas[:, first_move]
                after_first = activity + delta_first
                low_bad = np.flatnonzero(after_first < lo - numerical_slack)
                high_bad = np.flatnonzero(after_first > hi + numerical_slack)
                if low_bad.size == 0 and high_bad.size == 0:
                    continue

                # Any feasible pair must compensate each bad row.  Selecting the
                # shortest qualifying list avoids an all-pairs product.
                shortlist = None
                for row in low_bad:
                    candidates = np.flatnonzero(compatible_on_row(
                        int(row), None, lower=True, after_first=after_first,
                    ))
                    if shortlist is None or candidates.size < shortlist.size:
                        shortlist = candidates
                for row in high_bad:
                    candidates = np.flatnonzero(compatible_on_row(
                        int(row), None, lower=False, after_first=after_first,
                    ))
                    if shortlist is None or candidates.size < shortlist.size:
                        shortlist = candidates
                if shortlist is None or shortlist.size == 0:
                    continue
                # Intersect the shortlist with every other crossed bound before
                # doing a full-vector feasibility check.  Equality resources in
                # particular shrink from hundreds of candidates to true swaps.
                for row in low_bad:
                    shortlist = shortlist[compatible_on_row(
                        int(row), shortlist, lower=True, after_first=after_first,
                    )]
                    if shortlist.size == 0:
                        break
                if shortlist.size:
                    for row in high_bad:
                        shortlist = shortlist[compatible_on_row(
                            int(row), shortlist, lower=False,
                            after_first=after_first,
                        )]
                        if shortlist.size == 0:
                            break
                if shortlist.size == 0:
                    continue
                shortlist = shortlist[
                    move_jobs_array[shortlist] != first_job_index
                ]
                if shortlist.size == 0:
                    continue

                # If both component moves are infeasible, evaluate the unordered
                # pair only once.  If one component is feasible, its infeasible
                # partner must lead so that such asymmetric pairs are not lost.
                duplicate = (~move_feasible[shortlist]) & (
                    move_jobs_array[shortlist] < first_job_index
                )
                shortlist = shortlist[~duplicate]
                for begin in range(0, shortlist.size, 256):
                    if time.monotonic() >= until:
                        interrupted = True
                        break
                    batch = shortlist[begin:begin + 256]
                    batch_deltas = move_deltas[:, batch]
                    candidate_activities = after_first[:, None] + batch_deltas
                    strict_feasible = ~np.any(
                        (candidate_activities < candidate_lo[:, None])
                        | (candidate_activities > candidate_hi[:, None]),
                        axis=0,
                    )
                    # Widen only by an arithmetic error envelope.  Any candidate
                    # admitted solely by this envelope is rebuilt in checker order.
                    batch_scale = np.maximum.reduce((
                        np.abs(after_first),
                        np.max(np.abs(batch_deltas), axis=1),
                        finite_bound_scale,
                    ))
                    batch_guard = 8.0 * np.spacing(batch_scale)
                    batch_guard = np.where(
                        np.isfinite(batch_guard), batch_guard, 0.0
                    )
                    coarse_feasible = ~np.any(
                        (candidate_activities
                         < (candidate_lo - batch_guard)[:, None])
                        | (candidate_activities
                           > (candidate_hi + batch_guard)[:, None]),
                        axis=0,
                    )
                    near_lo = (
                        candidate_lo[resource_base:resource_stop]
                        + batch_guard[resource_base:resource_stop]
                    )
                    near_hi = (
                        candidate_hi[resource_base:resource_stop]
                        - batch_guard[resource_base:resource_stop]
                    )
                    for scored_count, local_index in enumerate(
                            np.flatnonzero(coarse_feasible)):
                        if ((scored_count & 31) == 0
                                and time.monotonic() >= until):
                            interrupted = True
                            break
                        second_move = int(batch[local_index])
                        replacements = [
                            (int(move_old_array[first_move]),
                             int(move_new_array[first_move])),
                            (int(move_old_array[second_move]),
                             int(move_new_array[second_move])),
                        ]
                        candidate_activity = candidate_activities[:, local_index]
                        near_bound = resource_row_count > 0 and np.any(
                            (candidate_activity[resource_base:resource_stop]
                             <= near_lo)
                            | (candidate_activity[resource_base:resource_stop]
                               >= near_hi)
                        )
                        if not strict_feasible[local_index] or near_bound:
                            checked_activity = authoritative_activity_change(
                                replacements
                            )
                            if checked_activity is None:
                                continue
                            candidate_activity = checked_activity
                        else:
                            candidate_activity = candidate_activity.copy()
                        value = evaluate_replacements(replacements)
                        if (value < current
                                and (best is None or value < best[0])):
                            best = (
                                value, first_job_index,
                                int(move_new_array[first_move]),
                                int(move_jobs_array[second_move]),
                                int(move_new_array[second_move]),
                                candidate_activity,
                                replacements,
                            )
                    if interrupted:
                        break
                if interrupted:
                    break

            if best is None:
                return
            (value, first_job_index, first_new, second_job_index, second_new,
             candidate_activity, replacements) = best
            committed = apply_move(
                [(names[first_job_index], first_new),
                 (names[second_job_index], second_new)],
                replacements, candidate_activity, value,
            )
            if not committed:
                return
            if interrupted:
                return

    def synergistic_pairs(until: float, max_passes: int = 4,
                          shortlist_size: int = 96) -> None:
        """Try bounded feasible two- and three-move quantile neighborhoods.

        Exact one-move values provide a strong global ranking, while small
        per-period heaps retain tail-local diversity that a single global top-k
        can discard.  If no pair improves, extend the most promising feasible
        overlapping pairs by a third move.  This catches order-statistic changes
        that require three simultaneous jobs without an unbounded cubic scan.
        """
        if time.monotonic() >= until:
            return

        def retain(heap, value, serial, item, limit):
            """Keep the lowest-valued items in a max-heap encoded by -value."""
            entry = (-value, serial, item)
            if len(heap) < limit:
                heapq.heappush(heap, entry)
            elif value < -heap[0][0]:
                heapq.heapreplace(heap, entry)

        for _ in range(max_passes):
            global_heap = []
            period_heaps: dict[int, list] = {}
            tail_heaps: dict[int, list] = {}
            best_single = None
            interrupted = False
            serial = 0
            period_quota = 3
            tail_quota = 2

            # Retain moves that push distinct scenarios near the current order-
            # statistic boundary downward.  Such moves may look mediocre alone
            # yet complement one another when the identity of the kth scenario
            # changes.  Ignore periods whose positive-part excess is already zero.
            tail_work = 0
            positive_tail_periods: list[int] = []
            for t, deviation in enumerate(period_deviations):
                if (t & 1023) == 0 and time.monotonic() >= until:
                    interrupted = True
                    break
                if period_excesses[t] <= 0.0:
                    continue
                tail_work += deviation.size
                if tail_work > 250_000:
                    break
                positive_tail_periods.append(t)
            tail_time_reserve = 0.01 + tail_work / 5_000_000.0
            tail_ranking_enabled = (
                not interrupted
                and tail_work <= 250_000
                and time.monotonic() + tail_time_reserve < until
            )
            critical_indices: dict[int, np.ndarray] = {}
            scenario_heaps: dict[int, list[list]] = {}
            if tail_ranking_enabled:
                for t in positive_tail_periods:
                    if time.monotonic() >= until:
                        interrupted = True
                        break
                    deviation = period_deviations[t]
                    count = deviation.size
                    kth = int(kth_indices[t])
                    if kth < 0:
                        kth += count
                    low = max(0, kth - 2)
                    high = min(count - 1, kth + 2)
                    if low == 0 and high == count - 1:
                        band = np.arange(count, dtype=np.int32)
                    else:
                        band = np.argpartition(
                            deviation, (low, high)
                        )[low:high + 1]
                    retained_band = np.asarray(band, dtype=np.int32)
                    critical_indices[t] = retained_band
                    scenario_heaps[t] = [
                        [] for _ in range(retained_band.size)
                    ]

            # Pair/triple scoring reuses each shortlisted move many times.  Cache
            # its centered risk delta once, then combine one or two arrays per
            # affected period rather than repeating dictionary lookups and four
            # vector operations for every candidate combination.
            centered_effect_cache: dict[
                tuple[int, int], dict[int, np.ndarray]
            ] = {}
            fast_scoring_enabled = False

            def centered_effect(old: int, new: int) -> dict[int, np.ndarray]:
                key = (old, new)
                cached = centered_effect_cache.get(key)
                if cached is not None:
                    return cached
                effects: dict[int, np.ndarray] = {}
                for t in replacement_periods(old, new):
                    effect = np.zeros(int(scenario_counts[t]), dtype=float)
                    old_risk = choice_period_risks[old].get(t)
                    if old_risk is not None:
                        effect -= old_risk
                        effect += choice_period_means[old][t]
                    new_risk = choice_period_risks[new].get(t)
                    if new_risk is not None:
                        effect += new_risk
                        effect -= choice_period_means[new][t]
                    effects[t] = effect
                centered_effect_cache[key] = effects
                return effects

            def evaluate_shortlisted(
                    replacements: list[tuple[int, int]]) -> float:
                if not fast_scoring_enabled:
                    return evaluate_replacements(replacements)
                mean_delta = sum(
                    mean_costs_array[new] - mean_costs_array[old]
                    for old, new in replacements
                )
                effects = [centered_effect(old, new)
                           for old, new in replacements]
                excess_delta = 0.0
                for t in affected_periods(replacements):
                    deviation = period_deviations[t].copy()
                    for effect in effects:
                        period_effect = effect.get(t)
                        if period_effect is not None:
                            deviation += period_effect
                    deviation.partition(kth_indices[t])
                    excess_delta += (
                        max(0.0, float(deviation[kth_indices[t]]))
                        - period_excesses[t]
                    )
                return float(current + alpha * mean_delta
                             + (1.0 - alpha) * excess_delta / horizon)

            def validated_shortlisted_value(
                    replacements: list[tuple[int, int]]) -> float:
                value = evaluate_shortlisted(replacements)
                if not fast_scoring_enabled:
                    return value
                # Cached centered effects deliberately regroup arithmetic.  They
                # are useful for ranking clearly noncompetitive combinations, but
                # a near-incumbent result must be rescored through the exact move
                # evaluator before it can be accepted or discarded.
                scale = max(float(objective_unit), abs(float(current)), abs(value))
                validation_guard = max(
                    checker_rounding_guard, 1e-12 * scale,
                    32.0 * float(np.spacing(scale)),
                )
                if value <= current + validation_guard:
                    return (
                        source_order_replacement_value(replacements)
                        if horizon >= 1024
                        else evaluate_replacements(replacements)
                    )
                return value

            for job_index, name in enumerate(names):
                old = selected[name]
                dense_base_activity = (
                    activity - dense_columns[:, old]
                    if dense_columns is not None else None
                )
                for new in by_job[name]:
                    if time.monotonic() >= until:
                        interrupted = True
                        break
                    if new == old:
                        continue
                    replacements = [(old, new)]
                    candidate_change = feasible_activity_change(
                        replacements, dense_base_activity
                    )
                    if candidate_change is None:
                        continue
                    value = evaluate_replacements(replacements)
                    periods = frozenset(affected_periods(replacements))
                    local_tail_merit: dict[int, float] = {}
                    scenario_merits: list[tuple[int, int, float]] = []
                    total_tail_merit = 0.0
                    for t in periods:
                        band = critical_indices.get(t)
                        if band is None:
                            continue
                        effect = np.zeros(
                            band.size,
                            dtype=np.longdouble if risk_precision_lost else float,
                        )
                        old_risk = choice_period_risks[old].get(t)
                        if old_risk is not None:
                            effect -= old_risk[band]
                            effect += choice_period_means[old][t]
                        new_risk = choice_period_risks[new].get(t)
                        if new_risk is not None:
                            effect += new_risk[band]
                            effect -= choice_period_means[new][t]
                        downward = np.maximum(-effect, 0.0)
                        merit = ((1.0 - alpha) / horizon
                                 * np.sum(downward)
                                 / max(1, band.size))
                        if merit > 0.0:
                            local_tail_merit[t] = merit
                            total_tail_merit += merit
                            scenario_merits.extend(
                                (t, slot, (1.0 - alpha) / horizon * amount)
                                for slot, amount in enumerate(downward)
                                if amount > 0.0
                            )
                    item = (value, job_index, old, new, periods,
                            total_tail_merit)
                    retain(global_heap, value, serial, item, shortlist_size)
                    for t in periods:
                        retain(period_heaps.setdefault(t, []), value, serial,
                               item, period_quota)
                        merit = local_tail_merit.get(t, 0.0)
                        if merit > 0.0:
                            # retain() keeps low keys; negate merit to keep the
                            # strongest tail-moving candidates.
                            retain(tail_heaps.setdefault(t, []), -merit,
                                   serial, item, tail_quota)
                    for t, slot, merit in scenario_merits:
                        retain(scenario_heaps[t][slot], -merit, serial, item, 1)
                    serial += 1
                    if (value < current
                            and (best_single is None
                                 or value < best_single[0])):
                        best_single = (
                            value, job_index, old, new,
                            candidate_change, replacements,
                        )
                if interrupted:
                    break

            # Preserve useful work if an earlier neighborhood reached this phase
            # late and only a partial one-move scan fit in the remaining slice.
            if best_single is not None:
                value, job_index, old, new, candidate_activity, replacements = best_single
                committed = apply_move(
                    [(names[job_index], new)], replacements,
                    candidate_activity, value,
                )
                if not committed:
                    return
                if interrupted:
                    return
                continue
            if interrupted:
                return

            # Add a bounded number of period-local moves not represented in the
            # global top-k.  Keying by (job,new) removes multi-period duplicates.
            candidates_by_key = {
                (entry[2][1], entry[2][3]): entry[2] for entry in global_heap
            }
            diverse = {}
            for heaps in (period_heaps.values(), tail_heaps.values()):
                for heap in heaps:
                    for _, _, item in heap:
                        key = (item[1], item[3])
                        if key not in candidates_by_key:
                            diverse[key] = item
            scenario_diverse = {}
            for period_scenario_heaps in scenario_heaps.values():
                for heap in period_scenario_heaps:
                    for specific_merit, _, item in heap:
                        key = (item[1], item[3])
                        if key in candidates_by_key:
                            continue
                        previous = scenario_diverse.get(key)
                        if previous is None or specific_merit > previous[0]:
                            scenario_diverse[key] = (specific_merit, item)
            diversity_limit = max(12, shortlist_size // 2)
            # Give objective quality, boundary-scenario identity, and aggregate
            # tail leverage separate reserves.  Exclude previously selected keys
            # at each stage so deduplication cannot silently shrink the quota.
            selected_diverse: list[tuple] = []
            selected_keys: set[tuple[int, int]] = set()

            def add_diverse(pool, limit) -> None:
                for item in pool:
                    key = (item[1], item[3])
                    if key in selected_keys or key in candidates_by_key:
                        continue
                    selected_keys.add(key)
                    selected_diverse.append(item)
                    if len(selected_diverse) >= limit:
                        return

            # Keep the complete objective-ranked reserve before spending separate
            # quotas on scenario identity and aggregate tail leverage.  Otherwise
            # merit ties can crowd out a move that is essential to the best pair.
            objective_limit = diversity_limit
            scenario_limit = objective_limit + max(1, diversity_limit // 2)
            tail_limit = 2 * diversity_limit
            add_diverse(sorted(
                diverse.values(), key=lambda candidate: candidate[0]
            ), objective_limit)
            add_diverse([
                item for _, item in sorted(
                    scenario_diverse.values(),
                    key=lambda merit_and_item: merit_and_item[0], reverse=True,
                )
            ], scenario_limit)
            tail_pool = dict(diverse)
            tail_pool.update(
                (key, item) for key, (_, item) in scenario_diverse.items()
            )
            add_diverse(sorted(
                tail_pool.values(),
                key=lambda candidate: candidate[5], reverse=True,
            ), tail_limit)
            # Fill any reserve left by overlaps with the best remaining local move.
            add_diverse(sorted(
                tail_pool.values(), key=lambda candidate: candidate[0]
            ), tail_limit)
            for item in selected_diverse:
                candidates_by_key[(item[1], item[3])] = item
            candidates = sorted(candidates_by_key.values(), key=lambda item: item[0])
            if len(candidates) < 2:
                return
            cached_effect_entries = sum(
                sum(int(scenario_counts[t]) for t in item[4])
                for item in candidates
            )
            cached_effect_arrays = sum(len(item[4]) for item in candidates)
            fast_scoring_reserve = 0.01 + cached_effect_entries / 10_000_000.0
            fast_scoring_enabled = (
                not risk_precision_lost
                and not checker_rescore_required
                and cached_effect_entries <= 4_000_000
                and cached_effect_arrays <= 20_000
                and time.monotonic() + fast_scoring_reserve < until
            )

            def canonical_rescore_needed(heap) -> bool:
                """Rescore only candidates close enough for regrouping to matter."""
                if not heap:
                    return False
                closest = min(float(entry[2][0]) for entry in heap)
                scale = max(float(objective_unit), abs(float(current)), abs(closest))
                drift_guard = max(
                    max(1, horizon) * checker_rounding_guard,
                    2e-12 * scale,
                    64.0 * max(1, horizon) * float(np.spacing(scale)),
                )
                return closest <= current + drift_guard

            best_pair = None
            pair_heap = []
            pair_serial = 0
            pair_limit = max(12, shortlist_size // 4)
            for first_index, first in enumerate(candidates):
                if time.monotonic() >= until:
                    interrupted = True
                    break
                _, first_job, first_old, first_new, first_periods, _ = first
                for second_index in range(first_index + 1, len(candidates)):
                    if time.monotonic() >= until:
                        interrupted = True
                        break
                    second = candidates[second_index]
                    (_, second_job, second_old, second_new,
                     second_periods, _) = second
                    if (second_job == first_job
                            or first_periods.isdisjoint(second_periods)):
                        continue
                    replacements = [
                        (first_old, first_new), (second_old, second_new)
                    ]
                    candidate_change = feasible_activity_change(replacements)
                    if candidate_change is None:
                        continue
                    value = validated_shortlisted_value(replacements)
                    pair_item = (
                        value, first_index, second_index,
                        first_periods | second_periods,
                    )
                    retain(pair_heap, value, pair_serial, pair_item, pair_limit)
                    pair_serial += 1
                    if (value < current
                            and (best_pair is None
                                 or value < best_pair[0])):
                        best_pair = (
                            value, first_job, first_new, second_job, second_new,
                            candidate_change, replacements,
                        )
                if interrupted:
                    break

            if (best_pair is None and fast_scoring_enabled and not interrupted
                    and canonical_rescore_needed(pair_heap)):
                # Cached arithmetic is a ranking device, not an acceptance proof.
                # Rescore the strongest approximate pairs even when accumulated
                # rounding placed them just outside the near-incumbent guard.
                approximate_pairs = sorted(
                    (entry[2] for entry in pair_heap), key=lambda item: item[0]
                )[:8]
                for _, first_index, second_index, _ in approximate_pairs:
                    if time.monotonic() >= until:
                        interrupted = True
                        break
                    first = candidates[first_index]
                    second = candidates[second_index]
                    _, first_job, first_old, first_new, _, _ = first
                    _, second_job, second_old, second_new, _, _ = second
                    replacements = [
                        (first_old, first_new), (second_old, second_new)
                    ]
                    candidate_change = feasible_activity_change(replacements)
                    if candidate_change is None:
                        continue
                    value = source_order_replacement_value(replacements)
                    if (value < current
                            and (best_pair is None or value < best_pair[0])):
                        best_pair = (
                            value, first_job, first_new, second_job, second_new,
                            candidate_change, replacements,
                        )

            if best_pair is not None:
                (value, first_job, first_new, second_job, second_new,
                 candidate_activity, replacements) = best_pair
                committed = apply_move(
                    [(names[first_job], first_new),
                     (names[second_job], second_new)],
                    replacements, candidate_activity, value,
                )
                if not committed:
                    return
                if interrupted:
                    return
                continue
            if interrupted or not pair_heap:
                return

            # No pair improves.  Extend only the closest feasible, overlapping
            # pairs; a disjoint third move has an additive nonnegative delta.
            best_triple = None
            triple_heap = []
            triple_serial = 0
            promising_pairs = sorted(
                (entry[2] for entry in pair_heap), key=lambda item: item[0]
            )
            for _, first_index, second_index, pair_periods in promising_pairs:
                first = candidates[first_index]
                second = candidates[second_index]
                _, first_job, first_old, first_new, _, _ = first
                _, second_job, second_old, second_new, _, _ = second
                for third_index, third in enumerate(candidates):
                    if time.monotonic() >= until:
                        interrupted = True
                        break
                    (_, third_job, third_old, third_new,
                     third_periods, _) = third
                    if (third_job == first_job or third_job == second_job
                            or pair_periods.isdisjoint(third_periods)):
                        continue
                    replacements = [
                        (first_old, first_new), (second_old, second_new),
                        (third_old, third_new),
                    ]
                    candidate_change = feasible_activity_change(replacements)
                    if candidate_change is None:
                        continue
                    value = validated_shortlisted_value(replacements)
                    triple_item = (
                        value, first_index, second_index, third_index,
                    )
                    retain(
                        triple_heap, value, triple_serial, triple_item, 8
                    )
                    triple_serial += 1
                    if (value < current
                            and (best_triple is None
                                 or value < best_triple[0])):
                        best_triple = (
                            value, first_job, first_new, second_job, second_new,
                            third_job, third_new, candidate_change, replacements,
                        )
                if interrupted:
                    break

            if (best_triple is None and fast_scoring_enabled and not interrupted
                    and canonical_rescore_needed(triple_heap)):
                approximate_triples = sorted(
                    (entry[2] for entry in triple_heap),
                    key=lambda item: item[0],
                )
                for _, first_index, second_index, third_index in approximate_triples:
                    if time.monotonic() >= until:
                        interrupted = True
                        break
                    first = candidates[first_index]
                    second = candidates[second_index]
                    third = candidates[third_index]
                    _, first_job, first_old, first_new, _, _ = first
                    _, second_job, second_old, second_new, _, _ = second
                    _, third_job, third_old, third_new, _, _ = third
                    replacements = [
                        (first_old, first_new), (second_old, second_new),
                        (third_old, third_new),
                    ]
                    candidate_change = feasible_activity_change(replacements)
                    if candidate_change is None:
                        continue
                    value = source_order_replacement_value(replacements)
                    if (value < current
                            and (best_triple is None or value < best_triple[0])):
                        best_triple = (
                            value, first_job, first_new, second_job, second_new,
                            third_job, third_new, candidate_change, replacements,
                        )

            if best_triple is None:
                return
            (value, first_job, first_new, second_job, second_new,
             third_job, third_new, candidate_activity, replacements) = best_triple
            committed = apply_move(
                [(names[first_job], first_new), (names[second_job], second_new),
                 (names[third_job], third_new)],
                replacements, candidate_activity, value,
            )
            if not committed:
                return
            if interrupted:
                return

    recompute_interrupted = object()

    def recompute_state(state_selected: dict[str, int]):
        """Fully validate activity and objective independently of local deltas."""
        if time.monotonic() >= deadline:
            return recompute_interrupted
        checked_activity = reconstruct_activity(state_selected)
        if time.monotonic() >= deadline:
            return recompute_interrupted
        if (np.any(checked_activity < lo - numerical_slack)
                or np.any(checked_activity > hi + numerical_slack)):
            return None
        try:
            checked_risk = aggregate_risk(
                (state_selected[name] for name in names), until=deadline
            )
        except TimeoutError:
            return recompute_interrupted
        checked_value = schedule_value(state_selected, checked_risk)
        if scoring_timed_out:
            return recompute_interrupted
        if not math.isfinite(float(checked_value)):
            return None
        return checked_activity, checked_risk, checked_value

    # Polish the best exact incumbent first, then spend bounded slices on other
    # surrogate elites.  Always retain the best exact value seen externally, so
    # a weak basin or deadline cannot damage the returned schedule.
    remember_elite("incumbent", selected, activity, total_risk, current)
    pending = sorted(elites, key=lambda item: item[4])
    if validated_selected is None:
        return validated_output()
    local_deadline = deadline - validation_reserve
    for elite_index, (_, elite_selected, elite_activity,
                       elite_risk, elite_value) in enumerate(pending):
        now = time.monotonic()
        if now >= local_deadline:
            break
        remaining_elites = len(pending) - elite_index
        # Reserve part of the local budget for a genuinely different basin.
        # The final elite receives everything left.
        if remaining_elites > 1 and seconds >= 40.0:
            if elite_index == 0:
                next_value = pending[elite_index + 1][4]
                relative_gap = ((next_value - elite_value)
                                / max(objective_unit, abs(elite_value)))
                # A remote surrogate basin rarely catches a polished exact one;
                # retain a token slice, but invest most effort in the incumbent.
                share = 0.90 if relative_gap > 0.15 else 0.60
            else:
                share = 0.65
            elite_end = now + share * (local_deadline - now)
        else:
            elite_end = local_deadline
        selected = elite_selected.copy()
        activity = elite_activity.copy()
        total_risk = elite_risk.copy()
        current = elite_value
        replacement_period_cache.clear()
        replacement_activity_cache.clear()
        activity_cache_bytes = 0
        try:
            period_deviations, period_excesses = build_period_state(
                total_risk, until=elite_end
            )
        except TimeoutError:
            break
        except MemoryError:
            return validated_output()
        one_end = now + 0.20 * (elite_end - now)
        greedy_end = now + 0.35 * (elite_end - now)
        narrow_end = now + 0.50 * (elite_end - now)
        compensate_end = now + 0.79 * (elite_end - now)
        pair_end = now + 0.84 * (elite_end - now)
        polish_end = now + 0.92 * (elite_end - now)
        try:
            steepest_one(one_end)
            improving_start_swaps(greedy_end)
            steepest_start_swaps(narrow_end)
            # Keep a tail slice explicit: on broad models the compensating scan can
            # otherwise consume the shared deadline and starve quantile synergy.
            compensating_pairs(compensate_end)
            synergistic_pairs(pair_end)
            steepest_one(polish_end, max_passes=4)
            steepest_start_swaps(elite_end)
            # Narrow neighborhoods often converge before their slice expires.  Split
            # any final slack rather than letting the first neighborhood monopolize it.
            tail_now = time.monotonic()
            tail_split = tail_now + 0.80 * max(0.0, elite_end - tail_now)
            compensating_pairs(tail_split, max_passes=4)
            synergistic_pairs(elite_end, max_passes=2, shortlist_size=64)
            # Full activity/objective recomputation removes incremental drift and
            # prevents a numerically suspect local state from becoming the winner.
            checked = recompute_state(selected)
        except MemoryError:
            return validated_output()
        if checked is recompute_interrupted:
            break
        if checked is not None:
            activity, total_risk, current = checked
            retain_validated(selected, activity, current)

    # Local states are promoted only after the independent recomputation above.
    # If that traversal cannot finish, return the last completed checkpoint
    # rather than performing another deadline-blind full pass.
    return validated_output()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--instance", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--time-limit", type=float, default=60.0)
    parser.add_argument("--seed", type=int, default=2020)
    parser.add_argument("--strategy", choices=("mean", "refine"), default="refine")
    args = parser.parse_args()
    started = time.monotonic()
    instance = json.loads(args.instance.read_text())
    budget = args.time_limit - (time.monotonic() - started)
    if budget <= 0:
        raise TimeoutError("input parsing exhausted the budget")
    schedule = solve(instance, budget, args.seed, refine=args.strategy == "refine")
    args.output.write_text("".join(f"{name} {start}\n" for name, start in schedule.items()))


if __name__ == "__main__":
    main()
