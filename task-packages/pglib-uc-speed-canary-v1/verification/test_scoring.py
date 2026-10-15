"""Boundary cases for reference-quality timing and feasibility qualification."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "support"))
from scoring import ReferenceError, aggregate, replay


class ScoringTests(unittest.TestCase):
    def run_score(self, snapshots, status="OK"):
        return replay(snapshots, status=status, seconds=300, upper=100, lower=100, epsilon=0.001)

    def test_conservative_cost_boundary(self):
        self.assertFalse(self.run_score([(10, 100.1)])["target_hit"])
        self.assertTrue(self.run_score([(10, 100.09)])["target_hit"])

    def test_first_hit_and_best_cost_are_separate(self):
        row = self.run_score([(1, 110), (30, 100.05), (50, 100)])
        self.assertEqual(row["penalized_seconds"], 30)
        self.assertEqual(row["reference_gap"], 0)

    def test_post_deadline_output_cannot_win(self):
        row = self.run_score([(300.00001, 100)])
        self.assertFalse(row["feasible"])
        self.assertEqual(row["penalized_seconds"], 600)

    def test_deadline_incumbent_qualifies_but_crash_does_not(self):
        self.assertTrue(self.run_score([(30, 100)], "DEADLINE")["feasible"])
        failed = self.run_score([(30, 100)], "CRASH")
        self.assertFalse(failed["feasible"])
        self.assertEqual(failed["penalized_seconds"], 600)

    def test_material_bound_inconsistency_is_not_candidate_failure(self):
        with self.assertRaises(ReferenceError):
            self.run_score([(10, 90)])

    def test_par2_keeps_miss_in_denominator(self):
        rows = [
            self.run_score([(30, 100)]),
            self.run_score([(150, 100)]),
            self.run_score([(20, 110)]),
        ]
        result = aggregate(rows, 300)
        self.assertTrue(result["feasible"])
        self.assertEqual(result["penalized_seconds"], 260)
        self.assertAlmostEqual(result["reward"], 0.5666666666666667)

    def test_any_failed_replay_removes_qualification(self):
        result = aggregate([self.run_score([(10, 100)]), self.run_score([])], 300)
        self.assertFalse(result["feasible"])
        self.assertEqual(result["reward"], 0)
        self.assertIsNone(result["reference_gap"])

    def test_feedback_has_only_declared_fields(self):
        result = aggregate([self.run_score([(10.123456, 100)])], 300)
        self.assertEqual(
            set(result),
            {
                "status",
                "feasible",
                "target_hit",
                "penalized_seconds",
                "reference_gap",
                "reward",
                "failure_category",
            },
        )
        self.assertEqual(result["penalized_seconds"], 10.123)
        self.assertEqual(result["reward"], 1 - 10.123 / 600)

    def test_terminal_preserves_precision(self):
        rows = [self.run_score([(10.123456789, 100)])]
        result = aggregate(rows, 300, delivered=False)
        self.assertEqual(result["penalized_seconds"], 10.123456789)
        self.assertEqual(result["reward"], 1 - 10.123456789 / 600)


if __name__ == "__main__":
    unittest.main()
