#!/usr/bin/env python3
"""Unmetered ABC development evaluation; never opens or queries protected X data."""
import argparse
import json
import math
from pathlib import Path
import tempfile

from runner import evaluate_manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, default=Path("/app/submission/solver.py"))
    parser.add_argument("--manifest", type=Path, default=Path("/app/public/manifest.json"))
    parser.add_argument("--case", help="optional single A/B/C case, e.g. C_15")
    parser.add_argument("--seconds", type=float, default=900)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--unsafe", action="store_true", help="trusted local development only")
    args = parser.parse_args()
    original = json.loads(args.manifest.read_text())
    if original["split"] != "public_abc" or any(c["id"].startswith("X_") for c in original["cases"]):
        parser.error("public evaluator only accepts ABC development manifests")
    if not 0 < args.seconds <= 900:
        parser.error("--seconds must be in (0,900]")
    original["seconds_per_case"] = args.seconds
    if args.case:
        original["cases"] = [c for c in original["cases"] if c["id"] == args.case]
        if not original["cases"]:
            parser.error("unknown ABC case")
    count = len(original["cases"])
    budget = math.ceil(count / args.workers) * (args.seconds + 300) + 30
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", dir=args.manifest.parent) as stream:
        json.dump(original, stream)
        stream.flush()
        result = evaluate_manifest(args.candidate, Path(stream.name), support=Path(__file__).parent,
                                   secure=not args.unsafe, timeout=budget, workers=args.workers)
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
