from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/renovate-guarded-automerge.yml"


class RenovateGuardedAutomergeTests(unittest.TestCase):
    def test_disable_race_rechecks_live_auto_merge_state(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("query_auto_merge() {", workflow)
        self.assertIn('auto_merge_enabled="$(query_auto_merge)"', workflow)
        self.assertIn("if ! disable_error=\"$(", workflow)
        self.assertGreaterEqual(
            workflow.count('auto_merge_enabled="$(query_auto_merge)"'), 2
        )
        self.assertIn('if [ "$auto_merge_enabled" != false ]; then', workflow)
        self.assertIn("printf '%s\\n' \"$disable_error\" >&2", workflow)
        self.assertIn(
            'gh pr merge "${PR_URL}" --auto --merge --delete-branch',
            workflow,
        )


if __name__ == "__main__":
    unittest.main()
