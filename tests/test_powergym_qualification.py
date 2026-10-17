"""Strong references retain the original generator and energy contract."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/distribution_qualification"))

from powergym_search import objective, paired_schedules, terminal_valid  # noqa: E402


class SearchTests(unittest.TestCase):
    @staticmethod
    def synthetic_evaluator():
        from types import SimpleNamespace

        from powergym_search import DayEvaluator

        evaluator = object.__new__(DayEvaluator)
        evaluator.case = {"terminal_energy_tolerance_kwh": 1.0}
        evaluator.backend = SimpleNamespace(initial_energy=[100.0])
        evaluator.initial_action, evaluator.devices, evaluator.caps = [1, 32, 16], 2, 1

        def query(_hour, action, energy):
            power = action[-1] - 16
            return {
                "next_energy_kwh": [energy[0] - power],
                "battery_actual_kw": [power],
                "voltage_violation_pu_hours": (abs(action[1] - 16) + action[0]) / 100,
                "active_loss_kw": 1 + abs(power) * 10,
            }

        evaluator.query = query
        return evaluator

    def test_complete_device_search_reaches_known_synthetic_feasible_setting(self):
        from powergym_search import current_idle, day_idle, static_idle

        evaluator = self.synthetic_evaluator()
        parameters = {
            "uniform_tap_starts": [0, 8, 16, 24, 32],
            "retained_starts": 3,
            "current_coordinate_passes": 2,
            "static_coordinate_passes": 2,
            "day_coordinate_passes": 2,
        }
        current = current_idle(evaluator, parameters)
        static = static_idle(evaluator, parameters)
        self.assertEqual(current, [[0, 16, 16]] * 24)
        self.assertEqual(static, current)
        self.assertEqual(day_idle(evaluator, [static, current], parameters), current)

    def test_active_storage_is_retained_even_when_idle_is_better(self):
        from powergym_search import storage

        evaluator = self.synthetic_evaluator()
        schedule = [[0, 16, 16] for _ in range(24)]
        free, active = storage(
            evaluator,
            schedule,
            {
                "battery_coordinate_passes": 2,
                "battery_slots": [0, 12, 23],
                "battery_amplitudes": [1, 4],
            },
        )
        self.assertEqual(free, schedule)
        self.assertIsNotNone(active)
        self.assertTrue(evaluator.evaluate(active)["valid"])
        self.assertGreater(evaluator.evaluate(active)["battery_throughput_kwh"], 0)
        self.assertGreater(evaluator.evaluate(active)["key"], evaluator.evaluate(free)["key"])

    def test_integer_ledger_neutrality_cannot_hide_actual_energy_consumption(self):
        from types import SimpleNamespace

        from powergym_search import DayEvaluator

        evaluator = object.__new__(DayEvaluator)
        evaluator.case = {"terminal_energy_tolerance_kwh": 1.0}
        evaluator.backend = SimpleNamespace(initial_energy=[100.0])
        evaluator.initial_action, evaluator.devices = [16], 0
        evaluator.query = lambda *_: {
            "next_energy_kwh": [100.0],
            "battery_actual_kw": [0.49],
            "voltage_violation_pu_hours": 0.0,
            "active_loss_kw": 0.0,
        }
        result = evaluator.evaluate([[16] for _ in range(24)])
        self.assertEqual(result["final_energy_kwh"], [100.0])
        self.assertAlmostEqual(result["actual_net_energy_kwh"][0], 11.76)
        self.assertFalse(result["valid"])

    def test_durable_output_cannot_replace_an_existing_file(self):
        from powergym_qualification import immutable_json

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "result.json"
            immutable_json(path, {"first": True})
            with self.assertRaises(FileExistsError):
                immutable_json(path, {"second": True})
            self.assertEqual(json.loads(path.read_text()), {"first": True})

    def test_voltage_priority_does_not_trade_safety_for_loss(self):
        safe = objective(0.0, 10000.0, 200)
        unsafe = objective(0.00001, 1.0, 0)
        self.assertLess(safe, unsafe)

    def test_pair_schedule_is_legal_and_changes_only_one_battery(self):
        schedule = [[1, 1] + [20] * 6 + [16, 16] for _ in range(24)]
        alternatives = list(paired_schedules(schedule, 8, [0, 12, 23], [1, 16]))
        self.assertEqual(len(alternatives), 6)
        for trial in alternatives:
            self.assertEqual(trial[0][:8], schedule[0][:8])
            self.assertTrue(all(row[9] == 16 for row in trial))
            changed = [i for i, row in enumerate(trial) if row[8] != 16]
            self.assertEqual(len(changed), 2)
            self.assertLess(changed[0], changed[1])
            self.assertEqual(trial[changed[0]][8] + trial[changed[1]][8], 32)
            self.assertGreater(trial[changed[0]][8], 16)
        self.assertTrue(all(row[8] == 16 for row in schedule))

    def test_terminal_constraint_is_per_battery_and_requires_full_horizon(self):
        self.assertTrue(terminal_valid([100, 100], [99, 101], 24, 1.0))
        self.assertFalse(terminal_valid([100, 100], [98, 102], 24, 1.0))
        self.assertFalse(terminal_valid([100, 100], [100, 100], 23, 1.0))
        self.assertFalse(terminal_valid([100, 100], [100], 24, 1.0))


POOL = ROOT / "work/distribution-selection-20261016/powergym/pool"


@unittest.skipUnless(importlib.util.find_spec("dss") and POOL.is_dir(), "needs DSS pool")
class BackendTests(unittest.TestCase):
    def test_budget_failure_preserves_attempt_and_phase_counts(self):
        from powergym_qualification import CaseFailure, case_results

        case = json.loads((POOL / "cases/34Bus-standard-p000-s1.json").read_text())
        protocol = json.loads(
            (ROOT / "configs/distribution-baseline-qualification-20261016.json").read_text()
        )["powergym"]
        numerics = json.loads(
            (
                ROOT / "configs/distribution-baseline-qualification-20261016-numerics.json"
            ).read_text()
        )["powergym"]
        protocol["max_pf_calls_per_case_all_baselines"] = 226
        with self.assertRaises(CaseFailure) as caught:
            next(case_results(case, POOL / "assets/34Bus", protocol, numerics, "fixture"))
        self.assertEqual(caught.exception.diagnostics["failed_baseline"], "strong_current_idle")
        self.assertEqual(caught.exception.diagnostics["case_cumulative_pf_calls"], 1)
        self.assertIsNotNone(caught.exception.diagnostics["last_query"])

    def test_cached_summary_or_ledger_edits_are_rejected_even_with_new_sha(self):
        from powergym_qualification import read_result, write_result
        from powergym_search import DayEvaluator

        case = json.loads((POOL / "cases/34Bus-standard-p000-s1.json").read_text())
        evaluator = DayEvaluator(case, POOL / "assets/34Bus")
        schedule = [[1, 1] + [20] * 6 + [16, 16] for _ in range(24)]
        result = evaluator.replay(schedule, "fixture")
        result.update(
            schema_version="powergym-qualification-result-v1",
            case_id=case["id"],
            run_lock_sha256="fixture",
            physical_voltage_feasible=False,
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "first.json"
            write_result(path, result)
            self.assertEqual(read_result(path, case, "fixture", "fixture"), result)
            result["phase_time_compliance"] = 0.5
            changed = Path(temporary) / "changed.json"
            write_result(changed, result)
            with self.assertRaisesRegex(ValueError, "phase_time_compliance"):
                read_result(changed, case, "fixture", "fixture")

    def test_snapshot_queries_do_not_advance_state_and_replay_nonzero_cycle(self):
        from powergym_search import DayEvaluator

        case = json.loads((POOL / "cases/34Bus-standard-p000-s1.json").read_text())
        evaluator = DayEvaluator(case, POOL / "assets/34Bus")
        before = evaluator.backend.observation()
        initial = list(evaluator.backend.energy)
        action = [1, 1] + [16] * 6 + [17, 16]
        measured = evaluator.query(0, action, initial)
        self.assertEqual(evaluator.backend.step, 0)
        self.assertEqual(evaluator.backend.energy, initial)
        self.assertEqual(evaluator.backend.observation(), before)
        self.assertGreater(measured["battery_actual_kw"][0], 1)
        self.assertLess(measured["next_energy_kwh"][0], initial[0])
        evaluator.backend.circuit.Generators.Name = "batt1"
        self.assertAlmostEqual(evaluator.backend.circuit.Generators.kvar, 31.25 / 0.95)
        schedule = [[1, 1] + [20] * 6 + [16, 16] for _ in range(24)]
        schedule[0][-2], schedule[23][-2] = 20, 12
        estimate = evaluator.evaluate(schedule)
        replay = evaluator.replay(schedule, "fixture")
        self.assertTrue(replay["valid"])
        self.assertGreater(replay["battery_throughput_kwh"], 249)
        self.assertEqual(replay["terminal_energy_error_kwh"], [0.0, 0.0])
        self.assertAlmostEqual(estimate["active_loss_kwh"], replay["active_loss_kwh"], places=7)
        self.assertEqual(estimate["final_energy_kwh"], replay["final_energy_kwh"])

    def test_fractional_quantum_rounding_can_block_recharge(self):
        from powergym_search import DayEvaluator

        case = json.loads((POOL / "cases/34Bus-standard-p000-s1.json").read_text())
        evaluator = DayEvaluator(case, POOL / "assets/34Bus")
        schedule = [[1, 1] + [16] * 6 + [16, 16] for _ in range(24)]
        schedule[0][-2], schedule[23][-2] = 17, 15
        result = evaluator.replay(schedule, "boundary")
        self.assertFalse(result["valid"])
        self.assertEqual(result["trajectory"][23]["battery_command_kw"][0], 0.0)
        self.assertEqual(result["terminal_energy_error_kwh"][0], 31.0)

    def test_query_order_and_cache_do_not_change_independent_replay(self):
        from powergym_search import DayEvaluator

        case = json.loads((POOL / "cases/34Bus-standard-p000-s1.json").read_text())
        evaluator = DayEvaluator(case, POOL / "assets/34Bus")
        first = [1, 1] + [16] * 6 + [20, 16]
        second = [0, 0] + [24] * 6 + [16, 16]
        energy = [4000.0, 4000.0]
        before = evaluator.query(0, first, energy)
        count = evaluator.pf_calls
        evaluator.query(5, second, energy)
        self.assertEqual(evaluator.query(0, first, energy), before)
        self.assertEqual(evaluator.pf_calls, count + 1)
        evaluator.cache.clear()
        repeat = evaluator.query(0, first, energy)
        self.assertAlmostEqual(before["active_loss_kw"], repeat["active_loss_kw"], places=7)
        self.assertEqual(before["next_energy_kwh"], repeat["next_energy_kwh"])

    def test_adversarial_interleaving_preserves_every_rounded_energy(self):
        import random

        from powergym_backend import QualificationBackend
        from powergym_search import DayEvaluator

        for case_id in (
            "34Bus-standard-p000-s1",
            "123Bus-standard-p000-s1",
            "123Bus-stress-p000-s2.5",
        ):
            with self.subTest(case=case_id):
                case = json.loads((POOL / f"cases/{case_id}.json").read_text())
                assets = POOL / "assets" / case["network"]
                evaluator = DayEvaluator(case, assets)
                randomizer = random.Random(103)
                batteries = len(evaluator.backend.batteries)
                regulators = evaluator.devices - evaluator.caps
                plan = [
                    [randomizer.randrange(2) for _ in range(evaluator.caps)]
                    + [randomizer.randrange(14, 23) for _ in range(regulators)]
                    + [randomizer.randrange(14, 19) for _ in range(batteries)]
                    for _ in range(24)
                ]
                energy, expected = list(evaluator.backend.initial_energy), []
                for hour, action in enumerate(plan):
                    junk = [randomizer.randrange(2) for _ in range(evaluator.caps)]
                    junk += [randomizer.randrange(33) for _ in range(regulators + batteries)]
                    evaluator.query(
                        randomizer.randrange(24),
                        junk,
                        [capacity / 2 for capacity in evaluator.backend.capacity],
                    )
                    row = evaluator.query(hour, action, energy)
                    expected.append(row)
                    energy = row["next_energy_kwh"]
                fresh = QualificationBackend(case, assets)
                for action, row in zip(plan, expected):
                    actual = fresh.advance(action)
                    self.assertEqual(actual["active_loss_kw"], row["active_loss_kw"])
                    self.assertEqual(actual["battery_energy_kwh"], row["next_energy_kwh"])


if __name__ == "__main__":
    unittest.main()
