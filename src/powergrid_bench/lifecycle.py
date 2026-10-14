"""One recoverable local lifecycle around task-specific evaluator backends.

This coordinator records policy; production clocks, container shutdown, gateways
and isolation must be supplied by an independently validated backend.
"""

import json
import time
from collections.abc import Callable

from .artifacts import ArtifactStore, content_hash
from .clock import RunClock
from .ledger import Ledger, LedgerError


class Lifecycle:
    def __init__(
        self, store: ArtifactStore, ledger: Ledger, *, now: Callable[[], float] = time.time
    ):
        self.store = store
        self.ledger = ledger
        self.now = now

    def prepare(
        self,
        run_id: str,
        context: dict,
        budget: int,
        baseline_digest: str,
        *,
        selection_direction: str = "higher",
        max_infrastructure_attempts: int = 1,
    ) -> dict:
        """Register a validated baseline after the caller completes preflight."""
        self.store.verify(baseline_digest)
        run = self.ledger.create_run(
            run_id,
            context,
            budget,
            baseline_digest=baseline_digest,
            selection_direction=selection_direction,
            max_infrastructure_attempts=max_infrastructure_attempts,
        )
        if run["state"] == "planned":
            return self.ledger.set_state(run_id, "prepared", expected={"planned"})
        return run

    def start(self, run_id: str, seconds: float) -> RunClock:
        run = self.ledger.get_run(run_id)
        if run["started_at"] is not None:
            clock = RunClock(run["started_at"], run["deadline_at"], run["duration_seconds"])
            if seconds != clock.duration_seconds:
                raise LedgerError("Recovery cannot change development duration")
            return clock
        if run["state"] != "prepared":
            raise LedgerError("Preflight and baseline preparation must finish first")
        return self.ledger.attach_clock(run_id, RunClock.start(seconds, now=self.now()))

    def submit(
        self, run_id: str, key: str, digest: str, *, request_context: dict | None = None
    ) -> dict:
        self.store.verify(digest)
        return self.ledger.accept(
            run_id, key, digest, request_context=request_context, now=self.now()
        )

    def record_selection(
        self,
        run_id: str,
        digest: str,
        score: float,
        *,
        feasible: bool = True,
        status: str = "succeeded",
        completed_at: float | None = None,
    ) -> dict:
        self.store.verify(digest)
        return self.ledger.record_selection(
            run_id,
            digest,
            score,
            feasible=feasible,
            status=status,
            completed_at=completed_at,
            now=self.now(),
        )

    def freeze(self, run_id: str, reason: str = "deadline") -> dict:
        run = self.ledger.get_run(run_id)
        if run["receipt"] is not None:
            receipt = json.loads(run["receipt"])
            self.store.verify(receipt["artifact_sha256"])
            return receipt
        observed = self.ledger.observe_time(run_id, now=self.now())
        if run["started_at"] is None:
            raise LedgerError("Unstarted development cannot freeze")
        if reason == "deadline" and observed < run["deadline_at"]:
            raise LedgerError("Deadline freeze cannot happen before deadline")
        self.ledger.set_state(run_id, "freezing", expected={"developing", "freezing"})
        selection = self.ledger.best_selection(run_id)
        digest = selection["artifact_sha256"] if selection else run["baseline"]
        summary = self.ledger.summary(run_id)
        receipt = self.store.freeze(digest, run_id=run_id, reason=reason, selection=selection)
        receipt.update(
            {
                "schema_version": 1,
                "frozen_at": observed,
                "deadline_at": run["deadline_at"],
                "context_sha256": content_hash(json.loads(run["context"])),
                "selection_direction": run["direction"],
                "selection_reason": "best_public_selection" if selection else "baseline_fallback",
                "feedback": summary,
                "unfinished_job_ids": [
                    job["job_id"]
                    for job in self.ledger.jobs(run_id)
                    if job["status"] in {"accepted", "running"}
                ],
            }
        )
        receipt["receipt_sha256"] = content_hash(receipt)
        return self.ledger.save_freeze(run_id, receipt)

    def final_start(self, run_id: str, *, request_context: dict | None = None) -> dict:
        run = self.ledger.get_run(run_id)
        if run["receipt"] is None:
            raise LedgerError("Final evaluation requires an immutable freeze receipt")
        receipt = json.loads(run["receipt"])
        self.store.verify(receipt["artifact_sha256"])
        context = {
            "freeze_receipt_sha256": receipt["receipt_sha256"],
            "evaluation": request_context or {},
        }
        job = self.ledger.accept(
            run_id,
            receipt["receipt_sha256"],
            receipt["artifact_sha256"],
            request_context=context,
            now=self.now(),
            kind="final",
        )
        if job["status"] == "accepted":
            self.ledger.start_job(job["job_id"], now=self.now())
            return self.ledger.get_job(job["job_id"])
        return job

    def final_retry(self, run_id: str, *, request_context: dict | None = None) -> dict:
        """Explicitly resume an infrastructure failure under the same job identity."""
        job = self.final_start(run_id, request_context=request_context)
        self.ledger.retry_job(job["job_id"], now=self.now())
        return self.ledger.get_job(job["job_id"])

    def final_finish(
        self, run_id: str, status: str, result: dict, *, job_id: str, attempt: int
    ) -> dict:
        """Commit only the dispatched attempt; stale workers cannot finish retries."""
        job = self.ledger.get_job(job_id)
        if job["run_id"] != run_id or job["kind"] != "final":
            raise LedgerError("Final result does not belong to this run")
        self.store.verify(job["artifact_sha256"])
        return self.ledger.finish_job(job["job_id"], attempt, status, result, now=self.now())
