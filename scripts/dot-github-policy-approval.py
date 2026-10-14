"""Bind one native, self-reviewable approval to a protected .github revision."""

from __future__ import annotations

import argparse
import base64
import time
import yaml
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
APPROVAL_JOB = "Approve dot-github policy revision"
BINDING_JOB = "Bind protected dot-github approval revision"
FINAL_JOB = "Required dot-github current-revision workflow"
METADATA_JOB = "dot-github / approved metadata"
MAX_LOG_BYTES = 4_000_000
MARKER = re.compile(r"^(?:\d{4}-\d\d-\d\dT\S+\s+)?LI319_APPROVAL_BINDING=([0-9a-f]{64})$")
SOURCE_MARKER = re.compile(r"^(?:\d{4}-\d\d-\d\dT\S+\s+)?LI319_PROTECTED_SOURCE=([0-9a-f]{40})$")


class SourceChanged(EVIDENCE.VerificationError):
    """A well-formed prior authorization belongs to another protected source."""


def positive_integer(value: Any, label: str) -> int:
    if not EVIDENCE.native_integer(value) or value <= 0:
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


def log_binding(client: Any, job_id: int, expected_source: str) -> str:
    # gh handles GitHub's authenticated log redirect without shell interpolation.
    # Only the protected .github repository and a validated numeric ID are used.
    result = subprocess.run(
        ["gh", "api", f"repos/{REPOSITORY}/actions/jobs/{job_id}/logs"],
        capture_output=True, timeout=30, check=True)
    if len(result.stdout) > MAX_LOG_BYTES:
        raise EVIDENCE.VerificationError("approval log exceeds its bounded input size")
    lines = result.stdout.decode("utf-8", errors="strict").splitlines()
    matches = [m.group(1) for line in lines
               if (m := MARKER.fullmatch(line))]
    sources = [m.group(1) for line in lines if (m := SOURCE_MARKER.fullmatch(line))]
    if len(matches) != 1 or len(sources) != 1:
        raise EVIDENCE.VerificationError("native approval/source binding is missing or ambiguous")
    if sources[0] != expected_source:
        raise SourceChanged("native authorization belongs to another protected source")
    return matches[0]


def native_run_binding(run: dict[str, Any], value: dict[str, Any], *, allow_local: bool = False) -> bool:
    """Authenticate the native ruleset run, whose API head is the candidate."""
    api = f"https://api.github.com/repos/{REPOSITORY}"
    workflow_id = run.get("workflow_id")
    entries = run.get("pull_requests")
    if type(workflow_id) is not int or workflow_id <= 0 or not isinstance(entries, list) or len(entries) != 1:
        return False
    record = entries[0]
    if not isinstance(record, dict):
        return False
    for side in ("base", "head"):
        if (not isinstance(record.get(side), dict)
                or not isinstance(record[side].get("repo"), dict)):
            return False
    if (not isinstance(run.get("repository"), dict)
            or not isinstance(run.get("head_repository"), dict)):
        return False
    if any(type(item) is not int for item in (
            run["repository"].get("id"), run["head_repository"].get("id"),
            record.get("number"), record["base"]["repo"].get("id"),
            record["head"]["repo"].get("id"))):
        return False
    allowed_urls = {f"{api}/actions/required_workflows/{workflow_id}"}
    if allow_local:
        allowed_urls.add(f"{api}/actions/workflows/{workflow_id}")
    return (run.get("workflow_url") in allowed_urls
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
                    or not EVIDENCE.native_integer(run.get("run_attempt")) or run["run_attempt"] not in {1, 2}
                    or run.get("status") != "completed"):
                # Technical outcome does not revoke genuine unchanged human
                # authorization; all current technical checks still run.
                continue
            approval_error = None
            try:
                native_approval(client, run_id, value["environment_id"])
            except EVIDENCE.VerificationError as exc:
                if str(exc) == "native human approval is missing":
                    continue
                approval_error = exc
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
            # Only a successful native Required-Workflow preflight owns this
            # receipt. It validates the actual workflow_sha against protected
            # main before emitting both source and exact-revision markers.
            try:
                prior = log_binding(client, positive_integer(matches[0].get("id"), "approval job ID"),
                                    value["source"])
            except SourceChanged:
                # A source change is a new revision requiring fresh admission;
                # it must neither reuse the old approval nor trap that revision.
                continue
            if prior == digest:
                if approval_error is not None:
                    raise approval_error
                if run["run_attempt"] == 2:
                    # Attempt 2 only reruns the final technical job. It cannot
                    # erase the already-consumed attempt-1 human authorization.
                    validate_final_recovery(client, value, digest, run_id)
                    recovered = EVIDENCE.native_jobs(client.get(
                        f"repos/{REPOSITORY}/actions/runs/{run_id}/attempts/2/jobs?per_page=100&page=1"),
                        run_id, 2, value["head"], "prior final recovery")
                    if (len(recovered) != 1 or recovered[0].get("name") != FINAL_JOB
                            or recovered[0].get("status") != "completed"
                            or recovered[0].get("conclusion") not in {"success", "failure", "cancelled", "timed_out"}):
                        raise EVIDENCE.VerificationError("prior recovery was not the sole bounded final job")
                native_approval(client, run_id, value["environment_id"])
                return run_id
        if len(runs) < 100:
            return None
    raise EVIDENCE.VerificationError("approval history exceeds the supported bounded window")


def output(name: str, value: str) -> None:
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as stream:
        stream.write(f"{name}={value}\n")


def validate_final_recovery(client: Any, value: dict[str, Any], digest: str, run_id: int) -> None:
    """Admit only the existing bot's final-job retry with intact first-attempt proof.

    Preflight and human admission never rerun. Current technical verification
    and native approval are still checked by the caller after this admission.
    """
    run = EVIDENCE.require_mapping(client.get(
        f"repos/{REPOSITORY}/actions/runs/{run_id}"), "recovery native run")
    for field, expected in (("id", run_id), ("run_attempt", 2),
                            ("event", "pull_request_target"), ("path", WORKFLOW)):
        EVIDENCE.require_equal(run.get(field), expected, f"recovery {field}")
    if not native_run_binding(run, value):
        raise EVIDENCE.VerificationError("recovery is not the bound native required workflow")
    actor = EVIDENCE.require_mapping(run.get("triggering_actor"), "recovery actor")
    EVIDENCE.require_equal(actor.get("login"), "github-actions[bot]", "recovery actor login")
    EVIDENCE.require_equal(actor.get("type"), "Bot", "recovery actor type")
    inventory = EVIDENCE.require_mapping(client.get(
        f"repos/{REPOSITORY}/actions/runs/{run_id}/attempts/1/jobs?per_page=100&page=1"),
        "original native jobs")
    jobs = EVIDENCE.require_list(inventory.get("jobs"), "original jobs")
    EVIDENCE.require_equal(inventory.get("total_count"), 4, "original job count")
    if len(jobs) != 4 or any(not isinstance(j, dict) for j in jobs):
        raise EVIDENCE.VerificationError("original job inventory is incomplete")
    ids = [positive_integer(j.get("id"), "original job ID") for j in jobs]
    if len(set(ids)) != 4 or sorted(j.get("name", "") for j in jobs) != sorted(
            (BINDING_JOB, APPROVAL_JOB, FINAL_JOB, METADATA_JOB)):
        raise EVIDENCE.VerificationError("original job inventory is ambiguous")
    for job in jobs:
        for field, expected in (("run_id", run_id), ("run_attempt", 1),
                                ("head_sha", value["head"]), ("status", "completed")):
            EVIDENCE.require_equal(job.get(field), expected, f"original job {field}")
        conclusion = job.get("conclusion")
        expected = ({"success"} if job["name"] == BINDING_JOB else
                    {"success", "skipped"} if job["name"] == APPROVAL_JOB else
                    {"skipped"} if job["name"] == METADATA_JOB else {"failure", "timed_out"})
        if conclusion not in expected:
            raise EVIDENCE.VerificationError("only the failed final technical job may recover")
    binding_job = next(j for j in jobs if j["name"] == BINDING_JOB)
    EVIDENCE.require_equal(log_binding(client, binding_job["id"], value["source"]), digest,
                           "original approved revision")


def metadata_controller(client: Any, value: dict[str, Any]) -> None:
    """The candidate supplies data; metadata controller orchestration stays main-owned."""
    documents = []
    for repository, ref in ((REPOSITORY, value["source"]),
                            (value["head_repository"], value["head"])):
        blob = EVIDENCE.require_mapping(client.get(
            f"repos/{repository}/contents/{WORKFLOW}?ref={ref}"), "metadata controller blob")
        if blob.get("type") != "file" or blob.get("encoding") != "base64":
            raise EVIDENCE.VerificationError("metadata controller is not a file blob")
        EVIDENCE.require_sha(blob.get("sha", ""), "metadata controller blob SHA")
        size = positive_integer(blob.get("size"), "metadata controller bytes")
        encoded = blob.get("content")
        if size > 200_000 or not isinstance(encoded, str) or len(encoded) > 300_000:
            raise EVIDENCE.VerificationError("metadata controller exceeds its bound")
        payload = base64.b64decode(''.join(encoded.split()), validate=True)
        if len(payload) != size:
            raise EVIDENCE.VerificationError("metadata controller byte count drifted")
        doc = EVIDENCE.require_mapping(yaml.safe_load(payload), "metadata controller YAML")
        documents.append(doc)
    canonical, candidate = documents
    for field in ("name", "run-name", "env", "defaults", "permissions", "concurrency"):
        EVIDENCE.require_equal(candidate.get(field), canonical.get(field), f"metadata controller {field}")
    EVIDENCE.require_equal(candidate.get("on", candidate.get(True)),
                           canonical.get("on", canonical.get(True)), "metadata controller event coverage")
    candidate_jobs = EVIDENCE.require_mapping(candidate.get("jobs"), "candidate jobs")
    canonical_jobs = EVIDENCE.require_mapping(canonical.get("jobs"), "canonical jobs")
    EVIDENCE.require_equal(sorted(candidate_jobs), sorted(canonical_jobs), "metadata controller job inventory")
    for job_id in canonical_jobs:
        EVIDENCE.require_equal(candidate_jobs[job_id].get("name"), canonical_jobs[job_id].get("name"),
                               "metadata controller native check names")
    EVIDENCE.require_equal(candidate_jobs.get("metadata"), canonical_jobs.get("metadata"),
                           "protected metadata job definition")


def audit_metadata(client: Any, environment: dict[str, str], run_id: int,
                   *, attempts: int = 90, sleep: Any = time.sleep) -> None:
    """Native pull_request job status blocks before any fallible setup begins."""
    if environment.get("GITHUB_EVENT_NAME") != "pull_request":
        raise EVIDENCE.VerificationError("metadata audit requires the native pull_request job envelope")
    value, digest = revision(client, environment)
    metadata_controller(client, value)
    run = EVIDENCE.require_mapping(client.get(f"repos/{REPOSITORY}/actions/runs/{run_id}"), "metadata native run")
    for field, expected in (("id", run_id), ("path", WORKFLOW), ("event", "pull_request"), ("run_attempt", 1)):
        EVIDENCE.require_equal(run.get(field), expected, f"metadata run {field}")
    # Both native Ruleset and ordinary PR metadata events must retain the exact
    # authenticated GitHub PR/head tuple; ordinary events use the local registry.
    if not native_run_binding(run, value, allow_local=True):
        raise EVIDENCE.VerificationError("metadata run is not bound to the exact current PR")
    reuse = None
    for attempt in range(attempts):
        reuse = reusable_approval(client, value, digest, run_id)
        if reuse is not None:
            break
        if attempt + 1 < attempts:
            sleep(10)
    if reuse is None:
        raise EVIDENCE.VerificationError("metadata has no matching completed native authorization")
    EVIDENCE.verify(client, environment, attempts=60)
    EVIDENCE.require_equal(revision(client, environment)[1], digest, "final metadata approval revision")
    EVIDENCE.require_equal(reusable_approval(client, value, digest, run_id), reuse, "final metadata native authorization")
    print(f"LI319_APPROVAL_BINDING={digest}")
    print(f"LI319_PROTECTED_SOURCE={value['source']}")
    print(f"LI319_APPROVAL_REUSE_RUN={reuse}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("preflight", "approve", "verify", "audit-metadata"))
    args = parser.parse_args()
    try:
        client = EVIDENCE.GitHubClient(os.environ.get("GH_TOKEN", ""),
                                       os.environ.get("GITHUB_API_URL", "https://api.github.com"))
        attempt = os.environ.get("GITHUB_RUN_ATTEMPT")
        if attempt != "1" and not (args.mode == "verify" and attempt == "2"):
            raise EVIDENCE.VerificationError("native run attempt is not admitted")
        run_id = EVIDENCE.require_positive_integer(os.environ.get("GITHUB_RUN_ID", ""), "run ID")
        if args.mode == "audit-metadata":
            audit_metadata(client, dict(os.environ), run_id)
            return 0
        value, digest = revision(client, dict(os.environ))
        metadata_controller(client, value)
        if attempt == "2":
            validate_final_recovery(client, value, digest, run_id)
        if args.mode == "preflight":
            reuse = reusable_approval(client, value, digest, run_id)
            output("binding", digest)
            output("reuse-run", str(reuse) if reuse is not None else "")
            # The successful preflight fixes what the subsequent native human
            # approves. A later technical interruption cannot require reapproval.
            print(f"LI319_APPROVAL_BINDING={digest}", file=sys.stderr)
            print(f"LI319_PROTECTED_SOURCE={value['source']}", file=sys.stderr)
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
    except (EVIDENCE.VerificationError, subprocess.SubprocessError, UnicodeError, OSError, json.JSONDecodeError, ValueError, yaml.YAMLError) as exc:
        print(f"ERROR: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
