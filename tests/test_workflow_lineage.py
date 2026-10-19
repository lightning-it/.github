"""Real production lineage and native readers; offline transport grants no admission."""

import copy
import hashlib
import json
import subprocess
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import test_workflow_control as original
import test_workflow_recovery as recovery_fixture

control = original.control
recovery = recovery_fixture.recovery
ROOT = Path(__file__).resolve().parents[1]
BB1 = "bb1a5df9f54c5f98547048297e7e367cc382543e"
MAIN678 = "678560bdd02d32ccae59c430f0047f85a81ec72e"
MAIN4F12 = "4f12f255b4375907967d87a5462cc99930c5f3c7"
MAINB634 = "b634a997ed0daa541945456f468512f7164c46ca"
MAIN1E48 = "1e48bd0b8fab9605558d747615f60696f2deb819"
MAIN652 = "652c1e48b40d643a5d954e4dbe8533079f3cb53d"
# The reader parameter models a future independent native selection. Neither
# this test nor the lineage file admits this actual, currently unselected commit.
CANDIDATE = "4dbd1a7d63a3ffae5ada5e6e0127a847585a051d"
PREDECESSORS = [
    "7215c32d9cc957e560110493d0d94cba14c8287b",
    "31cbb39db553a04c3b7badb53b2bcf18d88293d1",
    "b815cefb4a5f18cd97b3947c789b6db59fedf991",
    "6ae02b7b44e9a6a8708dd4e9e75f9491d0b472a4",
    "6845abfda6069e33b3939736c88177dabc9bf315",
    "8a96861b663a994a6dfd77ced2e984f65cc7d436",
    "6c569721323d24cabad43f8caa162be60a7afdcb",
    "f1bd4951288b1ce52a6cb30ab6432e201cf45507",
]


class AdoptedLineageTests(unittest.TestCase):
    def policy(self, api):
        api.file.return_value = (ROOT / ".lit/workflow-control.json").read_bytes()
        return control.policy(api, original.REPO, original.BASE, CANDIDATE)

    def transport(self, records):
        """Only replace native artifact download; execute real operation/proof readers."""
        def download(arguments, **kwargs):
            self.assertEqual(["gh", "run", "download"], arguments[:3])
            name = arguments[arguments.index("--name") + 1]
            target = Path(arguments[arguments.index("--dir") + 1])
            filename, value = records[name]
            (target / filename).write_text(json.dumps(value))
            return subprocess.CompletedProcess(arguments, 0, b"", b"")
        return patch.object(control.subprocess, "run", side_effect=download)

    def test_real_config_is_exact_retained_transitive_closure_without_self_or_unknown(self):
        value = json.loads((ROOT / ".lit/workflow-source-lineage.json").read_bytes())
        # Exact sequence catches deletion, duplication, replacement, unknown or
        # forward/self additions without adding a production validator/framework.
        self.assertEqual({"version": 1, "accepted_predecessors": [*PREDECESSORS, BB1, MAIN678, MAIN4F12, MAINB634, MAIN1E48, MAIN652]}, value)
        policy = json.loads((ROOT / ".lit/workflow-control.json").read_bytes())
        self.assertEqual([], policy["accepted_sources"])
        self.assertNotIn(CANDIDATE, value["accepted_predecessors"])

    def test_real_policy_retains_bb1_and_old_pins_but_consumer_cannot_admit_unknown(self):
        api = Mock()
        value = self.policy(api)
        self.assertEqual({CANDIDATE, BB1, MAIN678, MAIN4F12, MAINB634, MAIN1E48, MAIN652, *PREDECESSORS}, set(value["accepted_sources"]))
        consumer = json.loads((ROOT / ".lit/workflow-control.json").read_bytes())
        api.file.return_value = json.dumps(consumer | {"accepted_sources": ["e" * 40]}).encode()
        with self.assertRaisesRegex(control.ControlError, "consumer-cannot-admit-central-source"):
            control.policy(api, original.REPO, original.BASE, CANDIDATE)

    def ingress(self, *, defect=None):
        pull = original.pull()
        native = original.run() | {"status": "completed", "conclusion": "success"}
        if defect == "native":
            native["workflow_url"] = "https://api.github.com/repos/foreign/repo/actions/required_workflows/77"
        if defect == "pending":
            native["status"] = "in_progress"
        record = {"version": 1, "source_sha": BB1, "route": "copilot", "binding": control.binding(pull)}
        if defect == "source": record["source_sha"] = "e" * 40
        if defect == "tuple": record["binding"]["base"] = "e" * 40
        api = Mock()
        config = self.policy(api)

        def pages(path, key=None):
            if "/runs?head_sha=" in path: return [copy.deepcopy(native)]
            if path.endswith("/attempts/1/jobs"):
                return [{"id": 11, "run_id": 10, "name": "Current revision review", "conclusion": "success"}]
            if path.endswith("/runs/10/artifacts"):
                return [{"id": 12, "name": "control-proof-1", "expired": False}]
            raise AssertionError(path)

        api.pages.side_effect = pages
        api.call.side_effect = lambda path: copy.deepcopy(native)
        with self.transport({"control-proof-1": ("control-proof.json", record)}):
            return control.check_native_control(api, original.REPO, pull, config)

    def test_actual_native_ingress_reader_accepts_adopted_bb1_with_real_policy(self):
        self.assertEqual(BB1, self.ingress()["source_sha"])

    def test_unknown_source_wrong_native_origin_or_tuple_are_still_rejected(self):
        for defect in ("source", "native", "tuple", "pending"):
            with self.subTest(defect=defect), self.assertRaises(control.ControlError):
                self.ingress(defect=defect)

    def previous_bb1(self):
        fixture = recovery_fixture.RecoveryTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        # Use actual native artifact/operation readers, not the earlier unit
        # fixture's patched record helpers. Lineage always comes from disk.
        fixture.op.stop()
        fixture.outcome_patch.stop()
        fixture.record["source_sha"] = BB1
        fixture.outcome["source_sha"] = BB1
        fixture.api.native_job_log.return_value = (
            f'"workflow_sha": "{BB1}", "workflow_repository": "{control.SOURCE}", '
            f'"workflow_file_path": "{control.WORKFLOW}"'
        )
        fixture.artifacts[:] = [{"name": name, "expired": False} for name in (
            "control-operation-1", "control-review-outcome-1")]
        return fixture

    def recovery_plan(self, fixture, *, approve=False):
        records = {
            "control-operation-1": ("control-operation.json", fixture.record),
            "control-review-outcome-1": ("control-review-outcome.json", fixture.outcome),
        }
        with self.transport(records):
            if not approve:
                return recovery.plan(fixture.api, recovery_fixture.REPO, fixture.pull, CANDIDATE, fixture.native)
            planned = recovery.plan(fixture.api, recovery_fixture.REPO, fixture.pull, CANDIDATE, fixture.native)
            return recovery.authorize(fixture.api, recovery_fixture.REPO, fixture.pull,
                                      CANDIDATE, fixture.native, control.digest(planned))

    def test_actual_bb1_operation_and_outcome_are_retained_as_plan_not_release_authority(self):
        fixture = self.previous_bb1()
        result = self.recovery_plan(fixture)
        self.assertEqual(BB1, result["failed_source"])
        self.assertEqual(1, result["additional_attempts"])
        self.assertFalse(result["release_authorized"])
        fixture.api.call.assert_not_called()

    def test_bb1_recovery_preserves_native_terminal_tuple_and_outcome_guards(self):
        for defect in ("native", "tuple", "pending", "delivered", "missing-outcome", "expired", "outcome", "source", "log"):
            fixture = self.previous_bb1()
            if defect == "native": fixture.native["workflow_url"] = "https://example.invalid/foreign"
            elif defect == "tuple": fixture.record["binding"]["head"] = "e" * 40
            elif defect == "pending": fixture.failed["status"] = "in_progress"
            elif defect == "delivered": fixture.job["steps"][2]["conclusion"] = "success"
            elif defect == "missing-outcome": fixture.artifacts.pop()
            elif defect == "expired": fixture.artifacts[-1]["expired"] = True
            elif defect == "outcome": fixture.outcome["result_produced"] = True
            elif defect == "source": fixture.record["source_sha"] = "e" * 40
            else: fixture.api.native_job_log.return_value = "candidate assertion"
            try:
                with self.subTest(defect=defect), self.assertRaises(control.ControlError):
                    self.recovery_plan(fixture)
            finally:
                fixture.doCleanups()

    def test_bb1_retention_does_not_waive_real_native_approval(self):
        fixture = self.previous_bb1()
        fixture.api.call.return_value = []
        with self.assertRaisesRegex(control.ControlError, "native-human-approval-required"):
            self.recovery_plan(fixture, approve=True)

    def test_bb1_recovery_can_use_only_the_existing_bound_native_approval(self):
        fixture = self.previous_bb1()
        approval = {"state": "approved", "user": {"id": 60, "type": "User"},
                    "environments": [{"id": 50, "name": "normal-release-promotion-approval"}]}
        fixture.api.call.side_effect = lambda path: [approval] if path.endswith("/approvals") else fixture.pull
        result = self.recovery_plan(fixture, approve=True)
        self.assertEqual(BB1, result["failed_source"])
        self.assertEqual(60, result["approval"]["user"]["id"])
        self.assertFalse(result["release_authorized"])
        approval["environments"][0]["id"] = 99
        with self.assertRaisesRegex(control.ControlError, "recovery-exact-native-environment-approval"):
            self.recovery_plan(fixture, approve=True)

    def test_legacy_unknown_outcome_exception_cannot_be_relabelled_bb1(self):
        fixture = self.previous_bb1()
        fixture.artifacts.pop()
        log = fixture.api.native_job_log.return_value + (
            " We’re currently experiencing high demand Protected gateway failure category: single-contract-rejected"
        )
        fixture.api.native_job_log.return_value = log
        fixture.value["legacy_unknown_outcome_sha256"] = hashlib.sha256(log.encode()).hexdigest()
        fixture.comment["body"] = recovery.MARKER + json.dumps(fixture.value) + " -->"
        self.assertEqual("b815cefb4a5f18cd97b3947c789b6db59fedf991", recovery.LEGACY_SOURCE)
        with self.assertRaisesRegex(control.ControlError, "explicit-legacy-unknown-outcome"):
            self.recovery_plan(fixture)


if __name__ == "__main__":
    unittest.main()
