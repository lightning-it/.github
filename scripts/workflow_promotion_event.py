"""Authenticate an admitted private completion and native ingress before dispatch."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from workflow_control import API, ControlError, SOURCE, WORKFLOW, check_native_control, policy, require, sha, source_identity

DELIVERY = ".github/workflows/delivery-operations.yml"


def target(repository):
    value = json.loads((Path(__file__).resolve().parents[1] / ".lit/promotion-event-targets.json").read_bytes())
    require(set(value) == {"version", "targets"} and value["version"] == 1
            and type(value["targets"]) is list and len(value["targets"]) == 1,
            "promotion-event-target-registry")
    entry = value["targets"][0]
    require(type(entry) is dict and set(entry) == {"repository", "repository_id", "scope", "source_sha", "workflow", "workflow_name", "job"}
            and entry["repository"] == "lightning-it/shared-assets-lit" and entry["repository_id"] == 1120841013
            and entry["scope"] == "shared-assets" and entry["source_sha"] == "bb1a5df9f54c5f98547048297e7e367cc382543e"
            and entry["workflow"] == ".github/workflows/repository-quality.yml"
            and entry["workflow_name"] == "Repository policy audit" and entry["job"] == "Release policy audit artifact",
            "promotion-event-target-identity")
    require(entry["repository"] == repository, "promotion-event-target-not-admitted")
    return entry


def selected_control(api, entry):
    repository = entry["repository"]
    matching = [rule for rule in api.pages(f"repos/{repository}/rulesets?includes_parents=true")
                if rule.get("name") == "WF-1 central review / " + entry["scope"]]
    require(len(matching) == 1, "promotion-event-independent-selection-required")
    rule = api.call(f"repos/{repository}/rulesets/{matching[0]['id']}")
    expected = {"repository_id": 1112629689, "path": WORKFLOW,
                "sha": entry["source_sha"], "ref": "refs/heads/main"}
    require(rule.get("enforcement") in {"evaluate", "active"} and rule.get("bypass_actors") == []
            and rule.get("source_type") == "Organization" and rule.get("source") == "lightning-it"
            and rule.get("target") == "branch"
            and rule.get("conditions") == {"repository_id": {"repository_ids": [entry["repository_id"]]},
                                           "ref_name": {"include": ["refs/heads/develop", "refs/heads/main"], "exclude": []}}
            and rule.get("rules") == [{"type": "workflows", "parameters": {
                "do_not_enforce_on_create": False, "workflows": [expected]}}],
            "promotion-event-selection-drift")


def current_head(api, event, env):
    entry = target(env.get("GITHUB_REPOSITORY"))
    repository, identifier = entry["repository"], entry["repository_id"]
    require(env.get("GITHUB_REPOSITORY_ID") == str(identifier)
            and env.get("GITHUB_EVENT_NAME") == "workflow_run"
            and env.get("GITHUB_REF") == "refs/heads/develop"
            and env.get("GITHUB_WORKFLOW_REF") == f"{repository}/{DELIVERY}@refs/heads/develop",
            "promotion-event-protected-receiver-required")
    defining = json.loads(env["NATIVE_JOB"])
    source_identity(defining, expected_path=DELIVERY)
    signal = event.get("workflow_run", {})
    locator = signal.get("id")
    require(type(locator) is int and locator > 0 and event.get("action") == "completed",
            "promotion-event-locator")
    run = api.call(f"repos/{repository}/actions/runs/{locator}")
    workflow = api.call(f"repos/{repository}/actions/workflows/repository-quality.yml")
    require(run.get("id") == locator and run.get("workflow_id") == workflow.get("id")
            and workflow.get("path") == entry["workflow"] and run.get("path") == entry["workflow"]
            and run.get("workflow_url") == f"https://api.github.com/repos/{repository}/actions/workflows/{workflow['id']}"
            and run.get("name") == entry["workflow_name"] and run.get("event") == "push"
            and run.get("head_branch") == "develop" and run.get("run_attempt") == 1
            and run.get("status") == "completed" and run.get("conclusion") == "success"
            and run.get("repository", {}).get("id") == identifier and run.get("repository", {}).get("private") is True
            and run.get("head_repository", {}).get("id") == identifier,
            "promotion-event-native-origin")
    head = sha(run.get("head_sha"))
    require(head == signal.get("head_sha"), "promotion-event-binding")
    branch = api.call(f"repos/{repository}/branches/develop")
    require(branch.get("name") == "develop" and branch.get("protected") is True,
            "promotion-event-protected-develop")
    if branch["commit"]["sha"] != head:
        return None
    # Bind the protected receiver to the exact independently published adapter.
    receiver = api.file(repository, DELIVERY, head).decode("utf-8")
    require(f"uses: {SOURCE}/{DELIVERY}@{defining['workflow_sha']}" in receiver,
            "promotion-event-receiver-source-drift")
    jobs = api.pages(f"repos/{repository}/actions/runs/{locator}/jobs?filter=latest", "jobs")
    audit = [job for job in jobs if job.get("name") == entry["job"]]
    require(len(audit) == 1 and audit[0].get("run_id") == locator and audit[0].get("head_sha") == head
            and audit[0].get("status") == "completed" and audit[0].get("conclusion") == "success",
            "promotion-event-audit-job-required")
    selected_control(api, entry)
    pulls = api.pages(f"repos/{repository}/commits/{head}/pulls")
    merged = [pull for pull in pulls if pull.get("merged_at") and pull.get("merge_commit_sha") == head
              and pull.get("base", {}).get("ref") == "develop"
              and pull.get("base", {}).get("repo", {}).get("id") == identifier]
    require(len(merged) == 1, "promotion-event-unique-ingress-required")
    pull = api.call(f"repos/{repository}/pulls/{merged[0]['number']}")
    require(pull.get("merged") is True and pull.get("state") == "closed" and pull.get("merge_commit_sha") == head
            and pull.get("base", {}).get("ref") == "develop"
            and pull.get("base", {}).get("repo", {}).get("id") == identifier,
            "promotion-event-merged-ingress-required")
    configuration = policy(api, repository, pull["base"]["sha"], entry["source_sha"])
    proof = check_native_control(api, repository, pull, configuration)
    require(proof.get("source_sha") == entry["source_sha"], "promotion-event-ingress-source-drift")
    # Evidence reads can be long. Only the still-current exact event may dispatch.
    require(api.call(f"repos/{repository}/actions/runs/{locator}") == run,
            "promotion-event-producer-drift")
    current = api.call(f"repos/{repository}/branches/develop")
    require(current.get("protected") is True, "promotion-event-protected-develop")
    return head if current["commit"]["sha"] == head else None


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
