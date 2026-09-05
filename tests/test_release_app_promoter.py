"""Regression contract for the protected dot-github release promoter."""

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "promote-develop-to-main.yml"


class ReleaseAppPromoterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")

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
        self.assertIn("installation=\"$(gh api installation)\"", workflow)
        self.assertIn(
            '.app_slug == "lightning-it-release-automation"', workflow
        )
        self.assertIn('.target_type == "Organization"', workflow)
        self.assertIn('.account.login == "lightning-it"', workflow)
        self.assertIn("repositories: ${{ github.event.repository.name }}", workflow)
        self.assertNotIn("Resolve release automation App bot identity", workflow)
        self.assertNotIn("steps.release-bot.outputs", workflow)

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
