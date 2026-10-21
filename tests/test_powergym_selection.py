"""Selection pools are frozen before scores, with independent stress results."""

import hashlib
import importlib.util
import io
import json
import math
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools/distribution_selection/powergym_selection.py"
sys.path.insert(0, str(TOOL.parent))
SPEC = importlib.util.spec_from_file_location("powergym_selection", TOOL)
selection = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(selection)

from powergym_baselines.controllers import coordinated_voltage, hysteresis, idle  # noqa: E402


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def source(self):
        source = self.root / "source"
        files = {}
        for network, model in selection.MODELS.items():
            folder = source / "systems" / network
            (folder / "loadshape").mkdir(parents=True)
            (folder / model).write_text("New Load.a kW=10 kvar=2\n")
            (folder / "Battery.csv").write_text(
                "name,max_kw,pf,max_kwh,initial_kwh\nbatt1,10,.95,100,100\n"
            )
            (folder / "loadshape/LoadShape1.CSV").write_text("1\n" * (24 * 11))
        (source / "LICENSE").write_text("fixture license\n")
        for path in source.rglob("*"):
            if path.is_file():
                files[str(path.relative_to(source))] = hashlib.sha256(path.read_bytes()).hexdigest()
        (source / "source-receipt.json").write_text(
            json.dumps({"source_commit": selection.COMMIT, "files": files})
        )
        return source

    def test_equispaced_indices_include_endpoints_and_deduplicate(self):
        self.assertEqual(selection.equispaced_indices(20), [0, 3, 7, 11, 15, 19])
        self.assertEqual(selection.equispaced_indices(3), [0, 1, 2])
        self.assertEqual(selection.equispaced_indices(1), [0])
        with self.assertRaises(ValueError):
            selection.equispaced_indices(0)

    def test_pool_is_deterministic_and_stress_is_separate(self):
        source = self.source()
        first = selection.freeze_pool(source, self.root / "a")
        second = selection.freeze_pool(source, self.root / "b")
        self.assertEqual(first, second)
        self.assertEqual(len(first["cases"]), 18)
        stress = [case for case in first["cases"] if case["group"] == "stress"]
        self.assertEqual(len(stress), 6)
        self.assertTrue(all(case["network"] == "123Bus" for case in stress))
        self.assertTrue(all(case["scale"] == 2.5 for case in stress))
        standard = first["cases"][0]
        case = json.loads((self.root / "a" / standard["path"]).read_text())
        self.assertEqual(case["multipliers"], [[1.0] * 24])
        self.assertEqual(case["terminal_energy_tolerance_kwh"], 1.0)
        selection.verify_pool(self.root / "a")
        with self.assertRaises(FileExistsError):
            selection.freeze_pool(source, self.root / "a")
        (self.root / "a" / standard["path"]).write_text("{}")
        with self.assertRaises(ValueError):
            selection.verify_pool(self.root / "a")

    def test_source_mutation_is_rejected_before_pool_creation(self):
        source = self.source()
        (source / "systems/34Bus/Battery.csv").write_text("changed")
        destination = self.root / "pool"
        with self.assertRaises(ValueError):
            selection.freeze_pool(source, destination)
        self.assertFalse(destination.exists())

    def test_durable_cli_receipt_can_resume_and_detects_result_mutation(self):
        source, output = self.source(), self.root / "execution"
        arguments = [
            str(TOOL),
            "--source-dir",
            str(source),
            "--output",
            str(output),
            "--case-ids",
            "34Bus-standard-p000-s1",
            "--baselines",
            "hold_idle",
        ]
        fake = {
            "case_id": "34Bus-standard-p000-s1",
            "baseline": "hold_idle",
            "canary_quality": 0.5,
            "valid": True,
            "completed_steps": 24,
            "trajectory": [],
        }
        with (
            patch.object(sys, "argv", arguments),
            patch.object(selection, "run_case", return_value=fake) as evaluate,
            patch("importlib.metadata.version", return_value="fixture"),
            redirect_stdout(io.StringIO()),
        ):
            selection.main()
            self.assertEqual(evaluate.call_count, 1)
        result = output / "results/34Bus-standard-p000-s1--hold_idle.json"
        original = result.read_bytes()
        with (
            patch.object(sys, "argv", arguments + ["--resume"]),
            patch.object(
                selection, "run_case", side_effect=AssertionError("resume repeated solved case")
            ),
            patch("importlib.metadata.version", return_value="fixture"),
            redirect_stdout(io.StringIO()),
        ):
            selection.main()
            self.assertEqual(result.read_bytes(), original)
            result.write_text("{}")
            with self.assertRaises(ValueError):
                selection.main()

    def test_baselines_do_not_mutate_observation_or_drain_battery(self):
        observation = {
            "capacitor_states": [1, 1],
            "regulator_taps": [32] * 6,
            "battery_soc": [1.0, 1.0],
            "bus_voltages": {"a": [1.15, 1.13, 1.14]},
        }
        before = json.dumps(observation, sort_keys=True)
        self.assertEqual(idle(observation), [1, 1] + [32] * 6 + [16, 16])
        self.assertEqual(hysteresis(observation), [1, 1] + [31] * 6 + [16, 16])
        improved = coordinated_voltage(observation)
        self.assertTrue(all(value < 31 for value in improved[2:8]))
        self.assertEqual(improved[-2:], [16, 16])
        self.assertEqual(json.dumps(observation, sort_keys=True), before)

    def test_quality_requires_complete_episode_and_energy_neutrality(self):
        rows = [
            {
                "active_loss_kw": 10.0,
                "voltage_violation_pu_hours": 0.1,
                "compliant_phases": 2,
                "phases": 3,
                "all_phases_compliant": False,
                "min_voltage_pu": 0.94,
                "max_voltage_pu": 1.0,
            }
        ] * 24
        result = selection.summarize(
            rows,
            initial_energy=[100.0],
            final_energy=[98.0],
            cap_switches=1,
            tap_moves=2,
            step_hours=1.0,
            tolerance_kwh=1.0,
        )
        self.assertFalse(result["valid"])
        self.assertEqual(result["canary_quality"], 0.0)
        self.assertAlmostEqual(result["active_loss_kwh"], 240)
        self.assertAlmostEqual(result["phase_time_compliance"], 2 / 3)
        valid = selection.summarize(
            rows,
            initial_energy=[100.0],
            final_energy=[99.0],
            cap_switches=1,
            tap_moves=2,
            step_hours=1.0,
            tolerance_kwh=1.0,
        )
        self.assertTrue(valid["valid"])
        self.assertAlmostEqual(valid["canary_quality"], 1 / (1 + 2.4 + 0.24 + 3 / 33))
        incomplete = selection.summarize(
            rows[:-1],
            initial_energy=[100.0],
            final_energy=[100.0],
            cap_switches=0,
            tap_moves=0,
            step_hours=1.0,
            tolerance_kwh=1.0,
        )
        self.assertFalse(incomplete["valid"])


@unittest.skipUnless(
    importlib.util.find_spec("dss") and (ROOT / "work/distribution/powergym-verified").is_dir(),
    "requires verified local PowerGym sources and the DSS runtime",
)
class SimulationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.directory = Path(cls.temporary.name) / "pool"
        cls.pool = selection.freeze_pool(
            ROOT / "work/distribution/powergym-verified", cls.directory
        )

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def case(self, case_id="34Bus-standard-p000-s1"):
        item = next(item for item in self.pool["cases"] if item["id"] == case_id)
        return json.loads((self.directory / item["path"]).read_text())

    def test_matches_historical_canary_hold_and_hysteresis(self):
        reference = json.loads(
            (
                ROOT / "task-packages/powergym-volt-var-control-canary-v1/verification"
                "/local-numerical-receipt.json"
            ).read_text()
        )
        for name, historical in (("hold_idle", "hold_idle"), ("canary_hysteresis", "starter")):
            result = selection.run_case(
                self.case(), self.directory / "assets/34Bus", name, search_passes=1
            )
            self.assertTrue(result["valid"])
            self.assertEqual(result["completed_steps"], 24)
            self.assertEqual(result["pf_calls"], 25)
            for actual, expected in (
                ("canary_quality", "reward"),
                ("active_loss_kwh", "active_loss_kwh"),
                ("voltage_violation_pu_hours", "voltage_violation_pu_hours"),
            ):
                self.assertTrue(
                    math.isclose(
                        result[actual],
                        reference[historical][expected],
                        rel_tol=1e-10,
                        abs_tol=1e-10,
                    )
                )

    def test_preview_preserves_energy_counters_observation_and_current_step(self):
        from powergym_baselines.backend import SnapshotBackend
        from powergym_baselines.controllers import snapshot_search

        backend = SnapshotBackend(self.case(), self.directory / "assets/34Bus")
        before = backend.observation()
        energy = list(backend.energy)
        action = snapshot_search(backend, passes=1)
        self.assertEqual(action[-2:], [16, 16])
        self.assertEqual(backend.observation(), before)
        self.assertEqual(backend.energy, energy)
        self.assertEqual((backend.step, backend.cap_switches, backend.tap_moves), (0, 0, 0))
        self.assertGreater(backend.pf_calls, 1)
        row = backend.advance(action)
        self.assertEqual(row["step"], 0)
        self.assertEqual(backend.step, 1)
        self.assertEqual(backend.energy, energy)
        for invalid in ([True, 1] + [16] * 8, [1, 1] + [33] * 8, [1, 1]):
            with self.assertRaises(ValueError):
                backend.preview(invalid)

    def test_123bus_and_stress_keep_separate_assets_and_full_energy(self):
        standard = self.case("123Bus-standard-p000-s1")
        stress = self.case("123Bus-stress-p000-s2.5")
        self.assertEqual(len(standard["load_names"]), 91)
        self.assertTrue(
            all(
                a * 2.5 == b
                for left, right in zip(standard["multipliers"], stress["multipliers"])
                for a, b in zip(left, right)
            )
        )
        for case in (standard, stress):
            result = selection.run_case(
                case, self.directory / "assets/123Bus", "hold_idle", search_passes=1
            )
            self.assertTrue(result["valid"])
            self.assertEqual(result["final_soc"], [1.0] * 4)
            self.assertEqual(result["completed_steps"], 24)
        selection.verify_pool(self.directory)

    def test_drained_battery_is_invalid_after_all_24_steps(self):
        from powergym_baselines.backend import SnapshotBackend

        backend = SnapshotBackend(self.case(), self.directory / "assets/34Bus")
        rows = [backend.advance([1, 1] + [32] * 6 + [32, 32]) for _ in range(24)]
        result = selection.summarize(
            rows,
            initial_energy=backend.initial_energy,
            final_energy=backend.energy,
            cap_switches=backend.cap_switches,
            tap_moves=backend.tap_moves,
            step_hours=1.0,
            tolerance_kwh=1.0,
        )
        self.assertEqual(result["completed_steps"], 24)
        self.assertFalse(result["valid"])
        self.assertEqual(result["canary_quality"], 0.0)
        self.assertEqual(result["error"], "terminal_energy_violation")


if __name__ == "__main__":
    unittest.main()
