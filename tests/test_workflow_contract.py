"""Target contract regressions for actual architecture and activation boundaries."""

import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "lit-workflow-contract.py"
SPEC = importlib.util.spec_from_file_location("workflow_contract", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class WorkflowContractTests(unittest.TestCase):
    def setUp(self):
        self.contract = json.loads((ROOT / ".lit" / "workflow-target.json").read_text())

    def test_declared_target_is_valid_but_inactive(self):
        MODULE.validate(self.contract)
        self.assertEqual(self.contract["activation"], "inactive")

    def test_cycle_through_archive_to_source_is_rejected(self):
        self.contract["functions"][0]["depends_on"] = ["WF-07"]
        with self.assertRaisesRegex(MODULE.ContractError, "dependency-cycle"):
            MODULE.validate(self.contract)

    def test_new_source_cannot_claim_live_acceptance(self):
        for field, value in [("state", "live-verified"), ("activation", "active")]:
            with self.subTest(field=field):
                candidate = copy.deepcopy(self.contract)
                candidate[field] = value
                with self.assertRaisesRegex(MODULE.ContractError, "not-live-authority"):
                    MODULE.validate(candidate)

    def test_supplementary_cannot_become_central_source(self):
        self.contract["central_source"] = "lightning-it/ansible-collection-supplementary"
        with self.assertRaisesRegex(MODULE.ContractError, "central-source"):
            MODULE.validate(self.contract)

    def test_second_human_or_disallowed_self_approval_is_rejected(self):
        for field, value in [("classic_pr_approval_count", 1), ("normal_human_approvals", 2), ("normal_self_approval", False)]:
            with self.subTest(field=field):
                candidate = copy.deepcopy(self.contract)
                candidate["authorization"][field] = value
                with self.assertRaisesRegex(MODULE.ContractError, "single-person-authorization"):
                    MODULE.validate(candidate)

    def test_missing_security_or_review_dependency_is_rejected(self):
        self.contract["functions"][3]["depends_on"] = ["WF-02"]
        with self.assertRaisesRegex(MODULE.ContractError, "required-stage-dependency"):
            MODULE.validate(self.contract)

    def test_local_preparation_cannot_be_disconnected_from_pr_quality(self):
        self.contract["functions"][1]["depends_on"] = []
        with self.assertRaisesRegex(MODULE.ContractError, "required-stage-dependency"):
            MODULE.validate(self.contract)

    def test_local_preparation_cannot_acquire_an_undeclared_dependency(self):
        self.contract["functions"][0]["depends_on"] = ["WF-02"]
        with self.assertRaisesRegex(MODULE.ContractError, "dependency-cycle"):
            MODULE.validate(self.contract)

    def test_main_promotion_cannot_request_duplicate_cumulative_ai_review(self):
        self.contract["review"]["main_promotion_review"] = "request-new-cumulative-ai-review"
        with self.assertRaisesRegex(MODULE.ContractError, "review-policy"):
            MODULE.validate(self.contract)

    def test_review_failure_cannot_fallback_or_reuse_a_stale_result(self):
        for field, value in [("fallback", True), ("reuse_stale_review", True), ("budget_or_provider_failure", "pass")]:
            with self.subTest(field=field):
                candidate = copy.deepcopy(self.contract)
                candidate["review"][field] = value
                with self.assertRaisesRegex(MODULE.ContractError, "review-policy"):
                    MODULE.validate(candidate)

    def test_candidate_execution_and_all_secrets_are_rejected(self):
        for field in ["execute_candidate_for_authorization", "inherit_all_secrets"]:
            candidate = copy.deepcopy(self.contract)
            candidate["privacy"][field] = True
            with self.subTest(field=field), self.assertRaisesRegex(MODULE.ContractError, "privacy-boundary"):
                MODULE.validate(candidate)

    def test_archive_retention_cannot_be_replaced_with_run_retention(self):
        self.contract["evidence"]["archive"] = "github-actions-artifacts"
        with self.assertRaisesRegex(MODULE.ContractError, "evidence-policy"):
            MODULE.validate(self.contract)

    def test_missing_profile_is_rejected(self):
        del self.contract["profiles"]["container_image"]
        with self.assertRaisesRegex(MODULE.ContractError, "profile-coverage"):
            MODULE.validate(self.contract)

    def test_duplicate_function_cannot_hide_missing_function(self):
        self.contract["functions"][1] = copy.deepcopy(self.contract["functions"][0])
        with self.assertRaisesRegex(MODULE.ContractError, "function-identity"):
            MODULE.validate(self.contract)

    def test_each_profile_rejects_disabled_or_unconditional_publication_drift(self):
        for name, profile in self.contract["profiles"].items():
            with self.subTest(profile=name):
                candidate = copy.deepcopy(self.contract)
                declared = profile["artifact_publication"]
                candidate["profiles"][name]["artifact_publication"] = (
                    not declared if type(declared) is bool else True
                )
                with self.assertRaisesRegex(MODULE.ContractError, "profile-publication"):
                    MODULE.validate(candidate)

    def test_integer_fields_reject_boolean_substitutes(self):
        self.contract["authorization"]["normal_human_approvals"] = True
        with self.assertRaisesRegex(MODULE.ContractError, "single-person-authorization"):
            MODULE.validate(self.contract)

    def test_cli_rejects_unknown_fields_without_echoing_their_values(self):
        self.contract["private-value"] = "DO-NOT-ECHO-THIS-VALUE"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "contract.json"
            path.write_text(json.dumps(self.contract))
            result = subprocess.run([sys.executable, str(SCRIPT), str(path)], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("contract-shape", result.stdout)
        self.assertNotIn("DO-NOT-ECHO", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
