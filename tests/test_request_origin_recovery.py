"""Exercise the actual Required attempt-two caller with native transport fixtures."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / '.github/workflows/supplementary-current-revision-required.yml'
REPO = 'lightning-it/.github'
BASE, HEAD, SOURCE, JOURNAL = 'a' * 40, 'b' * 40, 'c' * 40, '1' * 40
RUN, PR = 77, 23
REQUEST_KEY = f'li219-review-request:v1:1112629689:{PR}:{HEAD}'
RERUN_KEY = f'li219-verifier-operation:v1:{PR}:{BASE}:{HEAD}:{RUN}'
REQUEST_PATH = 'operations/' + hashlib.sha256(REQUEST_KEY.encode()).hexdigest() + '.json'


def blob(value):
    text = json.dumps(value)
    return {'__typename': 'Blob', 'isTruncated': False, 'byteSize': len(text.encode()), 'text': text}


def snapshot(record):
    return {'data': {'repository': {'nameWithOwner': REPO,
            'source': {'__typename': 'Commit', 'oid': JOURNAL},
            'manifest': blob({'schema': 1, 'repository': REPO, 'repository_id': '1112629689',
                              'ref': 'refs/heads/lit-review-operations'}), 'record': blob(record)}}}


MOCK_GH = r'''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
assert args[0] == 'api' and '--method' not in args and '--input' not in args
state = json.loads(Path(os.environ['FIXTURE']).read_text())
route = next(a for a in args if a.startswith('repos/') or a == 'graphql')
with open(os.environ['CALLS'], 'a') as log: log.write(json.dumps(args) + '\n')
if route == 'graphql':
    fields = dict(arg.split('=', 1) for arg in args if '=' in arg)
    assert 'mutation' not in fields['query']
    kind = 'REQUEST_JOURNAL' if fields['record'].endswith(state['REQUEST_PATH']) else 'RERUN_JOURNAL'
    assert fields['oid'] == state['OID'] and fields['manifest'] == state['OID'] + ':manifest.json'
    result = state[kind]
elif route.endswith('/attempts/1'):
    result = state['FIRST']
elif '/actions/runs/77/attempts/1/jobs?' in route:
    result = state['FIRST_JOBS']
elif '/actions/runs/500/attempts/1/jobs?' in route:
    result = state['REFRESH_JOBS']
elif route.endswith('/actions/runs/500'):
    result = state['REFRESH']
elif '/check-runs?' in route:
    result = state['CLAIMS']
elif '/reviews?' in route:
    result = state['REVIEWS']
elif '/timeline?' in route:
    result = state['TIMELINE']
elif '/git/ref/' in route:
    if '--jq' in args:
        print(state['OID']); sys.exit(0)
    result = state['REF']
elif '/compare/' in route:
    result = state['ANCESTRY']
elif route.endswith('/branches/develop'):
    result = state['BRANCH']
elif route == 'repos/' + state['REPO']:
    result = state['METADATA']
else:
    raise AssertionError(route)
print(json.dumps(result))
'''


class RequestOriginRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        workflow = WORKFLOW.read_text()
        def heredoc(label):
            return textwrap.dedent(workflow.split("<<'" + label + "'\n", 1)[1].split('\n          ' + label, 1)[0])
        (self.root / 'request-origin.py').write_text(heredoc('REQUEST_ORIGIN'))
        guard = heredoc('EVENT_RECOVERY')
        ordering = workflow.split('cat >"${ordering}" <<\'JQ\'\n', 1)[1].split('\n          JQ', 1)[0]
        (self.root / 'native-recovery-ordering.jq').write_text(textwrap.dedent(ordering))
        owner = workflow.split('cat >"${owner_run_filter}" <<\'JQ\'\n', 1)[1].split('\n          JQ', 1)[0]
        (self.root / 'current-revision-owner-run.jq').write_text(textwrap.dedent(owner))
        # Execute the full real attempt-two branch, including the rerun CAS proof,
        # native first-attempt jobs, review filtering, request-origin call and final
        # attempt-two actor/conclusion check. No authorizing helper is stubbed.
        caller = 'attempt_one=' + workflow.split('              test "${producer_kind}" = copilot\n              attempt_one=', 1)[1].split(
            '\n            fi\n            jq -e \\\n              --arg run_url', 1)[0]
        self.shell = 'set -euo pipefail\n' + guard + '\n' + textwrap.dedent(caller)
        gh = self.root / 'gh'
        gh.write_text(MOCK_GH)
        gh.chmod(0o755)
        self.record = {'schema': 1, 'repository': REPO, 'repository_id': '1112629689',
                       'action': 'request', 'operation': REQUEST_KEY, 'claim_run': '77',
                       'claim_attempt': '1', 'source_sha': SOURCE}
        pull = {'number': PR, 'base': {'ref': 'develop', 'sha': BASE, 'repo': {'url': f'https://api.github.com/repos/{REPO}'}},
                'head': {'ref': 'fix/final', 'sha': HEAD, 'repo': {'url': f'https://api.github.com/repos/{REPO}'}}}
        first = {'id': RUN, 'event': 'pull_request_target', 'run_attempt': 1, 'status': 'completed', 'conclusion': 'failure',
                 'path': '.github/workflows/copilot-review.yml', 'name': 'Current revision review gate',
                 'head_sha': HEAD, 'head_branch': 'fix/final', 'actor': {'login': 'litroc'},
                 'triggering_actor': {'login': 'litroc'}, 'repository': {'full_name': REPO},
                 'head_repository': {'full_name': REPO}, 'pull_requests': [pull],
                 'created_at': '2026-10-05T17:50:00Z', 'updated_at': '2026-10-05T17:59:30Z'}
        self.producer = {**copy.deepcopy(first), 'run_attempt': 2, 'conclusion': 'success',
                         'triggering_actor': {'login': 'github-actions[bot]'}, 'run_started_at': '2026-10-05T18:00:04Z',
                         'updated_at': '2026-10-05T18:00:10Z'}
        names = ['Set up job', 'Materialize the protected operation claim',
                 'Request Copilot review for the current revision', 'Complete job']
        times = [('17:50:01', '17:50:02'), ('17:50:02', '17:50:03'), ('17:50:03', '17:50:58'), ('17:50:58', '17:50:59')]
        steps = [{'name': name, 'number': index + 1, 'status': 'completed', 'conclusion': 'success',
                  'started_at': f'2026-10-05T{times[index][0]}Z', 'completed_at': f'2026-10-05T{times[index][1]}Z'}
                 for index, name in enumerate(names)]
        request = {'id': 51, 'name': 'Request Copilot review for current revision', 'run_id': RUN, 'run_attempt': 1,
                   'head_sha': HEAD, 'status': 'completed', 'conclusion': 'success', 'runner_id': 6, 'steps': steps,
                   'started_at': '2026-10-05T17:50:01Z', 'completed_at': '2026-10-05T17:51:00Z'}
        verifier = {**request, 'id': 52, 'name': 'Verify current revision policy', 'conclusion': 'failure',
                    'completed_at': '2026-10-05T17:59:00Z', 'steps': []}
        inert = [{**request, 'id': 53 + i, 'name': name, 'conclusion': 'skipped', 'runner_id': None, 'steps': []}
                 for i, name in enumerate(('Classify protected main trust-root handoff', 'Request protected verifier re-evaluation'))]
        refresh = {'id': 500, 'run_attempt': 1, 'event': 'workflow_dispatch', 'path': '.github/workflows/copilot-review-refresh.yml',
                   'name': 'Refresh Copilot review gate', 'repository': {'full_name': REPO}, 'head_repository': {'full_name': REPO},
                   'head_branch': 'develop', 'head_sha': SOURCE, 'actor': {'login': 'github-actions[bot]'},
                   'triggering_actor': {'login': 'github-actions[bot]'}, 'status': 'completed', 'conclusion': 'success',
                   'display_title': f'Reconcile review PR #{PR} head {HEAD}',
                   'created_at': '2026-10-05T17:55:00Z', 'updated_at': '2026-10-05T18:00:07Z'}
        refresh_job = {'id': 55, 'run_id': 500, 'run_attempt': 1, 'head_sha': SOURCE, 'name': 'Refresh canonical Copilot review gate',
                       'status': 'completed', 'conclusion': 'success', 'started_at': '2026-10-05T18:00:00Z',
                       'completed_at': '2026-10-05T18:00:06Z', 'steps': [
                           {'name': 'Materialize the protected operation claim', 'number': 2, 'status': 'completed',
                            'conclusion': 'success', 'started_at': '2026-10-05T18:00:00Z', 'completed_at': '2026-10-05T18:00:01Z'},
                           {'name': 'Rerun the canonical protected gate when needed', 'number': 3, 'status': 'completed',
                            'conclusion': 'success', 'started_at': '2026-10-05T18:00:01Z', 'completed_at': '2026-10-05T18:00:05Z'}]}
        skipped = [{'id': 56 + index, 'run_id': 500, 'run_attempt': 1, 'head_sha': SOURCE, 'name': name, 'status': 'completed',
                    'conclusion': 'skipped', 'runner_id': None, 'steps': []}
                   for index, name in enumerate(('Locate protected review refresh', 'Inactive legacy writer'))]
        receipt = {'operation': RERUN_KEY, 'claim_run': '500', 'claim_attempt': '1', 'journal_commit': JOURNAL}
        claim = {'name': 'Review event operation', 'head_sha': HEAD, 'external_id': RERUN_KEY,
                 'app': {'id': 15368, 'slug': 'github-actions'}, 'status': 'completed', 'conclusion': 'neutral',
                 'started_at': '2026-10-05T18:00:02Z', 'output': {'title': 'Verifier mutation consumed', 'summary': json.dumps(receipt)}}
        rerun_record = {**self.record, 'action': 'rerun', 'operation': RERUN_KEY, 'claim_run': '500'}
        self.data = {'REPO': REPO, 'OID': JOURNAL, 'REQUEST_PATH': REQUEST_PATH,
                     'FIRST': first, 'FIRST_JOBS': [{'total_count': 4, 'jobs': [request, verifier, *inert]}],
                     'REFRESH': refresh, 'REFRESH_JOBS': [{'total_count': 3, 'jobs': [refresh_job, *skipped]}],
                     'CLAIMS': [{'check_runs': [claim]}], 'RERUN_JOURNAL': snapshot(rerun_record),
                     'REQUEST_JOURNAL': snapshot(self.record), 'ANCESTRY': {'status': 'identical'},
                     'METADATA': {'full_name': REPO, 'id': 1112629689, 'default_branch': 'develop'},
                     'BRANCH': {'name': 'develop', 'protected': True, 'commit': {'sha': SOURCE}},
                     'REF': {'ref': 'refs/heads/lit-review-operations', 'object': {'type': 'commit', 'sha': JOURNAL}},
                     'REVIEWS': [[{'id': 17, 'commit_id': HEAD, 'state': 'COMMENTED', 'body': 'Reviewed.',
                                  'user': {'login': 'copilot-pull-request-reviewer[bot]', 'type': 'Bot'},
                                  'submitted_at': '2026-10-05T18:00:00Z'}]],
                     'TIMELINE': [[{'id': 31, 'event': 'review_requested', 'actor': {'login': 'github-actions[bot]', 'type': 'Bot'},
                                   'requested_reviewer': {'login': 'Copilot'}, 'created_at': '2026-10-05T17:50:10Z'}]]}

    def run_caller(self, data=None, **env):
        fixture, calls = self.root / 'fixture.json', self.root / 'calls.jsonl'
        fixture.write_text(json.dumps(data or self.data))
        calls.write_text('')
        result = subprocess.run(['bash', '-c', self.shell], text=True, capture_output=True, timeout=30, check=False,
                                env={**os.environ, 'PATH': str(self.root) + os.pathsep + os.environ['PATH'],
                                     'FIXTURE': str(fixture), 'CALLS': str(calls), 'RUNNER_TEMP': str(self.root),
                                     'LI219_EVENT_MODE': 'enabled', 'GITHUB_REPOSITORY_ID': '1112629689',
                                     'GITHUB_API_URL': 'https://api.github.com', 'REPOSITORY': REPO, 'author': 'litroc',
                                     'owner_pr_number': '23', 'EVENT_BASE': BASE, 'EVENT_HEAD': HEAD, 'base_ref': 'develop',
                                     'controller_branch': 'develop', 'controller_head': SOURCE, 'controller_sha': SOURCE,
                                     'producer_run_id': '77', 'producer': json.dumps(self.producer), **env})
        self.calls = [json.loads(line) for line in calls.read_text().splitlines()]
        return result

    def test_real_bot_auto_missing_review_rerun_required_path_accepts(self):
        result = self.run_caller()
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue(any(REQUEST_PATH in ' '.join(call) for call in self.calls))
        self.assertTrue(any('/check-runs?' in ' '.join(call) for call in self.calls))
        self.assertFalse(any('--method' in call for call in self.calls))

    def test_same_caller_proof_supports_each_other_enabled_pilot(self):
        for repo, repo_id in (("lightning-it/shared-assets-lit", "1120841013"),
                              ("lightning-it/ansible-collection-supplementary", "123456")):
            with self.subTest(repo=repo):
                data = json.loads(json.dumps(self.data).replace(REPO, repo).replace("1112629689", repo_id))
                record = {**self.record, "repository": repo, "repository_id": repo_id,
                          "operation": f"li219-review-request:v1:{repo_id}:{PR}:{HEAD}"}
                data["REQUEST_PATH"] = "operations/" + hashlib.sha256(record["operation"].encode()).hexdigest() + ".json"
                # Re-encode native Blob byteSize after changing repository text.
                for key in ("REQUEST_JOURNAL", "RERUN_JOURNAL"):
                    for field in ("manifest", "record"):
                        value = data[key]["data"]["repository"][field]
                        value["byteSize"] = len(value["text"].encode())
                producer = json.dumps(self.producer).replace(REPO, repo)
                result = self.run_caller(data, REPOSITORY=repo, GITHUB_REPOSITORY_ID=repo_id, producer=producer)
                self.assertEqual(0, result.returncode, result.stderr)

    def test_native_commit_timeline_shape_does_not_require_issue_event_id(self):
        self.data['TIMELINE'][0].append({'event': 'committed', 'sha': HEAD,
                                        'node_id': 'native-commit-node', 'message': 'Commit'})
        result = self.run_caller()
        self.assertEqual(0, result.returncode, result.stderr)

    def test_author_route_remains_independent_of_request_cas(self):
        self.data['TIMELINE'][0][0]['actor'] = {'login': 'litroc', 'type': 'User'}
        self.data['REQUEST_JOURNAL'] = None
        result = self.run_caller()
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertFalse(any(REQUEST_PATH in ' '.join(call) for call in self.calls))

    def test_wrong_request_record_bindings_and_nonrequest_fail(self):
        for field, value in [('repository', 'lightning-it/foreign'), ('repository_id', '2'), ('action', 'rerun'),
                             ('operation', REQUEST_KEY.replace(HEAD, BASE)), ('operation', REQUEST_KEY.replace(':23:', ':24:')),
                             ('claim_run', '78'), ('claim_attempt', '2'), ('source_sha', BASE), ('schema', 2), ('schema', True)]:
            with self.subTest(field=field, value=value):
                data = copy.deepcopy(self.data)
                data['REQUEST_JOURNAL'] = snapshot({**self.record, field: value})
                self.assertNotEqual(0, self.run_caller(data).returncode)

    def test_missing_partial_stale_or_mixed_snapshot_fails(self):
        for mutate in (
            lambda d: d['REQUEST_JOURNAL'].update(errors=[]),
            lambda d: d['REQUEST_JOURNAL']['data']['repository'].update(record=None),
            lambda d: d['REQUEST_JOURNAL']['data']['repository']['source'].update(oid=BASE),
            lambda d: d['REQUEST_JOURNAL']['data']['repository']['record'].update(isTruncated=True),
            lambda d: d['REQUEST_JOURNAL']['data']['repository'].update(manifest=blob({'schema': 1})),
            lambda d: d['REF']['object'].update(type='tag'),
        ):
            data = copy.deepcopy(self.data)
            mutate(data)
            self.assertNotEqual(0, self.run_caller(data).returncode)

    def test_wrong_source_owner_base_head_actor_and_attempt_fail(self):
        for field, value in [('head_sha', BASE), ('actor', {'login': 'mallory'}), ('run_attempt', 2), ('id', 78)]:
            data = copy.deepcopy(self.data)
            data['FIRST'][field] = value
            self.assertNotEqual(0, self.run_caller(data).returncode)
        for side in ('head', 'base'):
            data = copy.deepcopy(self.data)
            data['FIRST']['pull_requests'][0][side]['sha'] = SOURCE
            self.assertNotEqual(0, self.run_caller(data).returncode)
        data = copy.deepcopy(self.data)
        data['FIRST']['pull_requests'][0]['number'] = 24
        self.assertNotEqual(0, self.run_caller(data).returncode)
        for changes in ({'controller_sha': BASE}, {'LI219_EVENT_MODE': 'disabled'},
                        {'GITHUB_REPOSITORY_ID': '9'}, {'author': 'mallory'}):
            self.assertNotEqual(0, self.run_caller(**changes).returncode)
        data = copy.deepcopy(self.data)
        data['BRANCH']['protected'] = False
        self.assertNotEqual(0, self.run_caller(data).returncode)

    def test_complete_native_job_and_step_inventory_is_required(self):
        for field, value in [('run_id', 78), ('head_sha', BASE), ('run_attempt', 2), ('runner_id', None),
                             ('status', 'in_progress'), ('conclusion', 'failure'), ('steps', [])]:
            data = copy.deepcopy(self.data)
            data['FIRST_JOBS'][0]['jobs'][0][field] = value
            self.assertNotEqual(0, self.run_caller(data).returncode)
        for mutate in (
            lambda d: d['FIRST_JOBS'][0].update(total_count=5),
            lambda d: d['FIRST_JOBS'][0]['jobs'].append(d['FIRST_JOBS'][0]['jobs'][0]),
            lambda d: d['FIRST_JOBS'][0]['jobs'][0]['steps'][1].update(conclusion='skipped'),
            lambda d: d['FIRST_JOBS'][0]['jobs'][0]['steps'][2].update(number=2),
            lambda d: d['FIRST_JOBS'][0]['jobs'][0]['steps'][2].update(name='Foreign request'),
            lambda d: d['FIRST_JOBS'][0]['jobs'][0]['steps'].append(d['FIRST_JOBS'][0]['jobs'][0]['steps'][2]),
        ):
            data = copy.deepcopy(self.data)
            mutate(data)
            self.assertNotEqual(0, self.run_caller(data).returncode)

    def test_bot_timeline_unique_and_inside_exact_effect_step(self):
        for changes in ({'actor': {'login': 'mallory', 'type': 'Bot'}},
                        {'actor': {'login': 'github-actions[bot]', 'type': 'User'}},
                        {'created_at': '2026-10-05T17:50:02Z'}, {'created_at': '2026-10-05T17:51:01Z'}):
            data = copy.deepcopy(self.data)
            data['TIMELINE'][0][0].update(changes)
            self.assertNotEqual(0, self.run_caller(data).returncode)
        for duplicate_id in (31, 32):
            data = copy.deepcopy(self.data)
            data['TIMELINE'][0].append({**data['TIMELINE'][0][0], 'id': duplicate_id})
            self.assertNotEqual(0, self.run_caller(data).returncode)

    def test_unknown_post_without_native_confirmation_is_rejected(self):
        # A consumed CAS is insufficient. Lost/unaccepted request response leaves
        # either no timeline or a failed request step; neither buys a second try.
        data = copy.deepcopy(self.data)
        data['TIMELINE'] = [[]]
        self.assertNotEqual(0, self.run_caller(data).returncode)
        data = copy.deepcopy(self.data)
        data['FIRST_JOBS'][0]['jobs'][0]['steps'][2]['conclusion'] = 'failure'
        self.assertNotEqual(0, self.run_caller(data).returncode)
        # Accepted-but-lost POST reconciled by the producer is represented by
        # the same native success/timeline proof, without any retry permission.
        self.assertEqual(0, self.run_caller().returncode)

    def test_terminal_review_and_forged_rerun_cas_still_fail(self):
        for body in ('premium request quota', 'encountered an error', 'no files to review'):
            data = copy.deepcopy(self.data)
            data['REVIEWS'][0][0]['body'] = body
            self.assertNotEqual(0, self.run_caller(data).returncode)
        data = copy.deepcopy(self.data)
        data['RERUN_JOURNAL']['data']['repository']['record'] = blob(self.record)
        self.assertNotEqual(0, self.run_caller(data).returncode)
