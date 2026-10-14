"""Bind one native, self-reviewable approval to a protected .github revision."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT = Path(__file__).with_name("verify-dot-github-current-revision.py")
SPEC = importlib.util.spec_from_file_location("dot_github_evidence", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Unable to load protected verifier")
EVIDENCE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EVIDENCE)

REPOSITORY = "lightning-it/.github"
REPOSITORY_ID = 1112629689
APPROVER_LOGIN = "litroc"
APPROVER_ID = 76040632
ENVIRONMENT = "dot-github-policy-approval"
WORKFLOW = ".github/workflows/dot-github-current-revision-required.yml"
SOURCE_PATHS = (WORKFLOW, "scripts/verify-dot-github-current-revision.py",
                "scripts/dot-github-policy-approval.py", "scripts/dot-github-policy-devtools.sh",
                "scripts/wunder-devtools-ee.sh")
APPROVAL_JOB = "Approve dot-github policy revision"
BINDING_JOB = "Bind protected dot-github approval revision"
FINAL_JOB = "Required dot-github current-revision workflow"
MAX_LOG_BYTES = 4_000_000
MARKER = re.compile(r"^(?:\d{4}-\d\d-\d\dT\S+\s+)?LI319_APPROVAL_BINDING=([0-9a-f]{64})$")


def positive_integer(value: Any, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise EVIDENCE.VerificationError(f"{label} must be a positive integer")
    return value


def approval_environment(client: Any) -> int:
    """The native environment, not a PR-controlled flag, owns admission."""
    value = EVIDENCE.require_mapping(
        client.get(f"repos/{REPOSITORY}/environments/{ENVIRONMENT}"), "approval environment")
    EVIDENCE.require_equal(value.get("name"), ENVIRONMENT, "environment name")
    if value.get("can_admins_bypass") is not False:
        raise EVIDENCE.VerificationError("environment bypass must be false")
    policy = value.get("deployment_branch_policy")
    if (not isinstance(policy, dict)
            or set(policy) != {"protected_branches", "custom_branch_policies"}
            or policy["protected_branches"] is not True
            or policy["custom_branch_policies"] is not False):
        raise EVIDENCE.VerificationError("environment branch policy is not exactly bound")
    rules = EVIDENCE.require_list(value.get("protection_rules"), "environment rules")
    if sorted(r.get("type", "") for r in rules if isinstance(r, dict)) != [
            "branch_policy", "required_reviewers"] or len(rules) != 2:
        raise EVIDENCE.VerificationError("unexpected environment protection rules")
    rule = next(r for r in rules if r["type"] == "required_reviewers")
    if rule.get("prevent_self_review") is not False:
        raise EVIDENCE.VerificationError("self-review must be allowed")
    reviewers = EVIDENCE.require_list(rule.get("reviewers"), "environment reviewers")
    if len(reviewers) != 1:
        raise EVIDENCE.VerificationError("exactly one authorized reviewer is required")
    reviewer = EVIDENCE.require_mapping(reviewers[0], "environment reviewer")
    EVIDENCE.require_equal(reviewer.get("type"), "User", "reviewer type")
    user = EVIDENCE.require_mapping(reviewer.get("reviewer"), "reviewer identity")
    EVIDENCE.require_equal(positive_integer(user.get("id"), "reviewer ID"), APPROVER_ID,
                           "reviewer ID")
    EVIDENCE.require_equal(user.get("login"), APPROVER_LOGIN, "reviewer login")
    return positive_integer(value.get("id"), "environment ID")


def revision(client: Any, environment: dict[str, str]) -> tuple[dict[str, Any], str]:
    EVIDENCE.require_equal(environment.get("REPOSITORY"), REPOSITORY, "target repository")
    source = EVIDENCE.require_sha(environment.get("WORKFLOW_SHA", ""), "source SHA")
    EVIDENCE.validate_source(client, environment.get("WORKFLOW_REF", ""), source)
    active = EVIDENCE.require_mapping(
        client.get(f"repos/{REPOSITORY}/branches/main"), "active source branch")
    commit = EVIDENCE.require_mapping(active.get("commit"), "active source commit")
    EVIDENCE.require_equal(commit.get("sha"), source, "active approval controller")
    binding = EVIDENCE.event_pr_binding(environment)
    number = EVIDENCE.require_positive_integer(environment.get("PR_NUMBER", ""), "PR number")
    base = EVIDENCE.require_sha(environment.get("EVENT_BASE", ""), "base SHA")
    head = EVIDENCE.require_sha(environment.get("EVENT_HEAD", ""), "head SHA")
    if base == head:
        raise EVIDENCE.VerificationError("base and head must differ")
    pr = EVIDENCE.validate_live_pr(client, number, base, head, binding)
    environment_id = approval_environment(client)
    value = {"schema": 1, "repository_id": REPOSITORY_ID, "pr": number,
             "base": base, "head": head, "base_ref": binding["base_ref"],
             "source": source, "workflow_ref": environment["WORKFLOW_REF"],
             "head_repository": binding["head_repository"], "head_ref": binding["head_ref"],
             "head_repository_id": positive_integer(pr["head"]["repo"].get("id"), "head repository ID"),
             "author": binding["author"], "author_type": binding["author_type"],
             "title": pr.get("title"), "body": pr.get("body"),
             "labels_sha256": binding["labels_sha256"],
             "metadata_revision": pr["_metadata_revision"],
             "environment_id": environment_id, "approver_id": APPROVER_ID,
             "event_mode": environment.get("LI219_EVENT_MODE", "disabled")}
    digest = hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return value, digest


def native_approval(client: Any, run_id: int, environment_id: int) -> None:
    reviews = EVIDENCE.require_list(
        client.get(f"repos/{REPOSITORY}/actions/runs/{run_id}/approvals"), "native approvals")
    matching = []
    for review in reviews:
        review = EVIDENCE.require_mapping(review, "native approval")
        environments = EVIDENCE.require_list(review.get("environments"), "review environments")
        if not any(isinstance(e, dict) and type(e.get("id")) is int
                   and e["id"] == environment_id for e in environments):
            continue
        user = EVIDENCE.require_mapping(review.get("user"), "native reviewer")
        if (review.get("state") != "approved" or user.get("login") != APPROVER_LOGIN
                or positive_integer(user.get("id"), "native reviewer ID") != APPROVER_ID):
            raise EVIDENCE.VerificationError("native approval is rejected or unauthorized")
        matching.append(review)
    if not matching:
        raise EVIDENCE.VerificationError("native human approval is missing")


def log_binding(client: Any, job_id: int) -> str:
    # gh handles GitHub's authenticated log redirect without shell interpolation.
    # Only the protected .github repository and a validated numeric ID are used.
    result = subprocess.run(
        ["gh", "api", f"repos/{REPOSITORY}/actions/jobs/{job_id}/logs"],
        capture_output=True, timeout=30, check=True)
    if len(result.stdout) > MAX_LOG_BYTES:
        raise EVIDENCE.VerificationError("approval log exceeds its bounded input size")
    matches = [m.group(1) for line in result.stdout.decode("utf-8", errors="strict").splitlines()
               if (m := MARKER.fullmatch(line))]
    if len(matches) != 1:
        raise EVIDENCE.VerificationError("native approval binding is missing or ambiguous")
    return matches[0]


def native_run_binding(run: dict[str, Any], value: dict[str, Any]) -> bool:
    """Authenticate the native ruleset run, whose API head is the candidate."""
    api = f"https://api.github.com/repos/{REPOSITORY}"
    workflow_id = run.get("workflow_id")
    entries = run.get("pull_requests")
    if type(workflow_id) is not int or workflow_id <= 0 or not isinstance(entries, list) or len(entries) != 1:
        return False
    record = entries[0]
    if not isinstance(record, dict):
        return False
    return (run.get("workflow_url") == f"{api}/actions/required_workflows/{workflow_id}"
            and run.get("repository", {}).get("id") == REPOSITORY_ID
            and run.get("head_repository", {}).get("id") == value["head_repository_id"]
            and run.get("head_sha") == value["head"]
            and run.get("head_branch") == value["head_ref"]
            and record.get("number") == value["pr"]
            and record.get("url") == f"{api}/pulls/{value['pr']}"
            and record.get("base", {}).get("sha") == value["base"]
            and record.get("base", {}).get("ref") == value["base_ref"]
            and record.get("base", {}).get("repo", {}).get("id") == REPOSITORY_ID
            and record.get("head", {}).get("sha") == value["head"]
            and record.get("head", {}).get("ref") == value["head_ref"]
            and record.get("head", {}).get("repo", {}).get("id") == value["head_repository_id"])


def reusable_approval(client: Any, value: dict[str, Any], digest: str, current_run: int) -> int | None:
    """Reuse native approval of a protected preflight; verify technical evidence anew."""
    for page in range(1, 6):
        response = EVIDENCE.require_mapping(client.get(
            f"repos/{REPOSITORY}/actions/runs?event=pull_request_target&head_sha={value['head']}"
            f"&per_page=100&page={page}"), "prior workflow runs")
        runs = EVIDENCE.require_list(response.get("workflow_runs"), "prior runs")
        for run in runs:
            run = EVIDENCE.require_mapping(run, "prior workflow run")
            run_id = positive_integer(run.get("id"), "prior run ID")
            if (run_id == current_run or run.get("path") != WORKFLOW
                    or run.get("event") != "pull_request_target"
                    or not native_run_binding(run, value)
                    or type(run.get("run_attempt")) is not int or run["run_attempt"] != 1
                    or run.get("status") != "completed"
                    or run.get("conclusion") not in {"success", "failure", "cancelled"}):
                continue
            try:
                native_approval(client, run_id, value["environment_id"])
            except EVIDENCE.VerificationError as exc:
                if str(exc) == "native human approval is missing":
                    continue
                raise
            # Native run metadata binds its protected base tree. All three
            # executable files must match the actual required-source commit.
            same_code = True
            for path in SOURCE_PATHS:
                old = EVIDENCE.require_mapping(client.get(
                    f"repos/{REPOSITORY}/contents/{path}?ref={value['base']}"), "prior source file")
                new = EVIDENCE.require_mapping(client.get(
                    f"repos/{REPOSITORY}/contents/{path}?ref={value['source']}"), "current source file")
                if (old.get("type") != "file" or new.get("type") != "file"
                        or not EVIDENCE.SHA_PATTERN.fullmatch(str(old.get("sha", "")))
                        or old.get("sha") != new.get("sha")):
                    same_code = False
                    break
            if not same_code:
                continue
            jobs = []
            total = None
            for jobs_page in range(1, 11):
                inventory = EVIDENCE.require_mapping(client.get(
                    f"repos/{REPOSITORY}/actions/runs/{run_id}/attempts/1/jobs"
                    f"?per_page=100&page={jobs_page}"), "prior native jobs")
                entries = EVIDENCE.require_list(inventory.get("jobs"), "prior job page")
                count = positive_integer(inventory.get("total_count"), "prior job inventory count")
                if total is not None and count != total:
                    raise EVIDENCE.VerificationError("prior job inventory count drifted")
                total = count
                if len(entries) > 100 or any(not isinstance(j, dict) for j in entries):
                    raise EVIDENCE.VerificationError("prior job inventory is malformed")
                jobs.extend(entries)
                ids = [positive_integer(j.get("id"), "prior job ID") for j in jobs]
                if len(ids) != len(set(ids)) or len(jobs) > total:
                    raise EVIDENCE.VerificationError("prior job inventory is ambiguous")
                if len(jobs) == total:
                    break
                if len(entries) < 100:
                    raise EVIDENCE.VerificationError("prior job inventory is truncated")
            else:
                raise EVIDENCE.VerificationError("prior job inventory exceeds its bound")
            matches = [j for j in jobs if j.get("name") == BINDING_JOB]
            approval_jobs = [j for j in jobs if j.get("name") == APPROVAL_JOB]
            if len(matches) != 1 or len(approval_jobs) != 1:
                raise EVIDENCE.VerificationError("approved native run has ambiguous job evidence")
            if not all(type(j.get("run_id")) is int and j["run_id"] == run_id
                       and type(j.get("run_attempt")) is int and j["run_attempt"] == 1
                       and j.get("head_sha") == value["head"]
                       and j.get("status") == "completed" and j.get("conclusion") == "success"
                       for j in matches):
                raise EVIDENCE.VerificationError("approved native run has no successful protected binding")
            if not all(type(j.get("run_id")) is int and j["run_id"] == run_id
                       and type(j.get("run_attempt")) is int and j["run_attempt"] == 1
                       and j.get("head_sha") == value["head"] for j in approval_jobs):
                raise EVIDENCE.VerificationError("native approval job identity is inconsistent")
            native_approval(client, run_id, value["environment_id"])
            if log_binding(client, positive_integer(matches[0].get("id"), "approval job ID")) == digest:
                return run_id
        if len(runs) < 100:
            return None
    raise EVIDENCE.VerificationError("approval history exceeds the supported bounded window")


def output(name: str, value: str) -> None:
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as stream:
        stream.write(f"{name}={value}\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("preflight", "approve", "verify"))
    args = parser.parse_args()
    try:
        client = EVIDENCE.GitHubClient(os.environ.get("GH_TOKEN", ""),
                                       os.environ.get("GITHUB_API_URL", "https://api.github.com"))
        EVIDENCE.require_equal(os.environ.get("GITHUB_RUN_ATTEMPT"), "1", "native run attempt")
        value, digest = revision(client, dict(os.environ))
        run_id = EVIDENCE.require_positive_integer(os.environ.get("GITHUB_RUN_ID", ""), "run ID")
        if args.mode == "preflight":
            reuse = reusable_approval(client, value, digest, run_id)
            output("binding", digest)
            output("reuse-run", str(reuse) if reuse is not None else "")
            # The successful preflight fixes what the subsequent native human
            # approves. A later technical interruption cannot require reapproval.
            print(f"LI319_APPROVAL_BINDING={digest}", file=sys.stderr)
        else:
            EVIDENCE.require_equal(digest, os.environ.get("APPROVAL_BINDING", ""), "approval revision")
            if args.mode == "approve":
                native_approval(client, run_id, value["environment_id"])
                print(f"LI319_APPROVAL_BINDING={digest}")
            else:
                reuse = os.environ.get("APPROVAL_REUSE_RUN", "")
                if reuse:
                    expected = EVIDENCE.require_positive_integer(reuse, "reused run ID")
                    EVIDENCE.require_equal(reusable_approval(client, value, digest, run_id), expected,
                                           "reused native approval")
                else:
                    native_approval(client, run_id, value["environment_id"])
                attempts = 1 if os.environ.get("LI219_EVENT_MODE") == "enabled" else 60
                EVIDENCE.verify(client, os.environ, attempts=attempts)
                EVIDENCE.require_equal(revision(client, dict(os.environ))[1], digest,
                                       "final approval revision")
                print("Protected evidence and native single-person approval verified.")
    except (EVIDENCE.VerificationError, subprocess.SubprocessError, UnicodeError, OSError) as exc:
        print(f"ERROR: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
