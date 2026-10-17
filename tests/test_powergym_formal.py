"""The formal 123Bus runner preserves qualified physics and enforces both energy gates."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "task-packages/powergym-volt-var-control-formal-v1"
POOL = ROOT / "work/distribution-selection-20261016/powergym/pool"
REFERENCES = (
    ROOT / "work/distribution-qualification-20261016/powergym-final/cases/123Bus-stress-p000-s2.5"
)


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scoring = load("powergym_formal_scoring", PACKAGE / "tests/scoring.py")

    def test_common_starter_is_the_existing_legal_coordinated_reference(self):
        starter = (PACKAGE / "environment/app/submission/controller.py").read_bytes()
        reference = (PACKAGE / "verification/observation_reference.py").read_bytes()
        self.assertEqual(starter, reference)
        lock = json.loads((PACKAGE / "formal-lock.json").read_text())
        self.assertEqual(hashlib.sha256(starter).hexdigest(), lock["starter_sha256"])
        self.assertTrue(lock["same_starter_all_n"])

    def rows(self, power=0.0, violation=0.1):
        return [
            {
                "step": hour,
                "active_loss_kw": 100.0,
                "voltage_violation_pu_hours": violation,
                "compliant_phases": 2,
                "phases": 3,
                "all_phases_compliant": False,
                "min_voltage_pu": 0.94,
                "max_voltage_pu": 1.0,
                "capacitor_switches": 0,
                "tap_moves": 0,
                "battery_energy_kwh": [1000.0] * 4,
                "battery_actual_kw": [power, 0.0, 0.0, 0.0],
                "battery_command_kw": [0.0] * 4,
                "rounding_residual_kwh": [power, 0.0, 0.0, 0.0],
                "clipping_residual_kwh": [0.0] * 4,
            }
            for hour in range(24)
        ]

    def summarize(self, rows, failure=None):
        return self.scoring.summarize(rows, [1000.0] * 4, [1000.0] * 4, failure=failure)

    def test_voltage_is_soft_cost_and_actual_loss_is_integrated(self):
        result = self.summarize(self.rows())
        self.assertTrue(result["valid"])
        self.assertEqual(result["active_loss_kwh"], 2400.0)
        self.assertAlmostEqual(result["reward"], 1 / (1 + 2.4 + 2.4))
        self.assertFalse(result["physical_voltage_feasible"])

    def test_actual_energy_gate_catches_neutral_integer_ledger(self):
        result = self.summarize(self.rows(power=0.49))
        self.assertFalse(result["valid"])
        self.assertEqual(result["reward"], 0.0)
        self.assertEqual(result["terminal_energy_error_kwh"], [0.0] * 4)
        self.assertAlmostEqual(result["actual_net_energy_kwh"][0], 11.76)
        self.assertEqual(result["error"], "actual_terminal_energy_violation")

    def test_each_battery_ledger_horizon_and_failures_are_hard(self):
        rows = self.rows()
        rows[-1]["battery_energy_kwh"] = [998, 1002, 1000, 1000]
        self.assertFalse(self.summarize(rows)["valid"])
        self.assertFalse(self.summarize(self.rows()[:-1])["valid"])
        self.assertFalse(self.summarize(self.rows(), "candidate_timeout")["valid"])
        self.assertTrue(self.summarize(self.rows(power=1 / 24))["valid"])

    def test_fifteen_bounded_integer_actions_exclude_bools(self):
        backend = load("powergym_formal_backend", PACKAGE / "tests/backend.py")
        self.assertEqual(backend.validate_action([1] * 4 + [32] * 11), [1] * 4 + [32] * 11)
        for action in ([True] + [16] * 14, [0] * 14, [2] + [0] * 14, [0] * 14 + [33]):
            with self.assertRaises(ValueError):
                backend.validate_action(action)


@unittest.skipUnless(importlib.util.find_spec("dss") and POOL.is_dir(), "needs DSS frozen pool")
class RealBackendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prepare = load("powergym_formal_prepare", PACKAGE / "prepare.py")
        cls.backend = load("powergym_formal_backend", PACKAGE / "tests/backend.py")
        cls.scoring = load("powergym_formal_scoring", PACKAGE / "tests/scoring.py")

    def test_legal_observation_only_controller_matches_qualified_reference(self):
        controller_module = load(
            "powergym_formal_observation_reference",
            PACKAGE / "verification/observation_reference.py",
        )
        with tempfile.TemporaryDirectory() as temporary:
            data = Path(temporary) / "data"
            self.prepare.prepare(POOL, data)
            backend = self.backend.Backend(data)
            controller = controller_module.Controller(backend.metadata)
            reference = json.loads((REFERENCES / "coordinated_voltage.json").read_text())
            for expected in reference["trajectory"]:
                observation = backend.observation()
                before = backend.observation()
                action = controller.act(observation)
                self.assertEqual(backend.observation(), before)
                self.assertEqual(action, expected["action"])
                row = backend.advance(action)
                self.assertEqual(row["active_loss_kw"], expected["active_loss_kw"])
                self.assertEqual(row["battery_energy_kwh"], expected["battery_energy_kwh"])

    def test_nine_qualified_references_replay_exactly_and_do_not_leak_loads(self):
        with tempfile.TemporaryDirectory() as temporary:
            data = Path(temporary) / "data"
            self.prepare.prepare(POOL, data)
            with self.assertRaises(FileExistsError):
                self.prepare.prepare(POOL, data)
            for result_file in sorted(REFERENCES.glob("*.json")):
                with self.subTest(reference=result_file.stem):
                    reference = json.loads(result_file.read_text())
                    backend = self.backend.Backend(data)
                    self.assertEqual(backend.metadata["capacitor_count"], 4)
                    self.assertEqual(backend.metadata["regulator_count"], 7)
                    self.assertEqual(backend.metadata["battery_count"], 4)
                    self.assertEqual(
                        set(backend.observation()),
                        {
                            "step",
                            "capacitor_states",
                            "regulator_taps",
                            "battery_soc",
                            "battery_actual_kw",
                            "bus_voltages",
                        },
                    )
                    self.assertFalse({"multipliers", "load_names", "plan"} & set(backend.metadata))
                    rows = []
                    for expected in reference["trajectory"]:
                        self.assertEqual(backend.observation()["step"], expected["step"])
                        row = backend.advance(expected["action"])
                        for key in (
                            "active_loss_kw",
                            "voltage_violation_pu_hours",
                            "battery_actual_kw",
                            "battery_energy_kwh",
                            "battery_command_kw",
                            "capacitor_switches",
                            "tap_moves",
                        ):
                            self.assertEqual(row[key], expected[key], key)
                        rows.append(row)
                    summary = self.scoring.summarize(rows, backend.initial_energy, backend.capacity)
                    self.assertEqual(summary["valid"], reference["qualification_valid"])
                    self.assertEqual(summary["reward"], reference["canary_quality"])
                    self.assertEqual(
                        summary["actual_net_energy_kwh"], reference["actual_net_energy_kwh"]
                    )
                    self.assertEqual(backend.pf_calls, 25)
                    with self.assertRaises(ValueError):
                        backend.advance([1] * 4 + [32] * 7 + [16] * 4)


if __name__ == "__main__":
    unittest.main()
