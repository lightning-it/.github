import datetime as dt
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from tests import test_copilot_review_refresh as contracts


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("review_event", ROOT / "scripts/review-event-reconcile.py")
EVENT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EVENT)


class ReviewEventTests(unittest.TestCase):
    head, base = "b" * 40, "a" * 40
    now = dt.datetime(2026, 10, 5, 18, tzinfo=dt.timezone.utc)

    def test_copilot_completion_wakes_only_the_protected_inventory_locator(self):
        import yaml
        path = ROOT / '.github/workflows/review-event-reconcile.yml'
        workflow = yaml.safe_load(path.read_text())
        events = workflow.get('on', workflow.get(True))
        self.assertEqual(['completed'], events['workflow_run']['types'])
        self.assertEqual({'Copilot', 'Running Copilot Code Review', 'Current revision review gate',
                          'Protected current-revision evidence verifier',
                          'Protected dot-github current-revision verifier'}, set(events['workflow_run']['workflows']))
        self.assertEqual([{'cron': '*/10 * * * *'}], events['schedule'])
        job = workflow['jobs']['reconcile']
        self.assertIn("vars.LI219_EVENT_MODE == 'enabled'", job['if'])
        self.assertEqual('${{ github.workflow_sha }}', job['steps'][0]['with']['ref'])
        self.assertIs(False, job['steps'][0]['with']['persist-credentials'])
        executable = job['steps'][1]['run']
        self.assertIn('python3 scripts/review-event-reconcile.py', executable)
        self.assertNotIn('github.event.', executable)
        self.assertNotIn('GITHUB_EVENT_PATH', executable)
        self.assertNotIn('GITHUB_EVENT_PATH', (ROOT / 'scripts/review-event-reconcile.py').read_text())
        mirror = ROOT / 'default/.github/workflows/review-event-reconcile.yml'
        if mirror.exists(): self.assertEqual(path.read_bytes(), mirror.read_bytes())

    def review(self, **changes):
        return {"id": 17, "commit_id": self.head, "body": "Review complete.",
                "user": {"login": "copilot-pull-request-reviewer[bot]"},
                "state": "COMMENTED", **changes}

    def test_any_files_marker_requires_explicit_negation_in_body_or_inline(self):
        positives = ('Copilot was able to review this pull request.', 'able to review this pull request',
                     'COPILOT WAS\u00a0ABLE\u2003TO REVIEW THIS PULL REQUEST',
                     'The bot was able to review any files.', 'able to review any files',
                     'THE BOT WAS\u00a0ABLE\u2003TO REVIEW ANY FILES')
        negatives = ("Copilot wasn't able to review this pull request.",
                     'Copilot wasn’t able to review this pull request.',
                     'Copilot was not able to review this pull request.',
                     'Copilot is not able to review this pull request.',
                     "Copilot isn't able to review this pull request.",
                     'Copilot isn’t able to review this pull request.',
                     'COPILOT ISN’T ABLE\u2003TO\u00a0REVIEW THIS PULL REQUEST.',
                     'COPILOT\u00a0WASN’T\u2003ABLE\tTO REVIEW THIS PULL REQUEST',
                     "Copilot wasn't able to review any files.",
                     'Copilot wasn’t able to review any files.',
                     "Copilot isn't able to review any files.",
                     "Copilot isn’t able to review any files.",
                     "COPILOT ISN’T ABLE\u2003TO\u00a0REVIEW\u202fANY\u2009FILES.",
                     "The bots aren't able to review any files.",
                     "The bots weren’t able to review any files.",
                     'COPILOT\u00a0WASN’T\u2003ABLE\tTO REVIEW ANY FILES',
                     'Copilot is not able to review any files.',
                     'Copilot is unable to review any files.')
        for messages, expected in ((positives, True), (negatives, False)):
            for text in messages:
                for inline in (False, True):
                    with self.subTest(text=text, inline=inline):
                        review = self.review() if inline else self.review(body=text)
                        comments = [{'body': text}] if inline else []
                        self.assertEqual(expected, EVENT.clean_review(review, comments, self.head))

    def test_review_content_rejects_stale_empty_quota_and_foreign(self):
        self.assertTrue(EVENT.clean_review(self.review(), [], self.head))
        for review in (self.review(commit_id=self.base), self.review(body=" "),
                       self.review(body="Quota\nexceeded"), self.review(state="DISMISSED"),
                       self.review(user={"login": "litroc"})):
            self.assertFalse(EVENT.clean_review(review, [], self.head))
        self.assertFalse(EVENT.clean_review(self.review(), [{"body": "Suppressed comments"}], self.head))
        self.assertTrue(EVENT.clean_review(self.review(body=""), [{"body": "Reviewed files"}], self.head))

    def reconcile(self, *, delay=180, missing=False, state="completed", drift=False, uncertain=False, review_body="Review complete.", comment_body=None, history=(), pr_count=1, transform=None, neutral=False, required=None, inventory_transform=None, base_ref="develop"):
        prefix = "repos/lightning-it/.github"
        pr = {"id": 23, "number": 23, "draft": False, "state": "open",
              "user": {"login": "litroc", "type": "User"},
              "head": {"sha": self.head, "ref": "fix/final", "repo": {"full_name": "lightning-it/.github"}},
              "base": {"sha": self.base, "ref": base_ref}}
        run = {"id": 77, "path": EVENT.PRODUCER, "event": "pull_request_target",
               "repository": {"full_name": "lightning-it/.github"},
               "head_repository": {"full_name": "lightning-it/.github"}, "run_attempt": 1, "head_sha": self.head,
               "head_branch": "fix/final", "pull_requests": [],
               "status": state, "created_at": (self.now - dt.timedelta(seconds=delay)).isoformat()}
        inventories = {

            f"{prefix}/pulls?state=open": [{**pr, "id": 23 + i, "number": 23 + i} for i in range(pr_count)],
            f"{prefix}/actions/runs?event=pull_request_target&head_sha={self.head}": [run],
            f"{prefix}/actions/runs?head_sha={self.head}": [run, *(required if required is not None else [self.required_run()])],
            f"{prefix}/actions/runs/77/attempts/1/jobs": [{"id": 78, "name": "Verify current revision policy",
                                                        "status": "completed", "conclusion": "success"}],
            f"{prefix}/commits/{self.head}/check-runs?filter=all": [{"id": 79, "name": "Current revision review",
                "app": {"id": 15368, "slug": "github-actions"}, "status": "completed", "conclusion": "success",
                "output": {"summary": '{"producer_run_id":77}'}}] if neutral else [],
            f"{prefix}/pulls/23/reviews": [] if missing else [self.review(body=review_body)],
            f"{prefix}/pulls/23/reviews/17/comments": [] if comment_body is None else [{"body": comment_body}],
        }
        mutations = []

        def api(route, payload=None):
            if payload is not None:
                mutations.append((route, payload))
                if uncertain:
                    raise TimeoutError("response lost after server accepted dispatch")
                return None
            if "/actions/workflows/" in route:
                response = self.inventory_response(history, route)
                return transform(route, response) if transform else response
            if inventory_transform and 'per_page=100&page=' in route:
                inventory_route = route.rsplit('&per_page=100&page=', 1)[0]
                if inventory_route == route:
                    inventory_route = route.rsplit('?per_page=100&page=', 1)[0]
                rows = inventories[inventory_route]
                key = 'workflow_runs' if '/actions/runs?' in inventory_route else 'jobs' if '/jobs' in inventory_route else 'check_runs' if '/check-runs' in inventory_route else None
                response = {'total_count': len(rows), key: rows} if key else rows
                return inventory_transform(route, response)
            if route == f"{prefix}/actions/runs/77":
                return run
            if route == prefix:
                return {"default_branch": "develop"}
            if route.startswith(f"{prefix}/pulls/"):
                return {**pr, "head": {**pr["head"], "sha": self.base}} if drift else pr
            raise AssertionError(route)

        with patch.object(EVENT, "api", side_effect=api), \
                patch.object(EVENT, "pages", side_effect=EVENT.pages if inventory_transform else lambda route, key=None: inventories[route.replace("/pulls/24/", "/pulls/23/").replace("/pulls/25/", "/pulls/23/")]), \
                patch.dict(os.environ, LI219_EVENT_MODE="enabled", GITHUB_REF="refs/heads/develop", GITHUB_REF_PROTECTED="true"):
            if uncertain:
                with self.assertRaises(TimeoutError):
                    EVENT.reconcile("lightning-it/.github", self.now)
            else:
                EVENT.reconcile("lightning-it/.github", self.now)
        return mutations

    def test_main_refresh_dispatch_uses_authenticated_main_base(self):
        calls = self.reconcile(base_ref="main")
        self.assertEqual(1, len(calls))
        self.assertTrue(calls[0][0].endswith("copilot-review-refresh.yml/dispatches"))
        self.assertEqual("main", calls[0][1]["ref"])

    def test_late_review_after_ten_minutes_dispatches_same_pr_without_review_request(self):
        for delay in (180, 601, 3600):
            calls = self.reconcile(delay=delay)
            self.assertEqual(1, len(calls))
            self.assertTrue(calls[0][0].endswith("copilot-review-refresh.yml/dispatches"))
            self.assertEqual("23", calls[0][1]["inputs"]["pr_number"])
            self.assertEqual(self.head, calls[0][1]["inputs"]["expected_head"])

    def test_terminal_markers_never_dispatch_and_later_valid_review_remains_eligible(self):
        for marker in EVENT.MARKERS:
            for field in ('review_body', 'comment_body'):
                with self.subTest(marker=marker, field=field):
                    value = marker.upper().replace(' ', '\n')
                    self.assertEqual([], self.reconcile(**{field: value}))
                    self.assertEqual(1, len(self.reconcile()))

    def test_missing_event_expiry_early_producer_and_stale_head_never_dispatch(self):
        for args in ({"missing": True}, {"delay": 7 * 86400 + 1},
                     {"state": "in_progress"}, {"drift": True}):
            self.assertEqual([], self.reconcile(**args))

    def test_ambiguous_dispatch_response_is_not_retried(self):
        self.assertEqual(1, len(self.reconcile(uncertain=True)))

    def test_active_dispatch_is_deduplicated(self):
        run = {"path": ".github/workflows/copilot-review-refresh.yml",
               "event": "workflow_dispatch", "display_title": "bound", "status": "queued"}
        self.assertTrue(EVENT.recent_dispatch([run], EVENT.REFRESH, "bound"))
        self.assertFalse(EVENT.recent_dispatch([run], EVENT.REFRESH, "foreign"))

    def required_run(self):
        repo = "lightning-it/.github"
        api_url = f"https://api.github.com/repos/{repo}"
        return {"id": 88, "workflow_id": 999, "event": "pull_request_target",
                "created_at": "2026-10-05T17:00:00Z", "run_attempt": 1,
                "actor": {"login": "litroc"}, "triggering_actor": {"login": "litroc"},
                "path": ".github/workflows/dot-github-current-revision-required.yml",
                "workflow_url": f"{api_url}/actions/required_workflows/999",
                "repository": {"full_name": repo}, "head_repository": {"full_name": repo},
                "head_sha": self.head, "head_branch": "fix/final", "status": "completed", "conclusion": "failure",
                "name": "Protected dot-github current-revision verifier",
                "display_title": f"Cross-protect .github PR #23 opened {self.head}",
                "pull_requests": [{"number": 23, "url": f"{api_url}/pulls/23",
                    "head": {"sha": self.head, "ref": "fix/final", "repo": {"url": api_url}},
                    "base": {"sha": self.base, "ref": "develop", "repo": {"url": api_url}}}]}

    def test_required_recovery_uses_unfiltered_native_authority_inventory(self):
        # The event-filtered inventory contains ONLY the producer. The no-event
        # inventory also contains the actual organization Required run.
        calls = self.reconcile(neutral=True)
        self.assertEqual(1, len(calls))
        self.assertTrue(calls[0][0].endswith("current-revision-rerun.yml/dispatches"))
        self.assertEqual("77", calls[0][1]["inputs"]["producer_run_id"])
        self.assertEqual([], self.reconcile(neutral=True, required=[]))
        run = self.required_run()
        run["conclusion"] = "success"
        self.assertEqual([], self.reconcile(neutral=True, required=[run]))

    def test_local_foreign_stale_or_ambiguous_runs_never_stand_in_for_required(self):
        for field, value in (
            ("workflow_url", "https://api.github.com/repos/lightning-it/.github/actions/workflows/999"),
            ("path", ".github/workflows/supplementary-current-revision-required.yml"),
            ("event", "push"), ("head_sha", self.base), ("head_branch", "foreign"),
            ("repository", {"full_name": "lightning-it/foreign"}),
            ("head_repository", {"full_name": "lightning-it/foreign"}),
            ("display_title", f"Cross-protect .github PR #24 opened {self.head}"),
            ("workflow_id", True), ("status", "in_progress"),
        ):
            with self.subTest(field=field):
                run = self.required_run()
                run[field] = value
                self.assertEqual([], self.reconcile(neutral=True, required=[run]))
        for side in ("base", "head"):
            run = self.required_run()
            run["pull_requests"][0][side]["sha"] = "c" * 40
            self.assertEqual([], self.reconcile(neutral=True, required=[run]))
        run = self.required_run()
        run["pull_requests"][0]["number"] = 24
        self.assertEqual([], self.reconcile(neutral=True, required=[run]))
        self.assertEqual([], self.reconcile(neutral=True, required=[self.required_run(), self.required_run()]))

    def test_ordered_required_terminal_supersession_preserves_all_guards(self):
        old = self.required_run()
        new = {**old, "id": 89, "created_at": "2026-10-05T17:01:00Z"}
        self.assertEqual(1, len(self.reconcile(neutral=True, required=[new, old])))
        self.assertEqual([], self.reconcile(neutral=True, required=[old, {**new, "conclusion": "success"}]))
        for changes in ({"status": "in_progress", "conclusion": None}, {"run_attempt": 3},
                        {"actor": {"login": "foreign"}}, {"triggering_actor": {"login": "foreign"}},
                        {"created_at": "invalid"}, {"created_at": "2026-02-30T17:00:00Z"}):
            with self.subTest(changes=changes):
                self.assertEqual([], self.reconcile(neutral=True, required=[{**old, **changes}, new]))
        self.assertEqual(1, len(self.reconcile(neutral=True, required=[old, {
            **new, "run_attempt": 2, "triggering_actor": {"login": "github-actions[bot]"}}])))

    def test_other_pilots_bind_the_central_organization_required_path(self):
        for repo in ("lightning-it/shared-assets-lit", "lightning-it/ansible-collection-supplementary"):
            run = self.required_run()
            import json
            run = json.loads(json.dumps(run).replace("lightning-it/.github", repo))
            run["path"] = ".github/workflows/supplementary-current-revision-required.yml"
            run["name"] = "Protected current-revision evidence verifier"
            run["display_title"] = f"Protected current revision PR #23 opened {self.head}"
            pr = {"number": 23, "head": {"sha": self.head, "ref": "fix/final"},
                  "base": {"sha": self.base, "ref": "develop"}}
            self.assertTrue(EVENT.required_locator(run, repo, pr))
            run["workflow_url"] = run["workflow_url"].replace("required_workflows", "workflows")
            self.assertFalse(EVENT.required_locator(run, repo, pr))

    def locator(self, index, *, pr=99, workflow=EVENT.REFRESH, **changes):
        created = self.now - dt.timedelta(seconds=1 + index * 600)
        return {
            "id": 10000 + index,
            "created_at": created.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "updated_at": created.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "path": f".github/workflows/{workflow}",
            "event": "workflow_dispatch",
            "display_title": f"Reconcile review PR #{pr} head {self.head}",
            "status": "completed",
            **changes,
        }

    @staticmethod
    def inventory_response(history, route):
        parsed = urlsplit(route)
        query = parse_qs(parsed.query)
        lower, upper = query["created"][0].split("..")
        workflow = parsed.path.split("/workflows/")[1].split("/")[0]
        selected = sorted(
            (run for run in history if lower <= run["created_at"] <= upper
             and run["path"] == f".github/workflows/{workflow}"),
            key=lambda run: run["id"], reverse=True,
        )
        page = int(query["page"][0])
        # Emulate the server's 1000-result ceiling, not an unlimited list.
        # Native filtered-search totals can be clipped independently of pages.
        return {"total_count": min(2500, len(selected)), "workflow_runs": selected[:1000][(page - 1) * 100:page * 100]}

    def inventory(self, history, transform=None):
        routes = []

        def api(route, payload=None):
            self.assertIsNone(payload)
            routes.append(route)
            response = self.inventory_response(history, route)
            return transform(route, response) if transform else response

        with patch.object(EVENT, "api", side_effect=api):
            result = EVENT.dispatch_inventory("repos/lightning-it/.github", self.now)
        self.assertLessEqual(len(routes), EVENT.DISPATCH_INVENTORY_REQUESTS)
        self.assertTrue(all(int(parse_qs(urlsplit(route).query)["page"][0]) <= 10 for route in routes))
        return result

    def test_dispatch_inventory_boundaries_and_full_seven_day_volume(self):
        for count in (0, 99, 100, 999, 1000, 1008):
            with self.subTest(count=count):
                history = [self.locator(i) for i in range(count)]
                self.assertEqual({run["id"] for run in history}, {run["id"] for run in self.inventory(history)})
        # Ten PRs each generating 1008 locators, including both consumers.
        history = [self.locator(i, id=10000 + pr * 1008 + i, pr=pr,
                                workflow=EVENT.REFRESH if pr % 2 else EVENT.HELPER)
                   for pr in range(10) for i in range(1008)]
        self.assertEqual(10080, len(self.inventory(history)))

    def test_clipped_parent_2500_retains_all_10080_disjoint_child_results(self):
        history = [self.locator(i, id=10000 + pr * 1008 + i, pr=pr)
                   for pr in range(10) for i in range(1008)]
        result = self.inventory(history)
        self.assertEqual(10080, len(result))
        self.assertEqual({run["id"] for run in history}, {run["id"] for run in result})

    def test_large_history_reaches_real_caller_and_keeps_per_pr_event_dedup(self):
        history = [self.locator(i) for i in range(1008)]
        history.append(self.locator(0, id=99999, pr=24, status="in_progress"))
        calls = self.reconcile(history=history, pr_count=3, delay=86400)
        self.assertEqual(["23", "25"], [payload["inputs"]["pr_number"] for _, payload in calls])
        self.assertTrue(all(route.endswith("/dispatches") for route, _ in calls))

    def test_unknown_post_later_native_inventory_suppresses_duplicate(self):
        history = [self.locator(i) for i in range(1008)]
        self.assertEqual(1, len(self.reconcile(history=history, uncertain=True)))
        accepted = self.locator(0, id=99999, pr=23, status="queued")
        self.assertEqual([], self.reconcile(history=[*history, accepted]))
        accepted["status"] = "completed"
        self.assertEqual([], self.reconcile(history=[*history, accepted]))
        accepted["updated_at"] = (self.now - dt.timedelta(minutes=11)).isoformat()
        self.assertEqual(1, len(self.reconcile(history=[*history, accepted])))
        # These are locators only; actual rerun CAS is covered by the real writer suite.

    def test_split_boundaries_are_disjoint_and_include_both_ttl_endpoints(self):
        middle = self.now - EVENT.TTL / 2
        stamps = (self.now - EVENT.TTL, middle, middle + dt.timedelta(seconds=1), self.now)
        history = [self.locator(i, created_at=stamps[i % 4].strftime("%Y-%m-%dT%H:%M:%SZ"))
                   for i in range(1008)]
        self.assertEqual(1008, len(self.inventory(history)))

    def test_incomplete_duplicate_or_racing_inventory_prevents_all_dispatches(self):
        history = [self.locator(i) for i in range(200)]

        def duplicate(route, response):
            if "page=2" in route and response["workflow_runs"]:
                response["workflow_runs"][0] = history[-1]
            return response

        def count_race(route, response):
            if "page=2" in route:
                response["total_count"] += 1
            return response

        def partial(route, response):
            response["workflow_runs"] = response["workflow_runs"][:-1]
            return response

        for transform in (duplicate, count_race, partial):
            with self.subTest(transform=transform.__name__), self.assertRaises(ValueError):
                self.reconcile(history=history, transform=transform)

    def test_split_count_race_and_cross_workflow_duplicate_fail_before_dispatch(self):
        history = [self.locator(i) for i in range(1008)]
        def split_race(route, response):
            if response["total_count"] == 1008:
                response["total_count"] = 1009
            return response
        with self.assertRaisesRegex(ValueError, "changed while splitting"):
            self.reconcile(history=history, transform=split_race)
        history = [self.locator(0), self.locator(0, workflow=EVENT.HELPER)]
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.reconcile(history=history)

    def test_long_running_locator_beyond_first_thousand_still_suppresses_dispatch(self):
        history = [self.locator(i) for i in range(1008)]
        history[0] = self.locator(0, pr=23, status="in_progress")
        self.assertEqual([], self.reconcile(history=history))

    def test_source_default_mirror_is_identical_when_present(self):
        mirror = ROOT / "default/scripts/review-event-reconcile.py"
        if mirror.exists():
            self.assertEqual((ROOT / "scripts/review-event-reconcile.py").read_bytes(), mirror.read_bytes())

    def test_saturated_second_and_budget_exhaustion_fail_closed(self):
        history = [self.locator(i, created_at=self.now.strftime("%Y-%m-%dT%H:%M:%SZ")) for i in range(1000)]
        with self.assertRaisesRegex(ValueError, "within one second"):
            self.reconcile(history=history)
        with patch.object(EVENT, "DISPATCH_INVENTORY_REQUESTS", 1):
            with self.assertRaisesRegex(ValueError, "budget exhausted"):
                self.reconcile(history=[self.locator(i) for i in range(1008)])

    def test_unbound_and_malformed_inventory_is_never_accepted(self):
        for field, value in (("id", True), ("event", "push"), ("created_at", "invalid"),
                             ("created_at", "2020-01-01T00:00:00Z"), ("path", "foreign")):
            def change(route, response):
                if response["workflow_runs"]:
                    response["workflow_runs"][0] = {**response["workflow_runs"][0], field: value}
                return response
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                self.reconcile(history=[self.locator(0)], transform=change)

    def test_all_rerun_writers_share_the_exact_head_lane(self):
        helper = (ROOT / ".github/workflows/current-revision-rerun.yml").read_text()
        self.assertIn("format('current-revision-{0}-head-{1}-check-current-revision-review', github.repository_id, inputs.expected_head)", helper)
        self.assertIn("cancel-in-progress: false\n  queue: max", helper)

    def test_required_verifier_accepts_bound_delayed_dispatch_and_rejects_forgery(self):
        workflow = (ROOT / ".github/workflows/supplementary-current-revision-required.yml").read_text()
        guard = workflow.split("<<'EVENT_RECOVERY'\n", 1)[1].split("\n          EVENT_RECOVERY", 1)[0]
        ordering = workflow.split('cat >"${ordering}" <<\'JQ\'\n', 1)[1].split("\n          JQ", 1)[0]
        key = f"li219-verifier-operation:v1:23:{self.base}:{self.head}:77"
        receipt = {"operation": key, "claim_run": "500", "claim_attempt": "1", "journal_commit": "1" * 40}
        claim = {"name": "Review event operation", "head_sha": self.head,
                 "external_id": key, "app": {"id": 15368, "slug": "github-actions"},
                 "status": "completed", "conclusion": "neutral", "started_at": "2026-10-05T18:00:02Z",
                 "output": {"title": "Verifier mutation consumed", "summary": json.dumps(receipt)}}
        run = {"id": 500, "run_attempt": 1, "event": "workflow_dispatch",
               "path": ".github/workflows/copilot-review-refresh.yml", "name": "Refresh Copilot review gate",
               "repository": {"full_name": "lightning-it/.github"},
               "head_repository": {"full_name": "lightning-it/.github"},
               "head_branch": "develop", "head_sha": "c" * 40,
               "actor": {"login": "github-actions[bot]"}, "triggering_actor": {"login": "github-actions[bot]"},
               "status": "completed", "conclusion": "success",
               "display_title": f"Reconcile review PR #23 head {self.head}",
               "created_at": "2026-10-05T17:55:00Z", "updated_at": "2026-10-05T18:00:07Z"}
        job = {"id": 55, "run_id": 500, "run_attempt": 1, "head_sha": "c" * 40,
               "name": "Refresh canonical Copilot review gate", "status": "completed", "conclusion": "success",
               "started_at": "2026-10-05T18:00:00Z", "completed_at": "2026-10-05T18:00:06Z",
               "steps": [{"name": "Materialize the protected operation claim", "number": 2,
                          "status": "completed", "conclusion": "success",
                          "started_at": "2026-10-05T18:00:00Z", "completed_at": "2026-10-05T18:00:01Z"},
                         {"name": "Rerun the canonical protected gate when needed", "number": 3,
                          "status": "completed", "conclusion": "success",
                          "started_at": "2026-10-05T18:00:01Z", "completed_at": "2026-10-05T18:00:05Z"}]}
        skipped = [{"id": 56 + index, "run_id": 500, "run_attempt": 1, "head_sha": "c" * 40,
                    "name": name, "status": "completed", "conclusion": "skipped", "runner_id": None, "steps": []}
                   for index, name in enumerate(("Locate protected review refresh", "Inactive legacy writer"))]
        full_jobs = [{"total_count": 3, "jobs": [*skipped, job]}]
        shell = r'''set -euo pipefail
gh() {
  case "$*" in
    *'/check-runs?'*) printf %s "${CLAIMS}" ;;
    *'/attempts/1/jobs?'*) printf %s "${JOBS}" ;;
    *'/actions/runs/500') printf %s "${REFRESH}" ;;
    *'/compare/'*) printf %s "${ANCESTRY}" ;;
    *'/git/ref/'*) printf %s "1111111111111111111111111111111111111111" ;;
    *'graphql'*) printf %s "${JOURNAL}" ;;
    *) return 99;;
  esac
}
''' + textwrap.dedent(guard) + "\nverify_event_recovery\n"
        record = {"schema": 1, "repository": "lightning-it/.github", "repository_id": "1112629689", "action": "rerun", "operation": key,
                  "claim_run": "500", "claim_attempt": "1", "source_sha": "c" * 40}
        def blob(value):
            encoded = json.dumps(value)
            return {"__typename": "Blob", "isTruncated": False, "byteSize": len(encoded), "text": encoded}
        journal = {"data": {"repository": {"nameWithOwner": "lightning-it/.github",
                   "source": {"__typename": "Commit", "oid": "1" * 40},
                   "manifest": blob({"schema": 1, "repository": "lightning-it/.github", "repository_id": "1112629689", "ref": "refs/heads/lit-review-operations"}),
                   "record": blob(record)}}}
        cases = [({}, 0), ({"CLAIMS": [{"check_runs": []}]}, 10),
                 ({"CLAIMS": [{"check_runs": [claim, claim]}]}, 1),
                 ({"REFRESH": {**run, "display_title": "foreign"}}, 1),
                 ({"REFRESH": {**run, "actor": {"login": "mallory"}}}, 1),
                 ({"ANCESTRY": {"status": "behind"}}, 1),
                 ({"JOBS": [{"total_count": 1, "jobs": [{**job, "head_sha": self.head}]}]}, 1)]
        import copy
        for index, field, value in ((0, "name", "Unknown sibling"), (1, "status", "in_progress"),
                                    (0, "conclusion", "failure"), (1, "runner_id", 99),
                                    (0, "run_id", 501), (1, "run_attempt", 2),
                                    (0, "head_sha", self.head), (1, "id", skipped[0]["id"])):
            forged = copy.deepcopy(full_jobs)
            forged[0]["jobs"][index][field] = value
            cases.append(({"JOBS": forged}, 1))
        cases.append(({"JOBS": [{"total_count": 3, "jobs": [job]}]}, 1))
        for field, value in (("record", blob({**record, "claim_run": "501"})),
                             ("record", blob({**record, "source_sha": "d" * 40})),
                             ("source", {"__typename": "Commit", "oid": "0" * 40}),
                             ("record", None)):
            forged = copy.deepcopy(journal)
            forged["data"]["repository"][field] = value
            cases.append(({"JOURNAL": forged}, 1))
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "native-recovery-ordering.jq").write_text(textwrap.dedent(ordering))
            for changes, expected in cases:
                data = {"CLAIMS": [{"check_runs": [claim]}], "REFRESH": run,
                        "JOBS": full_jobs, "ANCESTRY": {"status": "identical"}, "JOURNAL": journal, **changes}
                result = subprocess.run(["bash", "-c", shell], capture_output=True, text=True, check=False,
                                        env={**os.environ, "LI219_EVENT_MODE": "enabled", "GITHUB_REPOSITORY_ID": "1112629689", **{k: json.dumps(v) for k, v in data.items()},
                                             "RUNNER_TEMP": tmp, "owner_pr_number": "23", "EVENT_BASE": self.base,
                                             "EVENT_HEAD": self.head, "producer_run_id": "77",
                                             "REPOSITORY": "lightning-it/.github", "controller_branch": "develop",
                                             "controller_head": "c" * 40, "first_verifier_completed_at": "2026-10-05T17:59:00Z",
                                             "producer": json.dumps({"run_started_at": "2026-10-05T18:00:04Z"})})
                self.assertEqual(expected, result.returncode, result.stderr)

    def test_request_job_cannot_request_again_on_re_evaluation(self):
        workflow = (ROOT / ".github/workflows/copilot-review.yml").read_text()
        request = workflow.split("  request-current-revision-review:", 1)[1].split("    permissions:", 1)[0]
        self.assertIn("github.run_attempt == 1", request)
        self.assertIn("github.event.action == 'synchronize'", request)
        self.assertNotIn("github.event.action == 'edited'", request)
        self.assertNotIn("github.event.action == 'labeled'", request)
        verifier = contracts.CopilotReviewRefreshTests._review_script()
        self.assertNotIn("seq 1 40", verifier)
        self.assertNotIn("seq 1 20", verifier)

    def test_legacy_confirmed_request_records_uncertain_then_accepted_once_per_head(self):
        workflow = (ROOT / ".github/workflows/copilot-review.yml").read_text()
        fragment = workflow.split('          reviewer_is_requested() {\n', 1)[1].split('\n  verify-current-revision-policy:', 1)[0]
        fragment = textwrap.dedent('          reviewer_is_requested() {\n' + fragment)
        shell = r'''set -euo pipefail
sleep() { :; }
gh() {
  local arg body=''
  for arg in "$@"; do case "$arg" in body=*) body="${arg#body=}";; esac; done
  if [[ " $* " == *" --method POST "* ]]; then
    if [[ "$*" == *requested_reviewers* ]]; then
      printf '%s\n' "${EXPECTED_HEAD}" >>"${REQUESTS}"
      return 0
    fi
    jq -c --arg body "${body}" '.[0]+=[{user:{login:"github-actions[bot]"},body:$body}]' "${COMMENTS}" >"${COMMENTS}.next"
    mv "${COMMENTS}.next" "${COMMENTS}"
    return 42
  fi
  if [[ "$*" == *'/comments?'* ]]; then cat "${COMMENTS}"
  elif [[ "$*" == *requested_reviewers* ]]; then printf '%s' '{"users":[]}'
  elif [[ "$*" == *'/pulls/23' ]]; then
    jq -cn --arg head "${EXPECTED_HEAD}" --arg base "${EXPECTED_BASE}" '
      {number:23,state:"open",draft:false,user:{login:"litroc"},
       head:{sha:$head,repo:{full_name:"lightning-it/.github"}},
       base:{sha:$base,repo:{full_name:"lightning-it/.github"}}}'
  else return 99; fi
}
worker() (
  EXPECTED_HEAD="$1"
  marker="<!-- mlx90-copilot-request head=${EXPECTED_HEAD} -->"
''' + fragment + r'''
)
for head in "${FIRST_HEAD}" "${FIRST_HEAD}" "${SECOND_HEAD}" "${SECOND_HEAD}"; do
  worker "${head}" || true
done
'''
        with tempfile.TemporaryDirectory() as tmp:
            comments, requests = Path(tmp) / "comments", Path(tmp) / "requests"
            comments.write_text('[[]]')
            result = subprocess.run(["bash", "-c", shell], capture_output=True, text=True, check=False,
                                    env={**os.environ, "COMMENTS": str(comments), "REQUESTS": str(requests),
                                         "FIRST_HEAD": self.head, "SECOND_HEAD": "c" * 40,
                                         "EXPECTED_BASE": self.base, "PR_NUMBER": "23", "GITHUB_RUN_ID": "77",
                                         "REPOSITORY": "lightning-it/.github", "reviewer": "copilot-pull-request-reviewer[bot]",
                                         "requested_reviewers_url": "repos/lightning-it/.github/pulls/23/requested_reviewers"})
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual([self.head, "c" * 40], requests.read_text().splitlines())
            recorded = json.loads(comments.read_text())[0]
            self.assertEqual(4, len(recorded))
            for head in (self.head, 'c' * 40):
                self.assertEqual(1, sum(f'<!-- mlx90-copilot-request-uncertain head={head} -->' in item['body'] for item in recorded))
                self.assertEqual(1, sum(f'<!-- mlx90-copilot-request head={head} -->' in item['body'] for item in recorded))

    def test_missing_human_review_reaches_blocking_reservation_without_wait(self):
        workflow = (ROOT / ".github/workflows/supplementary-current-revision-required.yml").read_text()
        step = workflow.split("      - name: Await the exact protected producer run terminal state", 1)[1]
        script = textwrap.dedent(step.split("        run: |\n", 1)[1].split("\n      - name:", 1)[0])
        prefix = "gh() { printf '%s' '[{\"check_runs\":[]}]'; }\nsleep() { exit 99; }\n"
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "outputs"
            result = subprocess.run(["bash", "-c", prefix + script], capture_output=True, text=True, check=False,
                                    env={**os.environ, "LI219_EVENT_MODE": "enabled", "GITHUB_OUTPUT": str(output), "PR_AUTHOR_TYPE": "User",
                                         "REPOSITORY": "lightning-it/.github", "PR_NUMBER": "23",
                                         "EVENT_HEAD": self.head, "EVENT_BASE": self.base})
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual("producer_kind=copilot\nproducer_run_id=\n", output.read_text())
            self.assertNotIn("success", output.read_text())


if __name__ == "__main__":
    unittest.main()


class KeyedInventoryTests(unittest.TestCase):
    def test_short_native_inventories_stop_real_reconcile_before_dispatch(self):
        caller = ReviewEventTests()
        for fragment in ('actions/runs?event=', '/check-runs?', 'actions/runs?head_sha=', '/attempts/1/jobs?'):
            def corrupt(route, response):
                if fragment in route:
                    response['total_count'] += 1
                return response
            with self.subTest(fragment=fragment), self.assertRaisesRegex(ValueError, 'incomplete inventory'):
                caller.reconcile(neutral=True, inventory_transform=corrupt)
        self.assertEqual(1, len(caller.reconcile(neutral=True, inventory_transform=lambda route, response: response)))

    def test_keyed_inventory_counts_lengths_duplicates_and_bound(self):
        for key in ('workflow_runs', 'jobs', 'check_runs'):
            rows = [{'id': index + 1} for index in range(101)]
            good = [{'total_count': 101, key: rows[:100]}, {'total_count': 101, key: rows[100:]}]
            cases = [[{'total_count': value, key: []}] for value in (True, -1, '0', None, 1000)]
            cases += [[good[0], {'total_count': 102, key: rows[100:]}],
                      [{'total_count': 101, key: rows[:99]}],
                      [good[0], {'total_count': 101, key: []}],
                      [good[0], {'total_count': 101, key: rows[:1]}]]
            for responses in cases:
                with self.subTest(key=key, responses=len(responses)), patch.object(EVENT, 'api', side_effect=responses) as get:
                    with self.assertRaises(ValueError): EVENT.pages('repos/test/inventory', key)
                    self.assertLessEqual(get.call_count, 10)
            with patch.object(EVENT, 'api', side_effect=good):
                self.assertEqual(rows, EVENT.pages('repos/test/inventory', key))
