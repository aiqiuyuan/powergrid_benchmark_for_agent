"""Test settlement decisions independently of the model implementation."""
import importlib.util
from pathlib import Path
import unittest

import numpy as np

PATH = Path(__file__).parents[1] / "heftcom_models.py"
spec = importlib.util.spec_from_file_location("heft_models", PATH)
models = importlib.util.module_from_spec(spec)
spec.loader.exec_module(models)


class DecisionTests(unittest.TestCase):
    def test_expected_decision_maximizes_finite_distribution_revenue(self):
        generation = np.array([100., 400., 800.])
        spread = np.array([-20., 0., 35.])  # day-ahead minus imbalance
        weights = np.array([.2, .5, .3])
        bid = models.expected_bid(weights @ generation, weights @ spread)
        grid = np.linspace(0., 1800., 18001)
        revenue = (grid[:, None] * spread + .14 * grid[:, None] * generation
                   - .07 * grid[:, None] ** 2) @ weights
        self.assertLessEqual(abs(bid - grid[np.argmax(revenue)]), .051)

    def test_bounds_and_spread_sign(self):
        np.testing.assert_allclose(models.expected_bid([100, 100, 100], [-1000, 0, 1000]),
                                   [0, 100, 1800])

    def test_timestamp_alignment_is_required(self):
        with self.assertRaises(ValueError):
            models.check_alignment([{"timestamp": "a"}], [{"timestamp": "b"}])

    def test_quantile_mean_uses_fixed_midpoint_grid(self):
        # Five equally spaced midpoint quantiles integrate a uniform distribution exactly.
        values = np.array([[10, 30, 50, 70, 90], [20, 60, 100, 140, 180.]])
        np.testing.assert_allclose(models.quantile_mean(values), [50, 100])


if __name__ == "__main__":
    unittest.main()
