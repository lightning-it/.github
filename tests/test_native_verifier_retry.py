"""Real LI-259 caller/receiver and Git-CAS protocol against native API fixtures."""
import copy
import datetime as dt
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location("native_retry", ROOT / "scripts/native_verifier_retry.py")
RETRY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RETRY)


class NativeRetryTests(unittest.TestCase):
    def setUp(self):
        self.repo, self.repo_id = "lightning-it/.github", "123"
        self.head, self.source, self.receiver_source = "b" * 40, "c" * 40, "d" * 40
        self.start = dt.datetime(2026, 10, 7, tzinfo=dt.timezone.utc)
        self.now = self.start
        self.pr = {"id": 23, "number": 23, "draft": False, "state": "open", "title": "Fix", "body": "Review this", "labels": [],
                   "user": {"id": 76040632, "login": "litroc", "type": "User"},
                   "head": {"sha": self.head, "ref": "fix/test", "repo": {"full_name": self.repo}},
                   "base": {"sha": self.source, "ref": "develop", "repo": {"full_name": self.repo}}}
        recorded = {"number": 23, "url": f"https://api.github.com/repos/{self.repo}/pulls/23",
                    **{side: {"sha": self.pr[side]["sha"], "ref": self.pr[side]["ref"],
                               "repo": {"url": f"https://api.github.com/repos/{self.repo}"}} for side in ("head", "base")}}
        self.run = {"id": 99, "workflow_id": 5, "workflow_url": f"https://api.github.com/repos/{self.repo}/actions/workflows/5",
                    "path": RETRY.RECEIVER, "event": "pull_request_target", "repository": {"full_name": self.repo},
                    "head_repository": {"full_name": self.repo}, "head_sha": self.head, "head_branch": "fix/test",
                    "actor": {"login": "litroc"}, "triggering_actor": {"login": "litroc"}, "pull_requests": [recorded],
                    "display_title": f"Protected current revision PR #23 opened {self.head}",
                    "run_attempt": 1, "status": "completed", "conclusion": "failure", "run_started_at": self.at(-10)}
        self.original = {"id": 100, "name": RETRY.JOB, "run_id": 99, "run_attempt": 1, "head_sha": self.head,
                         "status": "completed", "conclusion": "failure", "steps": [{
                             "name": f"{RETRY.SOURCE_MARKER}{self.repo}/{RETRY.RECEIVER}@refs/heads/main {self.receiver_source} PR 23 base {self.source} head {self.head}",
                             "status": "completed", "conclusion": "success"}]}
        self.jobs = {1: [self.original]}
        self.history = {1: copy.deepcopy(self.run)}
        self.producer = {**self.run, "id": 77, "path": RETRY.proof.PRODUCER, "status": "completed", "conclusion": "success"}
        self.producer_jobs = [{"id": 78, "name": "Verify current revision policy", "run_id": 77,
                               "run_attempt": 1, "head_sha": self.head, "status": "completed", "conclusion": "success",
                               "runner_id": 1, "steps": [{"name": "Verify current Copilot review and resolved findings", "conclusion": "success"}]}]
        self.neutral = {"id": 79, "name": "Current revision review", "head_sha": self.head,
                        "app": {"id": 15368, "slug": "github-actions"}, "status": "completed", "conclusion": "success",
                        "completed_at": self.at(-1), "external_id": f"mlx90-current-revision:copilot:v6:23:77:{self.source}:{self.head}",
                        "output": {"summary": json.dumps({"schema": 4, "producer_run_id": 77, "pull_request_number": 23,
                                                           "base_sha": self.source, "head_sha": self.head, "controller_sha": self.source})}}
        self.review = {"id": 17, "commit_id": self.head, "user": {"login": RETRY.proof.BOT, "type": "Bot"},
                       "state": "APPROVED", "body": "Review complete.", "submitted_at": self.at(-2)}
        self.comments, self.thread_rows = [], []
        self.annotation_rows = [{"annotation_level": "failure", "message": RETRY.ACQUISITION,
                                 "path": ".github", "start_line": 1, "end_line": 1},
                                {"annotation_level": "notice", "message": "Runner image migration notice"}]
        self.effects, self.writes = [], []
        self.oid = "1" * 40
        self.snapshots = {self.oid: {}}
        self.cas_hook = None
        self.cas_unknown = False
        self.effect_unknown = None
        self.branches = {"develop": self.source, "main": self.receiver_source}
        self.env = {"LI219_EVENT_MODE": "enabled", "LI259_INFRA_RETRY": "enabled", "GITHUB_REPOSITORY": self.repo,
                    "GITHUB_REPOSITORY_ID": self.repo_id, "GITHUB_RUN_ID": "55", "GITHUB_RUN_ATTEMPT": "1",
                    "GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_WORKFLOW_SHA": self.source,
                    "GITHUB_REF_PROTECTED": "true", "WORKFLOW_SHA": self.receiver_source,
                    "WORKFLOW_REF": f"{self.repo}/{RETRY.RECEIVER}@refs/heads/main",
                    "EVENT_BASE": self.source, "EVENT_HEAD": self.head, "PR_NUMBER": "23"}
        self.stack = [patch.dict(os.environ, self.env), patch.object(RETRY.proof, "api", side_effect=self.api),
                      patch.object(RETRY, "utc_now", side_effect=lambda: self.now), patch("builtins.print")]
        for patcher in self.stack:
            patcher.start()
            self.addCleanup(patcher.stop)

    def at(self, seconds):
        return RETRY.stamp(self.start + dt.timedelta(seconds=seconds))

    def native_writer(self, run_id):
        return {"id": run_id, "run_attempt": 1, "path": RETRY.HELPER if run_id == 55 else RETRY.WORKFLOW,
                "event": "workflow_dispatch" if run_id == 55 else "schedule", "head_sha": self.source,
                "repository": {"full_name": self.repo}, "head_repository": {"full_name": self.repo},
                "actor": {"login": "github-actions[bot]"}, "triggering_actor": {"login": "github-actions[bot]"}}

    @staticmethod
    def blob(record):
        if record is None:
            return None
        text = json.dumps(record)
        return {"__typename": "Blob", "isTruncated": False, "byteSize": len(text.encode()), "text": text}

    def api(self, route, payload=None, fields=()):
        if route == "graphql" and payload is not None:
            import base64
            request = payload["variables"]["input"]
            prior = request["expectedHeadOid"]
            if self.cas_hook is not None:
                hook, self.cas_hook = self.cas_hook, None
                hook()
            if prior != self.oid:
                return {"data": {"createCommitOnBranch": None}, "errors": [{"type": "STALE_DATA",
                        "path": ["createCommitOnBranch"], "message": f'Expected branch to point to "{prior}" but it did not. Pull and try again.'}]}
            changes = request["fileChanges"]["additions"]
            record = json.loads(base64.b64decode(changes[0]["contents"]))
            self.writes.append((changes[0]["path"], record))
            self.oid = f"{len(self.writes) + 1:040x}"
            self.snapshots[self.oid] = {**self.snapshots[prior], changes[0]["path"]: record}
            if self.cas_unknown:
                raise subprocess.TimeoutExpired("gh", 30)
            return {"data": {"createCommitOnBranch": {"commit": {"oid": self.oid, "parents": {"nodes": [{"oid": prior}]}}}}}
        if payload is not None:
            self.effects.append((route, payload))
            if self.effect_unknown != "not-delivered":
                self.run = {**self.run, "run_attempt": self.run["run_attempt"] + 1, "status": "in_progress",
                            "conclusion": None, "run_started_at": RETRY.stamp(self.now + dt.timedelta(seconds=1))}
            if self.effect_unknown:
                raise subprocess.TimeoutExpired("gh", 30)
            return None
        if route == "graphql":
            values = dict(field.split("=", 1) for field in fields if "=" in field)
            if "reviewThreads" in values["query"]:
                return {"data": {"repository": {"pullRequest": {"reviewThreads": {
                    "nodes": copy.deepcopy(self.thread_rows), "pageInfo": {"hasNextPage": False, "endCursor": None}}}}}}
            oid = values["oid"]
            path = values["record"].split(":", 1)[1]
            return {"data": {"repository": {"nameWithOwner": self.repo, "source": {"__typename": "Commit", "oid": oid},
                    "manifest": self.blob({"schema": 1, "repository": self.repo, "repository_id": self.repo_id,
                                           "ref": "refs/heads/lit-review-operations"}),
                    "record": self.blob(self.snapshots[oid].get(path))}}}
        prefix = f"repos/{self.repo}"
        if route == prefix:
            return {"full_name": self.repo, "id": 123, "default_branch": "develop"}
        if route.startswith(prefix + "/branches/"):
            branch = route.rsplit("/", 1)[1]
            return {"name": branch, "protected": True, "commit": {"sha": self.branches[branch]}}
        if "/compare/" in route:
            return {"status": "identical"}
        if route == prefix + "/git/ref/heads/lit-review-operations":
            return {"ref": "refs/heads/lit-review-operations", "object": {"type": "commit", "sha": self.oid}}
        if route == prefix + "/pulls/23":
            return copy.deepcopy(self.pr)
        if route == prefix + "/actions/runs/99":
            return copy.deepcopy(self.run)
        if route == prefix + "/actions/runs/77":
            return copy.deepcopy(self.producer)
        if route in (prefix + "/actions/runs/55", prefix + "/actions/runs/66"):
            return self.native_writer(int(route.rsplit("/", 1)[1]))
        if route.startswith(prefix + "/actions/runs/99/attempts/") and "jobs" not in route:
            return copy.deepcopy(self.history[int(route.rsplit("/", 1)[1])])
        parsed, query = urlsplit(route), parse_qs(urlsplit(route).query)
        bare = parsed.path[len(prefix):]
        if bare == "/pulls":
            return [copy.deepcopy(self.pr)]
        if bare == "/actions/runs":
            rows, key = [self.run], "workflow_runs"
        elif bare.startswith("/actions/runs/99/attempts/") and bare.endswith("/jobs"):
            rows, key = self.jobs[int(bare.split("/")[-2])], "jobs"
        elif bare == "/actions/runs/77/attempts/1/jobs":
            rows, key = self.producer_jobs, "jobs"
        elif bare == f"/commits/{self.head}/check-runs":
            rows, key = [self.neutral], "check_runs"
        elif bare == "/pulls/23/reviews":
            rows, key = [self.review], None
        elif bare == "/pulls/23/reviews/17/comments":
            rows, key = self.comments, None
        elif bare.startswith("/check-runs/"):
            if bare.endswith("/annotations"):
                return copy.deepcopy(self.annotation_rows)
            check_id = int(bare.rsplit("/", 1)[1])
            return {"id": check_id, "name": RETRY.JOB, "head_sha": self.head,
                    "status": "completed", "conclusion": "cancelled", "app": {"id": 15368, "slug": "github-actions"},
                    "output": {"annotations_count": len(self.annotation_rows)}}
        else:
            raise AssertionError((route, fields))
        page = int(query["page"][0])
        batch = copy.deepcopy(rows[(page - 1) * 100:page * 100])
        return {"total_count": len(rows), key: batch} if key else batch

    def fail_attempt(self, attempt, started, completed):
        self.run.update(run_attempt=attempt, status="completed", conclusion="cancelled",
                        triggering_actor={"login": "github-actions[bot]"}, run_started_at=self.at(started))
        self.history[attempt] = copy.deepcopy(self.run)
        self.jobs[attempt] = [{"id": 100 + attempt, "run_id": 99, "run_attempt": attempt, "head_sha": self.head,
                               "name": RETRY.JOB, "status": "completed", "conclusion": "cancelled", "runner_id": 0,
                               "runner_name": "", "steps": [], "labels": ["ubuntu-latest"],
                               "created_at": self.at(started), "started_at": self.at(started), "completed_at": self.at(completed),
                               "check_run_url": f"https://api.github.com/repos/{self.repo}/check-runs/{100 + attempt}"}]

    def prime(self):
        RETRY.seal(self.repo, self.repo_id, 23, 99, self.source, self.start)
        key = f"li219-verifier-operation:v1:23:{self.source}:{self.head}:99"
        RETRY.proof.Journal(self.repo, self.repo_id).create(RETRY.proof.record_path(key), {
            "schema": 1, "action": "rerun", "operation": key, "repository": self.repo, "repository_id": self.repo_id,
            "claim_run": "55", "claim_attempt": "1", "source_sha": self.source})
        self.fail_attempt(2, 1, 902)
        self.now = self.start + dt.timedelta(seconds=2102)
        os.environ.update(GITHUB_RUN_ID="66", GITHUB_EVENT_NAME="schedule")

    def recover(self):
        return RETRY.recover(self.repo, self.repo_id, 99, self.source, self.now)

    def receive(self):
        os.environ.update(GITHUB_RUN_ID="99", GITHUB_RUN_ATTEMPT=str(self.run["run_attempt"]))
        RETRY.receiver(self.repo, self.repo_id, 99, self.run["run_attempt"], self.now)

    def test_native_acquisition_reaches_same_bound_receiver_and_one_job_post(self):
        self.prime()
        self.assertEqual("dispatched", self.recover())
        self.receive()
        self.assertEqual([(f"repos/{self.repo}/actions/jobs/102/rerun", {})], self.effects)
        self.assertFalse(any("requested_reviewers" in route or "/dispatches" in route for route, _ in self.effects))
        self.assertEqual(self.head, self.pr["head"]["sha"])

    def test_actual_schedule_main_calls_recovery_and_duplicate_delivery_is_inert(self):
        self.prime()
        self.effect_unknown = "not-delivered"
        with patch.object(sys, "argv", ["native_verifier_retry.py", "reconcile"]):
            RETRY.main()
            RETRY.main()
        self.assertEqual(1, len(self.effects))
        self.assertEqual("consumed-readback-only", self.recover())

    def test_native_empty_pr_projection_requires_exact_successful_source_step(self):
        self.run["pull_requests"] = []
        self.prime()
        self.assertEqual("dispatched", self.recover())
        self.receive()

    def test_mismatched_receiver_source_step_never_seals_empty_projection(self):
        self.run["pull_requests"] = []
        self.original["steps"][0]["name"] = self.original["steps"][0]["name"].replace("PR 23", "PR 24")
        with self.assertRaisesRegex(ValueError, "unwired receiver source"):
            RETRY.seal(self.repo, self.repo_id, 23, 99, self.source, self.start)
        self.assertEqual([], self.writes)

    def test_cas_race_loser_never_posts_even_when_winner_record_is_visible(self):
        self.prime()
        self.cas_hook = self.recover
        self.assertEqual("unconfirmed-claim-readback-only", self.recover())
        self.assertEqual(1, len(self.effects))

    def test_lost_claim_response_never_posts_and_remains_consumed(self):
        self.prime()
        self.cas_unknown = True
        self.assertEqual("unconfirmed-claim-readback-only", self.recover())
        self.cas_unknown = False
        self.assertEqual("consumed-readback-only", self.recover())
        self.assertEqual([], self.effects)

    def test_lost_post_response_is_readback_only_whether_delivered_or_not(self):
        for outcome in ("delivered", "not-delivered"):
            with self.subTest(outcome=outcome):
                self.setUp()
                self.prime()
                self.effect_unknown = outcome
                self.assertEqual("unknown-post-readback-only", self.recover())
                self.assertIn(self.recover(), ("active", "consumed-readback-only"))
                self.assertEqual(1, len(self.effects))

    def test_unknown_post_stays_get_only_after_drift_and_expiry(self):
        self.prime()
        self.effect_unknown = "not-delivered"
        self.recover()
        count = len(self.writes)
        self.review["body"] = "Edited"
        self.now += dt.timedelta(days=1)
        self.assertEqual("consumed-readback-only", self.recover())
        self.assertEqual(count, len(self.writes))
        self.assertEqual(1, len(self.effects))

    def test_cooldown_has_no_sleep_claim_or_effect_before_exact_boundary(self):
        self.prime()
        count = len(self.writes)
        self.now -= dt.timedelta(seconds=1)
        self.assertEqual("cooldown", self.recover())
        self.assertEqual(count, len(self.writes))
        self.assertEqual([], self.effects)
        self.now += dt.timedelta(seconds=1)
        self.assertEqual("dispatched", self.recover())

    def test_attempt_four_uses_longer_cooldown_and_exhaustion_is_absorbing(self):
        self.prime()
        self.recover()
        self.fail_attempt(3, 2103, 3004)
        self.now = self.start + dt.timedelta(seconds=5403)
        self.assertEqual("cooldown", self.recover())
        self.now += dt.timedelta(seconds=1)
        self.assertEqual("dispatched", self.recover())
        self.receive()
        os.environ.update(GITHUB_RUN_ID="66", GITHUB_RUN_ATTEMPT="1")
        self.fail_attempt(4, 5405, 6306)
        self.now = self.start + dt.timedelta(seconds=6306)
        self.assertEqual("terminal", self.recover())
        self.assertEqual("inactive", self.recover())
        self.assertEqual(2, len(self.effects))

    def test_runtime_reserve_deadline_boundary_and_receiver_total_deadline(self):
        self.prime()
        self.now = self.start + dt.timedelta(seconds=7200)
        self.assertEqual("dispatched", self.recover())
        self.now = self.start + dt.timedelta(seconds=10800)
        self.receive()
        self.now += dt.timedelta(seconds=1)
        with self.assertRaisesRegex(ValueError, "receiver deadline"):
            self.receive()

    def test_no_start_with_less_than_complete_runtime_reserve(self):
        self.prime()
        self.now = self.start + dt.timedelta(seconds=7201)
        self.assertEqual("terminal", self.recover())
        self.assertEqual([], self.effects)

    def test_receiver_rechecks_wall_clock_after_all_remote_reads(self):
        self.prime()
        self.recover()
        with patch.object(RETRY, "utc_now", return_value=self.start + dt.timedelta(seconds=10801)):
            with self.assertRaisesRegex(ValueError, "final receiver deadline"):
                self.receive()

    def test_clock_crossing_deadline_after_claim_consumes_without_post(self):
        self.prime()
        with patch.object(RETRY, "utc_now", return_value=self.start + dt.timedelta(seconds=7201)):
            with self.assertRaisesRegex(ValueError, "post-claim deadline"):
                self.recover()
        self.assertEqual([], self.effects)
        self.assertEqual("consumed-readback-only", self.recover())

    def test_no_retroactive_seed_or_unclaimed_native_attempt(self):
        os.environ.update(GITHUB_RUN_ID="66", GITHUB_EVENT_NAME="schedule")
        self.assertEqual("inactive", self.recover())
        with self.assertRaises((ValueError, TypeError)):
            RETRY.receiver(self.repo, self.repo_id, 99, 3, self.now)

    def test_pre_rollout_receiver_keeps_baseline_route_without_new_authority(self):
        self.original["steps"] = []
        self.assertFalse(RETRY.seal(self.repo, self.repo_id, 23, 99, self.source, self.start))
        self.assertEqual([], self.writes)
        self.fail_attempt(2, 1, 902)
        os.environ.update(GITHUB_RUN_ID="66", GITHUB_EVENT_NAME="schedule")
        self.assertEqual("inactive", self.recover())

    def test_receiver_rejects_changed_review_and_unclaimed_attempt(self):
        self.prime()
        self.recover()
        self.review["body"] = "Changed review"
        with self.assertRaisesRegex(ValueError, "receiver contract drift"):
            self.receive()
        self.review["body"] = "Review complete."
        self.run["run_attempt"] = 4
        with self.assertRaises(ValueError):
            self.receive()

    def test_policy_head_base_controller_review_and_thread_drift_are_terminal(self):
        cases = (lambda: self.pr["head"].update(sha="e" * 40),
                 lambda: self.pr["base"].update(sha="e" * 40),
                 lambda: self.branches.update(main="e" * 40),
                 lambda: self.review.update(body="Edited"),
                 lambda: self.thread_rows.append({"id": "T1", "isResolved": False}),
                 lambda: self.neutral["output"].update(summary="{}"))
        for index, change in enumerate(cases):
            with self.subTest(case=index):
                self.setUp()
                self.prime()
                change()
                self.assertEqual("terminal", self.recover())
                self.assertEqual("inactive", self.recover())
                self.assertEqual([], self.effects)

    def test_runnerless_dto_and_all_unclassified_failures_remain_terminal(self):
        for field, value in (("runner_id", None), ("runner_id", 7), ("steps", [{"name": "Verify", "conclusion": "failure"}]),
                             ("conclusion", "failure"), ("labels", ["self-hosted"]), ("name", "Published check")):
            with self.subTest(field=field, value=value):
                self.setUp()
                self.prime()
                self.jobs[2][0][field] = value
                self.assertEqual("terminal", self.recover())
                self.assertEqual([], self.effects)
        for message in ("Permission denied", "Quota exhausted", "Service unavailable", "permanent-producer-binding"):
            with self.subTest(message=message):
                self.setUp()
                self.prime()
                self.annotation_rows[0]["message"] = message
                self.assertEqual("terminal", self.recover())
                self.assertEqual([], self.effects)

    def test_duplicate_or_incomplete_native_inventories_never_authorize(self):
        self.prime()
        original = self.api
        for corruption in ("duplicate", "incomplete"):
            def malformed(route, payload=None, fields=()):
                result = original(route, payload, fields)
                if "/attempts/2/jobs?" in route:
                    result["total_count"] = 2
                    if corruption == "duplicate":
                        result["jobs"] *= 2
                return result
            with self.subTest(corruption=corruption), patch.object(RETRY.proof, "api", side_effect=malformed):
                with self.assertRaises(ValueError):
                    RETRY.infrastructure_cause(self.repo, self.run, self.head, self.now)
        self.assertEqual([], self.effects)

    def test_only_the_expected_dependent_gate_failure_can_accompany_acquisition(self):
        self.prime()
        aggregate = {**self.jobs[2][0], "id": 103, "name": RETRY.AGGREGATE,
                     "runner_id": 8, "conclusion": "failure", "steps": [{
                         "name": "Enforce exactly one terminal verification route",
                         "status": "completed", "conclusion": "failure"}]}
        self.jobs[2].append(aggregate)
        self.assertEqual(RETRY.POLICY["cause"], RETRY.infrastructure_cause(self.repo, self.run, self.head, self.now)["code"])
        aggregate["steps"][0]["name"] = "Set up job"
        with self.assertRaisesRegex(ValueError, "independent failed job"):
            RETRY.infrastructure_cause(self.repo, self.run, self.head, self.now)

    def test_disabled_mode_performs_zero_reads_and_writes(self):
        with patch.dict(os.environ, LI259_INFRA_RETRY="disabled"), patch.object(RETRY.proof, "api") as api:
            with patch.object(sys, "argv", ["native_verifier_retry.py", "reconcile"]):
                RETRY.main()
            api.assert_not_called()


class WorkflowCouplingTests(unittest.TestCase):
    def test_execute_real_handoff_caller_orders_seal_claim_rebind_and_post(self):
        text = (ROOT / ".github/workflows/current-revision-rerun.yml").read_text()
        function = "rerun_protected_verifier_once() {" + text.split("          rerun_protected_verifier_once() {", 1)[1].split("\n          rerun_cross_job_once()", 1)[0]
        shell = r'''set -euo pipefail
authorize_protected_rerun_transaction() { printf 'authorize\n'; }
require_deadline() { :; }
claim_review_operation() { printf 'claim\n'; }
bounded_gh_api() {
  if [ "$1" = --method ]; then printf 'POST\n' >>"${RUNNER_TEMP}/effects";
  else printf 'dHJ1ZQo='; fi
}
bash() {
  printf 'seal\n'
  if [ "$FAIL_REBIND" = yes ] && [ -f "${RUNNER_TEMP}/sealed" ]; then return 1; fi
  touch "${RUNNER_TEMP}/sealed"
}
''' + textwrap.dedent(function) + "\nrerun_protected_verifier_once\n"
        for fail, code, posts in (("no", 0, "POST\n"), ("yes", 10, "")):
            with self.subTest(fail=fail), tempfile.TemporaryDirectory() as tmp:
                result = subprocess.run(["bash", "-c", shell], text=True, capture_output=True, check=False,
                                        env={**os.environ, "RUNNER_TEMP": tmp, "LI259_INFRA_RETRY": "enabled",
                                             "REPOSITORY": "lightning-it/.github", "WORKFLOW_SHA": "a" * 40,
                                             "PR_NUMBER": "23", "run_id": "99", "EXPECTED_HEAD": "b" * 40,
                                             "EXPECTED_BASE": "a" * 40, "FAIL_REBIND": fail})
                self.assertEqual(code, result.returncode, result.stderr)
                self.assertEqual(["authorize", "seal", "claim", "authorize", "seal"], result.stdout.splitlines())
                effects = Path(tmp) / "effects"
                self.assertEqual(posts, effects.read_text() if effects.exists() else "")

    def test_existing_handoff_seals_before_claim_and_rebinds_before_post(self):
        text = (ROOT / ".github/workflows/current-revision-rerun.yml").read_text()
        function = text.split("          rerun_protected_verifier_once() {", 1)[1].split("\n          rerun_cross_job_once()", 1)[0]
        self.assertLess(function.index('bash "${launcher}" seal'), function.index("claim_review_operation"))
        self.assertLess(function.index('bash "${RUNNER_TEMP}/li259-launcher.sh" seal'), function.index("--method POST"))
        self.assertNotIn("li259", text.split("          rerun_cross_job_once()", 1)[1].split("          wait_for_attempt_two_success", 1)[0])

    def test_actual_receiver_guards_entry_and_final_acceptance_and_keeps_ai_first_attempt_only(self):
        text = (ROOT / ".github/workflows/supplementary-current-revision-required.yml").read_text()
        self.assertEqual(2, text.count('bash "${RUNNER_TEMP}/li259-launcher.sh" receiver'))
        self.assertIn("LI-259 receiver source ${{ github.workflow_ref }} ${{ github.workflow_sha }}", text)
        producer = (ROOT / ".github/workflows/copilot-review.yml").read_text()
        request = producer.split("  request-current-revision-review:", 1)[1].split("    permissions:", 1)[0]
        self.assertIn("github.run_attempt == 1", request)
        self.assertNotIn("LI259", producer)


if __name__ == "__main__":
    unittest.main()
