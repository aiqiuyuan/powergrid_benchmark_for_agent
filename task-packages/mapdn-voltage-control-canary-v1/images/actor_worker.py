#!/usr/bin/env python3
"""Public per-actor JSON-lines bridge. No simulator or target files are imported."""

from __future__ import annotations

import contextlib
import importlib.util
import json
import sys
from pathlib import Path


def main() -> None:
    source = Path(sys.argv[1])
    first = json.loads(sys.stdin.readline())
    with contextlib.redirect_stdout(sys.stderr):
        spec = importlib.util.spec_from_file_location("candidate", source)
        if spec is None or spec.loader is None:
            raise ValueError("candidate module cannot be loaded")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        controller = module.Controller(first["metadata"])
    print(json.dumps({"ready": True}), flush=True)
    for line in sys.stdin:
        message = json.loads(line)
        with contextlib.redirect_stdout(sys.stderr):
            action = controller.act(message["observation"])
        print(json.dumps({"action": action}, allow_nan=False), flush=True)


if __name__ == "__main__":
    main()
