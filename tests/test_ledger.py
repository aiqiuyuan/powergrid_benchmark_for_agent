import concurrent.futures
import tempfile
import unittest
from pathlib import Path

from powergrid_bench.clock import RunClock
from powergrid_bench.ledger import Ledger, LedgerError


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "ledger.db"
        self.ledger = Ledger(self.path)
        self.ledger.create_run("run", {"task": "fixture"}, 1, max_infrastructure_attempts=2)
        self.ledger.attach_clock("run", RunClock.start(10, now=100))

    def tearDown(self):
        self.directory.cleanup()

    def test_receipt_loss_retry_does_not_charge_after_deadline(self):
        job = self.ledger.accept("run", "request", "a" * 64, now=101)
        retry = Ledger(self.path).accept("run", "request", "a" * 64, now=111)
        self.assertEqual(job["job_id"], retry["job_id"])
        self.assertEqual(self.ledger.summary("run")["counted"], 1)
        with self.assertRaises(LedgerError):
            self.ledger.accept("run", "request", "b" * 64, now=102)
        with self.assertRaises(LedgerError):
            self.ledger.accept("run", "request", "a" * 64, request_context={"seed": 2}, now=102)

    def test_concurrent_retries_are_atomic(self):
        def submit(_):
            return Ledger(self.path).accept("run", "request", "a" * 64, now=101)

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            jobs = list(pool.map(submit, range(12)))
        self.assertEqual(len({job["job_id"] for job in jobs}), 1)
        with self.assertRaises(LedgerError):
            self.ledger.accept("run", "another", "a" * 64, now=102)

    def test_late_result_audited_but_cannot_deliver(self):
        job = self.ledger.accept("run", "request", "a" * 64, now=101)
        attempt = self.ledger.start_job(job["job_id"], now=102)
        self.ledger.finish_job(job["job_id"], attempt, "succeeded", {"metric": 2}, now=111)
        with self.assertRaises(LedgerError):
            self.ledger.deliver(job["job_id"], {"score": 2}, now=112)
        summary = self.ledger.summary("run")
        self.assertEqual(summary["completed"], 1)
        self.assertEqual(summary["delivered"], 0)

    def test_infrastructure_retry_preserves_attempt_and_budget(self):
        job = self.ledger.accept("run", "request", "a" * 64, now=101)
        attempt = self.ledger.start_job(job["job_id"], now=102)
        self.ledger.finish_job(
            job["job_id"], attempt, "infrastructure_error", {"message": "worker lost"}, now=103
        )
        second = self.ledger.retry_job(job["job_id"], now=104)
        self.assertEqual(second, attempt + 1)
        self.ledger.finish_job(job["job_id"], second, "succeeded", {}, now=105)
        self.assertEqual(self.ledger.summary("run")["counted"], 1)
        self.assertEqual(len(self.ledger.attempts(job["job_id"])), 2)

    def test_context_and_clock_cannot_be_reset(self):
        with self.assertRaises(LedgerError):
            self.ledger.create_run("run", {"task": "changed"}, 1)
        with self.assertRaises(LedgerError):
            self.ledger.attach_clock("run", RunClock.start(10, now=110))
        self.assertEqual(self.ledger.get_run("run")["deadline_at"], 110)
        with self.assertRaises(ValueError):
            RunClock.start(0, now=100)

    def test_attempt_ceiling_is_immutable_and_atomic(self):
        with self.assertRaises(LedgerError):
            self.ledger.create_run("run", {"task": "fixture"}, 1, max_infrastructure_attempts=3)
        job = self.ledger.accept("run", "request", "a" * 64, now=101)
        first = self.ledger.start_job(job["job_id"], now=102)
        self.ledger.finish_job(job["job_id"], first, "infrastructure_error", {}, now=103)
        second = self.ledger.retry_job(job["job_id"], now=104)
        self.ledger.finish_job(job["job_id"], second, "infrastructure_error", {}, now=105)
        with self.assertRaises(LedgerError):
            self.ledger.retry_job(job["job_id"], now=106)
        self.assertEqual(self.ledger.get_job(job["job_id"])["attempt"], 2)
        self.assertEqual(len(self.ledger.attempts(job["job_id"])), 2)

    def test_rejected_deadline_observation_survives_backward_clock(self):
        with self.assertRaises(LedgerError):
            self.ledger.accept("run", "late", "a" * 64, now=111)
        with self.assertRaises(LedgerError):
            Ledger(self.path).accept("run", "rewound", "a" * 64, now=101)
        self.assertEqual(self.ledger.get_run("run")["last_seen_at"], 111)
