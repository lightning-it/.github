"""Historical ingress acceptance; never an open-change or failed-review fallback."""
from __future__ import annotations

import re
from datetime import datetime, timedelta

from workflow_control import (
    binding,
    digest,
    native_jobs,
    native_required,
    operation_record,
    require,
)

FINAL_STEP = "Enforce native review and quality on the still-current tuple"
CLASSIFY_STEP = "Classify protected current revision"
CLOSED = "Protected control blocked: ControlError: pull-not-reviewable"


def instant(value):
    require(type(value) is str and value.endswith("Z"), "ingress-timestamp-unavailable")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def merged_lifecycle(api, repo, pull, attempt):
    """Rule out draft/manual-closure errors without trusting runner clock skew."""
    started = instant(attempt.get("run_started_at"))
    events = api.pages(f"repos/{repo}/issues/{pull['number']}/events")
    merges = [event for event in events if event.get("event") == "merged"]
    require(len(merges) == 1 and merges[0].get("commit_id") == pull["merge_commit_sha"]
            and merges[0].get("created_at") == pull["merged_at"]
            and type(merges[0].get("id")) is int, "ingress-native-merge-event-required")
    merge = merges[0]
    closed = []
    for event in events:
        kind = event.get("event")
        if kind not in {"convert_to_draft", "converted_to_draft", "reopened", "closed"}:
            continue
        if instant(event.get("created_at")) < started:
            continue
        require(kind == "closed" and event.get("created_at") == pull["merged_at"]
                and type(event.get("id")) is int and event["id"] > merge["id"],
                "ingress-ambiguous-reviewability-history")
        closed.append(event["id"])
    require(len(closed) == 1, "ingress-native-merge-closure-required")
    return {"merge_event": merge["id"], "closed_event": closed[0]}


def paired_closure_jobs(jobs):
    """Admit only the observed classifier/finalizer closure topology."""
    expected = {"Protected current revision": "failure", "Source common quality": "success",
                "Current revision review": "failure", "Approve exact main promotion": "skipped"}
    require(len(jobs) == len(expected)
            and {job.get("name"): job.get("conclusion") for job in jobs} == expected,
            "ingress-failure-topology")
    protected = next(job for job in jobs if job["name"] == "Protected current revision")
    steps = protected.get("steps", [])
    names = [step.get("name") for step in steps]
    require(len(names) == len(set(names)) and names.count(CLASSIFY_STEP) == 1,
            "ingress-closure-classification-unavailable")
    following = steps[names.index(CLASSIFY_STEP) + 1:]
    required = {"Persist protected operation binding", "Request current Copilot review",
                "Reserve protected Codex request", "Protected exact-revision Codex review"}
    require(required <= {step.get("name") for step in following}
            and all(step.get("status") == "completed"
                    and (step.get("conclusion") in {"success", "skipped"}
                         if step.get("name") in {"Post Load immutable common source", "Complete job"}
                         else step.get("conclusion") == "skipped") for step in following),
            "ingress-closure-classification-effects")


def merged_attempt(api, repo, pull, latest):
    """Distinguish a real pre-merge pass from a later closure-only invalidation.

    No failed attempt is reclassified. Return the genuine native successful
    attempt and retain every excluded failed attempt as a failed audit record.
    All metadata snapshots must be byte-equivalent to the accepted operation.
    """
    require(pull.get("merged") is True and pull.get("state") == "closed"
            and pull.get("merge_commit_sha"), "ingress-protected-run-not-successful")
    merged = instant(pull.get("merged_at"))
    # GitHub truncates merged_at to seconds. The entire reported second is
    # ambiguous: a draft rejection could precede a merge within that second.
    after_merge = merged + timedelta(seconds=1)
    require(latest.get("status") == "completed" and latest.get("conclusion") == "failure"
            and type(latest.get("run_attempt")) is int and 1 < latest["run_attempt"] <= 100,
            "ingress-protected-run-not-successful")
    ignored, operations = [], []
    for version in range(latest["run_attempt"], 0, -1):
        attempt = api.call(f"repos/{repo}/actions/runs/{latest['id']}/attempts/{version}")
        require(attempt.get("id") == latest["id"] and attempt.get("run_attempt") == version
                and attempt.get("head_sha") == latest["head_sha"]
                and attempt.get("workflow_id") == latest["workflow_id"] and native_required(attempt, repo),
                "ingress-attempt-origin")
        require(attempt.get("status") == "completed", "ingress-attempt-still-pending")
        if attempt.get("conclusion") == "success":
            require(instant(attempt.get("updated_at")) < merged and ignored,
                    "ingress-success-not-before-merge")
            operation = operation_record(api, repo, attempt)
            require(operation.get("binding") == binding(pull), "ingress-current-metadata-drift")
            accepted = digest(operation)
            require(all(item == accepted for item in operations),
                    "ingress-metadata-changed-before-merge")
            lifecycle = merged_lifecycle(api, repo, pull, attempt)
            for item in ignored:
                item.update(lifecycle)
            return attempt, ignored
        require(attempt.get("conclusion") == "failure" and instant(attempt.get("updated_at")) >= merged,
                "ingress-semantic-failure-before-merge")
        jobs = native_jobs(api, repo, attempt)
        failures = [job for job in jobs if job.get("conclusion") == "failure"]
        if len(failures) == 2:
            paired_closure_jobs(jobs)
        else:
            require(len(failures) == 1 and failures[0].get("name") == "Current revision review",
                    "ingress-failure-topology")
        require(all(job.get("status") == "completed"
                    and job.get("conclusion") in {"success", "skipped", "failure"} for job in jobs),
                "ingress-failure-topology")
        for gate in failures:
            expected_step = CLASSIFY_STEP if gate["name"] == "Protected current revision" else FINAL_STEP
            bad_steps = [step for step in gate.get("steps", []) if step.get("conclusion") == "failure"]
            require(gate.get("run_id") == attempt["id"] and gate.get("run_attempt") == version
                    and len(bad_steps) == 1 and bad_steps[0].get("name") == expected_step
                    and instant(gate.get("completed_at")) >= merged, "ingress-failure-step")
            log = api.native_job_log(repo, gate["id"])
            errors = [line for line in log.splitlines() if "Protected control blocked:" in line]
            require(len(errors) == 1, "ingress-closure-error-unavailable")
            match = re.fullmatch(r"(\S+Z) " + re.escape(CLOSED), errors[0])
            require(match is not None and instant(match[1]) >= after_merge, "ingress-not-closure-only")
            ignored.append({"attempt": version, "job": gate["id"], "conclusion": "failure",
                            "reason": "pull-not-reviewable-after-merge", "completed_at": gate["completed_at"]})
        operations.append(digest(operation_record(api, repo, attempt)))
    raise ValueError("ingress-successful-native-attempt-missing")
