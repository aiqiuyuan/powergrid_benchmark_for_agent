"""Run a frozen, non-LLM baseline matrix in a dedicated CPU-job Docker daemon.

Invocation: python runtime_cluster.py --manifest /new-batch/job-network.json
No submission, registry access, model gateway or historical mutation is performed.
"""

from __future__ import annotations

import argparse
import errno
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

ACCEPTANCE_SHA256 = "6dc486d560d47c5e98ddc23fac288a793c5f8e335a375c20ee7cb18fb011745c"
COPY_POOL_WRAPPER = """import hashlib, json, os, pathlib, shutil, subprocess, sys
os.umask(0o077)
source = pathlib.Path(sys.argv[1])
target = pathlib.Path(sys.argv[2])
expected = json.loads(sys.argv[3])
shutil.copytree(source, target, dirs_exist_ok=True)
target.chmod(0o700)
for name, checksum in expected.items():
    with (target / name).open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != checksum:
            raise RuntimeError('private pool copy checksum mismatch')
raise SystemExit(subprocess.run(sys.argv[4:], check=False).returncode)
"""
# DinD startup and ordinary owned-mount cleanup are copied from the accepted
# 2026-10-16 bootstrap, preserving its timeout and ownership checks.


def docker_info(environment: dict, *, timeout: float) -> str:
    """Return a bounded readiness state without exposing command output."""
    try:
        result = subprocess.run(
            ["docker", "info"],
            env=environment,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return "timeout"
    return "ready" if result.returncode == 0 else "not_ready"


def reject_existing_daemon(environment: dict) -> None:
    state = docker_info(environment, timeout=10)
    if state == "ready":
        raise RuntimeError("Refusing a pod with an existing Docker daemon")
    if state == "timeout":
        raise RuntimeError("Existing Docker daemon state is unknown after probe timeout")


def wait_for_daemon(daemon, environment: dict, *, startup_seconds: float = 90) -> None:
    deadline = time.monotonic() + startup_seconds
    while (remaining := deadline - time.monotonic()) > 0:
        if daemon.poll() is not None:
            raise RuntimeError("Dedicated build daemon exited before readiness")
        if docker_info(environment, timeout=min(5, remaining)) == "ready":
            return
        # A slow daemon may time out an individual client while still starting.
        if (remaining := deadline - time.monotonic()) > 0:
            time.sleep(min(1, remaining))
    raise RuntimeError("Dedicated build daemon startup timed out")


def cleanup_diagnostic(operation: str, exc: BaseException) -> dict:
    """Record only trusted operation names and finite OS classifications."""
    number = exc.errno if isinstance(exc, OSError) else None
    return {
        "operation": operation,
        "error_type": type(exc).__name__,
        "errno": number,
        "errno_name": errno.errorcode.get(number, "OTHER") if number is not None else None,
    }


def owned_mounts(scratch: Path) -> list[tuple[Path, str]]:
    """Read this namespace's mounts, selecting only strict scratch descendants."""
    selected = []
    for line in Path("/proc/self/mountinfo").read_text().splitlines():
        fields = line.split()
        separator = fields.index("-")
        mount = Path(re.sub(r"\\([0-7]{3})", lambda m: chr(int(m[1], 8)), fields[4]))
        if mount != scratch and mount.is_relative_to(scratch):
            selected.append((mount, fields[separator + 1]))
    return sorted(selected, key=lambda row: len(row[0].parts), reverse=True)


def owned_processes_running(scratch: Path) -> bool:
    """Check daemon/shim arguments and runtime pidfiles before detaching mounts."""
    for process in Path("/proc").iterdir():
        if not process.name.isdecimal():
            continue
        try:
            with (process / "cmdline").open("rb") as stream:
                command = stream.read(65537)
        except (FileNotFoundError, ProcessLookupError):
            continue
        if len(command) > 65536:
            raise RuntimeError("Cannot classify an oversized cleanup process command")
        for argument in command.decode(errors="surrogateescape").split("\0"):
            value = argument.split("=", 1)[-1].removeprefix("unix://")
            if value.startswith("/") and Path(value).is_relative_to(scratch):
                return True
    for path in [scratch / "docker.pid", *(scratch / "exec").rglob("*.pid")]:
        if not path.exists():
            continue
        if path.is_symlink() or not path.resolve().is_relative_to(scratch):
            raise RuntimeError("Unsafe runtime pidfile during cleanup")
        with path.open("rb") as stream:
            value = stream.read(65).strip()
        if not value.isdigit() or len(value) > 20:
            raise RuntimeError("Invalid runtime pidfile during cleanup")
        if (Path("/proc") / value.decode()).exists():
            return True
    return False


def remove_owned_scratch(
    scratch: Path,
    identity: tuple[int, int],
    *,
    daemon_stopped: bool,
    diagnostic: dict,
    storage: Path = Path("/var/lib/docker"),
    wait_seconds: float = 15,
) -> None:
    """Use bounded ordinary umount only after this daemon and its workers stop."""
    if not daemon_stopped:
        raise RuntimeError("Cannot clean storage while the dedicated daemon may run")
    if (
        scratch.parent != storage
        or not scratch.name.startswith("distribution-build-")
        or scratch.is_symlink()
        or scratch.resolve() != scratch
        or (scratch.stat().st_dev, scratch.stat().st_ino) != identity
        or scratch.stat().st_uid != os.geteuid()
    ):
        raise RuntimeError("Owned Docker scratch identity changed before cleanup")
    deadline = time.monotonic() + wait_seconds
    diagnostic.update(mounts_seen=0, unmounts_completed=0, filesystem_types=[])
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise OSError(errno.EBUSY, "Owned Docker storage did not become idle")
        if owned_processes_running(scratch):
            time.sleep(min(0.2, remaining))
            continue
        mounts = owned_mounts(scratch)
        diagnostic["mounts_seen"] = max(diagnostic["mounts_seen"], len(mounts))
        diagnostic["filesystem_types"] = sorted(
            set(diagnostic["filesystem_types"]) | {kind for _, kind in mounts}
        )
        if not mounts:
            break
        busy = False
        for mount, _ in mounts:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise OSError(errno.EBUSY, "Owned Docker mount cleanup timed out")
            if mount.resolve() != mount or not mount.is_relative_to(scratch):
                raise RuntimeError("Owned mount changed before cleanup")
            result = subprocess.run(
                ["umount", "--internal-only", "--no-canonicalize", "--", str(mount)],
                env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C"},
                capture_output=True,
                timeout=min(3, remaining),
                check=False,
            )
            if result.returncode:
                if b"busy" not in result.stderr.lower():
                    raise RuntimeError("Ordinary owned-mount unmount failed")
                busy = True
                break
            diagnostic["unmounts_completed"] += 1
        if busy:
            remaining = deadline - time.monotonic()
            if remaining > 0:
                time.sleep(min(0.2, remaining))
    if (scratch.stat().st_dev, scratch.stat().st_ino) != identity:
        raise RuntimeError("Owned Docker scratch changed after unmount")
    shutil.rmtree(scratch)


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


def verify_tree(root: Path, expected: dict) -> None:
    """Require the exact regular-file closure; never follow links into old data."""
    if (
        not root.is_absolute()
        or root.resolve() != root
        or root.is_symlink()
        or not root.is_dir()
        or not expected
    ):
        raise ValueError("frozen tree must be an absolute directory with a file manifest")
    actual = {}
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError("frozen tree contains a symbolic link")
        if path.is_file():
            actual[path.relative_to(root).as_posix()] = digest(path)
    if actual != expected:
        raise ValueError("frozen file closure does not match its manifest")


def validate_manifest(path: Path, expected_sha256: str) -> tuple[dict, dict]:
    if path.resolve() != path or path.is_symlink() or digest(path) != expected_sha256:
        raise ValueError("job manifest hash differs from the submitted invocation")
    manifest = json.loads(path.read_text())
    if manifest.get("schema_version") != 1 or manifest.get("network") not in {
        "mapdn33",
        "mapdn141",
        "powergym34",
        "powergym123",
    }:
        raise ValueError("unsupported selection manifest")
    for label in ("code", "pool"):
        verify_tree(Path(manifest[label]["root"]), manifest[label]["files"])
    code = Path(manifest["code"]["root"])
    if digest(Path(__file__).resolve()) != manifest["code"]["files"].get(
        Path(__file__).resolve().relative_to(code).as_posix()
    ):
        raise ValueError("runtime entry is outside the frozen code closure")
    acceptance = Path(manifest["runtime_acceptance"])
    if (
        acceptance.resolve() != acceptance
        or acceptance.is_symlink()
        or digest(acceptance) != ACCEPTANCE_SHA256
    ):
        raise ValueError("accepted runtime receipt hash mismatch")
    receipt = json.loads(acceptance.read_text())
    if receipt.get("passed") is not True:
        raise ValueError("runtime receipt is not accepted")
    family = "mapdn" if manifest["network"].startswith("mapdn") else "powergym"
    row = next(
        item for item in receipt["images"] if item["runtime_image"] == family + "-canary-runtime:1"
    )
    archive = Path(manifest["runtime_archive"])
    if (
        archive.resolve() != archive
        or archive.is_symlink()
        or not archive.is_file()
        or digest(archive) != row["runtime_archive_sha256"]
    ):
        raise ValueError("accepted numerical runtime archive hash mismatch")
    command = manifest.get("command")
    if (
        not isinstance(command, list)
        or not command
        or any(not isinstance(value, str) or not value or "\x00" in value for value in command)
    ):
        raise ValueError("command must be a nonempty argument list")
    if not 1 <= manifest.get("timeout_seconds", 0) <= 86400:
        raise ValueError("explicit baseline wall-clock limit required")
    output = Path(manifest["output"])
    if (
        not output.is_absolute()
        or output.resolve() != output
        or output.exists()
        or output.is_symlink()
        or any(output.is_relative_to(Path(manifest[k]["root"])) for k in ("code", "pool"))
        or output in archive.parents
        or output in acceptance.parents
    ):
        raise ValueError("output must be a fresh independent directory")
    return manifest, row


def execute(path: Path, expected_sha256: str) -> dict:
    if (
        sys.platform != "linux"
        or os.geteuid() != 0
        or os.environ.get("DISTRIBUTION_SELECTION_DIND") != "1"
    ):
        raise RuntimeError("a dedicated privileged Linux CPU job is required")
    manifest, image = validate_manifest(path, expected_sha256)
    storage = Path("/var/lib/docker")
    if storage.is_symlink() or not storage.is_mount():
        raise RuntimeError("a dedicated Docker storage mount is required")
    output = Path(manifest["output"])
    output.mkdir(parents=True, mode=0o700)
    old_umask = os.umask(0o077)
    daemon = None
    daemon_stopped = False
    scratch = None
    identity = None
    record = {
        "passed": False,
        "network": manifest["network"],
        "created_at": datetime.now(UTC).isoformat(),
        "job_manifest_sha256": expected_sha256,
        "runtime_image_id": image["runtime_image_id"],
        "host_kernel": os.uname().release,
        "model_calls": 0,
        "cleanup_errors": [],
    }
    failed = None
    container_name = "selection-" + manifest["network"] + "-" + expected_sha256[:16]
    client = {k: os.environ[k] for k in ("PATH", "HOME", "LANG", "LC_ALL") if k in os.environ}
    try:
        reject_existing_daemon({**client, "DOCKER_HOST": "unix:///var/run/docker.sock"})
        scratch = Path(tempfile.mkdtemp(prefix="distribution-build-", dir=storage))
        identity = (scratch.stat().st_dev, scratch.stat().st_ino)
        client.update(
            DOCKER_HOST="unix://" + str(scratch / "docker.sock"),
            DOCKER_CONFIG=str(scratch / "config"),
        )
        Path(client["DOCKER_CONFIG"]).mkdir(mode=0o700)
        with (output / "dockerd.log").open("w") as log:
            daemon = subprocess.Popen(
                [
                    "dockerd",
                    "--host=" + client["DOCKER_HOST"],
                    "--storage-driver=overlay2",
                    "--data-root=" + str(scratch / "data"),
                    "--exec-root=" + str(scratch / "exec"),
                    "--pidfile=" + str(scratch / "docker.pid"),
                    "--shutdown-timeout=15",
                    "--bridge=none",
                    "--iptables=false",
                    "--ip-forward=false",
                ],
                env=client,
                stdout=log,
                stderr=log,
            )
        wait_for_daemon(daemon, client)
        with (output / "load.log").open("w") as log:
            subprocess.run(
                ["docker", "load", "-i", manifest["runtime_archive"]],
                env=client,
                stdout=log,
                stderr=log,
                timeout=600,
                check=True,
            )
        inspection = subprocess.run(
            ["docker", "image", "inspect", image["runtime_image"], "--format", "{{.Id}}"],
            env=client,
            capture_output=True,
            text=True,
            timeout=15,
            check=True,
        )
        if inspection.stdout.strip() != image["runtime_image_id"]:
            raise RuntimeError("loaded numerical image ID mismatch")
        command = [
            "docker",
            "run",
            "--rm",
            "--name",
            container_name,
            "--network=none",
            "--cpus=8",
            "--memory=16g",
            "--pids-limit=256",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--read-only",
            "--tmpfs",
            "/tmp:rw,nosuid,nodev,size=2g",
            "--workdir=/selection",
            "--env",
            "PYTHONPATH=/selection:/selection/src",
            "--env",
            "PYTHONDONTWRITEBYTECODE=1",
            "--env",
            "OPENBLAS_NUM_THREADS=1",
            "--env",
            "OMP_NUM_THREADS=1",
        ]
        for source, target in [
            (manifest["code"]["root"], "/selection"),
            (manifest["pool"]["root"], "/pool"),
        ]:
            command += ["--mount", f"type=bind,src={source},dst={target},readonly"]
        command += ["--mount", f"type=bind,src={output},dst=/output"]
        # Existing baseline CLIs colocate frozen inputs and results. Keep the
        # source pool read-only, then verify a private copy before invoking them.
        clone_target = "/output" if manifest["network"].startswith("mapdn") else "/output/pool"
        command += [
            image["runtime_image_id"],
            "python",
            "-c",
            COPY_POOL_WRAPPER,
            "/pool",
            clone_target,
            json.dumps(manifest["pool"]["files"], sort_keys=True),
            *manifest["command"],
        ]
        with (output / "baseline.log").open("w") as log:
            result = subprocess.run(
                command,
                env=client,
                stdout=log,
                stderr=log,
                timeout=manifest["timeout_seconds"],
                check=False,
            )
        record["baseline_returncode"] = result.returncode
        if result.returncode:
            raise RuntimeError("trusted baseline command returned failure")
        for label in ("code", "pool"):
            verify_tree(Path(manifest[label]["root"]), manifest[label]["files"])
    except BaseException as exc:  # Preserve failure while still releasing owned resources.
        record["error_type"] = type(exc).__name__
        failed = exc
    finally:

        def cleanup(operation, action):
            try:
                action()
            except BaseException as exc:  # Cleanup must not skip the remaining resources.
                record["cleanup_errors"].append(cleanup_diagnostic(operation, exc))

        if daemon is not None:
            cleanup(
                "remove_container",
                lambda: subprocess.run(
                    ["docker", "rm", "--force", container_name],
                    env=client,
                    capture_output=True,
                    timeout=20,
                    check=False,
                ),
            )
            cleanup("terminate_daemon", daemon.terminate)
            cleanup("wait_daemon", lambda: daemon.wait(timeout=25))
            daemon_stopped = daemon.poll() is not None
        if scratch is not None:
            cleanup(
                "remove_scratch",
                lambda: remove_owned_scratch(
                    scratch,
                    identity,
                    daemon_stopped=daemon_stopped,
                    diagnostic=record.setdefault("mount_cleanup", {}),
                ),
            )
        record["passed"] = failed is None and not record["cleanup_errors"]
        try:
            write_json(output / "runtime-receipt.json", record)
        finally:
            os.umask(old_umask)
    if not record["passed"]:
        raise RuntimeError("selection runtime failed; inspect its owner-only receipt") from failed
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    if args.validate_only:
        validate_manifest(args.manifest, args.manifest_sha256)
    else:
        execute(args.manifest, args.manifest_sha256)


if __name__ == "__main__":
    main()
