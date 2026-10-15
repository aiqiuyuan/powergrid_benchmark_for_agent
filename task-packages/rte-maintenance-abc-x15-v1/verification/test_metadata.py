"""Source-only lock, split and security regression checks; no dataset downloads."""

from __future__ import annotations

import json
import math
import re
import subprocess
import sys
import tomllib
import unittest

from helpers import CHECKER_SHA256, FEEDBACK_IDS, PUBLIC_IDS, TASK, digest


class SourcePackageContractTests(unittest.TestCase):
    def test_locked_sixty_instances_have_complete_disjoint_roles(self) -> None:
        lock = json.loads((TASK / "data-lock.json").read_text())
        self.assertEqual(lock["source_commit"], "052def4d47271f913f89a68169083059732360f3")
        self.assertEqual((lock["public_count"], lock["protected_count"]), (45, 15))
        cases = lock["cases"]
        self.assertEqual(len(cases), 60)
        self.assertEqual({case["id"] for case in cases}, PUBLIC_IDS | FEEDBACK_IDS)
        public = [case for case in cases if case["role"] == "development"]
        protected = [case for case in cases if case["role"] == "protected_evaluation"]
        self.assertEqual({case["id"] for case in public}, PUBLIC_IDS)
        self.assertEqual({case["id"] for case in protected}, FEEDBACK_IDS)
        self.assertFalse(
            {case["sha256"] for case in public} & {case["sha256"] for case in protected}
        )
        self.assertFalse(lock["historical_rank_equivalence"])
        for case in cases:
            with self.subTest(case=case["id"]):
                self.assertRegex(case["sha256"], r"^[0-9a-f]{64}$")
                self.assertEqual(case["path"], f"{case['id']}.json")
                self.assertEqual(case["group"], case["id"][0])
                self.assertGreater(case["bytes"], 0)
                self.assertTrue(math.isfinite(case["scale"]))
                self.assertGreater(case["scale"], 0)

    def test_checker_starter_and_archive_sources_remain_pinned(self) -> None:
        lock = json.loads((TASK / "source-lock.json").read_text())
        name = "RTE_ChallengeROADEF2020_checker.py"
        self.assertEqual(lock["files"][name]["sha256"], CHECKER_SHA256)
        self.assertEqual(digest(TASK / "support/vendor" / name), CHECKER_SHA256)
        self.assertEqual(json.loads((TASK / "support/source-lock.json").read_text()), lock)
        starter = json.loads((TASK / "starter-lock.json").read_text())
        self.assertEqual(digest(TASK / "init.py"), starter["sha256"])
        self.assertEqual(digest(TASK / "environment/app/submission/solver.py"), starter["sha256"])
        archives = json.loads((TASK / "data-archives-lock.json").read_text())
        self.assertEqual({row["key"] for row in archives["archives"]}, {"A", "B", "C", "X1", "X2"})
        for row in archives["archives"]:
            self.assertRegex(row["sha256"], r"^[0-9a-f]{64}$")
            self.assertIn(archives["source_commit"], row["url"])

    def test_developer_payload_has_no_protected_x_instance(self) -> None:
        app = TASK / "environment/app"
        protected_names = {f"{case}.json" for case in FEEDBACK_IDS}
        leaked = [
            str(path.relative_to(app))
            for path in app.rglob("*")
            if path.is_file() and path.name in protected_names
        ]
        self.assertEqual(leaked, [])
        self.assertFalse((app / "tests/data/manifest.json").exists())

    def test_verifier_resources_and_separation_cover_the_declared_worker_panel(self) -> None:
        config = tomllib.loads((TASK / "task.toml").read_text())
        self.assertEqual(config["artifacts"], ["/app/submission/solver.py"])
        verifier = config["verifier"]
        self.assertEqual(verifier["environment_mode"], "separate")
        self.assertGreater(verifier["timeout_sec"], 900)
        self.assertLess(verifier["timeout_sec"], 15 * 900)
        self.assertGreaterEqual(verifier["environment"]["cpus"], 15)
        self.assertGreaterEqual(verifier["environment"]["memory_mb"], 15 * 8192)
        self.assertEqual(verifier["environment"]["network_mode"], "no-network")

    def test_freeze_cli_runs_without_third_party_site_packages(self) -> None:
        result = subprocess.run(
            [sys.executable, "-S", str(TASK / "tools/freeze_candidate.py"), "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--candidate", result.stdout)

    def test_seccomp_blocklist_includes_affinity_changes(self) -> None:
        # This catches accidental policy removal. It does not execute or certify seccomp.
        source = (TASK / "images/exec_candidate.c").read_text()
        match = re.search(r"const\s+char\s*\*\s*blocked\[\]\s*=\s*\{(.*?)\};", source, re.DOTALL)
        self.assertIsNotNone(match)
        self.assertIn("sched_setaffinity", re.findall(r'"([^"\\]+)"', match.group(1)))
        self.assertRegex(source, r"seccomp_rule_add\(filter,\s*SCMP_ACT_ERRNO\(EPERM\),\s*syscall")


if __name__ == "__main__":
    unittest.main()
