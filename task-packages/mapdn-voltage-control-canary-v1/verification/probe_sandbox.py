#!/usr/bin/env python3
"""Linux-only negative probes for the mandatory distribution filesystem/IPC sandbox."""

from __future__ import annotations

import argparse
import ctypes
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
legacy = sys.argv[1] == '1'
victim = os.fsencode(sys.argv[2])
with open(victim, 'rb') as stream:
    checks['readonly_source_read_allowed'] = (
        stream.read() == b'external file content must remain unchanged')
descriptor = os.open(victim, os.O_RDONLY)
try:
    os.ftruncate(descriptor, 0)
except OSError as error:
    checks['ftruncate_readonly_source_blocked'] = error.errno in (
        (errno.EPERM,) if legacy else (errno.EINVAL, errno.EBADF, errno.EACCES))
else:
    checks['ftruncate_readonly_source_blocked'] = False
os.close(descriptor)
with open('private.txt', 'x') as stream: stream.write('local')
with open('private.txt') as stream: checks['own_directory_read_write'] = stream.read() == 'local'
for path in sys.argv[3:-1]:
    try:
        with open(path) as stream: stream.read(1)
    except PermissionError:
        checks['read_blocked:' + path] = True
    else:
        checks['read_blocked:' + path] = False
try:
    with open(sys.argv[-1], 'x') as stream: stream.write('leak')
except PermissionError:
    checks['shared_tmp_write_blocked'] = True
else:
    checks['shared_tmp_write_blocked'] = False
libc = ctypes.CDLL(None, use_errno=True)
def denied_call(name, *arguments, expected=(errno.EPERM, errno.EACCES)):
    ctypes.set_errno(0)
    result = getattr(libc, name)(*arguments)
    return result == -1 and ctypes.get_errno() in expected

def denied_open(name, *arguments):
    ctypes.set_errno(0)
    descriptor = getattr(libc, name)(*arguments)
    error = ctypes.get_errno()
    if descriptor >= 0:
        os.close(descriptor)
    return descriptor == -1 and error in (errno.EPERM, errno.EACCES)

# This external file is mode 0666 in a mode 0777 directory. DAC alone cannot
# prevent these attacks; the parent also verifies its original content remains.
for name in ('truncate', 'truncate64'):
    if hasattr(libc, name):
        checks[name + '_external_blocked'] = denied_call(name, victim, 0)
for mode in (os.O_RDONLY, os.O_WRONLY, os.O_RDWR):
    checks['open_trunc_external_' + str(mode)] = denied_open('open', victim, mode | os.O_TRUNC)
    checks['openat_trunc_external_' + str(mode)] = denied_open(
        'openat', -100, victim, mode | os.O_TRUNC)
checks['write_open_external_blocked'] = denied_open('open', victim, os.O_WRONLY)
checks['creat_external_blocked'] = denied_open('creat', victim, 0o600)

class OpenHow(ctypes.Structure):
    _fields_ = [('flags', ctypes.c_uint64), ('mode', ctypes.c_uint64), ('resolve', ctypes.c_uint64)]

how = OpenHow(os.O_RDONLY | os.O_TRUNC, 0, 0)
# Both deployed architectures use the generic openat2 syscall number 437.
checks['openat2_external_blocked'] = denied_call(
    'syscall', 437, -100, victim, ctypes.byref(how), ctypes.sizeof(how),
    expected=(errno.ENOSYS,) if legacy else (errno.EPERM, errno.EACCES))
checks['cross_directory_link_blocked'] = denied_call(
    'link', victim, b'victim-link', expected=(errno.EPERM, errno.EACCES, errno.EXDEV))
checks['cross_directory_rename_blocked'] = denied_call(
    'rename', victim, b'victim-moved', expected=(errno.EPERM, errno.EACCES, errno.EXDEV))
if legacy:
    # The compatibility contract is deliberately stricter, including local files.
    for name in ('truncate', 'truncate64'):
        if hasattr(libc, name):
            checks[name + '_local_blocked'] = denied_call(name, b'private.txt', 0)
    descriptor = os.open('private.txt', os.O_WRONLY)
    for name in ('ftruncate', 'ftruncate64'):
        if hasattr(libc, name):
            checks[name + '_local_blocked'] = denied_call(name, descriptor, 0)
    os.close(descriptor)
    checks['creat_local_blocked'] = denied_open('creat', b'private.txt', 0o600)
    for mode in (os.O_RDONLY, os.O_WRONLY, os.O_RDWR):
        checks['open_trunc_local_' + str(mode)] = denied_open(
            'open', b'private.txt', mode | os.O_TRUNC)
        checks['openat_trunc_local_' + str(mode)] = denied_open(
            'openat', -100, b'private.txt', mode | os.O_TRUNC)
    checks['openat2_local_blocked'] = denied_call(
        'syscall', 437, -100, b'private.txt', ctypes.byref(how), ctypes.sizeof(how),
        expected=(errno.ENOSYS,))
else:
    with open('private.txt', 'w') as stream: stream.write('native')
    checks['native_local_truncation_preserved'] = True

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
    parser.add_argument(
        "--legacy-truncation",
        action="store_true",
        help="Expect the CI launcher compiled with DISTRIBUTION_TEST_MAX_ABI=1 or 2",
    )
    args = parser.parse_args()
    if sys.platform != "linux" or os.geteuid() != 0 or not shutil.which("mapdn-exec"):
        raise RuntimeError("probe requires Linux root and the built mapdn-exec launcher")
    if os.uname().machine not in ("x86_64", "aarch64"):
        raise RuntimeError("probe syscall numbers require Linux x86_64 or aarch64")
    libc = ctypes.CDLL(None, use_errno=True)
    abi = libc.syscall(444, None, 0, 1)
    if abi < 1:
        raise RuntimeError("probe requires an enabled Landlock ABI")
    legacy = args.legacy_truncation or abi < 3
    with tempfile.TemporaryDirectory(prefix="mapdn-sandbox-probe-") as temporary:
        root = Path(temporary)
        root.chmod(0o711)
        public = root / "public-shared.txt"
        public.write_text("this intentionally world-readable file must remain inaccessible")
        public.chmod(0o644)
        shared = root / "shared"
        shared.mkdir()
        shared.chmod(0o777)
        victim = shared / "world-writable-victim.txt"
        victim_content = b"external file content must remain unchanged"
        victim.write_bytes(victim_content)
        victim.chmod(0o666)
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
                "1" if legacy else "0",
                str(victim),
                str(public),
                str(other),
                "/proc/self/environ",
                str(write),
            ]
            completed = subprocess.run(
                command,
                cwd=work,
                env={
                    "PATH": "/usr/local/bin:/usr/bin:/bin",
                    "LANG": "C.UTF-8",
                    "DISTRIBUTION_READONLY_DIR": str(shared),
                },
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
            if not victim.is_file() or victim.read_bytes() != victim_content:
                raise RuntimeError("sandbox permitted modification of the external victim")
            results.append({"actor_uid": uid, "checks": json.loads(completed.stdout)})
    executable = Path(shutil.which("mapdn-exec"))
    with executable.open("rb") as stream:
        executable_hash = hashlib.file_digest(stream, "sha256").hexdigest()
    receipt = {
        "status": "passed",
        "platform": sys.platform,
        "kernel": os.uname().release,
        "kernel_landlock_abi": abi,
        "legacy_truncation_profile": legacy,
        "sandbox_executable_sha256": executable_hash,
        "actors": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
