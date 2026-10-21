"""Tests for exogenous selection, causal policies and complete-day accounting."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools/distribution_selection"
sys.path.insert(0, str(TOOLS))
HAS_DATA = all(importlib.util.find_spec(name) for name in ("numpy", "pandas"))
HAS_PP = importlib.util.find_spec("pandapower") is not None


@unittest.skipUnless(HAS_DATA, "optional numpy/pandas dependencies are required")
class SelectionTests(unittest.TestCase):
    def setUp(self):
        import mapdn_selection

        self.selection = mapdn_selection

    def test_quarters_use_first_complete_source_year_and_extremes_use_all_years(self):
        days = {
            "2012-01-02": {"load_mwh": 1.0, "pv_mwh": 1.0},
            "2012-04-01": {"load_mwh": 2.0, "pv_mwh": 2.0},
            "2012-07-01": {"load_mwh": 3.0, "pv_mwh": 3.0},
            "2012-10-01": {"load_mwh": 4.0, "pv_mwh": 4.0},
            "2014-02-01": {"load_mwh": 10.0, "pv_mwh": 1.0},
            "2014-05-01": {"load_mwh": 1.0, "pv_mwh": 10.0},
        }
        selected = self.selection.select_days(days)
        self.assertEqual(len(selected), 6)
        self.assertIn("maximum_daily_load_mwh", selected["2014-02-01"])
        self.assertIn("maximum_daily_pv_mwh", selected["2014-05-01"])

    def test_selection_deduplicates_and_breaks_extreme_ties_by_earliest_date(self):
        days = {
            "2012-01-02": {"load_mwh": 5.0, "pv_mwh": 5.0},
            "2012-01-03": {"load_mwh": 5.0, "pv_mwh": 5.0},
        }
        self.assertEqual(
            self.selection.select_days(days),
            {
                "2012-01-02": [
                    "quarter_1_first_complete",
                    "maximum_daily_load_mwh",
                    "maximum_daily_pv_mwh",
                ]
            },
        )

    def test_stream_scan_excludes_incomplete_day_and_counts_daily_energy(self):
        import numpy as np
        import pandas as pd

        timestamps = pd.date_range("2012-01-01 00:03", periods=959, freq="3min")
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "source.csv"
            pd.DataFrame(np.ones((959, 2)), index=timestamps).to_csv(path)
            scan = self.selection.scan_csv(path, 2, chunk_size=137)
            self.assertEqual(set(scan["complete_days"]), {"2012-01-02"})
            self.assertAlmostEqual(scan["complete_days"]["2012-01-02"]["mwh"], 48.0)
            self.assertEqual(scan["column_max_mw"], [1.0, 1.0])

    def test_stream_scan_rejects_duplicate_timestamps_and_nonfinite_power(self):
        import pandas as pd

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "source.csv"
            for frame in (
                pd.DataFrame({"p": [1, 2]}, index=["2012-01-01", "2012-01-01"]),
                pd.DataFrame({"p": [1, float("nan")]}, index=["2012-01-01", "2012-01-01 00:03"]),
            ):
                frame.to_csv(path)
                with self.assertRaises(ValueError):
                    self.selection.scan_csv(path, 1)

    def test_pool_checksum_is_checked_before_result_execution(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            payload = {"schema": "fixture"}
            self.selection.write_pool(output, payload)
            self.assertEqual(self.selection.read_pool(output)[0], payload)
            (output / "pool.json").write_text(json.dumps({"schema": "changed"}))
            with self.assertRaisesRegex(ValueError, "checksum"):
                self.selection.read_pool(output)

    def test_existing_pool_cannot_be_silently_replaced(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            self.selection.write_pool(output, {"schema": "fixture"})
            with self.assertRaisesRegex(ValueError, "replace"):
                self.selection.write_pool(output, {"schema": "different"})

    def test_cached_result_rejects_tampered_metrics(self):
        expected = {"schema": "mapdn-selection-result-v1", "case_id": "mapdn33-2012-01-02"}
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "result.json"
            self.selection.write_result(path, {**expected, "metrics": {"actual_loss_mwh": 2.0}})
            self.assertEqual(
                self.selection.read_result(path, expected)["metrics"], {"actual_loss_mwh": 2.0}
            )
            path.write_text(json.dumps({**expected, "metrics": {"actual_loss_mwh": 0.0}}))
            with self.assertRaisesRegex(ValueError, "checksum"):
                self.selection.read_result(path, expected)

    def test_cached_result_rejects_copied_case_and_runtime_drift(self):
        expected = {
            "schema": "mapdn-selection-result-v1",
            "case_id": "mapdn33-2012-01-02",
            "network": 33,
            "runtime": {"pandapower": "3.3.0"},
        }
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "result.json"
            self.selection.write_result(path, expected)
            for change in (
                {"case_id": "mapdn33-2012-04-01"},
                {"runtime": {"pandapower": "different"}},
                {"network": 141},
                {"schema": "old"},
            ):
                with self.subTest(change=change), self.assertRaisesRegex(ValueError, "match"):
                    self.selection.read_result(path, {**expected, **change})

    def test_valid_cached_result_requires_actual_complete_day_coverage(self):
        expected = {"schema": "mapdn-selection-result-v1", "case_id": "fixture"}
        complete = {
            **expected,
            "valid": True,
            "scheduled_intervals": 480,
            "completed_intervals": 480,
            "steps": [{"interval_index": index} for index in range(480)],
            "metrics": {"metric_coverage": 1.0, "actual_loss_mwh_is_partial": False},
        }
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "valid.json"
            self.selection.write_result(path, complete)
            self.assertTrue(self.selection.read_result(path, expected)["valid"])
            changes = [
                {"completed_intervals": 479},
                {"steps": complete["steps"][:-1]},
                {"completed_intervals": True},
                {"completed_intervals": 481},
                {"error": "hidden failure"},
                {"metrics": {"metric_coverage": 0.9, "actual_loss_mwh_is_partial": False}},
                {"metrics": {"metric_coverage": 1.0, "actual_loss_mwh_is_partial": True}},
            ]
            for index, change in enumerate(changes):
                corrupt = Path(temporary) / f"inconsistent-{index}.json"
                self.selection.write_result(corrupt, {**complete, **change})
                with self.assertRaisesRegex(ValueError, "coverage"):
                    self.selection.read_result(corrupt, expected)

    def test_failed_opf_cache_must_account_for_every_attempted_interval(self):
        expected = {"schema": "mapdn-selection-result-v1", "case_id": "fixture"}
        partial = {
            **expected,
            "valid": False,
            "scheduled_intervals": 480,
            "completed_intervals": 479,
            "attempted_intervals": 480,
            "policy": {"name": "full_information_ac_opf"},
            "error": "solver failure",
            "steps": [{"interval_index": index} for index in range(479)],
            "failures": [{"interval_index": 479, "error": "solver failed"}],
            "metrics": {"metric_coverage": 479 / 480, "actual_loss_mwh_is_partial": True},
        }
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "partial.json"
            self.selection.write_result(path, partial)
            self.assertFalse(self.selection.read_result(path, expected)["valid"])
            for index, change in enumerate(
                (
                    {"attempted_intervals": 479},
                    {"failures": []},
                    {"failures": [{"interval_index": 0}]},
                )
            ):
                path = Path(temporary) / f"corrupt-{index}.json"
                self.selection.write_result(path, {**partial, **change})
                with self.assertRaisesRegex(ValueError, "coverage"):
                    self.selection.read_result(path, expected)


@unittest.skipUnless(HAS_DATA, "optional numpy dependency is required")
class ControllerAndAccountingTests(unittest.TestCase):
    def test_grid_droop_uses_only_the_current_local_voltage_and_respects_141_bound(self):
        from mapdn_baselines.controllers import GridDroop

        controller = GridDroop({"action_bound": 0.6}, gain=20.0)
        self.assertEqual(controller.act({"pv_voltage_pu": [0.90]}), [0.6])
        self.assertEqual(controller.act({"pv_voltage_pu": [1.10]}), [-0.6])
        self.assertAlmostEqual(controller.act({"pv_voltage_pu": [1.01]})[0], -0.2)

    def test_complete_accounting_distinguishes_paper_cr_and_bus_time(self):
        from mapdn_baselines.simulation import summarize

        rows = [
            dict(
                compliant_bus_count=2,
                paper_all_buses_compliant=False,
                all_buses_compliant=False,
                actual_loss_mw=1.0,
                voltage_violation_sum_pu=0.1,
                worst_undervoltage_pu=0.1,
                worst_overvoltage_pu=0.0,
                power_balance_residual_mw=1e-10,
                mean_abs_q_mvar=0.3,
                voltage_l1=0.01,
                voltage_l2=0.001,
                voltage_bowl=0.002,
            )
            for _ in range(480)
        ]
        result = summarize(rows, bus_count=3, scheduled=480)
        self.assertAlmostEqual(result["bus_time_compliance"], 2 / 3)
        self.assertEqual(result["paper_cr"], 0.0)
        self.assertAlmostEqual(result["actual_loss_mwh"], 24.0)
        self.assertAlmostEqual(result["paper_reward_l1_mean"], -0.04)
        self.assertEqual(result["metric_coverage"], 1.0)

    def test_partial_reference_cannot_claim_full_coverage(self):
        from mapdn_baselines.simulation import summarize

        result = summarize([], bus_count=3, scheduled=480)
        self.assertEqual(result["metric_coverage"], 0.0)
        self.assertIsNone(result["paper_mean_abs_q_mvar"])


@unittest.skipUnless(HAS_PP, "optional Pandapower backend is required")
class PhysicalBackendTests(unittest.TestCase):
    def network(self):
        import pandapower as pp

        net = pp.create_empty_network()
        for zone in ("main", "zone1", "zone1", "zone2"):
            pp.create_bus(net, 12.66, zone=zone)
        pp.create_ext_grid(net, 0, vm_pu=1.0)
        for start, stop in ((0, 1), (1, 2), (0, 3)):
            pp.create_line_from_parameters(net, start, stop, 1, 0.1, 0.1, 0, 1)
        pp.create_load(net, 2, p_mw=0.2, q_mvar=0.1)
        pp.create_load(net, 3, p_mw=0.3, q_mvar=0.1)
        pp.create_sgen(net, 1, p_mw=0.01, q_mvar=0, name="zone1")
        pp.create_sgen(net, 3, p_mw=0.123456, q_mvar=0, name="zone2")
        pp.runpp(net, numba=False)
        return net

    def test_observation_contains_only_own_pv_and_current_region(self):
        import numpy as np
        from mapdn_baselines.simulation import local_data

        net = self.network()
        metadata, observation = local_data(
            net, 0, 0, "2012-01-02T00:00:00", 0.6, np.array([0.4, 0.4])
        )
        self.assertEqual(observation["region_bus_ids"], [1, 2])
        self.assertEqual(observation["pv_active_mw"], [0.01])
        self.assertEqual(metadata["apparent_power_mva"], [0.4])
        self.assertEqual(metadata["action_bound"], 0.6)
        self.assertEqual(len(observation["region_demand_p_mw"]), 2)
        self.assertNotIn("trajectory", observation)
        self.assertNotIn("global_state", observation)
        self.assertNotIn("0.123456", json.dumps(observation))

    def test_independent_power_balance_check_catches_corrupt_branch_losses(self):
        from mapdn_baselines.simulation import measure

        net = self.network()
        self.assertLess(measure(net)["power_balance_residual_mw"], 1e-7)
        net.res_line.loc[0, "pl_mw"] += 0.1
        with self.assertRaisesRegex(ValueError, "balance"):
            measure(net)

    def test_ac_opf_actions_preserve_fixed_active_power_and_original_bounds(self):
        import numpy as np
        from mapdn_baselines.reference import configure_reference, solve_snapshot

        net = self.network()
        trajectory = {
            "pv_active": [[0.01, 0.123456]],
            "load_active": [[0.2, 0.3]],
            "load_reactive": [[0.1, 0.1]],
            "timestamps": ["2012-01-02T00:00:00"],
        }
        configure_reference(net)
        row = solve_snapshot(net, trajectory, 0, np.array([0.4, 0.4]), 0.6)
        self.assertTrue(row["solver_success"])
        self.assertTrue(row["voltage_feasible_within_1e_minus_7"])
        self.assertLessEqual(max(abs(value) for value in row["normalized_actions"]), 0.6)
        np.testing.assert_allclose(net.sgen.p_mw.to_numpy(), [0.01, 0.123456])
        self.assertLess(row["power_balance_residual_mw"], 1e-7)


if __name__ == "__main__":
    unittest.main()
