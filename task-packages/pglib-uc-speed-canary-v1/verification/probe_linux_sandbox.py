"""Root-only acceptance of the real launcher; does not certify Julia or Harbor."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "support"))
from runner import CHILD_ENV, secure_prefix


def main() -> None:
    if sys.platform != "linux" or os.geteuid() != 0:
        raise RuntimeError("Linux root required")
    with tempfile.TemporaryDirectory(prefix="uc-sandbox-probe-") as directory:
        root = Path(directory)
        root.chmod(0o755)
        private = root / "private"
        private.mkdir(mode=0o700)
        secret = private / "reference.json"
        secret.write_text("test-only-private-value")
        output = root / "output"
        output.mkdir(mode=0o700)
        os.chown(output, 65534, 65534)
        code = """import json,os,socket,sys,threading
out={"uid":os.geteuid()}
for name,operation in (("fork",os.fork),("socket",socket.socket),
                       ("private_read",lambda:open(sys.argv[1]).read()),
                       ("tmp_write",lambda:open('/tmp/uc-forbidden-cache','w')),
                       ("shm_write",lambda:open('/dev/shm/uc-forbidden-cache','w'))):
    try:
        operation()
        out[name]="ALLOWED"
    except PermissionError:
        out[name]="DENIED"
thread=threading.Thread(target=lambda:out.update(thread="OK"))
thread.start();thread.join()
with open(sys.argv[2]+'/snapshot.tmp','w') as stream:stream.write('test')
os.rename(sys.argv[2]+'/snapshot.tmp',sys.argv[2]+'/snapshot.json')
out['output_write']='OK'
print(json.dumps(out))
"""
        result = subprocess.run(
            secure_prefix(10, output)
            + [sys.executable, "-I", "-c", code, str(secret), str(output)],
            capture_output=True,
            timeout=10,
            text=True,
            env=CHILD_ENV,
        )
        if result.returncode:
            raise RuntimeError("Real sandbox probe failed")
        expected = {
            "uid": 65534,
            "fork": "DENIED",
            "socket": "DENIED",
            "private_read": "DENIED",
            "thread": "OK",
            "tmp_write": "DENIED",
            "shm_write": "DENIED",
            "output_write": "OK",
        }
        facts = json.loads(result.stdout)
        if facts != expected:
            raise RuntimeError("Sandbox restrictions differ from contract")
        print(
            json.dumps(
                {"passed": True, "facts": facts, "scope": "linux-launcher-only-not-Julia-or-Harbor"}
            )
        )


if __name__ == "__main__":
    main()
