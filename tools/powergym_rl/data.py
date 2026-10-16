"""Freeze all sixteen upstream profiles separately from the six-case selection pool."""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/distribution_selection"))
from powergym_selection import digest, freeze_pool, write_json  # noqa: E402

from powergrid_bench.distribution.profiles import pack_profiles  # noqa: E402


def split_indices(count: int, seed: int) -> tuple[list[int], list[int]]:
    if count != 16:
        raise ValueError("paper-compatible data preparation requires all sixteen source profiles")
    indices = np.random.default_rng(seed).permutation(count).tolist()
    return sorted(indices[: count // 2]), sorted(indices[count // 2 :])


def prepare_pool(source: Path, destination: Path, *, split_seed: int) -> dict:
    source, destination = source.resolve(strict=True), destination.absolute()
    if destination.exists() or destination.is_symlink():
        raise FileExistsError("RL pool already exists; refusing to overwrite")
    if destination.resolve().is_relative_to(source):
        raise ValueError("RL pool cannot be written inside verified source")
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary) / "selection-source-check"
        parent = freeze_pool(source, base)
        preparations = []
        for network in ("34Bus", "123Bus"):
            item = next(
                row
                for row in parent["cases"]
                if row["network"] == network and row["group"] == "standard"
            )
            prototype = json.loads((base / item["path"]).read_text())
            curves = sorted(
                (source / "systems" / network / "loadshape").glob("*"),
                key=lambda path: path.name.casefold(),
            )
            curves = [
                path
                for path in curves
                if "loadshape" in path.name.lower() and path.suffix.lower() == ".csv"
            ]
            packed = pack_profiles(curves, load_count=len(prototype["load_names"]), horizon=24)
            if len(packed.profiles) != 16:
                raise ValueError("complete source does not contain exactly sixteen profiles")
            preparations.append((network, prototype, packed.profiles))
        destination.mkdir(parents=True)
        shutil.copytree(base / "assets", destination / "assets")
        shutil.copyfile(base / "UPSTREAM-LICENSE", destination / "UPSTREAM-LICENSE")
        cases, splits = [], {}
        for network, prototype, profiles in preparations:
            train, heldout = split_indices(len(profiles), split_seed)
            splits[network] = {"train_indices": train, "heldout_indices": heldout}
            for index, multipliers in enumerate(profiles):
                case = {
                    **prototype,
                    "id": f"{network}-rl-standard-p{index:03d}-s1",
                    "profile_index": index,
                    "multipliers": multipliers,
                    "schema_version": "powergym-rl-case-v1",
                }
                path = destination / "cases" / f"{case['id']}.json"
                path.parent.mkdir(exist_ok=True)
                write_json(path, case)
                cases.append(
                    {
                        "id": case["id"],
                        "network": network,
                        "profile_index": index,
                        "split": "train" if index in train else "heldout",
                        "path": str(path.relative_to(destination)),
                        "sha256": digest(path),
                    }
                )
        files = {
            str(path.relative_to(destination)): digest(path)
            for path in sorted(destination.rglob("*"))
            if path.is_file()
        }
        document = {
            "schema_version": "powergym-rl-pool-v1",
            "upstream_commit": parent["upstream_commit"],
            "source_files": parent["source_files"],
            "parent_selection_pool_sha256": digest(base / "pool.json"),
            "split_seed": split_seed,
            "split_rule": "numpy.default_rng(seed).permutation, first 8 train / last 8 heldout",
            "canonical_source_order": (
                "casefold filename sorted; upstream os.listdir order unspecified"
            ),
            "all_sixteen_profiles_retained": True,
            "calendar_independence_verified": False,
            "cases": cases,
            "splits": splits,
            "files": files,
            "release_ready": False,
            "paper_runtime_and_score_reproduction": False,
        }
        write_json(destination / "pool.json", document)
        (destination / "pool.sha256").write_text(digest(destination / "pool.json") + "\n")
        return document


def verify_pool(directory: Path) -> dict:
    directory = directory.resolve(strict=True)
    if digest(directory / "pool.json") != (directory / "pool.sha256").read_text().strip():
        raise ValueError("RL pool identity changed")
    document = json.loads((directory / "pool.json").read_text())
    if document["schema_version"] != "powergym-rl-pool-v1":
        raise ValueError("not an independent complete-profile RL pool")
    for name, expected in document["files"].items():
        path = directory / name
        if not path.resolve().is_relative_to(directory) or digest(path) != expected:
            raise ValueError(f"frozen RL asset changed: {name}")
    for network in ("34Bus", "123Bus"):
        rows = [row for row in document["cases"] if row["network"] == network]
        if len(rows) != 16 or sorted(row["profile_index"] for row in rows) != list(range(16)):
            raise ValueError("RL pool does not cover all original profiles exactly once")
        train, heldout = split_indices(16, document["split_seed"])
        if document["splits"][network] != {"train_indices": train, "heldout_indices": heldout}:
            raise ValueError("RL pool split does not match the recorded seed")
        if any(
            row["split"] != ("train" if row["profile_index"] in train else "heldout")
            for row in rows
        ):
            raise ValueError("RL case labels contradict the split manifest")
    return document
