#!/usr/bin/env python3
"""Run additive MAPDN strong references against unchanged frozen selection pools."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY / "tools/distribution_selection"))
from mapdn_baselines.simulation import summarize  # noqa: E402
from mapdn_selection import (  # noqa: E402
    json_bytes,
    load_case,
    read_pool,
    read_result,
    runtime_versions,
    sha256,
    write_once,
    write_result,
)
from mapdn_simulation import evaluate  # noqa: E402

SOURCE_COMMIT = "6895f1f0630b112745a3f681d7685d454407f9cb"
SOURCE_SHA256 = "c5b83ae69d94dd2dca9f644e34e7425317b413786ca33409b0f79da18e4eeb02"


def validate_protocol(protocol: dict, pool: dict, pool_hash: str, cases: list[str]) -> dict:
    config = protocol["mapdn"]
    original = config["source_iterative_droop"]
    relaxed = config["one_step_relaxed"]
    if (
        config["pool_sha256"][str(pool["network"])] != pool_hash
        or not set(cases) <= set(config["case_ids"])
        or config["normalized_action_bounds"][str(pool["network"])]
        != pool["normalized_action_bound"]
        or config["intervals"] != 480
        or config["interval_hours"] != 0.05
        or config["source_sha256"] != SOURCE_SHA256
        or original["max_iterations"] != 100
        or original["relaxation"] != 0.1
        or original["normalized_slope"] != 20
        or original["pv_voltage_l2_stop"] != 1e-4
        or original["initial_reactive_power_each_snapshot"] != "zero"
        or original["native_saturation_bound"] != 1.0
        or relaxed["relaxation"] != 0.1
        or relaxed["normalized_slope"] != 20
        or config["one_step_integral"]["gains"] != [1.0, 2.5]
        or config["max_pf_calls_per_case_and_baseline"] != 50000
        or config["max_wall_seconds_per_case_and_baseline"] != 1800
    ):
        raise ValueError(
            "protocol does not match frozen source, pool, cases or algorithm parameters"
        )
    return config


def read_qualified_result(path: Path, expected: dict) -> dict:
    """Verify receipts plus physical accounting, even after a marker is regenerated."""
    result = read_result(path, expected)
    rows = result["steps"]
    if [row["interval_index"] for row in rows] != list(range(len(rows))):
        raise ValueError("qualification cache has noncontiguous physical coverage")
    metrics = summarize(rows, bus_count=result["bus_count"])
    for key, value in metrics.items():
        cached = result["metrics"].get(key)
        if isinstance(value, (bool, type(None))):
            agrees = cached is value
        elif isinstance(cached, (int, float)):
            agrees = math.isclose(value, cached, rel_tol=1e-12, abs_tol=1e-12)
        else:
            agrees = False
        if not agrees:
            raise ValueError(f"qualification cache metric disagrees with physical rows: {key}")
    calls = 0
    for row in rows:
        audit = row["iteration_audit"]
        if audit["independent_final_pf_calls"] != 1:
            raise ValueError("qualification cache lacks an independent final PF")
        calls += audit["pf_calls"]
        if len(audit["physical_pf_trace"]) != audit["pf_calls"] or not all(
            item.get("converged") for item in audit["physical_pf_trace"]
        ):
            raise ValueError("qualification cache has inconsistent physical PF trace")
        actions, reactive, capability = (
            row[name] for name in ("normalized_actions", "pv_q_mvar", "q_capability_mvar")
        )
        if not len(actions) == len(reactive) == len(capability) == result["pv_count"]:
            raise ValueError("qualification cache has inconsistent inverter vectors")
        if audit["physical_pf_trace"][-1]["normalized_actions"] != actions:
            raise ValueError("qualification cache scored action lacks its final physical PF")
        for action, q, cap in zip(actions, reactive, capability, strict=True):
            if (
                not all(map(math.isfinite, (action, q, cap)))
                or cap < 0
                or abs(action) > result["action_bound"] + 1e-12
                or not math.isclose(q, action * cap, rel_tol=1e-12, abs_tol=1e-12)
            ):
                raise ValueError("qualification cache action and physical Q disagree")
    if result.get("failed_attempt"):
        failed = result["failed_attempt"]
        if failed["pf_calls"] != len(failed["physical_pf_trace"]):
            raise ValueError("qualification cache has inconsistent failed PF trace")
        calls += failed["pf_calls"]
    if calls != result["pf_calls"]:
        raise ValueError("qualification cache PF accounting disagrees")
    return result


def implementation_hashes() -> dict:
    files = [
        *sorted(Path(__file__).parent.glob("mapdn*.py")),
        REPOSITORY / "tools/distribution_selection/mapdn_selection.py",
        *sorted((REPOSITORY / "tools/distribution_selection/mapdn_baselines").glob("*.py")),
    ]
    return {str(path.relative_to(REPOSITORY)): sha256(path) for path in files}


def policies(names: list[str], gains: list[float]) -> list[dict]:
    result = []
    if "source_iterative_droop" in names:
        result.append(
            {
                "name": "source_iterative_droop",
                "relaxation": 0.1,
                "max_iterations": 100,
                "voltage_l2_tolerance": 1e-4,
                "slope_before_action_clipping": 20.0,
                "cold_start_each_snapshot": True,
            }
        )
    if "one_step_relaxed" in names:
        result.append(
            {"name": "one_step_relaxed", "relaxation": 0.1, "slope_before_action_clipping": 20.0}
        )
    if "one_step_integral" in names:
        result.extend({"name": "one_step_integral", "gain": gain} for gain in gains)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pool-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--source-matlab", type=Path, required=True)
    parser.add_argument("--case-id", action="append", required=True)
    parser.add_argument(
        "--baseline",
        action="append",
        choices=("source_iterative_droop", "one_step_relaxed", "one_step_integral"),
    )
    parser.add_argument("--integral-gains", type=float, nargs="+", default=[1.0, 2.5])
    parser.add_argument("--smoke-intervals", type=int, default=480)
    args = parser.parse_args()
    if (
        not 1 <= args.smoke_intervals <= 480
        or args.integral_gains != [1.0, 2.5]
        or sha256(args.source_matlab) != SOURCE_SHA256
    ):
        parser.error("invalid source hash, interval count or frozen integral gain list")
    protocol_hash = sha256(args.protocol)
    protocol = json.loads(args.protocol.read_text())
    pool, pool_hash = read_pool(args.pool_dir)
    config = validate_protocol(protocol, pool, pool_hash, args.case_id)
    chosen = [row for row in pool["cases"] if row["case_id"] in args.case_id]
    if set(args.case_id) != {row["case_id"] for row in chosen}:
        parser.error("a requested case is outside the unchanged frozen pool")
    names = args.baseline or ["source_iterative_droop", "one_step_relaxed", "one_step_integral"]
    locked = {
        "schema": "mapdn-qualification-run-lock-v1",
        "pool_sha256": pool_hash,
        "protocol_sha256": protocol_hash,
        "implementation_sha256": implementation_hashes(),
        "runtime": runtime_versions(),
        "source_matlab_commit": SOURCE_COMMIT,
        "source_matlab_sha256": SOURCE_SHA256,
        "requested_intervals": args.smoke_intervals,
        "case_ids": sorted(args.case_id),
        "policies": policies(names, args.integral_gains),
    }
    write_once(args.output / "run-lock.json", json_bytes(locked))
    write_once(args.output / "protocol.json", args.protocol.read_bytes())
    summaries = []
    for case in chosen:
        for policy in locked["policies"]:
            label = policy["name"] + (f"_gain_{policy['gain']:g}" if "gain" in policy else "")
            path = args.output / "results" / case["case_id"] / (label + ".json")
            expected = {
                key: value
                for key, value in locked.items()
                if key not in ("case_ids", "policies", "schema")
            }
            expected.update(
                schema="mapdn-qualification-result-v1",
                case_id=case["case_id"],
                policy=policy,
                network=pool["network"],
                bus_count=pool["bus_count"],
                pv_count=pool["pv_count"],
                action_bound=pool["normalized_action_bound"],
                information_access=(
                    "own PV voltage per inner iteration plus central "
                    "PV L2 stop; exogenous snapshot held fixed"
                    if policy["name"] == "source_iterative_droop"
                    else "one action per interval; independent actor; "
                    "current legal regional observation only"
                ),
            )
            if path.exists():
                result = read_qualified_result(path, expected)
            else:
                net, trajectory = load_case(args.pool_dir, pool, case)
                result = evaluate(
                    net,
                    trajectory,
                    pool,
                    policy,
                    args.smoke_intervals,
                    pf_budget=config["max_pf_calls_per_case_and_baseline"],
                    wall_seconds_budget=config["max_wall_seconds_per_case_and_baseline"],
                )
                result.update(expected)
                write_result(path, result)
                read_qualified_result(path, expected)
            summary = {key: value for key, value in result.items() if key != "steps"}
            summaries.append(summary)
            print(json.dumps(summary, allow_nan=False), flush=True)
    write_once(args.output / "summary.json", json_bytes({"run_lock": locked, "results": summaries}))


if __name__ == "__main__":
    main()
