"""Run a frozen controller in a separate restricted JSONL process."""

from __future__ import annotations

import hashlib
import json
import os
import select
import selectors
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path


class CandidateError(Exception):
    """An accepted candidate failed; this is a completed zero-score evaluation."""

    def __init__(self, code: str, source_sha256: str | None = None):
        super().__init__(code)
        self.code = code
        self.source_sha256 = source_sha256


class SandboxSetupError(RuntimeError):
    """A trusted preflight failed; fields contain no candidate or case content."""

    def __init__(self, code: str, returncode: int | None = None, stderr_class: str = "none"):
        self.code = code
        self.returncode = returncode
        self.stderr_class = stderr_class
        super().__init__(
            f"sandbox preflight failed: code={code}, returncode={returncode}, "
            f"stderr_class={stderr_class}"
        )


def secure_readiness(directory: Path) -> None:
    """Probe the launcher before importing candidate code; never expose raw stderr."""
    if sys.platform != "linux" or os.geteuid() != 0:
        raise SandboxSetupError("linux_root_required")
    try:
        result = subprocess.run(
            [
                "setpriv",
                "--reuid=65534",
                "--regid=65534",
                "--clear-groups",
                "--no-new-privs",
                "/usr/local/bin/exec-candidate",
                "/usr/bin/true",
            ],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            cwd=directory,
            env={"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"},
            start_new_session=True,
            preexec_fn=_limits,
            timeout=5,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise SandboxSetupError("launcher_timeout") from exc
    except OSError as exc:
        raise SandboxSetupError("launcher_unavailable") from exc
    if result.returncode:
        stages = (
            (b"Landlock ABI", "landlock_abi_required"),
            (b"distribution filesystem sandbox setup failed", "filesystem_setup_failed"),
            (b"RTE sandbox setup failed", "seccomp_setup_failed"),
            (b"RTE solver exec failed", "executable_setup_failed"),
            (b"setpriv:", "uid_setup_failed"),
        )
        code = next((name for token, name in stages if token in result.stderr), "launcher_exit")
        reasons = (
            (b"Permission denied", "EACCES"),
            (b"Operation not permitted", "EPERM"),
            (b"Invalid argument", "EINVAL"),
            (b"No such file", "ENOENT"),
            (b"Function not implemented", "ENOSYS"),
        )
        stderr_class = next(
            (name for token, name in reasons if token in result.stderr),
            "other" if result.stderr else "none",
        )
        raise SandboxSetupError(code, result.returncode, stderr_class)


def candidate_bytes(path: Path) -> bytes:
    """Open once without following links and bound reads before allocating bytes."""
    maximum = 1_000_000
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError as exc:
        raise CandidateError("invalid_artifact") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise CandidateError("invalid_artifact")
        if before.st_size > maximum:
            raise CandidateError("artifact_too_large")
        chunks = []
        length = 0
        while length <= maximum:
            chunk = os.read(descriptor, maximum + 1 - length)
            if not chunk:
                break
            chunks.append(chunk)
            length += len(chunk)
        if length > maximum:
            raise CandidateError("artifact_too_large")
        after = os.fstat(descriptor)
        fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
        if length != before.st_size or any(getattr(before, f) != getattr(after, f) for f in fields):
            raise CandidateError("artifact_changed")
        return b"".join(chunks)
    except OSError as exc:
        raise CandidateError("invalid_artifact") from exc
    finally:
        os.close(descriptor)


def _limits():
    import resource

    resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024**2, 512 * 1024**2))
    resource.setrlimit(resource.RLIMIT_FSIZE, (1024**2, 1024**2))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))


class Candidate:
    def __init__(self, controller: Path, metadata: dict, *, secure: bool = True):
        content = candidate_bytes(controller)
        self.source_sha256 = hashlib.sha256(content).hexdigest()
        self.directory = Path(tempfile.mkdtemp(prefix="powergym-candidate-"))
        self.process = None
        self.selector = selectors.DefaultSelector()
        self.buffer = b""
        self.bridge_ready = False
        try:
            target = self.directory / "controller.py"
            target.write_bytes(content)
            bridge = Path(os.environ.get("POWERGYM_BRIDGE", "/usr/local/lib/controller_bridge.py"))
            if secure:
                if sys.platform != "linux" or os.geteuid() != 0:
                    raise RuntimeError("secure evaluation requires the Linux root-owned verifier")
                os.chown(self.directory, 65534, 65534)
                os.chown(target, 65534, 65534)
                secure_readiness(self.directory)
                command = [
                    "setpriv",
                    "--reuid=65534",
                    "--regid=65534",
                    "--clear-groups",
                    "--no-new-privs",
                    "/usr/local/bin/exec-candidate",
                    sys.executable,
                    "-I",
                    "-u",
                    str(bridge),
                    str(target),
                ]
            else:
                bridge = Path(__file__).resolve().parents[1] / "images/controller_bridge.py"
                command = [sys.executable, "-I", "-u", str(bridge), str(target)]
            self.process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                cwd=self.directory,
                env={
                    "PATH": "/usr/local/bin:/usr/bin:/bin",
                    "HOME": str(self.directory),
                    "OPENBLAS_NUM_THREADS": "1",
                    "OMP_NUM_THREADS": "1",
                },
                start_new_session=True,
                preexec_fn=_limits if secure else None,
            )
            self.selector.register(self.process.stdout, selectors.EVENT_READ)
            os.set_blocking(self.process.stdin.fileno(), False)
            self.deadline = time.monotonic() + 30.0
            initialization_deadline = min(self.deadline, time.monotonic() + 5.0)
            response = self.request({"metadata": metadata}, seconds=5.0)
            if response != {"bridge_ready": True}:
                raise RuntimeError("trusted candidate bridge did not initialize")
            self.bridge_ready = True
            response = self._receive(initialization_deadline)
            if response != {"ready": True}:
                raise CandidateError("candidate_initialization_protocol")
        except BaseException as exc:
            if isinstance(exc, CandidateError):
                exc.source_sha256 = self.source_sha256
            self.close()
            raise

    def _failure(self, code: str):
        if not self.bridge_ready:
            raise RuntimeError(f"trusted sandbox/bridge startup failed: {code}")
        raise CandidateError(code, self.source_sha256)

    def request(self, message: dict, *, seconds: float = 1.0) -> dict:
        deadline = min(self.deadline, time.monotonic() + seconds)
        payload = memoryview((json.dumps(message, allow_nan=False) + "\n").encode())
        while payload:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([], [self.process.stdin], [], remaining)[1]:
                self._failure("candidate_timeout")
            try:
                written = os.write(self.process.stdin.fileno(), payload)
            except BlockingIOError:
                continue
            except BrokenPipeError:
                self._failure("candidate_exit")
            payload = payload[written:]
        return self._receive(deadline)

    def _receive(self, deadline: float) -> dict:
        while True:
            if b"\n" in self.buffer:
                line, self.buffer = self.buffer.split(b"\n", 1)
                try:
                    response = json.loads(line)
                except (ValueError, UnicodeError):
                    self._failure("candidate_malformed_json")
                if not isinstance(response, dict):
                    self._failure("candidate_protocol")
                return response
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not self.selector.select(remaining):
                self._failure("candidate_timeout")
            data = os.read(self.process.stdout.fileno(), 4096)
            if not data:
                self._failure("candidate_exit")
            self.buffer += data
            if len(self.buffer) > 8192:
                self._failure("candidate_output_limit")

    def act(self, observation: dict) -> object:
        response = self.request({"observation": observation})
        if set(response) != {"action"}:
            self._failure("candidate_protocol")
        return response["action"]

    def close(self) -> None:
        if self.process is not None:
            if self.process.poll() is None:
                try:
                    os.killpg(self.process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                except PermissionError:
                    # macOS may report EPERM for an already-exited process group.
                    # Do not mask a real inability to terminate a live candidate.
                    if self.process.poll() is None:
                        self.process.kill()
            self.process.wait(timeout=5)
            if self.process.stdin:
                self.process.stdin.close()
            if self.process.stdout:
                self.process.stdout.close()
        self.selector.close()
        shutil.rmtree(self.directory)
