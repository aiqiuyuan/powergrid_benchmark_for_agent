"""Checks for source-aligned iteration, local permissions and physical receipts."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/distribution_qualification"))
HAS_DATA = all(importlib.util.find_spec(name) for name in ("numpy", "pandas"))
HAS_PP = importlib.util.find_spec("pandapower") is not None


class LocalControllerTests(unittest.TestCase):
    def test_source_curve_saturates_and_clips_to_benchmark_action_bound(self):
        from mapdn_controllers import source_curve

        for bound in (0.6, 0.8):
            self.assertEqual(source_curve(0.90, bound), bound)
            self.assertEqual(source_curve(1.10, bound), -bound)
            self.assertEqual(source_curve(1.0, bound), 0.0)
            self.assertAlmostEqual(source_curve(0.99, bound), 0.2)
            self.assertAlmostEqual(source_curve(1.01, bound), -0.2)

    def test_single_step_actor_needs_only_legal_pv_local_fields(self):
        from mapdn_controllers import MemoryController

        actor = MemoryController(
            {"action_bound": 0.6, "apparent_power_mva": [1.0]},
            {"name": "one_step_integral", "gain": 2.5},
        )
        observation = {
            "pv_voltage_pu": [0.98],
            "pv_active_mw": [0.8],
            "pv_reactive_mvar": [0.3],
        }
        self.assertAlmostEqual(actor.act(observation)[0], 0.55)
        observation["pv_voltage_pu"] = [1.02]
        observation["pv_reactive_mvar"] = [0.0]
        self.assertAlmostEqual(actor.act(observation)[0], -0.05)

    def test_relaxed_memory_is_physical_q_divided_by_current_capability(self):
        from mapdn_controllers import MemoryController

        actor = MemoryController(
            {"action_bound": 0.8, "apparent_power_mva": [1.0]},
            {"name": "one_step_relaxed", "relaxation": 0.1},
        )
        self.assertAlmostEqual(
            actor.act({"pv_voltage_pu": [1.0], "pv_active_mw": [0.8], "pv_reactive_mvar": [0.3]})[
                0
            ],
            0.45,
        )
        self.assertEqual(
            actor.act({"pv_voltage_pu": [0.9], "pv_active_mw": [1.0], "pv_reactive_mvar": [0.0]}),
            [0.0],
        )

    def test_distinct_actors_do_not_share_memory_or_receive_global_data(self):
        from mapdn_controllers import MemoryController

        policy = {"name": "one_step_integral", "gain": 1.0}
        metadata = {"action_bound": 0.8, "apparent_power_mva": [1.0]}
        first, second = MemoryController(metadata, policy), MemoryController(metadata, policy)
        first.act({"pv_voltage_pu": [0.9], "pv_active_mw": [0.0], "pv_reactive_mvar": [0.0]})
        self.assertEqual(
            second.act({"pv_voltage_pu": [1.0], "pv_active_mw": [0.0], "pv_reactive_mvar": [0.0]}),
            [0.0],
        )
        self.assertNotIn("network", vars(first))


@unittest.skipUnless(HAS_DATA, "optional numpy/pandas dependencies are required")
class SourceIterationTests(unittest.TestCase):
    def test_iteration_resets_q_and_counts_initial_duplicate_and_final_solve(self):
        from mapdn_simulation import source_iteration

        calls = []

        def solve(action):
            calls.append(action.copy())
            return [1.0, 1.0]

        action, audit = source_iteration(solve, count=2, bound=0.8)
        self.assertEqual(action.tolist(), [0.0, 0.0])
        self.assertEqual(len(calls), 4)
        self.assertEqual(audit["loop_iterations"], 2)
        self.assertEqual(audit["stop_reason"], "pv_voltage_l2_converged")
        self.assertEqual(audit["independent_final_pf_calls"], 1)
        self.assertEqual(audit["pf_calls"], 4)

    def test_max_iteration_keeps_last_solved_q_not_last_unsolved_update(self):
        from mapdn_simulation import source_iteration

        calls = []

        def solve(action):
            calls.append(action.copy())
            return [0.9]

        action, audit = source_iteration(solve, count=1, bound=0.6, max_iterations=1)
        self.assertEqual(action.tolist(), [0.0])
        self.assertEqual(calls[-1].tolist(), [0.0])
        self.assertAlmostEqual(audit["trace"][-1]["proposed_next_actions"][0], 0.06)
        self.assertEqual(audit["stop_reason"], "maximum_iterations")
        self.assertEqual(audit["pf_calls"], 3)

    def test_convergence_test_uses_pv_l2_not_max_or_global_voltage(self):
        from mapdn_simulation import source_iteration

        voltage, previous_action = 1.0, None

        def solve(action):
            nonlocal voltage, previous_action
            if previous_action != action.tolist():
                voltage += 0.00008
                previous_action = action.tolist()
            return [voltage] * 2

        _, audit = source_iteration(solve, count=2, bound=0.8, max_iterations=3)
        self.assertEqual(audit["stop_reason"], "maximum_iterations")
        self.assertGreater(audit["trace"][-1]["voltage_change_l2"], 1e-4)

    def test_cache_rechecks_code_runtime_and_recomputed_physical_totals(self):
        import mapdn_qualification as qualification
        from mapdn_selection import write_result

        expected = {
            "schema": "mapdn-qualification-result-v1",
            "case_id": "fixture",
            "implementation_sha256": {"code": "abc"},
            "runtime": {"test": "1"},
        }
        result = {
            **expected,
            "valid": False,
            "scheduled_intervals": 480,
            "completed_intervals": 0,
            "pf_calls": 0,
            "steps": [],
            "metrics": qualification.summarize([], bus_count=33),
            "bus_count": 33,
            "action_bound": 0.8,
            "error": None,
        }
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "result.json"
            write_result(path, result)
            self.assertFalse(qualification.read_qualified_result(path, expected)["valid"])
            with self.assertRaisesRegex(ValueError, "match"):
                qualification.read_qualified_result(path, {**expected, "runtime": {"test": "2"}})
            changed = Path(temporary) / "changed.json"
            result["metrics"]["actual_loss_mwh"] = 42.0
            write_result(changed, result)
            with self.assertRaisesRegex(ValueError, "metric"):
                qualification.read_qualified_result(changed, expected)


@unittest.skipUnless(HAS_PP, "optional pandapower dependency is required")
class PhysicalBackendTests(unittest.TestCase):
    def test_real_smoke_has_independent_final_solve_and_full_balance_accounting(self):
        from mapdn_qualification import load_case, read_pool
        from mapdn_simulation import evaluate

        directory = ROOT / "work/distribution-selection-20261016/mapdn33-final"
        if not (directory / "pool.json").exists():
            self.skipTest("the frozen real source pool is unavailable")
        pool, _ = read_pool(directory)
        case = next(row for row in pool["cases"] if row["date"] == "2012-02-03")
        net, trajectory = load_case(directory, pool, case)
        result = evaluate(net, trajectory, pool, {"name": "source_iterative_droop"}, 2)
        self.assertFalse(result["valid"])
        self.assertEqual(result["completed_intervals"], 2)
        self.assertTrue(result["metrics"]["actual_loss_mwh_is_partial"])
        self.assertEqual(
            result["pf_calls"], sum(row["iteration_audit"]["pf_calls"] for row in result["steps"])
        )
        self.assertLess(result["metrics"]["max_power_balance_residual_mw"], 1e-7)
        for row in result["steps"]:
            self.assertEqual(row["iteration_audit"]["independent_final_pf_calls"], 1)
            self.assertAlmostEqual(
                row["pv_q_mvar"][0], row["normalized_actions"][0] * row["q_capability_mvar"][0]
            )
        from mapdn_qualification import read_qualified_result, write_result

        corrupt = json.loads(json.dumps(result))
        corrupt["steps"][0]["iteration_audit"]["physical_pf_trace"][-1]["normalized_actions"][
            0
        ] += 1e-3
        corrupt.update(schema="mapdn-qualification-result-v1", case_id=case["case_id"])
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "corrupt.json"
            write_result(path, corrupt)
            with self.assertRaisesRegex(ValueError, "final physical PF"):
                read_qualified_result(path, {"case_id": case["case_id"]})

    def test_resource_limit_retains_attempt_without_scoring_unsolved_action(self):
        from mapdn_qualification import load_case, read_pool
        from mapdn_simulation import evaluate

        directory = ROOT / "work/distribution-selection-20261016/mapdn33-final"
        if not (directory / "pool.json").exists():
            self.skipTest("the frozen real source pool is unavailable")
        pool, _ = read_pool(directory)
        case = next(row for row in pool["cases"] if row["date"] == "2012-02-03")
        net, trajectory = load_case(directory, pool, case)
        result = evaluate(net, trajectory, pool, {"name": "source_iterative_droop"}, 2, pf_budget=1)
        self.assertFalse(result["valid"])
        self.assertEqual(result["completed_intervals"], 0)
        self.assertEqual(result["pf_calls"], 1)
        self.assertEqual(result["failure_kind"], "resource_budget_exhausted")
        self.assertEqual(result["failed_attempt"]["pf_calls"], 1)
        self.assertEqual(result["metrics"]["actual_loss_mwh"], 0.0)


if __name__ == "__main__":
    unittest.main()
