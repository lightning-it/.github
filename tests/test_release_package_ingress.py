"""The package component keeps all accepted proof bytes and fails closed."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import release_package_ingress as package
from workflow_control import ControlError, SOURCE, WORKFLOW, digest

REPO = "lightning-it/.github"
HEAD, BASE, MERGE, POLICY = (letter * 40 for letter in "abcd")


def fixtures():
    proof = {"version": 1, "source_sha": POLICY, "route": "codex",
             "binding": {"number": 8, "base_ref": "develop", "head": HEAD},
             "evidence": {"response": "complete review\n" + "x" * 10000}}
    ref = {"pull": 8, "merge": MERGE,
           "control": {"run": 10, "attempt": 2, "job": 12, "head": HEAD,
                       "source_sha": POLICY, "route": "codex", "artifact": "control-proof-2",
                       "proof_sha256": digest(proof)}}
    promotion = {"version": 1, "source_sha": POLICY, "route": "promotion",
                 "binding": {"number": 9, "base_ref": "main", "head_ref": "develop",
                             "base": BASE, "head": MERGE, "head_repository": REPO},
                 "authorization": {"approval": {"state": "approved", "user": {"id": 1}}},
                 "evidence": {"base": BASE, "head": MERGE, "integration_tree": HEAD,
                              "ingress": [ref]}}
    run = {"id": 10, "run_attempt": 2, "head_sha": HEAD, "status": "completed", "conclusion": "success",
           "workflow_id": 13, "workflow_url": f"https://api.github.com/repos/{REPO}/actions/required_workflows/13",
           "path": WORKFLOW}
    job = {"id": 12, "run_id": 10, "name": "Current revision review", "conclusion": "success",
           "workflow_repository": SOURCE, "workflow_file_path": WORKFLOW, "workflow_sha": POLICY,
           "check_run_id": 14}
    pull = {"number": 8, "merged": True, "merge_commit_sha": MERGE,
            "base": {"ref": "develop", "repo": {"full_name": REPO}}, "head": {"sha": HEAD}}
    return promotion, proof, run, job, pull


class IngressPackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name) / "ingress.json"
        self.promotion, self.proof, self.run, self.job, self.pull = fixtures()
        self.api = Mock()
        self.api.call.side_effect = lambda path: self.run if "/attempts/" in path else self.pull
        self.api.pages.return_value = [self.job]
        self.fetch = patch.object(package, "artifact_record", return_value=self.proof).start()
        self.addCleanup(patch.stopall)

    def assemble(self, **changes):
        args = {"api": self.api, "repository": REPO, "promotion": self.promotion,
                "expected_digest": digest(self.promotion), "destination": self.output}
        args.update(changes)
        return package.assemble(**args)

    def assert_clean_failure(self, category):
        with self.assertRaisesRegex((ControlError, OSError), category):
            self.assemble()
        self.assertEqual([], list(self.output.parent.iterdir()))

    def test_full_evidence_and_approval_survive_exact_digest_binding(self):
        result = self.assemble()
        raw = self.output.read_bytes()
        document = json.loads(raw)
        self.assertEqual(self.promotion, document["promotion"])
        self.assertEqual(self.proof, document["ingress"][0]["proof"])
        self.assertEqual(digest(self.proof), document["ingress"][0]["reference"]["control"]["proof_sha256"])
        self.assertEqual(hashlib.sha256(raw).hexdigest(), result["sha256"])
        self.assertEqual(len(raw), result["bytes"])
        self.assertFalse(document["complete_release"])
        self.assertEqual(0o600, self.output.stat().st_mode & 0o777)
        self.api.call.assert_any_call(f"repos/{REPO}/actions/runs/10/attempts/2")
        self.fetch.assert_called_once_with(self.api, REPO, self.run, "control-proof-2", "control-proof.json")

    def test_output_is_deterministic_across_duplicate_read_only_assembly(self):
        first = self.assemble()
        second = self.assemble(destination=self.output.with_name("second.json"))
        self.assertEqual(first, second)
        self.assertEqual(self.output.read_bytes(), self.output.with_name("second.json").read_bytes())

    def test_promotion_digest_mismatch_precedes_network_and_output(self):
        with self.assertRaisesRegex(ControlError, "promotion-digest"):
            self.assemble(expected_digest="0" * 64)
        self.api.call.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_duplicate_or_malformed_reference_precedes_network(self):
        original = copy.deepcopy(self.promotion)
        for change in (lambda p: p["evidence"]["ingress"].append(copy.deepcopy(p["evidence"]["ingress"][0])),
                       lambda p: p["evidence"]["ingress"][0]["control"].update(attempt=True),
                       lambda p: p["evidence"]["ingress"][0]["control"].update(artifact="control-proof-3")):
            self.promotion = copy.deepcopy(original)
            change(self.promotion)
            self.assert_clean_failure("package-")
        self.api.call.assert_not_called()

    def test_changed_full_proof_fails_without_published_partial_component(self):
        self.proof["evidence"]["response"] += "tampered"
        self.assert_clean_failure("ingress-digest")

    def test_wrong_native_attempt_failed_run_or_foreign_workflow_is_rejected(self):
        original = dict(self.run)
        for changes in ({"run_attempt": 3}, {"id": 11}, {"head_sha": BASE},
                        {"conclusion": "failure"}, {"status": "in_progress"},
                        {"workflow_url": "https://attacker.invalid/required_workflows/13"}):
            self.run = original | changes
            self.assert_clean_failure("native-attempt")
        self.fetch.assert_not_called()

    def test_native_job_identity_is_required(self):
        original = dict(self.job)
        for changes in ({"name": "Other gate"}, {"conclusion": "failure"}, {"id": 99}):
            self.api.pages.return_value = [original | changes]
            self.assert_clean_failure("native-job")
        self.fetch.assert_not_called()

    def test_source_revision_must_match_the_accepted_reference(self):
        self.proof["source_sha"] = BASE
        self.promotion["evidence"]["ingress"][0]["control"]["proof_sha256"] = digest(self.proof)
        self.assert_clean_failure("ingress-proof")

    def test_foreign_or_changed_merge_cannot_substitute_for_accepted_ingress(self):
        original = copy.deepcopy(self.pull)
        for changes in ({"merged": False}, {"merge_commit_sha": BASE}, {"number": 99},
                        {"base": {"ref": "develop", "repo": {"full_name": "other/repo"}}}):
            self.pull = original | changes
            self.assert_clean_failure("merged-ingress")

    def test_missing_or_expired_artifact_is_a_blocking_failure(self):
        self.fetch.side_effect = ControlError("protected-native-artifact-missing-or-ambiguous")
        self.assert_clean_failure("artifact-missing")

    def test_total_package_budget_does_not_truncate_or_publish(self):
        with self.assertRaisesRegex(ControlError, "package-size-limit"):
            self.assemble(maximum=2000)
        self.assertEqual([], list(self.output.parent.iterdir()))

    def test_full_review_fetch_failure_removes_incomplete_output(self):
        loader = Mock(side_effect=ControlError("review-payload-expired"))
        with self.assertRaisesRegex(ControlError, "review-payload-expired"):
            self.assemble(review_loader=loader)
        self.assertEqual([], list(self.output.parent.iterdir()))

    def test_existing_output_and_symlink_remain_untouched(self):
        self.output.write_bytes(b"previous evidence")
        with self.assertRaisesRegex(ControlError, "output-exists"):
            self.assemble()
        self.assertEqual(b"previous evidence", self.output.read_bytes())
        self.api.call.assert_not_called()
        link = self.output.with_name("link.json")
        link.symlink_to(self.output)
        with self.assertRaisesRegex(ControlError, "output-exists"):
            self.assemble(destination=link)
        self.assertEqual(b"previous evidence", self.output.read_bytes())

    def test_competing_publication_is_not_overwritten(self):
        original = package.os.link
        def collision(source, destination):
            destination.write_bytes(b"winner")
            return original(source, destination)
        with patch.object(package.os, "link", side_effect=collision), self.assertRaises(FileExistsError):
            self.assemble()
        self.assertEqual(b"winner", self.output.read_bytes())
        self.assertEqual([self.output], list(self.output.parent.iterdir()))


if __name__ == "__main__":
    unittest.main()
