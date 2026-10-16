#!/usr/bin/env python3
"""Run stronger PowerGym references without changing the frozen selection pool."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import math
import os
import platform
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/distribution_selection"))
from powergym_backend import QualificationBackend  # noqa: E402
from powergym_baselines.controllers import POLICIES, snapshot_search  # noqa: E402
from powergym_search import DayEvaluator, current_idle, day_idle, static_idle, storage  # noqa: E402
from powergym_selection import digest, summarize, verify_pool  # noqa: E402

PROTOCOL_SHA256 = "6615eed909cdd0a330fede915f63a6ee89088c5dd2e70bd3357f43cb02f75e3e"
NUMERICS_SHA256 = "df22bc206b07a5cea0bcbfe0fa22570fb4761a1e018de3b7e4e5221bbd985991"


class CaseFailure(RuntimeError):
    def __init__(self, error: Exception, baseline: str, diagnostics: dict):
        super().__init__(f"{type(error).__name__}: {error}")
        self.diagnostics = {**diagnostics, "failed_baseline": baseline}


def immutable_json(path: Path, document: object) -> None:
    """Atomically link a complete result; never replace an existing destination."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("x") as stream:
            json.dump(document, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def write_result(path: Path, document: dict) -> None:
    immutable_json(path, document)
    marker = path.with_suffix(".sha256")
    with marker.open("x") as stream:
        stream.write(digest(path) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def effective_parameters(protocol: dict) -> dict:
    current = protocol["strong_current_idle"]
    oracle = protocol["oracle_day_idle"]
    battery = protocol["oracle_day_storage"]
    return {
        "uniform_tap_starts": current["uniform_tap_starts"],
        "retained_starts": current["retained_starts"],
        "current_coordinate_passes": current["coordinate_rounds"],
        "static_coordinate_passes": current["coordinate_rounds"],
        "static_search_inherits_current_multistart_and_full_tap_grid": True,
        "day_coordinate_passes": oracle["coordinate_rounds"],
        "battery_coordinate_passes": battery["rounds_per_battery"],
        "battery_slots": battery["timepoints"],
        "battery_amplitudes": battery["amplitudes_in_action_quanta"],
        "actual_net_energy_tolerance_kwh": protocol[
            "storage_reference_actual_net_energy_tolerance_kwh"
        ],
    }


def implementation_identity() -> dict:
    sources = sorted(Path(__file__).parent.glob("powergym*.py")) + [
        ROOT / "tools/distribution_selection/powergym_selection.py",
        ROOT / "tools/distribution_selection/powergym_baselines/backend.py",
        ROOT / "tools/distribution_selection/powergym_baselines/controllers.py",
        ROOT / "src/powergrid_bench/distribution/profiles.py",
    ]
    return {str(path.relative_to(ROOT)): digest(path) for path in sources}


def runtime_identity() -> dict:
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "dependencies": {
            name: importlib.metadata.version(name)
            for name in ("dss-python", "dss-python-backend", "numpy")
        },
    }


def validate_result(result: dict, case: dict, baseline: str, lock_sha: str) -> None:
    if result.get("schema_version") != "powergym-qualification-result-v1" or (
        result.get("case_id") != case["id"]
        or result.get("baseline") != baseline
        or result.get("run_lock_sha256") != lock_sha
    ):
        raise ValueError("result identity differs from case, baseline, or frozen run")
    rows = result["trajectory"]
    if len(rows) != result["completed_steps"] or len(rows) > 24:
        raise ValueError("result horizon declaration is inconsistent")
    caps, regs, batteries = {"34Bus": (2, 6, 2), "123Bus": (4, 7, 4)}[case["network"]]
    capacity = [4000.0 if case["network"] == "34Bus" else 1000.0] * batteries
    max_kw = [500.0 if case["network"] == "34Bus" else 100.0] * batteries
    if result["initial_energy_kwh"] != capacity:
        raise ValueError("cached initial energy differs from frozen full-charge batteries")
    previous = list(capacity)
    previous_action = [1] * caps + [32] * regs + [16] * batteries
    for hour, row in enumerate(rows):
        limits = [1] * caps + [32] * (regs + batteries)
        if (
            row["step"] != hour
            or len(row["action"]) != len(limits)
            or any(
                type(value) is not int or not 0 <= value <= bound
                for value, bound in zip(row["action"], limits)
            )
        ):
            raise ValueError("result trajectory has incomplete, reordered, or illegal actions")
        if any(
            not math.isfinite(row[key])
            for key in (
                "active_loss_kw",
                "voltage_violation_pu_hours",
                "min_voltage_pu",
                "max_voltage_pu",
            )
        ):
            raise ValueError("result trajectory contains nonfinite physical metrics")
        if row["capacitor_switches"] != sum(
            abs(a - b) for a, b in zip(row["action"][:caps], previous_action[:caps], strict=True)
        ) or row["tap_moves"] != sum(
            abs(a - b)
            for a, b in zip(
                row["action"][caps : caps + regs], previous_action[caps : caps + regs], strict=True
            )
        ):
            raise ValueError("cached operation counts differ from device transitions")
        previous_action = row["action"]
        if row["all_phases_compliant"] != (
            row["min_voltage_pu"] >= 0.95 and row["max_voltage_pu"] <= 1.05
        ) or row["all_phases_compliant"] != (row["compliant_phases"] == row["phases"]):
            raise ValueError("cached voltage compliance declarations are inconsistent")
        fields = [
            "battery_actual_kw",
            "battery_command_kw",
            "battery_energy_kwh",
            "clipping_residual_kwh",
            "rounding_residual_kwh",
        ]
        if any(
            len(row[field]) != batteries or any(not math.isfinite(v) for v in row[field])
            for field in fields
        ):
            raise ValueError("cached battery row has wrong dimensions or nonfinite values")
        for index in range(batteries):
            quantum = max_kw[index] / 16
            requested = (row["action"][caps + regs + index] - 16) * quantum
            available = previous[index] if requested > 0 else previous[index] - capacity[index]
            command = (
                min(requested, math.floor(available / quantum + 1e-8) * quantum)
                if (requested > 0)
                else max(requested, math.ceil(available / quantum - 1e-8) * quantum)
            )
            raw = previous[index] - row["battery_actual_kw"][index]
            clipped = max(0.0, min(capacity[index], raw))
            next_energy = float(round(clipped))
            if (
                command != row["battery_command_kw"][index]
                or next_energy != row["battery_energy_kwh"][index]
                or not math.isclose(
                    clipped - raw, row["clipping_residual_kwh"][index], abs_tol=1e-10
                )
                or not math.isclose(
                    next_energy - clipped, row["rounding_residual_kwh"][index], abs_tol=1e-10
                )
            ):
                raise ValueError("cached battery projection or original ledger recurrence differs")
        previous = row["battery_energy_kwh"]
    rebuilt = summarize(
        rows,
        initial_energy=result["initial_energy_kwh"],
        final_energy=result["final_energy_kwh"],
        cap_switches=sum(row["capacitor_switches"] for row in rows),
        tap_moves=sum(row["tap_moves"] for row in rows),
        step_hours=1.0,
        tolerance_kwh=case["terminal_energy_tolerance_kwh"],
        error=result["error"],
    )
    for key in rebuilt:
        if result[key] != rebuilt[key]:
            raise ValueError(f"cached result summary is inconsistent: {key}")
    if rows and rows[-1]["battery_energy_kwh"] != result["final_energy_kwh"]:
        raise ValueError("cached final energy differs from its last physical row")
    actual = [math.fsum(row["battery_actual_kw"][i] for row in rows) for i in range(batteries)]
    if actual != result["actual_net_energy_kwh"] or result["qualification_valid"] != (
        result["valid"] and all(abs(value) <= 1.0 for value in actual)
    ):
        raise ValueError("cached actual-energy qualification is inconsistent")
    for name, field, absolute in (
        ("actual_throughput_kwh", "battery_actual_kw", True),
        ("commanded_net_energy_kwh", "battery_command_kw", False),
        ("commanded_throughput_kwh", "battery_command_kw", True),
        ("rounding_residual_kwh", "rounding_residual_kwh", False),
        ("clipping_residual_kwh", "clipping_residual_kwh", False),
    ):
        totals = [
            math.fsum(abs(row[field][i]) if absolute else row[field][i] for row in rows)
            for i in range(batteries)
        ]
        if totals != result[name]:
            raise ValueError(f"cached storage audit differs from trajectory: {name}")
    if not math.isclose(
        result["battery_throughput_kwh"], math.fsum(result["actual_throughput_kwh"]), abs_tol=1e-9
    ):
        raise ValueError("cached battery throughput differs from per-device audit")
    if result["physical_voltage_feasible"] != (
        len(rows) == 24 and rebuilt["simultaneous_compliance"] == 1.0
    ) or result["nonzero_actual_throughput"] != (result["battery_throughput_kwh"] > 1e-6):
        raise ValueError("cached feasibility or battery-use declaration differs")
    if (
        baseline == "best_active_storage"
        and result["qualification_valid"]
        and not (result["battery_throughput_kwh"] > 1e-6)
    ):
        raise ValueError("active-storage result has no actual battery throughput")


def read_result(path: Path, case: dict, baseline: str, lock_sha: str) -> dict:
    marker = path.with_suffix(".sha256")
    if not marker.is_file() or digest(path) != marker.read_text().strip():
        raise ValueError("result SHA-256 does not match its durable receipt")
    result = json.loads(path.read_text())
    validate_result(result, case, baseline, lock_sha)
    return result


def case_results(case: dict, assets: Path, protocol: dict, numerics: dict, lock_sha: str):
    parameters = effective_parameters(protocol)
    evaluator = DayEvaluator(
        case,
        assets,
        max_pf_calls=protocol["max_pf_calls_per_case_all_baselines"],
        max_wall_seconds=protocol["max_wall_seconds_per_case_all_baselines"],
    )
    plans, prior_calls, prior_wall = {}, 0, evaluator.started

    def finish(name, plan):
        nonlocal prior_calls, prior_wall
        result = evaluator.replay(plan, name)
        permissions = protocol[name].get("permissions") if name in protocol else None
        if permissions is None:
            permissions = (
                "current load and full circuit; no future load"
                if name == "full_information_snapshot"
                else "canary lagged observation only"
                if name in POLICIES
                else protocol["oracle_day_storage"]["permissions"]
            )
        result.update(
            schema_version="powergym-qualification-result-v1",
            case_id=case["id"],
            network=case["network"],
            group=case["group"],
            profile_index=case["profile_index"],
            scale=case["scale"],
            run_lock_sha256=lock_sha,
            permissions=permissions,
            case_cumulative_pf_calls=evaluator.pf_calls,
            phase_pf_calls=evaluator.pf_calls - prior_calls,
            case_cumulative_wall_seconds=time.monotonic() - evaluator.started,
            phase_wall_seconds=time.monotonic() - prior_wall,
            no_global_optimum_claim=True,
            physical_voltage_feasible=(
                result["completed_steps"] == 24 and result["simultaneous_compliance"] == 1.0
            ),
            search_diagnostics=evaluator.diagnostics(),
        )
        prior_calls, prior_wall = evaluator.pf_calls, time.monotonic()
        return result

    active_baseline = "strong_current_idle"
    try:
        plans["strong_current_idle"] = current_idle(evaluator, parameters)
        yield finish("strong_current_idle", plans["strong_current_idle"])
        active_baseline = "static_day_idle"
        plans["static_day_idle"] = static_idle(evaluator, parameters)
        yield finish("static_day_idle", plans["static_day_idle"])
        active_baseline = "oracle_day_idle"
        plans["oracle_day_idle"] = day_idle(evaluator, list(plans.values()), parameters)
        yield finish("oracle_day_idle", plans["oracle_day_idle"])
        active_baseline = "oracle_day_storage"
        free, active = storage(evaluator, plans["oracle_day_idle"], parameters)
        yield finish("oracle_day_storage", free)
        active_baseline = "best_active_storage"
        if active is None:
            raise ValueError("no actual-energy-neutral nonzero-throughput storage candidate found")
        yield finish("best_active_storage", active)
        for name in numerics["calibration_baselines"]:
            active_baseline = name
            backend = QualificationBackend(
                case,
                assets,
                before_solve=evaluator.auxiliary_solve,
                failed_solve=evaluator.auxiliary_failure,
            )
            schedule = []
            for _ in range(24):
                action = (
                    snapshot_search(backend, numerics["calibration_snapshot_search_passes"])
                    if name == "full_information_snapshot"
                    else POLICIES[name](backend.observation())
                )
                backend.advance(action)
                schedule.append(action)
            result = finish(name, schedule)
            result["matched_numerical_calibration"] = True
            yield result
    except Exception as exc:
        raise CaseFailure(exc, active_baseline, evaluator.diagnostics()) from exc


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pool", required=True, type=Path)
    parser.add_argument("--protocol", required=True, type=Path)
    parser.add_argument("--numerics", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--case-ids", nargs="+")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if digest(args.protocol) != PROTOCOL_SHA256:
        parser.error("qualification protocol SHA differs from frozen identity")
    if digest(args.numerics) != NUMERICS_SHA256:
        parser.error("qualification numerical amendment SHA differs from frozen identity")
    numerical_document = json.loads(args.numerics.read_text())
    if numerical_document["parent_protocol_sha256"] != PROTOCOL_SHA256:
        parser.error("numerical amendment is not bound to this protocol")
    numerics = numerical_document["powergym"]
    if (
        numerics["solver_tolerance"] != 1e-10
        or numerics["build_y_matrix_option"] != 2
        or numerics["build_y_matrix_allocate_vi"] is not True
        or numerics["reset_solution_initialized_before_each_solve"] is not True
        or numerics["terminal_ledger_rule_changed"] is not False
        or numerics["battery_rounding_epsilon_added"] is not False
        or numerics["generator_reactive_convention_changed"] is not False
    ):
        parser.error("unsupported solver or physical semantics")
    protocol = json.loads(args.protocol.read_text())["powergym"]
    baseline_names = protocol["baselines"] + numerics["calibration_baselines"]
    pool_dir, output = args.pool.resolve(strict=True), args.output.absolute()
    pool = verify_pool(pool_dir)
    if digest(pool_dir / "pool.json") != protocol["pool_sha256"]:
        parser.error("pool is not the preregistered selection source")
    selected = args.case_ids or protocol["case_ids"]
    if len(selected) != len(set(selected)) or set(selected) - set(protocol["case_ids"]):
        parser.error("case ids must be a unique subset of the preregistered five")
    if output.exists() and not args.resume:
        parser.error("output exists; use a fresh destination or --resume")
    if output.resolve().is_relative_to(pool_dir):
        parser.error("output cannot alter frozen pool")
    lock = {
        "schema_version": "powergym-qualification-run-v1",
        "protocol_sha256": PROTOCOL_SHA256,
        "numerics_sha256": NUMERICS_SHA256,
        "numerics": numerics,
        "pool_sha256": digest(pool_dir / "pool.json"),
        "parameters": effective_parameters(protocol),
        "implementation_sha256": implementation_identity(),
        "runtime": runtime_identity(),
        "case_ids": selected,
        "baselines": baseline_names,
        "max_pf_calls_per_case_all_baselines": protocol["max_pf_calls_per_case_all_baselines"],
        "max_wall_seconds_per_case_all_baselines": protocol[
            "max_wall_seconds_per_case_all_baselines"
        ],
    }
    lock_path = output / "run-lock.json"
    if lock_path.exists():
        if json.loads(lock_path.read_text()) != lock:
            parser.error("existing run changed code, parameters, pool, protocol, or runtime")
    else:
        immutable_json(lock_path, lock)
    lock_sha, rows, failures = digest(lock_path), [], []
    for case_id in selected:
        verify_pool(pool_dir)
        item = next(row for row in pool["cases"] if row["id"] == case_id)
        case = json.loads((pool_dir / item["path"]).read_text())
        case_dir = output / "cases" / case_id
        if case_dir.exists():
            for name in baseline_names:
                path = case_dir / f"{name}.json"
                if path.exists():
                    rows.append(read_result(path, case, name, lock_sha))
            existing_names = [row["baseline"] for row in rows if row["case_id"] == case_id]
            failure_path = case_dir / "failure.json"
            if failure_path.exists():
                if digest(failure_path) != failure_path.with_suffix(".sha256").read_text().strip():
                    raise ValueError("partial-case failure receipt changed")
                failure = json.loads(failure_path.read_text())
                if (
                    failure["run_lock_sha256"] != lock_sha
                    or failure["case_id"] != case_id
                    or (set(failure["completed_baselines"]) != set(existing_names))
                ):
                    raise ValueError("partial-case failure receipt identity is inconsistent")
                failures.append(failure)
            elif set(existing_names) != set(baseline_names):
                raise ValueError("interrupted partial case retained; use fresh output to rerun")
            continue
        case_dir.mkdir(parents=True)
        try:
            for result in case_results(
                case, pool_dir / "assets" / case["network"], protocol, numerics, lock_sha
            ):
                if implementation_identity() != lock["implementation_sha256"]:
                    raise RuntimeError("source changed during execution; frozen run stopped")
                validate_result(result, case, result["baseline"], lock_sha)
                write_result(case_dir / f"{result['baseline']}.json", result)
                rows.append(result)
                print(
                    json.dumps(
                        {key: value for key, value in result.items() if key != "trajectory"}
                    ),
                    flush=True,
                )
        except Exception as exc:
            failure = {
                "case_id": case_id,
                "error": f"{type(exc).__name__}: {exc}",
                "run_lock_sha256": lock_sha,
                "completed_baselines": [
                    row["baseline"] for row in rows if row["case_id"] == case_id
                ],
            }
            if isinstance(exc, CaseFailure):
                failure.update(exc.diagnostics)
            write_result(case_dir / "failure.json", failure)
            failures.append(failure)
            print(json.dumps(failure), flush=True)
    summary = {
        "schema_version": "powergym-qualification-summary-v1",
        "run_lock_sha256": lock_sha,
        "results": [
            {key: value for key, value in row.items() if key != "trajectory"} for row in rows
        ],
        "release_ready": False,
        "agent_runs": 0,
        "failures": failures,
    }
    summary_path = output / "summary.json"
    if summary_path.exists():
        if json.loads(summary_path.read_text()) != summary:
            raise ValueError("existing summary differs from validated results")
    else:
        write_result(summary_path, summary)


if __name__ == "__main__":
    main()
