"""Complete-day trusted formal evaluation, independent of historical tool modules."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import time
from pathlib import Path

from backend import Backend, validate_action
from candidate import Candidate, CandidateError
from scoring import summarize

EXPECTED_CASE_SHA256 = "8930e4ded79ebf35566cf4ca168ec661c4e29cff624487721b77d4ea3d8f7922"
EXPECTED_DATA_LOCK_SHA256 = "71e9800367710dcb33beb6b07336efa685f92bcdf9459677e11dd88e60ed7ce0"


def verify_data(directory: Path) -> None:
    if hashlib.sha256((directory / "case.json").read_bytes()).hexdigest() != EXPECTED_CASE_SHA256:
        raise ValueError("case differs from frozen formal release")
    content = (directory / "data-lock.json").read_bytes()
    if hashlib.sha256(content).hexdigest() != EXPECTED_DATA_LOCK_SHA256:
        raise ValueError("formal data lock differs from release")
    for name, expected in json.loads(content)["files"].items():
        target = directory / name
        if target.is_symlink() or not target.resolve(strict=True).is_relative_to(
            directory.resolve()
        ):
            raise ValueError("invalid trusted case file")
        if hashlib.sha256(target.read_bytes()).hexdigest() != expected:
            raise ValueError("trusted data hash mismatch")


def evaluate(controller: Path, data: Path, *, secure: bool = True) -> dict:
    start = time.monotonic()
    verify_data(data)
    candidate = None
    with tempfile.TemporaryDirectory(prefix="powergym-formal-case-") as directory:
        private = Path(directory) / "case"
        shutil.copytree(data, private)
        private.chmod(0o700)
        backend = Backend(private)
        rows, failure = [], None
        try:
            candidate = Candidate(controller, backend.metadata, secure=secure)
            for _ in range(24):
                action = candidate.act(backend.observation())
                try:
                    validate_action(action)
                except ValueError as exc:
                    raise CandidateError("invalid_action", candidate.source_sha256) from exc
                try:
                    rows.append(backend.advance(action))
                except ValueError as exc:
                    raise CandidateError("invalid_trajectory", candidate.source_sha256) from exc
        except CandidateError as exc:
            failure = exc
        finally:
            if candidate is not None:
                candidate.close()
        result = summarize(
            rows,
            backend.initial_energy,
            backend.capacity,
            failure=failure.code if failure else None,
        )
        result.update(
            {
                "case_id": backend.case["id"],
                "track": backend.metadata["track"],
                "wall_seconds": time.monotonic() - start,
                "candidate_sha256": candidate.source_sha256 if candidate else failure.source_sha256,
                "sandbox": "linux-uid-seccomp-landlock" if secure else "local-numerical-only",
                "pf_calls": backend.pf_calls,
                "failed_pf_calls": backend.failed_pf_calls,
                "trajectory": rows,
            }
        )
        return result
