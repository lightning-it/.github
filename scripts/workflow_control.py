"""Protected change control. Never imports or executes consumer candidate code.

Native Required Workflows bind the immutable source; all operations run inside
that consumer. Native run/job records reserve funded effects, independently of
candidate-authored checks or editable PR comments. Unknown outcomes fail closed.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import quote

if __name__ == "__main__":
    sys.modules.setdefault("workflow_control", sys.modules[__name__])

SOURCE = "lightning-it/.github"
WORKFLOW = ".github/workflows/change-control-required.yml"
RELEASE = ("lightning-it-release-automation[bot]", 307565056, "Bot")
SYNC = ("lightning-it-shared-assets-sync[bot]", 307342877, "Bot")
RENOVATE = ("renovate[bot]", 29139614, "Bot")
COPILOT = "copilot-pull-request-reviewer[bot]"
VERSION = "workflow-control/v1"
MAX_OPERATION_BYTES = 262144
MAX_PROOF_BYTES = 50 * 1024 * 1024


class ControlError(RuntimeError):
    """Missing, stale, unsuccessful or ambiguous native evidence."""


def require(condition, message):
    if not condition:
        raise ControlError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def sha(value):
    require(type(value) is str and re.fullmatch(r"[0-9a-f]{40}", value), "invalid-revision")
    return value


class API:
    """No mutation retry; errors never echo provider bodies or private paths."""
    def call(self, path, *, method="GET", data=None):
        require(not path.startswith(("/", "http")), "api-path")
        command = ["gh", "api", "--method", method, path]
        if re.fullmatch(r"repos/lightning-it/[A-Za-z0-9_.-]+/pulls/[1-9][0-9]*/reviews(?:\?.*)?", path):
            command += ["--header", "Accept: application/vnd.github-commitcomment.full+json"]
        if data is not None:
            command += ["--input", "-"]
        result = subprocess.run(command, input=canonical(data) if data is not None else None,
                                capture_output=True, timeout=60, check=False)
        require(result.returncode == 0, "native-api-unavailable")
        if method != "GET" and not result.stdout.strip():
            return {}
        try:
            return json.loads(result.stdout)
        except ValueError as error:
            raise ControlError("native-api-malformed") from error

    def pages(self, path, key=None):
        result = []
        separator = "&" if "?" in path else "?"
        for page in range(1, 101):
            payload = self.call(f"{path}{separator}per_page=100&page={page}")
            items = payload[key] if key else payload
            require(type(items) is list, "native-pagination-shape")
            result.extend(items)
            if len(items) < 100:
                if key and "total_count" in payload:
                    require(len(result) == payload["total_count"], "native-pagination-drift")
                return result
        raise ControlError("native-pagination-incomplete")

    def file(self, repo, path, revision):
        sha(revision)
        value = self.call(f"repos/{repo}/contents/{quote(path, safe='/')}?ref={revision}")
        require(value.get("type") == "file" and value.get("path") == path
                and value.get("encoding") == "base64", "protected-file-shape")
        data = base64.b64decode(value["content"].replace("\n", ""), validate=True)
        blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        require(blob == value["sha"], "protected-file-digest")
        return data

    def native_job_log(self, repo, job):
        require(re.fullmatch(r"lightning-it/[A-Za-z0-9_.-]+", repo)
                and type(job) is int and job > 0, "native-log-locator")
        with tempfile.TemporaryFile() as stream:
            result = subprocess.run(["gh", "api", "--allow-escape-sequences",
                                     f"repos/{repo}/actions/jobs/{job}/logs"],
                                    stdout=stream, stderr=subprocess.PIPE, timeout=60, check=False)
            require(result.returncode == 0, "native-log-unavailable")
            stream.seek(0)
            payload = stream.read(MAX_OPERATION_BYTES + 1)
        require(len(payload) <= MAX_OPERATION_BYTES, "native-log-size")
        return payload.decode("utf-8")


def source_identity(job, expected_path=WORKFLOW):
    require(job.get("workflow_repository") == SOURCE, "untrusted-source-repository")
    require(job.get("workflow_file_path") == expected_path, "untrusted-source-path")
    require(type(job.get("check_run_id")) is int and job["check_run_id"] > 0, "native-job-missing")
    return sha(job.get("workflow_sha"))


def identity(user):
    return user.get("login"), user.get("id"), user.get("type")


def binding(pull):
    return {"number": pull["number"], "base": sha(pull["base"]["sha"]),
            "head": sha(pull["head"]["sha"]), "base_ref": pull["base"]["ref"],
            "head_ref": pull["head"]["ref"], "head_repository": (pull["head"].get("repo") or {}).get("full_name"),
            "author": list(identity(pull["user"])), "title": pull["title"], "body": pull.get("body"),
            "labels": sorted(label["name"] for label in pull["labels"]), "draft": pull["draft"]}


def live_pull(api, repo, number, expected=None):
    value = api.call(f"repos/{repo}/pulls/{number}")
    require(value["number"] == number and value["state"] == "open" and not value["draft"], "pull-not-reviewable")
    require(value["base"]["repo"]["full_name"] == repo
            and value["base"]["ref"] in {"develop", "main"}, "unsupported-target")
    if expected is not None:
        require(binding(value) == expected, "stale-not-applicable")
    return value


def classify(pull, repo):
    author = identity(pull["user"])
    same = (pull["head"].get("repo") or {}).get("full_name") == repo
    head, base = pull["head"]["ref"], pull["base"]["ref"]
    if author == RELEASE and same and head == "develop" and base == "main":
        return "promotion"
    require(base != "main", "main-requires-exact-protected-promotion")
    if (same and base == "develop" and head.startswith("backmerge/") and head.endswith("-main")
            and (author == RELEASE or repo == SOURCE and author == SYNC)):
        return "ancestry"
    if author == RELEASE:
        require(same, "release-app-fork-forbidden")
        return "codex"
    if author == RENOVATE:
        labels = {label["name"] for label in pull["labels"]}
        if (same and base == "develop" and head.startswith("renovate/")
                and {"renovate", "dependencies", "safe-automerge"} <= labels and "breaking-update" not in labels):
            return "renovate"
        return "copilot"
    if author == SYNC:
        require(same and base == "develop", "distribution-shape")
        return "distribution"
    require(pull["user"].get("type") == "User", "unclassified-automation")
    return "copilot"


def policy(api, repo, base, source_sha):
    value = json.loads(api.file(repo, ".lit/workflow-control.json", base))
    require(value.get("version") == 1 and value.get("repository") == repo, "protected-policy-shape")
    require(value.get("mode") in {"reference", "enforce"}, "scope-not-admitted")
    require(type(value.get("quality")) is list and value["quality"], "quality-policy-missing")
    for item in value["quality"]:
        require(set(item) == {"workflow", "job"} and item["workflow"].startswith(".github/workflows/"), "quality-policy-entry")
    lineage = json.loads((Path(__file__).resolve().parents[1] / ".lit/workflow-source-lineage.json").read_text())
    require(lineage.get("version") == 1 and type(lineage.get("accepted_predecessors")) is list, "central-lineage-shape")
    allowed = {sha(source_sha), *(sha(item) for item in lineage["accepted_predecessors"])}
    requested = value.get("accepted_sources", [])
    require(type(requested) is list and set(requested) <= allowed, "consumer-cannot-admit-central-source")
    # The externally selected native defining source owns its proof lineage.
    # Keep consumer configuration compatible with the previous immutable reader
    # throughout cutover; it cannot add sources or select candidate authority.
    value["accepted_sources"] = sorted(allowed)
    return value


def native_required(run, repo):
    workflow = run.get("workflow_id")
    return (type(workflow) is int and workflow > 0
            and run.get("workflow_url") == f"https://api.github.com/repos/{repo}/actions/required_workflows/{workflow}"
            and run.get("path", "").split("@", 1)[0] in {WORKFLOW, f"{SOURCE}/{WORKFLOW}"})


def artifact_record(api, repo, run, name, filename):
    from workflow_proofs import read_native_json
    artifacts = api.pages(f"repos/{repo}/actions/runs/{run['id']}/artifacts", "artifacts")
    matches = [a for a in artifacts if a["name"] == name and not a["expired"]]
    require(len(matches) == 1, "protected-native-artifact-missing-or-ambiguous")
    with tempfile.TemporaryDirectory(prefix="native-control-proof-") as temp:
        result = subprocess.run(["gh", "run", "download", str(run["id"]), "--repo", repo,
                                 "--name", name, "--dir", temp], capture_output=True, timeout=60, check=False)
        require(result.returncode == 0, "protected-native-artifact-unavailable")
        file = Path(temp) / filename
        maximum = MAX_OPERATION_BYTES if filename == "control-operation.json" else MAX_PROOF_BYTES
        return read_native_json(file, maximum)


def same_immutable_tuple(left, right):
    keys = {"number", "base", "head", "base_ref", "head_ref", "head_repository", "author"}
    return all(canonical(left.get(key)) == canonical(right.get(key)) for key in keys)


def normal_environment(api, repo):
    env = api.call(f"repos/{repo}/environments/normal-release-promotion-approval")
    require(env.get("name") == "normal-release-promotion-approval" and env.get("can_admins_bypass") is False,
            "normal-environment-bypass-or-missing")
    rules = [r for r in env.get("protection_rules", []) if r.get("type") == "required_reviewers"]
    require(len(rules) == 1 and rules[0].get("prevent_self_review") is False
            and rules[0].get("reviewers"), "one-person-native-approval-not-configured")
    # GitHub requires ONE member of this reviewer set, not one per listed team.
    require(all(r.get("type") in {"User", "Team", "BusinessTeam"} for r in rules[0]["reviewers"]),
            "native-approver-shape")
    return env


def native_approval(api, repo, run_id):
    history = api.call(f"repos/{repo}/actions/runs/{run_id}/approvals")
    require(type(history) is list, "native-approval-history-shape")
    matches = [entry for entry in history if entry.get("state") == "approved"
               and entry.get("user", {}).get("type") == "User"
               and any(e.get("name") == "normal-release-promotion-approval" for e in entry.get("environments", []))]
    require(len(matches) == 1, "one-native-human-approval-required")
    return matches[0]


def previous_approval(api, repo, pull, source):
    runs = api.pages(f"repos/{repo}/actions/runs?head_sha={pull['head']['sha']}", "workflow_runs")
    expected = binding(pull)
    for run in sorted(runs, key=lambda r: r["id"], reverse=True):
        if not native_required(run, repo):
            continue
        if not any(pr.get("number") == pull["number"] and pr.get("base", {}).get("sha") == expected["base"]
                   and pr.get("head", {}).get("sha") == expected["head"] for pr in run.get("pull_requests", [])):
            continue
        artifacts = api.pages(f"repos/{repo}/actions/runs/{run['id']}/artifacts", "artifacts")
        if not any(re.fullmatch(r"control-operation-[1-9][0-9]*", a["name"]) and not a["expired"] for a in artifacts):
            continue
        record = operation_record(api, repo, run)
        if record.get("source_sha") != source or not same_immutable_tuple(record.get("binding", {}), expected):
            continue
        history = api.call(f"repos/{repo}/actions/runs/{run['id']}/approvals")
        if any(a.get("state") == "approved" and any(e.get("name") == "normal-release-promotion-approval"
               for e in a.get("environments", [])) for a in history):
            native_approval(api, repo, run["id"])
            return run["id"]
    return None


def native_jobs(api, repo, run):
    items = api.pages(f"repos/{repo}/actions/runs/{run['id']}/attempts/{run['run_attempt']}/jobs", "jobs")
    require(all(item.get("run_id") == run["id"] for item in items), "job-run-drift")
    return items


def check_quality(api, repo, pull, config):
    checks = api.pages(f"repos/{repo}/commits/{pull['head']['sha']}/check-runs?filter=latest", "check_runs")
    proof = []
    for required in config["quality"]:
        candidates = []
        for check in checks:
            if check.get("name") != required["job"] or check.get("app", {}).get("id") != 15368:
                continue
            match = re.fullmatch(rf"https://github.com/{re.escape(repo)}/actions/runs/([1-9][0-9]*)/job/([1-9][0-9]*)", check.get("details_url", ""))
            require(match is not None, "quality-job-origin")
            run = api.call(f"repos/{repo}/actions/runs/{match[1]}")
            if run["path"] != required["workflow"] or run["head_sha"] != pull["head"]["sha"]:
                continue
            # Default PR checkout tests the integration represented by this native
            # association. Never accept a B1/H run for B2/H, or a head-only push
            # as proof of an untested PR integration.
            associated = [pr for pr in run.get("pull_requests", []) if pr.get("number") == pull["number"]
                          and pr.get("base", {}).get("sha") == pull["base"]["sha"]
                          and pr.get("head", {}).get("sha") == pull["head"]["sha"]]
            if run.get("event") == "pull_request" and len(associated) == 1:
                candidates.append((run, check, int(match[2])))
        require(candidates, "quality-check-missing-or-ambiguous")
        # Newer pending/failed evidence cannot be hidden behind an older success.
        run, check, job_id = max(candidates, key=lambda item: (item[0]["id"], item[0]["run_attempt"], item[1]["id"]))
        require(check.get("status") == "completed", "quality-pending")
        require(check.get("conclusion") == "success", "quality-not-successful")
        require(any(job["id"] == job_id and job.get("check_run_url", "").endswith(f"/{check['id']}")
                    and job["conclusion"] == "success" for job in native_jobs(api, repo, run)), "quality-native-job")
        proof.append({"check": check["id"], "run": run["id"], "attempt": run["run_attempt"],
                      "base": pull["base"]["sha"], "head": pull["head"]["sha"]})
    return proof


def validate_signal(api, repo, pull):
    path = ".github/workflows/review-events.yml"
    trusted = (Path(__file__).resolve().parents[1] / path).read_bytes()
    require(api.file(repo, path, pull["head"]["sha"]) == trusted, "candidate-review-signal-missing-or-modified")


def native_conversation_guard(api, repo, pull):
    # This live GitHub merge condition handles resolve/unresolve atomically;
    # no comment-event or a cached successful Actions job can substitute for it.
    rules = api.call(f"repos/{repo}/rules/branches/{quote(pull['base']['ref'], safe='')}")
    require(type(rules) is list and all(type(r) is dict for r in rules), "native-rule-shape")
    pulls = [r for r in rules if r.get("type") == "pull_request"]
    require(all(r.get("parameters", {}).get("required_approving_review_count") == 0
                and r.get("parameters", {}).get("require_code_owner_review") is False
                and r.get("parameters", {}).get("require_last_push_approval") is False for r in pulls),
            "native-extra-human-review-policy")
    guards = [r for r in pulls if r.get("type") == "pull_request"
              and (r.get("ruleset_source_type"), r.get("ruleset_source"))
                  in {("Organization", "lightning-it"), ("Repository", repo)}
              and r.get("parameters", {}).get("required_review_thread_resolution") is True
              and r.get("parameters", {}).get("required_approving_review_count") == 0
              and r.get("parameters", {}).get("require_code_owner_review") is False
              and r.get("parameters", {}).get("require_last_push_approval") is False]
    require(guards, "native-one-person-conversation-guard-missing")
    return sorted({r["ruleset_id"] for r in guards})


def associated_delivery(run, pull):
    require(type(run.get("pull_requests")) is list and run["pull_requests"], "native-copilot-pr-association-unavailable")
    matches = [p for p in run["pull_requests"] if p.get("number") == pull["number"]]
    require(len(matches) <= 1, "native-copilot-pr-association-ambiguous")
    if not matches:
        return False
    return (matches[0].get("head", {}).get("sha") == pull["head"]["sha"]
            and matches[0].get("base", {}).get("sha") == pull["base"]["sha"])


def copilot_review(api, repo, pull):
    import copilot_native_content as content
    reviews = api.pages(f"repos/{repo}/pulls/{pull['number']}/reviews")
    current = [r for r in reviews if r.get("commit_id") == pull["head"]["sha"]
               and r.get("user", {}).get("id") == 175728472
               and r.get("user", {}).get("type") == "Bot"
               and r.get("user", {}).get("login") in {COPILOT, COPILOT.removesuffix("[bot]"), "Copilot"}]
    if not current:
        return None
    require(not any(r.get("state") == "DISMISSED" for r in current), "copilot-review-not-accepted")
    runs = api.pages(f"repos/{repo}/actions/runs?head_sha={pull['head']['sha']}", "workflow_runs")
    deliveries = [r for r in runs if r.get("path") == "dynamic/agents/copilot-pull-request-reviewer"
                  and associated_delivery(r, pull)]
    eligible = []
    for review in current:
        # Native publication is asynchronous: observed run 38705673721 ended
        # four seconds BEFORE review 5530268361 was submitted. The native App,
        # current commit, unique successful same-PR service run and complete
        # frame provide authority; run.updated_at is not a publication deadline.
        producers = [r for r in deliveries if r.get("status") == "completed" and r.get("conclusion") == "success"
                     and r.get("event") == "dynamic" and r.get("head_sha") == pull["head"]["sha"]
                     and r.get("run_started_at", "~") <= review.get("submitted_at", "")]
        if len(producers) == 1:
            eligible.append((review, producers[0]))
    if not eligible:
        return None
    require(len(eligible) == 1, "copilot-review-ambiguous")
    review, producer = eligible[0]
    require(review["state"] in {"COMMENTED", "APPROVED"}, "copilot-review-not-accepted")
    # Preserve the admitted native frame protocol, including rendered-body and
    # body-only finding checks. A native v2 frame does not assert a file count.
    # Never fabricate that metric or accept an unknown/partial text response.
    filtered = [r for r in reviews if r["commit_id"] != pull["head"]["sha"] or r["id"] == review["id"]]
    try:
        content.validate_reported_file_coverage(review.get("body") or "", pull.get("changed_files"))
        frame = content.bind_copilot_review_findings([filtered], repository=repo,
                    pull_number=pull["number"], head_sha=pull["head"]["sha"])
    except content.EvidenceError as error:
        raise ControlError("copilot-native-frame-not-accepted") from error
    comments = api.pages(f"repos/{repo}/pulls/{pull['number']}/reviews/{review['id']}/comments")
    targets = frame["finding_comment_ids"]
    if targets is None:
        require(len(comments) == frame["historical_findings_count"], "copilot-native-finding-coverage")
        targets = [c["id"] for c in comments]
    needed = set(targets) | {c["id"] for c in comments}
    all_comments = api.pages(f"repos/{repo}/pulls/{pull['number']}/comments") if needed else []
    native_reviews = {r["id"]: r for r in filtered if r.get("node_id") in frame["native_reviews"]}
    linked = {c["id"]: c for c in all_comments}
    require(len(linked) == len(all_comments), "copilot-native-comment-duplicate")
    for identifier in needed:
        require(identifier in linked, "copilot-native-finding-coverage")
        comment = linked[identifier]
        owner = native_reviews.get(comment["pull_request_review_id"])
        require(owner is not None and owner["submitted_at"] <= review["submitted_at"]
                and comment.get("user", {}).get("id") == 175728472
                and comment.get("user", {}).get("type") == "Bot"
                and not comment.get("in_reply_to_id")
                and comment.get("original_commit_id") == owner.get("commit_id")
                and type(comment.get("body")) is str and bool(comment["body"].strip()), "copilot-native-finding-origin")
        require(not any(marker in content.normalized_review_text(comment.get("body") or "")
                        for marker in content.COPILOT_REVIEW_FAILURE_MARKERS), "copilot-provider-failure")
    return {"id": review["id"], "head": review["commit_id"], "state": review["state"],
            "service_run": producer["id"], "frame": {k: v for k, v in frame.items() if k != "native_reviews"},
            "finding_comment_ids": sorted(needed)}


def copilot_delivery_pending(api, repo, pull):
    requested = api.call(f"repos/{repo}/pulls/{pull['number']}/requested_reviewers")
    if any(user.get("id") == 175728472 for user in requested["users"]):
        return True
    runs = api.pages(f"repos/{repo}/actions/runs?head_sha={pull['head']['sha']}", "workflow_runs")
    deliveries = [run for run in runs if run.get("path") == "dynamic/agents/copilot-pull-request-reviewer"
                  and associated_delivery(run, pull)]
    require(not any(run.get("status") == "completed" and run.get("conclusion") != "success" for run in deliveries),
            "native-copilot-delivery-failed-no-automatic-retry")
    return bool(deliveries)


FUNDING_STEPS = {"Request current Copilot review", "Reserve protected Codex request"}


def request_slot_started(api, repo, run, *, attempt=None):
    version = run["run_attempt"] if attempt is None else attempt
    jobs = api.pages(f"repos/{repo}/actions/runs/{run['id']}/attempts/{version}/jobs", "jobs")
    review = [job for job in jobs if job["name"] == "Protected current revision"]
    # A verifier-only attempt does not create a new provider reservation.
    if not review:
        return None
    require(len(review) == 1 and review[0].get("run_id") == run["id"], "request-job-provenance")
    steps = [step for step in review[0].get("steps", []) if step["name"] in FUNDING_STEPS]
    require(steps and len({s["name"] for s in steps}) == len(steps), "request-boundary-history-unavailable")
    return any(step.get("conclusion") != "skipped" and step.get("status") != "queued" for step in steps)


def slot_consumed_before(api, repo, run, attempt):
    for previous in range(1, attempt):
        require(request_slot_started(api, repo, run, attempt=previous) is not True, "funded-effect-rerun-forbidden")


def reserve_request(api, repo, pull, source_sha, run_id, attempt):
    run = api.call(f"repos/{repo}/actions/runs/{run_id}")
    require(run.get("id") == run_id and native_required(run, repo)
            and run["head_sha"] == pull["head"]["sha"], "request-origin")
    require(run["run_attempt"] == attempt, "request-attempt-drift")
    slot_consumed_before(api, repo, run, attempt)
    runs = api.pages(f"repos/{repo}/actions/runs?head_sha={pull['head']['sha']}", "workflow_runs")
    owners = [r for r in runs if native_required(r, repo) and r["workflow_id"] == run["workflow_id"]
              and any(pr.get("number") == pull["number"]
                      and pr.get("base", {}).get("sha") == pull["base"]["sha"]
                      and pr.get("head", {}).get("sha") == pull["head"]["sha"]
                      for pr in r.get("pull_requests", []))]
    require(any(owner["id"] == run_id for owner in owners), "request-native-association-missing")
    require(run_id == max(owner["id"] for owner in owners), "funding-current-native-generation-required")
    for owner in owners:
        if owner["id"] == run_id:
            continue
        for version in range(1, owner["run_attempt"] + 1):
            require(request_slot_started(api, repo, owner, attempt=version) is not True, "request-slot-already-consumed")
    # The current native funding step is the reservation BEFORE the POST/model.
    # A known skipped earlier step is not a claim; unknown history blocks.
    return run_id


def operation_record(api, repo, run, source=None):
    artifacts = api.pages(f"repos/{repo}/actions/runs/{run['id']}/artifacts", "artifacts")
    candidates = []
    for artifact in artifacts:
        match = re.fullmatch(r"control-operation-([1-9][0-9]*)", artifact["name"])
        if match and not artifact["expired"] and int(match[1]) <= run["run_attempt"]:
            candidates.append((int(match[1]), artifact["name"]))
    require(candidates, "protected-operation-missing")
    _, name = max(candidates)
    record = artifact_record(api, repo, run, name, "control-operation.json")
    require(record.get("version") == 1 and (source is None or record.get("source_sha") == source), "protected-operation-source-drift")
    sha(record.get("source_sha"))
    return record


def check_renovate(api, repo, pull):
    events = api.pages(f"repos/{repo}/issues/{pull['number']}/events")
    policy_events = [e for e in events if e.get("event") in {"labeled", "unlabeled"}
                     and e.get("label", {}).get("name") in {"safe-automerge", "breaking-update"}]
    safe = [e for e in policy_events if e["label"]["name"] == "safe-automerge"]
    require(safe and safe[-1]["event"] == "labeled" and all(identity(e.get("actor", {})) == RENOVATE for e in safe)
            and not any(e["label"]["name"] == "breaking-update" and e["event"] == "labeled" for e in policy_events), "renovate-policy-provenance")
    commits = api.pages(f"repos/{repo}/pulls/{pull['number']}/commits")
    require(commits and commits[-1].get("sha") == pull["head"]["sha"], "renovate-current-head-provenance")
    for commit in commits:
        require(identity(commit.get("author") or {}) == RENOVATE
                and identity(commit.get("committer") or {}) == ("web-flow", 19864447, "User")
                and commit.get("commit", {}).get("verification", {}).get("verified") is True,
                "renovate-commit-provenance")
    return {"kind": "policy-bound-renovate", "label_events": [e["id"] for e in policy_events]}


def ingress_candidates(api, repo, pull, sources, runs, bindings, *, read_operations=True):
    """Use the same PR binding for initial selection and final generation read."""
    candidates = []
    for run in runs:
        if not native_required(run, repo) or run.get("head_sha") != pull["head"]["sha"]:
            continue
        associations = [p for p in run.get("pull_requests", []) if p.get("number") == pull["number"]]
        key = (run["id"], run["run_attempt"])
        if associations:
            require(len(associations) == 1, "ingress-association-ambiguous")
            associated = associations[0]
            if associated.get("base", {}).get("sha") != pull["base"]["sha"] or associated.get("head", {}).get("sha") != pull["head"]["sha"]:
                bindings[key] = False
                continue
            bindings[key] = True
        elif run.get("pull_requests"):
            bindings[key] = False
            continue
        elif pull.get("merged") is True and pull.get("merge_commit_sha"):
            if key not in bindings:
                require(read_operations, "ingress-generation-binding-unavailable")
                operation = operation_record(api, repo, run)
                bindings[key] = (operation["source_sha"] in sources
                                 and same_immutable_tuple(operation["binding"], binding(pull)))
            if not bindings[key]:
                continue
        else:
            continue
        candidates.append(run)
    return candidates


def check_native_control(api, repo, pull, config):
    """Authenticate the entire native required run, not a caller-authored name."""
    sources = config.get("accepted_sources", [])
    require(type(sources) is list and sources, "accepted-source-lineage-missing")
    for value in sources:
        sha(value)
    runs = api.pages(f"repos/{repo}/actions/runs?head_sha={pull['head']['sha']}", "workflow_runs")
    bindings = {}
    candidates = ingress_candidates(api, repo, pull, sources, runs, bindings)
    require(candidates, "ingress-protected-run-missing")
    selected = max(candidates, key=lambda run: (run["id"], run["run_attempt"]))
    observed = selected
    after_merge = []
    if selected["status"] != "completed" or selected["conclusion"] != "success":
        from workflow_ingress import merged_attempt
        selected, after_merge = merged_attempt(api, repo, pull, selected)
    jobs = native_jobs(api, repo, selected)
    gate = [j for j in jobs if j["name"] == "Current revision review"]
    require(len(gate) == 1 and gate[0]["conclusion"] == "success", "ingress-protected-job-missing")
    record = artifact_record(api, repo, selected, f"control-proof-{selected['run_attempt']}", "control-proof.json")
    require(record.get("version") == 1 and record.get("source_sha") in sources
            and record.get("binding") == binding(pull)
            and record.get("route") in {"copilot", "renovate", "ancestry", "distribution", "codex"},
            "ingress-protected-proof-binding")
    result = {"run": selected["id"], "attempt": selected["run_attempt"], "job": gate[0]["id"],
            "head": pull["head"]["sha"], "source_sha": record["source_sha"],
            "route": record.get("route"), "artifact": f"control-proof-{selected['run_attempt']}",
            "proof_sha256": digest(record)}
    # Every saved object above is a snapshot. Re-read all mutable decision
    # subjects after the evidence reads, for ordinary and historical passes.
    # Authenticate newly discovered persisted bindings BEFORE the final native
    # generation snapshot. Its selector performs no artifact/network reads.
    warm_runs = api.pages(f"repos/{repo}/actions/runs?head_sha={pull['head']['sha']}", "workflow_runs")
    ingress_candidates(api, repo, pull, sources, warm_runs, bindings)
    latest_runs = api.pages(f"repos/{repo}/actions/runs?head_sha={pull['head']['sha']}", "workflow_runs")
    generations = ingress_candidates(api, repo, pull, sources, latest_runs, bindings, read_operations=False)
    latest_generation = max(generations, key=lambda item: (item["id"], item["run_attempt"])) if generations else None
    fields = ("id", "run_attempt", "status", "conclusion", "head_sha",
              "workflow_id", "workflow_url", "path")
    require(latest_generation is not None
            and all(latest_generation.get(key) == observed.get(key) for key in fields),
            "ingress-native-generation-changed")
    if pull.get("merged") is True:
        current_pull = api.call(f"repos/{repo}/pulls/{pull['number']}")
        require(binding(current_pull) == binding(pull)
                and all(current_pull.get(key) == pull.get(key)
                        for key in ("state", "merged", "merged_at", "merge_commit_sha")),
                "ingress-referenced-pull-changed")
    current = api.call(f"repos/{repo}/actions/runs/{observed['id']}")
    require(native_required(current, repo)
            and all(current.get(key) == observed.get(key) for key in fields),
            "ingress-current-run-changed")
    if after_merge:
        result["post_merge_failed_attempts"] = after_merge
    return result


def promotion_ingress(api, repo, pull, config):
    # Full first-parent graph avoids GitHub compare's display truncation and
    # duplicate PR attribution of feature commits. Every integration has one PR.
    import tempfile

    from workflow_proofs import References
    from workflow_subject import fetch_objects, git
    base, head = pull["base"]["sha"], pull["head"]["sha"]
    with tempfile.TemporaryDirectory(prefix="promotion-objects-", dir=os.environ.get("RUNNER_TEMP")) as temp:
        objects = Path(temp) / "objects.git"
        result = subprocess.run(["git", "init", "--bare", str(objects)], capture_output=True, timeout=30, check=False)
        require(result.returncode == 0, "promotion-git-init")
        fetch_objects(objects, repo, f"{base}:refs/review/base", f"{head}:refs/review/head")
        ancestor = git(objects, "merge-base", "--all", base, head)
        require(ancestor == base, "promotion-needs-main-ancestry")
        commits = git(objects, "rev-list", "--reverse", "--first-parent", f"{base}..{head}").splitlines()
        require(commits and len(commits) <= 10000, "promotion-ingress-empty-or-unbounded")
        proof = References(MAX_PROOF_BYTES)
        for commit in commits:
            pulls = api.pages(f"repos/{repo}/commits/{commit}/pulls")
            matches = [p for p in pulls if p.get("merged_at") and p.get("merge_commit_sha") == commit
                       and p.get("base", {}).get("ref") == "develop"]
            require(len(matches) == 1, "promotion-unattributed-ingress")
            ingress = api.call(f"repos/{repo}/pulls/{matches[0]['number']}")
            require(ingress["merged_at"] and ingress["merge_commit_sha"] == commit, "ingress-association-drift")
            # Verify one native proof under fresh process/cgroup admission,
            # discard its full decoded content and retain only its digest/ref.
            proof.append({"pull": ingress["number"], "merge": commit,
                          "control": check_native_control(api, repo, ingress, config)})
        tree = sha(git(objects, "merge-tree", "--write-tree", base, head))
        payload = git(objects, "diff", "--binary", "--full-index", "--no-ext-diff", "--no-textconv",
                      f"{base}^{{tree}}", tree, binary=True)
    require(payload and any(item["control"]["route"] != "ancestry" for item in proof.items), "promotion-no-reviewed-change")
    return {"base": base, "head": head, "integration_tree": tree,
            "diff_sha256": hashlib.sha256(payload).hexdigest(), "ingress": proof.items}


def ancestry_evidence(api, repo, pull, config):
    import tempfile

    from workflow_subject import fetch_objects, git
    base, head = pull["base"]["sha"], pull["head"]["sha"]
    current_main = sha(api.call(f"repos/{repo}/git/ref/heads/main")["object"]["sha"])
    component = repo.split("/", 1)[1].lstrip(".")
    require(pull["head"]["ref"] == f"backmerge/{component}-{current_main[:12]}-{base[:12]}-main"
            and pull["title"] == f"chore(governance): record main ancestry before {current_main[:12]}", "ancestry-exact-operation")
    with tempfile.TemporaryDirectory(prefix="ancestry-objects-", dir=os.environ.get("RUNNER_TEMP")) as temp:
        objects = Path(temp) / "objects.git"
        result = subprocess.run(["git", "init", "--bare", str(objects)], capture_output=True, timeout=30, check=False)
        require(result.returncode == 0, "ancestry-git-init")
        fetch_objects(objects, repo, base, head, current_main)
        require(git(objects, "show", "-s", "--format=%P", head).split() == [base, current_main], "ancestry-parent-shape")
        require(git(objects, "rev-parse", f"{head}^{{tree}}") == git(objects, "rev-parse", f"{base}^{{tree}}"), "ancestry-content-change")
    return {"main": current_main, "head": head, "unchanged_tree": True}


def distribution_evidence(api, repo, pull, config):
    # New distributor receipts are candidate data until the independently
    # accepted private source run and exact rendered file manifest agree.
    marker = "<!-- lit-distribution/v1 "
    body = pull.get("body") or ""
    require(body.count(marker) == 1, "distribution-receipt-missing")
    encoded = body.split(marker, 1)[1].split(" -->", 1)[0]
    receipt = json.loads(encoded)
    require(set(receipt) == {"source", "source_sha", "run", "files"}, "distribution-receipt-shape")
    allowed = config.get("distribution_sources", [])
    require(receipt["source"] == "lightning-it/shared-assets-lit" and receipt["source_sha"] in allowed, "distribution-source-not-accepted")
    run = api.call(f"repos/{receipt['source']}/actions/runs/{receipt['run']}")
    require(run["head_sha"] == receipt["source_sha"] and run["head_branch"] == "main"
            and run["status"] == "completed" and run["conclusion"] == "success"
            and run["path"] == ".github/workflows/sync-repository-quality-repos.yml", "distribution-native-source")
    files = api.pages(f"repos/{repo}/pulls/{pull['number']}/files")
    manifest = receipt["files"]
    require(type(pull.get("changed_files")) is int and len(files) == pull["changed_files"], "distribution-native-file-list-incomplete")
    require(type(manifest) is list and len(manifest) == len(files), "distribution-full-coverage")
    actual = []
    for file in files:
        require(file["status"] in {"added", "modified"} and not file.get("previous_filename"), "distribution-change-kind")
        content = api.file(repo, file["filename"], pull["head"]["sha"])
        actual.append({"path": file["filename"], "sha256": hashlib.sha256(content).hexdigest()})
    require(sorted(actual, key=lambda f: f["path"]) == sorted(manifest, key=lambda f: f["path"]), "distribution-manifest-drift")
    # Verify the actual source-run-produced manifest artifact, not a PR assertion.
    artifacts = api.pages(f"repos/{receipt['source']}/actions/runs/{run['id']}/artifacts", "artifacts")
    expected_name = "distribution-" + repo.split("/", 1)[1]
    artifacts = [a for a in artifacts if a["name"] == expected_name and not a["expired"]]
    require(len(artifacts) == 1, "distribution-source-manifest-missing")
    import tempfile
    with tempfile.TemporaryDirectory(prefix="distribution-manifest-") as temp:
        result = subprocess.run(["gh", "run", "download", str(run["id"]), "--repo", receipt["source"],
                                 "--name", expected_name, "--dir", temp], capture_output=True, timeout=60, check=False)
        require(result.returncode == 0, "distribution-manifest-unavailable")
        records = list(Path(temp).glob("*.json"))
        require(len(records) == 1 and json.loads(records[0].read_text()) == receipt, "distribution-source-manifest-drift")
    return {"source_run": run["id"], "source_sha": receipt["source_sha"], "manifest_sha256": digest(manifest)}


def verify_existing_route(api, repo, pull, config, route):
    if route == "copilot":
        result = copilot_review(api, repo, pull)
        require(result is not None, "current-copilot-review-missing")
        return result
    if route == "renovate":
        return check_renovate(api, repo, pull)
    if route == "promotion":
        return promotion_ingress(api, repo, pull, config)
    if route == "ancestry":
        return ancestry_evidence(api, repo, pull, config)
    if route == "distribution":
        return distribution_evidence(api, repo, pull, config)
    if route == "codex":
        import workflow_codex
        from workflow_subject import materialize
        source = source_identity(json.loads(os.environ["NATIVE_JOB"]))
        native = api.call(f"repos/{repo}/actions/runs/{os.environ['GITHUB_RUN_ID']}")
        with tempfile.TemporaryDirectory(prefix="codex-final-input-") as temp:
            metadata = materialize(api, repo, pull, source, Path(temp) / "subject")
            return workflow_codex.current_evidence(api, repo, pull, metadata, source, native)
    raise ControlError("unclassified-review-route")


def output(name, value):
    require(re.fullmatch(r"[a-z_]+", name) and "\n" not in str(value), "output-shape")
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as file:
        file.write(f"{name}={value}\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("classify", "review", "finalize", "request-copilot", "prepare-codex", "reserve-codex", "verify-codex"))
    args = parser.parse_args()
    api = API()
    repo = os.environ["GITHUB_REPOSITORY"]
    require(re.fullmatch(r"lightning-it/[A-Za-z0-9_.-]+", repo), "consumer-repository")
    source_sha = source_identity(json.loads(os.environ["NATIVE_JOB"]))
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    native = api.call(f"repos/{repo}/actions/runs/{os.environ['GITHUB_RUN_ID']}")
    require(native_required(native, repo), "only-native-ruleset-workflow-may-authorize")
    number = event.get("pull_request", {}).get("number")
    require(type(number) is int and number > 0, "pull-event-required")
    pull = live_pull(api, repo, number)
    expected = binding(pull)
    if args.operation != "classify":
        if args.operation == "finalize":
            expected = operation_record(api, repo, native, source_sha)["binding"]
        else:
            record = json.loads(Path("control-operation.json").read_bytes())
            require(record.get("version") == 1 and record.get("source_sha") == source_sha, "operation-source-drift")
            expected = record["binding"]
        live_pull(api, repo, number, expected)
    require(pull["head"]["sha"] == event["pull_request"]["head"]["sha"]
            and pull["base"]["sha"] == event["pull_request"]["base"]["sha"], "stale-event")
    config = policy(api, repo, pull["base"]["sha"], source_sha)
    route = classify(pull, repo)
    snapshot = canonical({"version": 1, "source_sha": source_sha, "binding": expected})
    require(len(snapshot) <= MAX_OPERATION_BYTES, "operation-snapshot-size-before-funding")
    if args.operation == "classify":
        if route == "promotion":
            normal_environment(api, repo)
            prior = previous_approval(api, repo, pull, source_sha)
            output("approval_needed", "false" if prior else "true")
        else:
            output("approval_needed", "false")
        request_needed = False
        if route == "copilot" and identity(pull["user"]) == ("litroc", 76040632, "User") and copilot_review(api, repo, pull) is None:
            request_needed = not copilot_delivery_pending(api, repo, pull)
            if request_needed:
                import workflow_funding
                require(workflow_funding.finalized(api, repo, pull, native, event), "head-not-finalized-for-funded-review")
        output("request_needed", "true" if request_needed else "false")
        Path("control-operation.json").write_bytes(snapshot)
        output("route", route)
        output("base", pull["base"]["sha"])
        output("head", pull["head"]["sha"])
        return
    if args.operation == "request-copilot":
        require(route == "copilot" and identity(pull["user"]) == ("litroc", 76040632, "User"), "funded-author-not-allowed")
        require(copilot_review(api, repo, pull) is None, "current-head-already-reviewed")
        if copilot_delivery_pending(api, repo, pull):
            return
        import workflow_funding
        require(workflow_funding.finalized(api, repo, pull, native, event), "head-not-finalized-for-funded-review")
        reserve_request(api, repo, pull, source_sha, int(os.environ["GITHUB_RUN_ID"]), int(os.environ["GITHUB_RUN_ATTEMPT"]))
        live_pull(api, repo, number, expected)
        api.call(f"repos/{repo}/pulls/{number}/requested_reviewers", method="POST", data={"reviewers": [COPILOT]})
        return
    if args.operation == "prepare-codex":
        require(route == "codex", "codex-identity-required")
        import workflow_codex
        import workflow_funding
        from workflow_proofs import read_native_json
        directory = Path("exact-revision-review")
        metadata = read_native_json(directory / "review-metadata.json", 1_000_000)
        replay = workflow_codex.prepare(api, repo, pull, metadata, source_sha, directory)
        if not replay:
            require(workflow_funding.finalized(api, repo, pull, native, event), "head-not-finalized-for-funded-review")
        output("replay", "true" if replay else "false")
        return
    if args.operation == "reserve-codex":
        require(route == "codex", "codex-identity-required")
        import workflow_funding
        require(workflow_funding.finalized(api, repo, pull, native, event), "head-not-finalized-for-funded-review")
        reserve_request(api, repo, pull, source_sha, int(os.environ["GITHUB_RUN_ID"]), int(os.environ["GITHUB_RUN_ATTEMPT"]))
        live_pull(api, repo, number, expected)
        return
    if args.operation == "verify-codex":
        require(route == "codex", "codex-identity-required")
        import workflow_codex
        from workflow_proofs import read_native_json
        directory = Path("exact-revision-review")
        metadata = read_native_json(directory / "review-metadata.json", 1_000_000)
        require(metadata.get("base_sha") == expected["base"] and metadata.get("head_sha") == expected["head"]
                and metadata.get("repository") == repo and metadata.get("pull_request") == number,
                "codex-current-subject-binding")
        record = read_native_json(directory / "provider-native.json", MAX_PROOF_BYTES)
        path = directory / "provider-response.bin"
        import bounded_review_transport as transport
        require(path.is_file() and not path.is_symlink() and 0 < path.stat().st_size <= transport.MAX_RESPONSE_BYTES,
                "codex-current-wire-bound")
        workflow_codex.validate_record(record, path.read_bytes(), metadata, source_sha)
        live_pull(api, repo, number, expected)
        print("Protected actual model response and complete native request receipt verified.")
        return
    if args.operation == "review":
        require(route != "codex", "codex-job-required")
        review = None
        if route == "copilot":
            review = copilot_review(api, repo, pull)
            for _ in range(80):
                live_pull(api, repo, number, expected)
                review = copilot_review(api, repo, pull)
                if review:
                    break
                time.sleep(15)
            require(review is not None, "current-copilot-review-missing")
        elif route == "renovate":
            review = check_renovate(api, repo, pull)
        elif route == "promotion":
            review = promotion_ingress(api, repo, pull, config)
        elif route == "ancestry":
            review = ancestry_evidence(api, repo, pull, config)
        elif route == "distribution":
            review = distribution_evidence(api, repo, pull, config)
        else:
            raise ControlError("unclassified-review-route")
        require(len(canonical(review)) <= MAX_PROOF_BYTES, "native-proof-resource-bound")
        live_pull(api, repo, number, expected)
        # Native job is the authoritative result; no synthetic successful check.
        print(f"Verified {route} for exact current revision; native evidence retained.")
        return
    authorization = None
    if route == "codex":
        require(os.environ.get("REVIEW_RESULT") in {"success", "skipped"}, "codex-review-job-not-successful")
    if route == "promotion":
        normal_environment(api, repo)
        if os.environ.get("APPROVAL_RESULT") == "success":
            approval_run = int(os.environ["GITHUB_RUN_ID"])
        else:
            approval_run = previous_approval(api, repo, pull, source_sha)
            require(approval_run is not None, "native-human-approval-required")
        authorization = {"run": approval_run, "approval": native_approval(api, repo, approval_run)}
        promotion_ingress(api, repo, pull, config)
    for observation in range(80):
        live_pull(api, repo, number, expected)
        try:
            check_quality(api, repo, pull, config)
            break
        except ControlError as error:
            if str(error) not in {"quality-check-missing-or-ambiguous", "quality-pending"} or observation == 79:
                raise
            time.sleep(15)
    current = live_pull(api, repo, number, expected)
    validate_signal(api, repo, current)
    conversation_guard = native_conversation_guard(api, repo, current)
    evidence = verify_existing_route(api, repo, current, config, route)
    live_pull(api, repo, number, expected)
    proof = canonical({"version": 1, "source_sha": source_sha, "binding": expected, "route": route,
                       "evidence": evidence, "authorization": authorization,
                       "native_conversation_guard": conversation_guard})
    require(len(proof) <= MAX_PROOF_BYTES, "native-proof-resource-bound")
    Path("control-proof.json").write_bytes(proof)
    print("Protected current-revision control passed.")


if __name__ == "__main__":
    try:
        main()
    except (ControlError, KeyError, ValueError, OSError, subprocess.SubprocessError) as error:
        print(f"Protected control blocked: {type(error).__name__}: {error if isinstance(error, ControlError) else 'required evidence unavailable'}", file=sys.stderr)
        raise SystemExit(1) from None
