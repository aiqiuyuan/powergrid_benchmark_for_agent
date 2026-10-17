"""Bounded JSON artifacts; candidate code is never imported by the grader."""

from __future__ import annotations

import json
import math
import stat
from pathlib import Path

MAX_BYTES = 16 << 20


def reject_duplicates(pairs: list) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key: " + key)
        result[key] = value
    return result


def load(path: Path) -> dict:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError("Ordinary, link-free JSON required")
    if not 0 < info.st_size <= MAX_BYTES:
        raise ValueError("JSON artifact is empty or oversized")
    result = json.loads(path.read_text(), object_pairs_hook=reject_duplicates)
    if not isinstance(result, dict):
        raise ValueError("JSON object required")
    return result


def series(value: object, length: int, binary: bool = False) -> list[float]:
    if not isinstance(value, list) or len(value) != length:
        raise ValueError("Incorrect time-series length")
    result = []
    for number in value:
        if (
            isinstance(number, bool)
            or not isinstance(number, (int, float))
            or not math.isfinite(number)
        ):
            raise ValueError("Finite numeric values required")
        if binary and number not in (0, 1):
            raise ValueError("Commitment must be exactly 0 or 1")
        result.append(float(number))
    return result


def fields(value: dict, expected: set[str]) -> None:
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError("Missing or unexpected keys: expected " + str(sorted(expected)))


def write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)
