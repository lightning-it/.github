from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/shared-assets-guarded-automerge.yml"


class SharedAssetsGuardedAutomergeTests(unittest.TestCase):
    def test_policy_token_is_minted_only_after_exact_identity_validation(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        guard = workflow.index("- name: Verify automated sync PR identity")
        mint = workflow.index("- name: Mint policy-read App token")
        approve = workflow.index(
            "- name: Verify required checks and merge exact head"
        )

        self.assertLess(guard, mint)
        self.assertLess(mint, approve)
        mint_block = workflow[mint:approve]
        self.assertIn("if: steps.guard.outputs.trusted == 'true'", mint_block)
        self.assertNotIn("startsWith(", mint_block)

    def test_branch_suffixes_and_provenance_trailers_are_exact(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertEqual(4, workflow.count("=~ ^[1-9][0-9]*-[1-9][0-9]*$"))
        self.assertEqual(
            3,
            workflow.count("Shared-Assets-Source-Attempt: [1-9][0-9]*"),
        )
        self.assertEqual(3, workflow.count("'/^Shared-Assets-/ { count++ }"))
        self.assertEqual(3, workflow.count('managed_trailer_count" -ne 4'))


if __name__ == "__main__":
    unittest.main()
