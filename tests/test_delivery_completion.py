"""Completion cannot overlook a native hold just because its SHA is different."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import Mock

spec = importlib.util.spec_from_file_location('completion', Path(__file__).resolve().parents[1] / 'scripts/check-delivery-completion.py')
completion = importlib.util.module_from_spec(spec)
spec.loader.exec_module(completion)
SINCE = '2026-10-17T00:00:00Z'


def run(identifier=1, **overrides):
    return {'id': identifier, 'path': '.github/workflows/delivery-operations.yml',
            'created_at': SINCE, 'head_sha': 'default-branch-sha', 'run_attempt': 1,
            'status': 'completed', 'conclusion': 'success', **overrides}


class CompletionTests(unittest.TestCase):
    def audit(self, rows):
        api = Mock(return_value={'workflow_runs': rows, 'total_count': len(rows)})
        result = completion.audit(api, 'lightning-it/example', SINCE)
        self.assertNotIn('head_sha=', api.call_args.args[0])
        return result

    def test_default_branch_hold_blocks_and_all_success_clears(self):
        result = self.audit([run(conclusion='action_required')])
        self.assertFalse(result['auxiliary_clear'])
        self.assertEqual('default-branch-sha', result['approval_holds'][0]['head_sha'])
        self.assertTrue(self.audit([run()])['auxiliary_clear'])

    def test_second_stage_and_waiting_environment_are_not_hidden_by_first_success(self):
        for hold in (run(2, conclusion='action_required'), run(2, status='waiting', conclusion=None,
                         path='.github/workflows/product-release.yml')):
            self.assertFalse(self.audit([run(), hold])['auxiliary_clear'])

    def test_inflight_metadata_must_finish_but_a_skipped_historical_callback_is_not_a_pass(self):
        self.assertFalse(self.audit([run(status='queued', conclusion=None)])['auxiliary_clear'])
        result = self.audit([run(conclusion='skipped')])
        self.assertTrue(result['auxiliary_clear'])
        self.assertNotIn('required_checks_passed', result)

    def test_same_head_copilot_deliveries_flag_inspection_but_distinct_heads_do_not(self):
        first = run(path=completion.COPILOT, head_sha='a')
        self.assertFalse(self.audit([first, run(2, path=completion.COPILOT, head_sha='a')])['auxiliary_clear'])
        self.assertTrue(self.audit([first, run(2, path=completion.COPILOT, head_sha='b')])['auxiliary_clear'])
        self.assertFalse(self.audit([run(path=completion.COPILOT, run_attempt=2)])['auxiliary_clear'])

    def test_truncation_or_unstable_pages_cannot_report_success(self):
        api = Mock(return_value={'workflow_runs': [], 'total_count': 1})
        with self.assertRaises(ValueError):
            completion.audit(api, 'lightning-it/example', SINCE)
        with self.assertRaises(ValueError):
            self.audit([run(), run()])

    def test_timezone_is_explicit(self):
        with self.assertRaises(ValueError):
            completion.timestamp('2026-10-17T00:00:00')
