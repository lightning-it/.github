"""Exercise the actual default-mode CAS recovery and request-origin reader."""
import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[1]
BASE, HEAD, COMMIT = 'a' * 40, 'b' * 40, 'c' * 40
REPO = 'lightning-it/.github'


class RootDefaultRecoveryTests(unittest.TestCase):
    def setUp(self):
        source = (ROOT / '.github/workflows/supplementary-current-revision-required.yml').read_text()
        self.functions = textwrap.dedent(source.split("<<'EVENT_RECOVERY'\n", 1)[1].split('\n          EVENT_RECOVERY', 1)[0])
        self.ordering = textwrap.dedent(
            source.split('cat >"${ordering}" <<\'JQ\'\n', 1)[1].split('\n          JQ', 1)[0])
        t = lambda seconds: '2026-10-05T18:00:' + f'{seconds:02d}Z'
        self.key = f'li219-verifier-operation:v1:23:{BASE}:{HEAD}:99'
        record = {'schema': 1, 'repository': REPO, 'repository_id': '1112629689',
                  'action': 'rerun', 'operation': self.key, 'claim_attempt': '1',
                  'claim_run': '500', 'source_sha': BASE}
        receipt = {'operation': self.key, 'claim_run': '500', 'claim_attempt': '1', 'journal_commit': COMMIT}
        blob = lambda value: {'__typename': 'Blob', 'isTruncated': False,
                             'byteSize': len(json.dumps(value).encode()), 'text': json.dumps(value)}
        self.refresh = {'id': 500, 'run_attempt': 1, 'event': 'workflow_dispatch',
                        'path': '.github/workflows/copilot-review-refresh.yml',
                        'repository': {'full_name': REPO}, 'head_repository': {'full_name': REPO},
                        'head_branch': 'develop', 'head_sha': BASE,
                        'actor': {'login': 'github-actions[bot]'}, 'triggering_actor': {'login': 'github-actions[bot]'},
                        'status': 'completed', 'conclusion': 'success',
                        'name': 'Refresh Copilot review gate', 'display_title': f'Reconcile review PR #23 head {HEAD}',
                        'created_at': t(20), 'updated_at': t(30)}
        materialize = {'name': 'Materialize the protected operation claim', 'number': 2,
                       'status': 'completed', 'conclusion': 'success', 'started_at': t(22), 'completed_at': t(23)}
        effect = {'name': 'Rerun the canonical protected gate when needed', 'number': 3,
                  'status': 'completed', 'conclusion': 'success', 'started_at': t(24), 'completed_at': t(27)}
        writer = {'id': 501, 'run_id': 500, 'run_attempt': 1, 'head_sha': BASE,
                  'name': 'Refresh canonical Copilot review gate', 'status': 'completed', 'conclusion': 'success',
                  'runner_id': 1, 'started_at': t(21), 'completed_at': t(29), 'steps': [materialize, effect]}
        siblings = [{**writer, 'id': 502 + n, 'name': name, 'conclusion': 'skipped', 'runner_id': None, 'steps': []}
                    for n, name in enumerate(('Inactive legacy writer', 'Locate protected review refresh',
                                              'Locate deferred first review request', 'Resume deferred first review request'))]
        self.jobs = [{'total_count': 5, 'jobs': [writer, *siblings]}]
        self.claim = {'name': 'Review event operation', 'head_sha': HEAD,
                      'app': {'id': 15368, 'slug': 'github-actions'}, 'status': 'completed', 'conclusion': 'neutral',
                      'started_at': t(20), 'external_id': self.key,
                      'output': {'title': 'Verifier mutation consumed', 'summary': json.dumps(receipt)}}
        self.responses = {
            f'repos/{REPO}/commits/{HEAD}/check-runs?check_name=Review%20event%20operation&filter=all&per_page=100': [{'check_runs': [self.claim]}],
            f'repos/{REPO}/git/ref/heads/lit-review-operations': {'object': {'sha': COMMIT}},
            f'repos/{REPO}/compare/{COMMIT}...{COMMIT}': {'status': 'identical'},
            'graphql': {'data': {'repository': {'nameWithOwner': REPO,
                'source': {'__typename': 'Commit', 'oid': COMMIT},
                'manifest': blob({'schema': 1, 'repository': REPO, 'repository_id': '1112629689', 'ref': 'refs/heads/lit-review-operations'}),
                'record': blob(record)}}},
            f'repos/{REPO}/actions/runs/500': self.refresh,
            f'repos/{REPO}/branches/develop': {'name': 'develop', 'protected': True, 'commit': {'sha': BASE}},
            f'repos/{REPO}/compare/{BASE}...{BASE}': {'status': 'identical'},
            f'repos/{REPO}/actions/runs/500/attempts/1/jobs?per_page=100': self.jobs,
        }
        self.request = [{'jobs': [{'run_id': 99, 'run_attempt': 1, 'head_sha': HEAD,
            'name': 'Request Copilot review for current revision', 'status': 'completed', 'conclusion': 'success',
            'steps': [{'name': 'Request Copilot review for the current revision', 'number': 3,
                       'status': 'completed', 'conclusion': 'success', 'started_at': t(1), 'completed_at': t(4)}]}]}]
        self.timeline = [[{'event': 'review_requested', 'actor': {'login': 'github-actions[bot]', 'type': 'Bot'},
                           'requested_reviewer': {'login': 'Copilot'}, 'created_at': t(3)}]]
        self.environment = {'LI219_EVENT_MODE': 'disabled', 'REPOSITORY': REPO, 'GITHUB_REPOSITORY_ID': '1112629689',
            'EVENT_BASE': BASE, 'EVENT_HEAD': HEAD, 'base_ref': 'develop', 'owner_pr_number': '23',
            'producer_run_id': '99', 'first_verifier_completed_at': t(10), 'review_submitted_at': t(15),
            'producer': json.dumps({'run_started_at': t(26), 'created_at': t(0)}), 'author': 'litroc'}

    def run_reader(self, responses=None, request=None, timeline=None, overrides=None):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'native-recovery-ordering.jq').write_text(self.ordering)
            (root / 'responses.json').write_text(json.dumps(self.responses if responses is None else responses))
            (root / 'api-stub.py').write_text('import json,os,sys\nd=json.load(open(os.environ["RESPONSES"]))\nprint(json.dumps(d[sys.argv[1]]))\n')
            stub = '''gh() {
  [ "$1" = api ] || return 99
  shift
  while [ "${1:-}" = --paginate ] || [ "${1:-}" = --slurp ]; do shift; done
  [ "${1:-}" != --method ] || return 99
  if [ "${2:-}" = --jq ]; then
    python3 "${STUB}" "$1" | jq -r "$3"
  else
    python3 "${STUB}" "$1"
  fi
}
'''
            # All transport is hermetic; run_request_proof is deliberately not
            # stubbed, so accidentally entering the pilot funding route fails.
            script = self.functions + '\n' + stub + '\nverify_event_recovery || exit $?\nrecovery_status=0\nverify_request_origin "${TIMELINE}"\n'
            env = {**os.environ, **self.environment, 'RUNNER_TEMP': tmp, 'STUB': str(root / 'api-stub.py'),
                   'RESPONSES': str(root / 'responses.json'), 'attempt_one_jobs': json.dumps(self.request if request is None else request),
                   'TIMELINE': json.dumps(self.timeline if timeline is None else timeline), **(overrides or {})}
            result = subprocess.run(['bash', '-c', 'set -eu\n' + ('set -x\n' if os.environ.get('TRACE_RECOVERY') else '') + script], env=env, text=True, capture_output=True)
            return result

    def test_complete_default_recovery_and_original_request_without_pilot_enable(self):
        result = self.run_reader()
        self.assertEqual(0, result.returncode, result.stderr)

    def test_wrong_actor_source_revision_claim_inventory_and_original_request_fail(self):
        mutations = []
        for field, value in (('head_sha', HEAD), ('head_branch', 'main'), ('run_attempt', 2),
                             ('display_title', f'Reconcile review PR #24 head {HEAD}'),
                             ('actor', {'login': 'litroc'}), ('triggering_actor', {'login': 'litroc'})):
            data = copy.deepcopy(self.responses)
            data[f'repos/{REPO}/actions/runs/500'][field] = value
            mutations.append((field, data))
        data = copy.deepcopy(self.responses)
        data[f'repos/{REPO}/actions/runs/500/attempts/1/jobs?per_page=100'][0]['jobs'][1]['runner_id'] = 42
        mutations.append(('active sibling', data))
        data = copy.deepcopy(self.responses)
        data[f'repos/{REPO}/commits/{HEAD}/check-runs?check_name=Review%20event%20operation&filter=all&per_page=100'][0]['check_runs'][0]['external_id'] += 'different'
        mutations.append(('wrong claim', data))
        for label, responses in mutations:
            with self.subTest(label=label):
                self.assertNotEqual(0, self.run_reader(responses).returncode)
        for change in ({'conclusion': 'failure'}, {'run_attempt': 2}, {'head_sha': BASE}):
            request = copy.deepcopy(self.request)
            request[0]['jobs'][0].update(change)
            self.assertNotEqual(0, self.run_reader(request=request).returncode)
        timeline = copy.deepcopy(self.timeline)
        timeline[0][0]['created_at'] = '2026-10-05T18:00:05Z'
        self.assertNotEqual(0, self.run_reader(timeline=timeline).returncode)
        self.assertEqual(10, self.run_reader(overrides={'REPOSITORY': 'lightning-it/shared-assets-lit'}).returncode)


if __name__ == '__main__':
    unittest.main()
