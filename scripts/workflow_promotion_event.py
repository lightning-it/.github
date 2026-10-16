"""Read-only admission of a relevant native event; no review or approval effect."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from workflow_control import API, ControlError, require, sha, source_identity

REPOSITORY = "lightning-it/.github"
REPOSITORY_ID = 1112629689
QUALITY = ".github/workflows/repository-quality.yml"
DELIVERY = ".github/workflows/delivery-operations.yml"


def current_head(api, event, env):
    require(env.get("GITHUB_REPOSITORY") == REPOSITORY
            and env.get("GITHUB_REPOSITORY_ID") == str(REPOSITORY_ID)
            and env.get("GITHUB_EVENT_NAME") == "workflow_run"
            and env.get("GITHUB_REF") == "refs/heads/develop"
            and env.get("GITHUB_WORKFLOW_REF") == f"{REPOSITORY}/{DELIVERY}@refs/heads/develop",
            "promotion-event-reference-scope")
    source_identity(json.loads(env["NATIVE_JOB"]), expected_path=DELIVERY)
    signal = event.get("workflow_run", {})
    locator = signal.get("id")
    require(type(locator) is int and locator > 0 and event.get("action") == "completed",
            "promotion-event-locator")
    run = api.call(f"repos/{REPOSITORY}/actions/runs/{locator}")
    workflow = api.call(f"repos/{REPOSITORY}/actions/workflows/repository-quality.yml")
    require(run.get("id") == locator and run.get("workflow_id") == workflow.get("id")
            and workflow.get("path") == QUALITY and run.get("path") == QUALITY
            and run.get("name") == "Repository Quality" and run.get("event") == "push"
            and run.get("head_branch") == "develop" and run.get("run_attempt") == 1
            and run.get("status") == "completed" and run.get("conclusion") == "success"
            and run.get("repository", {}).get("id") == REPOSITORY_ID
            and run.get("head_repository", {}).get("id") == REPOSITORY_ID,
            "promotion-event-native-origin")
    head = sha(run["head_sha"])
    require(head == signal.get("head_sha"), "promotion-event-binding")
    branch = api.call(f"repos/{REPOSITORY}/branches/develop")
    require(branch.get("name") == "develop" and branch.get("protected") is True,
            "promotion-event-protected-develop")
    if branch["commit"]["sha"] != head:
        return None
    jobs = api.pages(f"repos/{REPOSITORY}/actions/runs/{locator}/jobs?filter=latest", "jobs")
    quality = [job for job in jobs if job.get("name") == "repository / quality"]
    require(len(quality) == 1 and quality[0].get("status") == "completed"
            and quality[0].get("conclusion") == "success", "promotion-event-quality-not-successful")
    return head


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-head")
    args = parser.parse_args()
    expected = sha(args.expected_head) if args.expected_head else None
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_bytes())
    head = current_head(API(), event, os.environ)
    if head is not None and (expected is None or expected == head):
        print(head)


if __name__ == "__main__":
    try:
        main()
    except (ControlError, KeyError, ValueError, TypeError, OSError):
        print("Promotion event blocked; no dispatch or approval granted.", file=sys.stderr)
        raise SystemExit(1) from None
