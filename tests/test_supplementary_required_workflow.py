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
REPOSITORY_QUALITY_WORKFLOW = (
    ROOT / ".github" / "workflows" / "repository-quality.yml"
)
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
        self.assertNotIn(
            'test "${REPOSITORY}" != \'lightning-it/.github\'',
            managed_sync,
        )
        required_workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("ALLOW_IN_PROGRESS_MANAGED_SYNC", required_workflow)
        self.assertNotIn(
            'test "${REPOSITORY}" != \'lightning-it/.github\'',
            required_workflow,
        )
        self.assertIn(
            "chore/sync-repository-quality-.github-", required_workflow
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
        self.assertEqual(
            0,
            self._run_neutral_publisher_routing(
                author=sync_app,
                base_ref="develop",
                repository="lightning-it/.github",
                trusted_kind="shared-assets",
            ),
        )
        self.assertNotEqual(
            0,
            self._run_neutral_publisher_routing(
                author=sync_app,
                base_ref="main",
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
        self.assertIn(
            "test \"$(jq 'length' <<<\"${neutral}\")\" -le 1",
            workflow,
        )
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
            4,
            neutral_producer.count("and .run_attempt == 1"),
        )
        self.assertEqual(workflow.count(".actor.login == $actor"), 7)
        self.assertEqual(workflow.count(".triggering_actor.login == $actor"), 5)
        self.assertIn(".input_sha256 | test", workflow)
        self.assertIn("and .workflow_sha == $base", workflow)

    def test_release_app_failed_producer_bridge_is_one_exact_promotion(
        self,
    ) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        transition = workflow.split(
            "      - name: Validate one immutable Shared Assets promotion handoff\n",
            1,
        )[1].split(
            "      - name: Verify one protected result for the exact live revision\n",
            1,
        )[0]
        release_path = workflow.split(
            "failure_stage='permanent-producer-binding'", 1
        )[1].split("          else", 1)[0]
        permanent_step_header = workflow.split(
            "      - name: Verify one protected result for the exact live revision\n",
            1,
        )[1].split("        env:\n", 1)[0]
        positive_predicate = transition.split(
            "        if: >-\n", 1
        )[1].split("        env:\n", 1)[0]
        negative_predicate = permanent_step_header.split(
            "          !(\n", 1
        )[1].rsplit("          )\n", 1)[0]

        for exact_binding in (
            "github.repository == 'lightning-it/shared-assets-lit'",
            "== 'b978d446c336ff2e6d86bef303f2dec5faad612c'",
            "== '5dc048e43ae2fd933c92af418f7b13e47a05f586'",
            ".workflow_id == 332483855",
            'and .conclusion == "failure"',
            "and ([.[].jobs[]] | length) == 2",
            'select(.name == "Current revision review")',
            'select(.name == "Request protected verifier re-evaluation")',
            'name == "Run protected history-free Exact-Revision Codex review"',
            'name == "Re-prove exact revision and enforce the Codex verdict"',
            'name: "Dispatch the protected re-evaluation helper from develop"',
        ):
            with self.subTest(exact_binding=exact_binding):
                self.assertIn(exact_binding, transition)

        self.assertIn(
            'and .conclusion == "success"',
            release_path,
        )
        self.assertEqual(1, release_path.count('.conclusion == "failure"'))
        self.assertIn(
            'or ($evidence_ready and (\n'
            '                    ((.status | IN("queued", "in_progress"))\n'
            '                      and .conclusion == null)\n'
            '                    or (.status == "completed"'
            ' and .conclusion == "failure")))',
            release_path,
        )
        self.assertNotIn(
            'if [ "${producer_conclusion}" != success ]; then',
            release_path,
        )
        self.assertIn("          !(\n", permanent_step_header)
        self.assertIn(
            "github.repository == 'lightning-it/shared-assets-lit'",
            permanent_step_header,
        )
        self.assertIn(
            "== 'b978d446c336ff2e6d86bef303f2dec5faad612c'",
            permanent_step_header,
        )
        self.assertIn(
            "== '5dc048e43ae2fd933c92af418f7b13e47a05f586'",
            permanent_step_header,
        )
        self.assertEqual(
            re.sub(r"\s+", " ", positive_predicate).strip(),
            re.sub(r"\s+", " ", negative_predicate).strip(),
        )
        for binding in (
            'test "${GITHUB_RUN_ATTEMPT}" -eq 1',
            "@refs/heads/main'",
            "compare/${WORKFLOW_SHA}...${protected_source_sha}",
            "rep60-required-workflow:v3:${GITHUB_RUN_ID}",
            "test \"$(jq 'length' <<<\"${same_revision}\")\" -eq 1",
            "test \"$(jq -er '.[0].id' <<<\"${same_revision}\")\" -eq 98499001131",
            '"id":98498876339',
            '"id":98499001131',
            '"external_id":"rep60-required-workflow:v3:33066823226:1498:',
            '"external_id":"rep60-required-workflow:v3:33066859444:1502:',
            'test "${prior_inventory}" = "${expected_prior_inventory}"',
            'test "${post_inventory}" = "${expected_prior_inventory}"',
            'and .repository.full_name == $repository',
            'and .head_repository.full_name == $repository',
            'and .user.type == "Bot"',
            "test \"$(jq 'length' <<<\"${exact_open_prs}\")\" -eq 1",
        ):
            with self.subTest(binding=binding):
                self.assertIn(binding, transition)
        self.assertIn(
            "output[title]=Protected transition evidence verified",
            transition,
        )
        self.assertIn("trap - EXIT", transition)

    def test_release_transition_accepts_only_the_exact_failed_inventory(
        self,
    ) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        transition = workflow.split(
            "      - name: Validate one immutable Shared Assets promotion handoff\n",
            1,
        )[1].split(
            "      - name: Verify one protected result for the exact live revision\n",
            1,
        )[0]
        inventory_guard = "expected_prior_inventory=" + transition.split(
            "          expected_prior_inventory=", 1
        )[1].split("          same_revision=", 1)[0]
        inventory_guard = textwrap.dedent(inventory_guard)
        expected_inventory = transition.split(
            "          EXPECTED_PRIOR_INVENTORY: >-\n", 1
        )[1].splitlines()[0].strip()
        bash = self._test_tool("bash")
        base = "b978d446c336ff2e6d86bef303f2dec5faad612c"
        head = "5dc048e43ae2fd933c92af418f7b13e47a05f586"
        title = "Protected current-revision evidence is absent or invalid"
        valid = [
            {
                "check_runs": [
                    {
                        "id": 98498876339,
                        "name": "Protected current-revision verifier",
                        "app": {"id": 15368, "slug": "github-actions"},
                        "head_sha": head,
                        "status": "completed",
                        "conclusion": "failure",
                        "external_id": (
                            "rep60-required-workflow:v3:33066823226:1498:"
                            f"{base}:{head}"
                        ),
                        "details_url": (
                            "https://github.com/lightning-it/shared-assets-lit/"
                            "runs/98498876339"
                        ),
                        "started_at": "2026-08-27T11:19:05Z",
                        "completed_at": "2026-08-27T11:19:07Z",
                        "output": {
                            "title": title,
                            "summary": (
                                f"PR #1498; head {head}; stage "
                                "permanent-producer-inventory; fail-closed."
                            ),
                        },
                    },
                    {
                        "id": 98499001131,
                        "name": "Protected current-revision verifier",
                        "app": {"id": 15368, "slug": "github-actions"},
                        "head_sha": head,
                        "status": "completed",
                        "conclusion": "failure",
                        "external_id": (
                            "rep60-required-workflow:v3:33066859444:1502:"
                            f"{base}:{head}"
                        ),
                        "details_url": (
                            "https://github.com/lightning-it/shared-assets-lit/"
                            "runs/98499001131"
                        ),
                        "started_at": "2026-08-27T11:19:36Z",
                        "completed_at": "2026-08-27T11:20:27Z",
                        "output": {
                            "title": title,
                            "summary": (
                                f"PR #1502; head {head}; stage "
                                "permanent-producer-binding; fail-closed."
                            ),
                        },
                    },
                ]
            }
        ]

        def validate(candidate: object) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                [bash, "-c", "set -euo pipefail\n" + inventory_guard],
                env={
                    "PATH": TEST_TOOL_PATH,
                    "EVENT_BASE": base,
                    "EVENT_HEAD": head,
                    "EXPECTED_PRIOR_INVENTORY": expected_inventory,
                    "reservations": json.dumps(candidate),
                },
                text=True,
                capture_output=True,
                check=False,
            )

        valid_result = validate(valid)
        self.assertEqual(0, valid_result.returncode, valid_result.stderr)
        rejected: list[object] = []
        for mutation in range(5):
            candidate = json.loads(json.dumps(valid))
            if mutation == 0:
                candidate[0]["check_runs"][0]["conclusion"] = "success"
            elif mutation == 1:
                candidate[0]["check_runs"][1]["id"] += 1
            elif mutation == 2:
                candidate[0]["check_runs"][1]["external_id"] += "-drift"
            elif mutation == 3:
                candidate[0]["check_runs"][0]["output"]["summary"] += " drift"
            else:
                candidate[0]["check_runs"].append(
                    json.loads(json.dumps(candidate[0]["check_runs"][0]))
                )
                candidate[0]["check_runs"][-1]["id"] = 99999999999
            rejected.append(candidate)
        for candidate in rejected:
            with self.subTest(candidate=candidate):
                self.assertNotEqual(0, validate(candidate).returncode)

    def test_release_app_failed_producer_bridge_rejects_mutated_job_ledgers(
        self,
    ) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        transition = workflow.split(
            "      - name: Validate one immutable Shared Assets promotion handoff\n",
            1,
        )[1].split(
            "      - name: Verify one protected result for the exact live revision\n",
            1,
        )[0]
        ledger = transition.split('          jobs_pages="$(gh api', 1)[1]
        jq_filter = ledger.split(
            '--argjson run_id "${producer_run_id}" \'\n', 1
        )[1].split(
            '\n            \' <<<"${jobs_pages}"', 1
        )[0]
        jq = self._test_tool("jq")
        run_id = 33066858958
        base = "b978d446c336ff2e6d86bef303f2dec5faad612c"
        valid = [
            {
                "jobs": [
                    {
                        "run_id": run_id,
                        "run_attempt": 1,
                        "head_sha": base,
                        "name": "Current revision review",
                        "status": "completed",
                        "conclusion": "success",
                        "steps": [
                            {
                                "name": "Set up job",
                                "status": "completed",
                                "conclusion": "success",
                            },
                            {
                                "name": "Run protected history-free Exact-Revision Codex review",
                                "status": "completed",
                                "conclusion": "success",
                            },
                            {
                                "name": "Re-prove exact revision and enforce the Codex verdict",
                                "status": "completed",
                                "conclusion": "success",
                            },
                            {
                                "name": "Complete job",
                                "status": "completed",
                                "conclusion": "success",
                            },
                        ],
                    },
                    {
                        "run_id": run_id,
                        "run_attempt": 1,
                        "head_sha": base,
                        "name": "Request protected verifier re-evaluation",
                        "status": "completed",
                        "conclusion": "failure",
                        "steps": [
                            {
                                "name": "Set up job",
                                "status": "completed",
                                "conclusion": "success",
                            },
                            {
                                "name": "Dispatch the protected re-evaluation helper from develop",
                                "status": "completed",
                                "conclusion": "failure",
                            },
                            {
                                "name": "Complete job",
                                "status": "completed",
                                "conclusion": "success",
                            },
                        ],
                    },
                ]
            }
        ]

        def validate(
            candidate: object,
        ) -> int:
            result = subprocess.run(
                [
                    jq,
                    "-e",
                    "--arg",
                    "base",
                    base,
                    "--argjson",
                    "run_id",
                    str(run_id),
                    jq_filter,
                ],
                input=json.dumps(candidate),
                text=True,
                capture_output=True,
                check=False,
                env={"PATH": TEST_TOOL_PATH},
            )
            return result.returncode

        self.assertEqual(0, validate(valid))
        rejected: list[object] = []
        for mutation in range(6):
            candidate = json.loads(json.dumps(valid))
            if mutation == 0:
                candidate[0]["jobs"][0]["run_attempt"] = 2
            elif mutation == 1:
                candidate[0]["jobs"][0]["head_sha"] = "0" * 40
            elif mutation == 2:
                candidate[0]["jobs"].append(
                    json.loads(json.dumps(candidate[0]["jobs"][0]))
                )
            elif mutation == 3:
                candidate[0]["jobs"][0]["steps"][1]["conclusion"] = "failure"
            elif mutation == 4:
                candidate[0]["jobs"][1]["conclusion"] = "success"
            else:
                candidate[0]["jobs"][1]["steps"][1]["conclusion"] = "success"
            rejected.append(candidate)
        for candidate in rejected:
            with self.subTest(candidate=candidate):
                self.assertNotEqual(0, validate(candidate))

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

    def test_late_review_rerun_requires_protected_single_request_evidence(
        self,
    ) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        late_authorization_marker = (
            '              test "${producer_kind}" = copilot\n'
            '              authorization_pages="$(gh api --paginate --slurp \\\n'
        )
        self.assertEqual(1, workflow.count(late_authorization_marker))
        late = workflow.split(late_authorization_marker, 1)[1]

        self.assertIn(
            "check_name=Late%20review%20rerun%20authorization",
            late,
        )
        self.assertIn(
            "^rep60-late-review-rerun:v1:[1-9][0-9]*:",
            late,
        )
        self.assertIn(
            '.schema == "rep60-late-review-rerun/v1"',
            late,
        )
        self.assertIn(
            '.path == ".github/workflows/copilot-review-refresh.yml"',
            late,
        )
        self.assertIn('.event == "pull_request_review"', late)
        self.assertIn('.actor.login == "Copilot"', late)
        self.assertIn(
            'pulls/${PR_NUMBER}/reviews/${review_id}',
            late,
        )
        self.assertIn(
            '.user.login == "copilot-pull-request-reviewer[bot]"',
            late,
        )
        self.assertIn(
            'actions/runs/${producer_run_id}/attempts/1/jobs',
            late,
        )
        self.assertIn('.conclusion == "failure"', late)
        self.assertIn(
            '.name == "Request Copilot review for current revision"',
            late,
        )
        self.assertIn(
            '.requested_reviewer.login=="Copilot"',
            late,
        )
        self.assertIn(
            '--arg start "$(jq -er \'.created_at | strings\'',
            late,
        )
        self.assertIn(
            '.created_at>=$start',
            late,
        )
        self.assertIn(
            '.created_at<=$end',
            late,
        )
        self.assertIn('| length == 1', late)
        self.assertIn(
            'test "$(date -u -d "${review_submitted_at}" +%s)" -gt',
            late,
        )
        self.assertIn('.run_attempt == 2', late)
        self.assertIn('.triggering_actor.login == $refresh_actor', late)
        self.assertNotIn('requested_reviewers', late)

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
            "              == 'lightning-it-shared-assets-sync[bot]'",
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
        controller_step = (
            "      - name: Mint protected-controller read App token"
        )
        self.assertIn(controller_step, source_token)
        controller_token = source_token.partition(controller_step)[2]
        self.assertIn("id: controller-app", controller_token)
        self.assertIn("repositories: .github", controller_token)
        self.assertIn("permission-contents: read", controller_token)
        self.assertNotIn("permission-actions: write", controller_token)
        self.assertNotIn("permission-contents: write", controller_token)
        self.assertNotIn("permission-checks", controller_token)
        self.assertIn(
            "SOURCE_GH_TOKEN: ${{ steps.source-app.outputs.token }}", workflow
        )
        self.assertIn(
            "CONTROLLER_GH_TOKEN: ${{ steps.controller-app.outputs.token }}",
            workflow,
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
        self.assertIn(".base.ref == $base_ref", human_path)
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
            "main-controller-seed-classification",
            "main-controller-seed-evidence",
            "main-controller-seed-final-rebind",
            "main-trust-root-bootstrap-classification",
            "main-trust-root-bootstrap-evidence",
            "main-trust-root-bootstrap-final-rebind",
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
        permanent = workflow.split(
            "      - name: Verify one protected result for the exact live revision\n",
            1,
        )[1]
        job_header = workflow.split(
            "  verify-protected-current-revision-evidence:", 1
        )[1].split("    permissions:", 1)[0]
        self.assertNotIn("if:", job_header)
        reservation = permanent.index("reservation_external_id=")
        failure_trap = permanent.index("trap finalize_failure ERR")
        draft_rejection = permanent.index('test "${draft}" = false')
        self.assertLess(reservation, draft_rejection)
        self.assertLess(failure_trap, draft_rejection)
        self.assertNotIn("openai/", workflow.lower())

    def test_failed_ready_run_reserves_a_single_later_rerun(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        permanent = workflow.split(
            "      - name: Verify one protected result for the exact live revision\n",
            1,
        )[1]
        reservation = permanent.index("reservation_external_id=")
        trap = permanent.index("trap finalize_failure ERR")
        self.assertLess(reservation, trap)
        self.assertIn(
            'test "${GITHUB_RUN_ATTEMPT}" -eq 1 || test "${GITHUB_RUN_ATTEMPT}" -eq 2',
            permanent,
        )
        self.assertIn(
            'reservation_id="$(jq -er \'.[0].id | select(type == "number" and . > 0)\'',
            permanent,
        )
        self.assertIn(
            'reservation_id="$(jq -er \'.id | select(type == "number" and . > 0)\'',
            permanent,
        )
        self.assertEqual(
            permanent.count('-f "details_url=${reservation_url}"'),
            2,
        )
        reservation_selection = permanent.split('all_reservations="$(jq -c', 1)[1].split(
            'reservation_count="$(jq', 1
        )[0]
        self.assertIn("select(.head_sha == $head)", reservation_selection)
        self.assertIn("startswith($v3_prefix)", reservation_selection)
        self.assertIn("endswith($v3_suffix)", reservation_selection)
        self.assertIn("startswith($v2_prefix)", reservation_selection)
        self.assertIn("endswith($v2_suffix)", reservation_selection)
        self.assertIn('foreign_reservations="$(jq -c', reservation_selection)
        self.assertEqual(
            permanent.count('-f external_id="${reservation_external_id}"'),
            3,
        )
        self.assertIn(
            "^rep60-required-workflow:v3:[1-9][0-9]*:${PR_NUMBER}:${EVENT_BASE}:${EVENT_HEAD}$",
            permanent,
        )
        self.assertIn(
            "^rep60-required-workflow:v2:([1-9][0-9]*):${PR_NUMBER}:${EVENT_HEAD}$",
            permanent,
        )
        self.assertIn('prior_verifier_run="$(gh api', permanent)
        self.assertIn('.workflow_id == $workflow_id', permanent)
        self.assertIn('.status == "completed"', permanent)
        self.assertIn(
            '(.conclusion == "success" or .conclusion == "failure")',
            permanent,
        )
        self.assertLess(
            permanent.index('prior_external_id="$(jq -er'),
            permanent.index('-f external_id="${reservation_external_id}"'),
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

    def test_identity_access_controller_seed_is_script_bound_and_fail_closed(
        self,
    ) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        seed = workflow.split("controller_seed_verified=false", 1)[1].split(
            "bootstrap_verified=false", 1
        )[0]

        self.assertEqual(
            3,
            workflow.count(
                "fix(rep60): seed protected main review controller"
            ),
        )
        self.assertIn("verify-main-trust-root-bootstrap.py", seed)
        self.assertEqual(2, seed.count("--controller-seed"))
        self.assertIn("rep60-main-controller-seed:v1:", seed)
        self.assertIn('"rep60-main-controller-seed/v1"', seed)
        self.assertIn(
            "immutable protected-source controller seed with exact Copilot review",
            seed,
        )
        self.assertIn("main-controller-seed-final-rebind", seed)
        self.assertIn("final_controller_seed_summary", seed)
        self.assertIn(
            'test "${final_controller_seed_summary}" =',
            seed,
        )
        self.assertIn("GH_TOKEN=\"${CONTROLLER_GH_TOKEN}\" gh api", seed)
        self.assertIn('test -n "${SOURCE_GH_TOKEN}"', seed)
        self.assertIn("git hash-object protected-controller-seed/verify.py", seed)
        self.assertIn("-f name='Current revision review'", seed)
        self.assertIn(".app.id == 15368", seed)
        self.assertIn('.app.slug == "github-actions"', seed)
        self.assertNotIn("temporary", seed)
        self.assertNotIn("openai/codex-action@", seed)
        self.assertNotRegex(seed, r'\[ "\$\{PR_NUMBER\}" = [0-9]+ \]')

        failure_trap = workflow.index("trap finalize_failure ERR")
        controller_seed = workflow.index("controller_seed_verified=false")
        durable_bootstrap = workflow.index("bootstrap_verified=false")
        self.assertLess(failure_trap, controller_seed)
        self.assertLess(controller_seed, durable_bootstrap)

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
        durable_bootstrap = workflow.index("bootstrap_verified=false")
        managed_sync = workflow.index("managed_sync_verified=false")
        permanent_inventory = workflow.index(
            "failure_stage='permanent-producer-inventory'"
        )
        self.assertLess(failure_trap, durable_bootstrap)
        self.assertLess(durable_bootstrap, managed_sync)
        self.assertLess(managed_sync, permanent_inventory)
        bootstrap = workflow[durable_bootstrap:managed_sync]
        self.assertIn("verify-main-trust-root-bootstrap.py", bootstrap)
        self.assertIn('bootstrap_content="$(jq -er .content', bootstrap)
        self.assertIn('base64 --decode <<<"${bootstrap_content}"', bootstrap)
        self.assertIn('bootstrap_blob_sha="$(base64 --decode', bootstrap)
        self.assertIn("git hash-object --stdin", bootstrap)
        self.assertIn('test "${bootstrap_blob_sha}" =', bootstrap)
        self.assertIn("| python3 -", bootstrap)
        self.assertNotIn("bootstrap_stage", bootstrap)
        self.assertNotIn("protected-bootstrap-final", bootstrap)
        self.assertNotIn("verify.py\"", bootstrap)
        self.assertNotIn(">protected-bootstrap/verify.py", bootstrap)
        self.assertLess(
            bootstrap.index('bootstrap_blob_sha="$(base64 --decode'),
            bootstrap.index('test "${bootstrap_blob_sha}" ='),
        )
        self.assertIn("rep60-main-trust-root-bootstrap:v1:", bootstrap)
        self.assertIn("Protected main trust-root bootstrap reviewed", bootstrap)
        self.assertIn('".github/workflows/current-revision-rerun.yml"', bootstrap)
        self.assertIn("main-trust-root-bootstrap-final-rebind", bootstrap)
        self.assertIn("final_bootstrap_summary", bootstrap)
        self.assertIn("test \"${final_bootstrap_summary}\"", bootstrap)
        self.assertIn("-f name='Current revision review'", bootstrap)
        check_id = bootstrap.index('bootstrap_check_id="$(jq -er')
        identity_verify = bootstrap.index(
            '--arg evidence "${bootstrap_summary}"', check_id
        )
        identity_verified = bootstrap.index(
            '<<<"${bootstrap_check}" >/dev/null', identity_verify
        )
        final_rebind = bootstrap.index(
            "failure_stage='main-trust-root-bootstrap-final-rebind'"
        )
        self.assertLess(check_id, identity_verify)
        self.assertLess(identity_verify, identity_verified)
        self.assertLess(identity_verified, final_rebind)
        identity_binding = bootstrap[identity_verify:final_rebind]
        for immutable_predicate in (
            '.id == $check_id',
            '.name == "Current revision review"',
            ".head_sha == $head",
            ".external_id == $external_id",
            '.status == "completed"',
            '.conclusion == "success"',
            '.app.id == 15368',
            '.app.slug == "github-actions"',
            ".output.title == $title",
            ".output.summary == $evidence",
        ):
            self.assertIn(immutable_predicate, identity_binding)
        self.assertIn('-f "output[summary]=${bootstrap_summary}"', bootstrap)
        self.assertNotIn('-f details_url="${producer_run_url}"', bootstrap)
        self.assertNotIn('-f "details_url=${producer_run_url}"', bootstrap)
        self.assertNotIn(
            '"repos/${REPOSITORY}/check-runs/${bootstrap_check_id}"',
            bootstrap,
        )
        self.assertNotIn("openai/codex-action@", bootstrap)
        self.assertNotIn("copilot-requests", bootstrap)
        self.assertNotIn("temporary", bootstrap)
        self.assertNotRegex(bootstrap, r'\[ "\$\{PR_NUMBER\}" = [0-9]+ \]')
        recovery = workflow[managed_sync:permanent_inventory]
        self.assertNotIn("temporary", recovery)
        self.assertNotIn("bootstrap", recovery)
        self.assertLess(
            workflow.index(
                "output[title]=Protected current-revision evidence verified"
            ),
            workflow.rindex("trap - ERR"),
        )

    def test_permanent_verifier_awaits_protected_evidence_without_a_rerun_race(
        self,
    ) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        permanent = workflow.split(
            "failure_stage='permanent-producer-inventory'", 1
        )[1].split("failure_stage='permanent-finalization'", 1)[0]

        self.assertIn("for evidence_observation in $(seq 1 450)", permanent)
        self.assertIn("sleep 2", permanent)
        self.assertIn('current_pr="$(gh api', permanent)
        for binding in (
            '.state == "open"',
            ".draft == false",
            ".base.sha == $base",
            ".head.sha == $head",
            ".base.repo.full_name == $repository",
            '(.head.repo.full_name | type) == "string"',
            "(.head.repo.full_name | length) > 0",
        ):
            self.assertIn(binding, permanent)
        self.assertIn('if [ "${neutral_count}" -gt 1 ]', permanent)
        self.assertIn('if [ "${neutral_count}" -eq 1 ]', permanent)
        self.assertIn('if [ "${neutral_status}" = completed ]', permanent)
        self.assertIn(
            '.[0].conclusion | debug | select(. == "success")', permanent
        )
        self.assertIn('^(queued|in_progress)$', permanent)
        self.assertIn(
            "The protected current-revision result did not become successful in time.",
            permanent,
        )

        self.assertIn("producer_evidence_ready=false", permanent)
        terminal_wait = workflow.split(
            "      - name: Await the exact protected producer run terminal state\n",
            1,
        )[1].split(
            "      - name: Verify one protected result for the exact live revision\n",
            1,
        )[0]
        self.assertIn("for observation in $(seq 1 450)", terminal_wait)
        self.assertIn("for observation in $(seq 1 120)", terminal_wait)
        self.assertIn("producer_kind=''", terminal_wait)
        self.assertIn('producer_kind=release-app', terminal_wait)
        self.assertEqual(
            2,
            terminal_wait.count('producer_kind="${BASH_REMATCH[1]}"'),
        )
        nonterminal_handoff_guard = (
            'if [ "${producer_kind}" = copilot ] \\\n'
            '            || [ "${producer_kind}" = release-app ] \\\n'
            '            || [ "${producer_kind}:${ALLOW_IN_PROGRESS_MANAGED_SYNC}" '
            '= managed-sync:true ]; then'
        )
        self.assertIn(nonterminal_handoff_guard, terminal_wait)
        self.assertIn(".id == $run_id", terminal_wait)
        self.assertIn('^(queued|in_progress)$', terminal_wait)
        self.assertIn('^(queued|in_progress|completed)$', terminal_wait)
        nonterminal_handoff = terminal_wait.split(nonterminal_handoff_guard, 1)[
            1
        ].split("          else\n", 1)[0]
        self.assertNotIn("for observation in $(seq 1 120)", nonterminal_handoff)
        self.assertIn(
            "Copilot, Exact-Revision, and the narrowly bound same-repository",
            nonterminal_handoff,
        )
        self.assertIn(
            "mlx90-current-revision:(copilot|managed-sync|ancestry-backmerge):v6:",
            terminal_wait,
        )
        self.assertIn(
            "mlx90-current-revision:(copilot|ancestry-backmerge):v5:",
            terminal_wait,
        )
        self.assertIn("mlx90-current-revision:v4:", terminal_wait)
        self.assertIn(
            "producer_kind=%s\\nproducer_run_id=%s\\n", terminal_wait
        )
        self.assertNotIn("wait_for_terminal_producer()", permanent)
        self.assertEqual(
            2,
            permanent.count(
                'test "${producer_run_id}" = "${TERMINAL_PRODUCER_RUN_ID}"'
            ),
        )
        self.assertIn('"${producer_kind}" = copilot', permanent)
        self.assertIn("for producer_observation in $(seq 1 60)", permanent)

        self.assertIn('if [ "${producer_status}" = queued ]', permanent)
        self.assertIn(
            "The protected producer run did not start in time.", permanent
        )
        self.assertIn("continue", permanent)
        self.assertIn('^(in_progress|completed)$', permanent)
        self.assertIn(
            "actions/runs/${producer_run_id}/jobs?filter=all&per_page=100",
            permanent,
        )
        self.assertIn('.name == "Verify current revision policy"', permanent)
        self.assertIn(
            '.name == "Verify current Copilot review and resolved findings"',
            permanent,
        )
        self.assertIn('.name == "Publish bound neutral result"', permanent)
        self.assertIn('disallowed_terminal_jobs="$(jq -c', permanent)
        self.assertIn('and .conclusion!="success"', permanent)
        self.assertIn('allowed_skipped_terminal_jobs="$(jq -c', permanent)
        self.assertIn(
            '.name=="Request Copilot review for current revision"', permanent
        )
        self.assertIn(
            "Diagnose Release-App reusable context and fail closed",
            permanent,
        )
        self.assertIn(
            "Re-run the one protected verifier attempt",
            permanent,
        )
        self.assertIn('has("runner_id") and .runner_id==null', permanent)
        self.assertIn('(.steps|type)=="array"', permanent)
        self.assertIn('(.steps|length)==0', permanent)
        self.assertIn('and .conclusion=="skipped"', permanent)
        self.assertIn("select(((", permanent)
        self.assertIn(") | not)]", permanent)
        self.assertIn("jq -e 'length == 0 or error(tojson)'", permanent)
        self.assertIn("length<=2", permanent)
        self.assertIn("(map(.name)|unique|length)==length", permanent)
        self.assertIn(
            "([.[].name|select(test($d))]|length)<=1",
            permanent,
        )
        helper_guard_match = re.search(
            r'''jq -e --arg d "\$\{d\}" '([^']+)' '''
            r'''<<<"\$\{allowed_skipped_terminal_jobs\}" >/dev/null''',
            permanent,
        )
        self.assertIsNotNone(helper_guard_match)
        helper_guard = helper_guard_match.group(1)
        jq = self._test_tool("jq")
        helper_pattern_match = re.search(
            r"\n\s+d='([^']+)'\n"
            r'\s+disallowed_terminal_jobs="\$\(jq -c --arg d',
            permanent,
        )
        self.assertIsNotNone(helper_pattern_match)
        helper_pattern = helper_pattern_match.group(1)

        def evaluate_helper_guard(names: list[str]) -> int:
            result = subprocess.run(
                [jq, "-e", "--arg", "d", helper_pattern, helper_guard],
                input=json.dumps([{"name": name} for name in names]),
                text=True,
                capture_output=True,
                check=False,
            )
            return result.returncode

        review_request = "Request Copilot review for current revision"
        legacy_helper = (
            "Request protected verifier re-evaluation / "
            "Diagnose Release-App reusable context and fail closed"
        )
        current_helper = (
            "Request protected verifier re-evaluation / "
            "Re-run the one protected verifier attempt"
        )
        self.assertEqual(
            0, evaluate_helper_guard([review_request, current_helper])
        )
        self.assertNotEqual(
            0, evaluate_helper_guard([current_helper, current_helper])
        )
        self.assertNotEqual(
            0, evaluate_helper_guard([legacy_helper, current_helper])
        )
        producer_loop = permanent.split(
            "for producer_observation in $(seq 1 60)", 1
        )[1].split("if [ \"${producer_run_attempt}\" -eq 1 ]; then", 1)[0]
        self.assertLess(
            producer_loop.index('disallowed_terminal_jobs="$(jq -c'),
            producer_loop.index('if [ "${producer_status}" = completed ]'),
        )
        self.assertIn('producer_evidence_ready=true', permanent)
        self.assertIn(
            '--argjson evidence_ready "${producer_evidence_ready}"', permanent
        )
        self.assertIn(
            '($evidence_ready\n                      and .status == "in_progress"',
            permanent,
        )
        self.assertLess(
            permanent.index("for evidence_observation in $(seq 1 450)"),
            permanent.index("producer_evidence_ready=false"),
        )
        self.assertNotIn("actions/runs/${run_id}/rerun", permanent)
        self.assertNotIn("actions/jobs/${required_job_id}/rerun", permanent)

    def test_release_app_producer_breaks_only_the_verified_helper_deadlock(
        self,
    ) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        validator = workflow.split(
            "      - name: Validate an Exact-Revision producer handoff\n",
            1,
        )[1].split(
            "      - name: Verify one protected result for the exact live revision\n",
            1,
        )[0]
        self.assertIn(
            "steps.terminal-producer.outputs.producer_kind == 'release-app'",
            validator,
        )
        for binding in (
            "producer_status",
            "producer_conclusion",
            'select(has("conclusion"))',
            'if .conclusion == null then ""',
            '.conclusion | select(type == "string")',
            "terminal_helper_handoff=false",
            "terminal_success_handoff=false",
            'if [ "${producer_conclusion}" = success ]; then',
            "terminal_success_handoff=true",
            'test "${producer_conclusion}" = failure',
            "terminal_helper_handoff=true",
            ".run_id == $run_id",
            ".run_attempt == 1",
            ".head_sha == $base",
            'or (.name | startswith(',
            '"Request protected verifier re-evaluation"',
            '(.status == "completed" and .conclusion == "success")',
            '.status == "requested"',
            '.status == "waiting"',
            '.status == "pending"',
            'and .conclusion == null)',
            'review_job_count="$(jq',
            'test "${review_job_count}" -le 1',
            'test "${helper_job_count}" -le 1',
            'select(.name == "Current revision review")',
            'select(.head_sha == $base and .run_attempt == 1)',
            'select(.status == "completed" and .conclusion == "success")',
            '[$review.steps[]?',
            '"Run protected history-free Exact-Revision Codex review"',
            '"Re-prove exact revision and enforce the Codex verdict"',
            'select(.conclusion == "success"',
            'or .conclusion == "skipped")',
            '--argjson terminal_helper_handoff',
            '"${terminal_helper_handoff}"',
            '--argjson terminal_success_handoff',
            '"${terminal_success_handoff}"',
            '.event == "workflow_dispatch"',
            '.run_attempt == 1',
            '.status == "queued"',
            '.status == "in_progress"',
            '.conclusion == null',
            '$terminal_success_handoff',
            '.conclusion == "success"',
            '$terminal_helper_handoff',
            '.status == "completed"',
            '.conclusion == "failure"',
            '.path == ".github/workflows/release-bot-exact-head-review.yml"',
            '.actor.login == $actor',
            '.triggering_actor.login == $actor',
            '.base.sha == $base',
            '.head.sha == $head',
            '.head.repo.full_name == $repository',
            '.user.login == "lightning-it-release-automation[bot]"',
            "ready=true",
        ):
            self.assertIn(binding, validator)
        self.assertNotIn(
            'if [ "${producer_status}" = completed ] \\\n'
            '              && [ "${producer_conclusion}" = success ]; then\n'
            "              exit 0",
            validator,
        )

        conclusion_filter = validator.split(
            'producer_conclusion="$(jq -er \'\n', 1
        )[1].split(
            '\n              \' <<<"${producer}")"', 1
        )[0]
        jq = self._test_tool("jq")
        for payload, expected in (
            ({"conclusion": None}, ""),
            ({"conclusion": "success"}, "success"),
            ({"conclusion": "failure"}, "failure"),
        ):
            result = subprocess.run(
                [jq, "-er", conclusion_filter],
                input=json.dumps(payload),
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout.rstrip("\n"), expected)
        for payload in (
            {},
            {"conclusion": 1},
            {"conclusion": True},
            {"conclusion": {}},
            {"conclusion": []},
        ):
            result = subprocess.run(
                [jq, "-er", conclusion_filter],
                input=json.dumps(payload),
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)

        producer_filter = validator.rsplit(
            '--argjson run_id "${PRODUCER_RUN_ID}" \'\n',
            1,
        )[1].split(
            '\n                \' <<<"${producer}" >/dev/null',
            1,
        )[0]
        base = "a" * 40
        run_id = 123
        title = f"Exact-Revision Codex PR #7 {base}..{'b' * 40}"
        producer_payload = {
            "id": run_id,
            "event": "workflow_dispatch",
            "run_attempt": 1,
            "status": "queued",
            "conclusion": None,
            "head_branch": "develop",
            "head_sha": base,
            "path": ".github/workflows/release-bot-exact-head-review.yml",
            "display_title": title,
            "actor": {"login": "lightning-it-release-automation[bot]"},
            "triggering_actor": {
                "login": "lightning-it-release-automation[bot]"
            },
        }

        def validates_producer(
            status: str,
            conclusion: object,
            *,
            terminal_failure: bool = False,
            terminal_success: bool = False,
        ) -> bool:
            payload = dict(producer_payload)
            payload.update(status=status, conclusion=conclusion)
            result = subprocess.run(
                [
                    jq,
                    "-e",
                    "--arg",
                    "actor",
                    "lightning-it-release-automation[bot]",
                    "--arg",
                    "base_ref",
                    "develop",
                    "--arg",
                    "base_sha",
                    base,
                    "--arg",
                    "head",
                    "b" * 40,
                    "--arg",
                    "title",
                    title,
                    "--argjson",
                    "terminal_helper_handoff",
                    str(terminal_failure).lower(),
                    "--argjson",
                    "terminal_success_handoff",
                    str(terminal_success).lower(),
                    "--argjson",
                    "run_id",
                    str(run_id),
                    producer_filter,
                ],
                input=json.dumps(payload),
                text=True,
                capture_output=True,
                check=False,
            )
            return result.returncode == 0

        self.assertTrue(validates_producer("queued", None))
        self.assertTrue(validates_producer("in_progress", None))
        self.assertTrue(
            validates_producer(
                "completed", "success", terminal_success=True
            )
        )
        self.assertTrue(
            validates_producer(
                "completed", "failure", terminal_failure=True
            )
        )
        self.assertFalse(validates_producer("queued", "success"))
        self.assertFalse(validates_producer("completed", "success"))
        self.assertFalse(validates_producer("completed", "failure"))
        self.assertFalse(validates_producer("waiting", None))

        inventory_filter = validator.split(
            '            jq -e \\\n'
            '              --arg base "${EVENT_BASE}" \\\n'
            '              --argjson run_id "${PRODUCER_RUN_ID}" \'\n',
            1,
        )[1].split(
            '\n              \' <<<"${jobs_pages}" >/dev/null',
            1,
        )[0]
        review_job = {
            "run_id": run_id,
            "run_attempt": 1,
            "head_sha": base,
            "name": "Current revision review",
            "status": "completed",
            "conclusion": "success",
        }

        def validates_inventory(
            helper_status: str,
            helper_conclusion: object = None,
            *,
            helper_name: str = "Request protected verifier re-evaluation",
        ) -> bool:
            helper_job = {
                "run_id": run_id,
                "run_attempt": 1,
                "head_sha": base,
                "name": helper_name,
                "status": helper_status,
                "conclusion": helper_conclusion,
            }
            result = subprocess.run(
                [
                    jq,
                    "-e",
                    "--arg",
                    "base",
                    base,
                    "--argjson",
                    "run_id",
                    str(run_id),
                    inventory_filter,
                ],
                input=json.dumps([{"jobs": [review_job, helper_job]}]),
                text=True,
                capture_output=True,
                check=False,
            )
            return result.returncode == 0

        for helper_status in (
            "requested",
            "waiting",
            "pending",
            "queued",
            "in_progress",
        ):
            with self.subTest(helper_status=helper_status):
                self.assertTrue(validates_inventory(helper_status))
        self.assertTrue(validates_inventory("completed", "success"))
        self.assertFalse(validates_inventory("completed", "failure"))
        self.assertFalse(validates_inventory("waiting", "success"))
        self.assertFalse(validates_inventory("unknown"))
        self.assertFalse(
            validates_inventory("queued", helper_name="unexpected")
        )

        terminal_filter = validator.split(
            '                  "${terminal_success_handoff}" \'\n'
            '                  [.[].jobs[]?] as $jobs\n',
            1,
        )[1].split(
            '\n                \' <<<"${jobs_pages}" >/dev/null',
            1,
        )[0]
        terminal_filter = "[.[].jobs[]?] as $jobs\n" + terminal_filter
        valid_job = {
            "name": "Current revision review",
            "status": "completed",
            "conclusion": "success",
            "steps": [
                {
                    "name": (
                        "Run protected history-free Exact-Revision Codex "
                        "review"
                    ),
                    "status": "completed",
                    "conclusion": "success",
                },
                {
                    "name": (
                        "Re-prove exact revision and enforce the Codex verdict"
                    ),
                    "status": "completed",
                    "conclusion": "success",
                },
            ],
        }
        def validates(
            jobs: list[dict[str, object]],
            *,
            terminal_failure: bool = True,
            terminal_success: bool = False,
        ) -> bool:
            result = subprocess.run(
                [
                    jq,
                    "-e",
                    "--argjson",
                    "terminal_helper_handoff",
                    str(terminal_failure).lower(),
                    "--argjson",
                    "terminal_success_handoff",
                    str(terminal_success).lower(),
                    terminal_filter,
                ],
                input=json.dumps([{"jobs": jobs}]),
                text=True,
                capture_output=True,
                check=False,
            )
            return result.returncode == 0

        self.assertTrue(validates([valid_job]))
        successful_helper = {
            "name": "Request protected verifier re-evaluation",
            "status": "completed",
            "conclusion": "success",
            "steps": [],
        }
        self.assertTrue(
            validates(
                [valid_job, successful_helper],
                terminal_failure=False,
                terminal_success=True,
            )
        )
        self.assertTrue(
            validates(
                [valid_job],
                terminal_failure=False,
                terminal_success=True,
            )
        )
        pending_helper = dict(successful_helper)
        pending_helper.update(status="queued", conclusion=None)
        self.assertTrue(
            validates(
                [valid_job, pending_helper],
                terminal_failure=False,
            )
        )
        self.assertFalse(
            validates(
                [valid_job, pending_helper],
                terminal_failure=False,
                terminal_success=True,
            )
        )
        reused_job = json.loads(json.dumps(valid_job))
        reused_job["steps"][0]["conclusion"] = "skipped"
        self.assertTrue(validates([reused_job]))
        for mutation in (
            "extra-job",
            "failed-review-job",
            "failed-codex-step",
            "missing-enforcement-step",
        ):
            candidate = json.loads(json.dumps(valid_job))
            jobs = [candidate]
            if mutation == "extra-job":
                jobs.append(
                    {
                        "name": "unexpected",
                        "status": "completed",
                        "conclusion": "success",
                        "steps": [],
                    }
                )
            elif mutation == "failed-review-job":
                candidate["conclusion"] = "failure"
            elif mutation == "failed-codex-step":
                candidate["steps"][0]["conclusion"] = "failure"
            else:
                candidate["steps"] = candidate["steps"][:1]
            with self.subTest(mutation=mutation):
                self.assertFalse(validates(jobs))

        final_verifier = workflow.split(
            "      - name: Verify one protected result for the exact live revision\n",
            1,
        )[1]
        self.assertIn(
            "RELEASE_APP_PRODUCER_EVIDENCE_READY", final_verifier
        )
        self.assertIn(
            '--argjson evidence_ready \\\n'
            '                "${RELEASE_APP_PRODUCER_EVIDENCE_READY:-false}"',
            final_verifier,
        )
        self.assertIn(
            '($evidence_ready and (\n'
            '                    ((.status | IN("queued", "in_progress"))\n'
            '                      and .conclusion == null)\n'
            '                    or (.status == "completed"'
            ' and .conclusion == "failure")))',
            final_verifier,
        )

    def test_required_verifier_stays_below_actionlint_pipe_deadlock_limit(
        self,
    ) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        verifier = workflow.split(
            "      - name: Verify one protected result for the exact live revision\n",
            1,
        )[1]
        script = verifier.split("        run: |\n", 1)[1]
        script_lines = script.splitlines()
        first_script_line = next(
            line for line in script_lines if line.strip()
        )
        indentation_width = len(first_script_line) - len(
            first_script_line.lstrip(" ")
        )
        self.assertGreater(indentation_width, 0)
        indentation = " " * indentation_width
        self.assertTrue(
            all(
                not line.strip() or line.startswith(indentation)
                for line in script_lines
            )
        )
        normalized = "\n".join(
            line[len(indentation) :] if line.startswith(indentation) else ""
            for line in script_lines
        ) + "\n"
        self.assertLessEqual(
            len(normalized.encode("utf-8")),
            64_500,
            "actionlint 1.7.12 deadlocks before ShellCheck starts when one "
            "run block approaches the Linux 65,536-byte pipe capacity",
        )

        quality = REPOSITORY_QUALITY_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("    timeout-minutes: 10\n", quality)

    def test_terminal_wait_extracts_only_one_exact_producer_run(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        terminal_wait = workflow.split(
            "      - name: Await the exact protected producer run terminal state\n",
            1,
        )[1].split(
            "      - name: Verify one protected result for the exact live revision\n",
            1,
        )[0]
        selector = 'neutral="$(jq -c \\\n' + terminal_wait.split(
            '            neutral="$(jq -c \\\n', 1
        )[1].split('            test "${observation}" -lt 450\n', 1)[0]
        selector = textwrap.dedent(selector)
        bash = self._test_tool("bash")
        base = "a" * 40
        head = "b" * 40
        pr_number = "1502"

        def extract(external_ids: list[str]) -> subprocess.CompletedProcess[str]:
            pages = [
                {
                    "check_runs": [
                        {
                            "name": "Current revision review",
                            "app": {"id": 15368, "slug": "github-actions"},
                            "head_sha": head,
                            "status": "completed",
                            "conclusion": "success",
                            "external_id": external_id,
                        }
                        for external_id in external_ids
                    ]
                }
            ]
            script = (
                "set -euo pipefail\n"
                "producer_run_id=''\n"
                "for observation in 1; do\n"
                f"{textwrap.indent(selector, '  ')}"
                "done\n"
                '[[ "${producer_run_id}" =~ ^[1-9][0-9]*$ ]]\n'
                'printf "%s" "${producer_run_id}"\n'
            )
            return subprocess.run(
                [bash, "-c", script],
                env={
                    "PATH": TEST_TOOL_PATH,
                    "EVENT_BASE": base,
                    "EVENT_HEAD": head,
                    "PR_NUMBER": pr_number,
                    "pages": json.dumps(pages),
                },
                text=True,
                capture_output=True,
                check=False,
            )

        accepted = {
            f"mlx90-current-revision:v4:123:{'c' * 64}": "123",
            f"mlx90-current-revision:copilot:v5:456:{base}:{head}": "456",
            (
                "mlx90-current-revision:managed-sync:v6:"
                f"{pr_number}:789:{base}:{head}"
            ): "789",
        }
        for external_id, run_id in accepted.items():
            with self.subTest(external_id=external_id):
                result = extract([external_id])
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual(run_id, result.stdout)

        rejected = (
            [f"mlx90-current-revision:copilot:v6:99:789:{base}:{head}"],
            [f"mlx90-current-revision:copilot:v5:789:{head}:{base}"],
            [
                f"mlx90-current-revision:v4:123:{'c' * 64}",
                f"mlx90-current-revision:v4:456:{'d' * 64}",
            ],
        )
        for external_ids in rejected:
            with self.subTest(external_ids=external_ids):
                self.assertNotEqual(0, extract(external_ids).returncode)

    def test_terminal_wait_uses_exact_live_readiness_on_rerun(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        readiness = workflow.split(
            "      - name: Classify the exact live pull request readiness\n",
            1,
        )[1].split(
            "      - name: Await the exact protected producer run terminal state\n",
            1,
        )[0]
        readiness_header = readiness.split("        env:\n", 1)[0]
        terminal_header = workflow.split(
            "      - name: Await the exact protected producer run terminal state\n",
            1,
        )[1].split("        env:\n", 1)[0]
        terminal = workflow.split(
            "      - name: Await the exact protected producer run terminal state\n",
            1,
        )[1].split(
            "      - name: Validate an Exact-Revision producer handoff\n",
            1,
        )[0]
        for binding in (
            "EXPECTED_HEAD_REPOSITORY: >-",
            "github.event.pull_request.head.repo.full_name",
            '[[ "${EXPECTED_HEAD_REPOSITORY}" =~ '
            '^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]]',
            'pr="$(gh api "repos/${REPOSITORY}/pulls/${PR_NUMBER}")"',
            ".number == $number",
            '.state == "open"',
            '(.draft | type) == "boolean"',
            ".base.sha == $base",
            ".base.repo.full_name == $repository",
            ".head.sha == $head",
            ".head.repo.full_name == $head_repository",
            'echo \'ready=true\' >>"${GITHUB_OUTPUT}"',
            'echo \'ready=false\' >>"${GITHUB_OUTPUT}"',
        ):
            with self.subTest(binding=binding):
                self.assertIn(binding, readiness)
        self.assertIn(
            "if: steps.bootstrap-handoff.outputs.active != 'true'",
            readiness_header,
        )
        self.assertIn("steps.live-pr.outputs.ready == 'true'", terminal_header)
        for binding in (
            "ALLOW_IN_PROGRESS_MANAGED_SYNC: >-",
            "github.repository == 'lightning-it/.github'",
            "== 'lightning-it-shared-assets-sync[bot]'",
            "github.event.pull_request.base.ref == 'develop'",
            "github.event.pull_request.head.repo.full_name",
            "== github.repository",
            "'chore/sync-repository-quality-.github-'",
            "'chore/sync-shared-assets-lit-.github-'",
            '[[ "${ALLOW_IN_PROGRESS_MANAGED_SYNC}" =~ ^(true|false)$ ]]',
            '|| [ "${producer_kind}:${ALLOW_IN_PROGRESS_MANAGED_SYNC}" '
            '= managed-sync:true ]; then',
        ):
            with self.subTest(managed_sync_in_progress_handoff=binding):
                self.assertIn(binding, terminal)
        self.assertNotIn(
            "lightning-it-shared-assets-sync[bot]", terminal_header
        )
        self.assertNotIn(
            "github.event.pull_request.draft == false", terminal_header
        )
        jq_filter = readiness.split(
            '--argjson number "${PR_NUMBER}" \'\n', 1
        )[1].split('\n            \' <<<"${pr}"', 1)[0]
        jq = self._test_tool("jq")
        base = "a" * 40
        head = "b" * 40
        repository = "lightning-it/.github"
        head_repository = "external-contributor/fork"

        def validate(payload: object) -> int:
            return subprocess.run(
                [
                    jq,
                    "-e",
                    "--arg",
                    "base",
                    base,
                    "--arg",
                    "head",
                    head,
                    "--arg",
                    "head_repository",
                    head_repository,
                    "--arg",
                    "repository",
                    repository,
                    "--argjson",
                    "number",
                    "358",
                    jq_filter,
                ],
                input=json.dumps(payload),
                text=True,
                capture_output=True,
                check=False,
                env={"PATH": TEST_TOOL_PATH},
            ).returncode

        live_pr = {
            "number": 358,
            "state": "open",
            "draft": False,
            "base": {"sha": base, "repo": {"full_name": repository}},
            "head": {"sha": head, "repo": {"full_name": head_repository}},
        }
        self.assertEqual(0, validate(live_pr))
        draft_pr = json.loads(json.dumps(live_pr))
        draft_pr["draft"] = True
        self.assertEqual(0, validate(draft_pr))
        for mutation in ("head", "state", "draft"):
            candidate = json.loads(json.dumps(live_pr))
            if mutation == "head":
                candidate["head"]["sha"] = "c" * 40
            elif mutation == "state":
                candidate["state"] = "closed"
            else:
                candidate["draft"] = "false"
            with self.subTest(mutation=mutation):
                self.assertNotEqual(0, validate(candidate))

    def test_permanent_verifier_rejects_every_unexpected_terminal_job(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        permanent = workflow.split(
            "failure_stage='permanent-producer-inventory'", 1
        )[1].split("failure_stage='permanent-finalization'", 1)[0]

        def assignment_filter(name: str) -> str:
            marker = f'{name}="$(jq -c'
            start = permanent.index(marker) + len(marker)
            start = permanent.index("'\n", start) + 2
            end = permanent.index(
                '\n                  \' <<<"${producer_jobs_pages}")"', start
            )
            return permanent[start:end]

        jobs = [
            {
                "name": "Verify current revision policy",
                "status": "completed",
                "conclusion": "success",
            },
            {
                "name": "Request Copilot review for current revision",
                "status": "completed",
                "conclusion": "skipped",
            },
            {
                "name": "Classify protected Release-App ancestry backmerge",
                "status": "completed",
                "conclusion": "skipped",
                "runner_id": None,
                "steps": [],
            },
            {
                "name": (
                    "Request protected verifier re-evaluation / "
                    "Diagnose Release-App reusable context and fail closed"
                ),
                "status": "completed",
                "conclusion": "skipped",
                "runner_id": None,
                "steps": [],
            },
            {
                "name": (
                    "Request protected verifier re-evaluation / "
                    "Re-run the one protected verifier attempt"
                ),
                "status": "completed",
                "conclusion": "skipped",
                "runner_id": None,
                "steps": [],
            },
            {
                "name": (
                    "Request protected verifier re-evaluation / "
                    "Diagnose Release-App reusable context and fail closed"
                ),
                "status": "completed",
                "conclusion": "skipped",
                "steps": [],
            },
            {
                "name": (
                    "Request protected verifier re-evaluation / "
                    "Re-run the one protected verifier attempt"
                ),
                "status": "completed",
                "conclusion": "skipped",
                "steps": [],
            },
            {
                "name": "Classify protected Release-App ancestry backmerge",
                "status": "completed",
                "conclusion": "skipped",
                "steps": [],
            },
            {
                "name": "cancelled job",
                "status": "completed",
                "conclusion": "cancelled",
            },
            {
                "name": "timed out job",
                "status": "completed",
                "conclusion": "timed_out",
            },
            {
                "name": "unexpected skipped job",
                "status": "completed",
                "conclusion": "skipped",
            },
            {
                "name": "running job",
                "status": "in_progress",
                "conclusion": None,
            },
        ]
        source = json.dumps([{"jobs": jobs}])
        jq = self._test_tool("jq")
        helper_pattern = (
            "^Request protected verifier re-evaluation / "
            "(Diagnose Release-App reusable context and fail closed|"
            "Re-run the one protected verifier attempt)$"
        )

        def evaluate(name: str) -> list[dict[str, object]]:
            result = subprocess.run(
                [
                    jq,
                    "-c",
                    "--arg",
                    "d",
                    helper_pattern,
                    assignment_filter(name),
                ],
                input=source,
                text=True,
                capture_output=True,
                check=True,
            )
            return json.loads(result.stdout)

        self.assertEqual(
            [job["name"] for job in evaluate("disallowed_terminal_jobs")],
            [
                "Request protected verifier re-evaluation / "
                "Diagnose Release-App reusable context and fail closed",
                "Request protected verifier re-evaluation / "
                "Re-run the one protected verifier attempt",
                "Classify protected Release-App ancestry backmerge",
                "cancelled job",
                "timed out job",
                "unexpected skipped job",
            ],
        )
        self.assertEqual(
            [job["name"] for job in evaluate("allowed_skipped_terminal_jobs")],
            [
                "Request Copilot review for current revision",
                "Classify protected Release-App ancestry backmerge",
                "Request protected verifier re-evaluation / "
                "Diagnose Release-App reusable context and fail closed",
                "Request protected verifier re-evaluation / "
                "Re-run the one protected verifier attempt",
            ],
        )

        allowed = evaluate("allowed_skipped_terminal_jobs")
        request = allowed[0]
        ancestry_classifier = allowed[1]
        release_helper = allowed[2]
        current_helper = allowed[3]
        for predicate, passing_cases, failing_cases in (
            (
                "length == 0 or error(tojson)",
                [[]],
                [evaluate("disallowed_terminal_jobs")],
            ),
            (
                "(length <= 3 "
                "and (map(.name) | unique | length) == length "
                "and ([.[].name | select(test($d))] "
                "| length) <= 1) "
                "or error(tojson)",
                [
                    [request, ancestry_classifier, release_helper],
                    [request, ancestry_classifier, current_helper],
                ],
                [
                    allowed,
                    [request, ancestry_classifier, ancestry_classifier],
                    [{"name": "duplicate"}, {"name": "duplicate"}],
                ],
            ),
        ):
            for passing in passing_cases:
                success = subprocess.run(
                    [
                        jq,
                        "-e",
                        "--arg",
                        "d",
                        helper_pattern,
                        predicate,
                    ],
                    input=json.dumps(passing),
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(success.returncode, 0)
                self.assertEqual(success.stderr, "")

            for failing in failing_cases:
                failure = subprocess.run(
                    [
                        jq,
                        "-e",
                        "--arg",
                        "d",
                        helper_pattern,
                        predicate,
                    ],
                    input=json.dumps(failing),
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertNotEqual(failure.returncode, 0)
                self.assertIn(
                    json.dumps(failing, separators=(",", ":")),
                    failure.stderr,
                )

    def test_bootstrap_controller_asset_predicate_accepts_live_file_shape(
        self,
    ) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        bootstrap = workflow.split("bootstrap_verified=false", 1)[1].split(
            "managed_sync_verified=false", 1
        )[0]
        marker = (
            '              --arg url "${GITHUB_API_URL}/repos/lightning-it/'
            '.github/contents/scripts/verify-main-trust-root-bootstrap.py'
            '?ref=${WORKFLOW_SHA}" \'\n'
        )
        start = bootstrap.index(marker) + len(marker)
        end = bootstrap.index(
            '\n              \' <<<"${controller_asset}"', start
        )
        predicate = bootstrap[start:end]
        path = "scripts/verify-main-trust-root-bootstrap.py"
        url = f"https://api.github.test/repos/lightning-it/.github/contents/{path}?ref={'a' * 40}"
        jq = self._test_tool("jq")

        def accepts(candidate: dict[str, object]) -> bool:
            result = subprocess.run(
                [
                    jq,
                    "-e",
                    "--arg",
                    "path",
                    path,
                    "--arg",
                    "url",
                    url,
                    predicate,
                ],
                input=json.dumps(candidate),
                text=True,
                capture_output=True,
                check=False,
            )
            return result.returncode == 0

        valid = {
            "type": "file",
            "encoding": "base64",
            "path": path,
            "url": url,
            "sha": "b" * 40,
            "size": 32768,
            "content": "dmVyaWZpZXI=",
        }
        self.assertTrue(accepts(valid))
        for invalid_size in (0, 100000, "32768", True, None):
            with self.subTest(size=invalid_size):
                self.assertFalse(accepts({**valid, "size": invalid_size}))

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

    def test_bootstrap_handoff_is_classified_before_bounded_review_wait(
        self,
    ) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        classifier_name = (
            "      - name: Classify protected main trust-root bootstrap "
            "handoff\n"
        )
        wait_name = "      - name: Wait for one finalized bootstrap pipeline review\n"
        verifier_name = (
            "      - name: Verify one protected result for the exact live revision\n"
        )
        classifier = workflow.split(classifier_name, 1)[1].split(
            wait_name, 1
        )[0]
        wait = workflow.split(wait_name, 1)[1].split(verifier_name, 1)[0]

        self.assertLess(workflow.index(classifier_name), workflow.index(wait_name))
        self.assertLess(workflow.index(wait_name), workflow.index(verifier_name))
        self.assertIn("timeout-minutes: 60", workflow)
        self.assertIn("--classify-only", classifier)
        self.assertIn("rep60-main-trust-root-handoff/v1", classifier)
        self.assertIn("active=true", classifier)
        self.assertIn("source_blobs", classifier)
        self.assertIn("install -d -m 0700 protected-bootstrap", classifier)
        self.assertIn(
            'test "$(git hash-object protected-bootstrap/verify.py)" =',
            classifier,
        )
        self.assertIn(
            '"$(jq -r .sha <<<"${verifier_payload}")"', classifier
        )
        self.assertIn("chmod 0500 protected-bootstrap/verify.py", classifier)
        self.assertNotIn("openai/", classifier.lower())
        self.assertNotIn("copilot-requests", classifier)

        self.assertIn(
            "if: steps.bootstrap-handoff.outputs.active == 'true'", wait
        )
        self.assertIn("for _observation in $(seq 1 300)", wait)
        self.assertIn("sleep 5", wait)
        self.assertIn(".draft | type", wait)
        self.assertIn(
            'if [ "${REPOSITORY}" = "lightning-it/.github" ]; then', wait
        )
        self.assertIn('producer_event="pull_request_target"', wait)
        self.assertIn('producer_name="Current revision review gate"', wait)
        self.assertIn('producer_event="pull_request"', wait)
        self.assertIn('producer_name="Copilot review gate"', wait)
        self.assertIn("event=${producer_event}&head_sha=${EVENT_HEAD}", wait)
        self.assertIn('--arg event "${producer_event}"', wait)
        self.assertIn('--arg name "${producer_name}"', wait)
        self.assertIn("select(.event == $event)", wait)
        self.assertIn('select(.path == ".github/workflows/copilot-review.yml")', wait)
        self.assertIn("select(.name == $name)", wait)
        self.assertNotIn('select(.event == "pull_request")', wait)
        self.assertNotIn('select(.name == "Copilot review gate")', wait)
        self.assertIn("eligible_producers=0", wait)
        self.assertIn(
            "for producer_id in $(jq -r '.[].id'", wait
        )
        self.assertIn("select(.run_id == $run_id)", wait)
        self.assertIn("select(.head_sha == $head)", wait)
        self.assertIn('if [ "${eligible_producers}" -gt 1 ]', wait)
        self.assertNotIn('if [ "${run_count}" -gt 1 ]', wait)
        self.assertIn(".pull_requests[0].base.sha == $base", wait)
        self.assertIn(".pull_requests[0].head.sha == $head", wait)
        self.assertIn(
            'select(.name == "Request Copilot review for current revision")',
            wait,
        )
        self.assertIn('select(.name == "Successful Copilot review")', wait)
        self.assertIn('if [ "${review_count}" -gt 1 ]', wait)
        self.assertIn('if [ "${request_count}" -gt 1 ]', wait)
        self.assertNotIn("gh pr edit", wait)
        self.assertNotIn("requested_reviewers", wait)
        self.assertNotIn("openai/", wait.lower())

    def test_copilot_controller_trusts_only_required_workflow_job_ledger(
        self,
    ) -> None:
        workflow = COPILOT_WORKFLOW.read_text(encoding="utf-8")
        classifier = workflow.split(
            "\n  classify-main-trust-root-handoff:", 1
        )[1].split("\n  request-current-revision-review:", 1)[0]
        request = workflow.split(
            "\n  request-current-revision-review:", 1
        )[1].split("\n  verify-current-revision-policy:", 1)[0]
        verify = workflow.split(
            "\n  verify-current-revision-policy:", 1
        )[1].split("\n  request-protected-verifier-reevaluation:", 1)[0]

        for fragment in (
            'if $repository == "lightning-it/.github" then',
            '+ "/actions/workflows/"',
            '+ "/actions/required_workflows/"',
            '+ (.workflow_id | tostring)',
            'select(.repository.full_name == $repository)',
            'select(.head_repository.full_name == $repository)',
            'select(.actor.login == "litroc")',
            '.triggering_actor.login == "github-actions[bot]"',
            'select(.name == "Required current-revision workflow")',
            'select(.name == "Classify protected main trust-root bootstrap handoff")',
            'if [ "${run_count}" -gt 1 ]',
            'if [ "${job_count}" -gt 1 ]',
            'if [ "${step_count}" -gt 1 ]',
        ):
            self.assertIn(fragment, classifier)
        self.assertEqual(1, classifier.count('+ "/actions/workflows/"'))
        self.assertEqual(
            1, classifier.count('+ "/actions/required_workflows/"')
        )
        self.assertNotIn("required_workflow_url_prefix", classifier)
        self.assertNotIn("contents: read", classifier)
        self.assertIn(
            '" opened " + $head)', classifier
        )
        for excluded_action in (
            '" synchronize " + $head)',
            '" reopened " + $head)',
            '" ready_for_review " + $head)',
            '" edited " + $head)',
        ):
            self.assertNotIn(excluded_action, classifier)
        self.assertNotIn("startsWith(", classifier)
        self.assertNotIn("format(", classifier)

        for job in (request, verify):
            self.assertIn("needs: classify-main-trust-root-handoff", job)
            self.assertIn("always()", job)
            self.assertIn(
                "needs.classify-main-trust-root-handoff.outputs.active != 'true'",
                job,
            )
            self.assertNotIn(
                "bootstrap protected main review trust root", job
            )


if __name__ == "__main__":
    unittest.main()
