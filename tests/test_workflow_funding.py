"""Only a finalized current head may spend a review request."""
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import workflow_funding as funding


class FundingTests(unittest.TestCase):
    def test_opening_a_final_head_is_distinct_from_intermediate_synchronization(self):
        pull = {'number': 3, 'draft': False, 'head': {'sha': 'a' * 40}}
        run = {'created_at': '2026-10-15T08:00:01Z'}
        event = {'action': 'opened', 'pull_request': {'head': pull['head']}}
        api = Mock()
        self.assertTrue(funding.finalized(api, 'lightning-it/.github', pull, run, event))
        api.pages.assert_not_called()
        event['action'] = 'synchronize'
        ready = {'event': 'ready_for_review', 'actor': {'type': 'User'}}
        for timestamp, expected in (('2026-10-15T08:00:00Z', False), ('2026-10-15T08:00:01Z', False),
                                    ('2026-10-15T08:00:02Z', True)):
            api.pages.return_value = [ready | {'created_at': timestamp}]
            with self.subTest(timestamp=timestamp):
                self.assertEqual(expected, funding.finalized(api, 'lightning-it/.github', pull, run, event))


if __name__ == '__main__':
    unittest.main()
