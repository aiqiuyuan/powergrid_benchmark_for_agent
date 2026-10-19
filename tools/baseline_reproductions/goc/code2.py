"""Compute every contingency from this execution's immutable PMSC base case."""
import os
from pathlib import Path
import shutil
import subprocess

submission = Path(os.environ.get("GOC_SUBMISSION", "/submission"))
output = Path(os.environ.get("GOC_OUTPUT", "/output"))
stage1 = Path(os.environ.get("GOC_STAGE1", "/stage1"))
output.mkdir(parents=True, exist_ok=True)
shutil.copyfile(stage1 / "solution1.txt", output / "solution1.txt")
subprocess.run([
    "/opt/julia/bin/julia", "--project=/opt/n1-julia-project", "--procs=12",
    str(submission / "pmsc_baseline.jl"), "2",
], check=True)
