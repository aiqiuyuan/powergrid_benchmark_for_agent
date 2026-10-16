#!/usr/bin/env python3
"""Independent all-profile preparation and immutable PPO/integer-SAC training runs."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import math
import os
import platform
import random
import sys
import time
from pathlib import Path

import numpy as np
import torch
from data import digest, prepare_pool, verify_pool
from env import PowerGymEnv

ROOT = Path(__file__).resolve().parents[2]


def immutable_json(path: Path, document: dict) -> None:
    payload = (json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    with path.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    with path.with_suffix(path.suffix + ".sha256").open("x") as handle:
        handle.write(digest(path) + "\n")


def finite_json(value):
    """Keep diagnostic evidence serializable even when the failure is nonfinite."""
    if isinstance(value, float) and not math.isfinite(value):
        return repr(value)
    if isinstance(value, dict):
        return {key: finite_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [finite_json(item) for item in value]
    return value


def algorithm_config(protocol: dict, algorithm: str) -> dict:
    return {**protocol["paper_reported"][algorithm], **protocol["assumptions"][algorithm]}


def make_agent(
    algorithm: str, observation_dim: int, action_sizes: list[int], config: dict, seed: int
):
    if algorithm == "ppo":
        from ppo import PPOAgent

        return PPOAgent(observation_dim, action_sizes, config, seed=seed)
    from sac import SACAgent

    return SACAgent(observation_dim, action_sizes, config, seed=seed)


def evaluate(
    agent, environment: PowerGymEnv, step: int, directory: Path, *, prefix: str = "heldout"
) -> dict:
    """Deterministic diagnostics; never select, tune, or update using these rewards."""
    episodes = []
    for item in environment.cases:
        observation = environment.reset(case_id=item["id"])
        for _ in range(24):
            observation, _, done, _ = environment.step(agent.act(observation, deterministic=True))
        if not done:
            raise ValueError("heldout evaluation did not end after 24 hours")
        result = environment.final_evaluation(f"{prefix}-step{step}")
        result["split"] = item["split"]
        episodes.append(result)
    summary = {
        "step": step,
        "scope": prefix,
        "selection_use": "prohibited",
        "episodes": episodes,
        "mean_rl_paper_vanilla_return": math.fsum(r["rl_paper_vanilla_return"] for r in episodes)
        / len(episodes),
        "valid_count": sum(r["valid"] for r in episodes),
        "qualification_valid_count": sum(r["qualification_valid"] for r in episodes),
        "environment_steps_cumulative": environment.environment_steps,
        "pf_calls_cumulative": environment.pf_calls,
        "replay_pf_calls_cumulative": environment.replay_pf_calls,
        "verification_pf_calls_cumulative": environment.verification_pf_calls,
    }
    immutable_json(directory / f"{prefix}-{step:06d}.json", summary)
    return {key: value for key, value in summary.items() if key != "episodes"}


def save_checkpoint(
    path: Path, agent, environment: PowerGymEnv, step: int, lock_sha: str, observation: np.ndarray
):
    """Mid-episode state includes replayable actions and unfinished PPO rollout."""
    state = {
        "schema_version": "powergym-rl-checkpoint-v2",
        "step": step,
        "run_lock_sha256": lock_sha,
        "agent": agent.training_state_dict(),
        "torch_rng": torch.get_rng_state(),
        "numpy_rng": np.random.get_state(),
        "python_rng": random.getstate(),
        "environment_random_state": environment.random.getstate(),
        "environment_case_id": environment.case["id"],
        "environment_episode_actions": [row["action"] for row in environment.rows],
        "environment_steps": environment.environment_steps,
        "observation": observation,
        "evaluation_selection_prohibited": True,
    }
    with path.open("xb") as handle:
        torch.save(state, handle)
        handle.flush()
        os.fsync(handle.fileno())
    with path.with_suffix(path.suffix + ".sha256").open("x") as handle:
        handle.write(digest(path) + "\n")


def run_training(args) -> dict:
    if digest(args.protocol) != args.protocol_sha256:
        raise ValueError("protocol SHA mismatch")
    protocol = json.loads(args.protocol.read_text())
    if protocol["schema_version"] != "powergym-rl-pilot-protocol-v2":
        raise ValueError("native reward v2 requires its matching v2 protocol")
    if protocol["status"] != "frozen":
        raise ValueError("training requires independently reviewed, frozen protocol")
    if (
        protocol["training_steps"] != 40000
        or protocol["checkpoints"] != [20000, 40000]
        or protocol["evaluation_interval"] != 120
    ):
        raise ValueError("this runner requires the declared actual-step pilot budget")
    if args.output.exists() or args.output.is_symlink():
        raise FileExistsError("run output exists; refusing to overwrite or silently resume")
    pool = verify_pool(args.pool)
    if (
        digest(args.pool / "pool.json") != args.pool_sha256
        or pool["split_seed"] != protocol["split_seed"]
    ):
        raise ValueError("pool/split identity mismatch")
    torch.set_num_threads(protocol["assumptions"]["runtime"]["torch_threads"])
    torch.use_deterministic_algorithms(True)
    seed = protocol["seed"]
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    training = PowerGymEnv(args.pool, protocol["network"], split="train", seed=seed)
    heldout = PowerGymEnv(args.pool, protocol["network"], split="heldout", seed=seed)
    observation = training.reset()
    config = algorithm_config(protocol, args.algorithm)
    agent = make_agent(args.algorithm, len(observation), training.action_sizes, config, seed)
    source_paths = list(Path(__file__).parent.glob("*.py")) + [
        ROOT / "tools/distribution_qualification/powergym_backend.py",
        ROOT / "tools/distribution_qualification/powergym_search.py",
        ROOT / "tools/distribution_selection/powergym_baselines/backend.py",
        ROOT / "tools/distribution_selection/powergym_baselines/__init__.py",
        ROOT / "tools/distribution_selection/powergym_selection.py",
        *sorted((ROOT / "src/powergrid_bench/distribution").glob("*.py")),
        ROOT / "src/powergrid_bench/__init__.py",
    ]
    lock = {
        "schema_version": "powergym-rl-run-lock-v2",
        "algorithm": args.algorithm,
        "protocol_sha256": args.protocol_sha256,
        "pool_sha256": args.pool_sha256,
        "protocol": protocol,
        "algorithm_config": config,
        "sources": {str(path.relative_to(ROOT)): digest(path) for path in sorted(source_paths)},
        "runtime": {
            "python": sys.version,
            "executable": sys.executable,
            "platform": platform.platform(),
            "torch_threads": torch.get_num_threads(),
            "versions": {
                key: importlib.metadata.version(key)
                for key in ("torch", "numpy", "dss-python", "dss-python-backend")
            },
        },
        "data_split": pool["splits"][protocol["network"]],
        "paper_score_reproduction": False,
    }
    args.output.mkdir(parents=True)
    immutable_json(args.output / "run-lock.json", lock)
    lock_sha = digest(args.output / "run-lock.json")
    started, step, diagnostics = time.monotonic(), 0, []
    extra_environments = []
    try:
        with (args.output / "training.jsonl").open("x") as log:
            for step in range(1, protocol["training_steps"] + 1):
                action = agent.act(observation)
                next_observation, reward, done, _ = training.step(action)
                metrics = agent.observe(observation, action, reward, next_observation, done)
                observation = next_observation
                log.write(
                    json.dumps(
                        {
                            "step": step,
                            "reward": reward,
                            "episode_done": done,
                            "profile_index": training.case["profile_index"],
                            "optimization": metrics,
                        },
                        allow_nan=False,
                    )
                    + "\n"
                )
                if done:
                    observation = training.reset()
                if step % protocol["evaluation_interval"] == 0:
                    diagnostics.append(evaluate(agent, heldout, step, args.output))
                    log.flush()
                if step == protocol["training_steps"]:
                    agent.finish()
                if step in protocol["checkpoints"]:
                    save_checkpoint(
                        args.output / f"checkpoint-{step:06d}.pt",
                        agent,
                        training,
                        step,
                        lock_sha,
                        observation,
                    )
            final = evaluate(agent, heldout, step, args.output, prefix="final-heldout")
        extras = []
        for split in ("train", "heldout"):
            extra = PowerGymEnv(args.pool, protocol["network"], split=split, seed=seed)
            extra_environments.append(extra)
            extra.cases = [
                row
                for row in extra.cases
                if row["profile_index"] in protocol["extra_comparison"]["pilot_compatible_profiles"]
            ]
            if extra.cases:
                extras.append(evaluate(agent, extra, step, args.output, prefix=f"extra-{split}"))
        result = {
            "complete": True,
            "training_steps": step,
            "training_full_episodes": step // 24,
            "training_partial_episode_steps": step % 24,
            "gradient_steps": getattr(agent, "gradient_steps", None),
            "training_pf_calls": training.pf_calls,
            "heldout_environment_steps": heldout.environment_steps,
            "heldout_pf_calls": heldout.pf_calls,
            "heldout_replay_pf_calls": heldout.replay_pf_calls,
            "heldout_verification_pf_calls": heldout.verification_pf_calls,
            "elapsed_seconds": time.monotonic() - started,
            "run_lock_sha256": lock_sha,
            "fixed_final_evaluation": final,
            "extra_comparisons": extras,
            "periodic_evaluations": diagnostics,
            "partial_training_episode_is_not_evaluation": True,
        }
        immutable_json(args.output / "summary.json", result)
        return result
    except Exception as exc:
        contexts = {
            "training": training,
            "heldout": heldout,
            **{f"extra{index}": env for index, env in enumerate(extra_environments)},
        }
        phase, active = max(
            contexts.items(), key=lambda pair: getattr(pair[1], "last_activity_ns", 0)
        )
        immutable_json(
            args.output / "failure.json",
            {
                "complete": False,
                "step": step,
                "error": f"{type(exc).__name__}: {exc}",
                "elapsed_seconds": time.monotonic() - started,
                "training_pf_calls": training.pf_calls,
                "heldout_pf_calls": heldout.pf_calls,
                "heldout_replay_pf_calls": heldout.replay_pf_calls,
                "heldout_verification_pf_calls": heldout.verification_pf_calls,
                "run_lock_sha256": lock_sha,
                "last_phase": phase,
                "last_case_id": getattr(active, "case", {}).get("id"),
                "last_completed_environment_steps": active.environment_steps,
                "last_episode_completed_steps": len(active.rows),
                "last_physical_row": finite_json(active.rows[-1]) if active.rows else None,
            },
        )
        raise


def evaluate_checkpoint(args) -> dict:
    lock_path = args.run / "run-lock.json"
    lock = json.loads(lock_path.read_text())
    if digest(lock_path) != lock_path.with_suffix(".json.sha256").read_text().strip():
        raise ValueError("saved run lock changed")
    if digest(args.checkpoint) != args.checkpoint.with_suffix(".pt.sha256").read_text().strip():
        raise ValueError("saved checkpoint changed")
    if digest(args.pool / "pool.json") != lock["pool_sha256"]:
        raise ValueError("checkpoint evaluation pool changed")
    for name, expected in lock["sources"].items():
        if digest(ROOT / name) != expected:
            raise ValueError(f"checkpoint source closure changed: {name}")
    if args.output.exists() or args.output.is_symlink():
        raise FileExistsError("evaluation output exists")
    # Only evaluate checkpoints produced by this local run and hash-checked above.
    state = torch.load(args.checkpoint, map_location="cpu", weights_only=False)
    if state["run_lock_sha256"] != digest(lock_path):
        raise ValueError("checkpoint belongs to another frozen run")
    protocol = lock["protocol"]
    torch.set_num_threads(protocol["assumptions"]["runtime"]["torch_threads"])
    environment = PowerGymEnv(
        args.pool, protocol["network"], split="heldout", seed=protocol["seed"]
    )
    observation = environment.reset()
    agent = make_agent(
        lock["algorithm"],
        len(observation),
        environment.action_sizes,
        lock["algorithm_config"],
        protocol["seed"],
    )
    agent.load_training_state_dict(state["agent"])
    args.output.mkdir(parents=True)
    immutable_json(
        args.output / "evaluation-lock.json",
        {
            "run_lock_sha256": digest(lock_path),
            "checkpoint_sha256": digest(args.checkpoint),
            "checkpoint_step": state["step"],
            "pool_sha256": lock["pool_sha256"],
            "purpose": "fixed-checkpoint heldout evaluation; selection prohibited",
        },
    )
    return evaluate(agent, environment, state["step"], args.output, prefix="checkpoint-heldout")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--source", type=Path, required=True)
    prepare.add_argument("--pool", type=Path, required=True)
    prepare.add_argument("--split-seed", type=int, default=0)
    train = commands.add_parser("train")
    train.add_argument("--algorithm", choices=("ppo", "sac"), required=True)
    train.add_argument("--protocol", type=Path, required=True)
    train.add_argument("--protocol-sha256", required=True)
    train.add_argument("--pool", type=Path, required=True)
    train.add_argument("--pool-sha256", required=True)
    train.add_argument("--output", type=Path, required=True)
    evaluate_parser = commands.add_parser("evaluate")
    evaluate_parser.add_argument("--run", type=Path, required=True)
    evaluate_parser.add_argument("--checkpoint", type=Path, required=True)
    evaluate_parser.add_argument("--pool", type=Path, required=True)
    evaluate_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "prepare":
        document = prepare_pool(args.source, args.pool, split_seed=args.split_seed)
        print(
            json.dumps(
                {
                    "cases": len(document["cases"]),
                    "splits": document["splits"],
                    "pool_sha256": digest(args.pool / "pool.json"),
                }
            )
        )
    elif args.command == "evaluate":
        print(json.dumps(evaluate_checkpoint(args)))
    else:
        summary = run_training(args)
        print(
            json.dumps(
                {
                    key: value
                    for key, value in summary.items()
                    if key not in ("periodic_evaluations", "extra_comparisons")
                }
            )
        )


if __name__ == "__main__":
    main()
