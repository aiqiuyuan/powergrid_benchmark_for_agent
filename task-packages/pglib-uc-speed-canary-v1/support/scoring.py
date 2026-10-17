"""Reference-quality scoring; consumes only independently validated snapshots."""

from __future__ import annotations

import math


class ReferenceError(RuntimeError):
    """Reference preparation is inconsistent; do not score the candidate."""


def replay(
    snapshots: list[tuple[float, float]],
    *,
    status: str,
    seconds: float,
    upper: float,
    lower: float,
    epsilon: float,
) -> dict:
    if (
        not all(math.isfinite(x) for x in (seconds, upper, lower, epsilon))
        or seconds <= 0
        or epsilon <= 0
        or upper < lower
    ):
        raise ReferenceError("Invalid reference or execution budget")
    guard = max(0.01, 1e-6 * abs(upper))
    if (upper - lower) / max(1, abs(upper)) > epsilon / 10:
        raise ReferenceError("Reference is too loose for this quality target")
    accepted = []
    for received, cost in snapshots:
        if not math.isfinite(received) or not math.isfinite(cost) or received < 0:
            raise ValueError("Invalid trusted snapshot measurement")
        if received > seconds:
            continue
        if cost < lower - guard:
            raise ReferenceError("Verified cost materially below trusted bound")
        accepted.append((received, cost))
    feasible = bool(accepted) and status in {"OK", "DEADLINE"}
    hit_times = [
        t for t, cost in accepted if (cost + guard - lower) / max(1, abs(cost + guard)) <= epsilon
    ]
    hit = feasible and bool(hit_times)
    cost = min((cost for _, cost in accepted), default=None)
    gap = (cost - lower) / max(1, abs(cost)) if cost is not None else None
    return {
        "feasible": feasible,
        "target_hit": hit,
        "penalized_seconds": min(hit_times) if hit else 2 * seconds,
        "reference_gap": gap if feasible else None,
        "failure_category": None
        if feasible
        else ("no-feasible-snapshot" if status in {"OK", "DEADLINE"} else status.lower()),
    }


def aggregate(rows: list[dict], seconds: float, *, delivered: bool = True) -> dict:
    if not rows or not math.isfinite(seconds) or seconds <= 0:
        raise ValueError("Positive budget and nonempty replay set required")
    feasible = all(row["feasible"] for row in rows)
    penalty = sum(row["penalized_seconds"] for row in rows) / len(rows)
    if delivered:
        penalty = round(penalty, 3)
    # Round only the delivered penalty, then derive the delivered reward from it.
    reward = max(0.0, 1 - penalty / (2 * seconds)) if feasible else 0.0
    gap = sum(row["reference_gap"] for row in rows) / len(rows) if feasible else None
    if delivered and gap is not None:
        gap = round(gap, 6)
    hit = all(row["target_hit"] for row in rows)
    return {
        "status": "qualified-hit" if hit else ("qualified-miss" if feasible else "unqualified"),
        "feasible": feasible,
        "target_hit": hit,
        "penalized_seconds": penalty,
        "reference_gap": gap,
        "reward": reward,
        "failure_category": None if feasible else "candidate-failure",
    }
