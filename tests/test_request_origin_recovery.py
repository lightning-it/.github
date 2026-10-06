"""Exercise the actual Required attempt-two caller with native transport fixtures."""
import copy
import hashlib
import json
import os
import runpy
from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[1]
DEVTOOLS_IMAGE = runpy.run_path(str(ROOT / 'scripts/lit-push-ready.py'))['COPILOT_DEVTOOL_IMAGE']
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
    lookup = fields['oid'] + ':' + fields['record'].split(':', 1)[1]
    if lookup in state.get('EXTRA_JOURNALS', {}):
        result = state['EXTRA_JOURNALS'][lookup]
    else:
        assert fields['oid'] == state['OID'] and fields['manifest'] == state['OID'] + ':manifest.json'
        result = state[kind]
elif route.split('?', 1)[0] in state.get('EXTRA_ROUTES', {}):
    result = state['EXTRA_ROUTES'][route.split('?', 1)[0]]
    if '--slurp' in args:
        result = [result]
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
        # The outer test suite already runs in the pinned image. This transport
        # fixture checks the actual Docker argument contract then executes the
        # unmodified protected proof there, without a nested Docker daemon.
        docker = self.root / 'docker'
        docker.write_text("""#!/usr/bin/env python3
import os, sys
from pathlib import Path
args = sys.argv[1:]
image = __EXPECTED_DEVTOOLS_IMAGE__
assert args[:3] == ['run', '--rm', '-i']
for flag in ('--read-only', '--cap-drop=ALL', '--security-opt=no-new-privileges', '--pids-limit=64', '--network=bridge'):
    assert flag in args
assert args.count('--mount') == 2
for i, value in enumerate(args):
    if value == '--mount':
        assert args[i+1].endswith(',readonly') and 'docker.sock' not in args[i+1]
assert 'GH_TOKEN' in args and not any(value.startswith('GH_TOKEN=') for value in args)
index = args.index(image)
command = args[index+1:]
assert command[0] == 'python3'
command = [value.replace('/proof/', os.environ['RUNNER_TEMP'] + '/') for value in command]
os.chdir(os.environ['RUNNER_TEMP'])
os.execvp(command[0], command)
""".replace("__EXPECTED_DEVTOOLS_IMAGE__", repr(DEVTOOLS_IMAGE)))
        docker.chmod(0o755)
        workflow = WORKFLOW.read_text()
        def heredoc(label):
            return textwrap.dedent(workflow.split("<<'" + label + "'\n", 1)[1].split('\n          ' + label, 1)[0])
        (self.root / 'request-origin.py').write_text(heredoc('REQUEST_ORIGIN'))
        (self.root / 'review_request_continuation.py').write_text(heredoc('CONTINUATION'))
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
                              ("lightning-it/ansible-collection-supplementary", "1103407173")):
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

    def resume_fixture(self):
        data = copy.deepcopy(self.data)
        intent = {'schema': 1, 'kind': 'deferred-first-request', 'repository': REPO, 'repository_id': '1112629689',
                  'operation': REQUEST_KEY, 'pr': PR, 'base': BASE, 'head': HEAD, 'base_ref': 'develop', 'head_ref': 'fix/final',
                  'owner_run': RUN, 'owner_attempt': 1, 'source_sha': SOURCE, 'event': 'pull_request_target', 'action': 'synchronize',
                  'author': 'litroc', 'actor': 'litroc', 'triggering_actor': 'litroc', 'created_at': '2026-10-05T17:50:10Z'}
        historical = '2' * 40
        old_head = 'd' * 40
        record = {**self.record, 'schema': 2, 'claim_run': '88', 'intent': intent,
                  'intent_commit': historical, 'old_review': 16, 'old_head': old_head}
        data['REQUEST_JOURNAL'] = snapshot(record)
        def history(value):
            result = snapshot(value)
            result['data']['repository']['source']['oid'] = historical
            if value is None:
                result['data']['repository']['record'] = None
            return result
        data['EXTRA_JOURNALS'] = {
            historical + ':' + REQUEST_PATH: history(None),
            historical + ':' + REQUEST_PATH.replace('operations/', 'deferred/'): history(intent),
        }
        resume = {**copy.deepcopy(data['REFRESH']), 'id': 88, 'path': '.github/workflows/review-request-continuation.yml',
                  'name': 'Continue deferred first review request',
                  'display_title': f'First review PR #{PR} head {HEAD} owner {RUN} old review 16',
                  'created_at': '2026-10-05T17:59:31Z', 'updated_at': '2026-10-05T17:59:59Z'}
        job = copy.deepcopy(data['FIRST_JOBS'][0]['jobs'][0])
        job.update(id=880, run_id=88, head_sha=SOURCE, name='Resume deferred first review request',
                   started_at='2026-10-05T17:59:32Z', completed_at='2026-10-05T17:59:59Z')
        names = ['Set up job', 'Materialize protected first-request continuation', 'Resume the deferred first request', 'Complete job']
        times = [('32', '33'), ('33', '34'), ('34', '58'), ('58', '59')]
        job['steps'] = [{'name': name, 'number': index + 1, 'status': 'completed', 'conclusion': 'success',
                         'started_at': '2026-10-05T17:59:' + times[index][0] + 'Z',
                         'completed_at': '2026-10-05T17:59:' + times[index][1] + 'Z'} for index, name in enumerate(names)]
        inactive = {**job, 'id': 881, 'name': 'Locate deferred first review request', 'conclusion': 'skipped', 'runner_id': None, 'steps': []}
        old = {'id': 16, 'commit_id': old_head, 'user': {'login': 'copilot-pull-request-reviewer[bot]', 'type': 'Bot'},
               'state': 'COMMENTED', 'body': 'Reviewed old head.', 'submitted_at': '2026-10-05T17:58:00Z'}
        data['EXTRA_ROUTES'] = {
            f'repos/{REPO}/actions/runs/77/attempts/1/jobs': data['FIRST_JOBS'][0],
            f'repos/{REPO}/actions/runs/88/attempts/1': resume,
            f'repos/{REPO}/actions/runs/88/attempts/1/jobs': {'total_count': 2, 'jobs': [job, inactive]},
            f'repos/{REPO}/pulls/{PR}/reviews/16': old,
            f'repos/{REPO}/pulls/{PR}/reviews/16/comments': [],
            f'repos/{REPO}/pulls/{PR}/reviews': [old, *data['REVIEWS'][0]],
        }
        data['TIMELINE'][0][0]['created_at'] = '2026-10-05T17:59:40Z'
        return data

    def test_actual_required_attempt2_accepts_separate_original_and_resume_proof(self):
        data = self.resume_fixture()
        result = self.run_caller(data)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue(any('/actions/runs/88/attempts/1/jobs' in ' '.join(call) for call in self.calls))
        self.assertTrue(any('deferred/' in ' '.join(call) for call in self.calls))
        self.assertFalse(any('--method' in call for call in self.calls))

    def test_actual_required_allows_old_completion_before_owner_but_keeps_effect_age_limit(self):
        data = self.resume_fixture()
        old = data['EXTRA_ROUTES'][f'repos/{REPO}/pulls/{PR}/reviews/16']
        old['submitted_at'] = '2026-10-05T17:49:30Z'
        result = self.run_caller(data)
        self.assertEqual(0, result.returncode, result.stderr)
        old['submitted_at'] = '2026-09-28T17:49:30Z'
        self.assertNotEqual(0, self.run_caller(data).returncode)

    def test_required_embeds_only_the_read_only_provenance_transport(self):
        program = (self.root / 'review_request_continuation.py').read_text()
        self.assertEqual((ROOT / 'scripts/review_request_provenance.py').read_text().strip(), program.strip())
        for forbidden in ('def resume(', 'def defer(', 'def locate(', 'def create(', '--method', '--input', 'requested_reviewers'):
            self.assertNotIn(forbidden, program)

    def test_actual_required_resume_rejects_forged_steps_source_owner_old_review_and_timeline(self):
        original = self.resume_fixture()
        prefix = f'repos/{REPO}'
        mutations = {
            'PR head masquerading as writer source': lambda d: d['EXTRA_ROUTES'][prefix + '/actions/runs/88/attempts/1'].update(head_sha=HEAD),
            'unprotected writer branch': lambda d: d['EXTRA_ROUTES'][prefix + '/actions/runs/88/attempts/1'].update(head_branch='fix/final'),
            'wrong event': lambda d: d['EXTRA_ROUTES'][prefix + '/actions/runs/88/attempts/1'].update(event='pull_request_review'),
            'failed POST': lambda d: d['EXTRA_ROUTES'][prefix + '/actions/runs/88/attempts/1/jobs']['jobs'][0]['steps'][2].update(conclusion='failure'),
            'extra step': lambda d: d['EXTRA_ROUTES'][prefix + '/actions/runs/88/attempts/1/jobs']['jobs'][0]['steps'].append({}),
            'wrong original job': lambda d: d['EXTRA_ROUTES'][prefix + '/actions/runs/77/attempts/1/jobs']['jobs'][0]['steps'][2].update(conclusion='failure'),
            'wrong locator step': lambda d: d['EXTRA_ROUTES'][prefix + '/actions/runs/88/attempts/1/jobs']['jobs'][1].update(conclusion='success'),
            'old quota': lambda d: d['EXTRA_ROUTES'][prefix + f'/pulls/{PR}/reviews/16'].update(body='Quota exceeded'),
            'old is current': lambda d: d['EXTRA_ROUTES'][prefix + f'/pulls/{PR}/reviews/16'].update(commit_id=HEAD),
            'request outside resume step': lambda d: d['TIMELINE'][0][0].update(created_at='2026-10-05T17:50:10Z'),
            'duplicate timeline': lambda d: d['TIMELINE'][0].append(copy.deepcopy(d['TIMELINE'][0][0])),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                data = copy.deepcopy(original)
                mutate(data)
                result = self.run_caller(data)
                self.assertNotEqual(0, result.returncode, result.stderr)

    def test_actual_required_resume_cannot_buy_budget_or_replace_intent(self):
        for field, value in [('owner_run', 78), ('owner_attempt', 2), ('source_sha', HEAD), ('action', 'edited'),
                             ('actor', 'mallory'), ('base', HEAD)]:
            with self.subTest(field=field):
                data = self.resume_fixture()
                record = json.loads(data['REQUEST_JOURNAL']['data']['repository']['record']['text'])
                record['intent'][field] = value
                data['REQUEST_JOURNAL'] = snapshot(record)
                self.assertNotEqual(0, self.run_caller(data).returncode)

    def test_actual_required_resume_preserves_complete_terminal_content_policy(self):
        baseline = self.resume_fixture()
        review_path = f'repos/{REPO}/pulls/{PR}/reviews/16'
        for marker in ('Copilot was not able to review this pull request.',
                     'Copilot is not able to review this pull request.',
                     "Copilot isn't able to review this pull request.",
                     'Copilot isn’t able to review this pull request.',
                     'COPILOT ISN’T ABLE\u2003TO\u00a0REVIEW THIS PULL REQUEST.',
                       "Copilot wasn't able to review this pull request.",
                       'Copilot wasn’t able to review this pull request.',
                       'suppressed comment', 'COPILOT\u00a0WASN’T\u2003ABLE TO REVIEW THIS PULL REQUEST',
                       "Copilot wasn't able to review any files.", 'Copilot wasn’t able to review any files.',
                       "Copilot isn't able to review any files.",
                       "Copilot isn’t able to review any files.",
                       "COPILOT ISN’T ABLE\u2003TO\u00a0REVIEW\u202fANY\u2009FILES.",
                       "The bots aren't able to review any files.",
                       "The bots weren’t able to review any files.",
                       'COPILOT\u00a0WASN’T\u2003ABLE\tTO REVIEW ANY FILES'):
            for inline in (False, True):
                with self.subTest(marker=marker, inline=inline):
                    data = copy.deepcopy(baseline)
                    if inline:
                        data['EXTRA_ROUTES'][review_path + '/comments'] = [{'id': 1001, 'body': marker}]
                    else:
                        data['EXTRA_ROUTES'][review_path]['body'] = marker
                    self.assertNotEqual(0, self.run_caller(data).returncode)
        for body, comments in ((None, []), ({}, []), ('\u2003', []), ('Reviewed.', [None]), ('Reviewed.', [17])):
            with self.subTest(body=body, comments=comments):
                data = copy.deepcopy(baseline)
                data['EXTRA_ROUTES'][review_path]['body'] = body
                data['EXTRA_ROUTES'][review_path + '/comments'] = [{'id': 1001 + index, 'body': value} for index, value in enumerate(comments)]
                self.assertNotEqual(0, self.run_caller(data).returncode)
        result = self.run_caller(baseline)
        self.assertEqual(0, result.returncode, result.stderr)

    def test_actual_required_selected_review_has_precise_negation_policy(self):
        for text, usable in (("Copilot is not able to review this pull request.", False),
                             ("Copilot isn't able to review this pull request.", False),
                             ('Copilot isn’t able to review this pull request.', False),
                             ('Copilot is able to review this pull request.', True),
                             ("Copilot isn't able to review any files.", False),
                             ('Copilot isn’t able to review any files.', False),
                             ('COPILOT ISN’T ABLE\u2003TO\u00a0REVIEW\u202fANY\u2009FILES.', False),
                             ('The bot was able to review any files.', True),
                             ('THE BOT WAS ABLE\u2003TO\u00a0REVIEW\u202fANY\u2009FILES.', True)):
            with self.subTest(text=text):
                data = self.resume_fixture()
                data['REVIEWS'][0][0]['body'] = text
                result = self.run_caller(data)
                self.assertEqual(usable, result.returncode == 0, result.stderr)

    def test_actual_required_proof_rejects_workflow_image_drift_from_engine(self):
        self.assertIn(DEVTOOLS_IMAGE, self.shell)
        self.shell = self.shell.replace(DEVTOOLS_IMAGE, DEVTOOLS_IMAGE.split('@')[0] + '@sha256:' + '0' * 64)
        result = self.run_caller(self.resume_fixture())
        self.assertNotEqual(0, result.returncode)

    def test_all_required_inline_jq_content_classifiers_reject_this_pr_negation(self):
        import re
        workflow = WORKFLOW.read_text()
        # Execute the three actual historical/selection content predicates without
        # replacing their normalization or marker lists with a test-side copy.
        classifiers = list(re.finditer(
            r'\["unabletoreviewthispullrequest"[^\]]+\]\s*\|\s*all\(\.\[\];.*?\|\s*not\)',
            workflow, re.S))
        self.assertEqual(3, len(classifiers))
        positives = ('Copilot was able to review this pull request.',
                     'COPILOT WAS\u00a0ABLE\u2003TO REVIEW THIS PULL REQUEST')
        negatives = ("Copilot wasn't able to review this pull request.",
                     'Copilot wasn’t able to review this pull request.',
                     'Copilot was not able to review this pull request.',
                     'Copilot is not able to review this pull request.',
                     "Copilot isn't able to review this pull request.",
                     'Copilot isn’t able to review this pull request.',
                     'COPILOT ISN’T ABLE\u2003TO\u00a0REVIEW THIS PULL REQUEST.',
                     'COPILOT\u00a0WASN’T\u2003ABLE\tTO REVIEW THIS PULL REQUEST')
        for classifier in classifiers:
            before = workflow[classifier.start() - 220:classifier.start()]
            normalizers = re.findall(r'ascii_downcase\s*\|\s*gsub\([^)]*\)\s*\|\s*gsub\([^)]*\)', before)
            self.assertEqual(1, len(normalizers))
            variable = re.search(r'as (\$[a-z]+)\s*\|\s*$', before)[1]
            program = '(' + normalizers[0] + ') as ' + variable + ' | ' + classifier[0]
            for texts, usable in ((positives, True), (negatives, False)):
                for body in texts:
                    with self.subTest(offset=classifier.start(), body=body):
                        result = subprocess.run(['jq', '-e', program], input=json.dumps(body),
                                                text=True, capture_output=True, check=False)
                        self.assertEqual(0 if usable else 1, result.returncode, result.stderr)

    def test_actual_required_positive_any_files_body_and_inline(self):
        for text in ('Copilot was able to review this pull request.',
                     'COPILOT WAS\u00a0ABLE\u2003TO REVIEW THIS PULL REQUEST',
                     'The bot was able to review any files.', 'able to review any files',
                     'THE BOT WAS\u00a0ABLE\u2003TO REVIEW ANY FILES'):
            for inline in (False, True):
                data = self.resume_fixture()
                path = f'repos/{REPO}/pulls/{PR}/reviews/16'
                if inline:
                    data['EXTRA_ROUTES'][path + '/comments'] = [{'id': 18, 'body': text}]
                else:
                    data['EXTRA_ROUTES'][path]['body'] = text
                result = self.run_caller(data)
                self.assertEqual(0, result.returncode, result.stderr)

    def test_actual_required_historical_review_supersession_uses_request_time(self):
        for timestamp, accepted in (('2026-10-05T17:59:41Z', True), ('2026-10-05T17:59:40Z', False),
                                    ('2026-10-05T17:59:35Z', False), ('2026-10-05T17:59:33Z', False)):
            data = self.resume_fixture()
            old = data['EXTRA_ROUTES'][f'repos/{REPO}/pulls/{PR}/reviews/16']
            data['EXTRA_ROUTES'][f'repos/{REPO}/pulls/{PR}/reviews'].append(
                {**old, 'id': 18, 'body': 'Copilot was not able to review any files.', 'submitted_at': timestamp})
            result = self.run_caller(data)
            self.assertEqual(accepted, result.returncode == 0, result.stderr)
            self.assertFalse(any('--method' in call for call in self.calls))

    def test_actual_required_empty_association_preserves_protected_fallback(self):
        for invalid in (None, 'ambiguous', 'binding', 'disabled', 'second attempt', 'source', 'source wrong sender'):
            with self.subTest(invalid=invalid):
                data = self.resume_fixture()
                pr = copy.deepcopy(data['FIRST']['pull_requests'][0])
                pr.update(id=23, state='open', draft=False, user={'login': 'litroc', 'type': 'User'})
                for side in ('head', 'base'): pr[side]['repo']['full_name'] = REPO
                data['FIRST']['pull_requests'] = []
                data['EXTRA_ROUTES'][f'repos/{REPO}/pulls'] = [pr]
                data['EXTRA_ROUTES'][f'repos/{REPO}/pulls/23'] = pr
                policy = next(job for job in data['FIRST_JOBS'][0]['jobs'] if job['name'] == 'Verify current revision policy')
                policy['steps'] = [{'name': f'Event binding #23:{BASE}:{HEAD}:77', 'number': 2, 'status': 'completed', 'conclusion': 'success'}]
                if invalid == 'ambiguous': data['EXTRA_ROUTES'][f'repos/{REPO}/pulls'].append({**pr, 'id': 24, 'number': 24})
                if invalid == 'binding': policy['steps'][0]['name'] = f'Event binding #23:{HEAD}:{HEAD}:77'
                producer = copy.deepcopy(self.producer)
                producer['pull_requests'] = []
                second = copy.deepcopy(data['FIRST_JOBS'][0])
                for job in second['jobs']:
                    job['run_attempt'] = 2
                    if job['name'] == 'Verify current revision policy': job['conclusion'] = 'success'
                if invalid == 'second attempt':
                    next(job for job in second['jobs'] if job['name'] == 'Verify current revision policy')['steps'][0]['name'] = 'Event binding #wrong'
                data['EXTRA_ROUTES'][f'repos/{REPO}/actions/runs/77/attempts/2/jobs'] = second
                env = {'producer': json.dumps(producer), 'LI219_EVENT_MODE': 'disabled' if invalid == 'disabled' else 'enabled'}
                if invalid in ('source', 'source wrong sender'):
                    repo, rid = 'lightning-it/shared-assets-lit', '1120841013'
                    if invalid == 'source':
                        for native_jobs in (data['FIRST_JOBS'][0]['jobs'], second['jobs']):
                            binding = next(job for job in native_jobs if job['name'] == 'Verify current revision policy')['steps'][0]
                            binding['name'] = f'Current revision tuple #23 develop@{BASE} -> {repo}:fix/final@{HEAD} run 77'
                    path = 'operations/' + hashlib.sha256(f'li219-review-request:v1:{rid}:23:{HEAD}'.encode()).hexdigest() + '.json'
                    def convert(text):
                        return text.replace(REPO, repo).replace('1112629689', rid).replace(REQUEST_PATH.split('/')[1], path.split('/')[1])
                    data = json.loads(convert(json.dumps(data)))
                    def sizes(value):
                        if isinstance(value, dict):
                            if value.get('__typename') == 'Blob': value['byteSize'] = len(value['text'].encode())
                            for child in value.values(): sizes(child)
                        elif isinstance(value, list):
                            for child in value: sizes(child)
                    sizes(data)
                    env.update(REPOSITORY=repo, GITHUB_REPOSITORY_ID=rid, producer=convert(json.dumps(producer)))
                result = self.run_caller(data, **env)
                self.assertEqual(invalid in (None, 'source'), result.returncode == 0, result.stderr)
                self.assertFalse(any('--method' in call for call in self.calls))


    def supplementary_fixture(self, resumed=True):
        data = self.resume_fixture() if resumed else copy.deepcopy(self.data)
        # Native names from the independently prepared six-job Supplementary producer.
        jobs = data['FIRST_JOBS'][0]['jobs']
        jobs[:] = jobs[:2]
        jobs[1]['steps'] = [{'name': 'Invalidate prior result after pull-request metadata change',
                             'number': 2, 'status': 'completed', 'conclusion': 'success'}]
        for index, name in enumerate(('Inactive legacy develop handoff', 'Inactive legacy main pin',
                                      'Inactive legacy main handoff', 'Request protected verifier re-evaluation')):
            jobs.append({**copy.deepcopy(jobs[0]), 'id': 100 + index, 'name': name,
                         'conclusion': 'skipped', 'runner_id': None, 'steps': []})
        data['FIRST_JOBS'][0]['total_count'] = 6
        repo, rid = 'lightning-it/ansible-collection-supplementary', '1103407173'
        path = 'operations/' + hashlib.sha256(f'li219-review-request:v1:{rid}:23:{HEAD}'.encode()).hexdigest() + '.json'
        def convert(text):
            return text.replace(REPO, repo).replace('1112629689', rid).replace(REQUEST_PATH.split('/')[1], path.split('/')[1])
        data = json.loads(convert(json.dumps(data)))
        def sizes(value):
            if isinstance(value, dict):
                if value.get('__typename') == 'Blob': value['byteSize'] = len(value['text'].encode())
                for child in value.values(): sizes(child)
            elif isinstance(value, list):
                for child in value: sizes(child)
        sizes(data)
        return data, dict(REPOSITORY=repo, GITHUB_REPOSITORY_ID=rid, producer=convert(json.dumps(self.producer)))

    def test_actual_required_supplementary_six_job_original_and_continuation(self):
        for resumed in (False, True):
            data, env = self.supplementary_fixture(resumed)
            result = self.run_caller(data, **env)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertFalse(any('--method' in call for call in self.calls))

    def test_actual_required_supplementary_empty_associations_fail_in_outer_caller(self):
        for resumed in (False, True):
            data, env = self.supplementary_fixture(resumed)
            repo = env['REPOSITORY']
            pr = copy.deepcopy(data['FIRST']['pull_requests'][0])
            pr.update(id=23, state='open', draft=False, user={'login': 'litroc', 'type': 'User'})
            for side in ('head', 'base'): pr[side]['repo']['full_name'] = repo
            data['FIRST']['pull_requests'] = []
            data.setdefault('EXTRA_ROUTES', {}).update({f'repos/{repo}/pulls': [pr], f'repos/{repo}/pulls/23': pr})
            producer = json.loads(env['producer'])
            producer['pull_requests'] = []
            env['producer'] = json.dumps(producer)
            result = self.run_caller(data, **env)
            self.assertNotEqual(0, result.returncode)
            self.assertFalse(any('--method' in call for call in self.calls))

    def test_authenticated_timeline_precedes_old_review_lookup_for_both_helpers(self):
        for helper in ('review_request_continuation.py', 'review_request_provenance.py'):
            (self.root / 'review_request_continuation.py').write_bytes((ROOT / 'scripts' / helper).read_bytes())
            for fault in ('missing', 'duplicate', 'foreign', 'human', 'zero', 'boolean', 'before', 'after', 'reviewer'):
                with self.subTest(helper=helper, fault=fault):
                    data = self.resume_fixture()
                    event = data['TIMELINE'][0][0]
                    if fault == 'missing': data['TIMELINE'] = [[]]
                    elif fault == 'duplicate': data['TIMELINE'][0].append(copy.deepcopy(event))
                    elif fault == 'foreign': event['actor']['login'] = 'mallory'
                    elif fault == 'human': event['actor']['type'] = 'User'
                    elif fault == 'boolean': event['id'] = True
                    elif fault == 'zero': event['id'] = 0
                    elif fault == 'before': event['created_at'] = '2026-10-05T17:59:33Z'
                    elif fault == 'after': event['created_at'] = '2026-10-05T17:59:59Z'
                    elif fault == 'reviewer': event['requested_reviewer']['login'] = 'mallory'
                    result = self.run_caller(data)
                    self.assertNotEqual(0, result.returncode)
                    self.assertFalse(any('/reviews/16' in ' '.join(call) for call in self.calls))

    def test_selected_clean_review_between_step_start_and_request_is_historically_valid(self):
        for helper in ('review_request_continuation.py', 'review_request_provenance.py'):
            (self.root / 'review_request_continuation.py').write_bytes((ROOT / 'scripts' / helper).read_bytes())
            for seconds, accepted, login in (('35', True, 'copilot-pull-request-reviewer[bot]'), ('35', True, 'copilot-pull-request-reviewer'), ('41', False, 'copilot-pull-request-reviewer')):
                data = self.resume_fixture()
                data['EXTRA_ROUTES'][f'repos/{REPO}/pulls/{PR}/reviews/16']['submitted_at'] = '2026-10-05T17:59:' + seconds + 'Z'
                data['EXTRA_ROUTES'][f'repos/{REPO}/pulls/{PR}/reviews/16']['user']['login'] = login
                result = self.run_caller(data)
                self.assertEqual(accepted, result.returncode == 0, result.stderr)
