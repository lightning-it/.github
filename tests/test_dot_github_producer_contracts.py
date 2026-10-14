"""Current protected publisher routes and full promotion acceptance/rejection."""

import copy
import importlib.util
import json
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location('route_evidence', Path(__file__).resolve().parents[1] /
                                            'scripts/verify-dot-github-current-revision.py')
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)
BASE, HEAD = 'a' * 40, 'b' * 40
API = 'https://api.github.com/repos/' + M.TARGET_REPOSITORY
WEB = 'https://github.com/' + M.TARGET_REPOSITORY
STAMP = '2026-10-14T03:00:00Z'


class PromotionClient:
    api_url = 'https://api.github.com'

    def __init__(self):
        repo = {'id': 1112629689, 'name': '.github', 'full_name': M.TARGET_REPOSITORY,
                'url': API, 'owner': {'login': 'lightning-it'}}
        self.pr = {'number': 4, 'state': 'open', 'draft': False,
                   'title': M.PROMOTION_TITLE, 'body': '', 'labels': [],
                   'base': {'sha': BASE, 'ref': 'main', 'repo': repo},
                   'head': {'sha': HEAD, 'ref': 'develop', 'repo': repo},
                   'user': {'login': M.RELEASE_APP_LOGIN, 'id': M.RELEASE_APP_ID, 'type': 'Bot'}}
        self.run = {'id': 77, 'event': 'pull_request_target', 'path': M.TARGET_VERIFIER_PATH,
                    'status': 'completed', 'conclusion': 'success', 'head_sha': HEAD,
                    'head_branch': 'develop', 'run_attempt': 1, 'workflow_id': 9,
                    'workflow_url': API + '/actions/workflows/9', 'html_url': WEB + '/actions/runs/77',
                    'display_title': f'Protected current revision PR #4 opened {HEAD}',
                    'actor': {'login': M.RELEASE_APP_LOGIN},
                    'repository': repo, 'head_repository': repo,
                    'triggering_actor': {'login': M.RELEASE_APP_LOGIN}, 'created_at': STAMP,
                    'pull_requests': [{'number': 4, 'url': API + '/pulls/4',
                                       'base': self.pr['base'], 'head': self.pr['head']}]}
        self.check = {'id': 51, 'name': M.TARGET_VERIFIER_NAME, 'head_sha': HEAD,
                      'status': 'completed', 'conclusion': 'success',
                      'app': {'id': 15368, 'slug': 'github-actions'},
                      'details_url': WEB + '/actions/runs/77/job/51'}
        self.jobs = [{'id': i, 'name': name, 'run_id': 77, 'head_sha': HEAD,
                      'run_attempt': 1, 'status': 'completed', 'conclusion': 'success'}
                     for i, name in ((51, M.TARGET_VERIFIER_NAME), (52, M.PROMOTION_VERIFIER_NAME))]
        self.workflow = {'id': 9, 'path': M.TARGET_VERIFIER_PATH, 'state': 'active'}
        self.metadata = None
        self.source_reads = 0
        self.source_drift = False
        self.checks = None

    def metadata_revision(self, number):
        return self.metadata

    def get(self, path):
        if path == 'repos/' + M.TARGET_REPOSITORY:
            return {'full_name': M.TARGET_REPOSITORY, 'visibility': 'public', 'default_branch': 'develop',
                    'archived': False, 'disabled': False}
        if path.endswith('/branches/main'):
            self.source_reads += 1
            sha = 'd' * 40 if self.source_drift and self.source_reads > 1 else BASE
            return {'name': 'main', 'protected': True, 'commit': {'sha': sha}}
        if '/compare/' in path:
            return {'status': 'identical', 'ahead_by': 0, 'behind_by': 0,
                    'base_commit': {'sha': BASE}, 'merge_base_commit': {'sha': BASE}}
        if '/contents/' in path:
            return {'type': 'file', 'sha': 'e' * 40}
        if path.endswith('/pulls/4'):
            return copy.deepcopy(self.pr)
        if '/check-runs?' in path:
            checks = self.checks if self.checks is not None else [self.check]
            return {'total_count': len(checks), 'check_runs': copy.deepcopy(checks)}
        if '/actions/runs/' in path and '/jobs?' not in path:
            run = copy.deepcopy(self.run)
            run['id'] = int(path.rsplit('/', 1)[-1])
            return run
        if path.endswith(('/actions/workflows/9', '/actions/workflows/supplementary-current-revision-required.yml')):
            return copy.deepcopy(self.workflow)
        if '/jobs?' in path:
            return {'total_count': len(self.jobs), 'jobs': copy.deepcopy(self.jobs)}
        raise AssertionError(path)

    def verify(self):
        env = {'REPOSITORY': M.TARGET_REPOSITORY, 'PR_NUMBER': '4', 'EVENT_BASE': BASE,
               'EVENT_HEAD': HEAD, 'WORKFLOW_SHA': BASE, 'WORKFLOW_REF': M.SOURCE_WORKFLOW_REF,
               'EVENT_HEAD_REPOSITORY': M.TARGET_REPOSITORY, 'EVENT_HEAD_REPOSITORY_OWNER': 'lightning-it',
               'EVENT_HEAD_REF': self.pr['head']['ref'], 'EVENT_BASE_REF': self.pr['base']['ref'],
               'EVENT_AUTHOR': self.pr['user']['login'], 'EVENT_AUTHOR_TYPE': self.pr['user']['type'],
               'EVENT_SENDER': self.pr['user']['login'], 'EVENT_ACTION': 'opened', 'EVENT_UPDATED_AT': STAMP,
               'EVENT_TITLE_JSON': json.dumps(self.pr['title']), 'EVENT_BODY_JSON': json.dumps(self.pr['body']),
               'EVENT_LABELS_JSON': '[]'}
        M.verify(self, env, attempts=1, sleep=lambda seconds: None)


class PromotionTests(unittest.TestCase):
    def test_full_develop_to_main_branch_accepts_exact_native_evidence(self):
        PromotionClient().verify()

    def test_full_promotion_accepts_required_run_without_deprecated_api_lookup(self):
        client = PromotionClient()
        client.run['workflow_url'] = API + '/actions/required_workflows/9'
        client.workflow['id'] = 19
        client.verify()
        client.workflow['id'] = True
        with self.assertRaises(M.VerificationError):
            client.verify()

    def test_promotion_classifier_and_association_reject_numeric_coercion(self):
        client = PromotionClient()
        client.pr['user']['id'] = float(M.RELEASE_APP_ID)
        self.assertFalse(M.is_aggregated_promotion(client.pr))
        client.run['pull_requests'][0]['number'] = 4.0
        self.assertFalse(M.exact_promotion_run_association(client.run, 4, BASE, HEAD))

    def test_native_workflow_job_association_failure_and_source_drift_are_rejected(self):
        for location, key, bad in (('run', 'head_sha', 'c' * 40), ('run', 'run_attempt', True),
                                    ('run', 'conclusion', 'failure'), ('workflow', 'path', 'wrong.yml'),
                                    ('workflow', 'state', 'disabled_manually'),
                                    ('pr', 'title', 'different promotion')):
            client = PromotionClient()
            getattr(client, location)[key] = bad
            with self.subTest(location=location, key=key), self.assertRaises(M.VerificationError):
                client.verify()
        for field, bad in (('head_sha', 'c' * 40), ('run_attempt', True),
                           ('run_id', 78), ('conclusion', 'failure')):
            for job in (0, 1):
                client = PromotionClient()
                client.jobs[job][field] = bad
                with self.subTest(field=field, job=job), self.assertRaises(M.VerificationError):
                    client.verify()
        client = PromotionClient()
        client.source_drift = True
        with self.assertRaises(M.VerificationError):
            client.verify()

    def test_newest_failed_result_cannot_be_hidden_by_older_success(self):
        client = PromotionClient()
        newer = dict(client.check, id=61, conclusion='failure', details_url=WEB + '/actions/runs/78/job/61')
        client.checks = [newer, client.check]
        with self.assertRaisesRegex(M.VerificationError, 'latest aggregated promotion evidence failed'):
            client.verify()


class OrdinaryClient(PromotionClient):
    def __init__(self, owner_number=4):
        super().__init__()
        self.pr.update(title='feat: ordinary source check', user={'login': 'litroc', 'id': 76040632, 'type': 'User'})
        self.pr['base']['ref'] = 'develop'
        self.pr['head']['ref'] = 'feature'
        self.run.update(head_branch='feature', actor={'login': 'litroc'}, triggering_actor={'login': 'litroc'})
        self.jobs = self.jobs[:1]
        self.check.update(id=17, name=M.RESERVATION_NAME, details_url=WEB + '/runs/17',
                          external_id=f'rep60-required-workflow:v3:77:4:{BASE}:{HEAD}',
                          output={'summary': f'PR #4; base {BASE}; head {HEAD}; producer {WEB}/actions/runs/88.'})
        summary = {'schema': 4, 'pull_request_number': owner_number, 'base_sha': BASE, 'head_sha': HEAD,
                   'controller_sha': BASE, 'producer_run_id': 88, 'run_url': WEB + '/actions/runs/88',
                   'review_path': 'applicable Copilot or governed automation exemption',
                   'pull_request_last_edited_at': None}
        self.neutral = dict(self.check, id=18, name='Current revision review', details_url=WEB + '/runs/18',
                            external_id=f'mlx90-current-revision:copilot:v6:{owner_number}:88:{BASE}:{HEAD}',
                            output={'title': 'Current revision review passed', 'summary': json.dumps(summary)})
        self.owner = copy.deepcopy(self.pr)
        self.owner.update(number=owner_number, state='closed' if owner_number != 4 else 'open', merged_at=None)
        self.owner_reads = 0
        self.owner_drift = False
        self.metadata_reads = 0
        self.metadata_drift = False
        self.reservation_reads = 0
        self.reservation_drift = False

    def metadata_revision(self, number):
        self.metadata_reads += 1
        return STAMP if self.metadata_drift and self.metadata_reads > 1 else None

    def get(self, path):
        if path.endswith('/pulls/3'):
            self.owner_reads += 1
            value = copy.deepcopy(self.owner)
            if self.owner_drift and self.owner_reads > 1:
                value['head']['sha'] = 'c' * 40
            return value
        if '/check-runs?' in path:
            if 'Current%20revision%20review' in path:
                return {'total_count': 1, 'check_runs': [copy.deepcopy(self.neutral)]}
            self.reservation_reads += 1
            value = copy.deepcopy(self.check)
            if self.reservation_drift and self.reservation_reads > 1:
                value['conclusion'] = 'failure'
            return {'total_count': 1, 'check_runs': [value]}
        return super().get(path)


class OrdinaryTests(unittest.TestCase):
    def test_full_ordinary_accepts_authenticated_overlapping_required_workflow(self):
        client = OrdinaryClient()
        client.run['workflow_url'] = API + '/actions/required_workflows/9'
        client.workflow['id'] = 19  # Registered local ID differs from native Required ID.
        client.verify()
        for bad in (API + '/actions/required_workflows/10',
                    'https://untrusted.invalid/actions/required_workflows/9'):
            client.run['workflow_url'] = bad
            with self.subTest(bad=bad), self.assertRaises(M.VerificationError):
                client.verify()
        client.run['workflow_url'] = API + '/actions/required_workflows/9'
        client.workflow['path'] = 'wrong.yml'
        with self.assertRaises(M.VerificationError):
            client.verify()

    def test_established_current_v5_copilot_is_preserved_with_optional_pr_field(self):
        for number_present in (True, False):
            for metadata_present in (True, False):
                client = OrdinaryClient()
                summary = json.loads(client.neutral['output']['summary'])
                if not number_present:
                    del summary['pull_request_number']
                if not metadata_present:
                    del summary['pull_request_last_edited_at']
                client.neutral['output']['summary'] = json.dumps(summary)
                client.neutral['external_id'] = f'mlx90-current-revision:copilot:v5:88:{BASE}:{HEAD}'
                with self.subTest(number=number_present, metadata=metadata_present):
                    client.verify()

    def test_full_ordinary_human_pr_composition(self):
        OrdinaryClient().verify()

    def test_malformed_final_job_and_post_validation_metadata_or_reservation_drift_block(self):
        for field, bad in (('run_id', 78), ('run_attempt', True), ('head_sha', 'c' * 40)):
            client = OrdinaryClient()
            client.jobs[0][field] = bad
            with self.subTest(field=field), self.assertRaises(M.VerificationError):
                client.verify()
        for field in ('metadata_drift', 'reservation_drift'):
            client = OrdinaryClient()
            setattr(client, field, True)
            with self.subTest(field=field), self.assertRaises(M.VerificationError):
                client.verify()

    def test_closed_unmerged_exact_predecessor_review_is_reused(self):
        OrdinaryClient(3).verify()

    def test_owner_actor_revision_state_merge_and_final_drift_are_rejected(self):
        for field, bad in (('state', 'open'), ('merged_at', STAMP), ('draft', True), ('number', 3.0)):
            client = OrdinaryClient(3)
            client.owner[field] = bad
            with self.subTest(field=field), self.assertRaises(M.VerificationError):
                client.verify()
        for container, field, bad in (('user', 'login', 'other'), ('head', 'sha', 'c' * 40),
                                       ('base', 'ref', 'main')):
            client = OrdinaryClient(3)
            client.owner[container][field] = bad
            with self.subTest(container=container, field=field), self.assertRaises(M.VerificationError):
                client.verify()
        client = OrdinaryClient(3)
        client.owner_drift = True
        with self.assertRaises(M.VerificationError):
            client.verify()


class PublisherTests(unittest.TestCase):
    def test_established_v5_ancestry_retains_its_deterministic_proof(self):
        main = 'c' * 40
        client, summary, reservation = self.fixture('managed-sync')
        client.pr['head']['ref'] = f'backmerge/github-{main[:12]}-{BASE[:12]}-main'
        client.pr['title'] = f'chore(governance): record main ancestry before {main[:12]}'
        summary['review_path'] = M.ANCESTRY_REVIEW_PATH
        client.check['external_id'] = f'mlx90-current-revision:ancestry-backmerge:v5:88:{BASE}:{HEAD}'
        client.check['output']['summary'] = json.dumps(summary)
        client.check['output']['title'] = 'Current revision deterministic exemption passed'
        import base64
        proof = json.dumps({'schema_version': 1, 'repository': M.TARGET_REPOSITORY, 'main_sha': main,
                            'develop_parent_sha': BASE, 'purpose': 'Bind the reviewed main ancestry backmerge.'}).encode()
        read = client.get
        def ancestry(path):
            if path.endswith('/branches/main'):
                return {'name': 'main', 'protected': True, 'commit': {'sha': main}}
            if '/git/commits/' in path:
                return {'sha': HEAD, 'parents': [{'sha': BASE}, {'sha': main}]}
            if '/compare/' in path:
                return {'merge_base_commit': {'sha': BASE}, 'files': [
                    {'filename': '.lit/main-ancestry.json', 'status': 'added'}]}
            if '/contents/.lit/main-ancestry.json' in path:
                return {'type': 'file', 'encoding': 'base64', 'size': len(proof),
                        'content': base64.b64encode(proof).decode()}
            return read(path)
        from unittest import mock
        with mock.patch.object(client, 'get', side_effect=ancestry):
            self.validate(client, reservation)
            client.pr['head']['ref'] = 'different'
            with self.assertRaises(M.VerificationError):
                self.validate(client, reservation)

    def fixture(self, kind):
        client = PromotionClient()
        client.pr['base']['ref'] = 'develop'
        client.pr['head']['ref'] = 'feature'
        client.pr['_metadata_revision'] = None
        run_url = WEB + '/actions/runs/88'
        summary = {'schema': 4, 'pull_request_number': 4, 'base_sha': BASE, 'head_sha': HEAD,
                   'producer_run_id': 88, 'run_url': run_url}
        if kind == 'managed-sync':
            client.pr['user'] = {'login': M.ANCESTRY_APP_LOGIN, 'id': M.ANCESTRY_APP_ID, 'type': 'Bot'}
            summary.update(controller_sha=BASE,
                           review_path='deterministic provenance-bound managed distribution exemption')
            external = f'mlx90-current-revision:managed-sync:v6:4:88:{BASE}:{HEAD}'
            title = 'Current revision managed distribution exemption passed'
        else:
            summary.update(workflow_sha=BASE, merge_base_sha='c' * 40, integration_tree_sha='d' * 40,
                           diff_sha256='e' * 64, input_sha256='f' * 64)
            external = 'mlx90-current-revision:v4:88:' + 'f' * 64
            title = 'Protected Exact-Revision Codex review passed'
            client.run.update(id=88, event='workflow_dispatch', head_branch='develop', head_sha=BASE,
                              path='.github/workflows/release-bot-exact-head-review.yml',
                              html_url=run_url, display_title=f'Exact-Revision Codex PR #4 {BASE}..{HEAD}',
                              actor={'login': M.RELEASE_APP_LOGIN, 'id': M.RELEASE_APP_ID, 'type': 'Bot'},
                              triggering_actor={'login': M.RELEASE_APP_LOGIN, 'id': M.RELEASE_APP_ID, 'type': 'Bot'})
            client.workflow['path'] = client.run['path']
            client.jobs = [{'id': 53, 'name': 'Current revision review', 'run_id': 88,
                            'run_attempt': 1, 'head_sha': BASE, 'status': 'completed', 'conclusion': 'success'}]
        client.check.update(id=17, name='Current revision review', details_url=WEB + '/runs/17',
                            external_id=external, output={'summary': json.dumps(summary), 'title': title})
        reservation = {'output': {'summary': f'PR #4; base {BASE}; head {HEAD}; producer {run_url}.'}}
        return client, summary, reservation

    def validate(self, client, reservation):
        return M.validate_neutral_metadata(client, reservation, client.pr, 4, BASE, HEAD, 'https://github.com')

    def test_actual_managed_sync_and_release_publisher_schemas_are_accepted(self):
        for kind in ('managed-sync', 'release-app'):
            client, _, reservation = self.fixture(kind)
            with self.subTest(kind=kind):
                self.validate(client, reservation)

    def test_wrong_actor_schema_and_current_revision_hashes_are_rejected(self):
        for kind in ('managed-sync', 'release-app'):
            for field, bad in (('schema', 4.0), ('base_sha', 'c' * 40),
                               ('producer_run_id', True), ('unexpected', 'field')):
                client, summary, reservation = self.fixture(kind)
                summary[field] = bad
                client.check['output']['summary'] = json.dumps(summary)
                with self.subTest(kind=kind, field=field), self.assertRaises(M.VerificationError):
                    self.validate(client, reservation)
            client, _, reservation = self.fixture(kind)
            client.pr['user']['id'] = float(client.pr['user']['id'])
            with self.assertRaises(M.VerificationError):
                self.validate(client, reservation)

    def test_release_review_job_can_finish_before_its_recovery_caller(self):
        client, _, reservation = self.fixture('release-app')
        client.run.update(status='in_progress', conclusion=None)
        self.validate(client, reservation)
        client.jobs[0]['conclusion'] = 'failure'
        with self.assertRaises(M.VerificationError):
            self.validate(client, reservation)
