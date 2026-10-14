import sys
import tempfile
import time
import unittest
from pathlib import Path

from powergrid_bench.process import run_process


class ProcessTests(unittest.TestCase):
    def test_argument_vector_and_bounded_output(self):
        result = run_process(
            [sys.executable, "-c", "print('x' * 10000)"], timeout_seconds=2, max_output_bytes=50
        )
        self.assertEqual(result.status, "succeeded")
        self.assertLessEqual(len(result.stdout.encode()), 50)
        self.assertTrue(result.output_truncated)

    def test_timeout_kills_child_process(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "child-survived"
            child_code = (
                "import time,pathlib;time.sleep(0.8);pathlib.Path(%r).write_text('bad')"
                % str(marker)
            )
            parent_code = (
                "import subprocess,sys,time;subprocess.Popen([sys.executable,'-c',%r]);"
                "time.sleep(10)" % child_code
            )
            result = run_process([sys.executable, "-c", parent_code], timeout_seconds=0.15)
            self.assertEqual(result.status, "timeout")
            time.sleep(1)
            self.assertFalse(marker.exists())

    def test_invalid_timeout_and_nonzero_exit(self):
        with self.assertRaises(ValueError):
            run_process([sys.executable], timeout_seconds=0)
        result = run_process([sys.executable, "-c", "raise SystemExit(7)"], timeout_seconds=2)
        self.assertEqual(result.status, "candidate_error")
        self.assertEqual(result.returncode, 7)
