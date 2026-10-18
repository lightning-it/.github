"""Trust boundaries and paid-effect admission; no live credentials or model calls."""
import json
import os
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


class ControlTests(unittest.TestCase):
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
        self.assertEqual('58b2cd8dce5d4ca094cad34f34c5c08311f74943', checkout['with']['ref'])
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

    def test_carried_review_origin_and_current_association_cannot_be_forged(self):
        for defect in ('job-id', 'job-run', 'job-head', 'job-attempt', 'job-failed', 'job-running',
                       'origin-run', 'origin-head', 'origin-attempt-bool', 'origin-workflow', 'origin-namespace',
                       'origin-pr', 'origin-pr-head', 'origin-membership', 'origin-job-attempt-bool',
                       'duplicate-origin', 'duplicate-current-review', 'duplicate-current-final', 'latest-head'):
            api, state = verifier_only_refresh_api()
            if defect == 'job-id': state['review'] |= {'id': 999}
            elif defect == 'job-run': state['review'] |= {'run_id': 11}
            elif defect == 'job-head': state['review'] |= {'head_sha': BASE}
            elif defect == 'job-attempt': state['review'] |= {'run_attempt': 2}
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
