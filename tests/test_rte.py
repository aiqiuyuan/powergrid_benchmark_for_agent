import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from powergrid_bench.artifacts import ArtifactStore
from powergrid_bench.rte import RTEAdapter, RTEAdapterError, feedback_payload


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class RTENativeAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.support = self.root / "support"
        (self.support / "vendor").mkdir(parents=True)
        checker = self.support / "vendor" / "RTE_ChallengeROADEF2020_checker.py"
        checker.write_text("# fixture checker, never an official contest result\n")
        lock = self.support / "source-lock.json"
        lock.write_text(json.dumps({"files": {checker.name: {"sha256": digest(checker)}}}))
        self.module = self.support / "external.py"
        self.module.write_text(
            "import json\n"
            "def check_solution(instance, solution, support):\n"
            "    expected = json.loads(instance.read_text())['expected']\n"
            "    text = solution.read_text()\n"
            "    return {'valid': text == expected, 'objective': 7.0, 'error': ''}\n"
        )
        self.candidate = self.root / "candidate"
        self.candidate.mkdir()
        (self.candidate / "candidate.json").write_text(
            json.dumps(
                {
                    "kind": "algorithm",
                    "task_id": "rte-maintenance",
                    "source": ["solver.py"],
                    "dependency_lock": "requirements.lock",
                    "entrypoint": [
                        "python3",
                        "solver.py",
                        "--instance",
                        "{input}",
                        "--output",
                        "{output}",
                    ],
                }
            )
        )
        (self.candidate / "requirements.lock").write_text("# stdlib fixture\n")
        (self.candidate / "solver.py").write_text(
            "import argparse,json\nfrom pathlib import Path\n"
            "p=argparse.ArgumentParser()\n"
            "p.add_argument('--instance');p.add_argument('--output')\n"
            "p.add_argument('--time-limit');p.add_argument('--seed')\n"
            "a=p.parse_args()\n"
            "Path(a.output).write_text(json.loads(Path(a.instance).read_text())['expected'])\n"
        )
        self.store = ArtifactStore(self.root / "artifacts")
        self.snapshot = self.store.snapshot(self.candidate)
        self.data = self.root / "data"
        self.data.mkdir()
        self.instance = self.data / "case.json"
        self.instance.write_text(json.dumps({"expected": "job 1\n"}))
        self.panel = self.root / "panel.json"
        self.panel.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "task_id": "rte-maintenance",
                    "protocol": "unit-test-only",
                    "split": "public-selection",
                    "seconds_per_case": 2,
                    "seed": 4,
                    "cases": [
                        {"id": "fixture", "path": "case.json", "sha256": digest(self.instance)}
                    ],
                }
            )
        )
        self.adapter = RTEAdapter(
            self.store,
            official_module=self.module,
            official_module_sha256=digest(self.module),
            support_root=self.support,
            source_lock_sha256=digest(lock),
            checker_sha256=digest(checker),
            work_root=self.root / "runs",
        )

    def tearDown(self):
        self.temp.cleanup()

    def evaluate(self, **kwargs):
        return self.adapter.evaluate(
            self.snapshot.digest,
            self.panel,
            panel_sha256=digest(self.panel),
            data_root=self.data,
            **kwargs,
        )

    def test_executes_algorithm_and_uses_independent_objective(self):
        result = self.evaluate(trusted_local=True)
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["score"], 7.0)
        self.assertTrue(result["feasible"])
        self.assertEqual(result["selection_direction"], "lower")
        self.assertTrue(result["algorithm_executed"])
        self.assertEqual(result["cases"][0]["instance_sha256"], digest(self.instance))

    def test_untrusted_local_requires_certified_backend(self):
        with self.assertRaises(RTEAdapterError):
            self.evaluate()

    def test_declared_entrypoint_must_match_the_executed_native_solver(self):
        manifest_path = self.candidate / "candidate.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["entrypoint"] = ["python3", "main.py", "{input}", "{output}"]
        manifest["source"].append("main.py")
        manifest_path.write_text(json.dumps(manifest))
        (self.candidate / "main.py").write_text("raise RuntimeError('different algorithm')\n")
        self.snapshot = self.store.snapshot(self.candidate)
        with self.assertRaisesRegex(RTEAdapterError, "declared native"):
            self.evaluate(trusted_local=True)

    def test_multifile_solver_keeps_its_frozen_module_dependencies(self):
        manifest = json.loads((self.candidate / "candidate.json").read_text())
        manifest["source"].append("helper.py")
        (self.candidate / "candidate.json").write_text(json.dumps(manifest))
        (self.candidate / "helper.py").write_text("SCHEDULE='job 1\\n'\n")
        (self.candidate / "solver.py").write_text(
            "import sys\nfrom pathlib import Path\nfrom helper import SCHEDULE\n"
            "Path(sys.argv[sys.argv.index('--output')+1]).write_text(SCHEDULE)\n"
        )
        self.snapshot = self.store.snapshot(self.candidate)
        result = self.evaluate(trusted_local=True)
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["score"], 7.0)

    def test_pinned_panel_prevents_changed_instances(self):
        self.instance.write_text("{}")
        with self.assertRaises(RTEAdapterError):
            self.evaluate(trusted_local=True)

    def test_pinned_checker_prevents_modified_scoring(self):
        (self.support / "vendor" / "RTE_ChallengeROADEF2020_checker.py").write_text("changed")
        with self.assertRaises(RTEAdapterError):
            self.evaluate(trusted_local=True)

    def test_rejects_escape_from_dataset_root(self):
        panel = json.loads(self.panel.read_text())
        panel["cases"][0]["path"] = "../outside.json"
        self.panel.write_text(json.dumps(panel))
        with self.assertRaises(RTEAdapterError):
            self.evaluate(trusted_local=True)

    def test_invalid_native_schedule_is_candidate_error(self):
        (self.candidate / "solver.py").write_text(
            "import sys\nfrom pathlib import Path\n"
            "Path(sys.argv[sys.argv.index('--output')+1]).write_text('bad schedule')\n"
        )
        self.snapshot = self.store.snapshot(self.candidate)
        result = self.evaluate(trusted_local=True)
        self.assertEqual(result["status"], "candidate_error")
        self.assertFalse(result["feasible"])
        self.assertIsNone(result["raw_objective"])

    def test_checker_failure_is_retryable_infrastructure_error(self):
        self.module.write_text("def check_solution(*args):\n    raise RuntimeError('failed')\n")
        self.adapter.official_module_sha256 = digest(self.module)
        result = self.evaluate(trusted_local=True)
        self.assertEqual(result["status"], "infrastructure_error")
        self.assertFalse(result["feasible"])

    def test_native_process_timeout_is_countable_candidate_timeout(self):
        (self.candidate / "solver.py").write_text("import time\ntime.sleep(5)\n")
        self.snapshot = self.store.snapshot(self.candidate)
        panel = json.loads(self.panel.read_text())
        panel["seconds_per_case"] = 0.05
        self.panel.write_text(json.dumps(panel))
        result = self.evaluate(trusted_local=True)
        self.assertEqual(result["status"], "timeout")
        self.assertFalse(result["feasible"])

    def test_feedback_projection_excludes_candidate_controlled_private_strings(self):
        result = self.evaluate(trusted_local=True)
        result["cases"][0]["stderr"] = "private instance encoded by candidate"
        projected = feedback_payload(result)
        self.assertEqual(
            set(projected), {"schema_version", "status", "feasible", "score", "raw_objective"}
        )
        self.assertNotIn("private instance", json.dumps(projected))

    def test_feedback_projection_rejects_inconsistent_feasibility(self):
        with self.assertRaises(RTEAdapterError):
            feedback_payload(
                {"status": "succeeded", "feasible": False, "score": 0, "raw_objective": None}
            )


if __name__ == "__main__":
    unittest.main()
