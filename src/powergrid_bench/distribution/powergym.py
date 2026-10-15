"""PowerGym action/energy checks without Gym or OpenDSS imports."""

import math
from collections.abc import Sequence

from .common import _finite_number, _integer, _numeric_vector, _sequence, integrate_active_loss


def _battery_limit(battery_max: int) -> int:
    limit = _integer(battery_max, "battery_max", minimum=2)
    if limit % 2:
        raise ValueError("battery_max must be even so the discrete action set contains zero power")
    return limit


def validate_actions(
    actions: Sequence[int | float],
    *,
    capacitor_count: int,
    regulator_count: int,
    battery_count: int,
    continuous_batteries: bool = False,
    tap_max: int = 32,
    battery_max: int = 32,
) -> tuple[int | float, ...]:
    """Validate flat [capacitors, regulators, batteries] actions before mutation.

    Caps are integers 0/1, taps are integers 0..tap_max; discrete batteries
    are integer 0..battery_max, continuous batteries are finite -1..1. Booleans
    and integral-looking floats are not discrete actions. No clipping occurs.
    """
    caps = _integer(capacitor_count, "capacitor_count")
    regulators = _integer(regulator_count, "regulator_count")
    batteries = _integer(battery_count, "battery_count")
    taps = _integer(tap_max, "tap_max")
    battery_limit = _battery_limit(battery_max)
    if type(continuous_batteries) is not bool:
        raise ValueError("continuous_batteries must be a boolean")
    values = _sequence(actions, "actions")
    if len(values) != caps + regulators + batteries:
        raise ValueError("action shape does not match device counts")
    output = []
    for index, value in enumerate(values):
        if index < caps:
            checked = _integer(value, f"actions[{index}]")
            limit = 1
        elif index < caps + regulators:
            checked = _integer(value, f"actions[{index}]")
            limit = taps
        elif continuous_batteries:
            checked = _finite_number(value, f"actions[{index}]")
            if not -1 <= checked <= 1:
                raise ValueError("continuous battery action must lie in [-1, 1]")
            output.append(checked)
            continue
        else:
            checked = _integer(value, f"actions[{index}]")
            limit = battery_limit
        if checked > limit:
            raise ValueError(f"actions[{index}] exceeds device action bound")
        output.append(checked)
    return tuple(output)


def idle_action(
    capacitor_states: Sequence[int],
    regulator_taps: Sequence[int],
    *,
    battery_count: int,
    continuous_batteries: bool = False,
    tap_max: int = 32,
    battery_max: int = 32,
) -> tuple[int | float, ...]:
    """Preserve capacitor/tap settings; default discrete battery idle is 16.

    A zero vector is not a hold action. Continuous battery idle is zero;
    discrete idle is the midpoint of the declared even maximum action index.
    """
    caps = tuple(_sequence(capacitor_states, "capacitor_states"))
    taps = tuple(_sequence(regulator_taps, "regulator_taps"))
    batteries = _integer(battery_count, "battery_count")
    limit = _battery_limit(battery_max)
    idle = 0.0 if continuous_batteries else limit // 2
    return validate_actions(
        caps + taps + (idle,) * batteries,
        capacitor_count=len(caps),
        regulator_count=len(taps),
        battery_count=batteries,
        continuous_batteries=continuous_batteries,
        tap_max=tap_max,
        battery_max=battery_max,
    )


def terminal_soc_valid(
    initial_soc: Sequence[float], final_soc: Sequence[float], *, tolerance: float
) -> bool:
    """Check a declared terminal SOC constraint; not upstream's soft SOC reward.

    SOC is a fraction in [0,1]. A 1e-12 relative comparison at the tolerance
    boundary accommodates roundoff; zero tolerance still requires equality.
    Empty vectors are valid for a declared case with no batteries.
    """
    threshold = _finite_number(tolerance, "tolerance")
    if not 0 <= threshold <= 1:
        raise ValueError("SOC tolerance must lie in [0, 1]")
    initial = _numeric_vector(initial_soc, "initial_soc", allow_empty=True)
    final = _numeric_vector(final_soc, "final_soc", expected_size=len(initial), allow_empty=True)
    if any(not 0 <= value <= 1 for value in initial + final):
        raise ValueError("SOC must lie in [0, 1]")
    return all(
        abs(start - end) <= threshold
        or math.isclose(abs(start - end), threshold, rel_tol=1e-12, abs_tol=0.0)
        for start, end in zip(initial, final, strict=True)
    )


def active_loss_kwh(
    losses_kw: Sequence[float], *, step_hours: float | Sequence[float] = 1.0
) -> float:
    """Integrate actual circuit active losses in kW to kWh, never a loss ratio."""
    return integrate_active_loss(
        losses_kw, step_hours=step_hours, power_unit="kW", energy_unit="kWh"
    )
