"""Exercise the Core handoff body with distinct default and PR-base sources."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]


class DefaultControllerHandoffTests(unittest.TestCase):
    def handoff(self, branch, *, overrides=None, drift=False):
        workflow = yaml.safe_load((ROOT / '.github/workflows/copilot-review.yml').read_text())
        body = workflow['jobs']['request-protected-verifier-reevaluation']['steps'][1]['run']
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            state = path / 'state.json'
            state.write_text(json.dumps({'reads': 0, 'posts': [], 'drift': drift}))
            shim = path / 'gh'
            shim.write_text('''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
p = Path(os.environ['STATE'])
s = json.loads(p.read_text())
a = sys.argv[1:]
if '--method' in a and a[a.index('--method') + 1] == 'POST':
    s['posts'].append(a)
    value = {}
elif a[-1] == 'repos/lightning-it/.github':
    value = {'full_name': 'lightning-it/.github', 'default_branch': 'develop'}
elif a[-1] == 'repos/lightning-it/.github/branches/develop':
    s['reads'] += 1
    value = {'name': 'develop', 'protected': True,
             'commit': {'sha': ('e' if s['drift'] and s['reads'] == 2 else 'd') * 40}}
elif a[-1] == 'repos/lightning-it/.github/branches/main':
    value = {'name': 'main', 'protected': True, 'commit': {'sha': 'a' * 40}}
else:
    raise SystemExit('unexpected route: ' + repr(a))
p.write_text(json.dumps(s))
print(json.dumps(value))
''')
            shim.chmod(0o755)
            # Election has separate whole-function tests. Here only its output
            # and the gh transport are seams; the entire dispatch body is real.
            (path / 'current-revision-producer-owner.sh').write_text(
                'oa() { gh api "$@"; }\neo() { printf 77; }\n'
            )
            env = {
                **os.environ, 'PATH': str(path) + os.pathsep + os.environ['PATH'],
                'STATE': str(state), 'RUNNER_TEMP': str(path),
                'BASE_REF': branch, 'DEFAULT_BRANCH': 'develop',
                'WORKFLOW_SHA': 'd' * 40, 'GITHUB_SHA': ('d' if branch == 'develop' else 'a') * 40,
                'TRUSTED_WORKFLOW_REF': 'lightning-it/.github/.github/workflows/copilot-review.yml@refs/heads/develop',
                'GITHUB_REF': 'refs/heads/' + branch, 'GITHUB_REF_PROTECTED': 'true',
                'REPOSITORY': 'lightning-it/.github',
                'EXPECTED_BASE': ('d' if branch == 'develop' else 'a') * 40,
                'EXPECTED_HEAD': 'b' * 40, 'EXPECTED_HEAD_REF': 'feature',
                'PR_NUMBER': '23', 'PRODUCER_RUN_ID': '77', 'OWNER_RUN_ID': '77',
                'PRODUCER_RUN_ATTEMPT': '1', 'GITHUB_RUN_ID': '77',
                **(overrides or {}),
            }
            result = subprocess.run(['bash', '-c', body], env=env, text=True,
                                    capture_output=True, check=False)
            return result, json.loads(state.read_text())

    def test_default_controller_dispatches_to_independent_pr_base(self):
        for branch in ('develop', 'main'):
            with self.subTest(branch=branch):
                result, state = self.handoff(branch)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual(4 if branch == 'develop' else 2, state['reads'])
                self.assertEqual(1, len(state['posts']))
                self.assertIn('ref=' + branch, state['posts'][0])
                self.assertIn('inputs[expected_base]=' + ('d' if branch == 'develop' else 'a') * 40, state['posts'][0])
                self.assertFalse(any('requested_reviewers' in value for value in state['posts'][0]))

    def test_wrong_or_drifting_execution_controller_never_dispatches(self):
        cases = (
            {'DEFAULT_BRANCH': 'main'}, {'GITHUB_REF': 'refs/heads/develop'},
            {'WORKFLOW_SHA': 'a' * 40}, {'GITHUB_SHA': 'd' * 40},
            {'EXPECTED_BASE': 'e' * 40},
            {'TRUSTED_WORKFLOW_REF': 'lightning-it/.github/.github/workflows/copilot-review.yml@refs/heads/main'},
            {'GITHUB_REF_PROTECTED': 'false'},
        )
        for overrides in cases:
            with self.subTest(overrides=overrides):
                result, state = self.handoff('main', overrides=overrides)
                self.assertNotEqual(0, result.returncode)
                self.assertEqual([], state['posts'])
        result, state = self.handoff('main', drift=True)
        self.assertNotEqual(0, result.returncode)
        self.assertEqual(2, state['reads'])
        self.assertEqual([], state['posts'])
