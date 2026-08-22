import json
from pathlib import Path
import shutil
import subprocess
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]
REFRESH_WORKFLOW = ROOT / ".github/workflows/copilot-review-refresh.yml"
RERUN_WORKFLOW = ROOT / ".github/workflows/current-revision-rerun.yml"
TEST_TOOL_PATH = "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"


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
        marker = '            --argjson pr_number "${PR_NUMBER}" \'\n'
        start = workflow.index(marker) + len(marker)
        end = workflow.index('\n            \' <<<"${run}"', start)
        return workflow[start:end]

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
                "event": "pull_request_target",
                "path": ".github/workflows/supplementary-current-revision-required.yml",
                "workflow_id": 337993808,
                "workflow_url": workflow_url,
                "head_branch": "fix/final",
                "head_sha": "b" * 40,
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
            }
            result = subprocess.run(
                [
                    self._test_tool("jq"),
                    "-e",
                    "--arg",
                    "api_url",
                    "https://api.github.example",
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

        self.assertIn("timeout-minutes: 20", workflow)
        self.assertIn(
            "repos/${REPOSITORY}/actions/runs?event=pull_request_target&"
            "head_sha=${EXPECTED_HEAD}&per_page=100",
            workflow,
        )
        self.assertIn(
            '.path == ".github/workflows/'
            'dot-github-current-revision-required.yml"',
            workflow,
        )
        self.assertIn(
            '.workflow_url == ($api_url + "/repos/" + $repository\n'
            '                  + "/actions/required_workflows/"',
            workflow,
        )
        self.assertIn(
            'select(.name == "Required dot-github current-revision workflow")',
            workflow,
        )
        self.assertIn(
            '"repos/${REPOSITORY}/actions/jobs/${cross_job_id}/rerun"',
            workflow,
        )
        self.assertIn(
            "test \"$(jq -r .triggering_actor.login "
            "<<<\"${cross_run}\")\" = 'github-actions[bot]'",
            workflow,
        )
        self.assertIn(
            "Independent dot-github cross-verifier rerun completed "
            "successfully.",
            workflow,
        )
        self.assertLess(
            workflow.index("Protected verifier rerun completed successfully."),
            workflow.index("cross_pages="),
        )

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
            with self.subTest(managed_distribution=external_id):
                result = self._run_refresh_filter(
                    author=sync_app,
                    external_id=external_id,
                    pull_request_number=pull_request_number,
                    repository="lightning-it/website",
                    review_path=(
                        "deterministic provenance-bound managed distribution exemption"
                    ),
                )
                self.assertEqual(0, result.returncode, result.stderr)

                for invalid_review_path in (None, "", "wrong review path"):
                    with self.subTest(invalid_review_path=invalid_review_path):
                        rejected = self._run_refresh_filter(
                            author=sync_app,
                            external_id=external_id,
                            pull_request_number=pull_request_number,
                            repository="lightning-it/website",
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
        self.assertNotEqual(
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
