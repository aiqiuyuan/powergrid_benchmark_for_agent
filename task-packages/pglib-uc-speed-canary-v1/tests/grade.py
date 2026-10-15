"""Native Harbor entry; private inputs, bounds, and raw diagnostics stay private."""

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "support"))
from runner import evaluate  # noqa: E402 -- trusted support is staged beside this entry point


def main() -> None:
    log = Path(os.environ.get("LOG_DIR", "/logs/verifier"))
    log.mkdir(mode=0o700, parents=True, exist_ok=True)
    log.chmod(0o700)
    (log / "reward.json").write_text(json.dumps({"reward": 0.0}))
    (log / "reward-details.json").write_text(
        json.dumps(
            {
                "reward": 0.0,
                "metric": None,
                "valid": False,
                "evaluation_completed": False,
                "error": "infrastructure-failure",
                "feedback": "",
                "details": {},
            }
        )
    )
    phase = os.environ.get("UC_SPEED_PHASE", "terminal")
    if phase not in {"feedback", "terminal"}:
        raise RuntimeError("Invalid trusted evaluation phase")
    manifest = ROOT / "data/manifest.json"
    if json.loads(manifest.read_text()).get("deployment_accepted") is not True:
        raise RuntimeError("Runtime deployment acceptance has not passed")
    result = evaluate(
        Path(os.environ.get("APP_DIR", "/app")) / "submission",
        manifest,
        seeds=[0] if phase == "feedback" else [0, 1, 2],
        secure=True,
    )
    feedback = result["feedback"] if phase == "feedback" else result["ranking"]
    details = {
        "reward": feedback["reward"],
        "metric": feedback["reward"],
        "metric_name": "uc_reference_quality_reward",
        "metric_direction": "higher",
        "valid": feedback["feasible"],
        "evaluation_completed": True,
        "error": feedback["failure_category"],
        "feedback": json.dumps(feedback, sort_keys=True, allow_nan=False),
        "details": result,
    }
    # The native judge archives details in its private ledger; its result API
    # exposes only feedback/metric/reward, never this unrounded diagnostics field.
    (log / "reward.json").write_text(json.dumps({"reward": feedback["reward"]}))
    (log / "reward-details.json").write_text(json.dumps(details, allow_nan=False))
    print("UC source evaluation complete")


if __name__ == "__main__":
    main()
