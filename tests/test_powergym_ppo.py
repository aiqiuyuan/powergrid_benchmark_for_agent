"""Algorithmic checks for the independently implemented PowerGym PPO baseline."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

try:
    import numpy as np
except ModuleNotFoundError:
    np = None

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/powergym_rl"))


def configuration() -> dict:
    return {
        "width": 64,
        "depth": 2,
        "activation": "tanh",
        "epochs": 2,
        "gae_lambda": 0.95,
        "lr": 3e-4,
        "gamma": 0.95,
        "clip_epsilon": 0.2,
        "batch_size": 4,
        "update_interval": 8,
        "entropy_coef": 0.01,
        "value_coef": 0.5,
        "max_grad_norm": 0.5,
        "normalize_advantages": True,
    }


@unittest.skipUnless(
    np is not None and importlib.util.find_spec("torch"),
    "requires isolated NumPy/PyTorch runtime",
)
class PPOTests(unittest.TestCase):
    def test_joint_probability_and_entropy_are_sums_over_devices(self):
        import torch
        from ppo import action_statistics

        logits = torch.tensor([[0.0, 0.0, 0.0, 0.0, 0.0]], requires_grad=True)
        log_probability, entropy = action_statistics(logits, [2, 3], torch.tensor([[1, 2]]))
        self.assertAlmostEqual(log_probability.item(), -np.log(6), places=6)
        self.assertAlmostEqual(entropy.item(), np.log(6), places=6)
        log_probability.sum().backward()
        self.assertTrue(torch.isfinite(logits.grad).all())
        self.assertGreater(logits.grad.abs().sum().item(), 0)

    def test_gae_bootstraps_rollout_boundary_but_stops_at_episode_terminal(self):
        from ppo import generalized_advantages

        advantages, returns = generalized_advantages(
            rewards=[1.0, 2.0, 3.0],
            values=[0.5, 0.6, 0.7],
            next_values=[0.6, 99.0, 0.8],
            terminated=[False, True, False],
            gamma=0.9,
            gae_lambda=0.5,
        )
        self.assertTrue(np.allclose(advantages, [1.04 + 0.45 * 1.4, 1.4, 3.02]))
        self.assertTrue(np.allclose(returns, advantages + [0.5, 0.6, 0.7]))

    def test_clipped_surrogate_handles_both_advantage_signs(self):
        import torch
        from ppo import clipped_policy_loss

        new = torch.log(torch.tensor([1.5, 0.5]))
        loss, fraction = clipped_policy_loss(new, torch.zeros(2), torch.tensor([2.0, -2.0]), 0.2)
        self.assertAlmostEqual(loss.item(), -0.4, places=6)
        self.assertEqual(fraction.item(), 1.0)

    def test_actions_are_valid_and_deterministic_evaluation_consumes_no_rng(self):
        from ppo import PPOAgent

        agent = PPOAgent(3, [2, 33, 33], configuration(), seed=4)
        observation = np.array([0.9, 16, 1], dtype=np.float32)
        state = agent.training_state_dict()
        reference = agent.act(observation)
        agent.load_training_state_dict(state)
        for _ in range(5):
            self.assertEqual(
                agent.act(observation, deterministic=True),
                agent.act(observation, deterministic=True),
            )
        self.assertEqual(agent.act(observation), reference)
        for _ in range(40):
            self.assertTrue(
                all(0 <= x < n for x, n in zip(agent.act(observation), [2, 33, 33], strict=True))
            )

    def test_rollout_updates_and_finish_retains_all_collected_transitions(self):
        import torch
        from ppo import PPOAgent

        agent = PPOAgent(3, [2, 3], configuration(), seed=3)
        initial = {key: value.clone() for key, value in agent.actor.state_dict().items()}
        for index in range(10):
            observation = np.array([index / 10, 1, -0.2], dtype=np.float32)
            agent.observe(
                observation,
                agent.act(observation),
                float(index % 3),
                observation + 0.1,
                index % 4 == 3,
            )
        state = agent.training_state_dict()
        self.assertEqual(state["environment_steps"], 10)
        self.assertEqual(state["updates"], 1)
        self.assertEqual(state["trained_transitions"], 8)
        self.assertEqual(len(state["buffer"]), 2)
        agent.finish()
        state = agent.training_state_dict()
        self.assertEqual(state["updates"], 2)
        self.assertEqual(state["trained_transitions"], 10)
        self.assertEqual(state["buffer"], [])
        self.assertTrue(
            any(
                not torch.equal(initial[key], value)
                for key, value in agent.actor.state_dict().items()
            )
        )

    def test_partial_checkpoint_restores_exact_training_and_action_rng(self):
        import torch
        from ppo import PPOAgent

        first = PPOAgent(3, [2, 3], configuration(), seed=0)
        for index in range(5):
            observation = np.array([index, 0.2, -0.1], dtype=np.float32)
            first.observe(
                observation, first.act(observation), index / 3, observation + 0.1, index == 3
            )
        checkpoint = first.training_state_dict()
        resumed = PPOAgent(3, [2, 3], configuration(), seed=92)
        resumed.load_training_state_dict(checkpoint)
        for index in range(5, 11):
            observation = np.array([index, 0.2, -0.1], dtype=np.float32)
            a, b = first.act(observation), resumed.act(observation)
            self.assertEqual(a, b)
            first.observe(observation, a, index / 3, observation + 0.1, index == 7)
            resumed.observe(observation, b, index / 3, observation + 0.1, index == 7)
        first.finish()
        resumed.finish()
        for left, right in zip(first.actor.parameters(), resumed.actor.parameters(), strict=True):
            self.assertTrue(torch.equal(left, right))
        self.assertEqual(
            first.training_state_dict()["updates"], resumed.training_state_dict()["updates"]
        )

    def test_missing_configuration_or_invalid_transition_is_rejected(self):
        from ppo import PPOAgent

        config = configuration()
        del config["gae_lambda"]
        with self.assertRaises(ValueError):
            PPOAgent(3, [2], config)
        agent = PPOAgent(3, [2], configuration())
        observation = np.ones(3, dtype=np.float32)
        for action, reward, next_obs in [
            ([2], 0.0, observation),
            ([0], float("nan"), observation),
            ([0], 0.0, np.array([1, 2])),
        ]:
            with self.assertRaises(ValueError):
                agent.observe(observation, action, reward, next_obs, False)
        changed = configuration()
        changed["gamma"] = 0.9
        with self.assertRaises(ValueError):
            PPOAgent(3, [2], changed).load_training_state_dict(agent.training_state_dict())


if __name__ == "__main__":
    unittest.main()
