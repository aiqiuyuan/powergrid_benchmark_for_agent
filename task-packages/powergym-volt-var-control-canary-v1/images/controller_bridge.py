#!/usr/bin/env python3
"""Public JSONL bridge: only metadata/current observations enter the candidate."""

import contextlib
import importlib.util
import json
import sys
from pathlib import Path


def main():
    request = json.loads(sys.stdin.readline())
    # This trusted handshake precedes all candidate imports and separates
    # sandbox/bridge startup failures from candidate-caused initialization exits.
    print(json.dumps({"bridge_ready": True}), flush=True)
    with contextlib.redirect_stdout(sys.stderr):
        spec = importlib.util.spec_from_file_location("candidate", Path(sys.argv[1]))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        controller = module.Controller(request["metadata"])
    print(json.dumps({"ready": True}), flush=True)
    for line in sys.stdin:
        observation = json.loads(line)["observation"]
        with contextlib.redirect_stdout(sys.stderr):
            action = controller.act(observation)
        print(json.dumps({"action": action}, allow_nan=False), flush=True)


if __name__ == "__main__":
    main()
