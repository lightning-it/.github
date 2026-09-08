"""Regression contract for the protected dot-github release promoter."""

import json
import os
from pathlib import Path
import re
import subprocess
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "promote-develop-to-main.yml"


class ReleaseAppPromoterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")
        cls.token_validation = cls.workflow.split(
            "      - name: Validate release bot token\n", 1
        )[1].split("\n      - name: Create or update protected promotion", 1)[0]
        cls.token_validation_script = textwrap.dedent(
            cls.token_validation.split("        run: |\n", 1)[1]
        )

    def _validate_release_token(
        self,
        response: object | str,
        *,
        app_slug: str = "lightning-it-release-automation",
        installation_id: str = "148019054",
        repository: str = "lightning-it/.github",
        token: str = "release-token",
        api_failure: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        fake_gh = r'''gh() {
  if [ "$#" -ne 4 ] \
    || [ "${1:-}" != api ] \
    || [ "${2:-}" != --paginate ] \
    || [ "${3:-}" != --slurp ] \
    || [ "${4:-}" != "installation/repositories?per_page=100" ]; then
    printf 'unexpected fake gh invocation\n' >&2
    return 88
  fi
  if [ "${GH_TOKEN}" != release-token ]; then
    printf 'unexpected release token\n' >&2
    return 87
  fi
  if [ "${GH_API_FAILURE}" = true ]; then
    return 42
  fi
  printf '%s\n' "${REPOSITORY_PAGES}"
}'''
        script = "\n".join(
            (fake_gh, self.token_validation_script, "printf 'TOKEN_SCOPE_VALID\\n'")
        )
        repository_pages = (
            response if isinstance(response, str) else json.dumps(response)
        )
        return subprocess.run(
            ["bash", "-c", script],
            text=True,
            capture_output=True,
            check=False,
            env={
                **os.environ,
                "APP_INSTALLATION_ID": installation_id,
                "APP_SLUG": app_slug,
                "EXPECTED_APP_SLUG": "lightning-it-release-automation",
                "EXPECTED_INSTALLATION_ID": "148019054",
                "EXPECTED_REPOSITORY": "lightning-it/.github",
                "GH_API_FAILURE": "true" if api_failure else "false",
                "GH_TOKEN": token,
                "REPOSITORY": repository,
                "REPOSITORY_PAGES": repository_pages,
            },
        )

    def test_controller_is_bound_to_dot_github_and_protected_develop(self) -> None:
        workflow = self.workflow

        self.assertIn("branches: [develop]", workflow)
        self.assertIn("workflow_dispatch:", workflow)
        self.assertIn('cron: "41 * * * *"', workflow)
        self.assertEqual(
            workflow.count("if: github.repository == 'lightning-it/.github'"), 1
        )
        self.assertNotIn(
            "if: github.repository == 'lightning-it/shared-assets-lit'", workflow
        )
        self.assertIn(
            "git merge-base --is-ancestor origin/main origin/develop", workflow
        )
        self.assertIn("git diff --quiet origin/main origin/develop", workflow)

    def test_release_app_tokens_are_separate_and_least_privilege(self) -> None:
        workflow = self.workflow

        action = (
            "actions/create-github-app-token@bcd2ba49218906704ab6c1aa796996da409d3eb1"
        )
        self.assertEqual(workflow.count(action), 2)
        self.assertEqual(
            workflow.count("secrets.RELEASE_AUTOMATION_APP_PRIVATE_KEY"), 2
        )
        self.assertEqual(workflow.count("permission-pull-requests: write"), 1)
        self.assertEqual(workflow.count("permission-actions: write"), 1)
        self.assertEqual(workflow.count("permission-contents: read"), 2)
        self.assertNotIn("permission-contents: write", workflow)
        self.assertNotIn("permission-checks: write", workflow)
        self.assertNotRegex(workflow, re.compile(r"(?m)^\s+checks:\s+write\s*$"))
        self.assertIn(
            "APP_SLUG: ${{ steps.release-app.outputs.app-slug }}", workflow
        )
        self.assertIn(
            "APP_INSTALLATION_ID: ${{ steps.release-app.outputs.installation-id }}",
            workflow,
        )
        self.assertIn("EXPECTED_APP_SLUG: lightning-it-release-automation", workflow)
        self.assertIn('EXPECTED_INSTALLATION_ID: "148019054"', workflow)
        self.assertIn("EXPECTED_REPOSITORY: lightning-it/.github", workflow)
        self.assertIn(
            "GH_TOKEN: ${{ steps.release-app.outputs.token }}",
            self.token_validation,
        )
        self.assertIn("gh api --paginate --slurp", self.token_validation)
        self.assertIn("jq -se", self.token_validation)
        self.assertIn(
            '"installation/repositories?per_page=100"', self.token_validation
        )
        self.assertNotIn("gh api installation", workflow)
        self.assertNotIn("users/", self.token_validation)
        self.assertIn("repositories: ${{ github.event.repository.name }}", workflow)
        self.assertNotIn("Resolve release automation App bot identity", workflow)
        self.assertNotIn("steps.release-bot.outputs", workflow)

    def test_release_app_token_accepts_only_exact_repository_scope(self) -> None:
        result = self._validate_release_token(
            [
                {
                    "total_count": 1,
                    "repositories": [{"full_name": "lightning-it/.github"}],
                }
            ]
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("TOKEN_SCOPE_VALID\n", result.stdout)

    def test_release_app_token_rejects_wrong_action_identity_outputs(self) -> None:
        valid_response = [
            {
                "total_count": 1,
                "repositories": [{"full_name": "lightning-it/.github"}],
            }
        ]
        cases = {
            "wrong app slug": {"app_slug": "foreign-app"},
            "missing app slug": {"app_slug": ""},
            "malformed app slug": {
                "app_slug": "lightning-it-release-automation/other"
            },
            "wrong installation id": {"installation_id": "148019055"},
            "missing installation id": {"installation_id": ""},
            "malformed installation id": {"installation_id": "148019054x"},
            "wrong protected repository": {"repository": "lightning-it/other"},
            "missing token": {"token": ""},
            "wrong token": {"token": "foreign-token"},
        }
        for name, overrides in cases.items():
            with self.subTest(case=name):
                result = self._validate_release_token(valid_response, **overrides)
                self.assertNotEqual(0, result.returncode)
                self.assertNotIn("TOKEN_SCOPE_VALID", result.stdout)

    def test_release_app_token_rejects_non_exact_repository_sets(self) -> None:
        cases = {
            "missing repository": [{"total_count": 0, "repositories": []}],
            "duplicate repository": [
                {
                    "total_count": 2,
                    "repositories": [
                        {"full_name": "lightning-it/.github"},
                        {"full_name": "lightning-it/.github"},
                    ],
                }
            ],
            "foreign repository": [
                {
                    "total_count": 1,
                    "repositories": [{"full_name": "lightning-it/other"}],
                }
            ],
            "target plus foreign repository": [
                {
                    "total_count": 2,
                    "repositories": [
                        {"full_name": "lightning-it/.github"},
                        {"full_name": "lightning-it/other"},
                    ],
                }
            ],
        }
        for name, response in cases.items():
            with self.subTest(case=name):
                result = self._validate_release_token(response)
                self.assertNotEqual(0, result.returncode)
                self.assertNotIn("TOKEN_SCOPE_VALID", result.stdout)

    def test_release_app_token_rejects_malformed_api_or_pagination(self) -> None:
        repository = {"full_name": "lightning-it/.github"}
        valid_page = {"total_count": 1, "repositories": [repository]}
        cases: dict[str, object | str] = {
            "invalid json": "not-json",
            "empty response": "",
            "extra leading json document": (
                "false\n" + json.dumps([valid_page])
            ),
            "extra trailing json document": (
                json.dumps([valid_page]) + "\nfalse"
            ),
            "non-array pagination envelope": valid_page,
            "empty pagination envelope": [],
            "multiple pages for one visible repository": [valid_page, valid_page],
            "non-object page": [7],
            "missing total count": [{"repositories": [repository]}],
            "string total count": [
                {"total_count": "1", "repositories": [repository]}
            ],
            "inconsistent total count": [
                {"total_count": 2, "repositories": [repository]}
            ],
            "non-array repositories": [
                {"total_count": 1, "repositories": repository}
            ],
            "non-object repository": [
                {"total_count": 1, "repositories": ["lightning-it/.github"]}
            ],
            "missing full name": [
                {"total_count": 1, "repositories": [{"name": ".github"}]}
            ],
            "non-string full name": [
                {"total_count": 1, "repositories": [{"full_name": 7}]}
            ],
        }
        for name, response in cases.items():
            with self.subTest(case=name):
                result = self._validate_release_token(response)
                self.assertNotEqual(0, result.returncode)
                self.assertNotIn("TOKEN_SCOPE_VALID", result.stdout)

        api_failure = self._validate_release_token([valid_page], api_failure=True)
        self.assertNotEqual(0, api_failure.returncode)
        self.assertNotIn("TOKEN_SCOPE_VALID", api_failure.stdout)

    def test_controller_creates_only_same_repo_develop_to_main_pr(self) -> None:
        workflow = self.workflow

        self.assertIn('"repos/${REPOSITORY}/pulls"', workflow)
        self.assertIn('-f "base=main"', workflow)
        self.assertIn('-f "head=develop"', workflow)
        self.assertIn(".base.repo.full_name == $repository", workflow)
        self.assertIn(".head.repo.full_name == $repository", workflow)
        self.assertIn('.base.ref == "main"', workflow)
        self.assertIn('.head.ref == "develop"', workflow)
        self.assertIn('.user.login == "lightning-it-release-automation[bot]"', workflow)
        self.assertNotIn("gh pr ready", workflow)
        self.assertNotIn("gh pr merge", workflow)
        self.assertNotIn("--auto", workflow)
        self.assertNotIn("--admin", workflow)
        self.assertNotIn("--force", workflow)
        self.assertNotIn("lightning-it/shared-assets-lit", workflow)
        self.assertNotIn("transition_title", workflow)

    def test_exact_revision_review_is_dispatched_once_only_for_new_pr(self) -> None:
        workflow = self.workflow

        dispatch = "gh workflow run release-bot-exact-head-review.yml"
        self.assertEqual(workflow.count(dispatch), 1)
        self.assertEqual(
            workflow.count(
                "if: steps.exact-review-target.outputs.dispatch_review == 'true'"
            ),
            3,
        )
        self.assertIn("dispatch_review=false", workflow)
        self.assertIn("dispatch_review=true", workflow)
        self.assertIn('-f "expected_base=${EXPECTED_BASE}"', workflow)
        self.assertIn('-f "expected_head=${EXPECTED_HEAD}"', workflow)
        dispatch_block = workflow.split(
            "- name: Dispatch protected Exact-Revision review", 1
        )[1].split("- name: Finalize accepted Exact-Revision review dispatch", 1)[0]
        self.assertIn('[[ "${PR_NUMBER}" =~ ^[1-9][0-9]*$ ]]', dispatch_block)
        self.assertIn("automatic review redispatch is forbidden", workflow)
        self.assertNotIn("gh run rerun", workflow)
        self.assertNotIn("gh copilot", workflow.lower())
        self.assertNotIn("openai/codex-action", workflow.lower())

    def test_dispatch_failure_is_tombstoned_and_closed_not_retried(self) -> None:
        workflow = self.workflow

        self.assertIn(
            "if: failure() && steps.release-app.outputs.token != ''", workflow
        )
        self.assertIn("lit-promotion-dispatch-failed:", workflow)
        self.assertIn('-f "state=closed"', workflow)
        self.assertIn("a fresh PR bound to a new develop head is required", workflow)
        self.assertIn(
            "the same develop head remains consumed and cannot be retried", workflow
        )
        cleanup_block = workflow.split(
            "- name: Close unusable promotion after dispatch failure", 1
        )[1]
        self.assertIn(
            'select(startswith("<!-- lit-promotion-head:"))] == [$head_marker]',
            cleanup_block,
        )
        self.assertIn(
            'select(startswith("<!-- lit-promotion-run:"))] == [$run_marker]',
            cleanup_block,
        )
        self.assertIn(
            "($captured_number == 0 or .number == $captured_number)", cleanup_block
        )
        self.assertNotIn("and .head.sha == $head", cleanup_block)


if __name__ == "__main__":
    unittest.main()
