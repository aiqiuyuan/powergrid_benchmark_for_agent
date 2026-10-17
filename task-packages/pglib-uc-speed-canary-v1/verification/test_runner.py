"""Real local child-process fixtures; Linux privilege acceptance is separate."""

import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "support"))
from runner import evaluate, regular_bytes, stage_source


def tiny_instance():
    return {
        "time_periods": 1,
        "demand": [5],
        "reserves": [0],
        "renewable_generators": {},
        "thermal_generators": {
            "g": {
                "must_run": 0,
                "power_output_minimum": 0,
                "power_output_maximum": 10,
                "ramp_up_limit": 10,
                "ramp_down_limit": 10,
                "ramp_startup_limit": 10,
                "ramp_shutdown_limit": 10,
                "time_up_minimum": 1,
                "time_down_minimum": 1,
                "unit_on_t0": 1,
                "time_up_t0": 1,
                "time_down_t0": 0,
                "power_output_t0": 5,
                "startup": [{"lag": 1, "cost": 0}],
                "piecewise_production": [{"mw": 0, "cost": 0}, {"mw": 10, "cost": 20}],
            }
        },
    }


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"
        self.source.mkdir()
        instance = self.root / "instance.json"
        instance.write_text(json.dumps(tiny_instance()))
        manifest = {
            "instance": instance.name,
            "instance_sha256": hashlib.sha256(instance.read_bytes()).hexdigest(),
            "execution_seconds": 1,
            "reference_upper": 10,
            "reference_lower": 10,
            "target_gap_ratio": 0.001,
        }
        self.manifest = self.root / "manifest.json"
        self.manifest.write_text(json.dumps(manifest))

    def tearDown(self):
        self.temporary.cleanup()

    def candidate(self, *, power=5, ending=""):
        # Python fixtures use a .jl name only to exercise the exact source contract.
        code = f"""import json,sys,time
from pathlib import Path
out=Path(sys.argv[2])
value={{"schema":"uc-schedule-v1", "renewable":{{}},
       "thermal":{{"g":{{"on":[1],"power":[{power}],"reserve":[0]}}}}}}
temporary=out/'0001.tmp'
temporary.write_text(json.dumps(value))
temporary.rename(out/'0001.json')
{ending}
"""
        (self.source / "solver.jl").write_text(code)

    def grade(self):
        return evaluate(
            self.source, self.manifest, seeds=[0], secure=False, interpreter=[sys.executable, "-I"]
        )

    def test_valid_source_is_executed_and_checked(self):
        self.candidate()
        result = self.grade()
        self.assertTrue(result["feedback"]["target_hit"])
        self.assertGreater(result["feedback"]["reward"], 0.5)
        self.assertGreater(result["execution"][0]["snapshots_received"], 0)

    def test_physically_invalid_output_cannot_score(self):
        self.candidate(power=4)
        self.assertFalse(self.grade()["feedback"]["feasible"])

    def test_crash_invalidates_an_earlier_valid_snapshot(self):
        self.candidate(ending="time.sleep(.05); raise SystemExit(7)")
        self.assertEqual(self.grade()["feedback"]["reward"], 0)

    def test_normal_wall_deadline_can_keep_valid_incumbent(self):
        self.candidate(ending="time.sleep(10)")
        result = self.grade()
        self.assertEqual(result["execution"][0]["status"], "DEADLINE")
        self.assertTrue(result["feedback"]["feasible"])

    def test_symlink_and_hardlink_artifacts_are_rejected(self):
        target = self.root / "target"
        target.write_text("test")
        link = self.root / "link"
        link.symlink_to(target)
        with self.assertRaises(OSError):
            regular_bytes(link, 100)
        link.unlink()
        os.link(target, link)
        with self.assertRaises(ValueError):
            regular_bytes(link, 100)

    def test_static_schedule_artifact_is_rejected(self):
        self.candidate()
        (self.source / "schedule.json").write_text("{}")
        with self.assertRaises(ValueError):
            stage_source(self.source, self.root / "staged")

    def test_mutated_frozen_input_is_infrastructure_error(self):
        self.candidate()
        (self.root / "instance.json").write_text("{}")
        with self.assertRaises(RuntimeError):
            self.grade()

    def test_source_is_frozen_once_before_all_replays(self):
        original = self.source / "solver.jl"
        self.candidate(ending=f"Path({str(original)!r}).write_text('raise SystemExit(9)')")
        result = evaluate(
            self.source,
            self.manifest,
            seeds=[0, 1, 2],
            secure=False,
            interpreter=[sys.executable, "-I"],
        )
        self.assertEqual(len(result["replays"]), 3)
        self.assertTrue(result["feedback"]["feasible"])


if __name__ == "__main__":
    unittest.main()
