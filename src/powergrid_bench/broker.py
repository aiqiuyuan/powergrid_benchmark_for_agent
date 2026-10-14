"""A private Unix socket boundary around the shared experiment lifecycle.

Callbacks are trusted backend adapters and must terminate their own processes.
The broker bounds waiting, suppresses late results, and keeps a lease until a
timed-out callback actually returns. A Python thread is not a security sandbox.
Only the socket directory should be mounted in a developer container; controller
storage, frozen snapshots, private inputs and credentials must stay outside it.
"""

import base64
import binascii
import fcntl
import gzip
import hashlib
import hmac
import io
import json
import math
import os
import queue
import secrets
import socket
import socketserver
import sqlite3
import tarfile
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path, PurePosixPath

from .adapters import AdapterError, validate_candidate
from .artifacts import ArtifactError, Snapshot, canonical, content_hash
from .ledger import TERMINAL, LedgerError
from .lifecycle import Lifecycle


class BrokerError(ValueError):
    """Invalid transport request or unsafe broker operation."""


def _object(data: bytes) -> dict:
    def constant(value):
        raise BrokerError("Nonfinite JSON")

    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise BrokerError("Duplicate JSON key")
            value[key] = item
        return value

    try:
        value = json.loads(data, parse_constant=constant, object_pairs_hook=pairs)
        if not isinstance(value, dict):
            raise BrokerError("JSON object required")
        canonical(value)
        return value
    except (ValueError, UnicodeError, RecursionError, OverflowError) as error:
        raise BrokerError("Malformed bounded JSON frame") from error


def client_request(
    socket_path: str | Path, payload: dict, *, timeout_seconds: float, max_frame_bytes: int
) -> dict:
    """Exchange one bounded JSON frame; callers explicitly ACK received results."""
    if timeout_seconds <= 0 or not math.isfinite(timeout_seconds) or max_frame_bytes <= 0:
        raise BrokerError("Positive finite transport bounds required")
    frame = canonical(payload) + b"\n"
    if len(frame) > max_frame_bytes:
        raise BrokerError("Request frame exceeds bound")
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(timeout_seconds)
            connection.connect(str(socket_path))
            connection.sendall(frame)
            with connection.makefile("rb") as response:
                data = response.readline(max_frame_bytes + 1)
                if len(data) > max_frame_bytes or not data.endswith(b"\n"):
                    raise BrokerError("Missing or oversized response frame")
                return _object(data)
    except OSError as error:
        raise BrokerError("Broker transport unavailable") from error


class _BoundedReader:
    def __init__(self, stream, limit: int):
        self.stream, self.remaining = stream, limit

    def read(self, size: int = -1) -> bytes:
        size = self.remaining + 1 if size < 0 else min(size, self.remaining + 1)
        data = self.stream.read(size)
        self.remaining -= len(data)
        if self.remaining < 0:
            raise BrokerError("Expanded archive exceeds bound")
        return data


class _UnixServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True
    block_on_close = False


class ExperimentBroker:
    """Agent-facing public selection and protected feedback for exactly one run.

    The controller prepares and starts Lifecycle before creating this broker.
    Evaluators receive Snapshot and return dictionaries with a terminal status.
    Public success additionally requires a finite score and boolean feasibility.
    recover() is a controller-only operation, never a socket operation.
    """

    def __init__(
        self,
        lifecycle: Lifecycle,
        run_id: str,
        task_id: str,
        selection_evaluator: Callable[[Snapshot], dict],
        feedback_evaluator: Callable[[Snapshot], dict],
        *,
        max_files: int,
        max_bytes: int,
        max_archive_bytes: int,
        max_frame_bytes: int,
        timeout_seconds: float,
        candidate_validator: Callable[[Snapshot], None] | None = None,
    ):
        for value in (max_files, max_bytes, max_archive_bytes, max_frame_bytes):
            if type(value) is not int or value <= 0:
                raise BrokerError("Positive integer packaging/frame bounds required")
        if (
            isinstance(timeout_seconds, bool)
            or not math.isfinite(timeout_seconds)
            or timeout_seconds <= 0
        ):
            raise BrokerError("Positive finite evaluator timeout required")
        lifecycle.ledger.get_run(run_id)
        self.lifecycle, self.run_id, self.task_id = lifecycle, run_id, task_id
        self.selection_evaluator, self.feedback_evaluator = selection_evaluator, feedback_evaluator
        self.max_files, self.max_bytes = max_files, max_bytes
        self.max_archive_bytes, self.max_frame_bytes = max_archive_bytes, max_frame_bytes
        self.timeout_seconds = timeout_seconds
        self.candidate_validator = candidate_validator
        self.controller_root = (
            lifecycle.ledger.path.parent
            / "broker-state"
            / hashlib.sha256(run_id.encode()).hexdigest()
        )
        self.controller_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.controller_root.is_symlink():
            raise BrokerError("Controller storage must not be linked")
        self.controller_root.chmod(0o700)
        self._lock_file = (self.controller_root / "controller.lock").open("a+b")
        try:
            fcntl.flock(self._lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            self._lock_file.close()
            raise BrokerError("Another broker owns this run") from error
        secret_path = self.controller_root / "ack-secret"
        if not secret_path.exists():
            descriptor = os.open(secret_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(secrets.token_bytes(32))
        self._secret = secret_path.read_bytes()
        if len(self._secret) != 32 or secret_path.is_symlink():
            self._lock_file.close()
            raise BrokerError("Invalid controller ACK secret")
        self._publish_db = self.controller_root / "publications.sqlite"
        with sqlite3.connect(self._publish_db) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS publications (request_key TEXT PRIMARY KEY, "
                "digest TEXT NOT NULL, status TEXT NOT NULL, result TEXT, completed_at REAL)"
            )
            columns = {row[1] for row in connection.execute("PRAGMA table_info(publications)")}
            if "completed_at" not in columns:
                connection.execute("ALTER TABLE publications ADD COLUMN completed_at REAL")
        self._requests_lock = threading.RLock()
        self._execution_lock = threading.Lock()
        self._closed = threading.Event()
        self._pending = queue.Queue()
        self._scheduled = set()
        self._server, self._server_thread, self._socket_path = None, None, None
        self._worker = threading.Thread(
            target=self._dispatch, daemon=True, name="protected-evaluator"
        )
        self._worker.start()
        # Accepted jobs have never started. Running jobs require explicit backend cleanup.
        for job in lifecycle.ledger.jobs(run_id, kind="development"):
            if job["status"] == "accepted":
                self._enqueue(job["job_id"])

    def _active(self) -> dict:
        observed = self.lifecycle.ledger.observe_time(self.run_id, now=self.lifecycle.now())
        run = self.lifecycle.ledger.get_run(self.run_id)
        if (
            run["state"] != "developing"
            or run["deadline_at"] is None
            or observed >= run["deadline_at"]
        ):
            raise BrokerError("Development window is closed")
        return run

    def _snapshot(self, encoded: str) -> Snapshot:
        if not isinstance(encoded, str) or len(encoded) > 4 * ((self.max_archive_bytes + 2) // 3):
            raise BrokerError("Archive upload exceeds bound")
        try:
            data = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as error:
            raise BrokerError("Invalid archive encoding") from error
        if not data or len(data) > self.max_archive_bytes:
            raise BrokerError("Archive upload exceeds bound")
        with tempfile.TemporaryDirectory(prefix="upload-", dir=self.controller_root) as temporary:
            root, names, total, members = Path(temporary), set(), 0, 0
            with gzip.GzipFile(fileobj=io.BytesIO(data)) as compressed:
                # Count all expanded bytes, including tar metadata and padding.
                stream = _BoundedReader(compressed, self.max_bytes + self.max_files * 2048 + 20_480)
                with tarfile.open(fileobj=stream, mode="r|") as archive:
                    for member in archive:
                        members += 1
                        name = member.name.rstrip("/") if member.isdir() else member.name
                        if (
                            members > self.max_files * 2
                            or not name
                            or name in names
                            or "\\" in name
                            or ":" in name
                            or "\x00" in name
                            or PurePosixPath(name).is_absolute()
                            or any(part in {"", ".", ".."} for part in name.split("/"))
                            or name == "_manifest.json"
                            or not (member.isfile() or member.isdir())
                        ):
                            raise BrokerError("Unsafe archive member")
                        names.add(name)
                        output = root / name
                        if member.isdir():
                            output.mkdir(parents=True, exist_ok=True)
                            continue
                        total += member.size
                        if member.size < 0 or total > self.max_bytes:
                            raise BrokerError("Expanded candidate exceeds bound")
                        output.parent.mkdir(parents=True, exist_ok=True)
                        incoming = archive.extractfile(member)
                        if incoming is None:
                            raise BrokerError("Unreadable archive member")
                        with incoming, output.open("xb") as target:
                            remaining = member.size
                            while remaining:
                                chunk = incoming.read(min(65_536, remaining))
                                if not chunk:
                                    raise BrokerError("Truncated archive member")
                                target.write(chunk)
                                remaining -= len(chunk)
                        output.chmod(0o755 if member.mode & 0o111 else 0o644)
            manifest = validate_candidate(root, self.task_id)
            required = tuple(["candidate.json", manifest["dependency_lock"], *manifest["source"]])
            snapshot = self.lifecycle.store.snapshot(
                root, required_files=required, max_files=self.max_files, max_bytes=self.max_bytes
            )
            if self.candidate_validator is not None:
                self.candidate_validator(snapshot)
            return snapshot

    def _job(self, job_id: str) -> dict:
        job = self.lifecycle.ledger.get_job(job_id)
        if job["run_id"] != self.run_id or job["kind"] != "development":
            raise BrokerError("Job does not belong to broker run")
        return job

    def _token(self, job_id: str, payload_hash: str) -> str:
        return hmac.new(
            self._secret,
            canonical({"job_id": job_id, "payload_sha256": payload_hash}),
            hashlib.sha256,
        ).hexdigest()

    @staticmethod
    def _feedback_payload(job: dict) -> dict:
        """Expose aggregate checker fields; candidate logs remain controller-only.

        A candidate can print private inputs to stdout or its native output. The
        trusted audit result therefore must never be the agent transport payload.
        Numbers here must originate from the independent checker, not self-report.
        """
        audited = json.loads(job["result"])
        payload = {"status": job["status"]}
        if type(audited.get("feasible")) is bool:
            payload["feasible"] = audited["feasible"]
        for name in ("score", "raw_objective"):
            value = audited.get(name)
            try:
                finite = type(value) in (int, float) and math.isfinite(value)
            except OverflowError:
                finite = False
            if finite:
                payload[name] = value
        for name in ("case_count", "feasible_case_count"):
            if type(audited.get(name)) is int and audited[name] >= 0:
                payload[name] = audited[name]
        return payload

    def _enqueue(self, job_id: str) -> None:
        with self._requests_lock:
            if job_id not in self._scheduled:
                self._scheduled.add(job_id)
                self._pending.put(job_id)

    def _evaluate(
        self, evaluator: Callable[[Snapshot], dict], snapshot: Snapshot
    ) -> tuple[dict, threading.Thread | None]:
        try:
            run = self.lifecycle.ledger.get_run(self.run_id)
            observed = self.lifecycle.ledger.observe_time(self.run_id, now=self.lifecycle.now())
            remaining = max(0, run["deadline_at"] - observed)
        except (LedgerError, OSError, sqlite3.Error):
            return {"status": "infrastructure_error", "error": "controller_clock_or_storage"}, None
        if remaining <= 0 or run["state"] != "developing":
            return {"status": "infrastructure_error", "error": "development_window_closed"}, None
        results = queue.Queue(maxsize=1)

        def execute():
            try:
                result = evaluator(snapshot)
                if not isinstance(result, dict) or result.get("status") not in TERMINAL:
                    raise BrokerError("Backend returned invalid terminal result")
                if len(canonical(result)) > self.max_frame_bytes // 2:
                    raise BrokerError("Backend result exceeds transport bound")
            except Exception:
                result = {"status": "infrastructure_error", "error": "backend_evaluation_failed"}
            results.put(result)

        callback = threading.Thread(target=execute, daemon=True, name="bounded-backend-callback")
        callback.start()
        try:
            result = results.get(timeout=min(self.timeout_seconds, remaining))
        except queue.Empty:
            # The trusted native callback establishes candidate timeouts itself.
            # A supervisor wait timeout means backend outcome/cleanup is unknown.
            result = {"status": "infrastructure_error", "error": "backend_supervisor_timeout"}
        # Caller retains the execution lease until callback cleanup. Completion at
        # timeout is recorded first; the late callback cannot replace that result.
        return result, callback

    def _dispatch(self) -> None:
        while not self._closed.is_set():
            try:
                job_id = self._pending.get(timeout=0.05)
            except queue.Empty:
                continue
            callback = None
            try:
                with self._execution_lock:
                    try:
                        job = self._job(job_id)
                        if job["status"] == "accepted":
                            attempt = self.lifecycle.ledger.start_job(
                                job_id, now=self.lifecycle.now()
                            )
                        elif job["status"] == "running":
                            attempt = job["attempt"]
                        else:
                            continue
                        snapshot = self.lifecycle.store.verify(job["artifact_sha256"])
                        result, callback = self._evaluate(self.feedback_evaluator, snapshot)
                        self.lifecycle.store.verify(snapshot.digest)
                        self.lifecycle.ledger.finish_job(
                            job_id, attempt, result["status"], result, now=self.lifecycle.now()
                        )
                    finally:
                        if callback is not None:
                            callback.join()
            except (BrokerError, LedgerError, ArtifactError, OSError, sqlite3.Error):
                # No new identity or attempt is silently created. Controller recovery
                # must inspect an interrupted accepted/running job before redispatch.
                pass
            finally:
                with self._requests_lock:
                    self._scheduled.discard(job_id)
                self._pending.task_done()

    def _publish(self, frame: dict) -> dict:
        self._active()
        key = frame["key"]
        snapshot = self._snapshot(frame["archive_base64"])
        lease_acquired = False
        try:
            with self._requests_lock, sqlite3.connect(self._publish_db) as connection:
                row = connection.execute(
                    "SELECT digest,status,result FROM publications WHERE request_key=?", (key,)
                ).fetchone()
                if row:
                    if row[0] != snapshot.digest:
                        raise BrokerError("Public idempotency key conflicts with artifact")
                    if row[1] != "retry-authorized":
                        return {
                            "artifact_sha256": snapshot.digest,
                            "ready": row[1] == "complete",
                            "public_result": json.loads(row[2]) if row[2] else None,
                        }
                if not self._execution_lock.acquire(blocking=False):
                    raise BrokerError("Backend cleanup or evaluation is active")
                lease_acquired = True
                if row:
                    connection.execute(
                        "UPDATE publications SET status='running',result=NULL,completed_at=NULL "
                        "WHERE request_key=?",
                        (key,),
                    )
                else:
                    connection.execute(
                        "INSERT INTO publications VALUES(?,?,?,NULL,NULL)",
                        (key, snapshot.digest, "running"),
                    )
        except BaseException:
            if lease_acquired:
                self._execution_lock.release()
            raise
        callback = None
        try:
            result, callback = self._evaluate(self.selection_evaluator, snapshot)
            self.lifecycle.store.verify(snapshot.digest)
            if result["status"] == "succeeded":
                try:
                    valid = (
                        type(result.get("feasible")) is bool
                        and type(result.get("score")) in (int, float)
                        and math.isfinite(result["score"])
                    )
                except OverflowError:
                    valid = False
                if not valid:
                    result = {"status": "infrastructure_error", "error": "invalid_public_score"}
            completed = self.lifecycle.ledger.observe_time(self.run_id, now=self.lifecycle.now())
            # Save independently computed evidence before registering the incumbent.
            # Recovery may re-register identical public evidence, preserving its
            # original completion time; no algorithm execution or n charge repeats.
            with sqlite3.connect(self._publish_db) as connection:
                connection.execute(
                    "UPDATE publications SET status='evaluated',result=?,completed_at=? "
                    "WHERE request_key=?",
                    (canonical(result).decode(), completed, key),
                )
            return self._commit_publication(key, snapshot, result, completed)
        finally:
            if callback is not None and callback.is_alive():

                def release():
                    callback.join()
                    self._execution_lock.release()

                threading.Thread(target=release, daemon=True).start()
            else:
                self._execution_lock.release()

    def _commit_publication(
        self, key: str, snapshot: Snapshot, result: dict, completed_at: float
    ) -> dict:
        run = self.lifecycle.ledger.get_run(self.run_id)
        if run["state"] != "developing" or run["receipt"] is not None:
            raise LedgerError("Reconcile public checkpoints before beginning freeze")
        if result["status"] == "succeeded":
            self.lifecycle.restore_selection(
                self.run_id,
                "broker-publication:" + key,
                snapshot.digest,
                result["score"],
                feasible=result["feasible"],
                status=result["status"],
                completed_at=completed_at,
            )
        with sqlite3.connect(self._publish_db) as connection:
            connection.execute(
                "UPDATE publications SET status='complete' WHERE request_key=?", (key,)
            )
        return {"artifact_sha256": snapshot.digest, "ready": True, "public_result": result}

    def recover_publication(self, key: str, *, backend_cleanup_confirmed: bool) -> dict:
        """Controller restore of cached predeadline public evidence before freeze.

        A persisted evaluated result is re-registered with its original completion
        time, including after deadline. An interrupted evaluation may retry only
        during development with the identical artifact. Deadline never resets.
        """
        if backend_cleanup_confirmed is not True or self._execution_lock.locked():
            raise BrokerError("Backend cleanup must finish before public recovery")
        with self._requests_lock, sqlite3.connect(self._publish_db) as connection:
            row = connection.execute(
                "SELECT digest,status,result,completed_at FROM publications WHERE request_key=?",
                (key,),
            ).fetchone()
            if row is None:
                raise BrokerError("Unknown public request identity")
            if row[1] in {"evaluated", "complete"}:
                return self._commit_publication(
                    key,
                    self.lifecycle.store.verify(row[0]),
                    json.loads(row[2]),
                    row[3],
                )
            if row[1] not in {"running", "retry-authorized"}:
                raise BrokerError("Public request does not need infrastructure recovery")
            self._active()
            connection.execute(
                "UPDATE publications SET status='retry-authorized' WHERE request_key=?", (key,)
            )
            return {"artifact_sha256": row[0], "ready": False, "retry_authorized": True}

    def reconcile_publications_before_freeze(self, *, backend_cleanup_confirmed: bool) -> dict:
        """Controller barrier: restore cached evidence and report unresolved work.

        Invoke after developer/backend cleanup and before Lifecycle.freeze. Known
        late completions are explicitly disqualified. Interrupted executions with
        no durable outcome remain unresolved, so a caller must fail closed instead
        of silently freezing the baseline. This is not an agent socket operation.
        """
        if backend_cleanup_confirmed is not True or self._execution_lock.locked():
            raise BrokerError("Backend cleanup must finish before checkpoint reconciliation")
        run = self.lifecycle.ledger.get_run(self.run_id)
        if run["state"] != "developing" or run["receipt"] is not None:
            raise LedgerError("Reconcile checkpoints before beginning freeze")
        restored, disqualified, unresolved = [], [], []
        with self._requests_lock:
            with sqlite3.connect(self._publish_db) as connection:
                rows = connection.execute(
                    "SELECT request_key,digest,status,result,completed_at FROM publications "
                    "WHERE status NOT IN ('complete','late-disqualified') ORDER BY request_key"
                ).fetchall()
            for key, digest, status, encoded, completed in rows:
                if status != "evaluated" or completed is None:
                    unresolved.append({"key": key, "artifact_sha256": digest, "status": status})
                    continue
                if not run["started_at"] <= completed <= run["deadline_at"]:
                    with sqlite3.connect(self._publish_db) as connection:
                        connection.execute(
                            "UPDATE publications SET status='late-disqualified' "
                            "WHERE request_key=?",
                            (key,),
                        )
                    disqualified.append(key)
                    continue
                self._commit_publication(
                    key,
                    self.lifecycle.store.verify(digest),
                    json.loads(encoded),
                    completed,
                )
                restored.append(key)
        return {
            "restored": restored,
            "disqualified": disqualified,
            "unresolved": unresolved,
            "ready_to_freeze": not unresolved,
        }

    def handle(self, frame: dict) -> dict:
        """Handle a frame without exposing tracebacks, controller paths or secrets."""
        try:
            if (
                self._closed.is_set()
                or not isinstance(frame, dict)
                or len(canonical(frame)) + 1 > self.max_frame_bytes
            ):
                raise BrokerError("Closed broker or oversized request")
            operation = frame.get("op")
            if operation in {"publish", "submit"}:
                if (
                    not isinstance(frame.get("key"), str)
                    or not frame["key"]
                    or len(frame["key"]) > 256
                ):
                    raise BrokerError("Bounded stable request key required")
            if operation == "publish":
                response = self._publish(frame)
            elif operation == "submit":
                snapshot = self._snapshot(frame["archive_base64"])
                context = frame.get("request_context", {})
                if not isinstance(context, dict):
                    raise BrokerError("Request context must be an object")
                with self._requests_lock:
                    existing = next(
                        (
                            job
                            for job in self.lifecycle.ledger.jobs(self.run_id, kind="development")
                            if job["request_key"] == frame["key"]
                        ),
                        None,
                    )
                    if existing is None and self._execution_lock.locked():
                        raise BrokerError("Backend cleanup or evaluation is active")
                    if existing is None:
                        self._active()
                    job = self.lifecycle.submit(
                        self.run_id, frame["key"], snapshot.digest, request_context=context
                    )
                    if job["status"] == "accepted":
                        self._enqueue(job["job_id"])
                response = {
                    "job_id": job["job_id"],
                    "status": job["status"],
                    "artifact_sha256": snapshot.digest,
                    "counted": self.lifecycle.ledger.summary(self.run_id)["counted"],
                }
            elif operation == "result":
                self._active()
                job = self._job(frame["job_id"])
                response = {"job_id": job["job_id"], "ready": job["status"] in TERMINAL}
                if response["ready"]:
                    payload = self._feedback_payload(job)
                    digest = content_hash(payload)
                    response.update(
                        payload=payload,
                        payload_sha256=digest,
                        ack_token=self._token(job["job_id"], digest),
                    )
            elif operation == "ack":
                job = self._job(frame["job_id"])
                if job["status"] not in TERMINAL:
                    raise BrokerError("No terminal result to acknowledge")
                payload = self._feedback_payload(job)
                digest = content_hash(payload)
                if (
                    frame.get("payload_sha256") != digest
                    or not isinstance(frame.get("ack_token"), str)
                    or not hmac.compare_digest(
                        frame["ack_token"], self._token(job["job_id"], digest)
                    )
                ):
                    raise BrokerError("Invalid feedback acknowledgment")
                response = {
                    "receipt": self.lifecycle.ledger.deliver(
                        job["job_id"], payload, now=self.lifecycle.now()
                    )
                }
            elif operation == "status":
                run = self.lifecycle.ledger.get_run(self.run_id)
                response = {
                    "summary": self.lifecycle.ledger.summary(self.run_id),
                    "deadline_at": run["deadline_at"],
                    "backend_cleanup_pending": self._execution_lock.locked(),
                }
            else:
                raise BrokerError("Unknown agent operation")
            return dict(response, ok=True)
        except (
            BrokerError,
            LedgerError,
            ArtifactError,
            AdapterError,
            KeyError,
            OSError,
            EOFError,
            tarfile.TarError,
            sqlite3.Error,
            ValueError,
            TypeError,
            OverflowError,
        ) as error:
            return {
                "ok": False,
                "error": type(error).__name__,
                "message": "Request rejected by broker policy",
            }

    def recover(self, job_id: str, *, backend_cleanup_confirmed: bool) -> dict:
        """Controller recovery conserves identity/budget and requires backend cleanup."""
        if backend_cleanup_confirmed is not True or self._execution_lock.locked():
            raise BrokerError("Backend cleanup must finish before recovery")
        self._active()
        with self._requests_lock:
            job = self._job(job_id)
            if job["status"] == "running":
                self.lifecycle.ledger.finish_job(
                    job_id,
                    job["attempt"],
                    "infrastructure_error",
                    {"status": "infrastructure_error", "error": "controller_interrupted"},
                    now=self.lifecycle.now(),
                )
                job = self._job(job_id)
            if job["status"] == "infrastructure_error":
                self.lifecycle.ledger.retry_job(job_id, now=self.lifecycle.now())
            elif job["status"] != "accepted":
                raise BrokerError("Only interrupted infrastructure work can recover")
            self._enqueue(job_id)
            return self._job(job_id)

    def start(self, socket_path: str | Path) -> "ExperimentBroker":
        """Serve a fresh socket in a private directory; no controller files are exposed."""
        path = Path(socket_path).absolute()
        if self._server is not None or path.exists() or path.is_symlink():
            raise BrokerError("Broker socket must be fresh")
        if (
            not path.parent.is_dir()
            or path.parent.is_symlink()
            or path.parent.stat().st_uid != os.getuid()
            or path.parent.stat().st_mode & 0o077
        ):
            raise BrokerError("Socket directory must be private and controller-owned")
        broker = self

        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                self.connection.settimeout(broker.timeout_seconds + 1)
                try:
                    data = self.rfile.readline(broker.max_frame_bytes + 1)
                    if len(data) > broker.max_frame_bytes or not data.endswith(b"\n"):
                        response = {"ok": False, "error": "invalid_frame"}
                    else:
                        response = broker.handle(_object(data))
                    encoded = canonical(response) + b"\n"
                    if len(encoded) > broker.max_frame_bytes:
                        encoded = canonical({"ok": False, "error": "oversized_result"}) + b"\n"
                    self.wfile.write(encoded)
                except (BrokerError, OSError):
                    return

        self._server = _UnixServer(str(path), Handler)
        path.chmod(0o600)
        self._socket_path = path
        self._server_thread = threading.Thread(
            target=self._server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
        )
        self._server_thread.start()
        return self

    def close(self) -> None:
        if self._closed.is_set():
            return
        self._closed.set()
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._socket_path is not None:
            self._socket_path.unlink(missing_ok=True)
        self._worker.join(timeout=1)
        if self._execution_lock.locked():
            # An externally supervised backend may still be cleaning up. Never
            # permit another controller to redispatch while that lease exists.
            def release_controller():
                with self._execution_lock:
                    self._lock_file.close()

            threading.Thread(target=release_controller, daemon=True).start()
        else:
            self._lock_file.close()

    def __enter__(self) -> "ExperimentBroker":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()
