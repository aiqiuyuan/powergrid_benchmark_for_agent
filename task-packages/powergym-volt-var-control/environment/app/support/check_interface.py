"""Execute only the bundled synthetic interface example; no target scorer."""

import importlib.util
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
toy = json.loads((root / "public/toy.json").read_text())
if toy.get("scope") != "synthetic-interface-only-no-target-case":
    raise ValueError("Only the bundled synthetic interface example is allowed")
spec = importlib.util.spec_from_file_location("starter", root / "submission/controller.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
controller = module.Controller(toy["metadata"])
actions = [controller.act(observation) for observation in toy["observations"]]
print(json.dumps({"scope": toy["scope"], "actions": actions}, allow_nan=False))
