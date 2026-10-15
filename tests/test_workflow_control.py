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
        api.call.side_effect = [pull(), pull(), {}]
        api.pages.side_effect = [[run()], [{'id': 100, 'run_id': 10, 'name': 'Current revision review',
                                           'status': 'completed', 'conclusion': 'success'},
                                          {'id': 101, 'run_id': 10, 'name': 'Protected current revision',
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
        checkout = next(step for step in receiver['jobs']['refresh']['steps'] if 'uses' in step)
        self.assertEqual('3e904965329c2045b52c3e9d4ca24ef6465c4b28', checkout['with']['ref'])
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
        api = Mock(); api.call.side_effect = [producer, pull(), pull(), {}]
        review = {'id': 101, 'run_id': 10, 'name': 'Protected current revision', 'status': 'completed', 'conclusion': 'success'}
        gate = {'id': 100, 'run_id': 10, 'name': 'Current revision review', 'status': 'in_progress', 'conclusion': None}
        api.pages.side_effect = [[run()], [review, gate], [review, gate | {'status': 'completed', 'conclusion': 'success'}]]
        with patch.object(events.time, 'sleep') as wait:
            events.refresh(api, REPO, 'workflow_run', {'workflow_run': {'id': 22}})
        wait.assert_called_once_with(15)
        self.assertEqual(f'repos/{REPO}/actions/jobs/100/rerun', api.call.call_args.args[0])

    def test_generic_comments_cannot_refresh_or_fund_a_protected_review(self):
        api = Mock()
        with self.assertRaisesRegex(control.ControlError, 'unsupported-refresh-event'):
            events.refresh(api, REPO, 'issue_comment', {'issue': {'number': 3, 'pull_request': {'url': 'native'}}})
        api.call.assert_not_called()
        api.pages.assert_not_called()

    def test_late_copilot_delivery_reruns_review_with_no_new_request(self):
        api = Mock(); api.call.side_effect = [pull(), pull(), {}]
        api.pages.side_effect = [[run()], [
            {'id': 101, 'run_id': 10, 'name': 'Protected current revision', 'status': 'completed', 'conclusion': 'failure'},
            {'id': 100, 'run_id': 10, 'name': 'Current revision review', 'status': 'completed', 'conclusion': 'failure'}]]
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
