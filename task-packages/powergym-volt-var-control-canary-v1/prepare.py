#!/usr/bin/env python3
"""Prepare a private, hash-locked 34Bus case from verified PowerGym sources."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parents[1] / "src"))
from powergrid_bench.distribution.profiles import pack_profiles  # noqa: E402

COMMIT = "c9fc6d8357308a1f2bd2389474b56089c2a6bd78"
HASHES = {
    "LoadShape1.CSV": "2150f57d6c185483a1210e9010e121a50e509e94ac21adb028c55d8be60469c8",
    "LoadShape2.CSV": "981d3ff3f78f57edcfafacf437a4dcfda70d1ad99ea8f8a46928a75fbff43de0",
    "LoadShape3.CSV": "17a5a62491f1725e9dde94388bb5fcfe1fa429413fad43d977436e3d544f62be",
}


def prepare(source: Path, destination: Path) -> dict:
    """Copy only trusted assets and freeze profile zero; never select by score."""
    source = source.resolve(strict=True)
    source_lock = json.loads((ROOT / "source-lock.json").read_text())
    if source_lock["commit"] != COMMIT:
        raise ValueError("source lock commit differs from the declared release")
    for name, digest in source_lock["files"].items():
        path = source / name
        if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError(f"source asset hash mismatch: {name}")
    feeder = source / "systems/34Bus"
    paths = [feeder / "loadshape" / name for name in HASHES]
    for path in paths:
        if hashlib.sha256(path.read_bytes()).hexdigest() != HASHES[path.name]:
            raise ValueError(f"source hash mismatch: {path.name}")
    model = feeder / "ieee34Mod1_daily.dss"
    names = re.findall(r"^new load\.([^\s]+)", model.read_text(), re.I | re.M)
    if len(names) != 68 or len(set(name.lower() for name in names)) != 68:
        raise ValueError("expected 68 distinct native 34Bus daily loads")
    packed = pack_profiles(paths, load_count=len(names), horizon=24)
    if destination.exists():
        raise FileExistsError("refusing to overwrite an existing prepared case")
    destination.mkdir(parents=True, mode=0o700)
    destination.chmod(0o700)
    for name in source_lock["files"]:
        if name.startswith("systems/34Bus/"):
            target = destination / "34Bus" / Path(name).relative_to("systems/34Bus")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / name, target)
    shutil.copyfile(source / "LICENSE", destination / "UPSTREAM-LICENSE")
    # Compiling the original feeder requires these named curves. Snapshot mode
    # then sets explicit kW/kvar multipliers, so the DSS clock cannot shift rows.
    (destination / "34Bus/loadshape.dss").write_text(
        "".join(f"New Loadshape.loadshape_{name} npts=1 interval=1 mult=(1)\n" for name in names)
    )
    packing = packed.manifest
    for item in packing["sources"]:
        item["declared_path"] = str(Path(item["declared_path"]).relative_to(source))
        del item["resolved_path"]
    case = {
        "schema_version": "powergym-canary-case-1",
        "id": "34Bus-explicit-order-profile-000-energy-neutral-v1",
        "upstream_commit": COMMIT,
        "track": "powergym-energy-neutral-canary-v1",
        "horizon": 24,
        "step_hours": 1.0,
        "profile_index": 0,
        "scale": 1.0,
        "load_names": names,
        "multipliers": packed.profiles[0],
        "initial_soc": [1.0, 1.0],
        "terminal_energy_tolerance_kwh": 1.0,
        "metric": "powergym_canary_quality",
        "quality_formula": (
            "1/(1+voltage_violation_pu_hours+active_loss_kwh/1000+(cap_switches+tap_moves)/33)"
        ),
        "packing": packing,
        "candidate_episode_timeout_sec": 30,
        "candidate_step_timeout_sec": 1,
    }
    case_bytes = (json.dumps(case, indent=2, allow_nan=False) + "\n").encode()
    (destination / "case.json").write_bytes(case_bytes)
    files = {
        str(path.relative_to(destination)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(destination.rglob("*"))
        if path.is_file()
    }
    receipt = {"source_commit": COMMIT, "case_id": case["id"], "files": files}
    (destination / "data-lock.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return {
        "case_id": case["id"],
        "case_sha256": files["case.json"],
        "profile_count": packing["profile_count"],
        "loads": len(names),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "tests/data")
    args = parser.parse_args()
    print(json.dumps(prepare(args.source, args.output)))
