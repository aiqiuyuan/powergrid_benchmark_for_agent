#!/usr/bin/env python3
"""Freeze an accepted final source after the development controller has stopped."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "support"))
from official import regular_bytes


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    code = regular_bytes(args.candidate, 1 << 20)
    args.output_dir.mkdir(parents=True, exist_ok=False)
    frozen = args.output_dir / "solver.py"
    frozen.write_bytes(code)
    frozen.chmod(0o444)
    receipt = {"protocol": "rte2020-abc-x15-v2", "candidate_sha256": hashlib.sha256(code).hexdigest(),
               "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
               "filename": "solver.py", "stage": "frozen_final_source",
               "controller_requirement": "development stopped; no final report returned to agent"}
    (args.output_dir / "freeze-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
