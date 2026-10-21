"""Finite infrastructure diagnostics for the trusted launcher preflight."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
from candidate import Candidate, CandidateError, SandboxSetupError, secure_readiness  # noqa: E402


class ReadinessTests(unittest.TestCase):
    def setUp(self):
        self.platform = patch("candidate.sys.platform", "linux")
        self.uid = patch("candidate.os.geteuid", return_value=0)
        self.platform.start()
        self.uid.start()
        self.addCleanup(self.platform.stop)
        self.addCleanup(self.uid.stop)

    def test_success_uses_private_cwd_and_same_session_contract(self):
        with patch(
            "candidate.subprocess.run", return_value=subprocess.CompletedProcess([], 0, b"", b"")
        ) as run:
            directory = Path("/private-actor")
            secure_readiness(directory)
        self.assertEqual(run.call_args.kwargs["cwd"], directory)
        self.assertTrue(run.call_args.kwargs["start_new_session"])
        self.assertEqual(run.call_args.args[0][-1], "/usr/bin/true")
        self.assertEqual(set(run.call_args.kwargs["env"]), {"PATH", "LANG", "LC_ALL"})

    def test_failure_exposes_only_whitelisted_stage_errno_and_returncode(self):
        raw = b"distribution filesystem sandbox setup failed: Permission denied\nprivate-value"
        with patch(
            "candidate.subprocess.run", return_value=subprocess.CompletedProcess([], 125, b"", raw)
        ):
            with self.assertRaises(SandboxSetupError) as raised:
                secure_readiness(Path("/private-actor"))
        exc = raised.exception
        self.assertEqual(exc.code, "filesystem_setup_failed")
        self.assertEqual(exc.returncode, 125)
        self.assertEqual(exc.stderr_class, "EACCES")
        self.assertNotIn("private-value", str(exc))
        self.assertNotIsInstance(exc, CandidateError)

    def test_empty_stderr_exit_is_infrastructure_failure(self):
        with patch(
            "candidate.subprocess.run", return_value=subprocess.CompletedProcess([], 125, b"", b"")
        ):
            with self.assertRaises(SandboxSetupError) as raised:
                secure_readiness(Path("/private-actor"))
        self.assertEqual(raised.exception.code, "launcher_exit")
        self.assertEqual(raised.exception.stderr_class, "none")

    def test_timeout_and_missing_executable_are_distinct(self):
        for failure, code in (
            (subprocess.TimeoutExpired(["setpriv"], 5), "launcher_timeout"),
            (FileNotFoundError("private-path"), "launcher_unavailable"),
        ):
            with self.subTest(code=code), patch("candidate.subprocess.run", side_effect=failure):
                with self.assertRaises(SandboxSetupError) as raised:
                    secure_readiness(Path("/private-actor"))
                self.assertEqual(raised.exception.code, code)
                self.assertNotIn("private-path", str(raised.exception))

    def test_oversized_artifact_does_not_start_sandbox(self):
        with tempfile.TemporaryDirectory() as directory:
            huge = Path(directory) / "controller.py"
            with huge.open("wb") as stream:
                stream.truncate(1 << 40)
            with patch("candidate.secure_readiness") as readiness:
                with self.assertRaises(CandidateError) as raised:
                    Candidate(huge, {}, secure=True)
            self.assertEqual(raised.exception.code, "artifact_too_large")
            readiness.assert_not_called()


if __name__ == "__main__":
    unittest.main()
