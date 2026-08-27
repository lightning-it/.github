#!/usr/bin/env python3
"""Verify one protected REP-60 main trust-root bootstrap.

The verifier is loaded from the organization-owned Required Workflow commit.
It is deliberately read-only: the calling workflow alone may publish the
neutral result after this script has returned canonical evidence twice.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from typing import Any, Callable


SOURCE_REPOSITORY = "lightning-it/shared-assets-lit"
SOURCE_BRANCH = "main"
EXPECTED_TITLE = "fix(rep60): bootstrap protected main review trust root"
EXPECTED_HEAD_REF = re.compile(
    r"^fix/rep60-main-trust-root-(?:successor|bootstrap)-v[1-9][0-9]*-[0-9]{8}$"
)
EXPECTED_FILES = frozenset(
    {
        ".github/codex/prompts/review-exact-head.md",
        ".github/codex/schemas/exact-head-review.schema.json",
        ".github/workflows/current-revision-rerun.yml",
        ".github/workflows/release-bot-exact-head-review.yml",
        "scripts/materialize-exact-revision-review.py",
    }
)
PREDECESSOR_FILES = frozenset(
    {
        ".github/codex/prompts/review-exact-head.md",
        ".github/codex/schemas/exact-head-review.schema.json",
        ".github/workflows/release-bot-exact-head-review.yml",
    }
)
COPILOT_LOGINS = {
    "copilot-pull-request-reviewer",
    "copilot-pull-request-reviewer[bot]",
    "github-copilot[bot]",
}
REJECTED_REVIEW_MARKERS = {
    "unabletoreviewthispullrequest",
    "nofileswerereviewed",
    "premiumrequestquota",
    "premiumrequestsquota",
    "encounteredanerror",
    "suppressedcomments",
}
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
REPOSITORY_RE = re.compile(r"^lightning-it/[A-Za-z0-9_.-]+$")
API_TIMEOUT_SECONDS = 30
MAX_REVIEW_THREAD_PAGES = 10

TreeEntry = dict[str, Any]
TreeEntries = dict[str, TreeEntry]
TreeCache = dict[str, TreeEntries]


class VerificationError(RuntimeError):
    """The candidate resembles a bootstrap but violates its contract."""


class NotApplicable(RuntimeError):
    """The pull request does not change the exact bootstrap path set."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def require_dict(value: Any, name: str) -> dict[str, Any]:
    require(isinstance(value, dict), f"{name} must be an object")
    return value


def require_list(value: Any, name: str) -> list[Any]:
    require(isinstance(value, list), f"{name} must be an array")
    return value


def require_string(value: Any, name: str) -> str:
    require(isinstance(value, str) and bool(value), f"{name} must be a string")
    return value


def require_positive_int(value: Any, name: str) -> int:
    require(
        isinstance(value, int) and not isinstance(value, bool) and value > 0,
        f"{name} must be a positive integer",
    )
    return value


def parse_timestamp(value: Any, name: str) -> dt.datetime:
    text = require_string(value, name)
    require(text.endswith("Z"), f"{name} must be UTC")
    try:
        parsed = dt.datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as error:
        raise VerificationError(f"{name} is malformed") from error
    require(parsed.tzinfo is not None, f"{name} lacks a timezone")
    return parsed


def normalized_review_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


@dataclass(frozen=True)
class GitHubAPI:
    target_token: str
    source_token: str

    @staticmethod
    def _invoke(arguments: list[str], token: str) -> Any:
        require(bool(token), "GitHub API token is missing")
        environment = os.environ.copy()
        environment["GH_TOKEN"] = token
        environment["GH_PROMPT_DISABLED"] = "1"
        try:
            result = subprocess.run(
                ["gh", "api", *arguments],
                check=False,
                capture_output=True,
                env=environment,
                text=True,
                timeout=API_TIMEOUT_SECONDS,
            )
        except FileNotFoundError as error:
            raise VerificationError("gh is unavailable") from error
        except subprocess.TimeoutExpired as error:
            raise VerificationError("GitHub API request timed out") from error
        if result.returncode != 0:
            detail = result.stderr.strip() or "unknown GitHub API error"
            raise VerificationError(f"GitHub API request failed: {detail}")
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise VerificationError("GitHub API returned malformed JSON") from error

    def target(self, endpoint: str) -> Any:
        return self._invoke([endpoint], self.target_token)

    def source(self, endpoint: str) -> Any:
        return self._invoke([endpoint], self.source_token)

    def target_pages(self, endpoint: str) -> list[Any]:
        pages = self._invoke(["--paginate", "--slurp", endpoint], self.target_token)
        return require_list(pages, "paginated response")

    def target_graphql(self, query: str, variables: dict[str, str | int]) -> Any:
        arguments = ["graphql", "-f", f"query={query}"]
        for name, value in variables.items():
            flag = "-F" if isinstance(value, int) else "-f"
            arguments.extend([flag, f"{name}={value}"])
        return self._invoke(arguments, self.target_token)


def flatten_array_pages(pages: list[Any], name: str) -> list[Any]:
    flattened: list[Any] = []
    require(bool(pages), f"{name} pagination is empty")
    for index, page in enumerate(pages):
        flattened.extend(require_list(page, f"{name} page {index}"))
    return flattened


def flatten_object_pages(pages: list[Any], key: str, name: str) -> list[Any]:
    flattened: list[Any] = []
    require(bool(pages), f"{name} pagination is empty")
    for index, raw_page in enumerate(pages):
        page = require_dict(raw_page, f"{name} page {index}")
        flattened.extend(require_list(page.get(key), f"{name} page {index}.{key}"))
    return flattened


def tree_entries(payload: Any, name: str) -> TreeEntries:
    tree = require_dict(payload, name)
    require(tree.get("truncated") is False, f"{name} is truncated")
    entries: TreeEntries = {}
    for raw_entry in require_list(tree.get("tree"), f"{name}.tree"):
        entry = require_dict(raw_entry, f"{name} entry")
        path = require_string(entry.get("path"), f"{name} entry path")
        require(path not in entries, f"{name} contains duplicate path {path}")
        entries[path] = entry
    return entries


def resolve_tree_asset(
    fetch_tree: Callable[[str], Any],
    root_tree_sha: str,
    path: str,
    name: str,
    cache: TreeCache,
    *,
    required: bool = True,
) -> TreeEntry | None:
    require(SHA_RE.fullmatch(root_tree_sha) is not None, f"{name} root tree is invalid")
    components = path.split("/")
    require(
        bool(components)
        and all(component not in {"", ".", ".."} for component in components),
        f"{name} path is invalid",
    )
    current_tree_sha = root_tree_sha
    traversed: list[str] = []
    for index, component in enumerate(components):
        tree_name = "/".join(traversed) or "/"
        if current_tree_sha not in cache:
            cache[current_tree_sha] = tree_entries(
                fetch_tree(current_tree_sha), f"{name} tree {tree_name}"
            )
        entries = cache[current_tree_sha]
        if component not in entries:
            if required:
                raise VerificationError(f"{name} is missing {path}")
            return None
        entry = entries[component]
        entry_sha = str(entry.get("sha", ""))
        require(
            SHA_RE.fullmatch(entry_sha) is not None,
            f"{name} {path} object is invalid",
        )
        if index == len(components) - 1:
            require(entry.get("type") == "blob", f"{name} {path} is not a blob")
            require(
                entry.get("mode") == "100644",
                f"{name} {path} mode is not 100644",
            )
            return entry
        require(
            entry.get("type") == "tree" and entry.get("mode") == "040000",
            f"{name} {'/'.join(components[: index + 1])} is not a tree",
        )
        traversed.append(component)
        current_tree_sha = entry_sha
    raise VerificationError(f"{name} path resolution ended unexpectedly")


def exact_pull_binding(
    pull: dict[str, Any], repository: str, number: int, base: str, head: str
) -> tuple[str, str]:
    require(pull.get("number") == number, "pull request number changed")
    require(pull.get("state") == "open", "pull request is not open")
    require(pull.get("draft") is False, "pull request is still a draft")
    require(pull.get("title") == EXPECTED_TITLE, "bootstrap title is not exact")
    user = require_dict(pull.get("user"), "pull request user")
    require(user.get("login") == "litroc", "bootstrap author is not litroc")
    require(user.get("type") == "User", "bootstrap author type is invalid")
    labels = require_list(pull.get("labels"), "pull request labels")
    require(not labels, "bootstrap pull request must not have labels")
    base_object = require_dict(pull.get("base"), "pull request base")
    head_object = require_dict(pull.get("head"), "pull request head")
    base_repo = require_dict(base_object.get("repo"), "pull request base repository")
    head_repo = require_dict(head_object.get("repo"), "pull request head repository")
    require(base_object.get("ref") == "main", "bootstrap base is not main")
    require(base_object.get("sha") == base, "bootstrap base SHA changed")
    require(base_repo.get("full_name") == repository, "bootstrap base repository changed")
    require(head_object.get("sha") == head, "bootstrap head SHA changed")
    require(head_repo.get("full_name") == repository, "bootstrap is not same-repository")
    head_ref = require_string(head_object.get("ref"), "pull request head ref")
    require(EXPECTED_HEAD_REF.fullmatch(head_ref) is not None, "bootstrap branch name is invalid")
    return require_string(base_object.get("ref"), "base ref"), head_ref


def exact_run_pull_binding(
    run: dict[str, Any], repository: str, number: int, base: str, head: str, head_ref: str
) -> bool:
    pulls = run.get("pull_requests")
    if not isinstance(pulls, list) or len(pulls) != 1:
        return False
    pull = pulls[0]
    if not isinstance(pull, dict):
        return False
    base_object = pull.get("base")
    head_object = pull.get("head")
    if not isinstance(base_object, dict) or not isinstance(head_object, dict):
        return False
    base_repo = base_object.get("repo")
    head_repo = head_object.get("repo")
    api_repository = f"https://api.github.com/repos/{repository}"
    return (
        pull.get("number") == number
        and pull.get("url") == f"{api_repository}/pulls/{number}"
        and base_object.get("ref") == "main"
        and base_object.get("sha") == base
        and isinstance(base_repo, dict)
        and base_repo.get("url") == api_repository
        and head_object.get("ref") == head_ref
        and head_object.get("sha") == head
        and isinstance(head_repo, dict)
        and head_repo.get("url") == api_repository
    )


def verify(args: argparse.Namespace, api: GitHubAPI) -> dict[str, Any]:
    repository = args.repository
    number = args.pull_request
    base = args.expected_base
    head = args.expected_head
    require(REPOSITORY_RE.fullmatch(repository) is not None, "repository is invalid")
    require(isinstance(number, int) and number > 0, "pull request number is invalid")
    require(SHA_RE.fullmatch(base) is not None, "expected base SHA is invalid")
    require(SHA_RE.fullmatch(head) is not None, "expected head SHA is invalid")
    require(SHA_RE.fullmatch(args.workflow_sha) is not None, "workflow SHA is invalid")

    target_repository = require_dict(api.target(f"repos/{repository}"), "target repository")
    owner = require_dict(target_repository.get("owner"), "target owner")
    require(target_repository.get("full_name") == repository, "target repository changed")
    require(owner.get("login") == "lightning-it", "target owner changed")
    require(target_repository.get("archived") is False, "target repository is archived")
    require(target_repository.get("disabled") is False, "target repository is disabled")
    require(target_repository.get("default_branch") == "develop", "target default branch is not develop")

    pull = require_dict(api.target(f"repos/{repository}/pulls/{number}"), "pull request")
    _, head_ref = exact_pull_binding(pull, repository, number, base, head)

    comparison = require_dict(api.target(f"repos/{repository}/compare/{base}...{head}"), "comparison")
    files = require_list(comparison.get("files"), "comparison files")
    observed_paths = {
        require_string(require_dict(item, "comparison file").get("filename"), "comparison filename")
        for item in files
    }
    expected_paths = set(EXPECTED_FILES)
    if not observed_paths & expected_paths:
        raise NotApplicable("pull request is not an exact trust-root bootstrap")
    require(
        observed_paths <= expected_paths,
        "trust-root bootstrap diff contains an unrelated path",
    )
    require(
        "scripts/materialize-exact-revision-review.py" in observed_paths,
        "trust-root bootstrap diff is missing the permanent materializer",
    )
    require(
        len(files) == len(observed_paths),
        "bootstrap comparison contains duplicate files",
    )
    require(comparison.get("status") == "ahead", "bootstrap comparison is not ahead")
    require(comparison.get("ahead_by") == 1, "bootstrap must contain one commit")
    require(comparison.get("behind_by") == 0, "bootstrap comparison is behind")
    require(comparison.get("total_commits") == 1, "bootstrap total commit count is not one")
    require(require_dict(comparison.get("base_commit"), "comparison base").get("sha") == base, "comparison base changed")
    require(require_dict(comparison.get("merge_base_commit"), "comparison merge base").get("sha") == base, "comparison merge base changed")
    commits = require_list(comparison.get("commits"), "comparison commits")
    require(len(commits) == 1 and require_dict(commits[0], "comparison commit").get("sha") == head, "comparison head changed")
    comparison_files: dict[str, dict[str, Any]] = {}
    for raw_file in files:
        file_object = require_dict(raw_file, "comparison file")
        path = require_string(file_object.get("filename"), "comparison filename")
        require(path not in comparison_files, f"duplicate comparison file {path}")
        require(
            SHA_RE.fullmatch(str(file_object.get("sha", ""))) is not None,
            f"invalid blob for {path}",
        )
        comparison_files[path] = file_object

    main_branch = require_dict(api.target(f"repos/{repository}/branches/main"), "target main branch")
    require(main_branch.get("name") == "main", "target main branch name changed")
    require(main_branch.get("protected") is True, "target main branch is not protected")
    require(require_dict(main_branch.get("commit"), "target main commit").get("sha") == base, "live target main moved")
    develop_branch = require_dict(api.target(f"repos/{repository}/branches/develop"), "target develop branch")
    require(develop_branch.get("name") == "develop", "target develop branch name changed")
    require(develop_branch.get("protected") is True, "target develop branch is not protected")

    head_commit = require_dict(api.target(f"repos/{repository}/commits/{head}"), "head commit")
    require(head_commit.get("sha") == head, "head commit changed")
    parents = require_list(head_commit.get("parents"), "head parents")
    require(len(parents) == 1 and require_dict(parents[0], "head parent").get("sha") == base, "bootstrap head is not a direct child of main")
    require(require_dict(head_commit.get("author"), "head author").get("login") == "litroc", "head author is not litroc")
    require(require_dict(head_commit.get("committer"), "head committer").get("login") == "litroc", "head committer is not litroc")
    head_tree_sha = require_string(require_dict(require_dict(head_commit.get("commit"), "head commit data").get("tree"), "head tree").get("sha"), "head tree SHA")
    require(SHA_RE.fullmatch(head_tree_sha) is not None, "head tree SHA is invalid")

    base_commit = require_dict(api.target(f"repos/{repository}/commits/{base}"), "base commit")
    base_tree_sha = require_string(require_dict(require_dict(base_commit.get("commit"), "base commit data").get("tree"), "base tree").get("sha"), "base tree SHA")
    target_tree_cache: TreeCache = {}

    def target_tree(tree_sha: str) -> Any:
        return api.target(f"repos/{repository}/git/trees/{tree_sha}")

    base_copilot = resolve_tree_asset(
        target_tree,
        base_tree_sha,
        ".github/workflows/copilot-review.yml",
        "base tree",
        target_tree_cache,
    )
    head_copilot = resolve_tree_asset(
        target_tree,
        head_tree_sha,
        ".github/workflows/copilot-review.yml",
        "head tree",
        target_tree_cache,
    )
    require(base_copilot is not None, "base Copilot workflow is missing")
    require(head_copilot is not None, "head Copilot workflow is missing")
    require(base_copilot.get("sha") == head_copilot.get("sha"), "candidate controls its Copilot workflow")
    base_assets = {
        path: resolve_tree_asset(
            target_tree,
            base_tree_sha,
            path,
            "base tree",
            target_tree_cache,
            required=False,
        )
        for path in sorted(EXPECTED_FILES)
    }
    present_predecessors = {
        path for path in PREDECESSOR_FILES if base_assets[path] is not None
    }
    require(
        len(present_predecessors) in {0, len(PREDECESSOR_FILES)},
        "base contains a partial trust-root predecessor set",
    )
    for path, base_entry in base_assets.items():
        if path not in comparison_files:
            require(
                base_entry is not None,
                f"unchanged trust-root asset is missing from base: {path}",
            )
            continue
        expected_status = "added" if base_entry is None else "modified"
        require(
            comparison_files[path].get("status") == expected_status,
            f"unexpected status for {path}",
        )
    base_materializer = base_assets["scripts/materialize-exact-revision-review.py"]
    require(base_materializer is None, "base already contains the permanent materializer")

    source_repository = require_dict(api.source(f"repos/{SOURCE_REPOSITORY}"), "source repository")
    require(source_repository.get("full_name") == SOURCE_REPOSITORY, "source repository changed")
    source_branch = require_dict(api.source(f"repos/{SOURCE_REPOSITORY}/branches/{SOURCE_BRANCH}"), "source main branch")
    require(source_branch.get("name") == SOURCE_BRANCH, "source branch changed")
    require(source_branch.get("protected") is True, "source main branch is not protected")
    source_sha = require_string(require_dict(source_branch.get("commit"), "source main commit").get("sha"), "source SHA")
    require(SHA_RE.fullmatch(source_sha) is not None, "source SHA is invalid")
    source_commit = require_dict(api.source(f"repos/{SOURCE_REPOSITORY}/commits/{source_sha}"), "source commit")
    source_tree_sha = require_string(require_dict(require_dict(source_commit.get("commit"), "source commit data").get("tree"), "source tree").get("sha"), "source tree SHA")
    source_tree_cache: TreeCache = {}

    def source_tree(tree_sha: str) -> Any:
        return api.source(f"repos/{SOURCE_REPOSITORY}/git/trees/{tree_sha}")

    source_blobs: dict[str, str] = {}
    for path in sorted(EXPECTED_FILES):
        source_entry = resolve_tree_asset(
            source_tree,
            source_tree_sha,
            path,
            "source tree",
            source_tree_cache,
        )
        head_entry = resolve_tree_asset(
            target_tree,
            head_tree_sha,
            path,
            "head tree",
            target_tree_cache,
        )
        require(source_entry is not None, f"source tree is missing {path}")
        require(head_entry is not None, f"head tree is missing {path}")
        require(head_entry.get("sha") == source_entry.get("sha"), f"candidate {path} differs from protected source")
        source_blobs[path] = require_string(source_entry.get("sha"), f"source blob {path}")
        if path not in comparison_files:
            base_entry = base_assets[path]
            require(base_entry is not None, f"unchanged base asset is missing {path}")
            require(
                base_entry.get("sha") == source_blobs[path],
                f"unchanged protected base {path} differs from protected source",
            )
    for raw_file in files:
        file_object = require_dict(raw_file, "comparison file")
        path = require_string(file_object.get("filename"), "comparison filename")
        require(file_object.get("sha") == source_blobs[path], f"comparison blob differs for {path}")

    exact_checks = flatten_object_pages(
        api.target_pages(f"repos/{repository}/commits/{head}/check-runs?check_name=Protected%20Exact-Revision%20Codex%20result&filter=all&per_page=100"),
        "check_runs",
        "Exact-Revision checks",
    )
    require(not exact_checks, "human bootstrap must not have an Exact-Revision Codex check")

    timeline = flatten_array_pages(
        api.target_pages(f"repos/{repository}/issues/{number}/timeline?per_page=100"),
        "pull request timeline",
    )
    ready_events = [event for event in timeline if isinstance(event, dict) and event.get("event") == "ready_for_review"]
    require(len(ready_events) == 1, "bootstrap must have exactly one Ready transition")
    ready_event = require_dict(ready_events[0], "Ready event")
    require(require_dict(ready_event.get("actor"), "Ready actor").get("login") == "litroc", "Ready actor is not litroc")
    ready_at = parse_timestamp(ready_event.get("created_at"), "Ready timestamp")

    run_pages = api.target_pages(f"repos/{repository}/actions/runs?event=pull_request&head_sha={head}&per_page=100")
    runs = flatten_object_pages(run_pages, "workflow_runs", "workflow runs")
    producer_candidates: list[tuple[dict[str, Any], list[Any]]] = []
    successful_requests = 0
    for raw_run in runs:
        run = require_dict(raw_run, "workflow run")
        if not (
            run.get("event") == "pull_request"
            and run.get("path") == ".github/workflows/copilot-review.yml"
            and run.get("name") == "Copilot review gate"
            and run.get("head_branch") == head_ref
            and run.get("head_sha") == head
            and require_dict(run.get("actor"), "workflow actor").get("login") == "litroc"
            and require_dict(run.get("triggering_actor"), "workflow triggering actor").get("login") == "litroc"
            and exact_run_pull_binding(run, repository, number, base, head, head_ref)
        ):
            continue
        run_id = require_positive_int(run.get("id"), "workflow run id")
        jobs = flatten_object_pages(
            api.target_pages(f"repos/{repository}/actions/runs/{run_id}/jobs?filter=all&per_page=100"),
            "jobs",
            "workflow jobs",
        )
        request_jobs = [
            job
            for job in jobs
            if isinstance(job, dict)
            and job.get("name") == "Request Copilot review for current revision"
            and job.get("run_attempt") == 1
            and job.get("status") == "completed"
            and job.get("conclusion") == "success"
        ]
        successful_requests += len(request_jobs)
        gate_jobs = [
            job
            for job in jobs
            if isinstance(job, dict)
            and job.get("name") == "Successful Copilot review"
            and job.get("run_attempt") == 1
            and job.get("status") == "completed"
            and job.get("conclusion") == "success"
        ]
        if (
            run.get("run_attempt") == 1
            and run.get("status") == "completed"
            and run.get("conclusion") == "success"
            and len(request_jobs) == 1
            and len(gate_jobs) == 1
        ):
            producer_candidates.append((run, jobs))
    require(successful_requests == 1, "bootstrap must contain exactly one successful Copilot request")
    require(len(producer_candidates) == 1, "bootstrap Copilot producer is missing or ambiguous")
    producer = producer_candidates[0][0]
    producer_run_id = require_positive_int(producer.get("id"), "producer run id")
    producer_run_url = f"https://github.com/{repository}/actions/runs/{producer_run_id}"
    require(producer.get("html_url") == producer_run_url, "producer run URL changed")
    producer_started = parse_timestamp(producer.get("created_at"), "producer created timestamp")
    producer_finished = parse_timestamp(producer.get("updated_at"), "producer updated timestamp")
    require(ready_at <= producer_started, "Copilot producer started before Ready")
    require(producer_started <= producer_finished, "producer timestamps are reversed")

    reviews = flatten_array_pages(
        api.target_pages(f"repos/{repository}/pulls/{number}/reviews?per_page=100"),
        "pull request reviews",
    )
    copilot_reviews = [
        review
        for review in reviews
        if isinstance(review, dict)
        and isinstance(review.get("user"), dict)
        and review["user"].get("login") in COPILOT_LOGINS
    ]
    require(len(copilot_reviews) == 1, "bootstrap must contain exactly one Copilot review")
    review = require_dict(copilot_reviews[0], "Copilot review")
    review_id = require_positive_int(review.get("id"), "Copilot review id")
    review_user = require_dict(review.get("user"), "Copilot review user")
    require(review_user.get("login") == "copilot-pull-request-reviewer[bot]", "Copilot review login is invalid")
    require(review_user.get("type") == "Bot", "Copilot reviewer type is invalid")
    require(review.get("commit_id") == head, "Copilot review is not bound to the final head")
    require(review.get("state") in {"COMMENTED", "APPROVED"}, "Copilot review state is invalid")
    submitted_at_text = require_string(review.get("submitted_at"), "Copilot submitted timestamp")
    submitted_at = parse_timestamp(submitted_at_text, "Copilot submitted timestamp")
    require(producer_started <= submitted_at <= producer_finished, "Copilot review is outside the producer run")

    review_comments = flatten_array_pages(
        api.target_pages(f"repos/{repository}/pulls/{number}/reviews/{review_id}/comments?per_page=100"),
        "Copilot review comments",
    )
    review_texts = [str(review.get("body") or "")]
    for raw_comment in review_comments:
        comment = require_dict(raw_comment, "Copilot review comment")
        review_texts.append(str(comment.get("body") or ""))
    require(any(text.strip() for text in review_texts), "Copilot review is empty")
    normalized_texts = [normalized_review_text(text) for text in review_texts]
    for marker in REJECTED_REVIEW_MARKERS:
        require(not any(marker in text for text in normalized_texts), f"Copilot review contains rejected marker {marker}")

    owner_name, repository_name = repository.split("/", 1)
    query = """query($owner:String!,$repository:String!,$number:Int!,$after:String){repository(owner:$owner,name:$repository){pullRequest(number:$number){headRefOid reviewThreads(first:100,after:$after){pageInfo{hasNextPage endCursor} nodes{isResolved comments(first:100){pageInfo{hasNextPage} nodes{body author{login} pullRequestReview{commit{oid}}}}}}}}}"""
    after = ""
    seen_cursors: set[str] = set()
    threads: list[Any] = []
    for _page_number in range(1, MAX_REVIEW_THREAD_PAGES + 1):
        variables: dict[str, str | int] = {
            "owner": owner_name,
            "repository": repository_name,
            "number": number,
        }
        if after:
            variables["after"] = after
        response = require_dict(api.target_graphql(query, variables), "review thread response")
        require(not response.get("errors"), "review thread query returned errors")
        data = require_dict(response.get("data"), "review thread data")
        graph_repository = require_dict(data.get("repository"), "review thread repository")
        graph_pull = require_dict(graph_repository.get("pullRequest"), "review thread pull request")
        require(graph_pull.get("headRefOid") == head, "head changed during thread verification")
        connection = require_dict(graph_pull.get("reviewThreads"), "review threads")
        page_threads = require_list(connection.get("nodes"), "review thread nodes")
        threads.extend(page_threads)
        page_info = require_dict(connection.get("pageInfo"), "review thread page info")
        has_next_page = page_info.get("hasNextPage")
        require(isinstance(has_next_page, bool), "review thread hasNextPage is invalid")
        if not has_next_page:
            break
        next_cursor = require_string(page_info.get("endCursor"), "review thread cursor")
        require(next_cursor not in seen_cursors, "review thread pagination repeats a cursor")
        seen_cursors.add(next_cursor)
        after = next_cursor
    else:
        raise VerificationError("review thread pagination exceeds the page limit")

    thread_texts: list[str] = []
    for raw_thread in threads:
        thread = require_dict(raw_thread, "review thread")
        require(thread.get("isResolved") is True, "an unresolved review thread remains")
        comments = require_dict(thread.get("comments"), "review thread comments")
        require(require_dict(comments.get("pageInfo"), "review comments page info").get("hasNextPage") is False, "review thread comment pagination is incomplete")
        comment_nodes = require_list(comments.get("nodes"), "review thread comment nodes")
        require(bool(comment_nodes), "review thread has no comments")
        for raw_comment in comment_nodes:
            comment = require_dict(raw_comment, "review thread comment")
            thread_texts.append(str(comment.get("body") or ""))
    for marker in REJECTED_REVIEW_MARKERS:
        require(not any(marker in normalized_review_text(text) for text in thread_texts), f"review thread contains rejected marker {marker}")

    final_pull = require_dict(api.target(f"repos/{repository}/pulls/{number}"), "final pull request")
    exact_pull_binding(final_pull, repository, number, base, head)
    final_main = require_dict(api.target(f"repos/{repository}/branches/main"), "final target main branch")
    require(final_main.get("protected") is True, "target main lost protection")
    require(require_dict(final_main.get("commit"), "final target main commit").get("sha") == base, "target main moved during verification")
    final_source = require_dict(api.source(f"repos/{SOURCE_REPOSITORY}/branches/{SOURCE_BRANCH}"), "final source main branch")
    require(final_source.get("protected") is True, "source main lost protection")
    require(require_dict(final_source.get("commit"), "final source main commit").get("sha") == source_sha, "source main moved during verification")

    return {
        "base_sha": base,
        "candidate_tree_sha": head_tree_sha,
        "controller_blob_sha": require_string(base_copilot.get("sha"), "controller blob SHA"),
        "head_sha": head,
        "producer_run_id": producer_run_id,
        "producer_run_url": producer_run_url,
        "pull_request_number": number,
        "review_id": review_id,
        "review_path": "protected final-head pipeline Copilot trust-root bootstrap",
        "review_submitted_at": submitted_at_text,
        "schema": "rep60-main-trust-root-bootstrap/v1",
        "source_blobs": source_blobs,
        "source_repository": SOURCE_REPOSITORY,
        "source_sha": source_sha,
        "source_tree_sha": source_tree_sha,
        "threads_resolved": len(threads),
        "workflow_sha": args.workflow_sha,
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True)
    parser.add_argument("--pull-request", required=True, type=int)
    parser.add_argument("--expected-base", required=True)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--workflow-sha", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    target_token = os.environ.get("GH_TOKEN", "")
    source_token = os.environ.get("SOURCE_GH_TOKEN", "")
    try:
        evidence = verify(args, GitHubAPI(target_token, source_token))
    except NotApplicable as error:
        print(str(error), file=sys.stderr)
        return 3
    except VerificationError as error:
        print(f"REP-60 trust-root bootstrap verification failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(evidence, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
