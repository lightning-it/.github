from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
REFRESH_WORKFLOW = ROOT / ".github/workflows/copilot-review-refresh.yml"


class CopilotReviewRefreshTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
