"""Metadata invalidation only; no provider call, acceptance or human approval.

Review signals are unprivileged. This receiver is loaded by a protected/default
branch workflow from one immutable helper commit, never a candidate checkout.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

from workflow_control import (
    API,
    ControlError,
    native_required,
    request_slot_started,
    require,
    sha,
    source_identity,
)

SIGNAL_PATH = ".github/workflows/review-events.yml"
SIGNAL_NAME = "Repository review events"


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
        require(name in {"pull_request_target", "issue_comment"}, "unsupported-refresh-event")
        if name == "pull_request_target":
            require(event.get("action") in {"edited", "labeled", "unlabeled", "ready_for_review", "converted_to_draft"}, "unsupported-metadata-action")
        number = event.get("pull_request", {}).get("number", event.get("issue", {}).get("number"))
        require(type(number) is int and number > 0, "refresh-pr-locator")
        require(name != "issue_comment" or event.get("issue", {}).get("pull_request"), "issue-is-not-pull-request")
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
    require(matches, "refresh-native-required-run-missing")
    selected = max(matches, key=lambda run: (run["id"], run["run_attempt"]))
    jobs = api.pages(f"repos/{repo}/actions/runs/{selected['id']}/jobs?filter=latest", "jobs")
    target = "Current revision review"
    if name == "pull_request_target" and event.get("action") == "ready_for_review":
        reviews = [job for job in jobs if job["name"] == "Protected current revision"]
        require(len(reviews) == 1, "refresh-native-review-job-ambiguous")
        if reviews[0]["status"] == "completed" and reviews[0]["conclusion"] != "success":
            for version in range(1, selected["run_attempt"] + 1):
                require(request_slot_started(api, repo, selected, attempt=version) is not True,
                        "ready-does-not-retry-consumed-request")
            target = "Protected current revision"
    gate = [job for job in jobs if job["name"] == target]
    require(len(gate) == 1, "refresh-native-job-ambiguous")
    if gate[0]["status"] != "completed":
        return
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
