"""Native RTE solver execution with separately pinned, external official checking.

The upstream solver, data and checker are user-supplied dependencies. They are
not redistributed by this package. Trusted-local acceptance proves integration,
not hostile-code isolation or an original competition leaderboard position.
"""

import hashlib
import importlib.util
import json
import math
import os
import re
import shutil
import stat
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

from .adapters import validate_candidate
from .artifacts import ArtifactStore, canonical
from .process import ProcessResult, run_process


class RTEAdapterError(ValueError):
    """The pinned RTE execution contract is incomplete or changed."""


NATIVE_ENTRYPOINT = ["python3", "solver.py", "--instance", "{input}", "--output", "{output}"]


def feedback_payload(result: dict) -> dict:
    """Project trusted aggregate fields; candidate output stays in controller audit.

    The caller must use an actual RTEAdapter result, not candidate-supplied JSON.
    This projection is the fixed protected-feedback schema for the canary.
    """
    status, feasible = result.get("status"), result.get("feasible")
    if status not in {"succeeded", "candidate_error", "infrastructure_error", "timeout"}:
        raise RTEAdapterError("Unknown result status")
    if type(feasible) is not bool or (status == "succeeded") != feasible:
        raise RTEAdapterError("Inconsistent trusted result feasibility")
    score, objective = result.get("score"), result.get("raw_objective")
    if type(score) not in {int, float} or not math.isfinite(score):
        raise RTEAdapterError("Finite trusted score required")
    if feasible and (type(objective) not in {int, float} or not math.isfinite(objective)):
        raise RTEAdapterError("Finite official objective required")
    return {
        "schema_version": "rte-aggregate-feedback-v1",
        "status": status,
        "feasible": feasible,
        "score": score,
        "raw_objective": objective if feasible else None,
    }


def _regular(path: Path, limit: int) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise RTEAdapterError("A bounded regular file is required")
        value = stream.read(limit + 1)
    if len(value) > limit:
        raise RTEAdapterError("File exceeds configured adapter bound")
    return value


def _check_digest(value: str) -> None:
    if not isinstance(value, str) or not re.fullmatch("[0-9a-f]{64}", value):
        raise RTEAdapterError("An explicit SHA-256 pin is required")


def _pinned(path: Path, expected: str) -> bytes:
    _check_digest(expected)
    value = _regular(path, 256 << 20)
    if hashlib.sha256(value).hexdigest() != expected:
        raise RTEAdapterError(f"Pinned dependency changed: {path.name}")
    return value


class RTEAdapter:
    """Execute complete native solvers on locked panels, then independently score.

    A certified_runner is a trusted controller-supplied execution transport. Its
    certification hash records an external attestation; this adapter does not
    certify an arbitrary callback or implement Docker resource enforcement.
    """

    def __init__(
        self,
        store: ArtifactStore,
        *,
        official_module: str | Path,
        official_module_sha256: str,
        support_root: str | Path,
        source_lock_sha256: str,
        checker_sha256: str,
        work_root: str | Path,
        python_executable: str | Path = sys.executable,
    ):
        self.store = store
        self.official_module = Path(official_module).absolute()
        self.official_module_sha256 = official_module_sha256
        self.support_root = Path(support_root).absolute()
        self.source_lock_sha256 = source_lock_sha256
        self.checker_sha256 = checker_sha256
        self.work_root = Path(work_root).absolute()
        self.python_executable = str(python_executable)
        for value in (official_module_sha256, source_lock_sha256, checker_sha256):
            _check_digest(value)

    def validate(self, digest: str):
        """Validate the native candidate ABI before broker admission or execution."""
        snapshot = self.store.verify(digest)
        manifest = validate_candidate(snapshot.path, "rte-maintenance")
        if "solver.py" not in manifest["source"]:
            raise RTEAdapterError("RTE native candidate must include executable solver.py")
        if manifest["entrypoint"] != NATIVE_ENTRYPOINT:
            raise RTEAdapterError("RTE requires the declared native solver entrypoint")
        return snapshot

    def _checker(self):
        _pinned(self.official_module, self.official_module_sha256)
        lock = json.loads(_pinned(self.support_root / "source-lock.json", self.source_lock_sha256))
        name = "RTE_ChallengeROADEF2020_checker.py"
        if lock.get("files", {}).get(name, {}).get("sha256") != self.checker_sha256:
            raise RTEAdapterError("Source lock does not identify the selected checker")
        _pinned(self.support_root / "vendor" / name, self.checker_sha256)
        spec = importlib.util.spec_from_file_location(
            f"powergrid_external_rte_{self.official_module_sha256}", self.official_module
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        if not callable(getattr(module, "check_solution", None)):
            raise RTEAdapterError("Pinned checker adapter lacks check_solution")
        return module.check_solution

    def evaluate(
        self,
        digest: str,
        panel_path: str | Path,
        *,
        panel_sha256: str,
        data_root: str | Path,
        trusted_local: bool = False,
        certified_runner: Callable | None = None,
        backend_certification_sha256: str | None = None,
    ) -> dict:
        if certified_runner is None and not trusted_local:
            raise RTEAdapterError("Require trusted-local acceptance or a certified backend")
        if certified_runner is not None:
            _check_digest(backend_certification_sha256)
        panel_path = Path(panel_path).absolute()
        panel = json.loads(_pinned(panel_path, panel_sha256))
        cases, seconds, seed = panel.get("cases"), panel.get("seconds_per_case"), panel.get("seed")
        if (
            panel.get("task_id") != "rte-maintenance"
            or panel.get("split")
            not in {"development", "public-selection", "protected-feedback", "final-test"}
            or not isinstance(cases, list)
            or not cases
            or type(seconds) not in {int, float}
            or not math.isfinite(seconds)
            or seconds <= 0
            or type(seed) is not int
            or seed < 0
        ):
            raise RTEAdapterError("Explicit nonempty panel, positive deadline and seed required")
        dataset = Path(data_root).resolve()
        inputs = []
        identifiers = set()
        for case in cases:
            path = case.get("path")
            identifier = case.get("id")
            if (
                not isinstance(path, str)
                or not path
                or "\\" in path
                or Path(path).is_absolute()
                or ".." in Path(path).parts
                or not isinstance(identifier, str)
                or not identifier
                or identifier in identifiers
            ):
                raise RTEAdapterError("Distinct case identifiers and safe relative paths required")
            identifiers.add(identifier)
            instance = dataset / path
            if dataset not in instance.resolve().parents:
                raise RTEAdapterError("Instance escapes the locked data root")
            inputs.append(_pinned(instance, case.get("sha256")))
        snapshot = self.validate(digest)
        checker = self._checker()
        self.work_root.mkdir(parents=True, exist_ok=True)
        records = []
        for case, content in zip(cases, inputs, strict=True):
            with tempfile.TemporaryDirectory(prefix="rte-case-", dir=self.work_root) as temporary:
                workspace = Path(temporary)
                algorithm = workspace / "algorithm"
                shutil.copytree(
                    snapshot.path, algorithm, ignore=shutil.ignore_patterns("_manifest.json")
                )
                instance, output = workspace / "instance.json", workspace / "schedule.txt"
                instance.write_bytes(content)
                instance.chmod(0o444)
                argv = [
                    self.python_executable,
                    "-E",
                    "-s",
                    str(algorithm / "solver.py"),
                    "--instance",
                    str(instance),
                    "--output",
                    str(output),
                    "--time-limit",
                    str(seconds),
                    "--seed",
                    str(seed),
                ]
                environment = {
                    "PATH": os.defpath,
                    "HOME": str(workspace),
                    "TMPDIR": str(workspace),
                    "PYTHONDONTWRITEBYTECODE": "1",
                    "PYTHONHASHSEED": str(seed),
                    "OMP_NUM_THREADS": "1",
                    "OPENBLAS_NUM_THREADS": "1",
                    "MKL_NUM_THREADS": "1",
                }
                process = (
                    run_process(argv, cwd=algorithm, timeout_seconds=seconds, env=environment)
                    if certified_runner is None
                    else certified_runner(
                        argv, cwd=algorithm, timeout_seconds=seconds, env=environment
                    )
                )
                if not isinstance(process, ProcessResult):
                    raise RTEAdapterError("Execution backend returned an invalid process receipt")
                record = {
                    "case": case["id"],
                    "instance_sha256": case["sha256"],
                    "status": process.status,
                    "wall_seconds": process.elapsed_seconds,
                    "returncode": process.returncode,
                    "stderr": process.stderr[-2000:],
                    "valid": False,
                    "objective": None,
                }
                if process.status == "succeeded":
                    try:
                        schedule = _regular(output, 4 << 20)
                        record["schedule_sha256"] = hashlib.sha256(schedule).hexdigest()
                    except (OSError, RTEAdapterError) as error:
                        record.update(status="candidate_error", error=type(error).__name__)
                    else:
                        try:
                            checked = checker(instance, output, self.support_root)
                            objective = checked.get("objective")
                            if type(checked.get("valid")) is not bool:
                                raise ValueError("Checker validity must be explicit")
                            if checked["valid"] and (
                                type(objective) not in {int, float} or not math.isfinite(objective)
                            ):
                                raise ValueError("A valid schedule requires a finite objective")
                            canonical(checked)
                            record.update(checked)
                            record["status"] = (
                                "succeeded" if checked["valid"] else "candidate_error"
                            )
                            if not checked["valid"]:
                                record["objective"] = None
                        except Exception as error:
                            record.update(
                                status="infrastructure_error",
                                valid=False,
                                objective=None,
                                error=type(error).__name__,
                            )
                records.append(record)
                self.store.verify(digest)
        feasible = all(record["valid"] for record in records)
        objective = (
            sum(record["objective"] for record in records) / len(records) if feasible else None
        )
        statuses = {record["status"] for record in records}
        status = (
            "succeeded"
            if feasible
            else "infrastructure_error"
            if "infrastructure_error" in statuses
            else "timeout"
            if "timeout" in statuses
            else "candidate_error"
        )
        return {
            "status": status,
            "feasible": feasible,
            "score": objective if feasible else 0.0,
            "raw_objective": objective,
            "selection_direction": "lower",
            "aggregation": "mean-official-objective",
            "algorithm_executed": True,
            "candidate_sha256": digest,
            "panel_sha256": panel_sha256,
            "split": panel["split"],
            "protocol": panel.get("protocol"),
            "seed": seed,
            "checker_sha256": self.checker_sha256,
            "checker_adapter_sha256": self.official_module_sha256,
            "source_lock_sha256": self.source_lock_sha256,
            "execution_scope": "trusted-local-calibration"
            if certified_runner is None
            else "externally-certified-backend",
            "backend_certification_sha256": backend_certification_sha256,
            "cases": records,
        }
