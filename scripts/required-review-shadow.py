"""Default-off read-only LI-228 integration of accepted LI-219 components.

Legacy v3 reservations are observed, never owned: outputs are advisory only.
There is no check/store writer, retry, review request or activation interface.
"""

import argparse
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import re
import time


ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


STATE = load("shadow_state", ROOT / "scripts/required-review-state.py")
TELEMETRY = load("shadow_metrics", ROOT / "scripts/required-review-telemetry.py")
TRANSPORT = load("shadow_transport", ROOT / "scripts/required-review-transport.py")
READS = load("shadow_reads", ROOT / "scripts/required-review-shadow-api.py")
EVIDENCE = load("shadow_native", ROOT / "scripts/verify-promotion-evidence.py")
API = READS.API
summarize = TELEMETRY.summarize


class ShadowRejected(ValueError):
    """Only fixed source-owned rejection identifiers."""


def require(condition, reason):
    if not condition:
        raise ShadowRejected(reason)


RUN_PATH = ".github/workflows/copilot-review.yml"
ADMISSION_PATH = ".github/workflows/supplementary-current-revision-required.yml"
POLICY_STEP = "Verify current Copilot review and resolved findings"
RESERVATION = re.compile(
    r"rep60-required-workflow:v3:([1-9][0-9]*):([1-9][0-9]*):"
    r"([0-9a-f]{40}):([0-9a-f]{40})"
)

def parsed(raw):
    return json.loads(raw, object_pairs_hook=TRANSPORT.pairs,
                      parse_constant=TRANSPORT.constant, parse_float=TRANSPORT.number)


def read_file(path, maximum=2 * 1024 * 1024):
    with path.open("rb") as source:
        raw = source.read(maximum + 1)
    require(len(raw) <= maximum, "input-byte-limit")
    return parsed(raw)


def epoch(value):
    require(type(value) is str and re.fullmatch(
        r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", value), "timestamp")
    return int(datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=timezone.utc).timestamp())


def one(values, reason):
    require(type(values) is list and len(values) == 1, reason)
    return values[0]


def valid_head_ref(value):
    """Bounded ASCII subset of Git branch refs, without normalization."""
    return (type(value) is str and 1 <= len(value) <= 255 and value != "HEAD"
            and re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9._/-]*", value) is not None
            and ".." not in value and not value.endswith(".")
            and all(part and not part.startswith(".") and not part.endswith(".lock")
                    for part in value.split("/")))


def reservation_state(check):
    # The native v3 writer admits pending checks and publishes success/failure.
    require((check.get("status"), check.get("conclusion")) in (
        ("queued", None), ("in_progress", None),
        ("completed", "success"), ("completed", "failure")), "reservation-state")


def scoped_reservations(checks, number, base, head):
    """Select this immutable scope before uniqueness or provenance validation.

    Commit check inventories may also contain a retired PR or an older base.
    Those records are not candidates and never authorize this observer.
    """
    selected = []
    for check in checks:
        if check.get("name") != "Protected current-revision verifier":
            continue
        external = check.get("external_id")
        match = RESERVATION.fullmatch(external) if type(external) is str else None
        if match is not None and match.groups()[1:] == (str(number), base, head):
            selected.append(check)
    require(len(selected) <= 1, "reservation-not-unique")
    return selected


def validate_policy(policy):
    require(type(policy) is dict and set(policy) == {
        "schema", "lifecycle", "repository", "repository_id", "controller_ref",
        "max_pages", "max_requests", "max_seconds", "reservation_ttl_seconds",
    }, "policy-shape")
    require(type(policy["schema"]) is int and policy["schema"] == 1, "policy-schema")
    require(policy["lifecycle"] in ("inactive", "shadow"), "writer-not-supported")
    require(policy["repository"] == "lightning-it/.github"
            and type(policy["repository_id"]) is int
            and policy["repository_id"] == 1112629689
            and policy["controller_ref"] == "develop", "policy-scope")
    for key, maximum in (("max_pages", 3), ("max_requests", 100),
                         ("max_seconds", 90), ("reservation_ttl_seconds", 86400)):
        require(STATE.positive(policy[key]) and policy[key] <= maximum, "policy-" + key)
    return policy


def producer(api, policy, run_id):
    require(STATE.positive(run_id), "run-id")
    run = api.read(f"repos/{policy['repository']}/actions/runs/{run_id}")
    require(run.get("id") == run_id and type(run.get("run_attempt")) is int
            and run["run_attempt"] == 1, "run-attempt")
    for key in ("repository", "head_repository"):
        require(run.get(key, {}).get("id") == policy["repository_id"]
                and run[key].get("full_name") == policy["repository"], "run-repository")
    for key in ("actor", "triggering_actor"):
        actor = run.get(key)
        require(type(actor) is dict and type(actor.get("id")) is int
                and actor["id"] == 76040632 and actor.get("login") == "litroc"
                and actor.get("type") == "User", "run-actor")
    require(run.get("path") == RUN_PATH and run.get("event") == "pull_request_target"
            and run.get("name") == "Current revision review gate", "run-workflow")
    require(run.get("status") == "completed" and run.get("conclusion") == "success", "run-state")
    require(type(run.get("head_sha")) is str and re.fullmatch(
        r"[0-9a-f]{40}", run["head_sha"]), "run-head")
    return run


def admission_run(api, policy, run_id, number, base, head, head_ref):
    require(STATE.positive(number), "admission-pr-number")
    for side, sha in (("base", base), ("head", head)):
        require(type(sha) is str and re.fullmatch(r"[0-9a-f]{40}", sha), "admission-" + side)
    require(valid_head_ref(head_ref), "admission-head-ref")
    admission = api.read(f"repos/{policy['repository']}/actions/runs/{run_id}")
    require(type(admission.get("id")) is int and admission["id"] == run_id
            and admission.get("path") == ADMISSION_PATH
            and admission.get("event") == "pull_request_target"
            and admission.get("head_sha") == head, "admission-provenance")
    require(type(admission.get("display_title")) is str
            and admission["display_title"] in (
                f"Protected current revision PR #{number} {action} {head}"
                for action in ("opened", "synchronize", "reopened", "ready_for_review", "edited")),
            "admission-title")
    association = one(admission.get("pull_requests"), "admission-pr-association")
    require(type(association) is dict and STATE.positive(association.get("number"))
            and association["number"] == number, "admission-pr-association")
    for side, sha, ref in (("base", base, "develop"), ("head", head, head_ref)):
        bound = association.get(side)
        require(type(bound) is dict and bound.get("sha") == sha and bound.get("ref") == ref
                and type(bound.get("repo")) is dict
                and type(bound["repo"].get("id")) is int
                and bound["repo"].get("id") == policy["repository_id"]
                and bound["repo"].get("url") == f"{TRANSPORT.ORIGIN}/repos/{policy['repository']}",
                "admission-pr-binding")
    require(admission.get("head_branch") == head_ref, "admission-head-ref")
    for key in ("repository", "head_repository"):
        require(admission.get(key, {}).get("id") == policy["repository_id"]
                and admission[key].get("full_name") == policy["repository"],
                "admission-repository")
    require(type(admission.get("run_attempt")) is int and admission["run_attempt"] == 1
            and all(type(admission.get(key)) is dict
                    and type(admission[key].get("id")) is int
                    and admission[key]["id"] == 76040632
                    and admission[key].get("login") == "litroc"
                    and admission[key].get("type") == "User"
                    for key in ("actor", "triggering_actor")), "admission-actor-attempt")
    return admission


def snapshot(api, policy, run_id, number):
    repo = policy["repository"]
    prefix = "repos/" + repo
    run = producer(api, policy, run_id)
    pull = api.read(f"{prefix}/pulls/{number}")
    require(pull.get("number") == number and pull.get("state") == "open"
            and pull.get("draft") is False, "pull-state")
    require(pull.get("user", {}).get("id") == 76040632
            and pull["user"].get("login") == "litroc"
            and pull["user"].get("type") == "User", "pull-author")
    for side in ("base", "head"):
        require(pull[side]["repo"]["id"] == policy["repository_id"]
                and pull[side]["repo"]["full_name"] == repo, "pull-repository")
    head, base = pull["head"]["sha"], pull["base"]["sha"]
    require(head == run["head_sha"] and pull["head"]["ref"] == run["head_branch"]
            and pull["base"]["ref"] == "develop", "pull-run-binding")
    branch = api.read(f"{prefix}/branches/develop")
    require(branch.get("protected") is True and branch["commit"]["sha"] == base,
            "protected-base-drift")
    rules = api.read(f"{prefix}/rules/branches/develop")
    require(type(rules) is list and all(type(rule) is dict for rule in rules), "rules-shape")
    require(any(rule.get("ruleset_id") == 21200954
        and rule.get("type") == "workflows" and rule.get("parameters", {}).get(
            "workflows") == [{"path": ".github/workflows/dot-github-current-revision-required.yml",
                              "ref": "refs/heads/main", "repository_id": 1103407173}]
        for rule in rules), "required-workflow-authority")
    checks = api.inventory(f"{prefix}/commits/{head}/check-runs?filter=all", "check_runs")
    expected = f"mlx90-current-revision:copilot:v6:{number}:{run_id}:{base}:{head}"
    neutral = one([check for check in checks if check.get("name") == "Current revision review"
                   and check.get("external_id") == expected], "neutral-not-unique")
    require(neutral.get("status") == "completed" and neutral.get("conclusion") == "success"
            and neutral.get("app", {}).get("id") == 15368
            and neutral["app"].get("slug") == "github-actions"
            and neutral.get("head_sha") == head, "neutral-provenance")
    summary = parsed(neutral["output"]["summary"])
    require(type(summary) is dict and set(summary) == {
        "schema", "base_sha", "head_sha", "controller_sha", "pull_request_number",
        "producer_run_id", "review_path", "run_url",
    }, "neutral-summary-shape")
    require(type(summary["schema"]) is int and summary["schema"] == 4, "neutral-summary-schema")
    require(all(STATE.positive(summary[key]) for key in ("producer_run_id", "pull_request_number")),
            "neutral-summary-integer")
    require(summary["review_path"] == "applicable Copilot or governed automation exemption",
            "neutral-summary-path")
    require(summary.get("base_sha") == base
            and summary.get("head_sha") == head and summary.get("producer_run_id") == run_id
            and summary.get("pull_request_number") == number
            and summary.get("run_url") == f"https://github.com/{repo}/actions/runs/{run_id}",
            "neutral-binding")
    controller = summary.get("controller_sha")
    require(type(controller) is str and re.fullmatch(r"[0-9a-f]{40}", controller), "controller")
    ancestry = api.read(f"{prefix}/compare/{controller}...{base}")
    require(ancestry.get("status") == "identical" or (ancestry.get("status") == "ahead"
            and ancestry.get("behind_by") == 0
            and ancestry.get("merge_base_commit", {}).get("sha") == controller), "controller-ancestry")
    reservation = one(scoped_reservations(checks, number, base, head), "reservation-not-unique")
    bound = RESERVATION.fullmatch(reservation["external_id"])
    require(bound.groups()[1:] == (str(number), base, head)
            and reservation.get("head_sha") == head
            and reservation.get("app", {}).get("id") == 15368
            and reservation["app"].get("slug") == "github-actions", "reservation-binding")
    admission_id = int(bound[1])
    admission = admission_run(api, policy, admission_id, number, base, head, pull["head"]["ref"])
    reviews = api.inventory(f"{prefix}/pulls/{number}/reviews")
    review = one([item for item in reviews if item.get("commit_id") == head
                  and item.get("user", {}).get("id") == 175728472
                  and item["user"].get("login") == "copilot-pull-request-reviewer[bot]"
                  and item["user"].get("type") == "Bot"], "review-not-unique")
    require(review.get("state") in ("COMMENTED", "APPROVED"), "review-state")
    comments = api.inventory(f"{prefix}/pulls/{number}/reviews/{review['id']}/comments")
    texts = [review.get("body")] + [item.get("body") for item in comments]
    require(all(type(value) is str for value in texts), "review-body")
    require(not any(marker in EVIDENCE.normalized_review_text(value)
                    for marker in EVIDENCE.COPILOT_REVIEW_FAILURE_MARKERS
                    for value in texts), "review-unavailable")
    # Match the producer's positive-content requirement; a transport-only HTML
    # marker cannot by itself constitute a substantive review.
    require(any(re.sub(r"<!--.*?-->", "", value, flags=re.DOTALL).strip()
                for value in texts), "review-content-empty")
    # Overview counts/recommendations are historical, not live resolution
    # authority. The complete bound GraphQL thread inventory below decides.
    require(epoch(review["submitted_at"]) <= epoch(neutral["completed_at"]), "review-chronology")
    issue_comments = api.inventory(f"{prefix}/issues/{number}/comments")
    marker = f"<!-- mlx90-copilot-request head={head} -->"
    requests = [item for item in issue_comments if type(item.get("body")) is str
                and item["body"].startswith(marker)]
    require(len(requests) <= 1, "request-marker-not-unique")
    requested = None
    if requests:
        request = requests[0]
        require(request.get("user", {}).get("id") == 41898282
                and request["user"].get("login") == "github-actions[bot]"
                and request["user"].get("type") == "Bot", "request-marker-provenance")
        requested = epoch(request["created_at"])
        require(requested <= epoch(review["submitted_at"]), "request-review-chronology")
    owner, name = repo.split("/")
    threads = api.read("graphql", {"owner": owner, "name": name, "number": number})
    require(not threads.get("errors"), "threads-api-errors")
    graph = threads["data"]["repository"]["pullRequest"]
    require(graph.get("number") == number and graph.get("headRefOid") == head
            and graph.get("baseRefOid") == base and "lastEditedAt" in graph, "thread-pull-drift")
    graph_reviews = graph["reviews"]
    require(type(graph_reviews.get("totalCount")) is int
            and type(graph_reviews.get("nodes")) is list and len(graph_reviews["nodes"]) <= 100
            and graph_reviews["pageInfo"].get("hasNextPage") is False
            and graph_reviews["totalCount"] == len(graph_reviews["nodes"]), "review-pagination")
    require(all(type(item.get("id")) is str and item["id"] for item in graph_reviews["nodes"])
            and len({item["id"] for item in graph_reviews["nodes"]}) == len(graph_reviews["nodes"]),
            "graph-review-id")
    graph_review = one([item for item in graph_reviews["nodes"] if item["id"] == review["node_id"]],
                       "graph-review-binding")
    require(graph_review["body"] == review["body"] and graph_review["commit"]["oid"] == head
            and "lastEditedAt" in graph_review, "graph-review-content")
    require(graph_review["lastEditedAt"] is None
            or epoch(graph_review["lastEditedAt"]) <= epoch(neutral["completed_at"]),
            "review-edited-after-evidence")
    connection = graph["reviewThreads"]
    require(type(connection.get("totalCount")) is int
            and type(connection.get("nodes")) is list and len(connection["nodes"]) <= 100
            and connection["pageInfo"].get("hasNextPage") is False
            and connection.get("totalCount") == len(connection["nodes"]), "thread-pagination")
    require(len({thread["id"] for thread in connection["nodes"]}) == len(connection["nodes"]),
            "thread-duplicate")
    for thread in connection["nodes"]:
        require(type(thread.get("id")) is str and bool(thread["id"]), "thread-id")
        require(thread.get("isResolved") is True, "unresolved-thread")
        items = thread["comments"]
        require(type(items.get("totalCount")) is int
                and type(items.get("nodes")) is list and len(items["nodes"]) <= 100
                and items["pageInfo"].get("hasNextPage") is False
                and items.get("totalCount") == len(items["nodes"]), "thread-comment-pagination")
        require(all(type(item) is dict and type(item.get("id")) is str and item["id"]
                    and type(item.get("body")) is str for item in items["nodes"]), "thread-comment-shape")
        require(len({item["id"] for item in items["nodes"]}) == len(items["nodes"]),
                "thread-comment-duplicate")
        require(all(epoch(item["updatedAt"]) <= epoch(neutral["completed_at"])
                    for item in items["nodes"]), "thread-edited-after-evidence")
    jobs = api.inventory(f"{prefix}/actions/runs/{run_id}/jobs?filter=all", "jobs")
    for item in jobs:
        require(item.get("run_id") == run_id and type(item.get("run_attempt")) is int
                and item["run_attempt"] == 1 and item.get("head_sha") == head,
                "job-inventory-binding")
        require((item.get("status"), item.get("conclusion")) in (
            ("completed", "success"), ("completed", "skipped"), ("in_progress", None),
            ("queued", None)), "job-inventory-failed")
    job = one([item for item in jobs if item.get("name") == "Verify current revision policy"],
              "job-not-unique")
    identity = {"repository": repo, "repository_id": policy["repository_id"], "pr": number,
                "base": base, "head": head, "controller": controller,
                "ruleset_digest": STATE.digest(rules), "actor_id": 76040632,
                "producer_run": run_id, "producer_attempt": 1, "admission_run": admission_id,
                "reviewer_id": 175728472, "metadata_digest": STATE.digest({
                    "title": pull["title"], "body": pull["body"], "labels": pull["labels"],
                    "last_edited": graph.get("lastEditedAt"), "threads": connection,
                    "review": review, "graph_review": graph_review, "comments": comments})}
    proof = {"binding": identity, "pr_open": True, "draft": False, "unresolved_threads": 0,
             "review": {"id": review["id"], "reviewer_id": 175728472, "head": head,
                        "state": review["state"]},
             "job": {key: job[key] for key in ("id", "run_id", "run_attempt", "head_sha",
                                               "status", "conclusion")}}
    proof["job"]["steps"] = [{key: step[key] for key in ("name", "status", "conclusion")}
                               for step in job["steps"]]
    STATE.evidence(proof, identity, POLICY_STEP)
    return {"proof": proof, "reservation": reservation, "run": run,
            "request_created": requested, "review_submitted": epoch(review["submitted_at"]),
            "neutral_completed": epoch(neutral["completed_at"]),
            "jobs": jobs, "neutral": neutral, "admission": admission}


def observe(api, policy, run_id, number, now):
    """Two independent network reads; no storage write is implemented."""
    first = snapshot(api, policy, run_id, number)
    final = snapshot(api, policy, run_id, number)
    require(first["reservation"] == final["reservation"], "reservation-read-drift")
    require(first["neutral"] == final["neutral"], "neutral-read-drift")
    require(first["admission"] == final["admission"], "admission-read-drift")
    check = first["reservation"]
    reservation_state(check)
    created = epoch(check["started_at"])
    identity = first["proof"]["binding"]
    model = STATE.admit(identity, check["id"], created, policy["reservation_ttl_seconds"])
    candidate = STATE.finalize(model, identity, first["proof"], final["proof"], POLICY_STEP, now)
    durations = []
    for job in final["jobs"]:
        if job.get("status") == "completed" and job.get("conclusion") == "skipped":
            durations.append(0)
        elif job.get("status") == "completed":
            duration = epoch(job["completed_at"]) - epoch(job["started_at"])
            require(duration >= 0, "job-clock")
            durations.append(duration)
    require(now >= final["review_submitted"] and now >= final["neutral_completed"], "event-clock")
    return {
        "schema": "li219-shadow-observation/v1", "authority": "none", "writes": 0,
        "operation_key": candidate["key"], "binding_digest": STATE.digest(identity),
        "evidence_digest": candidate["evidence_digest"], "check_id": check["id"],
        "would_finalize": candidate["state"], "observed_at": now,
        "native_reservation_state": check["status"],
        "native_reservation_conclusion": check.get("conclusion"),
        "metrics": {
            "producer_job_seconds": sum(durations) if len(durations) == len(final["jobs"]) else None,
            "producer_jobs_terminal": len(durations),
            "producer_job_minutes": sum(durations) / 60 if len(durations) == len(final["jobs"]) else None,
            "request_to_review_seconds": None if final["request_created"] is None else
                final["review_submitted"] - final["request_created"],
            "review_to_neutral_seconds": final["neutral_completed"] - final["review_submitted"],
            "neutral_to_observer_seconds": now - final["neutral_completed"],
            "reservation_to_observer_seconds": now - created,
            "request_to_observer_seconds": None if final["request_created"] is None else
                now - final["request_created"],
            "native_failure_with_ready_evidence": check.get("conclusion") == "failure",
        },
    }


def sweep(api, policy, now):
    """Audit current heads of open PRs; not a global durable-reservation ledger."""
    prefix = "repos/" + policy["repository"]
    pulls = api.inventory(prefix + "/pulls?state=open&base=develop")
    # One pull page + 14 * (three check pages + four revalidation reads) = 99.
    require(len(pulls) <= 14, "sweeper-pull-budget")
    results = []
    for pull in pulls:
        require(STATE.positive(pull.get("number")) and pull.get("state") == "open"
                and pull["base"]["ref"] == "develop"
                and all(pull[side]["repo"]["id"] == policy["repository_id"]
                        and pull[side]["repo"]["full_name"] == policy["repository"]
                        for side in ("head", "base")),
                "sweeper-pull-state")
        head = pull["head"]["sha"]
        require(type(head) is str and re.fullmatch(r"[0-9a-f]{40}", head), "sweeper-head")
        base = pull["base"].get("sha")
        require(type(base) is str and re.fullmatch(r"[0-9a-f]{40}", base), "sweeper-base")
        checks = api.inventory(f"{prefix}/commits/{head}/check-runs?filter=all", "check_runs")
        for check in scoped_reservations(checks, pull["number"], base, head):
            match = RESERVATION.fullmatch(check.get("external_id") or "")
            require(check.get("head_sha") == head and match[4] == head
                    and match[3] == base
                    and int(match[2]) == pull["number"]
                    and check.get("app", {}).get("id") == 15368
                    and check["app"].get("slug") == "github-actions", "sweeper-binding")
            reservation_state(check)
            if check["status"] == "completed":
                continue
            age = now - epoch(check["started_at"])
            require(age >= 0, "sweeper-clock")
            if age < policy["reservation_ttl_seconds"]:
                continue
            admission = admission_run(api, policy, int(match[1]), pull["number"],
                                      base, head, pull["head"]["ref"])
            refreshed = api.read(f"{prefix}/check-runs/{check['id']}")
            require(refreshed == check, "sweeper-reservation-drift")
            current = api.read(f"{prefix}/pulls/{pull['number']}")
            require(type(current) is dict and current.get("state") == "open"
                    and current.get("number") == pull["number"]
                    and current.get("base") == pull["base"]
                    and current.get("head") == pull["head"], "sweeper-pull-drift")
            require(admission_run(api, policy, int(match[1]), pull["number"],
                                  base, head, pull["head"]["ref"]) == admission,
                    "sweeper-admission-drift")
            results.append({"check_id": check["id"], "head": head,
                            "reservation_digest": STATE.digest(check), "age_seconds": age,
                            "admission_run": int(match[1]),
                            "admission_digest": STATE.digest(admission),
                            "would_finalize": "failure", "reason": "expired"})
    return {"schema": "li219-shadow-sweep/v1", "authority": "none", "writes": 0,
            "coverage": "current-heads-of-open-develop-pulls-only",
            "historical_controller_binding": "unavailable-in-legacy-v3",
            "complete_global_inventory": False, "expired": results}


def dispatch(api, policy, event_name, event, now):
    validate_policy(policy)
    if policy["lifecycle"] == "inactive":
        return {"schema": "li219-shadow-disabled/v1", "authority": "none", "writes": 0}
    require(type(event) is dict and type(event.get("repository")) is dict, "event-shape")
    require(event.get("repository", {}).get("id") == policy["repository_id"]
            and event["repository"].get("full_name") == policy["repository"], "event-repository")
    if event_name == "schedule":
        return sweep(api, policy, now)
    require(event_name == "workflow_run" and event.get("action") == "completed", "event-kind")
    delivered = event["workflow_run"]
    require(type(delivered) is dict, "event-run-shape")
    run = producer(api, policy, delivered.get("id"))
    require(all(delivered.get(key) == run.get(key) for key in (
        "id", "run_attempt", "head_sha", "path", "event", "status", "conclusion",
    )), "event-run-drift")
    for field, keys in (("actor", ("id", "login", "type")),
                        ("triggering_actor", ("id", "login", "type")),
                        ("repository", ("id", "full_name")),
                        ("head_repository", ("id", "full_name"))):
        require(type(delivered.get(field)) is dict
                and all(delivered[field].get(key) == run[field].get(key) for key in keys),
                "event-identity-drift")
    require(run["status"] == "completed" and run["conclusion"] == "success", "event-terminal")
    pulls = api.inventory(f"repos/{policy['repository']}/commits/{run['head_sha']}/pulls")
    pull = one([item for item in pulls if item.get("state") == "open"
                and item.get("head", {}).get("sha") == run["head_sha"]], "event-pull-not-unique")
    return observe(api, policy, run["id"], pull["number"], now)



def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event", required=True, choices=("workflow_run", "schedule"))
    parser.add_argument("--event-path", required=True, type=Path)
    args = parser.parse_args()
    try:
        policy = validate_policy(read_file(ROOT / ".lit/required-review-shadow.json", 16384))
        if policy["lifecycle"] == "inactive":
            result = dispatch(None, policy, args.event, {}, int(time.time()))
            result["api_requests"] = 0
        else:
            require(os.environ.get("LI219_EVENT_SHADOW") == "true", "shadow-not-enabled")
            api = API(policy)
            result = dispatch(api, policy, args.event, read_file(args.event_path), int(time.time()))
            result["api_requests"] = api.requests
            if result["schema"] == "li219-shadow-observation/v1":
                result["telemetry"] = summarize([result])
        encoded = json.dumps(result, sort_keys=True, allow_nan=False)
    except Exception as error:
        reason = str(error) if isinstance(error, (ShadowRejected, TRANSPORT.ReadFailure,
                                                  READS.TRANSPORT.ReadFailure)) else "invalid-evidence"
        print(json.dumps({"schema": "li219-shadow-rejection/v1", "authority": "none",
                          "writes": 0, "reason": reason}, sort_keys=True))
        return 1
    print(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
