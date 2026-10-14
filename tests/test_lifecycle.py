import tempfile
import unittest
from pathlib import Path

from powergrid_bench.artifacts import ArtifactError, ArtifactStore
from powergrid_bench.ledger import Ledger, LedgerError
from powergrid_bench.lifecycle import Lifecycle


class LifecycleTests(unittest.TestCase):
    def test_zero_feedback_run_can_select_freeze_and_finalize(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "solver.py").write_text("baseline")
            store = ArtifactStore(root / "store")
            baseline = store.snapshot(source)
            ledger = Ledger(root / "ledger.db")
            now = [100.0]
            lifecycle = Lifecycle(store, ledger, now=lambda: now[0])
            lifecycle.prepare("zero", {}, 0, baseline.digest, selection_direction="lower")
            lifecycle.start("zero", 10)
            with self.assertRaises(LedgerError):
                lifecycle.submit("zero", "request", baseline.digest)
            lifecycle.record_selection("zero", baseline.digest, 2)
            now[0] = 111
            receipt = lifecycle.freeze("zero")
            self.assertEqual(receipt["selection_direction"], "lower")
            self.assertEqual(ledger.summary("zero")["counted"], 0)
            final = lifecycle.final_start("zero")
            lifecycle.final_finish(
                "zero", "succeeded", {}, job_id=final["job_id"], attempt=final["attempt"]
            )
            self.assertEqual(ledger.get_run("zero")["state"], "complete")

    def test_final_infrastructure_retry_preserves_failure_and_context(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "solver.py").write_text("baseline")
            store = ArtifactStore(root / "store")
            baseline = store.snapshot(source)
            ledger = Ledger(root / "ledger.db")
            now = [100.0]
            lifecycle = Lifecycle(store, ledger, now=lambda: now[0])
            lifecycle.prepare("run", {}, 1, baseline.digest, max_infrastructure_attempts=2)
            lifecycle.start("run", 10)
            now[0] = 111
            lifecycle.freeze("run")
            original = lifecycle.final_start("run", request_context={"seed": 1})
            lifecycle.final_finish(
                "run",
                "infrastructure_error",
                {"failure": "worker"},
                job_id=original["job_id"],
                attempt=original["attempt"],
            )
            with self.assertRaises(LedgerError):
                lifecycle.final_retry("run", request_context={"seed": 2})
            retry = lifecycle.final_retry("run", request_context={"seed": 1})
            self.assertEqual(retry["job_id"], original["job_id"])
            self.assertEqual(retry["attempt"], 2)
            self.assertEqual(ledger.get_run("run")["state"], "final-evaluating")
            with self.assertRaises(LedgerError):
                lifecycle.final_finish(
                    "run",
                    "succeeded",
                    {"score": 999},
                    job_id=original["job_id"],
                    attempt=original["attempt"],
                )
            lifecycle.final_finish(
                "run", "succeeded", {"score": 2}, job_id=retry["job_id"], attempt=retry["attempt"]
            )
            with self.assertRaises(LedgerError):
                lifecycle.final_retry("run", request_context={"seed": 1})
            self.assertEqual(len(ledger.attempts(original["job_id"])), 2)
            self.assertEqual(ledger.summary("run")["counted"], 0)

    def test_recovery_selection_freeze_and_final_are_stable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "solver.py").write_text("baseline")
            store = ArtifactStore(root / "store")
            baseline = store.snapshot(source)
            ledger = Ledger(root / "ledger.db")
            now = [100.0]
            lifecycle = Lifecycle(store, ledger, now=lambda: now[0])
            lifecycle.prepare("run", {"task": "fixture"}, 2, baseline.digest)
            lifecycle.start("run", 10)
            (source / "solver.py").write_text("candidate")
            candidate = store.snapshot(source)
            now[0] = 101
            lifecycle.record_selection("run", candidate.digest, 1)
            lifecycle.record_selection("run", baseline.digest, 1)
            now[0] = 111
            recovered = Lifecycle(store, Ledger(root / "ledger.db"), now=lambda: now[0])
            receipt = recovered.freeze("run")
            self.assertEqual(receipt["artifact_sha256"], candidate.digest)
            self.assertEqual(receipt, recovered.freeze("run"))
            self.assertEqual(ledger.get_run("run")["deadline_at"], 110)
            final = recovered.final_start("run")
            self.assertEqual(final["job_id"], recovered.final_start("run")["job_id"])
            recovered.final_finish(
                "run",
                "succeeded",
                {"raw_score": 7},
                job_id=final["job_id"],
                attempt=final["attempt"],
            )
            self.assertEqual(ledger.get_run("run")["state"], "complete")
            self.assertEqual(recovered.final_start("run")["job_id"], final["job_id"])

    def test_fractional_duration_restores_at_current_epoch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "solver.py").write_text("baseline")
            store = ArtifactStore(root / "store")
            baseline = store.snapshot(source)
            ledger = Ledger(root / "ledger.db")
            now = [1_792_000_000.0]
            lifecycle = Lifecycle(store, ledger, now=lambda: now[0])
            lifecycle.prepare("run", {}, 0, baseline.digest)
            original = lifecycle.start("run", 0.1)
            now[0] += 100
            recovered = Lifecycle(store, Ledger(root / "ledger.db"), now=lambda: now[0])
            restored = recovered.start("run", 0.1)
            self.assertEqual(restored, original)
            self.assertEqual(restored.duration_seconds, 0.1)
            with self.assertRaises(LedgerError):
                recovered.start("run", 0.2)
            now[0] = float("nan")
            with self.assertRaises(LedgerError):
                recovered.freeze("run")
            self.assertEqual(ledger.get_run("run")["state"], "developing")

    def test_baseline_fallback_and_preaccept_rejection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "solver.py").write_text("baseline")
            store = ArtifactStore(root / "store")
            baseline = store.snapshot(source)
            ledger = Ledger(root / "ledger.db")
            now = [100.0]
            lifecycle = Lifecycle(store, ledger, now=lambda: now[0])
            lifecycle.prepare("run", {}, 1, baseline.digest)
            lifecycle.start("run", 10)
            with self.assertRaises(ArtifactError):
                lifecycle.submit("run", "bad", "a" * 64)
            self.assertEqual(ledger.summary("run")["counted"], 0)
            lifecycle.record_selection("run", baseline.digest, 100, feasible=False)
            now[0] = 111
            with self.assertRaises(LedgerError):
                lifecycle.record_selection("run", baseline.digest, 200)
            receipt = lifecycle.freeze("run")
            self.assertEqual(receipt["selection_reason"], "baseline_fallback")
            path = baseline.path / "solver.py"
            path.chmod(0o644)
            path.write_text("corrupted")
            with self.assertRaises(ArtifactError):
                lifecycle.final_start("run")
