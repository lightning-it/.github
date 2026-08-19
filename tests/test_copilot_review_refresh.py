import json
from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
REFRESH_WORKFLOW = ROOT / ".github/workflows/copilot-review-refresh.yml"
RERUN_WORKFLOW = ROOT / ".github/workflows/current-revision-rerun.yml"


class CopilotReviewRefreshTests(unittest.TestCase):
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

    def _run_refresh_filter(
        self,
        *,
        author: str,
        external_id: str,
        pull_request_number: int | None,
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
        check = {
            "status": "completed",
            "conclusion": "success",
            "details_url": "https://github.example/runs/42",
            "external_id": external_id,
            "output": {"summary": json.dumps(summary)},
        }
        return subprocess.run(
            [
                "jq",
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

    def test_event_specific_payloads_are_guarded(self) -> None:
        workflow = REFRESH_WORKFLOW.read_text(encoding="utf-8")

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
            "mlx90-current-revision:(copilot|ancestry-backmerge):v6", workflow
        )
        self.assertIn(
            "mlx90-current-revision:(copilot|ancestry-backmerge):v5", workflow
        )
        self.assertIn('evidence_version=v6', workflow)
        self.assertIn('evidence_version=v5', workflow)
        self.assertIn('if $evidence_version == "v6" then', workflow)
        self.assertIn('has("pull_request_number")', workflow)
        self.assertIn('.pull_request_number == $pr_number', workflow)

    def test_refresh_evidence_matrix_is_author_and_version_bound(self) -> None:
        base = "a" * 40
        head = "b" * 40
        release_app = "lightning-it-release-automation[bot]"
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

        rejected = (
            ("litroc", f"mlx90-current-revision:copilot:v6:123:77:{base}:{head}", None),
            ("litroc", f"mlx90-current-revision:copilot:v5:77:{base}:{head}", 999),
            (release_app, f"mlx90-current-revision:copilot:v5:77:{base}:{head}", None),
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

    def test_rerun_summary_requires_pr_binding_only_for_v6(self) -> None:
        summary = {
            "schema": 4,
            "base_sha": "a" * 40,
            "head_sha": "b" * 40,
            "producer_run_id": 77,
            "run_url": "https://github.example/actions/runs/77",
        }

        def run(version: str, evidence: dict[str, object]) -> int:
            result = subprocess.run(
                [
                    "jq",
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
            return result.returncode

        self.assertEqual(0, run("v5", summary))
        self.assertEqual(0, run("v4", summary))
        self.assertNotEqual(0, run("v6", summary))
        self.assertEqual(0, run("v6", {**summary, "pull_request_number": 123}))
        self.assertNotEqual(0, run("v5", {**summary, "pull_request_number": 999}))


if __name__ == "__main__":
    unittest.main()
