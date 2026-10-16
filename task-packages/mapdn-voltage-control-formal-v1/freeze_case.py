#!/usr/bin/env python3
"""Rebundle only the exact qualified fixed case, without modifying its bytes."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "support"))
from mapdn_contract import (
    CAPACITIES,
    CASE_ID,
    POOL_SHA256,
    SOURCE_SHA256,
    expected_manifest,  # noqa: E402
    json_bytes,
    sha256,
    validate_case,
)


def freeze_pool(pool_dir: Path, output: Path) -> dict:
    """Consume the frozen six-day pool; only this one trajectory is staged."""
    if sha256(pool_dir / "pool.json") != POOL_SHA256:
        raise ValueError("selection pool checksum differs from the qualified pool")
    pool = json.loads((pool_dir / "pool.json").read_text())
    if (
        pool["source_sha256"] != SOURCE_SHA256
        or pool["apparent_power_mva"] != CAPACITIES
        or pool["horizon"] != 480
        or pool["normalized_action_bound"] != 0.8
    ):
        raise ValueError("selection pool physical contract mismatch")
    manifest = expected_manifest()
    inputs = {
        "model.p": pool_dir / "assets/model.p",
        "trajectory.json": pool_dir / "cases" / CASE_ID / "trajectory.json",
    }
    for name, path in inputs.items():
        if sha256(path) != manifest["files"][name]:
            raise ValueError(f"qualified case checksum mismatch: {name}")
    if output.exists() and any(output.iterdir()):
        raise ValueError("refusing to replace an existing frozen bundle")
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    output.chmod(0o700)
    for name, source in inputs.items():
        shutil.copyfile(source, output / name)
        (output / name).chmod(0o600)
    (output / "manifest.json").write_bytes(json_bytes(manifest))
    (output / "manifest.json").chmod(0o600)
    validate_case(output)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pool", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = freeze_pool(args.pool, args.output)
    print(
        json.dumps(
            {
                "case_id": manifest["case_id"],
                "horizon": 480,
                "manifest_sha256": sha256(args.output / "manifest.json"),
                "files": manifest["files"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
