from __future__ import annotations

import json
import re
import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = (
    ROOT / ".github" / "workflows" / "supplementary-current-revision-required.yml"
)
REMEDIATION_WORKFLOW = (
    ROOT / ".github" / "workflows" / "codex-copilot-remediation.yml"
)
COPILOT_WORKFLOW = ROOT / ".github" / "workflows" / "copilot-review.yml"
TEST_TOOL_PATH = "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"


class OrganizationRequiredWorkflowTests(unittest.TestCase):
    def _test_tool(self, name: str) -> str:
        executable = shutil.which(name, path=TEST_TOOL_PATH)
        if executable is None:
            self.fail(
                f"{name} is required in the deterministic test tool path"
            )
        return executable

    @staticmethod
    def _required_verifier_producer_routing() -> str:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        marker = (
            '            if { [ "${author}" = '
            "'lightning-it-release-automation[bot]' ] \\\n"
        )
        start = workflow.index(marker)
        end = workflow.index(
            '            producer_run_url="${GITHUB_SERVER_URL}', start
        )
        return textwrap.dedent(workflow[start:end])

    def _run_required_verifier_producer_routing(
        self,
        *,
        author: str,
        base_ref: str,
        producer_kind: str,
        repository: str = "lightning-it/website",
    ) -> int:
        bash = self._test_tool("bash")
        result = subprocess.run(
            [
                bash,
                "-c",
                "set -euo pipefail\n"
                + self._required_verifier_producer_routing(),
            ],
            env={
                "PATH": TEST_TOOL_PATH,
                "REPOSITORY": repository,
                "author": author,
                "base_ref": base_ref,
                "central_sync_backmerge": "false",
                "producer_kind": producer_kind,
            },
            text=True,
            capture_output=True,
            check=False,
        )
        return result.returncode

    @staticmethod
    def _neutral_publisher_routing() -> str:
        workflow = COPILOT_WORKFLOW.read_text(encoding="utf-8")
        publish = workflow.split("      - name: Publish bound neutral result\n", 1)[
            1
        ]
        start = publish.index(
            '          if [[ "${TRUSTED_KIND}" =~ '
            '^(shared-assets|repository-quality)$ ]]; then\n'
        )
        end = publish.index('          run_url="${GITHUB_SERVER_URL}', start)
        return textwrap.dedent(publish[start:end])

    def _run_neutral_publisher_routing(
        self,
        *,
        author: str,
        base_ref: str,
        repository: str,
        trusted_kind: str,
    ) -> int:
        bash = self._test_tool("bash")
        result = subprocess.run(
            [
                bash,
                "-c",
                "set -euo pipefail\n" + self._neutral_publisher_routing(),
            ],
            env={
                "PATH": TEST_TOOL_PATH,
                "REPOSITORY": repository,
                "TRUSTED_KIND": trusted_kind,
                "author": author,
                "base_ref": base_ref,
            },
            text=True,
            capture_output=True,
            check=False,
        )
        return result.returncode

    def test_neutral_producer_distinguishes_managed_sync_from_backmerge(
        self,
    ) -> None:
        workflow = COPILOT_WORKFLOW.read_text(encoding="utf-8")
        self.assertTrue(
            workflow.startswith(
                "# Owned by the protected lightning-it/.github controller.\n"
                "# Generic shared-assets sync must preserve this "
                "repository-specific file.\n"
            )
        )
        self.assertNotIn("Do not edit downstream copies directly.", workflow)
        publish = workflow.split("      - name: Publish bound neutral result\n", 1)[
            1
        ]
        managed_sync, ancestry_and_rest = publish.split(
            '          elif [ "${TRUSTED_KIND}" = ancestry-backmerge ]; then\n',
            1,
        )
        ancestry = ancestry_and_rest.split("          run_url=", 1)[0]

        self.assertIn(
            '[[ "${TRUSTED_KIND}" =~ ^(shared-assets|repository-quality)$ ]]',
            managed_sync,
        )
        self.assertIn(
            'review_path="deterministic provenance-bound managed distribution exemption"',
            managed_sync,
        )
        self.assertIn('external_kind="managed-sync"', managed_sync)
        self.assertIn(
            'test "${author}" = \'lightning-it-shared-assets-sync[bot]\'\n',
            managed_sync,
        )
        self.assertIn(
            'test "${author}" != \'lightning-it-shared-assets-sync[bot]\'',
            ancestry,
        )
        self.assertIn(
            'test "${TRUSTED_KIND}" = ancestry-backmerge', ancestry
        )
        self.assertIn(
            'test "${TRUSTED_KIND}" != ancestry-backmerge', ancestry
        )
        self.assertNotIn(
            'if { [ "${author}" = \'lightning-it-release-automation[bot]\' ]',
            ancestry,
        )

    def test_neutral_producer_rejects_sync_actor_from_copilot_fallback(
        self,
    ) -> None:
        sync_app = "lightning-it-shared-assets-sync[bot]"
        self.assertNotEqual(
            0,
            self._run_neutral_publisher_routing(
                author=sync_app,
                base_ref="develop",
                repository="lightning-it/website",
                trusted_kind="none",
            ),
        )
        self.assertEqual(
            0,
            self._run_neutral_publisher_routing(
                author="litroc",
                base_ref="develop",
                repository="lightning-it/website",
                trusted_kind="none",
            ),
        )
        self.assertEqual(
            0,
            self._run_neutral_publisher_routing(
                author=sync_app,
                base_ref="develop",
                repository="lightning-it/website",
                trusted_kind="shared-assets",
            ),
        )
        self.assertNotEqual(
            0,
            self._run_neutral_publisher_routing(
                author=sync_app,
                base_ref="main",
                repository="lightning-it/website",
                trusted_kind="shared-assets",
            ),
        )
        self.assertNotEqual(
            0,
            self._run_neutral_publisher_routing(
                author=sync_app,
                base_ref="develop",
                repository="lightning-it/.github",
                trusted_kind="shared-assets",
            ),
        )

    def test_required_workflow_is_external_ai_free_and_source_bound(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("pull_request_target:", workflow)
        self.assertIn(
            "types: [opened, synchronize, reopened, ready_for_review, edited]",
            workflow,
        )
        self.assertNotIn("actions/checkout@", workflow)
        self.assertNotIn("openai/codex-action@", workflow)
        self.assertNotIn("if: github.repository ==", workflow)
        self.assertIn(
            '[[ "${REPOSITORY}" =~ ^lightning-it/[A-Za-z0-9_.-]+$ ]]',
            workflow,
        )
        self.assertIn('.owner.login == "lightning-it"', workflow)
        self.assertIn("and .archived == false", workflow)
        self.assertIn("and .disabled == false", workflow)
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

    def test_self_hosted_develop_controller_is_base_and_protection_bound(
        self,
    ) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn(
            "supplementary-current-revision-required.yml@refs/heads/develop)",
            workflow,
        )
        self.assertIn('test "${REPOSITORY}" = lightning-it/.github', workflow)
        self.assertIn(
            'if [ "${WORKFLOW_SHA}" = "${EVENT_BASE}" ]; then', workflow
        )
        self.assertIn(
            'test "${WORKFLOW_SHA}" = "${EVENT_HEAD}"', workflow
        )
        self.assertIn(
            "protected_develop=\"$(gh api "
            "repos/lightning-it/.github/branches/develop)\"",
            workflow,
        )
        self.assertIn(
            "protected_main=\"$(gh api "
            "repos/lightning-it/.github/branches/main)\"",
            workflow,
        )
        self.assertIn('and .protected == true', workflow)
        self.assertIn('and .commit.sha == $base', workflow)
        self.assertIn('source_sha="${EVENT_BASE}"', workflow)
        self.assertIn('source_sha="${EVENT_HEAD}"', workflow)
        self.assertIn('.base.ref == "main"', workflow)
        self.assertIn('.head.ref == "develop"', workflow)
        self.assertIn('and .head.repo.full_name == $repository', workflow)
        controller_case = workflow.index('          case "${WORKFLOW_REF}" in')
        for validated_input in (
            '[[ "${EVENT_BASE}" =~ ^[0-9a-f]{40}$ ]]',
            '[[ "${EVENT_HEAD}" =~ ^[0-9a-f]{40}$ ]]',
            '[[ "${PR_NUMBER}" =~ ^[1-9][0-9]*$ ]]',
            '[[ "${EVENT_ACTION}" =~ ^(opened|synchronize|reopened|ready_for_review|edited)$ ]]',
        ):
            with self.subTest(validated_input=validated_input):
                self.assertLess(workflow.index(validated_input), controller_case)

    def test_self_hosted_promotion_controller_requires_exact_live_pr(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        promotion = workflow.split('                pr="$(gh api', 1)[1].split(
            '                protected_main="$(gh api', 1
        )[0]
        marker = '                  --arg repository "${REPOSITORY}" \'\n'
        start = promotion.index(marker) + len(marker)
        end = promotion.index('\n                  \' <<<"${pr}"', start)
        identity_filter = promotion[start:end]

        self.assertIn('          pr=""\n          case "${WORKFLOW_REF}" in', workflow)
        self.assertIn(
            "          if [ -z \"${pr}\" ]; then\n"
            '            pr="$(gh api '
            '"repos/${REPOSITORY}/pulls/${PR_NUMBER}")"\n'
            "          fi",
            workflow,
        )

        valid = {
            "state": "open",
            "base": {
                "ref": "main",
                "sha": "a" * 40,
                "repo": {"full_name": "lightning-it/.github"},
            },
            "head": {
                "ref": "develop",
                "sha": "b" * 40,
                "repo": {"full_name": "lightning-it/.github"},
            },
        }

        def validate(candidate: dict[str, object]) -> int:
            try:
                result = subprocess.run(
                    [
                        self._test_tool("jq"),
                        "-e",
                        "--arg",
                        "base",
                        "a" * 40,
                        "--arg",
                        "head",
                        "b" * 40,
                        "--arg",
                        "repository",
                        "lightning-it/.github",
                        identity_filter,
                    ],
                    input=json.dumps(candidate),
                    text=True,
                    capture_output=True,
                    check=False,
                )
            except FileNotFoundError as error:
                self.fail(f"jq is required to validate promotion identity: {error}")
            return result.returncode

        self.assertEqual(0, validate(valid))
        rejected = (
            {**valid, "state": "closed"},
            {**valid, "base": {**valid["base"], "ref": "develop"}},
            {**valid, "base": {**valid["base"], "sha": "c" * 40}},
            {
                **valid,
                "base": {
                    **valid["base"],
                    "repo": {"full_name": "fork/.github"},
                },
            },
            {**valid, "head": {**valid["head"], "ref": "feature"}},
            {**valid, "head": {**valid["head"], "sha": "c" * 40}},
            {
                **valid,
                "head": {
                    **valid["head"],
                    "repo": {"full_name": "fork/.github"},
                },
            },
        )
        for candidate in rejected:
            with self.subTest(candidate=candidate):
                self.assertNotEqual(0, validate(candidate))

    def test_pr_comment_read_permissions_are_explicit_and_read_only(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        permissions = workflow.split("    runs-on:", 1)[0]
        self.assertIn("      pull-requests: read", permissions)
        self.assertIn("      issues: read", permissions)
        self.assertIn(
            "App binding exists only on the Issues REST representation",
            permissions,
        )

    def test_required_workflow_validates_exact_neutral_producer(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("Protected current-revision verifier", workflow)
        self.assertIn("    name: Required current-revision workflow\n", workflow)
        self.assertIn(
            'startswith("mlx90-current-revision:v4:")',
            workflow,
        )
        self.assertIn(
            'startswith("mlx90-current-revision:copilot:v5:")',
            workflow,
        )
        self.assertIn(
            'startswith("mlx90-current-revision:ancestry-backmerge:v5:")',
            workflow,
        )
        self.assertIn(
            'startswith("mlx90-current-revision:copilot:v6:")',
            workflow,
        )
        self.assertIn(
            'startswith("mlx90-current-revision:ancestry-backmerge:v6:")',
            workflow,
        )
        self.assertIn(
            'startswith("mlx90-current-revision:managed-sync:v6:")',
            workflow,
        )
        self.assertIn(
            "rep60-required-workflow:v3:${GITHUB_RUN_ID}:${PR_NUMBER}:${EVENT_BASE}:${EVENT_HEAD}",
            workflow,
        )
        self.assertIn(
            "check_name=Current%20revision%20review&filter=all&per_page=100",
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
            "mlx90-current-revision:(copilot|ancestry-backmerge):v5:([1-9][0-9]*):${EVENT_BASE}:${EVENT_HEAD}",
            workflow,
        )
        self.assertIn(
            "mlx90-current-revision:(copilot|managed-sync|ancestry-backmerge):v6:${PR_NUMBER}:([1-9][0-9]*):${EVENT_BASE}:${EVENT_HEAD}",
            workflow,
        )
        self.assertIn("Keep v5 valid only for already-open pull requests", workflow)
        self.assertIn("prevents v5 and v6 from satisfying the gate together", workflow)
        self.assertIn("producer_kind=\"${BASH_REMATCH[1]}\"", workflow)
        self.assertIn("producer_run_id=\"${BASH_REMATCH[2]}\"", workflow)
        self.assertIn('test "${producer_kind}" = ancestry-backmerge', workflow)
        self.assertIn('test "${producer_kind}" = managed-sync', workflow)
        self.assertIn('test "${producer_kind}" = copilot', workflow)
        self.assertIn(
            'expected_review_path="deterministic provenance-bound managed distribution exemption"',
            workflow,
        )
        self.assertIn('central_sync_backmerge=false', workflow)
        self.assertIn('central_sync_backmerge=true', workflow)
        self.assertEqual(
            2,
            workflow.count('[ "${central_sync_backmerge}" = true ]'),
        )
        self.assertIn(".producer_run_id == $run_id", workflow)
        self.assertIn(".schema == 4", workflow)
        self.assertIn(
            'test "${details_url}" = "${GITHUB_SERVER_URL}/${REPOSITORY}/runs/${check_id}"',
            workflow,
        )
        self.assertIn("and .base_sha == $base", workflow)
        neutral_producer = workflow.split(
            'if [ "${managed_sync_verified}" = false ]', 1
        )[1]
        self.assertEqual(
            2,
            neutral_producer.count("and .run_attempt == 1"),
        )
        self.assertEqual(workflow.count(".actor.login == $actor"), 2)
        self.assertEqual(workflow.count(".triggering_actor.login == $actor"), 2)
        self.assertIn(".input_sha256 | test", workflow)
        self.assertIn("and .workflow_sha == $base", workflow)

    def test_required_verifier_managed_sync_is_develop_only(self) -> None:
        sync_app = "lightning-it-shared-assets-sync[bot]"
        self.assertEqual(
            0,
            self._run_required_verifier_producer_routing(
                author=sync_app,
                base_ref="develop",
                producer_kind="managed-sync",
            ),
        )
        self.assertNotEqual(
            0,
            self._run_required_verifier_producer_routing(
                author=sync_app,
                base_ref="main",
                producer_kind="managed-sync",
            ),
        )
        self.assertNotEqual(
            0,
            self._run_required_verifier_producer_routing(
                author=sync_app,
                base_ref="develop",
                producer_kind="copilot",
            ),
        )
        self.assertEqual(
            0,
            self._run_required_verifier_producer_routing(
                author="litroc",
                base_ref="main",
                producer_kind="copilot",
            ),
        )

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

    def test_managed_sync_recovery_is_source_run_and_target_job_bound(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        recovery = workflow.split(
            "managed_sync_verified=false", 1
        )[1].split(
            'if [ "${managed_sync_verified}" = false ]', 1
        )[0]
        self.assertIn(
            "[ \"${author}\" = "
            "'lightning-it-shared-assets-sync[bot]' ]",
            recovery,
        )
        self.assertIn(
            '&& [ "${central_sync_backmerge}" = false ]', recovery
        )
        self.assertIn('test "${base_ref}" = develop', recovery)
        self.assertIn(
            'test "${head_repository}" = "${REPOSITORY}"', recovery
        )
        self.assertIn('test "$(jq -r .commits <<<"${pr}")" -eq 1', recovery)
        self.assertIn('and (.parents | length) == 1', recovery)
        self.assertIn('and .parents[0].sha == $base', recovery)
        self.assertIn('and .author.login == $bot', recovery)
        self.assertIn('and .committer.login == $bot', recovery)
        self.assertIn('Shared-Assets-Source-SHA:', recovery)
        self.assertIn('Shared-Assets-Source-Run:', recovery)
        self.assertIn('Shared-Assets-Source-Attempt:', recovery)
        self.assertIn('Shared-Assets-Sync-App-ID: 4351516', recovery)
        self.assertIn(
            'test "${managed_trailer_count}" -eq $((3 + source_attempt_count))',
            recovery,
        )
        for source_workflow in (
            "sync-repository-quality-repos.yml",
            "sync-ansible-inventories.yml",
            "sync-ansible-collections.yml",
            "sync-ee-containers.yml",
            "sync-playbook-runbook-repos.yml",
        ):
            with self.subTest(source_workflow=source_workflow):
                self.assertIn(source_workflow, recovery)
        self.assertIn(
            'and (.event == "push" or .event == "workflow_dispatch")',
            recovery,
        )
        self.assertNotIn('and .event == "push"\n', recovery)
        self.assertIn(
            'for ((attempt = 1; attempt <= 42; attempt++))', recovery
        )
        self.assertIn(
            'requested | waiting | pending | queued | in_progress', recovery
        )
        self.assertIn(
            'test "$(jq -r .status <<<"${source_run}")" = completed',
            recovery,
        )
        self.assertIn('and .head_branch == "main"', recovery)
        self.assertIn('and .head_sha == $head', recovery)
        self.assertIn('and .path == $path', recovery)
        self.assertIn('and .status == "completed"', recovery)
        self.assertIn('and .conclusion == "success"', recovery)
        self.assertIn('and .repository.full_name == $repository', recovery)
        self.assertIn('and .head_repository.full_name == $repository', recovery)
        self.assertIn('and .run_attempt == $run_attempt', recovery)
        self.assertIn(
            'attempts/${source_run_attempt}/jobs?per_page=100',
            recovery,
        )
        self.assertIn('.base_commit.sha == $source', recovery)
        self.assertIn('.merge_base_commit.sha == $source', recovery)
        self.assertIn('and .behind_by == 0', recovery)
        self.assertIn('and (.jobs | length) == .total_count', recovery)
        self.assertIn('select(.name == $expected)', recovery)
        self.assertIn(
            'select(.status == "completed" and .conclusion == "success")',
            recovery,
        )
        self.assertIn('| length) == 1', recovery)
        self.assertIn(
            '<!-- lit-shared-assets-sync-provenance:v1 -->', recovery
        )
        self.assertIn(
            '<!-- lit-shared-assets-sync-provenance:v2 -->', recovery
        )
        self.assertIn("The marker token is reserved anywhere", recovery)
        self.assertIn("(.body | contains($legacy_marker))", recovery)
        self.assertIn("(.body | contains($attempt_marker))", recovery)
        self.assertIn(
            '"repos/${REPOSITORY}/issues/${PR_NUMBER}/comments?per_page=100"',
            recovery,
        )
        self.assertIn(
            '$comment.performed_via_github_app.id == $app_id', recovery
        )
        self.assertIn(
            '$comment.performed_via_github_app.slug', recovery
        )
        self.assertIn(
            '== "lightning-it-shared-assets-sync"', recovery
        )
        self.assertIn(
            '== "lit-shared-assets-sync-provenance/v1"', recovery
        )
        self.assertIn(
            "sync_comment_schema='lit-shared-assets-sync-provenance/v2'",
            recovery,
        )
        self.assertIn(
            '$evidence.source_run_attempt == $run_attempt',
            recovery,
        )
        self.assertIn(
            '$evidence.target_base_sha == $base', recovery
        )
        self.assertIn(
            '$evidence.target_head_sha == $head', recovery
        )
        self.assertIn(
            '$evidence.target_tree_sha == $tree', recovery
        )
        self.assertIn(
            '$evidence.source_run_id == $run_id', recovery
        )
        self.assertIn(
            '$evidence.source_job == $job', recovery
        )
        self.assertIn(
            '($comment.updated_at | fromdateiso8601)', recovery
        )
        self.assertIn(
            'test "$(jq \'length\' <<<"${sync_comments}")" -eq 1',
            recovery,
        )
        self.assertIn('$comment.user.id == 307342877', recovery)
        self.assertIn(
            '$comment.created_at == $comment.updated_at', recovery
        )
        self.assertIn(
            'test "$(jq \'length\' <<<"${sync_app_comments}")" -eq 1',
            recovery,
        )

    def test_managed_sync_source_event_allowlist_is_exact(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        recovery = workflow.split("managed_sync_verified=false", 1)[1].split(
            'if [ "${managed_sync_verified}" = false ]', 1
        )[0]
        marker = '              --argjson run_id "${source_run_id}" \'\n'
        start = recovery.index(marker) + len(marker)
        end = recovery.index('\n              \' <<<"${source_run}"', start)
        source_run_filter = recovery[start:end]
        source_sha = "a" * 40
        source_path = ".github/workflows/sync-ansible-collections.yml"
        source_run_url = "https://github.example/actions/runs/42"
        jq = self._test_tool("jq")

        def accepts(event: str) -> bool:
            payload = {
                "id": 42,
                "event": event,
                "head_branch": "main",
                "head_sha": source_sha,
                "path": source_path,
                "status": "completed",
                "conclusion": "success",
                "html_url": source_run_url,
                "repository": {"full_name": "lightning-it/shared-assets-lit"},
                "head_repository": {
                    "full_name": "lightning-it/shared-assets-lit"
                },
                "run_attempt": 1,
            }
            result = subprocess.run(
                [
                    jq,
                    "-e",
                    "--arg",
                    "head",
                    source_sha,
                    "--arg",
                    "path",
                    source_path,
                    "--arg",
                    "repository",
                    "lightning-it/shared-assets-lit",
                    "--arg",
                    "run_url",
                    source_run_url,
                    "--argjson",
                    "run_attempt",
                    "1",
                    "--argjson",
                    "run_id",
                    "42",
                    source_run_filter,
                ],
                input=json.dumps(payload),
                text=True,
                capture_output=True,
                check=False,
            )
            return result.returncode == 0

        for accepted_event in ("push", "workflow_dispatch"):
            with self.subTest(accepted_event=accepted_event):
                self.assertTrue(accepts(accepted_event))
        for rejected_event in (
            "",
            "schedule",
            "pull_request",
            "pull_request_target",
            "workflow_run",
        ):
            with self.subTest(rejected_event=rejected_event):
                self.assertFalse(accepts(rejected_event))

    def test_managed_sync_uses_a_source_repository_scoped_app_token(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        source_token = workflow.split(
            "      - name: Mint source-read Release Automation App token", 1
        )[1].split(
            "      - name: Verify one protected result for the exact live revision",
            1,
        )[0]
        recovery = workflow.split(
            "managed_sync_verified=false", 1
        )[1].split(
            'if [ "${managed_sync_verified}" = false ]', 1
        )[0]

        self.assertIn("id: source-app", source_token)
        self.assertIn(
            "github.event.pull_request.user.login\n"
            "            == 'lightning-it-shared-assets-sync[bot]'",
            source_token,
        )
        self.assertIn(
            "github.event.pull_request.base.ref == 'develop'", source_token
        )
        self.assertIn(
            "github.event.pull_request.head.repo.full_name == github.repository",
            source_token,
        )
        self.assertIn("owner: lightning-it", source_token)
        self.assertIn("repositories: shared-assets-lit", source_token)
        self.assertIn("permission-actions: read", source_token)
        self.assertIn("permission-contents: read", source_token)
        self.assertIn(
            "client-id: ${{ vars.RELEASE_AUTOMATION_APP_CLIENT_ID }}",
            source_token,
        )
        self.assertIn(
            "private-key: ${{ secrets.RELEASE_AUTOMATION_APP_PRIVATE_KEY }}",
            source_token,
        )
        self.assertNotIn("SHARED_ASSETS_SYNC_APP", source_token)
        self.assertIn(
            "SOURCE_GH_TOKEN: ${{ steps.source-app.outputs.token }}", workflow
        )
        self.assertIn('test -n "${SOURCE_GH_TOKEN}"', recovery)
        self.assertEqual(
            6, recovery.count('GH_TOKEN="${SOURCE_GH_TOKEN}" gh api')
        )
        for query in (
            '"repos/lightning-it/shared-assets-lit/actions/runs/${source_run_id}"',
            '"repos/lightning-it/shared-assets-lit/commits/${source_sha}"',
            "repos/lightning-it/shared-assets-lit/branches/main --jq .commit.sha",
            '"repos/lightning-it/shared-assets-lit/compare/${source_sha}...${source_main}"',
            '"repos/lightning-it/shared-assets-lit/actions/runs/${source_run_id}/attempts/${source_run_attempt}/jobs?per_page=100"',
        ):
            with self.subTest(query=query):
                self.assertIn(query, recovery)

    def test_central_sync_backmerge_bypasses_only_distribution_provenance(
        self,
    ) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        routing = workflow.split(
            "central_sync_backmerge=false", 1
        )[1].split(
            "failure_stage='live-commit-binding'", 1
        )[0]

        for exact_binding in (
            "[ \"${REPOSITORY}\" = 'lightning-it/.github' ]",
            "[ \"${author}\" = 'lightning-it-shared-assets-sync[bot]' ]",
            '[ "${base_ref}" = develop ]',
            '[ "${head_repository}" = "${REPOSITORY}" ]',
            '[[ "${head_ref}" == backmerge/*-main ]]',
            '"chore(governance): record main ancestry before "*',
        ):
            with self.subTest(exact_binding=exact_binding):
                self.assertIn(exact_binding, routing)
        self.assertIn("central_sync_backmerge=true", routing)

        managed_sync = workflow.split(
            "managed_sync_verified=false", 1
        )[1].split(
            "failure_stage='managed-sync-provenance'", 1
        )[0]
        self.assertIn(
            '[ "${author}" = \'lightning-it-shared-assets-sync[bot]\' ]',
            managed_sync,
        )
        self.assertIn(
            '&& [ "${central_sync_backmerge}" = false ]', managed_sync
        )

        permanent = workflow.split(
            "failure_stage='permanent-producer-binding'", 1
        )[1]
        self.assertIn(
            '|| [ "${central_sync_backmerge}" = true ]', permanent
        )
        self.assertIn(
            'test "${producer_kind}" = ancestry-backmerge', permanent
        )

        routing_script = textwrap.dedent(
            workflow.split(
                "          central_sync_backmerge=false", 1
            )[1].split(
                "\n\n          failure_stage='live-commit-binding'", 1
            )[0]
        )

        def classify(**overrides: str) -> str:
            environment = {
                "REPOSITORY": "lightning-it/.github",
                "author": "lightning-it-shared-assets-sync[bot]",
                "base_ref": "develop",
                "head_repository": "lightning-it/.github",
                "head_ref": "backmerge/github-main",
                "pr_title": (
                    "chore(governance): record main ancestry before abc123"
                ),
                **overrides,
            }
            bash = self._test_tool("bash")
            try:
                result = subprocess.run(
                    [
                        bash,
                        "-c",
                        "set -euo pipefail\n"
                        "central_sync_backmerge=false\n"
                        f"{routing_script}\n"
                        'printf "%s" "${central_sync_backmerge}"\n',
                    ],
                    text=True,
                    capture_output=True,
                    check=False,
                    env={**environment, "PATH": TEST_TOOL_PATH},
                )
            except FileNotFoundError as error:
                self.fail(
                    f"bash disappeared before the workflow predicate ran: {error}"
                )
            self.assertEqual(0, result.returncode, result.stderr)
            return result.stdout

        self.assertEqual("true", classify())
        rejected = (
            {"REPOSITORY": "lightning-it/shared-assets-lit"},
            {"author": "lightning-it-release-automation[bot]"},
            {"base_ref": "main"},
            {"head_repository": "fork/.github"},
            {"head_ref": "chore/sync-repository-quality-.github"},
            {"pr_title": "chore: sync repository quality assets"},
        )
        for overrides in rejected:
            with self.subTest(rejected=overrides):
                self.assertEqual("false", classify(**overrides))

    def test_human_producer_separates_event_head_from_protected_controller(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        producer_paths = workflow.split(
            "failure_stage='permanent-producer-binding'", 1
        )[1].split("failure_stage='permanent-finalization'", 1)[0]
        human_path = producer_paths.split("          else", 1)[1]
        self.assertIn(".controller_sha", human_path)
        self.assertIn(".default_branch", human_path)
        self.assertNotIn('test "${controller_branch}" = develop', human_path)
        self.assertIn("'$value | @uri'", human_path)
        self.assertIn("branches/${controller_branch_uri}", human_path)
        self.assertNotIn("branches/${controller_branch}\"", human_path)
        self.assertIn(
            '[[ "${controller_head}" =~ ^[0-9a-f]{40}$ ]]', human_path
        )
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
            "managed-sync-provenance",
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

    def test_draft_events_reserve_before_failing_without_ai(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        job_header = workflow.split(
            "  verify-protected-current-revision-evidence:", 1
        )[1].split("    permissions:", 1)[0]
        self.assertNotIn("if:", job_header)
        reservation = workflow.index("reservation_external_id=")
        failure_trap = workflow.index("trap finalize_failure ERR")
        draft_rejection = workflow.index('test "${draft}" = false')
        self.assertLess(reservation, draft_rejection)
        self.assertLess(failure_trap, draft_rejection)
        self.assertNotIn("openai/", workflow.lower())

    def test_failed_ready_run_reserves_a_single_later_rerun(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        reservation = workflow.index("reservation_external_id=")
        trap = workflow.index("trap finalize_failure ERR")
        self.assertLess(reservation, trap)
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
        self.assertIn("startswith($v3_prefix)", reservation_selection)
        self.assertIn("endswith($v3_suffix)", reservation_selection)
        self.assertIn("startswith($v2_prefix)", reservation_selection)
        self.assertIn("endswith($v2_suffix)", reservation_selection)
        self.assertIn('foreign_reservations="$(jq -c', reservation_selection)
        self.assertEqual(
            workflow.count('-f external_id="${reservation_external_id}"'),
            3,
        )
        self.assertIn(
            "^rep60-required-workflow:v3:[1-9][0-9]*:${PR_NUMBER}:${EVENT_BASE}:${EVENT_HEAD}$",
            workflow,
        )
        self.assertIn(
            "^rep60-required-workflow:v2:([1-9][0-9]*):${PR_NUMBER}:${EVENT_HEAD}$",
            workflow,
        )
        self.assertIn('prior_verifier_run="$(gh api', workflow)
        self.assertIn('.workflow_id == $workflow_id', workflow)
        self.assertIn('.status == "completed"', workflow)
        self.assertIn(
            '(.conclusion == "success" or .conclusion == "failure")',
            workflow,
        )
        self.assertLess(
            workflow.index('prior_external_id="$(jq -er'),
            workflow.index('-f external_id="${reservation_external_id}"'),
        )

    def test_only_proven_same_workflow_foreign_reservations_are_retired(
        self,
    ) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        retirement = workflow.split('foreign_reservations="$(jq -c', 1)[1].split(
            '          reservation_count="$(jq', 1
        )[0]

        self.assertIn('if [ "${foreign_count}" -gt 20 ]; then', retirement)
        self.assertIn('.status == "completed"', retirement)
        self.assertIn(
            '(.conclusion == "success" or .conclusion == "failure")',
            retirement,
        )
        self.assertIn('[.[].external_id] | unique | length', retirement)
        self.assertIn('declare -A retired_pr_numbers=()', retirement)
        self.assertIn('declare -A retired_run_ids=()', retirement)
        self.assertIn(
            '"repos/${REPOSITORY}/actions/runs/${GITHUB_RUN_ID}"',
            retirement,
        )
        self.assertIn('.event == "pull_request_target"', retirement)
        self.assertIn('.display_title == (', retirement)
        self.assertIn(
            '.path == ".github/workflows/'
            'supplementary-current-revision-required.yml"',
            retirement,
        )
        self.assertIn('.status == "in_progress"', retirement)
        self.assertIn('.conclusion == null', retirement)
        self.assertIn('.workflow_id == $workflow_id', retirement)
        self.assertIn('.state == "closed"', retirement)
        self.assertIn('.state == "open"', retirement)
        self.assertIn('.base.sha == $base', retirement)
        self.assertIn('.base.repo.full_name == $repository', retirement)
        self.assertIn('.head.sha == $head', retirement)
        self.assertIn(
            'test "${foreign_base}" != "${EVENT_BASE}"',
            retirement,
        )
        self.assertIn("rep60-required-workflow:v3:", retirement)
        self.assertIn("rep60-required-workflow:v2:", retirement)
        self.assertIn("ready_for_review", retirement)
        self.assertIn("edited", retirement)
        self.assertIn(
            'test "${foreign_details_url}" =',
            retirement,
        )

    def test_v2_cutover_reuses_only_exact_protected_reservations(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        selection = workflow.split('          reservations="$(jq -c', 1)[1].split(
            '          foreign_reservations="$(jq -c', 1
        )[0]
        selection_filter = selection.split(" '\n", 1)[1].split(
            '\n            \' <<<"${all_reservations}")"', 1
        )[0]
        head = "a" * 40
        base = "b" * 40
        exact_v3 = {
            "id": 1,
            "external_id": f"rep60-required-workflow:v3:301:225:{base}:{head}",
        }
        exact_v2 = {
            "id": 2,
            "external_id": f"rep60-required-workflow:v2:201:225:{head}",
        }
        rejected = [
            {
                "id": 3,
                "external_id": f"rep60-required-workflow:v3:302:225:{'c' * 40}:{head}",
            },
            {
                "id": 4,
                "external_id": f"rep60-required-workflow:v2:202:224:{head}",
            },
            {"id": 5, "external_id": "untrusted"},
        ]
        selected = subprocess.run(
            [
                self._test_tool("jq"),
                "-c",
                "--arg",
                "v3_prefix",
                "rep60-required-workflow:v3:",
                "--arg",
                "v3_suffix",
                f":225:{base}:{head}",
                "--arg",
                "v2_prefix",
                "rep60-required-workflow:v2:",
                "--arg",
                "v2_suffix",
                f":225:{head}",
                selection_filter,
            ],
            input=json.dumps([exact_v3, exact_v2, *rejected]),
            text=True,
            capture_output=True,
            check=True,
        )
        self.assertEqual(
            [item["id"] for item in json.loads(selected.stdout)],
            [1, 2],
        )

        prior_block = workflow.split('prior_verifier_run="$(gh api', 1)[1].split(
            '            reservation_url=', 1
        )[0]
        prior_filter = prior_block.split(
            '--argjson workflow_id "${current_workflow_id}" \'\n', 1
        )[1].split('\n                \' <<<"${prior_verifier_run}"', 1)[0]
        title = f"Protected current revision PR #225 opened {head}"
        protected_run = {
            "id": 201,
            "workflow_id": 335,
            "event": "pull_request_target",
            "path": ".github/workflows/supplementary-current-revision-required.yml",
            "status": "completed",
            "conclusion": "failure",
            "head_sha": head,
            "run_attempt": 1,
            "display_title": title,
        }
        prior_args = [
            "--arg",
            "head",
            head,
            "--argjson",
            "pr_number",
            "225",
            "--argjson",
            "run_id",
            "201",
            "--argjson",
            "workflow_id",
            "335",
        ]

        def accepts(payload: dict[str, object]) -> bool:
            return (
                subprocess.run(
                    [self._test_tool("jq"), "-e", *prior_args, prior_filter],
                    input=json.dumps(payload),
                    text=True,
                    capture_output=True,
                    check=False,
                ).returncode
                == 0
            )

        self.assertTrue(accepts(protected_run))
        for forged in (
            {**protected_run, "workflow_id": 336},
            {**protected_run, "event": "pull_request"},
            {**protected_run, "status": "in_progress"},
            {**protected_run, "conclusion": None},
            {**protected_run, "head_sha": "c" * 40},
            {**protected_run, "display_title": f"Candidate workflow {head}"},
        ):
            with self.subTest(forged=forged):
                self.assertFalse(accepts(forged))

    def test_retired_reservation_filters_reject_open_or_foreign_evidence(
        self,
    ) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        retirement = workflow.split('foreign_reservations="$(jq -c', 1)[1].split(
            '          reservation_count="$(jq', 1
        )[0]

        def extract(block: str, argument_marker: str, end_marker: str) -> str:
            return block.split(argument_marker, 1)[1].split(end_marker, 1)[0]

        def accepts(
            jq_filter: str,
            arguments: list[str],
            payload: dict[str, object],
        ) -> bool:
            try:
                result = subprocess.run(
                    [self._test_tool("jq"), "-e", *arguments, jq_filter],
                    input=json.dumps(payload),
                    text=True,
                    capture_output=True,
                    check=False,
                )
            except FileNotFoundError as error:
                self.fail(
                    f"jq is required to validate retired reservations: {error}"
                )
            return result.returncode == 0

        current_filter = extract(
            retirement.split('current_workflow_id="$(jq -er', 1)[1],
            '--argjson run_id "${GITHUB_RUN_ID}" \'\n',
            '\n            \' <<<"${current_verifier_run}")"',
        )
        head = "a" * 40
        current_title = f"Protected current revision PR #225 opened {head}"
        current = {
            "id": 101,
            "event": "pull_request_target",
            "path": ".github/workflows/supplementary-current-revision-required.yml",
            "status": "in_progress",
            "conclusion": None,
            "head_sha": head,
            "run_attempt": 1,
            "name": current_title,
            "display_title": current_title,
            "workflow_id": 335,
        }
        current_args = [
            "--arg",
            "action",
            "opened",
            "--arg",
            "head",
            head,
            "--argjson",
            "pr_number",
            "225",
            "--argjson",
            "run_id",
            "101",
        ]
        self.assertTrue(accepts(current_filter, current_args, current))
        for rejected in (
            {**current, "event": "pull_request"},
            {**current, "status": "completed"},
            {**current, "conclusion": "success"},
            {**current, "run_attempt": 3},
            {**current, "workflow_id": 0},
            {
                **current,
                "display_title": f"Protected current revision PR #221 opened {head}",
            },
            {**current, "display_title": None},
        ):
            with self.subTest(current=rejected):
                self.assertFalse(accepts(current_filter, current_args, rejected))

        retired_pr_block = retirement.split('retired_pr="$(gh api', 1)[1].split(
            '              retired_verifier_run="$(gh api', 1
        )[0]
        same_pr_block, closed_pr_block = retired_pr_block.split(
            "              else\n", 1
        )
        same_pr_filter = extract(
            same_pr_block,
            '--argjson number "${foreign_pr_number}" \'\n',
            '\n                  \' <<<"${retired_pr}"',
        )
        retired_pr_filter = extract(
            closed_pr_block,
            '--argjson number "${foreign_pr_number}" \'\n',
            '\n                  \' <<<"${retired_pr}"',
        )
        current_pr = {
            "number": 225,
            "state": "open",
            "base": {
                "sha": "b" * 40,
                "repo": {"full_name": "lightning-it/.github"},
            },
            "head": {
                "sha": head,
                "repo": {"full_name": "lightning-it/.github"},
            },
        }
        same_pr_args = [
            "--arg",
            "base",
            "b" * 40,
            "--arg",
            "head",
            head,
            "--arg",
            "repository",
            "lightning-it/.github",
            "--argjson",
            "number",
            "225",
        ]
        self.assertTrue(accepts(same_pr_filter, same_pr_args, current_pr))
        for rejected in (
            {**current_pr, "state": "closed"},
            {**current_pr, "number": 221},
            {
                **current_pr,
                "base": {**current_pr["base"], "sha": "c" * 40},
            },
        ):
            with self.subTest(current_pr=rejected):
                self.assertFalse(
                    accepts(same_pr_filter, same_pr_args, rejected)
                )

        retired_pr = {
            "number": 221,
            "state": "closed",
            "base": {"repo": {"full_name": "lightning-it/.github"}},
            "head": {
                "sha": head,
                "repo": {"full_name": "lightning-it/.github"},
            },
        }
        retired_pr_args = [
            "--arg",
            "head",
            head,
            "--arg",
            "repository",
            "lightning-it/.github",
            "--argjson",
            "number",
            "221",
        ]
        self.assertTrue(accepts(retired_pr_filter, retired_pr_args, retired_pr))
        for rejected in (
            {**retired_pr, "state": "open"},
            {**retired_pr, "number": 220},
            {
                **retired_pr,
                "base": {"repo": {"full_name": "fork/.github"}},
            },
            {
                **retired_pr,
                "head": {
                    "sha": "b" * 40,
                    "repo": {"full_name": "lightning-it/.github"},
                },
            },
        ):
            with self.subTest(retired_pr=rejected):
                self.assertFalse(
                    accepts(retired_pr_filter, retired_pr_args, rejected)
                )

        retired_run_filter = extract(
            retirement.split('retired_verifier_run="$(gh api', 1)[1],
            '--argjson workflow_id "${current_workflow_id}" \'\n',
            '\n                \' <<<"${retired_verifier_run}"',
        )
        retired_title = f"Protected current revision PR #221 synchronize {head}"
        retired_run = {
            "id": 201,
            "workflow_id": 335,
            "event": "pull_request_target",
            "path": ".github/workflows/supplementary-current-revision-required.yml",
            "status": "completed",
            "conclusion": "failure",
            "head_sha": head,
            "run_attempt": 1,
            "name": retired_title,
            "display_title": retired_title,
        }
        retired_run_args = [
            "--arg",
            "conclusion",
            "failure",
            "--arg",
            "head",
            head,
            "--argjson",
            "pr_number",
            "221",
            "--argjson",
            "run_id",
            "201",
            "--argjson",
            "workflow_id",
            "335",
        ]
        self.assertTrue(accepts(retired_run_filter, retired_run_args, retired_run))
        for rejected in (
            {**retired_run, "workflow_id": 336},
            {**retired_run, "event": "pull_request"},
            {**retired_run, "status": "in_progress"},
            {**retired_run, "conclusion": "success"},
            {**retired_run, "run_attempt": 3},
            {
                **retired_run,
                "display_title": (
                    f"Protected current revision PR #220 synchronize {head}"
                ),
            },
            {**retired_run, "display_title": None},
        ):
            with self.subTest(retired_run=rejected):
                self.assertFalse(
                    accepts(retired_run_filter, retired_run_args, rejected)
                )

    def test_historical_bootstrap_transitions_are_absent(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        for retired_binding in (
            "rep60-main-bootstrap:v1:",
            "rep60-result-parser-bootstrap:v1:",
            "rep60-human-provenance-transition:v1:",
            '[ "${PR_NUMBER}" = 777 ]',
            '[ "${PR_NUMBER}" = 782 ]',
            '[ "${PR_NUMBER}" = 786 ]',
            "immutable one-time controller bootstrap; no AI",
            "immutable one-time result-parser bootstrap; no AI",
            "One-time immutable main-controller bootstrap verified",
            "One-time immutable result-parser bootstrap verified",
            "Exact human producer transition verified",
            "legacy_supplementary_pr819_copilot_v4_bridge",
            "mlx90-current-revision:copilot:v4:",
            '[ "${PR_NUMBER}" = 819 ]',
            "4989987869",
            "32451268553",
            "temporary: true",
        ):
            self.assertNotIn(retired_binding, workflow)

        failure_trap = workflow.index("trap finalize_failure ERR")
        managed_sync = workflow.index("managed_sync_verified=false")
        permanent_inventory = workflow.index(
            "failure_stage='permanent-producer-inventory'"
        )
        self.assertLess(failure_trap, managed_sync)
        self.assertLess(managed_sync, permanent_inventory)
        between = workflow[failure_trap:managed_sync]
        self.assertNotIn("if [", between)
        recovery = workflow[managed_sync:permanent_inventory]
        self.assertNotIn("temporary", recovery)
        self.assertNotIn("bootstrap", recovery)
        self.assertLess(
            workflow.index(
                "output[title]=Protected current-revision evidence verified"
            ),
            workflow.rindex("trap - ERR"),
        )

    def test_rereview_dispatch_supports_main_without_retrying_requests(
        self,
    ) -> None:
        workflow = REMEDIATION_WORKFLOW.read_text(encoding="utf-8")
        dispatch_marker = "  continue-after-push:\n"
        inspect_marker = "\n  inspect:\n"
        self.assertIn(
            dispatch_marker,
            workflow,
            "one-time rereview dispatch job is missing",
        )
        dispatch_and_after = workflow.split(dispatch_marker, 1)[1]
        self.assertIn(
            inspect_marker,
            dispatch_and_after,
            "rereview dispatch job boundary is missing",
        )
        dispatch = dispatch_and_after.split(inspect_marker, 1)[0]

        base_filters = [
            candidate
            for candidate in re.findall(
                r"jq -e(?:r)?\s+'([^']+)'",
                dispatch,
                flags=re.DOTALL,
            )
            if ".base.ref" in candidate
            and '"develop"' in candidate
            and '"main"' in candidate
        ]
        self.assertEqual(1, len(base_filters))
        jq = self._test_tool("jq")
        for base_ref, accepted in (
            ("develop", True),
            ("main", True),
            ("feature", False),
            ("release", False),
            ("master", False),
            ("", False),
        ):
            with self.subTest(base_ref=base_ref):
                result = subprocess.run(
                    [jq, "-e", base_filters[0]],
                    input=json.dumps({"base": {"ref": base_ref}}),
                    text=True,
                    capture_output=True,
                    check=False,
                )
                expectation = "accept" if accepted else "reject"
                self.assertEqual(
                    accepted,
                    result.returncode == 0,
                    f"expected jq predicate to {expectation} {base_ref!r}; "
                    f"exit={result.returncode}; stdout={result.stdout!r}; "
                    f"stderr={result.stderr!r}",
                )
        self.assertNotIn("test -n \"${base_ref}\"", dispatch)
        self.assertIn("if [ \"${author}\" != litroc ]; then", dispatch)
        self.assertIn(
            "Release-App pull requests use only the protected MLX-90 §7.2",
            dispatch,
        )
        request = (
            'gh api --method POST '
            '"repos/${REPOSITORY}/pulls/${PR_NUMBER}/requested_reviewers"'
        )
        self.assertEqual(1, dispatch.count(request))
        self.assertIn('-f "reviewers[]=${COPILOT_LOGIN}"', dispatch)
        self.assertNotIn(
            "-f 'reviewers[]=copilot-pull-request-reviewer[bot]'",
            dispatch,
        )
        self.assertIn('if [ "${request_status}" -eq 0 ]; then', dispatch)
        self.assertIn("request_response=\"$(", dispatch)
        response_filters = [
            candidate
            for candidate in re.findall(r"'([^']+)'", dispatch, flags=re.DOTALL)
            if ".number" in candidate
            and ".head.repo.full_name" in candidate
            and ".head.sha" in candidate
        ]
        self.assertEqual(1, len(response_filters))
        response_filter = response_filters[0]
        if '(.number | type) == "number"' in response_filter:
            for binding in (
                ".number == $number",
                '.state == "open"',
                ".draft == false",
                ".base.repo.full_name == $repository",
                ".base.ref == $base_ref",
            ):
                self.assertIn(binding, response_filter)
            # GitHub's special Copilot request can omit requested_reviewers from
            # a successful response. The outbound POST binds COPILOT_LOGIN;
            # the independent exact-head review lookup below binds the result.
            self.assertNotIn("requested_reviewers", response_filter)
        else:
            self.assertIn("(.number | tostring) == $number", response_filter)
            self.assertIn(
                "and any(.requested_reviewers[]?; .login == $login)",
                response_filter,
            )
        self.assertIn(
            "and .head.repo.full_name == $repository",
            dispatch,
        )
        self.assertIn(
            "and .head.sha == $head",
            dispatch,
        )
        self.assertEqual(
            2,
            dispatch.count(
                "any(add[]; .user.login == $login and .commit_id == $head)"
            ),
        )
        self.assertIn(
            "The one permitted exact-head Copilot review request was accepted and bound.",
            dispatch,
        )
        self.assertIn("returned success without the expected", dispatch)
        self.assertNotIn("sleep ", dispatch)
        self.assertNotIn("gh workflow run", dispatch)

        inspect = dispatch_and_after.split(inspect_marker, 1)[1]
        enable_marker = "\n  enable-develop-automerge:\n"
        self.assertIn(
            enable_marker,
            inspect,
            "develop-only auto-merge job boundary is missing",
        )
        inspect = inspect.split(enable_marker, 1)[0]
        self.assertIn(
            "'.base.ref | select(. == \"develop\" or . == \"main\")'",
            inspect,
        )
        self.assertNotIn("test -n \"${base_ref}\"", inspect)
        self.assertIn('if [ "${base_ref}" = "main" ]; then', inspect)
        self.assertIn(
            "in-place remediation and auto-merge remain disabled",
            inspect,
        )
        self.assertIn('echo "eligible=false"', inspect)
        self.assertEqual(
            1,
            workflow.count(
                'test "$(jq -r .base.ref <<<"${pr}")" = develop'
            ),
        )


if __name__ == "__main__":
    unittest.main()
