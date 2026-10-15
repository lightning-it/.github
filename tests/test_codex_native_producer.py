"""A cached response needs a real successful native producer, not a PR claim."""
import json
import os
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

try:
    from . import test_gateway_complete_replay as fixtures
except ImportError:
    import test_gateway_complete_replay as fixtures

gateway = fixtures.gateway
import workflow_codex as native
from workflow_control import WORKFLOW, ControlError

REPO = 'lightning-it/.github'
SOURCE = 'c' * 40


class NativeCodexTests(unittest.TestCase):
    setUp = fixtures.CompleteReplayTests.setUp
    request = fixtures.CompleteReplayTests.request
    response = fixtures.CompleteReplayTests.response
    original = fixtures.CompleteReplayTests.original

    def native_fixture(self):
        self.metadata.update(central_source_sha=SOURCE, repository=REPO, pull_request=3)
        receipt, wire = self.original()
        record = {'version': 1, 'source_sha': SOURCE, 'metadata_sha256': native.digest(self.metadata),
                  'response_sha256': gateway.review.sha(wire), 'receipt': receipt}
        pull = {'number': 3, 'title': 'Change', 'body': '', 'labels': [], 'draft': False,
                'user': {'login': 'lightning-it-release-automation[bot]', 'id': 307565056, 'type': 'Bot'},
                'head': {'sha': self.metadata['head_sha'], 'ref': 'release/v1.0.0', 'repo': {'full_name': REPO}},
                'base': {'sha': self.metadata['base_sha'], 'ref': 'develop', 'repo': {'full_name': REPO}}}
        run = {'id': 10, 'run_attempt': 1, 'workflow_id': 77, 'head_sha': pull['head']['sha'],
               'path': WORKFLOW,
               'workflow_url': f'https://api.github.com/repos/{REPO}/actions/required_workflows/77',
               'pull_requests': [{'number': 3, 'head': {'sha': pull['head']['sha']}, 'base': {'sha': pull['base']['sha']}}]}
        artifacts = [{'name': 'codex-receipt-1', 'expired': False, 'size_in_bytes': 1024}]
        job = {'id': 100, 'run_id': 10, 'name': 'Protected current revision', 'conclusion': 'success',
               'steps': [{'name': n, 'conclusion': 'success'} for n in (native.COLLECT_STEP, native.EXPORT_STEP)]}
        return pull, run, artifacts, job, record, wire

    def test_only_successful_native_exact_operation_can_install_replay(self):
        pull, run, artifacts, job, record, wire = self.native_fixture()
        operation = {'source_sha': SOURCE, 'binding': native.binding(pull)}
        api = Mock(); api.pages.side_effect = [[run], artifacts, [job]]
        with patch.object(native, 'operation_record', return_value=operation), \
             patch.object(native, 'download', return_value=(record, wire)):
            self.assertTrue(native.prepare(api, REPO, pull, self.metadata, SOURCE, self.directory))
        manifest = json.loads((self.directory / 'reuse-candidate.json').read_bytes())
        self.assertEqual({'repository': REPO, 'pull_request': 3, 'run': 10, 'attempt': 1, 'job': 100}, manifest['producer'])
        self.assertEqual(wire, (self.directory / 'reuse-response.bin').read_bytes())

    def test_candidate_run_wrong_pr_or_failed_collector_never_grants_replay(self):
        pull, run, artifacts, job, _record, _wire = self.native_fixture()
        ordinary = run | {'workflow_url': f'https://api.github.com/repos/{REPO}/actions/workflows/77'}
        other = run | {'pull_requests': [run['pull_requests'][0] | {'number': 4}]}
        for changed in (ordinary, other):
            api = Mock(); api.pages.return_value = [changed]
            with self.subTest(changed=changed), patch.object(native, 'download') as download:
                self.assertIsNone(native.native_evidence(api, REPO, pull, self.metadata, SOURCE))
                download.assert_not_called()
        operation = {'source_sha': SOURCE, 'binding': native.binding(pull)}
        for change in ({'conclusion': 'failure'}, {'steps': [{'name': native.EXPORT_STEP, 'conclusion': 'success'}]}):
            api = Mock(); api.pages.side_effect = [[run], artifacts, [job | change]]
            with patch.object(native, 'operation_record', return_value=operation), patch.object(native, 'download') as download:
                self.assertIsNone(native.native_evidence(api, REPO, pull, self.metadata, SOURCE))
                download.assert_not_called()

    def test_source_metadata_or_response_drift_is_never_a_pass(self):
        _pull, _run, _artifacts, _job, record, wire = self.native_fixture()
        for changed in (record | {'source_sha': 'd' * 40}, record | {'metadata_sha256': 'd' * 64}):
            with self.assertRaisesRegex(ControlError, 'codex-native-input-binding'):
                native.validate_record(changed, wire, self.metadata, SOURCE)
        with self.assertRaisesRegex(ControlError, 'codex-native-wire-binding'):
            native.validate_record(record, wire + b' ', self.metadata, SOURCE)

    def test_latest_failed_or_incomplete_producer_cannot_fall_back_to_attempt_one(self):
        pull, run, artifacts, job, _record, _wire = self.native_fixture()
        run['run_attempt'] = 2
        operation = {'source_sha': SOURCE, 'binding': native.binding(pull)}
        for latest in (job | {'conclusion': 'failure'}, job | {'conclusion': None}, job):
            api = Mock(); api.pages.side_effect = [artifacts, [latest]]
            with patch.object(native, 'operation_record', return_value=operation), \
                 patch.object(native, 'download') as download, \
                 self.assertRaises(ControlError):
                native.current_evidence(api, REPO, pull, self.metadata, SOURCE, run)
            download.assert_not_called()

    def test_replay_can_prepare_from_real_success_while_current_producer_is_not_yet_accepted(self):
        pull, run, artifacts, job, record, wire = self.native_fixture()
        run['run_attempt'] = 3
        operation = {'source_sha': SOURCE, 'binding': native.binding(pull)}
        pending = job | {'id': 300, 'conclusion': None, 'steps': [{'name': 'Classify protected current revision', 'conclusion': 'success'}]}
        draft_failure = job | {'id': 200, 'conclusion': 'failure', 'steps': [{'name': 'Classify protected current revision', 'conclusion': 'failure'}]}
        api = Mock(); api.pages.side_effect = [[run], artifacts, [pending], [draft_failure], [job]]
        with patch.object(native, 'operation_record', return_value=operation), \
             patch.object(native, 'download', return_value=(record, wire)):
            self.assertTrue(native.prepare(api, REPO, pull, self.metadata, SOURCE, self.directory))
        candidate = json.loads((self.directory / 'reuse-candidate.json').read_bytes())
        self.assertEqual(1, candidate['producer']['attempt'])
        # A candidate is data for the complete-request gateway, never a pass.
        current = Mock(); current.pages.side_effect = [artifacts, [pending]]
        with patch.object(native, 'operation_record', return_value=operation), \
             patch.object(native, 'download') as download, self.assertRaises(ControlError):
            native.current_evidence(current, REPO, pull, self.metadata, SOURCE, run)
        download.assert_not_called()


    def test_verifier_only_rerun_inherits_the_latest_actual_successful_producer(self):
        pull, run, artifacts, job, record, wire = self.native_fixture()
        run['run_attempt'] = 2
        verifier = {'id': 101, 'run_id': 10, 'name': 'Current revision review', 'conclusion': 'success'}
        skipped = {'id': 102, 'run_id': 10, 'name': 'Protected current revision', 'conclusion': 'skipped', 'steps': []}
        for latest_jobs in ([verifier], [skipped, verifier]):
            api = Mock(); api.pages.side_effect = [artifacts, latest_jobs, [job]]
            with self.subTest(latest_jobs=latest_jobs), \
                 patch.object(native, 'operation_record', return_value={'source_sha': SOURCE, 'binding': native.binding(pull)}), \
                 patch.object(native, 'download', return_value=(record, wire)):
                result = native.current_evidence(api, REPO, pull, self.metadata, SOURCE, run)
            self.assertEqual(1, result['producer']['attempt'])
            self.assertEqual(100, result['producer']['job'])

    def test_native_export_preserves_wire_and_rejects_changed_provider_bytes(self):
        receipt, wire = self.original()
        self.state['metadata']['central_source_sha'] = SOURCE
        receipt['state_sha256'] = gateway.review.sha(gateway.review.canonical(self.state))
        receipt_file = self.root / 'public/receipt.json'
        receipt_file.chmod(0o600); receipt_file.write_bytes(gateway.review.canonical(receipt))
        destination = Path(self.temporary.name) / 'export'; destination.mkdir()
        original_read = gateway.read_owned
        with patch.object(gateway, 'root_for', return_value=self.root), \
             patch.object(gateway, 'context', return_value=(self.state, self.prompt)), \
             patch.object(gateway, 'read_owned', side_effect=lambda p, _uid, m: original_read(p, os.getuid(), m)):
            gateway.export_native(destination, 42)
            self.assertEqual(wire, (destination / 'provider-response.bin').read_bytes())
            self.assertEqual(native.digest(self.state['metadata']), json.loads(
                (destination / 'provider-native.json').read_bytes())['metadata_sha256'])
            raw = self.root / 'public/response.bin'; raw.chmod(0o600); raw.write_bytes(wire + b' ')
            with self.assertRaisesRegex(gateway.review.ReviewError, 'single-native-export-binding'):
                gateway.export_native(destination, 42)


if __name__ == '__main__':
    unittest.main()
