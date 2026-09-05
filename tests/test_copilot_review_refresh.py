import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]
REFRESH_WORKFLOW = ROOT / ".github/workflows/copilot-review-refresh.yml"
RERUN_WORKFLOW = ROOT / ".github/workflows/current-revision-rerun.yml"
TEST_TOOL_PATH = "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"
FAKE_TIMEOUT_PASSTHROUGH = r'''timeout() {
  while [ "${1:-}" != gh ]; do
    [ "$#" -gt 0 ] || return 98
    shift
  done
  "$@"
}'''


class CopilotReviewRefreshTests(unittest.TestCase):
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
        marker = '              --arg url "${check_url}" \'\n'
        start = workflow.index(marker) + len(marker)
        end = workflow.index('\n              \' <<<"${neutral}"', start)
        return workflow[start:end]

    @staticmethod
    def _rerun_summary_filter() -> str:
        workflow = RERUN_WORKFLOW.read_text(encoding="utf-8")
        marker = '            --argjson run_id "${producer_id}" \'\n'
        start = workflow.index(marker) + len(marker)
        end = workflow.index('\n            \' <<<"${neutral_summary}"', start)
        return workflow[start:end]

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
    def _rerun_shell_function(name: str) -> str:
        workflow = RERUN_WORKFLOW.read_text(encoding="utf-8")
        marker = f"          {name}() {{\n"
        start = workflow.index(marker)
        end = workflow.index("\n          }\n", start) + len(
            "\n          }\n"
        )
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
                self._rerun_shell_function("validate_neutral_snapshot"),
                self._rerun_shell_function("validate_cross_run_binding"),
                self._rerun_shell_function(
                    "validate_cross_rerun_authorization"
                ),
                self._rerun_shell_function(
                    "authorize_cross_rerun_transaction"
                ),
                self._rerun_shell_function("rerun_cross_job_once"),
                FAKE_TIMEOUT_PASSTHROUGH,
                r'''revalidate_neutral_authorization() {
  printf 'ORDER:neutral\n' >&2
  test "${NEUTRAL_AUTHORIZED}" = true || return 1
  printf '%s\n' "${NEUTRAL}"
}
read_run_with_retry() {
  printf 'ORDER:cross_detail\n' >&2
  printf '%s\n' "${CROSS}"
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
  else
    printf 'unexpected fake gh endpoint: %s\n' "${endpoint}" >&2
    return 88
  fi
}''',
                'if [ "${DEADLINE_EXPIRED}" = true ]; then '
                "OPERATION_DEADLINE=${SECONDS}; else "
                "OPERATION_DEADLINE=$((SECONDS + 100)); fi",
                "rerun_cross_job_once",
                "printf 'POST_AUTHORIZED\\n'",
            )
        )
        cross_run_id = int(cross["id"])
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
                "neutral_details_url": str(frozen_neutral["details_url"]),
                "neutral_external_id": str(frozen_neutral["external_id"]),
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
        repository: str = "lightning-it/.github",
        review_path: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        base = "a" * 40
        head = "b" * 40
        summary: dict[str, object] = {
            "schema": 4,
            "base_sha": base,
            "head_sha": head,
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
                    "head",
                    head,
                    "--arg",
                    "pr",
                    "123",
                    "--arg",
                    "repository",
                    repository,
                    "--argjson",
                    "pr_number",
                    "123",
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

    def test_central_rerun_helper_rechecks_the_independent_required_workflow(
        self,
    ) -> None:
        workflow = RERUN_WORKFLOW.read_text(encoding="utf-8")

        post = '"repos/${REPOSITORY}/actions/jobs/${cross_job_id}/rerun"'
        protected_post = (
            '"repos/${REPOSITORY}/actions/runs/${run_id}/rerun"'
        )
        self.assertEqual(1, workflow.count(post))
        self.assertEqual(1, workflow.count(protected_post))

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

    def test_bounded_api_uses_remaining_deadline_and_propagates_timeout(
        self,
    ) -> None:
        script = "\n".join(
            (
                "set -euo pipefail",
                self._rerun_shell_function("require_deadline"),
                self._rerun_shell_function("bounded_gh_api"),
                r'''timeout() {
  printf '%s\n' "$*" >"${TIMEOUT_ARGS_FILE}"
  if [ "${TIMEOUT_STATUS}" -ne 0 ]; then
    return "${TIMEOUT_STATUS}"
  fi
  while [ "${1:-}" != gh ]; do
    [ "$#" -gt 0 ] || return 98
    shift
  done
  "$@"
}
gh() {
  test "${1:-}" = api || return 88
  shift
  printf 'API_OK:%s\n' "$*"
}
SECONDS=100
OPERATION_DEADLINE=$((SECONDS + DEADLINE_OFFSET))
api_status=0
api_output="$(bounded_gh_api repos/lightning-it/.github)" \
  || api_status=$?
printf 'STATUS:%s\n' "${api_status}"
printf 'OUTPUT:%s\n' "${api_output}"''',
            )
        )

        def run(
            *, deadline_offset: int, timeout_status: int = 0
        ) -> tuple[subprocess.CompletedProcess[str], str]:
            with tempfile.TemporaryDirectory() as temp_dir:
                args_file = Path(temp_dir) / "timeout-args"
                args_file.write_text("", encoding="utf-8")
                result = subprocess.run(
                    [self._test_tool("bash"), "-c", script],
                    text=True,
                    capture_output=True,
                    check=False,
                    env={
                        "PATH": TEST_TOOL_PATH,
                        "DEADLINE_OFFSET": str(deadline_offset),
                        "TIMEOUT_STATUS": str(timeout_status),
                        "TIMEOUT_ARGS_FILE": str(args_file),
                    },
                )
                timeout_args = args_file.read_text(encoding="utf-8")
            return result, timeout_args

        result, timeout_args = run(deadline_offset=100)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("STATUS:0", result.stdout)
        self.assertIn("API_OK:repos/lightning-it/.github", result.stdout)
        self.assertEqual(
            "--foreground --signal=TERM --kill-after=2s 30s gh api "
            "repos/lightning-it/.github\n",
            timeout_args,
        )

        result, timeout_args = run(deadline_offset=10)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("STATUS:0", result.stdout)
        self.assertIn("--kill-after=2s 8s gh api", timeout_args)

        result, timeout_args = run(
            deadline_offset=100, timeout_status=124
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("STATUS:124", result.stdout)
        self.assertNotEqual("", timeout_args)

        result, timeout_args = run(deadline_offset=0)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("STATUS:1", result.stdout)
        self.assertEqual("", timeout_args)
        self.assertIn("shared re-evaluation deadline", result.stderr)

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
        )
        self.assertEqual(0, accepted.returncode, accepted.stderr)
        self.assertEqual("POST_AUTHORIZED\n", accepted.stdout)
        ordered_reads = (
            "ORDER:neutral",
            "ORDER:pr",
            "ORDER:reservation",
            "ORDER:cross_detail",
            "ORDER:cross_job",
            "ORDER:reservation_inventory",
            "ORDER:cross_inventory",
            "ORDER:POST",
        )
        observed_order = [accepted.stderr.index(item) for item in ordered_reads]
        self.assertEqual(sorted(observed_order), observed_order)

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
            "conclusion": "success",
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

        protected_sequence = [
            self._protected_run(),
            self._protected_run(
                attempt=2, status="in_progress", conclusion=None
            ),
            self._protected_run(attempt=2, conclusion="success"),
        ]
        result, observations = execute(
            "wait_for_protected_attempt_two_success",
            "validate_protected_run_binding",
            protected_sequence,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(3, observations)

        cross_sequence = [
            self._cross_run(
                202, "2026-09-05T11:00:00Z", conclusion="failure"
            ),
            self._cross_run(
                202,
                "2026-09-05T11:00:00Z",
                attempt=2,
                status="in_progress",
                conclusion=None,
            ),
            self._cross_run(
                202,
                "2026-09-05T11:00:00Z",
                attempt=2,
                conclusion="success",
            ),
        ]
        result, observations = execute(
            "wait_for_cross_attempt_two_success",
            "validate_cross_run_binding",
            cross_sequence,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(3, observations)

        failed_attempt_two = self._cross_run(
            202,
            "2026-09-05T11:00:00Z",
            attempt=2,
            conclusion="failure",
        )
        result, observations = execute(
            "wait_for_cross_attempt_two_success",
            "validate_cross_run_binding",
            [failed_attempt_two],
        )
        self.assertNotEqual(0, result.returncode)
        self.assertEqual(1, observations)

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
        )
        for author, external_id, pull_request_number in cases:
            with self.subTest(external_id=external_id):
                result = self._run_refresh_filter(
                    author=author,
                    external_id=external_id,
                    pull_request_number=pull_request_number,
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


if __name__ == "__main__":
    unittest.main()
