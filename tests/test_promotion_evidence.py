from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from unittest import mock
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
        "details_url": "https://github.com/lightning-it/example/runs/99",
        "app": {"id": 15368, "slug": "github-actions"},
        "output": {"summary": summary},
    }


def ingress_pull(
    *, login: str = "litroc", user_id: int = 1, user_type: str = "User"
) -> dict[str, object]:
    return {
        "number": 17,
        "title": "fix: exact ingress",
        "user": {"login": login, "id": user_id, "type": user_type},
        "base": {"ref": "develop"},
        "head": {
            "ref": "fix/exact-ingress",
            "sha": HEAD,
            "repo": {"full_name": "lightning-it/example"},
        },
    }


def producer_run(*, login: str = "litroc", release: bool = False) -> dict[str, object]:
    if release:
        return {
            "id": 88,
            "html_url": "https://github.com/lightning-it/example/actions/runs/88",
            "actor": {"login": login},
            "triggering_actor": {"login": login},
            "run_attempt": 1,
            "event": "workflow_dispatch",
            "path": ".github/workflows/release-bot-exact-head-review.yml",
            "head_branch": "develop",
            "head_sha": BASE,
            "display_title": f"Exact-Revision Codex PR #17 {BASE}..{HEAD}",
        }
    return {
        "id": 88,
        "html_url": "https://github.com/lightning-it/example/actions/runs/88",
        "actor": {"login": login},
        "triggering_actor": {"login": login},
        "run_attempt": 1,
        "event": "pull_request_target",
        "path": ".github/workflows/copilot-review.yml",
        "name": "Current revision review gate",
        "head_branch": "fix/exact-ingress",
        "head_sha": HEAD,
        "status": "completed",
        "conclusion": "success",
    }


def v6_summary(kind: str = "copilot") -> str:
    paths = {
        "copilot": "applicable Copilot or governed automation exemption",
        "managed-sync": "deterministic provenance-bound managed distribution exemption",
        "ancestry-backmerge": "deterministic evidence-bound ancestry exemption",
        "renovate": "deterministic policy-bound Renovate exemption",
    }
    evidence: dict[str, object] = {
        "schema": 4,
        "base_sha": BASE,
        "head_sha": HEAD,
        "pull_request_number": 17,
        "producer_run_id": 88,
        "run_url": "https://github.com/lightning-it/example/actions/runs/88",
        "review_path": paths[kind],
        "controller_sha": "5" * 40,
    }
    if kind == "renovate":
        evidence.update(
            {
                "controller_ref": "develop",
                "head_repository": "lightning-it/example",
                "pull_request_labels_sha256": "7" * 64,
                "pull_request_last_edited_at": None,
                "review_id": None,
            }
        )
    return json.dumps(evidence)


def evidence_api(run: dict[str, object]):
    def dispatch(arguments: list[str]) -> dict[str, object]:
        endpoint = arguments[-1]
        if endpoint == "repos/lightning-it/example":
            return {"default_branch": "develop"}
        if endpoint == "repos/lightning-it/example/branches/develop":
            return {"commit": {"sha": "6" * 40}}
        if endpoint == f"repos/lightning-it/example/compare/{'5' * 40}...{'6' * 40}":
            return {
                "status": "ahead",
                "behind_by": 0,
                "merge_base_commit": {"sha": "5" * 40},
            }
        if endpoint == "repos/lightning-it/example/actions/runs/88":
            return run
        raise AssertionError(endpoint)

    return dispatch


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
            "head": {
                "sha": HEAD,
                "repo": {"full_name": "lightning-it/example"},
            },
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
        pages = [{"check_runs": [check_run(external_id, v6_summary())]}]
        with mock.patch.object(
            MODULE, "gh_json", side_effect=evidence_api(producer_run())
        ):
            evidence = MODULE.bound_review_check(
                pages,
                repository="lightning-it/example",
                pull=ingress_pull(),
                pull_number=17,
                base_sha=BASE,
                head_sha=HEAD,
            )
        self.assertEqual(evidence["producer_run_id"], 88)
        with self.assertRaises(MODULE.EvidenceError):
            MODULE.bound_review_check(
                pages,
                repository="lightning-it/example",
                pull=ingress_pull(),
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
                "run_url": "https://github.com/lightning-it/example/actions/runs/88",
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
        release_pull = ingress_pull(
            login="lightning-it-release-automation[bot]",
            user_id=307565056,
            user_type="Bot",
        )
        with mock.patch.object(
            MODULE,
            "gh_json",
            return_value=producer_run(
                login="lightning-it-release-automation[bot]", release=True
            ),
        ):
            self.assertEqual(
                MODULE.bound_review_check(
                    pages,
                    repository="lightning-it/example",
                    pull=release_pull,
                    pull_number=17,
                    base_sha=BASE,
                    head_sha=HEAD,
                )["evidence_kind"],
                "release-app",
            )

    def test_review_kind_and_producer_identity_are_bound_to_pull_author(self) -> None:
        managed = (
            f"mlx90-current-revision:managed-sync:v6:17:88:{BASE}:{HEAD}"
        )
        with self.assertRaises(MODULE.EvidenceError):
            MODULE.bound_review_check(
                [{"check_runs": [check_run(managed, v6_summary("managed-sync"))]}],
                repository="lightning-it/example",
                pull=ingress_pull(),
                pull_number=17,
                base_sha=BASE,
                head_sha=HEAD,
            )

        copilot = f"mlx90-current-revision:copilot:v6:17:88:{BASE}:{HEAD}"
        wrong_actor = producer_run(login="attacker")
        with mock.patch.object(
            MODULE, "gh_json", side_effect=evidence_api(wrong_actor)
        ):
            with self.assertRaisesRegex(
                MODULE.EvidenceError, "producer-run-actor-login"
            ):
                MODULE.bound_review_check(
                    [{"check_runs": [check_run(copilot, v6_summary())]}],
                    repository="lightning-it/example",
                    pull=ingress_pull(),
                    pull_number=17,
                    base_sha=BASE,
                    head_sha=HEAD,
                )

    def test_v6_rejects_schema_drift_and_failed_producer_run(self) -> None:
        external_id = f"mlx90-current-revision:copilot:v6:17:88:{BASE}:{HEAD}"
        schema_drift = json.loads(v6_summary())
        schema_drift["unexpected"] = True
        with self.assertRaisesRegex(MODULE.EvidenceError, "review-summary-schema"):
            MODULE.bound_review_check(
                [{"check_runs": [check_run(external_id, json.dumps(schema_drift))]}],
                repository="lightning-it/example",
                pull=ingress_pull(),
                pull_number=17,
                base_sha=BASE,
                head_sha=HEAD,
            )

        failed = producer_run()
        failed["conclusion"] = "failure"
        with mock.patch.object(
            MODULE, "gh_json", side_effect=evidence_api(failed)
        ):
            with self.assertRaisesRegex(
                MODULE.EvidenceError, "producer-run-conclusion"
            ):
                MODULE.bound_review_check(
                    [{"check_runs": [check_run(external_id, v6_summary())]}],
                    repository="lightning-it/example",
                    pull=ingress_pull(),
                    pull_number=17,
                    base_sha=BASE,
                    head_sha=HEAD,
                )

    def test_ingress_pull_must_have_same_repository_head(self) -> None:
        candidate = {
            "number": 17,
            "state": "closed",
            "merged_at": "2026-09-27T00:00:00Z",
            "merge_commit_sha": MERGE,
            "base": {
                "ref": "develop",
                "repo": {"full_name": "lightning-it/example"},
            },
            "head": {
                "sha": HEAD,
                "repo": {"full_name": "fork/example"},
            },
        }
        with self.assertRaises(MODULE.EvidenceError):
            MODULE.select_ingress_pull(
                [candidate],
                repository="lightning-it/example",
                merge_sha=MERGE,
                head_sha=HEAD,
            )

    def test_private_runtime_and_output_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory)
            old = os.environ.get("RUNNER_TEMP")
            try:
                os.environ["RUNNER_TEMP"] = str(runtime)
                runtime.chmod(0o777)
                with self.assertRaisesRegex(MODULE.EvidenceError, "runner-temp-mode"):
                    MODULE.private_runtime_directory()
                runtime.chmod(0o700)
                output = runtime / "evidence.json"
                MODULE.write_output(output, {"accepted": True})
                self.assertEqual(output.stat().st_mode & 0o777, 0o600)
                with self.assertRaises(FileExistsError):
                    MODULE.write_output(output, {"accepted": False})
            finally:
                if old is None:
                    os.environ.pop("RUNNER_TEMP", None)
                else:
                    os.environ["RUNNER_TEMP"] = old

    def test_duplicate_checks_and_unresolved_threads_fail_closed(self) -> None:
        external_id = f"mlx90-current-revision:copilot:v6:17:88:{BASE}:{HEAD}"
        run = check_run(external_id, v6_summary())
        duplicate = dict(run)
        duplicate["id"] = 100
        with self.assertRaises(MODULE.EvidenceError):
            MODULE.bound_review_check(
                [{"check_runs": [run, duplicate]}],
                repository="lightning-it/example",
                pull=ingress_pull(),
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
        promotion_job = workflow.split(
            "  verify-develop-main-promotion-evidence:\n", 1
        )[1].split("\n  verify-protected-current-revision-evidence:\n", 1)[0]
        for binding in (
            "umask 077",
            'test ! -L "${RUNNER_TEMP}"',
            'stat -c %u -- "${RUNNER_TEMP}"',
            "8#${runner_temp_mode} & 0022",
        ):
            self.assertIn(binding, promotion_job)
        self.assertIn("scripts/verify-promotion-evidence.py", workflow)
        self.assertIn("PROMOTION_RESULT", workflow)
        self.assertNotIn("MAX_REVIEW_BYTES", SCRIPT.read_text(encoding="utf-8"))
        self.assertNotIn("199999", SCRIPT.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
