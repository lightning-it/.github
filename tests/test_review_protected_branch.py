"""Real embedded locator/consumer regressions for protected develop and main."""

import copy
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

import test_review_request_continuation as continuation

ROOT = Path(__file__).resolve().parents[1]


class ProtectedReviewBranchTests(unittest.TestCase):
    def fixture(self, branch):
        fixture = continuation.ContinuationTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.route("/pulls/23")["base"]["ref"] = branch
        for route in ("/actions/runs/77", "/actions/runs/77/attempts/1"):
            fixture.route(route)["pull_requests"][0]["base"]["ref"] = branch
        fixture.state["routes"]["repos/" + continuation.REPO + "/branches/" + branch] = {
            "name": branch,
            "protected": True,
            "commit": {"sha": continuation.BASE},
        }
        for run in ("88", "89"):
            fixture.route("/actions/runs/" + run + "/attempts/1")["head_branch"] = branch
        # The workflow controller is default develop; the PRT runner uses the PR base.
        # A Main-target PR deliberately has different runner and controller sources.
        original_source = "c" * 40 if branch == "main" else continuation.BASE
        fixture.route("/branches/develop")["commit"]["sha"] = original_source
        fixture.env.update(GITHUB_REF="refs/heads/" + branch, WORKFLOW_SHA=original_source,
                           GITHUB_SHA=continuation.BASE)
        consumer = fixture.consumer
        fixture.consumer = lambda **changes: consumer(**{
            "GITHUB_REF": "refs/heads/" + branch,
            "WORKFLOW_SHA": continuation.BASE, "GITHUB_SHA": continuation.BASE,
            **changes,
        })
        return fixture

    def test_develop_and_main_locator_and_consumer_share_exact_protected_ref(self):
        for branch in ("develop", "main"):
            with self.subTest(branch=branch):
                f = self.fixture(branch)
                result = f.defer()
                self.assertEqual(0, result.returncode, result.stderr)
                intent = f.state["versions"][f.state["oid"]][continuation.INTENT]
                self.assertEqual(2, intent["schema"])
                self.assertEqual("develop", intent["source_ref"])
                self.assertEqual(f.env["WORKFLOW_SHA"], intent["source_sha"])
                self.assertEqual(branch, intent["base_ref"])
                if branch == "main":
                    self.assertNotEqual(intent["source_sha"], intent["base"])
                for companion in (False, True):
                    result = f.locator(companion)
                    self.assertEqual(0, result.returncode, result.stderr)
                    self.assertEqual(branch, f.state["dispatches"][-1]["ref"])
                result = f.consumer()
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual(1, len(f.state["requests"]))
                self.assertNotEqual(0, f.consumer().returncode)
                self.assertEqual(1, len(f.state["requests"]))

    def test_main_defer_rejects_wrong_runner_base_or_default_controller(self):
        for changes in (
                {"GITHUB_REF": "refs/heads/develop"},
                {"GITHUB_SHA": "c" * 40},
                {"EXPECTED_BASE": "e" * 40},
                {"WORKFLOW_SHA": continuation.BASE},
                {"GITHUB_WORKFLOW_REF": continuation.REPO + "/.github/workflows/copilot-review.yml@refs/heads/main"}):
            with self.subTest(changes=changes):
                fixture = self.fixture("main")
                fixture.env.update(changes)
                before = copy.deepcopy(fixture.state["versions"])
                result = fixture.defer()
                self.assertNotEqual(0, result.returncode)
                self.assertEqual(before, fixture.state["versions"])
                self.assertEqual([], fixture.state["requests"])

    def test_main_intent_rejects_develop_consumer_before_request_CAS(self):
        f = self.fixture("main")
        self.assertEqual(0, f.defer().returncode)
        before = copy.deepcopy(f.state["versions"])
        f.route("/actions/runs/88/attempts/1")["head_branch"] = "develop"
        result = f.consumer(GITHUB_REF="refs/heads/develop")
        self.assertNotEqual(0, result.returncode)
        self.assertEqual(before, f.state["versions"])
        self.assertEqual([], f.state["requests"])

    def test_reconciler_main_continuation_uses_live_base_ref(self):
        f = self.fixture("main")
        self.assertEqual(0, f.defer().returncode)
        result = f.execute(
            "python3 " + str(ROOT / "scripts/review-event-reconcile.py"), {}, {"GITHUB_REF": "refs/heads/develop"}
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(["main"], [v["ref"] for v in f.state["dispatches"]])

    def test_review_event_direct_forward_is_same_repository_only(self):
        fork = "contributor/dot-github-fork"
        for branch in ("develop", "main"):
            with self.subTest(branch=branch):
                result, calls = self.refresh(branch, head_repository=fork)
                self.assertNotEqual(0, result.returncode)
                self.assertEqual([], calls)
                result, calls = self.refresh(branch)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual(1, len(calls))

    def refresh(self, branch, consumer=False, execution_branch=None, controller=None, fence_only=False, protected_source=None, head_repository=continuation.REPO, expected_repository=None):
        workflow = yaml.safe_load((ROOT / ".github/workflows/copilot-review-refresh.yml").read_text())
        if fence_only:
            text = workflow["jobs"]["refresh-canonical-gate"]["steps"][1]["run"]
            text = "validate_live_pr_tuple() {" + text.split("validate_live_pr_tuple() {", 1)[1].split("\n}", 1)[0] + "\n}\noa() { gh api \"$@\"; }\nvalidate_live_pr_tuple\n"
        elif consumer:
            text = workflow["jobs"]["refresh-canonical-gate"]["steps"][1]["run"]
            text = text[: text.index("\njq -e \\\n  --arg actor")]
        else:
            text = workflow["jobs"]["forward-review-event"]["steps"][0]["run"]
        pr = {
            "number": 23,
            "state": "open",
            "draft": False,
            "user": {"login": "litroc", "type": "User"},
            "head": {"sha": continuation.HEAD, "ref": "fix/new", "repo": {"full_name": head_repository}},
            "base": {"sha": continuation.BASE, "ref": branch, "repo": {"full_name": continuation.REPO}},
        }
        review = {"id": 17, "commit_id": continuation.HEAD, "user": {"login": continuation.BOT}, "state": "COMMENTED"}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pr").write_text(json.dumps(pr))
            (root / "review").write_text(json.dumps(review))
            mock = root / "gh"
            mock.write_text(
                """#!/usr/bin/env python3
import json,os,sys
from pathlib import Path
r=Path(os.environ['FIXTURE']);args=sys.argv[1:]
if 'POST' in args:
    with (r/'dispatches').open('a') as f:f.write(json.dumps(args)+'\\n')
elif any('/reviews?per_page' in a for a in args):print('['+ '['+(r/'review').read_text()+']'+']')
elif any('/reviews/' in a for a in args):print((r/'review').read_text())
elif any('/pulls/' in a for a in args):print((r/'pr').read_text())
elif any('/branches/' in a for a in args):
    p=json.loads((r/'pr').read_text());print(json.dumps({'name':p['base']['ref'],'protected':True,'commit':{'sha':os.environ['PROTECTED_SOURCE']}}))
elif '--jq' in args:print('develop')
else:raise SystemExit('unexpected fixture route '+repr(args))
"""
            )
            mock.chmod(0o755)
            result = subprocess.run(  # noqa: S603 -- Actual workflow shell with offline mock transport.
                ["/bin/bash", "-euo", "pipefail", "-c", text],
                env={
                    **os.environ,
                    "PATH": str(root) + ":" + os.environ["PATH"],
                    "FIXTURE": str(root),
                    "RUNNER_TEMP": str(root),
                    "REPOSITORY": continuation.REPO,
                    "PR_NUMBER": "23",
                    "PR_AUTHOR": "litroc", "HEAD_REF": "fix/new", "BASE_REF": branch,
                    "HEAD_SHA": continuation.HEAD, "BASE_SHA": continuation.BASE,
                    "PROTECTED_SOURCE": protected_source or continuation.BASE,
                    "EXPECTED_HEAD": continuation.HEAD,
                    "EXPECTED_BASE": continuation.BASE,
                    "EXPECTED_HEAD_REPOSITORY": expected_repository or head_repository, "HEAD_REPOSITORY": expected_repository or head_repository,
                    "EXPECTED_HEAD_REF": "fix/new", "EXPECTED_BASE_REF": branch, "EXPECTED_AUTHOR": "litroc",
                    "LOCATOR_PR": "23",
                    "LOCATOR_HEAD": continuation.HEAD,
                    "LOCATOR_BASE": continuation.BASE,
                    "LOCATOR_REVIEW": "17",
                    "EVENT_NAME": "workflow_dispatch",
                    "TRIGGER_ACTOR": "github-actions[bot]",
                    "GITHUB_REF": "refs/heads/" + (execution_branch or branch),
                    "GITHUB_REF_PROTECTED": "true",
                    "WORKFLOW_SHA": controller or continuation.BASE,
                },
                capture_output=True,
                text=True,
                check=False,
            )
            dispatches = (
                [json.loads(line) for line in (root / "dispatches").read_text().splitlines()]
                if (root / "dispatches").exists()
                else []
            )
        return result, dispatches

    def test_authenticated_fork_refresh_uses_protected_ref_without_review_request(self):
        for branch in ("develop", "main"):
            for consumer, fence in ((False, False), (True, False), (False, True)):
                with self.subTest(branch=branch, consumer=consumer, fence=fence):
                    result, calls = self.refresh(branch, consumer=consumer, fence_only=fence, head_repository="contributor/core")
                    if consumer or fence:
                        self.assertEqual(0, result.returncode, result.stderr)
                    else:
                        self.assertNotEqual(0, result.returncode)
                    self.assertEqual([], calls)
                    self.assertFalse(any("requested_reviewers" in arg for call in calls for arg in call))
        for fence in (False, True):
            result, calls = self.refresh("main", fence_only=fence, head_repository="other/core", expected_repository="contributor/core")
            self.assertNotEqual(0, result.returncode)
            self.assertEqual([], calls)
        for repository in ("", "owner/repo/extra", "../repo", "owner/.."):
            result, calls = self.refresh("main", consumer=True, head_repository=repository)
            self.assertNotEqual(0, result.returncode)
            self.assertEqual([], calls)

    def test_refresh_locator_dispatches_authenticated_base_instead_of_default(self):
        for branch in ("develop", "main"):
            with self.subTest(branch=branch):
                result, dispatched = self.refresh(branch)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual(1, len(dispatched))
                self.assertIn("ref=" + branch, dispatched[0])

    def test_refresh_consumer_accepts_matching_ref_and_rejects_cross_ref(self):
        for branch in ("develop", "main"):
            with self.subTest(branch=branch):
                result, unused_dispatches = self.refresh(branch, consumer=True)
                self.assertEqual(0, result.returncode, result.stderr)
                result, unused_dispatches = self.refresh(
                    branch, consumer=True, execution_branch="main" if branch == "develop" else "develop"
                )
                self.assertNotEqual(0, result.returncode)

    def test_consumers_reject_wrong_controller_before_any_request_claim(self):
        for branch in ("develop", "main"):
            with self.subTest(branch=branch):
                fixture = self.fixture(branch)
                self.assertEqual(0, fixture.defer().returncode)
                before = copy.deepcopy(fixture.state["versions"])
                result = fixture.consumer(WORKFLOW_SHA="d" * 40)
                self.assertNotEqual(0, result.returncode)
                self.assertEqual(before, fixture.state["versions"])
                self.assertEqual([], fixture.state["requests"])
                result, dispatches = self.refresh(branch, consumer=True, controller="d" * 40)
                self.assertNotEqual(0, result.returncode)
                self.assertEqual([], dispatches)

    def test_readonly_receipt_binds_main_intent_and_native_execution_branch(self):
        fixture = self.fixture("main")
        receipt, context, check = fixture.prepare_readonly_provenance()
        context["base_ref"] = "main"
        environment = {"CONTEXT": json.dumps(context), "RECEIPT": json.dumps(receipt)}
        result = fixture.execute("python3 " + str(check), {}, environment)
        self.assertEqual(0, result.returncode, result.stderr)
        fixture.route("/branches/main")["commit"]["sha"] = "d" * 40
        fixture.state["ancestry_by_route"] = {
            "repos/" + continuation.REPO + "/compare/" + continuation.BASE + "..." + "d" * 40:
                {"status": "ahead", "behind_by": 0, "merge_base_commit": {"sha": continuation.BASE}},
        }
        result = fixture.execute("python3 " + str(check), {}, environment)
        self.assertEqual(0, result.returncode, result.stderr)
        before = copy.deepcopy(fixture.state)
        fixture.route("/actions/runs/88/attempts/1")["head_branch"] = "develop"
        result = fixture.execute("python3 " + str(check), {}, environment)
        self.assertNotEqual(0, result.returncode)
        self.assertEqual(before["versions"], fixture.state["versions"])
        self.assertEqual(before["requests"], fixture.state["requests"])

    def test_current_protected_source_drift_blocks_claim_and_retains_consumed_claim(self):
        for branch in ("develop", "main"):
            for after_claim in (False, True):
                with self.subTest(branch=branch, after_claim=after_claim):
                    fixture = self.fixture(branch)
                    self.assertEqual(0, fixture.defer().returncode)
                    mock = fixture.root / "gh"
                    source = mock.read_text()
                    if after_claim:
                        needle = "        if s.get('drift_after_cas') and item['path'].startswith('operations/'):"
                        insertion = ("        if item['path'].startswith('operations/'):\n"
                                     "            s['routes']['repos/' + s['repo'] + '/branches/" + branch + "']['commit']['sha'] = 'd' * 40\n")
                        source = source.replace(needle, insertion + needle)
                    else:
                        needle = "elif payload is not None:"
                        insertion = ("elif route.split('?')[0].endswith('/issues/23/comments'):\n"
                                     "    s['routes']['repos/' + s['repo'] + '/branches/" + branch + "']['commit']['sha'] = 'd' * 40\n"
                                     "    result = s['routes'][route.split('?')[0]]\n")
                        source = source.replace(needle, insertion + needle)
                    mock.write_text(source)
                    result = fixture.consumer()
                    self.assertNotEqual(0, result.returncode)
                    self.assertIn('controller drift', result.stderr)
                    self.assertEqual(after_claim, continuation.REQUEST in fixture.state['versions'][fixture.state['oid']])
                    self.assertEqual([], fixture.state['requests'])
                    self.assertNotEqual(0, fixture.consumer().returncode)
                    self.assertEqual([], fixture.state['requests'])

    def test_original_default_or_main_drift_around_intent_CAS_fails_closed(self):
        for changed_branch in ("develop", "main"):
            for after_claim in (False, True):
                with self.subTest(branch=changed_branch, after_claim=after_claim):
                    fixture = self.fixture("main")
                    mock = fixture.root / "gh"
                    source = mock.read_text()
                    if after_claim:
                        needle = "        if s.get('drift_after_cas') and item['path'].startswith('operations/'):"
                        insertion = ("        if item['path'].startswith('deferred/'):\n"
                                     "            s['routes']['repos/' + s['repo'] + '/branches/" + changed_branch + "']['commit']['sha'] = 'e' * 40\n")
                    else:
                        needle = "elif '/git/ref/' in route:\n"
                        insertion = (needle + "    s['routes']['repos/' + s['repo'] + '/branches/" + changed_branch + "']['commit']['sha'] = 'e' * 40\n")
                        source = source.replace(needle, insertion)
                        insertion = None
                    if insertion is not None:
                        source = source.replace(needle, insertion + needle)
                    mock.write_text(source)
                    result = fixture.defer()
                    self.assertNotEqual(0, result.returncode)
                    self.assertEqual(after_claim, continuation.INTENT in fixture.state['versions'][fixture.state['oid']])
                    self.assertNotIn(continuation.REQUEST, fixture.state['versions'][fixture.state['oid']])
                    self.assertEqual([], fixture.state['requests'])

    def test_main_unknown_write_outcomes_preserve_one_request_budget(self):
        fixture = self.fixture("main")
        fixture.state["lost_cas_response"] = True
        result = fixture.defer()
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(1, len(fixture.state["versions"]) - 1)
        self.assertIn(continuation.INTENT, fixture.state["versions"][fixture.state["oid"]])
        fixture.state.pop("lost_cas_response")
        fixture.state["lost_post_response"] = True
        result = fixture.consumer()
        self.assertNotEqual(0, result.returncode)
        self.assertEqual(1, len(fixture.state["requests"]))
        self.assertIn(continuation.REQUEST, fixture.state["versions"][fixture.state["oid"]])
        self.assertNotEqual(0, fixture.consumer().returncode)
        self.assertEqual(1, len(fixture.state["requests"]))
        self.assertNotEqual(0, fixture.consumer(GITHUB_RUN_ATTEMPT="2").returncode)
        self.assertEqual(1, len(fixture.state["requests"]))

    def test_typed_main_receipt_preserves_original_and_resume_roles(self):
        fixture = self.fixture("main")
        receipt, context, check = fixture.prepare_readonly_provenance()
        self.assertEqual("c" * 40, receipt["intent"]["source_sha"])
        self.assertEqual(continuation.BASE, receipt["source_sha"])
        self.assertEqual("main", context["base_ref"])
        before = copy.deepcopy(fixture.state)
        for role in ("resume-source", "original-source", "source-ref", "legacy-main"):
            with self.subTest(role=role):
                candidate = copy.deepcopy(receipt)
                if role == "resume-source":
                    candidate["source_sha"] = candidate["intent"]["source_sha"]
                elif role == "original-source":
                    candidate["intent"]["source_sha"] = candidate["source_sha"]
                elif role == "source-ref":
                    candidate["intent"]["source_ref"] = "main"
                else:
                    candidate["intent"]["schema"] = 1
                    del candidate["intent"]["source_ref"]
                result = fixture.execute("python3 " + str(check), {}, {
                    "CONTEXT": json.dumps(context), "RECEIPT": json.dumps(candidate),
                })
                self.assertNotEqual(0, result.returncode)
                self.assertEqual(before["versions"], fixture.state["versions"])
                self.assertEqual(before["requests"], fixture.state["requests"])

    def test_refresh_final_effect_fence_rechecks_protected_branch_head(self):
        for branch in ("develop", "main"):
            with self.subTest(branch=branch):
                result, dispatches = self.refresh(branch, fence_only=True)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual([], dispatches)
                result, dispatches = self.refresh(branch, fence_only=True, protected_source="d" * 40)
                self.assertNotEqual(0, result.returncode)
                self.assertEqual([], dispatches)

    def test_required_readonly_copy_matches_actual_standalone_provenance(self):
        import textwrap
        source = (ROOT / "scripts/review_request_provenance.py").read_text().strip()
        workflow = (ROOT / ".github/workflows/supplementary-current-revision-required.yml").read_text()
        chunks = workflow.split("<<'CONTINUATION'\n")[1:]
        self.assertEqual(1, len(chunks))
        self.assertEqual(source, textwrap.dedent(chunks[0].split("\n          CONTINUATION", 1)[0]).strip())

    def test_deferred_authority_rejects_advanced_protected_base_before_intent(self):
        for branch in ("develop", "main"):
            with self.subTest(branch=branch):
                fixture = self.fixture(branch)
                fixture.route("/branches/" + branch)["commit"]["sha"] = "d" * 40
                fixture.state["ancestry_by_route"] = {
                    "repos/" + continuation.REPO + "/compare/" + continuation.BASE + "..." + "d" * 40:
                        {"status": "ahead", "behind_by": 0, "merge_base_commit": {"sha": continuation.BASE}},
                }
                result = fixture.defer()
                self.assertNotEqual(0, result.returncode)
                self.assertIn("current default controller" if branch == "develop" else "current PR base", result.stderr)
                self.assertNotIn(continuation.INTENT, fixture.state["versions"][fixture.state["oid"]])
                self.assertEqual([], fixture.state["requests"])
