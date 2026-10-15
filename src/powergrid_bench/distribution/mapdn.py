"""MAPDN action checks and structural observation projection, without Pandapower."""

import math
from collections.abc import Mapping, Sequence
from numbers import Real

from .common import _finite_number, _integer, _numeric_vector, _sequence


def _bounds(bound: object, size: int) -> tuple[float, ...]:
    values = (
        (_finite_number(bound, "bound"),) * size
        if isinstance(bound, Real)
        else _numeric_vector(bound, "bound", expected_size=size)
    )
    if any(not 0 < value <= 1 for value in values):
        raise ValueError("each normalized bound must satisfy 0 < bound <= 1")
    return values


def validate_actions(
    actions: Sequence[float], *, expected_size: int, bound: float | Sequence[float]
) -> tuple[float, ...]:
    """Reject malformed or out-of-bound actions instead of clipping them silently."""
    size = _integer(expected_size, "expected_size", minimum=1)
    values = _numeric_vector(actions, "actions", expected_size=size)
    limits = _bounds(bound, size)
    if any(abs(value) > limit for value, limit in zip(values, limits, strict=True)):
        raise ValueError("MAPDN action exceeds its normalized bound")
    return values


def reactive_power(
    actions: Sequence[float],
    *,
    active_power: Sequence[float],
    apparent_power: Sequence[float],
    bound: float | Sequence[float],
) -> tuple[float, ...]:
    """Compute Q=a*sqrt(Smax**2-P**2) in the supplied common power unit.

    PV real powers must satisfy 0 <= P <= Smax. Bounds cannot exceed one;
    capability violations and impossible capacities are errors, not clipping.
    """
    active = _numeric_vector(active_power, "active_power")
    apparent = _numeric_vector(apparent_power, "apparent_power", expected_size=len(active))
    values = validate_actions(actions, expected_size=len(active), bound=bound)
    output = []
    for action, power, capacity in zip(values, active, apparent, strict=True):
        if not 0 <= power <= capacity:
            raise ValueError("PV capability requires 0 <= active_power <= apparent_power")
        ratio = power / capacity if capacity else 0.0
        capability = capacity * math.sqrt((1.0 - ratio) * (1.0 + ratio))
        output.append(_finite_number(action * capability, "reactive power"))
    return tuple(output)


def _check_field(field: object) -> str:
    if not isinstance(field, str) or not field:
        raise ValueError("observation field names must be nonempty strings")
    normalized = field.lower().replace("-", "_")
    forbidden = {
        "env",
        "environment",
        "state",
        "all_observations",
        "observations",
        "all_load_profiles",
        "profiles",
        "trajectory",
        "target_profile",
        "reward",
        "score",
    }
    if "future" in normalized or "global" in normalized or normalized in forbidden:
        raise ValueError(f"forbidden observation field: {field}")
    return field


def _copy_observation(value: object) -> object:
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, Real):
        return _finite_number(value, "observation value")
    if isinstance(value, Mapping):
        return {_check_field(key): _copy_observation(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_copy_observation(item) for item in value]
    raise ValueError("observation values must be finite JSON-like data, never environment objects")


def project_actor_observations(
    observations: Sequence[Mapping[str, object]], *, allowed_fields: Sequence[str]
) -> tuple[dict[str, object], ...]:
    """Copy one allowlisted observation per actor, rejecting named forbidden data.

    Only a trusted adapter should call this with preconstructed local fields.
    It cannot detect global data encoded under innocuous field names, enforce
    processes/filesystem isolation, or prevent the caller sharing all outputs.
    The harness must send each isolated actor only its own resulting mapping.
    """
    fields = tuple(_check_field(field) for field in _sequence(allowed_fields, "allowed_fields"))
    if not fields or len(set(fields)) != len(fields):
        raise ValueError("allowed_fields must be nonempty and unique")
    actors = _sequence(observations, "observations")
    if not actors:
        raise ValueError("observations must not be empty")
    output = []
    for observation in actors:
        if not isinstance(observation, Mapping):
            raise ValueError("each actor observation must be a mapping")
        for field in observation:
            _check_field(field)
        if any(field not in observation for field in fields):
            raise ValueError("actor observation is missing an allowlisted field")
        output.append({field: _copy_observation(observation[field]) for field in fields})
    return tuple(output)


def droop_action(voltage: float, *, gain: float, bound: float, target: float = 1.0) -> float:
    """A single local, bounded proportional rule for starters and toy examples."""
    measured = _finite_number(voltage, "voltage")
    reference = _finite_number(target, "target")
    slope = _finite_number(gain, "gain")
    limit = _bounds(bound, 1)[0]
    if measured < 0 or reference <= 0 or slope < 0:
        raise ValueError("droop requires voltage >= 0, target > 0 and gain >= 0")
    return max(-limit, min(limit, slope * (reference - measured)))
