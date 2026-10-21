#!/usr/bin/env python3
"""Freeze exogenous MAPDN dates, screen causal policies, then run full-day AC OPF.

This trusted preparation tool never changes the historical canary task or score.
Use a separate output directory per network. ``reference`` requires explicit case
IDs; an incomplete OPF series is retained as a failed reference, never filled in.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import shutil
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

FILES = ("pv_active.csv", "load_active.csv", "load_reactive.csv")
DATASET_COMMIT = "a41d8c269e402a827d36d9a153a4bce73a990e53"
REPOSITORY = Path(__file__).resolve().parents[2]
DEFAULT_PROTOCOL = REPOSITORY / "configs/distribution-case-selection-20261016.json"


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()


def write_once(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError(f"refusing to replace existing artifact: {path}")
        return
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.read_bytes() != data:
                raise ValueError(f"refusing to replace existing artifact: {path}") from None
    finally:
        temporary.unlink()


def write_pool(output: Path, pool: dict) -> str:
    payload = json_bytes(pool)
    digest = hashlib.sha256(payload).hexdigest()
    write_once(output / "pool.json", payload)
    write_once(output / "pool.sha256", (digest + "  pool.json\n").encode())
    return digest


def read_pool(output: Path) -> tuple[dict, str]:
    digest = sha256(output / "pool.json")
    if (output / "pool.sha256").read_text().split()[0] != digest:
        raise ValueError("frozen pool checksum mismatch")
    return json.loads((output / "pool.json").read_text()), digest


def runtime_versions() -> dict[str, str]:
    return {"python": platform.python_version(), **{
        name: importlib.metadata.version(name) for name in
        ("pandapower", "pandas", "numpy", "scipy")}}


def write_result(path: Path, result: dict) -> None:
    write_once(path, json_bytes(result))
    marker = path.with_suffix(path.suffix + ".sha256")
    write_once(marker, f"{sha256(path)}  {path.name}\n".encode())


def read_result(path: Path, expected: dict) -> dict:
    marker = path.with_suffix(path.suffix + ".sha256")
    fields = marker.read_text().split() if marker.is_file() else []
    if not fields or fields[0] != sha256(path):
        raise ValueError("saved result checksum is missing or mismatched")
    result = json.loads(path.read_text())
    if not isinstance(result, dict):
        raise ValueError("saved result is not a JSON object")
    for key, value in expected.items():
        if result.get(key) != value:
            raise ValueError(f"saved result does not match the current {key}")
    if "valid" in result:
        completed, steps = result.get("completed_intervals"), result.get("steps")
        metrics = result.get("metrics")
        if (not isinstance(result["valid"], bool) or type(completed) is not int
                or not 0 <= completed <= 480 or result.get("scheduled_intervals") != 480
                or not isinstance(steps, list) or len(steps) != completed
                or not isinstance(metrics, dict)):
            raise ValueError("saved result has inconsistent complete-day coverage")
        indices = [row.get("interval_index") for row in steps if isinstance(row, dict)]
        if (len(indices) != completed or any(type(index) is not int for index in indices)
                or len(set(indices)) != completed or any(not 0 <= i < 480 for i in indices)
                or metrics.get("metric_coverage") != completed / 480
                or metrics.get("actual_loss_mwh_is_partial") is not (completed != 480)):
            raise ValueError("saved result has inconsistent complete-day coverage")
        if result["valid"] and (completed != 480 or result.get("error") is not None
                                or indices != list(range(480))):
            raise ValueError("saved valid result has inconsistent complete-day coverage")
        if result.get("policy", {}).get("name") == "full_information_ac_opf":
            failures = result.get("failures")
            if (result.get("attempted_intervals") != 480 or not isinstance(failures, list)
                    or len(failures) + completed != 480 or (result["valid"] and failures)):
                raise ValueError("saved OPF result has inconsistent attempted interval coverage")
            failed_indices = [row.get("interval_index") for row in failures
                              if isinstance(row, dict)]
            if (len(failed_indices) != len(failures)
                    or any(type(index) is not int for index in failed_indices)
                    or sorted(indices + failed_indices) != list(range(480))):
                raise ValueError("saved OPF failures have inconsistent interval coverage")
    return result


def csv_chunks(path: Path, chunk_size: int = 48000):
    yield from pd.read_csv(path, index_col=0, parse_dates=True, chunksize=chunk_size)


def scan_csv(path: Path, columns: int, chunk_size: int = 48000) -> dict:
    """Bounded-memory validation and exogenous daily aggregation over the full CSV."""
    days, last, first, rows = {}, None, None, 0
    index_digest = hashlib.sha256()
    maxima = np.zeros(columns)
    for frame in csv_chunks(path, chunk_size):
        index = frame.index
        values = frame.to_numpy(dtype=float)
        if (not isinstance(index, pd.DatetimeIndex) or index.tz is not None
                or not index.is_unique or not index.is_monotonic_increasing
                or index.hasnans or (last is not None and index[0] <= last)):
            raise ValueError(f"source time index is not unique, ordered naive datetimes: {path}")
        if (values.shape[1] != columns or not np.isfinite(values).all()
                or (values < 0).any()):
            raise ValueError(f"source powers are nonfinite, negative or wrong device count: {path}")
        first = first or index[0]
        last = index[-1]
        rows += len(index)
        index_digest.update(index.asi8.astype("<i8").tobytes())
        maxima = np.maximum(maxima, values.max(axis=0))
        totals = values.sum(axis=1)
        table = pd.DataFrame({"total": totals, "time": index}, index=index)
        for date, group in table.groupby(index.normalize()):
            key = date.date().isoformat()
            row = days.setdefault(key, {"rows": 0, "mwh": 0.0, "peak_mw": 0.0,
                                        "aligned": True, "start": group.time.iloc[0],
                                        "stop": group.time.iloc[-1]})
            row["rows"] += len(group)
            row["mwh"] += float(group.total.sum()) * 0.05
            row["peak_mw"] = max(row["peak_mw"], float(group.total.max()))
            row["stop"] = group.time.iloc[-1]
            row["aligned"] &= bool((group.index.asi8 % (180 * 10**9) == 0).all())
    complete = {}
    for key, row in days.items():
        midnight = pd.Timestamp(key)
        if (row["rows"] == 480 and row["aligned"] and row["start"] == midnight
                and row["stop"] == midnight + pd.Timedelta(minutes=1437)):
            complete[key] = {"mwh": row["mwh"], "peak_mw": row["peak_mw"]}
    if first is None:
        raise ValueError(f"source CSV is empty: {path}")
    return {"complete_days": complete, "rows": rows, "index_sha256": index_digest.hexdigest(),
            "first_timestamp": first.isoformat(), "last_timestamp": last.isoformat(),
            "column_max_mw": maxima.tolist()}


def select_days(days: dict[str, dict]) -> dict[str, list[str]]:
    if not days:
        raise ValueError("no aligned complete 480-interval source day exists")
    ordered = sorted(days)
    year = pd.Timestamp(ordered[0]).year
    selected: dict[str, list[str]] = {}
    for quarter in range(1, 5):
        matching = [day for day in ordered if pd.Timestamp(day).year == year
                    and pd.Timestamp(day).quarter == quarter]
        if matching:
            selected.setdefault(matching[0], []).append(f"quarter_{quarter}_first_complete")
    for field, label in (("load_mwh", "maximum_daily_load_mwh"),
                         ("pv_mwh", "maximum_daily_pv_mwh")):
        day = min(ordered, key=lambda item: (-days[item][field], item))
        selected.setdefault(day, []).append(label)
    return dict(sorted(selected.items()))


def selected_trajectories(raw: Path, dates: list[str]) -> dict[str, dict]:
    selected = {day: {} for day in dates}
    for name in FILES:
        parts = {day: [] for day in dates}
        for chunk in csv_chunks(raw / name):
            day_labels = chunk.index.strftime("%Y-%m-%d")
            for day in dates:
                rows = chunk.loc[day_labels == day]
                if len(rows):
                    parts[day].append(rows)
        for day in dates:
            frame = pd.concat(parts[day])
            expected = pd.date_range(day, periods=480, freq="3min")
            if not frame.index.equals(expected):
                raise ValueError("a selected source day changed or is incomplete")
            selected[day][name.removesuffix(".csv")] = frame.to_numpy(dtype=float).tolist()
            selected[day]["timestamps"] = [stamp.isoformat() for stamp in expected]
    return selected


def freeze_pool(raw: Path, network: int, output: Path, protocol: Path) -> dict:
    import pandapower as pp
    from mapdn_baselines.simulation import validate_network

    if (output / "pool.json").exists():
        raise ValueError("pool already exists; use screen/reference to resume without replacing it")
    source_hashes = {name: sha256(raw / name) for name in ("model.p", *FILES)}
    receipt = json.loads((raw / "preparation-receipt.json").read_text())
    if receipt["dataset_commit"] != DATASET_COMMIT:
        raise ValueError("unexpected dataset revision")
    verified = {Path(row["member"]).name: row for row in receipt["members"]}
    if any(verified[name]["sha256"] != digest for name, digest in source_hashes.items()):
        raise ValueError("source checksum does not match preparation receipt")
    net = pp.from_pickle(raw / "model.p")
    validate_network(net, network)
    scans = {name: scan_csv(raw / name, count) for name, count in
             zip(FILES, (len(net.sgen), len(net.load), len(net.load)), strict=True)}
    pv, load, reactive = (scans[name] for name in FILES)
    if len({(scan["rows"], scan["index_sha256"]) for scan in scans.values()}) != 1:
        raise ValueError("source PV and load time indices do not align")
    common = set(pv["complete_days"]) & set(load["complete_days"]) & set(reactive["complete_days"])
    days = {day: {"load_mwh": load["complete_days"][day]["mwh"],
                  "pv_mwh": pv["complete_days"][day]["mwh"],
                  "peak_load_mw": load["complete_days"][day]["peak_mw"],
                  "peak_pv_mw": pv["complete_days"][day]["peak_mw"]} for day in sorted(common)}
    chosen = select_days(days)
    trajectories = selected_trajectories(raw, list(chosen))
    if any(sha256(raw / name) != digest for name, digest in source_hashes.items()):
        raise ValueError("source data changed during selection")
    model = output / "assets/model.p"
    model.parent.mkdir(parents=True, exist_ok=True)
    if model.exists() and sha256(model) != source_hashes["model.p"]:
        raise ValueError("existing model differs from source")
    shutil.copyfile(raw / "model.p", model)
    cases = []
    for day, reasons in chosen.items():
        case_id = f"mapdn{network}-{day}"
        path = output / "cases" / case_id / "trajectory.json"
        write_once(path, json_bytes(trajectories[day]))
        cases.append({"case_id": case_id, "date": day, "selection_reasons": reasons,
                      "exogenous_features": days[day], "trajectory_sha256": sha256(path)})
    pool = {"schema": "mapdn-exogenous-selection-pool-v1", "network": network,
            "protocol_sha256": sha256(protocol), "protocol_path": str(protocol.resolve()),
            "dataset_commit": DATASET_COMMIT, "source_members": verified,
            "source_sha256": source_hashes, "source_time_index_sha256": pv["index_sha256"],
            "source_rows": pv["rows"], "complete_source_days": len(common),
            "selection": "Q1-Q4 first complete day in earliest complete source year; "
                         "entire-source max daily demand MWh and PV MWh; "
                         "earliest tie; deduplicated",
            "selection_uses_controller_results": False, "noise": "none", "horizon": 480,
            "interval_hours": 0.05, "bus_count": len(net.bus), "pv_count": len(net.sgen),
            "apparent_power_mva": (1.2 * np.asarray(pv["column_max_mw"])).tolist(),
            "normalized_action_bound": {33: 0.8, 141: 0.6}[network],
            "voltage_bounds_pu": [0.95, 1.05], "cases": cases}
    digest = write_pool(output, pool)
    print(json.dumps({"stage": "freeze", "pool_sha256": digest, "cases": cases}), flush=True)
    return pool


def load_case(output: Path, pool: dict, case: dict):
    import pandapower as pp
    from mapdn_baselines.simulation import validate_network

    model = output / "assets/model.p"
    path = output / "cases" / case["case_id"] / "trajectory.json"
    if (sha256(model) != pool["source_sha256"]["model.p"]
            or sha256(path) != case["trajectory_sha256"]):
        raise ValueError("frozen model or trajectory checksum mismatch")
    trajectory = json.loads(path.read_text())
    for key, width in (("pv_active", pool["pv_count"]),
                       ("load_active", {33: 32, 141: 84}[pool["network"]]),
                       ("load_reactive", {33: 32, 141: 84}[pool["network"]])):
        values = np.asarray(trajectory[key])
        if values.shape != (480, width) or not np.isfinite(values).all() or (values < 0).any():
            raise ValueError("frozen trajectory has invalid powers or dimensions")
    expected = pd.date_range(case["date"], periods=480, freq="3min")
    if trajectory["timestamps"] != [stamp.isoformat() for stamp in expected]:
        raise ValueError("frozen trajectory does not cover a complete source day")
    net = pp.from_pickle(model)
    validate_network(net, pool["network"])
    return net, trajectory


def run_stage(output: Path, stage: str, gains: list[float], case_ids: list[str],
              protocol: Path, baselines: list[str] | None = None) -> dict:
    from mapdn_baselines.controllers import starter_path
    from mapdn_baselines.simulation import evaluate_local

    pool, pool_hash = read_pool(output)
    if pool["protocol_sha256"] != sha256(protocol):
        raise ValueError("protocol differs from the frozen pool")
    cases = [case for case in pool["cases"] if not case_ids or case["case_id"] in case_ids]
    if set(case_ids) - {case["case_id"] for case in cases}:
        raise ValueError("requested case ID is outside the frozen pool")
    policies = [{"name": "zero_q"}, {"name": "original_starter"}]
    policies.extend({"name": "grid_droop", "gain": gain} for gain in gains)
    if baselines:
        policies = [policy for policy in policies if policy["name"] in baselines]
    if stage == "reference":
        if not case_ids:
            raise ValueError("reference requires explicit --case-id shortlist entries")
        policies = [{"name": "full_information_ac_opf"}]
    implementation = {str(path.relative_to(REPOSITORY)): sha256(path) for path in
                      [Path(__file__).resolve(), *sorted(
                          Path(__file__).with_name("mapdn_baselines").glob("*.py"))]}
    runtime = runtime_versions()
    summaries = []
    for case in cases:
        for policy in policies:
            label = policy["name"] + (f"_gain_{policy['gain']:g}" if "gain" in policy else "")
            path = output / "results" / case["case_id"] / (label + ".json")
            expected = {"schema": "mapdn-selection-result-v1", "case_id": case["case_id"],
                        "network": pool["network"], "policy": policy, "pool_sha256": pool_hash,
                        "protocol_sha256": pool["protocol_sha256"], "runtime": runtime,
                        "implementation_sha256": implementation,
                        "original_starter_sha256": sha256(starter_path())}
            if path.exists():
                result = read_result(path, expected)
            else:
                net, trajectory = load_case(output, pool, case)
                if stage == "reference":
                    from mapdn_baselines.reference import evaluate_reference
                    result = evaluate_reference(net, trajectory, pool)
                else:
                    result = evaluate_local(net, trajectory, pool, policy)
                access = ("current full network snapshot" if stage == "reference"
                          else "current local region; independent PV instances")
                result.update(expected, information_access=access)
                write_result(path, result)
            summary = {key: value for key, value in result.items() if key != "steps"}
            summaries.append(summary)
            print(json.dumps(summary, allow_nan=False), flush=True)
    report = {"schema": "mapdn-selection-summary-v1", "stage": stage,
              "pool_sha256": pool_hash, "protocol_sha256": pool["protocol_sha256"],
              "results": summaries,
              "grid_interpretation": "Each gain is fixed before evaluation. Per-case best gain is "
                                     "an offline tuned reference, never the blind starter.",
              "comparison_rule": "Compare physical loss gaps only at comparable compliance; "
                                 "incomplete or failed references do not qualify a final case."}
    fingerprint = hashlib.sha256(json_bytes([stage, gains, case_ids, baselines])).hexdigest()[:12]
    write_once(output / f"{stage}-summary-{fingerprint}.json", json_bytes(report))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path)
    parser.add_argument("--network", type=int, choices=(33, 141), default=33)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--stage", choices=("freeze", "screen", "reference"), default="screen")
    parser.add_argument("--case-id", action="append", default=[])
    parser.add_argument("--baseline", action="append", choices=("zero_q", "original_starter",
                                                               "grid_droop"))
    parser.add_argument("--droop-gains", type=float, nargs="+", default=[5.0, 10.0, 20.0])
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    args = parser.parse_args()
    if any(not math.isfinite(gain) or gain <= 0 for gain in args.droop_gains):
        parser.error("droop gains must be finite and positive")
    if not (args.output / "pool.json").exists():
        if args.raw_dir is None:
            parser.error("--raw-dir is required to freeze a new pool")
        freeze_pool(args.raw_dir, args.network, args.output, args.protocol)
    pool, digest = read_pool(args.output)
    if pool["network"] != args.network or pool["protocol_sha256"] != sha256(args.protocol):
        parser.error("requested network or protocol differs from the frozen pool")
    if args.stage != "freeze":
        run_stage(args.output, args.stage, args.droop_gains, args.case_id, args.protocol,
                  args.baseline)
    else:
        print(json.dumps({"pool_sha256": digest, "network": pool["network"],
                          "case_count": len(pool["cases"])}), flush=True)


if __name__ == "__main__":
    main()
