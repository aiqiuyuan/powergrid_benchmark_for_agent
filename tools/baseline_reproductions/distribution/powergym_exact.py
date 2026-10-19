#!/usr/bin/env python3
"""Fixed final-policy PowerGym references on the frozen 123Bus stress contract.

This runner reuses the independently implemented PPO / integer SAC. Training is
an extra-information reference track, not an n-budget developer repetition.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools/powergym_rl"))

import numpy as np  # noqa: E402
import torch  # noqa: E402
from data import digest, verify_pool  # noqa: E402
from env import PowerGymEnv  # noqa: E402
from train import algorithm_config, immutable_json, make_agent  # noqa: E402


class ExactEnv(PowerGymEnv):
    """Read unchanged source profiles; scale an independent physical copy."""

    def reset(self, *, case_id: str | None = None) -> np.ndarray:
        from powergym_backend import QualificationBackend

        item = (
            next((row for row in self.cases if row["id"] == case_id), None)
            if case_id
            else self.random.choice(self.cases)
        )
        if item is None:
            raise ValueError("case is outside declared split")
        path = self.pool_dir / item["path"]
        if digest(path) != item["sha256"]:
            raise ValueError("profile digest changed")
        case = json.loads(path.read_text())
        self.case = {
            **case,
            "id": f"123Bus-stress-p{case['profile_index']:03d}-s2.5",
            "scale": 2.5,
            "group": "stress",
            "multipliers": [[float(value) * 2.5 for value in row] for row in case["multipliers"]],
        }
        self.assets = self.pool_dir / "assets" / "123Bus"
        if getattr(self, "continuous_battery", False):
            from cbat_sac import ContinuousBatteryBackend

            self.backend = ContinuousBatteryBackend(self.case, self.assets)
        else:
            self.backend = QualificationBackend(self.case, self.assets)
        self.rows = []
        self.last_activity_ns = time.monotonic_ns()
        self.pf_calls += self.backend.pf_calls
        self.reset_calls += 1
        return self.observation()


class RandomAgent:
    def __init__(self, sizes: list[int], seed: int):
        self.random = np.random.default_rng(seed)
        self.sizes = sizes

    def act(self, observation, deterministic=False) -> list[int]:
        return [int(self.random.integers(size)) for size in self.sizes]


def evaluate_fixed(agent, environment: ExactEnv, directory: Path) -> dict:
    observation = environment.reset(case_id="123Bus-rl-standard-p000-s1")
    for _ in range(24):
        observation, _, done, _ = environment.step(agent.act(observation, deterministic=True))
    if not done:
        raise ValueError("fixed-case evaluation incomplete")
    result = environment.final_evaluation("fixed-final-123Bus-p000-s2.5")
    immutable_json(directory / "fixed-case.json", result)
    return {key: value for key, value in result.items() if key != "trajectory"}


def source_lock() -> dict[str, str]:
    paths = sorted(
        {
            *Path(__file__).parent.glob("*.py"),
            *(ROOT / "tools/powergym_rl").glob("*.py"),
            *(ROOT / "tools/distribution_qualification").glob("powergym*.py"),
            *(ROOT / "tools/distribution_selection/powergym_baselines").glob("*.py"),
            ROOT / "tools/distribution_selection/powergym_selection.py",
            *(ROOT / "src/powergrid_bench/distribution").glob("*.py"),
        }
    )
    return {str(path.relative_to(ROOT)): digest(path) for path in paths}


def run(args) -> dict:
    if args.output.exists() or args.output.is_symlink():
        raise FileExistsError("create-only run output exists")
    protocol = json.loads(args.protocol.read_text())
    if digest(args.protocol) != args.protocol_sha256 or protocol["status"] != "frozen":
        raise ValueError("frozen parent protocol digest mismatch")
    pool = verify_pool(args.pool)
    if digest(args.pool / "pool.json") != args.pool_sha256 or pool["split_seed"] != 0:
        raise ValueError("frozen complete-profile pool mismatch")
    if args.steps not in (24, 40000):
        raise ValueError("only declared 24-step smoke or 40000-step full runs")
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    args.output.mkdir(parents=True)
    lock = {
        "schema": "powergym-exact-baseline-v1",
        "algorithm": args.algorithm,
        "seed": args.seed,
        "actual_training_transitions": 0 if args.algorithm == "random" else args.steps,
        "parent_protocol_sha256": args.protocol_sha256,
        "pool_sha256": args.pool_sha256,
        "sources": source_lock(),
        "network": "123Bus",
        "scale": 2.5,
        "fixed_profile": 0,
        "training_profiles": pool["splits"]["123Bus"]["train_indices"],
        "heldout_profiles": pool["splits"]["123Bus"]["heldout_indices"],
        "profile0_is_training_data": True,
        "selection": "final transition only; no evaluation checkpoint selection",
        "reward": "paper vanilla reward; no hard-energy penalty or repair",
        "scope": "independent same-contract retraining; not native paper score reproduction",
        "extra_training_permissions": "full training-profile simulator interactions and reward",
        "formal_actor_permissions": "current voltage/device observations; no simulator calls",
        "versions": {"python": sys.version, "torch": torch.__version__, "numpy": np.__version__},
        "periodic_evaluation": "omitted; final checkpoint evaluated once on fixed target",
        "cbat_reconstruction_assumptions": (
            {
                "actor": "ST-Gumbel cap/tap heads plus diagonal Gaussian batteries",
                "gaussian_log_std_clip": [-20, 2],
                "tanh_jacobian_epsilon": 1e-6,
                "continuous_projection": "clip kW to present energy bounds, no grid rounding",
                "terminal_benchmark_adapter": "nearest33point battery action grid; named projected",
                "native_paper_reproduction": False,
            }
            if args.algorithm == "cbat-sac-projected"
            else None
        ),
    }
    immutable_json(args.output / "run-lock.json", lock)
    started = time.monotonic()
    step = 0
    training = ExactEnv(args.pool, "123Bus", split="train", seed=args.seed)
    training.continuous_battery = args.algorithm == "cbat-sac-projected"
    try:
        observation = training.reset()
        if args.algorithm == "random":
            agent = RandomAgent(training.action_sizes, args.seed)
        else:
            config = algorithm_config(
                protocol, "sac" if training.continuous_battery else args.algorithm
            )
            if training.continuous_battery:
                from cbat_sac import HybridSAC

                agent = HybridSAC(len(observation), training.action_sizes, config, args.seed)
            else:
                agent = make_agent(
                    args.algorithm, len(observation), training.action_sizes, config, args.seed
                )
            with (args.output / "training.jsonl").open("x") as stream:
                for step in range(1, args.steps + 1):
                    action = agent.act(observation)
                    next_observation, reward, done, _ = training.step(action)
                    metrics = agent.observe(observation, action, reward, next_observation, done)
                    observation = next_observation
                    stream.write(
                        json.dumps(
                            {
                                "step": step,
                                "reward": reward,
                                "profile": training.case["profile_index"],
                                "done": done,
                                "optimization": metrics,
                            }
                        )
                        + "\n"
                    )
                    if done:
                        observation = training.reset()
                    if step % 120 == 0:
                        stream.flush()
                agent.finish()
            checkpoint = args.output / "fixed-final.pt"
            with checkpoint.open("xb") as stream:
                torch.save(
                    {
                        "step": step,
                        "state": agent.training_state_dict(),
                        "run_lock_sha256": digest(args.output / "run-lock.json"),
                    },
                    stream,
                )
            immutable_json(
                args.output / "checkpoint.json",
                {
                    "step": step,
                    "sha256": digest(checkpoint),
                    "checkpoint_selection": "fixed final; no periodic test selection",
                },
            )
        if training.continuous_battery:
            from cbat_sac import ProjectToBenchmarkGrid

            agent = ProjectToBenchmarkGrid(agent)
        fixed = evaluate_fixed(
            agent, ExactEnv(args.pool, "123Bus", split="train", seed=args.seed + 100), args.output
        )
        result = {
            "complete": True,
            "algorithm": args.algorithm,
            "seed": args.seed,
            "actual_training_transitions": step,
            "training_pf_calls": training.pf_calls,
            "elapsed_seconds": time.monotonic() - started,
            "fixed_case": fixed,
            "source_closure_sha256": hashlib.sha256(
                json.dumps(lock["sources"], sort_keys=True).encode()
            ).hexdigest(),
        }
        immutable_json(args.output / "summary.json", result)
        return result
    except BaseException as exc:
        immutable_json(
            args.output / "failure.json",
            {
                "complete": False,
                "step": step,
                "error": f"{type(exc).__name__}: {exc}",
                "elapsed_seconds": time.monotonic() - started,
            },
        )
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--algorithm", choices=("random", "ppo", "sac", "cbat-sac-projected"), required=True
    )
    parser.add_argument("--pool", type=Path, required=True)
    parser.add_argument("--pool-sha256", required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--protocol-sha256", required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--steps", type=int, default=40000)
    parser.add_argument("--output", type=Path, required=True)
    print(json.dumps(run(parser.parse_args())))


if __name__ == "__main__":
    main()
