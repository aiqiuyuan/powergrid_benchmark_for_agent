"""Formal fixed-case MAPDN score, provenance and local-controller contracts."""

from __future__ import annotations

import importlib.util
import json
import math
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
PACKAGE = REPO / "task-packages/mapdn-voltage-control-formal-v1"
POOL = REPO / "work/distribution-selection-20261016/mapdn33-final"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FormalContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(PACKAGE / "support"))
        cls.contract = load("mapdn_formal_contract_test", PACKAGE / "support/mapdn_contract.py")
        cls.freezer = load("mapdn_formal_freezer_test", PACKAGE / "freeze_case.py")
        cls.controller = load(
            "mapdn_formal_starter_test", PACKAGE / "environment/app/submission/controller.py"
        )

    def test_safety_has_strict_priority_and_incomplete_scores_zero(self):
        score = self.contract.quality
        unsafe = score(valid=True, compliant_points=15839, loss_mwh=0)
        safe = score(valid=True, compliant_points=15840, loss_mwh=1e100)
        self.assertLess(unsafe, 0.5)
        self.assertGreaterEqual(safe, 0.5)
        self.assertGreater(score(valid=True, compliant_points=15840, loss_mwh=1), safe)
        self.assertEqual(score(valid=False, compliant_points=15840, loss_mwh=0), 0)

    def test_score_rejects_nonphysical_or_wrong_denominator(self):
        for points, loss in (
            (15841, 1),
            (-1, 1),
            (True, 1),
            (1.5, 1),
            (15840, -1),
            (15840, math.nan),
            (15840, math.inf),
        ):
            with self.subTest(points=points, loss=loss), self.assertRaises(ValueError):
                self.contract.quality(valid=True, compliant_points=points, loss_mwh=loss)

    def test_manifest_is_immutable_and_date_is_explicit(self):
        manifest = self.contract.expected_manifest()
        self.assertEqual(manifest["case_id"], "mapdn33-2012-02-03")
        self.assertEqual(manifest["first_timestamp"], "2012-02-03T00:00:00")
        self.assertEqual(manifest["last_timestamp"], "2012-02-03T23:57:00")
        manifest["apparent_power_mva"][0] = 100
        self.assertNotEqual(manifest, self.contract.expected_manifest())
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "manifest.json").write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "manifest"):
                self.contract.validate_case(root)

    def test_starter_matches_frozen_qualified_rule_and_only_uses_local_fields(self):
        qualified = load(
            "mapdn_qualified_comparison",
            REPO / "tools/distribution_qualification/mapdn_controllers.py",
        )
        metadata = {"action_bound": 0.8, "apparent_power_mva": [2.0]}
        starter = self.controller.Controller(metadata)
        reference = qualified.MemoryController(
            metadata, {"name": "one_step_relaxed", "relaxation": 0.1}
        )
        for voltage, active, reactive in (
            (0.9, 0.2, 0),
            (0.95, 0.5, 0.3),
            (1.0, 1, -0.7),
            (1.1, 1.9, 0.1),
            (1, 2, 0),
        ):
            obs = {
                "pv_voltage_pu": [voltage],
                "pv_active_mw": [active],
                "pv_reactive_mvar": [reactive],
            }
            self.assertEqual(starter.act(obs), reference.act(obs))

    def test_free_check_is_synthetic_and_public_image_excludes_target(self):
        result = subprocess.run(
            [sys.executable, str(PACKAGE / "environment/app/check_interface.py")],
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertIn("no target score", result.stdout)
        self.assertFalse(list((PACKAGE / "environment").rglob("model.p")))
        self.assertFalse(list((PACKAGE / "environment").rglob("trajectory.json")))
        docker = (PACKAGE / "environment/Dockerfile").read_text()
        self.assertIn("COPY app/ /app/", docker)
        self.assertNotIn("COPY .", docker)
        self.assertEqual(
            (PACKAGE / "images/actor_worker.py").read_bytes(),
            (PACKAGE / "support/actor_worker.py").read_bytes(),
        )

    @unittest.skipUnless((POOL / "pool.json").exists(), "private frozen pool is absent")
    def test_freeze_exact_selected_case_reuses_verified_bytes_and_rejects_tampering(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "case"
            self.freezer.freeze_pool(POOL, output)
            manifest = self.contract.validate_case(output)
            self.assertEqual(manifest, self.contract.expected_manifest())
            self.assertEqual(
                (output / "trajectory.json").read_bytes(),
                (POOL / "cases/mapdn33-2012-02-03/trajectory.json").read_bytes(),
            )
            with self.assertRaisesRegex(ValueError, "replace"):
                self.freezer.freeze_pool(POOL, output)
            with (output / "trajectory.json").open("ab") as stream:
                stream.write(b" ")
            with self.assertRaisesRegex(ValueError, "checksum"):
                self.contract.validate_case(output)

    def test_mismatched_pool_rejected_before_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "pool.json").write_text("{}")
            with self.assertRaisesRegex(ValueError, "pool"):
                self.freezer.freeze_pool(root, root / "case")
            self.assertFalse((root / "case").exists())


HAS_PP = importlib.util.find_spec("pandapower") is not None


@unittest.skipUnless(HAS_PP, "optional numerical MAPDN runtime is absent")
class FormalBackendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(PACKAGE / "support"))
        cls.runner = load("mapdn_formal_runner_test", PACKAGE / "support/runner.py")

    def test_action_validation_and_actor_histories_are_independent(self):
        for invalid in ([True], [math.nan], [0.81], [], [0, 0]):
            with self.assertRaises(self.runner.CandidateError):
                self.runner.validate_action(invalid, 0.8)
        code = (
            b"class Controller:\n def __init__(self, metadata): self.n=0\n"
            b" def act(self, observation):\n  self.n+=1\n  return [self.n/100]\n"
        )
        with tempfile.TemporaryDirectory() as temporary:
            actors = []
            try:
                for actor_id in range(2):
                    actors.append(
                        self.runner.Actor(
                            code, {"actor_id": actor_id}, Path(temporary), secure=False
                        )
                    )
                self.assertEqual(actors[0].exchange({"observation": {}})["action"], [0.01])
                self.assertEqual(actors[0].exchange({"observation": {}})["action"], [0.02])
                self.assertEqual(actors[1].exchange({"observation": {}})["action"], [0.01])
            finally:
                for actor in actors:
                    actor.close()

    def test_real_active_loss_requires_energy_balance_and_does_not_use_q_proxy(self):
        from types import SimpleNamespace

        import pandas as pd

        net = SimpleNamespace(
            res_bus=pd.DataFrame({"vm_pu": [1, 1]}),
            res_line=pd.DataFrame({"pl_mw": [0.1]}),
            res_ext_grid=pd.DataFrame({"p_mw": [1.1]}),
            res_sgen=pd.DataFrame({"p_mw": [0], "q_mvar": [999]}),
            res_load=pd.DataFrame({"p_mw": [1]}),
        )
        manifest = {
            "voltage_bounds_pu": [0.95, 1.05],
            "voltage_tolerance_pu": 1e-9,
            "power_balance_tolerance_mw": 1e-7,
        }
        measured = self.runner.measure(net, manifest)
        self.assertEqual(measured["actual_loss_mw"], 0.1)
        net.res_line.loc[0, "pl_mw"] = 0.2
        with self.assertRaisesRegex(RuntimeError, "balance"):
            self.runner.measure(net, manifest)

    @unittest.skipUnless((POOL / "pool.json").exists(), "private frozen pool is absent")
    def test_full_day_matches_qualified_strong_local_reference(self):
        freezer = load("mapdn_formal_full_day_freezer", PACKAGE / "freeze_case.py")
        with tempfile.TemporaryDirectory() as temporary:
            case = Path(temporary) / "case"
            freezer.freeze_pool(POOL, case)
            result = self.runner.evaluate(
                PACKAGE / "environment/app/submission/controller.py", case, secure=False
            )
        self.assertTrue(result["valid"], result["error"])
        self.assertEqual(result["completed_intervals"], 480)
        self.assertEqual(result["pf_calls"], 960)
        self.assertEqual(result["metrics"]["bus_time_compliance"], 1)
        self.assertAlmostEqual(result["metrics"]["actual_loss_mwh"], 1.8352510375191953, places=10)
        self.assertGreater(result["reward"], 0.5)
        self.assertFalse(result["secure_execution"])
        self.assertEqual(result["score_tier"], "voltage_feasible")

    def test_secure_evaluation_fails_closed_without_linux_acceptance(self):
        with patch.object(self.runner.sys, "platform", "darwin"):
            with self.assertRaisesRegex(RuntimeError, "Linux root"):
                self.runner.secure_readiness()


if __name__ == "__main__":
    unittest.main()
