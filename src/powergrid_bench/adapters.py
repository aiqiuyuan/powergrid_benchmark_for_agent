"""Executable algorithm ABI and independently checked trusted local fixtures.

Real energy tasks need certified native harnesses and an isolated backend.
This runner deliberately refuses implicit execution of untrusted candidates.
"""

import json
import math
import os
import re
import shutil
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .artifacts import ArtifactStore, canonical
from .process import ProcessResult, run_process


class AdapterError(ValueError):
    """A candidate or input violates the executable algorithm contract."""


def _relative_file(root: Path, value: str) -> Path:
    if (
        not isinstance(value, str)
        or not value
        or "\\" in value
        or ":" in value
        or PurePosixPath(value).is_absolute()
        or any(part in {"", ".", ".."} for part in value.split("/"))
    ):
        raise AdapterError("Source and dependency paths must be safe relative files")
    path = root / value
    if not path.is_file() or path.is_symlink() or root.resolve() not in path.resolve().parents:
        raise AdapterError("Required source/dependency file is missing or escapes artifact")
    return path


def _load_object(path: Path, limit: int = 1_000_000) -> dict:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        raise AdapterError("Missing, linked or oversized JSON response")

    def reject_constant(value):
        raise ValueError(f"Nonfinite JSON value: {value}")

    try:
        with path.open("rb") as stream:
            data = stream.read(limit + 1)
        if len(data) > limit:
            raise AdapterError("JSON response exceeds bound")
        value = json.loads(data, parse_constant=reject_constant)
        if not isinstance(value, dict):
            raise AdapterError("JSON response must be an object")
        canonical(value)
        return value
    except (ValueError, UnicodeError, OSError, OverflowError) as error:
        raise AdapterError("Malformed JSON object") from error


def validate_candidate(root: str | Path, task_id: str) -> dict:
    root = Path(root)
    manifest = _load_object(root / "candidate.json")
    if manifest.get("kind") != "algorithm" or manifest.get("task_id") != task_id:
        raise AdapterError("Require an executable algorithm for the requested task")
    sources = manifest.get("source")
    if (
        not isinstance(sources, list)
        or not sources
        or not all(isinstance(value, str) for value in sources)
        or len(set(sources)) != len(sources)
    ):
        raise AdapterError("Explicit distinct source files required")
    for value in sources:
        _relative_file(root, value)
    _relative_file(root, manifest.get("dependency_lock"))
    argv = manifest.get("entrypoint")
    if (
        not isinstance(argv, list)
        or not argv
        or not all(isinstance(value, str) and value and "\x00" not in value for value in argv)
        or argv.count("{input}") != 1
        or argv.count("{output}") != 1
    ):
        raise AdapterError("Entrypoint requires argv and exact input/output placeholders")
    executable = argv[0]
    if "/" in executable or executable in {".", ".."}:
        _relative_file(root, executable)
    elif not re.fullmatch(r"[a-zA-Z0-9_.+-]+", executable):
        raise AdapterError("Invalid executable name")
    if any(
        ("{" in value or "}" in value) and value not in {"{input}", "{output}"} for value in argv
    ):
        raise AdapterError("Unknown entrypoint placeholder")
    return manifest


def _check_request(value: object) -> None:
    private_keys = {"private_labels", "test_labels", "final_labels", "provider_api_key"}
    if isinstance(value, dict):
        if private_keys.intersection(value):
            raise AdapterError("Private labels/provider credentials cannot enter candidate request")
        for item in value.values():
            _check_request(item)
    elif isinstance(value, list):
        for item in value:
            _check_request(item)


@dataclass(frozen=True)
class EvaluationResult:
    status: str
    checker: dict | None
    output: dict | None
    process: ProcessResult
    error: str | None = None


def execute_algorithm(
    store: ArtifactStore,
    digest: str,
    request: dict,
    *,
    task_id: str,
    checker: Callable[[dict, dict], dict],
    work_root: str | Path,
    timeout_seconds: float,
    trusted_local: bool = False,
    max_output_bytes: int = 1_000_000,
) -> EvaluationResult:
    """Run fresh code, then a trusted independent checker outside the candidate process.

    The flag acknowledges that the fixture is trusted; it is not a security sandbox.
    The caller must supervise the entire checker/batch deadline in production.
    """
    if not trusted_local:
        raise AdapterError("Execution requires explicit trusted-local fixture scope")
    if not isinstance(request, dict):
        raise AdapterError("Request must be an object")
    _check_request(request)
    snapshot = store.verify(digest)
    manifest = validate_candidate(snapshot.path, task_id)
    root = Path(work_root).absolute()
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="case-", dir=root) as temporary:
        workspace = Path(temporary)
        candidate = workspace / "algorithm"
        shutil.copytree(snapshot.path, candidate, ignore=shutil.ignore_patterns("_manifest.json"))
        request_path, output_path = workspace / "request.json", workspace / "output.json"
        payload = dict(request, artifact_sha256=digest)
        request_path.write_bytes(canonical(payload))
        argv = [
            str(request_path)
            if value == "{input}"
            else str(output_path)
            if value == "{output}"
            else value
            for value in manifest["entrypoint"]
        ]
        if argv[0] == "python3":
            argv[0] = sys.executable
        elif "/" in argv[0] or (candidate / argv[0]).is_file():
            argv[0] = str(candidate / argv[0])
        environment = {
            "PATH": os.environ.get("PATH", os.defpath),
            "HOME": str(workspace),
            "TMPDIR": str(workspace),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONHASHSEED": "0",
        }
        process = run_process(
            argv,
            cwd=candidate,
            timeout_seconds=timeout_seconds,
            max_output_bytes=max_output_bytes,
            env=environment,
        )
        store.verify(digest)
        if process.status != "succeeded":
            return EvaluationResult(process.status, None, None, process)
        try:
            output = _load_object(output_path, max_output_bytes)
        except AdapterError as error:
            return EvaluationResult("candidate_error", None, None, process, str(error))
        try:
            checked = checker(payload, output)
            if (
                not isinstance(checked, dict)
                or type(checked.get("feasible")) is not bool
                or type(checked.get("score")) not in (int, float)
                or not math.isfinite(checked["score"])
            ):
                raise ValueError("Checker must return a finite score and explicit feasibility")
            canonical(checked)
        except Exception as error:
            return EvaluationResult(
                "infrastructure_error",
                None,
                output,
                process,
                f"Independent checker failed: {type(error).__name__}",
            )
        status = "succeeded" if checked["feasible"] else "candidate_error"
        return EvaluationResult(status, checked, output, process)
