from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify-promotion-evidence.py"
WORKFLOW = (
    ROOT / ".github" / "workflows" / "supplementary-current-revision-required.yml"
)
SPEC = importlib.util.spec_from_file_location("promotion_evidence", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

BASE = "1" * 40
HEAD = "2" * 40
MERGE = "3" * 40
INPUT = "4" * 64


def promotion() -> dict[str, object]:
    return {
        "number": 41,
        "state": "open",
        "draft": False,
        "title": "chore(release): promote develop to main",
        "body": "release",
        "user": {
            "login": "lightning-it-release-automation[bot]",
            "id": 307565056,
            "type": "Bot",
        },
        "base": {
            "ref": "main",
            "sha": BASE,
            "repo": {"full_name": "lightning-it/example"},
        },
        "head": {
            "ref": "develop",
            "sha": HEAD,
            "repo": {"full_name": "lightning-it/example"},
        },
    }


def check_run(external_id: str, summary: str = "{}") -> dict[str, object]:
    return {
        "id": 99,
        "name": "Current revision review",
        "head_sha": HEAD,
        "status": "completed",
        "conclusion": "success",
        "external_id": external_id,
        "app": {"id": 15368, "slug": "github-actions"},
        "output": {"summary": summary},
    }


class PromotionEvidenceTests(unittest.TestCase):
    def test_exact_release_app_promotion_is_accepted(self) -> None:
        value = promotion()
        self.assertIs(
            MODULE.validate_live_promotion(
                value,
                repository="lightning-it/example",
                pull_number=41,
                expected_base=BASE,
                expected_head=HEAD,
            ),
            value,
        )

    def test_mutated_or_human_promotion_fails_closed(self) -> None:
        for field, value in (("draft", True), ("title", "release")):
            candidate = promotion()
            candidate[field] = value
            with self.subTest(field=field), self.assertRaises(MODULE.EvidenceError):
                MODULE.validate_live_promotion(
                    candidate,
                    repository="lightning-it/example",
                    pull_number=41,
                    expected_base=BASE,
                    expected_head=HEAD,
                )
        candidate = promotion()
        candidate["user"] = {"login": "litroc", "id": 1, "type": "User"}
        with self.assertRaises(MODULE.EvidenceError):
            MODULE.validate_live_promotion(
                candidate,
                repository="lightning-it/example",
                pull_number=41,
                expected_base=BASE,
                expected_head=HEAD,
            )

    def test_only_exact_merge_pull_is_selected(self) -> None:
        candidate = {
            "number": 17,
            "state": "closed",
            "merged_at": "2026-09-27T00:00:00Z",
            "merge_commit_sha": MERGE,
            "base": {
                "ref": "develop",
                "repo": {"full_name": "lightning-it/example"},
            },
            "head": {"sha": HEAD},
        }
        self.assertEqual(
            MODULE.select_ingress_pull(
                [candidate],
                repository="lightning-it/example",
                merge_sha=MERGE,
                head_sha=HEAD,
            )["number"],
            17,
        )
        with self.assertRaises(MODULE.EvidenceError):
            MODULE.select_ingress_pull(
                [candidate, dict(candidate)],
                repository="lightning-it/example",
                merge_sha=MERGE,
                head_sha=HEAD,
            )

    def test_v6_review_check_binds_pr_base_and_head(self) -> None:
        external_id = f"mlx90-current-revision:copilot:v6:17:88:{BASE}:{HEAD}"
        pages = [{"check_runs": [check_run(external_id)]}]
        evidence = MODULE.bound_review_check(
            pages,
            pull_number=17,
            base_sha=BASE,
            head_sha=HEAD,
        )
        self.assertEqual(evidence["producer_run_id"], 88)
        with self.assertRaises(MODULE.EvidenceError):
            MODULE.bound_review_check(
                pages,
                pull_number=18,
                base_sha=BASE,
                head_sha=HEAD,
            )

    def test_v4_release_review_requires_exact_json_evidence(self) -> None:
        summary = json.dumps(
            {
                "schema": 4,
                "base_sha": BASE,
                "head_sha": HEAD,
                "input_sha256": INPUT,
                "pull_request_number": 17,
                "producer_run_id": 88,
            }
        )
        pages = [
            {
                "check_runs": [
                    check_run(
                        f"mlx90-current-revision:v4:88:{INPUT}",
                        summary,
                    )
                ]
            }
        ]
        self.assertEqual(
            MODULE.bound_review_check(
                pages,
                pull_number=17,
                base_sha=BASE,
                head_sha=HEAD,
            )["evidence_kind"],
            "release-app",
        )

    def test_duplicate_checks_and_unresolved_threads_fail_closed(self) -> None:
        external_id = f"mlx90-current-revision:copilot:v6:17:88:{BASE}:{HEAD}"
        run = check_run(external_id)
        duplicate = dict(run)
        duplicate["id"] = 100
        with self.assertRaises(MODULE.EvidenceError):
            MODULE.bound_review_check(
                [{"check_runs": [run, duplicate]}],
                pull_number=17,
                base_sha=BASE,
                head_sha=HEAD,
            )
        with self.assertRaises(MODULE.EvidenceError):
            MODULE.validate_review_threads(
                {
                    "nodes": [{"isResolved": False}],
                    "pageInfo": {"hasNextPage": False},
                }
            )

    def test_ancestry_boundary_is_structural_not_timestamp_based(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory)
            environment = {
                **os.environ,
                "GIT_CONFIG_GLOBAL": "/dev/null",
                "GIT_CONFIG_NOSYSTEM": "1",
            }
            for name in ("GIT_COMMON_DIR", "GIT_DIR", "GIT_WORK_TREE"):
                environment.pop(name, None)
            subprocess.run(
                ["git", "init", "--quiet", repository], check=True, env=environment
            )
            marker = repository / "marker"
            marker.write_text("base\n", encoding="utf-8")
            subprocess.run(
                ["git", "-C", repository, "add", "marker"],
                check=True,
                env=environment,
            )
            subprocess.run(
                [
                    "git",
                    "-C",
                    repository,
                    "-c",
                    "user.name=test",
                    "-c",
                    "user.email=test@example.test",
                    "commit",
                    "--quiet",
                    "-m",
                    "base",
                ],
                check=True,
                env=environment,
            )
            base = subprocess.check_output(
                ["git", "-C", repository, "rev-parse", "HEAD"],
                text=True,
                env=environment,
            ).strip()
            subprocess.run(
                ["git", "-C", repository, "checkout", "--quiet", "-b", "feature"],
                check=True,
                env=environment,
            )
            marker.write_text("feature\n", encoding="utf-8")
            subprocess.run(
                [
                    "git",
                    "-C",
                    repository,
                    "-c",
                    "user.name=test",
                    "-c",
                    "user.email=test@example.test",
                    "commit",
                    "-qam",
                    "feature",
                ],
                check=True,
                env=environment,
            )
            feature = subprocess.check_output(
                ["git", "-C", repository, "rev-parse", "HEAD"],
                text=True,
                env=environment,
            ).strip()
            self.assertTrue(MODULE.is_ancestor(repository, base, feature))
            self.assertFalse(MODULE.is_ancestor(repository, feature, base))

    def test_workflow_has_one_fail_closed_promotion_route(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("promotion_candidate", workflow)
        self.assertIn("verify-develop-main-promotion-evidence:", workflow)
        self.assertIn("scripts/verify-promotion-evidence.py", workflow)
        self.assertIn("PROMOTION_RESULT", workflow)
        self.assertNotIn("MAX_REVIEW_BYTES", SCRIPT.read_text(encoding="utf-8"))
        self.assertNotIn("199999", SCRIPT.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
