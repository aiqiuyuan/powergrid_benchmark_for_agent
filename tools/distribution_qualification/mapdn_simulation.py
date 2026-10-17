"""Physical MAPDN baseline qualification; repeated solves have separate permission."""

from __future__ import annotations

import sys
import time
from collections.abc import Callable
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "distribution_selection"))
from mapdn_baselines.controllers import ControllerContractError, validate_action  # noqa: E402
from mapdn_baselines.simulation import (  # noqa: E402
    PF_OPTIONS,
    local_data,
    measure,
    set_exogenous,
    summarize,
)
from mapdn_controllers import MemoryController, source_curve  # noqa: E402


class ResourceBudgetExceeded(ValueError):
    """A frozen numerical-reference budget was reached."""


def source_iteration(
    solve: Callable, *, count: int, bound: float, max_iterations: int = 100
) -> tuple[np.ndarray, dict]:
    """Use the source's cold start, duplicate initial PF, relaxation and L2 stop.

    On the cap, the source scores the last *solved* Q rather than its final proposed
    update. An additional PF verifies exactly that solved action before scoring.
    The global PV L2 stop and repeated measurements are privileged permissions.
    """
    if not 1 <= max_iterations <= 100 or count <= 0:
        raise ValueError("invalid source iteration dimensions")
    action = np.zeros(count)
    solve(action.copy())  # Source records a separate no-control PF first.
    previous_voltage = np.full(count, 100.0)
    trace = []
    stop = "maximum_iterations"
    for iteration in range(1, max_iterations + 1):
        voltage = np.asarray(solve(action.copy()), dtype=float)
        if voltage.shape != (count,) or not np.isfinite(voltage).all():
            raise ValueError("invalid solved PV voltage")
        change = float(np.linalg.norm(previous_voltage - voltage, ord=2))
        row = {
            "iteration": iteration,
            "solved_normalized_actions": action.tolist(),
            "pv_voltage_pu": voltage.tolist(),
            "voltage_change_l2": change,
        }
        trace.append(row)
        if change < 1e-4:
            stop = "pv_voltage_l2_converged"
            break
        previous_voltage = voltage.copy()
        target = np.asarray([source_curve(float(value), bound) for value in voltage])
        proposed = 0.9 * action + 0.1 * target
        row.update(
            target_normalized_actions=target.tolist(), proposed_next_actions=proposed.tolist()
        )
        if iteration < max_iterations:
            action = proposed
    final_voltage = np.asarray(solve(action.copy()), dtype=float)
    if (
        final_voltage.shape != (count,)
        or not np.isfinite(final_voltage).all()
        or not np.allclose(final_voltage, voltage, rtol=0, atol=1e-7)
    ):
        raise ValueError("independent final PF does not reproduce the scored action")
    return action, {
        "trace": trace,
        "loop_iterations": len(trace),
        "stop_reason": stop,
        "source_initial_pf_calls": 1,
        "independent_final_pf_calls": 1,
        "pf_calls": len(trace) + 2,
        "proposed_update_at_cap_is_not_scored": stop == "maximum_iterations",
    }


def evaluate(
    net,
    trajectory: dict,
    pool: dict,
    policy: dict,
    intervals: int = 480,
    *,
    pf_budget: int = 50000,
    wall_seconds_budget: float = 1800,
) -> dict:
    import pandapower as pp

    if type(intervals) is not int or not 1 <= intervals <= 480:
        raise ValueError("evaluation must request between 1 and 480 intervals")
    name = policy["name"]
    if name not in ("source_iterative_droop", "one_step_relaxed", "one_step_integral"):
        raise ValueError("unknown qualification baseline")
    started = time.monotonic()
    capacities = np.asarray(pool["apparent_power_mva"], dtype=float)
    bound = pool["normalized_action_bound"]
    actions = np.zeros(len(net.sgen))
    controllers, rows = [], []
    calls = 0
    error, failure_kind, failed_attempt = None, None, None
    for step in range(intervals):
        before = calls
        physical_attempts = []
        try:
            capability = set_exogenous(net, trajectory, step, capacities)

            def solve(action: np.ndarray) -> list[float]:
                nonlocal calls
                if calls >= pf_budget or time.monotonic() - started >= wall_seconds_budget:
                    raise ResourceBudgetExceeded("frozen PF or wall-clock budget exhausted")
                if (
                    action.shape != (len(net.sgen),)
                    or not np.isfinite(action).all()
                    or np.abs(action).max() > bound + 1e-12
                ):
                    raise ControllerContractError("invalid simultaneous normalized action")
                net.sgen.loc[:, "q_mvar"] = action * capability
                calls += 1
                attempt = {"pf_call": calls, "normalized_actions": action.tolist()}
                physical_attempts.append(attempt)
                try:
                    pp.runpp(net, **PF_OPTIONS)
                except pp.LoadflowNotConverged:
                    attempt["converged"] = False
                    raise
                voltage = net.res_bus.loc[net.sgen.bus, "vm_pu"].tolist()
                attempt.update(converged=True, pv_voltage_pu=voltage)
                return voltage

            if name == "source_iterative_droop":
                actions, audit = source_iteration(solve, count=len(net.sgen), bound=bound)
            else:
                solve(actions)
                # Gather all current regional observations before any actor acts.
                local = [
                    local_data(net, actor, step, trajectory["timestamps"][step], bound, capacities)
                    for actor in range(len(net.sgen))
                ]
                if not controllers:
                    controllers = [MemoryController(metadata, policy) for metadata, _ in local]
                actions = np.asarray(
                    [
                        validate_action(actor.act(observation), bound)
                        for actor, (_, observation) in zip(controllers, local, strict=True)
                    ]
                )
                solve(actions)
                audit = {
                    "pf_calls": 2,
                    "source_initial_pf_calls": 1,
                    "independent_final_pf_calls": 1,
                    "loop_iterations": 1,
                    "stop_reason": "one_action_per_interval",
                }
            audit["physical_pf_trace"] = physical_attempts
            row = measure(net)
            row.update(
                interval_index=step,
                timestamp=trajectory["timestamps"][step],
                normalized_actions=actions.tolist(),
                q_capability_mvar=capability.tolist(),
                pv_q_mvar=net.sgen.q_mvar.tolist(),
                iteration_audit=audit,
            )
            rows.append(row)
        except (pp.LoadflowNotConverged, ValueError, FloatingPointError) as exc:
            error = f"{type(exc).__name__}: {exc}"
            failure_kind = (
                "resource_budget_exhausted"
                if isinstance(exc, ResourceBudgetExceeded)
                else "controller_contract_error"
                if isinstance(exc, ControllerContractError)
                else "power_flow_nonconvergence"
                if isinstance(exc, pp.LoadflowNotConverged)
                else "physical_or_source_integrity_failure"
            )
            failed_attempt = {
                "interval_index": step,
                "pf_calls": calls - before,
                "error": error,
                "physical_pf_trace": physical_attempts,
            }
            break
    valid = len(rows) == 480 and error is None
    metrics = summarize(rows, bus_count=len(net.bus))
    return {
        "valid": valid,
        "voltage_feasible": valid and metrics["all_bus_time_compliance"] == 1,
        "scheduled_intervals": 480,
        "requested_intervals": intervals,
        "completed_intervals": len(rows),
        "pf_calls": calls,
        "error": error,
        "failure_kind": failure_kind,
        "failed_attempt": failed_attempt,
        "metrics": metrics,
        "steps": rows,
        "bus_count": len(net.bus),
        "pv_count": len(net.sgen),
        "action_bound": bound,
        "wall_seconds": time.monotonic() - started,
        "pf_budget": pf_budget,
        "wall_seconds_budget": wall_seconds_budget,
        "source_converged_intervals": sum(
            row["iteration_audit"]["stop_reason"] == "pv_voltage_l2_converged" for row in rows
        ),
        "source_capped_intervals": sum(
            row["iteration_audit"]["stop_reason"] == "maximum_iterations" for row in rows
        ),
        "protocol_claim": "source-aligned clipped droop port; not original paper reproduction",
    }
