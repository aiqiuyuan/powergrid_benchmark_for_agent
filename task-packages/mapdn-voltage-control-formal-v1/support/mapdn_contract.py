"""Immutable public specification and trusted fixed-case identity; no target arrays."""

from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path

CASE_ID = "mapdn33-2012-02-03"
METRIC = "mapdn33_formal_quality_v1"
POOL_SHA256 = "69843ffcb35df4fb5d518f15648e0fffd7a78dc68668795ee912c005c013aebc"
MODEL_SHA256 = "b9452fa9896fc709258edd4cb7c431aec2ef348a090fd4184ada21dc821d3ef3"
TRAJECTORY_SHA256 = "da97c832399cdea127cd86be119b5cd93c55c92fb00dc4015658286ef0c1c65b"
CAPACITIES = [
    2.203309317604897,
    2.203309317604897,
    2.140855980289681,
    3.59060960131402,
    0.33415148573988346,
    0.33415148573988346,
]
SOURCE_SHA256 = {
    "model.p": MODEL_SHA256,
    "pv_active.csv": "a5d64f59e8e291f366768d601f16fe95662a5d25ccba86f21d31d04e940db9ef",
    "load_active.csv": "35c7657e886e46d8f2685540db1ee0ae327ec9446e21270217bbde190fc2365f",
    "load_reactive.csv": "0f296701a1f01be68cc63b19dc3787baa2883e101979dd5c5acc9e89b280cdc3",
}
QUALITY = (
    "invalid/incomplete=0; all 15840 bus-time voltage points compliant: "
    "0.5+0.5/(1+actual_loss_mwh); otherwise 0.5*bus_time_compliance"
)


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()


def expected_manifest() -> dict:
    """Return a fresh deterministic identity independent of local preparation paths."""
    return {
        "schema": "mapdn-formal-case-v1",
        "case_id": CASE_ID,
        "purpose": "fixed-case-formal-development-and-independent-terminal-replay",
        "upstream_source_commit": "6895f1f0630b112745a3f681d7685d454407f9cb",
        "dataset_commit": "a41d8c269e402a827d36d9a153a4bce73a990e53",
        "selection_pool_sha256": POOL_SHA256,
        "source_sha256": copy.deepcopy(SOURCE_SHA256),
        "complete_archive_sha256_verified": False,
        "files": {"model.p": MODEL_SHA256, "trajectory.json": TRAJECTORY_SHA256},
        "horizon": 480,
        "interval_hours": 0.05,
        "first_timestamp": "2012-02-03T00:00:00",
        "last_timestamp": "2012-02-03T23:57:00",
        "selection": (
            "maximum daily source load MWh candidate; qualified and frozen "
            "before formal development"
        ),
        "selection_uses_controller_results": True,
        "capacity_definition": "1.2 times each complete source PV CSV column maximum",
        "pv_scale": 1.0,
        "demand_scale": 1.0,
        "noise": "none",
        "initial_actions": [0.0] * 6,
        "apparent_power_mva": CAPACITIES.copy(),
        "normalized_action_bound": 0.8,
        "bus_order": list(range(33)),
        "load_order": list(range(32)),
        "pv_order": list(range(6)),
        "voltage_bounds_pu": [0.95, 1.05],
        "voltage_tolerance_pu": 1e-9,
        "power_balance_tolerance_mw": 1e-7,
        "quality": QUALITY,
        "pf": {"algorithm": "nr", "numba": False, "tolerance_mva": 1e-9, "max_iteration": 30},
        "runner_semantics": (
            "current exogenous + previous normalized action -> PF -> local "
            "observation -> validated actions -> PF -> score; "
            "exactly 480 intervals"
        ),
        "information": (
            "one current regional observation per PV per interval; private "
            "history; no shared state or within-snapshot simulator queries"
        ),
        "starter": {
            "name": "one_step_relaxed",
            "source_curve_slope": 20.0,
            "source_curve_clip": [-1.0, 1.0],
            "action_clip": [-0.8, 0.8],
            "relaxation": 0.1,
        },
    }


def validate_case(case: Path) -> dict:
    expected = expected_manifest()
    manifest_path = case / "manifest.json"
    if manifest_path.read_bytes() != json_bytes(expected):
        raise ValueError("case manifest differs from the immutable formal contract")
    for name, digest in expected["files"].items():
        if sha256(case / name) != digest:
            raise ValueError(f"formal case checksum mismatch: {name}")
    return expected


def quality(*, valid: bool, compliant_points: int, loss_mwh: float) -> float:
    """Safety tier uses exact counts; Q effort never enters the objective."""
    if (
        type(compliant_points) is not int
        or not 0 <= compliant_points <= 480 * 33
        or not math.isfinite(loss_mwh)
        or loss_mwh < 0
    ):
        raise ValueError("invalid physical score inputs")
    if not valid:
        return 0.0
    if compliant_points == 480 * 33:
        return 0.5 + 0.5 / (1 + loss_mwh)
    return 0.5 * compliant_points / (480 * 33)
