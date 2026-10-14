import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from powergrid_bench.cli import main

ROOT = Path(__file__).resolve().parents[1]


class CliTests(unittest.TestCase):
    def invoke(self, argv):
        output = StringIO()
        with redirect_stdout(output):
            code = main(argv)
        return code, json.loads(output.getvalue())

    def test_draft_can_be_reviewed_but_not_executed(self):
        path = str(ROOT / "configs/experiment.template.json")
        code, report = self.invoke(["config-check", path])
        self.assertEqual(code, 0)
        self.assertFalse(report["executable"])
        code, _ = self.invoke(["config-check", path, "--require-complete"])
        self.assertNotEqual(code, 0)

    def test_fixture_runs_frozen_algorithm_through_recovered_final(self):
        with tempfile.TemporaryDirectory() as directory:
            code, report = self.invoke(
                ["fixture-run", "--work-dir", directory + "/run", "--trusted-local"]
            )
            self.assertEqual(code, 0)
            self.assertEqual(report["status"], "passed")
            self.assertFalse(report["production_certified"])
            self.assertEqual(report["feedback"]["counted"], 1)
            self.assertEqual(report["feedback"]["delivered"], 1)
            self.assertEqual(report["final_attempts"], 2)
            self.assertTrue(report["fresh_final_input_executed"])
            self.assertTrue(report["zero_feedback_verified"])
            self.assertTrue((Path(directory) / "run/report.json").is_file())

    def test_fixture_requires_trusted_scope_and_preserves_existing_run(self):
        with tempfile.TemporaryDirectory() as directory:
            code, _ = self.invoke(["fixture-run", "--work-dir", directory + "/run"])
            self.assertNotEqual(code, 0)
            root = Path(directory) / "existing"
            root.mkdir()
            (root / "keep.txt").write_text("keep")
            code, _ = self.invoke(["fixture-run", "--work-dir", str(root), "--trusted-local"])
            self.assertNotEqual(code, 0)
            self.assertEqual((root / "keep.txt").read_text(), "keep")

    def test_adapter_draft_does_not_pass_release_gate(self):
        path = ROOT / "manifests/task-adapters/unit-commitment.json"
        code, report = self.invoke(["adapter-check", str(path)])
        self.assertEqual(code, 0)
        self.assertFalse(report["release_ready"])
        code, _ = self.invoke(["adapter-check", str(path), "--require-certified"])
        self.assertNotEqual(code, 0)
