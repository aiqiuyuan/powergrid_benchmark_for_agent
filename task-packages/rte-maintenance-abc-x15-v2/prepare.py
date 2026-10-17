#!/usr/bin/env python3
"""Reconstruct ABC-open / X-protected images from verified original inputs."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import tempfile

ROOT = Path(__file__).resolve().parent
COMMIT = "052def4d47271f913f89a68169083059732360f3"
PROTOCOL = "rte2020-abc-x15-v2"
GROUPS = ("A", "B", "C", "X")
EXPECTED = {f"{group}_{number:02d}" for group in GROUPS for number in range(1, 16)}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _job_scale(job: dict, horizon: int, scenarios: list[int]) -> float:
    costs = []
    for start in range(1, min(int(job["tmax"]), horizon) + 1):
        duration = int(job["Delta"][start - 1])
        if duration <= 0 or start + duration > horizon + 1:
            continue
        value = 0.0
        for t in range(start, start + duration):
            risks = job["risk"].get(str(t), {}).get(str(start), [])
            value += sum(abs(r) for r in risks) / scenarios[t - 1]
        costs.append(value / horizon)
    if not costs:
        raise ValueError("instance has no admissible start")
    return sum(costs) / len(costs)


def scale_for(instance: dict) -> float:
    """Unchanged pilot normalization: input risks only; no fitted leaderboard data."""
    scale = sum(_job_scale(job, instance["T"], instance["Scenarios_number"])
                for job in instance["Interventions"].values())
    if not math.isfinite(scale):
        raise ValueError("non-finite normalization scale")
    return max(1.0, scale)


def streaming_scale(path: Path, shape: dict | None = None) -> float:
    """Build-only parsing bounds memory by one intervention, not a multi-GB JSON."""
    if path.stat().st_size <= 1 << 20:
        with path.open() as stream:
            return scale_for(json.load(stream))
    import ijson
    shape = shape or {}
    horizon = shape.get("T")
    scenarios = shape.get("Scenarios_number")
    if horizon is None:
        with path.open("rb") as stream:
            horizon = next(ijson.items(stream, "T", use_float=True))
    if scenarios is None:
        with path.open("rb") as stream:
            scenarios = next(ijson.items(stream, "Scenarios_number", use_float=True))
    scale = 0.0
    with path.open("rb") as stream:
        for _, job in ijson.kvitems(stream, "Interventions", use_float=True):
            scale += _job_scale(job, horizon, scenarios)
    if not math.isfinite(scale):
        raise ValueError("non-finite normalization scale")
    return max(1.0, scale)


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def link_or_copy(source: Path, target: Path) -> None:
    """Only trusted build input is linked; do not modify a source-linked inode."""
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if sha256(target) != sha256(source):
            raise ValueError(f"refusing to replace different prepared file: {target.name}")
        return
    try:
        os.link(source, target)
    except OSError:
        shutil.copyfile(source, target)


def inventory_cases(inventory: dict) -> dict[str, dict]:
    commit = inventory.get("commit", inventory.get("source_commit"))
    if commit != COMMIT:
        raise ValueError("inventory must identify the pinned official commit")
    records = inventory.get("instances", inventory.get("cases", []))
    cases = {}
    for entry in records:
        case_id = entry.get("id", entry.get("case_id"))
        if case_id in cases:
            raise ValueError("duplicate inventory case")
        cases[case_id] = entry
    if set(cases) != EXPECTED:
        raise ValueError("inventory must contain exactly A01..15/B01..15/C01..15/X01..15")
    return cases


def _verify_sources() -> None:
    lock = json.loads((ROOT / "source-lock.json").read_text())
    for name in ("RTE_ChallengeROADEF2020_checker.py", "LICENSE"):
        if sha256(ROOT / "support/vendor" / name) != lock["files"][name]["sha256"]:
            raise ValueError("pinned official source checksum mismatch")
    starter = json.loads((ROOT / "starter-lock.json").read_text())
    if sha256(ROOT / "init.py") != starter["sha256"]:
        raise ValueError("initial starter source drift")


def portable_archives(value: object) -> dict:
    """Keep provenance, excluding local caches and machine-specific absolute paths."""
    if not isinstance(value, dict):
        return {}
    allowed = {"url", "sha256", "bytes", "git_blob", "blob_sha", "repository_path", "commit"}
    return {str(name): {key: item for key, item in record.items() if key in allowed}
            for name, record in value.items() if isinstance(record, dict)}


def materialize(inventory_path: Path) -> dict:
    """Build two disjoint contexts, freezing every instance hash and scale."""
    _verify_sources()
    inventory = json.loads(inventory_path.read_text())
    sources = inventory_cases(inventory)
    previous_path = ROOT / "data-lock.json"
    previous = json.loads(previous_path.read_text()) if previous_path.exists() else {}
    cached = {case["id"]: case for case in previous.get("cases", [])}
    all_cases = []
    for case_id in sorted(sources):
        entry = sources[case_id]
        source = Path(entry["path"]).resolve()
        digest = sha256(source)
        if digest != entry["sha256"] or source.stat().st_size != entry["bytes"]:
            raise ValueError(f"input checksum/size mismatch: {case_id}")
        old = cached.get(case_id, {})
        if old.get("sha256") == digest:
            scale = old["scale"]
        elif (entry.get("scale_input_sha256") == digest
              and entry.get("scale_definition") == "rte2020-input-only-v1"
              and "input_only_scale" in entry):
            scale = float(entry["input_only_scale"])
        else:
            scale = streaming_scale(source, entry.get("shape"))
        if not math.isfinite(scale) or scale < 1:
            raise ValueError("invalid input-only scale receipt")
        protected = case_id.startswith("X_")
        destination = ROOT / ("tests/data" if protected else "environment/app/public")
        link_or_copy(source, destination / f"{case_id}.json")
        all_cases.append({"id": case_id, "path": f"{case_id}.json", "sha256": digest,
                          "bytes": entry["bytes"], "scale": scale,
                          "group": case_id[0], "role": "protected_evaluation" if protected else "development"})
    common = {"protocol": PROTOCOL, "upstream_commit": COMMIT, "seconds_per_case": 900,
              "seed": 2020, "address_space_bytes": 16 << 30,
              "checker_timeout_seconds": 180, "staging_timeout_seconds": 120}
    public = dict(common, split="public_abc", workers=2,
                  cases=[c for c in all_cases if c["role"] == "development"])
    hidden = dict(common, split="protected_x15_feedback", workers=15,
                  cases=[c for c in all_cases if c["role"] == "protected_evaluation"])
    write_json(ROOT / "environment/app/public/manifest.json", public)
    write_json(ROOT / "tests/data/manifest.json", hidden)
    for target in (ROOT / "environment/app/support", ROOT / "tests/support"):
        shutil.copytree(ROOT / "support", target, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name in ("problem.md", "prompt.md"):
        shutil.copyfile(ROOT / name, ROOT / "environment/app" / name)
    shutil.copytree(ROOT / "tools", ROOT / "tests/offline", dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copyfile(ROOT / "init.py", ROOT / "environment/app/submission/solver.py")
    lock = {"protocol": PROTOCOL, "source_commit": COMMIT,
            "inventory_sha256": sha256(inventory_path),
            "scale_definition": "sum over interventions of the mean absolute scenario risk over admissible starts, divided by T; max(1,value)",
            "normalization": "0.5 - atan(official_objective / input_only_scale) / pi",
            "public_count": 45, "protected_count": 15,
            "cases": all_cases,
            "archives": portable_archives(inventory.get("archives", {})),
            "historical_rank_equivalence": False}
    write_json(previous_path, lock)
    return lock


def inventory_from_dirs(paths: dict[str, Path], lock_path: Path, temporary: Path) -> Path:
    """Portable reconstruction uses committed per-instance hashes, not local paths."""
    lock = json.loads(lock_path.read_text())
    records = []
    for case in lock["cases"]:
        matches = list(paths[case["group"]].rglob(f"{case['id']}.json"))
        if len(matches) != 1:
            raise ValueError(f"need exactly one original {case['id']}.json")
        records.append({"id": case["id"], "path": str(matches[0].resolve()),
                        "sha256": case["sha256"], "bytes": case["bytes"]})
    result = temporary / "inventory.json"
    write_json(result, {"commit": COMMIT, "instances": records})
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path)
    parser.add_argument("--archives-dir", type=Path,
                        help="directory holding all five official archives named in data-archives-lock.json")
    parser.add_argument("--a", type=Path, help="extracted original A directory or A_set.7z")
    parser.add_argument("--b", type=Path)
    parser.add_argument("--c", type=Path)
    parser.add_argument("--x", type=Path)
    parser.add_argument("--lock", type=Path, default=ROOT / "data-lock.json")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="rte-prepare-") as temp:
        temporary = Path(temp)
        if args.inventory:
            inventory = args.inventory
        else:
            paths = {}
            if args.archives_dir:
                import py7zr
                archive_lock = json.loads((ROOT / "data-archives-lock.json").read_text())
                for entry in archive_lock["archives"]:
                    archive_path = args.archives_dir / entry["filename"]
                    if (archive_path.stat().st_size != entry["bytes"]
                            or sha256(archive_path) != entry["sha256"]):
                        raise ValueError("official archive checksum/size mismatch")
                    group = "X" if entry["key"].startswith("X") else entry["key"]
                    target = temporary / group
                    target.mkdir(exist_ok=True)
                    with py7zr.SevenZipFile(archive_path) as archive:
                        archive.extractall(target)
                    paths[group] = target
            for group in GROUPS:
                if group in paths:
                    continue
                source = getattr(args, group.lower())
                if source is None:
                    parser.error("provide --inventory or all --a/--b/--c/--x plus frozen --lock")
                if source.is_file():
                    import py7zr
                    target = temporary / group
                    target.mkdir()
                    with py7zr.SevenZipFile(source) as archive:
                        archive.extractall(target)
                    source = target
                paths[group] = source
            inventory = inventory_from_dirs(paths, args.lock, temporary)
        lock = materialize(inventory)
    print(f"Prepared {lock['public_count']} public ABC and {lock['protected_count']} protected X cases")


if __name__ == "__main__":
    main()
