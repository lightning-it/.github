"""Historical ingress acceptance; never an open-change or failed-review fallback."""
from __future__ import annotations

import re
from datetime import datetime, timedelta

from workflow_control import (
    SOURCE,
    binding,
    classify,
    digest,
    native_jobs,
    native_required,
    operation_record,
    promotion_ingress,
    require,
    sha,
)

FINAL_STEP = "Enforce native review and quality on the still-current tuple"
CLOSED = "Protected control blocked: ControlError: pull-not-reviewable"


def instant(value):
    require(type(value) is str and value.endswith("Z"), "ingress-timestamp-unavailable")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


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
            accepted = digest(operation_record(api, repo, attempt))
            require(all(item == accepted for item in operations),
                    "ingress-metadata-changed-before-merge")
            return attempt, ignored
        require(attempt.get("conclusion") == "failure" and instant(attempt.get("updated_at")) >= merged,
                "ingress-semantic-failure-before-merge")
        jobs = native_jobs(api, repo, attempt)
        failures = [job for job in jobs if job.get("conclusion") == "failure"]
        require(len(failures) == 1 and failures[0].get("name") == "Current revision review"
                and all(job.get("status") == "completed" and job.get("conclusion") in {"success", "skipped", "failure"}
                        for job in jobs), "ingress-failure-topology")
        gate = failures[0]
        bad_steps = [step for step in gate.get("steps", []) if step.get("conclusion") == "failure"]
        require(gate.get("run_attempt") == version and len(bad_steps) == 1
                and bad_steps[0].get("name") == FINAL_STEP
                and instant(gate.get("completed_at")) >= merged, "ingress-failure-step")
        log = api.native_job_log(repo, gate["id"])
        errors = [line for line in log.splitlines() if "Protected control blocked:" in line]
        require(len(errors) == 1, "ingress-closure-error-unavailable")
        match = re.fullmatch(r"(\S+Z) " + re.escape(CLOSED), errors[0])
        require(match is not None and instant(match[1]) >= after_merge, "ingress-not-closure-only")
        operations.append(digest(operation_record(api, repo, attempt)))
        ignored.append({"attempt": version, "job": gate["id"], "conclusion": "failure",
                        "reason": "pull-not-reviewable-after-merge", "completed_at": gate["completed_at"]})
    raise ValueError("ingress-successful-native-attempt-missing")


def reference_ingress(api, repo, pull, config, source):
    """Exercise actual protected ingress before a reference's funded review.

    This read-only probe grants no main promotion, human approval or release
    acceptance. Its subjects are the actual current protected branch tips.
    """
    require(repo == SOURCE and config.get("mode") == "reference" and classify(pull, repo) == "codex"
            and pull["head"]["ref"].startswith("qualification/"), "reference-ingress-scope")
    def tips():
        result = {}
        for branch in ("main", "develop"):
            value = api.call(f"repos/{repo}/branches/{branch}")
            require(value.get("protected") is True, "reference-unprotected-tip")
            result[branch] = sha(value["commit"]["sha"])
        return result
    before = tips()
    require(before["develop"] == pull["base"]["sha"], "reference-ingress-develop-drift")
    evidence = promotion_ingress(api, repo, {"base": {"sha": before["main"]},
                                         "head": {"sha": before["develop"]}}, config)
    require(tips() == before, "reference-ingress-tip-drift")
    return {"version": 1, "scope": "reference-ingress-only", "source_sha": sha(source),
            "binding": binding(pull), "refs": before, "evidence": evidence, "release_authorized": False}
