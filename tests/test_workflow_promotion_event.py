"""Only a current protected push with an actual passing job can prepare a PR."""
import copy
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import workflow_promotion_event as event
from workflow_control import ControlError

HEAD = 'a' * 40


class PromotionEventTests(unittest.TestCase):
    def fixture(self):
        env = {'GITHUB_REPOSITORY': event.REPOSITORY, 'GITHUB_REPOSITORY_ID': str(event.REPOSITORY_ID),
               'GITHUB_EVENT_NAME': 'workflow_run', 'GITHUB_REF': 'refs/heads/develop',
               'GITHUB_WORKFLOW_REF': f'{event.REPOSITORY}/{event.DELIVERY}@refs/heads/develop',
               'NATIVE_JOB': json.dumps({'workflow_repository': event.REPOSITORY,
                    'workflow_file_path': event.DELIVERY, 'workflow_sha': 'b' * 40, 'check_run_id': 55})}
        signal = {'action': 'completed', 'workflow_run': {'id': 42, 'head_sha': HEAD}}
        run = {'id': 42, 'workflow_id': 7, 'name': 'Repository Quality', 'path': event.QUALITY,
               'event': 'push', 'head_branch': 'develop', 'run_attempt': 1, 'head_sha': HEAD,
               'status': 'completed', 'conclusion': 'success',
               'repository': {'id': event.REPOSITORY_ID}, 'head_repository': {'id': event.REPOSITORY_ID}}
        branch = {'name': 'develop', 'protected': True, 'commit': {'sha': HEAD}}
        job = {'name': 'repository / quality', 'status': 'completed', 'conclusion': 'success'}
        api = Mock()
        api.call.side_effect = [run, {'id': 7, 'path': event.QUALITY}, branch]
        api.pages.return_value = [job]
        return api, signal, env, run, branch, job

    def test_current_native_push_admits_only_a_head_and_performs_no_write(self):
        api, signal, env, *_ = self.fixture()
        self.assertEqual(HEAD, event.current_head(api, signal, env))
        self.assertTrue(all('method' not in call.kwargs for call in api.call.call_args_list))

    def test_stale_successful_push_is_a_noop_before_job_or_dispatch_access(self):
        api, signal, env, run, branch, _ = self.fixture()
        branch['commit']['sha'] = 'c' * 40
        self.assertIsNone(event.current_head(api, signal, env))
        api.pages.assert_not_called()

    def test_pr_fork_failed_skipped_rerun_and_wrong_workflow_cannot_admit(self):
        for change in ({'event': 'pull_request'}, {'head_branch': 'main'}, {'run_attempt': 2},
                       {'conclusion': 'failure'}, {'conclusion': 'skipped'}, {'status': 'in_progress'},
                       {'head_repository': {'id': 42}}, {'repository': {'id': 42}}, {'workflow_id': 9},
                       {'path': '.github/workflows/other.yml'}, {'head_sha': 'c' * 40}):
            api, signal, env, run, branch, _ = self.fixture()
            run.update(copy.deepcopy(change))
            with self.subTest(change=change), self.assertRaises(ControlError):
                event.current_head(api, signal, env)
            api.pages.assert_not_called()

    def test_successful_workflow_with_missing_skipped_or_duplicate_quality_blocks(self):
        for change in ([], [{'name': 'repository / quality', 'status': 'completed', 'conclusion': 'skipped'}],
                       [{'name': 'repository / quality', 'status': 'completed', 'conclusion': 'success'}] * 2):
            api, signal, env, *_ = self.fixture()
            api.pages.return_value = change
            with self.subTest(jobs=change), self.assertRaises(ControlError):
                event.current_head(api, signal, env)

    def test_candidate_or_foreign_context_blocks_before_access(self):
        for change in ({'GITHUB_EVENT_NAME': 'pull_request_target'}, {'GITHUB_REF': 'refs/pull/3/merge'},
                       {'GITHUB_REPOSITORY': 'contributor/fork'}, {'GITHUB_REPOSITORY_ID': '42'},
                       {'GITHUB_WORKFLOW_REF': f'{event.REPOSITORY}/{event.DELIVERY}@refs/heads/main'}):
            api, signal, env, *_ = self.fixture()
            env.update(change)
            with self.subTest(change=change), self.assertRaises(ControlError):
                event.current_head(api, signal, env)
            api.call.assert_not_called()

    def test_unprotected_branch_or_missing_native_signal_blocks(self):
        for locator in (None, True, 0, '42'):
            api, signal, env, *_ = self.fixture()
            signal['workflow_run']['id'] = locator
            with self.subTest(locator=locator), self.assertRaises(ControlError):
                event.current_head(api, signal, env)
            api.call.assert_not_called()
        api, signal, env, _, branch, _ = self.fixture()
        branch['protected'] = False
        with self.assertRaises(ControlError):
            event.current_head(api, signal, env)
