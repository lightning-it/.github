"""A candidate cannot replace its checks, profile, head or credential boundary."""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import workflow_common_quality as quality
import workflow_control as control
from test_workflow_control import BASE, HEAD, REPO, SOURCE, pull, run

ROOT = Path(__file__).resolve().parents[1]
RAW = b'schema_version: 1\nrepository: .github\nrepository_type: repository_profile\n'


class CommonQualityTests(unittest.TestCase):
    def environment(self):
        job = {'workflow_repository': REPO, 'workflow_file_path': control.WORKFLOW,
               'workflow_sha': SOURCE, 'check_run_id': 123}
        return {'GITHUB_REPOSITORY': REPO, 'GITHUB_RUN_ID': '10',
                'NATIVE_JOB': json.dumps(job), 'NATIVE_PULL_NUMBER': '3',
                'NATIVE_HEAD': HEAD, 'NATIVE_BASE': BASE}

    def prepare(self, native=None, subject=None):
        api = Mock()
        api.call.side_effect = [run() if native is None else native,
                                pull() if subject is None else subject]
        api.file.return_value = RAW
        with patch.object(quality, 'policy') as policy:
            result = quality.prepare(api, self.environment())
        policy.assert_called_once_with(api, REPO, BASE, SOURCE)
        api.file.assert_called_once_with(REPO, '.lit/repository.yml', BASE)
        return result

    def test_profile_is_read_only_from_protected_base(self):
        self.assertEqual({'version': 1, 'repository': REPO, 'source_sha': SOURCE,
                          'head': HEAD, 'base': BASE, 'repository_type': 'repository_profile'},
                         self.prepare())

    def test_candidate_defined_workflow_cannot_prepare_policy(self):
        with self.assertRaisesRegex(control.ControlError, 'native-required-origin'):
            self.prepare(native=run() | {'workflow_url': 'https://api.github.com/repos/x/actions/workflows/77'})

    def test_changed_head_base_or_closed_subject_blocks_preparation(self):
        for value in (pull(state='closed'), pull(head=pull()['head'] | {'sha': 'd' * 40}),
                      pull(base=pull()['base'] | {'sha': 'd' * 40})):
            with self.subTest(value=value), self.assertRaises(control.ControlError):
                self.prepare(subject=value)

    def test_quality_runs_on_draft_while_review_stays_blocked(self):
        self.assertEqual(self.prepare(), self.prepare(subject=pull(draft=True)))
        api = Mock()
        api.call.return_value = pull(draft=True)
        with self.assertRaisesRegex(control.ControlError, 'pull-not-reviewable'):
            control.live_pull(api, REPO, 3)

    def test_metadata_identity_and_resource_bounds(self):
        for raw in (b'', b'x' * 16385, b'[]', RAW.replace(b'.github', b'other'),
                    RAW.replace(b'repository_profile', b'../profile')):
            with self.subTest(raw=raw[:40]), self.assertRaises(control.ControlError):
                quality.metadata(raw, REPO)

    def test_validator_rejects_wrong_checkout_and_candidate_profile(self):
        record = self.prepare()
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {}, clear=True):
            directory = Path(temp)
            (directory / '.lit').mkdir()
            (directory / '.lit/repository.yml').write_bytes(RAW)
            previous = Path.cwd()
            os.chdir(directory)
            try:
                with patch.object(quality.subprocess, 'check_output', return_value='d' * 40):
                    with self.assertRaisesRegex(control.ControlError, 'checkout-head'):
                        quality.validate(record)
                (directory / '.lit/repository.yml').write_bytes(RAW.replace(b'repository_profile', b'other'))
                with patch.object(quality.subprocess, 'check_output', return_value=HEAD):
                    with self.assertRaisesRegex(control.ControlError, 'weaker-quality-profile'):
                        quality.validate(record)
            finally:
                os.chdir(previous)

    def test_validator_rejects_credentials_before_candidate_access(self):
        record = self.prepare()
        for name in ('GH_TOKEN', 'GITHUB_TOKEN'):
            with patch.dict(os.environ, {name: 'test-only'}, clear=True):
                with self.assertRaisesRegex(control.ControlError, 'must-not-receive-credentials'):
                    quality.validate(record)

    def test_source_validator_detects_invalid_yaml_despite_candidate_replacement(self):
        spec = importlib.util.spec_from_file_location('source_quality', ROOT / 'scripts/lit-repository-quality.py')
        engine = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(engine)
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            subprocess.run(['git', 'init', '-q', temp], check=True)
            (directory / 'scripts').mkdir()
            (directory / 'scripts/validate-embedded-code.py').write_text(
                'from pathlib import Path\nPath("candidate-executed").touch()\nraise SystemExit(0)\n')
            (directory / 'example.md').write_text('```yaml\nwrong: [\n```\n')
            subprocess.run(['git', '-C', temp, 'add', '.'], check=True)
            with patch.object(engine, 'ROOT', directory):
                with self.assertRaises(subprocess.CalledProcessError):
                    engine.check_embedded_code(source_owned=True)
            self.assertFalse((directory / 'candidate-executed').exists())
            (directory / 'example.md').write_text('```yaml\nvalid: true\n```\n')
            with patch.object(engine, 'ROOT', directory):
                engine.check_embedded_code(source_owned=True)
            self.assertFalse((directory / 'candidate-executed').exists())

    def test_native_dag_makes_common_quality_mandatory(self):
        import yaml
        workflow = yaml.safe_load((ROOT / '.github/workflows/change-control-required.yml').read_bytes())
        jobs = workflow['jobs']
        for job in ('required', 'normal-approval'):
            self.assertIn('common-quality', jobs[job]['needs'])
        final = next(step for step in jobs['required']['steps'] if step.get('run', '').endswith(' finalize'))
        self.assertEqual('${{ needs.common-quality.result }}', final['env']['COMMON_QUALITY_RESULT'])
        script = (ROOT / 'scripts/run-common-quality.sh').read_text()
        preparation, validation = script.split('# Source-owned validation:', 1)
        self.assertNotIn('-v "$candidate_root:', preparation)
        self.assertIn('--network none', validation)
        self.assertNotIn('-e GH_TOKEN', validation)
        self.assertNotIn('docker.sock', script)

    def test_failed_skipped_or_absent_common_result_cannot_finalize(self):
        for result in ('failure', 'skipped', 'cancelled', ''):
            api = Mock()
            api.call.side_effect = [run(), pull(), pull()]
            with tempfile.TemporaryDirectory() as temp:
                event = Path(temp) / 'event.json'
                event.write_text(json.dumps({'pull_request': pull()}))
                env = self.environment() | {'GITHUB_EVENT_PATH': str(event),
                                            'COMMON_QUALITY_RESULT': result}
                with self.subTest(result=result), patch.dict(os.environ, env, clear=True), \
                     patch.object(sys, 'argv', ['control', 'finalize']), \
                     patch.object(control, 'API', return_value=api), \
                     patch.object(control, 'policy', return_value={}), \
                     patch.object(control, 'operation_record', return_value={'binding': control.binding(pull())}), \
                     patch.object(control, 'check_quality') as downstream, \
                     self.assertRaisesRegex(control.ControlError, 'source-common-quality-not-successful'):
                    control.main()
                downstream.assert_not_called()


if __name__ == '__main__':
    unittest.main()
