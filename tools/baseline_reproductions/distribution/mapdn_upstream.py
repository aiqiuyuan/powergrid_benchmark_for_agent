#!/usr/bin/env python3
"""Train unchanged MAPDN MADDPG/MATD3 then evaluate one fixed final checkpoint."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def record(path: Path, value: dict) -> None:
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


class Logger:
    """Original trainer statistics without an additional TensorBoard dependency."""

    def __init__(self, path: Path):
        self.stream = path.open("x")

    def add_scalar(self, name, value, step):
        self.stream.write(json.dumps({"name": name, "value": float(value), "episode": step}) + "\n")

    def close(self):
        self.stream.close()


def fixed_replay(network, config: dict, case_dir: Path) -> dict:
    """Rebuild only permitted per-actor inputs, preserving isolated RNN state."""
    import numpy as np
    import pandapower as pp
    import torch

    sys.path.insert(0, str(ROOT / "tools/distribution_selection"))
    from mapdn_baselines.simulation import (
        PF_OPTIONS,
        local_data,
        measure,
        set_exogenous,
        summarize,
    )

    manifest = json.loads((case_dir / "manifest.json").read_text())
    for name, expected in manifest["files"].items():
        if sha(case_dir / name) != expected:
            raise ValueError(f"fixed-case input digest changed: {name}")
    trajectory = json.loads((case_dir / "trajectory.json").read_text())
    net = pp.from_pickle(case_dir / "model.p")
    capacity = np.asarray(manifest["apparent_power_mva"])
    bound = 0.8
    previous = np.zeros(len(net.sgen))
    hidden = network.policy_dicts[0].init_hidden()
    network.eval()
    rows = []
    calls = 0
    error = None
    try:
        for step in range(480):
            capability = set_exogenous(net, trajectory, step, capacity)
            net.sgen.loc[:, "q_mvar"] = previous * capability
            pp.runpp(net, **PF_OPTIONS)
            calls += 1
            observations = []
            for actor in range(len(net.sgen)):
                _, obs = local_data(
                    net, actor, step, trajectory["timestamps"][step], bound, capacity
                )
                values = (
                    obs["region_demand_p_mw"]
                    + obs["region_demand_q_mvar"]
                    + obs["pv_active_mw"]
                    + obs["pv_reactive_mvar"]
                    + obs["region_voltage_pu"]
                    + [value * np.pi / 180 for value in obs["region_angle_degree"]]
                )
                if len(values) > config["obs_size"]:
                    raise ValueError("fixed-case local observation exceeds upstream dimensions")
                observations.append(values + [0.0] * (config["obs_size"] - len(values)))
            state = torch.tensor([observations], dtype=torch.float32)
            with torch.no_grad():
                action, _, _, _, hidden = network.get_actions(
                    state,
                    status="test",
                    exploration=False,
                    actions_avail=torch.ones((1, len(net.sgen), 1)),
                    target=False,
                    last_hid=hidden,
                )
            previous = action.cpu().numpy().reshape(-1) * bound
            if not np.isfinite(previous).all() or np.any(np.abs(previous) > bound):
                raise ValueError("upstream policy produced invalid action")
            net.sgen.loc[:, "q_mvar"] = previous * capability
            pp.runpp(net, **PF_OPTIONS)
            calls += 1
            rows.append(
                {**measure(net), "interval_index": step, "normalized_actions": previous.tolist()}
            )
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    metrics = summarize(rows, bus_count=33)
    valid = len(rows) == 480 and error is None
    quality = (
        (
            0.5 + 0.5 / (1 + metrics["actual_loss_mwh"])
            if metrics["bus_time_compliance"] == 1
            else 0.5 * metrics["bus_time_compliance"]
        )
        if valid
        else 0.0
    )
    return {
        "valid": valid,
        "quality": quality,
        "completed_intervals": len(rows),
        "pf_calls": calls,
        "metrics": metrics,
        "error": error,
        "steps": rows,
        "scope": "causal480step frozen benchmark replay; trained-weight extra track",
        "actor_information": "regional demand/PV/V/angle plus own hidden state",
        "runtime_contract": "trusted baseline weight inference; not stdlib submission",
    }


def run(args) -> dict:
    import numpy as np
    import torch
    import yaml

    if args.output.exists() or args.output.is_symlink():
        raise FileExistsError("create-only output exists")
    if args.episodes not in (1, 400):
        raise ValueError("only 1episode smoke or native400episode protocol")
    upstream = args.upstream.resolve(strict=True)
    receipt = json.loads((upstream / "source-receipt.json").read_text())
    if receipt["source_commit"] != "6895f1f0630b112745a3f681d7685d454407f9cb":
        raise ValueError("unexpected upstream revision")
    for name, expected in receipt["files"].items():
        if sha(upstream / name) != expected:
            raise ValueError(f"unchanged upstream source verification failed: {name}")
    data_receipt = json.loads((args.data / "preparation-receipt.json").read_text())
    for item in data_receipt["members"]:
        path = args.data / Path(item["member"]).name
        if sha(path) != item["sha256"]:
            raise ValueError(f"MAPDN source-data digest mismatch: {path.name}")
    sys.path.insert(0, str(upstream))
    from environments.var_voltage_control.voltage_control_env import VoltageControl
    from models.model_registry import Model
    from utilities.trainer import PGTrainer
    from utilities.util import convert, setup_voltage_control_scenario

    torch.set_num_threads(1)
    logging.getLogger("pandapower").setLevel(logging.ERROR)
    torch.use_deterministic_algorithms(True)
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    env_config = yaml.safe_load((upstream / "args/env_args/var_voltage_control.yaml").read_text())[
        "env_args"
    ]
    setup_voltage_control_scenario(env_config, "case33_3min_final")
    env_config.update(
        data_path=str(args.data.resolve()),
        seed=args.seed,
        mode="distributed",
        voltage_barrier_type="bowl",
    )
    config = yaml.safe_load((upstream / "args/default.yaml").read_text())
    config.update(
        yaml.safe_load((upstream / f"args/alg_args/{args.algorithm}.yaml").read_text())["alg_args"]
    )
    config.update(
        cuda=False, action_scale=env_config["action_scale"], action_bias=env_config["action_bias"]
    )
    args.output.mkdir(parents=True)
    started = time.monotonic()
    episode = 0
    logger = Logger(args.output / "statistics.jsonl")
    try:
        environment = VoltageControl(env_config)
        config.update(
            agent_num=environment.get_num_of_agents(),
            obs_size=environment.get_obs_size(),
            action_dim=environment.get_total_actions(),
        )
        lock = {
            "schema": "mapdn-upstream-baseline-v1",
            "algorithm": args.algorithm,
            "upstream_commit": receipt["source_commit"],
            "upstream_files": receipt["files"],
            "dataset": data_receipt,
            "seed": args.seed,
            "requested_episodes": args.episodes,
            "native_training_config": config,
            "environment_config": env_config,
            "versions": {
                "python": sys.version,
                "torch": torch.__version__,
                "numpy": np.__version__,
            },
            "runner_sha256": sha(Path(__file__)),
            "checkpoint_selection": "final400episode; native tests never select checkpoint",
            "training_data_permissions": "upstream full multi-day stochastic training data",
            "split": "native random start episodes; no calendar holdout claim",
            "formal_target": "same known fixed day; extra trained-weight reference track",
            "device_difference": "CPU deterministic run, upstream launchers request GPU",
        }
        record(args.output / "run-lock.json", lock)
        trainer = PGTrainer(convert(config), Model[args.algorithm], environment, logger)
        with (args.output / "progress.jsonl").open("x") as progress:
            for episode in range(args.episodes):
                statistics = {}
                before = trainer.steps
                trainer.run(statistics, episode)
                trainer.logging(statistics)
                progress.write(
                    json.dumps(
                        {
                            "episode": episode + 1,
                            "actual_training_transitions": trainer.steps,
                            "episode_training_transitions": trainer.steps - before,
                            "native_statistics": statistics,
                            "elapsed_seconds": time.monotonic() - started,
                        }
                    )
                    + "\n"
                )
                progress.flush()
        checkpoint = args.output / "fixed-final.pt"
        with checkpoint.open("xb") as stream:
            torch.save(
                {
                    "model_state_dict": trainer.behaviour_net.state_dict(),
                    "episodes": trainer.episodes,
                    "steps": trainer.steps,
                    "run_lock_sha256": sha(args.output / "run-lock.json"),
                },
                stream,
            )
        record(
            args.output / "checkpoint.json",
            {
                "sha256": sha(checkpoint),
                "episodes": trainer.episodes,
                "actual_training_transitions": trainer.steps,
            },
        )
        replay = fixed_replay(trainer.behaviour_net, config, args.case)
        record(args.output / "fixed-case.json", replay)
        result = {
            "complete": True,
            "training_episodes": trainer.episodes,
            "actual_training_transitions": trainer.steps,
            "elapsed_seconds": time.monotonic() - started,
            "fixed_case": {key: value for key, value in replay.items() if key != "steps"},
        }
        record(args.output / "summary.json", result)
        return result
    except BaseException as exc:
        record(
            args.output / "failure.json",
            {
                "complete": False,
                "episode_index": episode,
                "error": f"{type(exc).__name__}: {exc}",
                "elapsed_seconds": time.monotonic() - started,
            },
        )
        raise
    finally:
        logger.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--case", type=Path, required=True)
    parser.add_argument("--algorithm", choices=("maddpg", "matd3"), required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--episodes", type=int, default=400)
    parser.add_argument("--output", type=Path, required=True)
    print(json.dumps(run(parser.parse_args())))


if __name__ == "__main__":
    main()
