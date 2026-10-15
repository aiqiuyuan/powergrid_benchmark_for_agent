"""MAPDN preparation and optional real-backend controller contract checks."""

from __future__ import annotations

import importlib.util
import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

PACKAGE = Path(__file__).resolve().parents[1] / "task-packages/mapdn-voltage-control-canary-v1"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


prepare = load("mapdn_canary_prepare", PACKAGE / "prepare.py")
HAS_PP = importlib.util.find_spec("pandapower") is not None


class RangePreparationTests(unittest.TestCase):
    def fixture(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("padding", b"x" * 100000)
            for name in prepare.MEMBERS:
                archive.writestr(
                    prepare.PREFIX + name,
                    b"trusted member " + name.encode(),
                    compress_type=zipfile.ZIP_DEFLATED,
                )
        return buffer.getvalue()

    def test_extract_complete_members_and_resume_from_partial_compressed_cache(self):
        data = self.fixture()
        with (
            patch.object(prepare, "ARCHIVE_SIZE", len(data)),
            patch.object(
                prepare,
                "open_range",
                side_effect=lambda start, end: io.BytesIO(data[start : end + 1]),
            ),
        ):
            catalog = prepare.entries()
            self.assertEqual(set(catalog), set(prepare.MEMBERS))
            with tempfile.TemporaryDirectory() as temporary:
                output = Path(temporary)
                for name, row in catalog.items():
                    start = row["offset"] + 30 + len(row["member"].encode())
                    (output / (name + ".deflate")).write_bytes(data[start : start + 3])
                    receipt = prepare.extract_one(output, row)
                    self.assertEqual(
                        (output / name).read_bytes(), b"trusted member " + name.encode()
                    )
                    self.assertEqual(receipt["size"], (output / name).stat().st_size)
                    self.assertIn("archive-sha256-not-verified", receipt["verification"])
                    self.assertEqual(prepare.extract_one(output, row), receipt)

    def test_crc_mismatch_cannot_be_certified(self):
        data = self.fixture()
        with (
            patch.object(prepare, "ARCHIVE_SIZE", len(data)),
            patch.object(
                prepare,
                "open_range",
                side_effect=lambda start, end: io.BytesIO(data[start : end + 1]),
            ),
        ):
            row = prepare.entries()["model.p"]
            row["crc32"] ^= 1
            with tempfile.TemporaryDirectory() as temporary:
                with self.assertRaisesRegex(ValueError, "CRC32"):
                    prepare.extract_one(Path(temporary), row)
                self.assertFalse((Path(temporary) / "model.p.receipt.json").exists())

    def test_public_worker_duplicate_matches(self):
        self.assertEqual(
            (PACKAGE / "images/actor_worker.py").read_bytes(),
            (PACKAGE / "support/actor_worker.py").read_bytes(),
        )


@unittest.skipUnless(HAS_PP, "optional Pandapower backend is not installed")
class LocalBackendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runner = load("mapdn_canary_runner", PACKAGE / "support/runner.py")

    def test_actions_reject_nonfinite_boolean_shape_and_excess(self):
        for invalid in ([float("nan")], [float("inf")], [True], [0.81], [-0.81], [], [0, 0], 0):
            with self.subTest(value=invalid), self.assertRaises(self.runner.CandidateError):
                self.runner.validate_action(invalid, 0.8)
        self.assertEqual(self.runner.validate_action([-0.8], 0.8), -0.8)

    def test_workers_keep_independent_instance_histories(self):
        code = b"""class Controller:
    def __init__(self, metadata): self.count = 0
    def act(self, observation):
        self.count += 1
        return [self.count * 0.1]
"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = self.runner.Actor(code, {"actor_id": 0}, root, secure=False)
            second = self.runner.Actor(code, {"actor_id": 1}, root, secure=False)
            try:
                self.assertEqual(first.exchange({"observation": {}})["action"], [0.1])
                self.assertEqual(first.exchange({"observation": {}})["action"], [0.2])
                self.assertEqual(second.exchange({"observation": {}})["action"], [0.1])
            finally:
                first.close()
                second.close()

    def test_controller_that_fakes_output_without_reading_cannot_block_input_write(self):
        code = b"""import os
os.write(1, b'{"ready":true}\\n')
while True:
    os.write(1, b'{"action":[0.0]}\\n')
"""
        with tempfile.TemporaryDirectory() as temporary:
            actor = self.runner.Actor(code, {"actor_id": 0}, Path(temporary), secure=False)
            try:
                with self.assertRaisesRegex(self.runner.CandidateError, "reading"):
                    actor.exchange({"observation": {"padding": "x" * 60000}}, timeout=0.2)
            finally:
                actor.close()

    def test_exited_worker_cleanup_preserves_candidate_failure(self):
        code = b"""class Controller:
    def __init__(self, metadata): pass
    def act(self, observation): return [float("nan")]
"""
        with tempfile.TemporaryDirectory() as temporary:
            actor = self.runner.Actor(code, {"actor_id": 0}, Path(temporary), secure=False)
            try:
                with self.assertRaises(self.runner.CandidateError):
                    actor.exchange({"observation": {}})
            finally:
                actor.close()


if __name__ == "__main__":
    unittest.main()
