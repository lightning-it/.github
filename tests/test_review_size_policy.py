from __future__ import annotations

from contextlib import redirect_stderr
import io
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / 'scripts/lit-push-ready.py'


class ReviewSizePolicyTests(unittest.TestCase):
    def setUp(self):
        self.ns = runpy.run_path(str(ENGINE))
        self.g = self.ns['main'].__globals__

    def test_legacy_config_is_advisory_and_warning_can_be_disabled(self):
        threshold = self.ns['review_warning_threshold']
        for review in ({'max_diff_bytes': 200000}, {'warn_diff_bytes': 500000},
                       {'max_diff_bytes': 1, 'warn_diff_bytes': 500000}, {}):
            self.assertEqual(500000, threshold(review))
        self.assertIsNone(threshold({'max_diff_bytes': 200000, 'warn_diff_bytes': None}))
        for review in ({'max_diff_bytes': True}, {'max_diff_bytes': 0},
                       {'warn_diff_bytes': False}, {'warn_diff_bytes': '500000'},
                       {'warn_diff_bytes': -1}, {'unknown': 1}):
            with self.assertRaises(RuntimeError):
                threshold(review)

    def planned(self, size, review, untracked=None, tracked=None):
        patch = tracked if tracked is not None else '+' + 'x' * (size - 1)
        def git(*args):
            if args[0] == 'rev-parse':
                return 'a' * 40
            if '--name-only' in args:
                return 'ordinary.txt\0'
            return patch
        overrides = {
            'git_output': git, 'tree_fingerprint': lambda: 'f' * 64,
            'resolve_base': lambda *a, **kw: ('refs/remotes/origin/develop', 'b' * 40, 'b' * 40),
            'untracked_names': lambda: ['new.txt'] if untracked is not None else [],
            'read_repository_file': mock.Mock(return_value=(untracked, 0o100644)),
            'ensure_review_safe': mock.Mock(), 'secret_fixture_manifest_for_change': lambda *a, **kw: {},
        }
        stream = io.StringIO()
        with mock.patch.dict(self.g, overrides), redirect_stderr(stream):
            change = self.ns['planned_change']({'review': review})
        return change, stream.getvalue(), overrides

    def test_complete_patch_warning_boundaries_do_not_truncate_or_enforce_old_ceiling(self):
        for size in (199999, 200000, 499999, 500000, 500001, 5_000_001):
            with self.subTest(size=size):
                change, warning, _ = self.planned(size, {'max_diff_bytes': 200000})
                self.assertEqual(size, len(change.diff.encode()))
                self.assertEqual(size >= 500000, 'Planning notice:' in warning)
                if warning:
                    self.assertIn('all deterministic checks still run', warning)
                    self.assertIn('No automatic PR splitting', warning)
        _, warning, _ = self.planned(500001, {'warn_diff_bytes': None})
        self.assertEqual('', warning)

    def test_untracked_content_uses_fingerprint_resource_budget_not_review_size(self):
        change, warning, overrides = self.planned(500001, {'max_diff_bytes': 1}, untracked=b'new content\n')
        self.assertIn('+new content\n', change.diff)
        self.assertIn('new.txt', change.untracked_sha256)
        overrides['read_repository_file'].assert_called_once_with(
            'new.txt', purpose='Untracked fingerprint', max_bytes=100_000_000)
        self.assertIn('Planning notice:', warning)
        with self.assertRaisesRegex(RuntimeError, 'binary content'):
            self.planned(0, {}, tracked='GIT binary patch\n')
        with self.assertRaisesRegex(RuntimeError, 'binary untracked'):
            self.planned(1, {}, untracked=b'\0')

    def test_safe_file_reader_still_rejects_overflow_and_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'file').write_bytes(b'12345')
            (root / 'link').symlink_to('file')
            with mock.patch.dict(self.g, {'ROOT': root}):
                with self.assertRaisesRegex(RuntimeError, 'exceeds 4 bytes'):
                    self.ns['read_repository_file']('file', purpose='Metadata', max_bytes=4)
                with self.assertRaisesRegex(RuntimeError, 'safely inspect'):
                    self.ns['read_repository_file']('link', purpose='Metadata', max_bytes=10)

    def test_unbudgeted_own_mlx_fails_before_action_without_rewriting_old_receipts(self):
        import yaml
        workflow = yaml.safe_load((ROOT / '.github/workflows/release-bot-exact-head-review.yml').read_text())
        steps = next(job['steps'] for job in workflow['jobs'].values()
                     if any(str(step.get('uses', '')).startswith('openai/codex-action@')
                            for step in job.get('steps', [])))
        index = next(i for i, step in enumerate(steps)
                     if str(step.get('uses', '')).startswith('openai/codex-action@'))
        barrier, action = steps[index - 1:index + 1]
        self.assertEqual("steps.dedupe.outputs.reuse != 'true'", barrier['if'])
        self.assertEqual(barrier['if'], action['if'])
        self.assertNotIn('continue-on-error', barrier)
        self.assertNotIn('always()', action['if'])
        result = subprocess.run(['bash', '-eu', '-c', barrier['run']], capture_output=True, text=True, check=False,
                                env={**os.environ, 'BUDGETED_GATEWAY_INSTALLED': ''})
        self.assertEqual(1, result.returncode)
        self.assertIn('complete-request token budget is not bound', result.stderr)
        self.assertIn('schema:4,', (ROOT / '.github/workflows/release-bot-exact-head-review.yml').read_text())
        self.assertIn('"schema_version": 5', (ROOT / 'scripts/materialize-exact-revision-review.py').read_text())

    def test_required_accepts_bound_reuse_with_skipped_guard_but_rejects_failed_new_call(self):
        source = (ROOT / '.github/workflows/supplementary-current-revision-required.yml').read_text()
        start = source.index('                  [.[].jobs[]?] as $jobs', source.index('id: release-app-producer'))
        end = source.index("' <<<\"${jobs_pages}\" >/dev/null", start)
        predicate = source[start:end]
        steps = [
            {'name': 'Require complete-request token budget before a new model call', 'status': 'completed', 'conclusion': 'skipped'},
            {'name': 'Run protected history-free Exact-Revision Codex review', 'status': 'completed', 'conclusion': 'skipped'},
            {'name': 'Re-prove exact revision and enforce the Codex verdict', 'status': 'completed', 'conclusion': 'success'},
        ]
        review = {'name': 'Current revision review', 'status': 'completed', 'conclusion': 'success', 'steps': steps}
        def evaluate(job):
            result = subprocess.run(['jq', '-e', '--argjson', 'terminal_helper_handoff', 'false',
                                     '--argjson', 'terminal_success_handoff', 'true', predicate],
                                    input=json.dumps([{'jobs': [job]}]), text=True, capture_output=True, check=False)
            return result.returncode
        self.assertEqual(0, evaluate(review))
        failed = {**review, 'conclusion': 'failure', 'steps': [
            {**steps[0], 'conclusion': 'failure'}, steps[1], {**steps[2], 'conclusion': 'skipped'}]}
        self.assertEqual(1, evaluate(failed))
        # Historical success has no budget guard and retains the original
        # named-step contract; no new request is implied by accepting it.
        historical = {**review, 'steps': [{**steps[1], 'conclusion': 'success'}, steps[2]]}
        self.assertEqual(0, evaluate(historical))

    def test_large_diff_runs_complete_integration_profile_and_propagates_failure(self):
        # Real local Git/merge/worktree/profile execution in the pinned test
        # container. Only remote fetch is replaced; no nested container needed.
        environment = {k: v for k, v in os.environ.items()
                       if k not in ('GIT_DIR', 'GIT_COMMON_DIR', 'GIT_WORK_TREE')}
        with tempfile.TemporaryDirectory(dir=os.environ.get('HOME')) as directory:
            root = Path(directory) / 'repo'
            root.mkdir()
            record = Path(directory) / 'checks.log'
            def git(*args):
                return subprocess.check_output(['git', '-C', str(root), *args], env=environment, stderr=subprocess.STDOUT).decode().strip()
            git('init', '-b', 'fix/large')
            git('config', 'user.email', 'fixture@example.invalid')
            git('config', 'user.name', 'Fixture')
            for path in ('scripts/lit-push-ready.py', '.lit/push-ready.json', 'AGENTS.md', '.github/copilot-instructions.md'):
                target = root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / path, target)
            profile = root / 'scripts/lit-ci-profile.sh'
            profile.write_text('#!/usr/bin/env bash\nset -eu\nprintf "lint\\ntests\\nbuild\\n" >> ' + str(record) + '\nexit "${FIXTURE_EXIT:-0}"\n')
            profile.chmod(0o755)
            git('add', '.')
            git('commit', '-m', 'base')
            git('update-ref', 'refs/remotes/origin/develop', 'HEAD')
            (root / 'large.txt').write_text('ordinary change\n' * 40000)
            git('add', 'large.txt')
            git('commit', '-m', 'large complete change')
            config = json.loads((root / '.lit/push-ready.json').read_text())
            actual_environment = self.ns['minimal_check_environment']
            for code in (0, 7):
                record.unlink(missing_ok=True)
                def check_environment(state_root):
                    return {**actual_environment(state_root), 'FIXTURE_EXIT': str(code)}
                overrides = {'ROOT': root, 'CONFIG': root / '.lit/push-ready.json',
                             'AGENTS': root / 'AGENTS.md', 'COPILOT': root / '.github/copilot-instructions.md',
                             '__file__': str(root / 'scripts/lit-push-ready.py'),
                             'refresh_authoritative_base': lambda _: None,
                             'minimal_check_environment': check_environment}
                stream = io.StringIO()
                with mock.patch.dict(self.g, overrides), mock.patch('sys.argv', ['lit-push-ready.py', 'validate']), redirect_stderr(stream):
                    result = self.ns['main']()
                self.assertEqual(0 if code == 0 else 1, result, stream.getvalue())
                self.assertEqual('lint\ntests\nbuild\n', record.read_text())
                self.assertIn('Planning notice:', stream.getvalue())
                self.assertEqual('', git('status', '--porcelain'))
                self.assertEqual(1, len(git('for-each-ref', '--format=%(refname)', 'refs/heads').splitlines()))
            self.assertEqual({'warn_diff_bytes': 500000}, config['review'])


if __name__ == '__main__':
    unittest.main()
