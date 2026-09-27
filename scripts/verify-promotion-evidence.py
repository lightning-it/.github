#!/usr/bin/env python3
"""Verify native ingress evidence for an exact develop-to-main promotion.

The verifier intentionally does not review the cumulative promotion diff again.
It proves that the protected first-parent history between main and develop consists
only of GitHub merge commits whose exact PR heads already carry one successful,
bound ``Current revision review`` result and no unresolved review conversations.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
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
V4_EXTERNAL_ID = re.compile(
    r"^mlx90-current-revision:v4:(?P<run>[1-9][0-9]*):"
    r"(?P<input>[0-9a-f]{64})$"
)
RELEASE_APP_LOGIN = "lightning-it-release-automation[bot]"
RELEASE_APP_ID = 307565056
MAX_API_BYTES = 16 * 1024 * 1024
MAX_FIRST_PARENT_MERGES = 900
MAX_THREADS_PER_PULL = 1000


class EvidenceError(ValueError):
    """A promotion evidence invariant failed closed."""


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
        return json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as error:
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
    require(value.get("number") == pull_number, "promotion-number")
    require(value.get("state") == "open", "promotion-not-open")
    require(value.get("draft") is False, "promotion-not-ready")
    require(
        value.get("title") == "chore(release): promote develop to main",
        "promotion-title",
    )
    require(author.get("login") == RELEASE_APP_LOGIN, "promotion-author-login")
    require(author.get("id") == RELEASE_APP_ID, "promotion-author-id")
    require(author.get("type") == "Bot", "promotion-author-type")
    require(base.get("ref") == "main", "promotion-base-ref")
    require(base.get("sha") == expected_base, "promotion-base-sha")
    require(base_repo.get("full_name") == repository, "promotion-base-repository")
    require(head.get("ref") == "develop", "promotion-head-ref")
    require(head.get("sha") == expected_head, "promotion-head-sha")
    require(head_repo.get("full_name") == repository, "promotion-head-repository")
    return value


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
) -> JSON:
    candidates = []
    for item in exact_array(pulls, "associated-pulls"):
        pull = exact_object(item, "associated-pull")
        base = exact_object(pull.get("base"), "associated-pull-base")
        head = exact_object(pull.get("head"), "associated-pull-head")
        base_repo = exact_object(base.get("repo"), "associated-pull-base-repository")
        if (
            pull.get("state") == "closed"
            and pull.get("merged_at") is not None
            and pull.get("merge_commit_sha") == merge_sha
            and base.get("ref") == "develop"
            and base_repo.get("full_name") == repository
            and head.get("sha") == head_sha
        ):
            candidates.append(pull)
    require(len(candidates) == 1, "associated-pull-not-unique")
    candidate = candidates[0]
    integer(candidate.get("number"), "associated-pull-number")
    timestamp(candidate.get("merged_at"), "associated-pull-merged-at")
    return candidate


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


def bound_review_check(
    pages: Any,
    *,
    pull_number: int,
    base_sha: str,
    head_sha: str,
) -> JSON:
    matches: list[JSON] = []
    for check in check_pages(pages):
        app = exact_object(check.get("app"), "check-app")
        if not (
            check.get("name") == "Current revision review"
            and app.get("id") == 15368
            and app.get("slug") == "github-actions"
            and check.get("head_sha") == head_sha
            and check.get("status") == "completed"
            and check.get("conclusion") == "success"
        ):
            continue
        external_id = text(check.get("external_id"), "check-external-id")
        v6 = V6_EXTERNAL_ID.fullmatch(external_id)
        if v6 is not None:
            if (
                int(v6.group("pr")) == pull_number
                and v6.group("base") == base_sha
                and v6.group("head") == head_sha
            ):
                matches.append(
                    {
                        "check_id": integer(check.get("id"), "check-id"),
                        "evidence_kind": v6.group("kind"),
                        "external_id": external_id,
                        "producer_run_id": int(v6.group("run")),
                    }
                )
            continue
        v4 = V4_EXTERNAL_ID.fullmatch(external_id)
        if v4 is None:
            continue
        output = exact_object(check.get("output"), "check-output")
        summary = text(output.get("summary"), "check-summary")
        try:
            evidence = json.loads(summary)
        except json.JSONDecodeError as error:
            raise EvidenceError("exact-review-summary-not-json") from error
        evidence = exact_object(evidence, "exact-review-summary")
        if (
            evidence.get("schema") == 4
            and evidence.get("pull_request_number") == pull_number
            and evidence.get("base_sha") == base_sha
            and evidence.get("head_sha") == head_sha
            and evidence.get("producer_run_id") == int(v4.group("run"))
            and evidence.get("input_sha256") == v4.group("input")
        ):
            matches.append(
                {
                    "check_id": integer(check.get("id"), "check-id"),
                    "evidence_kind": "release-app",
                    "external_id": external_id,
                    "producer_run_id": int(v4.group("run")),
                }
            )
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
    for item in nodes:
        thread = exact_object(item, "review-thread")
        require(type(thread.get("isResolved")) is bool, "review-thread-resolution")
        if thread["isResolved"] is False:
            unresolved += 1
    require(unresolved == 0, "unresolved-review-thread")
    return {"resolved_threads": len(nodes), "unresolved_threads": unresolved}


THREAD_QUERY = """
query($owner:String!,$name:String!,$number:Int!,$after:String){
  repository(owner:$owner,name:$name){
    pullRequest(number:$number){
      number
      reviewThreads(first:100,after:$after){
        nodes{isResolved}
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
        data = exact_object(payload.get("data"), "thread-data")
        repo = exact_object(data.get("repository"), "thread-repository")
        pull = exact_object(repo.get("pullRequest"), "thread-pull")
        require(pull.get("number") == pull_number, "thread-pull-number")
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


def compute_diff(repository_path: Path, base_sha: str, head_sha: str) -> JSON:
    runner_temp = Path(os.environ.get("RUNNER_TEMP", ""))
    require(runner_temp.is_absolute(), "runner-temp-not-absolute")
    metadata = runner_temp.lstat()
    require(
        stat.S_ISDIR(metadata.st_mode) and not runner_temp.is_symlink(),
        "runner-temp-unsafe",
    )
    descriptor, name = tempfile.mkstemp(prefix="promotion-diff.", dir=runner_temp)
    os.close(descriptor)
    path = Path(name)
    try:
        with path.open("wb") as stream:
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
        size = path.stat().st_size
        require(size > 0, "promotion-diff-empty")
        hasher = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                hasher.update(block)
        return {"bytes": size, "sha256": hasher.hexdigest()}
    finally:
        path.unlink(missing_ok=True)


def verify(arguments: argparse.Namespace) -> JSON:
    require(
        re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", arguments.repository)
        is not None,
        "repository",
    )
    require(arguments.base_ref == "main", "base-ref")
    require(arguments.head_ref == "develop", "head-ref")
    expected_base = sha(arguments.expected_base, "expected-base")
    expected_head = sha(arguments.expected_head, "expected-head")
    controller_sha = sha(arguments.controller_sha, "controller-sha")
    pull_number = integer(arguments.pull_request, "pull-request")
    repository_path = arguments.repository_path.resolve()

    live_pull = gh_json(["api", f"repos/{arguments.repository}/pulls/{pull_number}"])
    validate_live_promotion(
        live_pull,
        repository=arguments.repository,
        pull_number=pull_number,
        expected_base=expected_base,
        expected_head=expected_head,
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
    baseline_boundary: int | None = None
    for index, merge in enumerate(merges):
        if is_ancestor(repository_path, expected_base, merge["head_sha"]):
            baseline_boundary = index
            break
    require(baseline_boundary is not None, "baseline-reconciliation-not-found")
    ingress: list[JSON] = []
    for index, merge in enumerate(merges):
        associated = gh_json(
            [
                "api",
                "-H",
                "Accept: application/vnd.github+json",
                f"repos/{arguments.repository}/commits/{merge['merge_sha']}/pulls?per_page=100",
            ]
        )
        pull = select_ingress_pull(
            associated,
            repository=arguments.repository,
            merge_sha=merge["merge_sha"],
            head_sha=merge["head_sha"],
        )
        number = integer(pull.get("number"), "ingress-pull-number")
        merged_at = text(pull.get("merged_at"), "ingress-merged-at")
        timestamp(merged_at, "ingress-merged-at")
        post_baseline = index >= baseline_boundary
        if post_baseline:
            require(
                is_ancestor(repository_path, expected_base, merge["head_sha"]),
                "post-baseline-ingress-lost-main-ancestry",
            )
        review: JSON | None = None
        threads: JSON | None = None
        if post_baseline:
            checks = gh_json(
                [
                    "api",
                    "--paginate",
                    "--slurp",
                    (
                        f"repos/{arguments.repository}/commits/{merge['head_sha']}/check-runs"
                        "?check_name=Current%20revision%20review&filter=all&per_page=100"
                    ),
                ]
            )
            try:
                review = bound_review_check(
                    checks,
                    pull_number=number,
                    base_sha=merge["base_sha"],
                    head_sha=merge["head_sha"],
                )
                threads = validate_review_threads(
                    collect_review_threads(arguments.repository, number)
                )
            except EvidenceError as error:
                raise EvidenceError(f"ingress-pr-{number}:{error}") from error
        ingress.append(
            {
                **merge,
                "pull_request": number,
                "merged_at": merged_at,
                "post_baseline": post_baseline,
                "review": review,
                "threads": threads,
            }
        )
    post_baseline_count = sum(item["post_baseline"] is True for item in ingress)
    require(post_baseline_count > 0, "no-post-baseline-ingress")

    # Mutable bindings are deliberately read again after the complete inventory.
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
        canonical(promotion_binding(live_pull_after))
        == canonical(promotion_binding(live_pull)),
        "promotion-mutated-during-verification",
    )

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
    if path.exists():
        metadata = path.lstat()
        require(stat.S_ISREG(metadata.st_mode), "output-not-regular")
    path.write_bytes(canonical(value))
    path.chmod(0o600)


def parse_arguments(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True)
    parser.add_argument("--pull-request", required=True, type=int)
    parser.add_argument("--base-ref", required=True)
    parser.add_argument("--head-ref", required=True)
    parser.add_argument("--expected-base", required=True)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--controller-sha", required=True)
    parser.add_argument("--repository-path", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args(argv)


def main() -> int:
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
