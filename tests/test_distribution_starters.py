"""Public starters execute causal toy observations without a target simulator."""

import json
import subprocess
import sys
import unittest
from pathlib import Path

from powergrid_bench.distribution.mapdn import validate_actions as mapdn_actions
from powergrid_bench.distribution.powergym import validate_actions as powergym_actions

ROOT = Path(__file__).resolve().parents[1] / "task-packages"


class StarterTests(unittest.TestCase):
    def run_starter(self, task):
        path = ROOT / task / "environment/app/support/check_interface.py"
        result = subprocess.run(
            [sys.executable, str(path)], check=True, text=True, capture_output=True, timeout=10
        )
        return json.loads(result.stdout)

    def test_droop_responds_only_to_current_local_voltage(self):
        result = self.run_starter("mapdn-voltage-control")
        self.assertEqual(result["scope"], "synthetic-interface-only-no-target-case")
        self.assertGreater(result["actions"][0][0], 0)
        self.assertLess(result["actions"][0][1], 0)
        self.assertEqual(result["actions"][1][0], 0)
        for action in result["actions"]:
            mapdn_actions(action, expected_size=2, bound=0.8)

    def test_hold_starter_preserves_settings_and_uses_idle_batteries(self):
        result = self.run_starter("powergym-volt-var-control")
        self.assertEqual(result["actions"][0], [1, 1] + [32] * 6 + [16, 16])
        self.assertEqual(result["actions"][1], [0, 1, 16, 17, 18, 19, 20, 21, 16, 16])
        for action in result["actions"]:
            powergym_actions(action, capacitor_count=2, regulator_count=6, battery_count=2)
