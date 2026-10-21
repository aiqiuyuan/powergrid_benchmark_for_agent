"""Full-information AC OPF snapshots, independently checked with AC power flow.

This nonconvex numerical reference is not a certificate of global optimality.
Failures remain explicit; no sampled or interpolated reference replaces a day.
"""

from __future__ import annotations

import time

import numpy as np

from .simulation import PF_OPTIONS, measure, set_exogenous, summarize

OPF_VOLTAGE_GUARD_PU = 1e-6


def configure_reference(net) -> None:
    import pandapower as pp

    net.bus["min_vm_pu"] = 0.95 + OPF_VOLTAGE_GUARD_PU
    net.bus["max_vm_pu"] = 1.05 - OPF_VOLTAGE_GUARD_PU
    net.sgen["controllable"] = True
    net.load["controllable"] = False
    net.ext_grid["min_p_mw"] = -1e6
    net.ext_grid["max_p_mw"] = 1e6
    net.ext_grid["min_q_mvar"] = -1e6
    net.ext_grid["max_q_mvar"] = 1e6
    net.ext_grid["controllable"] = False
    for row in net.ext_grid.itertuples():
        net.bus.loc[row.bus, ["min_vm_pu", "max_vm_pu"]] = row.vm_pu
    # Match this voltage-control task's constraints; no additional thermal target.
    net.line["max_loading_percent"] = 1e6
    net.poly_cost = net.poly_cost.iloc[0:0].copy()
    net.pwl_cost = net.pwl_cost.iloc[0:0].copy()
    for index in net.ext_grid.index:
        pp.create_poly_cost(net, index, "ext_grid", cp1_eur_per_mw=1.0)


def solve_snapshot(net, trajectory: dict, step: int, capacities: np.ndarray,
                   bound: float, counters: dict | None = None) -> dict:
    import pandapower as pp

    capability = set_exogenous(net, trajectory, step, capacities)
    active = net.sgen.p_mw.to_numpy(copy=True)
    net.sgen["min_p_mw"] = active
    net.sgen["max_p_mw"] = active
    net.sgen["min_q_mvar"] = -bound * capability
    net.sgen["max_q_mvar"] = bound * capability
    if counters is not None:
        counters["opf"] += 1
    pp.runopp(net, numba=False, verbose=False, init="flat",
              OPF_VIOLATION=1e-9, PDIPM_FEASTOL=1e-9, PDIPM_MAX_IT=150)
    if not net.OPF_converged:
        raise ValueError("AC OPF did not report convergence")
    q = net.res_sgen.q_mvar.to_numpy(copy=True)
    p = net.res_sgen.p_mw.to_numpy(copy=True)
    slack_voltage_error = float(np.max(np.abs(
        net.res_bus.loc[net.ext_grid.bus, "vm_pu"].to_numpy()
        - net.ext_grid.vm_pu.to_numpy())))
    if (not np.isfinite(q).all() or not np.isfinite(p).all()
            or np.max(np.abs(q) - bound * capability) > 1e-7
            or np.max(np.abs(p - active)) > 1e-6 or slack_voltage_error > 1e-7):
        raise ValueError("OPF result changes fixed PV generation or violates reactive bounds")
    q = np.clip(q, -bound * capability, bound * capability)
    # Score only a new PF of the original exogenous powers and verified Q actions.
    net.sgen.loc[:, "p_mw"] = active
    net.sgen.loc[:, "q_mvar"] = q
    if counters is not None:
        counters["pf"] += 1
    pp.runpp(net, **PF_OPTIONS)
    row = measure(net)
    actions = np.divide(q, capability, out=np.zeros_like(q), where=capability > 0)
    row.update(interval_index=step, timestamp=trajectory["timestamps"][step],
               normalized_actions=actions.tolist(), pv_q_mvar=q.tolist(), solver_success=True,
               opf_slack_voltage_error_pu=slack_voltage_error,
               voltage_feasible_within_1e_minus_7=bool(
                   row["worst_undervoltage_pu"] <= 1e-7
                   and row["worst_overvoltage_pu"] <= 1e-7))
    return row


def evaluate_reference(net, trajectory: dict, pool: dict) -> dict:
    import pandapower as pp

    started = time.monotonic()
    configure_reference(net)
    capacities = np.asarray(pool["apparent_power_mva"], dtype=float)
    rows, failures = [], []
    counters = {"opf": 0, "pf": 0}
    for step in range(480):
        try:
            rows.append(solve_snapshot(net, trajectory, step, capacities,
                                       pool["normalized_action_bound"], counters))
        except (pp.OPFNotConverged, pp.LoadflowNotConverged, ValueError,
                FloatingPointError, np.linalg.LinAlgError) as exc:
            failures.append({"interval_index": step, "timestamp": trajectory["timestamps"][step],
                             "error": f"{type(exc).__name__}: {exc}"})
        if (step + 1) % 60 == 0:
            print(f"AC OPF attempted {step + 1}/480; successful {len(rows)}", flush=True)
    valid = (len(rows) == 480 and not failures
             and all(row["all_buses_compliant"] for row in rows))
    metrics = summarize(rows, bus_count=len(net.bus))
    quality = (0.8 * metrics["bus_time_compliance"]
               + 0.2 / (1 + metrics["actual_loss_mwh"])) if valid else 0.0
    return {"valid": valid, "quality": quality, "scheduled_intervals": 480,
            "attempted_intervals": 480, "completed_intervals": len(rows),
            "pf_calls": counters["pf"], "opf_calls": counters["opf"], "failures": failures,
            "pf_call_accounting": "explicit runpp calls; internal OPF solver iterations excluded",
            "failure_kind": None if valid else "opf_nonconvergence_or_infeasibility",
            "error": None if valid else "Incomplete or infeasible full-day AC OPF reference",
            "metrics": metrics, "steps": rows, "wall_seconds": time.monotonic() - started,
            "reference_scope": "current full-network snapshot, fixed active powers; "
                               "Q constrained to original normalized action limits; voltage-only",
            "solver": "pandapower.runopp nonconvex AC OPF; no global-optimum certificate",
            "evaluation_voltage_tolerance_pu": 1e-9,
            "solver_feasibility_tolerance_pu": 1e-7,
            "opf_internal_voltage_guard_pu": OPF_VOLTAGE_GUARD_PU,
            "voltage_guard_reason": "Numerical guard: optimize within [0.950001, 1.049999], "
                                    "then require [0.95, 1.05] with 1e-9 evaluation tolerance",
            "fixed_external_grid": [{"bus": int(row.bus), "vm_pu": float(row.vm_pu),
                                     "va_degree": float(row.va_degree)}
                                    for row in net.ext_grid.itertuples()],
            "protocol_claim": "fixed-case selection experiment; not a MAPDN paper reproduction"}
