"""Exercise the real workflow writer with a stateful GitHub CAS transport."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from tests import test_copilot_review_refresh as contracts

ROOT = Path(__file__).resolve().parents[1]
BASE, HEAD, SOURCE = "a" * 40, "b" * 40, "c" * 40
INITIAL, COMMITTED = "0" * 40, "1" * 40

MOCK = r'''
import datetime as dt
import json
import os
from pathlib import Path
import sys
args = sys.argv[1:]
file = Path(os.environ['STATE'])
s = json.loads(file.read_text())
worker = os.environ['GITHUB_RUN_ID']
mode = s['mode']
fields = dict(a.split('=', 1) for a in args if '=' in a)
route = next((a for a in args if a.startswith('repos/') or a == 'graphql'), '')
post = '--method' in args and args[args.index('--method') + 1] == 'POST'
call = {'worker': worker, 'route': route, 'post': post}
s['calls'].append(call)
rc, result = 0, None
if route == 'graphql' and '--input' in args:
    request = json.load(sys.stdin)['variables']['input']
    call.update(cas=True, input=request)
    assert request['branch'] == {'repositoryNameWithOwner': 'lightning-it/.github', 'branchName': 'lit-review-operations'}
    assert len(request['fileChanges']['additions']) == 1
    assert 'deletions' not in request['fileChanges']
    old = request['expectedHeadOid']
    if old != s['oid']:
        result, rc = {'errors': [{'message': 'expectedHeadOid mismatch'}]}, 1
    elif mode == 'not-applied':
        rc = 42
    else:
        import base64
        entry = request['fileChanges']['additions'][0]
        record = base64.b64decode(entry['contents']).decode()
        s['oid'] = '1' * 40 if old == '0' * 40 else format(int(old, 16) + 1, '040x')
        s['versions'][s['oid']] = {**s['versions'][old], entry['path']: json.loads(record)}
        result = {'data': {'createCommitOnBranch': {'commit': {
            'oid': s['oid'], 'parents': {'nodes': [{'oid': old}]}}}}}
        if mode == 'lost-cas':
            result, rc = None, 42
        if mode == 'partial-cas':
            result['errors'] = []
        if mode == 'wrong-parent':
            result['data']['createCommitOnBranch']['commit']['parents']['nodes'] = []
elif route == 'graphql':
    oid = fields['oid']
    assert fields['manifest'] == oid + ':manifest.json'
    assert fields['record'].startswith(oid + ':operations/')
    record = s['versions'][oid].get(fields['record'].split(':', 1)[1])
    manifest = {'schema': 1, 'repository': 'lightning-it/.github', 'repository_id': '1112629689', 'ref': 'refs/heads/lit-review-operations'}
    if mode == 'foreign-manifest':
        manifest['repository'] = 'mallory/foreign'
    def blob(value):
        text = json.dumps(value)
        return {'__typename': 'Blob', 'isTruncated': False, 'byteSize': len(text), 'text': text}
    result = {'data': {'repository': {'nameWithOwner': 'lightning-it/.github',
        'source': {'__typename': 'Commit', 'oid': 'f' * 40 if mode == 'mixed-source' else oid},
        'manifest': blob(manifest), 'record': None if record is None else blob(record)}}}
    if mode == 'missing-record-field':
        del result['data']['repository']['record']
    if mode == 'partial-read':
        result['errors'] = []
    if mode == 'truncated':
        result['data']['repository']['manifest']['isTruncated'] = True
elif '/git/ref/' in route:
    if mode == 'missing-bootstrap':
        rc = 1
    else:
        # Every later worker sees a stale but coherent immutable snapshot.
        # Authoritative CAS still checks the actual current server ref.
        oid = '0' * 40 if worker == '501' and mode in ('stale-ref', 'lost-cas-stale') else s['oid']
        result = {'ref': 'refs/heads/lit-review-operations', 'object': {'type': 'commit', 'sha': oid}}
elif post and route.endswith('/check-runs'):
    call['marker'] = True
    marker = {'id': 99, 'name': fields['name'], 'head_sha': fields['head_sha'],
        'external_id': fields['external_id'], 'status': fields['status'], 'conclusion': fields['conclusion'],
        'app': {'id': 15368, 'slug': 'github-actions'},
        'output': {'title': fields['output[title]'], 'summary': fields['output[summary]']}}
    s['markers'].append(marker)
    result = marker
    if mode == 'lost-marker':
        rc = 42
elif route.endswith('/requested_reviewers'):
    if post:
        call['request'] = True
        if mode == 'rejected-old-pending':
            call['accepted'] = False
            s['pending_head'] = 'a' * 40
        rc = 0 if mode == 'confirmed' else 42
    else:
        result = {'users': [{'login': 'copilot-pull-request-reviewer[bot]'}] if mode == 'pending-review' or (mode in ('accepted-unknown', 'accepted-unknown-cleared', 'rejected-old-pending') and (mode != 'accepted-unknown-cleared' or worker == '500') and any(c.get('request') for c in s['calls'])) else []}
elif '/comments' in route:
    if post:
        s.setdefault('comments', []).append({'user': {'login': 'github-actions[bot]'}, 'body': fields['body']})
        rc = 42
    else:
        result = [[] if worker == '501' and mode not in ('confirmed', 'accepted-unknown', 'uncertain') else s.get('comments', [])]
elif '/reviews?' in route:
    result = [[{'commit_id': os.environ['EXPECTED_HEAD'], 'body': 'Review complete.',
                'user': {'login': 'copilot-pull-request-reviewer[bot]'}}] if mode == 'existing-review' else []]
elif route.endswith('/pulls/23'):
    result = {'number': 23, 'state': 'open', 'draft': False, 'user': {'login': 'litroc'},
              'head': {'sha': os.environ['EXPECTED_HEAD'], 'repo': {'full_name': 'lightning-it/.github'}},
              'base': {'sha': os.environ['EXPECTED_BASE'], 'repo': {'full_name': 'lightning-it/.github'}}}
elif post and route.endswith('/rerun'):
    call['rerun'] = True
    rc = 42
elif '/check-runs?' in route:
    # Exact reported regression: old marker invisible through confirmation of
    # any new marker; no consistency assumption is made about this inventory.
    visible = [] if worker == '501' or mode == 'invisible-marker' else s['markers']
    result = [{'total_count': len(visible), 'check_runs': visible}]
elif '/actions/runs/' in route:
    created = dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    result = {'id': int(route.rsplit('/', 1)[1]), 'run_attempt': 1, 'status': 'completed',
              'created_at': '2000-01-01T00:00:00Z' if mode == 'expired' else created}
else:
    raise AssertionError(args)
file.write_text(json.dumps(s))
if result is not None:
    print(json.dumps(result))
sys.exit(rc)
'''


class ReviewOperationCASTests(unittest.TestCase):
    def probe(self, mode, terminal_review=None, terminal_in_comment=False, **changes):
        claim = contracts.CopilotReviewRefreshTests._rfn('claim_review_operation')
        self.assertEqual(claim, contracts.CopilotReviewRefreshTests._rerun_shell_function('claim_review_operation'))
        script = r'''set -euo pipefail
sleep() { :; }
gh() { python3 "${MOCK_GH}" "$@"; }
timeout() { while [ "$1" != gh ]; do shift; done; "$@"; }
revalidate_refresh_state() { :; }
validate_refresh_owner_run() { test "$2" = 77 && test "$3" = 23; }
assert_refresh_rerun_budget() { :; }
usable_current_review() { :; }
read_refresh_review_state() { printf '%s' '{"event_current":true,"incomplete":0,"unresolved":0}'; }
''' + claim + '\n' + contracts.CopilotReviewRefreshTests._rfn('rerun_owner_if_review_current') + '\nrerun_owner_if_review_current\n'
        if terminal_review is not None:
            script = script.replace('usable_current_review() { :; }',
                                    contracts.CopilotReviewRefreshTests._rfn('usable_current_review'))
            script = script.replace('sleep() { :; }', 'sleep() { :; }\noa() { gh "$@"; }')
        with tempfile.TemporaryDirectory() as tmp:
            state, mock = Path(tmp) / 'state', Path(tmp) / 'mock.py'
            state.write_text(json.dumps({'mode': mode, 'oid': INITIAL,
                                         'versions': {INITIAL: {}}, 'markers': [], 'calls': []}))
            transport = MOCK
            if terminal_review is not None:
                branch = """elif '/reviews' in route:
    body = os.environ['TERMINAL_REVIEW'] if worker == '500' else 'Review complete.'
    in_comment = os.environ['TERMINAL_IN_COMMENT'] == 'true'
    review = {'id': 17, 'commit_id': os.environ['HEAD_SHA'], 'body': '' if in_comment else body,
              'user': {'login': 'copilot-pull-request-reviewer[bot]'}, 'state': 'COMMENTED'}
    if '/comments' in route:
        result = [[{'body': body}]] if in_comment else [[]]
    elif '/reviews?' in route:
        result = [[review]]
    else:
        result = review
"""
                transport = transport.replace("elif '/comments' in route:", branch + "elif '/comments' in route:")
                transport = transport.replace("worker == '501' or mode == 'invisible-marker'", "(worker == '501' and mode != 'terminal-review') or mode == 'invisible-marker'")
            mock.write_text(transport)
            outcomes = []
            for worker in ('500', '501'):
                env = {**os.environ, 'STATE': str(state), 'MOCK_GH': str(mock), 'GITHUB_RUN_ID': worker,
                       'GITHUB_RUN_ATTEMPT': '1', 'GITHUB_EVENT_NAME': 'workflow_dispatch',
                       'GITHUB_REF_PROTECTED': 'true', 'GITHUB_REF': 'refs/heads/develop',
                       'GITHUB_REPOSITORY_ID': '1112629689', 'LI219_EVENT_MODE': 'enabled', 'WORKFLOW_SHA': SOURCE, 'REPOSITORY': 'lightning-it/.github', 'PR_NUMBER': '23',
                       'owner_run_id': '77', 'HEAD_SHA': HEAD, 'BASE_SHA': BASE,
                       'refresh_expected_count': '0', 'refresh_expected_snapshot': 'null',
                       'current_external_kind': 'copilot', 'TERMINAL_REVIEW': terminal_review or '',
                       'TERMINAL_IN_COMMENT': str(terminal_in_comment).lower(), **changes}
                result = subprocess.run(['bash', '-c', script], env=env, capture_output=True,
                                        text=True, timeout=30, check=False)
                self.assertEqual(0, result.returncode, result.stderr)
                outcomes.append(result)
            return json.loads(state.read_text()), outcomes

    def test_hidden_marker_cannot_authorize_second_rerun(self):
        for mode in ('consistent', 'stale-ref', 'lost-marker'):
            with self.subTest(mode=mode):
                state, _ = self.probe(mode)
                self.assertEqual(1, sum(c.get('rerun', False) for c in state['calls']))
                self.assertEqual(1, sum(c.get('marker', False) for c in state['calls']))
                self.assertEqual(2 if mode == 'stale-ref' else 1,
                                 sum(c.get('cas', False) for c in state['calls']))
                self.assertEqual(COMMITTED, state['oid'])
                if mode == 'stale-ref':
                    second = [c for c in state['calls'] if c['worker'] == '501' and c.get('cas')]
                    self.assertEqual(INITIAL, second[0]['input']['expectedHeadOid'])

    def test_terminal_review_preserves_cas_until_later_valid_review(self):
        for marker in ('premium request quota', 'premium requests quota', 'encountered an error'):
            for in_comment in (False, True):
                with self.subTest(marker=marker, in_comment=in_comment):
                    state, outcomes = self.probe('terminal-review', terminal_review=marker.upper().replace(' ', '\n'),
                                                 terminal_in_comment=in_comment)
                    first = [call for call in state['calls'] if call['worker'] == '500']
                    self.assertFalse(any(call.get('post') or call.get('cas') for call in first))
                    self.assertIn('preserving the one verifier retry', outcomes[0].stderr)
                    self.assertEqual(['501'], [call['worker'] for call in state['calls'] if call.get('cas')])
                    self.assertEqual(['501'], [call['worker'] for call in state['calls'] if call.get('rerun')])

    def test_unknown_or_partial_cas_response_consumes_without_rerun(self):
        for mode in ('lost-cas', 'partial-cas', 'wrong-parent'):
            with self.subTest(mode=mode):
                state, outcomes = self.probe(mode)
                self.assertEqual(COMMITTED, state['oid'])
                self.assertEqual(1, sum(c.get('cas', False) for c in state['calls']))
                self.assertFalse(any(c.get('marker') or c.get('rerun') for c in state['calls']))
                self.assertIn('reconciliation only', outcomes[0].stderr)

    def test_unknown_cas_not_applied_never_sends_rerun(self):
        state, _ = self.probe('not-applied')
        self.assertEqual(INITIAL, state['oid'])
        self.assertEqual(2, sum(c.get('cas', False) for c in state['calls']))
        self.assertFalse(any(c.get('marker') or c.get('rerun') for c in state['calls']))

    def test_missing_receipt_after_confirmed_cas_stays_consumed(self):
        state, _ = self.probe('invisible-marker')
        self.assertEqual(COMMITTED, state['oid'])
        self.assertEqual(1, sum(c.get('marker', False) for c in state['calls']))
        self.assertFalse(any(c.get('rerun') for c in state['calls']))

    def test_invalid_or_mixed_snapshot_and_expiry_never_mutate(self):
        for mode in ('foreign-manifest', 'mixed-source', 'missing-record-field', 'partial-read',
                     'truncated', 'expired', 'missing-bootstrap'):
            with self.subTest(mode=mode):
                state, _ = self.probe(mode)
                self.assertFalse(any(c.get('cas') or c.get('marker') or c.get('rerun') for c in state['calls']))

    def test_unprotected_or_repeated_invocation_never_mutates(self):
        for changes in ({'GITHUB_EVENT_NAME': 'pull_request_review'}, {'GITHUB_REF_PROTECTED': 'false'},
                        {'GITHUB_REF': 'refs/heads/feature'}, {'GITHUB_RUN_ATTEMPT': '2'},
                        {'WORKFLOW_SHA': 'invalid'}):
            with self.subTest(changes=changes):
                state, _ = self.probe('consistent', **changes)
                self.assertFalse(any(c.get('cas') or c.get('marker') or c.get('rerun') for c in state['calls']))

    def test_contents_write_is_limited_to_protected_dispatch_jobs(self):
        import yaml
        refresh = yaml.safe_load((ROOT / '.github/workflows/copilot-review-refresh.yml').read_text())
        forward = refresh['jobs']['forward-review-event']
        self.assertEqual('read', forward['permissions']['contents'])
        self.assertNotIn('checks', forward['permissions'])
        for job in (refresh['jobs']['refresh-canonical-gate'],
                    yaml.safe_load((ROOT / '.github/workflows/current-revision-rerun.yml').read_text())['jobs']['rerun-protected-verifier']):
            self.assertEqual('write', job['permissions']['contents'])
            self.assertIn("github.event_name == 'workflow_dispatch'", job['if'])
            self.assertIn('github.ref_protected', job['if'])
            self.assertIn("github.actor == 'github-actions[bot]'", job['if'])


    def test_request_job_static_write_ceiling_is_protected_and_pilot_mutation_only(self):
        import yaml
        source = (ROOT / '.github/workflows/copilot-review.yml').read_text()
        workflow = yaml.safe_load(source)
        job = workflow['jobs']['request-current-revision-review']
        self.assertEqual({'actions': 'read', 'contents': 'write', 'issues': 'write', 'pull-requests': 'write'}, job['permissions'])
        for guard in ("github.event_name == 'pull_request_target'", "github.actor == 'litroc'",
                      "github.triggering_actor == 'litroc'", "github.event.pull_request.user.login == 'litroc'",
                      'github.run_attempt == 1', 'github.event.pull_request.head.repo.full_name == github.repository',
                      'github.event.pull_request.draft == false'):
            self.assertIn(guard, job['if'])
        self.assertFalse(any('uses' in step for step in job['steps']))
        call = job['steps'][-1]
        self.assertEqual('${{ github.workflow_sha }}', call['env']['TRUSTED_WORKFLOW_SHA'])
        self.assertEqual('${{ github.workflow_ref }}', call['env']['TRUSTED_WORKFLOW_REF'])
        self.assertNotIn('GH_TOKEN', job['steps'][0].get('env', {}))
        script = call['run']
        for fragment in ('${REPOSITORY}/.github/workflows/copilot-review.yml@refs/heads/${DEFAULT_BRANCH}',
                         'compare/${TRUSTED_WORKFLOW_SHA}...${default_head}',
                         '.merge_base_commit.sha == $controller'):
            self.assertLess(script.index(fragment), script.index('claim_review_operation '))
        self.assertIn('if [ "${LI219_EVENT_MODE:-disabled}" = enabled ]; then', script)
        self.assertLess(script.index('claim_review_operation '), script.index('if ! gh api --method POST'))


class ReviewRequestCASTests(unittest.TestCase):
    def probe(self, mode, new_head=False, event_mode="enabled", interrupt="", repository="lightning-it/.github"):
        import textwrap
        source = (ROOT / '.github/workflows/copilot-review.yml').read_text()
        raw = source.split("<<'CLAIM'\n", 1)[1].split('\n          CLAIM', 1)[0]
        claim = textwrap.dedent(raw)
        self.assertEqual(claim.strip(), contracts.CopilotReviewRefreshTests._rfn('claim_review_operation').strip())
        raw = source.split('          review_exists_for_head() {\n', 1)[1].split('\n  verify-current-revision-policy:', 1)[0]
        caller = textwrap.dedent('          review_exists_for_head() {\n' + raw)
        shell = """set -euo pipefail
sleep() { :; }
gh() {
  if [ "${GITHUB_RUN_ID}" = 500 ] && [[ "$*" == *"--method POST"*requested_reviewers* ]] && [ "${INTERRUPT}" = before_request ]; then exit 91; fi
  if [ "${GITHUB_RUN_ID}" = 500 ] && [[ "$*" == *"--method POST"*comments* ]] && [ "${INTERRUPT}" = before_marker ]; then exit 91; fi
  python3 "${MOCK_GH}" "$@"
}
timeout() { while [ "$1" != gh ]; do shift; done; "$@"; }
marker="<!-- mlx90-copilot-request head=${EXPECTED_HEAD} -->"
""" + caller
        with tempfile.TemporaryDirectory() as tmp:
            state, mock = Path(tmp) / 'state', Path(tmp) / 'mock.py'
            state.write_text(json.dumps({'mode': mode, 'oid': INITIAL,
                                         'versions': {INITIAL: {}}, 'markers': [], 'calls': []}))
            mock.write_text(MOCK.replace('lightning-it/.github', repository))
            (Path(tmp) / 'request-operation.sh').write_text(claim)
            (Path(tmp) / 'review_request_continuation.py').write_text(
                (ROOT / 'scripts/review_request_continuation.py').read_text())
            workers = [('500', BASE, HEAD), ('501', 'd' * 40, HEAD)]
            if new_head:
                workers.append(('502', 'd' * 40, 'e' * 40))
            outcomes = []
            for worker, base, head in workers:
                env = {**os.environ, 'STATE': str(state), 'MOCK_GH': str(mock), 'RUNNER_TEMP': tmp,
                       'GITHUB_RUN_ID': worker, 'GITHUB_RUN_ATTEMPT': '1', 'GITHUB_EVENT_NAME': 'pull_request_target',
                       'GITHUB_REF_PROTECTED': 'true', 'GITHUB_REF': 'refs/heads/develop',
                       'WORKFLOW_SHA': SOURCE, 'GITHUB_REPOSITORY_ID': '1112629689', 'LI219_EVENT_MODE': event_mode, 'INTERRUPT': interrupt,
                       'REPOSITORY': repository, 'PR_NUMBER': '23', 'EXPECTED_HEAD': head, 'EXPECTED_BASE': base,
                       'reviewer': 'copilot-pull-request-reviewer[bot]', 'requested_reviewers_url': f'repos/{repository}/pulls/23/requested_reviewers',
                       'UNABLE_REVIEW_MARKER': 'unable to review this pull request', 'NO_FILES_REVIEW_MARKER': 'was not able to review any files',
                       'QUOTA_EXHAUSTED_MARKER': 'quota exhausted', 'QUOTA_EXCEEDED_MARKER': 'quota exceeded', 'SUPPRESSED_COMMENTS_MARKER': 'suppressed comments'}
                result = subprocess.run(['bash', '-c', shell], env=env, capture_output=True, text=True, timeout=30, check=False)
                self.assertIn(result.returncode, (0, 1, 91), result.stderr)
                outcomes.append(result.returncode)
            final = json.loads(state.read_text())
            final['outcomes'] = outcomes
            return final

    def test_invisible_comment_stale_ref_new_run_and_base_cannot_repeat_request(self):
        for mode in ('consistent', 'stale-ref'):
            with self.subTest(mode=mode):
                state = self.probe(mode, new_head=True)
                requests = [c for c in state['calls'] if c.get('request')]
                self.assertEqual(['500', '502'], [c['worker'] for c in requests])
                records = list(state['versions'][state['oid']].values())
                self.assertEqual(2, len(records))
                self.assertEqual({f'li219-review-request:v1:1112629689:23:{HEAD}',
                                  'li219-review-request:v1:1112629689:23:' + 'e' * 40},
                                 {record['operation'] for record in records})
                self.assertTrue(all(record['action'] == 'request' for record in records))

    def test_lost_cas_or_existing_review_or_pending_request_never_calls_ai(self):
        for mode in ('lost-cas', 'partial-cas', 'existing-review', 'pending-review', 'missing-bootstrap'):
            with self.subTest(mode=mode):
                state = self.probe(mode)
                self.assertFalse(any(c.get('request') for c in state['calls']))
                if mode in ('existing-review', 'pending-review'):
                    self.assertFalse(any(c.get('cas') for c in state['calls']))


    def test_legacy_confirmed_request_precedes_marker_without_cas(self):
        for repository in ('lightning-it/.github', 'lightning-it/nonpilot'):
            for mode in ('confirmed',):
                with self.subTest(repository=repository, mode=mode):
                    state = self.probe(mode, event_mode='disabled', repository=repository)
                    calls = state['calls']
                    self.assertFalse(any(c.get('cas') for c in calls))
                    effects = [c for c in calls if c.get('post')]
                    self.assertEqual(2, len(effects))
                    self.assertTrue(effects[0].get('request'))
                    self.assertTrue(effects[1]['route'].endswith('/comments'))
                    self.assertEqual(1, len(state['comments']))

    def test_interrupted_legacy_pre_request_does_not_consume_marker_but_pilot_cas_does(self):
        for event_mode, expected_workers in (('disabled', ['501']), ('enabled', [])):
            with self.subTest(event_mode=event_mode):
                state = self.probe('confirmed', event_mode=event_mode, interrupt='before_request')
                self.assertEqual(expected_workers, [c['worker'] for c in state['calls'] if c.get('request')])
                self.assertEqual(event_mode == 'enabled', any(c.get('cas') for c in state['calls']))
                first_posts = [c for c in state['calls'] if c['worker'] == '500' and c.get('post')]
                self.assertEqual(0 if event_mode == 'disabled' else 1, len(first_posts))

    def test_interruption_before_marker_preserves_legacy_request_and_pilot_consumption(self):
        for event_mode, expected_workers in (('disabled', ['500']), ('enabled', [])):
            state = self.probe('accepted-unknown', event_mode=event_mode, interrupt='before_marker')
            self.assertEqual(expected_workers, [c['worker'] for c in state['calls'] if c.get('request')])
            self.assertEqual([], state.get('comments', []))

    def test_unknown_unconfirmed_response_has_no_same_invocation_retry_in_either_mode(self):
        for event_mode in ('disabled', 'enabled'):
            state = self.probe('uncertain', event_mode=event_mode)
            requests = [c for c in state['calls'] if c.get('request')]
            self.assertTrue(all(sum(c['worker'] == worker for c in requests) <= 1 for worker in ('500', '501')))
            if event_mode == 'enabled':
                self.assertEqual(1, len(requests))
            else:
                self.assertEqual([], state.get('comments', []))
                self.assertFalse(any(c.get('cas') for c in state['calls']))


    def test_lost_original_post_response_never_publishes_accepted_marker(self):
        for flag in ("", "disabled", "enabled"):
            for new_head in (False, True):
                with self.subTest(flag=flag, new_head=new_head):
                    state = self.probe("accepted-unknown", new_head=new_head, event_mode=flag)
                    self.assertEqual(1, state["outcomes"][0])
                    self.assertEqual(1, sum(bool(c.get("request")) for c in state["calls"]))
                    self.assertEqual(int(flag == "enabled"), sum(bool(c.get("cas")) for c in state["calls"]))
                    comments = state.get("comments", [])
                    self.assertEqual(int(flag == "enabled"), len(comments))
                    # Pilot reservation predates POST and proves consumption only.
                    self.assertTrue(all("request reserved" in item["body"] for item in comments))
                    for index, call in enumerate(state["calls"]):
                        if call.get("request"):
                            self.assertFalse(any(later.get("post") and later["route"].endswith('/comments')
                                                 for later in state["calls"][index + 1:]))

    def test_lost_original_post_keeps_claim_consumed_after_pending_clears(self):
        for new_head in (False, True):
            with self.subTest(new_head=new_head):
                state = self.probe("accepted-unknown-cleared", new_head=new_head)
                expected = ["500", "502"] if new_head else ["500"]
                self.assertEqual(expected, [c["worker"] for c in state["calls"] if c.get("request")])
                self.assertEqual(len(expected), sum(bool(c.get("cas")) for c in state["calls"]))
                self.assertTrue(all("request reserved" in item["body"] for item in state.get("comments", [])))


    def test_rejected_original_post_then_old_pending_never_accepts_new_head(self):
        for flag in ("", "disabled", "enabled"):
            for new_head in (False, True):
                with self.subTest(flag=flag, new_head=new_head):
                    state = self.probe("rejected-old-pending", new_head=new_head, event_mode=flag)
                    attempts = [c for c in state["calls"] if c.get("request")]
                    self.assertEqual(1, len(attempts))
                    self.assertIs(False, attempts[0]["accepted"])
                    self.assertEqual(BASE, state["pending_head"])
                    self.assertEqual(1, state["outcomes"][0])
                    self.assertEqual(int(flag == "enabled"), sum(bool(c.get("cas")) for c in state["calls"]))
                    comments = state.get("comments", [])
                    self.assertEqual(int(flag == "enabled"), len(comments))
                    self.assertTrue(all("request reserved" in item["body"] for item in comments))


class PilotActivationTests(unittest.TestCase):
    def test_every_component_uses_identical_opt_in_and_exact_allowlist(self):
        import yaml
        names = ('copilot-review', 'copilot-review-refresh', 'current-revision-rerun',
                 'supplementary-current-revision-required', 'review-event-reconcile')
        flags = []
        for name in names:
            workflow = yaml.safe_load((ROOT / f'.github/workflows/{name}.yml').read_text())
            flags.append(workflow['env']['LI219_EVENT_MODE'])
        self.assertEqual(1, len(set(flags)))
        self.assertIn("vars.LI219_EVENT_MODE == 'enabled'", flags[0])
        self.assertIn("&& 'enabled' || 'disabled'", flags[0])
        pilots = json.loads(flags[0].split("fromJSON('")[1].split("')")[0])
        self.assertEqual(['lightning-it/.github', 'lightning-it/shared-assets-lit',
                          'lightning-it/ansible-collection-supplementary'], pilots)

    def test_disabled_reconciler_and_nonpilot_never_read_or_dispatch(self):
        from unittest.mock import patch
        from tests.test_review_event_reconcile import EVENT
        for repository, mode in (('lightning-it/.github', ''), ('lightning-it/shared-assets-lit', 'disabled'),
                                 ('lightning-it/nonpilot', 'enabled')):
            with patch.dict(os.environ, LI219_EVENT_MODE=mode), patch.object(EVENT, 'api') as api:
                EVENT.reconcile(repository, None)
                api.assert_not_called()

    def test_legacy_locator_still_waits_and_enabled_pilot_reaches_admission(self):
        import textwrap
        workflow = (ROOT / '.github/workflows/supplementary-current-revision-required.yml').read_text()
        step = workflow.split('      - name: Await the exact protected producer run terminal state', 1)[1]
        shell = textwrap.dedent(step.split('        run: |\n', 1)[1].split('\n      - name:', 1)[0])
        prefix = "gh() { printf '%s' '[{\"check_runs\":[]}]'; }\nsleep() { exit 91; }\n"
        with tempfile.TemporaryDirectory() as tmp:
            for mode, expected in (('disabled', 91), ('enabled', 0), ('', 91)):
                result = subprocess.run(['bash', '-c', prefix + shell], capture_output=True, text=True, check=False,
                                        env={**os.environ, 'LI219_EVENT_MODE': mode, 'GITHUB_OUTPUT': tmp + '/out',
                                             'PR_AUTHOR_TYPE': 'User', 'REPOSITORY': 'lightning-it/.github',
                                             'PR_NUMBER': '23', 'EVENT_HEAD': HEAD, 'EVENT_BASE': BASE})
                self.assertEqual(expected, result.returncode, result.stderr)

    def test_wait_budgets_are_legacy_by_default(self):
        import re
        import textwrap
        for workflow, variable, legacy in (('copilot-review', 'review_observations', 40),
                                          ('copilot-review', 'resolution_observations', 20),
                                          ('supplementary-current-revision-required', 'evidence_limit', 450),
                                          ('supplementary-current-revision-required', 'producer_limit', 60)):
            source = (ROOT / f'.github/workflows/{workflow}.yml').read_text()
            init = re.search(r'(?m)^ +'+variable+r'=\d+\n +\[ .*\n', source).group()
            for mode, expected in (('', legacy), ('disabled', legacy), ('enabled', 1)):
                result = subprocess.run(['bash', '-c', textwrap.dedent(init) + f'printf "%s" "${{{variable}}}"'],
                                        capture_output=True, text=True, check=False,
                                        env={**os.environ, 'LI219_EVENT_MODE': mode})
                self.assertEqual(str(expected), result.stdout)


class RequestSourceAndPolicyTests(unittest.TestCase):
    def test_actual_request_source_prefix_rejects_untrusted_bindings(self):
        import textwrap
        import yaml
        job = yaml.safe_load((ROOT / '.github/workflows/copilot-review.yml').read_text())['jobs']['request-current-revision-review']
        script = job['steps'][-1]['run'].split('reviewer_login=', 1)[0]
        run = {'event': 'pull_request_target', 'name': 'Current revision review gate',
               'path': '.github/workflows/copilot-review.yml', 'head_branch': 'fix/final', 'head_sha': HEAD,
               'repository': {'full_name': 'lightning-it/.github'}, 'head_repository': {'full_name': 'lightning-it/.github'}}
        pr = {'state': 'open', 'draft': False, 'user': {'login': 'litroc'},
              'base': {'ref': 'develop', 'sha': BASE, 'repo': {'full_name': 'lightning-it/.github'}},
              'head': {'sha': HEAD, 'repo': {'full_name': 'lightning-it/.github'}}}
        shell = r'''gh() {
  case "$*" in
    *'/branches/develop'*) printf %s "${WORKFLOW_SHA}" ;;
    *'/compare/'*) printf %s "${ANCESTRY}" ;;
    *'/actions/runs/'*) printf %s "${RUN}" ;;
    *'/pulls/23') printf %s "${PR}" ;;
    *) exit 99 ;;
  esac
}
''' + textwrap.dedent(script) + '\nprintf AUTHORIZED\n'
        cases = [({}, True), ({'TRUSTED_WORKFLOW_REF': 'lightning-it/.github/.github/workflows/copilot-review.yml@refs/pull/23/merge'}, False),
                 ({'DEFAULT_BRANCH': 'main'}, False), ({'TRUSTED_WORKFLOW_SHA': 'malformed'}, False),
                 ({'ANCESTRY': json.dumps({'status': 'behind'})}, False)]
        for field, value in (('event', 'pull_request'), ('path', '.github/workflows/foreign.yml'),
                             ('head_sha', BASE), ('repository', {'full_name': 'mallory/foreign'}),
                             ('head_repository', {'full_name': 'mallory/fork'})):
            cases.append(({'RUN': json.dumps({**run, field: value})}, False))
        for field, value in (('state', 'closed'), ('draft', True), ('user', {'login': 'mallory'}),
                             ('head', {'sha': BASE, 'repo': {'full_name': 'lightning-it/.github'}})):
            cases.append(({'PR': json.dumps({**pr, field: value})}, False))
        for changes, accepted in cases:
            result = subprocess.run(['bash', '-c', shell], capture_output=True, text=True, check=False,
                env={**os.environ, 'EXPECTED_BASE': BASE, 'EXPECTED_HEAD': HEAD, 'EXPECTED_HEAD_REF': 'fix/final',
                     'TRUSTED_WORKFLOW_SHA': SOURCE, 'WORKFLOW_SHA': SOURCE, 'DEFAULT_BRANCH': 'develop',
                     'TRUSTED_WORKFLOW_REF': 'lightning-it/.github/.github/workflows/copilot-review.yml@refs/heads/develop',
                     'GITHUB_RUN_ID': '500', 'REPOSITORY': 'lightning-it/.github', 'PR_NUMBER': '23',
                     'ANCESTRY': json.dumps({'status': 'identical'}), 'RUN': json.dumps(run), 'PR': json.dumps(pr), **changes})
            self.assertEqual(accepted, result.returncode == 0 and result.stdout.endswith('AUTHORIZED'), result.stderr)

    def test_canonical_amendment_and_instruction_hash_are_scoped_and_bound(self):
        import hashlib
        agents = (ROOT / 'AGENTS.md').read_bytes()
        policy = agents.decode()
        instructions = (ROOT / '.github/copilot-instructions.md').read_text()
        adr = (ROOT / 'docs/adr/li219-event-finalization-contract.md').read_text()
        self.assertIn('AGENTS_SHA256: ' + hashlib.sha256(agents).hexdigest(), instructions)
        for text in ('2878440201', '2887909377', '2026-10-05', 'LI219_EVENT_MODE=enabled',
                     'lightning-it/.github', 'lightning-it/shared-assets-lit', 'lightning-it/ansible-collection-supplementary',
                     'Attempt 2 must never request AI review', 'Non-pilots and disabled/default mode retain the legacy'):
            self.assertIn(text, policy)
        self.assertIn('version 12', policy)
        self.assertIn('version 13', policy)
        self.assertIn('intermediate `synchronize` pushes must not trigger AI review', policy)
        self.assertNotIn('explicitly supersedes the older blanket prohibition', adr)
        self.assertIn('only after a successful response', adr)
