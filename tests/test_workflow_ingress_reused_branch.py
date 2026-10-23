"""Historical branch locators never replace the original native proof."""
import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import workflow_control as control
from test_workflow_control import REPO, SOURCE, pull, run


class ReusedBranchIngressTests(unittest.TestCase):
    def fixture(self):
        original = pull(control.RENOVATE, state='closed', merged=True,
                        merged_at='2026-10-23T16:20:37Z', merge_commit_sha='e' * 40)
        for side in ('base', 'head'):
            original[side]['repo']['id'] = 7
        later = copy.deepcopy(original)
        later.update(number=4, state='open', merged=False,
                     created_at='2026-10-23T20:20:56Z')
        later['base']['sha'] = 'd' * 40
        later['head']['sha'] = 'f' * 40
        locator = {'number': 4, 'base': copy.deepcopy(later['base']),
                   'head': copy.deepcopy(later['head'])}
        native = run() | {'status': 'completed', 'conclusion': 'success',
                          'pull_requests': [locator]}
        operation = {'version': 1, 'source_sha': SOURCE,
                     'binding': control.binding(original)}
        proof = operation | {'route': 'renovate'}
        api = Mock(spec=control.API)
        def call(path):
            if path.endswith('/pulls/4'):
                return later
            if path.endswith('/pulls/3'):
                return original
            if path.endswith('/actions/runs/10'):
                return native
            raise AssertionError(path)
        def pages(path, key=None):
            if '/runs?head_sha=' in path:
                return [native]
            if path.endswith('/runs/10/artifacts'):
                return [{'name': 'control-operation-1', 'expired': False}]
            raise AssertionError(path)
        api.call.side_effect, api.pages.side_effect = call, pages
        return api, original, later, native, operation, proof

    def artifacts(self, operation, proof):
        return patch.object(control, 'artifact_record', side_effect=lambda _api, _repo, _run, _name, filename:
                            operation if filename == 'control-operation.json' else proof)

    def test_later_same_branch_locator_retains_original_native_proof(self):
        api, original, _, native, operation, proof = self.fixture()
        with self.artifacts(operation, proof), patch.object(control, 'native_jobs', return_value=[
                {'id': 103, 'name': 'Current revision review', 'conclusion': 'success'}]):
            actual = control.check_native_control(api, REPO, original, {'accepted_sources': [SOURCE]})
        self.assertEqual((10, 1, 'renovate'), (actual['run'], actual['attempt'], actual['route']))
        self.assertEqual(control.digest(proof), actual['proof_sha256'])
        # Initial and warm locator authentication only. Final generation selection
        # remains the final I/O and uses the authenticated exact locator snapshot.
        self.assertEqual(2, sum(c.args[0].endswith('/pulls/4') for c in api.call.call_args_list))
        self.assertEqual(native['head_sha'], original['head']['sha'])

    def test_unmerged_subject_never_uses_foreign_locator(self):
        api, original, _, native, operation, proof = self.fixture()
        original.update(state='open', merged=False)
        with self.artifacts(operation, proof):
            self.assertEqual([], control.ingress_candidates(api, REPO, original, [SOURCE], [native], {}))
        api.call.assert_not_called()

    def test_ambiguous_or_nonlater_locator_is_rejected(self):
        for change in ('multiple', 'original-number', 'missing-number', 'boolean-number'):
            api, original, _, native, operation, proof = self.fixture()
            if change == 'multiple':
                native['pull_requests'] *= 2
            else:
                native['pull_requests'][0]['number'] = {'original-number': 3,
                    'missing-number': None, 'boolean-number': True}[change]
            with self.subTest(change=change), self.artifacts(operation, proof):
                if change == 'original-number':
                    self.assertEqual([], control.ingress_candidates(api, REPO, original, [SOURCE], [native], {}))
                else:
                    with self.assertRaises(control.ControlError):
                        control.ingress_candidates(api, REPO, original, [SOURCE], [native], {})

    def test_later_pr_metadata_must_authenticate_chronology_author_and_tuple(self):
        for change in ('actor', 'number', 'before', 'same-second', 'ambiguous-second',
                       'missing-time', 'fork', 'other-base-repo', 'branch', 'base-ref',
                       'head-id', 'base-id', 'same-head', 'head-sha', 'base-sha'):
            api, original, later, native, operation, proof = self.fixture()
            if change == 'actor': later['user']['id'] += 1
            elif change == 'number': later['number'] = 9
            elif change in ('before', 'same-second', 'ambiguous-second', 'missing-time'):
                later['created_at'] = {'before': '2026-10-23T16:20:36Z',
                    'same-second': original['merged_at'], 'ambiguous-second': '2026-10-23T16:20:38Z',
                    'missing-time': None}[change]
            elif change == 'fork': later['head']['repo']['full_name'] = 'foreign/repository'
            elif change == 'other-base-repo': later['base']['repo']['full_name'] = 'foreign/repository'
            elif change == 'branch': later['head']['ref'] = 'other-branch'
            elif change == 'base-ref': later['base']['ref'] = 'main'
            elif change == 'head-id': later['head']['repo']['id'] = 8
            elif change == 'base-id': later['base']['repo']['id'] = 8
            elif change == 'same-head':
                later['head']['sha'] = original['head']['sha']
                native['pull_requests'][0]['head']['sha'] = original['head']['sha']
            elif change == 'head-sha': later['head']['sha'] = '1' * 40
            elif change == 'base-sha': later['base']['sha'] = '1' * 40
            with self.subTest(change=change), self.artifacts(operation, proof):
                if change == 'same-head':
                    self.assertEqual([], control.ingress_candidates(api, REPO, original, [SOURCE], [native], {}))
                else:
                    with self.assertRaises(control.ControlError):
                        control.ingress_candidates(api, REPO, original, [SOURCE], [native], {})

    def test_original_operation_source_and_tuple_are_still_mandatory(self):
        for change in ('source', 'number', 'base', 'head', 'author'):
            api, original, _, native, operation, proof = self.fixture()
            if change == 'source': operation['source_sha'] = '0' * 40
            else:
                operation['binding'][change] = {'number': 99, 'base': '0' * 40,
                    'head': '0' * 40, 'author': ['other', 1, 'User']}[change]
            with self.subTest(change=change), self.artifacts(operation, proof):
                self.assertEqual([], control.ingress_candidates(api, REPO, original, [SOURCE], [native], {}))

    def test_proof_cannot_bind_the_later_pr_instead(self):
        api, original, later, _, operation, proof = self.fixture()
        proof['binding'] = control.binding(later)
        with self.artifacts(operation, proof), patch.object(control, 'native_jobs', return_value=[
                {'id': 103, 'name': 'Current revision review', 'conclusion': 'success'}]), \
                self.assertRaisesRegex(control.ControlError, 'ingress-protected-proof-binding'):
            control.check_native_control(api, REPO, original, {'accepted_sources': [SOURCE]})

    def test_final_locator_change_fails_without_any_late_io(self):
        api, original, _, native, operation, proof = self.fixture()
        changed = copy.deepcopy(native)
        changed['pull_requests'][0]['head']['sha'] = '2' * 40
        pages = api.pages.side_effect
        reads = {'count': 0}
        def snapshots(path, key=None):
            if '/runs?head_sha=' in path:
                reads['count'] += 1
                return [changed if reads['count'] == 3 else native]
            return pages(path, key)
        api.pages.side_effect = snapshots
        with self.artifacts(operation, proof), patch.object(control, 'native_jobs', return_value=[
                {'id': 103, 'name': 'Current revision review', 'conclusion': 'success'}]), \
                self.assertRaisesRegex(control.ControlError, 'ingress-generation-locator-unavailable'):
            control.check_native_control(api, REPO, original, {'accepted_sources': [SOURCE]})
        self.assertEqual(2, sum(c.args[0].endswith('/pulls/4') for c in api.call.call_args_list))

    def test_newer_bound_failed_generation_is_not_hidden_by_older_success(self):
        api, original, _, native, operation, proof = self.fixture()
        newer = native | {'id': 20, 'status': 'in_progress', 'conclusion': None}
        with self.artifacts(operation, proof), patch.object(control, 'operation_record', return_value=operation):
            selected = control.ingress_candidates(api, REPO, original, [SOURCE], [native, newer], {})
        self.assertEqual([newer], selected)

    def direct_then_alias(self, api, original, native, *, missing_operation=False):
        direct = native | {'pull_requests': [{'number': original['number'],
                            'base': original['base'], 'head': original['head']}]}
        pages = api.pages.side_effect
        reads = {'count': 0}
        def snapshots(path, key=None):
            if '/runs?head_sha=' in path:
                reads['count'] += 1
                return [direct if reads['count'] == 1 else native]
            if missing_operation and path.endswith('/artifacts'):
                return []
            return pages(path, key)
        api.pages.side_effect = snapshots

    def test_warm_alias_authenticates_operation_independently_of_direct_binding_cache(self):
        api, original, _, native, operation, proof = self.fixture()
        self.direct_then_alias(api, original, native)
        with self.artifacts(operation, proof) as transport, \
                patch.object(control, 'native_jobs', return_value=[
                    {'id': 103, 'name': 'Current revision review', 'conclusion': 'success'}]):
            self.assertEqual(10, control.check_native_control(
                api, REPO, original, {'accepted_sources': [SOURCE]})['run'])
        self.assertEqual(1, sum(c.args[-1] == 'control-operation.json'
                                for c in transport.call_args_list))

    def test_warm_alias_cannot_use_direct_binding_cache_when_operation_is_missing(self):
        api, original, _, native, operation, proof = self.fixture()
        self.direct_then_alias(api, original, native, missing_operation=True)
        with self.artifacts(operation, proof), \
                patch.object(control, 'native_jobs', return_value=[
                    {'id': 103, 'name': 'Current revision review', 'conclusion': 'success'}]), \
                self.assertRaisesRegex(control.ControlError, 'protected-operation-missing'):
            control.check_native_control(api, REPO, original, {'accepted_sources': [SOURCE]})

    def test_demonstrably_foreign_operation_is_skipped_before_its_alias_is_validated(self):
        api, original, later, native, operation, proof = self.fixture()
        unrelated = native | {'id': 20}
        foreign = operation | {'binding': operation['binding'] | {'number': 99}}
        pages = api.pages.side_effect
        api.pages.side_effect = lambda path, key=None: [native, unrelated] if '/runs?head_sha=' in path else pages(path, key)
        # This foreign run cannot explain the original subject. Its locator's
        # author would be rejected if it were used as that subject's evidence.
        foreign_locator = copy.deepcopy(later)
        foreign_locator['user']['id'] += 1
        unrelated['pull_requests'] = [copy.deepcopy(native['pull_requests'][0]) | {'number': 5}]
        call = api.call.side_effect
        api.call.side_effect = lambda path: foreign_locator if path.endswith('/pulls/5') else call(path)
        with self.artifacts(operation, proof), \
                patch.object(control, 'operation_record', side_effect=lambda _api, _repo, run:
                             foreign if run['id'] == 20 else operation), \
                patch.object(control, 'native_jobs', return_value=[
                    {'id': 103, 'name': 'Current revision review', 'conclusion': 'success'}]):
            self.assertEqual(10, control.check_native_control(
                api, REPO, original, {'accepted_sources': [SOURCE]})['run'])
        self.assertFalse(any(c.args[0].endswith('/pulls/5') for c in api.call.call_args_list))


if __name__ == '__main__':
    unittest.main()
