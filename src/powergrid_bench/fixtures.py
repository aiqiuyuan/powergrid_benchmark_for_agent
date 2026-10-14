"""Cheap synthetic acceptance run; its settings are never research defaults."""

import json
from pathlib import Path

from .adapters import AdapterError, execute_algorithm
from .artifacts import ArtifactStore, canonical, content_hash
from .ledger import Ledger, LedgerError
from .lifecycle import Lifecycle


def _write_algorithm(root: Path, multiplier: int) -> None:
    root.mkdir()
    (root / "main.py").write_text(
        "import argparse,json\n"
        "p=argparse.ArgumentParser();p.add_argument('--request');p.add_argument('--output')\n"
        "a=p.parse_args();request=json.load(open(a.request))\n"
        f"json.dump({{'answer':request['value']*{multiplier}}},open(a.output,'w'))\n"
    )
    (root / "dependency-lock.json").write_bytes(canonical({"runtime": "python-stdlib"}))
    (root / "candidate.json").write_bytes(
        canonical(
            {
                "kind": "algorithm",
                "task_id": "fixture-only",
                "source": ["main.py"],
                "dependency_lock": "dependency-lock.json",
                "entrypoint": [
                    "python3",
                    "main.py",
                    "--request",
                    "{input}",
                    "--output",
                    "{output}",
                ],
            }
        )
    )


def _checker(request: dict, output: dict) -> dict:
    answer = output.get("answer")
    valid = type(answer) in (int, float)
    return {
        "feasible": valid,
        "score": -abs(answer - 2 * request["value"]) if valid else -1_000_000,
    }


def run_fixture(work_dir: str | Path, *, trusted_local: bool = False) -> dict:
    if not trusted_local:
        raise AdapterError("Only the explicitly trusted synthetic fixture may execute locally")
    root = Path(work_dir)
    if root.exists():
        raise AdapterError("Use a new fixture work directory; existing evidence is preserved")
    root.mkdir(parents=True)
    _write_algorithm(root / "baseline", 1)
    _write_algorithm(root / "candidate", 2)
    store = ArtifactStore(root / "artifacts")
    required = ("main.py", "candidate.json", "dependency-lock.json")
    baseline = store.snapshot(root / "baseline", required_files=required)
    candidate = store.snapshot(root / "candidate", required_files=required)
    ledger = Ledger(root / "ledger.sqlite3")
    now = [100.0]
    lifecycle = Lifecycle(store, ledger, now=lambda: now[0])
    context = {
        "scope": "fixture-only",
        "evaluator_sha256": content_hash("fixture-checker-v1"),
        "split_sha256": content_hash({"public_selection": [3], "protected": [5], "final": [11]}),
        "resources": "trusted-local; no production quota certification",
    }

    def execute(digest, value):
        result = execute_algorithm(
            store,
            digest,
            {"value": value},
            task_id="fixture-only",
            checker=_checker,
            work_root=root / "cases",
            timeout_seconds=5,
            trusted_local=True,
        )
        if result.status != "succeeded":
            raise AdapterError(f"Fixture evaluation failed: {result.status}")
        return result

    execute(baseline.digest, 1)  # Preparation validates the fallback before starting T.
    lifecycle.prepare("fixture", context, 1, baseline.digest, max_infrastructure_attempts=2)
    lifecycle.start("fixture", 10)
    now[0] = 101.0
    for snapshot in (baseline, candidate):
        result = execute(snapshot.digest, 3)
        lifecycle.record_selection("fixture", snapshot.digest, result.checker["score"])
    job = lifecycle.submit(
        "fixture", "feedback-1", candidate.digest, request_context={"split": "protected", "seed": 0}
    )
    retried = lifecycle.submit(
        "fixture", "feedback-1", candidate.digest, request_context={"split": "protected", "seed": 0}
    )
    if job["job_id"] != retried["job_id"]:
        raise AdapterError("Idempotent receipt recovery failed")
    attempt = ledger.start_job(job["job_id"], now=now[0])
    feedback = execute(candidate.digest, 5)
    ledger.finish_job(job["job_id"], attempt, feedback.status, feedback.checker, now=now[0])
    payload = {"score": feedback.checker["score"], "schema": "fixture-feedback-v1"}
    # This persisted file is the fixture's trusted feedback channel, not a Harbor transport.
    (root / "feedback-channel.json").write_bytes(canonical(payload))
    delivery = ledger.deliver(job["job_id"], payload, now=now[0])
    if delivery != ledger.deliver(job["job_id"], payload, now=now[0]):
        raise AdapterError("Delivery receipt changed under retry")
    now[0] = 111.0
    late_rejected = False
    try:
        lifecycle.submit("fixture", "late", candidate.digest)
    except LedgerError:
        late_rejected = True
    recovered = Lifecycle(store, Ledger(root / "ledger.sqlite3"), now=lambda: now[0])
    original_clock = recovered.start("fixture", 10)
    receipt = recovered.freeze("fixture")
    if receipt["artifact_sha256"] != candidate.digest:
        raise AdapterError("Public-selection freeze selected the wrong artifact")
    final_context = dict(context, split="final", seed=0, instance_id="fresh-11")
    final = recovered.final_start("fixture", request_context=final_context)
    recovered.final_finish(
        "fixture",
        "infrastructure_error",
        {"error": "injected worker loss"},
        job_id=final["job_id"],
        attempt=final["attempt"],
    )
    retry = recovered.final_retry("fixture", request_context=final_context)
    final_result = execute(receipt["artifact_sha256"], 11)
    recovered.final_finish(
        "fixture",
        final_result.status,
        final_result.checker,
        job_id=retry["job_id"],
        attempt=retry["attempt"],
    )
    zero_context = dict(context, split_sha256=content_hash({"final": [19]}))
    lifecycle.prepare("zero-feedback", zero_context, 0, baseline.digest)
    lifecycle.start("zero-feedback", 10)
    zero_rejected = False
    try:
        lifecycle.submit("zero-feedback", "forbidden", baseline.digest)
    except LedgerError:
        zero_rejected = True
    now[0] = 122.0
    zero_receipt = lifecycle.freeze("zero-feedback")
    zero_final = lifecycle.final_start(
        "zero-feedback", request_context=dict(zero_context, instance_id="fresh-19", seed=0)
    )
    zero_result = execute(zero_receipt["artifact_sha256"], 19)
    lifecycle.final_finish(
        "zero-feedback",
        zero_result.status,
        zero_result.checker,
        job_id=zero_final["job_id"],
        attempt=zero_final["attempt"],
    )
    report = {
        "schema_version": "fixture-acceptance-v1",
        "status": "passed",
        "scope": "trusted-local-synthetic",
        "production_certified": False,
        "fixture_values_are_research_defaults": False,
        "clock": {
            "started_at": original_clock.started_at,
            "deadline_at": original_clock.deadline_at,
            "kind": "injected logical clock; subprocesses actually execute",
        },
        "feedback": ledger.summary("fixture"),
        "lost_receipt_is_idempotent": True,
        "late_request_rejected": late_rejected,
        "freeze_receipt": receipt,
        "final_attempts": len(ledger.attempts(final["job_id"])),
        "final_job_identity_preserved": retry["job_id"] == final["job_id"],
        "final_state": ledger.get_run("fixture")["state"],
        "fresh_final_input_executed": final_result.output["answer"] == 22,
        "final_checker": final_result.checker,
        "zero_feedback_verified": zero_rejected and ledger.summary("zero-feedback")["counted"] == 0,
        "baseline_fallback_verified": zero_receipt["selection_reason"] == "baseline_fallback",
        "limitations": [
            "no real energy evaluator",
            "no Harbor/provider certification",
            "no hostile-code isolation or resource quota certification",
            "no actual agent-channel delivery acknowledgment",
        ],
    }
    if not all(
        (
            late_rejected,
            report["final_job_identity_preserved"],
            report["fresh_final_input_executed"],
            report["zero_feedback_verified"],
            report["baseline_fallback_verified"],
            report["final_state"] == "complete",
        )
    ):
        raise AdapterError("Fixture acceptance invariant failed")
    (root / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return report
