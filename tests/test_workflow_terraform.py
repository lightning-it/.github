"""Dependency download never executes candidate code or receives its contents."""
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
import workflow_terraform as terraform
from workflow_control import ControlError

ADDRESS = 'registry.terraform.io/integrations/github'
LOCK = 'provider "' + ADDRESS + '" {\nversion = "6.8.2"\nconstraints = "~> 6.0"\nhashes = ["zh:' + '0' * 64 + '",]\n}\n'


class TerraformDependencyTests(unittest.TestCase):
    def test_literal_lock_roundtrip_drops_comments_and_rejects_expressions_or_hosts(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / '.terraform.lock.hcl'
            path.write_text('# private comment must not leave extraction\n' + LOCK)
            data = terraform.lock_data(path)
            self.assertEqual({ADDRESS}, set(data))
            self.assertEqual('6.8.2', data[ADDRESS]['version'])
            for raw in (LOCK + LOCK, LOCK.replace('registry.terraform.io', 'attacker.example'),
                        LOCK.replace('"6.8.2"', 'env("SECRET")'), LOCK.replace('version', 'unknown'),
                        LOCK.replace('zh:' + '0' * 64, 'not-a-hash'), LOCK[:-2], LOCK + 'garbage'):
                path.write_text(raw)
                with self.subTest(raw=raw[:70]), self.assertRaises((ControlError, ValueError)):
                    terraform.lock_data(path)

    def repository(self, path, value):
        path.mkdir()
        subprocess.run(['git', 'init', '-q', str(path)], check=True)
        (path / 'main.tf').write_text('resource "terraform_data" "example" {\n input = "data"\n}\n')
        (path / '.terraform.lock.hcl').write_text(value)
        subprocess.run(['git', '-C', str(path), 'add', '.'], check=True)
        subprocess.run(['git', '-C', str(path), '-c', 'user.name=Fixture', '-c',
                        'user.email=fixture@example.invalid', 'commit', '-qm', 'fixture'], check=True)
        return subprocess.check_output(['git', '-C', str(path), 'rev-parse', 'HEAD'], text=True).strip()

    def prepare(self, directory, candidate_lock=LOCK, base_lock=LOCK):
        base, candidate = directory / 'base', directory / 'candidate'
        base_sha = self.repository(base, base_lock)
        self.repository(candidate, candidate_lock)
        previous = Path.cwd()
        try:
            os.chdir(candidate)
            with patch.object(terraform, 'subject', return_value={'repository_type': 'terraform_module'}):
                terraform.prepare({'base': base_sha}, base, directory / 'dependencies')
        finally:
            os.chdir(previous)
        return directory / 'dependencies'

    def test_extraction_outputs_only_canonical_provider_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = self.prepare(root, candidate_lock='# private-comment\n' + LOCK)
            self.assertEqual({'version': 1, 'tasks': ['provider-0000']},
                             json.loads((output / 'requests.json').read_bytes()))
            contents = '\n'.join(path.read_text() for path in output.rglob('*') if path.is_file())
            self.assertNotIn('private-comment', contents)
            self.assertNotIn('terraform_data', contents)
            self.assertNotIn('direct {', contents)
            self.assertNotIn(str(root), contents)
            normalized = terraform.lock_data(output / 'provider-0000/.terraform.lock.hcl')
            self.assertEqual(terraform.lock_data(root / 'candidate/.terraform.lock.hcl')[ADDRESS]['hashes'],
                             normalized[ADDRESS]['hashes'])

    def test_new_provider_or_changed_base_cannot_supply_dependencies(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(ControlError, 'provider-not-approved'):
                self.prepare(Path(temp), candidate_lock=LOCK.replace('integrations/github', 'hashicorp/http'))
        with tempfile.TemporaryDirectory() as temp, patch.object(terraform, 'subject', return_value={}):
            with patch.object(terraform.subprocess, 'check_output', return_value='wrong'), \
                 self.assertRaisesRegex(ControlError, 'protected-base-drift'):
                terraform.prepare({'base': 'a' * 40}, Path(temp), Path(temp) / 'out')

    def test_fetch_uses_only_mirror_not_init_validate_or_candidate_scripts(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'requests.json').write_text(json.dumps({'version': 1, 'tasks': ['provider-0000']}))
            with patch.object(terraform.subprocess, 'run') as command:
                terraform.fetch(root, Path('/providers'))
            command.assert_called_once_with(['terraform', f'-chdir={root / "provider-0000"}',
                                             'providers', 'mirror', '/providers'], check=True, timeout=600)
            (root / 'requests.json').write_text(json.dumps({'version': 1, 'tasks': ['../../candidate']}))
            with patch.object(terraform.subprocess, 'run') as command, self.assertRaises(ControlError):
                terraform.fetch(root, Path('/providers'))
            command.assert_not_called()

    def test_no_dependency_phase_accepts_a_github_credential(self):
        with patch.dict(os.environ, {'GH_TOKEN': 'synthetic-only'}, clear=True), \
             self.assertRaisesRegex(ControlError, 'no-credentials'):
            terraform.fetch(Path('/not-mounted'), Path('/providers'))
