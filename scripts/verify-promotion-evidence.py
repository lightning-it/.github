#!/usr/bin/env python3
"""Verify native ingress evidence for an exact develop-to-main promotion.

The verifier intentionally does not review the cumulative promotion diff again.
It proves that the protected develop first-parent history in the promotion range
consists only of GitHub merge commits whose exact PR heads already carry one
successful, bound ``Current revision review`` result and no unresolved review
conversations. The existing main tip is bound through exactly one separately
validated ancestry boundary.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import select
import socket
import socketserver
import stat
import subprocess
import sys
import tempfile
import time
import urllib.parse
from collections.abc import Iterable
from pathlib import Path
from typing import Any

JSON = dict[str, Any]
SHA = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
V6_EXTERNAL_ID = re.compile(
    r"^mlx90-current-revision:"
    r"(?P<kind>copilot|managed-sync|ancestry-backmerge|renovate):v6:"
    r"(?P<pr>[1-9][0-9]*):(?P<run>[1-9][0-9]*):"
    r"(?P<base>[0-9a-f]{40}):(?P<head>[0-9a-f]{40})$"
)
V5_EXTERNAL_ID = re.compile(
    r"^mlx90-current-revision:"
    r"(?P<kind>copilot|ancestry-backmerge):v5:"
    r"(?P<run>[1-9][0-9]*):"
    r"(?P<base>[0-9a-f]{40}):(?P<head>[0-9a-f]{40})$"
)
V4_EXTERNAL_ID = re.compile(
    r"^mlx90-current-revision:v4:(?P<run>[1-9][0-9]*):" r"(?P<input>[0-9a-f]{64})$"
)
RELEASE_APP_LOGIN = "lightning-it-release-automation[bot]"
RELEASE_APP_ID = 307565056
SYNC_APP_LOGIN = "lightning-it-shared-assets-sync[bot]"
SYNC_APP_ID = 307342877
RENOVATE_APP_LOGIN = "renovate[bot]"
RENOVATE_APP_ID = 29139614
GITHUB_ACTIONS_LOGIN = "github-actions[bot]"
GITHUB_ACTIONS_ID = 41898282
MAX_API_BYTES = 16 * 1024 * 1024
MAX_FIRST_PARENT_MERGES = 900
MAX_THREADS_PER_PULL = 1000
GITHUB_API_PROXY_PORT = 8080
MAX_PROXY_HEADER_BYTES = 8192


class EvidenceError(ValueError):
    """A promotion evidence invariant failed closed."""


def validate_github_api_connect_request(payload: bytes) -> None:
    """Accept only one exact HTTPS CONNECT request for api.github.com."""
    require(
        0 < len(payload) <= MAX_PROXY_HEADER_BYTES,
        "github-api-proxy-request-size",
    )
    require(
        payload.endswith(b"\r\n\r\n") and payload.count(b"\r\n\r\n") == 1,
        "github-api-proxy-request-framing",
    )
    try:
        lines = payload[:-4].decode("ascii", errors="strict").split("\r\n")
    except UnicodeDecodeError as error:
        raise EvidenceError("github-api-proxy-request-encoding") from error
    require(
        bool(lines) and lines[0] == "CONNECT api.github.com:443 HTTP/1.1",
        "github-api-proxy-target",
    )
    hosts: list[str] = []
    for line in lines[1:]:
        require(bool(line) and not line[0].isspace(), "github-api-proxy-header")
        name, separator, value = line.partition(":")
        require(
            separator == ":"
            and re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", name) is not None,
            "github-api-proxy-header",
        )
        require("\r" not in value and "\n" not in value, "github-api-proxy-header")
        if name.lower() == "host":
            hosts.append(value.strip())
        require(name.lower() != "proxy-authorization", "github-api-proxy-auth")
    require(hosts == ["api.github.com:443"], "github-api-proxy-host")


class GithubApiProxyHandler(socketserver.BaseRequestHandler):
    """Minimal token-blind CONNECT relay restricted to GitHub's API host."""

    def handle(self) -> None:
        self.request.settimeout(15)
        payload = b""
        while b"\r\n\r\n" not in payload:
            block = self.request.recv(
                min(4096, MAX_PROXY_HEADER_BYTES + 1 - len(payload))
            )
            if not block:
                return
            payload += block
            if len(payload) > MAX_PROXY_HEADER_BYTES:
                return
        try:
            validate_github_api_connect_request(payload)
            upstream = socket.create_connection(("api.github.com", 443), timeout=15)
        except (EvidenceError, OSError):
            self.request.sendall(b"HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n")
            return
        with upstream:
            upstream.settimeout(300)
            self.request.sendall(
                b"HTTP/1.1 200 Connection Established\r\nConnection: close\r\n\r\n"
            )
            sockets = [self.request, upstream]
            while sockets:
                readable, _, exceptional = select.select(sockets, [], sockets, 300)
                if exceptional or not readable:
                    return
                for source in readable:
                    target = upstream if source is self.request else self.request
                    try:
                        block = source.recv(65536)
                    except OSError:
                        return
                    if not block:
                        return
                    target.sendall(block)


class GithubApiProxyServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = False
    daemon_threads = True


def serve_github_api_proxy() -> None:
    require(not os.environ.get("GH_TOKEN"), "github-api-proxy-gh-token")
    require(not os.environ.get("GITHUB_TOKEN"), "github-api-proxy-github-token")
    with GithubApiProxyServer(
        ("0.0.0.0", GITHUB_API_PROXY_PORT), GithubApiProxyHandler
    ) as server:
        print("github-api-proxy-ready", flush=True)
        server.serve_forever()


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise EvidenceError(reason)


def canonical(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> JSON:
    value: JSON = {}
    for key, item in pairs:
        require(key not in value, "check-summary-duplicate-key")
        value[key] = item
    return value


def reject_nonstandard_constant(_: str) -> None:
    raise EvidenceError("check-summary-nonstandard-constant")


def exact_object(value: Any, label: str) -> JSON:
    require(type(value) is dict, f"{label}-not-object")
    return value


def exact_array(value: Any, label: str) -> list[Any]:
    require(type(value) is list, f"{label}-not-array")
    return value


def text(value: Any, label: str) -> str:
    require(type(value) is str and bool(value), f"{label}-not-string")
    return value


def integer(value: Any, label: str) -> int:
    require(type(value) is int and value > 0, f"{label}-not-positive-integer")
    return value


def sha(value: Any, label: str) -> str:
    result = text(value, label)
    require(SHA.fullmatch(result) is not None, f"{label}-not-sha")
    return result


def timestamp(value: Any, label: str) -> dt.datetime:
    raw = text(value, label)
    try:
        parsed = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as error:
        raise EvidenceError(f"{label}-not-timestamp") from error
    require(parsed.tzinfo is not None, f"{label}-missing-timezone")
    return parsed


def clean_environment() -> dict[str, str]:
    environment = os.environ.copy()
    for name in (
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_COMMON_DIR",
        "GIT_DIR",
        "GIT_INDEX_FILE",
        "GIT_OBJECT_DIRECTORY",
        "GIT_WORK_TREE",
    ):
        environment.pop(name, None)
    environment.update(
        {
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "LC_ALL": "C",
        }
    )
    return environment


def run(
    arguments: list[str],
    *,
    cwd: Path | None = None,
    input_text: str | None = None,
) -> str:
    completed = subprocess.run(
        arguments,
        cwd=cwd,
        env=clean_environment(),
        input=input_text,
        text=True,
        capture_output=True,
        check=False,
        timeout=90,
    )
    if completed.returncode != 0:
        stderr = completed.stderr.strip()
        raise EvidenceError(f"command-failed:{arguments[0]}:{stderr[:500]}")
    require(
        len(completed.stdout.encode("utf-8")) <= MAX_API_BYTES,
        "command-output-too-large",
    )
    return completed.stdout


def git(arguments: list[str], repository: Path) -> str:
    return run(["git", *arguments], cwd=repository).strip()


def is_ancestor(repository: Path, ancestor: str, descendant: str) -> bool:
    completed = subprocess.run(
        ["git", "merge-base", "--is-ancestor", ancestor, descendant],
        cwd=repository,
        env=clean_environment(),
        capture_output=True,
        check=False,
        timeout=30,
    )
    require(completed.returncode in (0, 1), "ancestry-check-failed")
    return completed.returncode == 0


def gh_json(arguments: list[str]) -> Any:
    require(bool(os.environ.get("GH_TOKEN")), "gh-token-missing")
    raw = run(["gh", *arguments])
    try:
        return json.loads(
            raw,
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_nonstandard_constant,
        )
    except EvidenceError:
        raise
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise EvidenceError("github-response-not-json") from error


def validate_live_promotion(
    pull: Any,
    *,
    repository: str,
    pull_number: int,
    expected_base: str,
    expected_head: str,
) -> JSON:
    value = exact_object(pull, "promotion")
    base = exact_object(value.get("base"), "promotion-base")
    head = exact_object(value.get("head"), "promotion-head")
    author = exact_object(value.get("user"), "promotion-author")
    base_repo = exact_object(base.get("repo"), "promotion-base-repository")
    head_repo = exact_object(head.get("repo"), "promotion-head-repository")
    require(
        integer(value.get("number"), "promotion-number") == pull_number,
        "promotion-number",
    )
    require(value.get("state") == "open", "promotion-not-open")
    require(value.get("draft") is False, "promotion-not-ready")
    require(
        value.get("title") == "chore(release): promote develop to main",
        "promotion-title",
    )
    require(author.get("login") == RELEASE_APP_LOGIN, "promotion-author-login")
    require(
        integer(author.get("id"), "promotion-author-id") == RELEASE_APP_ID,
        "promotion-author-id",
    )
    require(author.get("type") == "Bot", "promotion-author-type")
    require(base.get("ref") == "main", "promotion-base-ref")
    require(base.get("sha") == expected_base, "promotion-base-sha")
    require(base_repo.get("full_name") == repository, "promotion-base-repository")
    require(head.get("ref") == "develop", "promotion-head-ref")
    require(head.get("sha") == expected_head, "promotion-head-sha")
    require(head_repo.get("full_name") == repository, "promotion-head-repository")
    return value


def validate_protected_ref_tips(
    repository: str, *, expected_base: str, expected_head: str
) -> None:
    for ref, expected_sha in (("main", expected_base), ("develop", expected_head)):
        branch = exact_object(
            gh_json(["api", f"repos/{repository}/branches/{ref}"]),
            f"final-{ref}-branch",
        )
        commit = exact_object(branch.get("commit"), f"final-{ref}-commit")
        require(branch.get("name") == ref, f"final-{ref}-name")
        require(branch.get("protected") is True, f"final-{ref}-not-protected")
        require(commit.get("sha") == expected_sha, f"final-{ref}-moved")


def validate_repository_path(value: Path) -> Path:
    require(value.is_absolute(), "repository-path-not-absolute")
    metadata = value.lstat()
    require(not value.is_symlink(), "repository-path-symlink")
    require(stat.S_ISDIR(metadata.st_mode), "repository-path-not-directory")
    resolved = value.resolve(strict=True)
    require(resolved == value, "repository-path-not-canonical")
    return resolved


def promotion_body_sha256(value: JSON) -> str:
    body = text(value.get("body"), "promotion-body")
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def promotion_binding(value: JSON) -> JSON:
    """Return only the trust-boundary fields that must stay exact."""
    base = exact_object(value.get("base"), "promotion-binding-base")
    head = exact_object(value.get("head"), "promotion-binding-head")
    author = exact_object(value.get("user"), "promotion-binding-author")
    return {
        "number": value.get("number"),
        "state": value.get("state"),
        "draft": value.get("draft"),
        "title": value.get("title"),
        "body": value.get("body"),
        "author": {
            "login": author.get("login"),
            "id": author.get("id"),
            "type": author.get("type"),
        },
        "base": {"ref": base.get("ref"), "sha": base.get("sha")},
        "head": {"ref": head.get("ref"), "sha": head.get("sha")},
    }


def first_parent_merges(
    repository_path: Path, expected_base: str, expected_head: str
) -> tuple[str, str, list[JSON]]:
    require(
        repository_path.is_dir() and not repository_path.is_symlink(), "repository-path"
    )
    require(
        git(["status", "--porcelain=v1", "--untracked-files=no"], repository_path)
        == "",
        "repository-dirty",
    )
    for revision, label in ((expected_base, "base"), (expected_head, "head")):
        require(
            git(["cat-file", "-t", revision], repository_path) == "commit",
            f"{label}-not-commit",
        )
    run(
        ["git", "merge-base", "--is-ancestor", expected_base, expected_head],
        cwd=repository_path,
    )
    require(
        git(["merge-base", "--all", expected_base, expected_head], repository_path)
        == expected_base,
        "merge-base-not-exact-main",
    )
    integration_tree = sha(
        git(["rev-parse", f"{expected_head}^{{tree}}"], repository_path),
        "integration-tree",
    )
    revisions = [
        line
        for line in git(
            [
                "rev-list",
                "--first-parent",
                "--reverse",
                f"{expected_base}..{expected_head}",
            ],
            repository_path,
        ).splitlines()
        if line
    ]
    require(bool(revisions), "promotion-history-empty")
    require(len(revisions) <= MAX_FIRST_PARENT_MERGES, "promotion-history-too-large")
    previous: str | None = None
    history_anchor = ""
    merges: list[JSON] = []
    for revision in revisions:
        commit = sha(revision, "merge-commit")
        parents = git(["show", "-s", "--format=%P", commit], repository_path).split()
        require(len(parents) == 2, "non-merge-first-parent-commit")
        if previous is None:
            history_anchor = sha(parents[0], "history-anchor")
        else:
            require(parents[0] == previous, "first-parent-chain-drift")
        require(SHA.fullmatch(parents[1]) is not None, "merge-head-not-sha")
        merges.append(
            {"base_sha": parents[0], "head_sha": parents[1], "merge_sha": commit}
        )
        previous = commit
    require(previous == expected_head, "first-parent-tip-drift")
    return history_anchor, integration_tree, merges


def select_ingress_pull(
    pulls: Any,
    *,
    repository: str,
    merge_sha: str,
    head_sha: str,
    expected_number: int | None = None,
) -> JSON:
    candidates = []
    for item in exact_array(pulls, "associated-pulls"):
        pull = exact_object(item, "associated-pull")
        base = exact_object(pull.get("base"), "associated-pull-base")
        head = exact_object(pull.get("head"), "associated-pull-head")
        base_repo = exact_object(base.get("repo"), "associated-pull-base-repository")
        head_repo = exact_object(head.get("repo"), "associated-pull-head-repository")
        if (
            pull.get("state") == "closed"
            and pull.get("merged_at") is not None
            and pull.get("merge_commit_sha") == merge_sha
            and base.get("ref") == "develop"
            and base_repo.get("full_name") == repository
            and head_repo.get("full_name") == repository
            and head.get("sha") == head_sha
        ):
            candidates.append(pull)
    require(len(candidates) == 1, "associated-pull-not-unique")
    candidate = candidates[0]
    candidate_number = integer(candidate.get("number"), "associated-pull-number")
    if expected_number is not None:
        require(candidate_number == expected_number, "associated-pull-number-mismatch")
    timestamp(candidate.get("merged_at"), "associated-pull-merged-at")
    return candidate


def flatten_pull_pages(value: Any) -> list[JSON]:
    pages = exact_array(value, "associated-pull-pages")
    pulls: list[JSON] = []
    for page in pages:
        pulls.extend(
            exact_object(item, "associated-pull")
            for item in exact_array(page, "associated-pull-page")
        )
    require(len(pulls) <= 1000, "associated-pull-inventory-too-large")
    return pulls


def check_pages(value: Any) -> list[JSON]:
    pages = exact_array(value, "check-pages")
    runs: list[JSON] = []
    for page in pages:
        page_value = exact_object(page, "check-page")
        page_runs = exact_array(page_value.get("check_runs"), "check-runs")
        runs.extend(exact_object(item, "check-run") for item in page_runs)
    require(len(runs) <= 1000, "check-run-inventory-too-large")
    ids = [integer(item.get("id"), "check-run-id") for item in runs]
    require(len(ids) == len(set(ids)), "check-run-duplicate")
    return runs


def expected_evidence_kind(pull: JSON, *, repository: str) -> str:
    user = exact_object(pull.get("user"), "associated-pull-user")
    login = text(user.get("login"), "associated-pull-user-login")
    integer(user.get("id"), "associated-pull-user-id")
    user_type = text(user.get("type"), "associated-pull-user-type")
    head = exact_object(pull.get("head"), "associated-pull-head")
    head_ref = text(head.get("ref"), "associated-pull-head-ref")
    title = text(pull.get("title"), "associated-pull-title")
    ancestry = (
        head_ref.startswith("backmerge/")
        and head_ref.endswith("-main")
        and title.startswith("chore(governance): record main ancestry before ")
    )
    if ancestry:
        require(
            (
                login == RELEASE_APP_LOGIN
                and user.get("id") == RELEASE_APP_ID
                and user_type == "Bot"
            )
            or (
                repository == "lightning-it/.github"
                and login == SYNC_APP_LOGIN
                and user.get("id") == SYNC_APP_ID
                and user_type == "Bot"
            ),
            "ancestry-backmerge-author",
        )
        return "ancestry-backmerge"
    if login == RELEASE_APP_LOGIN:
        require(
            user.get("id") == RELEASE_APP_ID and user_type == "Bot",
            "release-app-identity",
        )
        return "release-app"
    if login == SYNC_APP_LOGIN:
        require(
            user.get("id") == SYNC_APP_ID and user_type == "Bot",
            "managed-sync-identity",
        )
        return "managed-sync"
    if login == RENOVATE_APP_LOGIN:
        require(
            user.get("id") == RENOVATE_APP_ID and user_type == "Bot",
            "renovate-identity",
        )
        return "renovate"
    require(user_type == "User", "copilot-ingress-author-type")
    return "copilot"


def is_authorized_ancestry_boundary(
    pull: Any,
    *,
    repository: str,
    expected_main: str,
    previous_develop: str,
) -> bool:
    """Return whether an ingress PR is the exact controller-created backmerge."""

    try:
        value = exact_object(pull, "ancestry-boundary-pull")
        user = exact_object(value.get("user"), "ancestry-boundary-user")
        base = exact_object(value.get("base"), "ancestry-boundary-base")
        head = exact_object(value.get("head"), "ancestry-boundary-head")
        base_repo = exact_object(base.get("repo"), "ancestry-boundary-base-repository")
        head_repo = exact_object(head.get("repo"), "ancestry-boundary-head-repository")
        repository_name = repository.split("/", 1)[1]
        branch_component = (
            repository_name[1:] if repository_name.startswith(".") else repository_name
        )
        expected_ref = (
            f"backmerge/{branch_component}-{expected_main[:12]}-"
            f"{previous_develop[:12]}-main"
        )
        user_id = integer(user.get("id"), "ancestry-boundary-user-id")
        identity = (
            user.get("login"),
            user_id,
            user.get("type"),
        )
        allowed_identities = {(RELEASE_APP_LOGIN, RELEASE_APP_ID, "Bot")}
        if repository == "lightning-it/.github":
            allowed_identities.add((SYNC_APP_LOGIN, SYNC_APP_ID, "Bot"))
        return (
            base.get("ref") == "develop"
            and base_repo.get("full_name") == repository
            and head_repo.get("full_name") == repository
            and head.get("ref") == expected_ref
            and value.get("title")
            == f"chore(governance): record main ancestry before {expected_main[:12]}"
            and identity in allowed_identities
        )
    except (EvidenceError, IndexError):
        return False


def has_exact_ancestry_merge_parents(
    repository_path: Path,
    *,
    head_sha: str,
    previous_develop: str,
    expected_main: str,
) -> bool:
    parents = git(["show", "-s", "--format=%P", head_sha], repository_path).split()
    return parents == [previous_develop, expected_main]


def validate_ancestry_boundary_content(
    repository_path: Path,
    *,
    repository: str,
    head_sha: str,
    previous_develop: str,
    expected_main: str,
) -> None:
    evidence_path = ".lit/main-ancestry.json"
    changed = git(
        [
            "diff",
            "--no-renames",
            "--name-only",
            previous_develop,
            head_sha,
            "--",
        ],
        repository_path,
    ).splitlines()
    require(changed == [evidence_path], "ancestry-boundary-content-scope")
    require(
        git(["show", "-s", "--format=%s", head_sha], repository_path)
        == "merge: preserve develop tree and main ancestry",
        "ancestry-boundary-subject",
    )
    raw = git(["show", f"{head_sha}:{evidence_path}"], repository_path)
    try:
        evidence = exact_object(
            json.loads(
                raw,
                object_pairs_hook=reject_duplicate_keys,
                parse_constant=reject_nonstandard_constant,
            ),
            "ancestry-boundary-evidence",
        )
    except (json.JSONDecodeError, RecursionError) as error:
        raise EvidenceError("ancestry-boundary-evidence-not-json") from error
    require(
        set(evidence)
        == {
            "develop_parent_sha",
            "main_sha",
            "purpose",
            "repository",
            "schema_version",
        },
        "ancestry-boundary-evidence",
    )
    require(
        integer(evidence.get("schema_version"), "ancestry-boundary-schema") == 1,
        "ancestry-boundary-schema",
    )
    require(
        sha(evidence.get("main_sha"), "ancestry-boundary-main") == expected_main,
        "ancestry-boundary-main",
    )
    require(
        sha(evidence.get("develop_parent_sha"), "ancestry-boundary-develop")
        == previous_develop,
        "ancestry-boundary-develop",
    )
    require(
        text(evidence.get("repository"), "ancestry-boundary-repository") == repository,
        "ancestry-boundary-repository",
    )
    require(
        text(evidence.get("purpose"), "ancestry-boundary-purpose")
        == "Bind the reviewed main ancestry backmerge.",
        "ancestry-boundary-purpose",
    )
    tree_entry = git(
        ["ls-tree", head_sha, "--", evidence_path], repository_path
    ).split()
    require(
        len(tree_entry) == 4
        and tree_entry[0] == "100644"
        and tree_entry[1] == "blob"
        and SHA.fullmatch(tree_entry[2]) is not None
        and tree_entry[3] == evidence_path,
        "ancestry-boundary-evidence-mode",
    )


def classify_ingress_position(index: int, baseline_boundary: int) -> tuple[bool, bool]:
    require(type(index) is int and index >= 0, "ingress-index")
    require(
        type(baseline_boundary) is int and baseline_boundary >= 0,
        "baseline-boundary-index",
    )
    return index == baseline_boundary, index > baseline_boundary


def review_summary(check: JSON) -> JSON:
    output = exact_object(check.get("output"), "check-output")
    raw = text(output.get("summary"), "check-summary")
    try:
        return exact_object(
            json.loads(
                raw,
                object_pairs_hook=reject_duplicate_keys,
                parse_constant=reject_nonstandard_constant,
            ),
            "check-summary-json",
        )
    except (json.JSONDecodeError, RecursionError) as error:
        raise EvidenceError("check-summary-not-json") from error


def validate_renovate_policy(pull: JSON, summary: JSON, *, repository: str) -> None:
    base = exact_object(pull.get("base"), "renovate-base")
    head = exact_object(pull.get("head"), "renovate-head")
    head_repo = exact_object(head.get("repo"), "renovate-head-repository")
    labels = exact_array(pull.get("labels"), "renovate-labels")
    names = [
        text(exact_object(item, "renovate-label").get("name"), "renovate-label-name")
        for item in labels
    ]
    require(len(names) == len(set(names)), "renovate-label-duplicate")
    require(base.get("ref") == "develop", "renovate-base-ref")
    require(
        text(head.get("ref"), "renovate-head-ref").startswith("renovate/"),
        "renovate-head-ref",
    )
    require(head_repo.get("full_name") == repository, "renovate-head-repository")
    require(
        {"renovate", "dependencies", "safe-automerge"}.issubset(names),
        "renovate-required-labels",
    )
    require("breaking-update" not in names, "renovate-breaking-label")
    labels_json = json.dumps(
        sorted(names), ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    require(
        hashlib.sha256(labels_json).hexdigest()
        == summary.get("pull_request_labels_sha256"),
        "renovate-labels-mutated",
    )
    last_edited_at = pull.get("last_edited_at")
    require(
        last_edited_at is None or type(last_edited_at) is str,
        "renovate-live-last-edited-at",
    )
    require(
        last_edited_at == summary.get("pull_request_last_edited_at"),
        "renovate-last-edited-at-mutated",
    )


def validate_producer_run(
    check: JSON,
    *,
    repository: str,
    pull: JSON,
    pull_number: int,
    base_sha: str,
    head_sha: str,
    evidence_kind: str,
    evidence_version: str,
    producer_run_id: int,
) -> JSON:
    check_id = integer(check.get("id"), "check-id")
    require(
        check.get("details_url") == f"https://github.com/{repository}/runs/{check_id}",
        "check-details-url",
    )
    user = exact_object(pull.get("user"), "associated-pull-user")
    author = text(user.get("login"), "associated-pull-user-login")
    author_id = integer(user.get("id"), "associated-pull-user-id")
    author_type = text(user.get("type"), "associated-pull-user-type")
    require(author_type in {"User", "Bot"}, "associated-pull-user-type")
    base = exact_object(pull.get("base"), "associated-pull-base")
    head = exact_object(pull.get("head"), "associated-pull-head")
    base_ref = text(base.get("ref"), "associated-pull-base-ref")
    head_ref = text(head.get("ref"), "associated-pull-head-ref")
    summary = review_summary(check)
    run_url = f"https://github.com/{repository}/actions/runs/{producer_run_id}"
    require(summary.get("schema") == 4, "review-summary-schema")
    require(summary.get("base_sha") == base_sha, "review-summary-base")
    require(summary.get("head_sha") == head_sha, "review-summary-head")
    if evidence_version == "v5":
        require(
            "pull_request_number" not in summary
            or integer(
                summary.get("pull_request_number"),
                "review-summary-pull-request",
            )
            == pull_number,
            "review-summary-pull-request",
        )
    else:
        require(
            integer(
                summary.get("pull_request_number"),
                "review-summary-pull-request",
            )
            == pull_number,
            "review-summary-pull-request",
        )
    require(
        integer(summary.get("producer_run_id"), "review-summary-producer")
        == producer_run_id,
        "review-summary-producer",
    )
    require(summary.get("run_url") == run_url, "review-summary-run-url")
    repository_state: JSON | None = None
    if evidence_kind != "release-app":
        expected_paths = {
            "copilot": "applicable Copilot or governed automation exemption",
            "managed-sync": (
                "deterministic provenance-bound managed distribution exemption"
            ),
            "ancestry-backmerge": ("deterministic evidence-bound ancestry exemption"),
            "renovate": "deterministic policy-bound Renovate exemption",
        }
        require(
            summary.get("review_path") == expected_paths[evidence_kind],
            "review-summary-path",
        )
        if evidence_kind == "renovate":
            expected_keys = {
                "base_sha",
                "controller_ref",
                "controller_sha",
                "head_repository",
                "head_sha",
                "producer_run_id",
                "pull_request_labels_sha256",
                "pull_request_last_edited_at",
                "pull_request_number",
                "review_id",
                "review_path",
                "run_url",
                "schema",
            }
            require(set(summary) == expected_keys, "renovate-review-summary-schema")
            require(
                summary.get("head_repository") == repository,
                "review-summary-head-repository",
            )
            require(summary.get("review_id") is None, "renovate-review-id")
            require(
                SHA256.fullmatch(
                    text(
                        summary.get("pull_request_labels_sha256"),
                        "renovate-labels-sha256",
                    )
                )
                is not None,
                "renovate-labels-sha256",
            )
            require(
                summary.get("pull_request_last_edited_at") is None
                or type(summary.get("pull_request_last_edited_at")) is str,
                "renovate-last-edited-at",
            )
            validate_renovate_policy(pull, summary, repository=repository)
        elif evidence_version == "v6":
            require(
                set(summary)
                == {
                    "base_sha",
                    "controller_sha",
                    "head_sha",
                    "producer_run_id",
                    "pull_request_number",
                    "review_path",
                    "run_url",
                    "schema",
                },
                "review-summary-schema",
            )
        else:
            require(evidence_version == "v5", "review-summary-version")
            expected_v5_keys = {
                "base_sha",
                "controller_sha",
                "head_sha",
                "producer_run_id",
                "review_path",
                "run_url",
                "schema",
            }
            require(
                set(summary)
                in (
                    expected_v5_keys,
                    expected_v5_keys | {"pull_request_number"},
                ),
                "review-summary-schema",
            )

        controller_sha = sha(summary.get("controller_sha"), "controller-sha")
        repository_state = exact_object(
            gh_json(["api", f"repos/{repository}"]), "controller-repository"
        )
        controller_ref = text(repository_state.get("default_branch"), "controller-ref")
        if evidence_kind == "renovate":
            require(
                summary.get("controller_ref") == controller_ref,
                "review-summary-controller-ref",
            )
        encoded_ref = urllib.parse.quote(controller_ref, safe="")
        controller_branch = exact_object(
            gh_json(["api", f"repos/{repository}/branches/{encoded_ref}"]),
            "controller-branch",
        )
        controller_commit = exact_object(
            controller_branch.get("commit"), "controller-branch-commit"
        )
        controller_head = sha(controller_commit.get("sha"), "controller-head")
        ancestry = exact_object(
            gh_json(
                [
                    "api",
                    f"repos/{repository}/compare/{controller_sha}...{controller_head}",
                ]
            ),
            "controller-ancestry",
        )
        merge_base = exact_object(
            ancestry.get("merge_base_commit"), "controller-merge-base"
        )
        require(
            ancestry.get("status") == "identical"
            or (
                ancestry.get("status") == "ahead"
                and ancestry.get("behind_by") == 0
                and merge_base.get("sha") == controller_sha
            ),
            "controller-not-protected-ancestor",
        )

    run = exact_object(
        gh_json(["api", f"repos/{repository}/actions/runs/{producer_run_id}"]),
        "producer-run",
    )
    require(run.get("id") == producer_run_id, "producer-run-id")
    require(run.get("html_url") == run_url, "producer-run-url")
    actor = exact_object(run.get("actor"), "producer-run-actor")
    triggering = exact_object(
        run.get("triggering_actor"), "producer-run-triggering-actor"
    )
    attempt = integer(run.get("run_attempt"), "producer-run-attempt")
    require(
        actor.get("login") == author
        and integer(actor.get("id"), "producer-run-actor-id") == author_id
        and actor.get("type") == author_type,
        "producer-run-actor-identity",
    )
    if evidence_kind == "copilot" and attempt == 2:
        require(
            triggering.get("login") == GITHUB_ACTIONS_LOGIN
            and integer(triggering.get("id"), "producer-run-triggering-actor-id")
            == GITHUB_ACTIONS_ID
            and triggering.get("type") == "Bot",
            "producer-run-triggering-actor-identity",
        )
    else:
        require(
            triggering.get("login") == author
            and integer(triggering.get("id"), "producer-run-triggering-actor-id")
            == author_id
            and triggering.get("type") == author_type,
            "producer-run-triggering-actor-identity",
        )
    require(run.get("status") == "completed", "producer-run-status")
    require(run.get("conclusion") == "success", "producer-run-conclusion")
    if evidence_kind == "release-app":
        require(attempt == 1, "release-producer-run-attempt")
        require(run.get("event") == "workflow_dispatch", "release-producer-event")
        require(
            run.get("path") == ".github/workflows/release-bot-exact-head-review.yml",
            "release-producer-workflow",
        )
        require(run.get("head_branch") == base_ref, "release-producer-branch")
        require(run.get("head_sha") == base_sha, "release-producer-head")
        require(
            run.get("display_title")
            == f"Exact-Revision Codex PR #{pull_number} {base_sha}..{head_sha}",
            "release-producer-title",
        )
    else:
        require(attempt in {1, 2}, "producer-run-attempt")
        require(
            attempt == 1 or evidence_kind == "copilot",
            "producer-rerun-kind",
        )
        require(run.get("event") == "pull_request_target", "producer-event")
        require(
            run.get("path") == ".github/workflows/copilot-review.yml",
            "producer-workflow",
        )
        require(run.get("name") == "Current revision review gate", "producer-name")
        require(run.get("head_branch") == head_ref, "producer-branch")
        require(run.get("head_sha") == head_sha, "producer-head")
        require(repository_state is not None, "producer-repository-state")
        repository_id = integer(repository_state.get("id"), "producer-repository-id")
        repository_name = repository.split("/", 1)[1]
        repository_url = f"https://api.github.com/repos/{repository}"
        associations = exact_array(
            run.get("pull_requests"), "producer-run-pull-requests"
        )
        if not associations:
            suite_id = integer(
                run.get("check_suite_id"), "producer-run-check-suite-id"
            )
            suite = exact_object(
                gh_json(["api", f"repos/{repository}/check-suites/{suite_id}"]),
                "producer-check-suite",
            )
            suite_app = exact_object(suite.get("app"), "producer-check-suite-app")
            require(
                integer(suite.get("id"), "producer-check-suite-id") == suite_id,
                "producer-check-suite-id",
            )
            require(
                integer(suite_app.get("id"), "producer-check-suite-app-id") == 15368
                and suite_app.get("slug") == "github-actions",
                "producer-check-suite-app",
            )
            require(
                suite.get("status") == "completed"
                and suite.get("conclusion") == "success",
                "producer-check-suite-result",
            )
            require(
                suite.get("head_branch") == head_ref
                and suite.get("head_sha") == head_sha,
                "producer-check-suite-head-binding",
            )
            return summary
        require(len(associations) == 1, "producer-run-pull-request-count")
        association = exact_object(associations[0], "producer-run-pull-request")
        association_base = exact_object(
            association.get("base"), "producer-run-pull-request-base"
        )
        association_head = exact_object(
            association.get("head"), "producer-run-pull-request-head"
        )
        for label, value, expected_ref, expected_sha in (
            ("base", association_base, base_ref, base_sha),
            ("head", association_head, head_ref, head_sha),
        ):
            association_repository = exact_object(
                value.get("repo"),
                f"producer-run-pull-request-{label}-repository",
            )
            require(
                value.get("ref") == expected_ref
                and value.get("sha") == expected_sha
                and integer(
                    association_repository.get("id"),
                    f"producer-run-pull-request-{label}-repository-id",
                )
                == repository_id
                and association_repository.get("name") == repository_name
                and association_repository.get("url") == repository_url,
                f"producer-run-pull-request-{label}-binding",
            )
        require(
            integer(association.get("number"), "producer-run-pull-request-number")
            == pull_number
            and association.get("url") == f"{repository_url}/pulls/{pull_number}",
            "producer-run-pull-request-binding",
        )
    return summary


def bound_review_check(
    pages: Any,
    *,
    repository: str,
    pull: JSON,
    pull_number: int,
    base_sha: str,
    head_sha: str,
    merge_base_sha: str | None = None,
) -> JSON:
    expected_kind = expected_evidence_kind(pull, repository=repository)
    matches: list[JSON] = []
    for check in check_pages(pages):
        app = exact_object(check.get("app"), "check-app")
        if not (
            check.get("name") == "Current revision review"
            and integer(app.get("id"), "check-app-id") == 15368
            and app.get("slug") == "github-actions"
            and check.get("head_sha") == head_sha
            and check.get("status") == "completed"
            and check.get("conclusion") == "success"
        ):
            continue
        external_id = text(check.get("external_id"), "check-external-id")
        output = exact_object(check.get("output"), "check-output")
        output_title = text(output.get("title"), "check-output-title")
        v6 = V6_EXTERNAL_ID.fullmatch(external_id)
        if v6 is not None:
            if (
                expected_kind == v6.group("kind")
                and int(v6.group("pr")) == pull_number
                and v6.group("base") == base_sha
                and v6.group("head") == head_sha
                and output_title == "Current revision review passed"
            ):
                summary = validate_producer_run(
                    check,
                    repository=repository,
                    pull=pull,
                    pull_number=pull_number,
                    base_sha=base_sha,
                    head_sha=head_sha,
                    evidence_kind=v6.group("kind"),
                    evidence_version="v6",
                    producer_run_id=int(v6.group("run")),
                )
                match = {
                    "check_id": integer(check.get("id"), "check-id"),
                    "evidence_kind": v6.group("kind"),
                    "evidence_version": "v6",
                    "external_id": external_id,
                    "producer_run_id": int(v6.group("run")),
                    "summary_sha256": digest(summary),
                }
                matches.append(match)
            continue
        v5 = V5_EXTERNAL_ID.fullmatch(external_id)
        if v5 is not None:
            if (
                expected_kind == v5.group("kind")
                and v5.group("base") == base_sha
                and v5.group("head") == head_sha
                and output_title == "Current revision review passed"
            ):
                summary = validate_producer_run(
                    check,
                    repository=repository,
                    pull=pull,
                    pull_number=pull_number,
                    base_sha=base_sha,
                    head_sha=head_sha,
                    evidence_kind=v5.group("kind"),
                    evidence_version="v5",
                    producer_run_id=int(v5.group("run")),
                )
                match = {
                    "check_id": integer(check.get("id"), "check-id"),
                    "evidence_kind": v5.group("kind"),
                    "evidence_version": "v5",
                    "external_id": external_id,
                    "producer_run_id": int(v5.group("run")),
                    "summary_sha256": digest(summary),
                }
                matches.append(match)
            continue
        v4 = V4_EXTERNAL_ID.fullmatch(external_id)
        if (
            v4 is None
            or expected_kind != "release-app"
            or output_title != "Protected Exact-Revision Codex review passed"
        ):
            continue
        require(merge_base_sha is not None, "expected-review-merge-base-missing")
        expected_merge_base = sha(merge_base_sha, "expected-review-merge-base")
        evidence = review_summary(check)
        expected_v4_keys = {
            "base_sha",
            "diff_sha256",
            "head_sha",
            "input_sha256",
            "integration_tree_sha",
            "merge_base_sha",
            "producer_run_id",
            "pull_request_number",
            "run_url",
            "schema",
            "workflow_sha",
        }
        if (
            set(evidence) == expected_v4_keys
            and evidence.get("schema") == 4
            and integer(
                evidence.get("pull_request_number"),
                "review-summary-pull-request",
            )
            == pull_number
            and evidence.get("base_sha") == base_sha
            and evidence.get("head_sha") == head_sha
            and integer(
                evidence.get("producer_run_id"),
                "review-summary-producer",
            )
            == int(v4.group("run"))
            and evidence.get("input_sha256") == v4.group("input")
            and evidence.get("workflow_sha") == base_sha
            and sha(evidence.get("merge_base_sha"), "review-summary-merge-base")
            == expected_merge_base
            and SHA.fullmatch(
                text(
                    evidence.get("integration_tree_sha"),
                    "review-summary-integration-tree",
                )
            )
            is not None
            and SHA256.fullmatch(
                text(evidence.get("diff_sha256"), "review-summary-diff-sha256")
            )
            is not None
        ):
            summary = validate_producer_run(
                check,
                repository=repository,
                pull=pull,
                pull_number=pull_number,
                base_sha=base_sha,
                head_sha=head_sha,
                evidence_kind="release-app",
                evidence_version="v4",
                producer_run_id=int(v4.group("run")),
            )
            match = {
                "check_id": integer(check.get("id"), "check-id"),
                "evidence_kind": "release-app",
                "evidence_version": "v4",
                "external_id": external_id,
                "producer_run_id": int(v4.group("run")),
                "summary_sha256": digest(summary),
            }
            matches.append(match)
    require(len(matches) == 1, "bound-current-revision-check-not-unique")
    return matches[0]


def validate_review_threads(connection: Any) -> JSON:
    value = exact_object(connection, "review-threads")
    nodes = exact_array(value.get("nodes"), "review-thread-nodes")
    page_info = exact_object(value.get("pageInfo"), "review-thread-page-info")
    require(
        page_info.get("hasNextPage") is False, "review-thread-pagination-incomplete"
    )
    unresolved = 0
    thread_ids: list[str] = []
    for item in nodes:
        thread = exact_object(item, "review-thread")
        thread_id = text(thread.get("id"), "review-thread-id")
        require(len(thread_id) <= 256, "review-thread-id-too-long")
        thread_ids.append(thread_id)
        require(type(thread.get("isResolved")) is bool, "review-thread-resolution")
        if thread["isResolved"] is False:
            unresolved += 1
    require(unresolved == 0, "unresolved-review-thread")
    require(len(thread_ids) == len(set(thread_ids)), "review-thread-id-duplicate")
    return {
        "resolved_thread_ids": sorted(thread_ids),
        "unresolved_threads": unresolved,
    }


THREAD_QUERY = """
query($owner:String!,$name:String!,$number:Int!,$after:String){
  repository(owner:$owner,name:$name){
    pullRequest(number:$number){
      number
      reviewThreads(first:100,after:$after){
        nodes{id isResolved}
        pageInfo{hasNextPage endCursor}
      }
    }
  }
}
"""


def collect_review_threads(repository: str, pull_number: int) -> JSON:
    owner, name = repository.split("/", 1)
    after: str | None = None
    nodes: list[JSON] = []
    while True:
        arguments = [
            "api",
            "graphql",
            "-f",
            f"query={THREAD_QUERY}",
            "-F",
            f"owner={owner}",
            "-F",
            f"name={name}",
            "-F",
            f"number={pull_number}",
        ]
        if after is not None:
            arguments.extend(["-F", f"after={after}"])
        payload = exact_object(gh_json(arguments), "thread-response")
        errors = payload.get("errors")
        require(errors is None or errors == [], "thread-response-errors")
        data = exact_object(payload.get("data"), "thread-data")
        repo = exact_object(data.get("repository"), "thread-repository")
        pull = exact_object(repo.get("pullRequest"), "thread-pull")
        require(
            integer(pull.get("number"), "thread-pull-number") == pull_number,
            "thread-pull-number",
        )
        connection = exact_object(pull.get("reviewThreads"), "thread-connection")
        page_nodes = exact_array(connection.get("nodes"), "thread-page-nodes")
        nodes.extend(exact_object(node, "thread-node") for node in page_nodes)
        require(len(nodes) <= MAX_THREADS_PER_PULL, "review-thread-inventory-too-large")
        page_info = exact_object(connection.get("pageInfo"), "thread-page-info")
        has_next = page_info.get("hasNextPage")
        require(type(has_next) is bool, "thread-has-next-page")
        if not has_next:
            return {"nodes": nodes, "pageInfo": {"hasNextPage": False}}
        cursor = page_info.get("endCursor")
        require(type(cursor) is str and 0 < len(cursor) <= 512, "thread-cursor")
        require(cursor != after, "thread-cursor-cycle")
        after = cursor


def collect_bound_ingress_evidence(
    *,
    repository: str,
    pull: JSON,
    pull_number: int,
    base_sha: str,
    head_sha: str,
    merge_base_sha: str | None = None,
) -> JSON:
    require(
        expected_evidence_kind(pull, repository=repository) != "ancestry-backmerge",
        "ancestry-backmerge-not-structural-boundary",
    )
    checks = gh_json(
        [
            "api",
            "--paginate",
            "--slurp",
            (
                f"repos/{repository}/commits/{head_sha}/check-runs"
                "?check_name=Current%20revision%20review&filter=all&per_page=100"
            ),
        ]
    )
    return {
        "review": bound_review_check(
            checks,
            repository=repository,
            pull=pull,
            pull_number=pull_number,
            base_sha=base_sha,
            head_sha=head_sha,
            merge_base_sha=merge_base_sha,
        ),
        "threads": validate_review_threads(
            collect_review_threads(repository, pull_number)
        ),
    }


def private_runtime_directory() -> Path:
    runner_temp = Path(os.environ.get("RUNNER_TEMP", ""))
    require(runner_temp.is_absolute(), "runner-temp-not-absolute")
    metadata = runner_temp.lstat()
    require(
        stat.S_ISDIR(metadata.st_mode) and not runner_temp.is_symlink(),
        "runner-temp-unsafe",
    )
    require(metadata.st_uid == os.geteuid(), "runner-temp-owner")
    require(metadata.st_mode & 0o022 == 0, "runner-temp-mode")
    require(
        os.access(runner_temp, os.R_OK | os.W_OK | os.X_OK),
        "runner-temp-access",
    )
    return runner_temp


def compute_diff(repository_path: Path, base_sha: str, head_sha: str) -> JSON:
    runner_temp = private_runtime_directory()
    descriptor, name = tempfile.mkstemp(prefix="promotion-diff.", dir=runner_temp)
    path = Path(name)
    try:
        path.unlink()
        with os.fdopen(descriptor, "w+b") as stream:
            completed = subprocess.run(
                [
                    "git",
                    "diff",
                    "--binary",
                    "--full-index",
                    "--no-renames",
                    "--no-color",
                    "--no-ext-diff",
                    "--no-textconv",
                    f"{base_sha}^{{tree}}",
                    f"{head_sha}^{{tree}}",
                    "--",
                ],
                cwd=repository_path,
                env=clean_environment(),
                stdout=stream,
                stderr=subprocess.PIPE,
                check=False,
                timeout=180,
            )
            require(completed.returncode == 0, "promotion-diff-failed")
            stream.flush()
            size = stream.tell()
            require(size > 0, "promotion-diff-empty")
            stream.seek(0)
            hasher = hashlib.sha256()
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                hasher.update(block)
        return {"bytes": size, "sha256": hasher.hexdigest()}
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass


def verify(arguments: argparse.Namespace) -> JSON:
    require(
        re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", arguments.repository)
        is not None,
        "repository",
    )
    require(arguments.repository.startswith("lightning-it/"), "repository-owner")
    require(arguments.base_ref == "main", "base-ref")
    require(arguments.head_ref == "develop", "head-ref")
    expected_base = sha(arguments.expected_base, "expected-base")
    expected_head = sha(arguments.expected_head, "expected-head")
    controller_sha = sha(arguments.controller_sha, "controller-sha")
    expected_body_sha256 = text(arguments.expected_body_sha256, "expected-body-sha256")
    require(
        SHA256.fullmatch(expected_body_sha256) is not None,
        "expected-body-sha256",
    )
    pull_number = integer(arguments.pull_request, "pull-request")
    repository_path = validate_repository_path(arguments.repository_path)

    live_pull = gh_json(["api", f"repos/{arguments.repository}/pulls/{pull_number}"])
    validate_live_promotion(
        live_pull,
        repository=arguments.repository,
        pull_number=pull_number,
        expected_base=expected_base,
        expected_head=expected_head,
    )
    require(
        promotion_body_sha256(live_pull) == expected_body_sha256,
        "promotion-event-body-mismatch",
    )
    baseline_commit = exact_object(
        gh_json(["api", f"repos/{arguments.repository}/commits/{expected_base}"]),
        "baseline-commit",
    )
    require(baseline_commit.get("sha") == expected_base, "baseline-commit-sha")
    baseline_verification = exact_object(
        exact_object(baseline_commit.get("commit"), "baseline-git-commit").get(
            "verification"
        ),
        "baseline-verification",
    )
    require(baseline_verification.get("verified") is True, "baseline-not-verified")
    require(
        baseline_verification.get("reason") == "valid", "baseline-verification-reason"
    )
    baseline_committer = exact_object(
        exact_object(baseline_commit.get("commit"), "baseline-git-commit").get(
            "committer"
        ),
        "baseline-committer",
    )
    baseline_time_raw = text(baseline_committer.get("date"), "baseline-date")
    timestamp(baseline_time_raw, "baseline-date")
    history_anchor, integration_tree, merges = first_parent_merges(
        repository_path, expected_base, expected_head
    )
    diff = compute_diff(repository_path, expected_base, expected_head)
    ingress_inventory: list[tuple[JSON, JSON]] = []
    for merge in merges:
        associated_pages = gh_json(
            [
                "api",
                "--paginate",
                "--slurp",
                "-H",
                "Accept: application/vnd.github+json",
                f"repos/{arguments.repository}/commits/{merge['merge_sha']}/pulls?per_page=100",
            ]
        )
        pull = select_ingress_pull(
            flatten_pull_pages(associated_pages),
            repository=arguments.repository,
            merge_sha=merge["merge_sha"],
            head_sha=merge["head_sha"],
        )
        ingress_inventory.append((merge, pull))

    baseline_candidates = [
        index
        for index, (merge, pull) in enumerate(ingress_inventory)
        if is_ancestor(repository_path, expected_base, merge["head_sha"])
        and has_exact_ancestry_merge_parents(
            repository_path,
            head_sha=merge["head_sha"],
            previous_develop=merge["base_sha"],
            expected_main=expected_base,
        )
        and is_authorized_ancestry_boundary(
            pull,
            repository=arguments.repository,
            expected_main=expected_base,
            previous_develop=merge["base_sha"],
        )
    ]
    require(len(baseline_candidates) == 1, "baseline-reconciliation-not-unique")
    baseline_boundary = baseline_candidates[0]
    boundary_merge, _ = ingress_inventory[baseline_boundary]
    validate_ancestry_boundary_content(
        repository_path,
        repository=arguments.repository,
        head_sha=boundary_merge["head_sha"],
        previous_develop=boundary_merge["base_sha"],
        expected_main=expected_base,
    )

    ingress: list[JSON] = []
    for index, (merge, pull) in enumerate(ingress_inventory):
        number = integer(pull.get("number"), "ingress-pull-number")
        merged_at = text(pull.get("merged_at"), "ingress-merged-at")
        timestamp(merged_at, "ingress-merged-at")
        ancestry_boundary, post_baseline = classify_ingress_position(
            index, baseline_boundary
        )
        if post_baseline:
            require(
                is_ancestor(repository_path, expected_base, merge["head_sha"]),
                "post-baseline-ingress-lost-main-ancestry",
            )
        review: JSON | None = None
        threads: JSON | None = None
        if not ancestry_boundary:
            try:
                ingress_merge_base = sha(
                    git(
                        ["merge-base", "--all", merge["base_sha"], merge["head_sha"]],
                        repository_path,
                    ),
                    "ingress-merge-base",
                )
                bound = collect_bound_ingress_evidence(
                    repository=arguments.repository,
                    pull=pull,
                    pull_number=number,
                    base_sha=merge["base_sha"],
                    head_sha=merge["head_sha"],
                    merge_base_sha=ingress_merge_base,
                )
                review = bound["review"]
                threads = bound["threads"]
            except EvidenceError as error:
                raise EvidenceError(f"ingress-pr-{number}:{error}") from error
        ingress.append(
            {
                **merge,
                "pull_request": number,
                "merged_at": merged_at,
                "ancestry_boundary": ancestry_boundary,
                "post_baseline": post_baseline,
                "review": review,
                "threads": threads,
            }
        )
    post_baseline_count = sum(item["post_baseline"] is True for item in ingress)
    require(post_baseline_count > 0, "no-post-baseline-ingress")

    # Finish every other mutable remote read before taking the final ingress
    # snapshot. No network operation is permitted between this snapshot and
    # constructing the evidence package.
    live_pull_after = gh_json(
        ["api", f"repos/{arguments.repository}/pulls/{pull_number}"]
    )
    validate_live_promotion(
        live_pull_after,
        repository=arguments.repository,
        pull_number=pull_number,
        expected_base=expected_base,
        expected_head=expected_head,
    )
    require(
        promotion_body_sha256(live_pull_after) == expected_body_sha256,
        "promotion-event-body-mismatch",
    )
    require(
        canonical(promotion_binding(live_pull_after))
        == canonical(promotion_binding(live_pull)),
        "promotion-mutated-during-verification",
    )
    validate_protected_ref_tips(
        arguments.repository,
        expected_base=expected_base,
        expected_head=expected_head,
    )

    # Re-read every mutable ingress acceptance binding after all other remote
    # validation. The package below is built from these final values, while the
    # comparisons retain the earlier observation as a race detector.
    for item in ingress:
        ancestry_boundary = item.get("ancestry_boundary") is True
        number = integer(item.get("pull_request"), "revalidation-pull-number")
        try:
            live_ingress = gh_json(
                ["api", f"repos/{arguments.repository}/pulls/{number}"]
            )
            refreshed_pull = select_ingress_pull(
                [live_ingress],
                repository=arguments.repository,
                merge_sha=sha(item.get("merge_sha"), "revalidation-merge-sha"),
                head_sha=sha(item.get("head_sha"), "revalidation-head-sha"),
                expected_number=number,
            )
            require(
                text(refreshed_pull.get("merged_at"), "revalidation-merged-at")
                == item["merged_at"],
                "ingress-merge-mutated-during-verification",
            )
            if ancestry_boundary:
                require(
                    is_authorized_ancestry_boundary(
                        refreshed_pull,
                        repository=arguments.repository,
                        expected_main=expected_base,
                        previous_develop=sha(
                            item.get("base_sha"), "revalidation-base-sha"
                        ),
                    ),
                    "ancestry-boundary-mutated-during-verification",
                )
                continue
            refreshed = collect_bound_ingress_evidence(
                repository=arguments.repository,
                pull=refreshed_pull,
                pull_number=number,
                base_sha=sha(item.get("base_sha"), "revalidation-base-sha"),
                head_sha=sha(item.get("head_sha"), "revalidation-head-sha"),
                merge_base_sha=sha(
                    git(
                        [
                            "merge-base",
                            "--all",
                            sha(item.get("base_sha"), "revalidation-base-sha"),
                            sha(item.get("head_sha"), "revalidation-head-sha"),
                        ],
                        repository_path,
                    ),
                    "revalidation-merge-base",
                ),
            )
            require(
                canonical(refreshed["review"]) == canonical(item["review"])
                and canonical(refreshed["threads"]) == canonical(item["threads"]),
                "ingress-evidence-mutated-during-verification",
            )
            item["review"] = refreshed["review"]
            item["threads"] = refreshed["threads"]
        except EvidenceError as error:
            raise EvidenceError(f"ingress-pr-{number}:{error}") from error

    evidence = {
        "schema_version": 1,
        "repository": arguments.repository,
        "pull_request": pull_number,
        "base_ref": "main",
        "base_sha": expected_base,
        "head_ref": "develop",
        "head_sha": expected_head,
        "merge_base_sha": expected_base,
        "baseline_committer_date": baseline_time_raw,
        "history_anchor_sha": history_anchor,
        "integration_tree_sha": integration_tree,
        "diff": diff,
        "controller_sha": controller_sha,
        "ingress_count": len(ingress),
        "post_baseline_ingress_count": post_baseline_count,
        "ingress": ingress,
    }
    return {**evidence, "evidence_sha256": digest(evidence)}


def write_output(path: Path, value: JSON) -> None:
    runner_temp = private_runtime_directory()
    require(path.is_absolute(), "output-not-absolute")
    require(path.parent == runner_temp, "output-outside-runner-temp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        payload = canonical(value)
        written = 0
        while written < len(payload):
            count = os.write(descriptor, payload[written:])
            require(count > 0, "output-short-write")
            written += count
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def parse_arguments(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True)
    parser.add_argument("--pull-request", required=True, type=int)
    parser.add_argument("--base-ref", required=True)
    parser.add_argument("--head-ref", required=True)
    parser.add_argument("--expected-base", required=True)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--controller-sha", required=True)
    parser.add_argument("--expected-body-sha256", required=True)
    parser.add_argument("--repository-path", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args(argv)


def main() -> int:
    if sys.argv[1:] == ["--serve-github-api-proxy"]:
        try:
            serve_github_api_proxy()
        except (EvidenceError, OSError) as error:
            print(f"promotion-evidence-proxy: {error}", file=sys.stderr)
            return 1
        return 0
    arguments = parse_arguments()
    try:
        result = verify(arguments)
        write_output(arguments.output, result)
    except (EvidenceError, OSError, subprocess.SubprocessError) as error:
        print(f"promotion-evidence: {error}", file=sys.stderr)
        return 1
    print(canonical(result).decode("utf-8"), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
