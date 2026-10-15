#!/usr/bin/env python3
"""Freeze the earliest complete aligned MAPDN 33-bus day, without added noise."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

import numpy as np
import pandapower as pp
import pandas as pd

FILES = ("pv_active.csv", "load_active.csv", "load_reactive.csv")
CASE_ID = "mapdn33-first-complete-day-causal-v1"


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def freeze(raw: Path, output: Path) -> dict:
    receipt = json.loads((raw / "preparation-receipt.json").read_text())
    if receipt["dataset_commit"] != "a41d8c269e402a827d36d9a153a4bce73a990e53":
        raise ValueError("unexpected dataset revision")
    verified = {Path(row["member"]).name: row for row in receipt["members"]}
    for name in ("model.p", *FILES):
        if sha256(raw / name) != verified[name]["sha256"]:
            raise ValueError(f"source member checksum mismatch: {name}")
    net = pp.from_pickle(raw / "model.p")
    if (len(net.bus), len(net.load), len(net.sgen)) != (33, 32, 6):
        raise ValueError("this canary requires the original 33-bus network")
    frames, capacities = [], None
    for name in FILES:
        frame = pd.read_csv(raw / name, index_col=0, parse_dates=True)
        if (
            not isinstance(frame.index, pd.DatetimeIndex)
            or not frame.index.is_unique
            or not frame.index.is_monotonic_increasing
        ):
            raise ValueError("source time index must be unique datetimes")
        if not np.isfinite(frame.to_numpy()).all() or (frame.to_numpy() < 0).any():
            raise ValueError("nonfinite or negative source powers are unsupported")
        if name == "pv_active.csv":
            capacities = (1.2 * frame.max().to_numpy()).tolist()
        frames.append(frame)
    if not all(frame.index.equals(frames[0].index) for frame in frames[1:]):
        raise ValueError("source PV and load time indices do not align")
    if [len(frame.columns) for frame in frames] != [6, 32, 32]:
        raise ValueError("source columns do not match frozen network device order")
    starts = frames[0].index[frames[0].index == frames[0].index.normalize()]
    selected = None
    for start in starts:
        index = pd.date_range(start, periods=480, freq="3min")
        if index.isin(frames[0].index).all():
            selected = index
            break
    if selected is None:
        raise ValueError("no aligned complete 480-interval day exists")
    if output.exists() and any(output.iterdir()):
        raise ValueError("refusing to replace an existing frozen bundle")
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    output.chmod(0o700)
    shutil.copyfile(raw / "model.p", output / "model.p")
    arrays = {
        name.split(".")[0]: frame.loc[selected].to_numpy(dtype=float).tolist()
        for name, frame in zip(FILES, frames, strict=True)
    }
    trajectory = {"timestamps": [stamp.isoformat() for stamp in selected], **arrays}
    (output / "trajectory.json").write_text(json.dumps(trajectory, allow_nan=False) + "\n")
    manifest = {
        "schema": "mapdn-canary-case-v1",
        "case_id": CASE_ID,
        "purpose": "integration-calibration-not-certified-hard-case",
        "upstream_source_commit": "6895f1f0630b112745a3f681d7685d454407f9cb",
        "dataset_commit": receipt["dataset_commit"],
        "source_members": verified,
        "complete_archive_sha256_verified": False,
        "files": {name: sha256(output / name) for name in ("model.p", "trajectory.json")},
        "horizon": 480,
        "interval_hours": 0.05,
        "first_timestamp": selected[0].isoformat(),
        "last_timestamp": selected[-1].isoformat(),
        "source_row_start_zero_based": int(frames[0].index.get_loc(selected[0])),
        "source_row_stop_exclusive": int(frames[0].index.get_loc(selected[-1])) + 1,
        "capacity_definition": "1.2 times each complete source PV CSV column maximum",
        "selection": "earliest complete aligned midnight-to-midnight source day",
        "pv_scale": 1.0,
        "demand_scale": 1.0,
        "noise": "none",
        "initial_actions": [0.0] * 6,
        "apparent_power_mva": capacities,
        "normalized_action_bound": 0.8,
        "bus_order": net.bus.index.tolist(),
        "load_order": net.load.index.tolist(),
        "pv_order": net.sgen.index.tolist(),
        "voltage_bounds_pu": [0.95, 1.05],
        "voltage_tolerance_pu": 1e-9,
        "power_balance_tolerance_mw": 1e-7,
        "quality": ("0.8 * bus_time_compliance + 0.2 / (1 + actual_loss_mwh); invalid=0"),
        "pf": {"algorithm": "nr", "numba": False, "tolerance_mva": 1e-9, "max_iteration": 30},
        "runner_semantics": (
            "current exogenous + previous normalized action -> PF -> local observation"
            " -> validated actions -> PF -> score, repeated exactly 480 intervals"
        ),
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2, allow_nan=False) + "\n")
    for path in output.iterdir():
        path.chmod(0o600)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = freeze(args.raw, args.output)
    print(
        json.dumps(
            {key: manifest[key] for key in ("case_id", "horizon", "first_timestamp", "files")},
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
