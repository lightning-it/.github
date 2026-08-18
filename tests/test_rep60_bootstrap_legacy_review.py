"""Temporary invariants for the protected REP-60 bootstrap bridge."""

from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/rep60-bootstrap-legacy-review.yml"


class Rep60BootstrapLegacyReviewTests(unittest.TestCase):
    def test_bridge_is_narrow_base_controlled_and_self_removing(self) -> None:
        text = WORKFLOW.read_text(encoding="utf-8")
        parsed = yaml.safe_load(text)
        triggers = parsed.get("on", parsed.get(True))["pull_request_target"]["types"]
        self.assertEqual(
            ["opened", "synchronize", "reopened", "ready_for_review", "edited"],
            triggers,
        )
        job = parsed["jobs"]["publish-legacy-review"]
        self.assertEqual(
            {"checks": "write", "contents": "read", "pull-requests": "read"},
            job["permissions"],
        )
        self.assertNotIn("actions/checkout@", text)
        self.assertIn("github.event.pull_request.user.login == 'litroc'", text)
        self.assertIn(
            "github.event.pull_request.head.ref == "
            "'fix/rep60-current-revision-rollout-20260818-v1'",
            text,
        )
        self.assertIn('test "${WORKFLOW_SHA}" = "${EVENT_BASE}"', text)
        self.assertIn('test "${GITHUB_SHA}" = "${WORKFLOW_SHA}"', text)
        self.assertIn("([.tree[] | select(.path == $bridge)] | length) == 0", text)
        self.assertIn("current-head Copilot review accepted", text)
        self.assertIn("unresolved findings 0", text)
        self.assertIn("-f name='Successful Copilot review'", text)


if __name__ == "__main__":
    unittest.main()
