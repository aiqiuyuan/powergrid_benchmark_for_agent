#!/usr/bin/env bash
set -euo pipefail
# The developer image already contains the locked inherited starter.
# This oracle hook verifies its syntax; full-panel feasibility is an acceptance gate.
python3 -c "import ast; from pathlib import Path; ast.parse(Path('/app/submission/solver.py').read_text())"
