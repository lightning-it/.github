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
            'event': 'workflow_run', 'html_url': 'https://github.com/lightning-it/example/actions/runs/1',
            'created_at': SINCE, 'head_sha': 'default-branch-sha', 'run_attempt': 1,
            'status': 'completed', 'conclusion': 'success', **overrides}


def review(identifier=1, *, number=1, base='b', head='a', **overrides):
    return run(identifier, path=completion.COPILOT, head_sha=head,
               pull_requests=[{'number': number,
                               'base': {'ref': 'develop', 'sha': base, 'repo': {'id': 1}},
                               'head': {'ref': 'change', 'sha': head, 'repo': {'id': 1}}}],
               **overrides)


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
        first = review()
        self.assertFalse(self.audit([first, review(2)])['auxiliary_clear'])
        self.assertTrue(self.audit([first, review(2, head='b')])['auxiliary_clear'])
        self.assertFalse(self.audit([review(run_attempt=2)])['auxiliary_clear'])

    def test_truncation_or_unstable_pages_cannot_report_success(self):
        api = Mock(return_value={'workflow_runs': [], 'total_count': 1})
        with self.assertRaises(ValueError):
            completion.audit(api, 'lightning-it/example', SINCE)
        with self.assertRaises(ValueError):
            self.audit([run(), run()])

    def test_timezone_is_explicit(self):
        with self.assertRaises(ValueError):
            completion.timestamp('2026-10-17T00:00:00')

    def test_inventory_shrinking_between_pages_cannot_hide_unread_hold(self):
        api = Mock(side_effect=[
            {'workflow_runs': [run(i) for i in range(1, 101)], 'total_count': 101},
            {'workflow_runs': [], 'total_count': 100}])
        with self.assertRaisesRegex(ValueError, 'changed during pagination'):
            completion.audit(api, 'lightning-it/example', SINCE)

    def test_missing_or_malformed_classification_fields_fail_closed(self):
        for key in run():
            row = run()
            del row[key]
            with self.subTest(missing=key), self.assertRaises(ValueError):
                self.audit([row])
        for overrides in ({'id': True}, {'run_attempt': 0}, {'run_attempt': '2'},
                          {'path': None}, {'status': 'unknown'}, {'conclusion': 'unknown'},
                          {'status': []}, {'conclusion': []},
                          {'status': 'queued', 'conclusion': 'success'},
                          {'created_at': 123}, {'head_sha': []}):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                self.audit([run(**overrides)])

    def test_consumer_and_ref_qualified_metadata_paths_cannot_hide_active_runs(self):
        for path in ('.github/workflows/delivery.yml',
                     '.github/workflows/review-events.yml@main',
                     '.github/workflows/review-events.yml@refs/heads/main'):
            with self.subTest(path=path):
                self.assertFalse(self.audit([run(path=path, status='in_progress', conclusion=None)])['auxiliary_clear'])

    def test_fixed_count_rerun_after_first_page_is_detected(self):
        first = [run(i) for i in range(1, 101)]
        changed = [run(1, run_attempt=2, status='waiting', conclusion=None), *first[1:]]
        api = Mock(side_effect=[
            {'workflow_runs': first, 'total_count': 101},
            {'workflow_runs': [run(101)], 'total_count': 101},
            {'workflow_runs': changed, 'total_count': 101},
            {'workflow_runs': [run(101)], 'total_count': 101}])
        with self.assertRaisesRegex(ValueError, 'state changed'):
            completion.audit(api, 'lightning-it/example', SINCE)

    def test_same_head_distinct_pr_or_base_is_not_a_duplicate(self):
        for distinct in (review(2, base='c'), review(2, number=2)):
            self.assertTrue(self.audit([review(), distinct])['auxiliary_clear'])
        for pulls in ([], None, [{}, {}], [{}]):
            row = review()
            row['pull_requests'] = pulls
            result = self.audit([row])
            self.assertFalse(result['auxiliary_clear'])
            self.assertEqual('native-pr-base-head-unavailable',
                             result['review_deliveries_to_inspect'][0]['inspection_reason'])

    def test_advanced_live_pr_head_does_not_relabel_an_older_native_run(self):
        old = review(head='old')
        old['pull_requests'][0]['head']['sha'] = 'new'
        self.assertTrue(self.audit([old, review(2, head='new')])['auxiliary_clear'])
