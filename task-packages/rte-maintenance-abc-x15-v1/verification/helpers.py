"""Portable synthetic fixtures; no energy datasets or framework installation needed."""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

TASK = Path(__file__).resolve().parents[1]
CHECKER_SHA256 = "9f1d7be2c5610d79ccbdd762c5c8736308fddc34e1ab39e6a6619be761f8322a"
PUBLIC_IDS = {f"{group}_{number:02d}" for group in "ABC" for number in range(1, 16)}
FEEDBACK_IDS = {f"X_{number:02d}" for number in range(1, 16)}
PYTHON = sys.executable


@contextlib.contextmanager
def patch_modules(replacements: dict):
    """Patch only named modules; do not unload freshly imported NumPy extensions."""
    missing = object()
    previous = {name: sys.modules.get(name, missing) for name in replacements}
    sys.modules.update(replacements)
    try:
        yield
    finally:
        for name, value in previous.items():
            if value is missing:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = value


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def load_task_module(relative: str, name: str):
    path = TASK / relative
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load task module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def tiny_instance(case_id: str, **extra) -> dict:
    """A real one-job official-schema scheduling problem, not a score stub."""
    return {
        "Resources": {"crew": {"min": [0], "max": [1]}},
        "Seasons": {"full": [1]},
        "Interventions": {
            "job": {
                "tmax": 1,
                "Delta": [1],
                "workload": {"crew": {"1": {"1": 0.5}}},
                "risk": {"1": {"1": [1.0, 3.0]}},
            },
        },
        "Exclusions": {},
        "T": 1,
        "Scenarios_number": [2],
        "Quantile": 0.5,
        "Alpha": 0.5,
        "_case_id": case_id,
        **extra,
    }


def synthetic_manifest(root: Path, cases: list[dict], *, seconds: float, workers: int) -> Path:
    rows = []
    for index, instance in enumerate(cases):
        path = root / f"case-{index}.json"
        path.write_text(json.dumps(instance))
        rows.append(
            {"id": instance["_case_id"], "path": path.name, "sha256": digest(path), "scale": 2.0}
        )
    manifest = root / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "protocol": "abc-x15-tiny-integration",
                "split": "feedback",
                "seconds_per_case": seconds,
                "workers": workers,
                "checker_timeout_seconds": 1,
                "staging_timeout_seconds": 1,
                "address_space_bytes": 16 * 1024**3,
                "seed": 2020,
                "cases": rows,
            }
        )
    )
    return manifest
