"""Causal snapshot runner for the fixed PowerGym 34Bus canary adaptation.

The upstream DSS feeder is unchanged. Explicit nominal-load scaling replaces
Gym's ambiguous reset/daily clock. Native battery Generator Q=P/pf and rounded
integer-kWh bookkeeping are retained and disclosed; terminal energy is hard.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import dss


def validate_action(action: object) -> list[int]:
    if not isinstance(action, list) or len(action) != 10:
        raise ValueError("expected ten discrete actions")
    limits = [1, 1] + [32] * 8
    if any(
        type(value) is not int or not 0 <= value <= limit
        for value, limit in zip(action, limits, strict=True)
    ):
        raise ValueError("actions must be in-range integers, excluding booleans")
    return action


class Backend:
    def __init__(self, case_directory: Path):
        self.case = json.loads((case_directory / "case.json").read_text())
        if self.case["horizon"] != 24 or self.case["scale"] != 1.0:
            raise ValueError("unexpected canary horizon or scale")
        self.engine = dss.DSS.NewContext()
        self.engine.AllowChangeDir = False
        self.engine.Text.Command = f'compile "{case_directory / "34Bus/ieee34Mod1_daily.dss"}"'
        self.engine.Text.Command = "set mode=snapshot controlmode=off maxiterations=100"
        self.circuit = self.engine.ActiveCircuit
        self.solution = self.circuit.Solution
        self.loads = list(self.case["load_names"])
        self.nominal = []
        for name in self.loads:
            self.circuit.Loads.Name = name
            self.nominal.append((float(self.circuit.Loads.kW), float(self.circuit.Loads.kvar)))
        self.capacitors = list(self.circuit.Capacitors.AllNames)
        self.regulators = []
        reg_controls = self.circuit.RegControls
        if reg_controls.First:
            while True:
                name = reg_controls.Transformer
                if name not in self.regulators:
                    self.regulators.append(name)
                if not reg_controls.Next:
                    break
        self.batteries = ["batt1", "batt2"]
        if len(self.capacitors) != 2 or len(self.regulators) != 6:
            raise ValueError("unexpected device schema")
        self.energy = [4000.0, 4000.0]
        self.cap_states = [1, 1]
        self.tap_states = [32] * 6
        self.actual_battery_kw = [0.0, 0.0]
        self.commands_kw = [0.0, 0.0]
        self.cap_switches = 0
        self.tap_moves = 0
        self.throughput_kwh = 0.0
        self.step = 0
        self._set_devices([1, 1] + [32] * 6 + [16, 16])
        self._load_and_solve(0)

    @property
    def metadata(self) -> dict:
        return {
            "capacitor_count": 2,
            "regulator_count": 6,
            "battery_count": 2,
            "continuous_batteries": False,
            "tap_max": 32,
            "battery_max": 32,
            "horizon": 24,
            "step_hours": 1.0,
            "capacitor_names": self.capacitors,
            "regulator_names": self.regulators,
            "battery_names": self.batteries,
            "battery_capacity_kwh": [4000.0] * 2,
            "battery_max_kw": [500.0] * 2,
            "terminal_soc": [1.0] * 2,
            "terminal_energy_tolerance_kwh": 1.0,
            "track": "powergym-energy-neutral-canary-v1",
        }

    def _set_devices(self, action: list[int]) -> None:
        action = validate_action(action)
        for index, name in enumerate(self.capacitors):
            self.circuit.Capacitors.Name = name
            self.circuit.Capacitors.States = [action[index]]
        for index, name in enumerate(self.regulators):
            transformer = self.circuit.Transformers
            transformer.Name = name
            transformer.Wdg = 2
            transformer.MinTap = 0.9
            transformer.MaxTap = 1.1
            # Keep 32 intervals; upstream writes the requested action to NumTaps.
            transformer.NumTaps = 32
            transformer.Tap = 0.9 + action[index + 2] * (0.2 / 32)
            if not math.isclose(
                transformer.Tap, 0.9 + action[index + 2] * (0.2 / 32), abs_tol=1e-10
            ):
                raise ValueError("backend failed to apply the declared tap")
        self.cap_switches += sum(abs(a - b) for a, b in zip(action[:2], self.cap_states))
        self.tap_moves += sum(abs(a - b) for a, b in zip(action[2:8], self.tap_states))
        self.cap_states, self.tap_states = action[:2], action[2:8]
        for index, name in enumerate(self.batteries):
            requested = (action[8 + index] - 16) * 31.25
            available = self.energy[index] if requested > 0 else self.energy[index] - 4000
            # Native discrete power projection, preserving 31.25 kW levels.
            if requested > 0:
                projected = min(requested, math.floor(available / 31.25 + 1e-8) * 31.25)
            else:
                projected = max(requested, math.ceil(available / 31.25 - 1e-8) * 31.25)
            self.commands_kw[index] = projected
            self.circuit.Generators.Name = name
            self.circuit.Generators.kW = projected
            self.circuit.Generators.kvar = projected / 0.95

    def _load_and_solve(self, step: int) -> None:
        for index, name in enumerate(self.loads):
            self.circuit.Loads.Name = name
            multiplier = self.case["multipliers"][index][step]
            self.circuit.Loads.kW = self.nominal[index][0] * multiplier
            self.circuit.Loads.kvar = self.nominal[index][1] * multiplier
        self.solution.Solve()
        if not self.solution.Converged:
            raise ValueError("power flow did not converge")

    def voltages(self) -> dict[str, list[float]]:
        values = {}
        for bus in self.circuit.AllBusNames:
            self.circuit.SetActiveBus(bus)
            values[bus] = [float(value) for value in self.circuit.ActiveBus.puVmagAngle[::2]]
        if any(not math.isfinite(v) or v <= 0 for row in values.values() for v in row):
            raise ValueError("non-finite or nonpositive voltage")
        return values

    def observation(self) -> dict:
        return {
            "step": self.step,
            "capacitor_states": list(self.cap_states),
            "regulator_taps": list(self.tap_states),
            "battery_soc": [v / 4000 for v in self.energy],
            "battery_actual_kw": list(self.actual_battery_kw),
            "bus_voltages": self.voltages(),
        }

    def advance(self, action: list[int]) -> dict:
        if self.step >= 24:
            raise ValueError("episode is complete")
        self._set_devices(action)
        self._load_and_solve(self.step)
        voltages = self.voltages()
        flat = [value for row in voltages.values() for value in row]
        loss_kw = float(self.circuit.Losses[0]) / 1000
        if not math.isfinite(loss_kw) or loss_kw < 0:
            raise ValueError("invalid circuit active loss")
        for index, name in enumerate(self.batteries):
            self.circuit.SetActiveElement("Generator." + name)
            # OpenDSS terminal powers are positive into the Generator element.
            power = sum(float(v) for v in self.circuit.ActiveCktElement.Powers[::2])
            if not math.isfinite(power):
                raise ValueError("invalid battery terminal power")
            self.actual_battery_kw[index] = -power
            self.throughput_kwh += abs(power)
            self.energy[index] = float(round(max(0.0, min(4000.0, self.energy[index] + power))))
        row = {
            "step": self.step,
            "active_loss_kw": loss_kw,
            "voltage_violation_pu_hours": sum(
                max(0.0, max(row) - 1.05) + max(0.0, 0.95 - min(row)) for row in voltages.values()
            ),
            "compliant_phases": sum(0.95 <= v <= 1.05 for v in flat),
            "phases": len(flat),
            "min_voltage_pu": min(flat),
            "max_voltage_pu": max(flat),
            "battery_soc": [v / 4000 for v in self.energy],
            "battery_command_kw": list(self.commands_kw),
            "battery_actual_kw": list(self.actual_battery_kw),
        }
        self.step += 1
        return row
