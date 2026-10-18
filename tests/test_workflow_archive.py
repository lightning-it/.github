"""Archived review payloads must match accepted native evidence exactly."""
import base64
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import workflow_archive as archive
from workflow_control import ControlError, digest
from test_release_package_ingress import fixtures, REPO, HEAD, POLICY


class ArchiveReviewTests(unittest.TestCase):
    def setUp(self):
        promotion, self.proof, self.run, _, _ = fixtures()
        self.reference = promotion["evidence"]["ingress"][0]
        self.response = b'event: response.completed\ndata: {"complete":"response"}\n\n'
        self.response_sha = hashlib.sha256(self.response).hexdigest()
        self.result = {"verdict": "PASS", "findings": [], "head_sha": HEAD}
        self.proof["evidence"] = {
            "producer": {"repository": REPO, "pull_request": 8, "run": 10, "attempt": 2, "job": 15},
            "metadata_sha256": "f" * 64, "response_sha256": self.response_sha,
            "request_sha256": ["e" * 64], "result": self.result}
        self.record = {"version": 1, "source_sha": POLICY, "metadata_sha256": "f" * 64,
                       "response_sha256": self.response_sha,
                       "receipt": {"response_sha256": self.response_sha,
                                   "provider": {"request_count": 1, "request_sha256": ["e" * 64]},
                                   "result": self.result}}
        self.api = Mock()
        self.api.call.return_value = self.run
        self.job = {"id": 15, "run_id": 10, "name": "Protected current revision", "conclusion": "success",
                    "steps": [{"name": name, "conclusion": "success"}
                              for name in (archive.workflow_codex.EXPORT_STEP, archive.workflow_codex.COLLECT_STEP)]}
        self.api.pages.return_value = [self.job]
        self.download = patch.object(archive.workflow_codex, "download", return_value=(self.record, self.response)).start()
        self.addCleanup(patch.stopall)

    def collect(self):
        return archive.collect_review(self.api, REPO, self.reference, self.proof)

    def test_complete_original_response_and_receipt_are_retained(self):
        collected = self.collect()
        self.assertEqual(self.response, base64.b64decode(collected["response"]))
        self.assertEqual(self.record, collected["record"])
        self.assertFalse(collected["request_payload_available"])
        self.assertEqual("codex-receipt-2", self.download.call_args.args[3])

    def test_changed_response_or_native_record_fails(self):
        for change in ({"source_sha": HEAD}, {"metadata_sha256": "0" * 64}, {"response_sha256": "0" * 64}):
            with self.subTest(change=change), patch.object(archive.workflow_codex, "download", return_value=(self.record | change, self.response)), \
                 self.assertRaisesRegex(ControlError, "full-receipt-binding"):
                self.collect()
        self.download.return_value = self.record, self.response + b"changed"
        with self.assertRaisesRegex(ControlError, "full-receipt-binding"):
            self.collect()

    def test_changed_full_request_hash_or_result_fails(self):
        original = copy.deepcopy(self.record)
        for receipt in ({"provider": {"request_count": 2, "request_sha256": ["e" * 64]}},
                        {"provider": {"request_count": 1, "request_sha256": ["0" * 64]}},
                        {"result": {"verdict": "PASS", "findings": ["changed"]}}):
            self.record = copy.deepcopy(original)
            self.record["receipt"].update(receipt)
            self.download.return_value = self.record, self.response
            with self.assertRaisesRegex(ControlError, "full-receipt-binding"):
                self.collect()

    def test_wrong_producer_or_failed_export_is_not_archivable(self):
        for attempt in (0, -1, True, 3):
            self.proof["evidence"]["producer"]["attempt"] = attempt
            with self.subTest(attempt=attempt), self.assertRaisesRegex(ControlError, "producer-binding"):
                self.collect()
        self.api.call.assert_not_called()
        self.proof["evidence"]["producer"]["attempt"] = 1
        self.run.update(run_attempt=1, conclusion="failure")
        self.job["steps"][0]["conclusion"] = "failure"
        with self.assertRaisesRegex(ControlError, "native-producer"):
            self.collect()
        self.download.assert_not_called()

    def assemble_verifier_rerun(self, destination):
        promotion, _, _, control_job, pull = fixtures()
        self.proof["evidence"]["producer"]["attempt"] = 1
        promotion["evidence"]["ingress"][0]["control"]["proof_sha256"] = digest(self.proof)
        producer_run = self.run | {"run_attempt": 1, "conclusion": "failure"}
        self.api.call.side_effect = lambda path: (
            producer_run if path.endswith("/attempts/1") else
            self.run if path.endswith("/attempts/2") else pull)
        self.api.pages.side_effect = lambda path, *args: (
            [control_job] if "/attempts/2/jobs" in path else
            [self.job] if "/attempts/1/jobs" in path else [])
        with patch.object(archive.ingress, "artifact_record", return_value=self.proof):
            return archive.assemble(self.api, REPO, promotion, digest(promotion), destination)

    def test_successful_control_rerun_archives_bound_earlier_successful_producer(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "ingress.json"
            self.assemble_verifier_rerun(destination)
            collected = json.loads(destination.read_bytes())["ingress"][0]["review"]
        self.assertEqual(1, collected["producer"]["attempt"])
        self.assertEqual(self.response, base64.b64decode(collected["response"]))
        self.assertEqual("codex-receipt-1", self.download.call_args.args[3])
        self.api.call.assert_any_call(f"repos/{REPO}/actions/runs/10/attempts/2")
        self.api.call.assert_any_call(f"repos/{REPO}/actions/runs/10/attempts/1")

    def test_failed_control_rerun_cannot_archive_earlier_successful_producer(self):
        self.run["conclusion"] = "failure"
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "ingress.json"
            with self.assertRaisesRegex(ControlError, "package-native-attempt"):
                self.assemble_verifier_rerun(destination)
            self.assertEqual([], list(Path(directory).iterdir()))
        self.download.assert_not_called()

    def test_expired_receipt_never_becomes_new_provider_or_storage_write(self):
        self.download.side_effect = ControlError("codex-native-artifact-admission")
        with self.assertRaisesRegex(ControlError, "artifact-admission"):
            self.collect()
        self.assertTrue(all(not call.kwargs for call in self.api.call.call_args_list))

    def copilot_fixture(self):
        review = {"id": 21, "node_id": "PRR_21", "body": "Full native review body", "body_html": "<p>Full native review body</p>",
                  "user": {"id": 175728472, "type": "Bot"}, "commit_id": HEAD, "state": "COMMENTED"}
        self.proof["route"] = "copilot"
        self.proof["evidence"] = {"id": 21, "state": "COMMENTED", "service_run": 22, "finding_comment_ids": [],
                                  "frame": {"review_database_id": 21, "review_id": "PRR_21",
                                            "review_body_sha256": hashlib.sha256(review["body"].encode()).hexdigest()}}
        self.api.pages.return_value = [review]
        self.api.call.return_value = {"id": 22, "event": "dynamic", "path": "dynamic/agents/copilot-pull-request-reviewer",
                                      "head_sha": HEAD, "status": "completed", "conclusion": "success"}
        return review

    def test_full_copilot_markdown_html_and_native_run_are_preserved(self):
        review = self.copilot_fixture()
        result = self.collect()
        self.assertEqual(review, result["review"])
        self.assertEqual(22, result["service_run"]["id"])
        self.download.assert_not_called()

    def test_edited_or_foreign_copilot_report_is_rejected(self):
        original = self.copilot_fixture()
        for change in ({"body": "edited"}, {"user": {"id": 1, "type": "User"}}, {"commit_id": POLICY}, {"state": "DISMISSED"}):
            self.api.pages.return_value = [original | change]
            with self.assertRaisesRegex(ControlError, "full-review-binding"):
                self.collect()

    def test_referenced_comment_cannot_disappear_and_snapshot_is_not_called_historical_bytes(self):
        review = self.copilot_fixture()
        self.proof["evidence"]["finding_comment_ids"] = [30]
        self.api.pages.side_effect = [[review], []]
        with self.assertRaisesRegex(ControlError, "comment-missing"):
            self.collect()
        comment = {"id": 30, "body": "Historical finding", "user": {"id": 175728472, "type": "Bot"}}
        self.api.pages.side_effect = [[review], [comment]]
        result = self.collect()
        self.assertEqual([comment], result["referenced_comments"])
        self.assertIn("historical-byte-digests-unavailable", result["comment_snapshot"])

    def test_governed_exemption_retains_real_evidence_without_synthetic_review(self):
        self.proof["route"] = "ancestry"
        self.proof["evidence"] = {"head": HEAD, "unchanged_tree": True}
        result = self.collect()
        self.assertEqual(self.proof["evidence"], result["evidence"])
        self.assertEqual("governed-exemption", result["kind"])
        self.api.call.assert_not_called()


if __name__ == "__main__":
    unittest.main()
