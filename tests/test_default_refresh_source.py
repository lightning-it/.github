"""Default-mode refresh must reach protected source, never the PR merge source."""
import json
import os
from pathlib import Path
import subprocess
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / '.github/workflows/copilot-review-refresh.yml'


class DefaultRefreshSourceTests(unittest.TestCase):
    def test_native_merge_source_is_rejected_and_protected_source_is_required(self):
        text = WORKFLOW.read_text()
        function = 'validate_live_pr_tuple() {' + text.split('validate_live_pr_tuple() {', 1)[1].split('\n          }', 1)[0] + '\n}'
        base, head = 'a' * 40, 'b' * 40
        pr = {'state': 'open', 'draft': False, 'user': {'login': 'litroc'},
              'base': {'ref': 'develop', 'sha': base, 'repo': {'full_name': 'lightning-it/.github'}},
              'head': {'ref': 'fix/test', 'sha': head, 'repo': {'full_name': 'lightning-it/.github'}}}
        branch = {'name': 'develop', 'protected': True, 'commit': {'sha': base}}
        environment = {**os.environ, 'BASE_REF': 'develop', 'BASE_SHA': base,
                       'WORKFLOW_SHA': base, 'GITHUB_REF': 'refs/heads/develop',
                       'REPOSITORY': 'lightning-it/.github', 'PR_NUMBER': '854',
                       'PR_AUTHOR': 'litroc', 'HEAD_REF': 'fix/test', 'HEAD_SHA': head,
                       'HEAD_REPOSITORY': 'lightning-it/.github', 'PR': json.dumps(pr),
                       'BRANCH': json.dumps(branch)}
        stub = '''oa() {
  case "$1" in
    */branches/develop) printf '%s' "${BRANCH}" ;;
    */pulls/854) printf '%s' "${PR}" ;;
    *) return 99 ;;
  esac
}
'''
        def run(**overrides):
            return subprocess.run(['bash', '-c', 'set -eu\n' + stub + function + '\nvalidate_live_pr_tuple'],
                                  env={**environment, **overrides}, capture_output=True, text=True).returncode
        self.assertEqual(0, run())
        # The real failing invocation used a synthetic merge ref and merge SHA.
        self.assertNotEqual(0, run(GITHUB_REF='refs/pull/854/merge', WORKFLOW_SHA='c' * 40))
        for changes in ({'WORKFLOW_SHA': 'c' * 40}, {'GITHUB_REF': 'refs/heads/main'},
                        {'HEAD_SHA': 'c' * 40}, {'PR_AUTHOR': 'other'},
                        {'BRANCH': json.dumps({**branch, 'protected': False})},
                        {'BRANCH': json.dumps({**branch, 'commit': {'sha': 'c' * 40}})}):
            with self.subTest(changes=changes):
                self.assertNotEqual(0, run(**changes))

    def test_root_default_route_has_no_candidate_writer_or_new_review_request(self):
        document = yaml.safe_load(WORKFLOW.read_text())
        jobs = document['jobs']
        forward = jobs['forward-review-event']
        self.assertIn("github.repository == 'lightning-it/.github'", forward['if'])
        self.assertEqual({'actions': 'write', 'contents': 'read', 'pull-requests': 'read'}, forward['permissions'])
        script = forward['steps'][0]['run']
        self.assertIn('"repos/${REPOSITORY}/pulls/${PR_NUMBER}/reviews?per_page=100"', script)
        self.assertIn('.commit_id == $head and .user.login == "copilot-pull-request-reviewer[bot]"', script)
        self.assertEqual(1, script.count('api --method POST'))
        self.assertIn('actions/workflows/copilot-review-refresh.yml/dispatches', script)
        self.assertNotIn('requested_reviewers', script)
        self.assertNotIn('/rerun', script)
        consumer = jobs['refresh-canonical-gate']
        for guard in ("inputs.operation != 'continue'", "github.ref_protected",
                      "github.actor == 'github-actions[bot]'",
                      "github.triggering_actor == 'github-actions[bot]'", 'github.run_attempt == 1'):
            self.assertIn(guard, consumer['if'])
        self.assertEqual({'actions': 'write', 'checks': 'write', 'contents': 'write', 'pull-requests': 'read'}, consumer['permissions'])
        self.assertNotIn('issues', consumer['permissions'])
        self.assertIn('test "${WORKFLOW_SHA}" = "${LOCATOR_BASE}"', consumer['steps'][1]['run'])
        self.assertIn('test "${GITHUB_REF}" = "refs/heads/${branch}"', consumer['steps'][1]['run'])


if __name__ == '__main__':
    unittest.main()
