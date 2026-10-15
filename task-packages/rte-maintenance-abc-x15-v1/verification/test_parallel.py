"""Real tiny subprocess integration and bounded-parallel RTE task checks.

Secure command construction is mocked; Linux sandbox enforcement is not claimed.
"""

from __future__ import annotations

import json
import math
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from helpers import (
    TASK,
    load_task_module,
    patch_modules,
    synthetic_manifest,
    tiny_instance,
)


class ABCX15RunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.support = TASK / "support"
        self.path_patch = mock.patch.object(sys, "path", [str(self.support), *sys.path])
        self.path_patch.start()
        self.addCleanup(self.path_patch.stop)
        official = load_task_module("support/official.py", "abc_x15_official")
        self.enterContext(patch_modules({"official": official}))
        self.runner = load_task_module("support/runner.py", "runner")
        # Spawned workers must import this task's runner, rather than a legacy one.
        self.enterContext(patch_modules({"runner": self.runner}))

    def test_real_starter_and_official_checker_produce_a_feasible_score(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            # Include cold SciPy wheel startup; this checks integration, not solver speed.
            manifest = synthetic_manifest(
                root, [tiny_instance("one"), tiny_instance("two")], seconds=20, workers=2
            )
            result = self.runner.evaluate_manifest(
                TASK / "init.py",
                manifest,
                support=self.support,
                secure=False,
                timeout=30,
                workers=2,
            )
            self.assertEqual(result["validity"], 1.0, result)
            self.assertGreater(result["combined_score"], 0)
            self.assertEqual([case["case"] for case in result["cases"]], ["one", "two"])
            self.assertTrue(all(case["valid"] for case in result["cases"]))
            self.assertTrue(all(math.isclose(case["objective"], 1.0) for case in result["cases"]))

    def test_real_parallel_cases_use_process_workers_cap_and_manifest_order(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            trace = root / "trace"
            trace.mkdir()
            candidate = root / "candidate.py"
            candidate.write_text(
                "import argparse,json,os,time\nfrom pathlib import Path\n"
                "p=argparse.ArgumentParser();p.add_argument('--instance');p.add_argument('--output');"
                "p.add_argument('--time-limit');p.add_argument('--seed');a=p.parse_args()\n"
                "d=json.loads(Path(a.instance).read_text());trace=Path(d['_trace_dir'])\n"
                "start=time.monotonic_ns();time.sleep(d['_delay'])\n"
                "schedule={name:next(t for t in range(1,int(j['tmax'])+1) "
                "if t+int(j['Delta'][t-1])<=d['T']+1) for name,j in d['Interventions'].items()}\n"
                "Path(a.output).write_text(''.join(f'{n} {t}\\n' for n,t in schedule.items()))\n"
                "(trace/(d['_case_id']+'.json')).write_text(json.dumps({'pid':os.getpid(),"
                "'worker_pid':os.getppid(),'start':start,'finish':time.monotonic_ns()}))\n"
            )
            names = [f"case-{index}" for index in range(6)]
            cases = [
                tiny_instance(name, _trace_dir=str(trace), _delay=0.6 if index == 0 else 0.25)
                for index, name in enumerate(names)
            ]
            manifest = synthetic_manifest(root, cases, seconds=3, workers=2)
            result = self.runner.evaluate_manifest(
                candidate, manifest, support=self.support, secure=False, timeout=15, workers=2
            )
            self.assertEqual(result["validity"], 1.0, result)
            self.assertEqual([case["case"] for case in result["cases"]], names)
            traces = [json.loads((trace / f"{name}.json").read_text()) for name in names]
            self.assertEqual(len({row["pid"] for row in traces}), 6)
            workers = {row["worker_pid"] for row in traces}
            self.assertGreaterEqual(len(workers), 2, "checker workers must be separate processes")
            self.assertNotIn(os.getpid(), workers, "a thread pool does not isolate checker stdout")
            events = sorted(
                [(row["start"], 1) for row in traces] + [(row["finish"], -1) for row in traces]
            )
            active = maximum = 0
            for _, change in events:
                active += change
                maximum = max(maximum, active)
            self.assertEqual(maximum, 2, "scheduler must run concurrently without exceeding cap")
            self.assertNotEqual(
                sorted(
                    names,
                    key=lambda name: json.loads((trace / f"{name}.json").read_text())["finish"],
                ),
                names,
                "fixture must finish out of order to test deterministic result ordering",
            )

    def test_manifest_hash_mismatch_is_infrastructure_failure_before_solver_runs(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = synthetic_manifest(root, [tiny_instance("bad")], seconds=1, workers=1)
            value = json.loads(manifest.read_text())
            value["cases"][0]["sha256"] = "0" * 64
            manifest.write_text(json.dumps(value))
            with self.assertRaisesRegex(RuntimeError, "checksum|hash"):
                self.runner.evaluate_manifest(
                    TASK / "init.py",
                    manifest,
                    support=self.support,
                    secure=False,
                    timeout=5,
                    workers=1,
                )

    def test_changed_official_checker_is_rejected_before_it_can_award_a_score(self) -> None:
        import shutil

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            altered_support = root / "support"
            shutil.copytree(
                self.support, altered_support, ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
            )
            checker = altered_support / "vendor/RTE_ChallengeROADEF2020_checker.py"
            checker.write_text(checker.read_text() + "\n# unapproved source change\n")
            instance = root / "one.json"
            instance.write_text(json.dumps(tiny_instance("one")))
            output = root / "schedule.txt"
            output.write_text("job 1\n")
            with self.assertRaisesRegex(RuntimeError, "checker.*hash|checksum"):
                self.runner.check_solution(instance, output, altered_support)

    def test_real_official_constraint_failure_zeros_the_whole_panel(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            candidate = root / "candidate.py"
            candidate.write_text(
                "import argparse,json\nfrom pathlib import Path\n"
                "p=argparse.ArgumentParser();p.add_argument('--instance');p.add_argument('--output');"
                "p.add_argument('--time-limit');p.add_argument('--seed');a=p.parse_args()\n"
                "d=json.loads(Path(a.instance).read_text())\n"
                "Path(a.output).write_text(''.join(f'{n} 1\\n' for n in d['Interventions']))\n"
            )
            invalid = tiny_instance("infeasible")
            invalid["Interventions"]["job"]["workload"]["crew"]["1"]["1"] = 2.0
            manifest = synthetic_manifest(
                root, [tiny_instance("valid"), invalid], seconds=2, workers=2
            )
            result = self.runner.evaluate_manifest(
                candidate, manifest, support=self.support, secure=False, timeout=10, workers=2
            )
            self.assertEqual(result["validity"], 0.0)
            self.assertEqual(result["combined_score"], 0.0)
            self.assertEqual(result["metric"]["feasible_fraction"], 0.5)
            self.assertEqual([case["status"] for case in result["cases"]], ["AC", "WA"])
            self.assertNotIn("objective", result["cases"][1])

    def test_worker_and_total_budget_caps_fail_before_execution(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = synthetic_manifest(root, [tiny_instance("one")], seconds=3, workers=1)
            with self.assertRaisesRegex(ValueError, "workers"):
                self.runner.evaluate_manifest(
                    TASK / "init.py",
                    manifest,
                    support=self.support,
                    secure=False,
                    timeout=10,
                    workers=16,
                )
            with self.assertRaisesRegex(ValueError, "outer timeout"):
                self.runner.evaluate_manifest(
                    TASK / "init.py",
                    manifest,
                    support=self.support,
                    secure=False,
                    timeout=3,
                    workers=1,
                )

    def test_candidate_failure_and_timeout_cleanup_descendant_processes(self) -> None:
        for failure in ("raise RuntimeError('candidate failed')", "time.sleep(30)"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                marker = root / "descendant.pid"
                candidate = root / "candidate.py"
                candidate.write_text(
                    "import argparse,json,subprocess,sys,time\nfrom pathlib import Path\n"
                    "p=argparse.ArgumentParser();p.add_argument('--instance');p.add_argument('--output');"
                    "p.add_argument('--time-limit');p.add_argument('--seed');a=p.parse_args()\n"
                    "d=json.loads(Path(a.instance).read_text())\n"
                    "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'])\n"
                    "Path(d['_marker']).write_text(str(child.pid))\n" + failure + "\n"
                )
                manifest = synthetic_manifest(
                    root, [tiny_instance("one", _marker=str(marker))], seconds=1, workers=1
                )
                started = time.monotonic()
                result = self.runner.evaluate_manifest(
                    candidate, manifest, support=self.support, secure=False, timeout=7, workers=1
                )
                self.assertLess(
                    time.monotonic() - started,
                    7,
                    "cleanup must be inside the advertised total budget",
                )
                self.assertEqual(result["validity"], 0.0)
                self.assertEqual(result["combined_score"], 0.0)
                self.assertEqual(
                    result["cases"][0]["status"], "RE" if failure.startswith("raise") else "TLE"
                )
                self.assertTrue(marker.exists(), "fixture must actually spawn a descendant")
                pid = int(marker.read_text())
                for _ in range(100):
                    state = subprocess.run(
                        ["ps", "-o", "stat=", "-p", str(pid)],
                        capture_output=True,
                        text=True,
                        check=False,
                    ).stdout.strip()
                    if not state or state.startswith("Z"):
                        break
                    time.sleep(0.02)
                else:
                    os.kill(pid, signal.SIGKILL)
                    self.fail("candidate descendant survived process-group cleanup")

    def test_private_failure_diagnostics_survive_cleanup_without_feedback_leak(self) -> None:
        with mock.patch.object(sys, "path", list(sys.path)):
            score = load_task_module("tests/score.py", "abc_x15_score_diagnostics")
        for failure, expected_status in (("raise SystemExit(23)", "RE"),
                                         ("time.sleep(30)", "TLE")):
            with self.subTest(status=expected_status), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                marker = root / "scratch-path.txt"
                candidate = root / "candidate.py"
                candidate.write_text(
                    "import argparse,json,sys,time\nfrom pathlib import Path\n"
                    "p=argparse.ArgumentParser();p.add_argument('--instance');p.add_argument('--output');"
                    "p.add_argument('--time-limit');p.add_argument('--seed');a=p.parse_args()\n"
                    "d=json.loads(Path(a.instance).read_text())\n"
                    "Path(d['_marker']).write_text(str(Path(a.instance).parent))\n"
                    "sys.stderr.buffer.write(b'old-prefix-' + b'x'*10000 + "
                    "b'\\xff\\xfeprivate-resource-failure');sys.stderr.flush()\n"
                    + failure + "\n"
                )
                manifest = synthetic_manifest(root, [tiny_instance("secret-case", _marker=str(marker))],
                                              seconds=0.8, workers=1)
                result = self.runner.evaluate_manifest(candidate, manifest, support=self.support,
                                                       secure=False, timeout=7, workers=1)
                record = result["cases"][0]
                self.assertFalse(Path(marker.read_text()).exists(),
                                 "diagnostics must outlive temporary scratch cleanup")
                self.assertEqual(record["status"], expected_status)
                self.assertEqual(record["candidate_returncode"], 23 if expected_status == "RE"
                                 else -signal.SIGKILL)
                tail = record["candidate_stderr_tail"]
                self.assertLessEqual(len(tail.encode("utf-8")), 8192)
                self.assertTrue(tail.endswith("private-resource-failure"))
                self.assertNotIn("old-prefix-", tail)
                self.assertGreater(record["staging_wall_seconds"], 0)
                self.assertGreater(record["candidate_wall_seconds"], 0)
                self.assertEqual(record["checker_wall_seconds"], 0.0,
                                 "failed candidates must not run the official checker")
                feedback = score.aggregate_feedback(result)
                for private_value in ("secret-case", "private-resource-failure", "candidate_returncode",
                                      "candidate_stderr_tail", "staging_wall_seconds"):
                    self.assertNotIn(private_value, feedback)

    def test_secure_commands_use_requested_distinct_cpu_and_eight_gib_limits(self) -> None:
        class ImmediateProcess:
            pid = 12345678
            returncode = 0

            def wait(self, timeout=None):
                return 0

        commands = []
        permission_layouts = []
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            candidate = root / "solver.py"
            candidate.write_text("pass\n")
            instance = root / "input.json"
            instance.write_text(json.dumps(tiny_instance("one")))
            for slot, cpu in enumerate((2, 3)):
                scratch = root / f"scratch-{slot}"
                scratch.mkdir()
                with (
                    mock.patch.object(self.runner.sys, "platform", "linux"),
                    mock.patch.object(self.runner.os, "geteuid", return_value=0),
                    mock.patch.object(self.runner.os, "chown") as ownership,
                    mock.patch.object(self.runner.os, "killpg"),
                    mock.patch.object(self.runner.shutil, "which", return_value="/bin/tool"),
                    mock.patch.object(self.runner, "check_sandbox"),
                    mock.patch.object(self.runner.subprocess, "Popen") as popen,
                ):

                    def launch(*args, **kwargs):
                        # Check the live layout before supervisor cleanup restores
                        # root:root/700. A candidate-owned parent permits replacing
                        # output/ with a symlink followed by privileged cleanup.
                        permission_layouts.append(
                            (scratch.stat().st_mode & 0o777, list(ownership.call_args_list))
                        )
                        return ImmediateProcess()

                    popen.side_effect = launch
                    self.runner.execute(
                        candidate,
                        instance,
                        scratch,
                        seconds=900,
                        seed=2020,
                        secure=True,
                        cpu=cpu,
                        uid=64000 + slot,
                    )
                commands.append(popen.call_args.args[0])
        for command, cpu, uid in zip(commands, (2, 3), (64000, 64001)):
            self.assertEqual(command[command.index("taskset") + 2], str(cpu))
            self.assertIn(f"--reuid={uid}", command)
            self.assertIn(f"--as={8 * 1024**3}", command)
            self.assertIn("--time-limit", command)
        for slot, (mode, ownership_calls) in enumerate(permission_layouts):
            scratch = root / f"scratch-{slot}"
            uid = 64000 + slot
            self.assertEqual(
                mode, 0o710, "candidate group may traverse, but must not write the parent"
            )
            self.assertIn(
                mock.call(scratch, 0, uid),
                ownership_calls,
                "root ownership anchors output/ against candidate replacement",
            )
            self.assertNotIn(mock.call(scratch, uid, uid), ownership_calls)
            self.assertIn(mock.call(scratch / "output", uid, uid), ownership_calls)


if __name__ == "__main__":
    unittest.main()
