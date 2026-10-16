"""A failed/unknown slot can only gain one genuine natively approved extra attempt."""
import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import workflow_control as control
import workflow_recovery as recovery

REPO = 'lightning-it/private-example'
SOURCE = 'a' * 40
PRIOR = 'b815cefb4a5f18cd97b3947c789b6db59fedf991'


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.pull = {'number': 9, 'state': 'open', 'draft': False, 'title': 'Real change', 'body': None, 'labels': [],
                     'user': dict(zip(('login', 'id', 'type'), control.RELEASE)),
                     'head': {'sha': 'b' * 40, 'ref': 'qualification/real', 'repo': {'full_name': REPO}},
                     'base': {'sha': 'c' * 40, 'ref': 'develop', 'repo': {'full_name': REPO}}}
        link = {'number': 9, 'head': {'sha': 'b' * 40}, 'base': {'sha': 'c' * 40}}
        self.failed = {'id': 10, 'workflow_id': 101, 'workflow_url': f'https://api.github.com/repos/{REPO}/actions/required_workflows/101',
                       'path': control.WORKFLOW, 'head_sha': 'b' * 40, 'pull_requests': [link], 'event': 'pull_request',
                       'run_attempt': 1, 'status': 'completed', 'conclusion': 'failure'}
        self.native = self.failed | {'id': 20, 'workflow_id': 102, 'workflow_url': f'https://api.github.com/repos/{REPO}/actions/required_workflows/102',
                                     'status': 'in_progress', 'conclusion': None}
        self.job = {'id': 30, 'run_id': 10, 'status': 'completed', 'conclusion': 'failure', 'name': 'Protected current revision',
                    'steps': [{'name': n, 'conclusion': outcome, 'status': 'completed'} for n, outcome in (
                        ('Classify protected current revision', 'success'), ('Reserve protected Codex request', 'success'),
                        ('Protected exact-revision Codex review', 'failure'), ('Collect and verify the protected model receipt', 'skipped'),
                        ('Export protected native Codex evidence', 'skipped'))]}
        self.value = {'repository': REPO, 'pull': 9, 'head': 'b' * 40, 'base': 'c' * 40, 'failed_run': 10, 'failed_attempt': 1}
        self.comment = {'id': 40, 'updated_at': '2026-10-16T10:00:00Z',
                        'user': dict(zip(('login', 'id', 'type'), recovery.OWNER)),
                        'body': recovery.MARKER + json.dumps(self.value) + ' -->'}
        self.api = Mock()
        self.runs = [self.failed, self.native]
        self.artifacts = [{'name': 'control-review-outcome-1', 'expired': False}]
        self.outcome = {'version': 1, 'run': 10, 'source_sha': SOURCE,
                        'binding': {'repository': REPO, 'pull_request': 9, 'head_sha': 'b' * 40, 'base_sha': 'c' * 40},
                        'category': 'transport-service-unavailable', 'result_produced': False,
                        'failure': {'category': 'transport-service-unavailable'}}
        self.comments = [self.comment]
        def pages(path, key=None):
            if '/issues/9/comments' in path: return self.comments
            if '/runs?head_sha=' in path: return self.runs
            if path.endswith('/runs/10/attempts/1/jobs'): return [self.job]
            if path.endswith('/runs/20/attempts/1/jobs'): return [self.job | {'run_id': 20}]
            if path.endswith('/runs/10/artifacts'): return self.artifacts
            raise AssertionError(path)
        self.api.pages.side_effect = pages
        self.api.native_job_log.return_value = f'"workflow_sha": "{SOURCE}", "workflow_repository": "{control.SOURCE}", "workflow_file_path": "{control.WORKFLOW}"'
        self.record = {'version': 1, 'source_sha': SOURCE, 'binding': control.binding(self.pull)}
        self.op = patch.object(control, 'operation_record', side_effect=lambda *a: self.record)
        self.env = patch.object(control, 'normal_environment', return_value={'id': 50})
        self.outcome_patch = patch.object(control, 'artifact_record', side_effect=lambda *a: self.outcome)
        self.op.start(); self.env.start(); self.outcome_patch.start()
        self.addCleanup(self.op.stop); self.addCleanup(self.env.stop); self.addCleanup(self.outcome_patch.stop)

    def plan(self): return recovery.plan(self.api, REPO, self.pull, SOURCE, self.native)

    def test_one_failed_reservation_is_a_plan_not_authority(self):
        plan = self.plan()
        self.assertEqual(plan['additional_attempts'], 1)
        self.assertEqual(plan['original_provider_outcome'], 'unknown')
        self.assertFalse(plan['release_authorized'])
        self.assertEqual(plan['failed_job'], 30)

    def test_no_owner_request_keeps_ordinary_funding_unchanged(self):
        self.comments = []
        self.assertIsNone(self.plan())
        self.comment['user']['id'] = 1; self.comments = [self.comment]
        self.assertIsNone(self.plan())

    def test_foreign_stale_or_duplicate_request_cannot_request_extra_funding(self):
        for field, value in (('head', 'd' * 40), ('base', 'd' * 40), ('pull', True), ('repository', 'other/repo'), ('failed_attempt', True)):
            with self.subTest(field=field):
                self.comment['body'] = recovery.MARKER + json.dumps(self.value | {field: value}) + ' -->'
                with self.assertRaises(control.ControlError): self.plan()
        self.comment['body'] = recovery.MARKER + json.dumps(self.value) + ' -->'
        self.comments = [self.comment, copy.deepcopy(self.comment)]
        with self.assertRaises(control.ControlError): self.plan()

    def test_current_native_subject_and_first_attempt_are_required(self):
        for change in ({'run_attempt': 2}, {'head_sha': 'd' * 40}, {'event': 'workflow_dispatch'}, {'pull_requests': []}):
            original = self.native; self.native = original | change
            with self.subTest(change=change), self.assertRaises(control.ControlError): self.plan()
            self.native = original

    def test_pending_successful_or_delivered_prior_outcomes_block(self):
        for target, key, value in ((self.failed, 'status', 'in_progress'), (self.failed, 'conclusion', 'success'),
                                    (self.job['steps'][2], 'conclusion', 'success'),
                                    (self.job['steps'][3], 'conclusion', 'failure')):
            before = target[key]; target[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(control.ControlError): self.plan()
            target[key] = before
        self.artifacts = [{'name': 'codex-receipt-1', 'expired': True}]
        with self.assertRaises(control.ControlError): self.plan()

    def test_prior_source_and_full_subject_cannot_be_forged(self):
        for change in ('source', 'binding', 'log', 'author'):
            with self.subTest(change=change):
                record = copy.deepcopy(self.record); log = self.api.native_job_log.return_value
                if change == 'source': self.record['source_sha'] = 'e' * 40
                if change == 'binding': self.record['binding']['base'] = 'e' * 40
                if change == 'log': self.api.native_job_log.return_value = 'candidate assertion'
                if change == 'author': self.record['binding']['author'] = list(control.SYNC)
                with self.assertRaises(control.ControlError): self.plan()
                self.record = record; self.api.native_job_log.return_value = log

    def test_a_second_reserved_slot_blocks_even_across_workflow_ids(self):
        additional = self.failed | {'id': 15, 'workflow_id': 103, 'workflow_url': f'https://api.github.com/repos/{REPO}/actions/required_workflows/103'}
        pages = self.api.pages.side_effect
        self.api.pages.side_effect = lambda path, key=None: [self.job | {'run_id': 15}] if path.endswith('/runs/15/attempts/1/jobs') else pages(path, key)
        self.runs.insert(1, additional)
        with self.assertRaisesRegex(control.ControlError, 'one-previous-reservation'): self.plan()

    def test_request_alone_or_wrong_native_approval_never_funds(self):
        digest = control.digest(self.plan())
        self.api.call.return_value = []
        with self.assertRaises(control.ControlError): recovery.authorize(self.api, REPO, self.pull, SOURCE, self.native, digest)
        bad = {'state': 'approved', 'user': {'id': 60, 'type': 'User'}, 'environments': [{'id': 99, 'name': 'normal-release-promotion-approval'}]}
        self.api.call.return_value = [bad]
        with self.assertRaisesRegex(control.ControlError, 'exact-native-environment'): recovery.authorize(self.api, REPO, self.pull, SOURCE, self.native, digest)

    def test_current_native_user_approval_and_fresh_binding_are_required(self):
        digest = control.digest(self.plan())
        approved = {'state': 'approved', 'user': {'id': 60, 'type': 'User'}, 'environments': [{'id': 50, 'name': 'normal-release-promotion-approval'}]}
        self.api.call.side_effect = lambda path: [approved] if path.endswith('/approvals') else self.pull
        result = recovery.authorize(self.api, REPO, self.pull, SOURCE, self.native, digest)
        self.assertEqual(result['approval']['user']['id'], 60)
        self.comment['updated_at'] = '2026-10-16T10:01:00Z'
        with self.assertRaisesRegex(control.ControlError, 'plan-drift'): recovery.authorize(self.api, REPO, self.pull, SOURCE, self.native, digest)

    def test_missing_environment_blocks_and_successful_prior_replay_grants_no_allocation(self):
        with patch.object(control, 'normal_environment', side_effect=control.ControlError('missing')):
            with self.assertRaises(control.ControlError): self.plan()
        self.job['conclusion'] = 'success'
        self.job['steps'][1]['conclusion'] = 'skipped'
        self.assertIsNone(self.plan())

    def test_post_response_action_failure_and_deterministic_rejection_block(self):
        for key, value in (('result_produced', True), ('category', 'single-full-input'), ('source_sha', 'd' * 40)):
            before = self.outcome[key]; self.outcome[key] = value
            with self.subTest(key=key), self.assertRaises(control.ControlError): self.plan()
            self.outcome[key] = before

    def test_legacy_unknown_outcome_requires_explicit_exact_log_acknowledgment(self):
        import hashlib
        self.artifacts = []
        with self.assertRaisesRegex(control.ControlError, 'legacy-unknown'): self.plan()
        self.record['source_sha'] = PRIOR
        self.api.native_job_log.return_value = self.api.native_job_log.return_value.replace(SOURCE, PRIOR)
        self.api.native_job_log.return_value += '\nERROR: We’re currently experiencing high demand\nProtected gateway failure category: single-contract-rejected'
        value = self.value | {'legacy_unknown_outcome_sha256': hashlib.sha256(self.api.native_job_log.return_value.encode()).hexdigest()}
        self.comment['body'] = recovery.MARKER + json.dumps(value) + ' -->'
        self.assertEqual(self.plan()['outcome']['result_produced'], 'unknown')
        self.api.native_job_log.return_value += '\nchanged'
        with self.assertRaises(control.ControlError): self.plan()

    def test_fully_skipped_generation_is_known_no_spend(self):
        skipped = self.failed | {'id': 15, 'conclusion': 'failure'}
        pages = self.api.pages.side_effect
        self.api.pages.side_effect = lambda path, key=None: [self.job | {'run_id': 15, 'conclusion': 'skipped', 'steps': []}] if path.endswith('/runs/15/attempts/1/jobs') else pages(path, key)
        self.runs.insert(1, skipped)
        self.assertEqual(self.plan()['additional_attempts'], 1)
        self.assertFalse(control.request_slot_started(self.api, REPO, skipped))

    def test_full_rerun_and_fresh_generation_can_replay_without_authority(self):
        self.job['conclusion'] = 'success'
        self.assertIsNone(self.plan())
        self.native['run_attempt'] = 2
        self.assertIsNone(self.plan())
        with self.assertRaisesRegex(control.ControlError, 'plan-drift'):
            recovery.authorize(self.api, REPO, self.pull, SOURCE, self.native, 'a' * 64)

    def test_no_request_does_not_bypass_cross_generation_ordinary_reservation(self):
        self.api.call.return_value = self.native
        self.comments = []
        self.assertIsNone(self.plan())
        with patch.dict(os.environ, {'REVIEW_RECOVERY_PLAN_SHA256': ''}):
            with self.assertRaisesRegex(control.ControlError, 'request-slot-already-consumed'):
                control.reserve_request(self.api, REPO, self.pull, SOURCE, 20, 1)

    def test_reservation_accepts_only_the_authorized_bound_plan(self):
        digest = control.digest(self.plan())
        self.api.call.return_value = self.native
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'REVIEW_RECOVERY_PLAN_SHA256': digest}):
            before = Path.cwd(); os.chdir(temp)
            try:
                with patch.object(recovery, 'authorize', return_value={'approved': True}) as authorize:
                    self.assertEqual(control.reserve_request(self.api, REPO, self.pull, SOURCE, 20, 1), 20)
                    self.assertEqual(json.loads(Path('control-recovery.json').read_bytes()), {'approved': True})
                    authorize.assert_called_once_with(self.api, REPO, self.pull, SOURCE, self.native, digest)
                Path('control-recovery.json').unlink()
                with patch.object(recovery, 'authorize', side_effect=control.ControlError('denied')), self.assertRaises(control.ControlError):
                    control.reserve_request(self.api, REPO, self.pull, SOURCE, 20, 1)
                self.assertFalse(Path('control-recovery.json').exists())
            finally: os.chdir(before)


if __name__ == '__main__': unittest.main()
