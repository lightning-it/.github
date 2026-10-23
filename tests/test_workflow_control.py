"""Trust boundaries and paid-effect admission; no live credentials or model calls."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import workflow_control as control
import workflow_events as events

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
            'path': control.WORKFLOW, 'workflow_id': 77,
            'workflow_url': f'https://api.github.com/repos/{REPO}/actions/required_workflows/77',
            'pull_requests': [{'number': 3, 'base': {'sha': BASE}, 'head': {'sha': HEAD}}]}


def refresh_jobs(attempt=1):
    return [{'id': attempt * 100 + index, 'run_id': 10, 'run_attempt': attempt,
             'name': name, 'status': 'completed', 'conclusion': 'success'}
            for index, name in enumerate(('Protected current revision', 'Current revision review'), 1)]


def refresh_api(observations, views, *, post_error=None):
    api = Mock()
    native, inventory = iter(observations), iter(views)
    def call(path, **kwargs):
        if kwargs.get('method') == 'POST':
            if post_error is not None:
                raise post_error
            return {}
        if path == f'repos/{REPO}/pulls/3':
            return pull()
        if path == f'repos/{REPO}/actions/runs/10':
            return next(native)
        raise AssertionError(path)
    def pages(path, key):
        if path == f'repos/{REPO}/actions/runs?head_sha={HEAD}':
            return [run()]
        if path.startswith(f'repos/{REPO}/actions/runs/10/attempts/') and path.endswith('/jobs'):
            return next(inventory)
        raise AssertionError(path)
    api.call.side_effect, api.pages.side_effect = call, pages
    return api


def verifier_only_refresh_api():
    api = Mock()
    review = refresh_jobs()[0] | {'head_sha': HEAD}
    origin = run() | {'status': 'completed', 'conclusion': 'success'}
    state = {'attempt': 2, 'review': review.copy(), 'origin': origin.copy(),
             'origin_jobs': [review.copy(), refresh_jobs()[1]]}
    def final():
        return refresh_jobs(state['attempt'])[1] | {'head_sha': HEAD}
    def call(path, **kwargs):
        if kwargs.get('method') == 'POST': return {}
        if path == f'repos/{REPO}/pulls/3': return pull()
        if path == f'repos/{REPO}/actions/runs/22':
            return {'id': 22, 'name': events.SIGNAL_NAME, 'path': events.SIGNAL_PATH, 'status': 'completed',
                    'event': 'pull_request_review', 'pull_requests': run()['pull_requests']}
        if path == f'repos/{REPO}/actions/runs/10':
            return origin | {'run_attempt': state['attempt']}
        if path == f'repos/{REPO}/actions/jobs/101': return state['review'].copy()
        if path == f'repos/{REPO}/actions/runs/10/attempts/1': return state['origin'].copy()
        raise AssertionError(path)
    def pages(path, key):
        if path == f'repos/{REPO}/actions/runs?head_sha={HEAD}': return [origin | {'run_attempt': state['attempt']}]
        if path == f'repos/{REPO}/actions/runs/10/jobs?filter=latest': return state.get('latest', [review, final()])
        if path == f'repos/{REPO}/actions/runs/10/attempts/1/jobs': return state['origin_jobs']
        if path == f'repos/{REPO}/actions/runs/10/attempts/{state["attempt"]}/jobs': return [final()]
        raise AssertionError(path)
    api.call.side_effect, api.pages.side_effect = call, pages
    return api, state


NATIVE_BODY = """<!-- ccr-overview-v2 -->

### 🟢 Approval recommended

The complete proposed source has no actionable findings.

**0 open findings**

🧠 **Review effort:** Balanced
"""


def native_review(**changes):
    return {'id': 9, 'node_id': 'PRR_native_review9', 'commit_id': HEAD,
            'user': {'login': control.COPILOT, 'id': 175728472, 'type': 'Bot'},
            'state': 'COMMENTED', 'submitted_at': '2026-10-15T00:00:05Z',
            'body': NATIVE_BODY, 'body_html': '<p>Native source assessment.</p>'} | changes


def delivery(**changes):
    return {'id': 20, 'run_attempt': 1, 'path': 'dynamic/agents/copilot-pull-request-reviewer',
            'event': 'dynamic', 'status': 'completed', 'conclusion': 'success', 'head_sha': HEAD,
            'run_started_at': '2026-10-15T00:00:00Z', 'updated_at': '2026-10-15T00:00:10Z',
            'pull_requests': run()['pull_requests']} | changes


class NativeAPIReadTests(unittest.TestCase):
    PATH = 'repos/lightning-it/private-example/pulls/791?private=value'

    @staticmethod
    def response(status=0, stdout=b'{}', stderr=b''):
        return subprocess.CompletedProcess(['gh'], status, stdout, stderr)

    def test_api_transient_get_recovers_without_repeating_a_write(self):
        for code in (502, 503, 504):
            with self.subTest(code=code), patch.object(control.subprocess, 'run') as command, \
                    patch.object(control.time, 'sleep') as wait:
                command.side_effect = [self.response(1, stderr=f'gh: unavailable (HTTP {code})\n'.encode()),
                                       self.response(stdout=b'{"id":791}')]
                self.assertEqual({'id': 791}, control.API().call(self.PATH))
                self.assertEqual(2, command.call_count)
                wait.assert_called_once_with(1)

    def test_api_transient_get_exhausts_one_bounded_read_budget(self):
        with patch.object(control.subprocess, 'run', return_value=self.response(
                1, stderr=b'gh: private vendor text (HTTP 503)\n')) as command, \
                patch.object(control.time, 'sleep') as wait:
            with self.assertRaisesRegex(control.ControlError, 'http503.*attempts3.*locator-'):
                control.API().call(self.PATH)
            self.assertEqual(3, command.call_count)
            self.assertEqual([unittest.mock.call(1), unittest.mock.call(2)], wait.call_args_list)

    def test_api_auth_missing_rate_limit_and_unknown_errors_never_retry(self):
        for code in (401, 403, 404, 429, 500):
            with self.subTest(code=code), patch.object(control.subprocess, 'run', return_value=self.response(
                    1, stderr=f'gh: rejected (HTTP {code})\n'.encode())) as command, \
                    patch.object(control.time, 'sleep') as wait:
                with self.assertRaisesRegex(control.ControlError, f'http{code}.*attempts1'):
                    control.API().call(self.PATH)
                command.assert_called_once()
                wait.assert_not_called()

    def test_api_unknown_error_is_private_and_not_retried(self):
        with patch.object(control.subprocess, 'run', return_value=self.response(
                1, stdout=b'private response', stderr=b'gh: private-token and private-path')) as command, \
                patch.object(control.time, 'sleep') as wait:
            with self.assertRaises(control.ControlError) as caught:
                control.API().call(self.PATH)
            message = str(caught.exception)
            self.assertIn('httpunknown', message)
            self.assertIn('locator-', message)
            for private in ('private-token', 'private-path', 'private response', self.PATH, 'private=value'):
                self.assertNotIn(private, message)
            command.assert_called_once()
            wait.assert_not_called()

    def test_api_mutations_never_retry_even_a_known_transient_http_error(self):
        for method in ('POST', 'PATCH', 'PUT', 'DELETE'):
            with self.subTest(method=method), patch.object(control.subprocess, 'run', return_value=self.response(
                    1, stderr=b'gh: unavailable (HTTP 503)\n')) as command, \
                    patch.object(control.time, 'sleep') as wait:
                with self.assertRaisesRegex(control.ControlError, 'http503.*attempts1'):
                    control.API().call(self.PATH, method=method, data={'id': 791})
                command.assert_called_once()
                self.assertEqual(b'{"id":791}', command.call_args.kwargs['input'])
                wait.assert_not_called()

    def test_api_read_with_a_payload_has_no_retry_authority(self):
        with patch.object(control.subprocess, 'run', return_value=self.response(
                1, stderr=b'gh: unavailable (HTTP 503)\n')) as command, \
                patch.object(control.time, 'sleep') as wait:
            with self.assertRaises(control.ControlError):
                control.API().call(self.PATH, data={'unexpected': True})
            command.assert_called_once()
            wait.assert_not_called()

    def test_api_timeout_is_classified_without_replaying_an_unknown_outcome(self):
        for method in ('GET', 'POST'):
            with self.subTest(method=method), patch.object(control.subprocess, 'run', side_effect=
                    subprocess.TimeoutExpired(['gh', 'private-token'], 60, stderr=b'private response')) as command, \
                    patch.object(control.time, 'sleep') as wait:
                with self.assertRaisesRegex(control.ControlError, 'timeout.*attempts1') as caught:
                    control.API().call(self.PATH, method=method)
                self.assertNotIn('private-token', str(caught.exception))
                command.assert_called_once()
                wait.assert_not_called()

    def test_api_malformed_success_never_retries_or_exposes_the_body(self):
        with patch.object(control.subprocess, 'run', return_value=self.response(stdout=b'private malformed')) as command, \
                patch.object(control.time, 'sleep') as wait:
            with self.assertRaisesRegex(control.ControlError, 'native-api-malformed'):
                control.API().call(self.PATH)
            command.assert_called_once()
            wait.assert_not_called()

    def test_api_ambiguous_status_claims_do_not_grant_another_read(self):
        with patch.object(control.subprocess, 'run', return_value=self.response(
                1, stderr=b'gh: upstream says (HTTP 503), rejected (HTTP 403)\n')) as command, \
                patch.object(control.time, 'sleep') as wait:
            with self.assertRaisesRegex(control.ControlError, 'httpunknown'):
                control.API().call(self.PATH)
            command.assert_called_once()
            wait.assert_not_called()

    def test_api_auth_failure_after_a_transient_read_stops_immediately(self):
        with patch.object(control.subprocess, 'run') as command, patch.object(control.time, 'sleep') as wait:
            command.side_effect = [self.response(1, stderr=b'gh: unavailable (HTTP 503)\n'),
                                   self.response(1, stderr=b'gh: forbidden (HTTP 403)\n')]
            with self.assertRaisesRegex(control.ControlError, 'http403.*attempts2'):
                control.API().call(self.PATH)
            self.assertEqual(2, command.call_count)
            wait.assert_called_once_with(1)

    def test_api_success_and_empty_mutation_responses_keep_their_existing_contract(self):
        with patch.object(control.subprocess, 'run', return_value=self.response(stdout=b'{"id":791}')) as command:
            self.assertEqual({'id': 791}, control.API().call(self.PATH))
            command.assert_called_once()
        with patch.object(control.subprocess, 'run', return_value=self.response(stdout=b'')) as command:
            self.assertEqual({}, control.API().call(self.PATH, method='POST'))
            command.assert_called_once()


class ControlTests(unittest.TestCase):
    def test_new_source_retains_current_native_ingress_without_consumer_self_admission(self):
        current = '5b72a68a352bd926620b0487b867f80bba774a2f'
        value = {'version': 1, 'repository': REPO, 'mode': 'reference',
                 'quality': [{'workflow': '.github/workflows/repository-quality.yml',
                              'job': 'repository / quality'}],
                 'accepted_sources': [current]}
        # Use the actual centrally owned registry. A new selected source must
        # retain the genuine ingress accepted under the current source.
        accepted = control.policy_value(value, REPO, SOURCE)
        self.assertIn(current, accepted['accepted_sources'])
        self.assertIn(SOURCE, accepted['accepted_sources'])
        with self.assertRaisesRegex(control.ControlError, 'consumer-cannot-admit-central-source'):
            control.policy_value(value | {'accepted_sources': ['f' * 40]}, REPO, SOURCE)

    def test_old_selected_source_accepts_new_consumer_base_during_cutover(self):
        config = (Path(__file__).resolve().parents[1] / '.lit/workflow-control.json').read_bytes()
        api = Mock(); api.file.return_value = config
        # Both immutable old sources have no predecessor allowlist. Simulate
        # their policy reader against the newly integrated consumer base.
        old_lineage = json.dumps({'version': 1, 'accepted_predecessors': []})
        with patch.object(Path, 'read_text', return_value=old_lineage):
            for source in ('6c569721323d24cabad43f8caa162be60a7afdcb',
                           'f1bd4951288b1ce52a6cb30ab6432e201cf45507'):
                with self.subTest(source=source):
                    self.assertEqual([source], control.policy(api, REPO, BASE, source)['accepted_sources'])

    def test_selected_central_source_retains_predecessors_without_consumer_cutover(self):
        api = Mock()
        api.file.return_value = json.dumps({
            'version': 1, 'repository': REPO, 'mode': 'reference',
            'quality': [{'workflow': '.github/workflows/repository-quality.yml', 'job': 'repository / quality'}],
            'accepted_sources': []}).encode()
        lineage = json.dumps({'version': 1, 'accepted_predecessors': ['d' * 40]})
        with patch.object(Path, 'read_text', return_value=lineage):
            self.assertEqual(sorted([SOURCE, 'd' * 40]),
                             control.policy(api, REPO, BASE, SOURCE)['accepted_sources'])

    def test_consumer_policy_cannot_select_unadmitted_source(self):
        api = Mock()
        config = {"version": 1, "repository": REPO, "mode": "reference",
                  "quality": [{"workflow": ".github/workflows/repository-quality.yml", "job": "repository / quality"}],
                  "accepted_sources": [SOURCE]}
        import json
        api.file.return_value = json.dumps(config).encode()
        with patch.object(Path, 'read_text', return_value=json.dumps({'version': 1, 'accepted_predecessors': []})):
            self.assertEqual([SOURCE], control.policy(api, REPO, BASE, SOURCE)["accepted_sources"])
            api.file.return_value = json.dumps(config | {"accepted_sources": ['d' * 40]}).encode()
            with self.assertRaisesRegex(control.ControlError, "consumer-cannot-admit-central-source"):
                control.policy(api, REPO, BASE, SOURCE)

    def test_serialized_operation_keeps_identical_native_binding(self):
        original = pull()
        restored = json.loads(control.canonical(control.binding(original)))
        api = Mock(); api.call.return_value = original
        self.assertEqual(original, control.live_pull(api, REPO, 3, restored))

    def test_native_copilot_delivery_prevents_duplicate_automatic_request(self):
        api = Mock(); api.call.return_value = {'users': []}
        api.pages.return_value = [delivery(status='in_progress', conclusion=None)]
        self.assertTrue(control.copilot_delivery_pending(api, REPO, pull()))
        api.pages.return_value[0].update(status='completed', conclusion='failure')
        with self.assertRaisesRegex(control.ControlError, 'no-automatic-retry'):
            control.copilot_delivery_pending(api, REPO, pull())

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

    def test_direct_main_cannot_bypass_promotion(self):
        value = pull()
        value['base']['ref'] = 'main'
        with self.assertRaisesRegex(control.ControlError, 'main-requires-exact-protected-promotion'):
            control.classify(value, REPO)

    def test_native_human_approval_and_self_approval_are_both_enforced(self):
        api = Mock()
        env = {'name': 'normal-release-promotion-approval', 'can_admins_bypass': False,
               'protection_rules': [{'type': 'required_reviewers', 'prevent_self_review': False,
                                     'reviewers': [{'type': 'User', 'reviewer': {'id': 76040632}}]}]}
        api.call.return_value = env
        self.assertEqual(env, control.normal_environment(api, REPO))
        for change in ({'protection_rules': []}, {'can_admins_bypass': True},
                       {'protection_rules': [env['protection_rules'][0] | {'prevent_self_review': True}]}):
            api.call.return_value = env | change
            with self.subTest(change=change), self.assertRaises(control.ControlError):
                control.normal_environment(api, REPO)
        approval = {'state': 'approved', 'user': {'type': 'User', 'id': 76040632},
                    'environments': [{'name': 'normal-release-promotion-approval'}]}
        api.call.return_value = [approval]
        self.assertEqual(approval, control.native_approval(api, REPO, 10))
        for history in ([], [approval, approval], [approval | {'state': 'rejected'}],
                        [approval | {'user': {'type': 'Bot'}}]):
            api.call.return_value = history
            with self.subTest(history=history), self.assertRaises(control.ControlError):
                control.native_approval(api, REPO, 10)

    def test_metadata_refresh_reruns_original_classification_without_granting_funding_or_success(self):
        api = Mock()
        completed = run() | {'status': 'completed'}
        api.call.side_effect = [pull(), pull(), completed, completed, pull(), completed, {}]
        api.pages.side_effect = [[run()], [{'id': 100, 'run_id': 10, 'run_attempt': 1, 'name': 'Current revision review',
                                           'status': 'completed', 'conclusion': 'success'},
                                          {'id': 101, 'run_id': 10, 'run_attempt': 1, 'name': 'Protected current revision',
                                           'status': 'completed', 'conclusion': 'success'}]]
        events.refresh(api, REPO, 'pull_request_target', {'action': 'edited', 'pull_request': {'number': 3}})
        writes = [call for call in api.call.call_args_list if call.kwargs.get('method') == 'POST']
        self.assertEqual(1, len(writes))
        self.assertEqual(f'repos/{REPO}/actions/jobs/101/rerun', writes[0].args[0])
        with self.assertRaises(control.ControlError):
            events.refresh(Mock(), REPO, 'pull_request', {'pull_request': {'number': 3}})

    def test_review_signal_is_unprivileged_and_receiver_loads_frozen_helper(self):
        import yaml
        root = Path(__file__).resolve().parents[1]
        signal = yaml.safe_load((root / '.github/workflows/review-events.yml').read_text())
        receiver = yaml.safe_load((root / '.github/workflows/delivery-operations.yml').read_text())
        self.assertEqual({}, signal['permissions'])
        self.assertIn('edited', signal.get('on', signal.get(True))['pull_request_review']['types'])
        self.assertEqual({}, signal['jobs']['signal']['permissions'])
        self.assertTrue(all('uses' not in step for step in signal['jobs']['signal']['steps']))
        triggers = receiver.get('on', receiver.get(True))
        self.assertNotIn('pull_request_review', triggers)
        self.assertNotIn('pull_request_review_comment', triggers)
        self.assertNotIn('issue_comment', triggers)
        self.assertEqual(['Repository review events'], triggers['workflow_run']['workflows'])
        self.assertIn("github.repository != 'lightning-it/.github'", receiver['jobs']['prepare']['if'])
        self.assertIn("Repository policy audit", receiver['jobs']['prepare']['if'])
        quality = yaml.safe_load((root / '.github/workflows/repository-quality.yml').read_text())
        prepare = quality['jobs']['prepare']
        self.assertEqual('quality', prepare['needs'])
        for guard in ("github.event_name == 'push'", "github.ref == 'refs/heads/develop'", 'github.run_attempt == 1'):
            self.assertIn(guard, prepare['if'])
        self.assertEqual({'contents': 'read'}, prepare['permissions'])
        self.assertFalse(any(step.get('uses', '').startswith('actions/checkout@') for step in prepare['steps']))
        app = next(step for step in prepare['steps'] if step.get('id') == 'app')
        self.assertEqual("steps.signal.outputs.current == 'true'", app['if'])
        self.assertEqual('github-management-lit', app['with']['repositories'])
        checkout = next(step for step in receiver['jobs']['refresh']['steps'] if 'uses' in step)
        self.assertEqual('bfb1e53be7ab05102aa3ea53c5ed3c468d1a593b', checkout['with']['ref'])
        self.assertFalse(checkout['with']['persist-credentials'])
        self.assertNotIn('${{', str(checkout['with']['ref']))

    def test_failed_unprivileged_signal_still_invalidates_and_stale_signal_blocks(self):
        producer = {'id': 22, 'name': events.SIGNAL_NAME, 'path': events.SIGNAL_PATH,
                    'event': 'pull_request_review', 'status': 'completed', 'conclusion': 'failure',
                    'pull_requests': [{'number': 3, 'head': {'sha': HEAD}}]}
        api = Mock(); api.call.side_effect = [producer, pull()]
        self.assertEqual(3, events.event_pull(api, REPO, 'workflow_run', {'workflow_run': {'id': 22}})['number'])
        for change in ({'path': '.github/workflows/untrusted.yml'}, {'name': 'Other signal'},
                       {'event': 'pull_request'}, {'pull_requests': []}):
            api.call.side_effect = [producer | change]
            with self.subTest(change=change), self.assertRaises(control.ControlError):
                events.event_pull(api, REPO, 'workflow_run', {'workflow_run': {'id': 22}})
        newer = pull(); newer['head']['sha'] = 'd' * 40
        api.call.side_effect = [producer, newer]
        with self.assertRaisesRegex(control.ControlError, 'stale-review-signal'):
            events.event_pull(api, REPO, 'workflow_run', {'workflow_run': {'id': 22}})

    def test_base_change_has_its_own_request_tuple(self):
        api = Mock()
        previous = run(9)
        previous['pull_requests'][0]['base']['sha'] = 'd' * 40
        api.call.return_value = run()
        api.pages.return_value = [previous, run()]
        self.assertEqual(10, control.reserve_request(api, REPO, pull(), SOURCE, 10, 1))

    def test_old_generation_cannot_spend_a_later_ready_transition(self):
        api = Mock(); api.call.return_value = run(10)
        api.pages.return_value = [run(10), run(11)]
        with self.assertRaisesRegex(control.ControlError, 'funding-current-native-generation-required'):
            control.reserve_request(api, REPO, pull(), SOURCE, 10, 1)

    def test_renovate_is_narrow_and_other_renovate_still_requires_review(self):
        value = pull(control.RENOVATE)
        value['head']['ref'] = 'renovate/dependency'
        value['labels'] = [{'name': name} for name in ('renovate', 'dependencies', 'safe-automerge')]
        self.assertEqual('renovate', control.classify(value, REPO))
        value['labels'].append({'name': 'breaking-update'})
        self.assertEqual('copilot', control.classify(value, REPO))

    def test_native_request_reservation_rejects_spent_run_or_attempt(self):
        api = Mock()
        api.call.return_value = run()
        api.pages.return_value = [run()]
        self.assertEqual(10, control.reserve_request(api, REPO, pull(), SOURCE, 10, 1))
        api.call.return_value = run(11)
        api.pages.return_value = [run(), run(11)]
        with patch.object(control, 'request_slot_started', return_value=True), self.assertRaisesRegex(control.ControlError, 'already-consumed'):
            control.reserve_request(api, REPO, pull(), SOURCE, 11, 1)
        api.call.return_value = run() | {'run_attempt': 2}
        with patch.object(control, 'request_slot_started', return_value=True), self.assertRaisesRegex(control.ControlError, 'rerun-forbidden'):
            control.reserve_request(api, REPO, pull(), SOURCE, 10, 2)
        self.assertTrue(all(call.kwargs.get('method', 'GET') == 'GET' for call in api.call.call_args_list))

    def test_draft_to_ready_does_not_consume_a_never_started_request(self):
        api = Mock()
        api.call.return_value = run(11)
        api.pages.return_value = [run(9), run(11)]
        with patch.object(control, 'request_slot_started', return_value=False):
            self.assertEqual(11, control.reserve_request(api, REPO, pull(), SOURCE, 11, 1))
        api.call.return_value = run(11) | {'run_attempt': 2}
        api.pages.return_value = [run(11) | {'run_attempt': 2}]
        with patch.object(control, 'request_slot_started', return_value=False):
            self.assertEqual(11, control.reserve_request(api, REPO, pull(), SOURCE, 11, 2))
        api.pages.return_value = [{'name': 'Protected current revision', 'run_id': 11, 'steps': []}]
        with self.assertRaisesRegex(control.ControlError, 'boundary-history-unavailable'):
            control.request_slot_started(api, REPO, run(11))

    def test_observed_cloud_context_exists_but_does_not_authorize_a_candidate(self):
        fixture = json.loads((Path(__file__).parent / 'fixtures/native-job-pr871.json').read_bytes())
        self.assertEqual('6532da1b9eadc0ccd56af2fd2646c6138d8d5c1f', control.source_identity(fixture))
        candidate = run() | {'workflow_url': f'https://api.github.com/repos/{REPO}/actions/workflows/77'}
        self.assertFalse(control.native_required(candidate, REPO))

    def test_label_change_between_review_and_finalization_is_stale(self):
        original = pull(control.RENOVATE)
        original['head']['ref'] = 'renovate/dependency'
        original['labels'] = [{'name': name} for name in ('renovate', 'dependencies', 'safe-automerge')]
        changed = original | {'labels': original['labels'] + [{'name': 'breaking-update'}]}
        api = Mock(); api.call.side_effect = [run(), changed, changed]
        job = {'workflow_repository': REPO, 'workflow_file_path': control.WORKFLOW,
               'workflow_sha': SOURCE, 'check_run_id': 123}
        with tempfile.TemporaryDirectory() as temp:
            event = Path(temp) / 'event.json'; event.write_text(json.dumps({'pull_request': original}))
            env = {'GITHUB_REPOSITORY': REPO, 'GITHUB_RUN_ID': '10', 'NATIVE_JOB': json.dumps(job),
                   'GITHUB_EVENT_PATH': str(event), 'REVIEW_RESULT': 'success'}
            with patch.dict(os.environ, env), patch.object(sys, 'argv', ['control', 'finalize']), \
                 patch.object(control, 'API', return_value=api), \
                 patch.object(control, 'operation_record', return_value={'binding': control.binding(original)}), \
                 self.assertRaisesRegex(control.ControlError, 'stale-not-applicable'):
                control.main()

    def test_candidate_authored_run_and_check_name_are_not_reservations(self):
        api = Mock()
        api.call.return_value = run() | {'workflow_url': f'https://api.github.com/repos/{REPO}/actions/workflows/77'}
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

    def test_copilot_review_needs_current_head_and_admitted_native_frame(self):
        review = native_review()
        api = Mock(); api.pages.side_effect = [[review], [delivery()], []]
        self.assertEqual(9, control.copilot_review(api, REPO, pull())['id'])
        for body in ('', 'Unable to review this pull request', 'Quota exceeded', 'No files were reviewed',
                     "Copilot wasn’t able to review this pull request", "Copilot wasn't able to review any files",
                     'Copilot reviewed 1 out of 2 changed files', 'Reviewed all changes with no findings.'):
            api.pages.side_effect = [[review | {'body': body}], [delivery()]]
            with self.subTest(body=body), self.assertRaisesRegex(control.ControlError, 'copilot-native-frame'):
                control.copilot_review(api, REPO, pull())
        api.pages.side_effect = [[review | {'commit_id': 'd' * 40}]]
        self.assertIsNone(control.copilot_review(api, REPO, pull()))

    def test_dismissed_or_ambiguous_current_reviews_never_pass(self):
        review = native_review()
        for reviews in ([review | {'state': 'DISMISSED'}], [review, review | {'id': 10}]):
            api = Mock(); api.pages.side_effect = [reviews, [delivery()]]
            with self.subTest(reviews=reviews), self.assertRaises(control.ControlError):
                control.copilot_review(api, REPO, pull())

    def test_native_publication_after_service_completion_still_requires_unique_successful_producer(self):
        review = native_review(submitted_at='2026-10-15T00:00:14Z')
        api = Mock(); api.pages.side_effect = [[review], [delivery()], []]
        self.assertEqual(20, control.copilot_review(api, REPO, pull())['service_run'])
        for runs in ([delivery(conclusion='failure')], [delivery(status='in_progress', conclusion=None)],
                     [delivery(), delivery(id=21)], [delivery(run_started_at='2026-10-15T00:00:15Z')]):
            api = Mock(); api.pages.side_effect = [[review], runs]
            with self.subTest(runs=runs):
                self.assertIsNone(control.copilot_review(api, REPO, pull()))

    def test_native_ingress_requires_exact_source_association_and_completed_gate(self):
        api = Mock(); source_run = run() | {'status': 'completed', 'conclusion': 'success'}
        api.pages.side_effect = [[source_run], [{'id': 100, 'run_id': 10, 'name': 'Current revision review', 'conclusion': 'success'}], [source_run], [source_run]]
        api.call.return_value = source_run
        with patch.object(control, 'artifact_record', return_value={'version': 1, 'source_sha': SOURCE, 'binding': control.binding(pull()), 'route': 'copilot'}):
            self.assertEqual(10, control.check_native_control(api, REPO, pull(), {'accepted_sources': [SOURCE]})['run'])
        for changed in (source_run | {'workflow_url': f'https://api.github.com/repos/{REPO}/actions/workflows/77'}, source_run | {'conclusion': 'failure'},
                        source_run | {'pull_requests': [{'number': 3, 'base': {'sha': 'f' * 40}, 'head': {'sha': HEAD}}]}):
            api.pages.side_effect = [[changed]]
            with self.subTest(changed=changed), self.assertRaises(control.ControlError):
                control.check_native_control(api, REPO, pull(), {'accepted_sources': [SOURCE]})

    def test_missing_distribution_proof_never_uses_actor_as_bypass(self):
        with self.assertRaisesRegex(control.ControlError, 'distribution-receipt-missing'):
            control.distribution_evidence(Mock(), REPO, pull(control.SYNC), {})

    def test_quality_selects_exact_pr_base_head_and_newest_attempt(self):
        value = pull()
        def check(i):
            return {'id': i, 'name': 'repository / quality', 'app': {'id': 15368},
                    'status': 'completed', 'conclusion': 'success',
                    'details_url': f'https://github.com/{REPO}/actions/runs/{i}/job/{i}'}
        native = run(10) | {'path': '.github/workflows/repository-quality.yml', 'event': 'pull_request'}
        api = Mock()
        api.pages.side_effect = [[check(9), check(10)], [{'id': 10, 'run_id': 10,
                                'check_run_url': 'https://api.github.com/check-runs/10', 'conclusion': 'success'}]]
        api.call.side_effect = [native | {'id': 9, 'event': 'push'}, native]
        config = {'quality': [{'job': 'repository / quality', 'workflow': '.github/workflows/repository-quality.yml'}]}
        self.assertEqual(10, control.check_quality(api, REPO, value, config)[0]['run'])
        for change, error in (({'status': 'in_progress'}, 'quality-pending'),
                              ({'conclusion': 'failure'}, 'quality-not-successful')):
            api.pages.side_effect = [[check(9), check(10) | change]]
            api.call.side_effect = [native | {'id': 9}, native]
            with self.subTest(change=change), self.assertRaisesRegex(control.ControlError, error):
                control.check_quality(api, REPO, value, config)
        old = native | {'pull_requests': [{'number': 3, 'base': {'sha': 'f' * 40}, 'head': {'sha': HEAD}}]}
        api.pages.side_effect = [[check(10)]]; api.call.side_effect = [old]
        with self.assertRaisesRegex(control.ControlError, 'quality-check-missing'):
            control.check_quality(api, REPO, value, config)

    def test_renovate_exemption_rejects_human_pushed_commit(self):
        value = pull(control.RENOVATE)
        label = {'id': 1, 'event': 'labeled', 'label': {'name': 'safe-automerge'}, 'actor': value['user']}
        commit = {'sha': HEAD, 'author': value['user'], 'committer': {'login': 'web-flow', 'id': 19864447, 'type': 'User'},
                  'commit': {'verification': {'verified': True}}}
        api = Mock(); api.pages.side_effect = [[label], [commit]]
        self.assertEqual('policy-bound-renovate', control.check_renovate(api, REPO, value)['kind'])
        for change in ({'author': pull()['user']}, {'sha': 'd' * 40}, {'commit': {'verification': {'verified': False}}}):
            api.pages.side_effect = [[label], [commit | change]]
            with self.subTest(change=change), self.assertRaises(control.ControlError):
                control.check_renovate(api, REPO, value)

    def test_inflight_invalidation_is_retained_then_reruns_original_job(self):
        producer = {'id': 22, 'name': events.SIGNAL_NAME, 'path': events.SIGNAL_PATH,
                    'event': 'pull_request_review', 'status': 'completed', 'conclusion': 'success',
                    'pull_requests': [{'number': 3, 'head': {'sha': HEAD}}]}
        active, completed = run() | {'status': 'in_progress'}, run() | {'status': 'completed'}
        api = Mock(); api.call.side_effect = [producer, pull(), pull(), active, pull(), completed,
                                             completed, pull(), completed, {}]
        review = {'id': 101, 'run_id': 10, 'run_attempt': 1, 'name': 'Protected current revision', 'status': 'completed', 'conclusion': 'success'}
        gate = {'id': 100, 'run_id': 10, 'run_attempt': 1, 'name': 'Current revision review', 'status': 'in_progress', 'conclusion': None}
        api.pages.side_effect = [[run()], [review, gate | {'status': 'completed', 'conclusion': 'success'}]]
        with patch.object(events.time, 'sleep') as wait:
            events.refresh(api, REPO, 'workflow_run', {'workflow_run': {'id': 22}})
        wait.assert_called_once_with(15)
        self.assertEqual(f'repos/{REPO}/actions/jobs/100/rerun', api.call.call_args.args[0])

    def test_metadata_waits_for_common_quality_before_final_job_exists(self):
        api = Mock()
        review = {'id': 101, 'run_id': 10, 'run_attempt': 1, 'name': 'Protected current revision',
                  'status': 'completed', 'conclusion': 'failure'}
        quality = {'id': 102, 'run_id': 10, 'run_attempt': 1, 'name': 'Source common quality',
                   'status': 'in_progress', 'conclusion': None}
        final = {'id': 100, 'run_id': 10, 'run_attempt': 1, 'name': 'Current revision review',
                 'status': 'completed', 'conclusion': 'failure'}
        active, completed = run() | {'status': 'in_progress'}, run() | {'status': 'completed'}
        api.call.side_effect = [pull(), pull(), active, pull(), completed, completed, pull(), completed, {}]
        api.pages.side_effect = [[run()], [review, quality | {'status': 'completed', 'conclusion': 'success'}, final]]
        def waiting(seconds):
            self.assertEqual(15, seconds)
            self.assertFalse(any(c.kwargs.get('method') == 'POST' for c in api.call.call_args_list))
        with patch.object(events.time, 'sleep', side_effect=waiting) as wait:
            events.refresh(api, REPO, 'pull_request_target', {'action': 'edited', 'pull_request': {'number': 3}})
        wait.assert_called_once()
        writes = [c for c in api.call.call_args_list if c.kwargs.get('method') == 'POST']
        self.assertEqual(1, len(writes))
        self.assertEqual(f'repos/{REPO}/actions/jobs/101/rerun', writes[0].args[0])

    def test_metadata_stops_immediately_if_head_changes_while_waiting(self):
        api = Mock()
        changed = pull(); changed['head']['sha'] = 'd' * 40
        active = run() | {'status': 'in_progress'}
        api.call.side_effect = [pull(), pull(), active, changed]
        api.pages.side_effect = [[run()]]
        with patch.object(events.time, 'sleep') as wait, self.assertRaisesRegex(control.ControlError, 'stale-refresh'):
            events.refresh(api, REPO, 'pull_request_target', {'action': 'edited', 'pull_request': {'number': 3}})
        wait.assert_called_once_with(15)
        self.assertFalse(any(c.kwargs.get('method') == 'POST' for c in api.call.call_args_list))

    def test_metadata_rejects_a_changed_native_run_before_rerun(self):
        for changed in (run() | {'id': 11}, run() | {'head_sha': 'd' * 40},
                        run() | {'workflow_id': 88}, run() | {'workflow_url': 'candidate-workflow'}):
            api = Mock(); api.call.side_effect = [pull(), pull(), changed]
            api.pages.return_value = [run()]
            with self.subTest(changed=changed), self.assertRaisesRegex(control.ControlError, 'refresh-native-run-drift'):
                events.refresh(api, REPO, 'pull_request_target', {'action': 'edited', 'pull_request': {'number': 3}})
            self.assertFalse(any(c.kwargs.get('method') == 'POST' for c in api.call.call_args_list))

    def test_metadata_wait_timeout_never_retries_or_writes(self):
        api = Mock()
        api.call.side_effect = lambda path: pull() if '/pulls/' in path else run() | {'status': 'in_progress'}
        api.pages.side_effect = lambda path, key: [run()] if 'head_sha=' in path else []
        with patch.object(events.time, 'sleep') as wait, self.assertRaisesRegex(control.ControlError, 'refresh-inflight-timeout'):
            events.refresh(api, REPO, 'pull_request_target', {'action': 'edited', 'pull_request': {'number': 3}})
        self.assertEqual(120, wait.call_count)
        self.assertEqual([f'repos/{REPO}/actions/runs?head_sha={HEAD}'],
                         [c.args[0] for c in api.pages.call_args_list])
        self.assertEqual(120, sum(c.args[0] == f'repos/{REPO}/actions/runs/10' for c in api.call.call_args_list))
        self.assertFalse(any(c.kwargs.get('method') == 'POST' for c in api.call.call_args_list))

    def test_metadata_running_attempt_reads_no_job_list_or_second_run_before_waiting(self):
        completed = run() | {'status': 'completed', 'conclusion': 'success'}
        for status in ('queued', 'in_progress', 'waiting'):
            active = completed | {'status': status, 'conclusion': None}
            api = refresh_api([active, completed, completed, completed], [refresh_jobs()])
            def waiting(seconds):
                self.assertEqual(15, seconds)
                self.assertEqual(1, api.pages.call_count)  # Initial run selection only.
                self.assertEqual(1, sum(c.args[0] == f'repos/{REPO}/actions/runs/10' for c in api.call.call_args_list))
                self.assertFalse(any(c.kwargs.get('method') == 'POST' for c in api.call.call_args_list))
            with self.subTest(status=status), patch.object(events.time, 'sleep', side_effect=waiting) as wait:
                events.refresh(api, REPO, 'pull_request_target', {'action': 'edited', 'pull_request': {'number': 3}})
            wait.assert_called_once_with(15)
            self.assertEqual(2, api.pages.call_count)
            self.assertEqual(4, sum(c.args[0] == f'repos/{REPO}/actions/runs/10' for c in api.call.call_args_list))

    def test_metadata_attempt_advance_after_job_read_reobserves_without_stale_write(self):
        first = run() | {'status': 'completed', 'conclusion': 'success'}
        second = first | {'run_attempt': 2}
        api = refresh_api([first, second | {'status': 'queued', 'conclusion': None}, second, second, second],
                          [refresh_jobs(1), refresh_jobs(2)])
        with patch.object(events.time, 'sleep') as wait:
            events.refresh(api, REPO, 'pull_request_target', {'action': 'edited', 'pull_request': {'number': 3}})
        wait.assert_called_once_with(15)
        self.assertEqual([f'repos/{REPO}/actions/jobs/201/rerun'],
                         [c.args[0] for c in api.call.call_args_list if c.kwargs.get('method') == 'POST'])
        self.assertEqual([f'repos/{REPO}/actions/runs/10/attempts/{attempt}/jobs' for attempt in (1, 2)],
                         [c.args[0] for c in api.pages.call_args_list[1:]])

    def test_metadata_attempt_advance_at_last_fence_never_writes_the_old_job(self):
        first = run() | {'status': 'completed', 'conclusion': 'success'}
        second = first | {'run_attempt': 2}
        api = refresh_api([first, first, second | {'status': 'in_progress'}, second, second, second],
                          [refresh_jobs(1), refresh_jobs(2)])
        with patch.object(events.time, 'sleep') as wait:
            events.refresh(api, REPO, 'pull_request_target', {'action': 'edited', 'pull_request': {'number': 3}})
        wait.assert_called_once_with(15)
        self.assertEqual([f'repos/{REPO}/actions/jobs/201/rerun'],
                         [c.args[0] for c in api.call.call_args_list if c.kwargs.get('method') == 'POST'])

    def test_metadata_empty_and_partial_completed_attempt_views_are_read_only_until_complete(self):
        completed = run() | {'status': 'completed', 'conclusion': 'success'}
        active_quality = {'id': 103, 'run_id': 10, 'run_attempt': 1, 'name': 'Source common quality',
                          'status': 'in_progress', 'conclusion': None}
        api = refresh_api([completed] * 9, [[], refresh_jobs()[:1], refresh_jobs() + [active_quality], refresh_jobs()])
        def waiting(seconds):
            self.assertEqual(15, seconds)
            self.assertFalse(any(c.kwargs.get('method') == 'POST' for c in api.call.call_args_list))
        with patch.object(events.time, 'sleep', side_effect=waiting) as wait:
            events.refresh(api, REPO, 'pull_request_target', {'action': 'edited', 'pull_request': {'number': 3}})
        self.assertEqual(3, wait.call_count)
        self.assertEqual(1, sum(c.kwargs.get('method') == 'POST' for c in api.call.call_args_list))

    def test_metadata_permanent_empty_completed_view_exhausts_only_existing_read_bound(self):
        completed = run() | {'status': 'completed', 'conclusion': 'success'}
        api = refresh_api([completed] * 240, [[]] * 120)
        with patch.object(events.time, 'sleep') as wait, self.assertRaisesRegex(control.ControlError, 'refresh-inflight-timeout'):
            events.refresh(api, REPO, 'pull_request_target', {'action': 'edited', 'pull_request': {'number': 3}})
        self.assertEqual(120, wait.call_count)
        self.assertFalse(any(c.kwargs.get('method') == 'POST' for c in api.call.call_args_list))

    def test_metadata_true_duplicate_named_jobs_remain_closed(self):
        completed = run() | {'status': 'completed', 'conclusion': 'success'}
        for duplicate in refresh_jobs():
            api = refresh_api([completed, completed], [refresh_jobs() + [duplicate]])
            with self.subTest(name=duplicate['name']), patch.object(events.time, 'sleep') as wait, \
                    self.assertRaisesRegex(control.ControlError, 'ambiguous'):
                events.refresh(api, REPO, 'pull_request_target', {'action': 'edited', 'pull_request': {'number': 3}})
            wait.assert_not_called()
            self.assertFalse(any(c.kwargs.get('method') == 'POST' for c in api.call.call_args_list))

    def test_metadata_requires_actual_positive_attempt_and_native_job_origin(self):
        completed = run() | {'status': 'completed', 'conclusion': 'success'}
        for attempt in (None, True, 0, -1, '1'):
            api = refresh_api([completed | {'run_attempt': attempt}], [])
            with self.subTest(attempt=attempt), self.assertRaisesRegex(control.ControlError, 'attempt-required'):
                events.refresh(api, REPO, 'pull_request_target', {'action': 'edited', 'pull_request': {'number': 3}})
            self.assertEqual(1, api.pages.call_count)
            self.assertFalse(any(c.kwargs.get('method') == 'POST' for c in api.call.call_args_list))
        for change in ({'run_id': 11}, {'run_attempt': None}, {'run_attempt': True}, {'run_attempt': 0}):
            jobs = refresh_jobs(); jobs[0] |= change
            api = refresh_api([completed], [jobs])
            with self.subTest(change=change), self.assertRaisesRegex(control.ControlError, 'job-origin'):
                events.refresh(api, REPO, 'pull_request_target', {'action': 'edited', 'pull_request': {'number': 3}})
            self.assertFalse(any(c.kwargs.get('method') == 'POST' for c in api.call.call_args_list))

    def test_metadata_other_job_attempt_is_reobserved_without_new_authority(self):
        first = run() | {'status': 'completed', 'conclusion': 'success'}
        second = first | {'run_attempt': 2}
        for mismatched in (refresh_jobs(2), refresh_jobs(1) + refresh_jobs(2)):
            api = refresh_api([first, first, second, second, second], [mismatched, refresh_jobs(2)])
            with self.subTest(view=mismatched), patch.object(events.time, 'sleep') as wait:
                events.refresh(api, REPO, 'pull_request_target', {'action': 'edited', 'pull_request': {'number': 3}})
            wait.assert_called_once_with(15)
            self.assertEqual([f'repos/{REPO}/actions/jobs/201/rerun'],
                             [c.args[0] for c in api.call.call_args_list if c.kwargs.get('method') == 'POST'])

    def test_metadata_same_attempt_status_or_conclusion_drift_is_read_only(self):
        completed = run() | {'status': 'completed', 'conclusion': 'success'}
        for changed in (completed | {'status': 'in_progress'}, completed | {'conclusion': 'failure'}):
            for reads in ([completed, changed, completed, completed, completed],
                          [completed, completed, changed, completed, completed, completed]):
                api = refresh_api(reads, [refresh_jobs(), refresh_jobs()])
                with self.subTest(changed=changed, fence=len(reads)), patch.object(events.time, 'sleep') as wait:
                    events.refresh(api, REPO, 'pull_request_target', {'action': 'edited', 'pull_request': {'number': 3}})
                wait.assert_called_once_with(15)
                self.assertEqual(1, sum(c.kwargs.get('method') == 'POST' for c in api.call.call_args_list))

    def test_metadata_revalidates_native_identity_after_jobs_and_at_last_fence(self):
        completed = run() | {'status': 'completed', 'conclusion': 'success'}
        changed = completed | {'workflow_id': 88}
        for observations in ([completed, changed], [completed, completed, changed]):
            api = refresh_api(observations, [refresh_jobs()])
            with self.subTest(reads=len(observations)), self.assertRaisesRegex(control.ControlError, 'run-drift'):
                events.refresh(api, REPO, 'pull_request_target', {'action': 'edited', 'pull_request': {'number': 3}})
            self.assertFalse(any(c.kwargs.get('method') == 'POST' for c in api.call.call_args_list))

    def test_metadata_unknown_post_outcome_never_retries_mutation(self):
        completed = run() | {'status': 'completed', 'conclusion': 'success'}
        api = refresh_api([completed] * 3, [refresh_jobs()], post_error=control.ControlError('native-api-unavailable'))
        with patch.object(events.time, 'sleep') as wait, self.assertRaisesRegex(control.ControlError, 'native-api-unavailable'):
            events.refresh(api, REPO, 'pull_request_target', {'action': 'edited', 'pull_request': {'number': 3}})
        wait.assert_not_called()
        self.assertEqual(1, sum(c.kwargs.get('method') == 'POST' for c in api.call.call_args_list))

    def test_two_successive_refreshes_after_verifier_only_attempt_authenticate_carried_review(self):
        api, state = verifier_only_refresh_api()
        with patch.object(events.time, 'sleep') as wait:
            for attempt in (2, 3):
                state['attempt'] = attempt
                events.refresh(api, REPO, 'workflow_run', {'workflow_run': {'id': 22}})
        wait.assert_not_called()
        self.assertEqual([f'repos/{REPO}/actions/jobs/{attempt * 100 + 2}/rerun' for attempt in (2, 3)],
                         [c.args[0] for c in api.call.call_args_list if c.kwargs.get('method') == 'POST'])

    def test_metadata_after_verifier_only_attempt_reclassifies_only_authenticated_original_review_job(self):
        api, _ = verifier_only_refresh_api()
        with patch.object(events.time, 'sleep') as wait:
            events.refresh(api, REPO, 'pull_request_target', {'action': 'edited', 'pull_request': {'number': 3}})
        wait.assert_not_called()
        self.assertEqual([f'repos/{REPO}/actions/jobs/101/rerun'],
                         [c.args[0] for c in api.call.call_args_list if c.kwargs.get('method') == 'POST'])
        self.assertIn(f'repos/{REPO}/actions/runs/10/attempts/1', [c.args[0] for c in api.call.call_args_list])

    def test_latest_association_attempt_tag_never_substitutes_for_actual_job_origin(self):
        api, state = verifier_only_refresh_api()
        state['latest'] = [state['review'] | {'run_attempt': 2}, refresh_jobs(2)[1] | {'head_sha': HEAD}]
        with patch.object(events.time, 'sleep') as wait:
            events.refresh(api, REPO, 'workflow_run', {'workflow_run': {'id': 22}})
        wait.assert_not_called()
        self.assertIn(f'repos/{REPO}/actions/runs/10/attempts/1', [c.args[0] for c in api.call.call_args_list])
        self.assertEqual([f'repos/{REPO}/actions/jobs/202/rerun'],
                         [c.args[0] for c in api.call.call_args_list if c.kwargs.get('method') == 'POST'])

    def test_partial_current_attempt_waits_for_complete_view_before_single_refresh(self):
        for event, payload, target in (
                ('workflow_run', {'workflow_run': {'id': 22}}, 202),
                ('pull_request_target', {'action': 'edited', 'pull_request': {'number': 3}}, 101)):
            api, state = verifier_only_refresh_api()
            state['review'] |= {'run_attempt': 2}
            state['latest'] = [state['review'], refresh_jobs(2)[1] | {'head_sha': HEAD}]
            original_pages = api.pages.side_effect
            def pages(path, key):
                if path == f'repos/{REPO}/actions/runs/10/attempts/2/jobs' and state.get('complete'):
                    return state['latest']
                return original_pages(path, key)
            api.pages.side_effect = pages
            def waiting(seconds):
                self.assertEqual(15, seconds)
                self.assertFalse(any(c.kwargs.get('method') == 'POST' for c in api.call.call_args_list))
                state['complete'] = True
            with self.subTest(event=event), patch.object(events.time, 'sleep', side_effect=waiting) as wait:
                events.refresh(api, REPO, event, payload)
            wait.assert_called_once_with(15)
            self.assertIn(f'repos/{REPO}/actions/jobs/101', [c.args[0] for c in api.call.call_args_list])
            self.assertNotIn(f'repos/{REPO}/actions/runs/10/attempts/1', [c.args[0] for c in api.call.call_args_list])
            self.assertEqual([f'repos/{REPO}/actions/jobs/{target}/rerun'],
                             [c.args[0] for c in api.call.call_args_list if c.kwargs.get('method') == 'POST'])

    def test_current_or_newer_exact_review_attempt_exhausts_read_bound_without_carried_authority(self):
        for attempt in (2, 3):
            api, state = verifier_only_refresh_api()
            state['review'] |= {'run_attempt': attempt}
            # The association's attempt tag is not the exact job's origin.
            state['latest'] = [state['review'] | {'run_attempt': 2}, refresh_jobs(2)[1] | {'head_sha': HEAD}]
            with self.subTest(attempt=attempt), patch.object(events.time, 'sleep') as wait, \
                    self.assertRaisesRegex(control.ControlError, 'refresh-inflight-timeout'):
                events.refresh(api, REPO, 'workflow_run', {'workflow_run': {'id': 22}})
            self.assertEqual([unittest.mock.call(15)] * 120, wait.call_args_list)
            reads = [c.args[0] for c in api.call.call_args_list]
            self.assertEqual(120, reads.count(f'repos/{REPO}/actions/jobs/101'))
            self.assertFalse(any('/attempts/' in path for path in reads))
            self.assertFalse(any(c.kwargs.get('method') == 'POST' for c in api.call.call_args_list))

    def test_carried_review_origin_and_current_association_cannot_be_forged(self):
        for defect in ('job-id', 'job-run', 'job-head', 'job-attempt-bool', 'job-attempt-zero',
                       'job-attempt-negative', 'job-failed', 'job-running',
                       'origin-run', 'origin-head', 'origin-attempt-bool', 'origin-workflow', 'origin-namespace',
                       'origin-pr', 'origin-pr-head', 'origin-membership', 'origin-job-attempt-bool',
                       'duplicate-origin', 'duplicate-current-review', 'duplicate-current-final', 'latest-head'):
            api, state = verifier_only_refresh_api()
            if defect == 'job-id': state['review'] |= {'id': 999}
            elif defect == 'job-run': state['review'] |= {'run_id': 11}
            elif defect == 'job-head': state['review'] |= {'head_sha': BASE}
            elif defect == 'job-attempt-bool': state['review'] |= {'run_attempt': True}
            elif defect == 'job-attempt-zero': state['review'] |= {'run_attempt': 0}
            elif defect == 'job-attempt-negative': state['review'] |= {'run_attempt': -1}
            elif defect == 'job-failed': state['review'] |= {'conclusion': 'failure'}
            elif defect == 'job-running': state['review'] |= {'status': 'in_progress'}
            elif defect == 'origin-run': state['origin'] |= {'id': 11}
            elif defect == 'origin-head': state['origin'] |= {'head_sha': BASE}
            elif defect == 'origin-attempt-bool': state['origin'] |= {'run_attempt': True}
            elif defect == 'origin-workflow': state['origin'] |= {'workflow_id': 88}
            elif defect == 'origin-namespace': state['origin'] |= {'workflow_url': 'ordinary-candidate-workflow'}
            elif defect == 'origin-pr': state['origin'] |= {'pull_requests': []}
            elif defect == 'origin-pr-head': state['origin'] |= {'pull_requests': [{'number': 3, 'head': {'sha': BASE}}]}
            elif defect == 'origin-membership': state['origin_jobs'] = [state['review'] | {'id': 999}]
            elif defect == 'origin-job-attempt-bool': state['origin_jobs'] = [state['review'] | {'run_attempt': True}]
            elif defect == 'duplicate-origin': state['origin_jobs'] = [state['review'], state['review']]
            else:
                final = refresh_jobs(2)[1] | {'head_sha': HEAD}
                state['latest'] = [state['review'], final]
                if defect == 'duplicate-current-review': state['latest'].append(state['review'])
                elif defect == 'duplicate-current-final': state['latest'].append(final)
                elif defect == 'latest-head': state['latest'][0] = state['review'] | {'head_sha': BASE}
            with self.subTest(defect=defect), patch.object(events.time, 'sleep') as wait, \
                    self.assertRaises(control.ControlError):
                events.refresh(api, REPO, 'pull_request_target', {'action': 'edited', 'pull_request': {'number': 3}})
            wait.assert_not_called()
            self.assertFalse(any(c.kwargs.get('method') == 'POST' for c in api.call.call_args_list))

    def test_carried_review_missing_current_or_origin_views_never_use_arbitrary_old_success(self):
        for view in ('latest', 'origin_jobs'):
            api, state = verifier_only_refresh_api()
            state[view] = []
            with self.subTest(view=view), patch.object(events.time, 'sleep') as wait, \
                    self.assertRaisesRegex(control.ControlError, 'refresh-inflight-timeout'):
                events.refresh(api, REPO, 'pull_request_target', {'action': 'edited', 'pull_request': {'number': 3}})
            self.assertEqual(120, wait.call_count)
            self.assertFalse(any(c.kwargs.get('method') == 'POST' for c in api.call.call_args_list))
            if view == 'latest':
                self.assertNotIn(f'repos/{REPO}/actions/jobs/101', [c.args[0] for c in api.call.call_args_list])

    def test_partial_carried_views_wait_for_actual_native_association_and_membership(self):
        for view in ('latest', 'origin_jobs'):
            api, state = verifier_only_refresh_api()
            original = state.get(view)
            state[view] = []
            def waiting(seconds):
                self.assertEqual(15, seconds)
                self.assertFalse(any(c.kwargs.get('method') == 'POST' for c in api.call.call_args_list))
                if view == 'latest': del state[view]
                else: state[view] = original
            with self.subTest(view=view), patch.object(events.time, 'sleep', side_effect=waiting) as wait:
                events.refresh(api, REPO, 'workflow_run', {'workflow_run': {'id': 22}})
            wait.assert_called_once_with(15)
            self.assertEqual(1, sum(c.kwargs.get('method') == 'POST' for c in api.call.call_args_list))

    def test_carried_review_generation_advance_during_origin_reads_or_last_fence_cannot_write_stale_job(self):
        for fence in ('origin', 'last'):
            api, state = verifier_only_refresh_api()
            original, observations = api.call.side_effect, [0]
            def call(path, **kwargs):
                if path == f'repos/{REPO}/actions/runs/10':
                    observations[0] += 1
                    if fence == 'last' and observations[0] == 3: state['attempt'] = 3
                value = original(path, **kwargs)
                if fence == 'origin' and path == f'repos/{REPO}/actions/jobs/101': state['attempt'] = 3
                return value
            api.call.side_effect = call
            with self.subTest(fence=fence), patch.object(events.time, 'sleep') as wait:
                events.refresh(api, REPO, 'workflow_run', {'workflow_run': {'id': 22}})
            wait.assert_called_once_with(15)
            self.assertEqual([f'repos/{REPO}/actions/jobs/302/rerun'],
                             [c.args[0] for c in api.call.call_args_list if c.kwargs.get('method') == 'POST'])

    def test_carried_review_native_error_and_unknown_post_outcome_never_retry_or_fund(self):
        for failure in ('origin-get', 'post'):
            api, _ = verifier_only_refresh_api()
            original = api.call.side_effect
            def call(path, **kwargs):
                if ((failure == 'origin-get' and path == f'repos/{REPO}/actions/jobs/101')
                        or (failure == 'post' and kwargs.get('method') == 'POST')):
                    raise control.ControlError('native-api-unavailable')
                return original(path, **kwargs)
            api.call.side_effect = call
            with self.subTest(failure=failure), patch.object(events.time, 'sleep') as wait, \
                    self.assertRaisesRegex(control.ControlError, 'native-api-unavailable'):
                events.refresh(api, REPO, 'workflow_run', {'workflow_run': {'id': 22}})
            wait.assert_not_called()
            self.assertEqual(0 if failure == 'origin-get' else 1,
                             sum(c.kwargs.get('method') == 'POST' for c in api.call.call_args_list))

    def test_unadmitted_metadata_caller_grants_no_acceptance(self):
        api = Mock()
        api.call.side_effect = [pull(), []]
        api.pages.return_value = []
        events.refresh(api, REPO, 'pull_request_target', {'action': 'edited', 'pull_request': {'number': 3}})
        self.assertEqual([f'repos/{REPO}/pulls/3', f'repos/{REPO}/rules/branches/develop'],
                         [call.args[0] for call in api.call.call_args_list])
        self.assertTrue(all('method' not in call.kwargs for call in api.call.call_args_list))

    def test_enforced_scope_cannot_silently_skip_a_missing_native_run(self):
        rule = {'type': 'workflows', 'parameters': {'workflows': [{
            'repository_id': 1112629689, 'path': control.WORKFLOW, 'sha': SOURCE}]}}
        for rules in ([rule], {'not': 'native rules'}):
            api = Mock(); api.call.side_effect = [pull(), rules]; api.pages.return_value = []
            with self.subTest(rules=rules), self.assertRaises(control.ControlError):
                events.refresh(api, REPO, 'pull_request_target', {'action': 'edited', 'pull_request': {'number': 3}})
            self.assertTrue(all('method' not in call.kwargs for call in api.call.call_args_list))

    def test_generic_comments_cannot_refresh_or_fund_a_protected_review(self):
        api = Mock()
        with self.assertRaisesRegex(control.ControlError, 'unsupported-refresh-event'):
            events.refresh(api, REPO, 'issue_comment', {'issue': {'number': 3, 'pull_request': {'url': 'native'}}})
        api.call.assert_not_called()
        api.pages.assert_not_called()

    def test_incomplete_native_workflow_rules_block_before_any_refresh_effect(self):
        entry = {'repository_id': 1112629689, 'path': control.WORKFLOW, 'sha': SOURCE}
        malformed = [
            {'type': 'workflows'}, {'type': 'workflows', 'parameters': {}},
            {'type': 'workflows', 'parameters': None},
            *[{'type': 'workflows', 'parameters': {'workflows': value}}
              for value in (None, {}, [], [None], [{}],
                            [entry | {'repository_id': True}], [entry | {'repository_id': 0}],
                            [entry | {'path': None}], [entry | {'path': 'other.yml'}],
                            [entry | {'sha': 'unknown'}], [entry | {'ref': None}])],
        ]
        for rule in malformed:
            api = Mock(); api.call.side_effect = [pull(), [rule]]; api.pages.return_value = []
            with self.subTest(rule=rule), self.assertRaises(control.ControlError):
                events.refresh(api, REPO, 'pull_request_target', {'action': 'edited', 'pull_request': {'number': 3}})
            self.assertTrue(all('method' not in call.kwargs for call in api.call.call_args_list))
        self.assertFalse(events.common_control_enforced([{'type': 'workflows', 'parameters': {
            'workflows': [entry | {'repository_id': 42}]}}]))
        self.assertTrue(events.common_control_enforced([{'type': 'workflows', 'parameters': {'workflows': [entry]}}]))

    def test_late_copilot_delivery_reruns_review_with_no_new_request(self):
        completed = run() | {'status': 'completed'}
        api = Mock(); api.call.side_effect = [pull(), pull(), completed, completed, pull(), completed, {}]
        api.pages.side_effect = [[run()], [
            {'id': 101, 'run_id': 10, 'run_attempt': 1, 'name': 'Protected current revision', 'status': 'completed', 'conclusion': 'failure'},
            {'id': 100, 'run_id': 10, 'run_attempt': 1, 'name': 'Current revision review', 'status': 'completed', 'conclusion': 'failure'}]]
        events.refresh(api, REPO, 'pull_request_target', {'action': 'edited', 'pull_request': {'number': 3}})
        self.assertEqual(f'repos/{REPO}/actions/jobs/101/rerun', api.call.call_args.args[0])
        # A delivered review makes classify request_needed false; a failed or
        # unknown paid reservation remains terminal through reserve_request().
        api.pages.side_effect = [[native_review()], [delivery()], []]
        self.assertIsNotNone(control.copilot_review(api, REPO, pull()))

    def test_previous_approval_reuses_operation_before_verifier_only_attempt(self):
        previous = run(9) | {'run_attempt': 2}
        api = Mock(); api.pages.side_effect = [[previous], [{'name': 'control-operation-1', 'expired': False}]]
        approval = {'state': 'approved', 'user': {'type': 'User'},
                    'environments': [{'name': 'normal-release-promotion-approval'}]}
        api.call.return_value = [approval]
        with patch.dict(os.environ, {'GITHUB_RUN_ID': '10'}), \
             patch.object(control, 'operation_record', return_value={'source_sha': SOURCE, 'binding': control.binding(pull())}) as record:
            self.assertEqual(9, control.previous_approval(api, REPO, pull(), SOURCE))
            record.assert_called_once_with(api, REPO, previous)

    def test_codex_requires_current_native_producer_without_copilot_fallback(self):
        import workflow_codex
        import workflow_subject
        job = {'workflow_repository': REPO, 'workflow_file_path': control.WORKFLOW,
               'workflow_sha': SOURCE, 'check_run_id': 123}
        with patch.dict(os.environ, {'NATIVE_JOB': json.dumps(job), 'GITHUB_RUN_ID': '10'}), \
             patch.object(workflow_subject, 'materialize', return_value={}), \
             patch.object(workflow_codex, 'current_evidence', side_effect=control.ControlError('codex-current-native-producer-required')), \
             patch.object(control, 'copilot_review') as copilot, \
             self.assertRaisesRegex(control.ControlError, 'codex-current-native-producer-required'):
            control.verify_existing_route(Mock(), REPO, pull(control.RELEASE), {}, 'codex')
        copilot.assert_not_called()

    def test_merged_ingress_uses_native_operation_when_live_association_disappears(self):
        value = pull() | {'merged': True, 'merge_commit_sha': 'e' * 40}
        native = run() | {'status': 'completed', 'conclusion': 'success', 'pull_requests': []}
        api = Mock(); api.pages.side_effect = [[native], [{'id': 100, 'run_id': 10,
                                'name': 'Current revision review', 'conclusion': 'success'}], [native], [native]]
        api.call.side_effect = [value, native]
        record = {'version': 1, 'source_sha': SOURCE, 'binding': control.binding(value), 'route': 'copilot'}
        with patch.object(control, 'operation_record', return_value=record), patch.object(control, 'artifact_record', return_value=record):
            self.assertEqual(10, control.check_native_control(api, REPO, value, {'accepted_sources': [SOURCE]})['run'])
            api.pages.side_effect = [[native]]
            with self.assertRaisesRegex(control.ControlError, 'ingress-protected-run-missing'):
                control.check_native_control(api, REPO, pull(), {'accepted_sources': [SOURCE]})
            api.pages.side_effect = [[native]]
            with patch.object(control, 'operation_record', return_value=record | {'binding': control.binding(value) | {'number': 44}}), \
                 self.assertRaisesRegex(control.ControlError, 'ingress-protected-run-missing'):
                control.check_native_control(api, REPO, value, {'accepted_sources': [SOURCE]})

    def test_current_run_previous_attempt_reuses_same_native_approval(self):
        native = run(10) | {'run_attempt': 2}
        api = Mock(); api.pages.side_effect = [[native], [{'name': 'control-operation-1', 'expired': False}]]
        approval = {'state': 'approved', 'user': {'type': 'User'},
                    'environments': [{'name': 'normal-release-promotion-approval'}]}
        api.call.return_value = [approval]
        with patch.dict(os.environ, {'GITHUB_RUN_ID': '10'}), \
             patch.object(control, 'operation_record', return_value={'source_sha': SOURCE, 'binding': control.binding(pull())}):
            self.assertEqual(10, control.previous_approval(api, REPO, pull(), SOURCE))

    def test_signal_cannot_be_removed_or_changed_by_candidate(self):
        path = Path(__file__).resolve().parents[1] / '.github/workflows/review-events.yml'
        api = Mock(); api.file.return_value = path.read_bytes()
        control.validate_signal(api, REPO, pull())
        for payload in (b'', path.read_bytes().replace(b'dismissed', b'opened'), path.read_bytes() + b'\njobs: {}'):
            api.file.return_value = payload
            with self.subTest(payload=payload[-20:]), self.assertRaisesRegex(control.ControlError, 'candidate-review-signal'):
                control.validate_signal(api, REPO, pull())

    def test_distribution_requires_full_native_changed_file_count(self):
        value = pull(control.SYNC)
        value['body'] = '<!-- lit-distribution/v1 ' + json.dumps({'source': 'lightning-it/shared-assets-lit',
                      'source_sha': SOURCE, 'run': 20, 'files': []}) + ' -->'
        value['changed_files'] = 3001
        api = Mock(); api.call.return_value = {'id': 20, 'head_sha': SOURCE, 'head_branch': 'main',
                    'status': 'completed', 'conclusion': 'success', 'path': '.github/workflows/sync-repository-quality-repos.yml'}
        api.pages.return_value = [{'filename': f'file-{i}', 'status': 'modified'} for i in range(3000)]
        with self.assertRaisesRegex(control.ControlError, 'distribution-native-file-list-incomplete'):
            control.distribution_evidence(api, REPO, value, {'distribution_sources': [SOURCE]})

    def test_native_conversation_guard_keeps_zero_human_approvals(self):
        guard = {'type': 'pull_request', 'ruleset_source_type': 'Repository', 'ruleset_source': REPO,
                 'ruleset_id': 42, 'parameters': {'required_review_thread_resolution': True,
                 'required_approving_review_count': 0, 'require_code_owner_review': False,
                 'require_last_push_approval': False}}
        api = Mock(); api.call.return_value = [guard]
        self.assertEqual([42], control.native_conversation_guard(api, REPO, pull()))
        for changes in ({'required_review_thread_resolution': False}, {'required_approving_review_count': 1},
                        {'require_code_owner_review': True}, {'require_last_push_approval': True}):
            api.call.return_value = [guard | {'parameters': guard['parameters'] | changes}]
            with self.subTest(changes=changes), self.assertRaises(control.ControlError):
                control.native_conversation_guard(api, REPO, pull())
        api.call.return_value = []
        with self.assertRaises(control.ControlError):
            control.native_conversation_guard(api, REPO, pull())

    def test_copilot_delivery_for_other_pr_cannot_consume_this_pr_request(self):
        other = delivery(pull_requests=[{'number': 44, 'base': {'sha': BASE}, 'head': {'sha': HEAD}}], conclusion='failure')
        api = Mock(); api.call.return_value = {'users': []}; api.pages.return_value = [other]
        self.assertFalse(control.copilot_delivery_pending(api, REPO, pull()))
        api.pages.return_value = [delivery(pull_requests=[])]
        with self.assertRaisesRegex(control.ControlError, 'pr-association-unavailable'):
            control.copilot_delivery_pending(api, REPO, pull())

    def test_old_base_review_cannot_cover_new_base_at_same_head(self):
        api = Mock(); api.pages.side_effect = [[native_review()], [delivery(pull_requests=[{
            'number': 3, 'base': {'sha': 'e' * 40}, 'head': {'sha': HEAD}}])]]
        self.assertIsNone(control.copilot_review(api, REPO, pull()))

    def test_older_source_approval_is_skipped_not_raised(self):
        previous = run(9)
        api = Mock(); api.pages.side_effect = [[previous], [{'name': 'control-operation-1', 'expired': False}]]
        with patch.object(control, 'operation_record', return_value={'source_sha': 'd' * 40, 'binding': control.binding(pull())}):
            self.assertIsNone(control.previous_approval(api, REPO, pull(), SOURCE))
        api.call.assert_not_called()

    def test_real_policy_receives_exact_pull_before_any_review_or_funding(self):
        value = pull()
        job = {'workflow_repository': REPO, 'workflow_file_path': control.WORKFLOW,
               'workflow_sha': SOURCE, 'check_run_id': 123}
        api = Mock(); api.call.side_effect = [run(), value]
        with tempfile.TemporaryDirectory() as temp:
            event = Path(temp) / 'event.json'; event.write_text(json.dumps({'pull_request': value}))
            env = {'GITHUB_REPOSITORY': REPO, 'GITHUB_RUN_ID': '10', 'NATIVE_JOB': json.dumps(job),
                   'GITHUB_EVENT_PATH': str(event)}
            with patch.dict(os.environ, env), patch.object(sys, 'argv', ['control', 'classify']), \
                 patch.object(control, 'API', return_value=api), \
                 patch.object(control, 'policy', side_effect=control.ControlError('exact-bootstrap-denied')) as policy, \
                 patch.object(control, 'copilot_review') as review, \
                 patch.object(control, 'reserve_request') as funding, \
                 self.assertRaisesRegex(control.ControlError, 'exact-bootstrap-denied'):
                control.main()
            policy.assert_called_once_with(api, REPO, BASE, SOURCE, pull=value)
            review.assert_not_called()
            funding.assert_not_called()
        self.assertTrue(all(call.kwargs.get('method', 'GET') == 'GET' for call in api.call.call_args_list))

    def test_unicode_operation_is_rejected_before_any_funded_effect(self):
        value = pull(body='界' * 50000)
        job = {'workflow_repository': REPO, 'workflow_file_path': control.WORKFLOW,
               'workflow_sha': SOURCE, 'check_run_id': 123}
        api = Mock(); api.call.side_effect = [run(), value]
        with tempfile.TemporaryDirectory() as temp:
            event = Path(temp) / 'event.json'; event.write_text(json.dumps({'pull_request': value}))
            env = {'GITHUB_REPOSITORY': REPO, 'GITHUB_RUN_ID': '10', 'NATIVE_JOB': json.dumps(job),
                   'GITHUB_EVENT_PATH': str(event)}
            with patch.dict(os.environ, env), patch.object(sys, 'argv', ['control', 'classify']), \
                 patch.object(control, 'API', return_value=api), patch.object(control, 'policy', return_value={}), \
                 patch.object(control, 'copilot_review') as review, \
                 self.assertRaisesRegex(control.ControlError, 'snapshot-size-before-funding'):
                control.main()
            review.assert_not_called()
        self.assertTrue(all(call.kwargs.get('method', 'GET') == 'GET' for call in api.call.call_args_list))

    def test_explicit_partial_native_frame_cannot_claim_complete_review(self):
        for report in ('Copilot reviewed 1 out of 2 changed files.',
                       'Copilot reviewed 1 out of\n2 changed files.',
                       'Copilot\nreviewed\t1 out of 2 changed\nfiles.'):
            body = NATIVE_BODY.replace('The complete proposed source has no actionable findings.', report)
            api = Mock(); api.pages.side_effect = [[native_review(body=body)], [delivery()]]
            with self.subTest(report=report), self.assertRaisesRegex(control.ControlError, 'copilot-native-frame'):
                control.copilot_review(api, REPO, pull(changed_files=2))

    def test_native_frame_without_synthetic_file_counter_remains_admitted(self):
        api = Mock(); api.pages.side_effect = [[native_review()], [delivery()], []]
        self.assertEqual(20, control.copilot_review(api, REPO, pull(changed_files=30))['service_run'])

    def test_native_issue_zero_frame_keeps_full_report_and_explicit_coverage(self):
        import hashlib
        body = NATIVE_BODY.replace('**0 open findings**', '**No open issues** 🎉').replace(
            '🧠 **Review effort:** Balanced', '<sub>Review effort: Balanced</sub>')
        api = Mock(); api.pages.side_effect = [[native_review(body=body)], [delivery()], []]
        proof = control.copilot_review(api, REPO, pull(changed_files=30))
        self.assertEqual(hashlib.sha256(body.encode()).hexdigest(), proof['frame']['review_body_sha256'])
        self.assertEqual(0, proof['frame']['historical_findings_count'])
        partial = body.replace('The complete proposed source has no actionable findings.',
                               'Copilot reviewed 1 out of 2 changed files.')
        api = Mock(); api.pages.side_effect = [[native_review(body=partial)], [delivery()]]
        with self.assertRaisesRegex(control.ControlError, 'copilot-native-frame'):
            control.copilot_review(api, REPO, pull(changed_files=2))

    def test_native_nonzero_findings_keep_prose_coverage_separate_from_container(self):
        findings = ('<details open>\n<summary><strong>1 open finding</strong></summary>\n\n'
                    '- [Correct the parser](https://github.com/lightning-it/.github/pull/3#discussion_r123) · New\n'
                    '</details>')
        comment = {'id': 123, 'pull_request_review_id': 9, 'original_commit_id': HEAD,
                   'user': native_review()['user'], 'body': 'Correct the parser.'}
        for assessment in ('The parser needs a correction.', 'Copilot reviewed 2 out of 2 changed files.'):
            body = NATIVE_BODY.replace('🟢 Approval recommended', '🟡 Changes recommended').replace(
                'The complete proposed source has no actionable findings.', assessment).replace(
                '**0 open findings**', findings)
            api = Mock(); api.pages.side_effect = [[native_review(body=body)], [delivery()], [comment], [comment]]
            with self.subTest(assessment=assessment):
                proof = control.copilot_review(api, REPO, pull(changed_files=2))
                self.assertEqual([123], proof['finding_comment_ids'])
                self.assertEqual(1, proof['frame']['historical_findings_count'])
            partial = body.replace(assessment, 'Copilot reviewed 1 out of 2 changed files.')
            api = Mock(); api.pages.side_effect = [[native_review(body=partial)], [delivery()]]
            with self.assertRaisesRegex(control.ControlError, 'copilot-native-frame'):
                control.copilot_review(api, REPO, pull(changed_files=2))

    def test_native_issue_findings_bind_actual_threads_and_full_file_coverage(self):
        findings = ('<details open>\n<summary><strong>1 open issue</strong></summary>\n\n'
                    '- [Correct the parser](https://github.com/lightning-it/.github/pull/3#discussion_r123) · New\n'
                    '</details>')
        comment = {'id': 123, 'pull_request_review_id': 9, 'original_commit_id': HEAD,
                   'user': native_review()['user'], 'body': 'Correct the parser.'}
        for assessment in ('The parser needs a correction.', 'Copilot reviewed 2 out of 2 changed files.'):
            body = NATIVE_BODY.replace('🟢 Approval recommended', '🟡 Changes recommended').replace(
                'The complete proposed source has no actionable findings.', assessment).replace(
                '**0 open findings**', findings).replace(
                '🧠 **Review effort:** Balanced', '<sub>Review effort: Balanced</sub>')
            api = Mock(); api.pages.side_effect = [[native_review(body=body)], [delivery()], [comment], [comment]]
            with self.subTest(assessment=assessment):
                proof = control.copilot_review(api, REPO, pull(changed_files=2))
                self.assertEqual([123], proof['finding_comment_ids'])
                self.assertEqual(1, proof['frame']['historical_findings_count'])
            partial = body.replace(assessment, 'Copilot reviewed 1 out of 2 changed files.')
            api = Mock(); api.pages.side_effect = [[native_review(body=partial)], [delivery()]]
            with self.assertRaisesRegex(control.ControlError, 'copilot-native-frame'):
                control.copilot_review(api, REPO, pull(changed_files=2))

    def test_aggregate_proof_larger_than_operation_limit_is_still_readable(self):
        from types import SimpleNamespace
        payload = {'version': 1, 'ingress': [{'body': 'x' * 300000}]}
        api = Mock(); api.pages.return_value = [{'name': 'control-proof-1', 'expired': False}]
        def download(command, **_kwargs):
            destination = Path(command[command.index('--dir') + 1])
            (destination / 'control-proof.json').write_bytes(control.canonical(payload))
            return SimpleNamespace(returncode=0)
        with patch.object(control.subprocess, 'run', side_effect=download):
            self.assertEqual(payload, control.artifact_record(api, REPO, run(), 'control-proof-1', 'control-proof.json'))


if __name__ == '__main__':
    unittest.main()


# Synthetic generated-unit authority: never consumer configuration or real private data.
GENERATED_REPO = 'lightning-it/container-ee-wunder-devtools-ubi9'
GENERATED_PATH = 'container-toolchain/pnpm-lock.yaml'
GENERATED_SECTION = ('<details>\n<summary><strong>1 file not reviewed</strong></summary>\n'
                     '<ul>\n<li><strong><code>' + GENERATED_PATH + '</code></strong>: Generated file</li>\n'
                     '</ul>\n</details>')
GENERATED_BODY = (NATIVE_BODY.replace('**0 open findings**', '**No open issues** 🎉')
                  .replace('🧠 **Review effort:** Balanced',
                           GENERATED_SECTION + '\n<sub>Review effort: Balanced</sub>'))
CURRENT_TARGET_PATHS = (
    'Dockerfile', 'collections/offline-requirements.lock.yml',
    'container-toolchain/package.json', GENERATED_PATH,
    'container-toolchain/pnpm-workspace.yaml', 'renovate.json',
    'requirements.lock', 'requirements.txt', 'scripts/devtools-container-ci.sh',
    'scripts/download_go_modules.py', 'scripts/verify_devtools_collection_python.py',
    'tests/test_container_toolchain_contract.py', 'tests/test_devtools_collection_inventory.py',
    'tests/test_devtools_collection_python.py', 'tests/test_go_download_retry.py',
)


def generated_fixture():
    import hashlib
    paths = ['Dockerfile', 'renovate.json', 'container-toolchain/package.json',
             'container-toolchain/pnpm-workspace.yaml', GENERATED_PATH]
    contents = {path: ('synthetic ' + path).encode() for path in paths}
    unit = [{'path': path, 'mode': '100644', 'git_blob': hashlib.sha1(
                b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest(),
             'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
            for path, data in contents.items()]
    descriptor = {'version': 1, 'id': 'synthetic-generated-unit', 'repository': GENERATED_REPO,
                  'excluded_file': {'path': GENERATED_PATH, 'native_reason': 'Generated file',
                                    'coverage': 'not-reviewed-by-copilot'},
                  'canonical_unit': unit, 'admitted_target_tree': 'd' * 40,
                  'producer_provenance': {'source_main': 'e' * 40, 'release': 'v0.0.1',
                    'release_id': 1, 'publisher': {'run': 2, 'attempt': 1, 'job': 3,
                    'conclusion': 'success', 'cleanup': 'success',
                    'token_revoked_at': '2026-01-01T00:00:00Z'},
                    'canonical_manifest_sha256': control.digest(unit)}}
    value = pull(changed_files=5)
    value['base']['repo']['full_name'] = GENERATED_REPO
    value['head']['repo']['full_name'] = GENERATED_REPO
    review = native_review(body=GENERATED_BODY, body_html=GENERATED_SECTION)
    api = Mock()
    api.pages.side_effect = [[review], [delivery()], [],
        [{'filename': path, 'status': 'modified'} for path in paths]]
    api.file.side_effect = lambda repo, path, head: contents[path]
    commit = {'sha': HEAD, 'tree': {'sha': descriptor['admitted_target_tree']}}
    tree = {'sha': descriptor['admitted_target_tree'], 'truncated': False,
            'tree': [{'path': x['path'], 'mode': x['mode'], 'sha': x['git_blob'],
                      'size': x['bytes'], 'type': 'blob'} for x in unit]}
    api.call.side_effect = lambda path: commit if '/git/commits/' in path else tree
    return api, value, descriptor, commit, tree, contents


class GeneratedLockTests(unittest.TestCase):
    def test_explicit_protected_admission_recognizes_native_exclusion(self):
        api, value, descriptor, *_ = generated_fixture()
        with patch.object(control, 'GENERATED_LOCK_ADMISSIONS', (descriptor,), create=True):
            result = control.copilot_review(api, GENERATED_REPO, value)
        self.assertEqual([{'path': GENERATED_PATH, 'reason': 'Generated file',
                           'reviewed_by_copilot': False}], result['generated_artifact_coverage']['unreviewed'])
        self.assertNotIn('quality', result['generated_artifact_coverage'])

    def test_complete_current_target_inventory_keeps_the_single_exclusion(self):
        api, value, descriptor, *_ = generated_fixture()
        files = [{'filename': path, 'status': 'modified'} for path in CURRENT_TARGET_PATHS]
        value['changed_files'] = len(files)
        api.pages.side_effect = [[native_review(body=GENERATED_BODY, body_html=GENERATED_SECTION)],
                                  [delivery()], [], files]
        with patch.object(control, 'GENERATED_LOCK_ADMISSIONS', (descriptor,)):
            result = control.copilot_review(api, GENERATED_REPO, value)
        coverage = result['generated_artifact_coverage']
        self.assertEqual(descriptor['admitted_target_tree'], coverage['target_tree'])
        self.assertEqual([{'path': GENERATED_PATH, 'reason': 'Generated file',
                           'reviewed_by_copilot': False}], coverage['unreviewed'])

    def test_other_generated_target_locks_remain_blocked_before_content_reads(self):
        for path in ('collections/offline-requirements.lock.yml', 'requirements.lock'):
            api, value, descriptor, *_ = generated_fixture()
            value['changed_files'] = len(CURRENT_TARGET_PATHS)
            api.pages.side_effect = [[native_review(
                body=GENERATED_BODY.replace(GENERATED_PATH, path),
                body_html=GENERATED_SECTION.replace(GENERATED_PATH, path))], [delivery()]]
            with self.subTest(path=path), patch.object(control, 'GENERATED_LOCK_ADMISSIONS', (descriptor,)), \
                    self.assertRaisesRegex(control.ControlError, 'copilot-native-frame-not-accepted'):
                control.copilot_review(api, GENERATED_REPO, value)
            api.file.assert_not_called()

    def test_previous_target_tree_cannot_reuse_the_current_registered_admission(self):
        for previous in ('4d854bf005cde8d21c3837680653a10b97bd59ec',
                         'dca77eb5067263307ba830a2c4e53d36046e0760'):
            api, value, _, commit, *_ = generated_fixture()
            commit['tree']['sha'] = previous
            with self.subTest(previous=previous), \
                    self.assertRaisesRegex(control.ControlError, 'generated-native-tree'):
                control.copilot_review(api, GENERATED_REPO, value)
            api.file.assert_not_called()

    def test_candidate_inputs_cannot_register_an_admission(self):
        api, value, descriptor, *_ = generated_fixture()
        value['body'] = json.dumps(descriptor)
        value['labels'] = [{'name': 'allow-generated-lock'}]
        with patch.object(control, 'GENERATED_LOCK_ADMISSIONS', ()), \
                self.assertRaisesRegex(control.ControlError, 'copilot-native-frame-not-accepted'):
            control.copilot_review(api, GENERATED_REPO, value)
        api.file.assert_not_called()
        self.assertIsNone(control.generated_lock_descriptor(REPO))

    def test_registered_source_descriptor_cannot_be_replaced_by_candidate_metadata(self):
        self.assertEqual(1, len(control.GENERATED_LOCK_ADMISSIONS))
        registered = control.generated_lock_descriptor(GENERATED_REPO)
        self.assertEqual('c36a9ead2cb6bdbe887e95fde4d6b60773754f52', registered['admitted_target_tree'])
        self.assertEqual('3b917d5281766050731a61bb5d5005da61e25f81',
                         registered['producer_provenance']['source_main'])
        api, value, candidate, *_ = generated_fixture()
        value['body'] = json.dumps(candidate)
        value['labels'] = [{'name': 'allow-generated-lock'}]
        with self.assertRaisesRegex(control.ControlError, 'generated-native-tree'):
            control.copilot_review(api, GENERATED_REPO, value)
        api.file.assert_not_called()

    def test_changed_tree_commit_identity_and_partial_tree_fail_closed(self):
        for change in ('commit-as-tree', 'wrong-tree', 'wrong-commit', 'truncated', 'wrong-tree-object'):
            api, value, descriptor, commit, tree, _ = generated_fixture()
            if change == 'commit-as-tree':
                descriptor['admitted_target_tree'] = HEAD
                commit['tree']['sha'] = HEAD
            elif change == 'wrong-tree': commit['tree']['sha'] = 'f' * 40
            elif change == 'wrong-commit': commit['sha'] = 'f' * 40
            elif change == 'truncated': tree['truncated'] = True
            else: tree['sha'] = HEAD
            with self.subTest(change=change), patch.object(control, 'GENERATED_LOCK_ADMISSIONS', (descriptor,)), \
                    self.assertRaisesRegex(control.ControlError, 'generated-native-'):
                control.copilot_review(api, GENERATED_REPO, value)

    def test_exact_complete_unit_modes_blobs_sizes_and_contents_required(self):
        for change in ('symlink', 'mode', 'blob', 'size', 'missing', 'duplicate', 'bytes'):
            api, value, descriptor, _, tree, contents = generated_fixture()
            entry = tree['tree'][-1]
            if change == 'symlink': entry['mode'] = '120000'
            elif change == 'mode': entry['mode'] = '100755'
            elif change == 'blob': entry['sha'] = 'f' * 40
            elif change == 'size': entry['size'] += 1
            elif change == 'missing': tree['tree'].pop()
            elif change == 'duplicate': tree['tree'].append(entry.copy())
            else: contents[GENERATED_PATH] = b'x' * len(contents[GENERATED_PATH])
            with self.subTest(change=change), patch.object(control, 'GENERATED_LOCK_ADMISSIONS', (descriptor,)), \
                    self.assertRaisesRegex(control.ControlError, 'generated-native-unit'):
                control.copilot_review(api, GENERATED_REPO, value)

    def test_changed_file_inventory_and_rename_cannot_supply_exclusion(self):
        for change in ('missing-list', 'duplicate', 'renamed', 'unchanged'):
            api, value, descriptor, *_ = generated_fixture()
            files = [{'filename': x['path'], 'status': 'modified'} for x in descriptor['canonical_unit']]
            if change == 'missing-list': files.pop()
            elif change == 'duplicate': files[-1] = files[0].copy()
            elif change == 'renamed': files[-1]['previous_filename'] = 'other.lock'
            else: files[-1]['status'] = 'unchanged'
            api.pages.side_effect = [[native_review(body=GENERATED_BODY, body_html=GENERATED_SECTION)],
                                      [delivery()], [], files]
            with self.subTest(change=change), patch.object(control, 'GENERATED_LOCK_ADMISSIONS', (descriptor,)), \
                    self.assertRaisesRegex(control.ControlError, 'generated-native-files'):
                control.copilot_review(api, GENERATED_REPO, value)

    def test_protected_descriptor_is_exact_and_cannot_admit_other_repositories(self):
        for change in ('duplicate', 'path', 'unit', 'provenance', 'digest', 'other-repo'):
            _, _, descriptor, *_ = generated_fixture()
            entries = (descriptor,)
            repo = GENERATED_REPO
            if change == 'duplicate': entries = (descriptor, descriptor)
            elif change == 'path': descriptor['excluded_file']['path'] = 'other.lock'
            elif change == 'unit': descriptor['canonical_unit'].pop()
            elif change == 'provenance': descriptor['producer_provenance']['publisher']['cleanup'] = 'failure'
            elif change == 'digest': descriptor['producer_provenance']['canonical_manifest_sha256'] = '0' * 64
            else: repo = REPO; descriptor['repository'] = REPO
            with self.subTest(change=change), patch.object(control, 'GENERATED_LOCK_ADMISSIONS', entries), \
                    self.assertRaises(control.ControlError):
                control.generated_lock_descriptor(repo)

    def test_final_generated_proof_requires_all_current_quality_including_trivy(self):
        api, value, descriptor, *_ = generated_fixture()
        with patch.object(control, 'GENERATED_LOCK_ADMISSIONS', (descriptor,)):
            result = control.copilot_review(api, GENERATED_REPO, value)
        config = {'quality': [{'workflow': wf, 'job': job} for wf, job in sorted(control.GENERATED_QUALITY)]}
        quality = [{'check': i+1, 'run': i+10, 'attempt': 1, 'base': BASE, 'head': HEAD}
                   for i in range(len(config['quality']))]
        for invalid_config, invalid_quality in (
                ({'quality': config['quality'][:-1]}, quality[:-1]), (config, quality[:-1]),
                (config, [item | {'head': 'f' * 40} for item in quality]),
                (config, [item | {'base': 'f' * 40} for item in quality])):
            with self.assertRaisesRegex(control.ControlError, 'generated-current-quality-required'):
                control.complete_generated_lock_quality(result, invalid_config, invalid_quality, value)
        control.complete_generated_lock_quality(result, config, quality, value)
        self.assertEqual(quality, result['generated_artifact_coverage']['quality'])
        legacy = {'id': 9, 'head': HEAD}
        control.complete_generated_lock_quality(legacy, {}, [], value)
        self.assertEqual({'id': 9, 'head': HEAD}, legacy)

    def test_failed_or_pending_trivy_cannot_produce_quality_for_final_admission(self):
        value = pull(changed_files=5)
        for status, conclusion in (('in_progress', None), ('completed', 'failure')):
            native = run() | {'path': '.github/workflows/container-trivy.yml', 'event': 'pull_request'}
            check = {'name': 'Trivy', 'app': {'id': 15368}, 'id': 7, 'status': status,
                     'conclusion': conclusion,
                     'details_url': f'https://github.com/{REPO}/actions/runs/10/job/11'}
            api = Mock(); api.pages.return_value = [check]; api.call.return_value = native
            with self.subTest(status=status), self.assertRaisesRegex(control.ControlError, 'quality-'):
                control.check_quality(api, REPO, value, {'quality': [
                    {'workflow': '.github/workflows/container-trivy.yml', 'job': 'Trivy'}]})

    def test_legacy_and_additive_proofs_reuse_unchanged_native_ingress_consumer(self):
        for extra in ({}, {'generated_artifact_coverage': {'descriptor_sha256': 'd' * 64,
                           'unreviewed': [{'path': GENERATED_PATH, 'reviewed_by_copilot': False}]}}):
            record = {'version': 1, 'source_sha': SOURCE, 'binding': control.binding(pull()),
                      'route': 'copilot', 'evidence': {'id': 9} | extra}
            source_run = run() | {'status': 'completed', 'conclusion': 'success'}
            api = Mock(); api.call.return_value = source_run
            api.pages.side_effect = [[source_run], [{'id': 100, 'run_id': 10,
                'name': 'Current revision review', 'conclusion': 'success'}], [source_run], [source_run]]
            with self.subTest(additive=bool(extra)), patch.object(control, 'artifact_record', return_value=record):
                result = control.check_native_control(api, REPO, pull(), {'accepted_sources': [SOURCE]})
            self.assertEqual('copilot', result['route'])
            self.assertEqual(control.digest(record), result['proof_sha256'])


# Only synthetic native APIs register a Source admission in these tests. The
# registered owner-accepted entry is separate from candidate-supplied metadata.
def source_qualification_fixture(unit=None, *, actual_metadata=False):
    value = {
        'version': 1, 'proof_plan_sha256': control.SOURCE_GENERATED_PLAN,
        'subject': control.SOURCE_GENERATED_SUBJECT.copy(),
        'unit_manifest_sha256': control.digest(unit or control.SOURCE_GENERATED_UNIT),
        'toolchain': control.SOURCE_GENERATED_TOOLCHAIN.copy(),
        'baseline_lock_sha256': '62ae5fc96a9740cb1f68eb1108e84a393a1652b58db16a3e7919d3ba14401848',
        'registry_integrities': control.SOURCE_GENERATED_REGISTRY_INTEGRITIES.copy(),
        'checks': {key: True for key in control.SOURCE_GENERATED_CHECKS},
        'exit_code': 0, 'generation_invocations': 1, 'container_invocations': 1,
        'output_lock_sha256': next(item['sha256'] for item in (unit or control.SOURCE_GENERATED_UNIT)
                                  if item['path'] == control.SOURCE_GENERATED_SUBJECT['path']),
        'raw_receipt_sha256': 'a' * 64, 'raw_log_sha256': 'b' * 64,
    }
    if actual_metadata:
        # Actual one-proof5953 metadata, not an activation/owner-acceptance claim.
        value['raw_receipt_sha256'] = '7d0f3f45b39ba8f1dcd77428309780e9c08acc831819ecc65e474e671ca18172'
        value['raw_log_sha256'] = '21c6ed822100c78609c3895525e63bb50dbeefa9059c52e8baaac9768ff24a9b'
    return value


def source_generated_fixture():
    import hashlib
    subject = control.SOURCE_GENERATED_SUBJECT
    repo, head, base = subject['repository'], subject['head'], subject['base']
    contents = {item['path']: ('synthetic Source unit ' + item['path']).encode()
                for item in control.SOURCE_GENERATED_UNIT}
    unit = [{'path': path, 'mode': '100644', 'git_blob': hashlib.sha1(
                b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest(),
             'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
            for path, data in contents.items()]
    qualification = source_qualification_fixture(unit)
    body = GENERATED_BODY.replace(GENERATED_PATH, subject['path'])
    rendered = GENERATED_SECTION.replace(GENERATED_PATH, subject['path'])
    native = native_review(id=control.SOURCE_GENERATED_REVIEW['id'], commit_id=head,
                           body=body, body_html=rendered)
    review_binding = control.SOURCE_GENERATED_REVIEW | {'body_sha256': hashlib.sha256(body.encode()).hexdigest()}
    value = pull(number=subject['pr'], changed_files=len(control.SOURCE_GENERATED_CHANGED_PATHS))
    value['base'] = {'sha': base, 'ref': 'develop', 'repo': {'full_name': repo, 'id': 1120841013}}
    value['head'] = {'sha': head, 'ref': 'fix/devtools-security-truststores',
                     'repo': {'full_name': repo, 'id': 1120841013}}
    producer = delivery(id=control.SOURCE_GENERATED_REVIEW['service_run'], head_sha=head,
        pull_requests=[{'number': subject['pr'], 'base': {'sha': base}, 'head': {'sha': head}}])
    entry = {'version': 1, 'id': 'source-2658-generated-lock', 'subject': subject.copy(),
             'unit': unit, 'review': review_binding, 'qualification': qualification,
             'owner_acceptance': {'scope': 'source-2658-generated-lock-only',
               'receipt_sha256': control.digest(qualification),
               'decision_reference': 'chat:00000000-0000-0000-0000-000000000001/00000000-0000-0000-0000-000000000002'}}
    files = [{'filename': path, 'status': 'modified'} for path in control.SOURCE_GENERATED_CHANGED_PATHS]
    tree = {'sha': subject['tree'], 'truncated': False,
            'tree': [{'path': x['path'], 'mode': x['mode'], 'sha': x['git_blob'],
                      'size': x['bytes'], 'type': 'blob'} for x in unit]}
    api = Mock()
    def pages(path, key=None):
        if path.endswith('/reviews'): return [native]
        if '/actions/runs?' in path: return [producer]
        if path.endswith('/comments'): return []
        if path.endswith('/files'): return files
        raise AssertionError(path)
    api.pages.side_effect = pages
    api.file.side_effect = lambda repository, path, revision: contents[path]
    api.call.side_effect = lambda path: ({'sha': head, 'tree': {'sha': subject['tree']}}
                                        if '/git/commits/' in path else tree)
    return api, value, entry, unit, review_binding, native, producer, files, tree, contents


class SourceGeneratedLockTests(unittest.TestCase):
    def registered(self, fixture):
        from contextlib import ExitStack
        stack = ExitStack()
        stack.enter_context(patch.object(control, 'SOURCE_GENERATED_LOCK_ADMISSIONS', (fixture[2],)))
        stack.enter_context(patch.object(control, 'SOURCE_GENERATED_UNIT', fixture[3]))
        stack.enter_context(patch.object(control, 'SOURCE_GENERATED_REVIEW', fixture[4]))
        return stack

    def test_actual_passed_proof_metadata_is_not_an_admission(self):
        receipt = source_qualification_fixture(actual_metadata=True)
        self.assertEqual(control.digest(receipt), control.source_generated_qualification(receipt))
        fixture = source_generated_fixture()
        fixture[1]['body'] = json.dumps(fixture[2])
        fixture[1]['labels'] = [{'name': 'accept-generated-source'}]
        with patch.object(control, 'SOURCE_GENERATED_LOCK_ADMISSIONS', ()), \
                self.assertRaisesRegex(control.ControlError, 'copilot-native-frame-not-accepted'):
            control.copilot_review(fixture[0], control.SOURCE_GENERATED_SUBJECT['repository'], fixture[1])
        fixture[0].file.assert_not_called()

    def test_registered_exact_owner_fact_binds_the_actual_qualification(self):
        fixture = source_generated_fixture()
        descriptor = control.source_generated_descriptor(
            control.SOURCE_GENERATED_SUBJECT['repository'], fixture[1])
        self.assertEqual(1, len(control.SOURCE_GENERATED_LOCK_ADMISSIONS))
        self.assertIs(descriptor, control.SOURCE_GENERATED_LOCK_ADMISSIONS[0])
        self.assertEqual('c9bb5b0d12b29b09c3665b086b76f0c89791ce20af2998f463a8d674d299fea2',
                         control.source_generated_qualification(descriptor['qualification']))
        self.assertEqual('chat:01a16039-c39f-77f0-9331-67822ff31eb3/01a1607a-a0da-7760-978a-b49759ef467a',
                         descriptor['owner_acceptance']['decision_reference'])
        self.assertEqual('source-2658-generated-lock-only', descriptor['owner_acceptance']['scope'])
        fixture[0].file.assert_not_called()

    def test_exact_source_case_keeps_native_exclusion_and_separate_quality(self):
        fixture = source_generated_fixture()
        with self.registered(fixture):
            proof = control.copilot_review(fixture[0], control.SOURCE_GENERATED_SUBJECT['repository'], fixture[1])
        coverage = proof['source_generated_artifact_coverage']
        self.assertEqual([{'path': control.SOURCE_GENERATED_SUBJECT['path'], 'reason': 'Generated file',
                           'reviewed_by_copilot': False}], coverage['unreviewed'])
        self.assertNotIn('quality', coverage)
        self.assertNotIn('generated_artifact_coverage', proof)
        self.assertTrue(all(call.kwargs.get('method', 'GET') == 'GET'
                            for call in fixture[0].call.call_args_list))

    def test_wrong_subject_fork_branch_or_actor_stops_before_file_reads(self):
        mutations = [('head', 'sha', 'e' * 40), ('base', 'sha', 'e' * 40),
                     ('head', 'ref', 'another-feature'), ('base', 'ref', 'main')]
        for side, key, value in mutations:
            fixture = source_generated_fixture(); fixture[1][side][key] = value
            with self.subTest(side=side, key=key), self.registered(fixture), self.assertRaises(control.ControlError):
                control.copilot_review(fixture[0], control.SOURCE_GENERATED_SUBJECT['repository'], fixture[1])
            fixture[0].file.assert_not_called()
        for change in ('fork', 'actor', 'closed', 'draft'):
            fixture = source_generated_fixture()
            if change == 'fork': fixture[1]['head']['repo']['id'] = 123
            if change == 'actor': fixture[1]['user']['id'] = 123
            if change == 'closed': fixture[1]['state'] = 'closed'
            if change == 'draft': fixture[1]['draft'] = True
            with self.subTest(change=change), self.registered(fixture), self.assertRaises(control.ControlError):
                control.source_generated_descriptor(control.SOURCE_GENERATED_SUBJECT['repository'], fixture[1])

    def test_unqualified_failed_stale_or_repeated_proof_cannot_be_registered(self):
        import copy
        for field, value in [('exit_code', 1), ('generation_invocations', 2), ('container_invocations', True),
                             ('proof_plan_sha256', '0' * 64), ('output_lock_sha256', '0' * 64),
                             ('baseline_lock_sha256', '0' * 64), ('raw_receipt_sha256', '')]:
            receipt = copy.deepcopy(source_qualification_fixture())
            receipt[field] = value
            with self.subTest(field=field), self.assertRaises(control.ControlError):
                control.source_generated_qualification(receipt)
        for key in control.SOURCE_GENERATED_CHECKS:
            receipt = source_qualification_fixture(); receipt['checks'][key] = False
            with self.subTest(check=key), self.assertRaisesRegex(control.ControlError, 'proof-not-successful'):
                control.source_generated_qualification(receipt)
        for field in ['subject', 'toolchain', 'registry_integrities']:
            receipt = source_qualification_fixture(); receipt[field] = {}
            with self.subTest(field=field), self.assertRaises(control.ControlError):
                control.source_generated_qualification(receipt)

    def test_owner_acceptance_cannot_be_implied_by_technical_pass(self):
        for approval in [None, {}, {'scope': 'all-source-locks', 'receipt_sha256': '0' * 64,
                                    'decision_reference': 'candidate-label'}]:
            fixture = source_generated_fixture(); fixture[2]['owner_acceptance'] = approval
            with self.registered(fixture), self.assertRaisesRegex(control.ControlError, 'owner-acceptance'):
                control.source_generated_descriptor(control.SOURCE_GENERATED_SUBJECT['repository'], fixture[1])

    def test_native_input_inventory_modes_tree_and_bytes_remain_strict(self):
        for damage in ['extra-path', 'rename', 'truncated', 'symlink', 'blob', 'size', 'bytes']:
            fixture = source_generated_fixture()
            if damage == 'extra-path': fixture[7].append({'filename': 'unreviewed.py', 'status': 'modified'})
            if damage == 'rename': fixture[7][0]['previous_filename'] = 'different'
            if damage == 'truncated': fixture[8]['truncated'] = True
            if damage == 'symlink': fixture[8]['tree'][0]['mode'] = '120000'
            if damage == 'blob': fixture[8]['tree'][0]['sha'] = 'e' * 40
            if damage == 'size': fixture[8]['tree'][0]['size'] += 1
            if damage == 'bytes': fixture[9][fixture[3][0]['path']] += b'changed'
            with self.subTest(damage=damage), self.registered(fixture), self.assertRaisesRegex(control.ControlError, 'source-generated-native'):
                control.copilot_review(fixture[0], control.SOURCE_GENERATED_SUBJECT['repository'], fixture[1])

    def test_review_or_provider_drift_does_not_reuse_the_admission(self):
        for field, value in [('id', 99), ('body', NATIVE_BODY), ('state', 'DISMISSED')]:
            fixture = source_generated_fixture(); fixture[5][field] = value
            with self.subTest(field=field), self.registered(fixture), self.assertRaises(control.ControlError):
                control.copilot_review(fixture[0], control.SOURCE_GENERATED_SUBJECT['repository'], fixture[1])
        fixture = source_generated_fixture(); fixture[6]['id'] = 99
        with self.registered(fixture), self.assertRaisesRegex(control.ControlError, 'review-binding'):
            control.copilot_review(fixture[0], control.SOURCE_GENERATED_SUBJECT['repository'], fixture[1])

    def test_extra_exclusion_or_wrong_reason_remains_rejected(self):
        import hashlib
        for body in [GENERATED_BODY.replace(GENERATED_PATH, 'another-generated.yaml'),
                     GENERATED_BODY.replace(GENERATED_PATH, control.SOURCE_GENERATED_SUBJECT['path'])
                         .replace('Generated file', 'Binary file'),
                     GENERATED_BODY.replace(GENERATED_PATH, control.SOURCE_GENERATED_SUBJECT['path'])
                         .replace('1 file not reviewed', '2 files not reviewed')]:
            fixture = source_generated_fixture(); fixture[5]['body'] = body
            fixture[4]['body_sha256'] = hashlib.sha256(body.encode()).hexdigest()
            with self.registered(fixture), self.assertRaisesRegex(control.ControlError, 'copilot-native-frame-not-accepted'):
                control.copilot_review(fixture[0], control.SOURCE_GENERATED_SUBJECT['repository'], fixture[1])

    def test_current_quality_is_still_required_before_final_acceptance(self):
        fixture = source_generated_fixture()
        with self.registered(fixture):
            proof = control.copilot_review(fixture[0], control.SOURCE_GENERATED_SUBJECT['repository'], fixture[1])
        config = {'quality': [{'workflow': '.github/workflows/repository-quality.yml', 'job': 'repository / quality'}]}
        quality = [{'check': 1, 'run': 2, 'attempt': 1, 'base': fixture[1]['base']['sha'], 'head': fixture[1]['head']['sha']}]
        for cfg, records in [({'quality': []}, []), (config, []),
                             (config, [quality[0] | {'head': 'e' * 40}]),
                             (config, [quality[0] | {'base': 'e' * 40}])]:
            with self.subTest(records=records), self.assertRaisesRegex(control.ControlError, 'current-quality-required'):
                control.complete_generated_lock_quality(proof, cfg, records, fixture[1])
        control.complete_generated_lock_quality(proof, config, quality, fixture[1])
        self.assertEqual(quality, proof['source_generated_artifact_coverage']['quality'])

    def test_repeated_native_observation_never_spends_another_slot(self):
        fixture = source_generated_fixture()
        with self.registered(fixture):
            first = control.copilot_review(fixture[0], control.SOURCE_GENERATED_SUBJECT['repository'], fixture[1])
            second = control.copilot_review(fixture[0], control.SOURCE_GENERATED_SUBJECT['repository'], fixture[1])
        self.assertEqual(first, second)
        self.assertTrue(all(call.kwargs.get('method', 'GET') == 'GET'
                            for call in fixture[0].call.call_args_list))

    def test_wrong_source_pr_or_candidate_metadata_cannot_select_a_case(self):
        fixture = source_generated_fixture(); fixture[1]['number'] += 1
        with self.registered(fixture):
            self.assertIsNone(control.source_generated_descriptor(control.SOURCE_GENERATED_SUBJECT['repository'], fixture[1]))
        fixture = source_generated_fixture(); fixture[2]['subject'] = fixture[2]['subject'] | {'pr': 123}
        with self.registered(fixture), self.assertRaisesRegex(control.ControlError, 'admission-shape'):
            control.source_generated_descriptor(control.SOURCE_GENERATED_SUBJECT['repository'], fixture[1])


class SourceLiteralRegistryTests(unittest.TestCase):
    """Mutate the actual registered entry, never its matching control constants."""
    def subject(self):
        return source_generated_fixture()[1]

    def mutation_rejects(self, mutate, reason):
        import copy
        entries=copy.deepcopy(control.SOURCE_GENERATED_LOCK_ADMISSIONS)
        mutate(entries[0])
        with patch.object(control,'SOURCE_GENERATED_LOCK_ADMISSIONS',entries), \
                self.assertRaisesRegex(control.ControlError,'^'+reason+'$'):
            control.source_generated_descriptor(control.SOURCE_GENERATED_SUBJECT['repository'],self.subject())

    def test_literal_owner_qualification_digest_and_scope_mutations(self):
        self.mutation_rejects(lambda e:e['owner_acceptance'].__setitem__('receipt_sha256','0'*64),
                              'source-generated-owner-acceptance')
        self.mutation_rejects(lambda e:e['owner_acceptance'].__setitem__('scope','all-generated-files'),
                              'source-generated-owner-acceptance')

    def test_literal_review_binding_mutations_reach_descriptor_guard(self):
        for key,value in [('id',99),('service_run',99),('body_sha256','0'*64)]:
            with self.subTest(key=key):
                self.mutation_rejects(lambda e:e['review'].__setitem__(key,value),
                                      'source-generated-admission-shape')

    def test_literal_input_or_qualification_hash_mutations(self):
        self.mutation_rejects(lambda e:e['unit'][0].__setitem__('sha256','0'*64),
                              'source-generated-admission-shape')
        self.mutation_rejects(lambda e:e['qualification'].__setitem__('unit_manifest_sha256','0'*64),
                              'source-generated-receipt-binding')
        self.mutation_rejects(lambda e:e['qualification'].__setitem__('output_lock_sha256','0'*64),
                              'source-generated-proof-not-successful')

    def test_literal_duplicate_registry_is_ambiguous(self):
        entry=control.SOURCE_GENERATED_LOCK_ADMISSIONS[0]
        with patch.object(control,'SOURCE_GENERATED_LOCK_ADMISSIONS',(entry,entry)), \
                self.assertRaisesRegex(control.ControlError,'^source-generated-admission-ambiguous$'):
            control.source_generated_descriptor(control.SOURCE_GENERATED_SUBJECT['repository'],self.subject())

    def test_literal_unknown_schema_fields_reject_at_own_boundary(self):
        self.mutation_rejects(lambda e:e.__setitem__('wildcard',True),'source-generated-admission-shape')
        self.mutation_rejects(lambda e:e['qualification'].__setitem__('ttl',999),'source-generated-receipt-shape')
        self.mutation_rejects(lambda e:e['owner_acceptance'].__setitem__('all_heads',True),
                              'source-generated-owner-acceptance')

    def test_other_pr_review_is_identical_with_populated_source_registry(self):
        def evaluate():
            api=Mock();api.pages.side_effect=[[native_review()],[delivery()],[]]
            result=control.copilot_review(api,REPO,pull())
            self.assertTrue(all(c.kwargs.get('method','GET')=='GET' for c in api.call.call_args_list))
            return result
        self.assertEqual(1,len(control.SOURCE_GENERATED_LOCK_ADMISSIONS));registered=evaluate()
        with patch.object(control,'SOURCE_GENERATED_LOCK_ADMISSIONS',()):unregistered=evaluate()
        self.assertEqual(registered,unregistered);self.assertEqual(9,registered['id'])
        other=self.subject();other['number']+=1
        self.assertIsNone(control.source_generated_descriptor(control.SOURCE_GENERATED_SUBJECT['repository'],other))
