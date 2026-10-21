"""Independent RL data splits, observation timing, and integer SAC gradients."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/powergym_rl"))

NUMPY_AVAILABLE = importlib.util.find_spec("numpy") is not None
DSS_AVAILABLE = importlib.util.find_spec("dss") is not None
if NUMPY_AVAILABLE:
    from data import split_indices


@unittest.skipUnless(NUMPY_AVAILABLE, "requires isolated NumPy runtime")
class DataTests(unittest.TestCase):
    def test_split_uses_all_complete_profiles_and_has_no_overlap(self):
        train, test = split_indices(16, 0)
        self.assertEqual(len(train), 8)
        self.assertEqual(len(test), 8)
        self.assertFalse(set(train) & set(test))
        self.assertEqual(sorted(train + test), list(range(16)))
        self.assertEqual((train, test), split_indices(16, 0))
        self.assertNotEqual((train, test), split_indices(16, 1))
        with self.assertRaises(ValueError):
            split_indices(6, 0)


@unittest.skipUnless(NUMPY_AVAILABLE, "requires isolated NumPy runtime")
class NativeRewardTests(unittest.TestCase):
    def row(self, source):
        return {
            "active_loss_kw": 10.0,
            "source_active_kw": source,
            "voltage_violation_pu_hours": 0.02,
            "capacitor_switches": 1,
            "tap_moves": 2,
            "battery_command_kw": [100.0, -50.0],
            "paper_vanilla_reward_diagnostic": None,
        }

    def test_positive_flow_equals_original_reward_and_reverse_flow_clips_to_zero(self):
        from env import native_vanilla_reward

        positive, reverse = self.row(100.0), self.row(-5.0)
        expected_positive = -(0.02 + 0.1 + 3 / 33 + (10 / 33) * 0.2)
        expected_reverse = -(0.02 + 0.0 + 3 / 33 + (10 / 33) * 0.2)
        self.assertEqual(
            native_vanilla_reward(positive, "34Bus", [500.0, 500.0]), expected_positive
        )
        self.assertEqual(native_vanilla_reward(reverse, "34Bus", [500.0, 500.0]), expected_reverse)
        self.assertIsNone(reverse["paper_vanilla_reward_diagnostic"])

    def test_zero_source_has_explicit_saturated_penalty_and_nonfinite_inputs_fail(self):
        from env import native_vanilla_reward

        for source, loss in ((0.0, 10.0), (0.0, 0.0), (-0.0, 0.0)):
            row = self.row(source)
            row["active_loss_kw"] = loss
            self.assertEqual(
                native_vanilla_reward(row, "34Bus", [500.0, 500.0]),
                -(0.02 + 1.0 + 3 / 33 + (10 / 33) * 0.2),
            )
        self.assertEqual(
            native_vanilla_reward(self.row(-0.0), "34Bus", [500.0, 500.0]),
            -(0.02 + 0.0 + 3 / 33 + (10 / 33) * 0.2),
        )
        for key in ("source_active_kw", "active_loss_kw", "voltage_violation_pu_hours"):
            for nonfinite in (float("nan"), float("inf"), -float("inf")):
                row = self.row(100.0)
                row[key] = nonfinite
                with self.assertRaises(ValueError):
                    native_vanilla_reward(row, "34Bus", [500.0, 500.0])
        row = self.row(100.0)
        row["battery_command_kw"] = [float("nan"), 0.0]
        with self.assertRaises(ValueError):
            native_vanilla_reward(row, "34Bus", [500.0, 500.0])


@unittest.skipUnless(importlib.util.find_spec("torch"), "requires isolated PyTorch runtime")
class IntegerActorTests(unittest.TestCase):
    def test_straight_through_actions_are_integers_and_have_policy_gradient(self):
        import torch
        from sac import IntegerActor

        torch.manual_seed(0)
        actor = IntegerActor(5, [2, 33, 33], width=16, depth=2, activation="relu")
        actions, log_probability = actor.sample(torch.randn(8, 5))
        physical = (actions + 1) * torch.tensor([1, 32, 32]) / 2
        self.assertTrue(torch.allclose(physical, physical.round(), atol=1e-6))
        self.assertEqual(tuple(actions.shape), (8, 3))
        self.assertEqual(tuple(log_probability.shape), (8, 1))
        loss = (actions * torch.tensor([1.0, 0.3, 0.1])).sum() + log_probability.sum() * 0.1
        loss.backward()
        total = sum(
            parameter.grad.abs().sum().item()
            for parameter in actor.parameters()
            if parameter.grad is not None
        )
        self.assertGreater(total, 1e-6)


@unittest.skipUnless(importlib.util.find_spec("torch"), "requires isolated PyTorch runtime")
class SACStateTests(unittest.TestCase):
    def test_interleaved_agent_resume_keeps_actions_updates_and_replay_exact(self):
        import copy

        import numpy as np
        import torch
        from sac import SACAgent

        torch.set_num_threads(1)
        config = {
            "width": 16,
            "depth": 2,
            "activation": "relu",
            "lr": 3e-4,
            "gamma": 0.95,
            "batch_size": 4,
            "entropy_coef": 0.4,
            "gumbel_temperature": 1.0,
            "replay_capacity": 32,
            "learning_starts": 4,
            "updates_per_step": 1,
            "tau": 0.005,
        }
        first = SACAgent(5, [2, 33, 33], config, seed=7)
        obs = np.linspace(0, 1, 5, dtype=np.float32)
        for index in range(8):
            action = first.act(obs)
            first.observe(obs, action, -0.2, obs, index % 4 == 3)
        state = copy.deepcopy(first.training_state_dict())
        second = SACAgent(5, [2, 33, 33], config, seed=99)
        second.load_training_state_dict(state)
        for index in range(5):
            a, b = first.act(obs), second.act(obs)
            self.assertEqual(a, b)
            metrics_a = first.observe(obs, a, -0.2, obs, False)
            torch.rand(99)  # A global RNG consumer must not affect this agent.
            metrics_b = second.observe(obs, b, -0.2, obs, False)
            self.assertEqual(metrics_a, metrics_b)
        for a, b in zip(first.actor.parameters(), second.actor.parameters(), strict=True):
            self.assertTrue(torch.equal(a, b))
        self.assertEqual(first.replay.size, 13)


@unittest.skipUnless(
    NUMPY_AVAILABLE
    and DSS_AVAILABLE
    and (ROOT / "work/distribution/powergym-verified/source-receipt.json").exists(),
    "requires verified upstream source",
)
class RealAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import tempfile

        from data import prepare_pool

        cls.temporary = tempfile.TemporaryDirectory()
        cls.pool = Path(cls.temporary.name) / "pool"
        prepare_pool(ROOT / "work/distribution/powergym-verified", cls.pool, split_seed=0)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_all16_packing_matches_selected_old_cases_and_source_is_immutable(self):
        import json

        from data import verify_pool

        manifest = verify_pool(self.pool)
        self.assertEqual(len(manifest["cases"]), 32)
        for network in ("34Bus", "123Bus"):
            for index in (0, 6, 15):
                original = (
                    ROOT
                    / "work/distribution-selection-20261016/powergym/pool/cases"
                    / (f"{network}-standard-p{index:03d}-s1.json")
                )
                new = self.pool / "cases" / f"{network}-rl-standard-p{index:03d}-s1.json"
                self.assertEqual(
                    json.loads(original.read_text())["multipliers"],
                    json.loads(new.read_text())["multipliers"],
                )
        with (self.pool / manifest["cases"][0]["path"]).open("a") as handle:
            handle.write(" ")
        with self.assertRaises(ValueError):
            verify_pool(self.pool)
        # Repair only this temporary test fixture.
        path = self.pool / manifest["cases"][0]["path"]
        path.write_bytes(path.read_bytes()[:-1])

    def test_observation_has_fixed_scales_no_clock_and_idle_terminal_gate(self):
        import numpy as np
        from env import PowerGymEnv

        environment = PowerGymEnv(self.pool, "34Bus", split="heldout", seed=0)
        observation = environment.reset()
        before = observation.copy()
        count = len(environment.backend._voltages())
        self.assertGreater(count, 0)
        self.assertTrue(np.array_equal(observation, environment.observation()))
        self.assertEqual(environment.backend.step, 0)
        # Idle controls preserve the strict terminal gate and exercise full replay.
        idle = [1, 1] + [32] * 6 + [16, 16]
        for hour in range(24):
            observation, reward, done, _ = environment.step(idle)
            self.assertEqual(observation.shape, before.shape)
            self.assertEqual(done, hour == 23)
            self.assertTrue(np.isfinite(reward))
            self.assertEqual(reward, environment.rows[-1]["paper_vanilla_reward_diagnostic"])
            self.assertTrue(np.allclose(observation[-10:-4], 1.0))
        result = environment.final_evaluation("test-idle")
        self.assertTrue(result["valid"])
        self.assertTrue(result["qualification_valid"])
        self.assertEqual(result["rl_paper_vanilla_return"], result["paper_vanilla_return"])
        self.assertEqual(environment.environment_steps, 24)
        self.assertEqual(environment.pf_calls, 25)
        self.assertEqual(environment.verification_pf_calls, 50)
        other = PowerGymEnv(self.pool, "34Bus", split="train", seed=0)
        with self.assertRaises(ValueError):
            other.reset(case_id=environment.case["id"])

    def test_native_reverse_flow_remains_finite_and_full_day_replay_preserves_old_none(self):
        import math

        from env import PowerGymEnv, native_vanilla_reward

        environment = PowerGymEnv(self.pool, "34Bus", split="train", seed=0)
        environment.reset(case_id="34Bus-rl-standard-p007-s1")
        idle = [1, 1] + [32] * 6 + [16, 16]
        for hour in range(24):
            action = [1, 1] + [0] * 6 + [32, 32] if hour == 4 else idle
            _, reward, _, info = environment.step(action)
            row = info["physical_row"]
            self.assertTrue(math.isfinite(reward))
            self.assertEqual(reward, row["rl_paper_vanilla_reward"])
            if hour == 4:
                self.assertLess(row["source_active_kw"], 0.0)
                self.assertIsNone(row["power_loss_ratio"])
                self.assertIsNone(row["paper_vanilla_reward_diagnostic"])
        result = environment.final_evaluation("test-reverse-flow")
        self.assertIsNone(result["paper_vanilla_reward_diagnostic"])
        self.assertIsNone(result["paper_vanilla_return"])
        self.assertTrue(math.isfinite(result["rl_paper_vanilla_return"]))
        self.assertEqual(
            result["rl_paper_vanilla_return"],
            math.fsum(
                native_vanilla_reward(row, "34Bus", environment.backend.max_kw)
                for row in result["trajectory"]
            ),
        )
        self.assertIsNone(result["trajectory"][4]["paper_vanilla_reward_diagnostic"])


@unittest.skipUnless(importlib.util.find_spec("torch"), "requires isolated PyTorch runtime")
class RunnerTests(unittest.TestCase):
    def test_runner_exact_40000_transitions_20k_no_flush_and_fixed_final(self):
        import json
        import random
        import tempfile
        from types import SimpleNamespace
        from unittest.mock import patch

        import numpy as np
        from data import digest
        from train import run_training

        class FakeEnv:
            def __init__(self, pool_dir, network, *, split, seed):
                self.cases = [
                    {"id": f"{split}-{i}", "split": split, "profile_index": i}
                    for i in (range(8) if split == "train" else range(8, 16))
                ]
                self.action_sizes = [2]
                self.random = random.Random(seed)
                self.environment_steps = self.pf_calls = self.replay_pf_calls = 0
                self.verification_pf_calls = 0

            def reset(self, *, case_id=None):
                self.case = next(
                    (item for item in self.cases if item["id"] == case_id), self.cases[0]
                )
                self.rows = []
                self.pf_calls += 1
                return np.zeros(2, dtype=np.float32)

            def step(self, action):
                self.environment_steps += 1
                self.pf_calls += 1
                self.rows.append({"action": action})
                return np.zeros(2, dtype=np.float32), -0.1, len(self.rows) == 24, {}

            def final_evaluation(self, label):
                self.replay_pf_calls += 25
                self.verification_pf_calls += 50
                return {
                    "paper_vanilla_return": -2.4,
                    "rl_paper_vanilla_return": -2.4,
                    "valid": False,
                    "qualification_valid": False,
                    "profile_index": self.case["profile_index"],
                }

        class FakeAgent:
            def __init__(self):
                self.count = self.finishes = 0

            def act(self, observation, deterministic=False):
                return [0]

            def observe(self, *transition):
                self.count += 1
                return {}

            def finish(self):
                self.finishes += 1

            def training_state_dict(self):
                return {"count": self.count, "finishes": self.finishes}

        agent, checkpoints = FakeAgent(), []

        def capture(path, agent, environment, step, lock, observation):
            checkpoints.append((step, agent.count, agent.finishes, len(environment.rows)))

        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            protocol = json.loads((ROOT / "configs/powergym-rl-pilot-20261016-v2.json").read_text())
            protocol["status"] = "frozen"
            protocol_path = directory / "protocol.json"
            protocol_path.write_text(json.dumps(protocol))
            pool = directory / "pool"
            pool.mkdir()
            (pool / "pool.json").write_text("{}")
            args = SimpleNamespace(
                protocol=protocol_path,
                protocol_sha256=digest(protocol_path),
                pool=pool,
                pool_sha256=digest(pool / "pool.json"),
                output=directory / "out",
                algorithm="sac",
            )
            fake_pool = {"split_seed": 0, "splits": {"34Bus": {}}}
            with (
                patch("train.verify_pool", return_value=fake_pool),
                patch("train.PowerGymEnv", FakeEnv),
                patch("train.make_agent", return_value=agent),
                patch("train.save_checkpoint", capture),
            ):
                result = run_training(args)
            self.assertEqual(agent.count, 40000)
            self.assertEqual(checkpoints, [(20000, 20000, 0, 8), (40000, 40000, 1, 16)])
            self.assertEqual(result["heldout_environment_steps"], 334 * 8 * 24)
            self.assertEqual(result["fixed_final_evaluation"]["valid_count"], 0)
            self.assertEqual(len(result["periodic_evaluations"]), 333)
            with self.assertRaises(FileExistsError):
                run_training(args)

            class BrokenEnv(FakeEnv):
                def step(self, action):
                    transition = super().step(action)
                    self.rows[-1]["source_active_kw"] = float("nan")
                    if self.environment_steps == 2:
                        raise ValueError("synthetic nonfinite source")
                    return transition

            args.output = directory / "out-failure"
            with (
                patch("train.verify_pool", return_value=fake_pool),
                patch("train.PowerGymEnv", BrokenEnv),
                patch("train.make_agent", return_value=FakeAgent()),
            ):
                with self.assertRaisesRegex(ValueError, "synthetic nonfinite source"):
                    run_training(args)
            failure = json.loads((args.output / "failure.json").read_text())
            self.assertEqual(failure["step"], 2)
            self.assertEqual(failure["last_phase"], "training")
            self.assertEqual(failure["last_completed_environment_steps"], 2)
            self.assertEqual(failure["last_physical_row"]["source_active_kw"], "nan")
            self.assertEqual(failure["training_pf_calls"], 3)
            args.output = directory / "rejected-v1"
            protocol["schema_version"] = "powergym-rl-pilot-protocol-v1"
            protocol_path.write_text(json.dumps(protocol))
            args.protocol_sha256 = digest(protocol_path)
            with self.assertRaisesRegex(ValueError, "requires its matching v2 protocol"):
                run_training(args)
            self.assertFalse(args.output.exists())


if __name__ == "__main__":
    unittest.main()
