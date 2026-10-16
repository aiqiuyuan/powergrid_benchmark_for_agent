"""Preparation copies only pinned clean sources into fresh trusted workspaces."""

import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from powergrid_bench.distribution import preparation
from powergrid_bench.distribution.preparation import (
    PreparationError,
    prepare_from_lock,
    prepare_workspace,
    verify_archive,
)


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.git("init", "-q")
        self.git("config", "user.name", "Fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        (self.source / "model.txt").write_text("toy source\n")
        self.git("add", "model.txt")
        self.git("commit", "-qm", "fixture")
        self.commit = self.git("rev-parse", "HEAD")
        self.destination = self.root / "worker"

    def git(self, *args):
        return subprocess.check_output(["git", *args], cwd=self.source, text=True).strip()

    def prepare(self, **kwargs):
        return prepare_workspace(
            self.source, self.destination, expected_commit=self.commit, **kwargs
        )

    def test_copies_clean_sources_and_writes_integrity_receipt(self):
        digest = hashlib.sha256(b"toy source\n").hexdigest()
        result = self.prepare(required_files={"model.txt": digest})
        self.assertEqual((self.destination / "model.txt").read_text(), "toy source\n")
        self.assertFalse((self.destination / ".git").exists())
        self.assertEqual(result["source_commit"], self.commit)
        self.assertFalse(result["release_ready"])
        receipt = json.loads((self.destination / "source-receipt.json").read_text())
        self.assertEqual(receipt["files"], {"model.txt": digest})
        (self.destination / "model.txt").write_text("worker writes")
        self.assertEqual((self.source / "model.txt").read_text(), "toy source\n")
        with self.assertRaises(PreparationError):
            self.prepare()

    def test_rejects_dirty_wrong_commit_nested_destination_and_hash(self):
        for options in ({"expected_commit": "0" * 40}, {"expected_commit": "HEAD"}):
            with self.assertRaises(PreparationError):
                prepare_workspace(self.source, self.destination, **options)
        with self.assertRaises(PreparationError):
            prepare_workspace(self.source, self.source / "worker", expected_commit=self.commit)
        with self.assertRaises(PreparationError):
            self.prepare(required_files={"model.txt": "0" * 64})
        self.assertFalse(self.destination.exists())
        (self.source / "extra.txt").write_text("not committed")
        with self.assertRaises(PreparationError):
            self.prepare()

    def test_symlinks_are_not_copied(self):
        (self.source / "linked").symlink_to(self.root / "outside")
        self.git("add", "linked")
        self.git("commit", "-qm", "link")
        self.commit = self.git("rev-parse", "HEAD")
        with self.assertRaises(PreparationError):
            self.prepare()
        self.assertFalse(self.destination.exists())

    def test_hidden_index_flags_cannot_forge_source_identity(self):
        for flag in ("--assume-unchanged", "--skip-worktree"):
            self.git("update-index", flag, "model.txt")
            (self.source / "model.txt").write_text("modified outside pinned commit")
            self.assertEqual(self.git("status", "--porcelain"), "")
            with self.assertRaises(PreparationError):
                self.prepare()
            self.assertFalse(self.destination.exists())
            (self.source / "model.txt").write_text("toy source\n")
            self.git("update-index", "--no-assume-unchanged", "--no-skip-worktree", "model.txt")

    def test_source_mutation_between_identity_and_digest_reads_is_rejected(self):
        original = preparation._digest

        def mutate_before_digest(path):
            if path == self.source.resolve() / "model.txt":
                path.write_text("changed after Git identity check")
            return original(path)

        with patch.object(preparation, "_digest", side_effect=mutate_before_digest):
            with self.assertRaises(PreparationError):
                self.prepare()
        self.assertFalse(self.destination.exists())

    def test_archive_requires_exact_size_digest_and_regular_file(self):
        archive = self.root / "archive.zip"
        archive.write_bytes(b"fixture bytes, not a real archive")
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        size = archive.stat().st_size
        self.assertEqual(verify_archive(archive, sha256=digest, size_bytes=size)["sha256"], digest)
        for pin in (
            {"sha256": "0" * 64, "size_bytes": size},
            {"sha256": digest, "size_bytes": size + 1},
        ):
            with self.assertRaises(PreparationError):
                verify_archive(archive, **pin)
        linked = self.root / "linked.zip"
        linked.symlink_to(archive)
        with self.assertRaises(PreparationError):
            verify_archive(linked, sha256=digest, size_bytes=size)

    def test_source_lock_and_optional_archive_receipt(self):
        archive = self.root / "fixture.zip"
        archive.write_bytes(b"toy archive")
        lock = self.root / "lock.json"
        document = {
            "schema_version": "distribution-sources-v1",
            "tasks": {
                "fixture": {
                    "source_commit": self.commit,
                    "archives": {
                        "toy": {
                            "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                            "size_bytes": archive.stat().st_size,
                        }
                    },
                }
            },
        }
        lock.write_text(json.dumps(document))
        result = prepare_from_lock(
            lock,
            "fixture",
            source=self.source,
            destination=self.destination,
            archives={"toy": str(archive)},
        )
        self.assertFalse(result["simulation_executed"])
        self.assertEqual(result["verified_archives"][0]["file"], "fixture.zip")
        self.assertEqual(
            json.loads((self.destination / "preparation-report.json").read_text()), result
        )
        with self.assertRaises(PreparationError):
            prepare_from_lock(
                lock,
                "fixture",
                source=self.source,
                destination=self.root / "other",
                archives={"unknown": str(archive)},
            )
        document["schema_version"] = "unknown"
        lock.write_text(json.dumps(document))
        with self.assertRaises(PreparationError):
            prepare_from_lock(lock, "fixture", source=self.source, destination=self.root / "other")
