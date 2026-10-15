"""Validate physical schedules against PGLib-UC's published MILP inequalities."""

from __future__ import annotations

from contextvars import ContextVar

from json_io import fields, series

TOL = ContextVar("mw_tolerance", default=1e-5)


def le(left: float, right: float, label: str) -> None:
    if left > right + TOL.get():
        raise ValueError(label)


def eq(left: float, right: float, label: str) -> None:
    if abs(left - right) > TOL.get():
        raise ValueError(label)


def curve_cost(points: list[dict], production: float) -> float:
    for a, b in zip(points, points[1:]):
        if production <= b["mw"] + TOL.get():
            return a["cost"] + (production - a["mw"]) * (b["cost"] - a["cost"]) / (
                b["mw"] - a["mw"]
            )
    return points[-1]["cost"]


def validate(data: dict, solution: dict) -> dict:
    # One frozen, declared instance scale; never adapt tolerance to a candidate.
    scale = max(
        1.0,
        *data["demand"],
        *data["reserves"],
        *(g["power_output_maximum"] for g in data["thermal_generators"].values()),
    )
    token = TOL.set(1e-5 + 1e-8 * scale)
    try:
        return _validate(data, solution)
    finally:
        TOL.reset(token)


def _validate(data: dict, solution: dict) -> dict:
    fields(solution, {"schema", "thermal", "renewable"})
    if solution["schema"] != "uc-schedule-v1":
        raise ValueError("Wrong schedule schema")
    fields(solution["thermal"], set(data["thermal_generators"]))
    fields(solution["renewable"], set(data["renewable_generators"]))
    horizon = data["time_periods"]
    demand = [0.0] * horizon
    reserve = [0.0] * horizon
    cost = 0.0
    for name, gen in data["thermal_generators"].items():
        value = solution["thermal"][name]
        fields(value, {"on", "power", "reserve"})
        on = series(value["on"], horizon, binary=True)
        power = series(value["power"], horizon)
        res = series(value["reserve"], horizon)
        minimum, maximum = gen["power_output_minimum"], gen["power_output_maximum"]
        initial = gen["unit_on_t0"]
        start = [max(0, u - (on[t - 1] if t else initial)) for t, u in enumerate(on)]
        stop = [max(0, (on[t - 1] if t else initial) - u) for t, u in enumerate(on)]
        up, down = gen["time_up_minimum"], gen["time_down_minimum"]
        residual = up - gen["time_up_t0"] if initial else down - gen["time_down_t0"]
        for t in range(min(max(0, residual), horizon)):
            eq(on[t], initial, name + ": initial minimum up/down time")
        for t in range(horizon):
            label = f"{name} period {t + 1}: "
            above = power[t] - minimum * on[t]
            le(0, above, label + "minimum output")
            le(0, res[t], label + "negative reserve")
            le(gen["must_run"], on[t], label + "must-run")
            le(
                above + res[t],
                (maximum - minimum) * on[t]
                - max(maximum - gen["ramp_startup_limit"], 0) * start[t],
                label + "capacity/startup",
            )
            if t < horizon - 1:
                le(
                    above + res[t],
                    (maximum - minimum) * on[t]
                    - max(maximum - gen["ramp_shutdown_limit"], 0) * stop[t + 1],
                    label + "shutdown capacity",
                )
            previous = (
                power[t - 1] - minimum * on[t - 1]
                if t
                else initial * (gen["power_output_t0"] - minimum)
            )
            le(above + res[t] - previous, gen["ramp_up_limit"], label + "ramp up")
            le(previous - above, gen["ramp_down_limit"], label + "ramp down")
            if not t:
                le(
                    previous,
                    initial * (maximum - minimum)
                    - max(maximum - gen["ramp_shutdown_limit"], 0) * stop[0],
                    label + "initial shutdown",
                )
            # Truncated rolling windows also enforce early transitions and the tail.
            le(sum(start[max(0, t - up + 1) : t + 1]), on[t], label + "minimum uptime")
            le(sum(stop[max(0, t - down + 1) : t + 1]), 1 - on[t], label + "minimum downtime")
            if start[t]:
                # Minimize auxiliary startup-category cost under the EXACT
                # published equations (7), (15), (16). Equation (7) also applies
                # after a later shutdown/restart, so physical downtime alone
                # is insufficient for exact PGLib objective reconstruction.
                allowed = []
                period = t + 1
                for index, category in enumerate(gen["startup"]):
                    if index == len(gen["startup"]) - 1:
                        allowed.append(category["cost"])
                        continue
                    next_lag = gen["startup"][index + 1]["lag"]
                    if (
                        max(1, next_lag - gen["time_down_t0"] + 1)
                        <= period
                        <= min(next_lag - 1, horizon)
                    ):
                        continue
                    if period >= next_lag and not any(
                        stop[t - lag] for lag in range(category["lag"], next_lag)
                    ):
                        continue
                    allowed.append(category["cost"])
                cost += min(allowed)
            cost += curve_cost(gen["piecewise_production"], power[t]) if on[t] else 0
            demand[t] += power[t]
            reserve[t] += res[t]
    for name, gen in data["renewable_generators"].items():
        power = series(solution["renewable"][name], horizon)
        for t, amount in enumerate(power):
            le(gen["power_output_minimum"][t], amount, name + ": renewable minimum")
            le(amount, gen["power_output_maximum"][t], name + ": renewable maximum")
            demand[t] += amount
    for t in range(horizon):
        eq(demand[t], data["demand"][t], "Demand balance")
        le(data["reserves"][t], reserve[t], "Spinning reserve requirement")
    return {"cost": cost, "periods": horizon, "contingencies_checked": 0}
