import os
import tempfile
import unittest
from pathlib import Path

from powergrid_bench.artifacts import ArtifactError, ArtifactStore


class ArtifactTests(unittest.TestCase):
    def test_snapshot_is_content_addressed_and_independent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "solver.py").write_text("print(1)\n")
            store = ArtifactStore(root / "store")
            first = store.snapshot(source, required_files=("solver.py",))
            self.assertEqual(first.digest, store.snapshot(source).digest)
            (source / "solver.py").write_text("print(2)\n")
            self.assertEqual((first.path / "solver.py").read_text(), "print(1)\n")
            self.assertNotEqual(first.digest, store.snapshot(source).digest)
            self.assertEqual(store.verify(first.digest).digest, first.digest)

    def test_links_and_missing_files_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "solver.py").write_text("x")
            store = ArtifactStore(root / "store")
            with self.assertRaises(ArtifactError):
                store.snapshot(source, required_files=("missing.py",))
            with self.assertRaises(ArtifactError):
                store.snapshot(source, required_files=("../solver.py",))
            os.symlink(source / "solver.py", source / "link")
            with self.assertRaises(ArtifactError):
                store.snapshot(source)
            (source / "link").unlink()
            os.link(source / "solver.py", source / "hardlink")
            with self.assertRaises(ArtifactError):
                store.snapshot(source)

    def test_bounds_and_tampering(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "solver.py").write_text("1234")
            store = ArtifactStore(root / "store")
            with self.assertRaises(ArtifactError):
                store.snapshot(source, max_bytes=3)
            with self.assertRaises(ArtifactError):
                store.snapshot(source, max_files=0)
            snapshot = store.snapshot(source)
            path = snapshot.path / "solver.py"
            path.chmod(0o644)
            path.write_text("tampered")
            with self.assertRaises(ArtifactError):
                store.verify(snapshot.digest)

    def test_executable_mode_is_part_of_identity_and_store_cannot_be_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            script = source / "solver.sh"
            script.write_text("#!/bin/sh\nexit 0\n")
            script.chmod(0o644)
            store = ArtifactStore(root / "store")
            ordinary = store.snapshot(source)
            script.chmod(0o755)
            executable = store.snapshot(source)
            self.assertNotEqual(ordinary.digest, executable.digest)
            self.assertTrue((executable.path / "solver.sh").stat().st_mode & 0o111)
            self.assertEqual(store.verify(executable.digest).digest, executable.digest)
            with self.assertRaises(ArtifactError):
                store.snapshot(root)

    def test_custom_size_limit_survives_snapshot_verification(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            with (source / "weights.bin").open("wb") as stream:
                stream.truncate(100_000_001)
            store = ArtifactStore(root / "store")
            snapshot = store.snapshot(source, max_bytes=110_000_000)
            self.assertEqual(store.verify(snapshot.digest).digest, snapshot.digest)
