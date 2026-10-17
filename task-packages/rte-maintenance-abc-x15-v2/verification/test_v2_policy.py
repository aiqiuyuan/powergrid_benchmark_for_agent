"""Synthetic protocol-v2 ranking, feedback and identity regression tests."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
from pathlib import Path
import runpy
import sys
import tempfile
import types
import unittest
from unittest import mock

from helpers import TASK, load_task_module

sys.path.insert(0, str(TASK / 'support'))
from official import normalized_score
from runner import aggregate


class FeedbackV2PolicyTests(unittest.TestCase):
    def manifest(self, size=15):
        return {'cases': [{'id': f'X_{i:02}', 'scale': 2.0} for i in range(1, size+1)],
                'protocol': 'rte2020-abc-x15-v2', 'split': 'protected_x15_feedback',
                'seconds_per_case': 900}

    def rows(self, k, objective=1.0, size=15):
        return [{'case': f'X_{i:02}', 'status': 'AC' if i <= k else 'WA',
                 'valid': i <= k, 'score': normalized_score(objective, 2.0) if i <= k else 0.0,
                 **({'objective': objective, 'mean_risk': 2.0, 'expected_excess': 0.0} if i <= k else {}),
                 'constraint_errors': {} if i <= k else {'resource_upper': 3},
                 'candidate_returncode': 0, 'candidate_wall_seconds': 899.12,
                 'candidate_peak_rss': 1024, 'peak_rss_unit': 'KiB',
                 'candidate_stderr_tail': '/secret/private-input-value', 'worker_pid': 123}
                for i in range(1, size+1)]

    def result(self, k, objective=1.0, size=15):
        return aggregate(self.rows(k, objective, size), elapsed=10,
                         manifest=self.manifest(size), secure=True,
                         candidate_sha256='a'*64, manifest_sha256='b'*64)

    def score(self):
        return load_task_module('tests/score.py', 'rte_feedback_v2_policy')

    def test_zero_one_fourteen_fifteen_use_fixed_denominator_and_lexicographic_reward(self):
        for k in (0, 1, 14, 15):
            result = self.result(k)
            q = normalized_score(1.0, 2.0)*k/15
            self.assertAlmostEqual(result['metric']['quality'], q)
            self.assertEqual(result['metric']['feasible_count'], k)
            self.assertAlmostEqual(result['combined_score'], (k+q)/16)
            self.assertEqual(result['all_cases_feasible'], k == 15)
            self.assertEqual(result['validity'], float(k == 15))
        for k in range(15):
            self.assertLess(self.result(k, -1e300)['combined_score'],
                            self.result(k+1, 1e300)['combined_score'])

    def test_nonfinite_and_boolean_objectives_qualities_and_scales_fail_closed(self):
        for field in ('objective', 'mean_risk', 'expected_excess', 'score'):
            for value in (math.nan, math.inf, -math.inf, True):
                rows = self.rows(1); rows[0][field] = value
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    aggregate(rows, elapsed=0, manifest=self.manifest(), secure=True,
                              candidate_sha256='a'*64, manifest_sha256='b'*64)
        for value in (0, -1, math.nan, math.inf, True, None):
            manifest = self.manifest(); manifest['cases'][0]['scale'] = value
            with self.subTest(scale=value), self.assertRaises(ValueError):
                aggregate(self.rows(0), elapsed=0, manifest=manifest, secure=True,
                          candidate_sha256='a'*64, manifest_sha256='b'*64)

    def test_same_coverage_improves_with_lower_official_cost_and_full_panel_matches_old_q(self):
        self.assertGreater(self.result(14, 1)['combined_score'], self.result(14, 2)['combined_score'])
        self.assertAlmostEqual(self.result(15)['metric']['quality'], normalized_score(1, 2))

    def test_reduction_rejects_missing_duplicate_nan_or_inconsistent_records(self):
        for mutate in (lambda r: r.pop(), lambda r: r.__setitem__(1, copy.deepcopy(r[0])),
                       lambda r: r[0].update(objective=math.nan),
                       lambda r: r[0].update(score=math.nan),
                       lambda r: r[0].update(score=0.99),
                       lambda r: r[0].update(valid=False)):
            rows = self.rows(14); mutate(rows)
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                aggregate(rows, elapsed=1, manifest=self.manifest(), secure=True,
                          candidate_sha256='a'*64, manifest_sha256='b'*64)

    def test_partial_feedback_has_complete_safe_rows_and_invalid_null_objectives(self):
        result = self.result(1)
        result.update(private_path='/secret/path', untrusted='data')
        encoded = self.score().aggregate_feedback(result)
        data = json.loads(encoded)
        self.assertLessEqual(len(encoded.encode('utf-8')), 16384)
        self.assertEqual(data['schema_version'], 'rte-feedback-v2')
        self.assertTrue(data['evaluation_completed'])
        self.assertEqual(data['candidate_sha256'], 'a'*64)
        self.assertEqual(len(data['cases']), 15)
        self.assertEqual(data['summary']['feasible_count'], 1)
        self.assertIsNotNone(data['cases'][0]['F'])
        self.assertGreater(data['cases'][0]['q'], 0)
        self.assertIsNone(data['cases'][1]['F'])
        self.assertIsNone(data['cases'][1]['mean_risk'])
        self.assertIsNone(data['cases'][1]['expected_excess'])
        self.assertIsNone(data['cases'][1]['q'])
        self.assertEqual(data['cases'][0]['candidate_peak_rss_unit'], 'KiB')
        self.assertEqual(data['summary']['constraint_errors']['resource_upper'], 42)
        for private in ('secret', 'worker_pid', 'candidate_stderr_tail', 'private_path'):
            self.assertNotIn(private, encoded)

    def test_feedback_rejects_untrusted_categories_nan_diagnostics_incomplete_and_oversize(self):
        changes = [lambda r: r['cases'].pop(),
                   lambda r: r['cases'][0].update(status='SECRET /private/input'),
                   lambda r: r['cases'][0].update(candidate_wall_seconds=math.inf),
                   lambda r: r['cases'][0].update(constraint_errors={'secret-input': 1}),
                   lambda r: r['cases'][0].update(candidate_peak_rss=math.nan)]
        for change in changes:
            result = self.result(1); change(result)
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.score().aggregate_feedback(result)
        score = self.score()
        with mock.patch.dict(score.aggregate_feedback.__globals__, {'FEEDBACK_LIMIT': 128}):
            with self.assertRaisesRegex(ValueError, 'limit'):
                score.aggregate_feedback(self.result(1))

    def test_writer_distinguishes_infrastructure_failure_from_completed_infeasible_panel(self):
        with tempfile.TemporaryDirectory() as temp, mock.patch.dict(os.environ, {'LOG_DIR': temp}):
            score = self.score()
            score.write(0.0, error='private infrastructure /mnt/secret crash')
            detail = json.loads((Path(temp)/'reward-details.json').read_text())
            failure = json.loads(detail['feedback'])
            self.assertFalse(failure['evaluation_completed'])
            self.assertIsNone(failure['summary'])
            self.assertEqual(failure['cases'], [])
            self.assertNotIn('/mnt/secret', detail['feedback'])
            result = self.result(1)
            score.write(result['combined_score'], result=result)
            detail = json.loads((Path(temp)/'reward-details.json').read_text())
            self.assertTrue(detail['evaluation_completed'])
            self.assertFalse(detail['valid'])
            self.assertGreater(detail['reward'], 0)
            self.assertEqual(detail['metric_name'], 'rte_x15_coverage_quality_900_v2')

    def test_public_abc_reduction_has_same_policy_with_its_actual_panel_size(self):
        result = self.result(1, size=3)
        self.assertAlmostEqual(result['metric']['quality'], normalized_score(1, 2)/3)
        self.assertAlmostEqual(result['combined_score'], (1+normalized_score(1, 2)/3)/4)

    def test_feedback_refuses_wrong_budget_protocol_or_metric(self):
        for change in (lambda r: r.update(seconds_per_case=5400),
                       lambda r: r.update(protocol='rte2020-abc-x15-v1')):
            result = self.result(1); change(result)
            with self.assertRaises(ValueError): self.score().aggregate_feedback(result)
        with self.assertRaises(ValueError):
            self.score().write(0, metric_name='rte_x15_quality_900')

    def test_invalid_submission_is_completed_candidate_failure_with_null_diagnostics(self):
        rows = [{'case': f'X_{i:02}', 'status': 'INVALID_SUBMISSION', 'valid': False,
                 'score': 0.0, 'constraint_errors': {}} for i in range(1, 16)]
        result = aggregate(rows, elapsed=0, manifest=self.manifest(), secure=True,
                           candidate_sha256=None, manifest_sha256='b'*64)
        feedback = json.loads(self.score().aggregate_feedback(result))
        self.assertTrue(feedback['evaluation_completed'])
        self.assertEqual(feedback['summary']['reward'], 0)
        self.assertEqual(feedback['summary']['statuses'], {'RE': 15})
        self.assertIsNone(feedback['candidate_sha256'])
        for row in feedback['cases']:
            self.assertEqual(row['failure_kind'], 'invalid_submission')
            for key in ('F', 'q', 'candidate_returncode', 'candidate_wall_seconds',
                        'candidate_peak_rss', 'candidate_peak_rss_unit'):
                self.assertIsNone(row[key])

    def test_real_score_entry_writes_partial_reward_and_complete_feedback(self):
        result = self.result(14)
        score = self.score()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); (root/'data').mkdir()
            manifest = dict(self.manifest(), workers=15)
            (root/'data/manifest.json').write_text(json.dumps(manifest))
            with mock.patch.dict(score.main.__globals__,
                                 {'ROOT': root, 'evaluate_manifest': mock.Mock(return_value=result)}), \
                 mock.patch.dict(os.environ, {'LOG_DIR': str(root/'logs')}):
                score.main()
            detail = json.loads((root/'logs/reward-details.json').read_text())
            self.assertFalse(detail['valid'])
            self.assertTrue(detail['evaluation_completed'])
            self.assertGreater(detail['reward'], 14/16)
            self.assertEqual(len(json.loads(detail['feedback'])['cases']), 15)

    def test_score_entry_incomplete_panel_is_infrastructure_error_not_algorithm_zero(self):
        score = self.score()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); (root/'data').mkdir()
            manifest = dict(self.manifest(), workers=15); manifest['cases'].pop()
            (root/'data/manifest.json').write_text(json.dumps(manifest))
            execution = mock.Mock(side_effect=AssertionError('must not execute'))
            with mock.patch.dict(score.main.__globals__, {'ROOT': root, 'evaluate_manifest': execution}), \
                 mock.patch.dict(os.environ, {'LOG_DIR': str(root/'logs')}):
                with self.assertRaises(ValueError): score.main()
            execution.assert_not_called()
            detail = json.loads((root/'logs/reward-details.json').read_text())
            self.assertFalse(detail['evaluation_completed'])
            self.assertIsNone(detail['metric'])
            self.assertIsNone(json.loads(detail['feedback'])['summary'])

    def test_frozen_primary_and_supplemental_bind_same_source_and_receipt(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            candidate = root/'solver.py'; candidate.write_text('pass\n')
            digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
            receipt = root/'receipt.json'
            receipt.write_text(json.dumps({'protocol': 'rte2020-abc-x15-v2',
                                          'stage': 'frozen_final_source', 'candidate_sha256': digest}))
            manifest = root/'manifest.json'; manifest.write_text(json.dumps(self.manifest()))
            before = hashlib.sha256(manifest.read_bytes()).hexdigest()
            calls = []
            def fake_evaluate(candidate_path, manifest_path, **kwargs):
                body = json.loads(manifest_path.read_text()); calls.append(body)
                return {'candidate_sha256': digest, 'cases': [], 'combined_score': 0.5}
            from helpers import patch_modules
            fake_runner = types.ModuleType('runner'); fake_runner.evaluate_manifest = fake_evaluate
            for seconds in (900, 5400):
                output = root/f'report-{seconds}.json'
                args = [str(TASK/'tools/final_evaluate.py'), '--candidate', str(candidate),
                        '--freeze-receipt', str(receipt), '--manifest', str(manifest),
                        '--output', str(output), '--seconds', str(seconds)]
                with patch_modules({'runner': fake_runner}), mock.patch.object(sys, 'argv', args):
                    runpy.run_path(args[0], run_name='__main__')
                report = json.loads(output.read_text())
                self.assertEqual(report['candidate_sha256'], digest)
                self.assertEqual(report['freeze_receipt']['candidate_sha256'], digest)
                self.assertFalse(report['returns_to_developer'])
                self.assertFalse(report['feedback_budget_charged'])
            self.assertEqual([c['seconds_per_case'] for c in calls], [900, 5400])
            self.assertEqual(hashlib.sha256(manifest.read_bytes()).hexdigest(), before)

if __name__ == '__main__': unittest.main()
