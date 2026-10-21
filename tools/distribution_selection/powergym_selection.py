#!/usr/bin/env python3
"""Freeze and measure a deterministic trusted PowerGym case-selection pool.

Not a benchmark release, agent evaluation, train/test split, or paper replay.
Standard and 2.5x stress groups are deliberately not ranked together.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import re
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from powergrid_bench.distribution.profiles import pack_profiles  # noqa: E402

COMMIT = "c9fc6d8357308a1f2bd2389474b56089c2a6bd78"
PROTOCOL_SHA256 = "8d5854ccf3e11273d7977913dba0720fdadb0e7d2b7b980f19ad4853f40b7fa0"
MODELS = {"34Bus": "ieee34Mod1_daily.dss", "123Bus": "IEEE123Master_daily.dss"}
REFERENCE = "full_information_snapshot"


def digest(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"require regular nonsymlink file: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, document: object) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + "\n")
    os.replace(temporary, path)


def equispaced_indices(count: int) -> list[int]:
    """Six preregistered floor(k*(N-1)/5) indices, with duplicates removed."""
    if type(count) is not int or count < 1:
        raise ValueError("profile count must be positive")
    return sorted({index * (count - 1) // 5 for index in range(6)})


def _verified_source(source: Path) -> dict:
    receipt = json.loads((source / "source-receipt.json").read_text())
    if receipt["source_commit"] != COMMIT:
        raise ValueError("source receipt is not the declared PowerGym commit")
    # This accepts an already verified preparation copy, not an arbitrary
    # checkout claiming a commit. Every copied byte is checked against its
    # recorded source receipt; this receipt is not a cryptographic signature.
    files = receipt["files"]
    needed = {name: value for name, value in files.items() if (
        name == "LICENSE" or any(name.startswith(f"systems/{network}/") for network in MODELS)
    )}
    for name, expected in needed.items():
        target = source / name
        if not target.resolve().is_relative_to(source) or digest(target) != expected:
            raise ValueError(f"source identity mismatch: {name}")
    if "LICENSE" not in needed:
        raise ValueError("verified source receipt lacks LICENSE")
    return needed


def freeze_pool(source: Path, destination: Path) -> dict:
    """Freeze source bytes and all cases before any controller runs."""
    source, destination = source.resolve(strict=True), destination.absolute()
    if destination.exists() or destination.is_symlink():
        raise FileExistsError("refusing to overwrite an existing selection pool")
    if destination.resolve().is_relative_to(source):
        raise ValueError("selection pool cannot be written inside verified source")
    source_files = _verified_source(source)
    preparations = []
    for network, model in MODELS.items():
        feeder = source / "systems" / network
        definitions = [feeder / model]
        if network == "123Bus" and (feeder / "IEEE123Loads_daily.dss").is_file():
            definitions.append(feeder / "IEEE123Loads_daily.dss")
        names = []
        for definition in definitions:
            relative = str(definition.relative_to(source))
            if relative not in source_files:
                raise ValueError("load definitions missing from verified receipt")
            names.extend(re.findall(
                r"^\s*new\s+(?:object=)?load\.([^\s]+)",
                definition.read_text(), re.I | re.M,
            ))
        if not names or len({name.lower() for name in names}) != len(names):
            raise ValueError("load names must be nonempty and unique")
        curves = sorted((feeder / "loadshape").glob("*"), key=lambda p: p.name.casefold())
        curves = [p for p in curves if "loadshape" in p.name.lower()
                  and p.suffix.lower() == ".csv"]
        if any(str(path.relative_to(source)) not in source_files for path in curves):
            raise ValueError("loadshape source missing from verified receipt")
        packed = pack_profiles(curves, load_count=len(names), horizon=24)
        if any(v < 0 for profile in packed.profiles for row in profile for v in row):
            raise ValueError("negative demand multipliers are outside this protocol")
        packing = packed.manifest
        for item in packing["sources"]:
            item["declared_path"] = str(Path(item["declared_path"]).relative_to(source))
            del item["resolved_path"]
        preparations.append((network, model, names, packed.profiles, packing))
    destination.mkdir(parents=True, mode=0o700)
    cases, networks = [], {}
    for network, model, names, profiles, packing in preparations:
        assets = destination / "assets" / network
        assets.mkdir(parents=True)
        for name in source_files:
            prefix = f"systems/{network}/"
            if name.startswith(prefix) and not name[len(prefix):].startswith("loadshape/"):
                target = assets / name[len(prefix):]
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source / name, target)
                if digest(target) != source_files[name]:
                    raise ValueError("source changed during copying")
        (assets / "loadshape.dss").write_text("".join(
            f"New Loadshape.loadshape_{name} npts=1 interval=1 mult=(1)\n" for name in names
        ))
        selected = equispaced_indices(len(profiles))
        networks[network] = {
            "load_count": len(names), "profile_count": len(profiles),
            "selected_profile_indices": selected, "packing": packing,
        }
        groups = [("standard", 1.0)] + ([("stress", 2.5)] if network == "123Bus" else [])
        for group, scale in groups:
            for index in selected:
                case_id = f"{network}-{group}-p{index:03d}-s{scale:g}"
                case = {
                    "schema_version": "powergym-selection-case-v1", "id": case_id,
                    "network": network, "group": group, "scale": scale,
                    "model_file": model, "upstream_commit": COMMIT,
                    "protocol_sha256": PROTOCOL_SHA256,
                    "horizon": 24, "step_hours": 1.0, "profile_index": index,
                    "load_names": names,
                    "multipliers": [[value * scale for value in row] for row in profiles[index]],
                    "terminal_energy_tolerance_kwh": 1.0,
                    "track": f"powergym-selection-{group}-energy-neutral-v1",
                }
                path = destination / "cases" / f"{case_id}.json"
                path.parent.mkdir(exist_ok=True)
                write_json(path, case)
                cases.append({
                    "id": case_id, "network": network, "group": group, "scale": scale,
                    "profile_index": index, "path": str(path.relative_to(destination)),
                    "sha256": digest(path),
                })
    shutil.copyfile(source / "LICENSE", destination / "UPSTREAM-LICENSE")
    files = {str(p.relative_to(destination)): digest(p) for p in sorted(destination.rglob("*"))
             if p.is_file()}
    pool = {
        "schema_version": "powergym-selection-pool-v1", "upstream_commit": COMMIT,
        "protocol_sha256": PROTOCOL_SHA256, "cases": cases, "networks": networks,
        "source_files": source_files, "files": files,
        "selection_rule": "deduplicated floor(k*(profile_count-1)/5), k=0..5",
        "calendar_independence_verified": False, "release_ready": False,
        "standard_and_stress_are_separate": True,
    }
    write_json(destination / "pool.json", pool)
    (destination / "pool.sha256").write_text(digest(destination / "pool.json") + "\n")
    return pool


def verify_pool(directory: Path) -> dict:
    expected = (directory / "pool.sha256").read_text().strip()
    if digest(directory / "pool.json") != expected:
        raise ValueError("pool manifest changed after freeze")
    pool = json.loads((directory / "pool.json").read_text())
    for name, expected in pool["files"].items():
        path = directory / name
        if not path.resolve().is_relative_to(directory.resolve()) or digest(path) != expected:
            raise ValueError(f"frozen selection asset changed: {name}")
    return pool


def summarize(rows: list[dict], *, initial_energy: list[float], final_energy: list[float],
              cap_switches: int, tap_moves: int, step_hours: float,
              tolerance_kwh: float, error: str | None = None) -> dict:
    errors = [abs(a - b) for a, b in zip(initial_energy, final_energy, strict=True)]
    valid = error is None and len(rows) == 24 and all(e <= tolerance_kwh for e in errors)
    loss = math.fsum(row["active_loss_kw"] * step_hours for row in rows)
    violation = math.fsum(row["voltage_violation_pu_hours"] for row in rows)
    cost = violation + loss / 1000 + (cap_switches + tap_moves) / 33
    phases = sum(row["phases"] for row in rows)
    diagnostic = [row.get("paper_vanilla_reward_diagnostic") for row in rows]
    return {
        "valid": valid, "completed_steps": len(rows), "error": error or (
            None if valid else "incomplete_episode" if len(rows) != 24
            else "terminal_energy_violation"
        ),
        "canary_quality": 1 / (1 + cost) if valid else 0.0, "canary_cost": cost,
        "active_loss_kwh": loss, "voltage_violation_pu_hours": violation,
        "phase_time_compliance": sum(row["compliant_phases"] for row in rows) / phases
        if phases else None,
        "simultaneous_compliance": sum(row["all_phases_compliant"] for row in rows) / len(rows)
        if rows else None,
        "min_voltage_pu": min((row["min_voltage_pu"] for row in rows), default=None),
        "max_voltage_pu": max((row["max_voltage_pu"] for row in rows), default=None),
        "capacitor_switches": cap_switches, "tap_moves": tap_moves,
        "initial_energy_kwh": initial_energy, "final_energy_kwh": final_energy,
        "terminal_energy_error_kwh": errors,
        "paper_vanilla_reward_diagnostic": math.fsum(diagnostic) if diagnostic and all(
            value is not None for value in diagnostic
        ) else None,
    }


def run_case(case: dict, assets: Path, baseline: str, *, search_passes: int) -> dict:
    from powergym_baselines.backend import SnapshotBackend
    from powergym_baselines.controllers import POLICIES, snapshot_search

    start = time.monotonic()
    backend, rows, error = None, [], None
    try:
        backend = SnapshotBackend(case, assets)
        for _ in range(24):
            action = snapshot_search(backend, search_passes) if baseline == REFERENCE else (
                POLICIES[baseline](backend.observation())
            )
            rows.append(backend.advance(action))
    except Exception as exc:
        # Isolate an infrastructure/solver failure to its case; preserve the
        # diagnostic and zero quality rather than aborting the remaining pool.
        error = f"{type(exc).__name__}: {exc}"
    if backend is None:
        return {"case_id": case["id"], "baseline": baseline, "group": case["group"],
                "network": case["network"], "valid": False, "canary_quality": 0.0,
                "scale": case["scale"], "profile_index": case["profile_index"],
                "permissions": "current_load_full_model_queries" if baseline == REFERENCE else (
                    "canary_observation_only_lagged_measurements"
                ), "completed_steps": 0, "error": error, "pf_calls": None,
                "wall_seconds": time.monotonic() - start, "trajectory": []}
    result = summarize(
        rows, initial_energy=backend.initial_energy, final_energy=backend.energy,
        cap_switches=backend.cap_switches, tap_moves=backend.tap_moves,
        step_hours=case["step_hours"], tolerance_kwh=case["terminal_energy_tolerance_kwh"],
        error=error,
    )
    result.update({
        "case_id": case["id"], "baseline": baseline, "network": case["network"],
        "group": case["group"], "scale": case["scale"], "profile_index": case["profile_index"],
        "permissions": "current_load_full_model_queries" if baseline == REFERENCE else (
            "canary_observation_only_lagged_measurements"
        ),
        "battery_throughput_kwh": backend.throughput_kwh,
        "initial_soc": [e / c for e, c in zip(backend.initial_energy, backend.capacity)],
        "final_soc": [e / c for e, c in zip(backend.energy, backend.capacity)],
        "pf_calls": backend.pf_calls, "failed_pf_calls": backend.failed_pf_calls,
        "wall_seconds": time.monotonic() - start, "trajectory": rows,
    })
    return result


def main() -> None:
    from powergym_baselines.controllers import POLICIES

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--resume", action="store_true", help="reuse verified frozen pool")
    parser.add_argument("--baselines", nargs="+", choices=[*POLICIES, REFERENCE],
                        default=[*POLICIES, REFERENCE])
    parser.add_argument("--search-passes", type=int, default=2)
    parser.add_argument("--case-ids", nargs="+",
                        help="smoke subset; the entire pool is still frozen")
    args = parser.parse_args()
    if args.search_passes < 1:
        parser.error("--search-passes must be positive")
    protocol = ROOT / "configs/distribution-case-selection-20261016.json"
    if digest(protocol) != PROTOCOL_SHA256:
        parser.error("selection protocol differs from the preregistered SHA-256")
    args.output = args.output.resolve()
    pool_dir = args.output / "pool"
    if args.resume:
        pool = verify_pool(pool_dir)
    else:
        if args.output.exists():
            parser.error("output exists; use a fresh path or --resume")
        pool = freeze_pool(args.source_dir, pool_dir)
    pool_sha = digest(pool_dir / "pool.json")
    print(json.dumps({"event": "pool_frozen", "pool_sha256": pool_sha,
                      "case_count": len(pool["cases"])}), flush=True)
    if args.prepare_only:
        return
    selected = set(args.case_ids or [case["id"] for case in pool["cases"]])
    if selected - {case["id"] for case in pool["cases"]}:
        parser.error("unknown --case-ids")
    implementation = {
        str(path.relative_to(ROOT)): digest(path) for path in [Path(__file__), *sorted(
            (Path(__file__).parent / "powergym_baselines").glob("*.py")
        )]
    }
    import importlib.metadata

    dependencies = {name: importlib.metadata.version(name) for name in (
        "dss-python", "dss-python-backend", "numpy"
    )}
    run_lock = {
        "schema_version": "powergym-selection-run-v1", "protocol_sha256": PROTOCOL_SHA256,
        "pool_sha256": pool_sha, "implementation_sha256": implementation,
        "python": platform.python_version(), "platform": platform.platform(),
        "dependencies": dependencies, "baselines": args.baselines,
        "search_passes": args.search_passes,
    }
    run_lock_path = args.output / "run-lock.json"
    if run_lock_path.exists():
        if json.loads(run_lock_path.read_text()) != run_lock:
            parser.error("existing run differs in code, parameters, or runtime; use fresh output")
    else:
        write_json(run_lock_path, run_lock)
    run_lock_sha = digest(run_lock_path)
    results_dir = args.output / "results"
    results_dir.mkdir(exist_ok=True)
    results = []
    for item in pool["cases"]:
        if item["id"] not in selected:
            continue
        case = json.loads((pool_dir / item["path"]).read_text())
        for baseline in args.baselines:
            verify_pool(pool_dir)
            path = results_dir / f"{case['id']}--{baseline}.json"
            sha_path = path.with_suffix(".sha256")
            if path.exists():
                if not sha_path.is_file() or digest(path) != sha_path.read_text().strip():
                    raise ValueError("existing result differs from its durable SHA-256")
                result = json.loads(path.read_text())
                if result.get("run_lock_sha256") != run_lock_sha:
                    raise ValueError("existing result belongs to another run")
            else:
                result = run_case(case, pool_dir / "assets" / case["network"], baseline,
                                  search_passes=args.search_passes)
                result.update(schema_version="powergym-selection-result-v1",
                              pool_sha256=pool_sha, protocol_sha256=PROTOCOL_SHA256,
                              run_lock_sha256=run_lock_sha)
                write_json(path, result)
                sha_path.write_text(digest(path) + "\n")
            results.append({key: value for key, value in result.items() if key != "trajectory"})
            print(json.dumps({"event": "result", **results[-1]}), flush=True)
    report = {
        "schema_version": "powergym-selection-results-v1", "protocol_sha256": PROTOCOL_SHA256,
        "pool_sha256": pool_sha, "implementation_sha256": implementation,
        "python": platform.python_version(), "platform": platform.platform(),
        "dependencies": dependencies, "run_lock_sha256": run_lock_sha,
        "baselines": args.baselines, "search_passes": args.search_passes,
        "results": results,
        "interpretation": {
            "purpose": "trusted-side case selection; no cross-case generalization claim",
            "ranking_groups": ["network", "group", "permissions"],
            "paper_reward": "vanilla-weight diagnostic only; snapshot timing and hard terminal "
                            "energy differ from paper protocol",
            "pf_calls": "explicit snapshot Solve calls including initial solve and search; "
                        "native DSS compile initialization is not instrumented",
            "battery_difficulty": "all baselines idle batteries; long-horizon storage control "
                                  "difficulty is not validated",
        },
    }
    write_json(args.output / "summary.json", report)


if __name__ == "__main__":
    main()
