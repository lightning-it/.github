from __future__ import annotations

import copy
import importlib.util
import pathlib
import subprocess
import sys
import unittest
from typing import Any
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify-main-trust-root-bootstrap.py"
SPEC = importlib.util.spec_from_file_location("main_trust_root_bootstrap", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot load trust-root bootstrap verifier")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class FakeAPI:
    def __init__(self) -> None:
        self.repository = "lightning-it/container-ee-wunder-toolbox-ubi9"
        self.number = 613
        self.base = "b" * 40
        self.head = "a" * 40
        self.workflow = "e" * 40
        self.source_sha = "d" * 40
        self.base_tree_sha = "1" * 40
        self.head_tree_sha = "2" * 40
        self.source_tree_sha = "3" * 40
        self.copilot_blob = "4" * 40
        self.paths = {
            ".github/codex/prompts/review-exact-head.md": "5" * 40,
            ".github/codex/schemas/exact-head-review.schema.json": "6" * 40,
            ".github/workflows/release-bot-exact-head-review.yml": "7" * 40,
            "scripts/materialize-exact-revision-review.py": "8" * 40,
        }
        self.pull = {
            "number": self.number,
            "state": "open",
            "draft": False,
            "title": "fix(rep60): bootstrap protected main review trust root",
            "user": {"login": "litroc", "type": "User"},
            "labels": [],
            "base": {
                "ref": "main",
                "sha": self.base,
                "repo": {"full_name": self.repository},
            },
            "head": {
                "ref": "fix/rep60-main-trust-root-successor-v8-20260826",
                "sha": self.head,
                "repo": {"full_name": self.repository},
            },
        }
        self.comparison = {
            "status": "ahead",
            "ahead_by": 1,
            "behind_by": 0,
            "total_commits": 1,
            "base_commit": {"sha": self.base},
            "merge_base_commit": {"sha": self.base},
            "commits": [{"sha": self.head}],
            "files": [
                {
                    "filename": path,
                    "status": MODULE.EXPECTED_FILES[path],
                    "sha": blob,
                }
                for path, blob in self.paths.items()
            ],
        }
        self.base_tree = {
            "truncated": False,
            "tree": [
                self._tree_entry(
                    ".github/workflows/copilot-review.yml", self.copilot_blob
                ),
                self._tree_entry(
                    ".github/codex/prompts/review-exact-head.md", "9" * 40
                ),
                self._tree_entry(
                    ".github/codex/schemas/exact-head-review.schema.json",
                    "0" * 40,
                ),
                self._tree_entry(
                    ".github/workflows/release-bot-exact-head-review.yml",
                    "c" * 40,
                ),
            ],
        }
        self.head_tree = {
            "truncated": False,
            "tree": [
                self._tree_entry(
                    ".github/workflows/copilot-review.yml", self.copilot_blob
                ),
                *[
                    self._tree_entry(path, blob)
                    for path, blob in self.paths.items()
                ],
            ],
        }
        self.source_tree = {
            "truncated": False,
            "tree": [
                self._tree_entry(path, blob)
                for path, blob in self.paths.items()
            ],
        }
        api_repository = f"https://api.github.com/repos/{self.repository}"
        self.run = {
            "id": 32942973929,
            "event": "pull_request",
            "path": ".github/workflows/copilot-review.yml",
            "name": "Copilot review gate",
            "head_branch": self.pull["head"]["ref"],
            "head_sha": self.head,
            "actor": {"login": "litroc"},
            "triggering_actor": {"login": "litroc"},
            "run_attempt": 1,
            "status": "completed",
            "conclusion": "success",
            "created_at": "2026-08-26T07:29:00Z",
            "updated_at": "2026-08-26T07:35:31Z",
            "html_url": f"https://github.com/{self.repository}/actions/runs/32942973929",
            "pull_requests": [
                {
                    "number": self.number,
                    "url": f"{api_repository}/pulls/{self.number}",
                    "base": {
                        "ref": "main",
                        "sha": self.base,
                        "repo": {"url": api_repository},
                    },
                    "head": {
                        "ref": self.pull["head"]["ref"],
                        "sha": self.head,
                        "repo": {"url": api_repository},
                    },
                }
            ],
        }
        self.jobs = [
            {
                "name": "Request Copilot review for current revision",
                "run_attempt": 1,
                "status": "completed",
                "conclusion": "success",
            },
            {
                "name": "Successful Copilot review",
                "run_attempt": 1,
                "status": "completed",
                "conclusion": "success",
            },
        ]
        self.review = {
            "id": 5027807975,
            "user": {
                "login": "copilot-pull-request-reviewer[bot]",
                "type": "Bot",
            },
            "commit_id": self.head,
            "state": "COMMENTED",
            "submitted_at": "2026-08-26T07:31:18Z",
            "body": "Copilot reviewed 4 out of 4 changed files.",
        }
        self.review_comments = [
            {"body": "A documented false positive with deterministic proof."}
        ]
        self.timeline = [
            {
                "event": "ready_for_review",
                "created_at": "2026-08-26T07:28:57Z",
                "actor": {"login": "litroc"},
            }
        ]
        self.graphql_payload = {
            "data": {
                "repository": {
                    "pullRequest": {
                        "headRefOid": self.head,
                        "reviewThreads": {
                            "pageInfo": {
                                "hasNextPage": False,
                                "endCursor": None,
                            },
                            "nodes": [
                                {
                                    "isResolved": True,
                                    "comments": {
                                        "pageInfo": {"hasNextPage": False},
                                        "nodes": [
                                            {
                                                "body": "Finding resolved with proof.",
                                                "author": {
                                                    "login": "copilot-pull-request-reviewer"
                                                },
                                                "pullRequestReview": {
                                                    "commit": {"oid": self.head}
                                                },
                                            }
                                        ],
                                    },
                                }
                            ],
                        },
                    }
                }
            }
        }

    @staticmethod
    def _tree_entry(path: str, sha: str) -> dict[str, Any]:
        return {"path": path, "mode": "100644", "type": "blob", "sha": sha}

    def target(self, endpoint: str) -> Any:
        mapping = {
            f"repos/{self.repository}": {
                "full_name": self.repository,
                "owner": {"login": "lightning-it"},
                "archived": False,
                "disabled": False,
                "default_branch": "develop",
            },
            f"repos/{self.repository}/pulls/{self.number}": self.pull,
            f"repos/{self.repository}/compare/{self.base}...{self.head}": self.comparison,
            f"repos/{self.repository}/branches/main": {
                "name": "main",
                "protected": True,
                "commit": {"sha": self.base},
            },
            f"repos/{self.repository}/branches/develop": {
                "name": "develop",
                "protected": True,
                "commit": {"sha": "f" * 40},
            },
            f"repos/{self.repository}/commits/{self.head}": {
                "sha": self.head,
                "parents": [{"sha": self.base}],
                "author": {"login": "litroc"},
                "committer": {"login": "litroc"},
                "commit": {"tree": {"sha": self.head_tree_sha}},
            },
            f"repos/{self.repository}/commits/{self.base}": {
                "sha": self.base,
                "commit": {"tree": {"sha": self.base_tree_sha}},
            },
            f"repos/{self.repository}/git/trees/{self.base_tree_sha}?recursive=1": self.base_tree,
            f"repos/{self.repository}/git/trees/{self.head_tree_sha}?recursive=1": self.head_tree,
        }
        if endpoint not in mapping:
            raise AssertionError(f"unexpected target endpoint: {endpoint}")
        return copy.deepcopy(mapping[endpoint])

    def source(self, endpoint: str) -> Any:
        mapping = {
            f"repos/{MODULE.SOURCE_REPOSITORY}": {
                "full_name": MODULE.SOURCE_REPOSITORY
            },
            f"repos/{MODULE.SOURCE_REPOSITORY}/branches/{MODULE.SOURCE_BRANCH}": {
                "name": MODULE.SOURCE_BRANCH,
                "protected": True,
                "commit": {"sha": self.source_sha},
            },
            f"repos/{MODULE.SOURCE_REPOSITORY}/commits/{self.source_sha}": {
                "sha": self.source_sha,
                "commit": {"tree": {"sha": self.source_tree_sha}},
            },
            f"repos/{MODULE.SOURCE_REPOSITORY}/git/trees/{self.source_tree_sha}?recursive=1": self.source_tree,
        }
        if endpoint not in mapping:
            raise AssertionError(f"unexpected source endpoint: {endpoint}")
        return copy.deepcopy(mapping[endpoint])

    def target_pages(self, endpoint: str) -> list[Any]:
        mapping = {
            f"repos/{self.repository}/commits/{self.head}/check-runs?check_name=Protected%20Exact-Revision%20Codex%20result&filter=all&per_page=100": [
                {"check_runs": []}
            ],
            f"repos/{self.repository}/issues/{self.number}/timeline?per_page=100": [
                self.timeline
            ],
            f"repos/{self.repository}/actions/runs?event=pull_request&head_sha={self.head}&per_page=100": [
                {"workflow_runs": [self.run]}
            ],
            f"repos/{self.repository}/actions/runs/{self.run['id']}/jobs?filter=all&per_page=100": [
                {"jobs": self.jobs}
            ],
            f"repos/{self.repository}/pulls/{self.number}/reviews?per_page=100": [
                [self.review]
            ],
            f"repos/{self.repository}/pulls/{self.number}/reviews/{self.review['id']}/comments?per_page=100": [
                self.review_comments
            ],
        }
        if endpoint not in mapping:
            raise AssertionError(f"unexpected paginated endpoint: {endpoint}")
        return copy.deepcopy(mapping[endpoint])

    def target_graphql(
        self, query: str, variables: dict[str, str | int]
    ) -> Any:
        self.last_graphql_query = query
        self.last_graphql_variables = variables
        return copy.deepcopy(self.graphql_payload)


class MainTrustRootBootstrapTests(unittest.TestCase):
    def args(self, api: FakeAPI) -> Any:
        return MODULE.parse_args(
            [
                "--repository",
                api.repository,
                "--pull-request",
                str(api.number),
                "--expected-base",
                api.base,
                "--expected-head",
                api.head,
                "--workflow-sha",
                api.workflow,
            ]
        )

    def test_exact_protected_bootstrap_emits_bound_evidence(self) -> None:
        api = FakeAPI()
        evidence = MODULE.verify(self.args(api), api)
        self.assertEqual("rep60-main-trust-root-bootstrap/v1", evidence["schema"])
        self.assertEqual(api.base, evidence["base_sha"])
        self.assertEqual(api.head, evidence["head_sha"])
        self.assertEqual(api.source_sha, evidence["source_sha"])
        self.assertEqual(api.run["id"], evidence["producer_run_id"])
        self.assertEqual(api.review["id"], evidence["review_id"])
        self.assertEqual(api.paths, evidence["source_blobs"])
        self.assertEqual(1, evidence["threads_resolved"])

    def test_unrelated_pr_is_not_applicable(self) -> None:
        api = FakeAPI()
        api.comparison["files"] = [
            {"filename": "README.md", "status": "modified", "sha": "f" * 40}
        ]
        with self.assertRaises(MODULE.NotApplicable):
            MODULE.verify(self.args(api), api)

    def test_partial_or_expanded_bootstrap_fails_closed(self) -> None:
        for files in (
            FakeAPI().comparison["files"][:-1],
            [
                *FakeAPI().comparison["files"],
                {
                    "filename": "README.md",
                    "status": "modified",
                    "sha": "f" * 40,
                },
            ],
        ):
            api = FakeAPI()
            api.comparison["files"] = files
            with self.subTest(files=files), self.assertRaises(
                MODULE.VerificationError
            ):
                MODULE.verify(self.args(api), api)

    def test_candidate_cannot_control_review_workflow(self) -> None:
        api = FakeAPI()
        next(
            entry
            for entry in api.head_tree["tree"]
            if entry["path"] == ".github/workflows/copilot-review.yml"
        )["sha"] = "f" * 40
        with self.assertRaisesRegex(MODULE.VerificationError, "controls"):
            MODULE.verify(self.args(api), api)

    def test_source_blob_or_mode_drift_fails_closed(self) -> None:
        for mutation in ("blob", "mode"):
            api = FakeAPI()
            entry = next(
                item
                for item in api.source_tree["tree"]
                if item["path"]
                == ".github/workflows/release-bot-exact-head-review.yml"
            )
            if mutation == "blob":
                entry["sha"] = "f" * 40
            else:
                entry["mode"] = "100755"
            with self.subTest(mutation=mutation), self.assertRaises(
                MODULE.VerificationError
            ):
                MODULE.verify(self.args(api), api)

    def test_ai_identity_count_and_findings_fail_closed(self) -> None:
        mutations = ("codex", "duplicate_review", "suppressed", "unresolved")
        for mutation in mutations:
            api = FakeAPI()
            if mutation == "codex":
                original = api.target_pages

                def target_pages(endpoint: str) -> list[Any]:
                    if "Protected%20Exact-Revision" in endpoint:
                        return [{"check_runs": [{"id": 1}]}]
                    return original(endpoint)

                api.target_pages = target_pages  # type: ignore[method-assign]
            elif mutation == "duplicate_review":
                original = api.target_pages

                def target_pages(endpoint: str) -> list[Any]:
                    if endpoint.endswith("/reviews?per_page=100"):
                        duplicate = copy.deepcopy(api.review)
                        duplicate["id"] += 1
                        return [[api.review, duplicate]]
                    return original(endpoint)

                api.target_pages = target_pages  # type: ignore[method-assign]
            elif mutation == "suppressed":
                api.review["body"] = "Suppressed comments (1)"
            else:
                api.graphql_payload["data"]["repository"]["pullRequest"][
                    "reviewThreads"
                ]["nodes"][0]["isResolved"] = False
            with self.subTest(mutation=mutation), self.assertRaises(
                MODULE.VerificationError
            ):
                MODULE.verify(self.args(api), api)

    def test_ready_and_request_are_exactly_once(self) -> None:
        for mutation in ("ready", "request"):
            api = FakeAPI()
            if mutation == "ready":
                api.timeline.append(copy.deepcopy(api.timeline[0]))
            else:
                api.jobs.append(copy.deepcopy(api.jobs[0]))
            with self.subTest(mutation=mutation), self.assertRaises(
                MODULE.VerificationError
            ):
                MODULE.verify(self.args(api), api)

    def test_github_api_timeout_fails_closed(self) -> None:
        with mock.patch.object(
            MODULE.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired(cmd=["gh", "api"], timeout=30),
        ):
            with self.assertRaisesRegex(MODULE.VerificationError, "timed out"):
                MODULE.GitHubAPI._invoke(["repos/lightning-it/example"], "token")

    def test_review_thread_cursor_repetition_fails_closed(self) -> None:
        api = FakeAPI()
        page_info = api.graphql_payload["data"]["repository"]["pullRequest"][
            "reviewThreads"
        ]["pageInfo"]
        page_info["hasNextPage"] = True
        page_info["endCursor"] = "repeated"
        with self.assertRaisesRegex(MODULE.VerificationError, "repeats"):
            MODULE.verify(self.args(api), api)

    def test_review_thread_page_limit_fails_closed(self) -> None:
        api = FakeAPI()
        call_count = 0

        def target_graphql(
            query: str, variables: dict[str, str | int]
        ) -> Any:
            nonlocal call_count
            call_count += 1
            payload = copy.deepcopy(api.graphql_payload)
            page_info = payload["data"]["repository"]["pullRequest"][
                "reviewThreads"
            ]["pageInfo"]
            page_info["hasNextPage"] = True
            page_info["endCursor"] = f"cursor-{call_count}"
            return payload

        api.target_graphql = target_graphql  # type: ignore[method-assign]
        with self.assertRaisesRegex(MODULE.VerificationError, "page limit"):
            MODULE.verify(self.args(api), api)
        self.assertEqual(MODULE.MAX_REVIEW_THREAD_PAGES, call_count)


if __name__ == "__main__":
    unittest.main()
