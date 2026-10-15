"""Pure-helper checks, without a simulator or complete target scoring."""

import math
import unittest

from powergrid_bench.distribution.common import integrate_active_loss, voltage_metrics
from powergrid_bench.distribution.mapdn import (
    droop_action,
    project_actor_observations,
    reactive_power,
)
from powergrid_bench.distribution.mapdn import (
    validate_actions as validate_mapdn_actions,
)
from powergrid_bench.distribution.powergym import (
    active_loss_kwh,
    idle_action,
    terminal_soc_valid,
)
from powergrid_bench.distribution.powergym import (
    validate_actions as validate_powergym_actions,
)


class DistributionMetricTests(unittest.TestCase):
    def test_voltage_compliance_and_integrated_violations(self):
        result = voltage_metrics(
            [[0.94, 1.06], [1.0, 1.05]],
            lower=0.95,
            upper=1.05,
            expected_steps=2,
            step_hours=[0.5, 1.0],
        )
        self.assertTrue(result.complete)
        self.assertEqual(result.steps, 2)
        self.assertEqual(result.points_per_step, 2)
        self.assertEqual(result.timestep_compliance_rate, 0.5)
        self.assertEqual(result.measurement_compliance_rate, 0.5)
        self.assertAlmostEqual(result.worst_violation_pu, 0.01)
        self.assertAlmostEqual(result.integrated_violation_pu_hours, 0.01)

    def test_early_horizon_is_not_complete(self):
        result = voltage_metrics([[1.0]], expected_steps=3)
        self.assertFalse(result.complete)
        self.assertEqual(result.expected_steps, 3)

    def test_unspecified_horizon_does_not_certify_completeness(self):
        result = voltage_metrics([[1.0]])
        self.assertFalse(result.complete)
        self.assertEqual(result.converged_steps, 1)

    def test_nonconverged_snapshot_is_never_compliant(self):
        result = voltage_metrics([[1.0], [1.0]], converged=[True, False])
        self.assertFalse(result.complete)
        self.assertEqual(result.converged_steps, 1)
        self.assertEqual(result.timestep_compliance_rate, 0.5)
        self.assertEqual(result.measurement_compliance_rate, 0.5)

    def test_rejects_invalid_snapshots_and_horizon(self):
        for snapshots in ([], [[]], [[1.0], [1.0, 1.01]], [[math.nan]], [[True]]):
            with self.subTest(snapshots=snapshots), self.assertRaises(ValueError):
                voltage_metrics(snapshots)
        for kwargs in (
            {"expected_steps": 0},
            {"expected_steps": True},
            {"expected_steps": 1.5},
            {"expected_steps": 1},
            {"converged": [True]},
            {"converged": [True, 1]},
            {"lower": 1.1, "upper": 1.0},
            {"step_hours": [1.0]},
            {"step_hours": 0},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                voltage_metrics([[1.0], [1.0]], **kwargs)

    def test_loss_integration_converts_units_and_durations(self):
        self.assertEqual(
            integrate_active_loss(
                [10, 20], step_hours=[0.5, 2], power_unit="kW", energy_unit="kWh"
            ),
            45,
        )
        self.assertAlmostEqual(
            integrate_active_loss(
                [0.01, 0.02], step_hours=[0.5, 2], power_unit="MW", energy_unit="MWh"
            ),
            0.045,
        )
        self.assertEqual(
            integrate_active_loss([1], step_hours=1, power_unit="MW", energy_unit="kWh"),
            1000,
        )
        self.assertAlmostEqual(
            integrate_active_loss([1], step_hours=1, power_unit="kW", energy_unit="MWh"),
            0.001,
        )

    def test_loss_rejects_nonfinite_negative_mixed_and_unknown_units(self):
        for losses in ([math.inf], [-1], [True], [[1]], []):
            with self.subTest(losses=losses), self.assertRaises(ValueError):
                integrate_active_loss(losses, step_hours=1, power_unit="kW", energy_unit="kWh")
        for kwargs in (
            {"step_hours": [1, 2], "power_unit": "kW", "energy_unit": "kWh"},
            {"step_hours": True, "power_unit": "kW", "energy_unit": "kWh"},
            {"step_hours": 1, "power_unit": "kwh", "energy_unit": "kWh"},
            {"step_hours": 1, "power_unit": "kW", "energy_unit": "MW"},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                integrate_active_loss([1], **kwargs)


class MAPDNHelperTests(unittest.TestCase):
    def test_action_bounds_and_capability_mapping(self):
        self.assertEqual(
            validate_mapdn_actions([0.6, -0.8], expected_size=2, bound=[0.6, 0.8]), (0.6, -0.8)
        )
        self.assertEqual(
            reactive_power([0.5, -0.5], active_power=[3, 0], apparent_power=[5, 2], bound=0.8),
            (2.0, -1.0),
        )
        self.assertEqual(
            reactive_power([0.0], active_power=[0], apparent_power=[0], bound=0.8), (0.0,)
        )

    def test_rejects_bad_action_shapes_values_and_bounds(self):
        for actions in ([0], [[0, 0]], [0, math.nan], [0, True], [0.9, 0], ["0", 0]):
            with self.subTest(actions=actions), self.assertRaises(ValueError):
                validate_mapdn_actions(actions, expected_size=2, bound=0.8)
        for bound in (0, 1.1, -0.8, math.inf, True, [0.8]):
            with self.subTest(bound=bound), self.assertRaises(ValueError):
                validate_mapdn_actions([0, 0], expected_size=2, bound=bound)

    def test_rejects_impossible_pv_capability(self):
        for active, apparent in (([2], [1]), ([-1], [1]), ([1], [-1]), ([1, 2], [3])):
            with self.subTest(active=active, apparent=apparent), self.assertRaises(ValueError):
                reactive_power([0.5], active_power=active, apparent_power=apparent, bound=0.8)

    def test_large_finite_capability_does_not_overflow(self):
        result = reactive_power([0.5], active_power=[3e200], apparent_power=[5e200], bound=0.8)
        self.assertAlmostEqual(result[0] / 1e200, 2.0)

    def test_projects_and_copies_each_actors_allowlisted_data(self):
        original = [{"actor_id": "a", "voltage": [1.01], "debug": "omit"}]
        projected = project_actor_observations(original, allowed_fields=["actor_id", "voltage"])
        self.assertEqual(projected, ({"actor_id": "a", "voltage": [1.01]},))
        projected[0]["voltage"][0] = 0.8
        self.assertEqual(original[0]["voltage"], [1.01])

    def test_rejects_global_future_missing_and_nonfinite_observations(self):
        for observations, fields in (
            ([{"voltage": [1.0], "global_state": [2]}], ["voltage"]),
            ([{"future_profiles": [1]}], ["future_profiles"]),
            ([{"voltage": {"future": [1]}}], ["voltage"]),
            ([{"voltage": [math.nan]}], ["voltage"]),
            ([{"voltage": object()}], ["voltage"]),
            ([{"actor_id": "a"}], ["voltage"]),
        ):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                project_actor_observations(observations, allowed_fields=fields)

    def test_droop_is_bounded_and_responds_to_voltage(self):
        self.assertEqual(droop_action(0.9, gain=10, bound=0.6), 0.6)
        self.assertEqual(droop_action(1.1, gain=10, bound=0.6), -0.6)
        self.assertEqual(droop_action(1.0, gain=10, bound=0.6), 0.0)


class PowerGymHelperTests(unittest.TestCase):
    def test_discrete_idle_preserves_settings_and_uses_battery_index_16(self):
        action = idle_action([1, 0], [32, 12], battery_count=2)
        self.assertEqual(action, (1, 0, 32, 12, 16, 16))
        self.assertEqual(
            validate_powergym_actions(
                action, capacitor_count=2, regulator_count=2, battery_count=2
            ),
            action,
        )

    def test_continuous_idle_and_bounds(self):
        self.assertEqual(
            idle_action([1], [32], battery_count=1, continuous_batteries=True), (1, 32, 0.0)
        )
        self.assertEqual(
            validate_powergym_actions(
                [0, 4, -0.75],
                capacitor_count=1,
                regulator_count=1,
                battery_count=1,
                continuous_batteries=True,
            ),
            (0, 4, -0.75),
        )

    def test_discrete_rejects_float_bool_range_nonfinite_and_mixed_shape(self):
        for action in (
            [0, 1],
            [True, 1, 16],
            [0.0, 1, 16],
            [0, 1, 16.0],
            [0, 33, 16],
            [2, 1, 16],
            [0, 1, -1],
            [0, 1, math.inf],
            [[0], 1, 16],
        ):
            with self.subTest(action=action), self.assertRaises(ValueError):
                validate_powergym_actions(
                    action, capacitor_count=1, regulator_count=1, battery_count=1
                )

    def test_continuous_rejects_bool_nonfinite_and_out_of_range(self):
        for battery in (True, math.nan, math.inf, 1.01, -1.01):
            with self.subTest(battery=battery), self.assertRaises(ValueError):
                validate_powergym_actions(
                    [battery],
                    capacitor_count=0,
                    regulator_count=0,
                    battery_count=1,
                    continuous_batteries=True,
                )

    def test_terminal_soc_tolerance_and_domain(self):
        self.assertTrue(terminal_soc_valid([0.5, 1.0], [0.51, 0.99], tolerance=0.01))
        self.assertFalse(terminal_soc_valid([0.5], [0.48], tolerance=0.01))
        self.assertTrue(terminal_soc_valid([], [], tolerance=0))
        for initial, final, tolerance in (
            ([0.5], [1.01], 0.1),
            ([True], [1], 0.1),
            ([0.5], [], 0.1),
            ([0.5], [0.5], -0.1),
            ([0.5], [0.5], math.nan),
        ):
            with self.subTest(initial=initial, final=final), self.assertRaises(ValueError):
                terminal_soc_valid(initial, final, tolerance=tolerance)

    def test_active_loss_is_energy_not_native_loss_ratio(self):
        self.assertEqual(active_loss_kwh([10, 20], step_hours=0.5), 15.0)


if __name__ == "__main__":
    unittest.main()
