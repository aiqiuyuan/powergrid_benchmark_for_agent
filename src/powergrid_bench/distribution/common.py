"""Finite-value validation and physical summaries; no simulator or task reward."""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from numbers import Real
from typing import Literal


def _finite_number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a finite real number, not a boolean")
    try:
        number = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError(f"{name} must be finite") from exc
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


def _integer(value: object, name: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}, not a boolean")
    return value


def _sequence(value: object, name: str) -> Sequence:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise ValueError(f"{name} must be a sequence")
    return value


def _numeric_vector(
    values: object, name: str, *, expected_size: int | None = None, allow_empty: bool = False
) -> tuple[float, ...]:
    sequence = _sequence(values, name)
    if not sequence and not allow_empty:
        raise ValueError(f"{name} must not be empty")
    if expected_size is not None and len(sequence) != expected_size:
        raise ValueError(f"{name} must have exactly {expected_size} entries")
    return tuple(_finite_number(value, f"{name}[{index}]") for index, value in enumerate(sequence))


def _durations(step_hours: object, size: int) -> tuple[float, ...]:
    if isinstance(step_hours, Real):
        durations = (_finite_number(step_hours, "step_hours"),) * size
    else:
        durations = _numeric_vector(step_hours, "step_hours", expected_size=size)
    if any(duration <= 0 for duration in durations):
        raise ValueError("step_hours must be strictly positive")
    return durations


def _finite_sum(values: Sequence[float], name: str) -> float:
    try:
        result = math.fsum(values)
    except OverflowError as exc:
        raise ValueError(f"{name} overflowed") from exc
    return _finite_number(result, name)


@dataclass(frozen=True, slots=True)
class VoltageMetrics:
    """Summaries over fixed measurement points at each observed physical step.

    A nonconverged snapshot contributes no compliant points or timestep. Its
    finite supplied readings still appear in violation diagnostics, which must
    not be treated as valid power-flow results. ``complete`` requires an explicit
    expected horizon; it is false when that horizon is unspecified.
    Integrated violation sums all measurement-point violations times hours.
    """

    steps: int
    expected_steps: int | None
    points_per_step: int
    converged_steps: int
    complete: bool
    timestep_compliance_rate: float
    measurement_compliance_rate: float
    worst_violation_pu: float
    integrated_violation_pu_hours: float


def voltage_metrics(
    snapshots: Sequence[Sequence[float]],
    *,
    lower: float = 0.95,
    upper: float = 1.05,
    expected_steps: int | None = None,
    converged: Sequence[bool] | None = None,
    step_hours: float | Sequence[float] = 1.0,
) -> VoltageMetrics:
    """Summarize supplied voltages, rejecting ragged, empty and nonfinite data.

    Rates use observed steps, so an early trace can have a high rate while
    ``complete`` is false. Check completeness separately before ranking a run.
    No missing steps, failed solves or voltage values are silently imputed.
    """
    low = _finite_number(lower, "lower")
    high = _finite_number(upper, "upper")
    if low < 0 or high <= low:
        raise ValueError("voltage limits must satisfy 0 <= lower < upper")
    rows = _sequence(snapshots, "snapshots")
    if not rows:
        raise ValueError("snapshots must not be empty")
    size = len(_sequence(rows[0], "snapshots[0]"))
    voltages = tuple(
        _numeric_vector(row, f"snapshots[{index}]", expected_size=size)
        for index, row in enumerate(rows)
    )
    if any(value < 0 for row in voltages for value in row):
        raise ValueError("voltage magnitudes must be nonnegative")
    steps = len(voltages)
    if expected_steps is not None:
        _integer(expected_steps, "expected_steps", minimum=1)
        if steps > expected_steps:
            raise ValueError("snapshots exceed expected_steps")
    if converged is None:
        solved = (True,) * steps
    else:
        solved = tuple(_sequence(converged, "converged"))
        if len(solved) != steps or any(type(flag) is not bool for flag in solved):
            raise ValueError("converged must contain exactly one boolean per step")
    durations = _durations(step_hours, steps)
    valid_steps = 0
    valid_points = 0
    worst = 0.0
    integrated = []
    for row, success, duration in zip(voltages, solved, durations, strict=True):
        compliant = sum(low <= value <= high for value in row) if success else 0
        valid_points += compliant
        valid_steps += int(success and compliant == size)
        violations = tuple(max(low - value, value - high, 0.0) for value in row)
        worst = max(worst, *violations)
        integrated.append(_finite_sum(violations, "step voltage violation") * duration)
    return VoltageMetrics(
        steps=steps,
        expected_steps=expected_steps,
        points_per_step=size,
        converged_steps=sum(solved),
        complete=all(solved) and expected_steps is not None and steps == expected_steps,
        timestep_compliance_rate=valid_steps / steps,
        measurement_compliance_rate=valid_points / (steps * size),
        worst_violation_pu=worst,
        integrated_violation_pu_hours=_finite_sum(integrated, "integrated voltage violation"),
    )


def integrate_active_loss(
    losses: Sequence[float],
    *,
    step_hours: float | Sequence[float],
    power_unit: Literal["kW", "MW"],
    energy_unit: Literal["kWh", "MWh"],
) -> float:
    """Integrate nonnegative physical active losses with explicit power/energy units.

    Loss ratios, reactive-power penalties and sums of rewards are not inputs.
    The caller determines which network elements the physical loss includes.
    """
    if power_unit not in ("kW", "MW") or energy_unit not in ("kWh", "MWh"):
        raise ValueError("units must be power kW/MW and energy kWh/MWh")
    values = _numeric_vector(losses, "losses")
    if any(value < 0 for value in values):
        raise ValueError("physical active losses must be nonnegative")
    durations = _durations(step_hours, len(values))
    # Convert per item, so a representable MWh result need not overflow in kWh first.
    factor = {("kW", "kWh"): 1.0, ("kW", "MWh"): 0.001, ("MW", "kWh"): 1000.0, ("MW", "MWh"): 1.0}[
        (power_unit, energy_unit)
    ]
    energy = tuple(value * factor * hours for value, hours in zip(values, durations, strict=True))
    return _finite_sum(energy, "active loss energy")
