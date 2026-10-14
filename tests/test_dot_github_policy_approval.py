"""Exercise native one-person admission, exact binding and duplicate reuse."""

import copy
import importlib.util
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "dot_github_approval", ROOT / "scripts/dot-github-policy-approval.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
ERROR = MODULE.EVIDENCE.VerificationError


def protected_environment():
    return {"id": 77, "name": MODULE.ENVIRONMENT, "can_admins_bypass": False,
            "deployment_branch_policy": {"protected_branches": True,
                                         "custom_branch_policies": False},
            "protection_rules": [{"type": "branch_policy"},
                {"type": "required_reviewers", "prevent_self_review": False,
                 "reviewers": [{"type": "User", "reviewer":
                    {"id": MODULE.APPROVER_ID, "login": MODULE.APPROVER_LOGIN}}]}]}


def review():
    return {"state": "approved", "user": {"id": MODULE.APPROVER_ID,
            "login": MODULE.APPROVER_LOGIN}, "environments": [{"id": 77}]}


class Client:
    def __init__(self, payload):
        self.payload = payload

    def get(self, path):
        return copy.deepcopy(self.payload)


class EnvironmentTests(unittest.TestCase):
    def test_one_user_can_approve_their_own_operation(self):
        self.assertEqual(MODULE.approval_environment(Client(protected_environment())), 77)
        MODULE.native_approval(Client([review()]), 100, 77)

    def test_missing_or_rejected_review_never_authorizes(self):
        for state in (None, "rejected", "pending"):
            r = review()
            r["state"] = state
            with self.subTest(state=state), self.assertRaises(ERROR):
                MODULE.native_approval(Client([r]), 100, 77)
        with self.assertRaises(ERROR):
            MODULE.native_approval(Client([]), 100, 77)

    def test_other_users_and_environments_do_not_authorize(self):
        for field, bad in (("id", 1), ("id", True), ("login", "other")):
            r = review()
            r["user"][field] = bad
            with self.subTest(field=field, bad=bad), self.assertRaises(ERROR):
                MODULE.native_approval(Client([r]), 100, 77)
        with self.assertRaises(ERROR):
            MODULE.native_approval(Client([review()]), 100, 78)

    def test_missing_gate_self_review_bypass_or_second_reviewer_is_rejected(self):
        cases = []
        for value in (True, 0, None):
            e = protected_environment()
            e["can_admins_bypass"] = value
            cases.append(e)
        e = protected_environment()
        e["protection_rules"][1]["prevent_self_review"] = True
        cases.append(e)
        e = protected_environment()
        e["protection_rules"][1]["reviewers"].append(
            {"type": "User", "reviewer": {"id": 2, "login": "other"}})
        cases.append(e)
        e = protected_environment()
        e["protection_rules"] = []
        cases.append(e)
        for e in cases:
            with self.subTest(environment=e), self.assertRaises(ERROR):
                MODULE.approval_environment(Client(e))


class BindingTests(unittest.TestCase):
    def test_hash_changes_when_reviewed_inputs_change(self):
        binding = {"base_ref": "develop", "head_repository": MODULE.REPOSITORY,
                   "head_ref": "feature", "author": "litroc", "author_type": "User",
                   "labels_sha256": "labels"}
        pr = {"title": "change", "body": "body", "_metadata_revision": None}
        env = {"REPOSITORY": MODULE.REPOSITORY, "WORKFLOW_SHA": "c" * 40,
               "WORKFLOW_REF": MODULE.EVIDENCE.SOURCE_WORKFLOW_REF,
               "PR_NUMBER": "1", "EVENT_BASE": "a" * 40, "EVENT_HEAD": "b" * 40}
        with mock.patch.object(MODULE.EVIDENCE, "validate_source"), \
             mock.patch.object(MODULE.EVIDENCE, "event_pr_binding", return_value=binding), \
             mock.patch.object(MODULE.EVIDENCE, "validate_live_pr", return_value=pr), \
             mock.patch.object(MODULE, "approval_environment", return_value=77):
            client = Client({"commit": {"sha": "c" * 40}})
            original = MODULE.revision(client, env)[1]
            self.assertEqual(MODULE.revision(client, env)[1], original)
            for key, value in (("EVENT_HEAD", "d" * 40), ("EVENT_BASE", "d" * 40),
                               ("LI219_EVENT_MODE", "enabled")):
                changed = dict(env, **{key: value})
                self.assertNotEqual(MODULE.revision(client, changed)[1], original)
            with self.assertRaisesRegex(ERROR, "active approval controller"):
                MODULE.revision(client, dict(env, WORKFLOW_SHA="d" * 40))
            with self.assertRaisesRegex(ERROR, "active approval controller"):
                MODULE.revision(Client({"commit": {"sha": "d" * 40}}), env)
            for key, value in (("title", "different"), ("body", "different"),
                               ("_metadata_revision", "2026-10-13T00:00:00Z")):
                changed = dict(pr, **{key: value})
                with mock.patch.object(MODULE.EVIDENCE, "validate_live_pr", return_value=changed):
                    self.assertNotEqual(MODULE.revision(client, env)[1], original)


class ReuseTests(unittest.TestCase):
    def setUp(self):
        self.value = {"base": "a" * 40, "source": "b" * 40,
                      "base_ref": "develop", "environment_id": 77}
        self.run = {"id": 100, "path": MODULE.WORKFLOW, "event": "pull_request_target",
                    "head_sha": "a" * 40, "head_branch": "develop", "run_attempt": 1,
                    "status": "completed", "conclusion": "success"}
        self.jobs = [{"id": i, "name": name, "run_id": 100, "run_attempt": 1,
                      "head_sha": "a" * 40, "status": "completed", "conclusion": "success"}
                     for i, name in enumerate((MODULE.APPROVAL_JOB, MODULE.FINAL_JOB), 1)]

    def client(self, changed_source=False):
        owner = self
        class NativeClient:
            def get(self, path):
                if "/actions/runs?" in path:
                    return {"workflow_runs": [copy.deepcopy(owner.run)]}
                if path.endswith("/approvals"):
                    return [review()]
                if "/contents/" in path:
                    sha = "f" * 40 if changed_source and path.endswith("b" * 40) else "e" * 40
                    return {"type": "file", "sha": sha}
                if "/attempts/1/jobs" in path:
                    return {"jobs": copy.deepcopy(owner.jobs)}
                raise AssertionError(path)
        return NativeClient()

    def test_duplicate_reuses_original_native_approval(self):
        with mock.patch.object(MODULE, "log_binding", return_value="c" * 64):
            self.assertEqual(MODULE.reusable_approval(self.client(), self.value, "c" * 64, 101), 100)

    def test_changed_binding_code_or_failed_native_job_cannot_be_reused(self):
        with mock.patch.object(MODULE, "log_binding", return_value="d" * 64):
            self.assertIsNone(MODULE.reusable_approval(self.client(), self.value, "c" * 64, 101))
        with mock.patch.object(MODULE, "log_binding", return_value="c" * 64):
            self.assertIsNone(MODULE.reusable_approval(self.client(True), self.value, "c" * 64, 101))
            self.jobs[0]["conclusion"] = "failure"
            self.assertIsNone(MODULE.reusable_approval(self.client(), self.value, "c" * 64, 101))

    def test_cancellation_after_approval_does_not_require_another_human_review(self):
        for conclusion in ("cancelled", "failure"):
            with mock.patch.dict(self.run, {"conclusion": conclusion}), \
                 mock.patch.object(MODULE, "log_binding", return_value="c" * 64):
                self.assertEqual(MODULE.reusable_approval(self.client(), self.value, "c" * 64, 101), 100)

    def test_reused_human_approval_never_replaces_failed_technical_verification(self):
        env = {"GITHUB_RUN_ATTEMPT": "1", "GITHUB_RUN_ID": "101",
               "APPROVAL_BINDING": "c" * 64, "APPROVAL_REUSE_RUN": "100"}
        with mock.patch.dict(MODULE.os.environ, env), \
             mock.patch.object(sys,
                               "argv", ["approval", "verify"]), \
             mock.patch.object(MODULE, "revision", return_value=(self.value, "c" * 64)), \
             mock.patch.object(MODULE.EVIDENCE, "GitHubClient"), \
             mock.patch.object(MODULE, "reusable_approval", return_value=100), \
             mock.patch.object(MODULE.EVIDENCE, "verify", side_effect=ERROR("technical failure")) as verify:
            self.assertEqual(MODULE.main(), 1)
            verify.assert_called_once()

    def test_unprotected_branch_run_other_attempt_or_current_run_is_not_reused(self):
        for key, value in (("head_branch", "feature"), ("run_attempt", 2),
                           ("event", "pull_request"), ("head_sha", "d" * 40)):
            with mock.patch.dict(self.run, {key: value}):
                self.assertIsNone(MODULE.reusable_approval(self.client(), self.value, "c" * 64, 101))
        self.assertIsNone(MODULE.reusable_approval(self.client(), self.value, "c" * 64, 100))

    def test_native_log_marker_must_be_unique(self):
        for data in (b"", ("LI319_APPROVAL_BINDING=" + "a" * 64 + "\n") .encode() * 2):
            with mock.patch.object(MODULE.subprocess, "run", return_value=mock.Mock(stdout=data)):
                with self.assertRaises(ERROR):
                    MODULE.log_binding(None, 1)


if __name__ == "__main__":
    unittest.main()
