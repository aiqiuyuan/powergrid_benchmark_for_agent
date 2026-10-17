"""Portable aggregate feedback, frozen-artifact and synthetic preparation tests."""

from __future__ import annotations

import contextlib
import io
import json
import os
import runpy
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from helpers import (
    FEEDBACK_IDS,
    PUBLIC_IDS,
    PYTHON,
    TASK,
    digest,
    load_task_module,
    patch_modules,
    synthetic_manifest,
    tiny_instance,
)


class ABCX15PreparationTests(unittest.TestCase):
    def test_inventory_requires_exactly_sixty_unique_official_case_ids(self) -> None:
        prepare = load_task_module("prepare.py", "abc_x15_prepare")
        records = [{"id": case} for case in sorted(PUBLIC_IDS | FEEDBACK_IDS)]
        self.assertEqual(
            set(prepare.inventory_cases({"commit": prepare.COMMIT, "instances": records})),
            PUBLIC_IDS | FEEDBACK_IDS,
        )
        for changed in (records[:-1], records + [records[0]], records + [{"id": "X_16"}]):
            with self.subTest(count=len(changed)), self.assertRaises(ValueError):
                prepare.inventory_cases({"commit": prepare.COMMIT, "instances": changed})

    def test_input_only_scale_and_portable_staging_preserve_package_sources(self) -> None:
        prepare = load_task_module("prepare.py", "abc_x15_prepare")
        instance = tiny_instance("scale")
        self.assertEqual(prepare.scale_for(instance), 2.0)
        self.assertEqual(
            prepare.scale_for({**instance, "official_objective": -1e20, "leaderboard_score": 1e20}),
            2.0,
        )
        old_paths = [
            TASK / name
            for name in ("data-lock.json", "source-lock.json", "starter-lock.json", "init.py")
        ]
        old_hashes = {path: digest(path) for path in old_paths}
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "relocated-task"
            shutil.copytree(
                TASK,
                target,
                ignore=shutil.ignore_patterns("data", "public", "__pycache__", "*.pyc"),
            )
            originals = root / "verified-inputs"
            originals.mkdir()
            records = []
            for case_id in sorted(PUBLIC_IDS | FEEDBACK_IDS):
                source = originals / f"{case_id}.json"
                source.write_text(json.dumps(tiny_instance(case_id)))
                records.append(
                    {
                        "id": case_id,
                        "path": str(source),
                        "sha256": digest(source),
                        "bytes": source.stat().st_size,
                    }
                )
            inventory = root / "inventory.json"
            inventory.write_text(json.dumps({"commit": prepare.COMMIT, "instances": records}))
            # The fixture is a new task root with deliberately tiny trusted inputs.
            # Production source files and the production data-lock are untouched.
            (target / "data-lock.json").unlink(missing_ok=True)
            with mock.patch.object(prepare, "ROOT", target):
                lock = prepare.materialize(inventory)
                self.assertEqual(lock["public_count"], 45)
                self.assertEqual(lock["protected_count"], 15)
                public_path = target / "environment/app/public/manifest.json"
                protected_path = target / "tests/data/manifest.json"
                for manifest_path in (public_path, protected_path):
                    self.assertEqual(json.loads(manifest_path.read_text())["address_space_bytes"],
                                     17179869184)
                first = (digest(public_path), digest(protected_path))
                prepare.materialize(inventory)
                self.assertEqual((digest(public_path), digest(protected_path)), first)
            self.assertEqual(
                {path.stem for path in (target / "environment/app/public").glob("*.json")}
                - {"manifest"},
                PUBLIC_IDS,
            )
            self.assertFalse(list((target / "environment/app").rglob("X_*.json")))
            self.assertNotIn(str(originals), (target / "data-lock.json").read_text())
            self.assertTrue(
                all(digest(originals / f"{row['id']}.json") == row["sha256"] for row in records)
            )
        self.assertEqual({path: digest(path) for path in old_paths}, old_hashes)


class ABCX15FrozenFinalTests(unittest.TestCase):
    def _manifest(self, root: Path) -> Path:
        manifest = synthetic_manifest(
            root, [tiny_instance(f"X_{n:02d}") for n in range(1, 16)], seconds=900, workers=15
        )
        value = json.loads(manifest.read_text())
        value["protocol"] = "rte2020-abc-x15-v2"
        value["split"] = "protected_x15_feedback"
        manifest.write_text(json.dumps(value))
        return manifest

    def test_freeze_copies_source_and_receipt_rejects_changed_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            candidate = root / "candidate.py"
            candidate.write_text("print('frozen')\n")
            source_hash = digest(candidate)
            frozen_dir = root / "frozen"
            completed = subprocess.run(
                [
                    PYTHON,
                    str(TASK / "tools/freeze_candidate.py"),
                    "--candidate",
                    str(candidate),
                    "--output-dir",
                    str(frozen_dir),
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            receipt = frozen_dir / "freeze-receipt.json"
            self.assertEqual(json.loads(receipt.read_text())["candidate_sha256"], source_hash)
            self.assertEqual(digest(frozen_dir / "solver.py"), source_hash)
            candidate.write_text("raise RuntimeError('changed')\n")
            self.assertEqual(digest(frozen_dir / "solver.py"), source_hash)
            manifest = self._manifest(root)
            completed = subprocess.run(
                [
                    PYTHON,
                    str(TASK / "tools/final_evaluate.py"),
                    "--candidate",
                    str(candidate),
                    "--freeze-receipt",
                    str(receipt),
                    "--manifest",
                    str(manifest),
                    "--output",
                    str(root / "report.json"),
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("freeze receipt", completed.stderr)
            self.assertFalse((root / "report.json").exists())

    def test_final_cli_requires_a_freeze_receipt_before_any_evaluation(self) -> None:
        completed = subprocess.run(
            [
                PYTHON,
                str(TASK / "tools/final_evaluate.py"),
                "--candidate",
                "/absent/solver.py",
                "--manifest",
                "/absent/manifest.json",
                "--output",
                "/absent/report.json",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(completed.returncode, 2)
        self.assertIn("--freeze-receipt", completed.stderr)

    def test_postfreeze_5400_override_does_not_mutate_feedback_or_return_to_agent(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            candidate = root / "solver.py"
            candidate.write_text("pass\n")
            receipt = root / "freeze.json"
            receipt.write_text(
                json.dumps(
                    {
                        "protocol": "rte2020-abc-x15-v2",
                        "stage": "frozen_final_source",
                        "candidate_sha256": digest(candidate),
                    }
                )
            )
            manifest = self._manifest(root)
            before = digest(manifest)
            output = root / "private-final/report.json"
            calls = []
            fake_runner = types.ModuleType("runner")

            def evaluate_manifest(code, path, **kwargs):
                calls.append((code, json.loads(path.read_text()), kwargs))
                return {
                    "candidate_sha256": digest(candidate),
                    "validity": 1.0,
                    "combined_score": 0.4,
                    "cases": [],
                }

            fake_runner.evaluate_manifest = evaluate_manifest
            argv = [
                str(TASK / "tools/final_evaluate.py"),
                "--candidate",
                str(candidate),
                "--freeze-receipt",
                str(receipt),
                "--manifest",
                str(manifest),
                "--output",
                str(output),
            ]
            with (
                patch_modules({"runner": fake_runner}),
                mock.patch.object(sys, "argv", argv),
                mock.patch.object(sys, "path", list(sys.path)),
                contextlib.redirect_stdout(io.StringIO()) as stdout,
            ):
                runpy.run_path(argv[0], run_name="__main__")
            self.assertEqual(len(calls), 1)
            _, final_manifest, kwargs = calls[0]
            self.assertEqual(final_manifest["seconds_per_case"], 5400)
            self.assertEqual(final_manifest["split"], "protected_x15_frozen_final")
            self.assertEqual(kwargs["workers"], 15)
            self.assertTrue(kwargs["secure"])
            self.assertGreaterEqual(kwargs["timeout"], 5400)
            self.assertEqual(digest(manifest), before)
            report = json.loads(output.read_text())
            self.assertFalse(report["returns_to_developer"])
            self.assertFalse(report["feedback_budget_charged"])
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            self.assertNotIn("combined_score", stdout.getvalue())
            saved_report = digest(output)
            with (
                patch_modules({"runner": fake_runner}),
                mock.patch.object(sys, "argv", argv),
                mock.patch.object(sys, "path", list(sys.path)),
            ):
                with self.assertRaises(FileExistsError):
                    runpy.run_path(argv[0], run_name="__main__")
            self.assertEqual(len(calls), 1, "a saved final report must not trigger re-evaluation")
            self.assertEqual(digest(output), saved_report)


if __name__ == "__main__":
    unittest.main()
