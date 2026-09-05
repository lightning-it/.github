from __future__ import annotations

import contextlib
import copy
import hashlib
import importlib.util
import io
import json
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
        self.source_head_sha = self.source_sha
        self.base_tree_sha = "1" * 40
        self.head_tree_sha = "2" * 40
        self.source_tree_sha = "3" * 40
        self.copilot_blob = "4" * 40
        self.controller_sha = "f" * 40
        self.develop_sha = self.controller_sha
        self.current_revision_checks: list[dict[str, Any]] = []
        self.target_endpoints: list[str] = []
        self.source_endpoints: list[str] = []
        self.paths = {
            ".github/codex/prompts/review-exact-head.md": "5" * 40,
            ".github/codex/schemas/exact-head-review.schema.json": "6" * 40,
            ".github/workflows/copilot-review.yml": "b" * 40,
            ".github/workflows/release-bot-exact-head-review.yml": "7" * 40,
            "scripts/materialize-exact-revision-review.py": "8" * 40,
            ".github/workflows/current-revision-rerun.yml": "a" * 40,
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
                    "status": (
                        "added"
                        if path
                        in {
                            ".github/workflows/current-revision-rerun.yml",
                            "scripts/materialize-exact-revision-review.py",
                        }
                        else "modified"
                    ),
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
            "event": "pull_request_target",
            "path": ".github/workflows/copilot-review.yml",
            "name": "Current revision review gate",
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
                "name": "Verify current revision policy",
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
            "body": "Copilot reviewed 5 out of 5 changed files.",
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

    @staticmethod
    def _tree_page(
        flat_tree: dict[str, Any], root_sha: str, requested_sha: str
    ) -> dict[str, Any] | None:
        if flat_tree.get("truncated") is not False:
            if requested_sha == root_sha:
                return {"truncated": True, "tree": []}
            return None
        directories = {""}
        for entry in flat_tree["tree"]:
            parts = entry["path"].split("/")
            directories.update(
                "/".join(parts[:index])
                for index in range(1, len(parts))
            )
        directory_shas = {
            directory: (
                root_sha
                if not directory
                else hashlib.sha1(
                    f"{root_sha}:{directory}".encode("utf-8"),
                    usedforsecurity=False,
                ).hexdigest()
            )
            for directory in directories
        }
        prefixes = {
            tree_sha: directory
            for directory, tree_sha in directory_shas.items()
        }
        if requested_sha not in prefixes:
            return None
        prefix = prefixes[requested_sha]
        prefix_with_separator = f"{prefix}/" if prefix else ""
        entries: dict[str, dict[str, Any]] = {}
        for raw_entry in flat_tree["tree"]:
            path = raw_entry["path"]
            if not path.startswith(prefix_with_separator):
                continue
            relative_path = path[len(prefix_with_separator) :]
            component, separator, _remainder = relative_path.partition("/")
            if separator:
                directory = f"{prefix_with_separator}{component}"
                entries[component] = {
                    "path": component,
                    "mode": "040000",
                    "type": "tree",
                    "sha": directory_shas[directory],
                }
            else:
                entry = copy.deepcopy(raw_entry)
                entry["path"] = component
                entries[component] = entry
        return {
            "truncated": False,
            "tree": [entries[key] for key in sorted(entries)],
        }

    def target(self, endpoint: str) -> Any:
        self.target_endpoints.append(endpoint)
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
                "commit": {"sha": self.develop_sha},
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
            f"repos/{self.repository}/actions/runs/{self.run['id']}": self.run,
        }
        if endpoint in mapping:
            return copy.deepcopy(mapping[endpoint])
        tree_prefix = f"repos/{self.repository}/git/trees/"
        if endpoint.startswith(tree_prefix):
            requested_sha = endpoint.removeprefix(tree_prefix)
            for flat_tree, root_sha in (
                (self.base_tree, self.base_tree_sha),
                (self.head_tree, self.head_tree_sha),
            ):
                page = self._tree_page(flat_tree, root_sha, requested_sha)
                if page is not None:
                    return page
        if endpoint == (
            f"repos/{self.repository}/compare/"
            f"{self.controller_sha}...{self.develop_sha}"
        ):
            return {
                "status": (
                    "identical"
                    if self.controller_sha == self.develop_sha
                    else "ahead"
                ),
                "ahead_by": 0 if self.controller_sha == self.develop_sha else 1,
                "behind_by": 0,
                "merge_base_commit": {"sha": self.controller_sha},
            }
        raise AssertionError(f"unexpected target endpoint: {endpoint}")

    def source(self, endpoint: str) -> Any:
        self.source_endpoints.append(endpoint)
        mapping = {
            f"repos/{MODULE.SOURCE_REPOSITORY}": {
                "full_name": MODULE.SOURCE_REPOSITORY
            },
            f"repos/{MODULE.SOURCE_REPOSITORY}/branches/{MODULE.SOURCE_BRANCH}": {
                "name": MODULE.SOURCE_BRANCH,
                "protected": True,
                "commit": {"sha": self.source_head_sha},
            },
            f"repos/{MODULE.SOURCE_REPOSITORY}/compare/"
            f"{MODULE.CONTROLLER_SEED_SOURCE}...{self.source_head_sha}": {
                "status": (
                    "identical"
                    if self.source_head_sha == MODULE.CONTROLLER_SEED_SOURCE
                    else "ahead"
                ),
                "ahead_by": (
                    0
                    if self.source_head_sha == MODULE.CONTROLLER_SEED_SOURCE
                    else 1
                ),
                "behind_by": 0,
                "base_commit": {"sha": MODULE.CONTROLLER_SEED_SOURCE},
                "merge_base_commit": {"sha": MODULE.CONTROLLER_SEED_SOURCE},
            },
            f"repos/{MODULE.SOURCE_REPOSITORY}/commits/{self.source_sha}": {
                "sha": self.source_sha,
                "commit": {"tree": {"sha": self.source_tree_sha}},
            },
        }
        if endpoint in mapping:
            return copy.deepcopy(mapping[endpoint])
        tree_prefix = f"repos/{MODULE.SOURCE_REPOSITORY}/git/trees/"
        if endpoint.startswith(tree_prefix):
            requested_sha = endpoint.removeprefix(tree_prefix)
            page = self._tree_page(
                self.source_tree, self.source_tree_sha, requested_sha
            )
            if page is not None:
                return page
        raise AssertionError(f"unexpected source endpoint: {endpoint}")

    def target_pages(self, endpoint: str) -> list[Any]:
        mapping = {
            f"repos/{self.repository}/commits/{self.head}/check-runs?check_name=Protected%20Exact-Revision%20Codex%20result&filter=all&per_page=100": [
                {"check_runs": []}
            ],
            f"repos/{self.repository}/commits/{self.head}/check-runs?check_name=Current%20revision%20review&filter=all&per_page=100": [
                {"check_runs": self.current_revision_checks}
            ],
            f"repos/{self.repository}/issues/{self.number}/timeline?per_page=100": [
                self.timeline
            ],
            f"repos/{self.repository}/actions/runs?event=pull_request_target&head_sha={self.head}&per_page=100": [
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


def make_controller_seed_api() -> FakeAPI:
    api = FakeAPI()
    api.repository = MODULE.CONTROLLER_SEED_REPOSITORY
    api.number = MODULE.CONTROLLER_SEED_PULL_REQUEST
    api.base = MODULE.CONTROLLER_SEED_BASE
    api.head = MODULE.CONTROLLER_SEED_HEAD
    api.source_sha = MODULE.CONTROLLER_SEED_SOURCE
    api.source_head_sha = api.source_sha
    api.head_tree_sha = MODULE.CONTROLLER_SEED_TREE
    api.pull = {
        "number": api.number,
        "state": "open",
        "draft": False,
        "title": MODULE.CONTROLLER_SEED_TITLE,
        "user": {"login": "litroc", "type": "User"},
        "labels": [],
        "base": {
            "ref": "main",
            "sha": api.base,
            "repo": {"full_name": api.repository},
        },
        "head": {
            "ref": MODULE.CONTROLLER_SEED_HEAD_REF,
            "sha": api.head,
            "repo": {"full_name": api.repository},
        },
    }
    api.comparison = {
        "status": "ahead",
        "ahead_by": 1,
        "behind_by": 0,
        "total_commits": 1,
        "base_commit": {"sha": api.base},
        "merge_base_commit": {"sha": api.base},
        "commits": [{"sha": api.head}],
        "files": [
            {
                "filename": MODULE.CONTROLLER_SEED_FILE,
                "status": "added",
                "sha": MODULE.CONTROLLER_SEED_BLOB,
            }
        ],
    }
    api.base_tree = {"truncated": False, "tree": []}
    api.head_tree = {
        "truncated": False,
        "tree": [
            api._tree_entry(
                MODULE.CONTROLLER_SEED_FILE,
                MODULE.CONTROLLER_SEED_BLOB,
            )
        ],
    }
    api.source_tree = copy.deepcopy(api.head_tree)
    api.timeline = [
        {
            "id": MODULE.CONTROLLER_SEED_REQUEST_EVENT_ID,
            "event": "review_requested",
            "created_at": MODULE.CONTROLLER_SEED_REQUESTED_AT,
            "actor": {"login": "litroc"},
            "requested_reviewer": {"login": "Copilot"},
        }
    ]
    api.review = {
        "id": MODULE.CONTROLLER_SEED_REVIEW_ID,
        "node_id": MODULE.CONTROLLER_SEED_REVIEW_NODE_ID,
        "user": {
            "login": "copilot-pull-request-reviewer[bot]",
            "type": "Bot",
        },
        "commit_id": api.head,
        "state": "COMMENTED",
        "submitted_at": MODULE.CONTROLLER_SEED_REVIEW_SUBMITTED_AT,
        "body": "Copilot reviewed the exact protected controller seed.",
    }
    api.review_comments = []
    api.controller_sha = "8" * 40
    api.develop_sha = api.controller_sha
    api.run = {
        "id": MODULE.CONTROLLER_SEED_CURRENT_REVISION_PRODUCER_RUN_ID,
        "event": "pull_request_target",
        "path": ".github/workflows/copilot-review.yml",
        "name": "Current revision review gate",
        "head_branch": MODULE.CONTROLLER_SEED_HEAD_REF,
        "head_sha": api.head,
        "actor": {"login": "litroc"},
        "triggering_actor": {"login": "litroc"},
        "run_attempt": 1,
        "status": "completed",
        "conclusion": "success",
        "display_title": MODULE.CONTROLLER_SEED_TITLE,
        "created_at": "2026-09-01T11:03:21Z",
        "updated_at": "2026-09-01T11:03:44Z",
        "html_url": (
            "https://github.com/lightning-it/identity-access-lit/"
            "actions/runs/33500514644"
        ),
        "workflow_id": 323691360,
        "workflow_url": (
            "https://api.github.com/repos/lightning-it/identity-access-lit/"
            "actions/workflows/323691360"
        ),
        "repository": {"full_name": api.repository},
        "head_repository": {"full_name": api.repository},
        "pull_requests": [
            {
                "number": api.number,
                "url": (
                    "https://api.github.com/repos/"
                    f"{api.repository}/pulls/{api.number}"
                ),
                "base": {
                    "ref": "main",
                    "sha": api.base,
                    "repo": {
                        "url": f"https://api.github.com/repos/{api.repository}"
                    },
                },
                "head": {
                    "ref": MODULE.CONTROLLER_SEED_HEAD_REF,
                    "sha": api.head,
                    "repo": {
                        "url": f"https://api.github.com/repos/{api.repository}"
                    },
                },
            }
        ],
    }
    def successful_step(name: str) -> dict[str, str]:
        return {
            "name": name,
            "status": "completed",
            "conclusion": "success",
        }
    api.jobs = [
        {
            "name": "Classify protected main trust-root handoff",
            "run_id": api.run["id"],
            "run_attempt": 1,
            "head_sha": api.head,
            "status": "completed",
            "conclusion": "success",
            "steps": [
                successful_step(
                    "Verify protected Required-Workflow handoff provenance"
                )
            ],
        },
        {
            "name": "Verify current revision policy",
            "run_id": api.run["id"],
            "run_attempt": 1,
            "head_sha": api.head,
            "status": "completed",
            "conclusion": "success",
            "steps": [
                successful_step(
                    "Verify current Copilot review and resolved findings"
                ),
                successful_step("Publish bound neutral result"),
            ],
        },
        {
            "name": "Request Copilot review for current revision",
            "run_id": api.run["id"],
            "run_attempt": 1,
            "head_sha": api.head,
            "status": "completed",
            "conclusion": "skipped",
            "steps": [],
        },
        {
            "name": (
                "Request protected verifier re-evaluation / "
                "Re-run the one protected verifier attempt"
            ),
            "run_id": api.run["id"],
            "run_attempt": 1,
            "head_sha": api.head,
            "status": "completed",
            "conclusion": "skipped",
            "steps": [],
        },
    ]
    summary = {
        "schema": 4,
        "base_sha": api.base,
        "head_sha": api.head,
        "head_repository": api.repository,
        "controller_sha": api.controller_sha,
        "controller_ref": "develop",
        "pull_request_number": api.number,
        "producer_run_id": api.run["id"],
        "pull_request_last_edited_at": None,
        "pull_request_labels_sha256": MODULE.CONTROLLER_SEED_EMPTY_LABELS_SHA256,
        "review_id": MODULE.CONTROLLER_SEED_REVIEW_NODE_ID,
        "review_path": "applicable Copilot or governed automation exemption",
        "run_url": api.run["html_url"],
    }
    check_id = MODULE.CONTROLLER_SEED_CURRENT_REVISION_CHECK_ID
    api.current_revision_checks = [
        {
            "id": check_id,
            "name": "Current revision review",
            "head_sha": api.head,
            "status": "completed",
            "conclusion": "success",
            "external_id": (
                "mlx90-current-revision:copilot:v6:"
                f"{api.number}:{api.run['id']}:{api.base}:{api.head}"
            ),
            "details_url": (
                f"https://github.com/{api.repository}/runs/{check_id}"
            ),
            "app": {"id": 15368, "slug": "github-actions"},
            "output": {
                "title": "Current revision review passed",
                "summary": json.dumps(summary, separators=(",", ":")),
            },
        }
    ]
    api.graphql_payload = {
        "data": {
            "repository": {
                "pullRequest": {
                    "headRefOid": api.head,
                    "reviewThreads": {
                        "pageInfo": {
                            "hasNextPage": False,
                            "endCursor": None,
                        },
                        "nodes": [],
                    },
                }
            }
        }
    }
    return api


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

    def controller_seed_args(self, api: FakeAPI) -> Any:
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
                "--controller-seed",
            ]
        )

    def test_immutable_controller_seed_emits_bound_evidence(self) -> None:
        api = make_controller_seed_api()
        evidence = MODULE.verify_controller_seed(
            self.controller_seed_args(api), api
        )

        self.assertEqual("rep60-main-controller-seed/v2", evidence["schema"])
        self.assertEqual(MODULE.CONTROLLER_SEED_REPOSITORY, evidence["repository"])
        self.assertEqual(MODULE.CONTROLLER_SEED_BASE, evidence["base_sha"])
        self.assertEqual(MODULE.CONTROLLER_SEED_HEAD, evidence["head_sha"])
        self.assertEqual(
            MODULE.CONTROLLER_SEED_BLOB,
            evidence["controller_blob_sha"],
        )
        self.assertEqual(MODULE.CONTROLLER_SEED_REVIEW_ID, evidence["review_id"])
        self.assertEqual(
            MODULE.CONTROLLER_SEED_CURRENT_REVISION_CHECK_ID,
            evidence["current_revision_check_id"],
        )
        self.assertEqual(
            MODULE.CONTROLLER_SEED_CURRENT_REVISION_PRODUCER_RUN_ID,
            evidence["current_revision_producer_run_id"],
        )
        self.assertEqual(0, evidence["threads_resolved"])

    def test_controller_seed_immutable_bindings_fail_closed(self) -> None:
        mutations = (
            "repository",
            "path",
            "blob",
            "review",
            "review_node",
            "thread",
            "check",
            "check_id",
            "missing_check",
            "summary",
            "producer_id",
            "producer",
            "producer_job",
        )
        for mutation in mutations:
            api = make_controller_seed_api()
            if mutation == "repository":
                api.repository = "lightning-it/another-repository"
            elif mutation == "path":
                api.comparison["files"].append(
                    {
                        "filename": "README.md",
                        "status": "modified",
                        "sha": "f" * 40,
                    }
                )
            elif mutation == "blob":
                api.head_tree["tree"][0]["sha"] = "f" * 40
            elif mutation == "review":
                api.review["id"] += 1
            elif mutation == "review_node":
                api.review["node_id"] = "forged"
            elif mutation == "thread":
                api.graphql_payload["data"]["repository"]["pullRequest"][
                    "reviewThreads"
                ]["nodes"] = [
                    {
                        "isResolved": False,
                        "comments": {
                            "pageInfo": {"hasNextPage": False},
                            "nodes": [],
                        },
                    }
                ]
            elif mutation == "check":
                api.current_revision_checks[0]["external_id"] = "forged"
            elif mutation == "check_id":
                api.current_revision_checks[0]["id"] += 1
            elif mutation == "missing_check":
                api.current_revision_checks = []
            elif mutation == "summary":
                api.current_revision_checks[0]["output"]["summary"] = "{}"
            elif mutation == "producer_id":
                api.current_revision_checks[0]["external_id"] = (
                    "mlx90-current-revision:copilot:v6:"
                    f"{api.number}:"
                    f"{MODULE.CONTROLLER_SEED_CURRENT_REVISION_PRODUCER_RUN_ID + 1}:"
                    f"{api.base}:{api.head}"
                )
            elif mutation == "producer":
                api.run["conclusion"] = "failure"
            else:
                api.jobs[1]["conclusion"] = "failure"
            with self.subTest(mutation=mutation), self.assertRaises(
                MODULE.VerificationError
            ):
                MODULE.verify_controller_seed(self.controller_seed_args(api), api)

    def test_controller_seed_final_rebind_ignores_volatile_pr_fields(
        self,
    ) -> None:
        api = make_controller_seed_api()
        original_target = api.target
        pull_endpoint = f"repos/{api.repository}/pulls/{api.number}"
        pull_reads = 0

        def target(endpoint: str) -> Any:
            nonlocal pull_reads
            payload = original_target(endpoint)
            if endpoint == pull_endpoint:
                pull_reads += 1
                if pull_reads == 2:
                    payload["updated_at"] = "2026-08-27T07:23:14Z"
                    payload["comments"] = 1
            return payload

        api.target = target  # type: ignore[method-assign]
        evidence = MODULE.verify_controller_seed(
            self.controller_seed_args(api), api
        )

        self.assertEqual("rep60-main-controller-seed/v2", evidence["schema"])
        self.assertEqual(2, pull_reads)

    def test_controller_seed_draft_state_must_be_boolean(self) -> None:
        for invalid_draft in (None, "false", 0, [], {}):
            api = make_controller_seed_api()
            api.pull["draft"] = invalid_draft
            with self.subTest(draft=invalid_draft), self.assertRaisesRegex(
                MODULE.VerificationError,
                "pull request draft state is invalid",
            ):
                MODULE.verify_controller_seed(self.controller_seed_args(api), api)

    def test_controller_seed_accepts_pinned_source_ancestor(self) -> None:
        api = make_controller_seed_api()
        api.source_head_sha = "c" * 40

        evidence = MODULE.verify_controller_seed(self.controller_seed_args(api), api)

        self.assertEqual(MODULE.CONTROLLER_SEED_SOURCE, evidence["source_sha"])
        self.assertIn(
            f"repos/{MODULE.SOURCE_REPOSITORY}/compare/"
            f"{MODULE.CONTROLLER_SEED_SOURCE}...{api.source_head_sha}",
            api.source_endpoints,
        )

    def test_controller_seed_rejects_diverged_source_history(self) -> None:
        api = make_controller_seed_api()
        api.source_head_sha = "c" * 40
        original_source = api.source
        ancestry_endpoint = (
            f"repos/{MODULE.SOURCE_REPOSITORY}/compare/"
            f"{MODULE.CONTROLLER_SEED_SOURCE}...{api.source_head_sha}"
        )

        def source(endpoint: str) -> Any:
            payload = original_source(endpoint)
            if endpoint == ancestry_endpoint:
                payload["status"] = "diverged"
                payload["merge_base_commit"]["sha"] = "f" * 40
            return payload

        api.source = source  # type: ignore[method-assign]
        with self.assertRaisesRegex(
            MODULE.VerificationError,
            "source main diverged",
        ):
            MODULE.verify_controller_seed(self.controller_seed_args(api), api)

    def test_controller_seed_rejects_source_rewind(self) -> None:
        api = make_controller_seed_api()
        api.source_head_sha = "c" * 40
        original_source = api.source
        ancestry_endpoint = (
            f"repos/{MODULE.SOURCE_REPOSITORY}/compare/"
            f"{MODULE.CONTROLLER_SEED_SOURCE}...{api.source_head_sha}"
        )

        def source(endpoint: str) -> Any:
            payload = original_source(endpoint)
            if endpoint == ancestry_endpoint:
                payload["status"] = "behind"
                payload["ahead_by"] = 0
                payload["behind_by"] = 1
                payload["merge_base_commit"]["sha"] = api.source_head_sha
            return payload

        api.source = source  # type: ignore[method-assign]
        with self.assertRaisesRegex(
            MODULE.VerificationError,
            "source main is behind",
        ):
            MODULE.verify_controller_seed(self.controller_seed_args(api), api)

    def test_controller_seed_rejects_boolean_ancestry_counts(self) -> None:
        for field, invalid_value in (("ahead_by", True), ("behind_by", False)):
            api = make_controller_seed_api()
            api.source_head_sha = "c" * 40
            original_source = api.source
            ancestry_endpoint = (
                f"repos/{MODULE.SOURCE_REPOSITORY}/compare/"
                f"{MODULE.CONTROLLER_SEED_SOURCE}...{api.source_head_sha}"
            )

            def source(endpoint: str) -> Any:
                payload = original_source(endpoint)
                if endpoint == ancestry_endpoint:
                    payload[field] = invalid_value
                return payload

            api.source = source  # type: ignore[method-assign]
            with self.subTest(field=field), self.assertRaisesRegex(
                MODULE.VerificationError,
                f"source ancestry {field} must be a non-negative integer",
            ):
                MODULE.verify_controller_seed(self.controller_seed_args(api), api)

    def test_main_reports_the_active_verification_mode(self) -> None:
        common_args = [
            "--repository",
            "lightning-it/example",
            "--pull-request",
            "1",
            "--expected-base",
            "b" * 40,
            "--expected-head",
            "a" * 40,
            "--workflow-sha",
            "e" * 40,
        ]
        cases = (
            ([], "main-bootstrap"),
            (["--classify-only"], "main-bootstrap classification"),
            (["--controller-seed"], "controller-seed"),
        )
        for mode_args, expected_mode in cases:
            stderr = io.StringIO()
            with (
                self.subTest(mode=expected_mode),
                mock.patch.object(MODULE, "GitHubAPI", return_value=mock.sentinel.api),
                mock.patch.object(
                    MODULE,
                    "verify",
                    side_effect=MODULE.VerificationError("bound failure"),
                ),
                mock.patch.object(
                    MODULE,
                    "verify_controller_seed",
                    side_effect=MODULE.VerificationError("bound failure"),
                ),
                contextlib.redirect_stderr(stderr),
            ):
                self.assertEqual(1, MODULE.main([*common_args, *mode_args]))
            self.assertEqual(
                f"REP-60 {expected_mode} verification failed: bound failure\n",
                stderr.getvalue(),
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
        self.assertEqual(api.copilot_blob, evidence["controller_blob_sha"])
        self.assertNotEqual(
            evidence["controller_blob_sha"],
            evidence["source_blobs"][".github/workflows/copilot-review.yml"],
        )
        self.assertEqual(1, evidence["threads_resolved"])
        self.assertFalse(
            any("recursive=1" in endpoint for endpoint in api.target_endpoints)
        )
        self.assertFalse(
            any("recursive=1" in endpoint for endpoint in api.source_endpoints)
        )

    def test_pre_seed_producer_name_is_rejected(self) -> None:
        api = FakeAPI()
        api.run["name"] = "Copilot review gate"
        with self.assertRaisesRegex(
            MODULE.VerificationError,
            "exactly one successful Copilot request",
        ):
            MODULE.verify(self.args(api), api)

    def test_draft_classifier_emits_only_static_protected_handoff(self) -> None:
        api = FakeAPI()
        api.pull["draft"] = True
        args = self.args(api)
        args.classify_only = True

        def unexpected_pages(_endpoint: str) -> list[Any]:
            self.fail("classification must not inspect review evidence")

        def unexpected_graphql(
            _query: str, _variables: dict[str, str | int]
        ) -> Any:
            self.fail("classification must not inspect review threads")

        api.target_pages = unexpected_pages  # type: ignore[method-assign]
        api.target_graphql = unexpected_graphql  # type: ignore[method-assign]
        evidence = MODULE.verify(args, api)

        self.assertEqual("rep60-main-trust-root-handoff/v1", evidence["schema"])
        self.assertEqual(api.repository, evidence["repository"])
        self.assertEqual(api.number, evidence["pull_request_number"])
        self.assertEqual(api.base, evidence["base_sha"])
        self.assertEqual(api.head, evidence["head_sha"])
        self.assertEqual(api.pull["head"]["ref"], evidence["head_ref"])
        self.assertEqual(api.paths, evidence["source_blobs"])
        self.assertNotIn("producer_run_id", evidence)
        self.assertNotIn("review_id", evidence)

    def test_full_verifier_still_rejects_a_draft(self) -> None:
        api = FakeAPI()
        api.pull["draft"] = True
        with self.assertRaisesRegex(MODULE.VerificationError, "still a draft"):
            MODULE.verify(self.args(api), api)

    def test_exact_bootstrap_accepts_an_empty_base_trust_root(self) -> None:
        api = FakeAPI()
        api.base_tree["tree"] = [
            entry
            for entry in api.base_tree["tree"]
            if entry["path"] not in MODULE.EXPECTED_FILES
            or entry["path"] == ".github/workflows/copilot-review.yml"
        ]
        for file_object in api.comparison["files"]:
            file_object["status"] = (
                "modified"
                if file_object["filename"]
                == ".github/workflows/copilot-review.yml"
                else "added"
            )
        evidence = MODULE.verify(self.args(api), api)
        self.assertEqual(api.head, evidence["head_sha"])
        self.assertEqual(api.paths, evidence["source_blobs"])

    def test_exact_bootstrap_reuses_source_identical_protected_helper(self) -> None:
        api = FakeAPI()
        helper = ".github/workflows/current-revision-rerun.yml"
        api.base_tree["tree"].append(api._tree_entry(helper, api.paths[helper]))
        api.comparison["files"] = [
            file_object
            for file_object in api.comparison["files"]
            if file_object["filename"] != helper
        ]
        evidence = MODULE.verify(self.args(api), api)
        self.assertEqual(api.paths, evidence["source_blobs"])

    def test_unchanged_helper_must_match_protected_source(self) -> None:
        api = FakeAPI()
        helper = ".github/workflows/current-revision-rerun.yml"
        api.base_tree["tree"].append(api._tree_entry(helper, "f" * 40))
        api.comparison["files"] = [
            file_object
            for file_object in api.comparison["files"]
            if file_object["filename"] != helper
        ]
        with self.assertRaisesRegex(
            MODULE.VerificationError,
            "unchanged protected base",
        ):
            MODULE.verify(self.args(api), api)

    def test_partial_base_predecessor_set_fails_closed(self) -> None:
        api = FakeAPI()
        retained = next(iter(MODULE.PREDECESSOR_FILES))
        api.base_tree["tree"] = [
            entry
            for entry in api.base_tree["tree"]
            if entry["path"] not in MODULE.PREDECESSOR_FILES
            or entry["path"] == retained
        ]
        for file_object in api.comparison["files"]:
            if file_object["filename"] in MODULE.PREDECESSOR_FILES:
                file_object["status"] = (
                    "modified"
                    if file_object["filename"] == retained
                    else "added"
                )
        with self.assertRaisesRegex(MODULE.VerificationError, "partial"):
            MODULE.verify(self.args(api), api)

    def test_comparison_status_must_match_base_presence(self) -> None:
        api = FakeAPI()
        api.comparison["files"][0]["status"] = "added"
        with self.assertRaisesRegex(MODULE.VerificationError, "unexpected status"):
            MODULE.verify(self.args(api), api)

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

    def test_candidate_copilot_workflow_must_match_protected_source(self) -> None:
        api = FakeAPI()
        next(
            entry
            for entry in api.head_tree["tree"]
            if entry["path"] == ".github/workflows/copilot-review.yml"
        )["sha"] = "f" * 40
        with self.assertRaisesRegex(
            MODULE.VerificationError,
            "candidate .github/workflows/copilot-review.yml differs from protected source",
        ):
            MODULE.verify(self.args(api), api)

    def test_bootstrap_requires_the_exact_six_file_dependency_closure(self) -> None:
        self.assertEqual(
            {
                ".github/codex/prompts/review-exact-head.md",
                ".github/codex/schemas/exact-head-review.schema.json",
                ".github/workflows/copilot-review.yml",
                ".github/workflows/current-revision-rerun.yml",
                ".github/workflows/release-bot-exact-head-review.yml",
                "scripts/materialize-exact-revision-review.py",
            },
            set(MODULE.EXPECTED_FILES),
        )

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
