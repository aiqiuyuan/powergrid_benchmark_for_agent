#!/bin/sh
set -eu
# The native development image already contains the frozen local droop starter.
python3 -c "import ast; from pathlib import Path; ast.parse(Path('/app/submission/controller.py').read_text())"
python3 /app/check_interface.py
