from pathlib import Path
import unittest


def guarded_automerge_workflow() -> Path:
    """Resolve the one workflow in source and distributed test layouts."""
    test_root = Path(__file__).resolve().parents[1]
    relative = Path(".github/workflows/shared-assets-guarded-automerge.yml")
    candidates = (test_root / relative, test_root.parent / relative)
    workflows = [
        candidate
        for candidate in candidates
        if candidate.is_file() and not candidate.is_symlink()
    ]
    if len(workflows) != 1:
        raise RuntimeError(
            "expected exactly one regular shared-assets guarded-automerge workflow"
        )
    return workflows[0]


WORKFLOW = guarded_automerge_workflow()


class SharedAssetsGuardedAutomergeTests(unittest.TestCase):
    def test_protected_helper_completion_can_only_reenter_exact_guard(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        trigger = workflow.split("on:\n", 1)[1].split("\npermissions:", 1)[0]
        self.assertIn(
            'workflows: ["Re-evaluate protected current-revision evidence"]',
            trigger,
        )
        self.assertIn("types: [completed]", trigger)
        self.assertIn("branches: [develop]", trigger)
        self.assertNotIn("workflow_dispatch:", trigger)

        classify = workflow.split(
            "  classify-shared-assets-invocation:", 1
        )[1].split("\n  verify-shared-assets:", 1)[0]
        for binding in (
            "github.event.workflow_run.event == 'workflow_dispatch'",
            "github.event.workflow_run.conclusion == 'success'",
            "github.event.workflow_run.path",
            "== '.github/workflows/current-revision-rerun.yml'",
            "github.event.workflow_run.head_branch == 'develop'",
            "github.event.workflow_run.run_attempt == 1",
            "github.event.workflow_run.actor.login == 'github-actions[bot]'",
            "github.event.workflow_run.triggering_actor.login",
        ):
            self.assertIn(binding, classify)
        for runtime_binding in (
            "EVENT_DEFAULT_BRANCH: ${{ github.event.repository.default_branch }}",
            "LISTENER_REF_PROTECTED: ${{ github.ref_protected }}",
            "LISTENER_WORKFLOW_SHA: ${{ github.workflow_sha }}",
            'test "${LISTENER_REF_PROTECTED}" = true',
            'test "${LISTENER_REF}" = "refs/heads/${EVENT_DEFAULT_BRANCH}"',
            'test "${LISTENER_SHA}" = "${LISTENER_WORKFLOW_SHA}"',
            'and .default_branch == $default_branch',
            'and .protected == true',
            'and .commit.sha == $workflow_sha',
        ):
            self.assertIn(runtime_binding, classify)
        self.assertNotIn(
            "shared-assets-guarded-automerge.yml@refs/heads/develop",
            classify,
        )
        self.assertIn("Malformed protected helper title binding.", classify)
        self.assertIn("actions/runs/${HELPER_RUN_ID}", classify)
        self.assertIn("Re-run the one protected verifier attempt", classify)
        self.assertIn("($matches | length) == 1", classify)
        self.assertIn("$matches[0].runner_id > 0", classify)
        self.assertIn('$matches[0].conclusion == "success"', classify)

        verifier = workflow.split("  verify-shared-assets:", 1)[1].split(
            "\n  finalize-shared-assets-merge:", 1
        )[0]
        self.assertIn(
            "${{ github.event.workflow_run.actor.login || github.actor }}",
            verifier,
        )
        self.assertIn(
            "github.event.workflow_run.triggering_actor.login",
            verifier,
        )
        self.assertIn(
            'workflow_run:"github-actions[bot]":"github-actions[bot]"',
            verifier,
        )
        self.assertNotIn(
            "workflow_run:github-actions[bot]:github-actions[bot]",
            verifier,
        )

        finalizer = workflow.split("  finalize-shared-assets-merge:", 1)[1]
        self.assertIn(
            "needs: [classify-shared-assets-invocation, verify-shared-assets]",
            finalizer,
        )
        self.assertIn(
            "needs.classify-shared-assets-invocation.outputs.head_sha",
            finalizer,
        )

    def test_trust_decision_uses_rebound_live_draft_state(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        guard = workflow.index("- name: Verify automated sync PR identity")
        revoke = workflow.index(
            "- name: Revoke auto-merge for an untrusted state or event"
        )
        identity_guard = workflow[guard:revoke]

        self.assertNotIn(
            "PR_DRAFT: ${{ github.event.pull_request.draft }}", identity_guard
        )
        self.assertNotIn('[ "$PR_DRAFT" != "false" ]', identity_guard)
        live_read = identity_guard.index(
            'live_pr="$(gh api "repos/${REPO}/pulls/${PR_NUMBER}")"'
        )
        live_ready = identity_guard.index(
            '(.state == "open") and (.draft == false)'
        )
        publish = identity_guard.index('echo "trusted=$trusted"')
        self.assertLess(live_read, live_ready)
        self.assertLess(live_ready, publish)

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
            "PR_BASE_SHA: ${{ needs.classify-shared-assets-invocation.outputs.base_sha }}",
            provenance_guard,
        )
        self.assertIn('--arg base_sha "$PR_BASE_SHA"', provenance_guard)
        self.assertIn("and (.base.sha == $base_sha)", provenance_guard)
        finalizer_guard = workflow[finalizer_job:mint]
        self.assertIn(
            "needs: [classify-shared-assets-invocation, verify-shared-assets]",
            finalizer_guard,
        )
        self.assertIn(
            "needs.verify-shared-assets.outputs.trusted == 'true'",
            finalizer_guard,
        )
        self.assertIn("    timeout-minutes: 35\n", finalizer_guard)
        self.assertIn("      actions: read\n", finalizer_guard)
        self.assertNotIn('gh pr merge "$PR_URL" --merge', workflow[verify:finalize])
        self.assertIn("completed_guard_is_bound()", workflow[finalize:])
        self.assertIn("EVENT_NAME: ${{ github.event_name }}", workflow[finalize:])
        self.assertIn('case "$EVENT_NAME" in', workflow[finalize:])
        self.assertIn(
            'repos/${REPO}/actions/runs/${CURRENT_RUN_ID}', workflow[finalize:]
        )
        self.assertIn(
            '.event == "workflow_run"', workflow[finalize:]
        )
        self.assertIn(
            '.path == ".github/workflows/shared-assets-guarded-automerge.yml"',
            workflow[finalize:],
        )
        self.assertIn(
            'select(.name == "Verify trusted shared-assets PR")',
            workflow[finalize:],
        )
        self.assertIn(
            '$matches[0].head_sha == $controller_sha', workflow[finalize:]
        )
        self.assertIn("CONTROLLER_SHA: ${{ github.workflow_sha }}", workflow[finalize:])
        self.assertIn(
            "DEFAULT_BRANCH: ${{ github.event.repository.default_branch }}",
            workflow[finalize:],
        )
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
        self.assertEqual(8, workflow.count("=~ ^[1-9][0-9]*-[1-9][0-9]*$"))
        self.assertEqual(
            3,
            workflow.count("Shared-Assets-Source-Attempt: [1-9][0-9]*"),
        )
        self.assertEqual(3, workflow.count("'/^Shared-Assets-/ { count++ }"))
        self.assertEqual(3, workflow.count('managed_trailer_count" -ne 4'))


if __name__ == "__main__":
    unittest.main()
