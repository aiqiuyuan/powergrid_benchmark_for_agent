"""Causal MAPDN/Pandapower canary with independently isolated local controllers."""

from __future__ import annotations

import hashlib
import json
import math
import os
import resource
import select
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import pandapower as pp

CHILD_ENV = {
    "PATH": "/usr/local/bin:/usr/bin:/bin",
    "LANG": "C.UTF-8",
    "HOME": "/nonexistent",
    "PYTHONHASHSEED": "0",
    "PYTHONDONTWRITEBYTECODE": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "OMP_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
}
METRIC = "mapdn33_canary_quality_v1"
ACTOR_ADDRESS_SPACE_BYTES = 384 << 20


class CandidateError(Exception):
    """An accepted candidate failed its bounded local control contract."""


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def candidate_bytes(path: Path) -> bytes:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError as exc:
        raise CandidateError("controller.py is missing, unreadable or a symlink") from exc
    try:
        status = os.fstat(descriptor)
        if not stat.S_ISREG(status.st_mode) or status.st_size > 1 << 20:
            raise CandidateError("controller.py must be a regular file of at most 1 MiB")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            code = stream.read((1 << 20) + 1)
        if len(code) > 1 << 20:
            raise CandidateError("controller.py grew beyond 1 MiB during snapshot")
        return code
    finally:
        os.close(descriptor)


def validate_action(value: object, bound: float) -> float:
    if not isinstance(value, list) or len(value) != 1:
        raise CandidateError("each actor must return a one-element action list")
    action = value[0]
    if (
        isinstance(action, bool)
        or not isinstance(action, (int, float))
        or not math.isfinite(action)
        or abs(action) > bound
    ):
        raise CandidateError("action must be finite and within the normalized bound")
    return float(action)


class Actor:
    """One candidate UID, cwd, process and history; JSON carries only its local data."""

    def __init__(self, code: bytes, metadata: dict, root: Path, *, secure: bool):
        self.process = None
        self.buffer = b""
        actor_id = int(metadata["actor_id"])
        directory = root / f"actor-{actor_id}"
        directory.mkdir(mode=0o700)
        source = directory / "controller.py"
        source.write_bytes(code)
        source.chmod(0o444)
        work = directory / "work"
        work.mkdir(mode=0o700)
        prefix = []
        worker = Path(__file__).with_name("actor_worker.py")
        if secure:
            uid = 64000 + actor_id
            os.chown(directory, 0, uid)
            directory.chmod(0o710)
            os.chown(work, uid, uid)
            worker = Path("/opt/mapdn/actor_worker.py")
            prefix = [
                "setpriv",
                "--no-new-privs",
                f"--reuid={uid}",
                f"--regid={uid}",
                "--clear-groups",
                "prlimit",
                f"--as={ACTOR_ADDRESS_SPACE_BYTES}",
                "--cpu=60",
                "--fsize=65536",
                "--nofile=32",
                "--nproc=16",
                "--core=0",
                "--",
                "mapdn-exec",
            ]
        self.process = subprocess.Popen(
            prefix + [sys.executable, "-I", str(worker), str(source)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            cwd=work,
            env={**CHILD_ENV, "DISTRIBUTION_READONLY_DIR": str(directory)} if secure else CHILD_ENV,
            start_new_session=True,
            bufsize=0,
        )
        os.set_blocking(self.process.stdin.fileno(), False)
        if self.exchange({"metadata": metadata}, timeout=15) != {"ready": True}:
            raise CandidateError("controller startup did not acknowledge initialization")

    def exchange(self, message: dict, *, timeout: float = 1.0) -> dict:
        deadline = time.monotonic() + timeout
        payload = memoryview(json.dumps(message, allow_nan=False).encode() + b"\n")
        if len(payload) > 65536:
            raise CandidateError("trusted local message exceeds 64 KiB")
        try:
            while payload:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not select.select([], [self.process.stdin], [], remaining)[1]:
                    raise CandidateError("controller stopped reading its bounded input channel")
                try:
                    written = os.write(self.process.stdin.fileno(), payload[:4096])
                except BlockingIOError:
                    continue
                payload = payload[written:]
        except (BrokenPipeError, OSError) as exc:
            raise CandidateError("controller exited before responding") from exc
        while b"\n" not in self.buffer:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([self.process.stdout], [], [], remaining)[0]:
                raise CandidateError("controller response timed out")
            chunk = os.read(self.process.stdout.fileno(), 4096)
            if not chunk:
                raise CandidateError("controller closed its response channel")
            self.buffer += chunk
            if len(self.buffer) > 65536:
                raise CandidateError("controller response exceeds 64 KiB")
        line, self.buffer = self.buffer.split(b"\n", 1)
        try:
            response = json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise CandidateError("controller response is not JSON") from exc
        if not isinstance(response, dict):
            raise CandidateError("controller response must be a JSON object")
        return response

    def close(self) -> None:
        if self.process is not None:
            try:
                os.killpg(self.process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except PermissionError:
                # macOS may reject killpg for an already-exited child group.
                # A live child must still be terminated; never mask its verdict.
                if self.process.poll() is None:
                    self.process.kill()
            self.process.wait(timeout=5)
            self.process.stdin.close()
            self.process.stdout.close()


def secure_readiness() -> None:
    if sys.platform != "linux" or os.geteuid() != 0:
        raise RuntimeError("secure MAPDN evaluation requires Linux root")
    if not all(shutil.which(tool) for tool in ("setpriv", "prlimit", "mapdn-exec")):
        raise RuntimeError("candidate sandbox tools are missing")
    if not Path("/opt/mapdn/actor_worker.py").is_file():
        raise RuntimeError("public actor worker is missing")
    probe = subprocess.run(
        [
            "setpriv",
            "--no-new-privs",
            "--reuid=64000",
            "--regid=64000",
            "--clear-groups",
            "mapdn-exec",
            "/usr/bin/true",
        ],
        env=CHILD_ENV,
        capture_output=True,
        timeout=5,
    )
    if probe.returncode:
        raise RuntimeError("candidate sandbox readiness probe failed")


def local_observation(net, actor_id: int, step: int, timestamp: str) -> tuple[dict, dict]:
    pv = net.sgen.iloc[actor_id]
    region = net.bus.index[net.bus.zone == pv["name"]]
    if int(pv.bus) not in region:
        raise RuntimeError("PV is not inside its declared local region")
    demand = (
        net.res_load.groupby(net.load.bus)[["p_mw", "q_mvar"]].sum().reindex(region, fill_value=0)
    )
    results = net.res_bus.loc[region]
    observation = {
        "interval_index": step,
        "timestamp": timestamp,
        "pv_voltage_pu": [float(net.res_bus.at[pv.bus, "vm_pu"])],
        "pv_active_mw": [float(pv.p_mw)],
        "pv_reactive_mvar": [float(pv.q_mvar)],
        "region_bus_ids": [int(bus) for bus in region],
        "region_demand_p_mw": demand.p_mw.tolist(),
        "region_demand_q_mvar": demand.q_mvar.tolist(),
        "region_voltage_pu": results.vm_pu.tolist(),
        "region_angle_degree": results.va_degree.tolist(),
    }
    metadata = {
        "actor_id": actor_id,
        "pv_count": 1,
        "pv_bus_id": int(pv.bus),
        "region_bus_ids": [int(bus) for bus in region],
        "action_bound": 0.8,
        "interval_hours": 0.05,
        "voltage_bounds_pu": [0.95, 1.05],
    }
    return metadata, observation


def measure(net, manifest: dict) -> dict:
    voltage = net.res_bus.vm_pu.to_numpy(dtype=float)
    if not np.isfinite(voltage).all():
        raise RuntimeError("nonfinite bus voltage after converged power flow")
    low, high = manifest["voltage_bounds_pu"]
    violations = np.maximum(low - voltage, 0) + np.maximum(voltage - high, 0)
    compliant = violations <= manifest["voltage_tolerance_pu"]
    # This specific network has only lines, loads, PV sgens and an external grid.
    loss = float(net.res_line.pl_mw.sum())
    balance = float(net.res_ext_grid.p_mw.sum() + net.res_sgen.p_mw.sum() - net.res_load.p_mw.sum())
    residual = abs(balance - loss)
    if (
        not math.isfinite(loss)
        or loss < -1e-10
        or residual > manifest["power_balance_tolerance_mw"]
    ):
        raise RuntimeError("line-loss and full-network active-power balance disagree")
    return {
        "all_buses_compliant": bool(compliant.all()),
        "compliant_bus_count": int(compliant.sum()),
        "voltage_violation_sum_pu": float(violations.sum()),
        "worst_undervoltage_pu": float(max(0, low - voltage.min())),
        "worst_overvoltage_pu": float(max(0, voltage.max() - high)),
        "actual_loss_mw": max(0.0, loss),
        "power_balance_residual_mw": residual,
        "q_effort_mvar": float(net.res_sgen.q_mvar.abs().sum()),
    }


def evaluate(candidate: Path, case_dir: Path, *, secure: bool = True) -> dict:
    started = time.monotonic()
    if secure:
        secure_readiness()
    manifest_path = case_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    if (
        manifest["case_id"] != "mapdn33-first-complete-day-causal-v1"
        or manifest["horizon"] != 480
        or manifest["normalized_action_bound"] != 0.8
        or manifest["interval_hours"] != 0.05
    ):
        raise RuntimeError("case manifest does not match the frozen canary contract")
    for name, expected in manifest["files"].items():
        if name not in {"model.p", "trajectory.json"} or sha256(case_dir / name) != expected:
            raise RuntimeError("frozen case checksum mismatch")
    trajectory = json.loads((case_dir / "trajectory.json").read_text())
    net = pp.from_pickle(case_dir / "model.p")
    if (len(net.bus), len(net.load), len(net.sgen), len(net.line)) != (33, 32, 6, 32):
        raise RuntimeError("unexpected network dimensions")
    for element in (
        "gen",
        "storage",
        "shunt",
        "trafo",
        "trafo3w",
        "dcline",
        "impedance",
        "ward",
        "xward",
        "motor",
    ):
        if len(net[element]):
            raise RuntimeError("unsupported loss-bearing or power-injecting element")
    if any(
        len(trajectory[key]) != 480
        for key in ("timestamps", "pv_active", "load_active", "load_reactive")
    ):
        raise RuntimeError("the frozen trajectory must contain exactly 480 intervals")
    result = {
        "case_id": manifest["case_id"],
        "metric_name": METRIC,
        "valid": False,
        "reward": 0.0,
        "scheduled_intervals": 480,
        "completed_intervals": 0,
        "pf_calls": 0,
        "secure_execution": secure,
        "error": None,
        "manifest_sha256": sha256(manifest_path),
        "steps": [],
    }
    actors = []
    try:
        code = candidate_bytes(candidate)
        result["candidate_sha256"] = hashlib.sha256(code).hexdigest()
        actions = np.array(manifest["initial_actions"], dtype=float)
        capacities = np.array(manifest["apparent_power_mva"], dtype=float)
        with tempfile.TemporaryDirectory(prefix="mapdn-actors-") as temporary:
            root = Path(temporary)
            if secure:
                root.chmod(0o711)
            try:
                for step in range(480):
                    if time.monotonic() - started > 240:
                        raise CandidateError("whole-episode runtime exceeded 240 seconds")
                    active = np.array(trajectory["pv_active"][step], dtype=float)
                    if (active < 0).any() or (active > capacities).any():
                        raise RuntimeError("frozen PV powers exceed the declared capability")
                    capability = np.sqrt(capacities**2 - active**2)
                    net.sgen.loc[:, "p_mw"] = active
                    net.sgen.loc[:, "q_mvar"] = actions * capability
                    net.load.loc[:, "p_mw"] = trajectory["load_active"][step]
                    net.load.loc[:, "q_mvar"] = trajectory["load_reactive"][step]
                    try:
                        pp.runpp(net, **manifest["pf"])
                        result["pf_calls"] += 1
                        observations = []
                        for actor_id in range(6):
                            metadata, observation = local_observation(
                                net, actor_id, step, trajectory["timestamps"][step]
                            )
                            if step == 0:
                                metadata["apparent_power_mva"] = [float(capacities[actor_id])]
                                actor = Actor.__new__(Actor)
                                actors.append(actor)
                                actor.__init__(code, metadata, root, secure=secure)
                            observations.append(observation)
                        actions = np.array(
                            [
                                validate_action(
                                    actor.exchange({"observation": observation}).get("action"), 0.8
                                )
                                for actor, observation in zip(actors, observations, strict=True)
                            ]
                        )
                        net.sgen.loc[:, "q_mvar"] = actions * capability
                        pp.runpp(net, **manifest["pf"])
                        result["pf_calls"] += 1
                    except pp.LoadflowNotConverged as exc:
                        raise CandidateError(
                            "power flow did not converge; complete-episode reward is zero"
                        ) from exc
                    record = measure(net, manifest)
                    record["interval_index"] = step
                    result["steps"].append(record)
                    result["completed_intervals"] += 1
            finally:
                for actor in actors:
                    actor.close()
    except CandidateError as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    rows = result["steps"]
    result["valid"] = len(rows) == 480 and result["error"] is None
    result["metrics"] = {
        "all_bus_time_compliance": sum(row["all_buses_compliant"] for row in rows) / 480,
        "bus_time_compliance": sum(row["compliant_bus_count"] for row in rows) / (480 * 33),
        "actual_loss_mwh": sum(row["actual_loss_mw"] * 0.05 for row in rows),
        "voltage_violation_pu_hours": sum(row["voltage_violation_sum_pu"] * 0.05 for row in rows),
        "worst_undervoltage_pu": max((row["worst_undervoltage_pu"] for row in rows), default=0),
        "worst_overvoltage_pu": max((row["worst_overvoltage_pu"] for row in rows), default=0),
        "max_power_balance_residual_mw": max(
            (row["power_balance_residual_mw"] for row in rows), default=0
        ),
        "q_effort_mvar_hours": sum(row["q_effort_mvar"] * 0.05 for row in rows),
    }
    if result["valid"]:
        result["reward"] = 0.8 * result["metrics"]["bus_time_compliance"] + 0.2 / (
            1 + result["metrics"]["actual_loss_mwh"]
        )
    result["wall_seconds"] = time.monotonic() - started
    result["peak_rss"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    result["peak_rss_unit"] = "KiB" if sys.platform == "linux" else "bytes"
    return result
