"""Standalone formal 123Bus backend: qualified cold solves and native device ledger."""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path


class Backend:
    """Independent DSS context, explicit hourly loads, and actual-energy ledger.

    Observation timing deliberately matches the historical canary: the first
    observation is the initial first-hour state, then observations show the
    previous completed hour. Model preview exposes current loads only to the
    explicitly privileged reference and does not commit device/energy state.
    """

    def __init__(self, case_directory: Path):
        case = json.loads((case_directory / "case.json").read_text())
        assets = case_directory / "123Bus"
        if (case["network"], case["profile_index"], case["scale"]) != ("123Bus", 0, 2.5):
            raise ValueError("unexpected formal case")
        import dss

        self.case = case
        if case["horizon"] != 24 or case["step_hours"] != 1.0:
            raise ValueError("selection requires 24 hourly steps")
        self.engine = dss.DSS.NewContext()
        self.engine.AllowChangeDir = False
        self.engine.Text.Command = f'compile "{assets / case["model_file"]}"'
        self.engine.Text.Command = "set mode=snapshot controlmode=off maxiterations=100"
        self.circuit = self.engine.ActiveCircuit
        self.solution = self.circuit.Solution
        self.loads = list(case["load_names"])
        native_loads = {name.lower() for name in self.circuit.Loads.AllNames}
        if native_loads != {name.lower() for name in self.loads}:
            raise ValueError("frozen loads differ from compiled circuit")
        self.nominal = []
        for name in self.loads:
            self.circuit.Loads.Name = name
            self.nominal.append((float(self.circuit.Loads.kW), float(self.circuit.Loads.kvar)))
        self.capacitors = list(self.circuit.Capacitors.AllNames)
        self.regulators = []
        controls = self.circuit.RegControls
        if controls.First:
            while True:
                if controls.Transformer not in self.regulators:
                    self.regulators.append(controls.Transformer)
                if not controls.Next:
                    break
        with (assets / "Battery.csv").open(newline="") as stream:
            batteries = list(csv.DictReader(stream))
        self.batteries = [row["name"] for row in batteries]
        self.capacity = [float(row["max_kwh"]) for row in batteries]
        self.max_kw = [float(row["max_kw"]) for row in batteries]
        self.pf = [float(row["pf"]) for row in batteries]
        self.initial_energy = [float(row["initial_kwh"]) for row in batteries]
        if any(not 0 <= e <= c for e, c in zip(self.initial_energy, self.capacity)):
            raise ValueError("invalid initial battery capacity")
        self.energy = list(self.initial_energy)
        expected = {"34Bus": (2, 6, 2), "123Bus": (4, 7, 4)}[case["network"]]
        if (len(self.capacitors), len(self.regulators), len(self.batteries)) != expected:
            raise ValueError("compiled devices differ from declared network schema")
        self.cap_states = [1] * len(self.capacitors)
        self.tap_states = [32] * len(self.regulators)
        self.actual_battery_kw = [0.0] * len(self.batteries)
        self.commands_kw = [0.0] * len(self.batteries)
        self.cap_switches = self.tap_moves = self.step = 0
        self.pf_calls = self.failed_pf_calls = 0
        self.throughput_kwh = 0.0
        initial = self.cap_states + self.tap_states + [16] * len(self.batteries)
        self._apply_devices(initial)
        self._load_and_solve(0)
        self._observation = self._observation_now()

    def validate(self, action: object) -> list[int]:
        limits = [1] * len(self.capacitors) + [32] * (len(self.regulators) + len(self.batteries))
        if not isinstance(action, list) or len(action) != len(limits):
            raise ValueError("action dimensions differ from the device schema")
        if any(type(a) is not int or not 0 <= a <= b for a, b in zip(action, limits)):
            raise ValueError("action must contain bounded discrete integers")
        return action

    def _apply_devices(self, action: list[int]) -> None:
        self.validate(action)
        caps, regs = len(self.capacitors), len(self.regulators)
        for name, value in zip(self.capacitors, action[:caps]):
            self.circuit.Capacitors.Name = name
            self.circuit.Capacitors.States = [value]
        for name, value in zip(self.regulators, action[caps : caps + regs]):
            transformer = self.circuit.Transformers
            transformer.Name = name
            transformer.Wdg = 2
            transformer.MinTap, transformer.MaxTap, transformer.NumTaps = 0.9, 1.1, 32
            transformer.Tap = 0.9 + value * (0.2 / 32)
            if not math.isclose(transformer.Tap, 0.9 + value * (0.2 / 32), abs_tol=1e-10):
                raise ValueError("DSS did not apply the commanded tap")
        for index, name in enumerate(self.batteries):
            quantum = self.max_kw[index] / 16
            requested = (action[caps + regs + index] - 16) * quantum
            available = (
                self.energy[index] if requested > 0 else (self.energy[index] - self.capacity[index])
            )
            projected = (
                min(requested, math.floor(available / quantum + 1e-8) * quantum)
                if (requested > 0)
                else max(requested, math.ceil(available / quantum - 1e-8) * quantum)
            )
            self.commands_kw[index] = projected
            self.circuit.Generators.Name = name
            self.circuit.Generators.kW = projected
            # Preserve the native PowerGym Generator convention, including Q=P/pf.
            self.circuit.Generators.kvar = projected / self.pf[index]

    def _load_and_solve(self, step: int) -> None:
        if not 0 <= step < self.case["horizon"]:
            raise ValueError("power-flow query outside current episode")
        for index, name in enumerate(self.loads):
            self.circuit.Loads.Name = name
            multiplier = self.case["multipliers"][index][step]
            self.circuit.Loads.kW = self.nominal[index][0] * multiplier
            self.circuit.Loads.kvar = self.nominal[index][1] * multiplier
        self.solution.Tolerance = 1e-10
        self.solution.BuildYMatrix(2, True)
        self.engine.YMatrix.SolutionInitialized = False
        self.pf_calls += 1
        self.solution.Solve()
        if not self.solution.Converged:
            self.failed_pf_calls += 1
            raise ValueError("power flow did not converge")

    def _voltages(self) -> dict[str, list[float]]:
        values = {}
        for bus in self.circuit.AllBusNames:
            self.circuit.SetActiveBus(bus)
            values[bus] = [float(v) for v in self.circuit.ActiveBus.puVmagAngle[::2]]
        if any(not math.isfinite(v) or v <= 0 for row in values.values() for v in row):
            raise ValueError("invalid bus voltage")
        return values

    def _observation_now(self) -> dict:
        return {
            "step": self.step,
            "capacitor_states": list(self.cap_states),
            "regulator_taps": list(self.tap_states),
            "battery_soc": [e / c for e, c in zip(self.energy, self.capacity)],
            "battery_actual_kw": list(self.actual_battery_kw),
            "bus_voltages": self._voltages(),
        }

    def observation(self) -> dict:
        # Search trials must never leak their measurements to observation-only policies.
        import copy

        return copy.deepcopy(self._observation)

    def _measure(self) -> dict:
        voltages = self._voltages()
        flat = [v for row in voltages.values() for v in row]
        loss_kw = float(self.circuit.Losses[0]) / 1000
        source_kw = -float(self.circuit.TotalPower[0])
        if not math.isfinite(loss_kw) or loss_kw < 0 or not math.isfinite(source_kw):
            raise ValueError("invalid whole-circuit active loss or source power")
        return {
            "step": self.step,
            "active_loss_kw": loss_kw,
            "source_active_kw": source_kw,
            "power_loss_ratio": max(0.0, min(1.0, loss_kw / source_kw)) if source_kw > 0 else None,
            "voltage_violation_pu_hours": math.fsum(
                max(0.0, max(row) - 1.05) + max(0.0, 0.95 - min(row)) for row in voltages.values()
            ),
            "compliant_phases": sum(0.95 <= v <= 1.05 for v in flat),
            "phases": len(flat),
            "all_phases_compliant": all(0.95 <= v <= 1.05 for v in flat),
            "min_voltage_pu": min(flat),
            "max_voltage_pu": max(flat),
        }

    def advance(self, action: list[int]) -> dict:
        if self.step >= 24:
            raise ValueError("episode is complete")
        self.validate(action)
        caps, regs = len(self.capacitors), len(self.regulators)
        cap_diff = sum(abs(a - b) for a, b in zip(action[:caps], self.cap_states))
        reg_diff = sum(abs(a - b) for a, b in zip(action[caps : caps + regs], self.tap_states))
        previous_energy = list(self.energy)
        self._apply_devices(action)
        self._load_and_solve(self.step)
        row = self._measure()
        self.cap_switches += cap_diff
        self.tap_moves += reg_diff
        self.cap_states, self.tap_states = action[:caps], action[caps : caps + regs]
        for index, name in enumerate(self.batteries):
            self.circuit.SetActiveElement("Generator." + name)
            power = sum(float(v) for v in self.circuit.ActiveCktElement.Powers[::2])
            if not math.isfinite(power):
                raise ValueError("invalid battery terminal power")
            self.actual_battery_kw[index] = -power
            self.throughput_kwh += abs(power)
            self.energy[index] = float(
                round(max(0.0, min(self.capacity[index], self.energy[index] + power)))
            )
        discharge = sum(max(0.0, p) / m for p, m in zip(self.commands_kw, self.max_kw))
        power_w, dis_w = {"34Bus": (1.0, 10 / 33), "123Bus": (10.0, 7 / 33)}[self.case["network"]]
        ratio = row["power_loss_ratio"]
        row.update(
            {
                "rounding_residual_kwh": [
                    self.energy[i] - max(0.0, min(self.capacity[i], previous_energy[i] - p))
                    for i, p in enumerate(self.actual_battery_kw)
                ],
                "clipping_residual_kwh": [
                    max(0.0, min(self.capacity[i], previous_energy[i] - p))
                    - (previous_energy[i] - p)
                    for i, p in enumerate(self.actual_battery_kw)
                ],
                "action": list(action),
                "capacitor_switches": cap_diff,
                "tap_moves": reg_diff,
                "battery_energy_kwh": list(self.energy),
                "battery_soc": [e / c for e, c in zip(self.energy, self.capacity)],
                "battery_command_kw": list(self.commands_kw),
                "battery_actual_kw": list(self.actual_battery_kw),
                "paper_vanilla_reward_diagnostic": None
                if ratio is None
                else -(
                    row["voltage_violation_pu_hours"]
                    + power_w * ratio
                    + (cap_diff + reg_diff) / 33
                    + dis_w * discharge
                ),
            }
        )
        self.step += 1
        self._observation = self._observation_now()
        return row

    @property
    def metadata(self) -> dict:
        return {
            "capacitor_count": len(self.capacitors),
            "regulator_count": len(self.regulators),
            "battery_count": len(self.batteries),
            "continuous_batteries": False,
            "tap_max": 32,
            "battery_max": 32,
            "horizon": 24,
            "step_hours": 1.0,
            "capacitor_names": list(self.capacitors),
            "regulator_names": list(self.regulators),
            "battery_names": list(self.batteries),
            "battery_capacity_kwh": list(self.capacity),
            "battery_max_kw": list(self.max_kw),
            "initial_soc": [e / c for e, c in zip(self.initial_energy, self.capacity)],
            "terminal_soc": [e / c for e, c in zip(self.initial_energy, self.capacity)],
            "terminal_energy_tolerance_kwh": 1.0,
            "actual_net_energy_tolerance_kwh": 1.0,
            "track": "powergym-formal-stress-energy-neutral-v1",
        }


def validate_action(action: object) -> list[int]:
    limits = [1] * 4 + [32] * 11
    if not isinstance(action, list) or len(action) != 15:
        raise ValueError("expected fifteen discrete device actions")
    if any(type(a) is not int or not 0 <= a <= limit for a, limit in zip(action, limits)):
        raise ValueError("expected bounded integers, excluding booleans")
    return action
