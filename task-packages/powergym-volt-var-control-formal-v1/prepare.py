#!/usr/bin/env python3
"""Copy the previously frozen stress case and its exact DSS asset closure."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def digest(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise ValueError("expected regular nonsymlink input")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(pool: Path, destination: Path) -> dict:
    lock = json.loads((ROOT / "source-lock.json").read_text())
    pool = pool.resolve(strict=True)
    if destination.resolve().is_relative_to(pool):
        raise ValueError("formal data must be outside the historical pool")
    if destination.exists() or destination.is_symlink():
        raise FileExistsError("refusing to replace an existing formal case")
    if digest(pool / "pool.json") != lock["pool_sha256"]:
        raise ValueError("pool manifest differs from the selected qualification pool")
    for name, expected in lock["files"].items():
        path = pool / name
        if not path.resolve().is_relative_to(pool) or digest(path) != expected:
            raise ValueError("frozen formal source hash mismatch")
    destination.mkdir(parents=True, mode=0o700)
    for name in lock["files"]:
        target_name = "case.json" if name == lock["case_path"] else name.removeprefix("assets/")
        target = destination / target_name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(pool / name, target)
        if digest(target) != lock["files"][name]:
            raise ValueError("source changed during formal preparation")
    files = {
        str(p.relative_to(destination)): digest(p)
        for p in sorted(destination.rglob("*"))
        if p.is_file()
    }
    receipt = {
        "source_commit": lock["commit"],
        "pool_sha256": lock["pool_sha256"],
        "case_sha256": lock["case_sha256"],
        "files": files,
    }
    (destination / "data-lock.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return {
        "case_sha256": lock["case_sha256"],
        "data_lock_sha256": digest(destination / "data-lock.json"),
        "files": len(files),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--pool", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "tests/data")
    args = parser.parse_args()
    print(json.dumps(prepare(args.pool, args.output)))
