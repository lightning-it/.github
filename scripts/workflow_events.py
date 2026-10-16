"""Metadata invalidation only; no provider call, acceptance or human approval.

Review signals are unprivileged. This receiver is loaded by a protected/default
branch workflow from one immutable helper commit, never a candidate checkout.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

from workflow_control import (
    API,
    ControlError,
    native_required,
    require,
    sha,
    source_identity,
)

SIGNAL_PATH = ".github/workflows/review-events.yml"
SIGNAL_NAME = "Repository review events"


def common_control_enforced(rules):
    """An absent rule is distinct from incomplete native enforcement data."""
    require(type(rules) is list and all(type(rule) is dict for rule in rules),
            "refresh-native-rule-shape")
    enforced = False
    for rule in rules:
        if rule.get("type") != "workflows":
            continue
        parameters = rule.get("parameters")
        require(type(parameters) is dict, "refresh-native-workflow-parameters")
        workflows = parameters.get("workflows")
        require(type(workflows) is list and bool(workflows), "refresh-native-workflow-list")
        for workflow in workflows:
            require(type(workflow) is dict
                    and type(workflow.get("repository_id")) is int and workflow["repository_id"] > 0
                    and type(workflow.get("path")) is str
                    and re.fullmatch(r"\.github/workflows/[A-Za-z0-9_.-]+\.ya?ml", workflow["path"]),
                    "refresh-native-workflow-entry")
            if workflow.get("sha") is not None:
                sha(workflow["sha"])
            if "ref" in workflow:
                require(type(workflow["ref"]) is str and bool(workflow["ref"]),
                        "refresh-native-workflow-ref")
            if workflow["repository_id"] == 1112629689 and workflow["path"] == ".github/workflows/change-control-required.yml":
                enforced = True
    return enforced


def event_pull(api, repo, name, event):
    if name == "workflow_run":
        locator = event.get("workflow_run", {}).get("id")
        require(type(locator) is int and locator > 0, "signal-native-run-locator")
        producer = api.call(f"repos/{repo}/actions/runs/{locator}")
        require(producer.get("id") == locator and producer.get("name") == SIGNAL_NAME
                and producer.get("path") == SIGNAL_PATH and producer.get("status") == "completed"
                and producer.get("event") in {"pull_request_review", "pull_request_review_comment"}, "signal-native-origin")
        # A failed/cancelled signal still invalidates stale evidence. Its
        # conclusion never grants authority; current state is checked afresh.
        pulls = producer.get("pull_requests", [])
        require(type(pulls) is list and len(pulls) == 1, "signal-pr-association")
        number = pulls[0].get("number")
        require(type(number) is int and number > 0, "signal-pr-number")
        expected_head = sha(pulls[0].get("head", {}).get("sha"))
    else:
        require(name == "pull_request_target", "unsupported-refresh-event")
        require(event.get("action") in {"edited", "labeled", "unlabeled", "ready_for_review", "converted_to_draft"}, "unsupported-metadata-action")
        number = event.get("pull_request", {}).get("number")
        require(type(number) is int and number > 0, "refresh-pr-locator")
        expected_head = None
    pull = api.call(f"repos/{repo}/pulls/{number}")
    require(pull.get("number") == number, "refresh-pull-identity")
    if pull["state"] != "open":
        return None
    require(expected_head is None or pull["head"]["sha"] == expected_head, "stale-review-signal")
    return pull


def refresh(api, repo, name, event):
    pull = event_pull(api, repo, name, event)
    if pull is None:
        return
    number, head = pull["number"], sha(pull["head"]["sha"])
    runs = api.pages(f"repos/{repo}/actions/runs?head_sha={head}", "workflow_runs")
    matches = [run for run in runs if native_required(run, repo)
               and any(pr.get("number") == number for pr in run.get("pull_requests", []))]
    if not matches:
        # An installed caller does not admit its repository. During the POC,
        # no control run and no enforced common rule grants nothing to refresh.
        # An enforced scope must fail closed if its native run is unavailable.
        base = pull["base"]["ref"]
        require(base in {"develop", "main"}, "refresh-protected-base-required")
        rules = api.call(f"repos/{repo}/rules/branches/{base}")
        require(not common_control_enforced(rules), "refresh-native-required-run-missing")
        print("Common control is not admitted here; no native verifier or approval created.")
        return
    selected = max(matches, key=lambda run: (run["id"], run["run_attempt"]))
    jobs = api.pages(f"repos/{repo}/actions/runs/{selected['id']}/jobs?filter=latest", "jobs")
    target = "Current revision review"
    if name == "pull_request_target":
        # Metadata changes require a fresh operation snapshot/classification.
        # Re-running the original review does not authorize a second provider
        # effect: only its source-bound funding step may reserve one.
        target = "Protected current revision"
    # Keep the invalidation signal until an in-flight gate finishes. Returning
    # here would allow a dismissal during finalization to leave a stale success.
    for _ in range(120):
        active = [job for job in jobs if job["name"] in {"Current revision review", "Protected current revision"}
                  and job["status"] != "completed"]
        if not active:
            break
        time.sleep(15)
        jobs = api.pages(f"repos/{repo}/actions/runs/{selected['id']}/jobs?filter=latest", "jobs")
    require(not active, "refresh-inflight-timeout")
    review = [job for job in jobs if job["name"] == "Protected current revision"]
    require(len(review) == 1, "refresh-native-review-job-ambiguous")
    # A completed failed review may now have received provider evidence. Its
    # original job reclassifies and skips already-delivered funded effects.
    if review[0]["conclusion"] != "success":
        target = "Protected current revision"
    gate = [job for job in jobs if job["name"] == target]
    require(len(gate) == 1, "refresh-native-job-ambiguous")
    current = api.call(f"repos/{repo}/pulls/{number}")
    require(current["state"] == "open" and current["head"]["sha"] == head, "stale-refresh")
    api.call(f"repos/{repo}/actions/jobs/{gate[0]['id']}/rerun", method="POST", data={})
    print("Original protected native job refreshed; no acceptance or provider retry granted.")


def main():
    repo = os.environ["GITHUB_REPOSITORY"]
    require(re.fullmatch(r"lightning-it/[A-Za-z0-9_.-]+", repo), "consumer-repository")
    source_identity(json.loads(os.environ["NATIVE_JOB"]), expected_path=".github/workflows/delivery-operations.yml")
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_bytes())
    refresh(API(), repo, os.environ["GITHUB_EVENT_NAME"], event)


if __name__ == "__main__":
    try:
        main()
    except (ControlError, KeyError, ValueError, OSError) as error:
        print(f"Metadata refresh blocked: {error if isinstance(error, ControlError) else 'native evidence unavailable'}", file=sys.stderr)
        raise SystemExit(1) from None
