#!/usr/bin/env python3
"""Linux-only negative probes for the mandatory distribution filesystem/IPC sandbox."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PROBE = r"""
import ctypes, errno, json, os, socket, sys
checks = {}
with open('private.txt', 'w') as stream: stream.write('local')
with open('private.txt') as stream: checks['own_directory_read_write'] = stream.read() == 'local'
for path in sys.argv[1:-1]:
    try:
        with open(path) as stream: stream.read(1)
    except PermissionError:
        checks['read_blocked:' + path] = True
    else:
        checks['read_blocked:' + path] = False
try:
    with open(sys.argv[-1], 'w') as stream: stream.write('leak')
except PermissionError:
    checks['shared_tmp_write_blocked'] = True
else:
    checks['shared_tmp_write_blocked'] = False
libc = ctypes.CDLL(None, use_errno=True)
for call, arguments in [('shmget', (0, 4096, 0o1000 | 0o600)),
                        ('msgget', (0, 0o1000 | 0o600)),
                        ('semget', (0, 1, 0o1000 | 0o600))]:
    ctypes.set_errno(0)
    result = getattr(libc, call)(*arguments)
    checks[call + '_blocked'] = result == -1 and ctypes.get_errno() == errno.EPERM
try:
    socket.socket()
except PermissionError:
    checks['socket_blocked'] = True
else:
    checks['socket_blocked'] = False
print(json.dumps(checks))
sys.exit(0 if all(checks.values()) else 1)
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if sys.platform != "linux" or os.geteuid() != 0 or not shutil.which("mapdn-exec"):
        raise RuntimeError("probe requires Linux root and the built mapdn-exec launcher")
    with tempfile.TemporaryDirectory(prefix="mapdn-sandbox-probe-") as temporary:
        root = Path(temporary)
        root.chmod(0o711)
        public = root / "public-shared.txt"
        public.write_text("this intentionally world-readable file must remain inaccessible")
        public.chmod(0o644)
        for actor in (0, 1):
            work = root / f"actor-{actor}"
            work.mkdir(mode=0o755)
            os.chown(work, 64000 + actor, 64000 + actor)
            secret = work / "advertised.txt"
            secret.write_text("cross-actor invitation")
            secret.chmod(0o644)
        results = []
        for actor in (0, 1):
            uid = 64000 + actor
            work = root / f"actor-{actor}"
            # Even an actor deliberately making its own directory world-readable
            # cannot grant the other actor access through a separate Landlock domain.
            other = root / f"actor-{1 - actor}" / "advertised.txt"
            write = Path(str(root) + f"-actor-{actor}-shared-write")
            command = [
                "setpriv",
                "--no-new-privs",
                f"--reuid={uid}",
                f"--regid={uid}",
                "--clear-groups",
                "mapdn-exec",
                sys.executable,
                "-I",
                "-c",
                PROBE,
                str(public),
                str(other),
                "/proc/self/environ",
                str(write),
            ]
            completed = subprocess.run(
                command,
                cwd=work,
                env={"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8"},
                capture_output=True,
                timeout=10,
            )
            if write.exists():
                write.unlink()
            if completed.returncode:
                raise RuntimeError(
                    "sandbox negative probe failed: "
                    + completed.stderr.decode()
                    + completed.stdout.decode()
                )
            results.append({"actor_uid": uid, "checks": json.loads(completed.stdout)})
    executable = Path(shutil.which("mapdn-exec"))
    with executable.open("rb") as stream:
        executable_hash = hashlib.file_digest(stream, "sha256").hexdigest()
    receipt = {
        "status": "passed",
        "platform": sys.platform,
        "kernel": os.uname().release,
        "sandbox_executable_sha256": executable_hash,
        "actors": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
