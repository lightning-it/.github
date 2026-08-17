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
        self.assertIn("@refs/heads/main", workflow)
        self.assertIn(
            '"repos/lightning-it/.github/compare/${WORKFLOW_SHA}...${source_sha}"',
            workflow,
        )
        self.assertIn("and .merge_base_commit.sha == $workflow_sha", workflow)

    def test_required_workflow_validates_exact_neutral_producer(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("Protected current-revision verifier", workflow)
        self.assertIn(
            "rep60-required-workflow:v2:${GITHUB_RUN_ID}:${PR_NUMBER}:${EVENT_HEAD}",
            workflow,
        )
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
            "mlx90-current-revision:copilot:v4:([1-9][0-9]*):${EVENT_BASE}:${EVENT_HEAD}",
            workflow,
        )
        self.assertIn("producer_run_id=\"${BASH_REMATCH[1]}\"", workflow)
        self.assertIn(".producer_run_id == $run_id", workflow)
        self.assertIn(".schema == 4", workflow)
        self.assertIn(
            'test "${details_url}" = "${GITHUB_SERVER_URL}/${REPOSITORY}/runs/${check_id}"',
            workflow,
        )
        self.assertIn("and .base_sha == $base", workflow)
        self.assertNotIn("and .run_attempt == 1", workflow)
        self.assertEqual(workflow.count(".actor.login == $actor"), 2)
        self.assertEqual(workflow.count(".triggering_actor.login == $actor"), 2)
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

    def test_human_producer_is_bound_to_the_protected_default_controller(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        author_paths = workflow.split(
            "          if [ \"${author}\" = 'lightning-it-release-automation[bot]' ]; then\n"
            '            [[ "${external_id}" =~ ^mlx90-current-revision:v4:',
            1,
        )[1]
        human_path = author_paths.split("          else", 1)[1].split("          fi", 1)[0]
        self.assertIn(".controller_sha", human_path)
        self.assertIn('test "${controller_branch}" = develop', human_path)
        self.assertIn("compare/${controller_sha}...${controller_head}", human_path)
        self.assertIn(".head_branch == $controller_branch", human_path)
        self.assertIn(".head_sha == $controller_sha", human_path)
        self.assertIn("and .controller_sha == $controller", human_path)
        self.assertIn("PR base_ref remains independently valid as main or", human_path)
        self.assertNotIn(".head_branch == $base_ref", human_path)
        self.assertNotIn(".head_sha == $base_sha", human_path)

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
        self.assertIn(
            'reservation_id="$(jq -er \'.id | select(type == "number" and . > 0)\'',
            workflow,
        )
        self.assertEqual(
            workflow.count('-f "details_url=${reservation_url}"'),
            2,
        )
        reservation_selection = workflow.split('all_reservations="$(jq -c', 1)[1].split(
            'reservation_count="$(jq', 1
        )[0]
        self.assertIn("select(.head_sha == $head)", reservation_selection)
        self.assertIn("startswith($prefix)", reservation_selection)
        self.assertIn("endswith($suffix)", reservation_selection)
        self.assertIn("belongs to a different PR/head binding", reservation_selection)
        self.assertEqual(
            workflow.count('-f external_id="${reservation_external_id}"'),
            3,
        )
        self.assertIn(
            "^rep60-required-workflow:v2:[1-9][0-9]*:${PR_NUMBER}:${EVENT_HEAD}$",
            workflow,
        )
        self.assertLess(
            workflow.index('prior_external_id="$(jq -er'),
            workflow.index('-f external_id="${reservation_external_id}"'),
        )

    def test_one_time_main_bootstrap_is_immutable_ai_free_and_not_acceptance(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        transition = workflow.split(
            "          # One immutable transition is needed because the first main promotion",
            1,
        )[1].split(
            '          test "${draft}" = false\n'
            '          neutral_pages="$(gh api --paginate --slurp',
            1,
        )[0]
        self.assertIn('[ "${PR_NUMBER}" = 776 ]', transition)
        self.assertIn(
            "01afb46890e6d7ac6008e8ed478aa6af91e1b19b",
            transition,
        )
        self.assertIn(
            "7a6cadc2c1048daec4a69ff0f71441b6ff257416",
            transition,
        )
        self.assertIn(
            "7c19ce8303b313b2911e2f8abd075a7b5b2fecd6",
            transition,
        )
        self.assertIn(".commit.verification.verified == true", transition)
        self.assertIn(".merge_commit_sha ==", transition)
        self.assertIn("and .ahead_by == 62", transition)
        self.assertIn("and .commits[-1].sha == $head", transition)
        self.assertIn(
            'local file_name="$1" expected_blob="$2" observed_blob',
            transition,
        )
        self.assertIn("all(.[].user.login;", transition)
        self.assertIn("copilot-pull-request-reviewer[bot]", transition)
        self.assertIn("Protected%20Exact-Revision%20Codex%20result", transition)
        self.assertIn('acceptance_evidence: false', transition)
        self.assertIn('review_path: "immutable one-time controller bootstrap; no AI"', transition)
        self.assertIn("rep60-main-bootstrap:v1:", transition)
        self.assertIn("-f name='Current revision review'", transition)
        self.assertNotIn("openai/codex-action@", transition)
        self.assertNotIn("copilot-requests", transition)


if __name__ == "__main__":
    unittest.main()
