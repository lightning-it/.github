from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = (
    ROOT / ".github" / "workflows" / "supplementary-current-revision-required.yml"
)


class SupplementaryRequiredWorkflowTests(unittest.TestCase):
    def test_required_workflow_is_external_ai_free_and_source_bound(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("pull_request_target:", workflow)
        self.assertNotIn("types:", workflow)
        self.assertNotIn("actions/checkout@", workflow)
        self.assertNotIn("openai/codex-action@", workflow)
        self.assertIn(
            "if: github.repository == 'lightning-it/ansible-collection-supplementary'",
            workflow,
        )
        self.assertIn("WORKFLOW_REF: ${{ github.workflow_ref }}", workflow)
        self.assertIn("@refs/heads/main'", workflow)
        self.assertIn('test "${WORKFLOW_SHA}" = "${source_sha}"', workflow)

    def test_required_workflow_validates_exact_neutral_producer(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("Protected current-revision verifier", workflow)
        self.assertIn("rep60-required-workflow:v1:${PR_NUMBER}:${EVENT_HEAD}", workflow)
        self.assertIn(".app.id == 15368", workflow)
        self.assertIn(
            '.path == ".github/workflows/release-bot-exact-head-review.yml"',
            workflow,
        )
        self.assertIn('.path == ".github/workflows/copilot-review.yml"', workflow)
        self.assertIn('.event == "workflow_dispatch"', workflow)
        self.assertIn(
            'expected_title="Exact-Revision Codex PR #${PR_NUMBER} '
            '${EVENT_BASE}..${EVENT_HEAD}"',
            workflow,
        )
        self.assertIn("and .display_title == $title", workflow)
        self.assertIn('.event == "pull_request_target"', workflow)
        self.assertIn('.name == "Current revision review gate"', workflow)
        self.assertIn(
            "mlx90-current-revision:copilot:v3:${EVENT_BASE}:${EVENT_HEAD}",
            workflow,
        )
        self.assertIn("and .base_sha == $base", workflow)
        self.assertIn(".run_attempt == 1", workflow)
        self.assertIn(".triggering_actor.login == $actor", workflow)
        self.assertIn(".input_sha256 | test", workflow)

    def test_head_repository_is_explicit_and_release_app_is_same_repo(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn(
            "head_repository=\"$(jq -er '.head.repo.full_name | "
            'select(type == "string" and length > 0)\'',
            workflow,
        )
        self.assertIn(
            'head_commit="$(gh api "repos/${head_repository}/commits/${EVENT_HEAD}")"',
            workflow,
        )
        self.assertIn(
            '[[ "${head_repository}" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]]',
            workflow,
        )
        self.assertIn(
            'target_commit="$(gh api "repos/${REPOSITORY}/commits/${EVENT_HEAD}")"',
            workflow,
        )
        self.assertIn('test "${head_repository}" = "${REPOSITORY}"', workflow)

    def test_api_identity_and_draft_types_fail_closed(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn(
            "author=\"$(jq -er '.user.login | "
            'select(type == "string" and length > 0)\'',
            workflow,
        )
        self.assertIn(
            'draft="$(jq -er \'.draft | select(type == "boolean")\'',
            workflow,
        )
        self.assertIn('test "${draft}" = false', workflow)
        self.assertNotIn('jq -r .draft <<<"${pr}"', workflow)

    def test_draft_open_reserves_a_single_later_rerun(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        reservation = workflow.index("reservation_external_id=")
        trap = workflow.index("trap finalize_failure ERR")
        draft = workflow.index('test "${draft}" = false')
        self.assertLess(reservation, trap)
        self.assertLess(trap, draft)
        self.assertIn(
            'test "${GITHUB_RUN_ATTEMPT}" -eq 1 || test "${GITHUB_RUN_ATTEMPT}" -eq 2',
            workflow,
        )
        self.assertIn(
            'reservation_id="$(jq -er \'.[0].id | select(type == "number" and . > 0)\'',
            workflow,
        )


if __name__ == "__main__":
    unittest.main()
