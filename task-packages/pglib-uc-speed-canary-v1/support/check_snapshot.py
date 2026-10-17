"""Private checker subprocess; invalid candidates have a stable exit code."""

import json
import sys
from pathlib import Path

from json_io import load
from pglib_validate import validate

if __name__ == "__main__":
    data = load(Path(sys.argv[1]))
    try:
        checked = validate(data, load(Path(sys.argv[2])))
    except (ValueError, TypeError, KeyError, OverflowError, RecursionError):
        raise SystemExit(2)
    print(json.dumps(checked, allow_nan=False))
