#!/usr/bin/env python3
"""Stage ignored, hash-verified Linux wheels and tests-only acceptance files."""

import argparse
import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def stage(wheelhouse: Path):
    lock = json.loads((ROOT / "images/wheels-lock.json").read_text())
    target = ROOT / "images/wheels"
    target.mkdir(exist_ok=True)
    for name, expected in lock["files"].items():
        source = wheelhouse / name
        if source.is_symlink() or hashlib.sha256(source.read_bytes()).hexdigest() != expected:
            raise ValueError(f"Linux wheel hash mismatch: {name}")
        shutil.copyfile(source, target / name)
    validation = ROOT / "tests/_validation"
    validation.mkdir(exist_ok=True)
    shutil.copyfile(ROOT / "verification/validate_runtime.py", validation / "validate_runtime.py")
    reference = ROOT / "tests/_reference"
    reference.mkdir(exist_ok=True)
    shutil.copyfile(ROOT / "environment/app/submission/controller.py", reference / "controller.py")
    return {
        "wheel_count": len(lock["files"]),
        "platform": lock["platform"],
        "validation_staged": True,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--wheelhouse", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(stage(args.wheelhouse)))
