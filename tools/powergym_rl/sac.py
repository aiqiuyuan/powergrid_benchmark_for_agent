"""Integer-reparameterized SAC using per-device straight-through Gumbel samples.

Only one normalized integer scalar per device enters each critic. Unpublished
implementation choices are configuration assumptions, not claimed paper values.
"""

from __future__ import annotations

import copy

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F


def mlp(inputs: int, outputs: int, width: int, depth: int, activation: str) -> nn.Sequential:
    activations = {"relu": nn.ReLU, "tanh": nn.Tanh}
    if activation not in activations or width < 1 or depth < 1:
        raise ValueError("invalid network architecture")
    layers = []
    for _ in range(depth):
        layers.extend((nn.Linear(inputs, width), activations[activation]()))
        inputs = width
    return nn.Sequential(*layers, nn.Linear(inputs, outputs))


class IntegerActor(nn.Module):
    def __init__(
        self,
        observations: int,
        action_sizes: list[int],
        *,
        width: int,
        depth: int,
        activation: str,
        temperature: float = 1.0,
    ):
        super().__init__()
        if any(size < 2 for size in action_sizes) or temperature <= 0:
            raise ValueError("integer action sizes and Gumbel temperature must be positive")
        self.action_sizes = list(action_sizes)
        self.temperature = temperature
        self.network = mlp(observations, sum(action_sizes), width, depth, activation)

    def heads(self, observation: torch.Tensor) -> tuple[torch.Tensor, ...]:
        return self.network(observation).split(self.action_sizes, dim=-1)

    def sample(
        self, observation: torch.Tensor, generator=None
    ) -> tuple[torch.Tensor, torch.Tensor]:
        actions, logs = [], []
        for logits in self.heads(observation):
            uniform = torch.rand(logits.shape, device=logits.device, generator=generator)
            uniform = uniform.clamp(
                torch.finfo(logits.dtype).eps, 1 - torch.finfo(logits.dtype).eps
            )
            relaxed = ((logits - (-uniform.log()).log()) / self.temperature).softmax(-1)
            one_hot = F.one_hot(relaxed.argmax(-1), logits.shape[-1]).to(logits.dtype)
            hard = one_hot - relaxed.detach() + relaxed
            grid = torch.linspace(-1, 1, logits.shape[-1], device=logits.device)
            actions.append((hard * grid).sum(-1, keepdim=True))
            logs.append((hard * logits.log_softmax(-1)).sum(-1, keepdim=True))
        return torch.cat(actions, -1), torch.stack(logs).sum(0)

    def deterministic(self, observation: torch.Tensor) -> list[int]:
        return [int(logits.argmax(-1).item()) for logits in self.heads(observation)]


class ReplayBuffer:
    def __init__(self, capacity: int, observations: int, actions: int, seed: int):
        self.capacity, self.position, self.size = capacity, 0, 0
        self.random = np.random.default_rng(seed)
        self.arrays = {
            "observation": np.zeros((capacity, observations), np.float32),
            "next_observation": np.zeros((capacity, observations), np.float32),
            "action": np.zeros((capacity, actions), np.float32),
            "reward": np.zeros((capacity, 1), np.float32),
            "terminated": np.zeros((capacity, 1), np.float32),
        }

    def add(self, **transition):
        for key, value in transition.items():
            self.arrays[key][self.position] = value
        self.position = (self.position + 1) % self.capacity
        self.size = min(self.size + 1, self.capacity)

    def sample(self, batch_size: int, device: str) -> dict[str, torch.Tensor]:
        indices = self.random.integers(self.size, size=batch_size)
        return {
            key: torch.as_tensor(value[indices], device=device)
            for key, value in self.arrays.items()
        }

    def state_dict(self) -> dict:
        return {
            "capacity": self.capacity,
            "position": self.position,
            "size": self.size,
            "arrays": {key: value[: self.size].copy() for key, value in self.arrays.items()},
            "random_state": copy.deepcopy(self.random.bit_generator.state),
        }

    def load_state_dict(self, state: dict):
        if state["capacity"] != self.capacity:
            raise ValueError("replay capacity changed on resume")
        self.position, self.size = state["position"], state["size"]
        for key, value in state["arrays"].items():
            self.arrays[key][: self.size] = value
        self.random.bit_generator.state = state["random_state"]


class SACAgent:
    def __init__(
        self,
        observation_dim: int,
        action_sizes: list[int],
        config: dict,
        seed: int = 0,
        device: str = "cpu",
    ):
        self.config, self.action_sizes, self.device = dict(config), list(action_sizes), device
        torch.manual_seed(seed)
        self.random = np.random.default_rng(seed)
        self.generator = torch.Generator(device=device).manual_seed(seed + 1)
        self.environment_steps = self.gradient_steps = 0
        architecture = {key: config[key] for key in ("width", "depth", "activation")}
        self.actor = IntegerActor(
            observation_dim, action_sizes, **architecture, temperature=config["gumbel_temperature"]
        ).to(device)
        self.q1 = mlp(observation_dim + len(action_sizes), 1, **architecture).to(device)
        self.q2 = mlp(observation_dim + len(action_sizes), 1, **architecture).to(device)
        self.target1, self.target2 = copy.deepcopy(self.q1), copy.deepcopy(self.q2)
        for parameter in list(self.target1.parameters()) + list(self.target2.parameters()):
            parameter.requires_grad_(False)
        self.actor_optimizer = torch.optim.Adam(self.actor.parameters(), lr=config["lr"])
        self.critic_optimizer = torch.optim.Adam(
            list(self.q1.parameters()) + list(self.q2.parameters()), lr=config["lr"]
        )
        self.replay = ReplayBuffer(
            config["replay_capacity"], observation_dim, len(action_sizes), seed
        )

    def act(self, observation: np.ndarray, deterministic: bool = False) -> list[int]:
        if not deterministic and self.environment_steps < self.config["learning_starts"]:
            return [int(self.random.integers(size)) for size in self.action_sizes]
        with torch.no_grad():
            tensor = torch.as_tensor(observation, device=self.device).unsqueeze(0)
            if deterministic:
                return self.actor.deterministic(tensor)
            normalized, _ = self.actor.sample(tensor, self.generator)
            return (
                np.rint((normalized.cpu().numpy()[0] + 1) * (np.asarray(self.action_sizes) - 1) / 2)
                .astype(int)
                .tolist()
            )

    def observe(self, observation, action, reward, next_observation, terminated: bool) -> dict:
        normalized = 2 * np.asarray(action) / (np.asarray(self.action_sizes) - 1) - 1
        self.replay.add(
            observation=observation,
            action=normalized,
            reward=reward,
            next_observation=next_observation,
            terminated=terminated,
        )
        self.environment_steps += 1
        metrics = {}
        if (
            self.environment_steps >= self.config["learning_starts"]
            and self.replay.size >= self.config["batch_size"]
        ):
            for _ in range(self.config["updates_per_step"]):
                metrics = self.update()
        return metrics

    def update(self) -> dict:
        batch = self.replay.sample(self.config["batch_size"], self.device)
        alpha, gamma = self.config["entropy_coef"], self.config["gamma"]
        with torch.no_grad():
            next_action, next_log_probability = self.actor.sample(
                batch["next_observation"], self.generator
            )
            inputs = torch.cat((batch["next_observation"], next_action), -1)
            target = batch["reward"] + gamma * (1 - batch["terminated"]) * (
                torch.minimum(self.target1(inputs), self.target2(inputs))
                - alpha * next_log_probability
            )
        inputs = torch.cat((batch["observation"], batch["action"]), -1)
        critic_loss = F.mse_loss(self.q1(inputs), target) + F.mse_loss(self.q2(inputs), target)
        self.critic_optimizer.zero_grad(set_to_none=True)
        critic_loss.backward()
        self.critic_optimizer.step()
        critics = list(self.q1.parameters()) + list(self.q2.parameters())
        for parameter in critics:
            parameter.requires_grad_(False)
        action, log_probability = self.actor.sample(batch["observation"], self.generator)
        inputs = torch.cat((batch["observation"], action), -1)
        actor_loss = (
            alpha * log_probability - torch.minimum(self.q1(inputs), self.q2(inputs))
        ).mean()
        self.actor_optimizer.zero_grad(set_to_none=True)
        actor_loss.backward()
        self.actor_optimizer.step()
        for parameter in critics:
            parameter.requires_grad_(True)
        with torch.no_grad():
            for target_network, network in ((self.target1, self.q1), (self.target2, self.q2)):
                for destination, source in zip(target_network.parameters(), network.parameters()):
                    destination.lerp_(source, self.config["tau"])
        self.gradient_steps += 1
        return {
            "critic_loss": float(critic_loss.detach()),
            "actor_loss": float(actor_loss.detach()),
            "gradient_steps": self.gradient_steps,
        }

    def finish(self) -> dict:
        return {}

    def training_state_dict(self) -> dict:
        return {
            "config": self.config,
            "action_sizes": self.action_sizes,
            "environment_steps": self.environment_steps,
            "gradient_steps": self.gradient_steps,
            "actor": self.actor.state_dict(),
            "q1": self.q1.state_dict(),
            "q2": self.q2.state_dict(),
            "target1": self.target1.state_dict(),
            "target2": self.target2.state_dict(),
            "actor_optimizer": self.actor_optimizer.state_dict(),
            "critic_optimizer": self.critic_optimizer.state_dict(),
            "replay": self.replay.state_dict(),
            "random_state": copy.deepcopy(self.random.bit_generator.state),
            "generator_state": self.generator.get_state(),
        }

    def load_training_state_dict(self, state: dict):
        if state["config"] != self.config or state["action_sizes"] != self.action_sizes:
            raise ValueError("SAC configuration changed on resume")
        for name in (
            "actor",
            "q1",
            "q2",
            "target1",
            "target2",
            "actor_optimizer",
            "critic_optimizer",
        ):
            getattr(self, name).load_state_dict(state[name])
        self.environment_steps, self.gradient_steps = (
            state["environment_steps"],
            state["gradient_steps"],
        )
        self.replay.load_state_dict(state["replay"])
        self.random.bit_generator.state = state["random_state"]
        self.generator.set_state(state["generator_state"])
