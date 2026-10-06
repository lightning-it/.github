"""Ordinary receipt collection across revoked engine access; no Docker/provider calls."""
import json
import os
import re
import socket
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from . import test_exact_revision_gateway as fixtures
except ImportError:
    import test_exact_revision_gateway as fixtures

gateway = fixtures.gateway
ROOT = Path(__file__).resolve().parents[1]


class CollectorBoundaryTests(unittest.TestCase):
    setUp = fixtures.SingleReviewGatewayTests.setUp

    def test_prestarted_collector_survives_revoked_socket_and_rejects_invalid_receipt(self):
        for valid in (True, False):
            with self.subTest(valid=valid):
                if not valid:
                    self.setUp()
                self.exercise_transition(valid)

    def exercise_transition(self, valid):
        engine_socket = self.root / 'engine.sock'
        service = socket.socket(socket.AF_UNIX)
        self.addCleanup(service.close)
        service.bind(str(engine_socket))
        service.listen(2)
        # This fixture grants current-user access, then removes it with chmod,
        # reproducing the effective socket denial of drop-sudo without root.
        engine_socket.chmod(0o600)
        launcher = self.root / 'engine_fixture.py'
        launcher.write_text('''import os, socket, sys
from pathlib import Path
root, directory, endpoint = map(Path, sys.argv[1:])
connection = socket.socket(socket.AF_UNIX)
connection.connect(str(endpoint))
sys.path.insert(0, str(root / 'code'))
import exact_revision_gateway as gateway
# Ordinary non-root fixtures retain all checks, substituting their real owner
# for the production protected files' UID0. No runtime ownership rule changes.
read_owned, owned_directory = gateway.read_owned, gateway.owned_directory
gateway.root_for = lambda run_id: root
gateway.read_owned = lambda path, uid, limit: read_owned(path, os.getuid() if uid == 0 else uid, limit)
gateway.owned_directory = lambda path, uid, **kw: owned_directory(path, os.getuid() if uid == 0 else uid, **kw)
gateway.collect(directory, 42, supervised=True)
''')
        commands = []
        native_popen = subprocess.Popen

        def engine(command, **kwargs):
            commands.append(command)
            return native_popen([sys.executable, str(launcher), str(self.root), str(self.directory),
                                 str(engine_socket)], **kwargs)

        root_for = lambda run_id: self.root
        owner = os.getuid() or 65534
        group = os.getgid() or 65534
        with patch.object(gateway.subprocess, 'Popen', side_effect=engine):
            process = gateway.start_collector(self.root, self.directory, 42, owner, group)
        self.addCleanup(gateway.stop_collector, process)
        attached, _ = service.accept()
        self.addCleanup(attached.close)
        engine_socket.chmod(0)
        denied = socket.socket(socket.AF_UNIX)
        self.addCleanup(denied.close)
        with self.assertRaises(PermissionError):
            denied.connect(str(engine_socket))
        self.assertIsNone(process.poll())
        result = dict(self.result)
        if not valid:
            result['head_sha'] = 'b' * 40
        gateway.write_once(self.root / 'public/receipt.json', {
            'version': gateway.VERSION,
            'state_sha256': gateway.review.sha(gateway.review.canonical(self.state)),
            'result': result,
        })
        if valid:
            gateway.finish_collector(process, self.root, 42)
        else:
            with self.assertRaisesRegex(gateway.review.ReviewError, 'single-collector-result'):
                gateway.finish_collector(process, self.root, 42)
            self.assertFalse((self.root / 'public/collected-result.json').exists())
        # A forged action output cannot stand in for a failed collector.
        (self.directory / 'result.json').write_text('{"verdict":"forged"}')
        read_owned, owned_directory = gateway.read_owned, gateway.owned_directory
        with (patch.object(gateway, 'root_for', side_effect=root_for),
              patch.object(gateway, 'read_owned', side_effect=lambda p, uid, maximum: read_owned(p, os.getuid(), maximum)),
              patch.object(gateway, 'owned_directory', side_effect=lambda p, uid: owned_directory(p, os.getuid()))):
            if valid:
                gateway.consume(self.directory, 42)
                self.assertEqual(self.result, json.loads((self.directory / 'result.json').read_text()))
            else:
                with self.assertRaisesRegex(gateway.review.ReviewError, 'single-collection-failed'):
                    gateway.consume(self.directory, 42)
        self.assertEqual(1, len(commands))
        command = commands[0]
        engine_path = ROOT / 'default/scripts/lit-push-ready.py'
        if not engine_path.exists():
            engine_path = ROOT / 'scripts/lit-push-ready.py'
        image = re.search(r'quay\.io/l-it/ee-wunder-devtools-ubi9:[^"\s]+@sha256:[0-9a-f]{64}',
                          engine_path.read_text()).group()
        self.assertIn(image, command)
        self.assertEqual(f'{owner}:{group}', command[command.index('--user') + 1])
        self.assertEqual('none', command[command.index('--network') + 1])
        self.assertIn('--read-only', command)
        self.assertEqual('ALL', command[command.index('--cap-drop') + 1])
        self.assertEqual('no-new-privileges', command[command.index('--security-opt') + 1])
        self.assertEqual([
            f'type=bind,src={self.root},dst={self.root},readonly',
            f'type=bind,src={self.directory},dst=/review,readonly',
        ], [command[i + 1] for i, value in enumerate(command) if value == '--mount'])
        self.assertEqual('--supervised', command[-1])

    def test_install_preserves_original_runner_identity_for_supervisor(self):
        gateway.write_once(self.root / 'public/port.json', {'port': 1234})
        with (patch.object(gateway.os, 'geteuid', return_value=0),
              patch.dict(os.environ, {'SUDO_UID': '1001', 'SUDO_GID': '1002'}),
              patch.object(gateway, 'root_for', return_value=self.root),
              patch.object(gateway, 'owned_directory'),
              patch.object(gateway, 'prepare') as prepare,
              patch.object(gateway.subprocess, 'Popen') as popen):
            gateway.install(self.directory, 42)
        prepare.assert_called_once_with(self.root, self.directory, 42, 1001)
        command = popen.call_args.args[0]
        self.assertEqual('1001', command[command.index('--owner-uid') + 1])
        self.assertEqual('1002', command[command.index('--owner-gid') + 1])
        self.assertEqual(str(self.directory.resolve()), command[command.index('--review-directory') + 1])

    def test_gateway_does_not_publish_port_until_collector_is_ready(self):
        events = []
        collector = object()
        original_write = gateway.write_once

        def start(*args):
            self.assertFalse((self.root / 'public/port.json').exists())
            events.append('collector-ready')
            return collector

        def write(path, value):
            if path.name == 'port.json':
                self.assertEqual(['collector-ready'], events)
                events.append('port-published')
            return original_write(path, value)

        class Reviewer:
            done = True
            failed = False

        class Server:
            server_address = ('127.0.0.1', 1234)

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return None

        with (patch.object(gateway.os, 'geteuid', return_value=0),
              patch.object(gateway, 'root_for', return_value=self.root),
              patch.object(gateway, 'owned_directory'),
              patch.object(gateway, 'context', return_value=(self.state, self.prompt)),
              patch.object(gateway, 'Reviewer', return_value=Reviewer()),
              patch.object(gateway.http.server, 'HTTPServer', return_value=Server()),
              patch.object(gateway, 'start_collector', side_effect=start),
              patch.object(gateway, 'write_once', side_effect=write),
              patch.object(gateway, 'finish_collector') as finish,
              patch.object(gateway, 'stop_collector') as stop):
            self.assertEqual(0, gateway.serve(42, self.directory, 1001, 1001))
            finish.assert_called_once_with(collector, self.root, 42)
            stop.assert_called_once_with(collector)
        self.assertEqual(['collector-ready', 'port-published'], events)


if __name__ == '__main__':
    unittest.main()
