"""Trust boundaries and paid-effect admission; no live credentials or model calls."""
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import workflow_control as control

REPO = 'lightning-it/.github'
BASE, HEAD, SOURCE = 'a' * 40, 'b' * 40, 'c' * 40


def pull(author=('litroc', 76040632, 'User'), **changes):
    result = {'number': 3, 'state': 'open', 'draft': False, 'title': 'Improve source', 'body': '', 'labels': [],
              'user': dict(zip(('login', 'id', 'type'), author)),
              'base': {'sha': BASE, 'ref': 'develop', 'repo': {'full_name': REPO}},
              'head': {'sha': HEAD, 'ref': 'feature', 'repo': {'full_name': REPO}}}
    result.update(changes)
    return result


def run(number=10, source=SOURCE):
    return {'id': number, 'run_attempt': 1, 'head_sha': HEAD,
            'referenced_workflows': [{'path': REPO + '/' + control.WORKFLOW + '@refs/heads/main', 'sha': source}],
            'pull_requests': [{'number': 3, 'base': {'sha': BASE}, 'head': {'sha': HEAD}}]}


class ControlTests(unittest.TestCase):
    def test_consumer_policy_cannot_select_unadmitted_source(self):
        api = Mock()
        config = {"version": 1, "repository": REPO, "mode": "reference",
                  "quality": [{"workflow": ".github/workflows/repository-quality.yml", "job": "repository / quality"}],
                  "accepted_sources": [SOURCE]}
        import json
        api.file.return_value = json.dumps(config).encode()
        self.assertEqual([SOURCE], control.policy(api, REPO, BASE, SOURCE)["accepted_sources"])
        api.file.return_value = json.dumps(config | {"accepted_sources": ['d' * 40]}).encode()
        with self.assertRaisesRegex(control.ControlError, "consumer-cannot-admit-central-source"):
            control.policy(api, REPO, BASE, SOURCE)

    def test_native_defining_source_required_not_caller_context(self):
        job = {'workflow_repository': REPO, 'workflow_file_path': control.WORKFLOW,
               'workflow_sha': SOURCE, 'check_run_id': 123}
        self.assertEqual(SOURCE, control.source_identity(job))
        for change in ({'workflow_repository': 'attacker/source'}, {'workflow_file_path': '.github/workflows/fake.yml'},
                       {'workflow_sha': 'main'}, {'check_run_id': None}):
            with self.subTest(change=change), self.assertRaises(control.ControlError):
                control.source_identity(job | change)

    def test_author_matrix_exact_ids_and_no_unknown_bot_fallback(self):
        self.assertEqual('copilot', control.classify(pull(), REPO))
        self.assertEqual('codex', control.classify(pull(control.RELEASE), REPO))
        for author in ((control.RELEASE[0], 1, 'Bot'), ('unknown[bot]', 1, 'Bot')):
            with self.subTest(author=author), self.assertRaises(control.ControlError):
                control.classify(pull(author), REPO)
        promotion = pull(control.RELEASE)
        promotion['head']['ref'], promotion['base']['ref'] = 'develop', 'main'
        self.assertEqual('promotion', control.classify(promotion, REPO))
        promotion['head']['repo']['full_name'] = 'attacker/fork'
        with self.assertRaises(control.ControlError):
            control.classify(promotion, REPO)

    def test_renovate_is_narrow_and_other_renovate_still_requires_review(self):
        value = pull(control.RENOVATE)
        value['head']['ref'] = 'renovate/dependency'
        value['labels'] = [{'name': name} for name in ('renovate', 'dependencies', 'safe-automerge')]
        self.assertEqual('renovate', control.classify(value, REPO))
        value['labels'].append({'name': 'breaking-update'})
        self.assertEqual('copilot', control.classify(value, REPO))

    def test_native_run_is_request_reservation_and_rerun_or_later_event_cannot_fund(self):
        api = Mock()
        api.call.return_value = run()
        api.pages.return_value = [run()]
        self.assertEqual(10, control.reserve_request(api, REPO, pull(), SOURCE, 10, 1))
        api.pages.return_value = [run(), run(11)]
        for number, attempt in ((11, 1), (10, 2)):
            with self.subTest(number=number, attempt=attempt), self.assertRaises(control.ControlError):
                control.reserve_request(api, REPO, pull(), SOURCE, number, attempt)
        self.assertTrue(all(call.kwargs.get('method', 'GET') == 'GET' for call in api.call.call_args_list))

    def test_candidate_authored_run_and_check_name_are_not_reservations(self):
        api = Mock()
        api.call.return_value = run() | {'referenced_workflows': []}
        with self.assertRaisesRegex(control.ControlError, 'request-origin'):
            control.reserve_request(api, REPO, pull(), SOURCE, 10, 1)

    def test_changed_head_labels_body_base_or_author_invalidates_current_tuple(self):
        value = pull()
        api = Mock(); api.call.return_value = value
        expected = control.binding(value)
        for change in ({'title': 'changed'}, {'body': 'changed'}, {'labels': [{'name': 'other'}]},
                       {'head': value['head'] | {'sha': 'd' * 40}}, {'base': value['base'] | {'sha': 'e' * 40}},
                       {'user': {'login': 'other', 'id': 2, 'type': 'User'}}):
            api.call.return_value = value | change
            with self.subTest(change=change), self.assertRaisesRegex(control.ControlError, 'stale'):
                control.live_pull(api, REPO, 3, expected)

    def test_copilot_review_needs_current_head_and_useful_error_free_content(self):
        review = {'id': 9, 'commit_id': HEAD, 'user': {'login': control.COPILOT, 'id': 175728472, 'type': 'Bot'}, 'state': 'COMMENTED',
                  'body': 'Reviewed all changes; no actionable issues found.'}
        api = Mock(); api.pages.side_effect = [[review], []]
        self.assertEqual(9, control.copilot_review(api, REPO, pull())['id'])
        for body in ('', 'Unable to review this pull request', 'Quota exceeded', 'No files were reviewed'):
            api.pages.side_effect = [[review | {'body': body}], []]
            with self.subTest(body=body), self.assertRaises(control.ControlError):
                control.copilot_review(api, REPO, pull())
        api.pages.side_effect = [[review | {'commit_id': 'd' * 40}]]
        self.assertIsNone(control.copilot_review(api, REPO, pull()))

    def test_unresolved_findings_and_dismissed_review_never_pass(self):
        review = {'id': 9, 'commit_id': HEAD, 'user': {'login': control.COPILOT, 'id': 175728472, 'type': 'Bot'}, 'state': 'COMMENTED', 'body': 'Reviewed'}
        for reviews, comments in (([review], [{'id': 1, 'body': 'Fix this'}]), ([review | {'state': 'DISMISSED'}], []),
                                  ([review, review | {'id': 10}], [])):
            api = Mock(); api.pages.side_effect = [reviews, comments]
            with self.subTest(reviews=reviews, comments=comments), self.assertRaises(control.ControlError):
                control.copilot_review(api, REPO, pull())

    def test_native_ingress_requires_exact_source_association_and_completed_gate(self):
        api = Mock(); source_run = run() | {'status': 'completed', 'conclusion': 'success'}
        api.pages.side_effect = [[source_run], [{'id': 100, 'run_id': 10, 'name': 'Current revision review', 'conclusion': 'success'}]]
        self.assertEqual(10, control.check_native_control(api, REPO, pull(), {'accepted_sources': [SOURCE]})['run'])
        for changed in (source_run | {'referenced_workflows': []}, source_run | {'conclusion': 'failure'},
                        source_run | {'pull_requests': [{'number': 3, 'base': {'sha': 'f' * 40}, 'head': {'sha': HEAD}}]}):
            api.pages.side_effect = [[changed]]
            with self.subTest(changed=changed), self.assertRaises(control.ControlError):
                control.check_native_control(api, REPO, pull(), {'accepted_sources': [SOURCE]})

    def test_missing_distribution_proof_never_uses_actor_as_bypass(self):
        with self.assertRaisesRegex(control.ControlError, 'distribution-receipt-missing'):
            control.distribution_evidence(Mock(), REPO, pull(control.SYNC), {})


if __name__ == '__main__':
    unittest.main()
