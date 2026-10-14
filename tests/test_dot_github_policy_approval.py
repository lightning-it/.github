"""Exercise native one-person admission, exact binding and duplicate reuse."""

import copy
import importlib.util
import sys
import unittest
from pathlib import Path
from unittest import mock

import yaml

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
    def test_workflow_title_remains_consumable_by_existing_required_locator(self):
        spec = importlib.util.spec_from_file_location(
            "existing_required_locator", ROOT / "scripts/review-event-reconcile.py")
        locator = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = locator
        spec.loader.exec_module(locator)
        document = yaml.safe_load((ROOT / MODULE.WORKFLOW).read_text())
        title = document["run-name"].strip()
        for expression, value in (("github.event.pull_request.number", "4"),
                                  ("github.event.action", "opened"),
                                  ("github.event.pull_request.head.sha", "b" * 40)):
            title = title.replace("${{ " + expression + " }}", value)
        api = "https://api.github.com/repos/" + MODULE.REPOSITORY
        pr = {"number": 4, "base": {"ref": "develop", "sha": "a" * 40},
              "head": {"ref": "feature", "sha": "b" * 40,
                       "repo": {"full_name": MODULE.REPOSITORY}}}
        record = {"number": 4, "url": api + "/pulls/4",
                  "base": dict(pr["base"], repo={"url": api}),
                  "head": {"ref": "feature", "sha": "b" * 40, "repo": {"url": api}}}
        run = {"id": 1, "workflow_id": 2, "event": "pull_request_target",
               "name": "Protected dot-github current-revision verifier",
               "path": MODULE.WORKFLOW, "workflow_url": api + "/actions/required_workflows/2",
               "head_sha": "b" * 40, "head_branch": "feature", "display_title": title,
               "repository": {"full_name": MODULE.REPOSITORY},
               "head_repository": {"full_name": MODULE.REPOSITORY}, "pull_requests": [record]}
        self.assertTrue(locator.required_locator(run, MODULE.REPOSITORY, pr))
        for action in MODULE.EVIDENCE.PRODUCER_ACTIONS:
            with self.subTest(action=action):
                run['display_title'] = title.replace(' opened ', f' {action} ')
                self.assertTrue(locator.required_locator(run, MODULE.REPOSITORY, pr))

    def test_hash_changes_when_reviewed_inputs_change(self):
        binding = {"base_ref": "develop", "head_repository": MODULE.REPOSITORY,
                   "head_ref": "feature", "author": "litroc", "author_type": "User",
                   "labels_sha256": "labels"}
        pr = {"title": "change", "body": "body", "_metadata_revision": None}
        pr["head"] = {"repo": {"id": MODULE.REPOSITORY_ID}}
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
            changed = dict(pr, head={"repo": {"id": 987654321}})
            with mock.patch.object(MODULE.EVIDENCE, "validate_live_pr", return_value=changed):
                self.assertNotEqual(MODULE.revision(client, env)[1], original)


class ReuseTests(unittest.TestCase):
    def setUp(self):
        self.value = {"base": "a" * 40, "source": "b" * 40,
                      "head": "c" * 40, "head_ref": "feature", "pr": 4,
                      "head_repository_id": MODULE.REPOSITORY_ID,
                      "base_ref": "develop", "environment_id": 77, "head_repository": MODULE.REPOSITORY}
        api = "https://api.github.com/repos/" + MODULE.REPOSITORY
        record = {"number": 4, "url": api + "/pulls/4",
                  "base": {"sha": "a" * 40, "ref": "develop", "repo": {"id": MODULE.REPOSITORY_ID}},
                  "head": {"sha": "c" * 40, "ref": "feature", "repo": {"id": MODULE.REPOSITORY_ID}}}
        self.run = {"id": 100, "path": MODULE.WORKFLOW, "event": "pull_request_target",
                    "head_sha": "c" * 40, "head_branch": "feature", "run_attempt": 1,
                    "workflow_id": 2, "workflow_url": api + "/actions/required_workflows/2",
                    "repository": {"id": MODULE.REPOSITORY_ID},
                    "head_repository": {"id": MODULE.REPOSITORY_ID}, "pull_requests": [record],
                    "status": "completed", "conclusion": "success"}
        self.jobs = [{"id": i, "name": name, "run_id": 100, "run_attempt": 1,
                      "head_sha": "c" * 40, "status": "completed", "conclusion": "success"}
                     for i, name in enumerate((MODULE.BINDING_JOB, MODULE.APPROVAL_JOB, MODULE.FINAL_JOB, MODULE.INACTIVE_METADATA_JOB), 1)]
        self.jobs[3]['conclusion'] = 'skipped'

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
                    return {"jobs": copy.deepcopy(owner.jobs), "total_count": len(owner.jobs)}
                if "/attempts/2/jobs" in path:
                    return {"jobs": copy.deepcopy(owner.recovered_jobs), "total_count": len(owner.recovered_jobs)}
                raise AssertionError(path)
        return NativeClient()

    def test_duplicate_reuses_original_native_approval(self):
        with mock.patch.object(MODULE, "log_binding", return_value="c" * 64):
            self.assertEqual(MODULE.reusable_approval(self.client(), self.value, "c" * 64, 101), 100)

    def test_user_fork_duplicate_reuses_exact_fork_identity(self):
        self.value["head_repository_id"] = 987654321
        self.run["head_repository"]["id"] = 987654321
        self.run["pull_requests"][0]["head"]["repo"]["id"] = 987654321
        with mock.patch.object(MODULE, "log_binding", return_value="c" * 64):
            self.assertEqual(MODULE.reusable_approval(self.client(), self.value, "c" * 64, 101), 100)

    def test_truncated_or_malformed_native_inventory_never_authorizes(self):
        delegate = self.client()
        class Truncated:
            count = 4
            def get(inner, path):
                result = delegate.get(path)
                if "/attempts/1/jobs" in path:
                    result["total_count"] = inner.count
                return result
        for count in (5, True, "4", None):
            client = Truncated()
            client.count = count
            with self.subTest(count=count), mock.patch.object(MODULE, "log_binding", return_value="c" * 64):
                with self.assertRaises(ERROR):
                    MODULE.reusable_approval(client, self.value, "c" * 64, 101)

    def test_complete_paginated_inventory_and_count_drift(self):
        self.jobs.extend({"id": i, "name": "other"} for i in range(5, 103))
        delegate = self.client()
        class Pages:
            drift = False
            def get(inner, path):
                result = delegate.get(path)
                if "/attempts/1/jobs" in path:
                    page = int(path.rsplit("page=", 1)[1])
                    result["jobs"] = result["jobs"][(page - 1) * 100:page * 100]
                    if inner.drift and page == 2:
                        result["total_count"] += 1
                return result
        client = Pages()
        with mock.patch.object(MODULE, "log_binding", return_value="c" * 64):
            self.assertEqual(MODULE.reusable_approval(client, self.value, "c" * 64, 101), 100)
            client.drift = True
            with self.assertRaisesRegex(ERROR, "count drifted"):
                MODULE.reusable_approval(client, self.value, "c" * 64, 101)

    def test_duplicate_job_ids_make_native_inventory_ambiguous(self):
        self.jobs.append(copy.deepcopy(self.jobs[0]))
        with self.assertRaisesRegex(ERROR, "inventory is ambiguous"):
            MODULE.reusable_approval(self.client(), self.value, "c" * 64, 101)

    def test_changed_binding_code_or_failed_native_job_cannot_be_reused(self):
        with mock.patch.object(MODULE, "log_binding", return_value="d" * 64):
            self.assertIsNone(MODULE.reusable_approval(self.client(), self.value, "c" * 64, 101))
        with mock.patch.object(MODULE, "log_binding", return_value="c" * 64):
            # Target develop and protected main may legitimately have different
            # blobs: reuse authenticates the native preflight's actual source.
            self.assertEqual(MODULE.reusable_approval(self.client(True), self.value, "c" * 64, 101), 100)
            self.jobs[0]["conclusion"] = "failure"
            with self.assertRaises(ERROR):
                MODULE.reusable_approval(self.client(), self.value, "c" * 64, 101)

    def test_reuse_requires_exact_native_preflight_source_marker(self):
        payload = ('LI319_APPROVAL_BINDING=' + 'c' * 64 + '\n'
                   + 'LI319_PROTECTED_SOURCE=' + self.value['source'] + '\n').encode()
        with mock.patch.object(MODULE.subprocess, 'run', return_value=mock.Mock(stdout=payload)):
            self.assertEqual(MODULE.reusable_approval(self.client(True), self.value, 'c' * 64, 101), 100)
        changed = payload.replace(self.value['source'].encode(), b'd' * 40)
        with mock.patch.object(MODULE.subprocess, 'run', return_value=mock.Mock(stdout=changed)):
            self.assertIsNone(MODULE.reusable_approval(self.client(), self.value, 'c' * 64, 101))
            self.prepare_recovery()
            with self.assertRaises(ERROR):
                MODULE.validate_final_recovery(self.recovery_client(), self.value, 'c' * 64, 100)
        self.run['run_attempt'] = 1
        self.run['status'] = 'completed'
        self.run['conclusion'] = 'failure'
        for bad in (payload.split(b'LI319_PROTECTED_SOURCE')[0], payload + payload):
            with mock.patch.object(MODULE.subprocess, 'run', return_value=mock.Mock(stdout=bad)), self.assertRaises(ERROR):
                MODULE.reusable_approval(self.client(), self.value, 'c' * 64, 101)

    def test_final_job_timeout_has_margin_for_both_existing_waits(self):
        document = yaml.safe_load((ROOT / MODULE.WORKFLOW).read_text())
        final = document['jobs']['verify-dot-github-current-revision']
        self.assertGreaterEqual(final['timeout-minutes'], 18)

    def test_rejected_other_revision_does_not_block_new_native_admission(self):
        data = ('LI319_APPROVAL_BINDING=' + 'c' * 64 + '\n'
                + 'LI319_PROTECTED_SOURCE=' + self.value['source'] + '\n').encode()
        with mock.patch.object(MODULE, 'native_approval', side_effect=ERROR('native approval is rejected or unauthorized')), \
             mock.patch.object(MODULE.subprocess, 'run', return_value=mock.Mock(stdout=data)):
            self.assertIsNone(MODULE.reusable_approval(self.client(), self.value, 'd' * 64, 101))
            with self.assertRaisesRegex(ERROR, 'rejected or unauthorized'):
                MODULE.reusable_approval(self.client(), self.value, 'c' * 64, 101)

    def test_interruption_after_native_approval_does_not_request_reapproval(self):
        self.run["conclusion"] = "failure"
        self.jobs[1]["conclusion"] = "failure"
        with mock.patch.object(MODULE, "log_binding", return_value="c" * 64):
            self.assertEqual(MODULE.reusable_approval(self.client(), self.value, "c" * 64, 101), 100)

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
             mock.patch.object(MODULE, "metadata_controller"), \
             mock.patch.object(MODULE.EVIDENCE, "verify", side_effect=ERROR("technical failure")) as verify:
            self.assertEqual(MODULE.main(), 1)
            verify.assert_called_once()

    def test_unprotected_branch_run_other_attempt_or_current_run_is_not_reused(self):
        for key, value in (("head_branch", "different"), ("run_attempt", 3),
                           ("event", "pull_request"), ("head_sha", "d" * 40)):
            with mock.patch.dict(self.run, {key: value}):
                self.assertIsNone(MODULE.reusable_approval(self.client(), self.value, "c" * 64, 101))
        self.assertIsNone(MODULE.reusable_approval(self.client(), self.value, "c" * 64, 100))

    def test_recovered_final_job_reuses_original_human_approval(self):
        self.prepare_recovery()
        self.run.update(status='completed', conclusion='success')
        self.recovered_jobs = [dict(self.jobs[2], id=4, run_attempt=2, conclusion='success')]
        with mock.patch.object(MODULE, 'log_binding', return_value='c' * 64):
            self.assertEqual(MODULE.reusable_approval(self.recovery_client(), self.value, 'c' * 64, 101), 100)

    def test_recovery_reuse_rejects_wrong_attempt_or_additional_effects(self):
        self.prepare_recovery()
        self.run.update(status='completed', conclusion='success')
        self.recovered_jobs = [dict(self.jobs[2], id=4, run_attempt=2, conclusion='success')]
        with mock.patch.object(MODULE, 'log_binding', return_value='c' * 64):
            for field, bad in (('run_id', 101), ('run_attempt', 1), ('name', MODULE.APPROVAL_JOB)):
                with mock.patch.dict(self.recovered_jobs[0], {field: bad}), self.assertRaises(ERROR):
                    MODULE.reusable_approval(self.recovery_client(), self.value, 'c' * 64, 101)
            self.recovered_jobs.append(dict(self.recovered_jobs[0], id=5))
            with self.assertRaises(ERROR):
                MODULE.reusable_approval(self.recovery_client(), self.value, 'c' * 64, 101)

    def test_candidate_run_requires_native_ruleset_identity_and_exact_pr_tuple(self):
        api = "https://api.github.com/repos/" + MODULE.REPOSITORY
        for key, value in (("workflow_url", api + "/actions/workflows/2"),
                           ("pull_requests", []), ("repository", {"id": 2}),
                           ("head_repository", {"id": 2})):
            with mock.patch.dict(self.run, {key: value}):
                self.assertIsNone(MODULE.reusable_approval(self.client(), self.value, "c" * 64, 101))
        for side, key, value in (("base", "sha", "d" * 40), ("base", "ref", "feature"),
                                 ("head", "sha", "d" * 40)):
            record = copy.deepcopy(self.run["pull_requests"])
            record[0][side][key] = value
            with mock.patch.dict(self.run, {"pull_requests": record}):
                self.assertIsNone(MODULE.reusable_approval(self.client(), self.value, "c" * 64, 101))

    def test_native_log_marker_must_be_unique(self):
        for data in (b"", ("LI319_APPROVAL_BINDING=" + "a" * 64 + "\n") .encode() * 2):
            with mock.patch.object(MODULE.subprocess, "run", return_value=mock.Mock(stdout=data)):
                with self.assertRaises(ERROR):
                    MODULE.log_binding(None, 1, self.value['source'])

    def test_real_native_log_transport_captures_color_without_terminal_output(self):
        payload = (b'2026-10-14T11:15:36Z \x1b[32mcontainer progress\x1b[0m\n'
                   + ('2026-10-14T11:15:36Z LI319_APPROVAL_BINDING=' + 'c'*64 + '\n'
                      + '2026-10-14T11:15:36Z LI319_PROTECTED_SOURCE=' + self.value['source'] + '\n').encode())
        with mock.patch.object(MODULE.subprocess, 'run', return_value=mock.Mock(stdout=payload)) as request:
            self.assertEqual(MODULE.log_binding(None, 1, self.value['source']), 'c'*64)
            args, kwargs = request.call_args
            self.assertEqual(args[0], ['gh', 'api', '--allow-escape-sequences',
                                      'repos/lightning-it/.github/actions/jobs/1/logs'])
            self.assertTrue(kwargs['capture_output'])
            self.assertEqual(kwargs['timeout'], 30)

    def test_pinned_runtime_real_cli_parser_supports_native_log_transport(self):
        # Run the installed CLI, not a mocked subprocess or a review host CLI.
        # --help parses options without auth, provider requests or network access.
        result = MODULE.subprocess.run(
            ['gh', 'api', '--allow-escape-sequences', '--help'],
            capture_output=True, timeout=30, check=False)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertIn(b'--allow-escape-sequences', result.stdout)

    def test_recovery_authenticates_native_skipped_expression_role(self):
        self.prepare_recovery()
        self.jobs[3]['name'] = MODULE.INACTIVE_METADATA_API_NAME
        with mock.patch.object(MODULE, 'log_binding', return_value='c'*64):
            MODULE.validate_final_recovery(self.recovery_client(), self.value, 'c'*64, 100)
            for field, bad in (('name', MODULE.METADATA_JOB), ('name', 'unknown expression'),
                               ('conclusion', 'success'), ('run_id', 101),
                               ('run_attempt', True), ('head_sha', 'd'*40)):
                with mock.patch.dict(self.jobs[3], {field: bad}), self.assertRaises(ERROR):
                    MODULE.validate_final_recovery(self.recovery_client(), self.value, 'c'*64, 100)

    def recovery_client(self):
        owner = self
        previous = self.client()
        class RecoveryClient:
            def get(self, path):
                if path.endswith('/actions/runs/100'):
                    return copy.deepcopy(owner.run)
                return previous.get(path)
        return RecoveryClient()

    def prepare_recovery(self):
        self.run.update(run_attempt=2, status='in_progress', conclusion=None,
                        triggering_actor={'login': 'github-actions[bot]', 'type': 'Bot'})
        self.jobs[2]['conclusion'] = 'failure'

    def test_final_recovery_preserves_original_approval_binding(self):
        self.prepare_recovery()
        with mock.patch.object(MODULE, 'log_binding', return_value='c' * 64):
            MODULE.validate_final_recovery(self.recovery_client(), self.value, 'c' * 64, 100)

    def test_recovery_success_still_runs_current_native_approval_and_technical_checks(self):
        self.prepare_recovery()
        env = {'GITHUB_RUN_ATTEMPT': '2', 'GITHUB_RUN_ID': '100',
               'APPROVAL_BINDING': 'c' * 64, 'APPROVAL_REUSE_RUN': ''}
        with mock.patch.dict(MODULE.os.environ, env), \
             mock.patch.object(sys, 'argv', ['approval', 'verify']), \
             mock.patch.object(MODULE, 'revision', return_value=(self.value, 'c' * 64)), \
             mock.patch.object(MODULE.EVIDENCE, 'GitHubClient', return_value=self.recovery_client()), \
             mock.patch.object(MODULE, 'log_binding', return_value='c' * 64), \
             mock.patch.object(MODULE, 'native_approval') as approval, \
             mock.patch.object(MODULE.EVIDENCE, 'verify') as verify, \
             mock.patch.object(MODULE, 'metadata_controller') as metadata:
            self.assertEqual(MODULE.main(), 0)
            metadata.assert_called_once()
            self.assertEqual(metadata.call_args.args[1:], (self.value,))
            approval.assert_called_once()
            verify.assert_called_once()

    def test_timeout_reuses_the_exact_original_native_human_approval(self):
        self.run['conclusion'] = 'timed_out'
        self.jobs[2]['conclusion'] = 'timed_out'
        with mock.patch.object(MODULE, 'log_binding', return_value='c'*64):
            self.assertEqual(MODULE.reusable_approval(self.client(), self.value, 'c'*64, 101), 100)
        self.prepare_recovery()
        self.jobs[2]['conclusion'] = 'timed_out'
        with mock.patch.object(MODULE, 'log_binding', return_value='c'*64), self.assertRaises(ERROR):
            MODULE.validate_final_recovery(self.recovery_client(), self.value, 'c'*64, 100)

    def test_native_repository_and_pr_ids_are_not_coerced(self):
        for target, field in ((self.run['repository'], 'id'),
                              (self.run['pull_requests'][0], 'number')):
            with mock.patch.dict(target, {field: float(target[field])}):
                self.assertFalse(MODULE.native_run_binding(self.run, self.value))

    def test_recovery_rejects_foreign_actor_changed_binding_and_incomplete_jobs(self):
        self.prepare_recovery()
        with mock.patch.object(MODULE, 'log_binding', return_value='c' * 64):
            for key, bad in (('run_attempt', 3), ('id', 101),
                             ('triggering_actor', {'login': 'litroc', 'type': 'User'}),
                             ('event', 'workflow_dispatch')):
                with mock.patch.dict(self.run, {key: bad}), self.assertRaises(ERROR):
                    MODULE.validate_final_recovery(self.recovery_client(), self.value, 'c' * 64, 100)
            with mock.patch.dict(self.jobs[0], {'conclusion': 'failure'}), self.assertRaises(ERROR):
                MODULE.validate_final_recovery(self.recovery_client(), self.value, 'c' * 64, 100)
            with mock.patch.dict(self.jobs[2], {'conclusion': 'success'}), self.assertRaises(ERROR):
                MODULE.validate_final_recovery(self.recovery_client(), self.value, 'c' * 64, 100)
        with mock.patch.object(MODULE, 'log_binding', return_value='d' * 64), self.assertRaises(ERROR):
            MODULE.validate_final_recovery(self.recovery_client(), self.value, 'c' * 64, 100)

    def test_attempt_two_is_only_admitted_for_final_technical_verification(self):
        for mode in ('preflight', 'approve'):
            with mock.patch.dict(MODULE.os.environ, {'GITHUB_RUN_ATTEMPT': '2'}), \
                 mock.patch.object(sys, 'argv', ['approval', mode]), \
                 mock.patch.object(MODULE.EVIDENCE, 'GitHubClient'), \
                 mock.patch.object(MODULE, 'revision') as revision:
                self.assertEqual(MODULE.main(), 1)
                revision.assert_not_called()


if __name__ == "__main__":
    unittest.main()
