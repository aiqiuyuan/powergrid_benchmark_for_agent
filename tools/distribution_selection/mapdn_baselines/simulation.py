"""Causal complete-day local-policy evaluation with physical balance checks."""

from __future__ import annotations

import time

import numpy as np

from .controllers import ControllerContractError, make_controller, validate_action

PF_OPTIONS = {"algorithm": "nr", "numba": False, "tolerance_mva": 1e-9,
              "max_iteration": 30}
VOLTAGE_TOLERANCE = 1e-9
BALANCE_TOLERANCE_MW = 1e-7


def validate_network(net, network: int) -> None:
    expected = {33: (33, 32, 6), 141: (141, 84, 22)}[network]
    if (len(net.bus), len(net.load), len(net.sgen)) != expected:
        raise ValueError("network dimensions do not match the requested MAPDN network")
    for element in ("gen", "storage", "shunt", "trafo", "trafo3w", "dcline",
                    "impedance", "ward", "xward", "motor"):
        if len(net[element]):
            raise ValueError(f"unsupported power-injecting or loss-bearing element: {element}")
    if "zone" not in net.bus or "name" not in net.sgen:
        raise ValueError("the network lacks the original regional partition")


def local_data(net, actor_id: int, step: int, timestamp: str,
               bound: float, capacities: np.ndarray) -> tuple[dict, dict]:
    pv = net.sgen.iloc[actor_id]
    region = net.bus.index[net.bus.zone == pv["name"]]
    if int(pv.bus) not in region:
        raise ValueError("PV is outside its declared local region")
    demand = net.res_load.groupby(net.load.bus)[["p_mw", "q_mvar"]].sum()
    demand = demand.reindex(region, fill_value=0)
    results = net.res_bus.loc[region]
    metadata = {"actor_id": actor_id, "pv_count": 1, "pv_bus_id": int(pv.bus),
                "region_bus_ids": [int(bus) for bus in region], "action_bound": bound,
                "interval_hours": 0.05, "voltage_bounds_pu": [0.95, 1.05],
                "apparent_power_mva": [float(capacities[actor_id])]}
    observation = {"interval_index": step, "timestamp": timestamp,
                   "pv_voltage_pu": [float(net.res_bus.at[pv.bus, "vm_pu"])],
                   "pv_active_mw": [float(pv.p_mw)],
                   "pv_reactive_mvar": [float(pv.q_mvar)],
                   "region_bus_ids": metadata["region_bus_ids"],
                   "region_demand_p_mw": demand.p_mw.tolist(),
                   "region_demand_q_mvar": demand.q_mvar.tolist(),
                   "region_voltage_pu": results.vm_pu.tolist(),
                   "region_angle_degree": results.va_degree.tolist()}
    return metadata, observation


def set_exogenous(net, trajectory: dict, step: int, capacities: np.ndarray) -> np.ndarray:
    active = np.asarray(trajectory["pv_active"][step], dtype=float)
    if (not np.isfinite(active).all() or (active < 0).any()
            or (active > capacities).any()):
        raise ValueError("PV active power exceeds its frozen capability")
    net.sgen.loc[:, "p_mw"] = active
    net.load.loc[:, "p_mw"] = trajectory["load_active"][step]
    net.load.loc[:, "q_mvar"] = trajectory["load_reactive"][step]
    return np.sqrt(np.maximum(0.0, capacities**2 - active**2))


def measure(net) -> dict:
    voltage = net.res_bus.vm_pu.to_numpy(dtype=float)
    q = net.res_sgen.q_mvar.to_numpy(dtype=float)
    if not np.isfinite(voltage).all() or not np.isfinite(q).all():
        raise ValueError("nonfinite voltage or reactive power after power flow")
    violation = np.maximum(0.95 - voltage, 0) + np.maximum(voltage - 1.05, 0)
    compliant = violation <= VOLTAGE_TOLERANCE
    loss = float(net.res_line.pl_mw.sum())
    balance = float(net.res_ext_grid.p_mw.sum() + net.res_sgen.p_mw.sum()
                    - net.res_load.p_mw.sum())
    residual = abs(balance - loss)
    if (not np.isfinite(loss) or not np.isfinite(residual) or loss < -1e-10
            or residual > BALANCE_TOLERANCE_MW):
        raise ValueError("physical line loss and full-network active-power balance disagree")
    deviation = np.abs(voltage - 1.0)
    density = np.exp(-0.5 * ((voltage - 1.0) / 0.1)**2) / (0.1 * np.sqrt(2 * np.pi))
    bowl = np.where(deviation > 0.05, 2 * deviation - 0.095, 0.04 - 0.01 * density)
    return {"all_buses_compliant": bool(compliant.all()),
            "paper_all_buses_compliant": bool((violation == 0).all()),
            "compliant_bus_count": int(compliant.sum()),
            "voltage_violation_sum_pu": float(violation.sum()),
            "worst_undervoltage_pu": float(max(0, 0.95 - voltage.min())),
            "worst_overvoltage_pu": float(max(0, voltage.max() - 1.05)),
            "voltage_min_pu": float(voltage.min()), "voltage_max_pu": float(voltage.max()),
            "actual_loss_mw": max(0.0, loss), "power_balance_residual_mw": residual,
            "mean_abs_q_mvar": float(np.abs(q).mean()),
            "voltage_l1": float(deviation.mean()),
            "voltage_l2": float((deviation**2).mean()), "voltage_bowl": float(bowl.mean())}


def summarize(rows: list[dict], *, bus_count: int, scheduled: int = 480) -> dict:
    completed = len(rows)

    def total(key: str) -> float:
        return sum(row[key] for row in rows)

    def average(key: str) -> float | None:
        return total(key) / completed if completed else None

    metrics = {
        "metric_coverage": completed / scheduled,
        "bus_time_compliance": total("compliant_bus_count") / (scheduled * bus_count),
        "all_bus_time_compliance": total("all_buses_compliant") / scheduled,
        "paper_cr": total("paper_all_buses_compliant") / scheduled,
        "actual_loss_mwh": total("actual_loss_mw") * 0.05,
        "actual_loss_mwh_is_partial": completed != scheduled,
        "mean_actual_loss_mw": average("actual_loss_mw"),
        "voltage_violation_pu_hours": total("voltage_violation_sum_pu") * 0.05,
        "paper_mean_abs_q_mvar": average("mean_abs_q_mvar"),
        "paper_voltage_l1_mean": average("voltage_l1"),
        "paper_voltage_l2_mean": average("voltage_l2"),
        "paper_voltage_bowl_mean": average("voltage_bowl"),
    }
    for key in ("worst_undervoltage_pu", "worst_overvoltage_pu"):
        metrics[key] = max((row[key] for row in rows), default=0.0)
    metrics["max_power_balance_residual_mw"] = max(
        (row["power_balance_residual_mw"] for row in rows), default=0.0)
    for barrier in ("l1", "l2", "bowl"):
        metrics[f"paper_reward_{barrier}_mean"] = (
            -average(f"voltage_{barrier}") - 0.1 * average("mean_abs_q_mvar")
            if completed else None)
    return metrics


def evaluate_local(net, trajectory: dict, pool: dict, policy: dict) -> dict:
    import pandapower as pp

    started = time.monotonic()
    capacities = np.asarray(pool["apparent_power_mva"], dtype=float)
    bound = pool["normalized_action_bound"]
    actions = np.zeros(len(net.sgen))
    controllers, rows = [], []
    error = None
    failure_kind = None
    calls = 0
    for step in range(480):
        try:
            capability = set_exogenous(net, trajectory, step, capacities)
            net.sgen.loc[:, "q_mvar"] = actions * capability
            calls += 1
            pp.runpp(net, **PF_OPTIONS)
            # Gather every observation before invoking any controller.
            local = [local_data(net, i, step, trajectory["timestamps"][step], bound, capacities)
                     for i in range(len(net.sgen))]
            if not controllers:
                controllers = [make_controller(meta, policy["name"], policy.get("gain", 1.0))
                               for meta, _ in local]
            actions = np.asarray([validate_action(controller.act(obs), bound)
                                  for controller, (_, obs) in zip(controllers, local, strict=True)])
            net.sgen.loc[:, "q_mvar"] = actions * capability
            calls += 1
            pp.runpp(net, **PF_OPTIONS)
            row = measure(net)
            row.update(interval_index=step, timestamp=trajectory["timestamps"][step],
                       normalized_actions=actions.tolist(),
                       pv_q_mvar=net.sgen.q_mvar.to_list())
            rows.append(row)
        except (pp.LoadflowNotConverged, ValueError, FloatingPointError) as exc:
            error = f"{type(exc).__name__}: {exc}"
            failure_kind = ("controller_contract_error" if isinstance(exc, ControllerContractError)
                            else "power_flow_nonconvergence"
                            if isinstance(exc, pp.LoadflowNotConverged)
                            else "physical_or_source_integrity_failure")
            break
    valid = len(rows) == 480 and error is None
    metrics = summarize(rows, bus_count=len(net.bus))
    quality = (0.8 * metrics["bus_time_compliance"]
               + 0.2 / (1 + metrics["actual_loss_mwh"])) if valid else 0.0
    return {"valid": valid, "quality": quality, "scheduled_intervals": 480,
            "completed_intervals": len(rows), "pf_calls": calls, "error": error,
            "failure_kind": failure_kind,
            "metrics": metrics, "steps": rows, "wall_seconds": time.monotonic() - started,
            "execution": "trusted known policies, separate instance per PV; causal regional data",
            "protocol_claim": "fixed-case selection experiment; not a MAPDN paper reproduction"}
