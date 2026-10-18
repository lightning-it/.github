"""Closed Security profiles use independent native and real data-only Git proof, never model calls."""
import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import workflow_control as core
import workflow_security_profile as security
import workflow_subject as subjects
import workflow_recovery as recovery

REPO = 'lightning-it/security-fixture'
VERSION, EVIDENCE, DOMAIN = '1.0.1', 'MLX90-FIXTURE-1.0.1', 'fixture/security-v1'
IDENTITY = dict(zip(('login', 'id', 'type'), core.RELEASE))


def moment(delta=0):
    return (datetime.now(UTC) + timedelta(minutes=delta)).strftime('%Y-%m-%dT%H:%M:%SZ')


def git_environment():
    environment = os.environ.copy()
    for key in ('GIT_DIR', 'GIT_COMMON_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE'):
        environment.pop(key, None)
    return environment


def git(root, *args, binary=False):
    payload = subprocess.check_output(['git', '-C', str(root), *args], env=git_environment())
    return payload if binary else payload.decode().strip()


class SecurityProfileTests(unittest.TestCase):
    def setUp(self):
        # The integration gate supplies its own worktree context. Fixtures and
        # the data-only helpers they exercise own independent repositories.
        context = patch.dict(os.environ, git_environment(), clear=True)
        context.start()
        self.addCleanup(context.stop)
        temp = tempfile.TemporaryDirectory(dir=os.environ.get('HOME'))
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        git(self.root, 'init', '-q')
        git(self.root, 'config', 'user.name', core.RELEASE[0])
        git(self.root, 'config', 'user.email', f'307565056+{core.RELEASE[0]}@users.noreply.github.com')
        self.files = {'.github/workflows/security-release-intake.yml': b'intake producer\n',
                      '.github/workflows/release-prepare.yml': b'preparation producer\n',
                      'scripts/producer.py': b'# Immutable producer closure.\n'}
        for path, raw in self.files.items(): self.write(path, raw)
        self.write('.lit/security-release-profiles.json', core.canonical({'schemaVersion': 1, 'profiles': {
            DOMAIN: {'description': 'Fixture only', 'releaseEligible': True}}}))
        self.write('galaxy.yml', b'version: 1.0.0\n')
        for path in security.GENERATED - {'galaxy.yml'}: self.write(path, b'{}\n')
        self.commit('Protected base')
        self.original_base = git(self.root, 'rev-parse', 'HEAD')
        self.metadata_path = f'.lit/security-releases/{VERSION}.json'
        self.intake_path = f'.lit/security-release-intakes/{VERSION}.json'
        self.fragment_path = 'changelogs/fragments/security-fixture.yml'
        self.issued, self.expires = moment(-10), moment(60)
        self.metadata = {'schemaVersion': 1, 'evidenceId': EVIDENCE, 'fixedVersion': VERSION,
                         'acceptanceProfile': DOMAIN,
                         'validity': {'notBefore': moment(-60), 'expiresAt': self.expires, 'revoked': False}}
        self.write(self.metadata_path, core.canonical(self.metadata))
        self.write(self.fragment_path, b'security_fixes: [Real security fixture]\n')
        self.commit('Original complete candidate')
        candidate = git(self.root, 'rev-parse', 'HEAD')
        payload = git(self.root, 'diff', '--binary', '--full-index',
            '--no-color', '--no-ext-diff', '--no-textconv', self.original_base, candidate, binary=True)
        request = {'schemaVersion': 2, 'repository': REPO, 'repositoryId': '1234', 'baseSha': self.original_base,
                   'candidateBaseSha': self.original_base, 'candidateHeadSha': candidate,
                   'candidateDiffSha256': 'sha256:' + hashlib.sha256(payload).hexdigest(),
                   'evidenceId': EVIDENCE, 'fixedVersion': VERSION, 'acceptanceProfile': DOMAIN,
                   'event': 'mlx90-security-release', 'humanActions': 0,
                   'metadataSha256': 'sha256:' + self.file_digest(self.metadata_path),
                   'issuedAt': self.issued, 'expiresAt': self.expires}
        chain = {key: request[key] for key in ('repository', 'repositoryId', 'baseSha', 'candidateHeadSha',
                 'candidateDiffSha256', 'evidenceId', 'fixedVersion', 'acceptanceProfile')}
        request['chainId'] = 'sha256:' + core.digest(chain)
        verified = request | {'changedPaths': sorted([self.metadata_path, self.fragment_path]),
                              'changelogFragmentPath': self.fragment_path,
                              'changelogFragmentSha256': 'sha256:' + self.file_digest(self.fragment_path)}
        self.intake = {'schemaVersion': 2, 'chainId': request['chainId'], 'request': request, 'verified': verified,
                      'automation': {'login': core.RELEASE[0], 'accountId': str(core.RELEASE[1]),
                                     'type': core.RELEASE[2], 'slug': 'lightning-it-release-automation'},
                      'controller': {'sourceSha': self.original_base, 'runId': '20', 'runAttempt': '1',
                        'path': '.github/workflows/security-release-intake.yml',
                        'ref': f'{REPO}/.github/workflows/security-release-intake.yml@refs/heads/main',
                        'event': 'workflow_dispatch', 'gitRef': 'refs/heads/main',
                        'actor': core.RELEASE[0], 'triggeringActor': core.RELEASE[0]}}
        git(self.root, 'checkout', '-q', '--detach', self.original_base)
        git(self.root, 'checkout', candidate, '--', self.metadata_path, self.fragment_path)
        self.write(self.intake_path, core.canonical(self.intake))
        self.commit(f'fix(security): {EVIDENCE}')
        self.base, self.head = self.original_base, git(self.root, 'rev-parse', 'HEAD')
        self.configure('intake', 20)

    def write(self, path, raw):
        destination = self.root / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(raw)

    def commit(self, message):
        git(self.root, 'add', '-A'); git(self.root, 'commit', '-q', '-m', message)

    def file_digest(self, path):
        return hashlib.sha256((self.root / path).read_bytes()).hexdigest()

    def configure(self, kind, run_id):
        workflow = '.github/workflows/' + ('security-release-intake.yml' if kind == 'intake' else 'release-prepare.yml')
        raw = self.files[workflow]
        self.entry = {'id': f'fixture-{kind}', 'repository': REPO, 'repository_id': 1234, 'kind': kind,
                      'source_sha': self.original_base, 'workflow': workflow,
                      'workflow_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest(),
                      'job': 'Qualified Security producer', 'files': {path: hashlib.sha256(raw).hexdigest()
                        for path, raw in self.files.items()}, 'acceptance_profiles': [DOMAIN],
                      'environment': 'mlx90-security-promotion-authorization', 'expires_at': moment(120), 'revoked': False}
        self.pull = {'number': 3 if kind == 'intake' else 4, 'state': 'open', 'draft': False, 'title': 'Security fix',
            'body': security.MARKER + json.dumps({'producer': self.entry['id'], 'run': run_id, 'attempt': 1}) + ' -->',
            'labels': [], 'user': IDENTITY,
            'base': {'sha': self.base, 'ref': 'main', 'repo': {'full_name': REPO}},
            'head': {'sha': self.head, 'ref': f'security-release/{EVIDENCE}' if kind == 'intake' else f'release/v{VERSION}',
                     'repo': {'full_name': REPO}}}
        self.run = {'id': run_id, 'run_attempt': 1, 'head_sha': self.base, 'head_branch': 'main', 'workflow_id': 9,
                    'path': workflow, 'event': 'workflow_dispatch' if kind == 'intake' else 'push',
                    'repository': {'id': 1234}, 'head_repository': {'id': 1234}, 'actor': IDENTITY,
                    'triggering_actor': IDENTITY, 'status': 'completed', 'conclusion': 'success'}
        self.job = {'id': 41, 'run_id': run_id, 'name': self.entry['job'], 'status': 'completed',
                    'conclusion': 'success', 'completed_at': moment(-1)}
        materials = [{'role': 'receipt', 'at': 'head', 'path': self.intake_path if kind == 'intake'
                     else 'changelogs/release-preparation.json'},
                     {'role': 'metadata', 'at': 'head', 'path': self.metadata_path},
                     {'role': 'fragment', 'at': 'head' if kind == 'intake' else 'base', 'path': self.fragment_path}]
        if kind == 'preparation': materials.append({'role': 'intake', 'at': 'base', 'path': self.intake_path})
        for item in materials:
            revision = self.head if item['at'] == 'head' else self.base
            raw = git(self.root, 'show', f"{revision}:{item['path']}", binary=True)
            item['sha256'] = hashlib.sha256(raw).hexdigest()
        diff = git(self.root, 'diff', '--binary', '--full-index',
            '--no-color', '--no-ext-diff', '--no-textconv', self.base, self.head, binary=True)
        self.packet = {'version': 1, 'profile': security.PROFILE, 'kind': kind, 'repository': REPO, 'repository_id': 1234,
            'binding': security.subject(self.pull), 'integration_tree': git(self.root, 'rev-parse', f'{self.head}^{{tree}}'),
            'diff_sha256': hashlib.sha256(diff).hexdigest(), 'chain_id': self.intake['chainId'], 'evidence_id': EVIDENCE,
            'fixed_version': VERSION, 'acceptance_profile': DOMAIN, 'issued_at': self.issued, 'expires_at': self.expires,
            'revoked': False, 'producer': {'id': self.entry['id'], 'run': run_id, 'attempt': 1, 'job': 41,
                                         'source_sha': self.base}, 'materials': materials}
        self.api = Mock()
        self.generations, self.jobs = [self.run], [self.job]
        self.environment = {'name': self.entry['environment'], 'can_admins_bypass': False, 'protection_rules': []}
        def call(path, **kwargs):
            if path == f'repos/{REPO}': return {'id': 1234}
            if path.endswith('/branches/main'): return {'protected': True, 'commit': {'sha': self.base}}
            if path.endswith(f'/actions/runs/{run_id}'): return copy.deepcopy(self.run)
            if '/actions/workflows/' in path: return {'id': 9, 'path': self.entry['workflow'], 'state': 'active'}
            if '/compare/' in path: return {'status': 'ahead'}
            if '/environments/' in path: return self.environment
            if path.endswith(f"/pulls/{self.pull['number']}"): return copy.deepcopy(self.pull)
            if path.endswith('/pulls/3') and kind == 'preparation': return copy.deepcopy(self.previous_pull)
            if path.endswith('/actions/runs/200'): return {'id': 200, 'run_attempt': 1}
            raise AssertionError(path)
        def pages(path, key=None):
            if '/jobs' in path: return copy.deepcopy(self.jobs)
            if '/actions/runs?' in path: return copy.deepcopy(self.generations)
            if '/commits/' in path: return [self.previous_pull]
            raise AssertionError(path)
        self.api.call.side_effect = call
        self.api.pages.side_effect = pages
        self.api.file.side_effect = lambda repo, path, revision: self.files[path]

    def fetch(self, objects, repo, *refs):
        self.assertEqual(REPO, repo)
        git(self.root, '--git-dir', str(objects), 'fetch', '--quiet', str(self.root), *refs)

    def artifact(self, api, repo, run, name, filename):
        if filename == security.FILENAME: return copy.deepcopy(self.packet)
        return {'route': 'codex', 'security': {'profile': security.PROFILE, 'kind': 'intake',
                                            'binding': security.subject(self.previous_pull)}}

    def authorize(self):
        with patch.object(security, 'registry', return_value=[self.entry]), \
                patch.object(security, 'artifact_record', side_effect=self.artifact), \
                patch.object(subjects, 'fetch_objects', side_effect=self.fetch), \
                patch.object(security, 'check_native_control', return_value={'run': 200, 'attempt': 1}):
            return security.authorize(self.api, REPO, self.pull, {'security_profile': security.PROFILE})

    def make_preparation(self):
        self.previous_pull = copy.deepcopy(self.pull)
        tree = git(self.root, 'rev-parse', f'{self.head}^{{tree}}')
        main = git(self.root, 'commit-tree', tree, '-p', self.original_base, '-p', self.head, '-m', 'Actual intake merge')
        self.previous_pull.update(state='closed', merged=True, merged_at=moment(-5), merge_commit_sha=main)
        self.base = main
        git(self.root, 'checkout', '-q', '--detach', main)
        fragment_digest = self.file_digest(self.fragment_path)
        intake_digest = self.file_digest(self.intake_path)
        self.write('galaxy.yml', b'version: 1.0.1\n')
        for path in security.GENERATED - {'galaxy.yml', 'changelogs/release-preparation.json'}:
            self.write(path, b'Published Security changelog\n')
        (self.root / self.fragment_path).unlink()
        receipt = {'schema_version': 2, 'repository': REPO, 'repository_id': '1234', 'release_mode': 'security',
            'preparer': {'login': core.RELEASE[0], 'account_id': str(core.RELEASE[1]),
                        'email': f'307565056+{core.RELEASE[0]}@users.noreply.github.com'},
            'chain_id': self.intake['chainId'], 'base_sha': main, 'current_version': '1.0.0', 'next_version': VERSION,
            'fragments': [{'path': Path(self.fragment_path).name, 'sha256': fragment_digest}],
            'security': {'evidence_id': EVIDENCE, 'metadata_path': self.metadata_path,
                'metadata_sha256': 'sha256:' + self.file_digest(self.metadata_path), 'intake_receipt_path': self.intake_path,
                'intake_receipt_sha256': 'sha256:' + intake_digest, 'human_actions': 0},
            'workflow': {'path': '.github/workflows/release-prepare.yml', 'source_sha': main, 'run_id': '30',
                'run_attempt': '1', 'ref': f'{REPO}/.github/workflows/release-prepare.yml@refs/heads/main',
                'event': 'push', 'git_ref': 'refs/heads/main', 'actor': core.RELEASE[0]}}
        self.write('changelogs/release-preparation.json', core.canonical(receipt))
        self.commit(f'chore(release): prepare v{VERSION}')
        self.head = git(self.root, 'rev-parse', 'HEAD')
        self.configure('preparation', 30)

    def test_source_registry_is_empty_and_consumer_cannot_admit_a_producer(self):
        self.assertEqual([], security.registry())
        self.assertIsNone(security.validate_policy({}, REPO))
        for policy in ({'security_profile': security.PROFILE}, {'security_profile': {'producer': self.entry}}):
            with self.subTest(policy=policy), self.assertRaises(core.ControlError): security.validate_policy(policy, REPO)
        with self.assertRaises(core.ControlError):
            security.authorize(self.api, REPO, self.pull, {'security_profile': security.PROFILE})
        self.api.call.assert_not_called()

    def test_git_fixture_binary_and_text_reads_ignore_foreign_worktree_context(self):
        foreign = {'GIT_DIR': '/not-this-fixture/repository.git', 'GIT_COMMON_DIR': '/not-this-fixture/common',
                   'GIT_WORK_TREE': '/not-this-fixture/worktree', 'GIT_INDEX_FILE': '/not-this-fixture/index'}
        with patch.dict(os.environ, foreign):
            self.assertEqual(self.head, git(self.root, 'rev-parse', 'HEAD'))
            self.assertEqual((self.root / self.metadata_path).read_bytes(),
                             git(self.root, 'show', f'{self.head}:{self.metadata_path}', binary=True))
            self.assertEqual(foreign, {key: os.environ[key] for key in foreign})

    def test_both_real_git_shapes_require_native_proof_and_keep_full_codex_route(self):
        for kind in ('intake', 'preparation'):
            if kind == 'preparation': self.make_preparation()
            with self.subTest(kind=kind):
                evidence = self.authorize()
                self.assertEqual('codex', core.classify(self.pull, REPO, security=evidence))
                self.assertEqual(self.packet['binding'], evidence.summary()['binding'])
                with self.assertRaises(core.ControlError): core.classify(self.pull, REPO)
                with self.assertRaises(core.ControlError): core.classify(self.pull, REPO, security=evidence.summary())
        self.assertFalse(any(call.kwargs.get('method') == 'POST' for call in self.api.call.call_args_list))

    def test_native_run_job_registry_and_environment_forgery_are_closed(self):
        for defect in ('actor', 'repository', 'workflow', 'failed', 'pending', 'attempt', 'job', 'duplicate-job',
                       'generation', 'generation-failed', 'code', 'revoked', 'expired', 'environment'):
            original = copy.deepcopy((self.run, self.job, self.entry, self.files, self.environment))
            if defect == 'actor': self.run['actor'] = IDENTITY | {'id': 1}
            elif defect == 'repository': self.run['repository']['id'] = 999
            elif defect == 'workflow': self.run['path'] = '.github/workflows/fake.yml'
            elif defect == 'failed': self.run['conclusion'] = 'failure'
            elif defect == 'pending': self.run.update(status='in_progress', conclusion=None)
            elif defect == 'attempt': self.run['run_attempt'] = 2
            elif defect == 'job': self.job['id'] = 999
            elif defect == 'duplicate-job': self.jobs = [self.job, self.job]
            elif defect == 'generation': self.generations = [self.run, self.run | {'id': 999}]
            elif defect == 'generation-failed': self.generations = [self.run | {'id': 999, 'conclusion': 'failure'}]
            elif defect == 'code': self.files['scripts/producer.py'] = b'Unregistered code\n'
            elif defect == 'revoked': self.entry['revoked'] = True
            elif defect == 'expired': self.entry['expires_at'] = moment(-1)
            else: self.environment['protection_rules'] = [{'type': 'required_reviewers'}]
            with self.subTest(defect=defect), self.assertRaises(core.ControlError): self.authorize()
            self.run, self.job, self.entry, self.files, self.environment = original
            self.generations, self.jobs = [self.run], [self.job]
            self.api.file.side_effect = lambda repo, path, revision: self.files[path]

    def test_packet_and_material_tampering_unknown_profiles_and_expiry_are_closed(self):
        valid = copy.deepcopy(self.packet)
        for field, value in (('binding', valid['binding'] | {'head': 'f' * 40}), ('integration_tree', 'f' * 40),
                ('diff_sha256', '0' * 64), ('chain_id', 'sha256:' + '0' * 64), ('fixed_version', '0.0.1'),
                ('acceptance_profile', 'unknown'), ('revoked', True), ('expires_at', moment(-1)),
                ('materials', valid['materials'] + [valid['materials'][0]])):
            self.packet = copy.deepcopy(valid); self.packet[field] = value
            with self.subTest(field=field), self.assertRaises(core.ControlError): self.authorize()
        self.packet = valid
        self.packet['materials'][0]['sha256'] = '0' * 64
        with self.assertRaises(core.ControlError): self.authorize()

    def test_mode_drift_and_unreviewed_authority_changes_are_closed(self):
        git(self.root, 'update-index', '--chmod=+x', self.metadata_path)
        git(self.root, 'commit', '-q', '--amend', '--no-edit')
        self.head = git(self.root, 'rev-parse', 'HEAD')
        self.configure('intake', 20)
        with self.assertRaisesRegex(core.ControlError, 'material-mode'): self.authorize()

    def test_missing_or_retrospective_prior_intake_acceptance_cannot_authorize_preparation(self):
        self.make_preparation()
        with patch.object(security, 'registry', return_value=[self.entry]), \
                patch.object(security, 'artifact_record', side_effect=lambda *args: copy.deepcopy(self.packet)
                             if args[-1] == security.FILENAME else {'route': 'codex'}), \
                patch.object(subjects, 'fetch_objects', side_effect=self.fetch), \
                patch.object(security, 'check_native_control', return_value={'run': 200, 'attempt': 1}), \
                self.assertRaisesRegex(core.ControlError, 'prior-intake-independent-proof'):
            security.authorize(self.api, REPO, self.pull, {'security_profile': security.PROFILE})

    def test_final_native_reenumeration_rejects_generation_started_during_evidence_reads(self):
        original = self.api.call.side_effect
        def read(path, **kwargs):
            if '/pulls/' in path: self.generations = [self.run, self.run | {'id': 999}]
            return original(path, **kwargs)
        self.api.call.side_effect = read
        with self.assertRaisesRegex(core.ControlError, 'generation'): self.authorize()

    def test_duplicate_json_and_noncanonical_packet_never_pass_decoder(self):
        with self.assertRaises(core.ControlError): security.decode(b'{"version":1,"version":1}')
        with self.assertRaises(core.ControlError): security.decode(b'{ "version": 1 }', canonical_required=True)
        self.assertEqual(self.packet, security.decode(core.canonical(self.packet), canonical_required=True))

    def test_security_decoder_rejects_nonfinite_constants_and_numeric_overflow_at_any_depth(self):
        for token in (b'NaN', b'Infinity', b'-Infinity', b'1e999', b'-1e999'):
            for raw in (token, b'{"nested":[{"value":' + token + b'}]}'):
                for canonical_required in (False, True):
                    with self.subTest(raw=raw, canonical=canonical_required), \
                            self.assertRaisesRegex(core.ControlError, 'security-nonfinite-json'):
                        security.decode(raw, canonical_required=canonical_required, maximum=security.MATERIAL_MAX)
        finite = {'values': [1.5, -0.25, 1e308], 'literal': 'NaN'}
        self.assertEqual(finite, security.decode(core.canonical(finite), canonical_required=True))

    def test_source_registry_rejects_duplicate_ids_missing_bindings_and_unknown_file_paths(self):
        path = self.root / 'source-registry.json'
        valid = copy.deepcopy(self.entry)
        for defect in ('valid', 'duplicate', 'missing', 'path', 'scope'):
            entry = copy.deepcopy(valid)
            if defect == 'missing': del entry['workflow_blob']
            elif defect == 'path': entry['files']['../candidate.py'] = 'a' * 64
            elif defect == 'scope': entry['repository'] = 'outside/repository'
            value = {'version': 1, 'producers': [entry, entry] if defect == 'duplicate' else [entry]}
            path.write_bytes(core.canonical(value))
            with self.subTest(defect=defect), patch.object(security, 'REGISTRY', path):
                if defect == 'valid': self.assertEqual([entry], security.registry())
                else:
                    with self.assertRaises(core.ControlError): security.registry()

    def test_native_artifact_reader_rejects_duplicates_noncanonical_and_oversized_packets(self):
        for raw in (b'{"version":1,"version":1}', b'{ "version": 1 }', b' ' * (core.MAX_OPERATION_BYTES + 1)):
            api = Mock()
            api.pages.return_value = [{'name': 'security-premerge-1', 'expired': False, 'size_in_bytes': 100}]
            def download(command, **kwargs):
                (Path(command[-1]) / security.FILENAME).write_bytes(raw)
                return Mock(returncode=0)
            with self.subTest(size=len(raw)), patch.object(core.subprocess, 'run', side_effect=download), \
                    self.assertRaises((core.ControlError, ValueError)):
                core.artifact_record(api, REPO, self.run, 'security-premerge-1', security.FILENAME)
        api.pages.return_value = [{'name': 'security-premerge-1', 'expired': True}]
        with patch.object(core.subprocess, 'run') as download, self.assertRaises(core.ControlError):
            core.artifact_record(api, REPO, self.run, 'security-premerge-1', security.FILENAME)
        download.assert_not_called()

    def test_security_artifact_requires_exactly_one_regular_file(self):
        for defect in ('none', 'extra-file', 'extra-directory', 'hidden-directory', 'symlink', 'directory', 'wrong-name'):
            api = Mock()
            api.pages.return_value = [{'name': 'security-premerge-1', 'expired': False, 'size_in_bytes': 100}]
            def download(command, **kwargs):
                root = Path(command[-1]); packet = root / security.FILENAME
                if defect == 'symlink': packet.symlink_to(self.root / self.metadata_path)
                elif defect == 'directory': packet.mkdir()
                elif defect == 'wrong-name': (root / 'wrong.json').write_bytes(b'{}')
                else: packet.write_bytes(b'{}')
                if defect == 'extra-file': (root / 'other.json').write_bytes(b'{}')
                elif defect == 'extra-directory': (root / 'other').mkdir()
                elif defect == 'hidden-directory': (root / '.hidden').mkdir()
                return Mock(returncode=0)
            with self.subTest(defect=defect), patch.object(core.subprocess, 'run', side_effect=download):
                if defect == 'none':
                    self.assertEqual({}, core.artifact_record(api, REPO, self.run, 'security-premerge-1', security.FILENAME))
                else:
                    with self.assertRaises((core.ControlError, ValueError)):
                        core.artifact_record(api, REPO, self.run, 'security-premerge-1', security.FILENAME)

    def test_security_artifact_metadata_is_admitted_before_download_only_for_new_packet(self):
        for size in (None, 0, -1, True, 1.5, '100', core.MAX_OPERATION_BYTES + 65537):
            api = Mock()
            api.pages.return_value = [{'name': 'security-premerge-1', 'expired': False, 'size_in_bytes': size}]
            with self.subTest(size=size), patch.object(core.subprocess, 'run') as download, \
                    self.assertRaises(core.ControlError):
                core.artifact_record(api, REPO, self.run, 'security-premerge-1', security.FILENAME)
            download.assert_not_called()
        # Existing artifact behavior is intentionally unchanged, including its
        # separate file bound and acceptance of unrelated extracted entries.
        api.pages.return_value = [{'name': 'control-operation-1', 'expired': False}]
        def legacy_download(command, **kwargs):
            root = Path(command[-1])
            (root / 'control-operation.json').write_bytes(b'{}')
            (root / 'legacy-extra').mkdir()
            return Mock(returncode=0)
        with patch.object(core.subprocess, 'run', side_effect=legacy_download):
            self.assertEqual({}, core.artifact_record(api, REPO, self.run, 'control-operation-1', 'control-operation.json'))
        api.pages.return_value = [{'name': 'security-premerge-1', 'expired': False, 'size_in_bytes': 100}]
        with patch('single_review_resources.wire_limit', return_value=99), \
                patch.object(core.subprocess, 'run') as download, self.assertRaises(core.ControlError):
            core.artifact_record(api, REPO, self.run, 'security-premerge-1', security.FILENAME)
        download.assert_not_called()

    def test_material_reader_accepts_json_above_packet_bound_up_to_one_mib(self):
        for size in (core.MAX_OPERATION_BYTES + 1, 1024 * 1024):
            value = self.metadata | {'padding': ''}
            value['padding'] = 'x' * (size - len(core.canonical(value)))
            raw = core.canonical(value)
            self.assertEqual(size, len(raw))
            self.write(self.metadata_path, raw)
            git(self.root, 'add', self.metadata_path); git(self.root, 'commit', '-q', '--amend', '--no-edit')
            self.head = git(self.root, 'rev-parse', 'HEAD'); self.configure('intake', 20)
            with self.subTest(size=size), patch.object(subjects, 'fetch_objects', side_effect=self.fetch):
                documents, _diff, _changes = security.git_materials(REPO, self.pull, self.packet, self.entry)
                self.assertEqual(value, documents[self.metadata_path])
                with self.assertRaises(core.ControlError): security.decode(raw)

    def test_material_reader_rejects_oversize_before_blob_read_and_detects_size_drift(self):
        for path in (self.fragment_path, self.metadata_path):
            original_raw = (self.root / path).read_bytes()
            self.write(path, b'x' * (1024 * 1024 + 1))
            git(self.root, 'add', path); git(self.root, 'commit', '-q', '--amend', '--no-edit')
            self.head = git(self.root, 'rev-parse', 'HEAD'); self.configure('intake', 20)
            with self.subTest(path=path), patch.object(subjects, 'fetch_objects', side_effect=self.fetch), \
                    patch.object(subjects, 'git', wraps=subjects.git) as reads, \
                    self.assertRaisesRegex(core.ControlError, 'material-size'):
                security.git_materials(REPO, self.pull, self.packet, self.entry)
            oid = git(self.root, 'rev-parse', f'{self.head}:{path}')
            self.assertFalse(any(call.args[1:] == ('cat-file', 'blob', oid) for call in reads.call_args_list))
            self.write(path, original_raw)
            git(self.root, 'add', path); git(self.root, 'commit', '-q', '--amend', '--no-edit')
            self.head = git(self.root, 'rev-parse', 'HEAD'); self.configure('intake', 20)
        original = subjects.git
        def drift(objects, *args, **kwargs):
            value = original(objects, *args, **kwargs)
            return str(int(value) + 1) if args[:2] == ('cat-file', '-s') else value
        with patch.object(subjects, 'fetch_objects', side_effect=self.fetch), \
                patch.object(subjects, 'git', side_effect=drift), \
                self.assertRaisesRegex(core.ControlError, 'material-size-drift'):
            security.git_materials(REPO, self.pull, self.packet, self.entry)

    def test_material_decoder_retains_memory_node_and_depth_admission(self):
        admission = {'max_wire_bytes': 1024 * 1024, 'max_json_nodes': 16384, 'max_json_depth': 64}
        for field, limit, raw in (('max_wire_bytes', 4, b'{"a":0}'),
                                  ('max_json_nodes', 1, b'{"a":0}'),
                                  ('max_json_depth', 1, b'[[0]]')):
            with self.subTest(field=field), patch('single_review_resources.memory_contract',
                    return_value=admission | {field: limit}), self.assertRaises((core.ControlError, ValueError)):
                security.decode(raw, maximum=security.MATERIAL_MAX)

    def test_native_operation_binds_risk_and_missing_evidence_blocks_before_funding(self):
        evidence = self.authorize()
        event_path = self.root / 'event.json'
        event_path.write_bytes(core.canonical({'action': 'opened', 'pull_request': self.pull}))
        native = {'id': 999, 'head_sha': self.head, 'workflow_id': 1,
                  'path': core.WORKFLOW, 'workflow_url': f'https://api.github.com/repos/{REPO}/actions/required_workflows/1'}
        api = Mock(); api.call.return_value = native
        env = {'GITHUB_REPOSITORY': REPO, 'GITHUB_RUN_ID': '999', 'GITHUB_EVENT_PATH': str(event_path),
               'NATIVE_JOB': json.dumps({'workflow_repository': core.SOURCE, 'workflow_file_path': core.WORKFLOW,
                                         'workflow_sha': 'c' * 40, 'check_run_id': 999})}
        old = Path.cwd()
        os.chdir(self.root)
        try:
            with patch.dict(os.environ, env), patch.object(sys, 'argv', ['control', 'classify']), \
                    patch.object(core, 'API', return_value=api), patch.object(core, 'live_pull', return_value=self.pull), \
                    patch.object(core, 'policy', return_value={'security_profile': security.PROFILE}), \
                    patch.object(security, 'authorize', return_value=evidence), patch.object(core, 'output') as output:
                core.main()
                self.assertIn(('route', 'codex'), [call.args for call in output.call_args_list])
                operation = json.loads(Path('control-operation.json').read_bytes())
                self.assertEqual(evidence.summary(), operation['security'])
            with patch.dict(os.environ, env), patch.object(sys, 'argv', ['control', 'reserve-codex']), \
                    patch.object(core, 'API', return_value=api), patch.object(core, 'live_pull', return_value=self.pull), \
                    patch.object(core, 'policy', return_value={'security_profile': security.PROFILE}), \
                    patch.object(security, 'authorize', side_effect=core.ControlError('missing-actual-producer')), \
                    patch.object(core, 'reserve_request') as funded, self.assertRaises(core.ControlError):
                core.main()
            funded.assert_not_called()
        finally:
            os.chdir(old)

    def test_common_quality_withdraws_security_recovery_without_granting_admission(self):
        native = {'head_sha': self.head, 'event': 'pull_request', 'workflow_id': 1, 'path': core.WORKFLOW,
                  'workflow_url': f'https://api.github.com/repos/{REPO}/actions/required_workflows/1',
                  'pull_requests': [{'number': self.pull['number'], 'base': {'sha': self.base}, 'head': {'sha': self.head}}]}
        config = {'version': 1, 'repository': REPO, 'mode': 'reference', 'accepted_sources': [],
                  'quality': [{'workflow': '.github/workflows/quality.yml', 'job': 'quality'}],
                  'security_profile': security.PROFILE}
        self.api.file.side_effect = None; self.api.file.return_value = core.canonical(config)
        # An empty real Source registry cannot turn the selector into authority.
        with self.assertRaisesRegex(core.ControlError, 'not-admitted'):
            recovery.plan(self.api, REPO, self.pull, 'c' * 40, native)
        with patch.object(security, 'registry', return_value=[self.entry]), \
                patch.object(recovery, 'request', return_value=None), patch.object(recovery, 'history') as funded:
            self.assertIsNone(recovery.plan(self.api, REPO, self.pull, 'c' * 40, native))
        funded.assert_not_called()
        with self.assertRaises(core.ControlError): core.classify(self.pull, REPO)
        with patch.object(security, 'registry', return_value=[self.entry]), \
                patch.object(recovery, 'request', return_value={'some': 'owner request'}), \
                self.assertRaisesRegex(core.ControlError, 'recovery-not-supported'):
            recovery.plan(self.api, REPO, self.pull, 'c' * 40, native)


if __name__ == '__main__': unittest.main()
