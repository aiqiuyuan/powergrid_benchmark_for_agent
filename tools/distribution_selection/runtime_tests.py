"""Local regression checks for the independent CPU baseline runtime."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

RUNTIME_FILE = Path(__file__).with_name("runtime_cluster.py")
SPEC = importlib.util.spec_from_file_location("selection_runtime", RUNTIME_FILE)
runtime = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runtime)


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.code = self.root / "code"
        self.pool = self.root / "pool"
        self.code.mkdir()
        self.pool.mkdir()
        self.entry = self.code / "runtime_cluster.py"
        self.entry.write_text("frozen runtime")
        (self.pool / "case.json").write_text("frozen case")
        self.archive = self.root / "runtime.tar"
        self.archive.write_bytes(b"numerical runtime")
        self.acceptance = self.root / "acceptance.json"
        self.acceptance.write_text(
            json.dumps(
                {
                    "passed": True,
                    "images": [
                        {
                            "runtime_image": "mapdn-canary-runtime:1",
                            "runtime_image_id": "sha256:" + "1" * 64,
                            "runtime_archive_sha256": runtime.digest(self.archive),
                        }
                    ],
                }
            )
        )
        self.manifest = {
            "schema_version": 1,
            "network": "mapdn33",
            "code": {
                "root": str(self.code),
                "files": {
                    "runtime_cluster.py": runtime.digest(self.entry),
                },
            },
            "pool": {
                "root": str(self.pool),
                "files": {
                    "case.json": runtime.digest(self.pool / "case.json"),
                },
            },
            "runtime_acceptance": str(self.acceptance),
            "runtime_archive": str(self.archive),
            "command": ["python", "/selection/run.py", "--output", "/output"],
            "output": str(self.root / "new-output"),
            "timeout_seconds": 3600,
        }
        self.path = self.root / "job.json"
        self.patch_file = mock.patch.object(runtime, "__file__", str(self.entry))
        self.patch_receipt = mock.patch.object(
            runtime,
            "ACCEPTANCE_SHA256",
            runtime.digest(self.acceptance),
        )
        self.patch_file.start()
        self.patch_receipt.start()
        self.addCleanup(self.patch_file.stop)
        self.addCleanup(self.patch_receipt.stop)

    def validate(self):
        self.path.write_text(json.dumps(self.manifest))
        return runtime.validate_manifest(self.path, runtime.digest(self.path))

    def test_valid_manifest(self):
        manifest, image = self.validate()
        self.assertEqual(manifest["network"], "mapdn33")
        self.assertEqual(image["runtime_image"], "mapdn-canary-runtime:1")
        self.assertFalse((self.root / "new-output").exists())

    def test_submitted_manifest_hash_mismatch(self):
        self.path.write_text(json.dumps(self.manifest))
        with self.assertRaises(ValueError):
            runtime.validate_manifest(self.path, "0" * 64)

    def test_changed_code_rejected(self):
        self.entry.write_text("modified runtime")
        with self.assertRaises(ValueError):
            self.validate()

    def test_unlisted_pool_file_rejected(self):
        (self.pool / "extra.json").write_text("extra")
        with self.assertRaises(ValueError):
            self.validate()

    def test_wrong_runtime_archive_rejected(self):
        self.archive.write_bytes(b"wrong image")
        with self.assertRaises(ValueError):
            self.validate()

    def test_unaccepted_receipt_rejected(self):
        self.acceptance.write_text("{}")
        with self.assertRaises(ValueError):
            self.validate()

    def test_output_dotdot_escape_rejected_without_mutation(self):
        outside = self.root / "outside"
        outside.mkdir()
        self.manifest["output"] = str(outside / ".." / "code" / "new-results")
        with self.assertRaises(ValueError):
            self.validate()
        self.assertFalse((self.code / "new-results").exists())

    def test_output_parent_symlink_rejected(self):
        alias = self.root / "alias"
        alias.symlink_to(self.code, target_is_directory=True)
        self.manifest["output"] = str(alias / "new-results")
        with self.assertRaises(ValueError):
            self.validate()
        self.assertFalse((self.code / "new-results").exists())

    def test_private_pool_copy_runs_worker_without_mutating_frozen_source(self):
        for layout in ("mapdn", "powergym"):
            with self.subTest(layout=layout):
                output = self.root / ("copy-" + layout)
                output.mkdir()
                target = output if layout == "mapdn" else output / "pool"
                child = (
                    "import pathlib,sys; p=pathlib.Path(sys.argv[1]); "
                    "assert (p/'case.json').read_text()=='frozen case'; "
                    "(p/'case.json').write_text('private copy changed')"
                )
                subprocess.run(
                    [
                        sys.executable,
                        "-c",
                        runtime.COPY_POOL_WRAPPER,
                        str(self.pool),
                        str(target),
                        json.dumps(self.manifest["pool"]["files"]),
                        sys.executable,
                        "-c",
                        child,
                        str(target),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=True,
                )
                self.assertEqual((target / "case.json").read_text(), "private copy changed")
                self.assertEqual((self.pool / "case.json").read_text(), "frozen case")
                self.assertEqual(target.stat().st_mode & 0o777, 0o700)


class DaemonStartupTests(unittest.TestCase):
    def test_slow_startup_recovers_after_individual_timeouts(self):
        daemon = mock.Mock()
        daemon.poll.return_value = None
        with (
            mock.patch.object(runtime, "docker_info", side_effect=["timeout", "ready"]),
            mock.patch.object(runtime.time, "sleep"),
        ):
            runtime.wait_for_daemon(daemon, {}, startup_seconds=1)

    def test_default_daemon_unknown_state_fails_closed(self):
        with mock.patch.object(runtime, "docker_info", return_value="timeout"):
            with self.assertRaises(RuntimeError):
                runtime.reject_existing_daemon({})

    def test_exited_daemon_fails_before_another_probe(self):
        daemon = mock.Mock()
        daemon.poll.return_value = 1
        with mock.patch.object(runtime, "docker_info") as info:
            with self.assertRaises(RuntimeError):
                runtime.wait_for_daemon(daemon, {})
            info.assert_not_called()


if __name__ == "__main__":
    unittest.main()
