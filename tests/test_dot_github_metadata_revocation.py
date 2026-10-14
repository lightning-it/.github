"""Native queue-time metadata context plus immutable protected orchestration."""
import base64
import copy
import json
import unittest
from unittest import mock
import yaml
import test_dot_github_policy_approval as A
M, ROOT, ERROR = A.MODULE, A.ROOT, A.ERROR

class MetadataControllerTests(unittest.TestCase):
    def setUp(self):
        fixture = A.ReuseTests(); fixture.setUp()
        self.value, self.run = fixture.value, fixture.run
        self.doc = yaml.safe_load((ROOT / M.WORKFLOW).read_text())
        self.candidate = copy.deepcopy(self.doc)
    def client(self):
        owner = self
        class Client:
            def get(self, path):
                doc = owner.candidate if path.endswith(owner.value['head']) else owner.doc
                payload = yaml.safe_dump(doc).encode()
                return {'type': 'file', 'encoding': 'base64', 'sha': 'e'*40,
                        'size': len(payload), 'content': base64.b64encode(payload).decode()}
        return Client()
    def test_same_protected_workflow_accepts_and_job_changes_require_staged_source_transition(self):
        M.metadata_controller(self.client(), self.value)
        self.candidate['jobs']['approve']['steps'][-1]['name'] = 'Reword trusted human step'
        with self.assertRaises(ERROR): M.metadata_controller(self.client(), self.value)
    def test_candidate_metadata_code_token_event_coverage_or_global_shell_cannot_replace_main(self):
        variants = []
        d = copy.deepcopy(self.doc); d['jobs']['metadata']['steps'][-1]['run'] = 'echo forged'; variants.append(d)
        d = copy.deepcopy(self.doc); d['defaults'] = {'run': {'shell': 'custom {0}'}}; variants.append(d)
        d = copy.deepcopy(self.doc); d['env']['GH_TOKEN'] = 'candidate token'; variants.append(d)
        d = copy.deepcopy(self.doc); d[True]['pull_request']['types'] = ['edited']; variants.append(d)
        d = copy.deepcopy(self.doc); d['jobs']['extra'] = d['jobs']['metadata']; variants.append(d)
        d = copy.deepcopy(self.doc); d['jobs']['approve']['name'] = M.METADATA_JOB; variants.append(d)
        for d in variants:
            self.candidate = d
            with self.subTest(doc=d), self.assertRaises(ERROR): M.metadata_controller(self.client(), self.value)
    def test_all_target_job_execution_fields_are_bound_to_main(self):
        for job in ('preflight', 'approve', 'verify-dot-github-current-revision'):
            variants = []
            d = copy.deepcopy(self.doc); d['jobs'][job]['if'] = 'always()'; variants.append(d)
            d = copy.deepcopy(self.doc); d['jobs'][job]['permissions'] = {'contents': 'write'}; variants.append(d)
            d = copy.deepcopy(self.doc); d['jobs'][job]['runs-on'] = 'candidate-runner'; variants.append(d)
            d = copy.deepcopy(self.doc); d['jobs'][job]['steps'][0]['with']['ref'] = self.value['head']; variants.append(d)
            d = copy.deepcopy(self.doc); d['jobs'][job]['steps'][-1]['run'] = 'echo forged'; variants.append(d)
            d = copy.deepcopy(self.doc); d['jobs'][job]['env'] = {'GH_TOKEN': 'candidate-token'}; variants.append(d)
            for candidate in variants:
                self.candidate = candidate
                with self.subTest(job=job, variant=variants.index(candidate)), self.assertRaises(ERROR):
                    M.metadata_controller(self.client(), self.value)
    def test_native_check_is_queued_without_publisher_and_uses_read_only_main(self):
        triggers = self.doc[True]
        self.assertEqual(triggers['pull_request']['types'], ['edited','labeled','unlabeled'])
        self.assertEqual(triggers['pull_request_target']['branches-ignore'], ['**'])
        job = self.doc['jobs']['metadata']
        self.assertEqual(job['name'], "${{ github.event_name == 'pull_request' && 'dot-github / approved metadata' || 'Inactive metadata audit for target event' }}")
        self.assertNotEqual(M.METADATA_JOB, M.INACTIVE_METADATA_JOB)
        self.assertNotIn('needs', job)
        self.assertEqual(job['steps'][0]['with']['ref'], 'refs/heads/main')
        self.assertTrue(job['steps'][-1]['run'].endswith(' audit-metadata'))
        self.assertNotIn('environment', job)
        for role in self.doc['jobs'].values():
            self.assertNotIn('write', role['permissions'].values())

class NativeMetadataAuditTests(unittest.TestCase):
    def setUp(self):
        fixture = A.ReuseTests(); fixture.setUp()
        self.value, self.run = fixture.value, fixture.run
        self.run.update(id=101, event='pull_request')
        self.env = {'GITHUB_EVENT_NAME': 'pull_request'}
        self.client = mock.Mock(); self.client.get.return_value = self.run
    def patches(self):
        return (mock.patch.object(M,'revision',return_value=(self.value,'c'*64)),
                mock.patch.object(M,'metadata_controller'),
                mock.patch.object(M,'reusable_approval',return_value=100),
                mock.patch.object(M.EVIDENCE,'verify'))
    def test_full_audit_reuses_human_but_never_requests_another_approval(self):
        from contextlib import ExitStack
        with ExitStack() as stack:
            for patch in self.patches(): stack.enter_context(patch)
            with mock.patch.object(M, 'native_approval') as human, mock.patch.object(M.subprocess, 'run') as write:
                M.audit_metadata(self.client,self.env,101,attempts=1,sleep=lambda _:None)
                human.assert_not_called(); write.assert_not_called()
                M.EVIDENCE.verify.assert_called_once()
    def test_missing_or_changed_approval_and_wrong_native_run_block(self):
        from contextlib import ExitStack
        for problem in ('missing','source','run'):
            with ExitStack() as stack:
                for patch in self.patches(): stack.enter_context(patch)
                if problem=='missing': M.reusable_approval.return_value=None
                if problem=='source': M.revision.side_effect=[(self.value,'c'*64),(self.value,'d'*64)]
                if problem=='run': self.run['head_sha']='d'*40
                with self.subTest(problem=problem), self.assertRaises(ERROR):
                    M.audit_metadata(self.client,self.env,101,attempts=1,sleep=lambda _:None)
