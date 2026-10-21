"""Run the pinned, complete PMSC Challenge 1 first-stage heuristic."""
import os
from pathlib import Path
import subprocess

submission = Path(os.environ.get("GOC_SUBMISSION", "/submission"))
subprocess.run([
    "/opt/julia/bin/julia", "--project=/opt/n1-julia-project", "--procs=12",
    str(submission / "pmsc_baseline.jl"), "1",
], check=True)
