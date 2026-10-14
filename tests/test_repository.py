"""Check persisted design declarations against the implemented field catalog."""

import json
import unittest
from pathlib import Path

from powergrid_bench.cli import _adapter_check
from powergrid_bench.config import TASKS, configuration_catalog, template_configuration

ROOT = Path(__file__).resolve().parents[1]


class RepositoryContractTests(unittest.TestCase):
    def test_configuration_files_match_implemented_catalog(self):
        self.assertEqual(
            json.loads((ROOT / "configs/experiment.template.json").read_text()),
            template_configuration(),
        )
        catalog = json.loads((ROOT / "configs/configuration-catalog.json").read_text())
        self.assertEqual(catalog, json.loads(json.dumps(configuration_catalog())))

    def test_all_five_task_designs_remain_uncertified(self):
        directory = ROOT / "manifests/task-adapters"
        self.assertEqual({path.stem for path in directory.glob("*.json")}, set(TASKS))
        for task_id in TASKS:
            report = _adapter_check(str(directory / f"{task_id}.json"))
            self.assertTrue(report["valid_design"], report)
            self.assertFalse(report["release_ready"])

    def test_manual_certification_flags_cannot_bypass_gate(self):
        import tempfile

        source = ROOT / "manifests/task-adapters/unit-commitment.json"
        document = json.loads(source.read_text())
        document["release_ready"] = True
        document["certification_status"] = "certified"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "forged.json"
            path.write_text(json.dumps(document))
            report = _adapter_check(str(path))
        self.assertFalse(report["valid_design"])
        self.assertFalse(report["release_ready"])
