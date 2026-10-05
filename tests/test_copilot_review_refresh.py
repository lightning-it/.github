import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]
COPILOT_WORKFLOW = ROOT / ".github/workflows/copilot-review.yml"
REFRESH_WORKFLOW = ROOT / ".github/workflows/copilot-review-refresh.yml"
RERUN_WORKFLOW = ROOT / ".github/workflows/current-revision-rerun.yml"
TEST_TOOL_PATH = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
FAKE_TIMEOUT_PASSTHROUGH = r'''timeout() {
  while [ "${1:-}" != gh ]; do
    [ "$#" -gt 0 ] || return 98
    shift
  done
  "$@"
}'''


class CopilotReviewRefreshTests(unittest.TestCase):
    def test_producer_step_binds_event_tuple_and_unpredictable_run_id(self):
        self.assertIn(
            "name: 'Event binding #${{ github.event.pull_request.number }}:"
            "${{ github.event.pull_request.base.sha }}:"
            "${{ github.event.pull_request.head.sha }}:"
            "${{ github.run_id }}'",
            COPILOT_WORKFLOW.read_text(encoding="utf-8"),
        )
    def _run_bash(self, script, env):
        return subprocess.run([self._test_tool("bash"), "-c", script],
            text=True, capture_output=True, check=False,
            env={"PATH": TEST_TOOL_PATH, **env})
    def test_serialization(self):
        group = (
            "current-revision-${{ github.repository_id }}-head-"
            "${{ github.event.pull_request.head.sha }}-"
            "check-current-revision-review"
        )
        block = f"group: {group}\n  cancel-in-progress: false\n  queue: max"
        workflow = COPILOT_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn(block, workflow)
        refresh = REFRESH_WORKFLOW.read_text(encoding="utf-8")
        expression = refresh.split("group: >-", 1)[1].split("cancel-in-progress", 1)[0]
        for value in (
            "format('current-revision-{0}-head-{1}-check-current-revision-review'",
            "github.event.pull_request.head.sha",
            "format('current-revision-quarantine-{0}'",
            "github.run_id",
            "cancel-in-progress: false",
            "queue: max",
        ):
            self.assertIn(value, expression if value.startswith(("format", "github")) else refresh)
        def lane(event, actor, login, association="NONE", sender=None, action="edited", run=1):
            trusted = event in ("pull_request_review", "pull_request_review_comment") and ((actor in ("Copilot", "copilot-pull-request-reviewer", "copilot-pull-request-reviewer[bot]") and login == "copilot-pull-request-reviewer[bot]") or actor == login == "litroc" or (association in ("COLLABORATOR", "MEMBER", "OWNER") and (sender or actor) == actor and (action in ("dismissed", "deleted") or login == actor)))
            return ("current-revision-1-head-" + "c" * 40
                    + "-check-current-revision-review" if trusted
                    else f"current-revision-quarantine-{run}")
        for event in ("pull_request_review", "pull_request_review_comment"):
            for args in (("Copilot", "copilot-pull-request-reviewer[bot]"), ("litroc", "litroc"), ("maintainer", "maintainer", "MEMBER", "maintainer")):
                self.assertEqual(
                    "current-revision-1-head-" + "c" * 40
                    + "-check-current-revision-review",
                    lane(event, *args),
                )
            self.assertNotEqual(lane(event, "mallory", "other", run=8), lane(event, "mallory", "other", run=9))
    @staticmethod
    def _guards():
        workflow = COPILOT_WORKFLOW.read_text(encoding="utf-8")
        marker = "          cat >\"${owner_guard}\" <<'PRODUCER_OWNER_GUARD'\n"
        guards = []
        cursor = 0
        while marker in workflow[cursor:]:
            start = workflow.index(marker, cursor) + len(marker)
            end = workflow.index("\n          PRODUCER_OWNER_GUARD", start)
            guards.append(workflow[start:end])
            cursor = end + 1
        if len(guards) != 1: raise AssertionError("want one anchored owner guard")
        if workflow.count("*materialize-producer-owner-guard") != 1:
            raise AssertionError("dispatch must reuse anchored guard")
        return [guards[0], guards[0], CopilotReviewRefreshTests._refresh_guard()]
    @classmethod
    def _guard(cls):
        return cls._guards()[0]
    @staticmethod
    def _refresh_guard():
        workflow = REFRESH_WORKFLOW.read_text(encoding="utf-8")
        marker = "          cat >\"${owner_guard}\" <<'PRODUCER_OWNER_GUARD'\n"
        start = workflow.index(marker) + len(marker)
        end = workflow.index("\n          PRODUCER_OWNER_GUARD", start)
        return workflow[start:end]
    def _run_guard(self, *, runs, jobs, guard=None, first_jobs=None,
        event_ref="feature/li179", fpulls=None, branch_pulls=None,
        runs2=None, cond=False, mode="copilot",
        event_base=None, live_base=None,
        add_req=True):
        njobs, ojobs = {}, {}
        for run_id, records in jobs.items():
            njobs[run_id] = list(records)
            if add_req and not any(record.get("name") ==
                    "Request Copilot review for current revision" for record in records):
                req_attempt = int(records[0].get("run_attempt", 1))
                njobs[run_id].append(self._req(run_id, req_attempt))
            orecords = (list(first_jobs[run_id]) if first_jobs
                is not None and run_id in first_jobs else
                [dict(record, run_attempt=1) for record in records])
            if add_req and not any(record.get("name") ==
                    "Request Copilot review for current revision" for record in orecords):
                orecords.append(self._req(run_id, 1))
            ojobs[run_id] = orecords
        bash = self._test_tool("bash")
        jq = self._test_tool("jq")
        job_cases = "".join(f'{i}) [ "${{run_attempt}}" -eq 1 ] && printf %s '
            f'"${{JOBS_{i}_ATTEMPT_1}}" || printf %s "${{JOBS_{i}}}" ;;'
            for i in sorted(njobs))
        pull_cases = "".join(f'{i}) printf %s "${{PULL_{i}}}" ;;'
                             for i in sorted(fpulls or {}))
        script = r'''set -euo pipefail
sleep() { :; }
gh() {
  local argument endpoint='' reads=0 run_id run_attempt
  for argument in "$@"; do case "${argument}" in repos/*) endpoint="${argument}";; esac; done
  if [[ "${endpoint}" == *'/actions/runs?'* ]]; then
    [ ! -f "${COUNTER_FILE}" ] || reads="$(cat "${COUNTER_FILE}")"
    printf %s "$((reads + 1))" >"${COUNTER_FILE}"
    [ "${reads}" -eq 0 ] && printf %s "${RUN_PAGES}" || printf %s "${RUN_PAGES_SECOND}"
  elif [[ "${endpoint}" =~ /actions/runs/([0-9]+)/attempts/([0-9]+)/jobs ]]; then
    run_id="${BASH_REMATCH[1]}"; run_attempt="${BASH_REMATCH[2]}"
    case "${run_id}" in __JOB_CASES__ *) return 92;; esac
  elif [[ "${endpoint}" =~ /pulls$ ]]; then
    [[ " $* " == *" state=open "* ]] || return 96
    jq -c '[.[] | map(select(.state == "open"))]' <<<"${BRANCH_PULL_PAGES}"
  elif [[ "${endpoint}" =~ /pulls/([0-9]+)$ ]]; then
    case "${BASH_REMATCH[1]}" in __PULL_CASES__ *) return 94;; esac
  else return 93; fi
}
'''.replace("__JOB_CASES__", job_cases).replace("__PULL_CASES__", pull_cases)
        script += guard or self._guard()
        script += (
            '\nif owner="$(eo)"; then printf %s "${owner}"; else exit 71; fi\n'
            if cond
            else "\neo\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            current_pull = {
                "number": 2334, "state": "open",
                "base": {"sha": "b" * 40,
                         "repo": {"full_name": "lightning-it/shared-assets-lit"}},
                "head": {"ref": event_ref, "sha": "c" * 40,
                         "repo": {"full_name": "lightning-it/shared-assets-lit"}},
            }
            env = {
                "PATH": str(Path(jq).parent) + ":" + TEST_TOOL_PATH,
                "REPOSITORY": "lightning-it/shared-assets-lit", "PR_NUMBER": "2334",
                "EVENT_BASE": event_base or "b" * 40,
                "LIVE_BASE": live_base or "b" * 40,
                "EVENT_HEAD": "c" * 40,
                "EVENT_HEAD_REF": event_ref, "PRODUCER_OWNER_MODE": mode,
                "COUNTER_FILE": str(Path(tmp) / "reads"),
                "RUN_PAGES": json.dumps([{"workflow_runs": runs}]),
                "RUN_PAGES_SECOND": json.dumps([{"workflow_runs": runs2 or runs}]),
                "BRANCH_PULL_PAGES": json.dumps([
                    branch_pulls if branch_pulls is not None else [current_pull]
                ])}
            def pages(records):
                return json.dumps([{"jobs": [record]} for record in records]
                                  or [{"jobs": []}])
            env.update({f"JOBS_{i}": pages(v) for i, v in njobs.items()})
            env.update({f"PULL_{i}": json.dumps(v)
                                for i, v in (fpulls or {}).items()})
            env.update({f"JOBS_{i}_ATTEMPT_1": pages(v)
                                for i, v in ojobs.items()})
            return subprocess.run([bash, "-c", script], env=env,
                text=True, capture_output=True, check=False)
    def _owner(self, want, **kwargs):
        res = self._run_guard(**kwargs)
        if want is None:
            self.assertNotEqual(0, res.returncode)
        else:
            self.assertEqual(0, res.returncode, res.stderr)
            self.assertEqual(want, res.stdout)
    @staticmethod
    def _run(run_id, attempt=1):
        repo = "lightning-it/shared-assets-lit"
        return {"id": run_id, "event": "pull_request_target",
            "path": ".github/workflows/copilot-review.yml",
            "name": "Current revision review gate", "run_attempt": attempt,
            "status": "in_progress", "conclusion": None,
            "head_branch": "feature/li179", "head_sha": "c" * 40,
            "repository": {"full_name": repo}, "head_repository": {"full_name": repo},
            "pull_requests": [{"number": 2334, "base": {"sha": "b" * 40},
                "head": {"sha": "c" * 40, "ref": "feature/li179"}}]}
    @staticmethod
    def _job(run_id, attempt=1, *, status="in_progress", conclusion=None):
        return {"id": run_id * 10, "name": "Verify current revision policy",
            "run_id": run_id, "run_attempt": attempt, "head_sha": "c" * 40,
            "steps": [{"name": "Event binding #2334:" + "b" * 40
                       + ":" + "c" * 40 + ":" + str(run_id)}],
            "status": status, "conclusion": conclusion}
    @staticmethod
    def _req(run_id, attempt=1, *, status="completed", conclusion="success"):
        return {
            "id": run_id * 10 + 1,
            "name": "Request Copilot review for current revision",
            "run_id": run_id, "run_attempt": attempt, "head_sha": "c" * 40,
            "status": status, "conclusion": conclusion}
    def test_owner_first(self):
        self._owner("101", runs=[self._run(101), self._run(102)],
                           jobs={101: [self._job(101)], 102: [self._job(102)]})
        workflow = COPILOT_WORKFLOW.read_text(encoding="utf-8")
        publish = workflow.split("      - name: Publish bound neutral result\n", 1)[1]
        dispatch = workflow.split("\n  request-protected-verifier-reevaluation:", 1)[1]
        self.assertIn("if: steps.producer-owner.outputs.owner == 'true'", publish)
        self.assertIn("needs['verify-current-revision-policy'].outputs.producer_owner "
                      "== 'true'", dispatch)
        self.assertIn("needs['verify-current-revision-policy'].outputs.owns_result "
                      "== 'true'", dispatch)

    def test_publisher_retains_permanent_foreign_owner_read_only(self):
        workflow = COPILOT_WORKFLOW.read_text(encoding="utf-8")
        policy = workflow.split("\n  verify-current-revision-policy:", 1)[1].split(
            "\n  request-protected-verifier-reevaluation:", 1
        )[0]
        publisher = policy.split("      - name: Publish bound neutral result\n", 1)[1]
        reuse = publisher.split("            reuse_permanent_owner() {\n", 1)[1].split(
            "\n            }\n            named=", 1
        )[0]
        self.assertIn("outputs.owns_result", workflow)
        self.assertIn("owner_snapshot=", reuse)
        self.assertIn("attempts/${owner_attempt}/jobs?filter=all&per_page=100", reuse)
        self.assertIn(".run_attempt == $owner_attempt", reuse)
        self.assertIn(".pull_requests[0].number == $owner_pr", reuse)
        self.assertIn("$actual.pull_request_number == $owner_pr", reuse)
        self.assertIn(".status == \"completed\" and .conclusion == \"success\"", reuse)
        self.assertIn("(.steps | type == \"array\")", reuse)
        self.assertIn("map(.id) | unique | length", reuse)
        self.assertIn("verify-current-copilot-review.sh", reuse)
        self.assertIn("$check.output.title == $title", reuse)
        self.assertIn("ro || return 1", reuse)
        self.assertIn("read_named_checks", reuse)
        self.assertNotIn("--method POST", reuse)
        self.assertNotIn("api_patch_bound", reuse)
        self.assertIn("printf 'reused:%s'", reuse)
        self.assertIn("echo 'owns_result=false'", publisher)
        self.assertIn("echo 'owns_result=true'", publisher)

    def test_permanent_owner_branch_executes_read_only_and_records_loser(self):
        base, head, owner, current = "b" * 40, "c" * 40, 100, 200
        repository = "lightning-it/.github"
        server = "https://github.example"
        owner_evidence = {
            "schema": 4,
            "base_sha": base,
            "head_sha": head,
            "controller_sha": "d" * 40,
            "pull_request_number": 779,
            "producer_run_id": owner,
            "review_path": "applicable Copilot or governed automation exemption",
            "run_url": f"{server}/{repository}/actions/runs/{owner}",
        }
        current_evidence = {
            **owner_evidence,
            "pull_request_number": 780,
            "producer_run_id": current,
            "run_url": f"{server}/{repository}/actions/runs/{current}",
        }
        check = {
            "id": 42,
            "name": "Current revision review",
            "head_sha": head,
            "status": "completed",
            "conclusion": "success",
            "external_id": (
                f"mlx90-current-revision:copilot:v6:779:{owner}:{base}:{head}"
            ),
            "details_url": f"{server}/{repository}/runs/42",
            "output": {
                "title": "Current revision review passed",
                "summary": json.dumps(owner_evidence, separators=(",", ":")),
            },
            "app": {"id": 15368, "slug": "github-actions"},
        }
        owner_run = {
            "id": owner,
            "run_attempt": 1,
            "event": "pull_request_target",
            "path": ".github/workflows/copilot-review.yml",
            "name": "Current revision review gate",
            "repository": {"full_name": repository},
            "head_repository": {"full_name": repository},
            "head_sha": head,
            "head_branch": "fix/permanent-owner",
            "status": "completed",
            "conclusion": "success",
            "pull_requests": [{
                "number": 779,
                "base": {"sha": base, "repo": {
                    "url": f"https://api.github.com/repos/{repository}"}},
                "head": {"sha": head, "ref": "fix/permanent-owner", "repo": {
                    "url": f"https://api.github.com/repos/{repository}"}},
            }],
        }
        request_job = {
            "id": 1001,
            "name": "Request Copilot review for current revision",
            "run_id": owner,
            "run_attempt": 1,
            "head_sha": head,
            "status": "completed",
            "conclusion": "success",
            "steps": [{"name": "Request review", "status": "completed",
                       "conclusion": "success"}],
        }
        policy_job = {
            "id": 1002,
            "name": "Verify current revision policy",
            "run_id": owner,
            "run_attempt": 1,
            "runner_id": 7,
            "head_sha": head,
            "status": "completed",
            "conclusion": "success",
            "steps": [
                {"name": "Verify current Copilot review and resolved findings",
                 "status": "completed", "conclusion": "success"},
                {"name": "Publish bound neutral result",
                 "status": "completed", "conclusion": "success"},
            ],
        }
        good_pages = [{"total_count": 1, "check_runs": [check]}]
        good_jobs = [{"total_count": 2, "jobs": [request_job, policy_job]}]
        functions = self._pub_nested("read_named_checks") + self._pub_nested(
            "reuse_permanent_owner"
        ) + self._pub("record_publication_ownership")

        def execute(*, first=good_pages, second=good_pages,
                    run=owner_run, jobs=good_jobs):
            with tempfile.TemporaryDirectory() as tmp:
                verification = Path(tmp) / "verify-current-copilot-review.sh"
                verification.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
                output = Path(tmp) / "output"
                mutation = Path(tmp) / "mutation"
                counter = Path(tmp) / "checks"
                script = r'''set -euo pipefail
api_read() {
  local endpoint="${*: -1}" reads=0
  case "${endpoint}" in
    *'/check-runs?'*)
      [ ! -f "${CHECK_COUNTER}" ] || reads="$(cat "${CHECK_COUNTER}")"
      printf %s "$((reads + 1))" >"${CHECK_COUNTER}"
      [ "${reads}" -eq 0 ] && printf %s "${CHECKS_FIRST}" || printf %s "${CHECKS_SECOND}"
      ;;
    */attempts/1/jobs*|*/attempts/2/jobs*) printf %s "${OWNER_JOBS}" ;;
    */actions/runs/*) printf %s "${OWNER_RUN}" ;;
    *) return 92 ;;
  esac
}
ro() { :; }
gh() { printf mutation >"${MUTATION}"; return 99; }
''' + functions + r'''
named="$(read_named_checks)"
result="$(reuse_permanent_owner)"
record_publication_ownership "${result}"
printf %s "${result}"
'''
                result = self._run_bash(script, {
                    "CHECK_COUNTER": str(counter),
                    "CHECKS_FIRST": json.dumps(first, separators=(",", ":")),
                    "CHECKS_SECOND": json.dumps(second, separators=(",", ":")),
                    "EVENT_BASE": base,
                    "EVENT_HEAD": head,
                    "EVENT_HEAD_REF": "fix/permanent-owner",
                    "GITHUB_API_URL": "https://api.github.com",
                    "GITHUB_OUTPUT": str(output),
                    "GITHUB_RUN_ID": str(current),
                    "GITHUB_SERVER_URL": server,
                    "MUTATION": str(mutation),
                    "OWNER_JOBS": json.dumps(jobs, separators=(",", ":")),
                    "OWNER_RUN": json.dumps(run, separators=(",", ":")),
                    "PR_NUMBER": "780",
                    "REPOSITORY": repository,
                    "RUNNER_TEMP": tmp,
                    "TRUSTED_KIND": "none",
                    "check_name": "Current revision review",
                    "evidence": json.dumps(current_evidence, separators=(",", ":")),
                    "named": json.dumps([check], separators=(",", ":")),
                    "result_title": "Current revision review passed",
                })
                return (
                    result,
                    output.read_text(encoding="utf-8") if output.exists() else "",
                    mutation.exists(),
                )

        accepted, ownership, mutated = execute()
        self.assertEqual(0, accepted.returncode, accepted.stderr)
        self.assertEqual("reused:42", accepted.stdout)
        self.assertEqual("owns_result=false\n", ownership)
        self.assertFalse(mutated)

        owner_run_attempt2 = json.loads(json.dumps(owner_run))
        owner_run_attempt2["run_attempt"] = 2
        good_jobs_attempt2 = json.loads(json.dumps(good_jobs))
        for job in good_jobs_attempt2[0]["jobs"]:
            job["run_attempt"] = 2
        accepted, ownership, mutated = execute(
            run=owner_run_attempt2, jobs=good_jobs_attempt2
        )
        self.assertEqual(0, accepted.returncode, accepted.stderr)
        self.assertEqual("reused:42", accepted.stdout)
        self.assertEqual("owns_result=false\n", ownership)
        self.assertFalse(mutated)

        drifted = json.loads(json.dumps(good_pages))
        drifted[0]["check_runs"][0]["output"]["title"] = "drifted"
        malformed_jobs = json.loads(json.dumps(good_jobs))
        del malformed_jobs[0]["jobs"][1]["steps"]
        mismatched_jobs = json.loads(json.dumps(good_jobs))
        mismatched_jobs[0]["jobs"][1]["run_attempt"] = 2
        wrong_owner_pr = json.loads(json.dumps(owner_run))
        wrong_owner_pr["pull_requests"][0]["number"] = 780
        wrong_external_id = json.loads(json.dumps(good_pages))
        wrong_external_id[0]["check_runs"][0]["external_id"] = (
            f"mlx90-current-revision:copilot:v6:780:{owner}:{base}:{head}"
        )
        bad_title = json.loads(json.dumps(good_pages))
        bad_title[0]["check_runs"][0]["output"]["title"] = "wrong"
        for kwargs in (
            {"second": drifted},
            {"jobs": malformed_jobs},
            {"jobs": mismatched_jobs},
            {"run": wrong_owner_pr},
            {"first": wrong_external_id, "second": wrong_external_id},
            {"first": bad_title, "second": bad_title},
        ):
            with self.subTest(kwargs=tuple(kwargs)):
                rejected, ownership, mutated = execute(**kwargs)
                self.assertNotEqual(0, rejected.returncode)
                self.assertEqual("", ownership)
                self.assertFalse(mutated)

        for invalid_attempt in (None, "2", 0, 1.5, 3):
            malformed_run = {**owner_run, "run_attempt": invalid_attempt}
            with self.subTest(invalid_attempt=invalid_attempt):
                rejected, ownership, mutated = execute(run=malformed_run)
                self.assertNotEqual(0, rejected.returncode)
                self.assertEqual("", ownership)
                self.assertFalse(mutated)

    def test_publisher_rechecks_complete_zero_inventory_before_create(self):
        workflow = COPILOT_WORKFLOW.read_text(encoding="utf-8")
        publisher = workflow.split("      - name: Publish bound neutral result\n", 1)[1]
        create = publisher.index(
            'if ! created="$(gh api --method POST "repos/${REPOSITORY}/check-runs"'
        )
        before_create = publisher[:create]
        after_create = publisher[create:]
        self.assertIn("total_count == ($inventory | length)", publisher)
        self.assertIn("map(.id) | unique | length", publisher)
        self.assertGreaterEqual(before_create.count("read_named_checks"), 4)
        self.assertIn('owner_snapshot="$(read_named_checks)"', before_create)
        self.assertIn('named="$(read_named_checks)"', before_create)
        self.assertIn('test "$(jq -cS . <<<"${named}")" =', before_create)
        self.assertIn('named="$(read_named_checks)"', after_create)
        self.assertIn('test "$(jq \'length\' <<<"${named}")" -eq 1', after_create)
        self.assertIn('test "$(jq -er \'.[0].external_id\'', after_create)
    def test_owner_queued(self):
        owner = self._run(101)
        queued = self._run(102)
        queued.update(status="queued", conclusion=None)
        o_jobs = [self._job(101), self._req(101)]
        started = self._run(102)
        q_first = self._run(100)
        q_first.update(status="queued", conclusion=None)
        s_jobs = [self._job(102), self._req(102)]
        wrong_job = dict(self._job(102), run_id=999)
        cases = (
            ([owner, queued], {101: o_jobs, 102: []}, "101"),
            ([owner, started], {101: o_jobs, 102: s_jobs}, "101"),
            ([owner, started], {101: o_jobs, 102: []}, None),
            ([owner, queued], {101: o_jobs, 102: [wrong_job]}, None),
            ([q_first, owner], {100: [], 101: o_jobs}, None),
        )
        for runs, jobs, want in cases:
            self._owner(
                want, runs=runs, jobs=jobs,
                add_req=False,
            )
    def test_owner_attempts(self):
        self._owner(
            "101",
            runs=[self._run(101), self._run(102, attempt=2)],
            jobs={
                101: [self._job(101)],
                102: [self._job(102, attempt=2)],
            },
        )
        for runs, records in (
            ([self._run(101)] * 2, [self._job(101)]),
            ([self._run(101)], [self._job(101)] * 2),
            ([self._run(101)], [self._job(101), *[self._req(101)] * 2]),
        ):
            self._owner(None, runs=runs, jobs={101: records})
        skip_req = self._req(101)
        skip_req.update(status="completed", conclusion="skipped")
        self._owner(
            "101",
            runs=[self._run(101)],
            jobs={101: [self._job(101), skip_req]},
            mode="deterministic",
        )
    def test_job_ids(self):
        cases = (
            (self._run(101), [self._job(101), dict(self._req(101), id=1010)], None),
            (self._run(101, attempt=2), [self._job(101, 2), self._req(101, 2)],
             {101: [self._req(101), dict(self._job(101), id=1011)]}),
        )
        for guard in self._guards():
            for run, jobs, attempt_one in cases:
                self._owner(
                    None,
                    guard=guard, runs=[run], jobs={101: jobs}, first_jobs=attempt_one,
                    add_req=False,
                    cond=True,
                )
    def test_job_tuples(self):
        for guard in self._guards():
            good=lambda a:[self._job(101,a),self._req(101,a)]
            for c in ({"run_id":999},{"run_attempt":9},{"head_sha":"d"*40}):
                for orig in (False,True):
                    a=1 if orig else 2
                    m=[*good(a),dict(self._job(101,a),id=2020,**c)]
                    self._owner(None,guard=guard,runs=[self._run(101,2)],
                        jobs={101:good(2) if orig else m},
                        first_jobs={101:m if orig else good(1)},
                        add_req=False,cond=True)
    def test_owner_attempt3(self):
        guards = self._guards()
        self.assertEqual(3, len(guards))
        for index, guard in enumerate(guards):
            with self.subTest(guard=index):
                self._owner(None, guard=guard,
                    runs=[self._run(101, attempt=3), self._run(102)],
                    jobs={101: [self._job(101, attempt=3)], 102: [self._job(102)]},
                    first_jobs={101: [self._job(101), self._req(101)]},
                    cond=True)
    def test_pr_tuple(self):
        original = self._run(101)
        tuple = original["pull_requests"][0]
        bad_runs = []
        for field in (
            "event",
            "path",
            "name",
            "head_branch",
            "head_sha",
            "repository",
            "head_repository",
        ):
            malformed = json.loads(json.dumps(original))
            malformed[field] = None
            bad_runs.append(malformed)
        for pull_requests in (None, [tuple, tuple],
                              [{**tuple, "number": None}],
                              [{**tuple, "base": {"sha": None}}],
                              [{**tuple, "head": {"sha": None,
                                                         "ref": None}}]):
            malformed = json.loads(json.dumps(original))
            malformed["pull_requests"] = pull_requests
            bad_runs.append(malformed)
        missing = json.loads(json.dumps(original))
        del missing["pull_requests"]
        bad_runs.append(missing)
        for key, value in (
            ("number", 123.5),
            ("number", 999),
            ("base_sha", "z" * 40),
            ("head_sha", "z" * 40),
            ("head_mismatch", "d" * 40),
            ("ref_mismatch", "feature/renamed"),
        ):
            malformed = json.loads(json.dumps(original))
            association = malformed["pull_requests"][0]
            target = (association if key == "number" else
                      association["base"] if key == "base_sha" else
                      association["head"])
            target[{"number": "number", "base_sha": "sha",
                    "ref_mismatch": "ref"}.get(key, "sha")] = value
            bad_runs.append(malformed)
        for field, value in (("id", 101.5), ("run_attempt", 1.5)):
            malformed = json.loads(json.dumps(original))
            malformed[field] = value
            bad_runs.append(malformed)
        for guard in self._guards():
            for malformed in bad_runs:
                with self.subTest(guard=guard[:20], malformed=malformed):
                    self._owner(
                        None,
                        guard=guard,
                        runs=[malformed, self._run(102)],
                        jobs={101: [self._job(101)],
                              102: [self._job(102)]},
                        cond=True,
                    )
    def test_foreign_pr(self):
        guards = self._guards()
        foreign = self._run(101)
        foreign["pull_requests"][0]["number"] = 999
        foreign["pull_requests"][0]["base"]["sha"] = "d" * 40
        fpull = {
            "number": 999,
            "base": {
                "sha": "d" * 40,
                "repo": {"full_name": "lightning-it/shared-assets-lit"},
            },
            "head": {
                "sha": "c" * 40,
                "ref": "feature/li179",
                "repo": {"full_name": "lightning-it/shared-assets-lit"},
            },
        }
        for gidx, guard in enumerate(guards):
            with self.subTest(guard=gidx):
                self._owner("102", guard=guard,
                    runs=[foreign, self._run(102)], jobs={102: [self._job(102)]},
                    fpulls={999: fpull}, cond=True)
                bad = json.loads(json.dumps(fpull))
                bad["head"]["sha"] = "e" * 40
                self._owner(None, guard=guard,
                    runs=[foreign, self._run(102)], jobs={102: [self._job(102)]},
                    fpulls={999: bad}, cond=True)
    def test_unrelated_run_associations(self):
        unrelated = self._run(100)
        unrelated["path"] = ".github/workflows/repository-quality.yml"
        first = unrelated["pull_requests"][0]
        second = json.loads(json.dumps(first))
        second["number"] = 999
        second["base"]["sha"] = "d" * 40
        for associations in ([], [first, second]):
            candidate = json.loads(json.dumps(unrelated))
            candidate["pull_requests"] = associations
            for guard in self._guards():
                self._owner("101", guard=guard,
                    runs=[candidate, self._run(101)],
                    jobs={101: [self._job(101)]}, cond=True)
        malformed = json.loads(json.dumps(unrelated))
        malformed["pull_requests"] = [{**first, "number": 123.5}]
        for guard in self._guards():
            self._owner(None, guard=guard,
                runs=[malformed, self._run(101)],
                jobs={101: [self._job(101)]}, cond=True)
    def test_empty_association_uses_unique_open_branch_binding(self):
        unassociated = self._run(101)
        unassociated["pull_requests"] = []
        repo = "lightning-it/shared-assets-lit"
        current_pull = {
            "number": 2334, "state": "open",
            "base": {"sha": "b" * 40, "repo": {"full_name": repo}},
            "head": {"ref": "feature/li179", "sha": "c" * 40,
                     "repo": {"full_name": repo}},
        }
        closed_pull = {**current_pull, "number": 12, "state": "closed",
                       "head": {**current_pull["head"], "sha": "d" * 40}}
        for guard in self._guards():
            self._owner("101", guard=guard, runs=[unassociated],
                        jobs={101: [self._job(101)]}, cond=True)
            old_base = self._run(100)
            old_base["pull_requests"] = []
            old_job = self._job(100)
            old_job["steps"][0]["name"] = (
                "Event binding #2334:" + "d" * 40 + ":" + "c" * 40 + ":100")
            self._owner("101", guard=guard,
                        runs=[old_base, unassociated],
                        jobs={100: [old_job], 101: [self._job(101)]},
                        cond=True)
            spoofed_title = self._run(100)
            spoofed_title["pull_requests"] = []
            spoofed_job = self._job(100)
            spoofed_job["steps"][0]["name"] = (
                "Event binding #2334:" + "b" * 40 + ":" + "c" * 40 + ":101")
            self._owner("101", guard=guard,
                        runs=[spoofed_title, unassociated],
                        jobs={100: [spoofed_job], 101: [self._job(101)]},
                        cond=True)
            self._owner("101", guard=guard, runs=[unassociated],
                        jobs={101: [self._job(101)]},
                        branch_pulls=[closed_pull, current_pull], cond=True)
            for branch_pulls in ([], [current_pull, current_pull],
                                 [{**current_pull, "number": 999}],
                                 [{**current_pull, "head": {
                                     **current_pull["head"], "sha": "d" * 40}}]):
                self._owner(None, guard=guard, runs=[unassociated],
                            jobs={101: [self._job(101)]},
                            branch_pulls=branch_pulls, cond=True)
            wrong_ref = json.loads(json.dumps(unassociated))
            wrong_ref["head_branch"] = "feature/other"
            self._owner(None, guard=guard, runs=[wrong_ref],
                        jobs={101: [self._job(101)]}, cond=True)

    def test_previous_base_unassociated_owner_uses_current_live_pull(self):
        previous_base = "d" * 40
        previous = self._run(100)
        previous["pull_requests"] = []
        previous_job = self._job(100)
        previous_job["steps"][0]["name"] = (
            "Event binding #2334:" + previous_base + ":" + "c" * 40 + ":100")
        guard = self._refresh_guard()
        self._owner("100", guard=guard, runs=[previous],
                    jobs={100: [previous_job]},
                    event_base=previous_base, cond=True)
        self._owner(None, guard=guard, runs=[previous],
                    jobs={100: [previous_job]},
                    event_base=previous_base, live_base=previous_base,
                    cond=True)
        wrong_event_job = self._job(100)
        self._owner(None, guard=guard, runs=[previous],
                    jobs={100: [wrong_event_job]},
                    event_base=previous_base, cond=True)

    def test_publish_revalidation_binds_live_base_before_owner_guard(self):
        workflow = COPILOT_WORKFLOW.read_text(encoding="utf-8")
        start = workflow.index("      - name: Publish bound neutral result\n")
        end = workflow.find("\n      - name:", start + 1)
        publish = workflow[start:end if end >= 0 else None]
        self.assertIn(
            "LIVE_BASE: ${{ github.event.pull_request.base.sha }}", publish
        )
        self.assertIn(
            'source "${RUNNER_TEMP}/current-revision-producer-owner.sh"',
            publish,
        )
        self.assertIn('live_owner="$(eo)"', publish)

    def test_owner_rename(self):
        guards = self._guards()
        original = self._run(101)
        original["head_branch"] = "feature/original"
        original["pull_requests"][0]["head"]["ref"] = "feature/original"
        renamed = self._run(102)
        renamed["head_branch"] = "feature/renamed"
        renamed["pull_requests"][0]["head"]["ref"] = "feature/renamed"
        for gidx, guard in enumerate(guards):
            with self.subTest(guard=gidx):
                self._owner("101", guard=guard,
                    event_ref="feature/renamed", runs=[original, renamed],
                    jobs={101: [self._job(101)], 102: [self._job(102)]},
                    cond=True)
    def test_owner_drift(self):
        malformed = self._run(101)
        malformed["run_attempt"] = "1"
        self._owner(None, runs=[malformed], jobs={101: [self._job(101)]},
                           cond=True)
        changed = self._run_guard(runs=[self._run(102)],
            runs2=[self._run(101), self._run(102)],
            jobs={101: [self._job(101)], 102: [self._job(102)]}, cond=True)
        self.assertNotEqual(0, changed.returncode)
        self.assertIn("changed between stable reads", changed.stderr)
        self._owner(None, runs=[self._run(101), self._run(102)],
            jobs={101: [self._req(101)], 102: [self._job(102)]},
            cond=True)
    def test_owner_draft(self):
        draft_job = self._job(101, status="completed", conclusion="skipped")
        done_job = self._job(101, status="completed", conclusion="failure")
        sync_req = self._req(101, status="completed", conclusion="skipped")
        rreq = self._req(102, status="in_progress", conclusion=None)
        sync_pol = self._job(37155519577, status="completed", conclusion="failure")
        sync_req2 = self._req(37155519577, status="completed", conclusion="skipped")
        ready_pol = self._job(37156339900, status="completed", conclusion="failure")
        ready_req = self._req(37156339900, status="completed", conclusion="success")
        runs = [self._run(101), self._run(102)]
        cases = (
            ("102", runs, {101: [draft_job], 102: [self._job(102)]}),
            ("101", runs, {101: [done_job], 102: [self._job(102)]}),
            ("102", runs, {101: [done_job, sync_req],
                                  102: [self._job(102), rreq]}),
            ("37156339900", [self._run(37155519577), self._run(37156339900)],
             {37155519577: [sync_pol, sync_req2],
              37156339900: [ready_pol, ready_req]}),
            ("101", [self._run(101)], {101: [done_job]}),
        )
        for want, runs, jobs in cases:
            self._owner(want, runs=runs, jobs=jobs, cond=True)
        for conclusion in ("", "unknown", "skipped ", "SUCCESS"):
            with self.subTest(conclusion=conclusion):
                unk_job = self._job(101, status="completed", conclusion=conclusion)
                self._owner(None, runs=runs,
                    jobs={101: [unk_job], 102: [self._job(102)]},
                    cond=True)
        bad_job = self._job(101, status="completed", conclusion={"bad": True})
        self._owner(None, runs=runs,
            jobs={101: [bad_job], 102: [self._job(102)]},
            cond=True)
    def test_owner_original(self):
        skip_req = self._req(101)
        skip_req.update(status="completed", conclusion="skipped")
        self._owner("101", runs=[self._run(101)],
            jobs={101: [self._job(101), skip_req]},
            mode="verification", cond=True)
        rerun_pol = self._job(101, attempt=2)
        rerun_req = self._req(101, attempt=2)
        rerun_req.update(status="completed", conclusion="skipped")
        self._owner("101",
            runs=[self._run(101, attempt=2), self._run(102)],
            jobs={101: [rerun_pol, rerun_req], 102: [self._job(102)]},
            first_jobs={101: [self._job(101), self._req(101)]},
            cond=True)
    def test_helper_owner(self):
        guards = self._guards()
        self.assertEqual(3, len(guards))
        self.assertTrue(all(guard == guards[0] for guard in guards))
        workflow = COPILOT_WORKFLOW.read_text(encoding="utf-8")
        publish = workflow.split("      - name: Publish bound neutral result\n", 1)[1]
        dispatch = workflow.split("      - name: Dispatch the protected re-evaluation helper ", 1)[1]
        revalidation = 'live_owner="$(eo)" || exit 1'
        mutation = "actions/workflows/current-revision-rerun.yml/dispatches"
        for fragment in (revalidation,
                         'test "${live_owner}" = "${OWNER_RUN_ID}"',
                         'test "${live_owner}" = "${PRODUCER_RUN_ID}"'):
            self.assertIn(fragment, dispatch)
        self.assertLess(dispatch.index(revalidation), dispatch.index(mutation))
        refresh = REFRESH_WORKFLOW.read_text(encoding="utf-8")
        self.assertNotIn("sort_by(.run_number)", refresh)
        rerun = '"repos/${REPOSITORY}/actions/runs/${owner_run_id}/rerun"'
        for fragment in (rerun, 'test "${live_owner}" = "${owner_run_id}"',
                         "revalidate_refresh_state", 'and .run_attempt == 1'):
            self.assertIn(fragment, refresh)
        retry_budget = 'if [ "${run_attempt}" -ne 1 ]; then'
        self.assertIn(retry_budget, refresh)
        self.assertLess(refresh.rindex("revalidate_refresh_state"), refresh.index(rerun))
        self.assertLess(refresh.index(retry_budget), refresh.index(rerun))
        rel_route = "Release-App review evidence is owned by its dedicated producer"
        self.assertIn(rel_route, refresh)
        owner_guard = 'owner_guard="${RUNNER_TEMP}/current-revision-producer-owner.sh"'
        self.assertLess(refresh.index(rel_route), refresh.index(owner_guard))
        for fragment, text in (
            ("producer_owner_mode: ${{ steps.producer-owner.outputs.owner_mode }}", workflow),
            ("PRODUCER_OWNER_MODE: ${{ steps.producer-owner.outputs.owner_mode }}", publish),
            ("needs.verify-current-revision-policy.outputs.producer_owner_mode", dispatch),
        ):
            self.assertIn(fragment, text)
    def test_neutral_binding(self):
        workflow = COPILOT_WORKFLOW.read_text(encoding="utf-8")
        publish = workflow.split("      - name: Publish bound neutral result\n", 1)[
            1
        ]
        self.assertIn("ro", publish)
        self.assertIn("vc", publish)
        self.assertNotIn("api_patch()", publish)
        self.assertIn("api_patch_bound", publish)
        self.assertIn('and .external_id == $external_id', publish)
        recovery = (
            "{schema:4,base_sha:$base,head_sha:$head,\n"
            "                  producer_run_id:$producer_run_id,\n"
            "                  invalidated_check_run_id:$check_run_id,\n"
            '                  reason:"canonical refresh invalidation"}'
        )
        self.assertIn(recovery, workflow)
        self.assertIn(
            recovery,
            REFRESH_WORKFLOW.read_text(encoding="utf-8"),
        )
    @staticmethod
    def _pub(name):
        workflow = COPILOT_WORKFLOW.read_text(encoding="utf-8")
        publish = workflow.index("      - name: Publish bound neutral result\n")
        marker = f"          {name}() {{\n"
        start = workflow.index(marker, publish)
        end = workflow.index("\n          }\n", start) + len("\n          }\n")
        return textwrap.dedent(workflow[start:end])
    @staticmethod
    def _pub_nested(name):
        workflow = COPILOT_WORKFLOW.read_text(encoding="utf-8")
        publish = workflow.index("      - name: Publish bound neutral result\n")
        marker = f"            {name}() {{\n"
        start = workflow.index(marker, publish)
        end = workflow.index("\n            }\n", start) + len("\n            }\n")
        return textwrap.dedent(workflow[start:end])
    @staticmethod
    def _rfn(name):
        workflow = REFRESH_WORKFLOW.read_text(encoding="utf-8")
        marker = f"          {name}() {{\n"
        start = workflow.index(marker)
        end = workflow.index("\n          }\n", start) + len("\n          }\n")
        function = textwrap.dedent(workflow[start:end])
        if name != "va":
            return function
        fixture = r'''
read_evidence_owner_pr() {
  if [ -n "${OWNER_PR:-}" ]; then printf '%s\n' "${OWNER_PR}"; return; fi
  jq -cn --arg author "${PR_AUTHOR}" --arg base "${BASE_SHA}" \
    --arg base_ref "${BASE_REF:-develop}" --arg head "${HEAD_SHA}" \
    --arg head_ref "${HEAD_REF:-fix/final}" \
    --arg repository "${REPOSITORY:-lightning-it/.github}" \
    --argjson number "${PR_NUMBER:-123}" \
    '{number:$number,state:"open",draft:false,merged_at:null,
      user:{login:$author},base:{ref:$base_ref,sha:$base,
      repo:{full_name:$repository}},head:{ref:$head_ref,sha:$head,
      repo:{full_name:$repository}}}'
}
'''
        function = function.replace("va() {", "workflow_va() {", 1)
        wrapper = r'''
va() {
  local payload="${1}"
  : "${BASE_REF:=develop}" "${HEAD_REF:=fix/final}"
  : "${PR_NUMBER:=123}" "${REPOSITORY:=lightning-it/.github}"
  if ! jq -e '.[0].output.summary | strings | fromjson? | type=="object"' \
      <<<"${payload}" >/dev/null; then
    payload="$(jq -c --arg base "${BASE_SHA}" --arg head "${HEAD_SHA}" \
      --argjson owner "${owner_run_id}" --argjson pr "${PR_NUMBER:-123}" \
      '.[0].output.summary=({schema:4,base_sha:$base,head_sha:$head,
        pull_request_number:$pr,producer_run_id:$owner}|tojson)' \
      <<<"${payload}")"
  fi
  workflow_va "${payload}"
}
'''
        return textwrap.dedent(fixture) + function + textwrap.dedent(wrapper)
    @staticmethod
    def _review_script():
        workflow = COPILOT_WORKFLOW.read_text(encoding="utf-8")
        marker = (
            '          cat >"${verification_script}" '
            "<<'VERIFY_COPILOT_REVIEW'\n"
        )
        start = workflow.index(marker) + len(marker)
        end = workflow.index("\n          VERIFY_COPILOT_REVIEW", start)
        return textwrap.dedent(workflow[start:end])
    def test_successor_head(self):
        bhead = "b" * 40
        def evaluate(lhead):
            empty = {"pageInfo": {"hasNextPage": False, "endCursor": None},
                     "nodes": []}
            review = {"id": "REVIEW_1",
                      "author": {"login": "copilot-pull-request-reviewer"},
                      "commit": {"oid": lhead}, "state": "COMMENTED"}
            pages = (
                {"errors": [], "data": {"repository": {"pullRequest": {
                    "headRefOid": lhead, "reviews": {
                        "pageInfo": {"hasPreviousPage": False, "startCursor": None},
                        "nodes": [review]}}}}},
                {"errors": [], "data": {"node": {"body": "Review complete.",
                    "commit": {"oid": lhead},
                    "pullRequest": {"headRefOid": lhead}, "comments": empty}}},
                {"errors": [], "data": {"repository": {"pullRequest": {
                    "headRefOid": lhead, "reviewThreads": empty}}}},
            )
            with tempfile.TemporaryDirectory() as tmp:
                script = r'''set -euo pipefail
sleep() { :; }
gh() {
  local calls=0
  [ ! -f "${CALL_COUNTER}" ] || calls="$(cat "${CALL_COUNTER}")"
  printf %s "$((calls + 1))" >"${CALL_COUNTER}"
  case "${calls}" in 0) printf %s "${PAGE_0}";; 1) printf %s "${PAGE_1}";; 2) printf %s "${PAGE_2}";; *) return 91;; esac
}
''' + self._review_script()
                env = {"PATH": TEST_TOOL_PATH,
                       "CALL_COUNTER": str(Path(tmp) / "calls"),
                       "COPILOT_REVIEWER_LOGIN": "copilot-pull-request-reviewer",
                       "EVENT_HEAD": bhead,
                       "NO_FILES_REVIEW_MARKER": "was not able to review any files",
                       "PR_NUMBER": "123", "QUOTA_EXCEEDED_MARKER": "quota exceeded",
                       "QUOTA_EXHAUSTED_MARKER": "quota exhausted",
                       "REPOSITORY": "lightning-it/.github",
                       "SUPPRESSED_COMMENTS_MARKER": "suppressed comments",
                       "UNABLE_REVIEW_MARKER": "unable to review this pull request"}
                env.update({f"PAGE_{index}": json.dumps(page)
                            for index, page in enumerate(pages)})
                return self._run_bash(script, env)
        current = evaluate(bhead)
        self.assertEqual(0, current.returncode, current.stderr)
        successor = evaluate("c" * 40)
        self.assertNotEqual(
            0,
            successor.returncode,
            f"stdout={successor.stdout!r} stderr={successor.stderr!r}",
        )
        self.assertIn("producer-bound head", successor.stderr)
    def test_refresh_binding(self):
        want = {
            "id": 42, "name": "Current revision review",
            "app": {"id": 15368, "slug": "github-actions"},
            "head_sha": "b" * 40, "external_id": "bound-owner-77",
            "status": "completed", "conclusion": "success",
            "details_url": "https://github.example/runs/42",
            "completed_at": "2026-10-03T12:00:00Z",
            "output": {"title": "passed", "summary": "evidence"}}
        def evaluate(
            live, owners
        ):
            with tempfile.TemporaryDirectory() as tmp:
                script = r'''set -euo pipefail
eo() {
  local reads=0
  [ ! -f "${OWNER_COUNTER}" ] || reads="$(cat "${OWNER_COUNTER}")"
  printf %s "$((reads + 1))" >"${OWNER_COUNTER}"
  [ "${reads}" -eq 0 ] && printf %s "${OWNER_BEFORE}" || printf %s "${OWNER_AFTER}"
}
validate_live_pr_tuple() { :; }
read_refresh_checks() { printf %s "${LIVE}"; }
''' + self._rfn("revalidate_refresh_state") + \
                    '\nrevalidate_refresh_state 1 "${EXPECTED}"\n'
                return self._run_bash(script, {
                    "EXPECTED": json.dumps([want], separators=(",", ":")),
                    "LIVE": json.dumps(live, separators=(",", ":")),
                    "OWNER_AFTER": str(owners[1]), "OWNER_BEFORE": str(owners[0]),
                    "OWNER_COUNTER": str(Path(tmp) / "owners"),
                    "owner_run_id": "77"})
        stable = evaluate([want], (77, 77))
        self.assertEqual(0, stable.returncode, stable.stderr)
        for live, owners in (([{**want, "external_id": "foreign"}], (77, 77)),
                             ([want, want], (77, 77)),
                             ([want], (77, 78))):
            self.assertNotEqual(0, evaluate(live, owners).returncode)
    def test_duplicate_refresh_checks_are_invalidated_in_id_order(self):
        base, head, owner = "b" * 40, "c" * 40, 77
        binding = f"mlx90-current-revision:copilot:v6:2334:{owner}:{base}:{head}"
        def check(check_id, external_id=binding):
            return {"id": check_id, "name": "Current revision review",
                "app": {"id": 15368, "slug": "github-actions"},
                "head_sha": head, "external_id": external_id,
                "status": "completed", "conclusion": "success",
                "details_url": f"https://github.example/lightning-it/.github/runs/{check_id}",
                "completed_at": "2026-10-04T12:00:00Z",
                "output": {"title": "PASS", "summary": "evidence"}}
        functions = "".join(self._rfn(name) for name in (
            "read_refresh_checks", "revalidate_refresh_state", "va",
            "invalidate_refresh_check", "invalidate_duplicate_refresh_checks"))
        def evaluate(checks, mode="stable", owner_drift=False):
            with tempfile.TemporaryDirectory() as tmp:
                state, log = Path(tmp) / "state", Path(tmp) / "patches"
                reads = Path(tmp) / "reads"
                state.write_text(json.dumps(checks), encoding="utf-8")
                reads.write_text("0", encoding="utf-8")
                script = r'''set -euo pipefail
oa() { gh api "$@"; }
eo() { [ "${OWNER_DRIFT}" != true ] || { printf 78; return; }; printf %s "${owner_run_id}"; }
validate_live_pr_tuple() { :; }
read_refresh_review_state() { printf '%s' '{"event_current":true,"incomplete":0,"unresolved":0}'; }
gh() {
  local arg endpoint='' id n updated
  for arg in "$@"; do case "${arg}" in repos/*) endpoint="${arg}";; esac; done
  if [[ " $* " != *" --method PATCH "* ]]; then
    n="$(cat "${READS}")"; printf %s "$((n + 1))" >"${READS}"
    [ "${MODE}" != api-fail ] || [ "${n}" -eq 0 ] || return 97
    if { [ "${MODE}" = count-drift ] && [ "${n}" -gt 0 ]; } ||
      { [ "${MODE}" = post-first-drift ] && [ "${n}" -gt 1 ]; }; then
      jq -cn --slurpfile state "${STATE}" '[{check_runs:($state[0][0:1])}]'
    elif [ "${MODE}" = snapshot-drift ] && [ "${n}" -gt 0 ]; then
      jq -cn --slurpfile state "${STATE}" '[{check_runs:($state[0] |
        map(if .id == 42 then .output.title="drift" else . end))}]'
    else
      jq -cn --slurpfile state "${STATE}" '[{check_runs:$state[0]}]'
    fi
    return
  fi
  id="${endpoint##*/}"
  updated="$(jq -ce --arg evidence "${recovery_evidence}" \
    --arg external "${current_external_id}" --arg url "${check_url}" \
    --argjson id "${id}" '.[] | select(.id == $id) |
      .status="completed" | .conclusion="failure" | .external_id=$external |
      .details_url=$url | .completed_at="2026-10-04T12:01:00Z" |
      .output={title:"Current revision review invalidated",summary:$evidence}' "${STATE}")" || return 1
  jq -c --argjson updated "${updated}" --argjson id "${id}" \
    'map(if .id == $id then $updated else . end)' "${STATE}" >"${STATE}.new"
  mv "${STATE}.new" "${STATE}"
  printf '%s\n' "${id}" >>"${LOG}"
  printf %s "${updated}"
}
''' + functions + r'''
neutral="$(read_refresh_checks)"
neutral_count="$(jq 'length' <<<"${neutral}")"
refresh_expected_count="${neutral_count}"
refresh_expected_snapshot=null
invalidate_duplicate_refresh_checks
jq -e 'length == 2 and all(.[]; .conclusion == "failure")' "${STATE}" >/dev/null
'''
                res = self._run_bash(script, {"BASE_SHA": base, "HEAD_SHA": head,
                    "GITHUB_SERVER_URL": "https://github.example",
                    "LOG": str(log), "PR_AUTHOR": "litroc", "PR_NUMBER": "2334",
                    "MODE": mode, "OWNER_DRIFT": str(owner_drift).lower(),
                    "READS": str(reads), "REPOSITORY": "lightning-it/.github",
                    "STATE": str(state),
                    "current_external_id": binding, "current_external_kind": "copilot",
                    "owner_run_id": str(owner)})
                return res, log.read_text() if log.exists() else ""
        result, log = evaluate([check(43), check(42)])
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("43\n42\n", log)
        rejected, log = evaluate([check(42), check(43, "foreign")])
        self.assertNotEqual(0, rejected.returncode)
        self.assertEqual("", log)
        for mode in ("count-drift", "snapshot-drift", "api-fail"):
            rejected, log = evaluate([check(42), check(43)], mode)
            self.assertNotEqual(0, rejected.returncode)
            self.assertEqual("", log)
        rejected, log = evaluate([check(42), check(43)], owner_drift=True)
        self.assertNotEqual(0, rejected.returncode)
        self.assertEqual("", log)
        rejected, log = evaluate([check(42), check(43)], "post-first-drift")
        self.assertNotEqual(0, rejected.returncode)
        self.assertEqual("43\n", log)
        malformed_cases = ([check(42), check(42)],
                           [check(42), {**check(43), "external_id": None}],
                           [check(index) for index in range(1, 22)])
        for checks in malformed_cases:
            rejected, log = evaluate(checks)
            self.assertNotEqual(0, rejected.returncode)
            self.assertEqual("", log)
    def test_attempt2_rerun(self):
        script = "\n".join(
            (
                "set -euo pipefail",
                self._rfn("assert_refresh_rerun_budget"),
                'assert_refresh_rerun_budget "${RUN}"',
            )
        )
        def evaluate(attempt):
            return self._run_bash(script, {
                "RUN": json.dumps({"id": 77, "status": "completed",
                                   "run_attempt": attempt}, separators=(",", ":")),
                "owner_run_id": "77"})
        self.assertEqual(0, evaluate(1).returncode)
        self.assertNotEqual(0, evaluate(2).returncode)
    def test_queued_refresh(self):
        functions = (self._rfn("assert_refresh_rerun_budget")
                     + self._rfn("rerun_owner_if_review_current"))
        def execute(state):
            with tempfile.TemporaryDirectory() as tmp:
                lfile = Path(tmp) / "log"
                script = r'''set -euo pipefail
claim_review_operation() { :; }
usable_current_review() { :; }
revalidate_refresh_state() { printf S >>"${LOG_FILE}"; }
validate_refresh_owner_run() { printf O >>"${LOG_FILE}"; }
read_refresh_review_state() { printf V >>"${LOG_FILE}"; printf %s "${STATE}"; }
gh() { if [[ " $* " == *" --method POST "* ]]; then printf P >>"${LOG_FILE}"; printf '{}'; else printf G >>"${LOG_FILE}"; printf %s "${RUN}"; fi; }
''' + functions + "\nrerun_owner_if_review_current\n"
                env = {"PATH": TEST_TOOL_PATH, "LOG_FILE": str(lfile),
                       "REPOSITORY": "lightning-it/.github",
                       "RUN": json.dumps({"id": 77, "status": "completed",
                                          "conclusion": "failure", "run_attempt": 1}),
                       "STATE": json.dumps(state, separators=(",", ":")),
                       "owner_run_id": "77", "PR_NUMBER": "123",
                       "HEAD_SHA": "b" * 40, "BASE_SHA": "a" * 40,
                       "refresh_expected_count": "0",
                       "refresh_expected_snapshot": "null"}
                res = self._run_bash(script, env)
                return res.returncode, lfile.read_text() if lfile.exists() else ""
        unresolved = {"event_current": True, "incomplete": 0, "unresolved": 1}
        resolved = {"event_current": True, "incomplete": 0, "unresolved": 0}
        superseded = {**resolved, "event_current": False}
        for name, state, want_log in (
            ("producer timeout before resolution", unresolved, "SGOV"),
            ("resolution before lane acquire", resolved, "SGOVSGSSP"),
            ("stale event superseded", superseded, "SGOV"),
        ):
            with self.subTest(name=name):
                returncode, log = execute(state)
                self.assertEqual(0, returncode)
                self.assertEqual(want_log, log)
        # Only the later resolved lane turn may consume attempt two.
        self.assertEqual((0, "SGOV"), execute(unresolved))
        self.assertEqual((0, "SGOVSGSSP"), execute(resolved))
    def test_superseded_event(self):
        function = self._rfn("invalidate_refresh_check")
        def execute(state, reason):
            with tempfile.TemporaryDirectory() as tmp:
                log = Path(tmp) / "mutations"
                script = r'''set -euo pipefail
read_refresh_review_state() { printf %s "${STATE}"; }
revalidate_refresh_state() { printf R >>"${LOG}"; }
gh() { printf P >>"${LOG}"; return 97; }
''' + function + '\ninvalidate_refresh_check "${REASON}"\n'
                res = self._run_bash(script, {"LOG": str(log),
                    "REASON": reason, "STATE": json.dumps(state)})
                self.assertEqual(0, res.returncode, res.stderr)
                self.assertFalse(log.exists(), "stale evidence reached PATCH path")
        execute({"event_current": False, "incomplete": 0, "unresolved": 0},
                "binding")
        execute({"event_current": True, "incomplete": 0, "unresolved": 0},
                "unresolved")
    def test_event_freshness(self):
        head = "c" * 40
        pull_url = "https://api.github.com/repos/lightning-it/.github/pulls/737"
        def page(ids=(), more=False, cursor=None, live=head, errors=None):
            nodes = [{"id": "T1", "isResolved": True,
                "comments": {"pageInfo": {"hasNextPage": False}, "nodes": [
                    {"databaseId": value, "author": {"login": "litroc"},
                     "pullRequestReview": {"commit": {"oid": head}}} for value in ids]}}] if ids else []
            res = {"data": {"repository": {"pullRequest": {"headRefOid": live,
                "reviewThreads": {"nodes": nodes, "pageInfo": {
                    "hasNextPage": more, "endCursor": cursor}}}}}}
            if errors is not None: res["errors"] = errors
            return res
        event = {"action": "submitted", "review": {"id": 42,
                 "user": {"login": "copilot-pull-request-reviewer[bot]"},
                 "author_association": "NONE", "commit_id": head,
                 "body": "finding", "state": "commented",
                 "submitted_at": "2026-10-04T04:45:53Z",
                 "pull_request_url": pull_url}}
        live = {**event["review"], "state": "COMMENTED"}
        def evaluate(event_record, live_record,
                     event_name="pull_request_review", pages=None, fail=False):
            with tempfile.TemporaryDirectory() as tmp:
                epath = Path(tmp) / "event.json"
                epath.write_text(json.dumps(event_record), encoding="utf-8")
                script = ('set -euo pipefail\noa() { [ "${COMMENT_FAIL}" != true ] || return 97; '
                          'if [ "${1}" = graphql ]; then local n=0; [ ! -f "${PAGE_COUNTER}" ] || n="$(cat "${PAGE_COUNTER}")"; '
                          'printf %s "$((n+1))" >"${PAGE_COUNTER}"; jq -ce --argjson n "${n}" \'.[$n]\' <<<"${COMMENT_PAGES}"; '
                          'else printf %s "${LIVE_RECORD}"; fi; }\n'
                          + self._rfn("refresh_event_record_state")
                          + self._rfn("read_refresh_review_state")
                          + "\nrefresh_event_record_state\n")
                env = {"PATH": TEST_TOOL_PATH, "EVENT_NAME": event_name,
                       "GITHUB_API_URL": "https://api.github.com",
                       "GITHUB_EVENT_PATH": str(epath), "HEAD_SHA": head,
                       "LIVE_RECORD": json.dumps(live_record),
                       "COMMENT_FAIL": str(fail).lower(),
                       "PAGE_COUNTER": str(Path(tmp) / "pages"),
                       "COMMENT_PAGES": json.dumps(pages if pages is not None else [page()]),
                       "PR_NUMBER": "737",
                       "REPOSITORY": "lightning-it/.github"}
                return self._run_bash(script, env)
        current = evaluate(event, live)
        self.assertEqual(0, current.returncode, current.stderr)
        self.assertEqual("current", current.stdout, current.stderr)
        edited = {**live, "body": "newer evidence"}
        self.assertEqual("superseded", evaluate(event, edited).stdout)
        malformed = json.loads(json.dumps(event))
        malformed["review"]["id"] = 42.5
        self.assertNotEqual(0, evaluate(malformed, live).returncode)
        comment = {"id": 43, "user": {"login": "litroc"},
                   "author_association": "MEMBER", "commit_id": head,
                   "body": "resolved", "path": "README.md",
                   "created_at": "2026-10-04T04:00:00Z",
                   "updated_at": "2026-10-04T04:45:53Z",
                   "pull_request_url": pull_url}
        comment_event = {"action": "edited", "comment": comment}
        current = evaluate(comment_event, comment, "pull_request_review_comment")
        self.assertEqual("current", current.stdout)
        self.assertEqual("superseded", evaluate(
            comment_event, {**comment, "body": "later"},
            "pull_request_review_comment").stdout)
        deleted = {"action": "deleted", "comment": comment}
        absent = evaluate(deleted, {}, "pull_request_review_comment", [page()])
        self.assertEqual("current", absent.stdout, f"{absent.returncode}: {absent.stderr}")
        self.assertEqual("superseded", evaluate(
            deleted, {}, "pull_request_review_comment", [page([43])]).stdout)
        bad = ([{"bad": True}], [page(more=True)],
               [page(more=True, cursor="C1"), page(more=True, cursor="C1")],
               [page(more=True, cursor=f"C{i}") for i in range(10)])
        for pages in bad:
            self.assertNotEqual(0, evaluate(
                deleted, {}, "pull_request_review_comment", pages).returncode)
        self.assertNotEqual(0, evaluate(
            deleted, {}, "pull_request_review_comment", [], True).returncode)
    def test_thread_pages(self):
        head = "c" * 40
        def thread(index, resolved=True, oid=head):
            comments = [] if resolved else [{"databaseId": index + 1,
                "author": {"login": "copilot-pull-request-reviewer"},
                "pullRequestReview": {"commit": {"oid": oid}}}]
            return {"id": f"T{index}", "isResolved": resolved,
                    "comments": {"pageInfo": {"hasNextPage": False}, "nodes": comments}}
        def page(nodes=(), more=False, cursor=None, live=head, errors=None):
            res = {"data": {"repository": {"pullRequest": {"headRefOid": live,
                "reviewThreads": {"nodes": list(nodes), "pageInfo": {
                    "hasNextPage": more, "endCursor": cursor}}}}}}
            if errors is not None: res["errors"] = errors
            return res
        def run(pages, fail=-1, state="current"):
            with tempfile.TemporaryDirectory() as tmp:
                script = r'''set -euo pipefail
validate_live_pr_tuple() { :; }
refresh_event_record_state() { local n=0; [ ! -f "${EC}" ] || n="$(cat "${EC}")"; printf %s "$((n + 1))" >"${EC}"; [ "${n}" -eq 0 ] && printf current || printf %s "${FINAL_EVENT}"; }
oa() { local n=0; [ ! -f "${PC}" ] || n="$(cat "${PC}")"; printf %s "$((n + 1))" >"${PC}"; [ "${n}" -ne "${FAIL}" ] || return 97; jq -ce --argjson n "${n}" '.[$n]' <<<"${PAGES}"; }
''' + self._rfn("read_refresh_review_state") + \
                    "\nread_refresh_review_state\n"
                return self._run_bash(script, {"FINAL_EVENT": state, "FAIL": str(fail),
                    "EC": str(Path(tmp) / "events"), "PC": str(Path(tmp) / "pages"),
                    "HEAD_SHA": head, "PAGES": json.dumps(pages), "PR_NUMBER": "737",
                    "REPOSITORY": "lightning-it/.github"})
        first = [thread(index) for index in range(100)]
        res = run([page(first, True, "C1"), page([thread(100)])])
        self.assertEqual(0, res.returncode, res.stderr)
        self.assertEqual({"event_current": True, "incomplete": 0, "unresolved": 0},
                         json.loads(res.stdout))
        res = run([page(first, True, "C1"), page([thread(100, False)])])
        self.assertEqual(1, json.loads(res.stdout)["unresolved"])
        superseded = run([page(first, True, "C1"), page([thread(100)])], state="superseded")
        self.assertFalse(json.loads(superseded.stdout)["event_current"])
        bad = ([page(first, True)], [page(first, True, "C1"), page(more=True, cursor="C1")],
               [page(first, True, "C1"), page(live="d" * 40)],
               [page(first, True, "C1"), page(errors=[{"message": "bad"}])],
               [page(first, True, "C1"), page([thread(0)])],
               [page(more=True, cursor=f"C{i}") for i in range(10)])
        for pages in bad:
            with self.subTest(pages=len(pages)): self.assertNotEqual(0, run(pages).returncode)
        self.assertNotEqual(0, run([page(first, True, "C1"), page()], fail=1).returncode)
    def test_refresh_rename(self):
        run = self._run(77)
        run["head_branch"] = "feature/original"
        run["pull_requests"][0]["head"]["ref"] = "feature/original"
        script = "\n".join((
            "set -euo pipefail",
            self._rfn("validate_refresh_owner_run"),
            'validate_refresh_owner_run "${RUN}"',
        ))
        def evaluate(candidate):
            res = self._run_bash(script, {
                    "BASE_SHA": "b" * 40,
                    "HEAD_REF": "feature/renamed",
                    "HEAD_SHA": "c" * 40,
                    "PR_NUMBER": "2334",
                    "REPOSITORY": "lightning-it/shared-assets-lit",
                    "RUN": json.dumps(candidate),
                    "owner_run_id": "77"})
            return res.returncode
        self.assertEqual(0, evaluate(run))
        inconsistent = json.loads(json.dumps(run))
        inconsistent["pull_requests"][0]["head"]["ref"] = "feature/other"
        self.assertNotEqual(0, evaluate(inconsistent))
        unassociated = json.loads(json.dumps(run))
        unassociated["pull_requests"] = []
        self.assertNotEqual(0, evaluate(unassociated))
        unassociated["head_branch"] = "feature/renamed"
        self.assertEqual(0, evaluate(unassociated))
    def test_invalidation(self):
        base, head, check_id, owner = "a" * 40, "b" * 40, 42, 77
        binding = f"mlx90-current-revision:copilot:v6:123:77:{base}:{head}"
        url = "https://github.example/runs/42"
        data = {"schema": 4, "base_sha": base, "head_sha": head,
                "producer_run_id": owner}
        def compact(value):
            return json.dumps(value, separators=(",", ":"))
        evidence = compact(data)
        rec = compact({**data, "invalidated_check_run_id": check_id,
                       "reason": "canonical refresh invalidation"})
        def evaluate(snapshot, *, after=None, vexit=0, kind="none", verifier=True):
            with tempfile.TemporaryDirectory() as tmp:
                path, log = Path(tmp), Path(tmp) / "verified"
                if verifier:
                    (path / "verify-current-copilot-review.sh").write_text(
                        '#!/usr/bin/env bash\nprintf "verification log\\n"\n'
                        'printf V >>"${VERIFY_LOG}"\nexit "${VERIFY_EXIT}"\n',
                        encoding="utf-8")
                script = r'''set -euo pipefail
api_read() { local reads=0; [ ! -f "${READ_COUNTER}" ] || reads="$(cat "${READ_COUNTER}")"; printf %s "$((reads + 1))" >"${READ_COUNTER}"; [ "${reads}" -eq 0 ] && printf %s "${SNAPSHOT}" || printf %s "${SNAPSHOT_AFTER}"; }
ro() { :; }
''' + self._pub("vc") + \
                    '\nvc 42 "${EXTERNAL_ID}" "Current revision review" "${DETAILS_URL}"\n'
                env = {"PATH": TEST_TOOL_PATH, "DETAILS_URL": url,
                       "EVENT_BASE": base, "EVENT_HEAD": head,
                       "EXTERNAL_ID": binding, "OWNER_RUN_ID": str(owner),
                       "READ_COUNTER": str(path / "reads"),
                       "REPOSITORY": "lightning-it/.github", "RUNNER_TEMP": tmp,
                       "SNAPSHOT": compact(snapshot),
                       "SNAPSHOT_AFTER": compact(after or snapshot),
                       "VERIFY_EXIT": str(vexit), "VERIFY_LOG": str(log),
                       "TRUSTED_KIND": kind, "evidence": evidence}
                res = self._run_bash(script, env)
                return res, len(log.read_text()) if log.exists() else 0
        common = {
            "id": check_id, "name": "Current revision review",
            "app": {"id": 15368, "slug": "github-actions"}, "head_sha": head,
            "external_id": binding, "status": "completed", "details_url": url,
            "completed_at": "2026-10-03T12:00:00Z"}
        success = {**common, "conclusion": "success",
                   "output": {"summary": evidence, "title": "passed"}}
        failed = {**common, "conclusion": "failure", "output": {
            "summary": rec, "title": "Current revision review invalidated"}}
        for snapshot, options, ok, count in (
            (success, {}, True, 0), (failed, {}, True, 1),
            (failed, {"vexit": 1}, False, 1),
            (failed, {"after": {**failed,
             "completed_at": "2026-10-03T12:00:01Z"}}, False, 1),
        ):
            res, attempts = evaluate(snapshot, **options)
            self.assertEqual(ok, res.returncode == 0, res.stderr)
            self.assertEqual(count, attempts)
        ok, _ = evaluate(failed)
        self.assertEqual("", ok.stdout)
        self.assertIn("verification log", ok.stderr)
        deterministic, attempts = evaluate(failed, kind="shared-assets",
                                           verifier=False)
        self.assertEqual(0, deterministic.returncode, deterministic.stderr)
        self.assertEqual(0, attempts)
        self.assertIn("Deterministic shared-assets evidence was revalidated",
                      deterministic.stderr)
        rejected = (
            {**failed, "external_id": "foreign"},
            {**failed, "output": {**failed["output"],
             "title": "Current revision review invalidated "}},
            {**failed, "output": {**failed["output"],
             "summary": rec.replace('"invalidated_check_run_id":42',
                                    '"invalidated_check_run_id":43')}},
            {**failed, "conclusion": "neutral"},
        )
        for snapshot in rejected:
            self.assertNotEqual(0, evaluate(snapshot)[0].returncode)
    def test_copilot_dispatcher_matches_the_rerun_helper_contract(self) -> None:
        workflow = COPILOT_WORKFLOW.read_text(encoding="utf-8")
        marker = (
            "      - name: Dispatch the protected re-evaluation helper "
            "from the exact base\n"
        )
        start = workflow.index(marker)
        dispatch = workflow[start:]

        self.assertIn("BASE_REF: ${{ github.event.pull_request.base.ref }}", dispatch)
        self.assertIn("PRODUCER_RUN_ID: ${{ github.run_id }}", dispatch)
        self.assertIn("PRODUCER_RUN_ATTEMPT: ${{ github.run_attempt }}", dispatch)
        self.assertNotIn("EXECUTED_WORKFLOW_SHA", dispatch)
        self.assertIn(
            'test "${GITHUB_REF}" = "refs/heads/${BASE_REF}"',
            dispatch,
        )
        self.assertIn('test "${GITHUB_REF_PROTECTED}" = true', dispatch)
        self.assertIn('-f "ref=${BASE_REF}"', dispatch)
        self.assertIn('-f "inputs[base_ref]=${BASE_REF}"', dispatch)
        self.assertIn(
            '-f "inputs[producer_run_id]=${PRODUCER_RUN_ID}"',
            dispatch,
        )
        self.assertIn(
            '-f "inputs[producer_run_attempt]=${PRODUCER_RUN_ATTEMPT}"',
            dispatch,
        )
        self.assertNotIn("-f ref=develop", dispatch)

    def _test_tool(self, name: str) -> str:
        executable = shutil.which(name, path=TEST_TOOL_PATH)
        if executable is None:
            self.fail(
                f"{name} is required in the deterministic test tool path"
            )
        return executable

    @staticmethod
    def _rerun_evidence_kind_guard() -> str:
        workflow = RERUN_WORKFLOW.read_text(encoding="utf-8")
        marker = '            if [ "${external_kind}" = ancestry-backmerge ]; then\n'
        start = workflow.index(marker)
        end = workflow.index('            controller_sha="$(jq -er', start)
        return textwrap.dedent(workflow[start:end])

    @staticmethod
    def _refresh_validation_filter() -> str:
        workflow = REFRESH_WORKFLOW.read_text(encoding="utf-8")
        branch = workflow.index("            elif ! jq -e \\\n")
        marker = '              --arg url "${check_url}" \'\n'
        start = workflow.index(marker, branch) + len(marker)
        end = workflow.index('\n              \' <<<"${neutral}"', start)
        return workflow[start:end]

    @staticmethod
    def _refresh_event_authorization_filter() -> str:
        workflow = REFRESH_WORKFLOW.read_text(encoding="utf-8")
        marker = '            --arg repository "${REPOSITORY}" \'\n'
        start = workflow.index(marker) + len(marker)
        end = workflow.index(
            '\n            \' "${GITHUB_EVENT_PATH}" >/dev/null', start
        )
        return workflow[start:end]

    @staticmethod
    def _rerun_summary_filter() -> str:
        workflow = RERUN_WORKFLOW.read_text(encoding="utf-8")
        summary = workflow.index("          validate_evidence_owner() {\n")
        marker = '            --argjson run_id "${producer_id}" \'\n'
        start = workflow.index(marker, summary) + len(marker)
        end = workflow.index('\n              \' <<<"${neutral_summary}"', start)
        return workflow[start:end]

    @staticmethod
    def _rerun_owner_binding_guard() -> str:
        return CopilotReviewRefreshTests._rerun_shell_function(
            "validate_evidence_owner"
        )

    @staticmethod
    def _rerun_list_summary_parsing() -> str:
        workflow = RERUN_WORKFLOW.read_text(encoding="utf-8")
        start = workflow.index('          neutral_summary_raw="$(jq -er \\\n')
        end = workflow.index('          producer_id="$(jq -er', start)
        return textwrap.dedent(workflow[start:end])

    @staticmethod
    def _rerun_detail_summary_parsing() -> str:
        workflow = RERUN_WORKFLOW.read_text(encoding="utf-8")
        function = workflow.index("          validate_neutral_snapshot() {")
        start = workflow.index(
            '            snapshot_summary="$(jq -cer \\\n', function
        )
        end = workflow.index('            jq -e \\\n', start)
        return textwrap.dedent(workflow[start:end])

    @staticmethod
    def _rerun_workflow_identity_filter() -> str:
        workflow = RERUN_WORKFLOW.read_text(encoding="utf-8")
        function = workflow.index(
            "          validate_protected_run_binding() {"
        )
        marker = '              --argjson pr_number "${PR_NUMBER}" \'\n'
        start = workflow.index(marker, function) + len(marker)
        end = workflow.index('\n              \' <<<"${1}" >/dev/null', start)
        return workflow[start:end]

    @staticmethod
    def _cross_run_inventory_filter() -> str:
        workflow = RERUN_WORKFLOW.read_text(encoding="utf-8")
        assignment = '            cross_runs="$(jq -ce \\\n'
        start = workflow.index(assignment)
        marker = '              --argjson pr_number "${PR_NUMBER}" \'\n'
        start = workflow.index(marker, start) + len(marker)
        end = workflow.index(
            '\n              \' <<<"${cross_pages}")"', start
        )
        return workflow[start:end]

    @staticmethod
    def _cross_run_page_filter() -> str:
        workflow = RERUN_WORKFLOW.read_text(encoding="utf-8")
        start = workflow.index("          load_cross_inventory() {")
        marker = "            jq -e '\n"
        start = workflow.index(marker, start) + len(marker)
        end = workflow.index(
            '\n            \' <<<"${cross_pages}" >/dev/null || return 20',
            start,
        )
        return workflow[start:end]

    @staticmethod
    def _cross_attempt_two_job_filter() -> str:
        workflow = RERUN_WORKFLOW.read_text(encoding="utf-8")
        marker = '\n                --argjson run_id "${expected_id}" \'\n'
        start = workflow.index(marker) + len(marker)
        end = workflow.index(
            '\n              \' <<<"${final_cross_jobs}" >/dev/null || return 1',
            start,
        )
        return workflow[start:end]

    @staticmethod
    def _canonical_producer_identity_filter() -> str:
        workflow = RERUN_WORKFLOW.read_text(encoding="utf-8")
        start = workflow.index(
            '            jq -e \\\n'
            '              --arg actor "${author}" \\\n'
            '              --arg head_sha "${EXPECTED_HEAD}" \\\n'
            '              --argjson attempt "${producer_attempt}" \\\n'
        )
        marker = '              --arg run_url "${producer_url}" \'\n'
        start = workflow.index(marker, start) + len(marker)
        end = workflow.index('\n              \' <<<"${producer}" >/dev/null', start)
        return workflow[start:end]

    @staticmethod
    def _rerun_shell_function(name: str) -> str:
        workflow = RERUN_WORKFLOW.read_text(encoding="utf-8")
        marker = f"          {name}() {{\n"
        start = workflow.index(marker)
        end = workflow.index("\n          }\n", start) + len(
            "\n          }\n"
        )
        return textwrap.dedent(workflow[start:end])

    @staticmethod
    def _producer_attempt_provenance_guard() -> str:
        workflow = RERUN_WORKFLOW.read_text(encoding="utf-8")
        start = workflow.index('          producer_attempt="$(jq -er \\\n')
        end = workflow.index(
            '          if [ "${evidence_version}" = v4 ]; then\n'
            '            test "${producer_attempt}" -eq 1',
            start,
        )
        return textwrap.dedent(workflow[start:end])

    @staticmethod
    def _producer_terminal_shape_guard() -> str:
        return CopilotReviewRefreshTests._rerun_shell_function(
            "validate_producer_terminal_shape"
        )

    @staticmethod
    def _canonical_producer_job_binding_checks() -> str:
        workflow = RERUN_WORKFLOW.read_text(encoding="utf-8")
        start = workflow.index('          bound_producer_jobs="$(jq -c \\\n')
        end = workflow.index('          producer_binding="$(jq -c \'\n', start)
        return textwrap.dedent(workflow[start:end])

    @staticmethod
    def _cross_run(
        run_id: int,
        created_at: str,
        *,
        attempt: int = 1,
        status: str = "completed",
        conclusion: str | None = "success",
        actor: str = "litroc",
        triggering_actor: str | None = None,
        base_sha: str | None = None,
        head_sha: str | None = None,
        path: str = (
            ".github/workflows/dot-github-current-revision-required.yml"
        ),
    ) -> dict[str, object]:
        repository = "lightning-it/.github"
        api_url = "https://api.github.example"
        server_url = "https://github.example"
        resolved_base = base_sha or "a" * 40
        resolved_head = head_sha or "b" * 40
        trigger = triggering_actor
        if trigger is None:
            trigger = actor if attempt == 1 else "github-actions[bot]"
        return {
            "id": run_id,
            "created_at": created_at,
            "event": "pull_request_target",
            "path": path,
            "display_title": (
                f"Cross-protect .github PR #554 reopened {resolved_head}"
            ),
            "head_branch": "fix/final",
            "head_sha": resolved_head,
            "run_attempt": attempt,
            "status": status,
            "conclusion": conclusion,
            "workflow_id": 337993808,
            "workflow_url": (
                f"{api_url}/repos/{repository}/actions/required_workflows/"
                "337993808"
            ),
            "html_url": (
                f"{server_url}/{repository}/actions/runs/{run_id}"
            ),
            "actor": {"login": actor},
            "triggering_actor": {"login": trigger},
            "pull_requests": [
                {
                    "number": 554,
                    "url": f"{api_url}/repos/{repository}/pulls/554",
                    "base": {
                        "ref": "develop",
                        "sha": resolved_base,
                        "repo": {"url": f"{api_url}/repos/{repository}"},
                    },
                    "head": {
                        "ref": "fix/final",
                        "sha": resolved_head,
                        "repo": {"url": f"{api_url}/repos/{repository}"},
                    },
                }
            ],
        }

    @staticmethod
    def _protected_run(
        *,
        attempt: int = 1,
        status: str = "completed",
        conclusion: str | None = "failure",
    ) -> dict[str, object]:
        repository = "lightning-it/.github"
        api_url = "https://api.github.example"
        base = "a" * 40
        head = "b" * 40
        actor = "litroc"
        run_id = 900
        return {
            "id": run_id,
            "event": "pull_request_target",
            "path": (
                ".github/workflows/"
                "supplementary-current-revision-required.yml"
            ),
            "workflow_id": 337993808,
            "workflow_url": (
                f"{api_url}/repos/{repository}/actions/workflows/337993808"
            ),
            "head_branch": "fix/final",
            "head_sha": head,
            "html_url": (
                f"https://github.example/{repository}/actions/runs/{run_id}"
            ),
            "run_attempt": attempt,
            "status": status,
            "conclusion": conclusion,
            "actor": {"login": actor},
            "triggering_actor": {
                "login": actor if attempt == 1 else "github-actions[bot]"
            },
            "pull_requests": [
                {
                    "number": 554,
                    "url": f"{api_url}/repos/{repository}/pulls/554",
                    "base": {
                        "ref": "develop",
                        "sha": base,
                        "repo": {"url": f"{api_url}/repos/{repository}"},
                    },
                    "head": {
                        "ref": "fix/final",
                        "sha": head,
                        "repo": {"url": f"{api_url}/repos/{repository}"},
                    },
                }
            ],
        }

    @staticmethod
    def _protected_jobs(
        *,
        attempt: int = 1,
        required_status: str = "completed",
        required_conclusion: str | None = "success",
    ) -> dict[str, object]:
        run_id = 900
        head = "b" * 40
        jobs = [
            {
                "id": 901,
                "name": "Route protected current-revision verification",
                "run_id": run_id,
                "head_sha": head,
                "run_attempt": attempt,
                "status": "completed",
                "conclusion": "success",
            },
            {
                "id": 902,
                "name": "Authorize exact Supplementary catch-up v5 successor",
                "run_id": run_id,
                "head_sha": head,
                "run_attempt": attempt,
                "status": "completed",
                "conclusion": "skipped",
            },
            {
                "id": 903,
                "name": "Required current-revision workflow",
                "run_id": run_id,
                "head_sha": head,
                "run_attempt": attempt,
                "status": required_status,
                "conclusion": required_conclusion,
            },
        ]
        return {"total_count": len(jobs), "jobs": jobs}

    def _evaluate_cross_inventory(
        self, runs: list[dict[str, object]]
    ) -> subprocess.CompletedProcess[str]:
        repository = "lightning-it/.github"
        pages = [{"total_count": len(runs), "workflow_runs": runs}]
        page_result = self._evaluate_cross_pages(pages)
        if page_result.returncode != 0:
            return page_result
        return subprocess.run(
            [
                self._test_tool("jq"),
                "-ce",
                "--arg",
                "api_url",
                "https://api.github.example",
                "--arg",
                "author",
                "litroc",
                "--arg",
                "base_ref",
                "develop",
                "--arg",
                "base_sha",
                "a" * 40,
                "--arg",
                "head_ref",
                "fix/final",
                "--arg",
                "head_sha",
                "b" * 40,
                "--arg",
                "repository",
                repository,
                "--arg",
                "server_url",
                "https://github.example",
                "--argjson",
                "pr_number",
                "554",
                self._cross_run_inventory_filter(),
            ],
            input=json.dumps(pages),
            text=True,
            capture_output=True,
            check=False,
            env={"PATH": TEST_TOOL_PATH},
        )

    def _evaluate_cross_pages(
        self, pages: list[dict[str, object]]
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                self._test_tool("jq"),
                "-e",
                self._cross_run_page_filter(),
            ],
            input=json.dumps(pages),
            text=True,
            capture_output=True,
            check=False,
            env={"PATH": TEST_TOOL_PATH},
        )

    def _evaluate_cross_inventory_shell(
        self, pages: list[dict[str, object]]
    ) -> subprocess.CompletedProcess[str]:
        script = r'''set -euo pipefail
cross_pages="$(cat)"
jq -e "${CROSS_PAGE_FILTER}" <<<"${cross_pages}" >/dev/null
jq -ce \
  --arg api_url "${GITHUB_API_URL}" \
  --arg author "${author}" \
  --arg base_ref "${base_ref}" \
  --arg base_sha "${EXPECTED_BASE}" \
  --arg head_ref "${head_ref}" \
  --arg head_sha "${EXPECTED_HEAD}" \
  --arg repository "${REPOSITORY}" \
  --arg server_url "${GITHUB_SERVER_URL}" \
  --argjson pr_number "${PR_NUMBER}" \
  "${CROSS_INVENTORY_FILTER}" <<<"${cross_pages}" >/dev/null
printf 'POST_AUTHORIZED\n'
'''
        return subprocess.run(
            [self._test_tool("bash"), "-c", script],
            input=json.dumps(pages),
            text=True,
            capture_output=True,
            check=False,
            env={
                "PATH": TEST_TOOL_PATH,
                "CROSS_PAGE_FILTER": self._cross_run_page_filter(),
                "CROSS_INVENTORY_FILTER": (
                    self._cross_run_inventory_filter()
                ),
                "GITHUB_API_URL": "https://api.github.example",
                "GITHUB_SERVER_URL": "https://github.example",
                "REPOSITORY": "lightning-it/.github",
                "PR_NUMBER": "554",
                "EXPECTED_BASE": "a" * 40,
                "EXPECTED_HEAD": "b" * 40,
                "author": "litroc",
                "base_ref": "develop",
                "head_ref": "fix/final",
            },
        )

    def _run_cross_rerun_authorization(
        self,
        *,
        cross: dict[str, object],
        inventory: list[dict[str, object]],
        live_pr: dict[str, object],
        neutral: dict[str, object],
        neutral_summary_raw: str,
        reservation: dict[str, object],
        expected_neutral: dict[str, object] | None = None,
        expected_reservation: dict[str, object] | None = None,
        neutral_authorized: bool = True,
        reservation_pages: list[dict[str, object]] | None = None,
        deadline_expired: bool = False,
        cross_job: dict[str, object] | None = None,
        protected: dict[str, object] | None = None,
        protected_jobs: dict[str, object] | None = None,
        protected_sequence: list[dict[str, object]] | None = None,
        protected_jobs_sequence: list[dict[str, object]] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        frozen_neutral = expected_neutral or neutral
        frozen_reservation = expected_reservation or reservation
        inventory_pages = (
            reservation_pages
            if reservation_pages is not None
            else [{"total_count": 1, "check_runs": [frozen_reservation]}]
        )
        selected_job = (
            cross_job
            if cross_job is not None
            else {
                "id": 98563887790,
                "name": "Required dot-github current-revision workflow",
                "run_id": int(cross["id"]),
                "head_sha": "b" * 40,
                "run_attempt": 1,
                "status": "completed",
                "conclusion": "failure",
            }
        )
        producer = protected or self._protected_run(
            status="completed", conclusion="success"
        )
        producer_jobs = protected_jobs or self._protected_jobs(
            attempt=int(producer["run_attempt"])
        )
        producer_sequence = protected_sequence or [producer]
        producer_jobs_sequence = protected_jobs_sequence or [producer_jobs]
        script = "\n".join(
            (
                "set -euo pipefail",
                self._rerun_shell_function("require_deadline"),
                self._rerun_shell_function("bounded_gh_api"),
                self._rerun_shell_function("bounded_sleep"),
                self._rerun_shell_function("validate_live_pr_snapshot"),
                self._rerun_shell_function("validate_reservation_snapshot"),
                self._rerun_shell_function(
                    "load_reservation_inventory_snapshot"
                ),
                self._rerun_shell_function("validate_protected_run_binding"),
                self._rerun_shell_function(
                    "validate_reservation_producer_jobs"
                ),
                self._rerun_shell_function(
                    "capture_reservation_producer_success"
                ),
                self._rerun_shell_function(
                    "wait_for_stable_reservation_producer_success"
                ),
                self._rerun_shell_function("validate_neutral_snapshot"),
                self._rerun_shell_function("validate_cross_run_binding"),
                self._rerun_shell_function(
                    "validate_cross_rerun_authorization"
                ),
                self._rerun_shell_function(
                    "authorize_cross_rerun_transaction"
                ),
                "claim_review_operation() { :; }",
                self._rerun_shell_function("rerun_cross_job_once"),
                FAKE_TIMEOUT_PASSTHROUGH,
                r'''revalidate_neutral_authorization() {
  printf 'ORDER:neutral\n' >&2
  test "${NEUTRAL_AUTHORIZED}" = true || return 1
  printf '%s\n' "${NEUTRAL}"
}
sequence_item() {
  local index state_file="${1}" values="${2}"
  index="$(cat "${state_file}")"
  printf '%s' "$((index + 1))" >"${state_file}"
  jq -ce --argjson index "${index}" '.[$index] // .[-1]' <<<"${values}"
}
read_run_with_retry() {
  if [ "${1}" = "${run_id}" ]; then
    printf 'ORDER:protected_detail\n' >&2
    sequence_item "${PROTECTED_STATE_FILE}" "${PROTECTED_SEQUENCE}"
  else
    test "${1}" = "${cross_run_id}" || return 88
    printf 'ORDER:cross_detail\n' >&2
    printf '%s\n' "${CROSS}"
  fi
}
load_cross_inventory_with_retry() {
  printf 'ORDER:cross_inventory\n' >&2
  printf '%s\n' "${INVENTORY}"
}
load_cross_attempt_one_failed_job_with_retry() {
  printf 'ORDER:cross_job\n' >&2
  printf '%s\n' "${CROSS_JOB}"
}
gh() {
  local endpoint="${!#}"
  if [ "${2:-}" = --method ]; then
    test "${3:-}" = POST || return 88
    test "${endpoint}" = \
      "repos/${REPOSITORY}/actions/jobs/${cross_job_id}/rerun" || return 88
    printf 'ORDER:POST\n' >&2
  elif [ "${endpoint}" = "repos/${REPOSITORY}/pulls/${PR_NUMBER}" ]; then
    printf 'ORDER:pr\n' >&2
    printf '%s\n' "${LIVE_PR}"
  elif [[ "${endpoint}" == *"check_name=Protected%20current-revision%20verifier"* ]]; then
    printf 'ORDER:reservation_inventory\n' >&2
    printf '%s\n' "${RESERVATION_PAGES}"
  elif [ "${endpoint}" = "repos/${REPOSITORY}/check-runs/${reservation_id}" ]; then
    printf 'ORDER:reservation\n' >&2
    printf '%s\n' "${RESERVATION}"
  elif [[ "${endpoint}" == "repos/${REPOSITORY}/actions/runs/${run_id}/attempts/"*"/jobs?filter=all&per_page=100" ]]; then
    printf 'ORDER:protected_jobs\n' >&2
    sequence_item "${PROTECTED_JOBS_STATE_FILE}" "${PROTECTED_JOBS_SEQUENCE}"
  else
    printf 'unexpected fake gh endpoint: %s\n' "${endpoint}" >&2
    return 88
  fi
}
sleep() { printf 'ORDER:sleep:%s\n' "${1}" >&2; }''',
                'if [ "${DEADLINE_EXPIRED}" = true ]; then '
                "OPERATION_DEADLINE=${SECONDS}; else "
                "OPERATION_DEADLINE=$((SECONDS + 100)); fi",
                "rerun_cross_job_once",
                "printf 'POST_AUTHORIZED\\n'",
            )
        )
        cross_run_id = int(cross["id"])
        with tempfile.TemporaryDirectory() as temp_dir:
            producer_state = Path(temp_dir) / "producer-state"
            producer_jobs_state = Path(temp_dir) / "producer-jobs-state"
            producer_state.write_text("0", encoding="utf-8")
            producer_jobs_state.write_text("0", encoding="utf-8")
            result = subprocess.run(
                [self._test_tool("bash"), "-c", script],
                text=True,
                capture_output=True,
                check=False,
                env={
                    "PATH": TEST_TOOL_PATH,
                    "GITHUB_API_URL": "https://api.github.example",
                    "GITHUB_SERVER_URL": "https://github.example",
                    "REPOSITORY": "lightning-it/.github",
                    "PR_NUMBER": "554",
                    "EXPECTED_BASE": "a" * 40,
                    "EXPECTED_HEAD": "b" * 40,
                    "author": "litroc",
                    "base_ref": "develop",
                    "head_ref": "fix/final",
                    "run_id": "900",
                    "verifier_run_url": (
                        "https://github.example/lightning-it/.github/"
                        "actions/runs/900"
                    ),
                    "cross_job_id": "98563887790",
                    "cross_run_id": str(cross_run_id),
                    "cross_created_at": str(cross["created_at"]),
                    "reservation_id": str(frozen_reservation["id"]),
                    "reservation_url": str(frozen_reservation["details_url"]),
                    "reservation_external_id": str(
                        frozen_reservation["external_id"]
                    ),
                    "neutral_check_id": str(frozen_neutral["id"]),
                    "neutral_head_sha": "b" * 40,
                    "neutral_details_url": str(
                        frozen_neutral["details_url"]
                    ),
                    "neutral_external_id": str(
                        frozen_neutral["external_id"]
                    ),
                    "neutral_summary_raw": neutral_summary_raw,
                    "evidence_version": "v6",
                    "producer_id": "77",
                    "producer_url": (
                        "https://github.example/lightning-it/.github/"
                        "actions/runs/77"
                    ),
                    "expected_review_path": (
                        "applicable Copilot or governed automation exemption"
                    ),
                    "controller_sha": "c" * 40,
                    "v4_input_sha256": "",
                    "v4_workflow_sha": "",
                    "LIVE_PR": json.dumps(live_pr, separators=(",", ":")),
                    "RESERVATION": json.dumps(
                        reservation, separators=(",", ":")
                    ),
                    "CROSS": json.dumps(cross, separators=(",", ":")),
                    "PROTECTED": json.dumps(
                        producer, separators=(",", ":")
                    ),
                    "PROTECTED_JOBS": json.dumps(
                        producer_jobs, separators=(",", ":")
                    ),
                    "PROTECTED_SEQUENCE": json.dumps(
                        producer_sequence, separators=(",", ":")
                    ),
                    "PROTECTED_JOBS_SEQUENCE": json.dumps(
                        producer_jobs_sequence, separators=(",", ":")
                    ),
                    "PROTECTED_STATE_FILE": str(producer_state),
                    "PROTECTED_JOBS_STATE_FILE": str(producer_jobs_state),
                    "CROSS_JOB": json.dumps(
                        selected_job, separators=(",", ":")
                    ),
                    "INVENTORY": json.dumps(
                        inventory, separators=(",", ":")
                    ),
                    "NEUTRAL": json.dumps(neutral, separators=(",", ":")),
                    "NEUTRAL_AUTHORIZED": str(neutral_authorized).lower(),
                    "RESERVATION_PAGES": json.dumps(
                        inventory_pages, separators=(",", ":")
                    ),
                    "DEADLINE_EXPIRED": str(deadline_expired).lower(),
                },
            )
        return result

    def _run_protected_rerun_authorization(
        self,
        *,
        protected: dict[str, object],
        live_pr: dict[str, object],
        reservation: dict[str, object],
        expected_reservation: dict[str, object] | None = None,
        neutral_authorized: bool = True,
        deadline_expired: bool = False,
        cross_inventory: object | None = None,
    ) -> subprocess.CompletedProcess[str]:
        frozen_reservation = expected_reservation or reservation
        frozen_cross = [self._cross_run(700, "2026-09-05T10:00:00Z")]
        live_cross = frozen_cross if cross_inventory is None else cross_inventory
        reservation_pages = [
            {"total_count": 1, "check_runs": [frozen_reservation]}
        ]
        script = "\n".join(
            (
                "set -euo pipefail",
                self._rerun_shell_function("require_deadline"),
                self._rerun_shell_function("bounded_gh_api"),
                self._rerun_shell_function("validate_live_pr_snapshot"),
                self._rerun_shell_function("validate_reservation_snapshot"),
                self._rerun_shell_function(
                    "load_reservation_inventory_snapshot"
                ),
                self._rerun_shell_function(
                    "validate_protected_cross_inventory"
                ),
                self._rerun_shell_function("validate_protected_run_binding"),
                self._rerun_shell_function(
                    "authorize_protected_rerun_transaction"
                ),
                "claim_review_operation() { :; }",
                self._rerun_shell_function(
                    "rerun_protected_verifier_once"
                ),
                FAKE_TIMEOUT_PASSTHROUGH,
                r'''revalidate_neutral_authorization() {
  printf 'ORDER:neutral\n' >&2
  test "${NEUTRAL_AUTHORIZED}" = true || return 1
  printf '{}\n'
}
read_run_with_retry() {
  printf 'ORDER:protected_detail\n' >&2
  printf '%s\n' "${PROTECTED}"
}
load_cross_inventory_with_retry() {
  if [ "${protected_cross_inventory:-[]}" = '[]' ]; then
    printf 'ORDER:initial_cross_inventory\n' >&2
    printf '%s\n' "${EXPECTED_CROSS_INVENTORY}"
  else
    printf 'ORDER:cross_inventory\n' >&2
    printf '%s\n' "${CROSS_INVENTORY}"
  fi
}
gh() {
  local endpoint="${!#}"
  if [ "${2:-}" = --method ]; then
    test "${3:-}" = POST || return 88
    test "${endpoint}" = \
      "repos/${REPOSITORY}/actions/runs/${run_id}/rerun" || return 88
    printf 'ORDER:POST\n' >&2
  elif [ "${endpoint}" = "repos/${REPOSITORY}/pulls/${PR_NUMBER}" ]; then
    printf 'ORDER:pr\n' >&2
    printf '%s\n' "${LIVE_PR}"
  elif [[ "${endpoint}" == *"check_name=Protected%20current-revision%20verifier"* ]]; then
    printf 'ORDER:reservation_inventory\n' >&2
    printf '%s\n' "${RESERVATION_PAGES}"
  elif [ "${endpoint}" = "repos/${REPOSITORY}/check-runs/${reservation_id}" ]; then
    printf 'ORDER:reservation\n' >&2
    printf '%s\n' "${RESERVATION}"
  else
    printf 'unexpected fake gh endpoint: %s\n' "${endpoint}" >&2
    return 88
  fi
}''',
                'if [ "${DEADLINE_EXPIRED}" = true ]; then '
                "OPERATION_DEADLINE=${SECONDS}; else "
                "OPERATION_DEADLINE=$((SECONDS + 100)); fi",
                "protected_cross_inventory='[]'",
                'protected_cross_inventory="$(load_cross_inventory_with_retry)"',
                'validate_protected_cross_inventory "${protected_cross_inventory}"',
                "rerun_protected_verifier_once",
                "printf 'POST_AUTHORIZED\\n'",
            )
        )
        return subprocess.run(
            [self._test_tool("bash"), "-c", script],
            text=True,
            capture_output=True,
            check=False,
            env={
                "PATH": TEST_TOOL_PATH,
                "GITHUB_API_URL": "https://api.github.example",
                "GITHUB_SERVER_URL": "https://github.example",
                "REPOSITORY": "lightning-it/.github",
                "PR_NUMBER": "554",
                "EXPECTED_BASE": "a" * 40,
                "EXPECTED_HEAD": "b" * 40,
                "author": "litroc",
                "base_ref": "develop",
                "head_ref": "fix/final",
                "run_id": "900",
                "verifier_run_url": (
                    "https://github.example/lightning-it/.github/"
                    "actions/runs/900"
                ),
                "reservation_id": str(frozen_reservation["id"]),
                "reservation_url": str(frozen_reservation["details_url"]),
                "reservation_external_id": str(
                    frozen_reservation["external_id"]
                ),
                "LIVE_PR": json.dumps(live_pr, separators=(",", ":")),
                "RESERVATION": json.dumps(
                    reservation, separators=(",", ":")
                ),
                "RESERVATION_PAGES": json.dumps(
                    reservation_pages, separators=(",", ":")
                ),
                "PROTECTED": json.dumps(
                    protected, separators=(",", ":")
                ),
                "EXPECTED_CROSS_INVENTORY": json.dumps(
                    frozen_cross, separators=(",", ":")
                ),
                "CROSS_INVENTORY": json.dumps(
                    live_cross, separators=(",", ":")
                ),
                "NEUTRAL_AUTHORIZED": str(neutral_authorized).lower(),
                "DEADLINE_EXPIRED": str(deadline_expired).lower(),
            },
        )

    def _run_refresh_filter(
        self,
        *,
        author: str,
        external_id: str,
        pull_request_number: int | None,
        owner_pr_number: int = 123,
        repository: str = "lightning-it/.github",
        review_path: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        base = "a" * 40
        head = "b" * 40
        summary: dict[str, object] = {
            "schema": 4,
            "base_sha": base,
            "head_sha": head,
            "producer_run_id": 77,
        }
        if pull_request_number is not None:
            summary["pull_request_number"] = pull_request_number
        if review_path is not None:
            summary["review_path"] = review_path
        check = {
            "status": "completed",
            "conclusion": "success",
            "details_url": "https://github.example/runs/42",
            "external_id": external_id,
            "output": {"summary": json.dumps(summary)},
        }
        try:
            return subprocess.run(
                [
                    self._test_tool("jq"),
                    "-e",
                    "--arg",
                    "author",
                    author,
                    "--arg",
                    "base",
                    base,
                    "--arg",
                    "current_kind",
                    ("renovate" if author == "renovate[bot]" else
                     "ancestry-backmerge" if "ancestry-backmerge" in external_id else
                     "managed-sync" if "managed-sync" in external_id else "copilot"),
                    "--arg",
                    "head",
                    head,
                    "--arg",
                    "pr",
                    "123",
                    "--arg",
                    "owner_pr",
                    str(owner_pr_number),
                    "--arg",
                    "repository",
                    repository,
                    "--argjson",
                    "pr_number",
                    "123",
                    "--argjson",
                    "owner_pr_number",
                    str(owner_pr_number),
                    "--arg",
                    "owner_run_id",
                    "77",
                    "--arg",
                    "url",
                    "https://github.example/runs/42",
                    self._refresh_validation_filter(),
                ],
                input=json.dumps([check]),
                text=True,
                capture_output=True,
                check=False,
            )
        except FileNotFoundError as error:
            self.fail(f"jq is required to validate refresh evidence: {error}")

    def test_event_specific_payloads_are_guarded(self) -> None:
        workflow = REFRESH_WORKFLOW.read_text(encoding="utf-8")

        self.assertTrue(
            workflow.startswith(
                "# Owned by the protected lightning-it/.github controller.\n"
                "# Generic shared-assets sync must preserve this "
                "repository-specific file.\n"
            )
        )
        self.assertNotIn("Do not edit downstream copies directly.", workflow)
        self.assertNotIn("EVENT_PATH: ${{ github.event_path }}", workflow)
        self.assertIn("' \"${GITHUB_EVENT_PATH}\" >/dev/null", workflow)

        self.assertEqual(
            1,
            workflow.count("github.event_name == 'pull_request_review' &&"),
        )
        self.assertEqual(
            1,
            workflow.count(
                "github.event_name == 'pull_request_review_comment' &&"
            ),
        )
        self.assertEqual(
            1,
            workflow.count(
                "github.event.review.user.login == "
                "'copilot-pull-request-reviewer[bot]'"
            ),
        )
        self.assertEqual(
            1,
            workflow.count(
                "github.event.comment.user.login == "
                "'copilot-pull-request-reviewer[bot]'"
            ),
        )
        self.assertEqual(2, workflow.count("github.actor == 'litroc'"))
        self.assertEqual(
            1,
            workflow.count("github.event.review.user.login == 'litroc'"),
        )
        self.assertEqual(
            1,
            workflow.count("github.event.comment.user.login == 'litroc'"),
        )

    def test_refresh_event_authorization_is_fail_closed(self) -> None:
        jq = self._test_tool("jq")
        repository = "lightning-it/.github"

        def accepted(
            event: str,
            actor: str,
            *,
            login: str,
            action: str | None = None,
            association: str = "NONE",
            draft: bool = False,
            head_repository: str = repository,
            sender_login: str | None = None,
        ) -> bool:
            subject = {"user": {"login": login}, "author_association": association}
            if action is None:
                action = (
                    "submitted"
                    if event == "pull_request_review"
                    else "created"
                )
            payload: dict[str, object] = {
                "action": action,
                "pull_request": {
                    "draft": draft,
                    "head": {"repo": {"full_name": head_repository}},
                },
                "sender": {"login": sender_login or actor},
            }
            if event == "pull_request_review":
                payload["review"] = subject
            elif event == "pull_request_review_comment":
                payload["comment"] = subject
            result = subprocess.run(
                [
                    jq,
                    "-e",
                    "--arg",
                    "actor",
                    actor,
                    "--arg",
                    "event",
                    event,
                    "--arg",
                    "repository",
                    repository,
                    self._refresh_event_authorization_filter(),
                ],
                input=json.dumps(payload),
                text=True,
                capture_output=True,
                check=False,
            )
            return result.returncode == 0

        for event in ("pull_request_review", "pull_request_review_comment"):
            with self.subTest(event=event, actor="litroc"):
                self.assertTrue(accepted(event, "litroc", login="litroc"))
                self.assertFalse(accepted(event, "litroc", login="other"))
                self.assertFalse(accepted(event, "other", login="litroc"))
            with self.subTest(event=event, actor="Copilot"):
                self.assertTrue(
                    accepted(
                        event,
                        "Copilot",
                        login="copilot-pull-request-reviewer[bot]",
                    )
                )
                self.assertFalse(
                    accepted(event, "Copilot", login="untrusted-reviewer")
                )
            with self.subTest(event=event, association="MEMBER"):
                self.assertTrue(
                    accepted(event, "maintainer", login="maintainer", association="MEMBER")
                )
                self.assertFalse(
                    accepted(event, "other", login="maintainer", association="MEMBER")
                )
            destructive_action = (
                "dismissed"
                if event == "pull_request_review"
                else "deleted"
            )
            with self.subTest(event=event, action=destructive_action):
                self.assertTrue(
                    accepted(
                        event,
                        "dismisser",
                        action=destructive_action,
                        login="maintainer",
                        association="MEMBER",
                    )
                )
                self.assertFalse(
                    accepted(
                        event,
                        "dismisser",
                        action=destructive_action,
                        login="maintainer",
                        association="MEMBER",
                        sender_login="other",
                    )
                )
                self.assertFalse(
                    accepted(
                        event,
                        "dismisser",
                        action=destructive_action,
                        login="untrusted",
                    )
                )
            self.assertFalse(
                accepted(event, "litroc", action="unknown", login="litroc")
            )
            self.assertFalse(
                accepted(event, "litroc", login="litroc", draft=True)
            )
            self.assertFalse(
                accepted(
                    event,
                    "litroc",
                    login="litroc",
                    head_repository="attacker/fork",
                )
            )
        self.assertFalse(
            accepted("workflow_dispatch", "litroc", login="litroc")
        )

    def test_refresh_preserves_every_supported_protected_evidence_version(self) -> None:
        workflow = REFRESH_WORKFLOW.read_text(encoding="utf-8")

        self.assertIn(
            "PR_AUTHOR: ${{ github.event.pull_request.user.login }}", workflow
        )
        for evidence_prefix in (
            "mlx90-current-revision:copilot:v6:",
            "mlx90-current-revision:managed-sync:v6:",
            "mlx90-current-revision:ancestry-backmerge:v6:",
            "mlx90-current-revision:copilot:v5:",
            "mlx90-current-revision:ancestry-backmerge:v5:",
            "mlx90-current-revision:v4:",
        ):
            self.assertIn(evidence_prefix, workflow)
        self.assertIn('has("pull_request_number")', workflow)
        self.assertIn('$summary.pull_request_number == $pr_number', workflow)

    def test_rerun_helper_accepts_pr_bound_and_transition_evidence(self) -> None:
        workflow = RERUN_WORKFLOW.read_text(encoding="utf-8")

        self.assertIn(
            "mlx90-current-revision:(copilot|managed-sync|ancestry-backmerge):v6", workflow
        )
        self.assertIn(
            "mlx90-current-revision:(copilot|ancestry-backmerge):v5", workflow
        )
        self.assertIn('evidence_version=v6', workflow)
        self.assertIn('evidence_version=v5', workflow)
        self.assertIn('if $evidence_version == "v6" then', workflow)
        self.assertIn('has("pull_request_number")', workflow)
        self.assertIn('.pull_request_number == $pr_number', workflow)
        self.assertIn("lightning-it-shared-assets-sync[bot]", workflow)
        self.assertIn("lightning-it/.github", workflow)
        self.assertIn('[ "${external_kind}" = managed-sync ]', workflow)
        self.assertIn('test "${base_ref}" = develop', workflow)
        self.assertIn(
            "test \"${author}\" != 'lightning-it-shared-assets-sync[bot]'",
            workflow,
        )
        self.assertIn('prefix "rep60-required-workflow:v3:"', workflow)
        self.assertIn(
            '":${PR_NUMBER}:${EXPECTED_BASE}:${EXPECTED_HEAD}"', workflow
        )
        self.assertIn(
            "^rep60-required-workflow:v3:([1-9][0-9]*):${PR_NUMBER}:"
            "${EXPECTED_BASE}:${EXPECTED_HEAD}$",
            workflow,
        )
        self.assertIn('prefix "rep60-required-workflow:v2:"', workflow)
        self.assertIn(
            "^rep60-required-workflow:v2:([1-9][0-9]*):${PR_NUMBER}:"
            "${EXPECTED_HEAD}$",
            workflow,
        )
        self.assertIn(
            "Protected verifier evidence is missing or version-ambiguous.",
            workflow,
        )
        self.assertIn(
            '[ "${v3_count}" -eq 1 ] && [ "${v2_count}" -eq 0 ]',
            workflow,
        )
        self.assertIn(
            '[ "${v3_count}" -eq 0 ] && [ "${v2_count}" -eq 1 ]',
            workflow,
        )

    def test_rerun_parses_live_check_list_and_detail_summaries(self) -> None:
        summary = {"schema": 4, "producer_run_id": 77}
        summary_raw = json.dumps(summary, separators=(",", ":"))

        def run(
            representation: str, summary_value: object
        ) -> subprocess.CompletedProcess[str]:
            check_run = {"output": {"summary": summary_value}}
            if representation == "list":
                payload = [check_run]
                input_name = "neutral"
                output_name = "neutral_summary"
                parser = self._rerun_list_summary_parsing()
            else:
                payload = check_run
                input_name = "snapshot"
                output_name = "snapshot_summary"
                parser = self._rerun_detail_summary_parsing()
            script = "\n".join(
                (
                    "set -euo pipefail",
                    f'{input_name}="${{SUMMARY_PAYLOAD}}"',
                    parser,
                    f'printf "%s\\n" "${{{output_name}}}"',
                )
            )
            return subprocess.run(
                [self._test_tool("bash"), "-c", script],
                text=True,
                capture_output=True,
                check=False,
                env={
                    "PATH": TEST_TOOL_PATH,
                    "SUMMARY_PAYLOAD": json.dumps(
                        payload, separators=(",", ":")
                    ),
                },
            )

        for representation in ("list", "detail"):
            with self.subTest(representation=representation, case="valid"):
                accepted = run(representation, summary_raw)
                self.assertEqual(0, accepted.returncode, accepted.stderr)
                self.assertEqual(summary, json.loads(accepted.stdout))

        invalid_summaries = (
            ("api-object", summary),
            ("empty", ""),
            ("invalid-json", "not-json"),
            ("array", "[]"),
            ("scalar", "42"),
        )
        for representation in ("list", "detail"):
            for case, invalid_summary in invalid_summaries:
                with self.subTest(representation=representation, case=case):
                    rejected = run(representation, invalid_summary)
                    self.assertNotEqual(0, rejected.returncode)

    def test_rerun_helper_binds_central_and_distributed_workflow_urls(self) -> None:
        workflow = RERUN_WORKFLOW.read_text(encoding="utf-8")

        self.assertIn(
            'if $repository == "lightning-it/.github" then',
            workflow,
        )
        self.assertIn(
            '$api_url + "/repos/" + $repository + "/actions/workflows/"',
            workflow,
        )
        self.assertIn(
            '+ "/actions/required_workflows/"', workflow
        )

        def validate(repository: str, workflow_url: str) -> int:
            run = {
                "id": 42,
                "event": "pull_request_target",
                "path": ".github/workflows/supplementary-current-revision-required.yml",
                "workflow_id": 337993808,
                "workflow_url": workflow_url,
                "head_branch": "fix/final",
                "head_sha": "b" * 40,
                "run_attempt": 1,
                "html_url": f"https://github.example/{repository}/actions/runs/42",
                "actor": {"login": "litroc"},
                "triggering_actor": {"login": "litroc"},
                "pull_requests": [
                    {
                        "number": 220,
                        "url": f"https://api.github.example/repos/{repository}/pulls/220",
                        "base": {
                            "ref": "develop",
                            "sha": "a" * 40,
                            "repo": {
                                "url": f"https://api.github.example/repos/{repository}"
                            },
                        },
                        "head": {
                            "ref": "fix/final",
                            "sha": "b" * 40,
                            "repo": {
                                "url": f"https://api.github.example/repos/{repository}"
                            },
                        },
                    }
                ],
                "status": "completed",
                "conclusion": "success",
            }
            result = subprocess.run(
                [
                    self._test_tool("jq"),
                    "-e",
                    "--arg",
                    "api_url",
                    "https://api.github.example",
                    "--arg",
                    "author",
                    "litroc",
                    "--arg",
                    "base_ref",
                    "develop",
                    "--arg",
                    "base_sha",
                    "a" * 40,
                    "--arg",
                    "head_ref",
                    "fix/final",
                    "--arg",
                    "head_sha",
                    "b" * 40,
                    "--arg",
                    "repository",
                    repository,
                    "--arg",
                    "run_url",
                    f"https://github.example/{repository}/actions/runs/42",
                    "--argjson",
                    "id",
                    "42",
                    "--argjson",
                    "pr_number",
                    "220",
                    self._rerun_workflow_identity_filter(),
                ],
                input=json.dumps(run),
                text=True,
                capture_output=True,
                check=False,
            )
            return result.returncode

        central = "lightning-it/.github"
        target = "lightning-it/shared-assets-lit"
        central_url = (
            f"https://api.github.example/repos/{central}/actions/workflows/337993808"
        )
        target_url = (
            f"https://api.github.example/repos/{target}"
            "/actions/required_workflows/337993808"
        )
        self.assertEqual(0, validate(central, central_url))
        self.assertEqual(0, validate(target, target_url))
        self.assertNotEqual(0, validate(central, target_url))
        self.assertNotEqual(0, validate(target, central_url))

    def test_rerun_shared_deadline_is_monotonic_and_fail_closed(self) -> None:
        workflow = RERUN_WORKFLOW.read_text(encoding="utf-8")
        deadline_seconds = int(
            workflow.split("OPERATION_DEADLINE=$((SECONDS + ", 1)[1].split(
                "))", 1
            )[0]
        )
        self.assertLess(deadline_seconds, 20 * 60)
        script = "\n".join(
            (
                "set -euo pipefail",
                self._rerun_shell_function("require_deadline"),
                self._rerun_shell_function("bounded_sleep"),
                "sleep() { :; }",
                "SECONDS=10",
                "OPERATION_DEADLINE=$((SECONDS + 5))",
                "bounded_sleep 2",
                "OPERATION_DEADLINE=${SECONDS}",
                "if bounded_sleep 1; then exit 91; fi",
            )
        )
        result = subprocess.run(
            [self._test_tool("bash"), "-c", script],
            text=True,
            capture_output=True,
            check=False,
            env={"PATH": TEST_TOOL_PATH},
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("shared re-evaluation deadline", result.stderr)

    def test_bounded_api_and_post_mutation_classification(self) -> None:
        workflow = RERUN_WORKFLOW.read_text(encoding="utf-8")

        def runtime(marker: str, final_call: str) -> str:
            start = workflow.index(marker)
            end = workflow.index(final_call, start) + len(final_call)
            return textwrap.dedent(workflow[start:end])

        protected = runtime(
            "            protected_rerun_status=0\n",
            "            wait_for_protected_attempt_two_success",
        )
        cross = runtime(
            "          cross_rerun_status=0\n",
            "          wait_for_cross_attempt_two_success",
        )
        script = "\n".join(
            (
                "set -euo pipefail",
                self._rerun_shell_function("require_deadline"),
                self._rerun_shell_function("bounded_gh_api"),
                "claim_review_operation() { :; }",
                self._rerun_shell_function("rerun_protected_verifier_once"),
                "claim_review_operation() { :; }",
                self._rerun_shell_function("rerun_cross_job_once"),
                r'''claim_review_operation() { :; }
EXPECTED_HEAD=bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
EXPECTED_BASE=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
PR_NUMBER=123
cross_run_id=901
authorize_protected_rerun_transaction() { :; }
authorize_cross_rerun_transaction() { :; }
wait_for_protected_attempt_two_success() { printf 'POLL\n' >&2; }
wait_for_cross_attempt_two_success() { printf 'POLL\n' >&2; }
timeout() {
  printf 'TIMEOUT\n' >&2
  printf 'ARGS:%s\n' "$*"
  if [ "${TIMEOUT_RC}" -ne 0 ]; then return "${TIMEOUT_RC}"; fi
  while [ "${1:-}" != gh ]; do shift || return 98; done
  "$@"
}
gh() {
  printf 'GH\n' >&2
  test "${1:-}" = api || return 88
  shift
  printf 'API_OK:%s\n' "$*"
  return "${GH_RC}"
}
REPOSITORY=lightning-it/.github
run_id=900
cross_job_id=98563887790
TIMEOUT_RC=0
GH_RC=0
SECONDS=100
OPERATION_DEADLINE=$((SECONDS + 100))
out="$(bounded_gh_api repos/lightning-it/.github)"
[[ "${out}" == *'ARGS:--foreground --signal=TERM --kill-after=2s 30s gh api repos/lightning-it/.github'* \
  && "${out}" == *'API_OK:repos/lightning-it/.github'* ]]
SECONDS=100
OPERATION_DEADLINE=$((SECONDS + 10))
out="$(bounded_gh_api repos/lightning-it/.github)"
[[ "${out}" == *'ARGS:--foreground --signal=TERM --kill-after=2s 8s gh api repos/lightning-it/.github'* ]]
SECONDS=100
OPERATION_DEADLINE=$((SECONDS + 100))
TIMEOUT_RC=124
rc=0
out="$(bounded_gh_api repos/lightning-it/.github)" || rc=$?
[ "${rc}" -eq 124 ]
TIMEOUT_RC=0
''',
                "run_protected() (\nSECONDS=100\n"
                "OPERATION_DEADLINE=$((SECONDS + OFFSET))\n"
                + protected
                + "\n)",
                "run_cross() (\nSECONDS=100\n"
                "OPERATION_DEADLINE=$((SECONDS + OFFSET))\n"
                + cross
                + "\n)",
                r'''assert_budget() {
  local out
  if out="$(OFFSET="$1" GH_RC=0 "$2" 2>&1)"; then return 91; fi
  [[ "${out}" != *TIMEOUT* && "${out}" != *GH* \
    && "${out}" != *POLL* && "${out}" != *uncertain* ]]
}
assert_uncertain() {
  local out
  out="$(OFFSET=100 GH_RC=42 "$1" 2>&1)" || return 92
  [[ "${out}" == *TIMEOUT* && "${out}" == *GH* \
    && "${out}" == *POLL* && "${out}" == *uncertain* ]]
}
for r in 1 2; do
  assert_budget "${r}" run_protected
  assert_budget "${r}" run_cross
done
assert_uncertain run_protected
assert_uncertain run_cross''',
            )
        )
        result = subprocess.run(
            [self._test_tool("bash"), "-c", script],
            text=True,
            capture_output=True,
            check=False,
            env={"PATH": TEST_TOOL_PATH},
        )
        self.assertEqual(0, result.returncode, result.stderr)

    def test_completion_and_inventory_reads_retry_only_transient_failures(
        self,
    ) -> None:
        common = "\n".join(
            (
                "set -euo pipefail",
                self._rerun_shell_function("require_deadline"),
                self._rerun_shell_function("bounded_gh_api"),
                self._rerun_shell_function("bounded_sleep"),
                self._rerun_shell_function("load_cross_inventory_with_retry"),
                self._rerun_shell_function("read_run_with_retry"),
                FAKE_TIMEOUT_PASSTHROUGH,
                "sleep() { :; }",
                "OPERATION_DEADLINE=$((SECONDS + 100))",
                "REPOSITORY=lightning-it/.github",
            )
        )

        def run(body: str) -> tuple[subprocess.CompletedProcess[str], int]:
            with tempfile.TemporaryDirectory() as temp_dir:
                state_file = Path(temp_dir) / "api-attempts"
                state_file.write_text("0", encoding="utf-8")
                result = subprocess.run(
                    [self._test_tool("bash"), "-c", common + "\n" + body],
                    text=True,
                    capture_output=True,
                    check=False,
                    env={
                        "PATH": TEST_TOOL_PATH,
                        "API_STATE_FILE": str(state_file),
                    },
                )
                attempts = int(state_file.read_text(encoding="utf-8"))
            return result, attempts

        transient_inventory = r'''load_cross_inventory() {
  local count
  count="$(cat "${API_STATE_FILE}")"
  printf '%s' "$((count + 1))" >"${API_STATE_FILE}"
  if [ "${count}" -lt 2 ]; then return 10; fi
  printf '[]\n'
}
load_cross_inventory_with_retry >/dev/null
'''
        result, attempts = run(transient_inventory)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(3, attempts)

        semantic_inventory = r'''load_cross_inventory() {
  local count
  count="$(cat "${API_STATE_FILE}")"
  printf '%s' "$((count + 1))" >"${API_STATE_FILE}"
  return 20
}
if load_cross_inventory_with_retry; then exit 92; fi
'''
        result, attempts = run(semantic_inventory)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(1, attempts)

        transient_completion = r'''gh() {
  local count
  count="$(cat "${API_STATE_FILE}")"
  printf '%s' "$((count + 1))" >"${API_STATE_FILE}"
  if [ "${count}" -lt 2 ]; then
    printf 'temporary API failure\n' >&2
    return 42
  fi
  printf '{"id":202}\n'
}
read_run_with_retry 202 | jq -e '.id == 202' >/dev/null
'''
        result, attempts = run(transient_completion)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(3, attempts)

    def test_cross_inventory_selects_latest_run_independent_of_api_order(
        self,
    ) -> None:
        older = self._cross_run(
            101,
            "2026-09-05T10:00:00Z",
            conclusion="cancelled",
        )
        latest = self._cross_run(
            202,
            "2026-09-05T11:00:00Z",
            conclusion="failure",
        )
        for runs in ([older, latest], [latest, older]):
            with self.subTest(order=[run["id"] for run in runs]):
                result = self._evaluate_cross_inventory(runs)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual(
                    [101, 202],
                    [run["id"] for run in json.loads(result.stdout)],
                )

        lower_id = self._cross_run(
            303,
            "2026-09-05T12:00:00Z",
            conclusion="success",
        )
        higher_id = self._cross_run(
            404,
            "2026-09-05T12:00:00Z",
            conclusion="failure",
        )
        tied = self._evaluate_cross_inventory([higher_id, lower_id])
        self.assertEqual(0, tied.returncode, tied.stderr)
        self.assertEqual(
            [303, 404],
            [run["id"] for run in json.loads(tied.stdout)],
        )

        prior_success = self._cross_run(
            505,
            "2026-09-05T13:00:00Z",
            conclusion="success",
        )
        authoritative_cancelled = self._cross_run(
            606,
            "2026-09-05T14:00:00Z",
            conclusion="cancelled",
        )
        cancelled = self._evaluate_cross_inventory(
            [authoritative_cancelled, prior_success]
        )
        self.assertEqual(0, cancelled.returncode, cancelled.stderr)
        selected = json.loads(cancelled.stdout)[-1]
        self.assertEqual(606, selected["id"])
        self.assertEqual("cancelled", selected["conclusion"])

    def test_cross_inventory_requires_complete_consistent_unique_pages(
        self,
    ) -> None:
        first = self._cross_run(101, "2026-09-05T10:00:00Z")
        second = self._cross_run(202, "2026-09-05T11:00:00Z")
        valid_pages = [
            {"total_count": 2, "workflow_runs": [first]},
            {"total_count": 2, "workflow_runs": [second]},
        ]
        valid = self._evaluate_cross_pages(valid_pages)
        self.assertEqual(0, valid.returncode, valid.stderr)

        truncated = self._evaluate_cross_pages(
            [{"total_count": 2, "workflow_runs": [first]}]
        )
        self.assertNotEqual(0, truncated.returncode)

        inconsistent = self._evaluate_cross_pages(
            [
                {"total_count": 2, "workflow_runs": [first]},
                {"total_count": 3, "workflow_runs": [second]},
            ]
        )
        self.assertNotEqual(0, inconsistent.returncode)

        duplicate_raw_id = self._cross_run(
            101, "2026-09-05T11:00:00Z"
        )
        duplicate = self._evaluate_cross_pages(
            [
                {"total_count": 2, "workflow_runs": [first]},
                {"total_count": 2, "workflow_runs": [duplicate_raw_id]},
            ]
        )
        self.assertNotEqual(0, duplicate.returncode)

    def test_cross_inventory_accepts_terminal_priors_and_filters_wrong_bindings(
        self,
    ) -> None:
        runs = [
            self._cross_run(
                100,
                "2026-09-05T10:00:00Z",
                conclusion="success",
            ),
            self._cross_run(
                200,
                "2026-09-05T10:10:00Z",
                conclusion="failure",
            ),
            self._cross_run(
                300,
                "2026-09-05T10:20:00Z",
                conclusion="cancelled",
            ),
            self._cross_run(
                400,
                "2026-09-05T10:30:00Z",
                attempt=2,
                conclusion="success",
            ),
            self._cross_run(
                999,
                "2026-09-05T11:00:00Z",
                conclusion="failure",
                head_sha="c" * 40,
            ),
            self._cross_run(
                1000,
                "2026-09-05T11:10:00Z",
                conclusion="failure",
                path=".github/workflows/unrelated.yml",
            ),
        ]
        result = self._evaluate_cross_inventory(list(reversed(runs)))
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            [100, 200, 300, 400],
            [run["id"] for run in json.loads(result.stdout)],
        )

    def test_cross_inventory_rejects_ambiguous_or_malformed_candidates(
        self,
    ) -> None:
        cases = {
            "nonterminal prior": [
                self._cross_run(
                    100,
                    "2026-09-05T10:00:00Z",
                    status="in_progress",
                    conclusion=None,
                ),
                self._cross_run(
                    200,
                    "2026-09-05T11:00:00Z",
                    conclusion="failure",
                ),
            ],
            "malformed RFC3339": [
                self._cross_run(100, "2026-02-31T10:00:00Z")
            ],
            "attempt above two": [
                self._cross_run(
                    100,
                    "2026-09-05T10:00:00Z",
                    attempt=3,
                    triggering_actor="github-actions[bot]",
                )
            ],
            "attempt-one provenance": [
                self._cross_run(
                    100,
                    "2026-09-05T10:00:00Z",
                    triggering_actor="github-actions[bot]",
                )
            ],
            "attempt-two provenance": [
                self._cross_run(
                    100,
                    "2026-09-05T10:00:00Z",
                    attempt=2,
                    triggering_actor="litroc",
                )
            ],
            "wrong actor": [
                self._cross_run(
                    100,
                    "2026-09-05T10:00:00Z",
                    actor="mallory",
                    triggering_actor="mallory",
                )
            ],
            "duplicate ids": [
                self._cross_run(100, "2026-09-05T10:00:00Z"),
                self._cross_run(100, "2026-09-05T11:00:00Z"),
            ],
            "unknown terminal conclusion": [
                self._cross_run(
                    100,
                    "2026-09-05T10:00:00Z",
                    conclusion="neutral",
                )
            ],
            "unknown status": [
                self._cross_run(
                    100,
                    "2026-09-05T10:00:00Z",
                    status="mystery",
                    conclusion=None,
                )
            ],
        }
        for name, runs in cases.items():
            with self.subTest(case=name):
                result = self._evaluate_cross_inventory(runs)
                self.assertNotEqual(0, result.returncode, result.stdout)

    def test_cross_inventory_shell_rejects_malformed_newest_in_any_api_order(
        self,
    ) -> None:
        older = self._cross_run(
            101,
            "2026-02-28T10:00:00Z",
            conclusion="success",
        )
        malformed_newest = self._cross_run(
            202,
            "2026-02-31T11:00:00Z",
            conclusion="failure",
        )
        valid_newest = self._cross_run(
            303,
            "2026-03-01T11:00:00Z",
            conclusion="failure",
        )
        valid = self._evaluate_cross_inventory_shell(
            [{"total_count": 2, "workflow_runs": [valid_newest, older]}]
        )
        self.assertEqual(0, valid.returncode, valid.stderr)
        self.assertEqual("POST_AUTHORIZED\n", valid.stdout)
        for runs in (
            [older, malformed_newest],
            [malformed_newest, older],
        ):
            with self.subTest(order=[run["id"] for run in runs]):
                pages = [{"total_count": 2, "workflow_runs": runs}]
                result = self._evaluate_cross_inventory_shell(pages)
                self.assertNotEqual(0, result.returncode, result.stdout)
                self.assertNotIn("POST_AUTHORIZED", result.stdout)

    def test_cross_verifier_job_ledger_converges_only_to_one_failed_job(
        self,
    ) -> None:
        ledger = self._rerun_shell_function(
            "load_cross_attempt_one_failed_job_with_retry"
        )
        marker = '--argjson run_id "${cross_run_id}" \'\n'
        shape_filter = ledger.split(marker, 1)[1].split(
            '\n      \' <<<"${jobs}"', 1
        )[0]
        failed_filter = ledger.split('failed="$(jq -c \\\n', 1)[1]
        failed_filter = failed_filter.split(marker, 1)[1].split(
            '\n      \' <<<"${jobs}")"', 1
        )[0]
        jq = self._test_tool("jq")

        def evaluate(
            payload: object, jq_filter: str
        ) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                [
                    jq,
                    "-ce",
                    "--arg",
                    "head",
                    "b" * 40,
                    "--argjson",
                    "run_id",
                    "202",
                    jq_filter,
                ],
                input=json.dumps(payload),
                text=True,
                capture_output=True,
                check=False,
                env={"PATH": TEST_TOOL_PATH},
            )

        valid = {
            "total_count": 1,
            "jobs": [
                {
                    "id": 98563887790,
                    "name": "Required dot-github current-revision workflow",
                    "run_id": 202,
                    "head_sha": "b" * 40,
                    "run_attempt": 1,
                    "status": "completed",
                    "conclusion": "failure",
                }
            ],
        }
        self.assertEqual(0, evaluate(valid, shape_filter).returncode)
        failed = evaluate(valid, failed_filter)
        self.assertEqual(0, failed.returncode, failed.stderr)
        self.assertEqual([valid["jobs"][0]], json.loads(failed.stdout))

        incomplete = {"total_count": 0, "jobs": []}
        self.assertEqual(0, evaluate(incomplete, shape_filter).returncode)
        self.assertEqual(
            [], json.loads(evaluate(incomplete, failed_filter).stdout)
        )

        duplicate = json.loads(json.dumps(valid))
        duplicate["jobs"].append(json.loads(json.dumps(valid["jobs"][0])))
        duplicate["jobs"][1]["id"] += 1
        duplicate["total_count"] = 2
        self.assertEqual(
            2, len(json.loads(evaluate(duplicate, failed_filter).stdout))
        )

        duplicate_id = json.loads(json.dumps(valid))
        duplicate_id["jobs"].append(
            json.loads(json.dumps(valid["jobs"][0]))
        )
        duplicate_id["total_count"] = 2
        self.assertNotEqual(
            0, evaluate(duplicate_id, shape_filter).returncode
        )

        unrelated_failure = json.loads(json.dumps(valid))
        unrelated_failure["jobs"].append(
            {
                **json.loads(json.dumps(valid["jobs"][0])),
                "id": 98563887791,
                "name": "Unexpected failed job",
            }
        )

        unrelated_failure["total_count"] = 2
        self.assertEqual(
            2,
            len(
                json.loads(
                    evaluate(unrelated_failure, failed_filter).stdout
                )
            ),
        )

        for field, value in (
            ("run_attempt", 2), ("run_id", 203), ("head_sha", "c" * 40)
        ):
            malformed = json.loads(json.dumps(valid))
            malformed["jobs"][0][field] = value
            self.assertNotEqual(0, evaluate(malformed, shape_filter).returncode)
            self.assertEqual(
                [], json.loads(evaluate(malformed, failed_filter).stdout)
            )

    def test_cross_rerun_keeps_frozen_neutral_producer_binding(self) -> None:
        function = self._rerun_shell_function(
            "authorize_cross_rerun_transaction"
        )
        self.assertIn(
            "local live_pr neutral_snapshot reservation_run "
            "producer_rebind",
            function,
        )
        self.assertIn(
            'reservation_run="$(wait_for_stable_'
            'reservation_producer_success)"',
            function,
        )
        self.assertIn(
            'test "${producer_rebind}" = '
            '"${reservation_run}"',
            function,
        )
        self.assertNotIn(
            "local live_pr neutral_snapshot producer_binding",
            function,
        )

    def test_cross_attempt_two_ledger_is_exactly_one_successful_job(
        self,
    ) -> None:
        jq = self._test_tool("jq")
        jq_filter = self._cross_attempt_two_job_filter()

        def evaluate(payload: object) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                [
                    jq,
                    "-e",
                    "--arg",
                    "head",
                    "b" * 40,
                    "--argjson",
                    "run_id",
                    "202",
                    jq_filter,
                ],
                input=json.dumps(payload),
                text=True,
                capture_output=True,
                check=False,
                env={"PATH": TEST_TOOL_PATH},
            )

        expected_job = {
            "id": 98563887792,
            "name": "Required dot-github current-revision workflow",
            "run_id": 202,
            "head_sha": "b" * 40,
            "run_attempt": 2,
            "status": "completed",
            "conclusion": "success",
        }
        valid = {"total_count": 1, "jobs": [expected_job]}
        accepted = evaluate(valid)
        self.assertEqual(0, accepted.returncode, accepted.stderr)

        additional_job = {
            "total_count": 2,
            "jobs": [
                expected_job,
                {
                    "id": 98563887793,
                    "name": "Unexpected additional job",
                    "run_id": 202,
                    "head_sha": "b" * 40,
                    "run_attempt": 2,
                    "status": "completed",
                    "conclusion": "success",
                },
            ],
        }
        rejected = evaluate(additional_job)
        self.assertNotEqual(0, rejected.returncode, rejected.stdout)
        for field, value in (("run_id", 203), ("head_sha", "c" * 40)):
            wrong_binding = json.loads(json.dumps(valid))
            wrong_binding["jobs"][0][field] = value
            self.assertNotEqual(0, evaluate(wrong_binding).returncode)

    def test_canonical_producer_attempt_two_is_native_and_job_bound(self) -> None:
        jq = self._test_tool("jq")
        identity_filter = self._canonical_producer_identity_filter()
        head = "b" * 40
        producer = {
            "event": "pull_request_target",
            "path": ".github/workflows/copilot-review.yml",
            "name": "Current revision review gate",
            "head_branch": "fix/final",
            "head_sha": head,
            "html_url": "https://github.example/actions/runs/77",
            "actor": {"login": "litroc"},
            "triggering_actor": {"login": "github-actions[bot]"},
            "pull_requests": [
                {"number": 123, "head": {"ref": "fix/final"}}
            ],
        }

        def evaluate_identity(
            payload: object, attempt: int
        ) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                [
                    jq,
                    "-e",
                    "--arg",
                    "actor",
                    "litroc",
                    "--arg",
                    "head_ref",
                    "fix/renamed",
                    "--arg",
                    "head_sha",
                    head,
                    "--argjson",
                    "attempt",
                    str(attempt),
                    "--argjson",
                    "owner_pr",
                    "123",
                    "--arg",
                    "run_url",
                    "https://github.example/actions/runs/77",
                    identity_filter,
                ],
                input=json.dumps(payload),
                text=True,
                capture_output=True,
                check=False,
                env={"PATH": TEST_TOOL_PATH},
            )

        accepted = evaluate_identity(producer, 2)
        self.assertEqual(0, accepted.returncode, accepted.stderr)
        for field, value in (
            ("triggering_actor", {"login": "litroc"}),
            ("triggering_actor", {"login": "mallory"}),
            ("actor", {"login": "github-actions[bot]"}),
            ("head_sha", "c" * 40),
        ):
            with self.subTest(identity_drift=field):
                drifted = json.loads(json.dumps(producer))
                drifted[field] = value
                self.assertNotEqual(
                    0, evaluate_identity(drifted, 2).returncode
                )
        drifted = json.loads(json.dumps(producer))
        drifted["pull_requests"][0]["head"]["ref"] = "fix/other"
        self.assertNotEqual(0, evaluate_identity(drifted, 2).returncode)

        attempt_guard = self._producer_attempt_provenance_guard()
        attempt_binding_guard = self._rerun_shell_function(
            "validate_producer_attempt_binding"
        )

        def evaluate_attempt(attempt: object) -> subprocess.CompletedProcess[str]:
            payload = {**producer, "run_attempt": attempt}
            script = "\n".join(
                (
                    "set -euo pipefail",
                    'producer="${PRODUCER}"',
                    attempt_binding_guard,
                    attempt_guard,
                    'printf "%s\\n" "${producer_attempt}"',
                )
            )
            return subprocess.run(
                [self._test_tool("bash"), "-c", script],
                text=True,
                capture_output=True,
                check=False,
                env={
                    "PATH": TEST_TOOL_PATH,
                    "PRODUCER": json.dumps(payload, separators=(",", ":")),
                    "PRODUCER_RUN_ATTEMPT": str(attempt),
                },
            )

        self.assertEqual("1\n", evaluate_attempt(1).stdout)
        self.assertEqual("2\n", evaluate_attempt(2).stdout)
        for invalid_attempt in (3, "2", True):
            self.assertNotEqual(0, evaluate_attempt(invalid_attempt).returncode)

        def evaluate_v4_attempt(attempt: object) -> int:
            payload = {**producer, "run_attempt": attempt}
            script = "\n".join(
                (
                    "set -euo pipefail",
                    'producer="${PRODUCER}"',
                    attempt_binding_guard,
                    attempt_guard,
                    'test "${producer_attempt}" -eq 1',
                )
            )
            return subprocess.run(
                [self._test_tool("bash"), "-c", script],
                text=True,
                capture_output=True,
                check=False,
                env={
                    "PATH": TEST_TOOL_PATH,
                    "PRODUCER": json.dumps(payload, separators=(",", ":")),
                    "PRODUCER_RUN_ATTEMPT": str(attempt),
                },
            ).returncode

        self.assertEqual(0, evaluate_v4_attempt(1))
        self.assertNotEqual(0, evaluate_v4_attempt(2))
        for evidence_version in ("v5", "v6"):
            for attempt, actor in ((1, "litroc"), (2, "github-actions[bot]")):
                with self.subTest(
                    evidence_version=evidence_version, attempt=attempt
                ):
                    bound = json.loads(json.dumps(producer))
                    bound["triggering_actor"] = {"login": actor}
                    self.assertEqual(
                        0, evaluate_identity(bound, attempt).returncode
                    )

        reevaluation_job = {
            "id": 89,
            "name": "Request protected verifier re-evaluation",
            "run_id": 77,
            "run_attempt": 2,
            "head_sha": head,
            "status": "completed",
            "conclusion": "success",
        }

        primary_job = {
            "id": 88,
            "name": "Verify current revision policy",
            "run_id": 77,
            "run_attempt": 2,
            "head_sha": head,
            "status": "completed",
            "conclusion": "success",
        }
        producer_binding = {
            "id": 77,
            "event": "pull_request_target",
            "path": ".github/workflows/copilot-review.yml",
            "name": "Current revision review gate",
            "display_title": "Current revision review",
            "head_branch": "fix/final",
            "head_sha": head,
            "html_url": "https://github.example/actions/runs/77",
            "workflow_id": 616,
            "workflow_url": "https://api.github.example/workflows/616",
            "run_attempt": 2,
            "status": "completed",
            "conclusion": "success",
            "actor": "litroc",
            "triggering_actor": "github-actions[bot]",
            "pull_requests": [],
        }
        producer_payload = {
            **producer_binding,
            "actor": {"login": producer_binding["actor"]},
            "triggering_actor": {
                "login": producer_binding["triggering_actor"]
            },
        }

        def evaluate_job_ledger(
            jobs: list[dict[str, object]],
            conclusion: str = "success",
        ) -> subprocess.CompletedProcess[str]:
            script = "\n".join(
                (
                    "set -euo pipefail",
                    'producer_jobs="${JOBS}"',
                    'producer_job_head_sha="${HEAD}"',
                    "producer_attempt=2",
                    "producer_id=77",
                    f"producer_conclusion={conclusion}",
                    "producer_job_name='Verify current revision policy'",
                    self._canonical_producer_job_binding_checks(),
                )
            )
            return subprocess.run(
                [self._test_tool("bash"), "-c", script],
                text=True,
                capture_output=True,
                check=False,
                env={
                    "PATH": TEST_TOOL_PATH,
                    "HEAD": head,
                    "JOBS": json.dumps(
                        {"total_count": len(jobs), "jobs": jobs},
                        separators=(",", ":"),
                    ),
                },
            )

        accepted = evaluate_job_ledger([primary_job, reevaluation_job])
        self.assertEqual(0, accepted.returncode, accepted.stderr)
        failed_dispatch = {**reevaluation_job, "conclusion": "failure"}
        accepted_recovery = evaluate_job_ledger(
            [primary_job, failed_dispatch], "failure"
        )
        self.assertEqual(
            0, accepted_recovery.returncode, accepted_recovery.stderr
        )
        self.assertNotEqual(
            0,
            evaluate_job_ledger([reevaluation_job]).returncode,
        )
        for dispatch in (
            [],
            [{**reevaluation_job, "name": "Unexpected dispatch"}],
            [{**reevaluation_job, "conclusion": "failure"}],
            [reevaluation_job, {**reevaluation_job, "id": 90}],
        ):
            self.assertNotEqual(
                0,
                evaluate_job_ledger([primary_job, *dispatch]).returncode,
            )

        def evaluate_revalidation(
            jobs: list[dict[str, object]],
            payload: dict[str, object] = producer_payload,
        ) -> subprocess.CompletedProcess[str]:
            script = "\n".join(
                (
                    "set -euo pipefail",
                    self._rerun_shell_function("validate_producer_snapshot"),
                    'validate_producer_snapshot "${PRODUCER}" "${JOBS}"',
                )
            )
            return subprocess.run(
                [self._test_tool("bash"), "-c", script],
                text=True,
                capture_output=True,
                check=False,
                env={
                    "PATH": TEST_TOOL_PATH,
                    "PRODUCER": json.dumps(
                        payload, separators=(",", ":")
                    ),
                    "JOBS": json.dumps(
                        {"total_count": len(jobs), "jobs": jobs},
                        separators=(",", ":"),
                    ),
                    "producer_binding": json.dumps(
                        producer_binding, separators=(",", ":")
                    ),
                    "producer_jobs_binding": json.dumps(
                        [primary_job, reevaluation_job], separators=(",", ":")
                    ),
                    "producer_job_id": "88",
                    "producer_job_binding": json.dumps(
                        primary_job, separators=(",", ":")
                    ),
                },
            )

        revalidated = evaluate_revalidation([primary_job, reevaluation_job])
        self.assertEqual(0, revalidated.returncode, revalidated.stderr)
        drifted_reevaluation = {
            **reevaluation_job,
            "conclusion": "failure",
        }
        self.assertNotEqual(
            0,
            evaluate_revalidation([primary_job, drifted_reevaluation]).returncode,
        )
        for field, value in (
            ("actor", {"login": "mallory"}),
            ("run_attempt", 1),
        ):
            with self.subTest(producer_reread_drift=field):
                drifted_producer = json.loads(json.dumps(producer_payload))
                drifted_producer[field] = value
                self.assertNotEqual(
                    0,
                    evaluate_revalidation(
                        [primary_job, reevaluation_job], drifted_producer
                    ).returncode,
                )

    def test_producer_failure_is_only_the_bound_helper_dispatch(self) -> None:
        head = "b" * 40
        primary = {
            "id": 88,
            "name": "Current revision review",
            "run_id": 77,
            "run_attempt": 1,
            "head_sha": head,
            "status": "completed",
            "conclusion": "success",
        }
        rejected = {
            "id": 89,
            "name": "Reject unauthorized Exact-Revision dispatch",
            "run_id": 77,
            "run_attempt": 1,
            "head_sha": head,
            "status": "completed",
            "conclusion": "skipped",
        }
        dispatch = {
            "id": 90,
            "name": "Request protected verifier re-evaluation",
            "run_id": 77,
            "run_attempt": 1,
            "head_sha": head,
            "status": "completed",
            "conclusion": "failure",
        }

        def evaluate(
            conclusion: str, jobs: list[dict[str, object]]
        ) -> subprocess.CompletedProcess[str]:
            script = "\n".join(
                (
                    "set -euo pipefail",
                    "producer_id=77",
                    "producer_attempt=1",
                    'producer_job_head_sha="${HEAD}"',
                    self._producer_terminal_shape_guard(),
                    'validate_producer_terminal_shape "${CONCLUSION}" "${JOBS}"',
                )
            )
            return subprocess.run(
                [self._test_tool("bash"), "-c", script],
                text=True,
                capture_output=True,
                check=False,
                env={
                    "PATH": TEST_TOOL_PATH,
                    "HEAD": head,
                    "CONCLUSION": conclusion,
                    "JOBS": json.dumps(
                        {"total_count": len(jobs), "jobs": jobs},
                        separators=(",", ":"),
                    ),
                },
            )

        accepted = evaluate("failure", [primary, rejected, dispatch])
        self.assertEqual(0, accepted.returncode, accepted.stderr)
        accepted = evaluate("success", [primary, rejected])
        self.assertEqual(0, accepted.returncode, accepted.stderr)

        invalid_ledgers = (
            ("failure", [primary, rejected]),
            ("failure", [primary, rejected, {**dispatch, "name": "Other"}]),
            ("failure", [primary, dispatch, {**dispatch, "id": 91}]),
            ("failure", [{**primary, "conclusion": "failure"}, dispatch]),
            ("failure", [primary, {**dispatch, "run_id": 78}]),
            ("failure", [primary, {**dispatch, "run_attempt": 2}]),
            ("failure", [primary, {**dispatch, "head_sha": "c" * 40}]),
            ("success", [primary, dispatch]),
            ("cancelled", [primary, rejected]),
            (
                "failure",
                [
                    primary,
                    {
                        **dispatch,
                        "status": "in_progress",
                        "conclusion": None,
                    },
                ],
            ),
        )
        for conclusion, jobs in invalid_ledgers:
            with self.subTest(conclusion=conclusion, jobs=jobs):
                self.assertNotEqual(0, evaluate(conclusion, jobs).returncode)


    def test_cross_pre_post_authorization_rejects_live_mutations(self) -> None:
        base = "a" * 40
        head = "b" * 40
        controller = "c" * 40
        producer_url = (
            "https://github.example/lightning-it/.github/actions/runs/77"
        )
        neutral_summary_raw = json.dumps(
            {
                "schema": 4,
                "base_sha": base,
                "head_sha": head,
                "producer_run_id": 77,
                "run_url": producer_url,
                "pull_request_number": 554,
                "controller_sha": controller,
                "review_path": (
                    "applicable Copilot or governed automation exemption"
                ),
            },
            separators=(",", ":"),
        )
        live_pr: dict[str, object] = {
            "number": 554,
            "state": "open",
            "draft": False,
            "user": {"login": "litroc"},
            "base": {
                "ref": "develop",
                "sha": base,
                "repo": {"full_name": "lightning-it/.github"},
            },
            "head": {
                "ref": "fix/final",
                "sha": head,
                "repo": {"full_name": "lightning-it/.github"},
            },
        }
        reservation: dict[str, object] = {
            "id": 43,
            "name": "Protected current-revision verifier",
            "app": {"id": 15368, "slug": "github-actions"},
            "details_url": (
                "https://github.example/lightning-it/.github/runs/43"
            ),
            "external_id": (
                f"rep60-required-workflow:v3:900:554:{base}:{head}"
            ),
            "head_sha": head,
            "status": "completed",
            "conclusion": "success",
        }
        neutral: dict[str, object] = {
            "id": 42,
            "name": "Current revision review",
            "app": {"id": 15368, "slug": "github-actions"},
            "details_url": (
                "https://github.example/lightning-it/.github/runs/42"
            ),
            "external_id": (
                f"mlx90-current-revision:copilot:v6:554:77:{base}:{head}"
            ),
            "head_sha": head,
            "status": "completed",
            "conclusion": "success",
            "output": {"summary": neutral_summary_raw},
        }
        cross = self._cross_run(
            202,
            "2026-09-05T11:00:00Z",
            conclusion="failure",
        )
        accepted = self._run_cross_rerun_authorization(
            cross=cross,
            inventory=[cross],
            live_pr=live_pr,
            neutral=neutral,
            neutral_summary_raw=neutral_summary_raw,
            reservation=reservation,
            protected=self._protected_run(
                attempt=2, status="completed", conclusion="success"
            ),
            protected_jobs=self._protected_jobs(attempt=2),
        )
        self.assertEqual(0, accepted.returncode, accepted.stderr)
        self.assertEqual("POST_AUTHORIZED\n", accepted.stdout)
        ordered_reads = (
            "ORDER:reservation_inventory",
            "ORDER:protected_detail",
            "ORDER:protected_jobs",
            "ORDER:neutral",
            "ORDER:pr",
            "ORDER:reservation",
            "ORDER:cross_detail",
            "ORDER:cross_job",
            "ORDER:cross_inventory",
            "ORDER:POST",
        )
        stderr_lines = accepted.stderr.splitlines()
        observed_order = [stderr_lines.index(item) for item in ordered_reads]
        self.assertEqual(sorted(observed_order), observed_order)
        self.assertEqual(6, stderr_lines.count("ORDER:protected_detail"))
        self.assertEqual(6, stderr_lines.count("ORDER:protected_jobs"))
        self.assertGreater(
            len(stderr_lines)
            - 1
            - stderr_lines[::-1].index("ORDER:protected_detail"),
            stderr_lines.index("ORDER:cross_inventory"),
        )
        self.assertGreater(
            stderr_lines.index("ORDER:POST"),
            len(stderr_lines)
            - 1
            - stderr_lines[::-1].index("ORDER:protected_jobs"),
        )
        last_reservation_inventory = (
            len(stderr_lines)
            - 1
            - stderr_lines[::-1].index("ORDER:reservation_inventory")
        )
        self.assertGreater(
            last_reservation_inventory,
            stderr_lines.index("ORDER:cross_inventory"),
        )
        self.assertLess(
            last_reservation_inventory, stderr_lines.index("ORDER:POST")
        )

        producer_success = self._protected_run(
            status="completed", conclusion="success"
        )
        producer_jobs = self._protected_jobs()
        converged = self._run_cross_rerun_authorization(
            cross=cross,
            inventory=[cross],
            live_pr=live_pr,
            neutral=neutral,
            neutral_summary_raw=neutral_summary_raw,
            reservation=reservation,
            protected_sequence=[
                self._protected_run(status="in_progress", conclusion=None),
                producer_success,
                producer_success,
                producer_success,
            ],
            protected_jobs_sequence=[producer_jobs] * 3,
        )
        self.assertEqual(0, converged.returncode, converged.stderr)
        self.assertIn("ORDER:POST", converged.stderr)
        self.assertEqual(
            7, converged.stderr.splitlines().count("ORDER:protected_detail")
        )

        def reverse_key_order(value: object) -> object:
            if isinstance(value, dict):
                return {
                    key: reverse_key_order(item)
                    for key, item in reversed(value.items())
                }
            if isinstance(value, list):
                return [reverse_key_order(item) for item in value]
            return value

        reordered_producer = reverse_key_order(producer_success)
        self.assertIsInstance(reordered_producer, dict)
        key_order_converged = self._run_cross_rerun_authorization(
            cross=cross,
            inventory=[cross],
            live_pr=live_pr,
            neutral=neutral,
            neutral_summary_raw=neutral_summary_raw,
            reservation=reservation,
            protected_sequence=[producer_success, reordered_producer] * 30,
            protected_jobs_sequence=[producer_jobs] * 3,
        )
        self.assertEqual(
            0, key_order_converged.returncode, key_order_converged.stderr
        )
        key_order_lines = key_order_converged.stderr.splitlines()
        self.assertEqual(6, key_order_lines.count("ORDER:protected_detail"))
        self.assertEqual(6, key_order_lines.count("ORDER:protected_jobs"))
        self.assertEqual(2, key_order_lines.count("ORDER:sleep:2"))
        self.assertEqual(1, key_order_lines.count("ORDER:POST"))
        self.assertIn("jq -Scn", RERUN_WORKFLOW.read_text(encoding="utf-8"))

        changed_success_jobs = json.loads(json.dumps(producer_jobs))
        changed_success_jobs["jobs"][0]["id"] = 9900
        snapshot_converged = self._run_cross_rerun_authorization(
            cross=cross,
            inventory=[cross],
            live_pr=live_pr,
            neutral=neutral,
            neutral_summary_raw=neutral_summary_raw,
            reservation=reservation,
            protected_sequence=[producer_success],
            protected_jobs_sequence=[producer_jobs, changed_success_jobs],
        )
        self.assertEqual(
            0, snapshot_converged.returncode, snapshot_converged.stderr
        )
        snapshot_lines = snapshot_converged.stderr.splitlines()
        job_reads = [
            index
            for index, line in enumerate(snapshot_lines)
            if line == "ORDER:protected_jobs"
        ]
        sleeps = [
            index
            for index, line in enumerate(snapshot_lines)
            if line == "ORDER:sleep:2"
        ]
        self.assertEqual(8, len(job_reads))
        self.assertEqual(4, len(sleeps))
        self.assertLess(job_reads[0], sleeps[0])
        self.assertLess(sleeps[0], job_reads[1])
        self.assertLess(job_reads[1], sleeps[1])
        self.assertLess(sleeps[1], job_reads[2])
        self.assertLess(job_reads[2], sleeps[2])
        self.assertLess(sleeps[2], job_reads[3])
        self.assertEqual(1, snapshot_lines.count("ORDER:POST"))

        final_drift_jobs = json.loads(json.dumps(producer_jobs))
        final_drift_jobs["jobs"][0]["id"] = 9901
        final_drift = self._run_cross_rerun_authorization(
            cross=cross,
            inventory=[cross],
            live_pr=live_pr,
            neutral=neutral,
            neutral_summary_raw=neutral_summary_raw,
            reservation=reservation,
            protected_sequence=[producer_success] * 3,
            protected_jobs_sequence=[
                producer_jobs,
                producer_jobs,
                final_drift_jobs,
            ],
        )
        self.assertNotEqual(0, final_drift.returncode, final_drift.stdout)
        self.assertNotIn("ORDER:POST", final_drift.stderr)

        cancelled = json.loads(json.dumps(cross))
        cancelled["conclusion"] = "cancelled"
        changed_pr = json.loads(json.dumps(live_pr))
        changed_pr["head"]["sha"] = "d" * 40
        changed_reservation = json.loads(json.dumps(reservation))
        changed_reservation["external_id"] = "drifted"
        changed_neutral = json.loads(json.dumps(neutral))
        changed_neutral["external_id"] = "drifted"
        duplicate_reservation_pages = [
            {"total_count": 2, "check_runs": [reservation, reservation]}
        ]
        malformed_reservation = json.loads(json.dumps(reservation))
        malformed_reservation["id"] = None
        malformed_reservation_pages = [
            {"total_count": 1, "check_runs": [malformed_reservation]}
        ]
        bound_cross_job = {
            "id": 98563887790,
            "name": "Required dot-github current-revision workflow",
            "run_id": 202,
            "head_sha": head,
            "run_attempt": 1,
            "status": "completed",
            "conclusion": "failure",
        }
        changed_cross_job = {**bound_cross_job, "id": 98563887791}
        wrong_cross_job_name = {
            **bound_cross_job,
            "name": "Unexpected job",
        }
        wrong_cross_job_run = {**bound_cross_job, "run_id": 203}
        wrong_cross_job_head = {**bound_cross_job, "head_sha": "c" * 40}
        failed_producer = self._protected_run(
            status="completed", conclusion="failure"
        )
        excess_attempt_producer = self._protected_run(
            attempt=3, status="completed", conclusion="success"
        )
        pending_producer = self._protected_run(
            status="in_progress", conclusion=None
        )
        pending_required_jobs = self._protected_jobs(
            required_status="in_progress", required_conclusion=None
        )
        failed_required_jobs = self._protected_jobs(
            required_status="completed", required_conclusion="failure"
        )
        wrong_run_jobs = self._protected_jobs()
        wrong_run_jobs["jobs"][0]["run_id"] = 901  # type: ignore[index]
        duplicate_required_jobs = self._protected_jobs()
        duplicate_required_jobs["jobs"].append(  # type: ignore[union-attr]
            {
                **duplicate_required_jobs["jobs"][2],  # type: ignore[index]
                "id": 904,
            }
        )
        duplicate_required_jobs["total_count"] = 4
        newer = self._cross_run(
            303,
            "2026-09-05T12:00:00Z",
            conclusion="failure",
        )
        cases = (
            {
                "name": "authoritative cancellation",
                "cross": cancelled,
                "inventory": [cancelled],
                "live_pr": live_pr,
                "reservation": reservation,
            },
            {
                "name": "pull request drift",
                "cross": cross,
                "inventory": [cross],
                "live_pr": changed_pr,
                "reservation": reservation,
            },
            {
                "name": "neutral transaction failure",
                "cross": cross,
                "inventory": [cross],
                "live_pr": live_pr,
                "reservation": reservation,
                "neutral_authorized": False,
            },
            {
                "name": "neutral check drift",
                "cross": cross,
                "inventory": [cross],
                "live_pr": live_pr,
                "reservation": reservation,
                "neutral": changed_neutral,
            },
            {
                "name": "reservation check drift",
                "cross": cross,
                "inventory": [cross],
                "live_pr": live_pr,
                "reservation": changed_reservation,
            },
            {
                "name": "duplicate reservation inventory IDs",
                "cross": cross,
                "inventory": [cross],
                "live_pr": live_pr,
                "reservation": reservation,
                "reservation_pages": duplicate_reservation_pages,
            },
            {
                "name": "malformed reservation inventory ID",
                "cross": cross,
                "inventory": [cross],
                "live_pr": live_pr,
                "reservation": reservation,
                "reservation_pages": malformed_reservation_pages,
            },
            {
                "name": "selected attempt-one job drift",
                "cross": cross,
                "inventory": [cross],
                "live_pr": live_pr,
                "reservation": reservation,
                "cross_job": changed_cross_job,
            },
            {
                "name": "selected attempt-one job name drift",
                "cross": cross,
                "inventory": [cross],
                "live_pr": live_pr,
                "reservation": reservation,
                "cross_job": wrong_cross_job_name,
            },
            {
                "name": "selected job wrong run",
                "cross": cross,
                "inventory": [cross],
                "live_pr": live_pr,
                "reservation": reservation,
                "cross_job": wrong_cross_job_run,
            },
            {
                "name": "selected job wrong head",
                "cross": cross,
                "inventory": [cross],
                "live_pr": live_pr,
                "reservation": reservation,
                "cross_job": wrong_cross_job_head,
            },
            {
                "name": "newer inventory entry",
                "cross": cross,
                "inventory": [cross, newer],
                "live_pr": live_pr,
                "reservation": reservation,
            },
            {
                "name": "reservation producer failure",
                "cross": cross,
                "inventory": [cross],
                "live_pr": live_pr,
                "reservation": reservation,
                "protected": failed_producer,
            },
            {
                "name": "reservation producer exceeds attempt two",
                "cross": cross,
                "inventory": [cross],
                "live_pr": live_pr,
                "reservation": reservation,
                "protected": excess_attempt_producer,
            },
            {
                "name": "reservation producer remains nonterminal",
                "cross": cross,
                "inventory": [cross],
                "live_pr": live_pr,
                "reservation": reservation,
                "protected": pending_producer,
            },
            {
                "name": "required producer job remains nonterminal",
                "cross": cross,
                "inventory": [cross],
                "live_pr": live_pr,
                "reservation": reservation,
                "protected_jobs": pending_required_jobs,
            },
            {
                "name": "required producer job failed",
                "cross": cross,
                "inventory": [cross],
                "live_pr": live_pr,
                "reservation": reservation,
                "protected_jobs": failed_required_jobs,
            },
            {
                "name": "producer job belongs to another run",
                "cross": cross,
                "inventory": [cross],
                "live_pr": live_pr,
                "reservation": reservation,
                "protected_jobs": wrong_run_jobs,
            },
            {
                "name": "duplicate required producer job",
                "cross": cross,
                "inventory": [cross],
                "live_pr": live_pr,
                "reservation": reservation,
                "protected_jobs": duplicate_required_jobs,
            },
            {
                "name": "deadline expires before POST",
                "cross": cross,
                "inventory": [cross],
                "live_pr": live_pr,
                "reservation": reservation,
                "deadline_expired": True,
            },
        )
        for case in cases:
            with self.subTest(case=case["name"]):
                result = self._run_cross_rerun_authorization(
                    cross=case["cross"],
                    inventory=case["inventory"],
                    live_pr=case["live_pr"],
                    neutral=case.get("neutral", neutral),
                    neutral_summary_raw=neutral_summary_raw,
                    reservation=case["reservation"],
                    expected_neutral=neutral,
                    expected_reservation=reservation,
                    neutral_authorized=case.get(
                        "neutral_authorized", True
                    ),
                    reservation_pages=case.get("reservation_pages"),
                    deadline_expired=case.get("deadline_expired", False),
                    cross_job=case.get("cross_job"),
                    protected=case.get("protected"),
                    protected_jobs=case.get("protected_jobs"),
                )
                self.assertNotEqual(0, result.returncode, result.stdout)
                self.assertNotIn("POST_AUTHORIZED", result.stdout)
                self.assertNotIn("ORDER:POST", result.stderr)

    def test_protected_pre_post_transaction_executes_all_guards(self) -> None:
        base = "a" * 40
        head = "b" * 40
        live_pr: dict[str, object] = {
            "number": 554,
            "state": "open",
            "draft": False,
            "user": {"login": "litroc"},
            "base": {
                "ref": "develop",
                "sha": base,
                "repo": {"full_name": "lightning-it/.github"},
            },
            "head": {
                "ref": "fix/final",
                "sha": head,
                "repo": {"full_name": "lightning-it/.github"},
            },
        }
        reservation: dict[str, object] = {
            "id": 43,
            "name": "Protected current-revision verifier",
            "app": {"id": 15368, "slug": "github-actions"},
            "details_url": (
                "https://github.example/lightning-it/.github/runs/43"
            ),
            "external_id": (
                f"rep60-required-workflow:v3:900:554:{base}:{head}"
            ),
            "head_sha": head,
            "status": "completed",
            "conclusion": "failure",
        }
        protected = self._protected_run()
        accepted = self._run_protected_rerun_authorization(
            protected=protected,
            live_pr=live_pr,
            reservation=reservation,
        )
        self.assertEqual(0, accepted.returncode, accepted.stderr)
        self.assertEqual("POST_AUTHORIZED\n", accepted.stdout)
        ordered_reads = (
            "ORDER:initial_cross_inventory",
            "ORDER:neutral",
            "ORDER:pr",
            "ORDER:reservation",
            "ORDER:reservation_inventory",
            "ORDER:protected_detail",
            "ORDER:cross_inventory",
            "ORDER:POST",
        )
        observed_order = [accepted.stderr.index(item) for item in ordered_reads]
        self.assertEqual(sorted(observed_order), observed_order)

        changed_reservation = json.loads(json.dumps(reservation))
        changed_reservation["external_id"] = "drifted"
        cancelled = self._protected_run(conclusion="cancelled")
        cases = (
            {
                "name": "neutral or producer drift",
                "protected": protected,
                "reservation": reservation,
                "neutral_authorized": False,
            },
            {
                "name": "reservation drift",
                "protected": protected,
                "reservation": changed_reservation,
            },
            {
                "name": "protected run cancellation",
                "protected": cancelled,
                "reservation": reservation,
            },
            {
                "name": "deadline expires before POST",
                "protected": protected,
                "reservation": reservation,
                "deadline_expired": True,
            },
        )
        cross = self._cross_run(700, "2026-09-05T10:00:00Z")
        cases += tuple(
            {
                "name": name,
                "protected": protected,
                "reservation": reservation,
                "cross_inventory": inventory,
            }
            for name, inventory in (
                (
                    "bad cross inventory",
                    [{**cross, "actor": {"login": "mallory"}}],
                ),
                (
                    "newer cross run",
                    [
                        cross,
                        self._cross_run(701, "2026-09-05T11:00:00Z"),
                    ],
                ),
                (
                    "nonterminal cross run",
                    [
                        {
                            **cross,
                            "status": "in_progress",
                            "conclusion": None,
                        }
                    ],
                ),
                ("malformed cross inventory", [{"id": 700}]),
                (
                    "cancelled cross run",
                    [{**cross, "conclusion": "cancelled"}],
                ),
            )
        )
        for case in cases:
            with self.subTest(case=case["name"]):
                result = self._run_protected_rerun_authorization(
                    protected=case["protected"],
                    live_pr=live_pr,
                    reservation=case["reservation"],
                    expected_reservation=reservation,
                    neutral_authorized=case.get(
                        "neutral_authorized", True
                    ),
                    deadline_expired=case.get("deadline_expired", False),
                    cross_inventory=case.get("cross_inventory"),
                )
                self.assertNotEqual(0, result.returncode, result.stdout)
                self.assertNotIn("POST_AUTHORIZED", result.stdout)
                self.assertNotIn("ORDER:POST", result.stderr)

    def test_post_rerun_reads_converge_from_attempt_one_to_attempt_two(
        self,
    ) -> None:
        def execute(
            function_name: str,
            validator_name: str,
            sequence: list[dict[str, object]],
        ) -> tuple[subprocess.CompletedProcess[str], int]:
            authoritative_stub = ""
            if function_name == "wait_for_cross_attempt_two_success":
                authoritative_stub = (
                    "validate_authoritative_cross_success() { return 0; }"
                )
            script = "\n".join(
                (
                    "set -euo pipefail",
                    self._rerun_shell_function("require_deadline"),
                    self._rerun_shell_function("bounded_sleep"),
                    self._rerun_shell_function(validator_name),
                    self._rerun_shell_function(
                        "wait_for_attempt_two_success"
                    ),
                    self._rerun_shell_function(function_name),
                    authoritative_stub,
                    r'''read_run_with_retry() {
  local index
  index="$(cat "${RUN_STATE_FILE}")"
  printf '%s' "$((index + 1))" >"${RUN_STATE_FILE}"
  jq -ce --argjson index "${index}" \
    '.[$index] // .[-1]' <<<"${RUN_SEQUENCE}"
}
sleep() { :; }''',
                    "OPERATION_DEADLINE=$((SECONDS + 100))",
                    function_name,
                )
            )
            with tempfile.TemporaryDirectory() as temp_dir:
                state_file = Path(temp_dir) / "run-observations"
                state_file.write_text("0", encoding="utf-8")
                result = subprocess.run(
                    [self._test_tool("bash"), "-c", script],
                    text=True,
                    capture_output=True,
                    check=False,
                    env={
                        "PATH": TEST_TOOL_PATH,
                        "RUN_STATE_FILE": str(state_file),
                        "RUN_SEQUENCE": json.dumps(
                            sequence, separators=(",", ":")
                        ),
                        "GITHUB_API_URL": "https://api.github.example",
                        "GITHUB_SERVER_URL": "https://github.example",
                        "REPOSITORY": "lightning-it/.github",
                        "PR_NUMBER": "554",
                        "EXPECTED_BASE": "a" * 40,
                        "EXPECTED_HEAD": "b" * 40,
                        "author": "litroc",
                        "base_ref": "develop",
                        "head_ref": "fix/final",
                        "run_id": "900",
                        "verifier_run_url": (
                            "https://github.example/lightning-it/.github/"
                            "actions/runs/900"
                        ),
                        "cross_run_id": "202",
                    },
                )
                observations = int(state_file.read_text(encoding="utf-8"))
            return result, observations

        def protected(**state: object) -> dict[str, object]:
            return self._protected_run(**state)  # type: ignore[arg-type]

        def cross(**state: object) -> dict[str, object]:
            return self._cross_run(
                202,
                "2026-09-05T11:00:00Z",
                **state,  # type: ignore[arg-type]
            )

        waiters = (
            (
                "protected",
                "wait_for_protected_attempt_two_success",
                "validate_protected_run_binding",
                protected,
            ),
            (
                "cross",
                "wait_for_cross_attempt_two_success",
                "validate_cross_run_binding",
                cross,
            ),
        )
        for name, function_name, validator_name, make_run in waiters:
            with self.subTest(waiter=name, case="full convergence"):
                sequence = [
                    make_run(
                        attempt=1,
                        status="completed",
                        conclusion="failure",
                    ),
                    make_run(attempt=1, status="queued", conclusion=None),
                    make_run(
                        attempt=1,
                        status="in_progress",
                        conclusion=None,
                    ),
                    make_run(attempt=2, status="queued", conclusion=None),
                    make_run(
                        attempt=2,
                        status="in_progress",
                        conclusion=None,
                    ),
                    make_run(
                        attempt=2,
                        status="completed",
                        conclusion="success",
                    ),
                ]
                result, observations = execute(
                    function_name, validator_name, sequence
                )
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual(6, observations)

            for transient in (
                "requested",
                "waiting",
                "pending",
                "queued",
                "in_progress",
            ):
                with self.subTest(
                    waiter=name,
                    case="nonterminal transition",
                    status=transient,
                ):
                    sequence = [
                        make_run(
                            attempt=1,
                            status=transient,
                            conclusion=None,
                        ),
                        make_run(
                            attempt=2,
                            status=transient,
                            conclusion=None,
                        ),
                        make_run(
                            attempt=2,
                            status="completed",
                            conclusion="success",
                        ),
                    ]
                    result, observations = execute(
                        function_name, validator_name, sequence
                    )
                    self.assertEqual(0, result.returncode, result.stderr)
                    self.assertEqual(3, observations)

            rejected_sequences = (
                (
                    "attempt-one success",
                    [
                        make_run(
                            attempt=1,
                            status="completed",
                            conclusion="success",
                        )
                    ],
                    1,
                ),
                (
                    "attempt-one cancelled",
                    [
                        make_run(
                            attempt=1,
                            status="completed",
                            conclusion="cancelled",
                        )
                    ],
                    1,
                ),
                (
                    "attempt-two failure",
                    [
                        make_run(
                            attempt=2,
                            status="completed",
                            conclusion="failure",
                        )
                    ],
                    1,
                ),
                (
                    "attempt-two cancelled",
                    [
                        make_run(
                            attempt=2,
                            status="completed",
                            conclusion="cancelled",
                        )
                    ],
                    1,
                ),
                (
                    "attempt-two rollback",
                    [
                        make_run(
                            attempt=2,
                            status="in_progress",
                            conclusion=None,
                        ),
                        make_run(
                            attempt=1,
                            status="queued",
                            conclusion=None,
                        ),
                    ],
                    2,
                ),
                (
                    "nonterminal conclusion",
                    [
                        make_run(
                            attempt=1,
                            status="queued",
                            conclusion="failure",
                        )
                    ],
                    1,
                ),
            )
            for case, sequence, expected_observations in rejected_sequences:
                with self.subTest(waiter=name, case=case):
                    result, observations = execute(
                        function_name, validator_name, sequence
                    )
                    self.assertNotEqual(0, result.returncode)
                    self.assertEqual(expected_observations, observations)

            with self.subTest(waiter=name, case="attempt-one timeout"):
                result, observations = execute(
                    function_name,
                    validator_name,
                    [
                        make_run(
                            attempt=1,
                            status="queued",
                            conclusion=None,
                        )
                    ],
                )
                self.assertNotEqual(0, result.returncode)
                self.assertIn("did not converge", result.stderr)
                self.assertEqual(60, observations)

    def test_attempt_two_inventory_rejects_a_newer_bound_run(self) -> None:
        strict_function = self._rerun_shell_function(
            "validate_authoritative_cross_inventory"
        )
        retry_function = self._rerun_shell_function(
            "validate_authoritative_cross_inventory_with_retry"
        )

        def run_strict(inventory: list[dict[str, object]]) -> int:
            script = "\n".join(
                (
                    "set -euo pipefail",
                    strict_function,
                    'validate_authoritative_cross_inventory 202 2 '
                    '"${INVENTORY}"',
                )
            )
            result = subprocess.run(
                [self._test_tool("bash"), "-c", script],
                text=True,
                capture_output=True,
                check=False,
                env={
                    "PATH": TEST_TOOL_PATH,
                    "author": "litroc",
                    "INVENTORY": json.dumps(
                        inventory, separators=(",", ":")
                    ),
                },
            )
            return result.returncode

        def run_with_retry(
            sequence: list[list[dict[str, object]]],
        ) -> tuple[subprocess.CompletedProcess[str], int]:
            fake_inventory = r'''load_cross_inventory_with_retry() {
  local index
  index="$(cat "${INVENTORY_STATE_FILE}")"
  printf '%s' "$((index + 1))" >"${INVENTORY_STATE_FILE}"
  jq -ce --argjson index "${index}" \
    '.[$index] // .[-1]' <<<"${INVENTORY_SEQUENCE}"
}
'''
            script = "\n".join(
                (
                    "set -euo pipefail",
                    self._rerun_shell_function("require_deadline"),
                    self._rerun_shell_function("bounded_sleep"),
                    strict_function,
                    retry_function,
                    fake_inventory,
                    "sleep() { :; }",
                    "OPERATION_DEADLINE=$((SECONDS + 100))",
                    "validate_authoritative_cross_inventory_with_retry 202 2",
                )
            )
            with tempfile.TemporaryDirectory() as temp_dir:
                state_file = Path(temp_dir) / "inventory-observations"
                state_file.write_text("0", encoding="utf-8")
                result = subprocess.run(
                    [self._test_tool("bash"), "-c", script],
                    text=True,
                    capture_output=True,
                    check=False,
                    env={
                        "PATH": TEST_TOOL_PATH,
                        "author": "litroc",
                        "INVENTORY_STATE_FILE": str(state_file),
                        "INVENTORY_SEQUENCE": json.dumps(
                            sequence, separators=(",", ":")
                        ),
                    },
                )
                attempts = int(state_file.read_text(encoding="utf-8"))
            return result, attempts

        completed_attempt_two = self._cross_run(
            202,
            "2026-09-05T11:00:00Z",
            attempt=2,
            conclusion="success",
        )
        self.assertEqual(0, run_strict([completed_attempt_two]))
        stale_attempt_one = self._cross_run(
            202,
            "2026-09-05T11:00:00Z",
            conclusion="failure",
        )
        delayed_attempt_two = self._cross_run(
            202,
            "2026-09-05T11:00:00Z",
            attempt=2,
            status="in_progress",
            conclusion=None,
        )
        converged, attempts = run_with_retry(
            [
                [stale_attempt_one],
                [delayed_attempt_two],
                [completed_attempt_two],
            ]
        )
        self.assertEqual(0, converged.returncode, converged.stderr)
        self.assertEqual(3, attempts)

        newer = self._cross_run(
            303,
            "2026-09-05T12:00:00Z",
            conclusion="failure",
        )
        rejected, attempts = run_with_retry([[completed_attempt_two, newer]])
        self.assertNotEqual(0, rejected.returncode)

        self.assertEqual(1, attempts)

        failed_attempt_two = self._cross_run(
            202,
            "2026-09-05T11:00:00Z",
            attempt=2,
            conclusion="failure",
        )
        rejected, attempts = run_with_retry([[failed_attempt_two]])
        self.assertNotEqual(0, rejected.returncode)
        self.assertEqual(1, attempts)

    def test_old_handoff(self):
        current, previous, head = "a" * 40, "c" * 40, "b" * 40
        summary = {"schema": 4, "base_sha": previous, "head_sha": head,
                   "producer_run_id": 77, "pull_request_number": 123,
                   "review_path": "applicable Copilot or governed automation exemption"}
        check = [{"id": 42,
            "status": "completed", "conclusion": "success",
            "completed_at": "2026-10-03T20:00:00Z",
            "details_url": "https://github.example/runs/42",
            "external_id": f"mlx90-current-revision:copilot:v6:123:77:{previous}:{head}",
            "output": {"summary": json.dumps(summary)}}]
        script = "\n".join((
            "set -euo pipefail",
            "eo() {",
            '  test "${EVENT_BASE}" = "${EXPECTED_PREVIOUS_BASE}"',
            '  printf "%s" "${ELECTED_PREVIOUS_OWNER}"',
            "}",
            self._rfn("vh"),
            'vh "${CHECK}" "${CHECK_URL}"',
        ))

        def evaluate(candidate, *, elected="77", author="litroc", kind="copilot"):
            env = {"PATH": TEST_TOOL_PATH, "BASE_SHA": current,
                   "CHECK": json.dumps(candidate),
                   "CHECK_URL": "https://github.example/runs/42",
                   "ELECTED_PREVIOUS_OWNER": elected,
                   "EXPECTED_PREVIOUS_BASE": previous, "HEAD_SHA": head,
                   "PR_AUTHOR": author, "PR_NUMBER": "123",
                   "current_external_kind": kind}
            return subprocess.run([self._test_tool("bash"), "-c", script],
                                  text=True, capture_output=True,
                                  check=False, env=env)

        accepted = evaluate(check)
        self.assertEqual(0, accepted.returncode, accepted.stderr)
        marker = {"schema": 4, "base_sha": previous, "head_sha": head,
                  "producer_run_id": 77, "invalidated_check_run_id": 42,
                  "reason": "canonical refresh invalidation"}
        failed = [{**check[0], "conclusion": "failure", "output": {
            "title": "Current revision review invalidated",
            "summary": json.dumps(marker)}}]
        self.assertEqual(0, evaluate(failed).returncode)
        for malformed in (
            [{**failed[0], "output": {**failed[0]["output"], "title": "failure"}}],
            [{**failed[0], "output": {**failed[0]["output"], "summary": json.dumps({**marker, "reason": "foreign"})}}],
            [{**failed[0], "output": {**failed[0]["output"], "summary": json.dumps({**marker, "invalidated_check_run_id": 43})}}],
            [{**failed[0], "output": {**failed[0]["output"], "summary": json.dumps({**marker, "review_path": summary["review_path"]})}}],
            [{**failed[0], "external_id": "foreign"}],
        ):
            self.assertNotEqual(0, evaluate(malformed).returncode)

        for drift in (
            [{**check[0], "external_id": "foreign"}],
            [{**check[0], "output": {"summary": json.dumps(
                {**summary, "base_sha": "d" * 40})}}],
            [{**check[0], "external_id":
              f"mlx90-current-revision:copilot:v6:123:77:{current}:{head}",
              "output": {"summary": json.dumps(
                  {**summary, "base_sha": current})}}],
        ):
            with self.subTest(drift=drift):
                self.assertNotEqual(0, evaluate(drift).returncode)
        self.assertNotEqual(0, evaluate(check, elected="78").returncode)

        renovate_summary = {
            **summary,
            "review_path": "deterministic policy-bound Renovate exemption",
        }
        renovate = [{**check[0], "external_id":
                     f"mlx90-current-revision:renovate:v6:123:77:{previous}:{head}",
                     "output": {"summary": json.dumps(renovate_summary)}}]
        result = evaluate(renovate, author="renovate[bot]", kind="renovate")
        self.assertEqual(0, result.returncode, result.stderr)

        refresh = REFRESH_WORKFLOW.read_text(encoding="utf-8")
        self.assertEqual(
            1, refresh.count('-f "external_id=${current_external_id}"')
        )
        self.assertGreaterEqual(refresh.count("validate_live_pr_tuple"), 4)

    def test_cross_success_converges_transient_detail_and_job_reads(
        self,
    ) -> None:
        completed = self._cross_run(
            202,
            "2026-09-05T11:00:00Z",
            attempt=2,
            conclusion="success",
        )
        expected_job = {
            "id": 98563887792,
            "name": "Required dot-github current-revision workflow",
            "run_id": 202,
            "head_sha": "b" * 40,
            "run_attempt": 2,
            "status": "completed",
            "conclusion": "success",
        }
        script = "\n".join(
            (
                "set -euo pipefail",
                self._rerun_shell_function("require_deadline"),
                self._rerun_shell_function("bounded_gh_api"),
                self._rerun_shell_function("bounded_sleep"),
                self._rerun_shell_function("validate_cross_run_binding"),
                self._rerun_shell_function(
                    "validate_authoritative_cross_inventory"
                ),
                self._rerun_shell_function(
                    "validate_authoritative_cross_inventory_with_retry"
                ),
                self._rerun_shell_function(
                    "validate_authoritative_cross_success"
                ),
                FAKE_TIMEOUT_PASSTHROUGH,
                r'''load_cross_inventory_with_retry() {
  printf '%s\n' "${FINAL_INVENTORY}"
}
gh() {
  local count endpoint="${!#}"
  if [ "${endpoint}" = \
      "repos/${REPOSITORY}/actions/runs/202" ]; then
    count="$(cat "${DETAIL_STATE_FILE}")"
    printf '%s' "$((count + 1))" >"${DETAIL_STATE_FILE}"
    if [ "${count}" -lt "${DETAIL_FAILURES}" ]; then
      printf 'transient detail failure\n' >&2
      return 42
    fi
    printf '%s\n' "${DETAIL_RESPONSE}"
  elif [ "${endpoint}" = \
      "repos/${REPOSITORY}/actions/runs/202/attempts/2/jobs?filter=all&per_page=100" ]; then
    count="$(cat "${JOBS_STATE_FILE}")"
    printf '%s' "$((count + 1))" >"${JOBS_STATE_FILE}"
    if [ "${count}" -lt "${JOBS_EMPTY_READS}" ]; then
      printf '{"total_count":0,"jobs":[]}\n'
    else
      printf '%s\n' "${JOBS_RESPONSE}"
    fi
  else
    printf 'unexpected fake gh endpoint: %s\n' "${endpoint}" >&2
    return 88
  fi
}
sleep() { :; }''',
                "OPERATION_DEADLINE=$((SECONDS + 100))",
                "validate_authoritative_cross_success 2 202",
            )
        )

        def run(
            detail: dict[str, object],
            jobs: dict[str, object],
            *,
            detail_failures: int = 0,
            jobs_empty_reads: int = 0,
        ) -> tuple[subprocess.CompletedProcess[str], int, int]:
            with tempfile.TemporaryDirectory() as temp_dir:
                detail_state = Path(temp_dir) / "detail-observations"
                jobs_state = Path(temp_dir) / "job-observations"
                detail_state.write_text("0", encoding="utf-8")
                jobs_state.write_text("0", encoding="utf-8")
                result = subprocess.run(
                    [self._test_tool("bash"), "-c", script],
                    text=True,
                    capture_output=True,
                    check=False,
                    env={
                        "PATH": TEST_TOOL_PATH,
                        "DETAIL_STATE_FILE": str(detail_state),
                        "JOBS_STATE_FILE": str(jobs_state),
                        "DETAIL_FAILURES": str(detail_failures),
                        "JOBS_EMPTY_READS": str(jobs_empty_reads),
                        "DETAIL_RESPONSE": json.dumps(
                            detail, separators=(",", ":")
                        ),
                        "JOBS_RESPONSE": json.dumps(
                            jobs, separators=(",", ":")
                        ),
                        "FINAL_INVENTORY": json.dumps(
                            [completed], separators=(",", ":")
                        ),
                        "GITHUB_API_URL": "https://api.github.example",
                        "GITHUB_SERVER_URL": "https://github.example",
                        "REPOSITORY": "lightning-it/.github",
                        "PR_NUMBER": "554",
                        "EXPECTED_BASE": "a" * 40,
                        "EXPECTED_HEAD": "b" * 40,
                        "author": "litroc",
                        "base_ref": "develop",
                        "head_ref": "fix/final",
                    },
                )
                detail_reads = int(
                    detail_state.read_text(encoding="utf-8")
                )
                job_reads = int(jobs_state.read_text(encoding="utf-8"))
            return result, detail_reads, job_reads

        result, detail_reads, job_reads = run(
            completed,
            {"total_count": 1, "jobs": [expected_job]},
            detail_failures=1,
            jobs_empty_reads=1,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(2, detail_reads)
        self.assertEqual(2, job_reads)

        terminal_failure = self._cross_run(
            202,
            "2026-09-05T11:00:00Z",
            attempt=2,
            conclusion="failure",
        )
        result, detail_reads, job_reads = run(
            terminal_failure,
            {"total_count": 1, "jobs": [expected_job]},
        )
        self.assertNotEqual(0, result.returncode)
        self.assertEqual(1, detail_reads)
        self.assertEqual(0, job_reads)

    def test_neutral_authorization_requires_a_stable_frozen_producer(
        self,
    ) -> None:
        base = "a" * 40
        head = "b" * 40
        controller = "c" * 40
        repository = "lightning-it/.github"
        producer_url = f"https://github.example/{repository}/actions/runs/77"
        review_path = "applicable Copilot or governed automation exemption"
        summary = {
            "schema": 4,
            "base_sha": base,
            "head_sha": head,
            "producer_run_id": 77,
            "run_url": producer_url,
            "pull_request_number": 554,
            "controller_sha": controller,
            "review_path": review_path,
        }
        summary_raw = json.dumps(summary, separators=(",", ":"))
        external_id = (
            f"mlx90-current-revision:copilot:v6:554:77:{base}:{head}"
        )

        def neutral_snapshot(updated_at: str) -> dict[str, object]:
            return {
                "id": 42,
                "name": "Current revision review",
                "app": {"id": 15368, "slug": "github-actions"},
                "head_sha": head,
                "details_url": f"https://github.example/{repository}/runs/42",
                "external_id": external_id,
                "status": "completed",
                "conclusion": "success",
                "started_at": "2026-09-05T10:00:00Z",
                "completed_at": "2026-09-05T10:01:00Z",
                "updated_at": updated_at,
                "output": {"title": "PASS", "summary": summary_raw},
            }

        producer = {
            "id": 77,
            "event": "pull_request_target",
            "path": ".github/workflows/copilot-review.yml",
            "name": "Current revision review gate",
            "display_title": "Current revision review",
            "head_branch": "fix/final",
            "head_sha": head,
            "html_url": producer_url,
            "workflow_id": 616,
            "workflow_url": (
                f"https://api.github.example/repos/{repository}/"
                "actions/workflows/616"
            ),
            "run_attempt": 1,
            "status": "completed",
            "conclusion": "success",
            "actor": {"login": "litroc"},
            "triggering_actor": {"login": "litroc"},
            "pull_requests": [],
        }
        producer_job = {
            "id": 88,
            "name": "Verify current revision policy",
            "run_id": 77,
            "run_attempt": 1,
            "head_sha": head,
            "status": "completed",
            "conclusion": "success",
        }
        producer_jobs = {"total_count": 1, "jobs": [producer_job]}
        producer_binding = {
            "id": 77,
            "event": "pull_request_target",
            "path": ".github/workflows/copilot-review.yml",
            "name": "Current revision review gate",
            "display_title": "Current revision review",
            "head_branch": "fix/final",
            "head_sha": head,
            "html_url": producer_url,
            "workflow_id": 616,
            "workflow_url": (
                f"https://api.github.example/repos/{repository}/"
                "actions/workflows/616"
            ),
            "run_attempt": 1,
            "status": "completed",
            "conclusion": "success",
            "actor": "litroc",
            "triggering_actor": "litroc",
            "pull_requests": [],
        }
        fake_gh = r'''gh() {
  local current endpoint="${!#}" index
  local producer_jobs_endpoint
  producer_jobs_endpoint="repos/${REPOSITORY}/actions/runs/${producer_id}"
  producer_jobs_endpoint+="/attempts/${producer_attempt}/jobs"
  producer_jobs_endpoint+="?filter=all&per_page=100"
  if [ "${endpoint}" = "repos/${REPOSITORY}/check-runs/${neutral_check_id}" ]; then
    index="$(cat "${GH_STATE_FILE}")"
    printf '%s\n' "$((index + 1))" >"${GH_STATE_FILE}"
    jq -ce --argjson index "${index}" \
      '.[$index] // .[-1]' <<<"${NEUTRAL_SEQUENCE}"
  elif [[ "${endpoint}" == *"check_name=Current%20revision%20review"* ]]; then
    index="$(cat "${GH_STATE_FILE}")"
    current="$(jq -ce --argjson index "${index}" \
      '.[$index] // .[-1]' <<<"${NEUTRAL_SEQUENCE}")"
    if [ "${NEUTRAL_INVENTORY_MODE}" = duplicate ]; then
      jq -cn --argjson current "${current}" \
        '[{total_count:2,check_runs:[$current,$current]}]'
    elif [ "${NEUTRAL_INVENTORY_MODE}" = malformed ]; then
      jq -cn --argjson current "${current}" \
        '[{total_count:1,check_runs:[($current + {id:null})]}]'
    else
      jq -cn --argjson current "${current}" \
        '[{total_count:1,check_runs:[$current]}]'
    fi
  elif [ "${endpoint}" = "${producer_jobs_endpoint}" ]; then
    printf '%s\n' "${PRODUCER_JOBS_RESPONSE}"
  elif [ "${endpoint}" = "repos/${REPOSITORY}/actions/runs/${producer_id}" ]; then
    printf '%s\n' "${PRODUCER_RESPONSE}"
  elif [ "${endpoint}" = "repos/${REPOSITORY}" ]; then
    printf '%s\n' '{"default_branch":"develop"}'
  elif [ "${endpoint}" = "repos/${REPOSITORY}/branches/develop" ]; then
    printf '{"commit":{"sha":"%s"}}\n' "${controller_sha}"
  elif [ "${endpoint}" = \
      "repos/${REPOSITORY}/compare/${controller_sha}...${controller_sha}" ]; then
    printf \
      '{"status":"identical","behind_by":0,"merge_base_commit":{"sha":"%s"}}\n' \
      "${controller_sha}"
  else
    printf 'unexpected fake gh endpoint: %s\n' "${endpoint}" >&2
    return 88
  fi
}
'''
        script = "\n".join(
            (
                "set -euo pipefail",
                self._rerun_shell_function("require_deadline"),
                self._rerun_shell_function("bounded_gh_api"),
                self._rerun_shell_function("bounded_sleep"),
                self._rerun_shell_function("validate_neutral_snapshot"),
                self._rerun_shell_function("neutral_snapshot_projection"),
                self._rerun_shell_function(
                    "load_neutral_inventory_snapshot"
                ),
                self._rerun_shell_function("validate_producer_snapshot"),
                self._rerun_shell_function(
                    "capture_neutral_authorization_observation"
                ),
                self._rerun_shell_function(
                    "revalidate_neutral_authorization"
                ),
                FAKE_TIMEOUT_PASSTHROUGH,
                fake_gh,
                "sleep() { :; }",
                "OPERATION_DEADLINE=$((SECONDS + 100))",
                "revalidate_neutral_authorization >/dev/null",
                "printf 'POST_AUTHORIZED\\n'",
            )
        )
        self.assertIn(
            'test "${current_job_binding}" = '
            '"${producer_job_binding}" || return 1',
            script,
        )

        def run(
            sequence: list[dict[str, object]],
            *,
            producer_jobs_response: dict[str, object] = producer_jobs,
            producer_response: dict[str, object] = producer,
            neutral_inventory_mode: str = "valid",
        ) -> tuple[subprocess.CompletedProcess[str], int]:
            with tempfile.TemporaryDirectory() as temp_dir:
                state_file = Path(temp_dir) / "neutral-observations"
                state_file.write_text("0", encoding="utf-8")
                result = subprocess.run(
                    [self._test_tool("bash"), "-c", script],
                    text=True,
                    capture_output=True,
                    check=False,
                    env={
                        "PATH": TEST_TOOL_PATH,
                        "GH_STATE_FILE": str(state_file),
                        "GITHUB_API_URL": "https://api.github.example",
                        "GITHUB_SERVER_URL": "https://github.example",
                        "REPOSITORY": repository,
                        "PR_NUMBER": "554",
                        "EXPECTED_BASE": base,
                        "EXPECTED_HEAD": head,
                        "neutral_check_id": "42",
                        "neutral_head_sha": head,
                        "neutral_details_url": (
                            f"https://github.example/{repository}/runs/42"
                        ),
                        "neutral_external_id": external_id,
                        "neutral_summary_raw": summary_raw,
                        "evidence_version": "v6",
                        "producer_id": "77",
                        "producer_url": producer_url,
                        "producer_attempt": "1",
                        "producer_job_id": "88",
                        "producer_binding": json.dumps(
                            producer_binding, separators=(",", ":")
                        ),
                        "producer_job_binding": json.dumps(
                            producer_job, separators=(",", ":")
                        ),
                        "producer_jobs_binding": json.dumps(
                            [producer_job], separators=(",", ":")
                        ),
                        "expected_review_path": review_path,
                        "controller_sha": controller,
                        "v4_input_sha256": "",
                        "v4_workflow_sha": "",
                        "NEUTRAL_SEQUENCE": json.dumps(
                            sequence, separators=(",", ":")
                        ),
                        "PRODUCER_RESPONSE": json.dumps(
                            producer_response, separators=(",", ":")
                        ),
                        "PRODUCER_JOBS_RESPONSE": json.dumps(
                            producer_jobs_response, separators=(",", ":")
                        ),
                        "NEUTRAL_INVENTORY_MODE": neutral_inventory_mode,
                    },
                )
                observations = int(
                    state_file.read_text(encoding="utf-8").strip()
                )
            return result, observations

        first = neutral_snapshot("2026-09-05T10:01:01Z")
        stable = neutral_snapshot("2026-09-05T10:01:02Z")
        accepted, observations = run([first, stable, stable, stable])
        self.assertEqual(0, accepted.returncode, accepted.stderr)
        self.assertEqual("POST_AUTHORIZED\n", accepted.stdout)
        self.assertEqual(4, observations)

        never_stable = [
            neutral_snapshot(f"2026-09-05T10:01:{second:02d}Z")
            for second in range(10, 20)
        ]
        rejected, observations = run(never_stable)
        self.assertNotEqual(0, rejected.returncode)
        self.assertNotIn("POST_AUTHORIZED", rejected.stdout)
        self.assertEqual(10, observations)

        external_drift = json.loads(json.dumps(stable))
        external_drift["external_id"] = "drifted"
        rejected, observations = run([external_drift])
        self.assertNotEqual(0, rejected.returncode)
        self.assertNotIn("POST_AUTHORIZED", rejected.stdout)
        self.assertEqual(0, observations)

        producer_job_drift = {
            "total_count": 1,
            "jobs": [{**producer_job, "conclusion": "failure"}],
        }
        rejected, observations = run(
            [stable], producer_jobs_response=producer_job_drift
        )
        self.assertNotEqual(0, rejected.returncode)
        self.assertNotIn("POST_AUTHORIZED", rejected.stdout)
        self.assertEqual(1, observations)

        summary_drift = json.loads(json.dumps(stable))
        summary_drift["output"]["summary"] = json.dumps(
            {**summary, "base_sha": "d" * 40}, separators=(",", ":")
        )
        rejected, observations = run([summary_drift])
        self.assertNotEqual(0, rejected.returncode)
        self.assertNotIn("POST_AUTHORIZED", rejected.stdout)
        self.assertEqual(0, observations)

        producer_drift = {**producer, "conclusion": "failure"}
        rejected, observations = run(
            [stable], producer_response=producer_drift
        )
        self.assertNotEqual(0, rejected.returncode)
        self.assertNotIn("POST_AUTHORIZED", rejected.stdout)
        self.assertEqual(1, observations)

        for inventory_mode in ("duplicate", "malformed"):
            with self.subTest(inventory_mode=inventory_mode):
                rejected, observations = run(
                    [stable], neutral_inventory_mode=inventory_mode
                )
                self.assertNotEqual(0, rejected.returncode)
                self.assertNotIn("POST_AUTHORIZED", rejected.stdout)
                self.assertEqual(0, observations)

    def test_refresh_evidence_matrix_is_author_and_version_bound(self) -> None:
        base = "a" * 40
        head = "b" * 40
        release_app = "lightning-it-release-automation[bot]"
        sync_app = "lightning-it-shared-assets-sync[bot]"
        refresh_workflow = REFRESH_WORKFLOW.read_text(encoding="utf-8")
        renovate_route = (
            'if [ "${PR_AUTHOR}" = "renovate[bot]" ] \\\n'
            '            && [[ "${HEAD_REF}" == renovate/* ]]; then\n'
            "            current_external_kind=renovate"
        )
        self.assertIn(renovate_route, refresh_workflow)
        self.assertLess(
            refresh_workflow.index(renovate_route),
            refresh_workflow.index("current_external_kind=managed-sync"),
        )
        cases = (
            ("litroc", f"mlx90-current-revision:copilot:v6:123:77:{base}:{head}", 123),
            (
                release_app,
                f"mlx90-current-revision:ancestry-backmerge:v6:123:77:{base}:{head}",
                123,
            ),
            ("litroc", f"mlx90-current-revision:copilot:v5:77:{base}:{head}", None),
            (
                release_app,
                f"mlx90-current-revision:ancestry-backmerge:v5:77:{base}:{head}",
                None,
            ),
            (
                sync_app,
                f"mlx90-current-revision:ancestry-backmerge:v6:123:77:{base}:{head}",
                123,
            ),
            (
                sync_app,
                f"mlx90-current-revision:ancestry-backmerge:v5:77:{base}:{head}",
                None,
            ),
            (release_app, f"mlx90-current-revision:v4:77:{'c' * 64}", None),
            (
                "renovate[bot]",
                f"mlx90-current-revision:renovate:v6:123:77:{base}:{head}",
                123,
            ),
        )
        for author, external_id, pull_request_number in cases:
            with self.subTest(external_id=external_id):
                result = self._run_refresh_filter(
                    author=author,
                    external_id=external_id,
                    pull_request_number=pull_request_number,
                    review_path=(
                        "deterministic policy-bound Renovate exemption"
                        if author == "renovate[bot]"
                        else None
                    ),
                )
                self.assertEqual(0, result.returncode, result.stderr)

        for external_id, pull_request_number in (
            (
                f"mlx90-current-revision:managed-sync:v6:123:77:{base}:{head}",
                123,
            ),
        ):
            for repository in (
                "lightning-it/website",
                "lightning-it/.github",
            ):
                with self.subTest(
                    managed_distribution=external_id,
                    repository=repository,
                ):
                    result = self._run_refresh_filter(
                        author=sync_app,
                        external_id=external_id,
                        pull_request_number=pull_request_number,
                        repository=repository,
                        review_path=(
                            "deterministic provenance-bound managed distribution exemption"
                        ),
                    )
                    self.assertEqual(0, result.returncode, result.stderr)

                for invalid_review_path in (None, "", "wrong review path"):
                    with self.subTest(
                        invalid_review_path=invalid_review_path,
                        repository=repository,
                    ):
                        rejected = self._run_refresh_filter(
                            author=sync_app,
                            external_id=external_id,
                            pull_request_number=pull_request_number,
                            repository=repository,
                            review_path=invalid_review_path,
                        )
                        self.assertNotEqual(0, rejected.returncode)

        rejected = (
            ("litroc", f"mlx90-current-revision:copilot:v6:123:77:{base}:{head}", None),
            ("litroc", f"mlx90-current-revision:copilot:v5:77:{base}:{head}", 999),
            (release_app, f"mlx90-current-revision:copilot:v5:77:{base}:{head}", None),
            (sync_app, f"mlx90-current-revision:copilot:v6:123:77:{base}:{head}", 123),
            (sync_app, f"mlx90-current-revision:copilot:v5:77:{base}:{head}", None),
            (
                "renovate[bot]",
                f"mlx90-current-revision:copilot:v6:123:77:{base}:{head}",
                123,
            ),
            (
                "litroc",
                f"mlx90-current-revision:managed-sync:v6:123:77:{base}:{head}",
                123,
            ),
            (
                sync_app,
                f"mlx90-current-revision:managed-sync:v6:123:77:{base}:{head}",
                123,
            ),
            ("litroc", f"mlx90-current-revision:ancestry-backmerge:v5:77:{base}:{head}", None),
        )
        for author, external_id, pull_request_number in rejected:
            with self.subTest(rejected=external_id, author=author):
                result = self._run_refresh_filter(
                    author=author,
                    external_id=external_id,
                    pull_request_number=pull_request_number,
                )
                self.assertNotEqual(0, result.returncode)

        for external_id, pull_request_number in (
            (
                f"mlx90-current-revision:ancestry-backmerge:v6:123:77:{base}:{head}",
                123,
            ),
            (
                f"mlx90-current-revision:ancestry-backmerge:v5:77:{base}:{head}",
                None,
            ),
        ):
            with self.subTest(outside_repository=external_id):
                result = self._run_refresh_filter(
                    author=sync_app,
                    external_id=external_id,
                    pull_request_number=pull_request_number,
                    repository="lightning-it/website",
                )
                self.assertNotEqual(0, result.returncode)

        for external_id, pull_request_number in (
            (
                f"mlx90-current-revision:copilot:v6:123:77:{base}:{head}",
                123,
            ),
            (f"mlx90-current-revision:copilot:v5:77:{base}:{head}", None),
        ):
            with self.subTest(sync_bot_copilot_rejected=external_id):
                result = self._run_refresh_filter(
                    author=sync_app,
                    external_id=external_id,
                    pull_request_number=pull_request_number,
                    repository="lightning-it/website",
                )
                self.assertNotEqual(0, result.returncode)

    def test_renovate_binding(self):
        base, head, owner = "a" * 40, "b" * 40, "77"
        current = f"mlx90-current-revision:renovate:v6:123:{owner}:{base}:{head}"
        script = "\n".join((
            "set -euo pipefail",
            self._rfn("va"),
            "gh() { : >\"${PATCH_FILE}\"; }",
            'if va "${CHECK}"; then',
            "  gh api --method PATCH",
            "else",
            "  exit 73",
            "fi",
        ))

        def evaluate(external_id):
            with tempfile.TemporaryDirectory() as temporary:
                patch_file = Path(temporary) / "patch"
                result = subprocess.run(
                    [self._test_tool("bash"), "-c", script],
                    text=True, capture_output=True, check=False,
                    env={
                        "PATH": TEST_TOOL_PATH,
                        "BASE_SHA": base,
                        "CHECK": json.dumps([{"external_id": external_id}]),
                        "HEAD_SHA": head,
                        "PATCH_FILE": str(patch_file),
                        "PR_AUTHOR": "renovate[bot]",
                        "current_external_id": current,
                        "current_external_kind": "renovate",
                        "owner_run_id": owner,
                    },
                )
                return result.returncode, patch_file.exists()

        legacy = f"mlx90-current-revision:copilot:v5:{owner}:{base}:{head}"
        for binding, code, patched in ((current, 0, True), (legacy, 73, False)):
            result, mutated = evaluate(binding)
            self.assertEqual(code, result)
            self.assertEqual(patched, mutated)

    def test_rerun_managed_sync_is_bound_to_develop_and_sync_actor(self) -> None:
        guard = "set -euo pipefail\n" + self._rerun_evidence_kind_guard()
        summary = json.dumps(
            {
                "review_path": (
                    "deterministic provenance-bound managed distribution exemption"
                )
            }
        )

        def run(*, author: str, base_ref: str, repository: str) -> int:
            bash = self._test_tool("bash")
            result = subprocess.run(
                [bash, "-c", guard],
                env={
                    "PATH": TEST_TOOL_PATH,
                    "REPOSITORY": repository,
                    "author": author,
                    "base_ref": base_ref,
                    "external_kind": "managed-sync",
                    "neutral_summary": summary,
                },
                text=True,
                capture_output=True,
                check=False,
            )
            return result.returncode

        sync_app = "lightning-it-shared-assets-sync[bot]"
        self.assertEqual(
            0,
            run(
                author=sync_app,
                base_ref="develop",
                repository="lightning-it/website",
            ),
        )
        self.assertNotEqual(
            0,
            run(
                author=sync_app,
                base_ref="main",
                repository="lightning-it/website",
            ),
        )
        self.assertEqual(
            0,
            run(
                author=sync_app,
                base_ref="develop",
                repository="lightning-it/.github",
            ),
        )
        self.assertNotEqual(
            0,
            run(
                author=sync_app,
                base_ref="main",
                repository="lightning-it/.github",
            ),
        )
        self.assertNotEqual(
            0,
            run(
                author="litroc",
                base_ref="develop",
                repository="lightning-it/website",
            ),
        )

    def test_rerun_summary_requires_pr_binding_only_for_v6(self) -> None:
        summary = {
            "schema": 4,
            "base_sha": "a" * 40,
            "head_sha": "b" * 40,
            "producer_run_id": 77,
            "run_url": "https://github.example/actions/runs/77",
        }

        def run(version: str, evidence: dict[str, object]) -> int:
            try:
                result = subprocess.run(
                    [
                        self._test_tool("jq"),
                        "-e",
                        "--arg",
                        "base",
                        "a" * 40,
                        "--arg",
                        "evidence_version",
                        version,
                        "--arg",
                        "head",
                        "b" * 40,
                        "--arg",
                        "run_url",
                        "https://github.example/actions/runs/77",
                        "--argjson",
                        "pr_number",
                        "123",
                        "--argjson",
                        "run_id",
                        "77",
                        self._rerun_summary_filter(),
                    ],
                    input=json.dumps(evidence),
                    text=True,
                    capture_output=True,
                    check=False,
                )
            except FileNotFoundError as error:
                self.fail(f"jq is required to validate rerun evidence: {error}")
            return result.returncode

        self.assertEqual(0, run("v5", summary))
        self.assertEqual(0, run("v4", summary))
        self.assertNotEqual(0, run("v6", summary))
        self.assertEqual(0, run("v6", {**summary, "pull_request_number": 123}))
        self.assertNotEqual(0, run("v5", {**summary, "pull_request_number": 999}))


    def test_same_sha_rename_preserves_historical_helper_bindings(
        self,
    ) -> None:
        workflow = RERUN_WORKFLOW.read_text(encoding="utf-8")
        self.assertNotIn("head_ref=$(jq -r .head_branch", workflow)
        cross = self._cross_run(202, "2026-09-05T11:00:00Z")
        pages = [{"total_count": 1, "workflow_runs": [cross]}]
        producer = {
            "head_branch": "fix/final",
            "pull_requests": [{"head": {"ref": "fix/final"}}],
        }
        script = "\n".join((
            "set -euo pipefail",
            'producer="${PRODUCER}"',
            'head_ref="fix/renamed"',
            self._rerun_shell_function("validate_live_pr_snapshot"),
            self._rerun_shell_function("validate_protected_run_binding"),
            self._rerun_shell_function("validate_cross_run_binding"),
            'validate_live_pr_snapshot "${LIVE_PR}"',
            'jq -ce --arg api_url "${GITHUB_API_URL}" '
            '--arg author "${author}" --arg base_ref "${base_ref}" '
            '--arg base_sha "${EXPECTED_BASE}" --arg head_ref "${head_ref}" '
            '--arg head_sha "${EXPECTED_HEAD}" --arg repository "${REPOSITORY}" '
            '--arg server_url "${GITHUB_SERVER_URL}" '
            '--argjson pr_number "${PR_NUMBER}" "${CROSS_FILTER}" '
            '<<<"${PAGES}" >/dev/null',
            'validate_protected_run_binding "${PROTECTED}"',
            'validate_cross_run_binding "${CROSS}" 202',
        ))
        environment = {
            "PATH": TEST_TOOL_PATH,
            "GITHUB_API_URL": "https://api.github.example",
            "GITHUB_SERVER_URL": "https://github.example",
            "REPOSITORY": "lightning-it/.github",
            "PR_NUMBER": "554",
            "EXPECTED_BASE": "a" * 40,
            "EXPECTED_HEAD": "b" * 40,
            "author": "litroc",
            "base_ref": "develop",
            "producer": json.dumps(producer),
            "PRODUCER": json.dumps(producer),
            "LIVE_PR": json.dumps({
                "number": 554,
                "state": "open",
                "draft": False,
                "user": {"login": "litroc"},
                "base": {
                    "ref": "develop",
                    "sha": "a" * 40,
                    "repo": {"full_name": "lightning-it/.github"},
                },
                "head": {
                    "ref": "fix/renamed",
                    "sha": "b" * 40,
                    "repo": {"full_name": "lightning-it/.github"},
                },
            }),
            "PAGES": json.dumps(pages),
            "CROSS_FILTER": self._cross_run_inventory_filter(),
            "PROTECTED": json.dumps(self._protected_run()),
            "CROSS": json.dumps(cross),
            "run_id": "900",
            "verifier_run_url": (
                "https://github.example/lightning-it/.github/actions/runs/900"
            ),
        }
        accepted = subprocess.run(
            [self._test_tool("bash"), "-c", script],
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, accepted.returncode, accepted.stderr)
        release_v4 = {
            "head_branch": "develop",
            "pull_requests": [],
        }
        environment["PRODUCER"] = json.dumps(release_v4)
        accepted_release = subprocess.run(
            [self._test_tool("bash"), "-c", script],
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, accepted_release.returncode, accepted_release.stderr)

        inconsistent = json.loads(json.dumps(cross))
        inconsistent["pull_requests"][0]["head"]["ref"] = "fix/other"
        environment["CROSS"] = json.dumps(inconsistent)
        environment["PAGES"] = json.dumps([
            {"total_count": 1, "workflow_runs": [inconsistent]}
        ])
        rejected = subprocess.run(
            [self._test_tool("bash"), "-c", script],
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertNotEqual(0, rejected.returncode)


if __name__ == "__main__":
    unittest.main()
