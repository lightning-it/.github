"""Proof decoding and compact cumulative references share real memory limits."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import workflow_proofs as proofs


class ProofResourceTests(unittest.TestCase):
    def contract(self, maximum=4096, nodes=100):
        return {'max_wire_bytes': maximum, 'max_json_nodes': nodes, 'max_json_depth': 64}

    def test_aggregate_budget_blocks_individually_valid_references_before_retaining_them(self):
        reference = {'pull': 3, 'control': {'run': 10, 'proof_sha256': 'a' * 64}}
        encoded = json.dumps(reference, sort_keys=True, separators=(',', ':')).encode()
        with patch.object(proofs.resources, 'memory_contract', return_value=self.contract(len(encoded) * 2)):
            aggregate = proofs.References(50 * 1024 * 1024)
            aggregate.append(reference)
            with self.assertRaisesRegex(ValueError, 'aggregate-resource-admission'):
                aggregate.append(reference | {'pull': 4})
            self.assertEqual([reference], aggregate.items)

    def test_decode_admission_happens_before_file_read_or_json_allocation(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'proof.json'
            path.write_text(json.dumps({'large': 'x' * 10000}))
            with patch.object(proofs.resources, 'memory_contract', return_value=self.contract()), \
                 patch.object(Path, 'read_bytes') as read, self.assertRaisesRegex(ValueError, 'resource-admission'):
                proofs.read_native_json(path, 50 * 1024 * 1024)
            read.assert_not_called()
            path.write_text(json.dumps([''] * 500))
            with patch.object(proofs.resources, 'memory_contract', return_value=self.contract()), \
                 patch.object(proofs.json, 'loads') as decode, self.assertRaisesRegex(ValueError, 'node-budget'):
                proofs.read_native_json(path, 50 * 1024 * 1024)
            decode.assert_not_called()

    def test_reference_has_no_retained_full_native_payload(self):
        from unittest.mock import Mock

        import workflow_control as control
        from test_workflow_control import BASE, HEAD, REPO, SOURCE, pull, run
        api = Mock(); native = run() | {'status': 'completed', 'conclusion': 'success'}
        api.pages.side_effect = [[native], [{'id': 100, 'run_id': 10, 'name': 'Current revision review', 'conclusion': 'success'}], [native], [native]]
        api.call.return_value = native
        record = {'version': 1, 'source_sha': SOURCE, 'binding': control.binding(pull()),
                  'route': 'copilot', 'evidence': {'large': 'x' * 300000}}
        with patch.object(control, 'artifact_record', return_value=record):
            result = control.check_native_control(api, REPO, pull(), {'accepted_sources': [SOURCE]})
        self.assertNotIn('proof', result)
        self.assertEqual(control.digest(record), result['proof_sha256'])
        self.assertEqual('control-proof-1', result['artifact'])
        self.assertEqual(HEAD, result['head'])
        self.assertNotEqual(BASE, result['head'])


if __name__ == '__main__':
    unittest.main()
