"""Historical closure races never substitute for current or failed review."""
import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import workflow_control as control
import workflow_ingress as ingress

REPO = 'lightning-it/.github'
HEAD, SOURCE = 'a' * 40, 'b' * 40
MERGED = '2026-10-15T12:01:00Z'


def native(attempt, conclusion, timestamp):
    return {'id': 10, 'run_attempt': attempt, 'head_sha': HEAD, 'status': 'completed',
            'conclusion': conclusion, 'updated_at': timestamp, 'run_started_at': '2026-10-15T12:00:00Z', 'workflow_id': 77,
            'workflow_url': f'https://api.github.com/repos/{REPO}/actions/required_workflows/77',
            'path': control.WORKFLOW}


class HistoricalIngressTests(unittest.TestCase):
    def fixture(self):
        from test_workflow_control import pull as ordinary_pull
        pull = ordinary_pull(state='closed', merged=True, merge_commit_sha='c' * 40, merged_at=MERGED)
        accepted = native(1, 'success', '2026-10-15T12:00:40Z')
        failed = native(2, 'failure', '2026-10-15T12:01:04Z')
        gate = {'id': 101, 'run_id': 10, 'run_attempt': 2, 'name': 'Current revision review',
                'status': 'completed', 'conclusion': 'failure', 'completed_at': '2026-10-15T12:01:03Z',
                'steps': [{'name': ingress.FINAL_STEP, 'conclusion': 'failure'}]}
        operation = {'version': 1, 'source_sha': SOURCE, 'binding': control.binding(pull)}
        api = Mock(spec=control.API)
        api.call.side_effect = [failed, accepted]
        api.pages.return_value = [gate]
        api.lifecycle = [{'id': 200, 'event': 'merged', 'created_at': MERGED, 'commit_id': pull['merge_commit_sha']},
                         {'id': 201, 'event': 'closed', 'created_at': MERGED}]
        api.pages.side_effect = lambda path, _key=None: api.lifecycle if path.endswith('/events') else api.pages.return_value
        api.native_job_log.return_value = '2026-10-15T12:01:02.1234567Z ' + ingress.CLOSED + '\n'
        return api, pull, accepted, failed, gate, operation

    def test_real_premerge_success_is_returned_with_later_failure_preserved(self):
        api, pull, accepted, failed, _, operation = self.fixture()
        with patch.object(ingress, 'operation_record', return_value=operation):
            actual, failures = ingress.merged_attempt(api, REPO, pull, failed)
        self.assertEqual(accepted, actual)
        self.assertEqual([{'attempt': 2, 'job': 101, 'conclusion': 'failure',
                           'reason': 'pull-not-reviewable-after-merge',
                           'completed_at': '2026-10-15T12:01:03Z', 'merge_event': 200, 'closed_event': 201}], failures)
        self.assertTrue(all(not call.kwargs for call in api.call.call_args_list))

    def test_open_unmerged_pending_or_single_failed_attempt_cannot_fall_back(self):
        for change in ({'state': 'open'}, {'merged': False}, {'merge_commit_sha': None}):
            api, pull, _, failed, _, _ = self.fixture()
            with self.subTest(change=change), self.assertRaises(control.ControlError):
                ingress.merged_attempt(api, REPO, pull | change, failed)
            api.call.assert_not_called()
        for change in ({'status': 'in_progress'}, {'conclusion': 'cancelled'}, {'run_attempt': 1}):
            api, pull, _, failed, _, _ = self.fixture()
            with self.subTest(change=change), self.assertRaises(control.ControlError):
                ingress.merged_attempt(api, REPO, pull, failed | change)

    def test_semantic_premerge_and_unknown_failures_are_terminal(self):
        for text in ('2026-10-15T12:00:59Z ' + ingress.CLOSED,
                     '2026-10-15T12:01:00.1000000Z ' + ingress.CLOSED,
                     '2026-10-15T12:01:00.9999999Z ' + ingress.CLOSED,
                     '2026-10-15T12:01:02Z Protected control blocked: ControlError: quality-not-successful',
                     'Unknown provider failure',
                     '2026-10-15T12:01:02Z ' + ingress.CLOSED + '\n2026-10-15T12:01:03Z ' + ingress.CLOSED):
            api, pull, _, failed, _, operation = self.fixture()
            api.native_job_log.return_value = text
            with self.subTest(text=text), patch.object(ingress, 'operation_record', return_value=operation), \
                    self.assertRaises(control.ControlError):
                ingress.merged_attempt(api, REPO, pull, failed)

        api, pull, _, failed, _, _ = self.fixture()
        api.call.side_effect = [failed | {'updated_at': '2026-10-15T12:00:59Z'}]
        with self.assertRaisesRegex(control.ControlError, 'semantic-failure-before-merge'):
            ingress.merged_attempt(api, REPO, pull, failed)

    def test_historical_proof_read_must_not_hide_a_concurrent_rerun(self):
        from test_workflow_control import pull as ordinary_pull
        from test_workflow_control import run
        subject = ordinary_pull(state='closed', merged=True, merge_commit_sha='c' * 40, merged_at=MERGED)
        observed = run() | {'status': 'completed', 'conclusion': 'failure', 'run_attempt': 2}
        accepted = observed | {'conclusion': 'success', 'run_attempt': 1}
        proof = {'version': 1, 'source_sha': SOURCE, 'binding': control.binding(subject), 'route': 'copilot'}
        gate = {'id': 103, 'name': 'Current revision review', 'conclusion': 'success'}
        for change in ({}, {'run_attempt': 3, 'status': 'in_progress', 'conclusion': None},
                       {'run_attempt': 3}, {'workflow_id': 78}, {'head_sha': 'e' * 40},
                       {'path': 'untrusted.yml'}, {'workflow_url': 'https://untrusted.invalid'}):
            api = Mock(spec=control.API)
            api.pages.return_value = [observed]
            api.call.side_effect = [subject, observed | change]
            with self.subTest(change=change), \
                    patch.object(ingress, 'merged_attempt', return_value=(accepted, [{'attempt': 2}])), \
                    patch.object(control, 'native_jobs', return_value=[gate]), \
                    patch.object(control, 'artifact_record', return_value=proof):
                if change:
                    with self.assertRaisesRegex(control.ControlError, 'ingress-current-run-changed'):
                        control.check_native_control(api, REPO, subject, {'accepted_sources': [SOURCE]})
                else:
                    result = control.check_native_control(api, REPO, subject, {'accepted_sources': [SOURCE]})
                    self.assertEqual(1, result['attempt'])
                self.assertEqual([f"repos/{REPO}/pulls/3", f"repos/{REPO}/actions/runs/10"],
                                 [call.args[0] for call in api.call.call_args_list])

    def test_proof_read_cannot_hide_referenced_metadata_or_new_generation(self):
        from test_workflow_control import pull as ordinary_pull
        from test_workflow_control import run
        subject = ordinary_pull(state='closed', merged=True, merge_commit_sha='c' * 40, merged_at=MERGED)
        observed = run() | {'status': 'completed', 'conclusion': 'failure', 'run_attempt': 2}
        accepted = observed | {'conclusion': 'success', 'run_attempt': 1}
        proof = {'version': 1, 'source_sha': SOURCE, 'binding': control.binding(subject), 'route': 'copilot'}
        gate = {'id': 103, 'name': 'Current revision review', 'conclusion': 'success'}
        for changes in ({'title': 'Edited during proof read'}, {'body': 'New metadata'},
                        {'labels': [{'name': 'changed'}]}, {'merged_at': '2026-10-15T12:01:01Z'},
                        {'merge_commit_sha': 'e' * 40}, {'state': 'open'}, {'merged': False}, {}):
            api = Mock(spec=control.API)
            api.call.side_effect = [subject | changes, observed]
            api.pages.side_effect = [[observed], [observed], [observed] if changes else
                                     [observed, observed | {'id': 11, 'status': 'in_progress'}]]
            with self.subTest(changes=changes), \
                    patch.object(ingress, 'merged_attempt', return_value=(accepted, [{'attempt': 2}])), \
                    patch.object(control, 'native_jobs', return_value=[gate]), \
                    patch.object(control, 'artifact_record', return_value=proof), \
                    self.assertRaisesRegex(control.ControlError,
                                           'referenced-pull-changed' if changes else 'native-generation-changed'):
                control.check_native_control(api, REPO, subject, {'accepted_sources': [SOURCE]})

    def test_stable_unrelated_same_head_runs_do_not_invalidate_bound_generation(self):
        from test_workflow_control import pull as ordinary_pull
        from test_workflow_control import run
        subject = ordinary_pull(state='closed', merged=True, merge_commit_sha='c' * 40, merged_at=MERGED)
        bound = run() | {'status': 'completed', 'conclusion': 'success'}
        proof = {'version': 1, 'source_sha': SOURCE, 'binding': control.binding(subject), 'route': 'copilot'}
        unrelated = bound | {'id': 11, 'pull_requests': [{'number': 44, 'base': subject['base'], 'head': subject['head']}]}
        for associated in (True, False):
            foreign = unrelated if associated else unrelated | {'pull_requests': []}
            api = Mock(spec=control.API)
            api.pages.return_value = [bound, foreign]
            api.call.side_effect = [subject, bound]
            foreign_record = proof | {'binding': proof['binding'] | {'number': 44}}
            with self.subTest(associated=associated), \
                    patch.object(control, 'native_jobs', return_value=[{'id': 103, 'name': 'Current revision review', 'conclusion': 'success'}]), \
                    patch.object(control, 'operation_record', return_value=foreign_record) as operation, \
                    patch.object(control, 'artifact_record', return_value=proof):
                self.assertEqual(10, control.check_native_control(api, REPO, subject, {'accepted_sources': [SOURCE]})['run'])
                self.assertEqual(0 if associated else 1, operation.call_count)

    def test_new_generation_during_operation_read_is_rejected_without_late_artifact_io(self):
        from test_workflow_control import pull as ordinary_pull
        from test_workflow_control import run
        subject = ordinary_pull(state='closed', merged=True, merge_commit_sha='c' * 40, merged_at=MERGED)
        bound = run() | {'status': 'completed', 'conclusion': 'success'}
        foreign = bound | {'id': 11, 'pull_requests': []}
        proof = {'version': 1, 'source_sha': SOURCE, 'binding': control.binding(subject), 'route': 'copilot'}
        for associated in (True, False):
            late = bound | {'id': 12, 'status': 'in_progress', 'conclusion': None}
            if not associated:
                late['pull_requests'] = []
            phase = {'read': 0, 'discovered': False}
            def pages(_path, _key=None, late=late, phase=phase):
                phase['read'] += 1
                if phase['read'] == 1:
                    return [bound]
                if phase['read'] == 2:
                    return [bound, foreign]
                self.assertTrue(phase['discovered'])
                return [bound, foreign, late]
            def operation(_api, _repo, source_run, phase=phase):
                self.assertEqual(11, source_run['id'])
                self.assertEqual(2, phase['read'], 'No operation I/O after final generation snapshot')
                phase['discovered'] = True
                return proof | {'binding': proof['binding'] | {'number': 44}}
            api = Mock(spec=control.API); api.pages.side_effect = pages
            with self.subTest(associated=associated), \
                    patch.object(control, 'native_jobs', return_value=[{'id': 103, 'name': 'Current revision review', 'conclusion': 'success'}]), \
                    patch.object(control, 'operation_record', side_effect=operation), \
                    patch.object(control, 'artifact_record', return_value=proof), \
                    self.assertRaisesRegex(control.ControlError, 'native-generation-changed' if associated else 'generation-binding-unavailable'):
                control.check_native_control(api, REPO, subject, {'accepted_sources': [SOURCE]})
            api.call.assert_not_called()

    def test_draft_or_manual_closure_cannot_be_misclassified_by_a_skewed_runner_clock(self):
        for event in ({'id': 199, 'event': 'convert_to_draft', 'created_at': '2026-10-15T12:00:30Z'},
                      {'id': 199, 'event': 'closed', 'created_at': MERGED},
                      {'id': 199, 'event': 'reopened', 'created_at': MERGED}):
            api, pull, _, failed, _, operation = self.fixture()
            api.lifecycle.insert(0, event)
            with self.subTest(event=event), patch.object(ingress, 'operation_record', return_value=operation), \
                    self.assertRaisesRegex(control.ControlError, 'ambiguous-reviewability-history'):
                ingress.merged_attempt(api, REPO, pull, failed)
        api, pull, accepted, failed, _, operation = self.fixture()
        api.lifecycle.insert(0, {'id': 199, 'event': 'convert_to_draft', 'created_at': '2026-10-15T11:59:59Z'})
        with patch.object(ingress, 'operation_record', return_value=operation):
            self.assertEqual(accepted, ingress.merged_attempt(api, REPO, pull, failed)[0])

    def test_metadata_changes_and_success_after_merge_cannot_inherit_old_acceptance(self):
        for field, changed in (('title', 'Changed title'), ('body', 'Changed body'),
                               ('labels', [{'name': 'changed-label'}])):
            api, pull, _, failed, _, operation = self.fixture()
            pull[field] = changed
            with self.subTest(field=field), patch.object(ingress, 'operation_record', return_value=operation), \
                    self.assertRaisesRegex(control.ControlError, 'current-metadata-drift'):
                ingress.merged_attempt(api, REPO, pull, failed)
        api, pull, _, failed, _, operation = self.fixture()
        changed = copy.deepcopy(operation); changed['binding']['body'] = 'Changed operation'
        with patch.object(ingress, 'operation_record', side_effect=[changed, operation]), \
                self.assertRaisesRegex(control.ControlError, 'metadata-changed'):
            ingress.merged_attempt(api, REPO, pull, failed)
        api, pull, accepted, failed, _, operation = self.fixture()
        api.call.side_effect = [failed, accepted | {'updated_at': '2026-10-15T12:01:05Z'}]
        with patch.object(ingress, 'operation_record', return_value=operation), \
                self.assertRaisesRegex(control.ControlError, 'success-not-before-merge'):
            ingress.merged_attempt(api, REPO, pull, failed)

    def test_wrong_run_source_or_failed_step_cannot_be_called_closure_only(self):
        for change in ({'head_sha': 'd' * 40}, {'workflow_id': 78}, {'path': 'candidate.yml'}):
            api, pull, _, failed, _, _ = self.fixture()
            api.call.side_effect = [failed | change]
            with self.subTest(change=change), self.assertRaisesRegex(control.ControlError, 'attempt-origin'):
                ingress.merged_attempt(api, REPO, pull, failed)
        for change in ({'name': 'Protected current revision'}, {'run_attempt': 1},
                       {'steps': [{'name': 'Request current Copilot review', 'conclusion': 'failure'}]}):
            api, pull, _, failed, gate, _ = self.fixture()
            api.pages.return_value = [gate | change]
            with self.subTest(change=change), self.assertRaises(control.ControlError):
                ingress.merged_attempt(api, REPO, pull, failed)


if __name__ == '__main__':
    unittest.main()
