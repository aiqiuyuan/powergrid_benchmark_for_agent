"""Persisted UTC deadlines; the controller must supply a trusted host clock."""

import math
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class RunClock:
    started_at: float
    deadline_at: float
    duration_seconds: float | None = None

    def __post_init__(self) -> None:
        if (
            not math.isfinite(self.started_at)
            or not math.isfinite(self.deadline_at)
            or self.deadline_at <= self.started_at
        ):
            raise ValueError("Clock needs finite timestamps and a positive duration")
        duration = (
            self.deadline_at - self.started_at
            if self.duration_seconds is None
            else self.duration_seconds
        )
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError("Clock duration must be finite and positive")
        if self.duration_seconds is not None and self.deadline_at != self.started_at + duration:
            raise ValueError("Persisted clock duration disagrees with its deadline")
        object.__setattr__(self, "duration_seconds", duration)

    @classmethod
    def start(cls, seconds: float, *, now: float | None = None) -> "RunClock":
        if isinstance(seconds, bool) or not math.isfinite(seconds) or seconds <= 0:
            raise ValueError("Development duration must be finite and positive")
        started = time.time() if now is None else float(now)
        return cls(started, started + seconds, seconds)

    def remaining(self, now: float | None = None) -> float:
        current = time.time() if now is None else float(now)
        if not math.isfinite(current):
            raise ValueError("Clock observation must be finite")
        return max(0.0, self.deadline_at - current)

    def expired(self, now: float | None = None) -> bool:
        return self.remaining(now) == 0

    def to_dict(self) -> dict[str, float]:
        return {
            "started_at": self.started_at,
            "deadline_at": self.deadline_at,
            "duration_seconds": self.duration_seconds,
        }

    @classmethod
    def from_dict(cls, value: dict[str, float]) -> "RunClock":
        return cls(value["started_at"], value["deadline_at"], value.get("duration_seconds"))
