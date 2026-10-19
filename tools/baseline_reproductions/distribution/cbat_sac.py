"""Explicit hybrid SAC reimplementation; continuous training, named grid projection.

The author implementation is unavailable. Gaussian battery branches and their
clipping constants are reconstruction assumptions, not recovered author settings.
"""

from __future__ import annotations

import math

import numpy as np
import torch
from powergym_backend import QualificationBackend
from sac import IntegerActor, SACAgent, mlp
from torch import nn


class ContinuousBatteryBackend(QualificationBackend):
    def validate(self, action):
        caps, regs = len(self.capacitors), len(self.regulators)
        if not isinstance(action, list) or len(action) != caps + regs + len(self.batteries):
            raise ValueError("hybrid action dimension mismatch")
        if any(
            type(value) is not int or not 0 <= value <= limit
            for value, limit in zip(action[: caps + regs], [1] * caps + [32] * regs)
        ):
            raise ValueError("hybrid capacitor/regulator action is not a legal integer")
        if any(
            type(value) not in (float, int) or not math.isfinite(value) or not 0 <= value <= 32
            for value in action[caps + regs :]
        ):
            raise ValueError("hybrid battery action is not finite in [0,32]")
        return action

    def _apply_devices(self, action):
        self.validate(action)
        count = len(self.capacitors) + len(self.regulators)
        # The unchanged parent applies exactly the current cap/tap semantics.
        super()._apply_devices(action[:count] + [16] * len(self.batteries))
        for index, name in enumerate(self.batteries):
            requested = (float(action[count + index]) - 16) * self.max_kw[index] / 16
            projected = (
                min(requested, self.energy[index])
                if requested > 0
                else max(requested, self.energy[index] - self.capacity[index])
            )
            self.commands_kw[index] = projected
            self.circuit.Generators.Name = name
            self.circuit.Generators.kW = projected
            self.circuit.Generators.kvar = projected / self.pf[index]


class HybridActor(nn.Module):
    def __init__(
        self, observations, action_sizes, *, width, depth, activation, temperature=1.0, batteries=4
    ):
        super().__init__()
        self.batteries = batteries
        self.integer = IntegerActor(
            observations,
            action_sizes[:-batteries],
            width=width,
            depth=depth,
            activation=activation,
            temperature=temperature,
        )
        self.continuous = mlp(observations, batteries * 2, width, depth, activation)

    def sample(self, observation, generator=None):
        integers, integer_log = self.integer.sample(observation, generator)
        mean, log_std = self.continuous(observation).chunk(2, dim=-1)
        log_std = log_std.clamp(-20, 2)
        noise = torch.randn(mean.shape, device=mean.device, generator=generator)
        latent = mean + log_std.exp() * noise
        continuous = latent.tanh()
        log_probability = (
            -0.5 * (noise.square() + 2 * log_std + math.log(2 * math.pi))
            - torch.log(1 - continuous.square() + 1e-6)
        ).sum(-1, keepdim=True)
        return torch.cat((integers, continuous), -1), integer_log + log_probability

    def deterministic(self, observation):
        discrete = self.integer.deterministic(observation)
        mean, _ = self.continuous(observation).chunk(2, dim=-1)
        return discrete + ((mean.tanh().detach().cpu().numpy()[0] + 1) * 16).tolist()


class HybridSAC(SACAgent):
    def __init__(self, observations, action_sizes, config, seed=0, device="cpu"):
        super().__init__(observations, action_sizes, config, seed=seed, device=device)
        architecture = {key: config[key] for key in ("width", "depth", "activation")}
        self.actor = HybridActor(
            observations, action_sizes, **architecture, temperature=config["gumbel_temperature"]
        ).to(device)
        self.actor_optimizer = torch.optim.Adam(self.actor.parameters(), lr=config["lr"])

    def act(self, observation, deterministic=False):
        if not deterministic and self.environment_steps < self.config["learning_starts"]:
            return [
                int(self.random.integers(size)) for size in self.action_sizes[:-4]
            ] + self.random.uniform(0, 32, 4).tolist()
        with torch.no_grad():
            tensor = torch.as_tensor(observation, device=self.device).unsqueeze(0)
            if deterministic:
                return self.actor.deterministic(tensor)
            normalized, _ = self.actor.sample(tensor, self.generator)
            values = normalized.cpu().numpy()[0]
            discrete = np.rint((values[:-4] + 1) * (np.asarray(self.action_sizes[:-4]) - 1) / 2)
            return discrete.astype(int).tolist() + ((values[-4:] + 1) * 16).tolist()


class ProjectToBenchmarkGrid:
    """Named post-training action adapter; never presented as native cbat output."""

    def __init__(self, agent):
        self.agent = agent

    def act(self, observation, deterministic=True):
        action = self.agent.act(observation, deterministic=deterministic)
        return action[:-4] + [int(np.rint(value)) for value in action[-4:]]
