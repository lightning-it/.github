"""Native metadata revocation never grants local human approval."""
import copy
import json
import subprocess
import unittest
from unittest import mock
import yaml
import test_dot_github_policy_approval as APPROVAL_TESTS
from test_dot_github_policy_approval import MODULE, ROOT, ERROR

class MetadataRevocationTests(unittest.TestCase):
    def setUp(self):
        fixture = APPROVAL_TESTS.ReuseTests()
        fixture.setUp()
        self.value, self.run = fixture.value, fixture.run
        self.local = copy.deepcopy(self.run)
        self.local.update(workflow_url=self.local['workflow_url'].replace('/required_workflows/', '/workflows/'),
                          display_title=f"Cross-protect .github PR #4 edited {self.value['head']}")
        self.pr = {'number': 4, 'title': 'changed after approval', 'body': 'changed body',
                   'base': {'ref': 'develop', 'repo': {'id': MODULE.REPOSITORY_ID}},
                   'head': {'sha': self.value['head'], 'ref': 'feature', 'repo': {'id': MODULE.REPOSITORY_ID}}}
        self.env = {'REPOSITORY': MODULE.REPOSITORY, 'EVENT_ACTION': 'edited',
                    'PR_NUMBER': '4', 'EVENT_HEAD': self.value['head'],
                    'WORKFLOW_SHA': self.value['source'], 'WORKFLOW_REF': MODULE.EVIDENCE.SOURCE_WORKFLOW_REF}
        self.posts = []
    def client(self, local=False):
        owner = self
        class Client:
            api_url = 'https://api.github.com'
            def get(self, path):
                if path == 'repos/' + MODULE.REPOSITORY:
                    return {'full_name': MODULE.REPOSITORY, 'visibility': 'public', 'archived': False, 'disabled': False}
                if path.endswith('/branches/main'):
                    return {'name': 'main', 'protected': True, 'commit': {'sha': owner.value['source']}}
                if '/compare/' in path:
                    return {'base_commit': {'sha': owner.value['source']}, 'merge_base_commit': {'sha': owner.value['source']},
                            'status': 'identical', 'ahead_by': 0, 'behind_by': 0}
                if '/contents/' in path: return {'type': 'file', 'sha': 'e' * 40}
                if path.endswith('/pulls/4'): return copy.deepcopy(owner.pr)
                if path.endswith('/actions/runs/100'): return copy.deepcopy(owner.local if local else owner.run)
                if path.endswith('/actions/workflows/2'): return {'id': 2, 'path': MODULE.WORKFLOW, 'state': 'active'}
                raise AssertionError(path)
        return Client()
    def post(self, argv, **kwargs):
        self.assertEqual(argv, ['gh', 'api', '--method', 'POST', 'repos/' + MODULE.REPOSITORY + '/check-runs', '--input', '-'])
        self.assertEqual(kwargs['timeout'], 30)
        payload = json.loads(kwargs['input']); self.posts.append(payload)
        return subprocess.CompletedProcess(argv, 0, json.dumps(dict(payload, app={'id': 15368})).encode(), b'')
    def test_title_body_and_labels_only_revoke_exact_head(self):
        for action in ('edited', 'labeled', 'unlabeled'):
            self.local['display_title'] = f"Cross-protect .github PR #4 {action} {self.value['head']}"
            with mock.patch.object(MODULE.subprocess, 'run', side_effect=self.post):
                MODULE.invalidate_metadata(self.client(True), dict(self.env, EVENT_ACTION=action), 100)
            self.assertEqual(self.posts[-1]['conclusion'], 'failure')
            self.assertEqual(self.posts[-1]['head_sha'], self.value['head'])
            self.assertEqual(self.posts[-1]['name'], MODULE.METADATA_CHECK)
    def test_old_head_foreign_source_and_non_metadata_event_never_publish(self):
        for name, value in (('EVENT_HEAD', 'd'*40), ('EVENT_ACTION', 'opened'), ('WORKFLOW_SHA', 'd'*40), ('REPOSITORY', 'lightning-it/private')):
            with mock.patch.object(MODULE.subprocess, 'run') as post, self.assertRaises(ERROR):
                MODULE.invalidate_metadata(self.client(True), dict(self.env, **{name: value}), 100)
            post.assert_not_called()
        self.local['workflow_url'] = self.local['workflow_url'].replace('api.github.com', 'untrusted.invalid')
        with mock.patch.object(MODULE.subprocess, 'run') as post, self.assertRaises(ERROR):
            MODULE.invalidate_metadata(self.client(True), self.env, 100)
        post.assert_not_called()
    def test_only_authenticated_required_gate_can_publish_success(self):
        with mock.patch.object(MODULE.subprocess, 'run', side_effect=self.post):
            MODULE.publish_metadata_check(self.client(), self.value, 100, approved=True)
        self.assertEqual(self.posts[-1]['conclusion'], 'success')
        with mock.patch.object(MODULE.subprocess, 'run') as post, self.assertRaises(ERROR):
            MODULE.publish_metadata_check(self.client(True), self.value, 100, approved=True)
        post.assert_not_called()
    def test_local_metadata_yaml_cannot_enter_admission(self):
        doc = yaml.safe_load((ROOT / MODULE.WORKFLOW).read_text())
        self.assertEqual(doc['on' if 'on' in doc else True]['pull_request_target']['types'], ['edited', 'labeled', 'unlabeled'])
        job = doc['jobs']['preflight']; step = next(s for s in job['steps'] if 'Revoke approval' in s['name'])
        self.assertEqual(step['env']['WORKFLOW_REF'], MODULE.EVIDENCE.SOURCE_WORKFLOW_REF)
        self.assertEqual(step['env']['WORKFLOW_SHA'], '${{ steps.source.outputs.commit }}')
        self.assertTrue(step['run'].endswith(' invalidate'))
        self.assertNotIn('checks', doc['jobs']['approve']['permissions'])
