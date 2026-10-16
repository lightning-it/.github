"""One explicitly requested, natively approved extra Codex attempt; no retries."""
from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import re

import workflow_control as control

MARKER = "<!-- lit-review-recovery/v1 "
OWNER = ("litroc", 76040632, "User")
LEGACY_SOURCE = "b815cefb4a5f18cd97b3947c789b6db59fedf991"
require = control.require


def history(api, repo, pull, native):
    """Count reserved effects across every native workflow generation/source."""
    reserved, delivered = [], False
    runs = api.pages(f"repos/{repo}/actions/runs?head_sha={pull['head']['sha']}", "workflow_runs")
    for run in runs:
        if not control.native_required(run, repo) or run.get("head_sha") != pull["head"]["sha"]:
            continue
        related = [p for p in run.get("pull_requests", []) if p.get("number") == pull["number"]
                   and p.get("base", {}).get("sha") == pull["base"]["sha"]
                   and p.get("head", {}).get("sha") == pull["head"]["sha"]]
        if len(related) != 1:
            continue
        require(run["id"] <= native["id"], "recovery-stale-native-generation")
        for attempt in range(1, run["run_attempt"] + 1):
            if run["id"] == native["id"] and attempt == native["run_attempt"]:
                continue
            jobs = api.pages(f"repos/{repo}/actions/runs/{run['id']}/attempts/{attempt}/jobs", "jobs")
            review = [j for j in jobs if j.get("name") == "Protected current revision"]
            require(len(review) <= 1, "recovery-ambiguous-native-job")
            if not review:
                continue
            job = review[0]
            require(job.get("run_id") == run["id"] and type(job.get("steps")) is list,
                    "recovery-native-job-provenance")
            if job.get("status") == "completed" and job.get("conclusion") == "skipped" \
                    and all(s.get("conclusion") == "skipped" for s in job["steps"]):
                continue
            delivered |= job.get("conclusion") == "success"
            steps = [s for s in job.get("steps", []) if s.get("name") == "Reserve protected Codex request"]
            require(len(steps) == 1 and job.get("run_id") == run["id"], "recovery-native-funding-history-required")
            if steps[0].get("conclusion") == "skipped":
                continue
            require(job.get("status") == "completed", "recovery-previous-request-still-pending")
            reserved.append((run, attempt, job))
    return reserved, delivered


def request(api, repo, pull):
    comments = api.pages(f"repos/{repo}/issues/{pull['number']}/comments")
    matches = [c for c in comments if control.identity(c.get("user", {})) == OWNER
               and MARKER in c.get("body", "")]
    if not matches:
        return None
    require(len(matches) == 1, "recovery-single-owner-request-required")
    comment = matches[0]
    body = comment["body"]
    require(len(body) <= 4096 and body.count(MARKER) == 1, "recovery-request-size-or-ambiguity")
    match = re.search(re.escape(MARKER) + r'(\{[^\n]+\}) -->', body)
    require(match is not None, "recovery-request-shape")
    value = json.loads(match[1])
    required = {"repository", "pull", "head", "base", "failed_run", "failed_attempt"}
    require(type(value) is dict and required <= set(value) <= required | {"legacy_unknown_outcome_sha256"}
            and value["repository"] == repo and type(value["pull"]) is int and value["pull"] == pull["number"]
            and value["head"] == pull["head"]["sha"] and value["base"] == pull["base"]["sha"]
            and all(type(value[k]) is int and value[k] > 0 for k in ("failed_run", "failed_attempt")),
            "recovery-exact-request-binding")
    return value | {"comment": comment["id"], "updated_at": comment["updated_at"]}


def plan(api, repo, pull, source, native):
    require(control.native_required(native, repo) and native["head_sha"] == pull["head"]["sha"],
            "recovery-current-native-origin")
    require(pull.get("state") == "open" and native.get("event") == "pull_request"
            and len([p for p in native.get("pull_requests", []) if p.get("number") == pull["number"]
                     and p.get("head", {}).get("sha") == pull["head"]["sha"]
                     and p.get("base", {}).get("sha") == pull["base"]["sha"]]) == 1,
            "recovery-current-subject-association")
    if pull.get("draft") or control.classify(pull, repo) != "codex":
        return None
    wanted = request(api, repo, pull)
    if wanted is None:
        return None
    reserved, delivered = history(api, repo, pull, native)
    # This grants no funding: prepare-codex must still authenticate the complete
    # cached request, and ordinary cross-generation reservation blocks a miss.
    if delivered:
        return None
    require(native["run_attempt"] == 1, "recovery-new-generation-only")
    require(len(reserved) == 1, "recovery-one-previous-reservation-only")
    failed, attempt, job = reserved[0]
    require((failed["id"], attempt) == (wanted["failed_run"], wanted["failed_attempt"])
            and failed["id"] < native["id"] and failed.get("status") == "completed"
            and failed.get("conclusion") == "failure" and failed["run_attempt"] == attempt
            and job.get("conclusion") == "failure", "recovery-exact-terminal-failure-required")
    steps = {s["name"]: s for s in job["steps"]}
    require(steps.get("Classify protected current revision", {}).get("conclusion") == "success"
            and steps.get("Reserve protected Codex request", {}).get("conclusion") == "success"
            and steps.get("Protected exact-revision Codex review", {}).get("conclusion") == "failure"
            and all(steps.get(name, {}).get("conclusion") == "skipped" for name in (
                "Collect and verify the protected model receipt", "Export protected native Codex evidence")),
            "recovery-no-delivered-review-only")
    prior = control.operation_record(api, repo, failed)
    lineage = json.loads((Path(__file__).resolve().parents[1] / ".lit/workflow-source-lineage.json").read_bytes())
    require(prior.get("source_sha") in {source, *lineage["accepted_predecessors"]}
            and control.same_immutable_tuple(prior.get("binding", {}), control.binding(pull)),
            "recovery-prior-source-and-subject-required")
    log = api.native_job_log(repo, job["id"])
    require(f'"workflow_sha": "{prior["source_sha"]}"' in log
            and f'"workflow_repository": "{control.SOURCE}"' in log
            and f'"workflow_file_path": "{control.WORKFLOW}"' in log,
            "recovery-prior-native-defining-source-required")
    artifacts = api.pages(f"repos/{repo}/actions/runs/{failed['id']}/artifacts", "artifacts")
    require(not any(a.get("name", "").startswith("codex-receipt-") for a in artifacts),
            "recovery-existing-provider-evidence-forbidden")
    outcome_name = f"control-review-outcome-{attempt}"
    if any(a.get("name") == outcome_name for a in artifacts):
        outcome = control.artifact_record(api, repo, failed, outcome_name, "control-review-outcome.json")
        require(outcome.get("version") == 1 and outcome.get("run") == failed["id"]
                and outcome.get("source_sha") == prior["source_sha"]
                and outcome.get("binding") == {"repository": repo, "pull_request": pull["number"],
                                               "head_sha": pull["head"]["sha"], "base_sha": pull["base"]["sha"]}
                and outcome.get("result_produced") is False
                and outcome.get("category") == "transport-service-unavailable"
                and type(outcome.get("failure")) is dict
                and outcome["failure"].get("category") == "transport-service-unavailable",
                "recovery-authenticated-service-failure-without-result-required")
        outcome_reference = {"artifact": outcome_name, "sha256": control.digest(outcome)}
    else:
        # The owner explicitly accepted the unknown result/cost of the old
        # source's terminal failure. Do not invent a retrospective gateway
        # outcome. This cutover exception requires acknowledgment of the exact
        # native log and the same genuine approval, and cannot apply to new code.
        require(prior["source_sha"] == LEGACY_SOURCE
                and wanted.get("legacy_unknown_outcome_sha256") == hashlib.sha256(log.encode()).hexdigest()
                and "We’re currently experiencing high demand" in log
                and "Protected gateway failure category: single-contract-rejected" in log,
                "recovery-explicit-legacy-unknown-outcome-acknowledgment-required")
        outcome_reference = {"legacy_unknown_outcome_sha256": wanted["legacy_unknown_outcome_sha256"],
                             "result_produced": "unknown"}
    control.normal_environment(api, repo)
    return {"version": 1, "binding": control.binding(pull), "source_sha": source,
            "request": wanted, "failed_source": prior["source_sha"], "failed_job": job["id"],
            "outcome": outcome_reference,
            "current_run": native["id"], "additional_attempts": 1,
            "original_provider_outcome": "unknown", "release_authorized": False}


def authorize(api, repo, pull, source, native, expected):
    result = plan(api, repo, pull, source, native)
    require(result is not None and control.digest(result) == expected, "recovery-reviewed-plan-drift")
    environment = control.normal_environment(api, repo)
    approval = control.native_approval(api, repo, native["id"])
    require(len(approval.get("environments", [])) == 1
            and approval["environments"][0].get("id") == environment.get("id")
            and type(approval.get("user", {}).get("id")) is int and approval["user"]["id"] > 0,
            "recovery-exact-native-environment-approval")
    control.live_pull(api, repo, pull["number"], control.binding(pull))
    return result | {"approval": approval}


def main():
    repo = os.environ["GITHUB_REPOSITORY"]
    source = control.source_identity(json.loads(os.environ["NATIVE_JOB"]))
    api = control.API()
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_bytes())
    number = event["pull_request"]["number"]
    pull = api.call(f"repos/{repo}/pulls/{number}")
    native = api.call(f"repos/{repo}/actions/runs/{int(os.environ['GITHUB_RUN_ID'])}")
    result = plan(api, repo, pull, source, native)
    with open(os.environ["GITHUB_OUTPUT"], "a") as output:
        output.write("required=" + ("true" if result else "false") + "\n")
        output.write("sha256=" + (control.digest(result) if result else "") + "\n")
    print("Recovery request classified; only a genuine native approval can authorize an extra attempt.")


if __name__ == "__main__":
    main()
