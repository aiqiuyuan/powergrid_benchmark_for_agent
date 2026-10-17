"""Exercise the real Linux launcher under the package's UID and directory policy."""

import argparse
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

PROBE = """
import errno
import json
import os
from pathlib import Path
import resource
import socket
import stat
import sys

source, output, external, cpu = sys.argv[1:]
output = Path(output)
assert os.getuid() == os.getgid() == 64000
assert os.getgroups() == []
assert os.sched_getaffinity(0) == {int(cpu)}
assert resource.getrlimit(resource.RLIMIT_AS) == (17179869184, 17179869184)
assert resource.getrlimit(resource.RLIMIT_NPROC) == (32, 32)
assert resource.getrlimit(resource.RLIMIT_CORE) == (0, 0)
assert json.loads(Path(source).read_text()) == {"probe": "input"}
output.write_text(json.dumps({"probe": "output"}))

def denied(operation, codes):
    try:
        operation()
    except OSError as exc:
        assert exc.errno in codes, exc
    else:
        raise AssertionError("Forbidden operation succeeded")

def fork():
    child = os.fork()
    if child == 0:
        os._exit(0)
    os.waitpid(child, 0)

def network():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM):
        pass

denied(lambda: os.rename(output.parent, output.parent.with_name("moved")),
       {errno.EACCES, errno.EPERM})
denied(lambda: os.sched_setaffinity(0, {int(cpu)}), {errno.EPERM})
denied(fork, {errno.EPERM})
denied(network, {errno.EPERM})
denied(lambda: os.chmod(external, 0o700), {errno.EPERM})
assert stat.S_IMODE(os.stat(external).st_mode) == 0o755
assert output.parent.is_dir()
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--launcher", required=True, type=Path)
    args = parser.parse_args()
    if sys.platform != "linux" or os.geteuid() != 0:
        parser.error("Run this real Linux sandbox probe as root")
    for tool in ("setpriv", "prlimit", "taskset"):
        if shutil.which(tool) is None:
            parser.error(f"Required Linux tool is missing: {tool}")
    launcher = args.launcher.resolve(strict=True)
    cpu = min(os.sched_getaffinity(0))
    with tempfile.TemporaryDirectory(prefix="rte-sandbox-probe-") as temporary:
        root = Path(temporary)
        root.chmod(0o755)
        external = root / "external"
        external.mkdir(mode=0o755)
        external.chmod(0o755)
        external_before = external.stat()
        scratch = root / "scratch"
        scratch.mkdir()
        os.chown(scratch, 0, 64000)
        scratch.chmod(0o710)
        output = scratch / "output"
        output.mkdir()
        os.chown(output, 64000, 64000)
        output.chmod(0o700)
        source = scratch / "probe.py"
        source.write_text(textwrap.dedent(PROBE), encoding="utf-8")
        source.chmod(0o444)
        input_path = scratch / "input.json"
        input_path.write_text('{"probe": "input"}', encoding="utf-8")
        input_path.chmod(0o444)
        command = [
            "setpriv",
            "--no-new-privs",
            "--reuid=64000",
            "--regid=64000",
            "--clear-groups",
            "prlimit",
            "--as=17179869184",
            "--nproc=32",
            "--core=0",
            "--",
            "taskset",
            "-c",
            str(cpu),
            str(launcher),
            sys.executable,
            "-I",
            str(source),
            str(input_path),
            str(output / "result.json"),
            str(external),
            str(cpu),
        ]
        result = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if result.returncode:
            raise RuntimeError(f"Linux sandbox probe failed: {result.stderr.strip()}")
        assert json.loads((output / "result.json").read_text()) == {"probe": "output"}
        scratch_stat = scratch.stat()
        assert (scratch_stat.st_uid, scratch_stat.st_gid) == (0, 64000)
        assert stat.S_IMODE(scratch_stat.st_mode) == 0o710
        assert output.is_dir() and not (scratch / "moved").exists()
        assert output.stat().st_uid == output.stat().st_gid == 64000
        assert stat.S_IMODE(output.stat().st_mode) == 0o700
        assert external.stat().st_ino == external_before.st_ino
        assert stat.S_IMODE(external.stat().st_mode) == 0o755
    print("Linux sandbox probe passed")


if __name__ == "__main__":
    main()
