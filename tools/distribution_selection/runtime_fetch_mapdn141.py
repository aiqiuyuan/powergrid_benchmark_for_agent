"""Fetch the four pinned MAPDN141 members without changing historical canaries."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

PREPARER_SHA256 = "292e20f31e85fca2ac959aa178bbf03aa91d42f23b77d07c95ffd332655a777e"
NETWORK = "case141_3min_final"


def validate_destination(destination: Path, catalog: dict, dataset_commit: str) -> None:
    """Reject foreign caches before the reused preparer can replace any file."""
    preparation_receipt = destination / "preparation-receipt.json"
    if preparation_receipt.exists():
        old = json.loads(preparation_receipt.read_text())
        if old.get("network") != NETWORK or old.get("dataset_commit") != dataset_commit:
            raise RuntimeError("output contains a different network or dataset receipt")
    for name, expected in catalog.items():
        output = destination / name
        receipt = destination / (name + ".receipt.json")
        if not (output.exists() or receipt.exists()):
            continue
        if (
            output.is_symlink()
            or receipt.is_symlink()
            or not output.is_file()
            or not receipt.is_file()
        ):
            raise RuntimeError("existing member requires its regular-file receipt")
        old = json.loads(receipt.read_text())
        if old.get("dataset_commit") != dataset_commit or any(
            old.get(key) != value for key, value in expected.items()
        ):
            raise RuntimeError("output contains a member from a different ZIP entry")


def main() -> None:
    repository = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=repository / "work/distribution-selection/raw141",
    )
    parser.add_argument("--catalog-only", action="store_true")
    args = parser.parse_args()
    preparer = repository / "task-packages/mapdn-voltage-control-canary-v1/prepare.py"
    if hashlib.sha256(preparer.read_bytes()).hexdigest() != PREPARER_SHA256:
        raise RuntimeError("range preparer differs from the reviewed implementation")
    spec = importlib.util.spec_from_file_location("mapdn141_range_preparer", preparer)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load the reviewed range preparer")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.PREFIX = f"voltage_control_data/{NETWORK}/"
    catalog = module.entries()
    print(json.dumps({"network": NETWORK, "members": catalog}), flush=True)
    if args.catalog_only:
        return
    validate_destination(args.output, catalog, module.DATASET_COMMIT)
    args.output.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=4) as pool:
        receipts = list(
            pool.map(
                lambda name: module.extract_one(args.output, catalog[name]),
                module.MEMBERS,
            )
        )
    result = {
        "dataset_commit": module.DATASET_COMMIT,
        "archive_size_bytes": module.ARCHIVE_SIZE,
        "archive_sha256_verified": False,
        "network": NETWORK,
        "range_preparer_sha256": PREPARER_SHA256,
        "members": receipts,
    }
    (args.output / "preparation-receipt.json").write_text(
        json.dumps(result, indent=2) + "\n",
    )


if __name__ == "__main__":
    main()
