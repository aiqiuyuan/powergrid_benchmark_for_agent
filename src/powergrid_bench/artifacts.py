"""Content-addressed snapshots for a trusted evaluator filesystem.

Read-only permissions detect accidental changes; they do not replace a sandbox
or a separate storage identity when running hostile candidate code.
"""

import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


class ArtifactError(ValueError):
    """Candidate packaging or stored snapshot integrity failure."""


def canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def content_hash(value: object) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def _relative(value: str) -> str:
    path = PurePosixPath(value)
    if (
        not value
        or "\\" in value
        or ":" in value
        or "\x00" in value
        or path.is_absolute()
        or any(part in {".", "..", ""} for part in value.split("/"))
        or value == "_manifest.json"
    ):
        raise ArtifactError("Unsafe or reserved relative artifact path")
    return path.as_posix()


def _files(root: Path, *, stored: bool = False) -> list[Path]:
    if root.is_symlink() or not root.is_dir():
        raise ArtifactError("Artifact source must be an ordinary directory")
    result = []
    for directory, directories, files in os.walk(root, followlinks=False):
        for name in directories + files:
            path = Path(directory) / name
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode):
                raise ArtifactError("Symbolic links are forbidden")
            if stat.S_ISDIR(info.st_mode):
                continue
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ArtifactError("Only ordinary files without hard links are allowed")
            relative = path.relative_to(root).as_posix()
            if stored and relative == "_manifest.json":
                continue
            _relative(relative)
            result.append(path)
    return sorted(result, key=lambda path: path.relative_to(root).as_posix())


def _read(path: Path, *, limit: int) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                raise ArtifactError("Artifact file changed type during snapshot")
            data = stream.read(limit + 1)
            after = os.fstat(stream.fileno())
        if (
            len(data) > limit
            or before.st_size != len(data)
            or (before.st_size, before.st_mtime_ns, before.st_ino)
            != (after.st_size, after.st_mtime_ns, after.st_ino)
        ):
            raise ArtifactError("File exceeds bounds or changed while snapshotting")
        return data
    except OSError as error:
        raise ArtifactError("Cannot read artifact file safely") from error


@dataclass(frozen=True)
class Snapshot:
    digest: str
    path: Path
    manifest: dict

    @property
    def artifact_sha256(self) -> str:
        return self.digest


class ArtifactStore:
    def __init__(self, root: str | Path):
        self.root = Path(root).absolute()
        self.snapshots = self.root / "snapshots"
        self.snapshots.mkdir(parents=True, exist_ok=True)
        if self.root.is_symlink() or self.snapshots.is_symlink():
            raise ArtifactError("Store directories must not be symbolic links")

    def snapshot(
        self,
        source: str | Path,
        *,
        required_files: tuple[str, ...] = (),
        max_files: int = 1000,
        max_bytes: int = 100_000_000,
    ) -> Snapshot:
        if max_files <= 0 or max_bytes <= 0:
            raise ArtifactError("Snapshot limits must be positive")
        required = {_relative(value) for value in required_files}
        source = Path(source).absolute()
        if source == self.root or source in self.root.parents:
            raise ArtifactError("Artifact source must not contain the snapshot store")
        files = _files(source)
        if not files or len(files) > max_files:
            raise ArtifactError("Empty artifact or file-count limit exceeded")
        names = {path.relative_to(source).as_posix() for path in files}
        if not required.issubset(names):
            raise ArtifactError("Artifact is missing required files")
        temporary = Path(tempfile.mkdtemp(prefix="snapshot-", dir=self.root))
        records, total = [], 0
        try:
            for path in files:
                data = _read(path, limit=max_bytes - total)
                total += len(data)
                relative = path.relative_to(source).as_posix()
                output = temporary / relative
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(data)
                executable = bool(path.stat().st_mode & 0o111)
                output.chmod(0o755 if executable else 0o644)
                records.append(
                    {
                        "path": relative,
                        "size": len(data),
                        "sha256": hashlib.sha256(data).hexdigest(),
                        "executable": executable,
                    }
                )
            manifest = {"schema_version": 1, "files": records}
            if len(canonical(manifest)) > 5_000_000:
                raise ArtifactError("Artifact manifest exceeds the metadata limit")
            digest = content_hash(manifest)
            (temporary / "_manifest.json").write_bytes(canonical(manifest))
            destination = self.snapshots / digest
            if destination.exists():
                return self.verify(digest)
            try:
                temporary.rename(destination)
            except FileExistsError:
                return self.verify(digest)
            self._readonly(destination)
            return Snapshot(digest, destination, manifest)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)

    @staticmethod
    def _readonly(root: Path) -> None:
        for directory, directories, files in os.walk(root, topdown=False):
            for name in files:
                path = Path(directory) / name
                path.chmod(0o555 if path.stat().st_mode & 0o111 else 0o444)
            for name in directories:
                (Path(directory) / name).chmod(0o555)
        root.chmod(0o555)

    def verify(self, digest: str) -> Snapshot:
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ArtifactError("Invalid SHA-256 artifact identity")
        root = self.snapshots / digest
        if root.is_symlink() or not root.is_dir():
            raise ArtifactError("Snapshot root must be an ordinary stored directory")
        try:
            manifest = json.loads(_read(root / "_manifest.json", limit=5_000_000))
            if content_hash(manifest) != digest:
                raise ArtifactError("Artifact manifest digest mismatch")
            records = manifest["files"]
            if manifest.get("schema_version") != 1 or not isinstance(records, list):
                raise ArtifactError("Invalid authenticated snapshot manifest")
            expected = {}
            for record in records:
                relative = _relative(record["path"])
                size = record["size"]
                if (
                    relative in expected
                    or isinstance(size, bool)
                    or not isinstance(size, int)
                    or size < 0
                ):
                    raise ArtifactError("Invalid file size or duplicate path in manifest")
                expected[relative] = size
            actual = []
            for path in _files(root, stored=True):
                relative = path.relative_to(root).as_posix()
                if relative not in expected:
                    raise ArtifactError("Unexpected file in snapshot")
                data = _read(path, limit=expected[relative])
                actual.append(
                    {
                        "path": relative,
                        "size": len(data),
                        "sha256": hashlib.sha256(data).hexdigest(),
                        "executable": bool(path.stat().st_mode & 0o111),
                    }
                )
            if manifest != {"schema_version": 1, "files": actual}:
                raise ArtifactError("Artifact files disagree with frozen manifest")
            return Snapshot(digest, root, manifest)
        except (OSError, json.JSONDecodeError, TypeError, KeyError) as error:
            raise ArtifactError("Missing or malformed stored snapshot") from error

    def freeze(
        self, digest: str, *, run_id: str, reason: str, selection: dict | None = None
    ) -> dict:
        snapshot = self.verify(digest)
        return {
            "run_id": run_id,
            "artifact_sha256": digest,
            "manifest_sha256": content_hash(snapshot.manifest),
            "reason": reason,
            "selection": selection,
        }
