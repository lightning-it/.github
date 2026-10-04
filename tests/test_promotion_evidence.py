from __future__ import annotations

import hashlib
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


def check_run(
    external_id: str,
    summary: str = "{}",
    title: str = "Current revision review passed",
) -> dict[str, object]:
    return {
        "id": 99,
        "name": "Current revision review",
        "head_sha": HEAD,
        "status": "completed",
        "conclusion": "success",
        "completed_at": "2026-09-27T00:04:30Z",
        "external_id": external_id,
        "details_url": "https://github.com/lightning-it/example/runs/99",
        "app": {"id": 15368, "slug": "github-actions"},
        "check_suite": {"id": 199},
        "output": {"summary": summary, "title": title},
    }


def ingress_pull(
    *, login: str = "litroc", user_id: int = 1, user_type: str = "User"
) -> dict[str, object]:
    return {
        "number": 17,
        "state": "closed",
        "merged_at": "2026-09-27T00:06:00Z",
        "merge_commit_sha": MERGE,
        "title": "fix: exact ingress",
        "user": {"login": login, "id": user_id, "type": user_type},
        "base": {
            "ref": "develop",
            "sha": BASE,
            "repo": {"full_name": "lightning-it/example"},
        },
        "head": {
            "ref": "fix/exact-ingress",
            "sha": HEAD,
            "repo": {"full_name": "lightning-it/example"},
        },
    }


def producer_run(*, login: str = "litroc", release: bool = False) -> dict[str, object]:
    identity = {
        "login": login,
        "id": 307565056 if login == "lightning-it-release-automation[bot]" else 1,
        "type": "Bot" if login.endswith("[bot]") else "User",
    }
    if release:
        return {
            "id": 88,
            "html_url": "https://github.com/lightning-it/example/actions/runs/88",
            "actor": identity,
            "triggering_actor": identity,
            "run_attempt": 1,
            "event": "workflow_dispatch",
            "path": ".github/workflows/release-bot-exact-head-review.yml",
            "head_branch": "develop",
            "head_sha": BASE,
            "display_title": f"Exact-Revision Codex PR #17 {BASE}..{HEAD}",
            "status": "completed",
            "conclusion": "success",
        }
    return {
        "id": 88,
        "check_suite_id": 199,
        "html_url": "https://github.com/lightning-it/example/actions/runs/88",
        "actor": identity,
        "triggering_actor": identity,
        "run_attempt": 1,
        "event": "pull_request_target",
        "path": ".github/workflows/copilot-review.yml",
        "name": "Current revision review gate",
        "head_branch": "fix/exact-ingress",
        "head_sha": HEAD,
        "status": "completed",
        "conclusion": "success",
        "created_at": "2026-09-27T00:00:00Z",
        "updated_at": "2026-09-27T00:05:00Z",
        "pull_requests": [
            {
                "id": 1700,
                "number": 17,
                "url": "https://api.github.com/repos/lightning-it/example/pulls/17",
                "base": {
                    "ref": "develop",
                    "sha": BASE,
                    "repo": {
                        "id": 700,
                        "name": "example",
                        "url": "https://api.github.com/repos/lightning-it/example",
                    },
                },
                "head": {
                    "ref": "fix/exact-ingress",
                    "sha": HEAD,
                    "repo": {
                        "id": 700,
                        "name": "example",
                        "url": "https://api.github.com/repos/lightning-it/example",
                    },
                },
            }
        ],
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


def expanded_v6_summary(kind: str = "copilot") -> str:
    evidence = json.loads(v6_summary(kind))
    evidence.update(
        {
            "controller_ref": "develop",
            "head_repository": "lightning-it/example",
            "pull_request_labels_sha256": hashlib.sha256(b"[]").hexdigest(),
            "pull_request_last_edited_at": None,
            "review_id": (
                "PRR_kwDOQs6tNc8AAAABPj6qbQ" if kind == "copilot" else None
            ),
        }
    )
    return json.dumps(evidence)


def evidence_api(
    run: dict[str, object],
    suite: dict[str, object] | None = None,
    review: dict[str, object] | None = None,
    merge: dict[str, object] | None = None,
    review_comment: dict[str, object] | None = None,
    jobs: list[dict[str, object]] | None = None,
):
    def dispatch(arguments: list[str]) -> dict[str, object]:
        if arguments[:2] == ["api", "graphql"] and any(
            "lastEditedAt" in argument for argument in arguments
        ):
            return {
                "data": {
                    "repository": {
                        "pullRequest": {"number": 17, "lastEditedAt": None}
                    }
                }
            }
        endpoint = arguments[-1]
        if endpoint == "repos/lightning-it/example":
            return {
                "id": 700,
                "name": "example",
                "url": "https://api.github.com/repos/lightning-it/example",
                "default_branch": "develop",
            }
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
        if endpoint == (
            "repos/lightning-it/example/actions/runs/88/jobs?filter=all&per_page=100"
        ):
            return {"total_count": len(jobs or []), "jobs": jobs or []}
        if endpoint == "repos/lightning-it/example/check-suites/199":
            return suite or {
                "id": 199,
                "head_branch": "fix/exact-ingress",
                "head_sha": HEAD,
                "status": "completed",
                "conclusion": "success",
                "app": {"id": 15368, "slug": "github-actions"},
            }
        if endpoint == f"repos/lightning-it/example/commits/{MERGE}":
            return merge or {
                "sha": MERGE,
                "parents": [{"sha": BASE}, {"sha": HEAD}],
            }
        if endpoint == "repos/lightning-it/example/pulls/17/reviews?per_page=100":
            return [
                [
                    review
                    or {
                        "id": 17001,
                        "node_id": "PRR_kwDOQs6tNc8AAAABPj6qbQ",
                        "user": {
                            "login": "copilot-pull-request-reviewer[bot]",
                            "id": 175728472,
                            "type": "Bot",
                        },
                        "state": "COMMENTED",
                        "commit_id": HEAD,
                        "submitted_at": "2026-09-27T00:04:00Z",
                        "body": (
                            "<!-- ccr-overview-v2 -->\n\n"
                            "## Copilot review overview\n\n"
                            "### 🟢 Approval recommended\n\n"
                            "**Findings:** None\n"
                        ),
                    }
                ]
            ]
        if endpoint == (
            "repos/lightning-it/example/pulls/17/reviews/17001/"
            "comments?per_page=100"
        ):
            return [[review_comment] if review_comment is not None else []]
        raise AssertionError(endpoint)

    return dispatch


class PromotionEvidenceTests(unittest.TestCase):
    def test_github_api_proxy_accepts_only_exact_connect_target(self) -> None:
        accepted = (
            b"CONNECT api.github.com:443 HTTP/1.1\r\n"
            b"Host: api.github.com:443\r\n"
            b"User-Agent: gh\r\n\r\n"
        )
        MODULE.validate_github_api_connect_request(accepted)
        rejected = (
            accepted.replace(b"api.github.com", b"example.com"),
            accepted + b"smuggled",
            accepted.replace(
                b"User-Agent: gh\r\n",
                b"Host: api.github.com:443\r\nUser-Agent: gh\r\n",
            ),
            accepted.replace(
                b"User-Agent: gh\r\n",
                b"Proxy-Authorization: Basic secret\r\n",
            ),
        )
        for request in rejected:
            with self.subTest(request=request), self.assertRaises(MODULE.EvidenceError):
                MODULE.validate_github_api_connect_request(request)

    def test_github_api_json_parser_fails_closed(self) -> None:
        with mock.patch.dict(os.environ, {"GH_TOKEN": "test-token"}):
            with mock.patch.object(MODULE, "run", return_value='{"id":1,"id":2}'):
                with self.assertRaisesRegex(
                    MODULE.EvidenceError, "check-summary-duplicate-key"
                ):
                    MODULE.gh_json(["api", "example"])
            with mock.patch.object(MODULE, "run", return_value='{"id":NaN}'):
                with self.assertRaisesRegex(
                    MODULE.EvidenceError, "check-summary-nonstandard-constant"
                ):
                    MODULE.gh_json(["api", "example"])
            with mock.patch.object(MODULE, "run", return_value='{"id":1}'):
                self.assertEqual({"id": 1}, MODULE.gh_json(["api", "example"]))
            with (
                mock.patch.object(MODULE, "run", return_value="{}"),
                mock.patch.object(MODULE.json, "loads", side_effect=RecursionError),
            ):
                with self.assertRaisesRegex(
                    MODULE.EvidenceError, "github-response-not-json"
                ):
                    MODULE.gh_json(["api", "example"])

    def test_github_api_json_retries_only_bounded_transient_reads(self) -> None:
        transient = MODULE.EvidenceError(
            "command-failed:gh:unexpected end of JSON input"
        )
        with (
            mock.patch.dict(os.environ, {"GH_TOKEN": "test-token"}),
            mock.patch.object(
                MODULE, "run", side_effect=[transient, '{"id":1}']
            ) as command,
            mock.patch.object(MODULE.time, "sleep") as pause,
        ):
            self.assertEqual({"id": 1}, MODULE.gh_json(["api", "example"]))
        self.assertEqual(2, command.call_count)
        pause.assert_called_once_with(0.25)

        with (
            mock.patch.dict(os.environ, {"GH_TOKEN": "test-token"}),
            mock.patch.object(
                MODULE,
                "run",
                side_effect=[transient, transient, transient],
            ) as command,
            mock.patch.object(MODULE.time, "sleep") as pause,
        ):
            with self.assertRaisesRegex(
                MODULE.EvidenceError, "unexpected end of JSON input"
            ):
                MODULE.gh_json(["api", "example"])
        self.assertEqual(3, command.call_count)
        self.assertEqual(
            [mock.call(0.25), mock.call(0.5)],
            pause.call_args_list,
        )

        with (
            mock.patch.dict(os.environ, {"GH_TOKEN": "test-token"}),
            mock.patch.object(MODULE, "run", return_value="{]") as command,
            mock.patch.object(MODULE.time, "sleep") as pause,
        ):
            with self.assertRaisesRegex(
                MODULE.EvidenceError, "github-response-not-json"
            ):
                MODULE.gh_json(["api", "example"])
        self.assertEqual(1, command.call_count)
        pause.assert_not_called()

        with (
            mock.patch.dict(os.environ, {"GH_TOKEN": "test-token"}),
            mock.patch.object(
                MODULE,
                "run",
                side_effect=MODULE.EvidenceError("command-failed:gh:HTTP 403"),
            ) as command,
            mock.patch.object(MODULE.time, "sleep") as pause,
        ):
            with self.assertRaisesRegex(MODULE.EvidenceError, "HTTP 403"):
                MODULE.gh_json(["api", "example"])
        self.assertEqual(1, command.call_count)
        pause.assert_not_called()

        with (
            mock.patch.dict(os.environ, {"GH_TOKEN": "test-token"}),
            mock.patch.object(
                MODULE,
                "run",
                side_effect=MODULE.EvidenceError(
                    "command-failed:gh:unexpected end of JSON input; HTTP 403"
                ),
            ) as command,
            mock.patch.object(MODULE.time, "sleep") as pause,
        ):
            with self.assertRaisesRegex(MODULE.EvidenceError, "HTTP 403"):
                MODULE.gh_json(["api", "example"])
        self.assertEqual(1, command.call_count)
        pause.assert_not_called()

        with mock.patch.dict(os.environ, {"GH_TOKEN": "test-token"}):
            with self.assertRaisesRegex(
                MODULE.EvidenceError, "gh-json-read-command"
            ):
                MODULE.gh_json(["pr", "view", "1"])

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
        self.assertEqual(
            hashlib.sha256(b"release").hexdigest(),
            MODULE.promotion_body_sha256(value),
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
        candidate = promotion()
        candidate["number"] = True
        with self.assertRaisesRegex(MODULE.EvidenceError, "promotion-number"):
            MODULE.validate_live_promotion(
                candidate,
                repository="lightning-it/example",
                pull_number=1,
                expected_base=BASE,
                expected_head=HEAD,
            )
        candidate = promotion()
        candidate["user"]["id"] = float(307565056)
        with self.assertRaisesRegex(MODULE.EvidenceError, "promotion-author-id"):
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
                expected_number=17,
            )["number"],
            17,
        )
        with self.assertRaisesRegex(
            MODULE.EvidenceError, "associated-pull-number-mismatch"
        ):
            MODULE.select_ingress_pull(
                [candidate],
                repository="lightning-it/example",
                merge_sha=MERGE,
                head_sha=HEAD,
                expected_number=18,
            )
        with self.assertRaises(MODULE.EvidenceError):
            MODULE.select_ingress_pull(
                [candidate, dict(candidate)],
                repository="lightning-it/example",
                merge_sha=MERGE,
                head_sha=HEAD,
            )
        flattened = MODULE.flatten_pull_pages([[candidate], [dict(candidate)]])
        with self.assertRaisesRegex(MODULE.EvidenceError, "associated-pull-not-unique"):
            MODULE.select_ingress_pull(
                flattened,
                repository="lightning-it/example",
                merge_sha=MERGE,
                head_sha=HEAD,
            )

    def test_first_parent_history_allows_structural_backmerge_anchor(self) -> None:
        def history_git(arguments: list[str], _: Path) -> str:
            if arguments == ["status", "--porcelain=v1", "--untracked-files=no"]:
                return ""
            if arguments[:2] == ["cat-file", "-t"]:
                return "commit"
            if arguments == ["merge-base", "--all", BASE, HEAD]:
                return BASE
            if arguments == ["rev-parse", f"{HEAD}^{{tree}}"]:
                return "4" * 40
            if arguments == [
                "rev-list",
                "--first-parent",
                "--reverse",
                f"{BASE}..{HEAD}",
            ]:
                return HEAD
            if arguments == ["show", "-s", "--format=%P", HEAD]:
                return f"{MERGE} {BASE}"
            raise AssertionError(arguments)

        with tempfile.TemporaryDirectory() as directory:
            with (
                mock.patch.object(MODULE, "git", side_effect=history_git),
                mock.patch.object(MODULE, "run", return_value=""),
            ):
                history_anchor, integration_tree, merges = MODULE.first_parent_merges(
                    Path(directory), BASE, HEAD
                )
        self.assertEqual(history_anchor, MERGE)
        self.assertEqual(integration_tree, "4" * 40)
        self.assertEqual(
            merges,
            [{"base_sha": MERGE, "head_sha": BASE, "merge_sha": HEAD}],
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
        pages[0]["check_runs"][0]["output"]["title"] = "unbound title"
        with self.assertRaisesRegex(
            MODULE.EvidenceError, "bound-current-revision-check-not-unique"
        ):
            MODULE.bound_review_check(
                pages,
                repository="lightning-it/example",
                pull=ingress_pull(),
                pull_number=17,
                base_sha=BASE,
                head_sha=HEAD,
            )
        pages[0]["check_runs"][0]["output"]["title"] = "Current revision review passed"
        with self.assertRaises(MODULE.EvidenceError):
            MODULE.bound_review_check(
                pages,
                repository="lightning-it/example",
                pull=ingress_pull(),
                pull_number=18,
                base_sha=BASE,
                head_sha=HEAD,
            )

    def test_v6_renovate_check_requires_the_exact_producer_title(self) -> None:
        renovate = ingress_pull(
            login="renovate[bot]", user_id=29139614, user_type="Bot"
        )
        renovate["base"]["ref"] = "develop"
        renovate["head"]["ref"] = "renovate/dependency"
        renovate["labels"] = [
            {"name": "safe-automerge"},
            {"name": "dependencies"},
            {"name": "renovate"},
        ]
        renovate["last_edited_at"] = None

        summary = json.loads(v6_summary("renovate"))
        summary["pull_request_labels_sha256"] = hashlib.sha256(
            b'["dependencies","renovate","safe-automerge"]'
        ).hexdigest()
        external_id = (
            f"mlx90-current-revision:renovate:v6:17:88:{BASE}:{HEAD}"
        )
        run = producer_run(login="renovate[bot]")
        renovate_identity = {
            "login": "renovate[bot]",
            "id": 29139614,
            "type": "Bot",
        }
        run["actor"] = renovate_identity
        run["triggering_actor"] = renovate_identity
        run["head_branch"] = "renovate/dependency"
        run["pull_requests"][0]["head"]["ref"] = "renovate/dependency"

        check = check_run(
            external_id,
            json.dumps(summary),
            "Current revision Renovate exemption passed",
        )
        with mock.patch.object(
            MODULE, "gh_json", side_effect=evidence_api(run)
        ):
            evidence = MODULE.bound_review_check(
                [{"check_runs": [check]}],
                repository="lightning-it/example",
                pull=renovate,
                pull_number=17,
                base_sha=BASE,
                head_sha=HEAD,
            )
        self.assertEqual("renovate", evidence["evidence_kind"])

        check["output"]["title"] = "Current revision review passed"
        with self.assertRaisesRegex(
            MODULE.EvidenceError, "bound-current-revision-check-not-unique"
        ):
            MODULE.bound_review_check(
                [{"check_runs": [check]}],
                repository="lightning-it/example",
                pull=renovate,
                pull_number=17,
                base_sha=BASE,
                head_sha=HEAD,
            )

    def test_v6_renovate_allows_one_empty_run_association(self) -> None:
        renovate = ingress_pull(
            login="renovate[bot]", user_id=29139614, user_type="Bot"
        )
        renovate["base"]["ref"] = "develop"
        renovate["head"]["ref"] = "renovate/dependency"
        renovate["labels"] = [
            {"name": "safe-automerge"},
            {"name": "dependencies"},
            {"name": "renovate"},
        ]
        renovate["last_edited_at"] = None

        summary = json.loads(v6_summary("renovate"))
        summary["pull_request_labels_sha256"] = hashlib.sha256(
            b'["dependencies","renovate","safe-automerge"]'
        ).hexdigest()
        run = producer_run(login="renovate[bot]")
        renovate_identity = {
            "login": "renovate[bot]",
            "id": 29139614,
            "type": "Bot",
        }
        run["actor"] = renovate_identity
        run["triggering_actor"] = renovate_identity
        run["head_branch"] = "renovate/dependency"
        run["pull_requests"] = []
        check = check_run(
            f"mlx90-current-revision:renovate:v6:17:88:{BASE}:{HEAD}",
            json.dumps(summary),
            "Current revision Renovate exemption passed",
        )
        suite = {
            "id": 199,
            "head_branch": "renovate/dependency",
            "head_sha": HEAD,
            "status": "completed",
            "conclusion": "success",
            "app": {"id": 15368, "slug": "github-actions"},
        }

        with mock.patch.object(
            MODULE,
            "gh_json",
            side_effect=evidence_api(run, suite=suite),
        ):
            evidence = MODULE.bound_review_check(
                [{"check_runs": [check]}],
                repository="lightning-it/example",
                pull=renovate,
                pull_number=17,
                base_sha=BASE,
                head_sha=HEAD,
            )
        self.assertEqual("renovate", evidence["evidence_kind"])

        run["updated_at"] = "2026-09-27T00:04:00Z"
        with (
            mock.patch.object(
                MODULE,
                "gh_json",
                side_effect=evidence_api(run, suite=suite),
            ),
            self.assertRaisesRegex(
                MODULE.EvidenceError, "producer-renovate-time-binding"
            ),
        ):
            MODULE.bound_review_check(
                [{"check_runs": [check]}],
                repository="lightning-it/example",
                pull=renovate,
                pull_number=17,
                base_sha=BASE,
                head_sha=HEAD,
            )

    def test_v6_managed_sync_check_requires_the_exact_producer_title(self) -> None:
        managed = ingress_pull(
            login="lightning-it-shared-assets-sync[bot]",
            user_id=307342877,
            user_type="Bot",
        )
        run = producer_run(login="lightning-it-shared-assets-sync[bot]")
        run["actor"]["id"] = 307342877
        run["triggering_actor"]["id"] = 307342877
        external_id = (
            f"mlx90-current-revision:managed-sync:v6:17:88:{BASE}:{HEAD}"
        )
        check = check_run(
            external_id,
            v6_summary("managed-sync"),
            "Current revision managed distribution exemption passed",
        )

        with mock.patch.object(
            MODULE, "gh_json", side_effect=evidence_api(run)
        ):
            evidence = MODULE.bound_review_check(
                [{"check_runs": [check]}],
                repository="lightning-it/example",
                pull=managed,
                pull_number=17,
                base_sha=BASE,
                head_sha=HEAD,
            )
        self.assertEqual("managed-sync", evidence["evidence_kind"])

        check["output"]["title"] = "Current revision review passed"
        with self.assertRaisesRegex(
            MODULE.EvidenceError, "bound-current-revision-check-not-unique"
        ):
            MODULE.bound_review_check(
                [{"check_runs": [check]}],
                repository="lightning-it/example",
                pull=managed,
                pull_number=17,
                base_sha=BASE,
                head_sha=HEAD,
            )

    def test_v6_ancestry_check_requires_the_exact_producer_title(self) -> None:
        ancestry = ingress_pull(
            login="lightning-it-release-automation[bot]",
            user_id=307565056,
            user_type="Bot",
        )
        ancestry["title"] = "chore(governance): record main ancestry before abc"
        ancestry["head"]["ref"] = "backmerge/release-main"
        run = producer_run(login="lightning-it-release-automation[bot]")
        run["head_branch"] = "backmerge/release-main"
        run["pull_requests"][0]["head"]["ref"] = "backmerge/release-main"
        external_id = (
            f"mlx90-current-revision:ancestry-backmerge:v6:17:88:{BASE}:{HEAD}"
        )
        check = check_run(
            external_id,
            v6_summary("ancestry-backmerge"),
            "Current revision deterministic exemption passed",
        )

        with mock.patch.object(
            MODULE, "gh_json", side_effect=evidence_api(run)
        ):
            evidence = MODULE.bound_review_check(
                [{"check_runs": [check]}],
                repository="lightning-it/example",
                pull=ancestry,
                pull_number=17,
                base_sha=BASE,
                head_sha=HEAD,
            )
        self.assertEqual("ancestry-backmerge", evidence["evidence_kind"])

        check["output"]["title"] = "Current revision review passed"
        with self.assertRaisesRegex(
            MODULE.EvidenceError, "bound-current-revision-check-not-unique"
        ):
            MODULE.bound_review_check(
                [{"check_runs": [check]}],
                repository="lightning-it/example",
                pull=ancestry,
                pull_number=17,
                base_sha=BASE,
                head_sha=HEAD,
            )

    def test_v5_copilot_evidence_remains_compatible(self) -> None:
        summary = json.loads(v6_summary())
        summary.pop("pull_request_number")
        external_id = f"mlx90-current-revision:copilot:v5:88:{BASE}:{HEAD}"
        with mock.patch.object(
            MODULE, "gh_json", side_effect=evidence_api(producer_run())
        ):
            evidence = MODULE.bound_review_check(
                [{"check_runs": [check_run(external_id, json.dumps(summary))]}],
                repository="lightning-it/example",
                pull=ingress_pull(),
                pull_number=17,
                base_sha=BASE,
                head_sha=HEAD,
            )
        self.assertEqual("v5", evidence["evidence_version"])

    def test_copilot_attempt_two_requires_github_actions_trigger(self) -> None:
        run = producer_run()
        run["run_attempt"] = 2
        run["triggering_actor"] = {
            "login": "github-actions[bot]",
            "id": 41898282,
            "type": "Bot",
        }
        external_id = f"mlx90-current-revision:copilot:v6:17:88:{BASE}:{HEAD}"
        with mock.patch.object(MODULE, "gh_json", side_effect=evidence_api(run)):
            MODULE.bound_review_check(
                [{"check_runs": [check_run(external_id, v6_summary())]}],
                repository="lightning-it/example",
                pull=ingress_pull(),
                pull_number=17,
                base_sha=BASE,
                head_sha=HEAD,
            )
        run["triggering_actor"] = {
            "login": "litroc",
            "id": 1,
            "type": "User",
        }
        with mock.patch.object(MODULE, "gh_json", side_effect=evidence_api(run)):
            with self.assertRaisesRegex(
                MODULE.EvidenceError, "producer-run-triggering-actor-identity"
            ):
                MODULE.bound_review_check(
                    [{"check_runs": [check_run(external_id, v6_summary())]}],
                    repository="lightning-it/example",
                    pull=ingress_pull(),
                    pull_number=17,
                    base_sha=BASE,
                    head_sha=HEAD,
                )

    def test_producer_run_requires_exact_pull_request_association(self) -> None:
        external_id = f"mlx90-current-revision:copilot:v6:17:88:{BASE}:{HEAD}"
        for mutate, reason in (
            (
                lambda run: run["pull_requests"].append(dict(run["pull_requests"][0])),
                "producer-run-pull-request-count",
            ),
            (
                lambda run: run["pull_requests"][0].update({"number": 18}),
                "producer-run-pull-request-binding",
            ),
            (
                lambda run: run["pull_requests"][0]["head"].update({"sha": "f" * 40}),
                "producer-run-pull-request-head-binding",
            ),
        ):
            run = producer_run()
            mutate(run)
            with mock.patch.object(MODULE, "gh_json", side_effect=evidence_api(run)):
                with self.assertRaisesRegex(MODULE.EvidenceError, reason):
                    MODULE.bound_review_check(
                        [{"check_runs": [check_run(external_id, v6_summary())]}],
                        repository="lightning-it/example",
                        pull=ingress_pull(),
                        pull_number=17,
                        base_sha=BASE,
                        head_sha=HEAD,
                    )

    def test_empty_run_association_uses_native_binding_when_check_suite_is_reused(
        self,
    ) -> None:
        external_id = f"mlx90-current-revision:copilot:v6:17:88:{BASE}:{HEAD}"
        run = producer_run()
        run["pull_requests"] = []
        check = check_run(external_id, v6_summary())
        check["check_suite"] = {"id": 198}
        with mock.patch.object(
            MODULE, "gh_json", side_effect=evidence_api(run)
        ):
            evidence = MODULE.bound_review_check(
                [{"check_runs": [check]}],
                repository="lightning-it/example",
                pull=ingress_pull(),
                pull_number=17,
                base_sha=BASE,
                head_sha=HEAD,
            )
        self.assertEqual(88, evidence["producer_run_id"])

        late_success_check = check_run(external_id, v6_summary())
        late_success_check["completed_at"] = "2026-09-27T00:05:01Z"
        with mock.patch.object(MODULE, "gh_json", side_effect=evidence_api(run)):
            with self.assertRaisesRegex(
                MODULE.EvidenceError, "producer-review-binding"
            ):
                MODULE.bound_review_check(
                    [{"check_runs": [late_success_check]}],
                    repository="lightning-it/example",
                    pull=ingress_pull(),
                    pull_number=17,
                    base_sha=BASE,
                    head_sha=HEAD,
                )

        early_check = check_run(external_id, v6_summary())
        early_check["completed_at"] = "2026-09-27T00:03:00Z"
        with mock.patch.object(
            MODULE, "gh_json", side_effect=evidence_api(run)
        ):
            with self.assertRaisesRegex(
                MODULE.EvidenceError, "producer-review-binding"
            ):
                MODULE.bound_review_check(
                    [{"check_runs": [early_check]}],
                    repository="lightning-it/example",
                    pull=ingress_pull(),
                    pull_number=17,
                    base_sha=BASE,
                    head_sha=HEAD,
                )

        mismatched_suite = {
            "id": 199,
            "head_branch": "fix/other-ingress",
            "head_sha": HEAD,
            "status": "completed",
            "conclusion": "success",
            "app": {"id": 15368, "slug": "github-actions"},
        }
        with mock.patch.object(
            MODULE,
            "gh_json",
            side_effect=evidence_api(run, mismatched_suite),
        ):
            with self.assertRaisesRegex(
                MODULE.EvidenceError,
                "producer-check-suite-head-binding",
            ):
                MODULE.bound_review_check(
                    [{"check_runs": [check_run(external_id, v6_summary())]}],
                    repository="lightning-it/example",
                    pull=ingress_pull(),
                    pull_number=17,
                    base_sha=BASE,
                    head_sha=HEAD,
                )

    def test_empty_run_association_requires_native_pr_merge_and_review_binding(
        self,
    ) -> None:
        external_id = f"mlx90-current-revision:copilot:v6:17:88:{BASE}:{HEAD}"
        check = check_run(external_id, v6_summary())
        run = producer_run()
        run["pull_requests"] = []
        valid_review = {
            "id": 17001,
            "user": {
                "login": "copilot-pull-request-reviewer[bot]",
                "id": 175728472,
                "type": "Bot",
            },
            "state": "COMMENTED",
            "commit_id": HEAD,
            "submitted_at": "2026-09-27T00:04:00Z",
            "body": (
                "<!-- ccr-overview-v2 -->\n\n"
                "## Copilot review overview\n\n"
                "### 🟢 Approval recommended\n\n"
                "**Findings:** None\n"
            ),
        }

        invalid_cases = (
            (
                ingress_pull() | {"state": "open", "merged_at": None},
                None,
                valid_review,
                run,
                "producer-pull-not-merged",
            ),
            (
                ingress_pull(),
                {"sha": MERGE, "parents": [{"sha": "f" * 40}, {"sha": HEAD}]},
                valid_review,
                run,
                "producer-pull-merge-binding",
            ),
            (
                ingress_pull()
                | {
                    "base": {
                        "ref": "develop",
                        "sha": BASE,
                        "repo": {"full_name": "attacker/example"},
                    }
                },
                None,
                valid_review,
                run,
                "producer-pull-revision-binding",
            ),
            (
                ingress_pull(),
                {"sha": MERGE, "parents": [{"sha": 7}, {"sha": HEAD}]},
                valid_review,
                run,
                "producer-pull-merge-parent-0-sha-not-string",
            ),
            (
                ingress_pull(),
                None,
                valid_review | {"commit_id": "f" * 40},
                run,
                "producer-current-copilot-review-not-unique",
            ),
            (
                ingress_pull(),
                None,
                valid_review | {"body": "<!-- ccr-overview-v2 -->\nChanges recommended"},
                run,
                "producer-review-binding",
            ),
            (
                ingress_pull(),
                None,
                valid_review,
                run | {"created_at": "2026-09-27T00:04:31Z"},
                "producer-review-binding",
            ),
            (
                ingress_pull(),
                None,
                valid_review,
                run | {"updated_at": "2026-09-27T00:07:00Z"},
                "producer-review-binding",
            ),
        )
        for pull, merge, review, candidate_run, reason in invalid_cases:
            with self.subTest(reason=reason), mock.patch.object(
                MODULE,
                "gh_json",
                side_effect=evidence_api(candidate_run, review=review, merge=merge),
            ):
                with self.assertRaisesRegex(MODULE.EvidenceError, reason):
                    MODULE.bound_review_check(
                        [{"check_runs": [check]}],
                        repository="lightning-it/example",
                        pull=pull,
                        pull_number=17,
                        base_sha=BASE,
                        head_sha=HEAD,
                    )

        with mock.patch.object(
            MODULE,
            "gh_json",
            side_effect=evidence_api(
                run,
                review=valid_review | {"state": "APPROVED"},
            ),
        ):
            evidence = MODULE.bound_review_check(
                [{"check_runs": [check]}],
                repository="lightning-it/example",
                pull=ingress_pull(),
                pull_number=17,
                base_sha=BASE,
                head_sha=HEAD,
            )
        self.assertEqual(88, evidence["producer_run_id"])

        # GitHub may reuse a valid native review for the same exact head in a
        # later protected verifier run. The review therefore may predate the
        # producer run while still preceding its bound check and the merge.
        reused_review_run = run | {"created_at": "2026-09-27T00:04:15Z"}
        with mock.patch.object(
            MODULE,
            "gh_json",
            side_effect=evidence_api(reused_review_run, review=valid_review),
        ):
            evidence = MODULE.bound_review_check(
                [{"check_runs": [check]}],
                repository="lightning-it/example",
                pull=ingress_pull(),
                pull_number=17,
                base_sha=BASE,
                head_sha=HEAD,
            )
        self.assertEqual(88, evidence["producer_run_id"])

        for marker in (
            "Unable to review this pull request",
            "No files to review",
            "Wasn't able to review any files",
            "Wasn’t able to review any files",
            "Premium request quota unavailable",
            "Premium requests quota unavailable",
            "Premium request quota exhausted",
            "Premium request quota exceeded",
            "Suppressed comments",
            "Encountered an error",
        ):
            with self.subTest(marker=marker), mock.patch.object(
                MODULE,
                "gh_json",
                side_effect=evidence_api(
                    run,
                    review=valid_review
                    | {"body": f"{valid_review['body']}\n{marker}"},
                ),
            ):
                with self.assertRaisesRegex(
                    MODULE.EvidenceError, "producer-review-binding"
                ):
                    MODULE.bound_review_check(
                        [{"check_runs": [check_run(external_id, v6_summary())]}],
                        repository="lightning-it/example",
                        pull=ingress_pull(),
                        pull_number=17,
                        base_sha=BASE,
                        head_sha=HEAD,
                    )

        with mock.patch.object(
            MODULE,
            "gh_json",
            side_effect=evidence_api(
                run,
                review=valid_review,
                review_comment={
                    "id": 18001,
                    "body": "Copilot encountered an error while reviewing",
                },
            ),
        ):
            with self.assertRaisesRegex(
                MODULE.EvidenceError, "producer-review-binding"
            ):
                MODULE.bound_review_check(
                    [{"check_runs": [check_run(external_id, v6_summary())]}],
                    repository="lightning-it/example",
                    pull=ingress_pull(),
                    pull_number=17,
                    base_sha=BASE,
                    head_sha=HEAD,
                )

        managed_run = producer_run(
            login="lightning-it-shared-assets-sync[bot]"
        )
        managed_run["actor"]["id"] = 307342877
        managed_run["triggering_actor"]["id"] = 307342877
        managed_run["pull_requests"] = []
        managed_external_id = (
            f"mlx90-current-revision:managed-sync:v6:17:88:{BASE}:{HEAD}"
        )
        with mock.patch.object(
            MODULE, "gh_json", side_effect=evidence_api(managed_run)
        ):
            with self.assertRaisesRegex(
                MODULE.EvidenceError, "producer-empty-association-kind"
            ):
                MODULE.bound_review_check(
                    [
                        {
                            "check_runs": [
                                check_run(
                                    managed_external_id,
                                    v6_summary("managed-sync"),
                                    "Current revision managed distribution exemption passed",
                                )
                            ]
                        }
                    ],
                    repository="lightning-it/example",
                    pull=ingress_pull(
                        login="lightning-it-shared-assets-sync[bot]",
                        user_id=307342877,
                        user_type="Bot",
                    ),
                    pull_number=17,
                    base_sha=BASE,
                    head_sha=HEAD,
                )

        invalid_suites = (
            ({"id": 199.0}, "producer-check-suite-id-not-positive-integer"),
            ({"id": 200}, "producer-check-suite-id"),
            (
                {"app": {"id": 15368.0, "slug": "github-actions"}},
                "producer-check-suite-app-id-not-positive-integer",
            ),
            (
                {"app": {"id": 15368, "slug": "untrusted-actions"}},
                "producer-check-suite-app",
            ),
            ({"status": "in_progress"}, "producer-check-suite-result"),
            ({"head_sha": "f" * 40}, "producer-check-suite-head-binding"),
        )
        valid_suite = {
            "id": 199,
            "head_branch": "fix/exact-ingress",
            "head_sha": HEAD,
            "status": "completed",
            "conclusion": "success",
            "app": {"id": 15368, "slug": "github-actions"},
        }
        for mutation, reason in invalid_suites:
            suite = {**valid_suite, **mutation}
            with self.subTest(mutation=mutation), mock.patch.object(
                MODULE,
                "gh_json",
                side_effect=evidence_api(run, suite),
            ):
                with self.assertRaisesRegex(MODULE.EvidenceError, reason):
                    MODULE.bound_review_check(
                        [{"check_runs": [check_run(external_id, v6_summary())]}],
                        repository="lightning-it/example",
                        pull=ingress_pull(),
                        pull_number=17,
                        base_sha=BASE,
                        head_sha=HEAD,
                    )

        failed_locator_suite = {**valid_suite, "conclusion": "failure"}
        with mock.patch.object(
            MODULE,
            "gh_json",
            side_effect=evidence_api(run, failed_locator_suite),
        ):
            result = MODULE.bound_review_check(
                [{"check_runs": [check_run(external_id, v6_summary())]}],
                repository="lightning-it/example",
                pull=ingress_pull(),
                pull_number=17,
                base_sha=BASE,
                head_sha=HEAD,
            )
        self.assertEqual(result["producer_run_id"], 88)

        run["check_suite_id"] = 199.0
        with mock.patch.object(MODULE, "gh_json", side_effect=evidence_api(run)):
            with self.assertRaisesRegex(
                MODULE.EvidenceError,
                "producer-run-check-suite-id-not-positive-integer",
            ):
                MODULE.bound_review_check(
                    [{"check_runs": [check_run(external_id, v6_summary())]}],
                    repository="lightning-it/example",
                    pull=ingress_pull(),
                    pull_number=17,
                    base_sha=BASE,
                    head_sha=HEAD,
                )

    def test_bound_review_digest_detects_valid_v5_summary_mutation(self) -> None:
        external_id = f"mlx90-current-revision:copilot:v5:88:{BASE}:{HEAD}"
        first = json.loads(v6_summary())
        first.pop("pull_request_number")
        second = {**first, "pull_request_number": 17}
        records = []
        for summary in (first, second):
            with mock.patch.object(
                MODULE, "gh_json", side_effect=evidence_api(producer_run())
            ):
                records.append(
                    MODULE.bound_review_check(
                        [{"check_runs": [check_run(external_id, json.dumps(summary))]}],
                        repository="lightning-it/example",
                        pull=ingress_pull(),
                        pull_number=17,
                        base_sha=BASE,
                        head_sha=HEAD,
                    )
                )
        self.assertNotEqual(records[0]["summary_sha256"], records[1]["summary_sha256"])

    def test_v4_release_review_requires_exact_json_evidence(self) -> None:
        summary = json.dumps(
            {
                "schema": 4,
                "base_sha": BASE,
                "head_sha": HEAD,
                "merge_base_sha": BASE,
                "integration_tree_sha": "3" * 40,
                "diff_sha256": "6" * 64,
                "input_sha256": INPUT,
                "pull_request_number": 17,
                "producer_run_id": 88,
                "run_url": "https://github.com/lightning-it/example/actions/runs/88",
                "workflow_sha": BASE,
            }
        )
        pages = [
            {
                "check_runs": [
                    check_run(
                        f"mlx90-current-revision:v4:88:{INPUT}",
                        summary,
                        "Protected Exact-Revision Codex review passed",
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
                    merge_base_sha=BASE,
                )["evidence_kind"],
                "release-app",
            )

        mismatched_merge_base = json.loads(summary)
        mismatched_merge_base["merge_base_sha"] = "9" * 40
        pages[0]["check_runs"][0]["output"]["summary"] = json.dumps(
            mismatched_merge_base
        )
        with mock.patch.object(
            MODULE,
            "gh_json",
            return_value=producer_run(
                login="lightning-it-release-automation[bot]", release=True
            ),
        ):
            with self.assertRaisesRegex(
                MODULE.EvidenceError, "bound-current-revision-check-not-unique"
            ):
                MODULE.bound_review_check(
                    pages,
                    repository="lightning-it/example",
                    pull=release_pull,
                    pull_number=17,
                    base_sha=BASE,
                    head_sha=HEAD,
                    merge_base_sha=BASE,
                )
        pages[0]["check_runs"][0]["output"]["summary"] = summary

        pages[0]["check_runs"][0]["output"]["title"] = "unbound title"
        with self.assertRaisesRegex(
            MODULE.EvidenceError, "bound-current-revision-check-not-unique"
        ):
            MODULE.bound_review_check(
                pages,
                repository="lightning-it/example",
                pull=release_pull,
                pull_number=17,
                base_sha=BASE,
                head_sha=HEAD,
                merge_base_sha=BASE,
            )
        pages[0]["check_runs"][0]["output"][
            "title"
        ] = "Protected Exact-Revision Codex review passed"

        failed_run = producer_run(
            login="lightning-it-release-automation[bot]", release=True
        )
        failed_run["conclusion"] = "failure"
        with mock.patch.object(MODULE, "gh_json", return_value=failed_run):
            with self.assertRaisesRegex(
                MODULE.EvidenceError, "producer-run-conclusion"
            ):
                MODULE.bound_review_check(
                    pages,
                    repository="lightning-it/example",
                    pull=release_pull,
                    pull_number=17,
                    base_sha=BASE,
                    head_sha=HEAD,
                    merge_base_sha=BASE,
                )

        untrusted = json.loads(summary)
        untrusted["workflow_sha"] = "9" * 40
        pages[0]["check_runs"][0]["output"]["summary"] = json.dumps(untrusted)
        with mock.patch.object(
            MODULE,
            "gh_json",
            return_value=producer_run(
                login="lightning-it-release-automation[bot]", release=True
            ),
        ):
            with self.assertRaisesRegex(
                MODULE.EvidenceError, "bound-current-revision-check-not-unique"
            ):
                MODULE.bound_review_check(
                    pages,
                    repository="lightning-it/example",
                    pull=release_pull,
                    pull_number=17,
                    base_sha=BASE,
                    head_sha=HEAD,
                    merge_base_sha=BASE,
                )

        for field in ("pull_request_number", "producer_run_id"):
            malformed = json.loads(summary)
            malformed[field] = True
            pages[0]["check_runs"][0]["output"]["summary"] = json.dumps(malformed)
            with self.assertRaisesRegex(
                MODULE.EvidenceError,
                f"review-summary-{'pull-request' if field == 'pull_request_number' else 'producer'}",
            ):
                MODULE.bound_review_check(
                    pages,
                    repository="lightning-it/example",
                    pull=release_pull,
                    pull_number=17,
                    base_sha=BASE,
                    head_sha=HEAD,
                    merge_base_sha=BASE,
                )

    def test_ancestry_exemption_requires_exact_ref_and_author_scope(self) -> None:
        release = ingress_pull(
            login="lightning-it-release-automation[bot]",
            user_id=307565056,
            user_type="Bot",
        )
        release["title"] = "chore(governance): record main ancestry before abc"
        release["head"]["ref"] = "backmerge/release-main"
        self.assertEqual(
            "ancestry-backmerge",
            MODULE.expected_evidence_kind(release, repository="lightning-it/example"),
        )
        release["head"]["ref"] = "backmerge/release"
        self.assertEqual(
            "release-app",
            MODULE.expected_evidence_kind(release, repository="lightning-it/example"),
        )

        managed = ingress_pull(
            login="lightning-it-shared-assets-sync[bot]",
            user_id=307342877,
            user_type="Bot",
        )
        managed["title"] = "chore(governance): record main ancestry before abc"
        managed["head"]["ref"] = "backmerge/sync-main"
        self.assertEqual(
            "ancestry-backmerge",
            MODULE.expected_evidence_kind(managed, repository="lightning-it/.github"),
        )
        with self.assertRaisesRegex(MODULE.EvidenceError, "ancestry-backmerge-author"):
            MODULE.expected_evidence_kind(managed, repository="lightning-it/example")

        release["head"]["ref"] = "backmerge/release-main"
        with (
            mock.patch.object(MODULE, "gh_json") as api,
            self.assertRaisesRegex(
                MODULE.EvidenceError,
                "ancestry-backmerge-not-structural-boundary",
            ),
        ):
            MODULE.collect_bound_ingress_evidence(
                repository="lightning-it/example",
                pull=release,
                pull_number=17,
                base_sha=BASE,
                head_sha=HEAD,
            )
        api.assert_not_called()

    def test_ancestry_boundary_requires_exact_controller_contract(self) -> None:
        boundary = ingress_pull(
            login="lightning-it-release-automation[bot]",
            user_id=307565056,
            user_type="Bot",
        )
        boundary["title"] = (
            f"chore(governance): record main ancestry before {BASE[:12]}"
        )
        boundary["base"] = {
            "ref": "develop",
            "repo": {"full_name": "lightning-it/example"},
        }
        boundary["head"]["ref"] = f"backmerge/example-{BASE[:12]}-{MERGE[:12]}-main"
        self.assertTrue(
            MODULE.is_authorized_ancestry_boundary(
                boundary,
                repository="lightning-it/example",
                expected_main=BASE,
                previous_develop=MERGE,
            )
        )
        ordinary = json.loads(json.dumps(boundary))
        ordinary["head"]["ref"] = "fix/ordinary"
        self.assertFalse(
            MODULE.is_authorized_ancestry_boundary(
                ordinary,
                repository="lightning-it/example",
                expected_main=BASE,
                previous_develop=MERGE,
            )
        )
        wrong_title = json.loads(json.dumps(boundary))
        wrong_title["title"] += "-changed"
        self.assertFalse(
            MODULE.is_authorized_ancestry_boundary(
                wrong_title,
                repository="lightning-it/example",
                expected_main=BASE,
                previous_develop=MERGE,
            )
        )

    def test_final_ref_validation_requires_protection_and_exact_tips(self) -> None:
        branches = {
            "repos/lightning-it/example/branches/main": {
                "name": "main",
                "protected": True,
                "commit": {"sha": BASE},
            },
            "repos/lightning-it/example/branches/develop": {
                "name": "develop",
                "protected": True,
                "commit": {"sha": HEAD},
            },
        }

        def branch_api(arguments: list[str]) -> dict[str, object]:
            return branches[arguments[-1]]

        with mock.patch.object(MODULE, "gh_json", side_effect=branch_api):
            MODULE.validate_protected_ref_tips(
                "lightning-it/example", expected_base=BASE, expected_head=HEAD
            )
        branches["repos/lightning-it/example/branches/main"]["protected"] = False
        with mock.patch.object(MODULE, "gh_json", side_effect=branch_api):
            with self.assertRaisesRegex(
                MODULE.EvidenceError, "final-main-not-protected"
            ):
                MODULE.validate_protected_ref_tips(
                    "lightning-it/example", expected_base=BASE, expected_head=HEAD
                )

    def test_repository_path_rejects_symlink_before_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "target"
            target.mkdir()
            link = Path(directory) / "repository"
            link.symlink_to(target, target_is_directory=True)
            with self.assertRaisesRegex(
                MODULE.EvidenceError, "repository-path-symlink"
            ):
                MODULE.validate_repository_path(link)

    def test_baseline_boundary_is_not_post_baseline_ingress(self) -> None:
        self.assertEqual((False, False), MODULE.classify_ingress_position(0, 1))
        self.assertEqual((True, False), MODULE.classify_ingress_position(1, 1))
        self.assertEqual((False, True), MODULE.classify_ingress_position(2, 1))

    def test_ancestry_boundary_requires_exact_merge_parents(self) -> None:
        with mock.patch.object(MODULE, "git", return_value=f"{MERGE} {BASE}"):
            self.assertTrue(
                MODULE.has_exact_ancestry_merge_parents(
                    ROOT,
                    head_sha=HEAD,
                    previous_develop=MERGE,
                    expected_main=BASE,
                )
            )
        with mock.patch.object(MODULE, "git", return_value=f"{MERGE} {'9' * 40}"):
            self.assertFalse(
                MODULE.has_exact_ancestry_merge_parents(
                    ROOT,
                    head_sha=HEAD,
                    previous_develop=MERGE,
                    expected_main=BASE,
                )
            )

    def test_historical_ancestry_boundary_uses_its_exact_main_parent(self) -> None:
        with mock.patch.object(MODULE, "git", return_value=f"{MERGE} {BASE}"):
            self.assertEqual(
                BASE,
                MODULE.ancestry_merge_main(
                    ROOT,
                    head_sha=HEAD,
                    previous_develop=MERGE,
                ),
            )
        with mock.patch.object(MODULE, "git", return_value=f"{'9' * 40} {BASE}"):
            self.assertIsNone(
                MODULE.ancestry_merge_main(
                    ROOT,
                    head_sha=HEAD,
                    previous_develop=MERGE,
                )
            )
        with mock.patch.object(MODULE, "git", return_value=MERGE):
            self.assertIsNone(
                MODULE.ancestry_merge_main(
                    ROOT,
                    head_sha=HEAD,
                    previous_develop=MERGE,
                )
            )

    def test_ancestry_boundary_content_is_exact(self) -> None:
        evidence = json.dumps(
            {
                "schema_version": 1,
                "repository": "lightning-it/example",
                "main_sha": BASE,
                "develop_parent_sha": MERGE,
                "purpose": "Bind the reviewed main ancestry backmerge.",
            }
        )

        def boundary_git(arguments: list[str], _: Path) -> str:
            if arguments == [
                "diff",
                "--no-renames",
                "--name-only",
                MERGE,
                HEAD,
                "--",
            ]:
                return ".lit/main-ancestry.json"
            if arguments == ["show", "-s", "--format=%s", HEAD]:
                return "merge: preserve develop tree and main ancestry"
            if arguments == ["show", f"{HEAD}:.lit/main-ancestry.json"]:
                return evidence
            if arguments == ["ls-tree", HEAD, "--", ".lit/main-ancestry.json"]:
                return f"100644 blob {'9' * 40}\t.lit/main-ancestry.json"
            raise AssertionError(arguments)

        with mock.patch.object(MODULE, "git", side_effect=boundary_git):
            MODULE.validate_ancestry_boundary_content(
                ROOT,
                repository="lightning-it/example",
                head_sha=HEAD,
                previous_develop=MERGE,
                expected_main=BASE,
            )

        def extra_file(arguments: list[str], path: Path) -> str:
            if arguments == [
                "diff",
                "--no-renames",
                "--name-only",
                MERGE,
                HEAD,
                "--",
            ]:
                return ".lit/main-ancestry.json\nextra"
            return boundary_git(arguments, path)

        with mock.patch.object(MODULE, "git", side_effect=extra_file):
            with self.assertRaisesRegex(
                MODULE.EvidenceError, "ancestry-boundary-content-scope"
            ):
                MODULE.validate_ancestry_boundary_content(
                    ROOT,
                    repository="lightning-it/example",
                    head_sha=HEAD,
                    previous_develop=MERGE,
                    expected_main=BASE,
                )

    def test_managed_sync_requires_exact_numeric_identity(self) -> None:
        managed = ingress_pull(
            login="lightning-it-shared-assets-sync[bot]",
            user_id=307342877,
            user_type="Bot",
        )
        self.assertEqual(
            "managed-sync",
            MODULE.expected_evidence_kind(managed, repository="lightning-it/example"),
        )
        managed["user"]["id"] = 1
        with self.assertRaisesRegex(MODULE.EvidenceError, "managed-sync-identity"):
            MODULE.expected_evidence_kind(managed, repository="lightning-it/example")

    def test_renovate_policy_rebinds_labels_head_and_edit_time(self) -> None:
        renovate = ingress_pull(
            login="renovate[bot]", user_id=29139614, user_type="Bot"
        )
        renovate["base"] = {"ref": "develop"}
        renovate["head"]["ref"] = "renovate/dependency"
        renovate["labels"] = [
            {"name": "safe-automerge"},
            {"name": "dependencies"},
            {"name": "renovate"},
        ]
        renovate["last_edited_at"] = None
        labels_json = b'["dependencies","renovate","safe-automerge"]'
        summary = {
            "pull_request_labels_sha256": hashlib.sha256(labels_json).hexdigest(),
            "pull_request_last_edited_at": None,
        }
        MODULE.validate_renovate_policy(
            renovate, summary, repository="lightning-it/example"
        )
        renovate["labels"].append({"name": "breaking-update"})
        with self.assertRaisesRegex(MODULE.EvidenceError, "renovate-breaking-label"):
            MODULE.validate_renovate_policy(
                renovate, summary, repository="lightning-it/example"
            )
        renovate["labels"].pop()
        renovate["user"]["id"] = 1
        with self.assertRaisesRegex(MODULE.EvidenceError, "renovate-identity"):
            MODULE.expected_evidence_kind(renovate, repository="lightning-it/example")

    def test_graphql_errors_fail_closed_before_partial_thread_data(self) -> None:
        partial = {
            "errors": [{"message": "partial result"}],
            "data": {
                "repository": {
                    "pullRequest": {
                        "number": 17,
                        "reviewThreads": {
                            "nodes": [],
                            "pageInfo": {
                                "hasNextPage": False,
                                "endCursor": None,
                            },
                        },
                    }
                }
            },
        }
        with mock.patch.object(MODULE, "gh_json", return_value=partial):
            with self.assertRaisesRegex(MODULE.EvidenceError, "thread-response-errors"):
                MODULE.collect_review_threads("lightning-it/example", 17)

    def test_review_summary_rejects_duplicate_keys_and_numeric_hashes(self) -> None:
        for raw in (
            '{"schema":4,"schema":4}',
            '{"schema":NaN}',
        ):
            with self.subTest(raw=raw), self.assertRaises(MODULE.EvidenceError):
                MODULE.review_summary(check_run("external", raw))

        summary = {
            "schema": 4,
            "base_sha": BASE,
            "head_sha": HEAD,
            "merge_base_sha": int("1" * 40),
            "integration_tree_sha": "3" * 40,
            "diff_sha256": "6" * 64,
            "input_sha256": INPUT,
            "pull_request_number": 17,
            "producer_run_id": 88,
            "run_url": "https://github.com/lightning-it/example/actions/runs/88",
            "workflow_sha": BASE,
        }
        release_pull = ingress_pull(
            login="lightning-it-release-automation[bot]",
            user_id=307565056,
            user_type="Bot",
        )
        pages = [
            {
                "check_runs": [
                    check_run(
                        f"mlx90-current-revision:v4:88:{INPUT}",
                        json.dumps(summary),
                        "Protected Exact-Revision Codex review passed",
                    )
                ]
            }
        ]
        with mock.patch.object(
            MODULE,
            "gh_json",
            return_value=producer_run(
                login="lightning-it-release-automation[bot]", release=True
            ),
        ):
            with self.assertRaisesRegex(
                MODULE.EvidenceError, "review-summary-merge-base"
            ):
                MODULE.bound_review_check(
                    pages,
                    repository="lightning-it/example",
                    pull=release_pull,
                    pull_number=17,
                    base_sha=BASE,
                    head_sha=HEAD,
                    merge_base_sha=BASE,
                )

    def test_review_kind_and_producer_identity_are_bound_to_pull_author(self) -> None:
        managed = f"mlx90-current-revision:managed-sync:v6:17:88:{BASE}:{HEAD}"
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
                MODULE.EvidenceError, "producer-run-actor-identity"
            ):
                MODULE.bound_review_check(
                    [{"check_runs": [check_run(copilot, v6_summary())]}],
                    repository="lightning-it/example",
                    pull=ingress_pull(),
                    pull_number=17,
                    base_sha=BASE,
                    head_sha=HEAD,
                    merge_base_sha=BASE,
                )

        for field, value in (("id", 2), ("type", "Bot")):
            wrong_identity = producer_run()
            wrong_identity["actor"][field] = value
            with mock.patch.object(
                MODULE, "gh_json", side_effect=evidence_api(wrong_identity)
            ):
                with self.assertRaisesRegex(
                    MODULE.EvidenceError, "producer-run-actor-identity"
                ):
                    MODULE.bound_review_check(
                        [{"check_runs": [check_run(copilot, v6_summary())]}],
                        repository="lightning-it/example",
                        pull=ingress_pull(),
                        pull_number=17,
                        base_sha=BASE,
                        head_sha=HEAD,
                    )

        for field, value in (("id", 2), ("type", "Bot")):
            wrong_trigger = producer_run()
            wrong_trigger["triggering_actor"] = dict(wrong_trigger["triggering_actor"])
            wrong_trigger["triggering_actor"][field] = value
            with mock.patch.object(
                MODULE, "gh_json", side_effect=evidence_api(wrong_trigger)
            ):
                with self.assertRaisesRegex(
                    MODULE.EvidenceError,
                    "producer-run-triggering-actor-identity",
                ):
                    MODULE.bound_review_check(
                        [{"check_runs": [check_run(copilot, v6_summary())]}],
                        repository="lightning-it/example",
                        pull=ingress_pull(),
                        pull_number=17,
                        base_sha=BASE,
                        head_sha=HEAD,
                    )

    def test_review_summary_rejects_boolean_integer_bindings(self) -> None:
        external_id = f"mlx90-current-revision:copilot:v6:17:88:{BASE}:{HEAD}"
        for field, label in (
            ("pull_request_number", "review-summary-pull-request"),
            ("producer_run_id", "review-summary-producer"),
        ):
            malformed = json.loads(v6_summary())
            malformed[field] = True
            with (
                self.subTest(field=field),
                mock.patch.object(
                    MODULE, "gh_json", side_effect=evidence_api(producer_run())
                ),
            ):
                with self.assertRaisesRegex(MODULE.EvidenceError, label):
                    MODULE.bound_review_check(
                        [
                            {
                                "check_runs": [
                                    check_run(external_id, json.dumps(malformed))
                                ]
                            }
                        ],
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
        with mock.patch.object(MODULE, "gh_json", side_effect=evidence_api(failed)):
            with self.assertRaisesRegex(
                MODULE.EvidenceError, "producer-run-job-count"
            ):
                MODULE.bound_review_check(
                    [{"check_runs": [check_run(external_id, v6_summary())]}],
                    repository="lightning-it/example",
                    pull=ingress_pull(),
                    pull_number=17,
                    base_sha=BASE,
                    head_sha=HEAD,
                    merge_base_sha=BASE,
                )

    def test_v6_accepts_only_exact_post_evidence_handoff_failure(self) -> None:
        external_id = f"mlx90-current-revision:copilot:v6:17:88:{BASE}:{HEAD}"
        run = producer_run()
        run["conclusion"] = "failure"
        exact_jobs = [
            {
                "id": 1,
                "run_id": 88,
                "run_attempt": 1,
                "head_sha": HEAD,
                "name": "Request Copilot review for current revision",
                "status": "completed",
                "conclusion": "success",
            },
            {
                "id": 2,
                "run_id": 88,
                "run_attempt": 1,
                "head_sha": HEAD,
                "name": "Verify current revision policy",
                "status": "completed",
                "conclusion": "success",
                "started_at": "2026-09-27T00:04:20Z",
                "completed_at": "2026-09-27T00:04:29Z",
            },
            {
                "id": 3,
                "run_id": 88,
                "run_attempt": 1,
                "head_sha": HEAD,
                "name": "Classify protected main trust-root handoff",
                "status": "completed",
                "conclusion": "skipped",
            },
            {
                "id": 4,
                "run_id": 88,
                "run_attempt": 1,
                "head_sha": HEAD,
                "name": (
                    "Request protected verifier re-evaluation / "
                    "Re-run the one protected verifier attempt"
                ),
                "status": "completed",
                "conclusion": "failure",
                "started_at": "2026-09-27T00:04:31Z",
                "completed_at": "2026-09-27T00:04:40Z",
            },
            {
                "id": 5,
                "run_id": 88,
                "run_attempt": 1,
                "head_sha": HEAD,
                "name": "Dispatch protected managed-sync finalizer re-evaluation",
                "status": "completed",
                "conclusion": "skipped",
            },
        ]
        with mock.patch.object(
            MODULE,
            "gh_json",
            side_effect=evidence_api(run, jobs=exact_jobs),
        ):
            evidence = MODULE.bound_review_check(
                [{"check_runs": [check_run(external_id, v6_summary())]}],
                repository="lightning-it/example",
                pull=ingress_pull(),
                pull_number=17,
                base_sha=BASE,
                head_sha=HEAD,
            )
        self.assertEqual(88, evidence["producer_run_id"])

        # GitHub may publish the neutral check after the failed handoff and
        # even after the producer run closes. The verified policy job, rather
        # than the asynchronous check publication, orders the handoff.
        delayed_check = check_run(external_id, v6_summary())
        delayed_check["completed_at"] = "2026-09-27T00:05:01Z"
        with mock.patch.object(
            MODULE, "gh_json", side_effect=evidence_api(run, jobs=exact_jobs)
        ):
            delayed = MODULE.bound_review_check(
                [{"check_runs": [delayed_check]}],
                repository="lightning-it/example",
                pull=ingress_pull(),
                pull_number=17,
                base_sha=BASE,
                head_sha=HEAD,
            )
        self.assertEqual(88, delayed["producer_run_id"])

        empty_association_run = dict(run)
        empty_association_run["pull_requests"] = []
        with mock.patch.object(
            MODULE,
            "gh_json",
            side_effect=evidence_api(empty_association_run, jobs=exact_jobs),
        ):
            delayed_without_association = MODULE.bound_review_check(
                [{"check_runs": [delayed_check]}],
                repository="lightning-it/example",
                pull=ingress_pull(),
                pull_number=17,
                base_sha=BASE,
                head_sha=HEAD,
            )
        self.assertEqual(88, delayed_without_association["producer_run_id"])

        for completed_at in (
            "2026-09-27T00:04:28Z",
            "2026-09-27T00:06:01Z",
        ):
            invalid_check = check_run(external_id, v6_summary())
            invalid_check["completed_at"] = completed_at
            with self.subTest(completed_at=completed_at):
                with mock.patch.object(
                    MODULE, "gh_json", side_effect=evidence_api(run, jobs=exact_jobs)
                ):
                    with self.assertRaisesRegex(
                        MODULE.EvidenceError, "producer-post-evidence-failure-order"
                    ):
                        MODULE.bound_review_check(
                            [{"check_runs": [invalid_check]}],
                            repository="lightning-it/example",
                            pull=ingress_pull(),
                            pull_number=17,
                            base_sha=BASE,
                            head_sha=HEAD,
                        )

        for mutate, reason in (
            (
                lambda candidate: candidate[1].update({"conclusion": "failure"}),
                "producer-run-job-binding",
            ),
            (
                lambda candidate: candidate[0].update({"run_id": 89}),
                "producer-run-job-binding",
            ),
            (
                lambda candidate: candidate[1].update({"run_attempt": 2}),
                "producer-run-job-binding",
            ),
            (
                lambda candidate: candidate[2].update({"head_sha": "9" * 40}),
                "producer-run-job-binding",
            ),
            (
                lambda candidate: candidate[1].update(
                    {"completed_at": "2026-09-27T00:04:32Z"}
                ),
                "producer-post-evidence-failure-order",
            ),
            (
                lambda candidate: candidate.append(
                    {
                        "id": 6,
                        "name": "Unexpected job",
                        "status": "completed",
                        "conclusion": "success",
                    }
                ),
                "producer-run-job-count",
            ),
        ):
            candidate = [dict(job) for job in exact_jobs]
            mutate(candidate)
            with mock.patch.object(
                MODULE,
                "gh_json",
                side_effect=evidence_api(run, jobs=candidate),
            ):
                with self.assertRaisesRegex(MODULE.EvidenceError, reason):
                    MODULE.bound_review_check(
                        [{"check_runs": [check_run(external_id, v6_summary())]}],
                        repository="lightning-it/example",
                        pull=ingress_pull(),
                        pull_number=17,
                        base_sha=BASE,
                        head_sha=HEAD,
                    )

    def test_managed_sync_v6_accepts_only_exact_post_evidence_handoff_failure(self) -> None:
        managed = ingress_pull(
            login="lightning-it-shared-assets-sync[bot]",
            user_id=307342877,
            user_type="Bot",
        )
        managed["labels"] = []
        run = producer_run(login="lightning-it-shared-assets-sync[bot]")
        run["actor"]["id"] = 307342877
        run["triggering_actor"]["id"] = 307342877
        run["conclusion"] = "failure"
        run["pull_requests"] = []
        external_id = f"mlx90-current-revision:managed-sync:v6:17:88:{BASE}:{HEAD}"
        check = check_run(
            external_id,
            expanded_v6_summary("managed-sync"),
            "Current revision managed distribution exemption passed",
        )
        outcomes = (
            ("Request Copilot review for current revision", "skipped"),
            ("Verify current revision policy", "success"),
            ("Classify protected main trust-root handoff", "skipped"),
            (
                "Request protected verifier re-evaluation / "
                "Re-run the one protected verifier attempt",
                "failure",
            ),
            ("Dispatch protected managed-sync finalizer re-evaluation", "success"),
        )
        exact_jobs = [
            {
                "id": index,
                "run_id": 88,
                "run_attempt": 1,
                "head_sha": HEAD,
                "name": name,
                "status": "completed",
                "conclusion": conclusion,
                "started_at": (
                    "2026-09-27T00:04:20Z"
                    if name == "Verify current revision policy"
                    else "2026-09-27T00:04:31Z"
                ),
                "completed_at": (
                    "2026-09-27T00:04:29Z"
                    if name == "Verify current revision policy"
                    else "2026-09-27T00:04:40Z"
                ),
            }
            for index, (name, conclusion) in enumerate(outcomes, start=1)
        ]

        def verify(jobs):
            with mock.patch.object(
                MODULE, "gh_json", side_effect=evidence_api(run, jobs=jobs)
            ):
                return MODULE.bound_review_check(
                    [{"check_runs": [check]}],
                    repository="lightning-it/example",
                    pull=managed,
                    pull_number=17,
                    base_sha=BASE,
                    head_sha=HEAD,
                )

        evidence = verify(exact_jobs)
        self.assertEqual("managed-sync", evidence["evidence_kind"])
        self.assertEqual(88, evidence["producer_run_id"])

        check["completed_at"] = "2026-09-27T00:05:01Z"
        self.assertEqual(88, verify(exact_jobs)["producer_run_id"])
        check["completed_at"] = "2026-09-27T00:04:30Z"

        for index, field, value, reason in (
            (0, "conclusion", "success", "producer-run-job-binding"),
            (1, "conclusion", "failure", "producer-run-job-binding"),
            (4, "conclusion", "failure", "producer-run-job-binding"),
            (4, "conclusion", "skipped", "producer-run-job-binding"),
            (0, "run_id", 89, "producer-run-job-binding"),
            (1, "run_attempt", 2, "producer-run-job-binding"),
            (2, "head_sha", "9" * 40, "producer-run-job-binding"),
            (4, "status", "in_progress", "producer-run-job-binding"),
            (4, "id", 1, "producer-run-job-topology"),
            (4, "name", "Unexpected job", "producer-run-job-binding"),
            (4, "name", outcomes[0][0], "producer-run-job-binding"),
            (
                1,
                "completed_at",
                "2026-09-27T00:04:32Z",
                "producer-post-evidence-failure-order",
            ),
        ):
            jobs = [dict(job) for job in exact_jobs]
            jobs[index][field] = value
            with self.subTest(index=index, field=field, value=value):
                with self.assertRaisesRegex(MODULE.EvidenceError, reason):
                    verify(jobs)
        for jobs in (exact_jobs[:-1], exact_jobs + [dict(exact_jobs[0])]):
            with self.assertRaisesRegex(MODULE.EvidenceError, "producer-run-job-count"):
                verify(jobs)
        for attempt in (2, 3):
            run["run_attempt"] = attempt
            with self.assertRaisesRegex(
                MODULE.EvidenceError, "producer-rerun-kind|producer-run-attempt"
            ):
                verify(exact_jobs)

    def test_v6_accepts_exact_expanded_review_metadata(self) -> None:
        external_id = f"mlx90-current-revision:copilot:v6:17:88:{BASE}:{HEAD}"
        pull = ingress_pull()
        pull["labels"] = []
        with mock.patch.object(
            MODULE, "gh_json", side_effect=evidence_api(producer_run())
        ):
            evidence = MODULE.bound_review_check(
                [{"check_runs": [check_run(external_id, expanded_v6_summary())]}],
                repository="lightning-it/example",
                pull=pull,
                pull_number=17,
                base_sha=BASE,
                head_sha=HEAD,
            )
        self.assertEqual("v6", evidence["evidence_version"])
        self.assertEqual("copilot", evidence["evidence_kind"])

    def test_v6_accepts_exact_expanded_managed_sync_metadata(self) -> None:
        managed = ingress_pull(
            login="lightning-it-shared-assets-sync[bot]",
            user_id=307342877,
            user_type="Bot",
        )
        managed["labels"] = []
        run = producer_run(login="lightning-it-shared-assets-sync[bot]")
        run["actor"]["id"] = 307342877
        run["triggering_actor"]["id"] = 307342877
        external_id = (
            f"mlx90-current-revision:managed-sync:v6:17:88:{BASE}:{HEAD}"
        )
        with mock.patch.object(
            MODULE, "gh_json", side_effect=evidence_api(run)
        ):
            evidence = MODULE.bound_review_check(
                [
                    {
                        "check_runs": [
                            check_run(
                                external_id,
                                expanded_v6_summary("managed-sync"),
                                (
                                    "Current revision managed distribution "
                                    "exemption passed"
                                ),
                            )
                        ]
                    }
                ],
                repository="lightning-it/example",
                pull=managed,
                pull_number=17,
                base_sha=BASE,
                head_sha=HEAD,
            )
        self.assertEqual("v6", evidence["evidence_version"])
        self.assertEqual("managed-sync", evidence["evidence_kind"])

    def test_v6_accepts_expanded_managed_sync_without_run_association(self) -> None:
        managed = ingress_pull(
            login="lightning-it-shared-assets-sync[bot]",
            user_id=307342877,
            user_type="Bot",
        )
        managed["labels"] = []
        run = producer_run(login="lightning-it-shared-assets-sync[bot]")
        run["actor"]["id"] = 307342877
        run["triggering_actor"]["id"] = 307342877
        run["pull_requests"] = []
        external_id = (
            f"mlx90-current-revision:managed-sync:v6:17:88:{BASE}:{HEAD}"
        )
        with mock.patch.object(
            MODULE, "gh_json", side_effect=evidence_api(run)
        ):
            evidence = MODULE.bound_review_check(
                [
                    {
                        "check_runs": [
                            check_run(
                                external_id,
                                expanded_v6_summary("managed-sync"),
                                (
                                    "Current revision managed distribution "
                                    "exemption passed"
                                ),
                            )
                        ]
                    }
                ],
                repository="lightning-it/example",
                pull=managed,
                pull_number=17,
                base_sha=BASE,
                head_sha=HEAD,
            )
        self.assertEqual("v6", evidence["evidence_version"])
        self.assertEqual("managed-sync", evidence["evidence_kind"])

    def test_v6_expanded_managed_sync_empty_association_binds_time(self) -> None:
        managed = ingress_pull(
            login="lightning-it-shared-assets-sync[bot]",
            user_id=307342877,
            user_type="Bot",
        )
        managed["labels"] = []
        run = producer_run(login="lightning-it-shared-assets-sync[bot]")
        run["actor"]["id"] = 307342877
        run["triggering_actor"]["id"] = 307342877
        run["pull_requests"] = []
        run["updated_at"] = "2026-09-27T00:03:00Z"
        external_id = (
            f"mlx90-current-revision:managed-sync:v6:17:88:{BASE}:{HEAD}"
        )
        with (
            mock.patch.object(MODULE, "gh_json", side_effect=evidence_api(run)),
            self.assertRaisesRegex(
                MODULE.EvidenceError, "producer-managed-sync-time-binding"
            ),
        ):
            MODULE.bound_review_check(
                [
                    {
                        "check_runs": [
                            check_run(
                                external_id,
                                expanded_v6_summary("managed-sync"),
                                (
                                    "Current revision managed distribution "
                                    "exemption passed"
                                ),
                            )
                        ]
                    }
                ],
                repository="lightning-it/example",
                pull=managed,
                pull_number=17,
                base_sha=BASE,
                head_sha=HEAD,
            )

    def test_v6_expanded_managed_sync_requires_null_review_id(self) -> None:
        managed = ingress_pull(
            login="lightning-it-shared-assets-sync[bot]",
            user_id=307342877,
            user_type="Bot",
        )
        managed["labels"] = []
        run = producer_run(login="lightning-it-shared-assets-sync[bot]")
        run["actor"]["id"] = 307342877
        run["triggering_actor"]["id"] = 307342877
        summary = json.loads(expanded_v6_summary("managed-sync"))
        summary["review_id"] = "PRR_kwDOQs6tNc8AAAABPj6qbQ"
        external_id = (
            f"mlx90-current-revision:managed-sync:v6:17:88:{BASE}:{HEAD}"
        )
        with (
            mock.patch.object(MODULE, "gh_json", side_effect=evidence_api(run)),
            self.assertRaisesRegex(
                MODULE.EvidenceError, "managed-sync-review-id"
            ),
        ):
            MODULE.bound_review_check(
                [
                    {
                        "check_runs": [
                            check_run(
                                external_id,
                                json.dumps(summary),
                                (
                                    "Current revision managed distribution "
                                    "exemption passed"
                                ),
                            )
                        ]
                    }
                ],
                repository="lightning-it/example",
                pull=managed,
                pull_number=17,
                base_sha=BASE,
                head_sha=HEAD,
            )

    def test_v6_expanded_review_metadata_fails_closed(self) -> None:
        external_id = f"mlx90-current-revision:copilot:v6:17:88:{BASE}:{HEAD}"
        cases = (
            ("head_repository", "fork/example", "review-summary-head-repository"),
            ("controller_ref", "main", "review-summary-controller-ref"),
            ("pull_request_labels_sha256", "7" * 64, "review-summary-labels-mutated"),
            (
                "pull_request_last_edited_at",
                "2026-09-28T00:00:00Z",
                "review-summary-last-edited-at-mutated",
            ),
            ("review_id", "not-a-review", "review-summary-review-id"),
            (
                "review_id",
                "PRR_kwDOQs6tNc8AAAABDifferent",
                "review-summary-review-binding",
            ),
        )
        for field, value, error in cases:
            summary = json.loads(expanded_v6_summary())
            summary[field] = value
            pull = ingress_pull()
            pull["labels"] = []
            pull["last_edited_at"] = None
            with (
                self.subTest(field=field),
                mock.patch.object(
                    MODULE, "gh_json", side_effect=evidence_api(producer_run())
                ),
                self.assertRaisesRegex(MODULE.EvidenceError, error),
            ):
                MODULE.bound_review_check(
                    [{"check_runs": [check_run(external_id, json.dumps(summary))]}],
                    repository="lightning-it/example",
                    pull=pull,
                    pull_number=17,
                    base_sha=BASE,
                    head_sha=HEAD,
                )

        summary = json.loads(expanded_v6_summary())
        summary["unexpected"] = True
        pull = ingress_pull()
        pull["labels"] = []
        pull["last_edited_at"] = None
        with self.assertRaisesRegex(MODULE.EvidenceError, "review-summary-schema"):
            MODULE.bound_review_check(
                [{"check_runs": [check_run(external_id, json.dumps(summary))]}],
                repository="lightning-it/example",
                pull=pull,
                pull_number=17,
                base_sha=BASE,
                head_sha=HEAD,
            )

    def test_v6_expanded_review_metadata_rebinds_graphql_edit_time(self) -> None:
        external_id = f"mlx90-current-revision:copilot:v6:17:88:{BASE}:{HEAD}"
        delegate = evidence_api(producer_run())

        def api_with_edit_response(payload: dict[str, object]):
            def dispatch(arguments: list[str]) -> dict[str, object]:
                if arguments[:2] == ["api", "graphql"] and any(
                    "lastEditedAt" in argument for argument in arguments
                ):
                    return payload
                return delegate(arguments)

            return dispatch

        cases = (
            (
                {"errors": [{"message": "partial"}], "data": {}},
                "review-summary-edit-response-errors",
            ),
            (
                {
                    "data": {
                        "repository": {"pullRequest": {"number": 17}}
                    }
                },
                "review-summary-live-last-edited-at",
            ),
            (
                {
                    "data": {
                        "repository": {
                            "pullRequest": {
                                "number": 17,
                                "lastEditedAt": "not-a-timestamp",
                            }
                        }
                    }
                },
                "review-summary-live-last-edited-at-not-timestamp",
            ),
            (
                {
                    "data": {
                        "repository": {
                            "pullRequest": {
                                "number": 17,
                                "lastEditedAt": "2026-09-28T00:00:00Z",
                            }
                        }
                    }
                },
                "review-summary-last-edited-at-mutated",
            ),
        )
        for payload, error in cases:
            pull = ingress_pull()
            pull["labels"] = []
            with (
                self.subTest(error=error),
                mock.patch.object(
                    MODULE,
                    "gh_json",
                    side_effect=api_with_edit_response(payload),
                ),
                self.assertRaisesRegex(MODULE.EvidenceError, error),
            ):
                MODULE.bound_review_check(
                    [{"check_runs": [check_run(external_id, expanded_v6_summary())]}],
                    repository="lightning-it/example",
                    pull=pull,
                    pull_number=17,
                    base_sha=BASE,
                    head_sha=HEAD,
                )

    def test_expanded_fallback_reuses_one_review_inventory_snapshot(self) -> None:
        external_id = f"mlx90-current-revision:copilot:v6:17:88:{BASE}:{HEAD}"
        run = producer_run()
        run["pull_requests"] = []
        pull = ingress_pull()
        pull["labels"] = []
        pull["last_edited_at"] = None
        delegate = evidence_api(run)
        review_calls = 0

        def mutating_api(arguments: list[str]) -> dict[str, object]:
            nonlocal review_calls
            if arguments[-1] == (
                "repos/lightning-it/example/pulls/17/reviews?per_page=100"
            ):
                review_calls += 1
                if review_calls > 1:
                    replacement = delegate(arguments)
                    replacement[0][0]["node_id"] = "PRR_kwDOQs6tNc8AAAABReplacement"
                    return replacement
            return delegate(arguments)

        with mock.patch.object(MODULE, "gh_json", side_effect=mutating_api):
            evidence = MODULE.bound_review_check(
                [{"check_runs": [check_run(external_id, expanded_v6_summary())]}],
                repository="lightning-it/example",
                pull=pull,
                pull_number=17,
                base_sha=BASE,
                head_sha=HEAD,
            )
        self.assertEqual("v6", evidence["evidence_version"])
        self.assertEqual(1, review_calls)

    def test_expanded_fallback_uses_bound_review_instead_of_stale_overview(self) -> None:
        external_id = f"mlx90-current-revision:copilot:v6:17:88:{BASE}:{HEAD}"
        run = producer_run()
        run["pull_requests"] = []
        pull = ingress_pull()
        pull["labels"] = []
        pull["last_edited_at"] = None
        stale_overview = {
            "id": 17001,
            "node_id": "PRR_kwDOQs6tNc8AAAABPj6qbQ",
            "user": {
                "login": "copilot-pull-request-reviewer[bot]",
                "id": 175728472,
                "type": "Bot",
            },
            "state": "COMMENTED",
            "commit_id": HEAD,
            "submitted_at": "2026-09-27T00:04:00Z",
            "body": (
                "<!-- ccr-overview-v2 -->\n\n"
                "## Copilot review overview\n\n"
                "### 🟢 Approval recommended\n\n"
                "**Findings:** 1\n\n"
                "<details open><summary><strong>Open (1)</strong></summary>"
                "Previously reported finding"
                "</details>"
            ),
        }
        delegate = evidence_api(run, review=stale_overview)
        comment_calls = 0

        def tracked_api(arguments: list[str]) -> dict[str, object]:
            nonlocal comment_calls
            if arguments[-1] == (
                "repos/lightning-it/example/pulls/17/reviews/17001/"
                "comments?per_page=100"
            ):
                comment_calls += 1
            return delegate(arguments)

        with mock.patch.object(MODULE, "gh_json", side_effect=tracked_api):
            evidence = MODULE.bound_review_check(
                [{"check_runs": [check_run(external_id, expanded_v6_summary())]}],
                repository="lightning-it/example",
                pull=pull,
                pull_number=17,
                base_sha=BASE,
                head_sha=HEAD,
            )
        self.assertEqual("v6", evidence["evidence_version"])
        self.assertEqual("copilot", evidence["evidence_kind"])
        self.assertEqual(0, comment_calls)

    def test_expanded_positive_findings_require_native_thread_coverage(self) -> None:
        external_id = f"mlx90-current-revision:copilot:v6:17:88:{BASE}:{HEAD}"
        check = check_run(external_id, expanded_v6_summary())
        run = producer_run()
        run["pull_requests"] = []
        pull = ingress_pull()
        pull["labels"] = []
        review = {
            "id": 17001,
            "node_id": "PRR_kwDOQs6tNc8AAAABPj6qbQ",
            "user": {"login": "copilot-pull-request-reviewer[bot]",
                     "id": 175728472, "type": "Bot"},
            "state": "COMMENTED", "commit_id": HEAD,
            "submitted_at": "2026-09-27T00:04:00Z",
            "body": ("<!-- ccr-overview-v2 -->\n"
                     "## Copilot review overview\n"
                     "**Findings:** 1\n"
                     "<strong>Open (1)</strong>"),
        }
        delegate = evidence_api(run, review=review)

        def api(arguments):
            if "check-runs?check_name=" in arguments[-1]:
                return [{"check_runs": [check]}]
            return delegate(arguments)

        for nodes in ([], [{"id": "PRRT_1", "isResolved": True}]):
            with (
                self.subTest(nodes=nodes),
                mock.patch.object(MODULE, "gh_json", side_effect=api),
                mock.patch.object(
                    MODULE, "collect_review_threads",
                    return_value={
                        "nodes": nodes, "pageInfo": {"hasNextPage": False},
                    },
                ),
            ):
                if nodes:
                    result = MODULE.collect_bound_ingress_evidence(
                        repository="lightning-it/example",
                        pull=pull, pull_number=17,
                        base_sha=BASE, head_sha=HEAD,
                    )
                    self.assertEqual(
                        1, result["review"]["historical_findings_count"]
                    )
                else:
                    with self.assertRaisesRegex(
                        MODULE.EvidenceError, "producer-review-thread-coverage"
                    ):
                        MODULE.collect_bound_ingress_evidence(
                            repository="lightning-it/example",
                            pull=pull, pull_number=17,
                            base_sha=BASE, head_sha=HEAD,
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

    def test_verify_aggregates_ingress_and_rejects_final_promotion_mutation(
        self,
    ) -> None:
        pre_boundary_head = "6" * 40
        pre_boundary_merge = "d" * 40
        boundary_head = "7" * 40
        boundary_merge = "8" * 40
        feature_merge = "9" * 40
        historical_main = "c" * 40
        pre_boundary = ingress_pull(
            login="lightning-it-release-automation[bot]",
            user_id=307565056,
            user_type="Bot",
        )
        pre_boundary.update(
            {
                "number": 16,
                "state": "closed",
                "merged_at": "2026-09-26T23:00:00Z",
                "merge_commit_sha": pre_boundary_merge,
            }
        )
        pre_boundary["base"].update(
            {"ref": "develop", "repo": {"full_name": "lightning-it/example"}}
        )
        pre_boundary["head"].update(
            {
                "ref": (
                    f"backmerge/example-{historical_main[:12]}-"
                    f"{'a' * 12}-main"
                ),
                "sha": pre_boundary_head,
                "repo": {"full_name": "lightning-it/example"},
            }
        )
        pre_boundary["title"] = (
            f"chore(governance): record main ancestry before {historical_main[:12]}"
        )
        boundary = ingress_pull(
            login="lightning-it-release-automation[bot]",
            user_id=307565056,
            user_type="Bot",
        )
        boundary.update(
            {
                "number": 10,
                "state": "closed",
                "merged_at": "2026-09-27T00:00:00Z",
                "merge_commit_sha": boundary_merge,
            }
        )
        boundary["base"].update(
            {"ref": "develop", "repo": {"full_name": "lightning-it/example"}}
        )
        boundary["head"].update(
            {
                "ref": (
                    f"backmerge/example-{BASE[:12]}-"
                    f"{pre_boundary_merge[:12]}-main"
                ),
                "sha": boundary_head,
                "repo": {"full_name": "lightning-it/example"},
            }
        )
        boundary["title"] = (
            f"chore(governance): record main ancestry before {BASE[:12]}"
        )
        feature = ingress_pull()
        feature.update(
            {
                "state": "closed",
                "merged_at": "2026-09-27T01:00:00Z",
                "merge_commit_sha": feature_merge,
            }
        )
        feature["base"].update(
            {"ref": "develop", "repo": {"full_name": "lightning-it/example"}}
        )
        merges = [
            {
                "base_sha": "a" * 40,
                "head_sha": pre_boundary_head,
                "merge_sha": pre_boundary_merge,
            },
            {
                "base_sha": pre_boundary_merge,
                "head_sha": boundary_head,
                "merge_sha": boundary_merge,
            },
            {
                "base_sha": boundary_merge,
                "head_sha": HEAD,
                "merge_sha": feature_merge,
            },
        ]
        bound = {
            "review": {"check_id": 99, "summary_sha256": "6" * 64},
            "threads": {"resolved_thread_ids": [], "unresolved_threads": 0},
        }

        def execute(
            *, mutate_final_pull: bool, reviewed_release: bool = False,
            missing_release_review: bool = False, late_baseline: bool = False,
            change_kind: str = "feature", missing_feature_review: bool = False,
            mutated_feature_review: bool = False,
        ) -> dict[str, object]:
            current = promotion()
            pull_reads = 0
            api_calls: list[str] = []
            active_boundary = json.loads(json.dumps(boundary))
            active_feature = json.loads(json.dumps(feature))
            active_merges = json.loads(json.dumps(merges))
            if change_kind == "structural":
                active_feature["user"] = pre_boundary["user"]
                active_feature["title"] = pre_boundary["title"]
                active_feature["head"]["ref"] = (
                    f"backmerge/example-{historical_main[:12]}-"
                    f"{boundary_merge[:12]}-main"
                )
            if late_baseline:
                active_merges = [active_merges[0], active_merges[2], active_merges[1]]
                active_merges[1]["base_sha"] = pre_boundary_merge
                active_merges[2]["base_sha"] = feature_merge
                active_boundary["head"]["ref"] = (
                    f"backmerge/example-{BASE[:12]}-{feature_merge[:12]}-main"
                )
                active_feature["merged_at"] = "2026-09-26T23:30:00Z"
            if change_kind == "absent":
                active_merges = json.loads(json.dumps(merges[:2]))
            if reviewed_release:
                active_boundary["user"] = {"login": "litroc", "id": 1, "type": "User"}
                active_boundary["title"] = "chore(release): sync v1.14.0 back to develop"
                active_boundary["head"]["ref"] = "backsync/release-v1.14.0-to-develop"

            feature_reads = 0

            def collect(**kwargs: object) -> dict[str, object]:
                nonlocal feature_reads
                if missing_release_review and kwargs["pull_number"] == 10:
                    raise MODULE.EvidenceError("no-current-head-review")
                if kwargs["pull_number"] == 17:
                    feature_reads += 1
                    if missing_feature_review:
                        raise MODULE.EvidenceError("no-current-head-review")
                    if mutated_feature_review and feature_reads == 2:
                        return {**bound, "review": {"check_id": 100}}
                return bound

            def api(arguments: list[str]) -> object:
                nonlocal pull_reads
                endpoint = arguments[-1]
                api_calls.append(endpoint)
                if endpoint == "repos/lightning-it/example/pulls/41":
                    pull_reads += 1
                    value = json.loads(json.dumps(current))
                    if mutate_final_pull and pull_reads == 2:
                        value["body"] = "mutated release"
                    return value
                if endpoint == f"repos/lightning-it/example/commits/{BASE}":
                    return {
                        "sha": BASE,
                        "commit": {
                            "verification": {"verified": True, "reason": "valid"},
                            "committer": {"date": "2026-09-27T00:00:00Z"},
                        },
                    }
                if endpoint.endswith(f"commits/{boundary_merge}/pulls?per_page=100"):
                    return [[active_boundary]]
                if endpoint.endswith(
                    f"commits/{pre_boundary_merge}/pulls?per_page=100"
                ):
                    return [[pre_boundary]]
                if endpoint.endswith(f"commits/{feature_merge}/pulls?per_page=100"):
                    return [[active_feature]]
                if endpoint == "repos/lightning-it/example/pulls/10":
                    return active_boundary
                if endpoint == "repos/lightning-it/example/pulls/16":
                    return pre_boundary
                if endpoint == "repos/lightning-it/example/pulls/17":
                    return active_feature
                if endpoint == "repos/lightning-it/example/branches/main":
                    return {"name": "main", "protected": True, "commit": {"sha": BASE}}
                if endpoint == "repos/lightning-it/example/branches/develop":
                    return {
                        "name": "develop",
                        "protected": True,
                        "commit": {"sha": HEAD},
                    }
                raise AssertionError(endpoint)

            with tempfile.TemporaryDirectory() as directory:
                runtime = Path(directory).resolve(strict=True)
                repository = runtime / "repository"
                repository.mkdir()
                output = runtime / "promotion-evidence.json"
                arguments = MODULE.argparse.Namespace(
                    repository="lightning-it/example",
                    pull_request=41,
                    base_ref="main",
                    head_ref="develop",
                    expected_base=BASE,
                    expected_head=HEAD,
                    controller_sha="5" * 40,
                    expected_body_sha256=hashlib.sha256(b"release").hexdigest(),
                    repository_path=repository,
                    output=output,
                )
                previous = os.environ.get("RUNNER_TEMP")
                os.environ["RUNNER_TEMP"] = str(runtime)
                try:
                    with (
                        mock.patch.object(MODULE, "gh_json", side_effect=api),
                        mock.patch.object(
                            MODULE,
                            "first_parent_merges",
                            return_value=("a" * 40, "b" * 40, active_merges),
                        ),
                        mock.patch.object(
                            MODULE,
                            "compute_diff",
                            return_value={"bytes": 707454, "sha256": "c" * 64},
                        ),
                        mock.patch.object(
                            MODULE,
                            "is_ancestor",
                            side_effect=lambda _path, _ancestor, descendant: not reviewed_release
                            or descendant in {boundary_head, boundary_merge}
                            or (not late_baseline and descendant in {HEAD, feature_merge}),
                        ),
                        mock.patch.object(
                            MODULE,
                            "has_exact_ancestry_merge_parents",
                            side_effect=lambda _repository, *, head_sha, **_kwargs: head_sha
                            == boundary_head and not reviewed_release,
                        ),
                        mock.patch.object(
                            MODULE,
                            "ancestry_merge_main",
                            side_effect=lambda _repository, *, head_sha, **_kwargs: (
                                historical_main
                                if head_sha == pre_boundary_head
                                or (head_sha == HEAD and change_kind == "structural")
                                else BASE if head_sha == boundary_head else None
                            ),
                        ),
                        mock.patch.object(MODULE, "validate_ancestry_boundary_content"),
                        mock.patch.object(MODULE, "validate_reviewed_release_baseline") as release_binding,
                        mock.patch.object(MODULE, "git", return_value=BASE),
                        mock.patch.object(
                            MODULE,
                            "collect_bound_ingress_evidence",
                            side_effect=collect,
                        ) as native_evidence,
                    ):
                        value = MODULE.verify(arguments)
                        MODULE.write_output(output, value)
                    self.assertEqual(3, value["ingress_count"])
                    self.assertEqual(0 if late_baseline else 1, value["post_baseline_ingress_count"])
                    self.assertEqual(1, value["reviewed_change_ingress_count"])
                    self.assertTrue(value["ingress"][0]["ancestry_boundary"])
                    baseline_index = 2 if late_baseline else 1
                    feature_index = 1 if late_baseline else 2
                    self.assertEqual(not reviewed_release, value["ingress"][baseline_index]["ancestry_boundary"])
                    self.assertTrue(value["ingress"][baseline_index]["baseline_reconciliation"])
                    self.assertFalse(value["ingress"][feature_index]["baseline_reconciliation"])
                    self.assertFalse(value["ingress"][feature_index]["ancestry_boundary"])
                    self.assertEqual(bound["review"], value["ingress"][feature_index]["review"])
                    self.assertEqual(2, feature_reads)
                    self.assertIsNone(value["ingress"][0]["review"])
                    if reviewed_release:
                        self.assertEqual(bound["review"], value["ingress"][baseline_index]["review"])
                        self.assertEqual(bound["threads"], value["ingress"][baseline_index]["threads"])
                        self.assertEqual(2, release_binding.call_count)
                        self.assertEqual(
                            2,
                            sum(call.kwargs["pull_number"] == 10 for call in native_evidence.call_args_list),
                        )
                    else:
                        release_binding.assert_not_called()
                    self.assertNotIn("promotion_review", value)
                    self.assertEqual(value, json.loads(output.read_text()))
                    self.assertEqual(
                        [
                            "repos/lightning-it/example/pulls/16",
                            f"repos/lightning-it/example/pulls/{17 if late_baseline else 10}",
                            f"repos/lightning-it/example/pulls/{10 if late_baseline else 17}",
                        ],
                        api_calls[-3:],
                    )
                    return value
                finally:
                    if previous is None:
                        os.environ.pop("RUNNER_TEMP", None)
                    else:
                        os.environ["RUNNER_TEMP"] = previous

        execute(mutate_final_pull=False, reviewed_release=True, late_baseline=True)
        execute(mutate_final_pull=False)
        execute(mutate_final_pull=False, reviewed_release=True)
        for reviewed_release in (False, True):
            with self.subTest(reviewed_release=reviewed_release):
                execute(mutate_final_pull=False, reviewed_release=reviewed_release, late_baseline=True)
                for change_kind in ("absent", "structural"):
                    with self.assertRaisesRegex(MODULE.EvidenceError, "no-reviewed-change-ingress"):
                        execute(mutate_final_pull=False, reviewed_release=reviewed_release, change_kind=change_kind)
                with self.assertRaisesRegex(MODULE.EvidenceError, "ingress-pr-17:no-current-head-review"):
                    execute(mutate_final_pull=False, reviewed_release=reviewed_release, late_baseline=True, missing_feature_review=True)
                with self.assertRaisesRegex(MODULE.EvidenceError, "ingress-pr-17:ingress-evidence-mutated"):
                    execute(mutate_final_pull=False, reviewed_release=reviewed_release, late_baseline=True, mutated_feature_review=True)
                with self.assertRaisesRegex(MODULE.EvidenceError, "promotion-event-body-mismatch"):
                    execute(mutate_final_pull=True, reviewed_release=reviewed_release, late_baseline=True)
        with self.assertRaisesRegex(MODULE.EvidenceError, "ingress-pr-10:no-current-head-review"):
            execute(mutate_final_pull=False, reviewed_release=True, missing_release_review=True)
        with self.assertRaisesRegex(
            MODULE.EvidenceError, "promotion-event-body-mismatch"
        ):
            execute(mutate_final_pull=True)

    def test_workflow_package_gate_accepts_reviewed_prebaseline_changes_only(self) -> None:
        aggregate = WORKFLOW.read_text().split(
            "      - name: Aggregate exact protected ingress evidence\n", 1
        )[1].split("      - name: Persist exact promotion evidence package\n", 1)[0]
        predicate = aggregate.split(
            '--argjson pull_request "${PR_NUMBER}" \'', 1
        )[1].split('\' "${output}" >/dev/null', 1)[0]
        package = {
            "schema_version": 1, "repository": "lightning-it/example",
            "pull_request": 41, "base_sha": BASE, "head_sha": HEAD,
            "controller_sha": "5" * 40, "ingress_count": 2,
            "post_baseline_ingress_count": 0, "reviewed_change_ingress_count": 1,
            "diff": {"bytes": 100, "sha256": "6" * 64},
            "evidence_sha256": "7" * 64,
            "ingress": [
                {"ancestry_boundary": False, "baseline_reconciliation": False,
                 "post_baseline": False, "review": {}, "threads": {}},
                {"ancestry_boundary": False, "baseline_reconciliation": True,
                 "post_baseline": False, "review": {}, "threads": {}},
            ],
        }

        def accepted(value: dict[str, object]) -> bool:
            result = subprocess.run(
                ["jq", "-e", "--arg", "base", BASE, "--arg", "head", HEAD,
                 "--arg", "controller", "5" * 40, "--arg", "repository",
                 "lightning-it/example", "--argjson", "pull_request", "41", predicate],
                input=json.dumps(value), text=True, capture_output=True, check=False,
            )
            self.assertNotEqual(3, result.returncode, result.stderr)
            return result.returncode == 0

        self.assertTrue(accepted(package))
        post_baseline = json.loads(json.dumps(package))
        post_baseline["ingress"].reverse()
        post_baseline["ingress"][1]["post_baseline"] = True
        post_baseline["post_baseline_ingress_count"] = 1
        self.assertTrue(accepted(post_baseline))
        swapped_marker = json.loads(json.dumps(package))
        swapped_marker["ingress"][0]["baseline_reconciliation"] = True
        swapped_marker["ingress"][1]["baseline_reconciliation"] = False
        self.assertFalse(accepted(swapped_marker))
        for template, index, flag, count in (
            (package, 0, True, 1),  # A pre-baseline change cannot be post-baseline.
            (package, 1, True, 1),  # The baseline itself cannot be post-baseline.
            (post_baseline, 1, False, 0),  # Later entries must be post-baseline.
        ):
            with self.subTest(position=index, post_baseline=flag):
                inconsistent = json.loads(json.dumps(template))
                inconsistent["ingress"][index]["post_baseline"] = flag
                inconsistent["post_baseline_ingress_count"] = count
                self.assertFalse(accepted(inconsistent))
        for markers in ((False, False), (True, True)):
            inconsistent = json.loads(json.dumps(package))
            for item, marker in zip(inconsistent["ingress"], markers):
                item["baseline_reconciliation"] = marker
            self.assertFalse(accepted(inconsistent))
        for field, values in (
            ("post_baseline_ingress_count", (-1, 1, None, "0")),
            ("reviewed_change_ingress_count", (0, 2, None, "1")),
            ("ingress_count", (0, 1, None, "2")),
        ):
            for value in values:
                with self.subTest(field=field, value=value):
                    self.assertFalse(accepted({**package, field: value}))
        for field, value in (
            ("ancestry_boundary", True), ("ancestry_boundary", None),
            ("baseline_reconciliation", True), ("baseline_reconciliation", None),
            ("post_baseline", None), ("review", None), ("threads", None),
        ):
            with self.subTest(ingress_field=field, value=value):
                invalid = json.loads(json.dumps(package))
                invalid["ingress"][0][field] = value
                self.assertFalse(accepted(invalid))
        baseline_only = {**package, "ingress": package["ingress"][1:],
                         "ingress_count": 1, "reviewed_change_ingress_count": 0}
        self.assertFalse(accepted(baseline_only))

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
                    "nodes": [{"id": "PRRT_1", "isResolved": False}],
                    "pageInfo": {"hasNextPage": False},
                }
            )

    def test_historical_copilot_overview_uses_live_thread_resolution(self) -> None:
        external_id = f"mlx90-current-revision:copilot:v6:17:88:{BASE}:{HEAD}"
        check = check_run(external_id, v6_summary())
        review = {
            "id": 17001,
            "node_id": "PRR_kwDOQs6tNc8AAAABPj6qbQ",
            "user": {"login": "copilot-pull-request-reviewer[bot]",
                     "id": 175728472, "type": "Bot"},
            "state": "COMMENTED", "commit_id": HEAD,
            "submitted_at": "2026-09-27T00:04:00Z",
            "body": ("<!-- ccr-overview-v2 -->\n"
                     "## Copilot review overview\n"
                     "### 🔵 Needs a closer look\n"
                     "**Findings:** 1\n"
                     "<strong>Open (1)</strong>"),
        }
        run = producer_run()
        run["pull_requests"] = []
        remote = evidence_api(run, review=review)

        def api(arguments):
            if "check-runs?check_name=" in arguments[-1]:
                return [{"check_runs": [check]}]
            return remote(arguments)

        for resolved in (True, False):
            with (
                self.subTest(resolved=resolved),
                mock.patch.object(MODULE, "gh_json", side_effect=api),
                mock.patch.object(
                    MODULE, "collect_review_threads",
                    return_value={
                        "nodes": [{"id": "PRRT_1", "isResolved": resolved}],
                        "pageInfo": {"hasNextPage": False},
                    },
                ),
            ):
                if resolved:
                    result = MODULE.collect_bound_ingress_evidence(
                        repository="lightning-it/example",
                        pull=ingress_pull(), pull_number=17,
                        base_sha=BASE, head_sha=HEAD,
                    )
                    self.assertEqual(["PRRT_1"],
                                     result["threads"]["resolved_thread_ids"])
                    self.assertEqual(88, result["review"]["producer_run_id"])
                else:
                    with self.assertRaisesRegex(
                        MODULE.EvidenceError, "unresolved-review-thread"
                    ):
                        MODULE.collect_bound_ingress_evidence(
                            repository="lightning-it/example",
                            pull=ingress_pull(), pull_number=17,
                            base_sha=BASE, head_sha=HEAD,
                        )

        valid_body = review["body"]
        review["body"] = valid_body.replace(
            "**Findings:** 1",
            '**Findings:** 1 <picture><source media="(prefers-color-scheme: dark)" '
            'srcset="https://github.githubassets.com/static/images/icons/'
            'copilot-code-review/high-v2-dark.svg">'
            '<source media="(prefers-color-scheme: light)" '
            'srcset="https://github.githubassets.com/static/images/icons/'
            'copilot-code-review/high-v2-light.svg">'
            '<img src="https://github.githubassets.com/static/images/icons/'
            'copilot-code-review/high-v2-light.png" alt="High severity" '
            'width="62" height="18" align="texttop"></picture>',
        )
        remote = evidence_api(run, review=review)
        with (
            mock.patch.object(MODULE, "gh_json", side_effect=api),
            mock.patch.object(
                MODULE, "collect_review_threads",
                return_value={
                    "nodes": [{"id": "PRRT_1", "isResolved": True}],
                    "pageInfo": {"hasNextPage": False},
                },
            ),
        ):
            MODULE.collect_bound_ingress_evidence(
                repository="lightning-it/example",
                pull=ingress_pull(), pull_number=17,
                base_sha=BASE, head_sha=HEAD,
            )
        for invalid_body in (
            valid_body.replace("**Findings:** 1", "**Findings:**"),
            valid_body.replace("**Findings:** 1", "**Findings:** arbitrary"),
            valid_body.replace("**Findings:** 1", "**Findings:** 0"),
            valid_body.replace("**Findings:** 1", "**Findings:** 1 extra"),
            valid_body.replace(
                "**Findings:** 1",
                '**Findings:** 1 <picture><source x><source y><img z></picture>',
            ),
            valid_body + "\n**Findings:** None",
            valid_body + "\nprefix **Findings:** None",
            valid_body + "\nprefix ## Copilot review overview",
            valid_body.replace("## Copilot review overview", "prefix ## Copilot review overview"),
        ):
            with (
                self.subTest(invalid_body=invalid_body),
                mock.patch.object(MODULE, "gh_json", side_effect=api),
                mock.patch.object(
                    MODULE, "collect_review_threads",
                    return_value={
                        "nodes": [{"id": "PRRT_1", "isResolved": True}],
                        "pageInfo": {"hasNextPage": False},
                    },
                ),
            ):
                review["body"] = invalid_body
                remote = evidence_api(run, review=review)
                with self.assertRaisesRegex(
                    MODULE.EvidenceError, "producer-review-binding"
                ):
                    MODULE.collect_bound_ingress_evidence(
                        repository="lightning-it/example",
                        pull=ingress_pull(), pull_number=17,
                        base_sha=BASE, head_sha=HEAD,
                    )

        review["body"] = valid_body
        remote = evidence_api(run, review=review)
        with (
            mock.patch.object(MODULE, "gh_json", side_effect=api),
            mock.patch.object(
                MODULE, "collect_review_threads",
                return_value={
                    "nodes": [], "pageInfo": {"hasNextPage": False},
                },
            ),
        ):
            with self.assertRaisesRegex(
                MODULE.EvidenceError, "producer-review-thread-coverage"
            ):
                MODULE.collect_bound_ingress_evidence(
                    repository="lightning-it/example",
                    pull=ingress_pull(), pull_number=17,
                    base_sha=BASE, head_sha=HEAD,
                )

        review["body"] = valid_body.replace(
            "**Findings:** 1", "**Findings:** None"
        ).replace("<strong>Open (1)</strong>", "")
        remote = evidence_api(run, review=review)
        with (
            mock.patch.object(MODULE, "gh_json", side_effect=api),
            mock.patch.object(
                MODULE, "collect_review_threads",
                return_value={
                    "nodes": [], "pageInfo": {"hasNextPage": False},
                },
            ),
        ):
            result = MODULE.collect_bound_ingress_evidence(
                repository="lightning-it/example",
                pull=ingress_pull(), pull_number=17,
                base_sha=BASE, head_sha=HEAD,
            )
            self.assertEqual(0, result["review"]["historical_findings_count"])

    def test_review_thread_evidence_binds_stable_unique_ids(self) -> None:
        accepted = MODULE.validate_review_threads(
            {
                "nodes": [
                    {"id": "PRRT_2", "isResolved": True},
                    {"id": "PRRT_1", "isResolved": True},
                ],
                "pageInfo": {"hasNextPage": False},
            }
        )
        self.assertEqual(["PRRT_1", "PRRT_2"], accepted["resolved_thread_ids"])
        with self.assertRaisesRegex(MODULE.EvidenceError, "review-thread-id-duplicate"):
            MODULE.validate_review_threads(
                {
                    "nodes": [
                        {"id": "PRRT_1", "isResolved": True},
                        {"id": "PRRT_1", "isResolved": True},
                    ],
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
        expected_name = (
            "    name: Verify aggregated develop-to-main promotion evidence\n"
        )
        self.assertIn(expected_name, promotion_job)
        self.assertNotIn("Authorize exact Supplementary catch-up", promotion_job)
        self.assertNotIn("    name: >-\n      ${{", promotion_job)
        self.assertNotIn(
            "  authorize-supplementary-catchup-v5-successor:\n",
            workflow,
        )
        self.assertNotIn("normal-release-promotion-approval", promotion_job)
        self.assertNotIn("normal-release-promotion-approval", workflow)
        for binding in (
            "umask 077",
            'test ! -L "${RUNNER_TEMP}"',
            'stat -c %u -- "${RUNNER_TEMP}"',
            "8#${runner_temp_mode} & 0022",
        ):
            self.assertIn(binding, promotion_job)
        self.assertIn("scripts/verify-promotion-evidence.py", workflow)
        self.assertIn("ee-wunder-devtools-ubi9:v1.16.1@sha256:", promotion_job)
        self.assertIn("docker run --rm", promotion_job)
        self.assertIn("actions/upload-artifact@043fb46d", promotion_job)
        self.assertIn("Persisted archive SHA-256", promotion_job)
        self.assertIn('test "${EVENT_ACTION}" = opened', promotion_job)
        self.assertIn("lit-promotion-dispatch-pending", promotion_job)
        self.assertIn("lit-promotion-dispatch-succeeded", promotion_job)
        self.assertIn("lit-promotion-evidence-ready", promotion_job)
        self.assertIn("lit-protected-promotion:v2", promotion_job)
        self.assertIn("--expected-body-sha256", promotion_job)
        self.assertIn('.owner.login == "lightning-it"', promotion_job)
        self.assertIn("controller_ref=main", promotion_job)
        self.assertIn("controller_ref=develop", promotion_job)
        self.assertIn('-v "${TARGET}:${TARGET}:ro"', promotion_job)
        self.assertIn('-v "${CONTROLLER}:${CONTROLLER}:ro"', promotion_job)
        self.assertIn(
            'verifier_runtime="$(mktemp -d', promotion_job
        )
        self.assertIn('chmod 0700 "${verifier_runtime}"', promotion_job)
        self.assertIn(
            '-v "${verifier_runtime}:${verifier_runtime}:rw"', promotion_job
        )
        self.assertIn(
            '-e RUNNER_TEMP="${verifier_runtime}"', promotion_job
        )
        self.assertIn('-e GH_CONFIG_DIR="${gh_config_dir}"', promotion_job)
        self.assertIn('-e HOME="${verifier_home}"', promotion_job)
        self.assertIn(
            'mkdir -m 0700 "${verifier_home}" "${gh_config_dir}"',
            promotion_job,
        )
        self.assertNotIn(
            '-v "${RUNNER_TEMP}:${RUNNER_TEMP}:rw"', promotion_job
        )
        self.assertIn(
            'docker network create --internal "${verifier_network}"', promotion_job
        )
        self.assertIn('--network "${verifier_network}"', promotion_job)
        self.assertIn("--network-alias github-api-proxy", promotion_job)
        self.assertIn("--serve-github-api-proxy", promotion_job)
        self.assertIn("-e GH_TOKEN=", promotion_job)
        self.assertIn("-e GH_TOKEN \\", promotion_job)
        self.assertIn("-e HTTPS_PROXY=http://github-api-proxy:8080", promotion_job)
        self.assertNotIn("--network bridge \\", promotion_job)
        self.assertNotIn("promotion_review", promotion_job)
        self.assertGreaterEqual(
            SCRIPT.read_text(encoding="utf-8").count("collect_bound_ingress_evidence("),
            3,
        )
        self.assertGreaterEqual(
            SCRIPT.read_text(encoding="utf-8").count(
                "is_authorized_ancestry_boundary("
            ),
            3,
        )
        self.assertIn("PROMOTION_RESULT", workflow)
        self.assertNotIn("MAX_REVIEW_BYTES", SCRIPT.read_text(encoding="utf-8"))
        self.assertNotIn("199999", SCRIPT.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
