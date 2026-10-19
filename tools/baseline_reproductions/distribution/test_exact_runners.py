"""Physical identity and information-flow regression checks for new references."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(Path(__file__).parent))
from powergym_exact import ExactEnv, RandomAgent  # noqa: E402

POOL = ROOT / "work/distribution-qualification-20261016/rl-pool"


@pytest.mark.skipif(not POOL.exists(), reason="private pinned source-data pool unavailable")
def test_exact_fixed_case_identity_and_replay():
    env = ExactEnv(POOL, "123Bus", split="train", seed=0)
    observation = env.reset(case_id="123Bus-rl-standard-p000-s1")
    target = json.loads(
        (
            ROOT / "task-packages/powergym-volt-var-control-formal-v1/tests/data/case.json"
        ).read_text()
    )
    for key in (
        "multipliers",
        "load_names",
        "model_file",
        "horizon",
        "scale",
        "step_hours",
        "terminal_energy_tolerance_kwh",
        "upstream_commit",
    ):
        assert env.case[key] == target[key]
    agent = RandomAgent(env.action_sizes, 0)
    for _ in range(24):
        observation, reward, done, _ = env.step(agent.act(observation))
        assert np.isfinite(observation).all() and np.isfinite(reward)
    assert done
    result = env.final_evaluation("regression-only")
    assert result["completed_steps"] == 24
    assert not result["valid"]
    assert result["error"] == "terminal_energy_violation"
    assert result["active_loss_kwh"] > 0


@pytest.mark.skipif(not POOL.exists(), reason="private pinned source-data pool unavailable")
def test_train_heldout_identity_unchanged_and_no_cross_split_reset():
    env = ExactEnv(POOL, "123Bus", split="heldout", seed=0)
    assert sorted(item["profile_index"] for item in env.cases) == [1, 6, 8, 9, 12, 13, 14, 15]
    with pytest.raises(ValueError, match="outside declared split"):
        env.reset(case_id="123Bus-rl-standard-p000-s1")


def test_random_agent_seed_and_action_domains():
    first, second = RandomAgent([2, 33, 33], 7), RandomAgent([2, 33, 33], 7)
    for _ in range(20):
        action = first.act(None)
        assert action == second.act(None)
        assert all(
            type(value) is int and 0 <= value < bound
            for value, bound in zip(action, [2, 33, 33], strict=True)
        )


def test_create_only_output_rejects_before_training(tmp_path):
    import argparse

    from powergym_exact import run

    with pytest.raises(FileExistsError):
        run(argparse.Namespace(output=tmp_path))


def test_hybrid_gradients_and_projection():
    import torch
    from cbat_sac import HybridActor, ProjectToBenchmarkGrid

    actor = HybridActor(7, [2] * 4 + [33] * 11, width=16, depth=2, activation="relu")
    state = torch.ones((3, 7))
    actions, logs = actor.sample(state, torch.Generator().manual_seed(4))
    assert actions.shape == (3, 15) and logs.shape == (3, 1)
    assert torch.isfinite(actions).all() and torch.isfinite(logs).all()
    (actions.sum() + logs.sum()).backward()
    assert any(p.grad is not None and p.grad.abs().sum() > 0 for p in actor.continuous.parameters())
    assert any(p.grad is not None and p.grad.abs().sum() > 0 for p in actor.integer.parameters())

    class Fixed:
        def act(self, *args, **kwargs):
            return [1] * 4 + [16] * 7 + [0.1, 7.6, 20.3, 31.99]

    assert ProjectToBenchmarkGrid(Fixed()).act(None)[-4:] == [0, 8, 20, 32]


@pytest.mark.skipif(not POOL.exists(), reason="private pinned source-data pool unavailable")
def test_continuous_battery_training_is_separate_from_benchmark_grid():
    env = ExactEnv(POOL, "123Bus", split="train", seed=1)
    env.continuous_battery = True
    env.reset(case_id="123Bus-rl-standard-p000-s1")
    action = [1] * 4 + [32] * 7 + [16.123, 16.0, 16.0, 16.0]
    _, _, done, info = env.step(action)
    assert not done
    assert info["physical_row"]["battery_command_kw"][0] == pytest.approx(0.76875)
    with pytest.raises(ValueError, match="bounded discrete integers"):
        standard = ExactEnv(POOL, "123Bus", split="train", seed=1)
        standard.reset(case_id="123Bus-rl-standard-p000-s1")
        standard.step(action)
