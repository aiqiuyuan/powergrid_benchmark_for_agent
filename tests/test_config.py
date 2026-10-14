"""Configuration values remain undecided until explicitly supplied."""

import copy
import json
import unittest
from pathlib import Path

from powergrid_bench.config import FIELDS, validate_configuration

ROOT = Path(__file__).resolve().parents[1]


def configured_fixture() -> dict:
    """Produce only synthetic test settings, with no calibrated research claim."""
    config = json.loads((ROOT / "configs/experiment.template.json").read_text())
    config["status"] = "configured"
    for field in FIELDS:
        parent = config
        parts = field.path.split(".")
        for part in parts[:-1]:
            parent = parent[part]
        if field.choices:
            value = field.choices[0]
        elif field.kind == "integer":
            value = 1
        elif field.kind == "number":
            value = 1.0
        elif field.kind == "array":
            value = [0]
        elif field.kind == "boolean":
            value = True
        elif field.kind == "digest":
            value = "a" * 64
        else:
            value = "fixture-only"
        parent[parts[-1]] = value
    config["repetitions"]["count"] = 1
    config["deployment"]["runtime_image_digest"] = "sha256:" + "b" * 64
    return config


class ConfigurationTests(unittest.TestCase):
    def test_draft_reports_unset_values_without_defaults(self):
        draft = json.loads((ROOT / "configs/experiment.template.json").read_text())
        before = copy.deepcopy(draft)
        report = validate_configuration(draft)
        self.assertTrue(report.valid_draft)
        self.assertFalse(report.executable)
        self.assertIn("budgets.feedback_jobs", report.unresolved)
        self.assertIn("budgets.development_seconds", report.unresolved)
        self.assertEqual(before, draft)

    def test_fully_explicit_fixture_is_configured(self):
        self.assertTrue(validate_configuration(configured_fixture()).executable)

    def test_zero_is_zero_feedback_not_unlimited(self):
        config = configured_fixture()
        config["budgets"]["feedback_jobs"] = 0
        self.assertTrue(validate_configuration(config).executable)
        config["budgets"]["feedback_jobs"] = -1
        self.assertFalse(validate_configuration(config).valid_draft)

    def test_bool_nan_and_infinity_are_not_numeric_budgets(self):
        for value in (True, float("nan"), float("inf"), 0, -1):
            config = configured_fixture()
            config["budgets"]["development_seconds"] = value
            self.assertFalse(validate_configuration(config).valid_draft, repr(value))

    def test_unknown_keys_cannot_silently_change_protocol(self):
        config = configured_fixture()
        config["budgets"]["feedback_jobz"] = 20
        self.assertFalse(validate_configuration(config).valid_draft)

    def test_cumulative_cap_and_reservations_are_rejected(self):
        for field, value in (
            ("cumulative_token_cap", 100),
            ("token_reservation", True),
            ("token_reservation", 0),
        ):
            config = configured_fixture()
            config["policy"][field] = value
            self.assertFalse(validate_configuration(config).valid_draft)

    def test_paired_repetitions_have_exact_distinct_seeds(self):
        config = configured_fixture()
        config["repetitions"] = {"count": 2, "development_seeds": [0]}
        self.assertFalse(validate_configuration(config).valid_draft)
        config["repetitions"]["development_seeds"] = [0, 0]
        self.assertFalse(validate_configuration(config).valid_draft)

    def test_draft_flag_prevents_execution_even_when_fields_are_filled(self):
        config = configured_fixture()
        config["status"] = "draft"
        report = validate_configuration(config)
        self.assertTrue(report.valid_draft)
        self.assertFalse(report.executable)

    def test_non_model_method_does_not_need_model_settings(self):
        config = configured_fixture()
        config["method"]["backend"] = "training"
        config["model"] = {key: None for key in config["model"]}
        self.assertTrue(validate_configuration(config).executable)

    def test_extremely_large_number_is_rejected_without_crashing(self):
        config = configured_fixture()
        config["budgets"]["development_seconds"] = 1 << 20000
        self.assertFalse(validate_configuration(config).valid_draft)
