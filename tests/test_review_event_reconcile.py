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

    def reconcile(self, *, delay=180, missing=False, state="completed", drift=False, uncertain=False):
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
            f"{prefix}/pulls/23/reviews": [] if missing else [self.review()],
            f"{prefix}/pulls/23/reviews/17/comments": [],
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
                patch.dict(os.environ, GITHUB_REF="refs/heads/develop", GITHUB_REF_PROTECTED="true"):
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

    def test_missing_event_expiry_early_producer_and_stale_head_never_dispatch(self):
        for args in ({"missing": True}, {"delay": 7 * 86400 + 1},
                     {"state": "in_progress"}, {"drift": True}):
            self.assertEqual([], self.reconcile(**args))

    def test_ambiguous_dispatch_response_is_not_retried(self):
        self.assertEqual(1, len(self.reconcile(uncertain=True)))

    def test_lost_rerun_response_and_next_worker_send_only_one_rerun(self):
        shell = r'''set -euo pipefail
sleep() { :; }
revalidate_refresh_state() { :; }
validate_refresh_owner_run() { test "$2" = 77 && test "$3" = 23; }
assert_refresh_rerun_budget() { :; }
usable_current_review() { :; }
read_refresh_review_state() { printf '%s' '{"event_current":true,"incomplete":0,"unresolved":0}'; }
claim_review_operation() { [ ! -f "${CLAIM}" ] || return 1; touch "${CLAIM}"; }
gh() {
  if [[ " $* " == *" --method POST "* ]]; then
    printf 'RERUN\n' >>"${LOG}"
    return 42
  fi
  printf 'READ\n' >>"${LOG}"
  printf '%s' '{"id":77,"status":"completed","run_attempt":1}'
}
''' + contracts.CopilotReviewRefreshTests._rfn("rerun_owner_if_review_current") + "\nrerun_owner_if_review_current\nrerun_owner_if_review_current\n"
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "log"
            result = subprocess.run(["bash", "-c", shell], capture_output=True, text=True, check=False,
                                    env={**os.environ, "CLAIM": str(Path(tmp) / "claim"), "LOG": str(log),
                                         "REPOSITORY": "lightning-it/.github", "PR_NUMBER": "23", "owner_run_id": "77",
                                         "HEAD_SHA": self.head, "BASE_SHA": self.base,
                                         "refresh_expected_count": "0", "refresh_expected_snapshot": "null"})
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(1, log.read_text().splitlines().count("RERUN"))
            self.assertIn("response unresolved", result.stdout)

    def test_active_dispatch_is_deduplicated(self):
        run = {"path": ".github/workflows/copilot-review-refresh.yml",
               "event": "workflow_dispatch", "display_title": "bound", "status": "queued"}
        self.assertTrue(EVENT.recent_dispatch([run], EVENT.REFRESH, "bound"))
        self.assertFalse(EVENT.recent_dispatch([run], EVENT.REFRESH, "foreign"))

    def claim(self, mode):
        claim = contracts.CopilotReviewRefreshTests._rfn("claim_review_operation")
        self.assertEqual(claim, contracts.CopilotReviewRefreshTests._rerun_shell_function("claim_review_operation"))
        script = r'''set -euo pipefail
sleep() { :; }
timeout() { while [ "$1" != gh ]; do shift; done; "$@"; }
gh() {
  if [[ " $* " == *" --method POST "* ]]; then
    printf 'POST\n' >>"${LOG}"
    local arg summary=''
    for arg in "$@"; do
      case "$arg" in output\[summary\]=*) summary="${arg#*=}";; esac
    done
    if [ "${MODE}" != absent ]; then
      jq -cn --arg head "${HEAD}" --arg key "${KEY}" --arg summary "${summary}" '
        [{total_count:1,check_runs:[{id:99,name:"Review event operation",head_sha:$head,
          external_id:$key,app:{id:15368,slug:"github-actions"},
          status:"completed",conclusion:"neutral",
          output:{title:"Verifier mutation consumed",summary:$summary}}]}]' >"${STATE}"
    fi
    return 42
  fi
  if [[ " $* " == *"/actions/runs/77"* ]]; then
    local created
    created="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    [ "${MODE}" != expired ] || created=2000-01-01T00:00:00Z
    jq -cn --arg created "${created}" '{id:77,run_attempt:1,created_at:$created}'
    return
  fi
  cat "${STATE}"
}
''' + claim + r'''
first=0
claim_review_operation 77 "${HEAD}" "${BASE}" 23 || first=$?
second=0
claim_review_operation 77 "${HEAD}" "${BASE}" 23 || second=$?
printf '%s %s' "${first}" "${second}"
'''
        with tempfile.TemporaryDirectory() as tmp:
            state, log = Path(tmp) / "state", Path(tmp) / "log"
            state.write_text('[{"total_count":0,"check_runs":[]}]')
            result = subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                                    env={**os.environ, "STATE": str(state), "LOG": str(log),
                                         "MODE": mode, "HEAD": self.head, "BASE": self.base,
                                         "KEY": f"li219-verifier-operation:v1:23:{self.base}:{self.head}:77",
                                         "REPOSITORY": "lightning-it/.github",
                                         "GITHUB_RUN_ID": "500", "GITHUB_RUN_ATTEMPT": "1"}, check=False)
            return result, log.read_text() if log.exists() else ""

    def test_lost_claim_response_is_reconciled_and_duplicate_event_cannot_reclaim(self):
        result, log = self.claim("accepted")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("0 1", result.stdout)
        self.assertEqual("POST\n", log)

    def test_missing_claim_never_authorizes_rerun(self):
        result, _ = self.claim("absent")
        self.assertEqual("1 1", result.stdout)

    def test_expired_operation_never_writes_a_claim_or_reruns(self):
        result, log = self.claim("expired")
        self.assertEqual("1 1", result.stdout)
        self.assertEqual("", log)

    def test_all_rerun_writers_share_the_exact_head_lane(self):
        helper = (ROOT / ".github/workflows/current-revision-rerun.yml").read_text()
        self.assertIn("current-revision-${{ github.repository_id }}-head-${{ inputs.expected_head }}-check-current-revision-review", helper)
        self.assertIn("cancel-in-progress: false\n  queue: max", helper)

    def test_required_verifier_accepts_bound_delayed_dispatch_and_rejects_forgery(self):
        workflow = (ROOT / ".github/workflows/supplementary-current-revision-required.yml").read_text()
        guard = workflow.split("<<'EVENT_RECOVERY'\n", 1)[1].split("\n          EVENT_RECOVERY", 1)[0]
        ordering = workflow.split('cat >"${ordering}" <<\'JQ\'\n', 1)[1].split("\n          JQ", 1)[0]
        key = f"li219-verifier-operation:v1:23:{self.base}:{self.head}:77"
        receipt = {"operation": key, "claim_run": "500", "claim_attempt": "1"}
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
               "steps": [{"name": "Rerun the canonical protected gate when needed", "number": 2,
                          "status": "completed", "conclusion": "success",
                          "started_at": "2026-10-05T18:00:01Z", "completed_at": "2026-10-05T18:00:05Z"}]}
        shell = r'''set -euo pipefail
gh() {
  case "$*" in
    *'/check-runs?'*) printf %s "${CLAIMS}" ;;
    *'/attempts/1/jobs?'*) printf %s "${JOBS}" ;;
    *'/actions/runs/500') printf %s "${REFRESH}" ;;
    *'/compare/'*) printf %s "${ANCESTRY}" ;;
    *) return 99;;
  esac
}
''' + textwrap.dedent(guard) + "\nverify_event_recovery\n"
        cases = [({}, 0), ({"CLAIMS": [{"check_runs": []}]}, 10),
                 ({"CLAIMS": [{"check_runs": [claim, claim]}]}, 1),
                 ({"REFRESH": {**run, "display_title": "foreign"}}, 1),
                 ({"REFRESH": {**run, "actor": {"login": "mallory"}}}, 1),
                 ({"ANCESTRY": {"status": "behind"}}, 1),
                 ({"JOBS": [{"total_count": 1, "jobs": [{**job, "head_sha": self.head}]}]}, 1)]
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "native-recovery-ordering.jq").write_text(textwrap.dedent(ordering))
            for changes, expected in cases:
                data = {"CLAIMS": [{"check_runs": [claim]}], "REFRESH": run,
                        "JOBS": [{"total_count": 1, "jobs": [job]}], "ANCESTRY": {"status": "identical"}, **changes}
                result = subprocess.run(["bash", "-c", shell], capture_output=True, text=True, check=False,
                                        env={**os.environ, **{k: json.dumps(v) for k, v in data.items()},
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
        verifier = contracts.CopilotReviewRefreshTests._review_script()
        self.assertNotIn("seq 1 40", verifier)
        self.assertNotIn("seq 1 20", verifier)

    def test_missing_human_review_reaches_blocking_reservation_without_wait(self):
        workflow = (ROOT / ".github/workflows/supplementary-current-revision-required.yml").read_text()
        step = workflow.split("      - name: Await the exact protected producer run terminal state", 1)[1]
        script = textwrap.dedent(step.split("        run: |\n", 1)[1].split("\n      - name:", 1)[0])
        prefix = "gh() { printf '%s' '[{\"check_runs\":[]}]'; }\nsleep() { exit 99; }\n"
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "outputs"
            result = subprocess.run(["bash", "-c", prefix + script], capture_output=True, text=True, check=False,
                                    env={**os.environ, "GITHUB_OUTPUT": str(output), "PR_AUTHOR_TYPE": "User",
                                         "REPOSITORY": "lightning-it/.github", "PR_NUMBER": "23",
                                         "EVENT_HEAD": self.head, "EVENT_BASE": self.base})
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual("producer_kind=copilot\nproducer_run_id=\n", output.read_text())
            self.assertNotIn("success", output.read_text())


if __name__ == "__main__":
    unittest.main()
