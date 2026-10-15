"""Deterministic PowerGym profile packing for trusted evaluator preparation.

The upstream allocation is load-major, then episode-major, then step-major:
global row = (load_index * profile_count + profile_index) * horizon + step.
An explicit source order replaces upstream's unsorted directory discovery.
Packed profiles do not establish calendar days or independent source series.
No simulator, complete task score, scaling or filesystem mutation is provided.
"""

import csv
import hashlib
import io
import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .common import _integer, _sequence


@dataclass(frozen=True, slots=True)
class PackedProfiles:
    """Immutable values indexed [profile][load][step] and a copied receipt.

    ``manifest`` returns a fresh JSON-compatible dictionary so edits to a
    caller's receipt cannot change the source-to-value mapping stored here.
    Raw source hashes refer to bytes; the packed hash refers to canonical
    compact JSON of the nested finite float tuples, without a trailing newline.
    """

    profiles: tuple[tuple[tuple[float, ...], ...], ...]
    _manifest_json: str

    @property
    def manifest(self) -> dict[str, object]:
        return json.loads(self._manifest_json)


@dataclass(frozen=True, slots=True)
class _Source:
    index: int
    declared_path: str
    resolved_path: str
    sha256: str
    values: tuple[float, ...]
    start: int

    @property
    def end(self) -> int:
        return self.start + len(self.values)

    def receipt(self) -> dict[str, object]:
        return {
            "source_index": self.index,
            "declared_path": self.declared_path,
            "resolved_path": self.resolved_path,
            "sha256": self.sha256,
            "row_count": len(self.values),
            "global_rows": [self.start, self.end],
        }


def _read_values(path: Path) -> tuple[tuple[float, ...], str]:
    try:
        raw = path.read_bytes()
        text = raw.decode("utf-8-sig")
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"cannot read UTF-8 profile file: {path}") from exc
    values = []
    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    try:
        for row_index, row in enumerate(reader, start=1):
            if len(row) != 1 or reader.line_num != row_index:
                raise ValueError("each physical source row must contain one numeric CSV field")
            try:
                value = float(row[0])
            except (ValueError, OverflowError) as exc:
                raise ValueError(f"invalid profile number at {path}:{row_index}") from exc
            if not math.isfinite(value):
                raise ValueError(f"profile number must be finite at {path}:{row_index}")
            values.append(value)
    except csv.Error as exc:
        raise ValueError(f"malformed profile CSV: {path}") from exc
    if not values:
        raise ValueError(f"profile file must contain numeric rows: {path}")
    return tuple(values), hashlib.sha256(raw).hexdigest()


def _read_sources(paths: Sequence[str | Path]) -> tuple[_Source, ...]:
    declared = _sequence(paths, "paths")
    if not declared:
        raise ValueError("paths must be a nonempty declared ordered sequence")
    seen = set()
    sources = []
    start = 0
    for index, value in enumerate(declared):
        if not isinstance(value, (str, Path)) or not str(value):
            raise ValueError("each source path must be a nonempty string or Path")
        try:
            path = Path(value).resolve(strict=True)
        except (OSError, ValueError) as exc:
            raise ValueError(f"profile source does not resolve: {value}") from exc
        if not path.is_file():
            raise ValueError(f"profile source must be a regular file: {value}")
        if path in seen:
            raise ValueError(f"duplicate resolved source path: {value}")
        seen.add(path)
        numbers, digest = _read_values(path)
        sources.append(_Source(index, str(value), str(path), digest, numbers, start))
        start += len(numbers)
    return tuple(sources)


def _segments(
    sources: Sequence[_Source], start: int, end: int, *, with_steps: bool = False
) -> list[dict[str, object]]:
    result = []
    for source in sources:
        left, right = max(start, source.start), min(end, source.end)
        if left >= right:
            continue
        segment: dict[str, object] = {
            "source_index": source.index,
            "source_rows": [left - source.start + 1, right - source.start],
        }
        if with_steps:
            segment["step_rows"] = [left - start, right - start]
        result.append(segment)
    return result


def pack_profiles(
    paths: Sequence[str | Path], *, load_count: int, horizon: int = 24
) -> PackedProfiles:
    """Pack declared single-column CSVs using upstream's allocation, without writes.

    Sources must be nonempty UTF-8 numeric CSVs with exactly one finite number
    on each physical row. Blank rows, headers and multiline fields are rejected
    rather than silently filtered, preserving traceable physical row numbers.
    Negative finite numbers are preserved; physical multiplier bounds require
    a separately declared task policy. Duplicate resolved paths are rejected.

    A complete profile contains ``load_count * horizon`` values. The unused
    tail is recorded, never reassigned or padded. Global/step ranges are
    zero-based half-open; source ranges are one-based inclusive. This helper
    neither infers dates nor verifies chronological independence or licenses.
    """
    loads = _integer(load_count, "load_count", minimum=1)
    steps = _integer(horizon, "horizon", minimum=1)
    sources = _read_sources(paths)
    values = tuple(value for source in sources for value in source.values)
    profile_count = len(values) // (loads * steps)
    if profile_count == 0:
        raise ValueError("not enough source rows for one complete profile")
    used = profile_count * loads * steps
    profiles = []
    assignments = []
    for profile_index in range(profile_count):
        profile = []
        for load_index in range(loads):
            start = (load_index * profile_count + profile_index) * steps
            end = start + steps
            profile.append(values[start:end])
            assignments.append(
                {
                    "profile_index": profile_index,
                    "load_index": load_index,
                    "global_rows": [start, end],
                    "source_segments": _segments(sources, start, end, with_steps=True),
                }
            )
        profiles.append(tuple(profile))
    packed = tuple(profiles)
    payload = json.dumps(packed, separators=(",", ":"), allow_nan=False).encode("utf-8")
    manifest = {
        "schema_version": "powergym-profile-packing-1.0",
        "status": "trusted-preparation-only",
        "release_ready": False,
        "calendar_provenance_verified": False,
        "source_order": "explicit-argument-order",
        "packing_order": "load-major/profile-major/step-major",
        "range_convention": {
            "global_rows": "zero-based-half-open",
            "source_rows": "one-based-inclusive",
            "step_rows": "zero-based-half-open",
        },
        "load_count": loads,
        "horizon": steps,
        "profile_count": profile_count,
        "source_rows": len(values),
        "used_rows": used,
        "unused_rows": len(values) - used,
        "sources": [source.receipt() for source in sources],
        "assignments": assignments,
        "unused_source_segments": _segments(sources, used, len(values)),
        "packed_values_sha256": hashlib.sha256(payload).hexdigest(),
    }
    return PackedProfiles(packed, json.dumps(manifest, sort_keys=True, allow_nan=False))
