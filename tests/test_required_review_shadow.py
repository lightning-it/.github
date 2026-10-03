"""Integration tests exercise real normalization against deterministic GitHub reads."""

from copy import deepcopy
import importlib.util
import io
import json
from pathlib import Path
import re
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("review_events", ROOT / "scripts/required-review-shadow.py")
EVENTS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EVENTS)


class FakeAPI(EVENTS.API):
    def __init__(self, policy, responses):
        super().__init__(policy)
        self.responses = responses
        self.paths = []
        self.transform = lambda path, value, occurrence: value

    def read(self, path, variables=None):
        self.paths.append(path)
        self.requests += 1
        value = deepcopy(self.responses[path])
        return self.transform(path, value, self.paths.count(path))


class EventAdapterTests(unittest.TestCase):
    def setUp(self):
        self.policy = json.loads((ROOT / ".lit/required-review-shadow.json").read_text())
        self.policy["lifecycle"] = "shadow"
        self.repo = "lightning-it/.github"
        self.prefix = "repos/" + self.repo
        self.head, self.base = "b" * 40, "a" * 40
        self.repo_object = {"id": 1112629689, "full_name": self.repo}
        actor = {"id": 76040632, "login": "litroc", "type": "User"}
        self.run = {"id": 200, "run_attempt": 1, "repository": self.repo_object,
                    "head_repository": self.repo_object, "actor": actor, "triggering_actor": actor,
                    "path": EVENTS.RUN_PATH, "event": "pull_request_target",
                    "name": "Current revision review gate", "status": "completed",
                    "conclusion": "success", "head_sha": self.head, "head_branch": "feature"}
        self.pull = {"id": 700, "number": 7, "state": "open", "draft": False, "user": actor,
                     "title": "Test", "body": "Body", "labels": [],
                     "head": {"sha": self.head, "ref": "feature", "repo": self.repo_object},
                     "base": {"sha": self.base, "ref": "develop", "repo": self.repo_object}}
        association = {"number": 7}
        for side in ("base", "head"):
            association[side] = {**self.pull[side], "repo": {
                "id": self.policy["repository_id"],
                "url": f"{EVENTS.TRANSPORT.ORIGIN}/repos/{self.repo}"}}
        self.admission = {**self.run, "id": 201, "path": EVENTS.ADMISSION_PATH,
                          "display_title": f"Protected current revision PR #7 opened {self.head}",
                          "pull_requests": [association]}
        app = {"id": 15368, "slug": "github-actions"}
        summary = {"schema": 4, "base_sha": self.base, "head_sha": self.head,
                   "producer_run_id": 200, "pull_request_number": 7, "controller_sha": self.base,
                   "review_path": "applicable Copilot or governed automation exemption",
                   "run_url": f"https://github.com/{self.repo}/actions/runs/200"}
        self.check = {"id": 300, "name": "Protected current-revision verifier",
                      "external_id": f"rep60-required-workflow:v3:201:7:{self.base}:{self.head}",
                      "head_sha": self.head, "app": app, "status": "in_progress", "conclusion": None,
                      "started_at": "2026-10-02T00:00:00Z"}
        neutral = {"id": 301, "name": "Current revision review",
                   "external_id": f"mlx90-current-revision:copilot:v6:7:200:{self.base}:{self.head}",
                   "head_sha": self.head, "app": app, "status": "completed", "conclusion": "success",
                   "completed_at": "2026-10-02T00:00:20Z", "output": {"summary": json.dumps(summary)}}
        review = {"id": 500, "node_id": "R500", "commit_id": self.head, "state": "COMMENTED",
                  "user": {"id": 175728472, "login": "copilot-pull-request-reviewer[bot]", "type": "Bot"},
                  "body": "<!-- ccr-overview-v2 -->\n**Findings:** None",
                  "submitted_at": "2026-10-02T00:00:10Z"}
        self.job = {"id": 400, "name": "Verify current revision policy", "run_id": 200,
                    "run_attempt": 1, "head_sha": self.head, "status": "in_progress", "conclusion": None,
                    "started_at": "2026-10-02T00:00:00Z", "completed_at": None,
                    "steps": [{"name": name, "status": "completed", "conclusion": "success"}
                              for name in (EVENTS.POLICY_STEP, "Publish bound neutral result")]}
        self.responses = {
            f"{self.prefix}/actions/runs/200": self.run,
            f"{self.prefix}/actions/runs/201": self.admission,
            f"{self.prefix}/pulls/7": self.pull,
            f"{self.prefix}/branches/develop": {"protected": True, "commit": {"sha": self.base}},
            f"{self.prefix}/rules/branches/develop": [{"ruleset_id": 21200954, "type": "workflows",
                "parameters": {"workflows": [{"repository_id": 1103407173, "ref": "refs/heads/main",
                    "path": ".github/workflows/dot-github-current-revision-required.yml"}]}}],
            f"{self.prefix}/commits/{self.head}/check-runs?filter=all&per_page=100&page=1": {
                "total_count": 2, "check_runs": [self.check, neutral]},
            f"{self.prefix}/compare/{self.base}...{self.base}": {"status": "identical"},
            f"{self.prefix}/pulls/7/reviews?per_page=100&page=1": [review],
            f"{self.prefix}/pulls/7/reviews/500/comments?per_page=100&page=1": [],
            f"{self.prefix}/issues/7/comments?per_page=100&page=1": [{"id": 600,
                "body": f"<!-- mlx90-copilot-request head={self.head} -->Accepted",
                "user": {"id": 41898282, "login": "github-actions[bot]", "type": "Bot"},
                "created_at": "2026-10-02T00:00:05Z"}],
            "graphql": {"data": {"repository": {"pullRequest": {"number": 7,
                "headRefOid": self.head, "baseRefOid": self.base, "lastEditedAt": None,
                "reviews": {"totalCount": 1, "pageInfo": {"hasNextPage": False},
                    "nodes": [{"id": "R500", "body": review["body"], "lastEditedAt": None,
                               "commit": {"oid": self.head}}]},
                "reviewThreads": {"totalCount": 0, "pageInfo": {"hasNextPage": False}, "nodes": []}}}}},
            f"{self.prefix}/actions/runs/200/jobs?filter=all&per_page=100&page=1": {
                "total_count": 1, "jobs": [self.job]},
            f"{self.prefix}/commits/{self.head}/pulls?per_page=100&page=1": [self.pull],
            f"{self.prefix}/pulls?state=open&base=develop&per_page=100&page=1": [self.pull],
            f"{self.prefix}/check-runs/300": self.check,
        }
        self.now = EVENTS.epoch("2026-10-02T00:03:00Z")

    def api(self):
        return FakeAPI(self.policy, self.responses)

    def event(self):
        return {"repository": self.repo_object, "action": "completed", "workflow_run": self.run}

    def test_delayed_event_uses_real_two_read_adapter_and_zero_writes(self):
        api = self.api()
        result = EVENTS.dispatch(api, self.policy, "workflow_run", self.event(), self.now)
        self.assertEqual("success", result["would_finalize"])
        self.assertEqual(180, result["metrics"]["reservation_to_observer_seconds"])
        self.assertEqual(0, result["writes"])
        self.assertEqual("none", result["authority"])
        self.assertEqual(2, api.paths.count(f"{self.prefix}/pulls/7"))
        self.assertEqual(3, api.paths.count(f"{self.prefix}/actions/runs/200"))
        self.assertEqual("in_progress", self.job["status"])
        self.assertEqual(0, result["metrics"]["producer_jobs_terminal"])
        self.assertIsNone(result["metrics"]["producer_job_seconds"])
        duplicate = EVENTS.dispatch(self.api(), self.policy, "workflow_run", self.event(), self.now)
        self.assertEqual(result, duplicate)

    def test_producer_requires_terminal_success_at_every_read(self):
        for operation, reads in (("dispatch", 3), ("observe", 2)):
            for selected in range(1, reads + 1):
                for status, conclusion in (("in_progress", None), ("queued", None),
                                           ("completed", "failure"), ("completed", None)):
                    with self.subTest(operation=operation, read=selected, status=status,
                                      conclusion=conclusion):
                        api = self.api()
                        def regress(path, value, occurrence):
                            if path == f"{self.prefix}/actions/runs/200" and occurrence == selected:
                                value.update(status=status, conclusion=conclusion)
                            return value
                        api.transform = regress
                        with self.assertRaisesRegex(EVENTS.ShadowRejected, "^run-state$"):
                            if operation == "dispatch":
                                EVENTS.dispatch(api, self.policy, "workflow_run", self.event(), self.now)
                            else:
                                EVENTS.observe(api, self.policy, 200, 7, self.now)
                        self.assertEqual(selected, api.paths.count(f"{self.prefix}/actions/runs/200"))

    def assert_summary_rejected(self, summary, reason):
        path = f"{self.prefix}/commits/{self.head}/check-runs?filter=all&per_page=100&page=1"
        for selected in (1, 2):
            with self.subTest(read=selected):
                api = self.api()
                def malformed(endpoint, value, occurrence):
                    if endpoint == path and occurrence == selected:
                        value["check_runs"][1]["output"]["summary"] = json.dumps(summary)
                    return value
                api.transform = malformed
                with self.assertRaisesRegex(EVENTS.ShadowRejected, "^" + reason + "$"):
                    EVENTS.observe(api, self.policy, 200, 7, self.now)

    def test_neutral_summary_requires_exact_legacy_v6_key_set(self):
        path = f"{self.prefix}/commits/{self.head}/check-runs?filter=all&per_page=100&page=1"
        summary = json.loads(self.responses[path]["check_runs"][1]["output"]["summary"])
        for key in summary:
            with self.subTest(missing=key):
                self.assert_summary_rejected({k: v for k, v in summary.items() if k != key},
                                             "neutral-summary-shape")
        for extra in ({"unexpected": True}, {"review_id": "R500"},
                      {"controller_ref": "develop", "head_repository": self.repo,
                       "pull_request_labels_sha256": "c" * 64,
                       "pull_request_last_edited_at": None, "review_id": "R500"}):
            with self.subTest(extra=extra):
                self.assert_summary_rejected({**summary, **extra}, "neutral-summary-shape")
        for value in (None, [], 4, "summary"):
            with self.subTest(shape=value):
                self.assert_summary_rejected(value, "neutral-summary-shape")

    def test_neutral_summary_integer_types_and_values_are_strict(self):
        path = f"{self.prefix}/commits/{self.head}/check-runs?filter=all&per_page=100&page=1"
        summary = json.loads(self.responses[path]["check_runs"][1]["output"]["summary"])
        for key in ("schema", "producer_run_id", "pull_request_number"):
            reason = "neutral-summary-schema" if key == "schema" else "neutral-summary-integer"
            for value in (float(summary[key]), str(summary[key]), True, False, None, 0, -1, [], {}):
                with self.subTest(field=key, value=value):
                    self.assert_summary_rejected({**summary, key: value}, reason)
            self.assert_summary_rejected({**summary, key: summary[key] + 1},
                                         "neutral-summary-schema" if key == "schema" else "neutral-binding")

    def test_neutral_summary_requires_exact_copilot_path(self):
        path = f"{self.prefix}/commits/{self.head}/check-runs?filter=all&per_page=100&page=1"
        summary = json.loads(self.responses[path]["check_runs"][1]["output"]["summary"])
        for value in (None, "", False, 0, [], {}, "copilot",
                      "deterministic provenance-bound managed distribution exemption",
                      "deterministic evidence-bound ancestry exemption",
                      "deterministic policy-bound Renovate exemption",
                      summary["review_path"] + "\n", summary["review_path"].upper()):
            with self.subTest(path=value):
                self.assert_summary_rejected({**summary, "review_path": value}, "neutral-summary-path")

    def test_neutral_summary_identity_fields_reject_malformed_or_mismatched_values(self):
        path = f"{self.prefix}/commits/{self.head}/check-runs?filter=all&per_page=100&page=1"
        summary = json.loads(self.responses[path]["check_runs"][1]["output"]["summary"])
        for key in ("base_sha", "head_sha", "controller_sha", "run_url"):
            for value in (None, "", False, 0, [], {}, "x" * 40):
                with self.subTest(field=key, value=value):
                    self.assert_summary_rejected({**summary, key: value},
                                                 "controller" if key == "controller_sha" else "neutral-binding")

    def test_second_read_job_regression_rejects(self):
        api = self.api()
        def regression(path, value, occurrence):
            if "/jobs?" in path and occurrence == 1:
                value["jobs"][0].update(status="completed", conclusion="success",
                                         completed_at="2026-10-02T00:00:20Z")
            return value
        api.transform = regression
        with self.assertRaisesRegex(ValueError, "job-visibility-regressed"):
            EVENTS.observe(api, self.policy, 200, 7, self.now)

    def test_webhook_transport_metadata_is_not_identity(self):
        event = deepcopy(self.event())
        event["workflow_run"]["actor"]["avatar_url"] = "https://example.invalid/avatar"
        event["workflow_run"]["repository"]["description"] = "Webhook representation"
        self.assertEqual("success", EVENTS.dispatch(
            self.api(), self.policy, "workflow_run", event, self.now)["would_finalize"])
        event["workflow_run"]["actor"]["id"] = 123
        with self.assertRaisesRegex(ValueError, "event-identity-drift"):
            EVENTS.dispatch(self.api(), self.policy, "workflow_run", event, self.now)

    def test_second_read_metadata_drift_rejects(self):
        api = self.api()
        def change(path, value, occurrence):
            if path.endswith("/pulls/7") and occurrence == 2:
                value["body"] += " changed"
            return value
        api.transform = change
        with self.assertRaisesRegex(ValueError, "evidence-binding-drift"):
            EVENTS.observe(api, self.policy, 200, 7, self.now)

    def test_stale_head_actor_attempt_controller_and_ruleset_reject(self):
        cases = [("head_sha", "c" * 40), ("run_attempt", 2),
                 ("actor", {"id": 123, "login": "unknown", "type": "User"})]
        for key, value in cases:
            with self.subTest(key=key):
                api = self.api()
                api.responses = deepcopy(self.responses)
                api.responses[f"{self.prefix}/actions/runs/200"][key] = value
                with self.assertRaises(ValueError):
                    EVENTS.dispatch(api, self.policy, "workflow_run", self.event(), self.now)
        for path, payload in ((f"{self.prefix}/compare/{self.base}...{self.base}", {"status": "behind"}),
                              (f"{self.prefix}/rules/branches/develop", [])):
            api = self.api()
            api.responses = {**self.responses, path: payload}
            with self.assertRaises(ValueError):
                EVENTS.observe(api, self.policy, 200, 7, self.now)

    def test_missing_failed_and_duplicate_critical_step_reject(self):
        for mode in ("missing", "failed", "duplicate"):
            api = self.api()
            api.responses = deepcopy(self.responses)
            job = api.responses[f"{self.prefix}/actions/runs/200/jobs?filter=all&per_page=100&page=1"]["jobs"][0]
            if mode == "missing":
                job["steps"].pop()
            elif mode == "failed":
                job["steps"][0]["conclusion"] = "failure"
            else:
                job["steps"].append(deepcopy(job["steps"][0]))
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                EVENTS.observe(api, self.policy, 200, 7, self.now)

    def test_threads_pagination_and_unresolved_fail_closed(self):
        for mode in ("pagination", "unresolved"):
            api = self.api()
            api.responses = deepcopy(self.responses)
            threads = api.responses["graphql"]["data"]["repository"]["pullRequest"]["reviewThreads"]
            if mode == "pagination":
                threads["pageInfo"]["hasNextPage"] = True
            else:
                threads.update(totalCount=1, nodes=[{"id": "T1", "isResolved": False}])
            with self.assertRaises(ValueError):
                EVENTS.observe(api, self.policy, 200, 7, self.now)

    def test_inventory_duplicate_incomplete_and_overflow_reject(self):
        path = f"{self.prefix}/items"
        for value in ({"total_count": 2, "items": [{"id": 1}]},
                      {"total_count": 2, "items": [{"id": 1}, {"id": 1}]}):
            api = FakeAPI(self.policy, {path + "?per_page=100&page=1": value})
            with self.assertRaises(EVENTS.READS.TRANSPORT.ReadFailure):
                api.inventory(path, "items")
        responses = {path + f"?per_page=100&page={page}": [{"id": n + (page - 1) * 100}
                    for n in range(1, 101)] for page in range(1, 4)}
        with self.assertRaisesRegex(EVENTS.READS.TRANSPORT.ReadFailure, "page-limit"):
            FakeAPI(self.policy, responses).inventory(path)

    def test_sweeper_only_emits_bound_expiry_and_never_writes(self):
        result = EVENTS.sweep(self.api(), self.policy, self.now + 86400)
        self.assertEqual([300], [item["check_id"] for item in result["expired"]])
        self.assertFalse(result["complete_global_inventory"])
        self.assertEqual(0, result["writes"])
        self.assertEqual([], EVENTS.sweep(self.api(), self.policy, self.now)["expired"])

    def test_sweeper_worst_case_request_budget_boundary(self):
        for count in (14, 15):
            with self.subTest(pulls=count):
                pulls, responses = [], {}
                for number in range(1, count + 1):
                    head = f"{number:040x}"
                    pull = deepcopy(self.pull)
                    pull.update(id=number, number=number)
                    pull["head"]["sha"] = head
                    pulls.append(pull)
                    check = {**self.check, "id": 300 + number, "head_sha": head,
                             "external_id":
                             f"rep60-required-workflow:v3:{200 + number}:{number}:{self.base}:{head}"}
                    checks = [{"id": 1000 + index, "name": "Unrelated check"}
                              for index in range(200)] + [check]
                    for page in range(1, 4):
                        path = f"{self.prefix}/commits/{head}/check-runs?filter=all"
                        responses[path + f"&per_page=100&page={page}"] = {
                            "total_count": len(checks),
                            "check_runs": checks[(page - 1) * 100:page * 100]}
                    admission = deepcopy(self.admission)
                    admission.update(id=200 + number, head_sha=head, display_title=
                                     f"Protected current revision PR #{number} opened {head}")
                    admission["pull_requests"][0]["number"] = number
                    admission["pull_requests"][0]["head"]["sha"] = head
                    responses[f"{self.prefix}/actions/runs/{200 + number}"] = admission
                    responses[f"{self.prefix}/check-runs/{check['id']}"] = check
                    responses[f"{self.prefix}/pulls/{number}"] = pull
                responses[f"{self.prefix}/pulls?state=open&base=develop&per_page=100&page=1"] = pulls
                api = EVENTS.API(self.policy)

                def respond(request, timeout):
                    self.assertEqual("GET", request.method)
                    path = request.full_url.removeprefix(EVENTS.READS.TRANSPORT.ORIGIN + "/")
                    response = mock.MagicMock()
                    response.__enter__.return_value.status = 200
                    response.__enter__.return_value.length = 0
                    response.__enter__.return_value.read.return_value = json.dumps(
                        responses[path]).encode()
                    return response

                api.opener.open = mock.Mock(side_effect=respond)
                with mock.patch.dict(EVENTS.os.environ, {"GH_TOKEN": "test-token"}):
                    if count == 15:
                        with self.assertRaisesRegex(ValueError, "^sweeper-pull-budget$"):
                            EVENTS.sweep(api, self.policy, self.now + 86400)
                        self.assertEqual(1, api.requests)
                    else:
                        result = EVENTS.sweep(api, self.policy, self.now + 86400)
                        self.assertEqual(list(range(301, 315)),
                                         [item["check_id"] for item in result["expired"]])
                        self.assertEqual(0, result["writes"])
                        self.assertEqual(99, api.requests)
                        api.read(f"{self.prefix}/pulls/1")
                        with self.assertRaisesRegex(EVENTS.READS.TRANSPORT.ReadFailure,
                                                    "^request-budget-exhausted$"):
                            api.read(f"{self.prefix}/pulls/1")
                        self.assertEqual(100, api.requests)
                self.assertEqual(api.requests, api.opener.open.call_count)

    def test_sweeper_malformed_base_rejects_before_reservation_inventory(self):
        path = f"{self.prefix}/commits/{self.head}/check-runs?filter=all&per_page=100&page=1"
        invalid = ("", "a" * 39, "a" * 41, "g" * 40, "A" * 40,
                   "a" * 39 + "B", self.base + "\n", " " + self.base,
                   "\u0430" * 40, None, False, 0, 1.5, [], {}, [self.base])
        for base in invalid:
            for checks in ([], [self.check]):
                with self.subTest(base=base, reservations=len(checks)):
                    api = self.api()
                    api.responses = deepcopy(self.responses)
                    api.responses[path] = {"total_count": len(checks), "check_runs": checks}
                    api.responses[f"{self.prefix}/pulls?state=open&base=develop&per_page=100&page=1"][
                        0]["base"]["sha"] = base
                    with self.assertRaisesRegex(EVENTS.ShadowRejected, "^sweeper-base$"):
                        EVENTS.sweep(api, self.policy, self.now + 86400)
                    self.assertEqual(1, api.requests)

    def test_sweeper_missing_base_sha_still_rejects(self):
        path = f"{self.prefix}/commits/{self.head}/check-runs?filter=all&per_page=100&page=1"
        for checks in ([], [self.check]):
            with self.subTest(reservations=len(checks)):
                api = self.api()
                api.responses = deepcopy(self.responses)
                api.responses[path] = {"total_count": len(checks), "check_runs": checks}
                del api.responses[f"{self.prefix}/pulls?state=open&base=develop&per_page=100&page=1"][
                    0]["base"]["sha"]
                with self.assertRaisesRegex(EVENTS.ShadowRejected, "^sweeper-base$"):
                    EVENTS.sweep(api, self.policy, self.now + 86400)
                self.assertEqual(1, api.requests)

    def test_sweeper_valid_base_scopes_reservations_including_empty_inventory(self):
        path = f"{self.prefix}/commits/{self.head}/check-runs?filter=all&per_page=100&page=1"
        for base in (self.base, "0123456789abcdef" * 2 + "01234567"):
            for checks in ([], [self.check]):
                with self.subTest(base=base, reservations=len(checks)):
                    api = self.api()
                    api.responses = deepcopy(self.responses)
                    api.responses[path] = {"total_count": len(checks), "check_runs": checks}
                    api.responses[f"{self.prefix}/pulls?state=open&base=develop&per_page=100&page=1"][
                        0]["base"]["sha"] = base
                    result = EVENTS.sweep(api, self.policy, self.now + 86400)
                    expected = [300] if checks and base == self.base else []
                    self.assertEqual(expected, [item["check_id"] for item in result["expired"]])
                    self.assertEqual(0, result["writes"])
                    self.assertEqual(6 if expected else 2, api.requests)

    def test_terminal_foreign_reservations_do_not_poison_exact_scope(self):
        path = f"{self.prefix}/commits/{self.head}/check-runs?filter=all&per_page=100&page=1"
        for foreign_pr, foreign_base in ((8, self.base), (7, "c" * 40)):
            for conclusion in ("success", "failure"):
                api = self.api()
                api.responses = deepcopy(self.responses)
                foreign = {**deepcopy(self.check), "id": 302, "status": "completed",
                           "conclusion": conclusion, "external_id":
                           f"rep60-required-workflow:v3:202:{foreign_pr}:{foreign_base}:{self.head}"}
                api.responses[path]["check_runs"].append(foreign)
                api.responses[path]["total_count"] = 3
                with self.subTest(pr=foreign_pr, base=foreign_base, conclusion=conclusion):
                    self.assertEqual(300, EVENTS.observe(api, self.policy, 200, 7, self.now)["check_id"])
                    sweep = EVENTS.sweep(api, self.policy, self.now + 86400)
                    self.assertEqual([300], [item["check_id"] for item in sweep["expired"]])
                    self.assertFalse(any(path.endswith("/actions/runs/202") for path in api.paths))

    def test_sweeper_terminal_foreign_reservation_is_ignored(self):
        path = f"{self.prefix}/commits/{self.head}/check-runs?filter=all&per_page=100&page=1"
        self.responses[path]["check_runs"].append({**deepcopy(self.check), "id": 302,
            "status": "completed", "conclusion": "success", "external_id":
            f"rep60-required-workflow:v3:202:8:{self.base}:{self.head}"})
        self.responses[path]["total_count"] = 3
        self.assertEqual([300], [item["check_id"] for item in
                         EVENTS.sweep(self.api(), self.policy, self.now + 86400)["expired"]])

    def test_exact_scope_duplicates_and_forged_provenance_still_reject(self):
        path = f"{self.prefix}/commits/{self.head}/check-runs?filter=all&per_page=100&page=1"
        for mode in ("duplicate", "app", "head"):
            api = self.api()
            api.responses = deepcopy(self.responses)
            checks = api.responses[path]["check_runs"]
            if mode == "duplicate":
                checks.append({**deepcopy(self.check), "id": 302})
                api.responses[path]["total_count"] = 3
            elif mode == "app":
                checks[0]["app"] = {"id": 42, "slug": "unknown"}
            else:
                checks[0]["head_sha"] = "c" * 40
            for operation in (lambda: EVENTS.observe(api, self.policy, 200, 7, self.now),
                              lambda: EVENTS.sweep(api, self.policy, self.now + 86400)):
                with self.subTest(mode=mode), self.assertRaises(ValueError):
                    operation()

    def test_sweeper_drift_rejects(self):
        self.responses[f"{self.prefix}/check-runs/300"] = {**self.check, "head_sha": "c" * 40}
        with self.assertRaisesRegex(ValueError, "sweeper-reservation-drift"):
            EVENTS.sweep(self.api(), self.policy, self.now + 86400)

    def assert_admission_rejected(self, admission, reason):
        for operation in ("observer", "sweeper"):
            with self.subTest(operation=operation):
                api = self.api()
                api.responses = deepcopy(self.responses)
                api.responses[f"{self.prefix}/actions/runs/201"] = deepcopy(admission)
                with self.assertRaisesRegex(EVENTS.ShadowRejected, "^" + reason + "$"):
                    if operation == "observer":
                        EVENTS.observe(api, self.policy, 200, 7, self.now)
                    else:
                        EVENTS.sweep(api, self.policy, self.now + 86400)

    def test_admission_all_native_actions_bind_both_paths(self):
        for action in ("opened", "synchronize", "reopened", "ready_for_review", "edited"):
            with self.subTest(action=action):
                self.admission["display_title"] = (
                    f"Protected current revision PR #7 {action} {self.head}")
                self.assertEqual("success", EVENTS.observe(
                    self.api(), self.policy, 200, 7, self.now)["would_finalize"])
                self.assertEqual([300], [item["check_id"] for item in EVENTS.sweep(
                    self.api(), self.policy, self.now + 86400)["expired"]])

    def test_admission_expected_pr_requires_positive_integer_before_read(self):
        for number in (None, False, True, 0, -1, 7.0, "7", "07", "", [], {}):
            with self.subTest(number=number):
                api = self.api()
                with self.assertRaisesRegex(EVENTS.ShadowRejected, "^admission-pr-number$"):
                    EVENTS.admission_run(api, self.policy, 201, number,
                                         self.base, self.head, "feature")
                self.assertEqual(0, api.requests)

    def test_admission_title_must_match_exact_native_scope(self):
        title = self.admission["display_title"]
        for value in (None, "", False, [], {}, title + "\n", " " + title,
                      title.replace("#7", "#8"), title.replace("#7", "#07"),
                      title.replace("#7", "#+7"), title.replace("opened", "closed"),
                      title.replace("opened", "converted_to_draft"),
                      title.replace("opened", "Opened"), title.replace(" opened ", "  opened "),
                      title.replace(self.head, "c" * 40), title.replace(self.head, self.head.upper()),
                      "lightning-it/other " + title):
            with self.subTest(title=value):
                admission = {**self.admission, "display_title": value}
                self.assert_admission_rejected(admission, "admission-title")
        admission = deepcopy(self.admission)
        del admission["display_title"]
        self.assert_admission_rejected(admission, "admission-title")

    def test_admission_expected_shas_are_canonical_before_read(self):
        for side in ("base", "head"):
            for value in (None, False, 0, [], {}, "", "a" * 39, "a" * 41,
                          "g" * 40, "A" * 40, self.head + "\n"):
                with self.subTest(side=side, value=value):
                    api = self.api()
                    base, head = (value, self.head) if side == "base" else (self.base, value)
                    with self.assertRaisesRegex(EVENTS.ShadowRejected, "^admission-" + side + "$"):
                        EVENTS.admission_run(api, self.policy, 201, 7, base, head, "feature")
                    self.assertEqual(0, api.requests)

    def test_admission_malformed_head_ref_rejects_even_when_all_evidence_agrees(self):
        for value in (None, False, True, 0, [], {}, "", "HEAD", "a" * 256, "-feature", "/feature",
                      "feature/", "feature//x", ".feature", "feature/.hidden", "feature..x",
                      "feature.", "feature.lock", "feature.lock/x", "feature@{x}", "@",
                      "feature x", "feature\t", "feature\n", "feature\x00", "feature\x7f",
                      "feature~x", "feature^x", "feature:x", "feature?x", "feature*x",
                      "feature[x", "feature\\x", "f\u00e9ature"):
            with self.subTest(ref=value):
                self.pull["head"]["ref"] = value
                self.run["head_branch"] = value
                self.admission["head_branch"] = value
                self.admission["pull_requests"][0]["head"]["ref"] = value
                api = self.api()
                with self.assertRaisesRegex(EVENTS.ShadowRejected, "^admission-head-ref$"):
                    EVENTS.admission_run(api, self.policy, 201, 7, self.base, self.head, value)
                self.assertEqual(0, api.requests)
                self.assert_admission_rejected(self.admission, "admission-head-ref")

    def test_admission_supported_head_refs_bind_both_paths(self):
        for value in ("feature", "feat/li-219-shadow-integration", "renovate/python-3.x",
                      "_feature", "head", "HeAd", "a" * 255):
            with self.subTest(ref=value):
                self.pull["head"]["ref"] = value
                self.run["head_branch"] = value
                self.admission["head_branch"] = value
                self.admission["pull_requests"][0]["head"]["ref"] = value
                self.assertEqual("success", EVENTS.observe(
                    self.api(), self.policy, 200, 7, self.now)["would_finalize"])
                self.assertEqual([300], [item["check_id"] for item in EVENTS.sweep(
                    self.api(), self.policy, self.now + 86400)["expired"]])

    def test_admission_requires_one_native_numeric_pr_association(self):
        association = self.admission["pull_requests"][0]
        for value in (None, {}, "", [], [None], [association, association]):
            with self.subTest(associations=value):
                admission = {**self.admission, "pull_requests": value}
                self.assert_admission_rejected(admission, "admission-pr-association")
        admission = deepcopy(self.admission)
        del admission["pull_requests"]
        self.assert_admission_rejected(admission, "admission-pr-association")
        for number in (None, False, True, 0, -1, 7.0, "7", "07", 8):
            with self.subTest(number=number):
                admission = deepcopy(self.admission)
                admission["pull_requests"][0]["number"] = number
                self.assert_admission_rejected(admission, "admission-pr-association")
        admission = deepcopy(self.admission)
        del admission["pull_requests"][0]["number"]
        self.assert_admission_rejected(admission, "admission-pr-association")

    def test_same_head_other_pr_admission_cannot_authorize_reservation(self):
        admission = deepcopy(self.admission)
        admission["display_title"] = f"Protected current revision PR #8 opened {self.head}"
        admission["pull_requests"][0]["number"] = 8
        self.assert_admission_rejected(admission, "admission-title")

    def test_admission_association_binds_both_shas_refs_and_repositories(self):
        for side in ("base", "head"):
            for field, value in (("sha", "c" * 40), ("sha", None), ("ref", "other"),
                                 ("repo", None), ("repo", {"id": 42}),
                                 ("repo", {"id": float(self.policy["repository_id"]),
                                           "url": f"{EVENTS.TRANSPORT.ORIGIN}/repos/{self.repo}"}),
                                 ("repo", {"id": self.policy["repository_id"],
                                           "url": "https://api.github.com/repos/other/repo"})):
                with self.subTest(side=side, field=field, value=value):
                    admission = deepcopy(self.admission)
                    admission["pull_requests"][0][side][field] = value
                    self.assert_admission_rejected(admission, "admission-pr-binding")
            admission = deepcopy(self.admission)
            del admission["pull_requests"][0][side]
            self.assert_admission_rejected(admission, "admission-pr-binding")

    def test_admission_existing_provenance_checks_apply_to_both_paths(self):
        for field, value, reason in (
                ("path", EVENTS.RUN_PATH, "admission-provenance"),
                ("event", "workflow_dispatch", "admission-provenance"),
                ("head_sha", "c" * 40, "admission-provenance"),
                ("head_branch", "other", "admission-head-ref"),
                ("repository", {"id": 42}, "admission-repository"),
                ("head_repository", {"id": 42}, "admission-repository"),
                ("actor", {"id": 42}, "admission-actor-attempt"),
                ("triggering_actor", {"id": 42}, "admission-actor-attempt"),
                ("run_attempt", 2, "admission-actor-attempt")):
            with self.subTest(field=field):
                self.assert_admission_rejected({**self.admission, field: value}, reason)

    def test_admission_association_is_revalidated_on_both_paths(self):
        for operation in ("observer", "sweeper"):
            with self.subTest(operation=operation):
                api = self.api()
                def drift(path, value, occurrence):
                    if path == f"{self.prefix}/actions/runs/201" and occurrence == 2:
                        value["pull_requests"][0]["number"] = 8
                    return value
                api.transform = drift
                with self.assertRaisesRegex(EVENTS.ShadowRejected, "^admission-pr-association$"):
                    if operation == "observer":
                        EVENTS.observe(api, self.policy, 200, 7, self.now)
                    else:
                        EVENTS.sweep(api, self.policy, self.now + 86400)

    def test_sweeper_admission_actor_attempt_repository_and_drift_reject(self):
        path = f"{self.prefix}/actions/runs/201"
        for key, value in (("actor", {"id": 42}), ("run_attempt", 2),
                           ("head_repository", {"id": 1112629689, "full_name": "other/repo"}),
                           ("head_sha", "c" * 40), ("head_branch", "other")):
            api = self.api()
            api.responses = deepcopy(self.responses)
            api.responses[path][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                EVENTS.sweep(api, self.policy, self.now + 86400)
        api = self.api()
        def drift(endpoint, value, occurrence):
            if endpoint == path and occurrence == 2:
                value["status"] = "in_progress"
            return value
        api.transform = drift
        with self.assertRaisesRegex(ValueError, "sweeper-admission-drift"):
            EVENTS.sweep(api, self.policy, self.now + 86400)

    def test_reservation_status_conclusion_pairs_fail_closed(self):
        for status, conclusion in (("completed", None), ("in_progress", "failure"),
                                   ("queued", "success"), ("completed", "neutral")):
            self.check.update(status=status, conclusion=conclusion)
            for operation in (lambda: EVENTS.observe(self.api(), self.policy, 200, 7, self.now),
                              lambda: EVENTS.sweep(self.api(), self.policy, self.now + 86400)):
                with self.subTest(status=status, conclusion=conclusion), self.assertRaisesRegex(
                        ValueError, "reservation-state"):
                    operation()

    def test_terminal_reservations_are_observed_but_not_expired(self):
        for conclusion in ("success", "failure"):
            self.check.update(status="completed", conclusion=conclusion)
            result = EVENTS.observe(self.api(), self.policy, 200, 7, self.now)
            self.assertEqual(conclusion == "failure",
                             result["metrics"]["native_failure_with_ready_evidence"])
            self.assertEqual([], EVENTS.sweep(self.api(), self.policy, self.now + 86400)["expired"])

    def test_sweeper_revalidates_pull_after_reservation_refresh(self):
        for field, value in (("state", "closed"), ("number", 8),
                             ("head", {**self.pull["head"], "sha": "c" * 40}),
                             ("base", {**self.pull["base"], "sha": "d" * 40}),
                             ("base", {**self.pull["base"], "ref": "main"})):
            api = self.api()
            def drift(path, payload, occurrence):
                if path == f"{self.prefix}/pulls/7":
                    self.assertIn(f"{self.prefix}/check-runs/300", api.paths)
                    payload[field] = value
                return payload
            api.transform = drift
            with self.subTest(field=field, value=value), self.assertRaisesRegex(
                    ValueError, "sweeper-pull-drift"):
                EVENTS.sweep(api, self.policy, self.now + 86400)

    def test_malformed_json_shapes_produce_sanitized_cli_rejection(self):
        for mode in ("event-array", "rule-array", "nested-shape"):
            api = self.api()
            if mode == "rule-array":
                api.responses = {**self.responses, f"{self.prefix}/rules/branches/develop": [[]]}
            elif mode == "nested-shape":
                api.responses = {**self.responses, f"{self.prefix}/branches/develop": []}
            event = [] if mode == "event-array" else self.event()
            with mock.patch("sys.argv", ["observer", "--event", "workflow_run", "--event-path", "event.json"]), \
                    mock.patch.object(EVENTS, "read_file", side_effect=[self.policy, event]), \
                    mock.patch.dict(EVENTS.os.environ, {"LI219_EVENT_SHADOW": "true"}), \
                    mock.patch.object(EVENTS, "API", return_value=api), \
                    mock.patch("sys.stdout", new_callable=io.StringIO) as output:
                self.assertEqual(1, EVENTS.main())
                result = json.loads(output.getvalue())
            self.assertEqual("li219-shadow-rejection/v1", result["schema"])
            self.assertEqual(0, result["writes"])
            self.assertNotIn("Traceback", output.getvalue())

    def test_inactive_policy_performs_zero_api_calls_and_active_is_refused(self):
        policy = {**self.policy, "lifecycle": "inactive"}
        api = self.api()
        self.assertEqual("li219-shadow-disabled/v1", EVENTS.dispatch(api, policy, "schedule", {}, self.now)["schema"])
        self.assertEqual([], api.paths)
        with self.assertRaisesRegex(ValueError, "writer-not-supported"):
            EVENTS.validate_policy({**self.policy, "lifecycle": "active"})

    def test_metrics_deduplicate_events_and_report_sample_limits(self):
        first = EVENTS.observe(self.api(), self.policy, 200, 7, self.now)
        duplicate = EVENTS.observe(self.api(), self.policy, 200, 7, self.now + 30)
        result = EVENTS.summarize([duplicate, first, first])
        self.assertEqual(1, result["unique_operations"])
        self.assertEqual({"median": 5, "p95": 5, "observed_samples": 1},
                         result["statistics"]["request_to_review_seconds"])
        self.assertIsNone(first["metrics"]["producer_job_seconds"])
        self.assertEqual(0, result["statistics"]["producer_job_seconds"]["observed_samples"])
        self.assertIsNone(result["measured_false_negative_rate"])
        self.assertIsNone(EVENTS.summarize([])["candidate_rate"])

    def test_duplicate_or_foreign_request_marker_rejects(self):
        path = f"{self.prefix}/issues/7/comments?per_page=100&page=1"
        self.responses[path][0]["user"]["id"] = 123
        with self.assertRaisesRegex(ValueError, "request-marker-provenance"):
            EVENTS.observe(self.api(), self.policy, 200, 7, self.now)
        self.responses[path].append({**self.responses[path][0], "id": 601})
        with self.assertRaisesRegex(ValueError, "request-marker-not-unique"):
            EVENTS.observe(self.api(), self.policy, 200, 7, self.now)

    def test_preexisting_review_without_request_marker_is_supported(self):
        self.responses[f"{self.prefix}/issues/7/comments?per_page=100&page=1"] = []
        result = EVENTS.observe(self.api(), self.policy, 200, 7, self.now)
        self.assertEqual("success", result["would_finalize"])
        self.assertIsNone(result["metrics"]["request_to_review_seconds"])
        self.assertIsNone(result["metrics"]["request_to_observer_seconds"])
        self.assertEqual(10, result["metrics"]["review_to_neutral_seconds"])

    def test_empty_or_marker_only_review_after_native_success_rejects(self):
        path = f"{self.prefix}/pulls/7/reviews?per_page=100&page=1"
        for body in ("", " \t\n", "<!-- ccr-overview-v2 -->", "unable to review this pull request"):
            with self.subTest(body=body):
                self.responses[path][0]["body"] = body
                with self.assertRaisesRegex(ValueError, "review-content-empty|review-unavailable"):
                    EVENTS.observe(self.api(), self.policy, 200, 7, self.now)

    def test_review_content_edit_between_reads_rejects(self):
        api = self.api()
        def edit(path, value, occurrence):
            if path == f"{self.prefix}/pulls/7/reviews?per_page=100&page=1" and occurrence == 2:
                value[0]["body"] = " "
            return value
        api.transform = edit
        with self.assertRaisesRegex(ValueError, "review-content-empty"):
            EVENTS.observe(api, self.policy, 200, 7, self.now)

    def test_skipped_job_without_times_adds_no_runner_duration(self):
        path = f"{self.prefix}/actions/runs/200/jobs?filter=all&per_page=100&page=1"
        self.job.update(status="completed", conclusion="success",
                        completed_at="2026-10-02T00:03:00Z")
        self.responses[path]["jobs"].append({**self.job, "id": 401, "name": "Skipped helper",
            "conclusion": "skipped", "started_at": None, "completed_at": None})
        self.responses[path]["total_count"] = 2
        result = EVENTS.observe(self.api(), self.policy, 200, 7, self.now)
        self.assertEqual(180, result["metrics"]["producer_job_seconds"])
        self.assertEqual(3, result["metrics"]["producer_job_minutes"])


    def test_historical_overview_counts_use_live_thread_resolution(self):
        path = f"{self.prefix}/pulls/7/reviews?per_page=100&page=1"
        for body in ("**Findings:** None\n<strong>Previously missed (1)</strong>",
                     "**Findings:** 1\n<strong>Open (1)</strong>",
                     "Changes recommended\n**Findings:** 2\n<strong>Open (2)</strong>"):
            api = self.api()
            api.responses = deepcopy(self.responses)
            api.responses[path][0]["body"] = body
            graph = api.responses["graphql"]["data"]["repository"]["pullRequest"]
            graph["reviews"]["nodes"][0]["body"] = body
            graph["reviewThreads"].update(totalCount=1, nodes=[{
                "id": "T1", "isResolved": True, "comments": {
                    "totalCount": 1, "pageInfo": {"hasNextPage": False},
                    "nodes": [{"id": "C1", "body": "Historical finding",
                               "updatedAt": "2026-10-02T00:00:10Z"}]}}])
            with self.subTest(body=body):
                self.assertEqual("success", EVENTS.observe(
                    api, self.policy, 200, 7, self.now)["would_finalize"])
            graph["reviewThreads"]["nodes"][0]["isResolved"] = False
            with self.assertRaisesRegex(ValueError, "unresolved-thread"):
                EVENTS.observe(api, self.policy, 200, 7, self.now)

    def test_post_success_review_edits_fail_closed(self):
        graph = self.responses["graphql"]["data"]["repository"]["pullRequest"]["reviews"]
        graph["nodes"][0]["lastEditedAt"] = "2026-10-02T00:00:21Z"
        with self.assertRaisesRegex(ValueError, "review-edited-after-evidence"):
            EVENTS.observe(self.api(), self.policy, 200, 7, self.now)

    def test_later_native_failure_is_not_lost_by_integrated_reducer(self):
        first = EVENTS.observe(self.api(), self.policy, 200, 7, self.now)
        self.check.update(status="completed", conclusion="failure")
        later = EVENTS.observe(self.api(), self.policy, 200, 7, self.now + 30)
        for values in ([first, later], [later, first]):
            result = EVENTS.summarize(values)
            self.assertEqual(1, result["native_failure_with_ready_evidence_count"])
            self.assertEqual(1, result["unique_operations"])

    def test_disabled_cli_never_constructs_client_or_reads_event(self):
        policy = {**self.policy, "lifecycle": "inactive"}
        with mock.patch("sys.argv", ["observer", "--event", "workflow_run", "--event-path", "missing"]), \
                mock.patch.object(EVENTS, "read_file", return_value=policy) as read, \
                mock.patch.object(EVENTS, "API") as api, \
                mock.patch("sys.stdout", new_callable=io.StringIO) as output:
            self.assertEqual(0, EVENTS.main())
            self.assertEqual(1, read.call_count)
            api.assert_not_called()
        self.assertEqual(0, json.loads(output.getvalue())["api_requests"])

    def test_transport_uses_accepted_kernel_and_closed_read_routes(self):
        import http.client
        api = EVENTS.API(self.policy)
        response = mock.MagicMock()
        response.__enter__.return_value.status = 200
        response.__enter__.return_value.length = 0
        response.__enter__.return_value.read.return_value = b"{}"
        api.opener.open = mock.Mock(return_value=response)
        with mock.patch.dict(EVENTS.os.environ, {"GH_TOKEN": "test-token"}):
            api.read(self.prefix + "/pulls/7")
            self.assertEqual("GET", api.opener.open.call_args.args[0].method)
            api.read("graphql", {"owner": "lightning-it", "name": ".github", "number": 7})
            request = api.opener.open.call_args.args[0]
            self.assertEqual("POST", request.method)
            self.assertEqual(EVENTS.READS.THREAD_QUERY, json.loads(request.data)["query"])
            self.assertNotIn("mutation", EVENTS.READS.THREAD_QUERY)
            for endpoint, variables in (
                ("https://evil.invalid", None), (self.prefix.replace(".github", "Xgithub") + "/pulls/7", None),
                (self.prefix + "/check-runs/300", {"conclusion": "success"}),
                (self.prefix + "/pulls/7/reviews?per_page=100&page=4", None),
                ("graphql", {"owner": "other", "name": ".github", "number": 7}),
                ("graphql", {"owner": "lightning-it", "name": ".github", "number": True}),
            ):
                with self.assertRaises(EVENTS.READS.TRANSPORT.ReadFailure):
                    api.read(endpoint, variables)
            self.assertEqual(2, api.opener.open.call_count)
            response.__enter__.return_value.read.side_effect = http.client.IncompleteRead(b"private")
            with self.assertRaisesRegex(EVENTS.READS.TRANSPORT.ReadFailure, "^read-failed$"):
                api.read(self.prefix + "/pulls/7")

    def test_adapter_cli_sanitizes_all_ordinary_exception_classes(self):
        import http.client
        for error in (http.client.IncompleteRead(b"private"), RuntimeError("private"),
                      OSError("private"), AttributeError("private")):
            with mock.patch("sys.argv", ["observer", "--event", "schedule", "--event-path", "unused"]), \
                    mock.patch.object(EVENTS, "read_file", side_effect=error), \
                    mock.patch("sys.stdout", new_callable=io.StringIO) as output:
                self.assertEqual(1, EVENTS.main())
            self.assertEqual("invalid-evidence", json.loads(output.getvalue())["reason"])
            self.assertNotIn("private", output.getvalue())

    def test_workflows_are_default_off_read_only_and_use_protected_source(self):
        import yaml
        for filename in ("required-review-event-shadow.yml", "required-review-sweeper-shadow.yml"):
            workflow = yaml.safe_load((ROOT / ".github/workflows" / filename).read_text())
            self.assertTrue(all(value == "read" for value in workflow["permissions"].values()))
            self.assertEqual({"actions", "checks", "contents", "pull-requests"},
                             set(workflow["permissions"]))
            job = workflow["jobs"]["observe"]
            self.assertIn("vars.LI219_EVENT_SHADOW == 'true'", job["if"])
            self.assertEqual("${{ github.workflow_sha }}", job["steps"][0]["with"]["ref"])
            self.assertFalse(job["steps"][0]["with"]["persist-credentials"])
            self.assertIn("--read-only", job["steps"][1]["run"])
            self.assertNotIn("check-runs", job["steps"][1]["run"])
            expected_image = re.search(r'^COPILOT_DEVTOOL_IMAGE = "([^"]+)"',
                (ROOT / "scripts/lit-push-ready.py").read_text(), re.MULTILINE).group(1)
            self.assertEqual(expected_image, job["steps"][1]["env"]["DEVTOOLS_IMAGE"])


if __name__ == "__main__":
    unittest.main()
