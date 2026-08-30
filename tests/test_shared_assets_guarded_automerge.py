from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/shared-assets-guarded-automerge.yml"


class SharedAssetsGuardedAutomergeTests(unittest.TestCase):
    def test_policy_token_is_minted_only_after_exact_identity_validation(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        guard = workflow.index("- name: Verify automated sync PR identity")
        verify = workflow.index(
            "- name: Verify exact provenance before merge finalization"
        )
        finalizer_job = workflow.index("finalize-shared-assets-merge:")
        mint = workflow.index("- name: Mint finalizer policy-read App token")
        finalize = workflow.index(
            "- name: Re-prove completed guard and merge exact head"
        )

        self.assertLess(guard, verify)
        self.assertLess(verify, finalizer_job)
        self.assertLess(finalizer_job, mint)
        self.assertLess(mint, finalize)
        self.assertLess(verify, finalize)
        provenance_guard = workflow[verify:finalizer_job]
        self.assertIn(
            "PR_BASE_SHA: ${{ github.event.pull_request.base.sha }}",
            provenance_guard,
        )
        self.assertIn('--arg base_sha "$PR_BASE_SHA"', provenance_guard)
        self.assertIn("and (.base.sha == $base_sha)", provenance_guard)
        finalizer_guard = workflow[finalizer_job:mint]
        self.assertIn("needs: verify-shared-assets", finalizer_guard)
        self.assertIn(
            "needs.verify-shared-assets.outputs.trusted == 'true'",
            finalizer_guard,
        )
        self.assertIn("    timeout-minutes: 35\n", finalizer_guard)
        self.assertNotIn('gh pr merge "$PR_URL" --merge', workflow[verify:finalize])
        self.assertIn("completed_guard_is_bound()", workflow[finalize:])
        self.assertIn("required_checks_state()", workflow[finalize:])
        self.assertIn("strict_base_guard_is_enforced()", workflow[finalize:])
        self.assertIn("deadline=$((SECONDS + 1800))", workflow[finalize:])
        self.assertIn(
            'while [ "$SECONDS" -lt "$deadline" ]; do', workflow[finalize:]
        )
        self.assertIn("sleep_for=60", workflow[finalize:])
        self.assertIn('sleep "$sleep_for"', workflow[finalize:])
        self.assertNotIn("for _ in $(seq 1 180); do", workflow[finalize:])
        self.assertNotIn("for _ in $(seq 1 60); do", workflow[finalize:])
        self.assertIn(
            ".parameters.strict_required_status_checks_policy // false",
            workflow[finalize:],
        )
        self.assertIn("$classic.strict // false", workflow[finalize:])
        self.assertIn("| any(.[]; . == true)", workflow[finalize:])
        self.assertEqual(1, workflow[finalize:].count('"$classic" >&2'))
        self.assertEqual(
            3,
            workflow[finalize:].count("strict_base_guard_is_enforced"),
        )
        self.assertEqual(
            2,
            workflow.count(
                'if auto_merge_enabled="$(query_auto_merge)"; then'
            ),
        )
        self.assertEqual(
            2,
            workflow.count(
                'if ! auto_merge_enabled="$(query_auto_merge)"; then'
            ),
        )
        self.assertEqual(2, workflow.count('            disable_error=""'))
        self.assertEqual(
            4,
            workflow.count(
                '              [ -z "$disable_error" ] || printf '
                "'%s\\n' \"$disable_error\" >&2"
            ),
        )
        self.assertNotIn(
            '            auto_merge_enabled="$(query_auto_merge)"\n'
            '            [ "$auto_merge_enabled" = false ] && return 0',
            workflow,
        )
        self.assertIn(
            "          disable_auto_merge\n"
            "          if ! wait_for_required_checks; then\n"
            "            disable_auto_merge\n"
            "            exit 1\n"
            "          fi\n",
            workflow[finalize:],
        )
        self.assertIn(
            'all(.[]; .context != "Finalize exact trusted shared-assets merge")',
            workflow[finalize:],
        )
        self.assertIn(
            "          required_checks_state\n"
            "          # GitHub re-evaluates this strict up-to-date policy "
            "atomically while\n"
            "          # accepting the merge, so a concurrent base advance "
            "rejects it.\n"
            "          strict_base_guard_is_enforced\n\n"
            '          gh pr merge "$PR_URL" --merge --delete-branch',
            workflow[finalize:],
        )
        self.assertIn('gh pr merge "$PR_URL" --merge', workflow[finalize:])
        post_merge = workflow.index('          merged_pr=""', finalize)
        self.assertIn(
            '--arg base_sha "$PR_BASE_SHA"', workflow[finalize:post_merge]
        )
        self.assertIn(
            "and (.base.sha == $base_sha)", workflow[finalize:post_merge]
        )
        self.assertNotIn('--arg base_sha "$PR_BASE_SHA"', workflow[post_merge:])
        self.assertNotIn("and .base.sha == $base_sha", workflow[post_merge:])
        self.assertIn("and .parents[0].sha == $base", workflow[post_merge:])
        self.assertIn("and .parents[1].sha == $head", workflow[post_merge:])

    def test_branch_suffixes_and_provenance_trailers_are_exact(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertEqual(6, workflow.count("=~ ^[1-9][0-9]*-[1-9][0-9]*$"))
        self.assertEqual(
            3,
            workflow.count("Shared-Assets-Source-Attempt: [1-9][0-9]*"),
        )
        self.assertEqual(3, workflow.count("'/^Shared-Assets-/ { count++ }"))
        self.assertEqual(3, workflow.count('managed_trailer_count" -ne 4'))


if __name__ == "__main__":
    unittest.main()
