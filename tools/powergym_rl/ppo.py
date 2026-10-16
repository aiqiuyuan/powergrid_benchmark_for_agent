"""Factorized categorical PPO; a declared reimplementation, not author training code.

PowerGym arXiv:2109.03970 Table 6 reports Adam/lr/gamma/clip/batch/update
interval/entropy coefficient. Architecture, GAE, epochs, value coefficient,
gradient clipping and normalization are explicitly supplied implementation
assumptions. Preprocessing belongs to the environment's fixed physical scaling.
"""

from __future__ import annotations

import copy
import math
from collections.abc import Sequence

import numpy as np
import torch
from torch import nn
from torch.distributions import Categorical


def action_statistics(
    logits: torch.Tensor, action_sizes: list[int], actions: torch.Tensor
) -> tuple[torch.Tensor, torch.Tensor]:
    """Joint log probability and entropy of independent actuator categories."""
    distributions = [Categorical(logits=head) for head in logits.split(action_sizes, dim=-1)]
    log_probability = torch.stack(
        [
            distribution.log_prob(actions[..., index])
            for index, distribution in enumerate(distributions)
        ],
        dim=-1,
    ).sum(dim=-1)
    entropy = torch.stack([item.entropy() for item in distributions], dim=-1).sum(dim=-1)
    return log_probability, entropy


def generalized_advantages(
    rewards: Sequence[float],
    values: Sequence[float],
    next_values: Sequence[float],
    terminated: Sequence[bool],
    gamma: float,
    gae_lambda: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Bootstrap unfinished rollouts, and never cross a true daily terminal."""
    if not (len(rewards) == len(values) == len(next_values) == len(terminated)):
        raise ValueError("GAE transition arrays differ in length")
    advantages = np.zeros(len(rewards), dtype=np.float64)
    following = 0.0
    for index in reversed(range(len(rewards))):
        mask = float(not terminated[index])
        delta = rewards[index] + gamma * next_values[index] * mask - values[index]
        following = delta + gamma * gae_lambda * mask * following
        advantages[index] = following
    return advantages, advantages + np.asarray(values, dtype=np.float64)


def clipped_policy_loss(
    new_log_probability: torch.Tensor,
    old_log_probability: torch.Tensor,
    advantages: torch.Tensor,
    clip_epsilon: float,
) -> tuple[torch.Tensor, torch.Tensor]:
    ratio = torch.exp(new_log_probability - old_log_probability)
    clipped = ratio.clamp(1 - clip_epsilon, 1 + clip_epsilon)
    loss = -torch.minimum(ratio * advantages, clipped * advantages).mean()
    return loss, ((ratio - 1).abs() > clip_epsilon).float().mean()


def _network(inputs: int, outputs: int, config: dict) -> nn.Sequential:
    activation = {"tanh": nn.Tanh, "relu": nn.ReLU}[config["activation"]]
    layers: list[nn.Module] = []
    for _ in range(config["depth"]):
        layers.extend([nn.Linear(inputs, config["width"]), activation()])
        inputs = config["width"]
    return nn.Sequential(*layers, nn.Linear(inputs, outputs))


def _validate_config(config: dict) -> None:
    required = {
        "width",
        "depth",
        "activation",
        "epochs",
        "gae_lambda",
        "lr",
        "gamma",
        "clip_epsilon",
        "batch_size",
        "update_interval",
        "entropy_coef",
        "value_coef",
        "max_grad_norm",
        "normalize_advantages",
    }
    if not required.issubset(config):
        raise ValueError(f"PPO configuration missing: {sorted(required - set(config))}")
    for key in ("width", "depth", "epochs", "batch_size", "update_interval"):
        if type(config[key]) is not int or config[key] < 1:
            raise ValueError(f"PPO {key} must be a positive integer")
    for key in (
        "lr",
        "gamma",
        "clip_epsilon",
        "gae_lambda",
        "entropy_coef",
        "value_coef",
        "max_grad_norm",
    ):
        if not isinstance(config[key], (float, int)) or not math.isfinite(config[key]):
            raise ValueError(f"PPO {key} must be finite")
    if not (0 <= config["gamma"] <= 1 and 0 <= config["gae_lambda"] <= 1):
        raise ValueError("PPO gamma and GAE lambda must be in [0,1]")
    if not 0 < config["clip_epsilon"] < 1 or config["lr"] <= 0:
        raise ValueError("PPO learning rate and clip range are invalid")
    if config["entropy_coef"] < 0 or config["value_coef"] < 0 or config["max_grad_norm"] <= 0:
        raise ValueError("PPO loss coefficients or gradient bound are invalid")
    if config["activation"] not in ("tanh", "relu"):
        raise ValueError("PPO activation must be explicit tanh or relu")
    if type(config["normalize_advantages"]) is not bool:
        raise ValueError("PPO advantage normalization must be an explicit boolean")


class PPOAgent:
    """One transition per physical action; deterministic evaluation never learns.

    A completed 24-hour episode is terminal, rather than an infinite-horizon time
    limit. The unfinished rollout at a checkpoint is retained, with its original
    policy log probabilities, values, and next-state bootstrap values.
    """

    def __init__(
        self,
        observation_dim: int,
        action_sizes: list[int],
        config: dict,
        seed: int = 0,
        device: str = "cpu",
    ):
        _validate_config(config)
        if type(observation_dim) is not int or observation_dim < 1:
            raise ValueError("PPO observation dimension must be positive")
        if not action_sizes or any(type(size) is not int or size < 2 for size in action_sizes):
            raise ValueError("PPO action cardinalities must be integers >=2")
        self.observation_dim = observation_dim
        self.action_sizes = list(action_sizes)
        self.config = copy.deepcopy(config)
        self.device = torch.device(device)
        if self.device.type != "cpu":
            raise ValueError("this qualification implementation freezes CPU execution")
        self.generator = torch.Generator(device="cpu").manual_seed(seed)
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(seed)
            self.actor = _network(observation_dim, sum(action_sizes), self.config).to(self.device)
            self.value = _network(observation_dim, 1, self.config).to(self.device)
        self.parameters = list(self.actor.parameters()) + list(self.value.parameters())
        self.optimizer = torch.optim.Adam(self.parameters, lr=config["lr"])
        self.buffer: list[dict] = []
        self.environment_steps = 0
        self.trained_transitions = 0
        self.updates = 0
        self.gradient_steps = 0

    def _observation(self, observation: np.ndarray) -> torch.Tensor:
        array = np.asarray(observation, dtype=np.float32)
        if array.shape != (self.observation_dim,) or not np.isfinite(array).all():
            raise ValueError("PPO observation has invalid dimensions or nonfinite values")
        return torch.as_tensor(array.copy(), dtype=torch.float32, device=self.device)

    def act(self, observation: np.ndarray, deterministic: bool = False) -> list[int]:
        with torch.no_grad():
            logits = self.actor(self._observation(observation))
            if not torch.isfinite(logits).all():
                raise ValueError("PPO policy produced nonfinite logits")
            heads = logits.split(self.action_sizes, dim=-1)
            if deterministic:
                return [int(head.argmax().item()) for head in heads]
            return [
                int(torch.multinomial(head.softmax(-1), 1, generator=self.generator).item())
                for head in heads
            ]

    def observe(
        self,
        observation: np.ndarray,
        action: list[int],
        reward: float,
        next_observation: np.ndarray,
        terminated: bool,
    ) -> dict:
        obs, next_obs = self._observation(observation), self._observation(next_observation)
        if len(action) != len(self.action_sizes) or any(
            isinstance(item, (bool, np.bool_))
            or not isinstance(item, (int, np.integer))
            or not 0 <= item < size
            for item, size in zip(action, self.action_sizes, strict=True)
        ):
            raise ValueError("PPO action violates a discrete actuator bound")
        if not isinstance(terminated, (bool, np.bool_)) or not math.isfinite(reward):
            raise ValueError("PPO terminal flag or reward is invalid")
        with torch.no_grad():
            log_probability, _ = action_statistics(
                self.actor(obs), self.action_sizes, torch.tensor(action, device=self.device)
            )
            value, next_value = self.value(obs).item(), self.value(next_obs).item()
        if not all(math.isfinite(item) for item in (log_probability.item(), value, next_value)):
            raise ValueError("PPO transition has nonfinite policy or value predictions")
        self.buffer.append(
            {
                "observation": obs.cpu().tolist(),
                "action": [int(item) for item in action],
                "reward": float(reward),
                "value": value,
                "next_value": next_value,
                "log_probability": log_probability.item(),
                "terminated": bool(terminated),
            }
        )
        self.environment_steps += 1
        return self._update() if len(self.buffer) >= self.config["update_interval"] else {}

    def _update(self) -> dict:
        if not self.buffer:
            return {}
        count = len(self.buffer)
        c = self.config
        advantages, returns = generalized_advantages(
            *[
                [row[key] for row in self.buffer]
                for key in ("reward", "value", "next_value", "terminated")
            ],
            gamma=c["gamma"],
            gae_lambda=c["gae_lambda"],
        )
        observations = torch.tensor(
            [row["observation"] for row in self.buffer], dtype=torch.float32, device=self.device
        )
        actions = torch.tensor([row["action"] for row in self.buffer], device=self.device)
        old_log = torch.tensor([row["log_probability"] for row in self.buffer], device=self.device)
        advantages = torch.tensor(advantages, dtype=torch.float32, device=self.device)
        returns = torch.tensor(returns, dtype=torch.float32, device=self.device)
        if c["normalize_advantages"]:
            advantages = (advantages - advantages.mean()) / advantages.std(
                unbiased=False
            ).clamp_min(1e-8)
        totals = dict.fromkeys(("policy_loss", "value_loss", "entropy", "clip_fraction"), 0.0)
        batches = 0
        for _ in range(c["epochs"]):
            permutation = torch.randperm(count, generator=self.generator, device=self.device)
            for start in range(0, count, c["batch_size"]):
                indices = permutation[start : start + c["batch_size"]]
                log_probability, entropy = action_statistics(
                    self.actor(observations[indices]), self.action_sizes, actions[indices]
                )
                policy_loss, clipped = clipped_policy_loss(
                    log_probability, old_log[indices], advantages[indices], c["clip_epsilon"]
                )
                value_loss = (
                    (self.value(observations[indices]).squeeze(-1) - returns[indices])
                    .square()
                    .mean()
                )
                loss = (
                    policy_loss + c["value_coef"] * value_loss - c["entropy_coef"] * entropy.mean()
                )
                if not torch.isfinite(loss):
                    raise ValueError("PPO update produced a nonfinite objective")
                self.optimizer.zero_grad()
                loss.backward()
                nn.utils.clip_grad_norm_(
                    self.parameters, c["max_grad_norm"], error_if_nonfinite=True
                )
                self.optimizer.step()
                for key, item in zip(
                    totals, (policy_loss, value_loss, entropy.mean(), clipped), strict=True
                ):
                    totals[key] += item.detach().item()
                batches += 1
        self.buffer.clear()
        self.trained_transitions += count
        self.gradient_steps += batches
        self.updates += 1
        return {
            **{key: item / batches for key, item in totals.items()},
            "rollout_steps": count,
            "updates": self.updates,
            "gradient_steps": self.gradient_steps,
            "trained_transitions": self.trained_transitions,
        }

    def finish(self) -> dict:
        """Flush the final partial rollout; intermediate checkpoints must not call it."""
        return self._update()

    def training_state_dict(self) -> dict:
        return copy.deepcopy(
            {
                "schema_version": "powergym-ppo-v1",
                "observation_dim": self.observation_dim,
                "action_sizes": self.action_sizes,
                "config": self.config,
                "actor": self.actor.state_dict(),
                "value": self.value.state_dict(),
                "optimizer": self.optimizer.state_dict(),
                "generator": self.generator.get_state(),
                "buffer": self.buffer,
                "environment_steps": self.environment_steps,
                "trained_transitions": self.trained_transitions,
                "updates": self.updates,
                "gradient_steps": self.gradient_steps,
            }
        )

    def load_training_state_dict(self, state: dict) -> None:
        if (
            state.get("schema_version") != "powergym-ppo-v1"
            or state.get("observation_dim") != self.observation_dim
            or state.get("action_sizes") != self.action_sizes
            or state.get("config") != self.config
        ):
            raise ValueError("PPO checkpoint architecture, algorithm or configuration mismatch")
        if (
            state["environment_steps"] != state["trained_transitions"] + len(state["buffer"])
            or len(state["buffer"]) >= self.config["update_interval"]
        ):
            raise ValueError("PPO checkpoint transition accounting is inconsistent")
        self.actor.load_state_dict(state["actor"])
        self.value.load_state_dict(state["value"])
        self.optimizer.load_state_dict(state["optimizer"])
        self.generator.set_state(state["generator"])
        self.buffer = copy.deepcopy(state["buffer"])
        for name in ("environment_steps", "trained_transitions", "updates", "gradient_steps"):
            setattr(self, name, state[name])
