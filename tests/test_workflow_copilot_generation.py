"""A service run predating a PR cannot reserve that PR's review request."""
import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import workflow_control as control
from test_workflow_control import REPO, delivery, native_review, pull


class CopilotGenerationTests(unittest.TestCase):
    CREATED = '2026-10-14T23:00:00Z'
    BEFORE = '2026-10-14T22:59:59Z'
    AFTER = '2026-10-14T23:00:01Z'

    def pending(self, deliveries):
        api = Mock()
        api.call.return_value = {'users': []}
        api.pages.return_value = deliveries
        return control.copilot_delivery_pending(api, REPO, pull(created_at=self.CREATED))

    def test_older_empty_locator_does_not_reserve_a_later_pr_request(self):
        self.assertFalse(self.pending([delivery(created_at=self.BEFORE, pull_requests=[])]))

    def test_older_failed_delivery_cannot_spend_the_later_pr_budget(self):
        self.assertFalse(self.pending([delivery(created_at=self.BEFORE, pull_requests=[], conclusion='failure')]))

    def test_real_current_pending_delivery_still_prevents_a_duplicate(self):
        self.assertTrue(self.pending([delivery(created_at=self.BEFORE, pull_requests=[]),
                                     delivery(id=21, created_at=self.AFTER, status='in_progress', conclusion=None)]))

    def test_real_current_failure_still_forbids_automatic_retry(self):
        with self.assertRaisesRegex(control.ControlError, 'no-automatic-retry'):
            self.pending([delivery(created_at=self.BEFORE, pull_requests=[]),
                          delivery(id=21, created_at=self.AFTER, conclusion='failure')])

    def test_later_native_review_uses_only_its_actual_current_producer(self):
        api = Mock()
        api.pages.side_effect = [[native_review()],
                                 [delivery(created_at=self.BEFORE, pull_requests=[]),
                                  delivery(id=21, created_at=self.AFTER)], []]
        result = control.copilot_review(api, REPO, pull(created_at=self.CREATED))
        self.assertEqual(21, result['service_run'])

    def test_missing_equal_later_or_invalid_times_never_exclude_unknown_delivery(self):
        for value in (None, '', self.CREATED, self.AFTER, '2026-02-30T00:00:00Z',
                      '2026-10-14', '2026-10-14T22:59:59+00:00',
                      '2026-10-14T22:59:59.999Z', 1, True):
            with self.subTest(created_at=value), self.assertRaisesRegex(control.ControlError, 'pr-association-unavailable'):
                self.pending([delivery(created_at=value, pull_requests=[])])

    def test_missing_or_invalid_pr_time_never_excludes_unknown_delivery(self):
        for value in (None, '', 'invalid', '2026-02-30T00:00:00Z'):
            subject = pull(created_at=value)
            with self.subTest(created_at=value), self.assertRaisesRegex(control.ControlError, 'pr-association-unavailable'):
                control.associated_delivery(delivery(created_at=self.BEFORE, pull_requests=[]), subject)

    def test_time_possible_ambiguous_locator_still_fails_closed(self):
        current = delivery(created_at=self.AFTER)
        current['pull_requests'].append(copy.deepcopy(current['pull_requests'][0]))
        with self.assertRaisesRegex(control.ControlError, 'pr-association-ambiguous'):
            self.pending([current])

    def test_chronology_cannot_exclude_a_non_native_or_wrong_head_record(self):
        for change in ({'event': 'pull_request'}, {'head_sha': 'f' * 40}):
            with self.subTest(change=change), self.assertRaisesRegex(control.ControlError, 'pr-association-unavailable'):
                self.pending([delivery(created_at=self.BEFORE, pull_requests=[], **change)])

    def test_unknown_chronology_does_not_replace_a_valid_current_binding(self):
        self.assertTrue(self.pending([delivery(created_at='unknown', status='in_progress', conclusion=None)]))
