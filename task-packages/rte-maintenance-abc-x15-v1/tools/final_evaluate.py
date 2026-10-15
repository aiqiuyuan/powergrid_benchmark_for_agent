#!/usr/bin/env python3
"""Offline private frozen-source X15 final evaluation; no feedback-ledger endpoint."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "support"))
from official import regular_bytes
from runner import evaluate_manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--freeze-receipt", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    code = regular_bytes(args.candidate, 1 << 20)
    digest = hashlib.sha256(code).hexdigest()
    receipt = json.loads(args.freeze_receipt.read_text())
    if (receipt.get("protocol") != "rte2020-abc-x15-v1"
            or receipt.get("stage") != "frozen_final_5400"
            or receipt.get("candidate_sha256") != digest):
        raise ValueError("final source does not match its freeze receipt")
    manifest = json.loads(args.manifest.read_text())
    if (manifest["split"] != "protected_x15_feedback"
            or [c["id"] for c in manifest["cases"]] != [f"X_{n:02d}" for n in range(1, 16)]):
        raise ValueError("final evaluation requires the complete locked X15 panel")
    if args.output.exists():
        raise FileExistsError("refusing to overwrite a private final report")
    manifest["seconds_per_case"] = 5400
    manifest["split"] = "protected_x15_frozen_final"
    # A private temporary manifest beside inputs keeps all relative data paths fixed.
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", dir=args.manifest.parent) as stream:
        json.dump(manifest, stream)
        stream.flush()
        result = evaluate_manifest(args.candidate, Path(stream.name),
                                   support=Path(__file__).resolve().parents[1] / "support",
                                   secure=True, timeout=6300, workers=15)
    if result["candidate_sha256"] != digest:
        raise RuntimeError("candidate changed between freeze verification and evaluation")
    result.update(stage="frozen_final_5400", returns_to_developer=False,
                  feedback_budget_charged=False, freeze_receipt=receipt)
    args.output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with args.output.open("x") as output:
        output.write(json.dumps(result, indent=2, allow_nan=False) + "\n")
    args.output.chmod(0o600)
    print("Private frozen-final report saved")


if __name__ == "__main__":
    main()
