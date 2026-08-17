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
        source_compare = workflow.split('source_compare="$(gh api', 1)[1].split(
            '          test "${GITHUB_RUN_ATTEMPT}"', 1
        )[0]
        self.assertIn('(.status == "identical"', source_compare)
        self.assertIn('and $source_sha == $workflow_sha', source_compare)
        self.assertIn('and .head_commit == null', source_compare)
        self.assertIn('(.status == "ahead"', source_compare)
        self.assertIn('and $source_sha != $workflow_sha', source_compare)
        self.assertIn('and .head_commit.sha == $source_sha', source_compare)

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

    def test_human_producer_separates_event_head_from_protected_controller(self) -> None:
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
        self.assertIn('--arg head_ref "${head_ref}"', human_path)
        self.assertIn('--arg head_sha "${EVENT_HEAD}"', human_path)
        self.assertIn(".head_branch == $head_ref", human_path)
        self.assertIn(".head_sha == $head_sha", human_path)
        self.assertIn("and .controller_sha == $controller", human_path)
        self.assertIn("PR base_ref remains independently valid as main or", human_path)
        self.assertNotIn(".head_branch == $controller_branch", human_path)
        self.assertNotIn(".head_sha == $controller_sha", human_path)

    def test_api_identity_and_draft_types_fail_closed(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn(
            "author=\"$(jq -er '.user.login | "
            'select(type == "string" and length > 0)\'',
            workflow,
        )
        self.assertIn(
            'draft="$(jq -er \'.draft | select(type == "boolean") | tostring\'',
            workflow,
        )
        self.assertIn('test "${draft}" = false', workflow)
        self.assertNotIn('jq -r .draft <<<"${pr}"', workflow)

    def test_failure_diagnostics_are_fixed_stage_names_only(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("trap report_failure_stage EXIT", workflow)
        self.assertIn(
            "::error title=REP-60 verifier failed closed::stage=%s",
            workflow,
        )
        expected_stages = {
            "initialization",
            "protected-source-binding",
            "event-metadata-binding",
            "live-pr-binding",
            "live-commit-binding",
            "reservation-inventory",
            "reservation-materialization",
            "producer-evidence-selection",
            "transition-static-provenance",
            "transition-ai-absence",
            "transition-neutral-check",
            "transition-finalization",
            "human-transition-static-provenance",
            "human-transition-review",
            "human-transition-neutral-check",
            "human-transition-finalization",
            "permanent-producer-inventory",
            "permanent-producer-binding",
            "permanent-finalization",
        }
        observed_stages = {
            line.strip().split("=", 1)[1].strip("'")
            for line in workflow.splitlines()
            if line.strip().startswith("failure_stage=")
        }
        self.assertEqual(observed_stages, expected_stages)
        self.assertIn("stage ${failure_stage}; fail-closed", workflow)
        self.assertIn("trap - ERR", workflow)
        self.assertIn('exit "${exit_code}"', workflow)
        self.assertNotIn('return "${exit_code}"', workflow)

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
            "          # One exact protected transition repairs the human producer's",
            1,
        )[0]
        self.assertIn('[ "${PR_NUMBER}" = 777 ]', transition)
        self.assertIn(
            'test "${GITHUB_ACTOR}" = \'lightning-it-release-automation[bot]\'',
            transition,
        )
        self.assertIn(
            'test "${GITHUB_TRIGGERING_ACTOR}" = '
            '\'lightning-it-release-automation[bot]\'',
            transition,
        )
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
        self.assertIn("copilot-pull-request-reviewer[bot]", transition)
        self.assertIn("Protected%20Exact-Revision%20Codex%20result", transition)
        self.assertIn('acceptance_evidence: false', transition)
        self.assertIn('review_path: "immutable one-time controller bootstrap; no AI"', transition)
        self.assertIn("rep60-main-bootstrap:v1:", transition)
        self.assertIn("-f name='Current revision review'", transition)
        self.assertIn(
            'neutral_pages="$(gh api --paginate --slurp',
            transition,
        )
        self.assertIn(
            'review_pages="$(gh api --paginate --slurp',
            transition,
        )
        self.assertIn("all(.[][]?;", transition)
        self.assertIn(
            '(.user.login | type == "string" and length > 0)',
            transition,
        )
        self.assertIn(
            'exact_check_pages="$(gh api --paginate --slurp',
            transition,
        )
        self.assertIn('if [ "${neutral_count}" -gt 1 ]; then', transition)
        self.assertIn('if [ "${neutral_count}" -eq 1 ]; then', transition)
        self.assertIn('and .external_id == $external_id', transition)
        self.assertIn('and .output.title == $title', transition)
        self.assertIn('and .output.summary == $evidence', transition)
        self.assertEqual(transition.count('-f name=\'Current revision review\''), 1)
        self.assertLess(
            transition.index(
                "output[title]=Immutable one-time main-controller bootstrap verified"
            ),
            transition.index("trap - ERR"),
        )
        self.assertNotIn("openai/codex-action@", transition)
        self.assertNotIn("copilot-requests", transition)

        permanent = workflow.split(
            '          test "${draft}" = false\n'
            '          neutral_pages="$(gh api --paginate --slurp',
            1,
        )[1]
        self.assertLess(
            permanent.index(
                "output[title]=Protected current-revision evidence verified"
            ),
            permanent.index("trap - ERR"),
        )

    def test_one_time_human_provenance_transition_is_exact_and_review_bound(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        transition = workflow.split(
            "          # One exact protected transition repairs the human producer's",
            1,
        )[1].split("          failure_stage='permanent-producer-inventory'", 1)[0]
        self.assertIn('[ "${PR_NUMBER}" = 779 ]', transition)
        self.assertIn("7a6cadc2c1048daec4a69ff0f71441b6ff257416", transition)
        self.assertIn("c354f0199b3b8beb9fd8eccc25de367e4a7dfe50", transition)
        self.assertIn("a232c2282ba142bf44829e78d2ebbce6a8af299e", transition)
        self.assertIn("fix/rep60-current-revision-provenance-rearm-20260817", transition)
        self.assertIn("and .ahead_by == 1", transition)
        self.assertIn("and .total_commits == 1", transition)
        self.assertIn("pulls/779/files?per_page=100", transition)
        for blob in (
            "d0c403f0185ade0637c2820af3d4abe2f99cefd0",
            "ec93b568838aee70214d2c02b73a67b870d82ab8",
            "d463e75bb1667ac08465aeb78dcf7692b93dd696",
            "e29cf8ab2c1a0311030fc059497604287f291df9",
            "a7b62d83649c3561d20dd1b07a0536a62f38361c",
            "8f7e69631b0b5181b61c91c0e1a5f5b55d685ee6",
        ):
            self.assertIn(blob, transition)
        self.assertIn("copilot-pull-request-reviewer[bot]", transition)
        self.assertIn("and .commit_id == $head", transition)
        self.assertIn('test "$(jq \'length\' <<<"${accepted_reviews}")" -eq 1', transition)
        self.assertIn("reviewThreads(first:100,after:$after)", transition)
        self.assertIn('test "${unresolved}" -eq 0', transition)
        self.assertIn('review_path: "exact current-head Copilot review"', transition)
        self.assertIn("rep60-human-provenance-transition:v1:", transition)
        self.assertIn("-f name='Current revision review'", transition)
        self.assertIn("acceptance_evidence: true", transition)
        self.assertNotIn("openai/codex-action@", transition)
        self.assertNotIn("copilot-requests", transition)


if __name__ == "__main__":
    unittest.main()
