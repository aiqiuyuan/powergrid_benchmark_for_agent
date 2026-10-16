"""Review drafts and run reference acceptance without implicit paid experiments."""

import argparse
import json
from pathlib import Path

from .adapters import AdapterError
from .artifacts import ArtifactError
from .config import TASKS, configuration_catalog, validate_configuration
from .distribution.preparation import PreparationError, prepare_from_lock
from .fixtures import run_fixture
from .ledger import LedgerError


def _adapter_check(path: str) -> dict:
    document = json.loads(Path(path).read_text())
    errors = []
    if not isinstance(document, dict):
        raise AdapterError("Adapter declaration must be a JSON object")
    if document.get("task_id") not in TASKS:
        errors.append("Unknown task_id")
    if document.get("schema_version") != "1.0-design" or document.get("status") != "design":
        errors.append("This checker supports 1.0-design contracts only")
    implementation = document.get("implementation", {})
    argv = implementation.get("argv") if isinstance(implementation, dict) else None
    if not isinstance(argv, list) or "{input}" not in argv or "{output}" not in argv:
        errors.append("Task contract requires input/output argv placeholders")
    if (
        document.get("release_ready") is not False
        or document.get("certification_status") != "pending"
    ):
        errors.append("Production certification is unavailable in this reference implementation")
    return {
        "valid_design": not errors,
        "task_id": document.get("task_id"),
        "errors": errors,
        "release_ready": False,
        "certification_verifier_implemented": False,
        "reason": "Real native adapter/backend acceptance evidence remains required",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="powergrid-bench")
    commands = parser.add_subparsers(dest="command", required=True)
    config = commands.add_parser(
        "config-check", help="Review explicit configuration and unset fields"
    )
    config.add_argument("path")
    config.add_argument("--require-complete", action="store_true")
    adapter = commands.add_parser(
        "adapter-check", help="Check a design declaration, not certification"
    )
    adapter.add_argument("path")
    adapter.add_argument("--require-certified", action="store_true")
    commands.add_parser("catalog", help="Emit configuration field catalog")
    fixture = commands.add_parser(
        "fixture-run", help="Run the cheap synthetic acceptance lifecycle"
    )
    fixture.add_argument("--work-dir", required=True)
    fixture.add_argument("--trusted-local", action="store_true")
    prepare = commands.add_parser(
        "distribution-prepare", help="Stage pinned sources in a fresh trusted simulator workspace"
    )
    prepare.add_argument("lock")
    prepare.add_argument("task_id")
    prepare.add_argument("--source", required=True)
    prepare.add_argument("--destination", required=True)
    prepare.add_argument("--archive", action="append", default=[], metavar="NAME=PATH")
    args = parser.parse_args(argv)
    code = 0
    try:
        if args.command == "config-check":
            report = validate_configuration(json.loads(Path(args.path).read_text())).to_dict()
            code = (
                0
                if report["valid_draft"] and (not args.require_complete or report["executable"])
                else 2
            )
        elif args.command == "adapter-check":
            report = _adapter_check(args.path)
            code = 0 if report["valid_design"] and not args.require_certified else 2
        elif args.command == "catalog":
            report = configuration_catalog()
        elif args.command == "distribution-prepare":
            archives = {}
            for value in args.archive:
                name, separator, path = value.partition("=")
                if not separator or not name or not path or name in archives:
                    raise PreparationError("Archives require distinct NAME=PATH entries")
                archives[name] = path
            report = prepare_from_lock(
                args.lock,
                args.task_id,
                source=args.source,
                destination=args.destination,
                archives=archives,
            )
        else:
            report = run_fixture(args.work_dir, trusted_local=args.trusted_local)
    except (AdapterError, ArtifactError, LedgerError, OSError, ValueError, KeyError) as error:
        report, code = {"status": "error", "error": str(error)}, 2
    print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
