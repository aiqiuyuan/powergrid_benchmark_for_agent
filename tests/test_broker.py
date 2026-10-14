"""Real socket transport and protected feedback accounting regression tests."""

import base64
import io
import json
import sqlite3
import tarfile
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from powergrid_bench.artifacts import ArtifactStore
from powergrid_bench.broker import BrokerError, ExperimentBroker, client_request
from powergrid_bench.ledger import Ledger, LedgerError
from powergrid_bench.lifecycle import Lifecycle


def archive_payload(extra=None):
    manifest = {
        "kind": "algorithm",
        "task_id": "rte-maintenance",
        "source": ["main.py"],
        "dependency_lock": "requirements.lock",
        "entrypoint": ["python3", "main.py", "{input}", "{output}"],
    }
    files = {
        "candidate.json": json.dumps(manifest).encode(),
        "main.py": b"# test algorithm\n",
        "requirements.lock": b"# stdlib\n",
    }
    files.update(extra or {})
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w:gz") as package:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            package.addfile(info, io.BytesIO(data))
    return base64.b64encode(stream.getvalue()).decode()


class BrokerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="pgb-")
        self.root = Path(self.temporary.name)
        self.clock = [100.0]
        self.store = ArtifactStore(self.root / "store")
        baseline = self.root / "baseline"
        baseline.mkdir()
        (baseline / "base.txt").write_text("baseline")
        self.baseline = self.store.snapshot(baseline).digest
        self.ledger = Ledger(self.root / "controller" / "ledger.sqlite")
        self.lifecycle = Lifecycle(self.store, self.ledger, now=lambda: self.clock[0])
        self.brokers = []

    def tearDown(self):
        for broker in self.brokers:
            broker.close()
        self.temporary.cleanup()

    def make_broker(self, budget=1, evaluator=None, timeout=1):
        self.lifecycle.prepare(
            "run",
            {"task": "rte-maintenance"},
            budget,
            self.baseline,
            selection_direction="lower",
            max_infrastructure_attempts=2,
        )
        self.lifecycle.start("run", 100)
        broker = ExperimentBroker(
            self.lifecycle,
            "run",
            "rte-maintenance",
            lambda snapshot: {"status": "succeeded", "feasible": True, "score": 4},
            evaluator or (lambda snapshot: {"status": "succeeded", "score": 7}),
            max_files=10,
            max_bytes=10_000,
            max_archive_bytes=20_000,
            max_frame_bytes=40_000,
            timeout_seconds=timeout,
        )
        self.brokers.append(broker)
        return broker

    def ready(self, broker, job_id):
        for _ in range(100):
            result = broker.handle({"op": "result", "job_id": job_id})
            if result.get("ready"):
                return result
            time.sleep(0.01)
        self.fail("worker did not complete")

    def test_socket_roundtrip_requires_explicit_ack(self):
        broker = self.make_broker()
        socket_dir = self.root / "socket"
        socket_dir.mkdir(mode=0o700)
        path = socket_dir / "agent.sock"
        broker.start(path)

        def call(payload):
            return client_request(path, payload, timeout_seconds=2, max_frame_bytes=40_000)

        submitted = call({"op": "submit", "key": "one", "archive_base64": archive_payload()})
        self.assertTrue(submitted["ok"])
        result = self.ready(broker, submitted["job_id"])
        self.assertEqual(self.ledger.summary("run")["delivered"], 0)
        receipt = call(
            {
                "op": "ack",
                "job_id": submitted["job_id"],
                "payload_sha256": result["payload_sha256"],
                "ack_token": result["ack_token"],
            }
        )
        self.assertTrue(receipt["ok"])
        self.assertEqual(self.ledger.summary("run")["delivered"], 1)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_zero_feedback_still_allows_public_selection(self):
        broker = self.make_broker(budget=0)
        published = broker.handle(
            {"op": "publish", "key": "public", "archive_base64": archive_payload()}
        )
        self.assertTrue(published["ok"])
        self.assertEqual(self.ledger.best_selection("run")["score"], 4)
        submitted = broker.handle(
            {"op": "submit", "key": "protected", "archive_base64": archive_payload()}
        )
        self.assertFalse(submitted["ok"])
        self.assertEqual(self.ledger.summary("run")["counted"], 0)

    def test_duplicate_submission_executes_once_and_budget_once(self):
        calls = []

        def evaluate(snapshot):
            calls.append(snapshot.digest)
            return {"status": "succeeded", "score": 1}

        broker = self.make_broker(evaluator=evaluate)
        frame = {"op": "submit", "key": "same", "archive_base64": archive_payload()}
        first, second = broker.handle(frame), broker.handle(frame)
        self.assertEqual(first["job_id"], second["job_id"])
        self.ready(broker, first["job_id"])
        self.assertEqual(len(calls), 1)
        conflict = dict(frame, archive_base64=archive_payload({"other.txt": b"changed"}))
        self.assertFalse(broker.handle(conflict)["ok"])
        self.assertEqual(self.ledger.summary("run")["counted"], 1)

    def test_archive_traversal_link_duplicate_and_bomb_are_rejected(self):
        broker = self.make_broker()
        for kind in ("traversal", "symlink", "hardlink", "duplicate", "oversize"):
            stream = io.BytesIO()
            with tarfile.open(fileobj=stream, mode="w:gz") as package:
                entry = tarfile.TarInfo("../escape" if kind == "traversal" else "file")
                if kind in {"symlink", "hardlink"}:
                    entry.type = tarfile.SYMTYPE if kind == "symlink" else tarfile.LNKTYPE
                    entry.linkname = "/etc/passwd"
                    package.addfile(entry)
                else:
                    data = b"x" * (10_001 if kind == "oversize" else 1)
                    entry.size = len(data)
                    package.addfile(entry, io.BytesIO(data))
                    if kind == "duplicate":
                        package.addfile(entry, io.BytesIO(data))
            frame = {
                "op": "submit",
                "key": kind,
                "archive_base64": base64.b64encode(stream.getvalue()).decode(),
            }
            with self.subTest(kind=kind):
                self.assertFalse(broker.handle(frame)["ok"])
        self.assertEqual(self.ledger.summary("run")["counted"], 0)

    def test_late_result_hidden_and_ack_rejected(self):
        release = threading.Event()
        started = threading.Event()

        def evaluate(snapshot):
            started.set()
            release.wait(0.2)
            return {"status": "succeeded", "score": 9}

        broker = self.make_broker(evaluator=evaluate)
        submission = broker.handle(
            {"op": "submit", "key": "late", "archive_base64": archive_payload()}
        )
        self.assertTrue(started.wait(0.3))
        self.clock[0] = 201
        release.set()
        time.sleep(0.05)
        result = broker.handle({"op": "result", "job_id": submission["job_id"]})
        self.assertFalse(result["ok"])
        self.assertNotIn("payload", result)
        self.assertEqual(self.ledger.summary("run")["delivered"], 0)

    def test_ack_token_and_job_scope_are_checked(self):
        broker = self.make_broker()
        submission = broker.handle(
            {"op": "submit", "key": "one", "archive_base64": archive_payload()}
        )
        result = self.ready(broker, submission["job_id"])
        response = broker.handle(
            {
                "op": "ack",
                "job_id": submission["job_id"],
                "payload_sha256": result["payload_sha256"],
                "ack_token": "forged",
            }
        )
        self.assertFalse(response["ok"])
        self.assertEqual(self.ledger.summary("run")["delivered"], 0)
        self.assertFalse(broker.handle({"op": "freeze"})["ok"])

    def test_restart_preserves_tokens_and_completed_job(self):
        broker = self.make_broker()
        frame = {"op": "submit", "key": "restart", "archive_base64": archive_payload()}
        submission = broker.handle(frame)
        result = self.ready(broker, submission["job_id"])
        broker.close()
        recovered = self.make_broker()
        self.assertEqual(recovered.handle(frame)["job_id"], submission["job_id"])
        self.assertEqual(
            self.ready(recovered, submission["job_id"])["ack_token"], result["ack_token"]
        )
        self.assertEqual(self.ledger.summary("run")["counted"], 1)

    def test_infrastructure_retry_is_controller_only_and_same_identity(self):
        values = [
            {"status": "infrastructure_error", "error": "backend failed"},
            {"status": "succeeded", "score": 2},
        ]
        broker = self.make_broker(evaluator=lambda snapshot: values.pop(0))
        submitted = broker.handle(
            {"op": "submit", "key": "recover", "archive_base64": archive_payload()}
        )
        first = self.ready(broker, submitted["job_id"])
        self.assertEqual(first["payload"]["status"], "infrastructure_error")
        broker.recover(submitted["job_id"], backend_cleanup_confirmed=True)
        second = self.ready(broker, submitted["job_id"])
        self.assertEqual(second["payload"]["status"], "succeeded")
        self.assertEqual(self.ledger.summary("run")["counted"], 1)
        self.assertEqual(len(self.ledger.attempts(submitted["job_id"])), 2)

    def test_timeout_does_not_allow_double_execution_before_cleanup(self):
        release = threading.Event()
        calls = []

        def evaluate(snapshot):
            calls.append(snapshot.digest)
            release.wait(0.5)
            return {"status": "succeeded", "score": 20}

        broker = self.make_broker(budget=2, evaluator=evaluate, timeout=0.03)
        first = broker.handle({"op": "submit", "key": "slow", "archive_base64": archive_payload()})
        result = self.ready(broker, first["job_id"])
        self.assertEqual(result["payload"]["status"], "infrastructure_error")
        second = broker.handle({"op": "submit", "key": "next", "archive_base64": archive_payload()})
        self.assertFalse(second["ok"])
        self.assertEqual(len(calls), 1)
        release.set()

    def test_second_controller_for_same_run_is_rejected(self):
        self.make_broker()
        with self.assertRaises(BrokerError):
            self.make_broker()

    def test_interrupted_running_job_requires_controller_recovery(self):
        broker = self.make_broker()
        broker.close()
        job = self.lifecycle.submit("run", "interrupted", self.baseline)
        self.ledger.start_job(job["job_id"], now=self.clock[0])
        recovered = self.make_broker()
        time.sleep(0.03)
        self.assertEqual(self.ledger.get_job(job["job_id"])["attempt"], 1)
        with self.assertRaises(BrokerError):
            recovered.recover(job["job_id"], backend_cleanup_confirmed=False)
        recovered.recover(job["job_id"], backend_cleanup_confirmed=True)
        result = self.ready(recovered, job["job_id"])
        self.assertEqual(result["payload"]["status"], "succeeded")
        self.assertEqual(self.ledger.get_job(job["job_id"])["attempt"], 2)
        self.assertEqual(self.ledger.summary("run")["counted"], 1)

    def test_receipt_received_before_deadline_cannot_be_acked_late(self):
        broker = self.make_broker()
        frame = {"op": "submit", "key": "one", "archive_base64": archive_payload()}
        submitted = broker.handle(frame)
        result = self.ready(broker, submitted["job_id"])
        self.clock[0] = 201
        acknowledged = broker.handle(
            {
                "op": "ack",
                "job_id": submitted["job_id"],
                "payload_sha256": result["payload_sha256"],
                "ack_token": result["ack_token"],
            }
        )
        self.assertFalse(acknowledged["ok"])
        self.assertEqual(self.ledger.summary("run")["delivered"], 0)
        # Transport retries can recover existing identity after expiry; no new work.
        self.assertEqual(broker.handle(frame)["job_id"], submitted["job_id"])

    def test_corrupt_gzip_and_static_output_are_rejected_before_budget(self):
        broker = self.make_broker()
        truncated = base64.b64encode(b"\x1f\x8b\x08").decode()
        self.assertFalse(
            broker.handle({"op": "submit", "key": "bad", "archive_base64": truncated})["ok"]
        )
        static = archive_payload(
            {"candidate.json": b'{"kind":"static-output","task_id":"rte-maintenance"}'}
        )
        self.assertFalse(
            broker.handle({"op": "submit", "key": "static", "archive_base64": static})["ok"]
        )
        self.assertEqual(self.ledger.summary("run")["counted"], 0)

    def test_public_publish_stable_key_does_not_repeat_checker(self):
        broker = self.make_broker(budget=0)
        calls = []

        def evaluate(snapshot):
            calls.append(snapshot.digest)
            return {"status": "succeeded", "feasible": True, "score": 4}

        broker.selection_evaluator = evaluate
        frame = {"op": "publish", "key": "public", "archive_base64": archive_payload()}
        first = broker.handle(frame)
        second = broker.handle(frame)
        self.assertTrue(first["ok"] and second["ok"])
        self.assertEqual(first["public_result"], second["public_result"])
        self.assertEqual(len(calls), 1)

    def test_socket_directory_and_client_frames_are_bounded(self):
        broker = self.make_broker()
        exposed = self.root / "exposed"
        exposed.mkdir(mode=0o755)
        with self.assertRaises(BrokerError):
            broker.start(exposed / "agent.sock")
        with self.assertRaises(BrokerError):
            client_request(
                exposed / "missing.sock",
                {"oversize": "a" * 50},
                timeout_seconds=1,
                max_frame_bytes=10,
            )

    def test_protected_logs_and_outputs_never_enter_agent_feedback(self):
        secret = "PRIVATE-CASE-LABEL-AND-PATH"
        broker = self.make_broker(
            evaluator=lambda snapshot: {
                "status": "succeeded",
                "feasible": True,
                "score": 3,
                "stdout": secret,
                "stderr": secret,
                "output": {"labels": secret},
                "cases": [{"path": secret, "objective": secret}],
                "error": secret,
            }
        )
        submitted = broker.handle(
            {"op": "submit", "key": "private", "archive_base64": archive_payload()}
        )
        result = self.ready(broker, submitted["job_id"])
        self.assertNotIn(secret, json.dumps(result))
        self.assertEqual(result["payload"], {"status": "succeeded", "feasible": True, "score": 3})
        self.assertIn(secret, self.ledger.get_job(submitted["job_id"])["result"])
        acknowledged = broker.handle(
            {
                "op": "ack",
                "job_id": submitted["job_id"],
                "payload_sha256": result["payload_sha256"],
                "ack_token": result["ack_token"],
            }
        )
        self.assertTrue(acknowledged["ok"])
        self.assertNotIn(secret, json.dumps(acknowledged))

    def test_huge_public_score_is_classified_and_does_not_stick_running(self):
        broker = self.make_broker(budget=0)
        broker.selection_evaluator = lambda snapshot: {
            "status": "succeeded",
            "feasible": True,
            "score": 10**1000,
        }
        frame = {"op": "publish", "key": "huge", "archive_base64": archive_payload()}
        response = broker.handle(frame)
        self.assertTrue(response["ok"] and response["ready"])
        self.assertEqual(response["public_result"]["status"], "infrastructure_error")
        self.assertIsNone(self.ledger.best_selection("run"))
        self.assertTrue(broker.handle(frame)["ready"])

    def test_public_recovery_registers_cached_original_completion_without_execution(self):
        broker = self.make_broker(budget=0)
        snapshot = broker._snapshot(archive_payload())
        result = {"status": "succeeded", "feasible": True, "score": 2}
        with sqlite3.connect(broker._publish_db) as connection:
            connection.execute(
                "INSERT INTO publications VALUES(?,?,?,?,?)",
                ("interrupted", snapshot.digest, "evaluated", json.dumps(result), 102),
            )
        broker.close()
        self.clock[0] = 103
        recovered = self.make_broker(budget=0)
        recovered.selection_evaluator = lambda snapshot: self.fail("must not re-execute")
        response = recovered.recover_publication("interrupted", backend_cleanup_confirmed=True)
        self.assertTrue(response["ready"])
        incumbent = self.ledger.best_selection("run")
        self.assertEqual(incumbent["completed_at"], 102)
        self.assertEqual(incumbent["score"], 2)
        self.assertEqual(self.ledger.summary("run")["counted"], 0)

    def test_public_interruption_needs_explicit_recovery_same_artifact(self):
        broker = self.make_broker(budget=0)
        snapshot = broker._snapshot(archive_payload())
        with sqlite3.connect(broker._publish_db) as connection:
            connection.execute(
                "INSERT INTO publications VALUES(?,?,?,NULL,NULL)",
                ("interrupted", snapshot.digest, "running"),
            )
        frame = {"op": "publish", "key": "interrupted", "archive_base64": archive_payload()}
        self.assertFalse(broker.handle(frame)["ready"])
        broker.recover_publication("interrupted", backend_cleanup_confirmed=True)
        changed = dict(frame, archive_base64=archive_payload({"extra": b"other"}))
        self.assertFalse(broker.handle(changed)["ok"])
        self.assertTrue(broker.handle(frame)["ready"])
        self.assertEqual(self.ledger.summary("run")["counted"], 0)

    def cached_publication(self, broker, key, *, completed_at, score=2):
        snapshot = broker._snapshot(archive_payload({"key.txt": key.encode()}))
        result = {"status": "succeeded", "feasible": True, "score": score}
        with sqlite3.connect(broker._publish_db) as connection:
            connection.execute(
                "INSERT INTO publications VALUES(?,?,?,?,?)",
                (key, snapshot.digest, "evaluated", json.dumps(result), completed_at),
            )
        return snapshot

    def test_recovery_after_deadline_restores_predeadline_winner_once(self):
        broker = self.make_broker(budget=0)
        snapshot = self.cached_publication(broker, "completed-before-crash", completed_at=199)
        broker.close()
        self.clock[0] = 201
        recovered = self.make_broker(budget=0)
        recovered.recover_publication("completed-before-crash", backend_cleanup_confirmed=True)
        recovered.recover_publication("completed-before-crash", backend_cleanup_confirmed=True)
        with sqlite3.connect(self.ledger.path) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM selections").fetchone()[0], 1)
        receipt = self.lifecycle.freeze("run")
        self.assertEqual(receipt["artifact_sha256"], snapshot.digest)
        self.assertEqual(receipt["selection"]["completed_at"], 199)
        self.assertEqual(self.ledger.summary("run")["counted"], 0)

    def test_recovery_late_completion_never_qualifies_for_selection(self):
        broker = self.make_broker(budget=0)
        self.cached_publication(broker, "late", completed_at=201)
        self.clock[0] = 202
        with self.assertRaises(LedgerError):
            broker.recover_publication("late", backend_cleanup_confirmed=True)
        self.assertIsNone(self.ledger.best_selection("run"))

    def test_restore_preserves_original_time_tie_and_refuses_postfreeze_change(self):
        broker = self.make_broker(budget=0)
        self.clock[0] = 150
        self.lifecycle.record_selection("run", self.baseline, 2)
        snapshot = self.cached_publication(broker, "earlier", completed_at=120)
        self.clock[0] = 201
        broker.recover_publication("earlier", backend_cleanup_confirmed=True)
        self.assertEqual(self.ledger.best_selection("run")["artifact_sha256"], snapshot.digest)
        frozen = self.lifecycle.freeze("run")
        self.cached_publication(broker, "after-freeze", completed_at=119, score=1)
        with self.assertRaises(LedgerError):
            broker.recover_publication("after-freeze", backend_cleanup_confirmed=True)
        self.assertEqual(self.lifecycle.freeze("run"), frozen)

    def test_native_validator_rejects_before_feedback_counting(self):
        def reject(snapshot):
            raise ValueError("Wrong task-native ABI")

        broker = self.make_broker()
        broker.candidate_validator = reject
        frame = {"op": "submit", "key": "invalid-native", "archive_base64": archive_payload()}
        self.assertFalse(broker.handle(frame)["ok"])
        self.assertEqual(self.ledger.summary("run")["counted"], 0)

    def test_finish_failure_cannot_release_live_callback_lease(self):
        release = threading.Event()
        broker = self.make_broker(
            evaluator=lambda snapshot: release.wait(2) and {"status": "succeeded", "score": 4},
            timeout=0.03,
        )
        original = self.ledger.finish_job
        self.ledger.finish_job = lambda *args, **kwargs: (_ for _ in ()).throw(
            LedgerError("Injected storage failure")
        )
        submitted = broker.handle(
            {"op": "submit", "key": "blocked", "archive_base64": archive_payload()}
        )
        time.sleep(0.08)
        public = broker.handle(
            {"op": "publish", "key": "parallel", "archive_base64": archive_payload()}
        )
        self.assertFalse(public["ok"])
        with self.assertRaises(BrokerError):
            broker.recover(submitted["job_id"], backend_cleanup_confirmed=True)
        release.set()
        self.ledger.finish_job = original

    def test_public_storage_failure_does_not_leak_execution_lease(self):
        broker = self.make_broker(budget=0)
        frame = {"op": "publish", "key": "failed-write", "archive_base64": archive_payload()}
        real_connect = sqlite3.connect

        def connect(path, *args, **kwargs):
            if path == broker._publish_db:
                return real_connect(f"file:{path}?mode=ro", uri=True)
            return real_connect(path, *args, **kwargs)

        with patch("powergrid_bench.broker.sqlite3.connect", side_effect=connect):
            response = broker.handle(frame)
        self.assertFalse(response["ok"])
        self.assertFalse(broker._execution_lock.locked())
        self.assertTrue(broker.handle(dict(frame, key="safe-retry"))["ok"])

    def test_prefreeze_barrier_restores_and_disqualifies_then_blocks_unknown_outcome(self):
        broker = self.make_broker(budget=0)
        snapshot = self.cached_publication(broker, "valid", completed_at=199)
        self.cached_publication(broker, "late", completed_at=201, score=1)
        self.clock[0] = 202
        report = broker.reconcile_publications_before_freeze(backend_cleanup_confirmed=True)
        self.assertTrue(report["ready_to_freeze"])
        self.assertEqual(report["restored"], ["valid"])
        self.assertEqual(report["disqualified"], ["late"])
        self.assertEqual(self.ledger.best_selection("run")["artifact_sha256"], snapshot.digest)
        with sqlite3.connect(broker._publish_db) as connection:
            connection.execute(
                "INSERT INTO publications VALUES(?,?,?,NULL,NULL)",
                ("unknown", snapshot.digest, "running"),
            )
        report = broker.reconcile_publications_before_freeze(backend_cleanup_confirmed=True)
        self.assertFalse(report["ready_to_freeze"])
        self.assertEqual(report["unresolved"][0]["key"], "unknown")


if __name__ == "__main__":
    unittest.main()
