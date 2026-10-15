#!/bin/sh
set -eu
export LOG_DIR="${LOG_DIR:-/logs/verifier}"
mkdir -p "$LOG_DIR"
chmod 700 "$LOG_DIR"
python3 "${TESTS_DIR:-/tests}/score.py"
