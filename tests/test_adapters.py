"""The algorithm ABI executes fresh inputs and uses an independent checker."""

import json
import os
import tempfile
import unittest
from pathlib import Path

from powergrid_bench.adapters import AdapterError, execute_algorithm, validate_candidate
from powergrid_bench.artifacts import ArtifactStore


def write_algorithm(root: Path, body: str | None = None) -> None:
    root.mkdir()
    (root / "main.py").write_text(
        body
        or (
            "import argparse,json\n"
            "p=argparse.ArgumentParser();p.add_argument('--request');p.add_argument('--output')\n"
            "a=p.parse_args();r=json.load(open(a.request))\n"
            "json.dump({'answer':r['value']*2,'score':999999},open(a.output,'w'))\n"
        )
    )
    (root / "dependency-lock.json").write_text('{"runtime":"python-stdlib"}')
    (root / "candidate.json").write_text(
        json.dumps(
            {
                "kind": "algorithm",
                "task_id": "fixture-only",
                "source": ["main.py"],
                "dependency_lock": "dependency-lock.json",
                "entrypoint": [
                    "python3",
                    "main.py",
                    "--request",
                    "{input}",
                    "--output",
                    "{output}",
                ],
            }
        )
    )


def independent_checker(request: dict, output: dict) -> dict:
    feasible = output.get("answer") == request["value"] * 2
    return {"feasible": feasible, "score": 1.0 if feasible else 0.0}


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "candidate"
        write_algorithm(self.source)
        self.store = ArtifactStore(self.root / "store")
        self.snapshot = self.store.snapshot(self.source)

    def run_candidate(self, request, **kwargs):
        return execute_algorithm(
            self.store,
            self.snapshot.digest,
            request,
            task_id="fixture-only",
            checker=independent_checker,
            work_root=self.root / "work",
            timeout_seconds=5,
            trusted_local=True,
            **kwargs,
        )

    def test_algorithm_runs_new_inputs_and_cannot_self_award_score(self):
        for value in (3, 17):
            result = self.run_candidate({"value": value})
            self.assertEqual(result.status, "succeeded")
            self.assertEqual(result.checker["score"], 1.0)
            self.assertEqual(result.output["answer"], value * 2)
        self.store.verify(self.snapshot.digest)

    def test_static_submission_and_wrong_task_rejected(self):
        manifest = json.loads((self.source / "candidate.json").read_text())
        manifest["kind"] = "static-output"
        (self.source / "candidate.json").write_text(json.dumps(manifest))
        with self.assertRaises(AdapterError):
            validate_candidate(self.source, "fixture-only")
        with self.assertRaises(AdapterError):
            validate_candidate(self.snapshot.path, "unit-commitment")

    def test_missing_sources_and_path_escape_rejected(self):
        manifest = json.loads((self.source / "candidate.json").read_text())
        for path in ("missing.py", "../outside.py", "/etc/passwd"):
            manifest["source"] = [path]
            (self.source / "candidate.json").write_text(json.dumps(manifest))
            with self.assertRaises(AdapterError):
                validate_candidate(self.source, "fixture-only")

    def test_request_rejects_private_final_labels(self):
        with self.assertRaises(AdapterError):
            self.run_candidate({"value": 3, "metadata": {"final_labels": [6]}})

    def test_execution_requires_explicit_trusted_local_scope(self):
        with self.assertRaises(AdapterError):
            execute_algorithm(
                self.store,
                self.snapshot.digest,
                {"value": 3},
                task_id="fixture-only",
                checker=independent_checker,
                work_root=self.root / "work",
                timeout_seconds=5,
            )

    def test_checker_failure_is_infrastructure_failure(self):
        def broken_checker(request, output):
            raise RuntimeError("checker unavailable")

        result = execute_algorithm(
            self.store,
            self.snapshot.digest,
            {"value": 3},
            task_id="fixture-only",
            checker=broken_checker,
            work_root=self.root / "work",
            timeout_seconds=5,
            trusted_local=True,
        )
        self.assertEqual(result.status, "infrastructure_error")

    def test_candidate_that_produces_no_response_fails(self):
        (self.source / "main.py").write_text("pass\n")
        self.snapshot = self.store.snapshot(self.source)
        self.assertEqual(self.run_candidate({"value": 3}).status, "candidate_error")

    def test_input_and_output_placeholders_are_mandatory(self):
        manifest = json.loads((self.source / "candidate.json").read_text())
        manifest["entrypoint"] = ["python3", "main.py"]
        (self.source / "candidate.json").write_text(json.dumps(manifest))
        with self.assertRaises(AdapterError):
            validate_candidate(self.source, "fixture-only")

    def test_relative_work_directory_resolves_before_candidate_cwd_changes(self):
        relative = os.path.relpath(self.root / "relative-work", Path.cwd())
        result = execute_algorithm(
            self.store,
            self.snapshot.digest,
            {"value": 3},
            task_id="fixture-only",
            checker=independent_checker,
            work_root=relative,
            timeout_seconds=5,
            trusted_local=True,
        )
        self.assertEqual(result.status, "succeeded")
