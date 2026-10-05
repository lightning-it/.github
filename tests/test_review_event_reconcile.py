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

from tests import test_copilot_review_refresh as contracts


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("review_event", ROOT / "scripts/review-event-reconcile.py")
EVENT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EVENT)


class ReviewEventTests(unittest.TestCase):
    head, base = "b" * 40, "a" * 40
    now = dt.datetime(2026, 10, 5, 18, tzinfo=dt.timezone.utc)

    def review(self, **changes):
        return {"id": 17, "commit_id": self.head, "body": "Review complete.",
                "user": {"login": "copilot-pull-request-reviewer[bot]"},
                "state": "COMMENTED", **changes}

    def test_review_content_rejects_stale_empty_quota_and_foreign(self):
        self.assertTrue(EVENT.clean_review(self.review(), [], self.head))
        for review in (self.review(commit_id=self.base), self.review(body=" "),
                       self.review(body="Quota\nexceeded"), self.review(state="DISMISSED"),
                       self.review(user={"login": "litroc"})):
            self.assertFalse(EVENT.clean_review(review, [], self.head))
        self.assertFalse(EVENT.clean_review(self.review(), [{"body": "Suppressed comments"}], self.head))
        self.assertTrue(EVENT.clean_review(self.review(body=""), [{"body": "Reviewed files"}], self.head))

    def reconcile(self, *, delay=180, missing=False, state="completed", drift=False, uncertain=False, review_body="Review complete.", comment_body=None):
        prefix = "repos/lightning-it/.github"
        pr = {"id": 23, "number": 23, "draft": False, "state": "open",
              "user": {"login": "litroc", "type": "User"},
              "head": {"sha": self.head, "ref": "fix/final", "repo": {"full_name": "lightning-it/.github"}},
              "base": {"sha": self.base, "ref": "develop"}}
        run = {"id": 77, "path": EVENT.PRODUCER, "head_sha": self.head,
               "head_branch": "fix/final", "pull_requests": [{"number": 23}],
               "status": state, "created_at": (self.now - dt.timedelta(seconds=delay)).isoformat()}
        inventories = {

            f"{prefix}/pulls?state=open": [pr],
            f"{prefix}/actions/runs?event=pull_request_target&head_sha={self.head}": [run],
            f"{prefix}/commits/{self.head}/check-runs?filter=all": [],
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
            if route == prefix:
                return {"default_branch": "develop"}
            if route == f"{prefix}/pulls/23":
                return {**pr, "head": {**pr["head"], "sha": self.base}} if drift else pr
            raise AssertionError(route)

        with patch.object(EVENT, "api", side_effect=api), \
                patch.object(EVENT, "pages", side_effect=lambda route, key=None: [] if "/actions/workflows/" in route else inventories[route]), \
                patch.dict(os.environ, LI219_EVENT_MODE="enabled", GITHUB_REF="refs/heads/develop", GITHUB_REF_PROTECTED="true"):
            if uncertain:
                with self.assertRaises(TimeoutError):
                    EVENT.reconcile("lightning-it/.github", self.now)
            else:
                EVENT.reconcile("lightning-it/.github", self.now)
        return mutations

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

    def test_legacy_confirmed_request_records_marker_once_per_head(self):
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
            self.assertEqual(2, len(json.loads(comments.read_text())[0]))

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
