#!/usr/bin/env python3
"""Stage checked private case and offline wheels into native Docker contexts."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import zipfile
from email.parser import BytesParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", type=Path, required=True)
    parser.add_argument("--wheels", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads((args.case / "manifest.json").read_text())
    if set(manifest["files"]) != {"model.p", "trajectory.json"}:
        raise ValueError("unexpected case file set")
    for name, digest in manifest["files"].items():
        if sha256(args.case / name) != digest:
            raise ValueError("private case checksum mismatch")
    case = ROOT / "tests/data"
    case.mkdir(parents=True, exist_ok=True, mode=0o700)
    case.chmod(0o700)
    for name in ("model.p", "trajectory.json", "manifest.json"):
        destination = case / name
        if destination.exists() and sha256(destination) != sha256(args.case / name):
            raise ValueError("refusing to replace a different staged frozen case")
        shutil.copyfile(args.case / name, destination)
        destination.chmod(0o600)
    support = ROOT / "tests/support"
    support.mkdir(exist_ok=True)
    for source in (ROOT / "support").glob("*.py"):
        shutil.copyfile(source, support / source.name)
    validation = ROOT / "tests/_validation"
    validation.mkdir(exist_ok=True)
    for source in (ROOT / "verification").glob("*.py"):
        shutil.copyfile(source, validation / source.name)
    reference = ROOT / "tests/_reference"
    reference.mkdir(exist_ok=True)
    shutil.copyfile(ROOT / "environment/app/submission/controller.py", reference / "controller.py")
    shutil.copyfile(ROOT / "support/actor_worker.py", ROOT / "images/actor_worker.py")
    wheels = sorted(args.wheels.glob("*.whl"))
    if not wheels:
        raise ValueError("no offline Linux Python 3.12 wheels found")
    wheel_dir = ROOT / "images/wheels"
    wheel_dir.mkdir(exist_ok=True)
    assets = []
    locked = {}
    for source in wheels:
        destination = wheel_dir / source.name
        if destination.exists() and sha256(destination) != sha256(source):
            raise ValueError("offline wheel cache checksum mismatch")
        shutil.copyfile(source, destination)
        assets.append(
            {"file": source.name, "size": source.stat().st_size, "sha256": sha256(source)}
        )
        with zipfile.ZipFile(source) as wheel:
            names = [name for name in wheel.namelist() if name.endswith(".dist-info/METADATA")]
            if len(names) != 1:
                raise ValueError("wheel does not have unique package metadata")
            metadata = BytesParser().parsebytes(wheel.read(names[0]))
        key = re.sub(r"[-_.]+", "-", metadata["Name"]).lower()
        if key in locked:
            raise ValueError("multiple wheels for one package in the offline platform lock")
        locked[key] = (metadata["Version"], assets[-1]["sha256"])
    requirements = []
    for line in (ROOT / "images/requirements.txt").read_text().splitlines():
        name, version = line.split("==")
        key = re.sub(r"[-_.]+", "-", name).lower()
        if key not in locked or locked[key][0] != version:
            raise ValueError("offline wheel set does not cover all exact dependencies")
        requirements.append(f"{name}=={version} --hash=sha256:{locked[key][1]}")
    (ROOT / "images/requirements.lock").write_text("\n".join(requirements) + "\n")
    (ROOT / "images/wheels-lock.json").write_text(
        json.dumps(
            {
                "platform": "linux-amd64-cp312",
                "assets": assets,
            },
            indent=2,
        )
        + "\n"
    )
    receipt = {
        "case_manifest_sha256": sha256(case / "manifest.json"),
        "requirements_sha256": sha256(ROOT / "images/requirements.txt"),
        "offline_wheel_assets": assets,
        "source_sha256": {
            str(path.relative_to(ROOT)): sha256(path)
            for path in sorted((ROOT / "support").glob("*.py"))
        },
    }
    (case / "stage-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
