"""Read-only LI-219 event adapter and bounded native-reservation sweep.

Shadow decisions are observations, never check-write authorization. Legacy
reservations lack the complete immutable LI-219 admission binding. This adapter
must therefore never PATCH them, even when its two live reads agree.
"""

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import time
import urllib.error
import urllib.request


ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


STATE = load("li219_state", ROOT / "scripts/required-review-state.py")
EVIDENCE = load("li219_native", ROOT / "scripts/verify-promotion-evidence.py")
require = STATE.require
RUN_PATH = ".github/workflows/copilot-review.yml"
ADMISSION_PATH = ".github/workflows/supplementary-current-revision-required.yml"
POLICY_STEP = "Verify current Copilot review and resolved findings"
RESERVATION = re.compile(
    r"rep60-required-workflow:v3:([1-9][0-9]*):([1-9][0-9]*):"
    r"([0-9a-f]{40}):([0-9a-f]{40})"
)
THREAD_QUERY = """query($owner:String!,$name:String!,$number:Int!){
repository(owner:$owner,name:$name){pullRequest(number:$number){
number headRefOid baseRefOid lastEditedAt
reviewThreads(first:100){totalCount pageInfo{hasNextPage}
nodes{id isResolved comments(first:100){totalCount pageInfo{hasNextPage}
nodes{databaseId body updatedAt author{login}}}}}}}}"""


def parsed(raw):
    return json.loads(raw, object_pairs_hook=EVIDENCE.reject_duplicate_keys,
                      parse_constant=EVIDENCE.reject_nonstandard_constant)


def epoch(value):
    require(type(value) is str and re.fullmatch(
        r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", value), "timestamp")
    return int(datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=timezone.utc).timestamp())


def one(values, reason):
    require(type(values) is list and len(values) == 1, reason)
    return values[0]


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


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("api-redirect-refused")


class API:
    """Read-only, fixed-origin transport with per-invocation resource bounds."""
    def __init__(self, policy):
        self.policy = validate_policy(policy)
        self.requests = 0
        self.started = time.monotonic()
        self.opener = urllib.request.build_opener(NoRedirect())

    def read(self, endpoint, variables=None):
        require(endpoint == "graphql" or endpoint.startswith(
            "repos/" + self.policy["repository"] + "/")
            or endpoint == "repos/" + self.policy["repository"], "api-scope")
        require(".." not in endpoint and "#" not in endpoint, "api-path")
        require(variables is None or endpoint == "graphql", "api-method")
        remaining = self.policy["max_seconds"] - (time.monotonic() - self.started)
        require(remaining > 0 and self.requests < self.policy["max_requests"],
                "api-budget-exhausted")
        token = os.environ.get("GH_TOKEN", "")
        require(bool(token), "api-token-missing")
        body = None if variables is None else json.dumps({
            "query": THREAD_QUERY, "variables": variables,
        }).encode()
        request = urllib.request.Request(
            "https://api.github.com/" + endpoint, data=body,
            headers={"Authorization": "Bearer " + token,
                     "Accept": "application/vnd.github+json",
                     "Content-Type": "application/json",
                     "X-GitHub-Api-Version": "2022-11-28"},
            method="GET" if body is None else "POST",
        )
        self.requests += 1
        try:
            with self.opener.open(request, timeout=min(10, remaining)) as response:
                raw = response.read(2 * 1024 * 1024 + 1)
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ValueError("api-read-failed") from exc
        require(len(raw) <= 2 * 1024 * 1024, "api-response-too-large")
        return parsed(raw)

    def inventory(self, path, field=None):
        records = []
        expected_total = None
        for page in range(1, self.policy["max_pages"] + 1):
            payload = self.read(path + ("&" if "?" in path else "?")
                                + f"per_page=100&page={page}")
            items = payload if field is None else payload.get(field)
            require(type(items) is list and len(items) <= 100, "inventory-shape")
            if field is not None:
                total = payload.get("total_count")
                require(type(total) is int and total >= 0, "inventory-total")
                require(expected_total is None or total == expected_total,
                        "inventory-total-drift")
                expected_total = total
            records.extend(items)
            require(all(type(item) is dict and STATE.positive(item.get("id"))
                        for item in records), "inventory-id")
            require(len({item["id"] for item in records}) == len(records),
                    "inventory-duplicate")
            if len(items) < 100:
                require(expected_total is None or expected_total == len(records),
                        "inventory-incomplete")
                return records
        raise ValueError("inventory-page-limit")


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
    require((run.get("status"), run.get("conclusion")) in (
        ("in_progress", None), ("completed", "success")), "run-state")
    require(type(run.get("head_sha")) is str and re.fullmatch(
        r"[0-9a-f]{40}", run["head_sha"]), "run-head")
    return run


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
    require(type(rules) is list and any(rule.get("ruleset_id") == 21200954
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
    require(summary.get("schema") == 4 and summary.get("base_sha") == base
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
    reservation = one([check for check in checks if check.get("name") ==
                       "Protected current-revision verifier" and RESERVATION.fullmatch(
                           check.get("external_id") or "")], "reservation-not-unique")
    bound = RESERVATION.fullmatch(reservation["external_id"])
    require(bound.groups()[1:] == (str(number), base, head)
            and reservation.get("head_sha") == head
            and reservation.get("app", {}).get("id") == 15368
            and reservation["app"].get("slug") == "github-actions", "reservation-binding")
    admission_id = int(bound[1])
    admission = api.read(f"{prefix}/actions/runs/{admission_id}")
    require(admission.get("id") == admission_id and admission.get("path") == ADMISSION_PATH
            and admission.get("event") == "pull_request_target"
            and admission.get("head_sha") == head
            and admission.get("repository", {}).get("id") == policy["repository_id"],
            "admission-provenance")
    require(type(admission.get("run_attempt")) is int and admission["run_attempt"] == 1
            and all(type(admission.get(key)) is dict
                    and admission[key].get("id") == 76040632
                    and admission[key].get("login") == "litroc"
                    and admission[key].get("type") == "User"
                    for key in ("actor", "triggering_actor")), "admission-actor-attempt")
    reviews = api.inventory(f"{prefix}/pulls/{number}/reviews")
    review = one([item for item in reviews if item.get("commit_id") == head
                  and item.get("user", {}).get("id") == 175728472
                  and item["user"].get("login") == "copilot-pull-request-reviewer[bot]"
                  and item["user"].get("type") == "Bot"], "review-not-unique")
    require(review.get("state") in ("COMMENTED", "APPROVED"), "review-state")
    if "review_id" in summary:
        require(summary["review_id"] == review.get("node_id"), "review-id-binding")
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
    connection = graph["reviewThreads"]
    require(connection["pageInfo"].get("hasNextPage") is False
            and connection.get("totalCount") == len(connection["nodes"]), "thread-pagination")
    require(len({thread["id"] for thread in connection["nodes"]}) == len(connection["nodes"]),
            "thread-duplicate")
    for thread in connection["nodes"]:
        require(thread.get("isResolved") is True, "unresolved-thread")
        items = thread["comments"]
        require(items["pageInfo"].get("hasNextPage") is False
                and items.get("totalCount") == len(items["nodes"]), "thread-comment-pagination")
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
                    "review": review, "comments": comments})}
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
            "jobs": jobs}


def observe(api, policy, run_id, number, now):
    """Two independent network reads; no storage write is implemented."""
    first = snapshot(api, policy, run_id, number)
    final = snapshot(api, policy, run_id, number)
    require(first["reservation"] == final["reservation"], "reservation-read-drift")
    check = first["reservation"]
    require(check.get("status") in ("queued", "in_progress", "completed"), "reservation-status")
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


def summarize(observations):
    """Deduplicate native-log observations; missing/rejected samples stay unknown."""
    require(type(observations) is list and len(observations) <= 10000, "metrics-input")
    unique = {}
    for item in observations:
        require(item.get("schema") == "li219-shadow-observation/v1"
                and item.get("authority") == "none" and item.get("writes") == 0,
                "metrics-schema")
        key = item["operation_key"]
        if key in unique:
            require(item["binding_digest"] == unique[key]["binding_digest"], "metrics-binding-drift")
            if item["observed_at"] >= unique[key]["observed_at"]:
                continue
        unique[key] = item
    statistics = {}
    for metric in ("producer_job_seconds", "request_to_review_seconds",
                   "review_to_neutral_seconds", "neutral_to_observer_seconds",
                   "request_to_observer_seconds"):
        values = sorted(item["metrics"][metric] for item in unique.values()
                        if item["metrics"][metric] is not None)
        require(all(type(value) in (int, float) and math.isfinite(value)
                    and value >= 0 for value in values), "metrics-value")
        statistics[metric] = {
            "observed_samples": len(values),
            "median": None if not values else (values[(len(values) - 1) // 2]
                                               + values[len(values) // 2]) / 2,
            "p95": None if not values else values[math.ceil(len(values) * .95) - 1],
        }
    flagged = sum(item["metrics"]["native_failure_with_ready_evidence"] is True
                  for item in unique.values())
    return {"unique_operations": len(unique), "statistics": statistics,
            "native_failure_with_ready_evidence_count": flagged,
            "candidate_rate": flagged / len(unique) if unique else None,
            "measured_false_negative_rate": None,
            "cohort": "validated-shadow-observations-only"}


def sweep(api, policy, now):
    """Audit current heads of open PRs; not a global durable-reservation ledger."""
    prefix = "repos/" + policy["repository"]
    pulls = api.inventory(prefix + "/pulls?state=open&base=develop")
    require(len(pulls) <= 20, "sweeper-pull-budget")
    results = []
    for pull in pulls:
        head = pull["head"]["sha"]
        require(type(head) is str and re.fullmatch(r"[0-9a-f]{40}", head), "sweeper-head")
        checks = api.inventory(f"{prefix}/commits/{head}/check-runs?filter=all", "check_runs")
        for check in checks:
            match = RESERVATION.fullmatch(check.get("external_id") or "")
            if check.get("name") != "Protected current-revision verifier" or match is None:
                continue
            require(check.get("head_sha") == head and match[4] == head
                    and int(match[2]) == pull["number"]
                    and check.get("app", {}).get("id") == 15368
                    and check["app"].get("slug") == "github-actions", "sweeper-binding")
            if check.get("status") not in ("queued", "in_progress"):
                continue
            age = now - epoch(check["started_at"])
            require(age >= 0, "sweeper-clock")
            if age < policy["reservation_ttl_seconds"]:
                continue
            refreshed = api.read(f"{prefix}/check-runs/{check['id']}")
            require(refreshed == check, "sweeper-reservation-drift")
            results.append({"check_id": check["id"], "head": head,
                            "reservation_digest": STATE.digest(check), "age_seconds": age,
                            "would_finalize": "failure", "reason": "expired"})
    return {"schema": "li219-shadow-sweep/v1", "authority": "none", "writes": 0,
            "coverage": "current-heads-of-open-develop-pulls-only",
            "complete_global_inventory": False, "expired": results}


def dispatch(api, policy, event_name, event, now):
    validate_policy(policy)
    if policy["lifecycle"] == "inactive":
        return {"schema": "li219-shadow-disabled/v1", "authority": "none", "writes": 0}
    require(event.get("repository", {}).get("id") == policy["repository_id"]
            and event["repository"].get("full_name") == policy["repository"], "event-repository")
    if event_name == "schedule":
        return sweep(api, policy, now)
    require(event_name == "workflow_run" and event.get("action") == "completed", "event-kind")
    delivered = event["workflow_run"]
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
    started = time.monotonic()
    try:
        policy = validate_policy(parsed((ROOT / ".lit/required-review-events.json").read_bytes()))
        api = API(policy)
        if policy["lifecycle"] == "inactive":
            result = dispatch(api, policy, args.event, {}, int(time.time()))
        else:
            require(args.event_path.stat().st_size <= 2 * 1024 * 1024, "event-too-large")
            result = dispatch(api, policy, args.event, parsed(args.event_path.read_bytes()), int(time.time()))
        result["api_requests"] = api.requests
        result["observer_seconds"] = round(time.monotonic() - started, 3)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (ValueError, KeyError, TypeError, OSError) as error:
        # Only emit invariant identifiers, never user-controlled response bodies.
        reason = str(error)
        if re.fullmatch(r"[a-z][a-z0-9-]{0,100}", reason) is None:
            reason = "malformed-or-unavailable-evidence"
        print(json.dumps({"schema": "li219-shadow-rejection/v1", "authority": "none",
                          "writes": 0, "reason": reason}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
