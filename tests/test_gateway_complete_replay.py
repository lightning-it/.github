"""Same model bytes may only replay for the same actual complete request."""
import json
import unittest
from unittest.mock import patch

try:
    from . import test_exact_revision_gateway as fixtures
except ImportError:
    import test_exact_revision_gateway as fixtures

gateway = fixtures.gateway
transport = gateway.transport


class CompleteReplayTests(unittest.TestCase):
    setUp = fixtures.SingleReviewGatewayTests.setUp
    request = fixtures.SingleReviewGatewayTests.request
    response = fixtures.SingleReviewGatewayTests.response

    def original(self):
        wire = gateway.review.canonical(self.response())
        counted = gateway.review.canonical({'object': 'response.input_tokens', 'input_tokens': 10})
        with patch.object(transport, 'run_worker', side_effect=[counted, wire]):
            self.reviewer.submit(self.request(), 'fixture')
        receipt = json.loads((self.root / 'public/receipt.json').read_text())
        return receipt, wire

    def replay(self, receipt, wire):
        destination = self.root / 'replay'
        destination.mkdir()
        return gateway.ReplayReviewer(self.state, self.prompt, destination, receipt=receipt, wire=wire)

    def test_identical_complete_client_request_replays_real_bytes_without_provider(self):
        receipt, wire = self.original()
        reviewer = self.replay(receipt, wire)
        with patch.object(transport, 'run_worker') as provider:
            self.assertEqual(wire, reviewer.submit(self.request(), 'unused-fixture'))
        provider.assert_not_called()
        stored = json.loads((self.root / 'replay/receipt.json').read_text())
        self.assertEqual(0, stored['new_provider_requests'])
        self.assertTrue(stored['replayed'])
        self.assertEqual(receipt['provider']['request_sha256'], stored['provider']['request_sha256'])

    def test_changed_instructions_or_tools_never_reuse_metadata_only_match(self):
        receipt, wire = self.original()
        for change in ({'instructions': 'different trusted context'},
                       {'tools': [{'type': 'function', 'name': 'new_context', 'parameters': {'type': 'object'}}]}):
            reviewer = self.replay(receipt, wire)
            with patch.object(transport, 'run_worker') as provider, \
                 self.assertRaisesRegex(gateway.review.ReviewError, 'single-replay-complete-request-drift'):
                reviewer.submit(self.request() | change, 'unused-fixture')
            provider.assert_not_called()
            self.assertFalse((self.root / 'replay/receipt.json').exists())
            (self.root / 'replay/failure.json').unlink()
            (self.root / 'replay').rmdir()

    def test_changed_response_bytes_are_rejected_before_client_submit(self):
        receipt, wire = self.original()
        with self.assertRaisesRegex(gateway.review.ReviewError, 'single-replay-response-binding'):
            self.replay(receipt, wire + b' ')

    def test_session_cache_hints_are_absent_from_forwarded_and_replayed_request(self):
        original = self.request() | {'prompt_cache_key': 'session-one'}
        wire = gateway.review.canonical(self.response())
        count = gateway.review.canonical({'object': 'response.input_tokens', 'input_tokens': 10})
        with patch.object(transport, 'run_worker', side_effect=[count, wire]) as provider:
            self.reviewer.submit(original, 'fixture')
        self.assertTrue(all('prompt_cache_key' not in call.args[0] for call in provider.call_args_list))
        receipt = json.loads((self.root / 'public/receipt.json').read_text())
        reviewer = self.replay(receipt, wire)
        with patch.object(transport, 'run_worker') as provider:
            self.assertEqual(wire, reviewer.submit(self.request() | {'prompt_cache_key': 'session-two'}, 'fixture'))
        provider.assert_not_called()

    def test_cross_run_environment_uses_stable_workspace_but_still_binds_context(self):
        self.assertEqual(gateway.root_for(42), gateway.root_for(99))
        context = f'<environment_context><cwd>{gateway.root_for(42) / "public"}</cwd><current_date>2026-10-15</current_date></environment_context>'
        request = self.request() | {'input': self.prompt + '\n' + context}
        wire = gateway.review.canonical(self.response())
        count = gateway.review.canonical({'object': 'response.input_tokens', 'input_tokens': 10})
        with patch.object(transport, 'run_worker', side_effect=[count, wire]):
            self.reviewer.submit(request, 'fixture')
        receipt = json.loads((self.root / 'public/receipt.json').read_text())
        reviewer = self.replay(receipt, wire)
        with patch.object(transport, 'run_worker') as provider:
            self.assertEqual(wire, reviewer.submit(request, 'fixture'))
        provider.assert_not_called()

    def test_large_valid_instruction_metadata_survives_receipt_and_replay(self):
        import hashlib
        import shutil
        metadata = self.metadata
        agents = next(f for f in metadata['review_instructions']['files'] if f['path'] == 'AGENTS.md')
        agents['content'] += 'Protected instruction context. ' * 12000
        raw = agents['content'].encode()
        agents['sha256'] = gateway.review.sha(raw)
        agents['blob_sha'] = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
        copilot = next(f for f in metadata['review_instructions']['files'] if f['path'] == '.github/copilot-instructions.md')
        copilot['content'] = 'Follow protected AGENTS.md.\n<!-- AGENTS_SHA256: ' + agents['sha256'] + ' -->\n'
        raw = copilot['content'].encode()
        copilot['sha256'] = gateway.review.sha(raw)
        copilot['blob_sha'] = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
        metadata['instructions_sha256'] = gateway.review.sha(gateway.review.canonical(metadata['review_instructions']))
        encoded = gateway.review.canonical(metadata)
        self.assertGreater(len(encoded), 262144)
        self.assertLess(len(encoded), gateway.MAX_CONTROL_BYTES)
        (self.directory / 'review-metadata.json').write_bytes(encoded)
        shutil.rmtree(self.root)
        gateway.prepare(self.root, self.directory, 42, gateway.os.getuid())
        self.state, self.prompt = gateway.context(self.root, 42, uid=gateway.os.getuid())
        self.reviewer = gateway.Reviewer(self.state, self.prompt, self.root / 'public')
        receipt, wire = self.original()
        # Native transport evidence carries digests/results, not another copy of
        # the entire instruction bundle. The full actual request hash still binds it.
        self.assertLess(len(gateway.review.canonical(receipt)), 262144)
        reviewer = self.replay(receipt, wire)
        with patch.object(transport, 'run_worker') as provider:
            self.assertEqual(wire, reviewer.submit(self.request(), 'unused-fixture'))
        provider.assert_not_called()

    def test_replay_installation_seals_only_exact_input_and_source(self):
        import shutil
        metadata = self.metadata
        metadata.update(central_source_sha='c' * 40, repository='lightning-it/.github', pull_request=3)
        (self.directory / 'review-metadata.json').write_bytes(gateway.review.canonical(metadata))
        shutil.rmtree(self.root)
        gateway.prepare(self.root, self.directory, 42, gateway.os.getuid())
        self.state, self.prompt = gateway.context(self.root, 42, uid=gateway.os.getuid())
        self.reviewer = gateway.Reviewer(self.state, self.prompt, self.root / 'public')
        receipt, wire = self.original()
        manifest = {'version': 1, 'source_sha': metadata['central_source_sha'],
                    'metadata_sha256': gateway.review.sha(gateway.review.canonical(metadata)),
                    'response_sha256': gateway.review.sha(wire), 'receipt': receipt,
                    'producer': {'repository': metadata['repository'], 'pull_request': 3,
                                 'run': 10, 'attempt': 1, 'job': 100}}
        (self.directory / 'reuse-candidate.json').write_bytes(gateway.review.canonical(manifest))
        (self.directory / 'reuse-response.bin').write_bytes(wire)
        destination = self.root.parent / 'replay-install'
        gateway.prepare(destination, self.directory, 42, gateway.os.getuid())
        state, _ = gateway.context(destination, 42, uid=gateway.os.getuid())
        self.assertEqual(manifest['response_sha256'], state['replay']['response_sha256'])
        self.assertEqual(wire, (destination / 'public/reuse-response.bin').read_bytes())
        for change in ({'source_sha': 'd' * 40}, {'metadata_sha256': 'e' * 64},
                       {'producer': manifest['producer'] | {'pull_request': 44}}):
            (self.directory / 'reuse-candidate.json').write_bytes(gateway.review.canonical(manifest | change))
            with self.subTest(change=change), self.assertRaises(gateway.review.ReviewError):
                gateway.prepare(self.root.parent / 'invalid-replay', self.directory, 42, gateway.os.getuid())


if __name__ == '__main__':
    unittest.main()
