"""Transactional local ledger. The database belongs to the trusted controller."""

import json
import math
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from .artifacts import canonical, content_hash
from .clock import RunClock


class LedgerError(ValueError):
    """Invalid transition, conflicting retry, or exhausted development budget."""


TERMINAL = {"succeeded", "candidate_error", "infrastructure_error", "timeout"}


class Ledger:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._transaction() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY, context TEXT NOT NULL,
                    budget INTEGER NOT NULL, state TEXT NOT NULL,
                    baseline TEXT, direction TEXT NOT NULL,
                    max_infrastructure_attempts INTEGER NOT NULL DEFAULT 1,
                    started_at REAL, deadline_at REAL, duration_seconds REAL, last_seen_at REAL,
                    receipt TEXT);
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY, run_id TEXT NOT NULL,
                    request_key TEXT NOT NULL, fingerprint TEXT NOT NULL,
                    artifact_sha256 TEXT NOT NULL, kind TEXT NOT NULL,
                    accepted_at REAL NOT NULL, status TEXT NOT NULL,
                    attempt INTEGER NOT NULL DEFAULT 0, completed_at REAL,
                    result TEXT, delivered_at REAL, delivery TEXT,
                    UNIQUE(run_id, request_key, kind));
                CREATE TABLE IF NOT EXISTS attempts (
                    job_id TEXT NOT NULL, attempt INTEGER NOT NULL,
                    started_at REAL NOT NULL, completed_at REAL,
                    status TEXT NOT NULL, result TEXT,
                    PRIMARY KEY(job_id, attempt));
                CREATE TABLE IF NOT EXISTS selections (
                    evidence_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL, artifact_sha256 TEXT NOT NULL,
                    score REAL NOT NULL, feasible INTEGER NOT NULL,
                    status TEXT NOT NULL, completed_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS selection_restores (
                    run_id TEXT NOT NULL, evidence_key TEXT NOT NULL,
                    fingerprint TEXT NOT NULL, evidence_id INTEGER NOT NULL,
                    PRIMARY KEY(run_id, evidence_key));
            """)
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(runs)")}
            if "max_infrastructure_attempts" not in columns:
                connection.execute(
                    "ALTER TABLE runs ADD COLUMN max_infrastructure_attempts "
                    "INTEGER NOT NULL DEFAULT 1"
                )
            if "duration_seconds" not in columns:
                connection.execute("ALTER TABLE runs ADD COLUMN duration_seconds REAL")

    @contextmanager
    def _transaction(self):
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _row(connection, table: str, key: str, value: str) -> dict:
        row = connection.execute(f"SELECT * FROM {table} WHERE {key}=?", (value,)).fetchone()
        if row is None:
            raise LedgerError(f"Unknown {table} identity")
        return dict(row)

    @staticmethod
    def _now(now: float | None) -> float:
        value = time.time() if now is None else float(now)
        if not math.isfinite(value):
            raise LedgerError("Timestamp must be finite")
        return value

    def _observe(self, connection, run: dict, now: float | None) -> float:
        previous = run["last_seen_at"]
        value = max(self._now(now), previous if previous is not None else float("-inf"))
        connection.execute("UPDATE runs SET last_seen_at=? WHERE run_id=?", (value, run["run_id"]))
        return value

    def observe_time(self, run_id: str, *, now: float | None = None) -> float:
        """Commit the trusted host observation even if a later action is rejected."""
        with self._transaction() as connection:
            run = self._row(connection, "runs", "run_id", run_id)
            return self._observe(connection, run, now)

    def create_run(
        self,
        run_id: str,
        context: dict,
        budget: int,
        *,
        baseline_digest: str | None = None,
        selection_direction: str = "higher",
        max_infrastructure_attempts: int = 1,
    ) -> dict:
        if not run_id or isinstance(budget, bool) or not isinstance(budget, int) or budget < 0:
            raise LedgerError("Run identity and nonnegative integer feedback budget required")
        if selection_direction not in {"higher", "lower"}:
            raise LedgerError("Unknown selection direction")
        if (
            isinstance(max_infrastructure_attempts, bool)
            or not isinstance(max_infrastructure_attempts, int)
            or max_infrastructure_attempts < 1
        ):
            raise LedgerError("Infrastructure attempt ceiling must be a positive integer")
        encoded = canonical(context).decode()
        with self._transaction() as connection:
            existing = connection.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if existing:
                existing = dict(existing)
                if (
                    existing["context"],
                    existing["budget"],
                    existing["baseline"],
                    existing["direction"],
                    existing["max_infrastructure_attempts"],
                ) != (
                    encoded,
                    budget,
                    baseline_digest,
                    selection_direction,
                    max_infrastructure_attempts,
                ):
                    raise LedgerError("Recovery cannot change immutable run context")
                return existing
            connection.execute(
                "INSERT INTO runs(run_id,context,budget,state,baseline,direction,"
                "max_infrastructure_attempts) VALUES(?,?,?,?,?,?,?)",
                (
                    run_id,
                    encoded,
                    budget,
                    "planned",
                    baseline_digest,
                    selection_direction,
                    max_infrastructure_attempts,
                ),
            )
            return self._row(connection, "runs", "run_id", run_id)

    def get_run(self, run_id: str) -> dict:
        with self._transaction() as connection:
            return self._row(connection, "runs", "run_id", run_id)

    def set_state(self, run_id: str, state: str, *, expected: set[str]) -> dict:
        with self._transaction() as connection:
            run = self._row(connection, "runs", "run_id", run_id)
            if run["state"] == state:
                return run
            if run["state"] not in expected:
                raise LedgerError("Invalid lifecycle state transition")
            connection.execute("UPDATE runs SET state=? WHERE run_id=?", (state, run_id))
            return self._row(connection, "runs", "run_id", run_id)

    def attach_clock(self, run_id: str, clock: RunClock) -> RunClock:
        with self._transaction() as connection:
            run = self._row(connection, "runs", "run_id", run_id)
            if run["started_at"] is not None:
                saved = RunClock(run["started_at"], run["deadline_at"], run["duration_seconds"])
                if saved != clock:
                    raise LedgerError("Recovery cannot reset development clock")
                return saved
            if run["state"] not in {"planned", "prepared"}:
                raise LedgerError("Clock must start after preparation")
            connection.execute(
                "UPDATE runs SET started_at=?,deadline_at=?,duration_seconds=?,"
                "last_seen_at=?,state='developing' WHERE run_id=?",
                (
                    clock.started_at,
                    clock.deadline_at,
                    clock.duration_seconds,
                    clock.started_at,
                    run_id,
                ),
            )
            return clock

    def accept(
        self,
        run_id: str,
        key: str,
        artifact_sha256: str,
        *,
        request_context: dict | None = None,
        now: float | None = None,
        kind: str = "development",
    ) -> dict:
        if not key or kind not in {"development", "final"}:
            raise LedgerError("Valid submission key and evaluation kind required")
        fingerprint = content_hash({"artifact": artifact_sha256, "request": request_context or {}})
        observation = self.observe_time(run_id, now=now)
        with self._transaction() as connection:
            run = self._row(connection, "runs", "run_id", run_id)
            existing = connection.execute(
                "SELECT * FROM jobs WHERE run_id=? AND request_key=? AND kind=?",
                (run_id, key, kind),
            ).fetchone()
            if existing:
                if existing["fingerprint"] != fingerprint:
                    raise LedgerError("Idempotency key conflicts with artifact or request context")
                return dict(existing)
            observed = self._observe(connection, run, observation)
            if kind == "development":
                if (
                    run["state"] != "developing"
                    or run["deadline_at"] is None
                    or observed >= run["deadline_at"]
                ):
                    raise LedgerError("Development submission outside active window")
                counted = connection.execute(
                    "SELECT COUNT(*) FROM jobs WHERE run_id=? AND kind='development'", (run_id,)
                ).fetchone()[0]
                if counted >= run["budget"]:
                    raise LedgerError("Protected-feedback budget exhausted")
                active = connection.execute(
                    "SELECT 1 FROM jobs WHERE run_id=? AND kind='development' "
                    "AND status IN ('accepted','running')",
                    (run_id,),
                ).fetchone()
                if active:
                    raise LedgerError("One protected evaluation may be active per run")
            else:
                if run["state"] != "frozen" or run["receipt"] is None:
                    raise LedgerError("Final evaluation requires a freeze receipt")
                if connection.execute(
                    "SELECT 1 FROM jobs WHERE run_id=? AND kind='final'", (run_id,)
                ).fetchone():
                    raise LedgerError("Final evaluation already has a stable job identity")
                receipt = json.loads(run["receipt"])
                if artifact_sha256 != receipt["artifact_sha256"]:
                    raise LedgerError("Final evaluation artifact differs from freeze receipt")
            job_id = str(uuid.uuid4())
            connection.execute(
                "INSERT INTO jobs(job_id,run_id,request_key,fingerprint,artifact_sha256,"
                "kind,accepted_at,status) VALUES(?,?,?,?,?,?,?,'accepted')",
                (job_id, run_id, key, fingerprint, artifact_sha256, kind, observed),
            )
            if kind == "final":
                connection.execute(
                    "UPDATE runs SET state='final-evaluating' WHERE run_id=?", (run_id,)
                )
            return self._row(connection, "jobs", "job_id", job_id)

    def start_job(self, job_id: str, *, now: float | None = None) -> int:
        with self._transaction() as connection:
            job = self._row(connection, "jobs", "job_id", job_id)
            if job["status"] != "accepted":
                raise LedgerError("Only an accepted job may start")
            return self._start_attempt(connection, job, now)

    def _start_attempt(self, connection, job: dict, now: float | None) -> int:
        run = self._row(connection, "runs", "run_id", job["run_id"])
        observed = self._observe(connection, run, now)
        if job["kind"] == "development" and (
            run["state"] != "developing" or observed >= run["deadline_at"]
        ):
            raise LedgerError("Development execution or retry past deadline")
        if job["attempt"] >= run["max_infrastructure_attempts"]:
            raise LedgerError("Infrastructure attempt ceiling exhausted")
        attempt = job["attempt"] + 1
        connection.execute(
            "UPDATE jobs SET status='running',attempt=?,completed_at=NULL,"
            "result=NULL WHERE job_id=?",
            (attempt, job["job_id"]),
        )
        connection.execute(
            "INSERT INTO attempts(job_id,attempt,started_at,status) VALUES(?,?,?,'running')",
            (job["job_id"], attempt, observed),
        )
        return attempt

    def retry_job(self, job_id: str, *, now: float | None = None) -> int:
        with self._transaction() as connection:
            job = self._row(connection, "jobs", "job_id", job_id)
            if job["status"] != "infrastructure_error" or job["delivered_at"] is not None:
                raise LedgerError("Only undelivered infrastructure failures may retry")
            if (
                job["kind"] == "development"
                and connection.execute(
                    "SELECT 1 FROM jobs WHERE run_id=? AND kind='development' "
                    "AND status IN ('accepted','running') AND job_id!=?",
                    (job["run_id"], job_id),
                ).fetchone()
            ):
                raise LedgerError("Another protected job is active")
            attempt = self._start_attempt(connection, job, now)
            if job["kind"] == "final":
                run = self._row(connection, "runs", "run_id", job["run_id"])
                if run["state"] != "failed":
                    raise LedgerError("Only a failed final lifecycle may recover")
                connection.execute(
                    "UPDATE runs SET state='final-evaluating' WHERE run_id=?", (job["run_id"],)
                )
            return attempt

    def finish_job(
        self, job_id: str, attempt: int, status: str, result: dict, *, now: float | None = None
    ) -> dict:
        if status not in TERMINAL:
            raise LedgerError("Unknown evaluation terminal status")
        encoded = canonical(result).decode()
        with self._transaction() as connection:
            job = self._row(connection, "jobs", "job_id", job_id)
            if job["attempt"] != attempt:
                raise LedgerError("Stale evaluation attempt")
            if job["status"] in TERMINAL:
                if (job["status"], job["result"]) == (status, encoded):
                    return job
                raise LedgerError("Conflicting terminal result")
            if job["status"] != "running":
                raise LedgerError("Evaluation has not started")
            run = self._row(connection, "runs", "run_id", job["run_id"])
            observed = self._observe(connection, run, now)
            connection.execute(
                "UPDATE jobs SET status=?,completed_at=?,result=? WHERE job_id=?",
                (status, observed, encoded, job_id),
            )
            connection.execute(
                "UPDATE attempts SET status=?,completed_at=?,result=? WHERE job_id=? AND attempt=?",
                (status, observed, encoded, job_id, attempt),
            )
            if job["kind"] == "final":
                state = (
                    "complete"
                    if status in {"succeeded", "candidate_error", "timeout"}
                    else "failed"
                )
                connection.execute("UPDATE runs SET state=? WHERE run_id=?", (state, job["run_id"]))
            return self._row(connection, "jobs", "job_id", job_id)

    def deliver(self, job_id: str, payload: dict, *, now: float | None = None) -> dict:
        payload_hash = content_hash(payload)
        observation = self.observe_time(self.get_job(job_id)["run_id"], now=now)
        with self._transaction() as connection:
            job = self._row(connection, "jobs", "job_id", job_id)
            if job["delivery"] is not None:
                receipt = json.loads(job["delivery"])
                if receipt["payload_sha256"] != payload_hash:
                    raise LedgerError("Conflicting delivery payload")
                return receipt
            run = self._row(connection, "runs", "run_id", job["run_id"])
            observed = self._observe(connection, run, observation)
            if (
                job["kind"] != "development"
                or job["status"] not in TERMINAL
                or run["state"] != "developing"
                or observed >= run["deadline_at"]
            ):
                raise LedgerError("Feedback unavailable or delivery after deadline")
            receipt = {
                "job_id": job_id,
                "artifact_sha256": job["artifact_sha256"],
                "payload_sha256": payload_hash,
                "delivered_at": observed,
            }
            connection.execute(
                "UPDATE jobs SET delivered_at=?,delivery=? WHERE job_id=?",
                (observed, canonical(receipt).decode(), job_id),
            )
            return receipt

    def record_selection(
        self,
        run_id: str,
        artifact_sha256: str,
        score: float,
        *,
        feasible: bool = True,
        status: str = "succeeded",
        completed_at: float | None = None,
        now: float | None = None,
    ) -> dict:
        if isinstance(score, bool) or not math.isfinite(score):
            raise LedgerError("Public-selection score must be finite")
        observation = self.observe_time(run_id, now=now)
        with self._transaction() as connection:
            run = self._row(connection, "runs", "run_id", run_id)
            observed = self._observe(connection, run, observation)
            completed = observed if completed_at is None else self._now(completed_at)
            if (
                run["state"] != "developing"
                or observed > run["deadline_at"]
                or completed > observed
                or not run["started_at"] <= completed <= run["deadline_at"]
            ):
                raise LedgerError("Public selection must complete and register during development")
            cursor = connection.execute(
                "INSERT INTO selections(run_id,artifact_sha256,score,feasible,status,"
                "completed_at) VALUES(?,?,?,?,?,?)",
                (run_id, artifact_sha256, score, bool(feasible), status, completed),
            )
            return dict(
                connection.execute(
                    "SELECT * FROM selections WHERE evidence_id=?", (cursor.lastrowid,)
                ).fetchone()
            )

    def restore_selection(
        self,
        run_id: str,
        evidence_key: str,
        artifact_sha256: str,
        score: float,
        *,
        completed_at: float,
        feasible: bool = True,
        status: str = "succeeded",
        now: float | None = None,
    ) -> dict:
        """Controller-only restore of an authenticated durable public checkpoint.

        The controller must read evidence from its protected checkpoint store;
        an agent-supplied timestamp is never admissible evidence. Restoration can
        happen after the deadline, but the checkpoint's original completion must
        fall inside development. No changes are allowed once freezing starts.
        The evidence key and full fingerprint make crash replay idempotent.
        """
        if not isinstance(evidence_key, str) or not evidence_key or len(evidence_key) > 1024:
            raise LedgerError("Bounded durable selection evidence identity required")
        try:
            if type(score) not in (int, float) or not math.isfinite(score):
                raise LedgerError("Restored public-selection score must be finite")
            normalized_score = float(score)
        except OverflowError as error:
            raise LedgerError("Restored public-selection score must be finite") from error
        if type(feasible) is not bool or status not in TERMINAL:
            raise LedgerError("Restored selection has invalid feasibility/status")
        if type(completed_at) not in (int, float):
            raise LedgerError("Trusted selection completion timestamp required")
        completed = self._now(completed_at)
        fingerprint = content_hash(
            {
                "artifact_sha256": artifact_sha256,
                "score": normalized_score,
                "feasible": feasible,
                "status": status,
                "completed_at": completed,
            }
        )
        observation = self.observe_time(run_id, now=now)
        with self._transaction() as connection:
            run = self._row(connection, "runs", "run_id", run_id)
            observed = self._observe(connection, run, observation)
            if (
                run["state"] != "developing"
                or run["receipt"] is not None
                or run["started_at"] is None
                or run["deadline_at"] is None
                or not run["started_at"] <= completed <= run["deadline_at"]
                or completed > observed
            ):
                raise LedgerError("Restore requires predeadline evidence before freezing")
            existing = connection.execute(
                "SELECT fingerprint,evidence_id FROM selection_restores "
                "WHERE run_id=? AND evidence_key=?",
                (run_id, evidence_key),
            ).fetchone()
            if existing is not None:
                if existing["fingerprint"] != fingerprint:
                    raise LedgerError("Conflicting durable selection evidence")
                return self._row(connection, "selections", "evidence_id", existing["evidence_id"])
            cursor = connection.execute(
                "INSERT INTO selections(run_id,artifact_sha256,score,feasible,status,completed_at) "
                "VALUES(?,?,?,?,?,?)",
                (run_id, artifact_sha256, normalized_score, feasible, status, completed),
            )
            connection.execute(
                "INSERT INTO selection_restores VALUES(?,?,?,?)",
                (run_id, evidence_key, fingerprint, cursor.lastrowid),
            )
            return self._row(connection, "selections", "evidence_id", cursor.lastrowid)

    def best_selection(self, run_id: str) -> dict | None:
        with self._transaction() as connection:
            run = self._row(connection, "runs", "run_id", run_id)
            order = "DESC" if run["direction"] == "higher" else "ASC"
            row = connection.execute(
                "SELECT * FROM selections WHERE run_id=? AND feasible=1 "
                "AND status='succeeded' AND completed_at<=? "
                f"ORDER BY score {order},completed_at ASC,evidence_id ASC LIMIT 1",
                (run_id, run["deadline_at"]),
            ).fetchone()
            return dict(row) if row else None

    def save_freeze(self, run_id: str, receipt: dict) -> dict:
        encoded = canonical(receipt).decode()
        with self._transaction() as connection:
            run = self._row(connection, "runs", "run_id", run_id)
            if run["receipt"]:
                if run["receipt"] != encoded:
                    raise LedgerError("Conflicting freeze receipt")
                return json.loads(run["receipt"])
            if run["state"] != "freezing":
                raise LedgerError("Run must be freezing")
            connection.execute(
                "UPDATE runs SET receipt=?,state='frozen' WHERE run_id=?", (encoded, run_id)
            )
            return receipt

    def get_job(self, job_id: str) -> dict:
        with self._transaction() as connection:
            return self._row(connection, "jobs", "job_id", job_id)

    def jobs(self, run_id: str, *, kind: str | None = None) -> list[dict]:
        with self._transaction() as connection:
            query, values = "SELECT * FROM jobs WHERE run_id=?", [run_id]
            if kind:
                query, values = query + " AND kind=?", values + [kind]
            return [
                dict(row)
                for row in connection.execute(query + " ORDER BY accepted_at,job_id", values)
            ]

    def attempts(self, job_id: str) -> list[dict]:
        with self._transaction() as connection:
            return [
                dict(row)
                for row in connection.execute(
                    "SELECT * FROM attempts WHERE job_id=? ORDER BY attempt", (job_id,)
                )
            ]

    def summary(self, run_id: str) -> dict:
        run, jobs = self.get_run(run_id), self.jobs(run_id, kind="development")
        return {
            "run_id": run_id,
            "state": run["state"],
            "budget": run["budget"],
            "counted": len(jobs),
            "completed": sum(job["completed_at"] is not None for job in jobs),
            "delivered": sum(job["delivered_at"] is not None for job in jobs),
            "active": sum(job["status"] in {"accepted", "running"} for job in jobs),
            "read_acknowledged": None,
        }
