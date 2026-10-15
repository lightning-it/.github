"""Actual Git fetch keeps ancestry but omits unchanged historical blobs."""
import os
import random
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import workflow_subject as subject


class PartialFetchTests(unittest.TestCase):
    def test_large_historical_blob_is_not_downloaded_for_complete_current_diff(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); source = root / 'source'; source.mkdir()
            environment = {**os.environ, 'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_NOSYSTEM': '1'}
            def command(*args):
                return subprocess.check_output(['git', '-C', str(source), *args], env=environment,
                                               stderr=subprocess.PIPE).decode().strip()
            command('init')
            command('config', 'user.name', 'Fixture'); command('config', 'user.email', 'fixture@example.invalid')
            command('config', 'commit.gpgsign', 'false'); command('config', 'uploadpack.allowFilter', 'true')
            (source / 'historic.bin').write_bytes(random.Random(7).randbytes(5 * 1024 * 1024))
            command('add', '.'); command('commit', '-m', 'historical data')
            historical = command('rev-parse', 'HEAD:historic.bin')
            (source / 'historic.bin').unlink(); (source / 'current.txt').write_text('old\n')
            command('add', '-A'); command('commit', '-m', 'current base')
            base = command('rev-parse', 'HEAD')
            (source / 'current.txt').write_text('new\n')
            command('add', '.'); command('commit', '-m', 'current change')
            head = command('rev-parse', 'HEAD')
            objects = root / 'objects.git'
            subprocess.run(['git', 'init', '--bare', str(objects)], env=environment,
                           check=True, capture_output=True)
            original = subject.git
            original(objects, 'config', 'protocol.file.allow', 'always')
            def local_remote(directory, *args, **kwargs):
                if args[:3] == ('remote', 'add', 'origin'):
                    args = (*args[:3], source.as_uri())
                return original(directory, *args, **kwargs)
            with patch.object(subject, 'git', side_effect=local_remote):
                subject.fetch_objects(objects, 'lightning-it/fixture',
                                      f'{base}:refs/review/base', f'{head}:refs/review/head')
            missing = original(objects, 'rev-list', '--objects', '--all', '--missing=print')
            self.assertIn('?' + historical, missing)
            diff = original(objects, 'diff', '--binary', base, head, binary=True)
            self.assertIn(b'-old\n+new\n', diff)
            self.assertIn('?' + historical, original(objects, 'rev-list', '--objects', '--all', '--missing=print'))
            self.assertLess(sum(p.stat().st_size for p in (objects / 'objects').rglob('*') if p.is_file()), 1024 * 1024)


if __name__ == '__main__':
    unittest.main()
