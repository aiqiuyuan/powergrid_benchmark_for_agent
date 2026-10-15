"""Integrity checks and private source copies for trusted simulator preparation.

This does not provision a development image, fetch data, certify physical models,
extract archives, or isolate hostile controllers. Never mount this full upstream
source tree in the agent workspace under the strict feedback protocol.
"""

import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path, PurePosixPath


class PreparationError(ValueError):
    """Source identity or a preparation destination is unsuitable."""


def _digest(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise PreparationError("Require regular files without symbolic links")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_archive(path: str | Path, *, sha256: str, size_bytes: int) -> dict:
    """Stream a caller-supplied archive to verify its published LFS identity."""
    path = Path(path)
    if not re.fullmatch(r"[a-f0-9]{64}", sha256):
        raise PreparationError("Require a literal SHA-256")
    if type(size_bytes) is not int or size_bytes <= 0:
        raise PreparationError("Require a positive byte count")
    if path.is_symlink() or not path.is_file() or path.stat().st_size != size_bytes:
        raise PreparationError("Archive file type or byte count mismatch")
    actual = _digest(path)
    if actual != sha256:
        raise PreparationError("Archive SHA-256 mismatch")
    return {"file": path.name, "sha256": actual, "size_bytes": size_bytes}


def _git(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *arguments], capture_output=True, text=True, timeout=60
    )
    if result.returncode:
        raise PreparationError("Cannot inspect the source Git checkout")
    return result.stdout.strip()


def prepare_workspace(
    source: str | Path,
    destination: str | Path,
    *,
    expected_commit: str,
    required_files: dict[str, str] | None = None,
) -> dict:
    """Copy tracked files into a fresh trusted worker directory with a receipt.

    Use one directory AND one simulator process per PowerGym worker. Source
    copies alone cannot isolate the singleton DSS engine or adversarial code.
    """
    source, destination = Path(source).resolve(), Path(destination).absolute()
    if not re.fullmatch(r"[a-f0-9]{40}", expected_commit):
        raise PreparationError("Require an immutable 40-character source commit")
    if source == destination.resolve() or source in destination.resolve().parents:
        raise PreparationError("Worker directory must be outside the source checkout")
    if destination.exists() or destination.is_symlink():
        raise PreparationError("Worker destination must not exist")
    if Path(_git(source, "rev-parse", "--show-toplevel")).resolve() != source:
        raise PreparationError("Source must be the checkout root")
    if _git(source, "rev-parse", "HEAD") != expected_commit:
        raise PreparationError("Source commit mismatch")
    if _git(source, "status", "--porcelain", "--untracked-files=all"):
        raise PreparationError("Source checkout must be clean, including untracked files")
    entries = _git(source, "ls-tree", "-rz", "--full-tree", expected_commit).split("\x00")
    files = {}
    blobs = {}
    for entry in filter(None, entries):
        identity, name = entry.split("\t", 1)
        mode, kind, blob = identity.split()
        if mode not in {"100644", "100755"} or kind != "blob":
            raise PreparationError("Only regular committed source files are supported")
        path = PurePosixPath(name)
        if path.is_absolute() or any(part in {"", ".", ".."} for part in name.split("/")):
            raise PreparationError("Unsafe tracked file path")
        target = source / name
        if source not in target.resolve().parents:
            raise PreparationError("Tracked path escapes checkout")
        if _git(source, "hash-object", "--no-filters", "--", name) != blob:
            raise PreparationError("Working file differs from the pinned Git blob")
        files[name] = _digest(target)
        blobs[name] = blob
    if "source-receipt.json" in files or not files:
        raise PreparationError("Source tree is empty or contains a reserved receipt")
    for name, expected in (required_files or {}).items():
        if files.get(name) != expected:
            raise PreparationError(f"Required source file identity mismatch: {name}")
    receipt = {
        "schema_version": "distribution-source-receipt-v1",
        "source_commit": expected_commit,
        "files": files,
        "scope": "trusted-simulator-source-copy-only",
        "release_ready": False,
    }
    destination.mkdir(parents=True)
    try:
        for name, digest in files.items():
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / name, target)
            if (
                _digest(target) != digest
                or _git(source, "hash-object", "--no-filters", "--", str(target)) != blobs[name]
            ):
                raise PreparationError("Source changed during preparation")
        (destination / "source-receipt.json").write_text(
            json.dumps(receipt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    except BaseException:
        shutil.rmtree(destination)
        raise
    return receipt


def prepare_from_lock(
    lock_path: str | Path,
    task_id: str,
    *,
    source: str | Path,
    destination: str | Path,
    archives: dict[str, str] | None = None,
) -> dict:
    """Verify optional data archives and stage an explicitly locked source tree."""
    lock = json.loads(Path(lock_path).read_text(encoding="utf-8"))
    if lock.get("schema_version") != "distribution-sources-v1":
        raise PreparationError("Unsupported distribution source lock")
    task = lock["tasks"][task_id]
    verified = []
    for name, path in (archives or {}).items():
        pin = task.get("archives", {}).get(name)
        if pin is None:
            raise PreparationError("Unknown archive identity")
        verified.append(verify_archive(path, sha256=pin["sha256"], size_bytes=pin["size_bytes"]))
    receipt = prepare_workspace(
        source,
        destination,
        expected_commit=task["source_commit"],
        required_files=task.get("required_files", {}),
    )
    report = {
        "task_id": task_id,
        "source_commit": receipt["source_commit"],
        "tracked_files": len(receipt["files"]),
        "verified_archives": verified,
        "source_receipt": str(Path(destination).absolute() / "source-receipt.json"),
        "release_ready": False,
        "simulation_executed": False,
    }
    (Path(destination) / "preparation-report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return report
