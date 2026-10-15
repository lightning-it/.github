#!/usr/bin/env python3
"""Validate the inactive target specification; never authorize live operations."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


class ContractError(ValueError):
    """A safe diagnostic category, without echoing input values."""


SECTIONS = {
    "schema_version", "contract_version", "state", "activation", "central_source",
    "functions", "profiles", "review", "promotion", "authorization", "privacy",
    "evidence", "rollout",
}
EXPECTED_FUNCTIONS = {
    "WF-01": "local-quality",
    "WF-02": "pr-quality-security",
    "WF-03": "current-revision-review",
    "WF-04": "promotion-pr",
    "WF-05": "release-authorization",
    "WF-06": "artifact-assurance-publication",
    "WF-07": "release-audit-archive",
}
PROFILES = {
    "repository_profile", "shared_assets", "generic_managed", "private_infrastructure",
    "ansible_collection", "container_image", "terraform_module", "terraform_policy",
    "helm_chart", "packer_template", "playbook_runbook", "documentation",
}


def require(condition: bool, category: str) -> None:
    if not condition:
        raise ContractError(category)


def exact(data: object, expected: dict, category: str) -> None:
    # JSON booleans must not be admitted as integer approval counts or versions.
    require(isinstance(data, dict) and set(data) == set(expected), category)
    for key, value in expected.items():
        require(type(data[key]) is type(value) and data[key] == value, category)


def validate(data: object) -> None:
    require(isinstance(data, dict) and set(data) == SECTIONS, "contract-shape")
    require(type(data["schema_version"]) is int and data["schema_version"] == 1, "schema-version")
    require(isinstance(data["contract_version"], str) and re.fullmatch(r"[1-9][0-9]*\.[0-9]+\.[0-9]+", data["contract_version"]) is not None, "contract-version")
    require(data["state"] == "defined" and data["activation"] == "inactive", "not-live-authority")
    require(data["central_source"] == "lightning-it/.github", "central-source")
    functions = data["functions"]
    require(isinstance(functions, list) and len(functions) == 7, "function-coverage")
    graph = {}
    for function in functions:
        require(isinstance(function, dict) and set(function) == {"id", "name", "runtime", "depends_on", "failure"}, "function-shape")
        identifier = function["id"]
        require(isinstance(identifier, str) and identifier in EXPECTED_FUNCTIONS and identifier not in graph, "function-identity")
        require(function["name"] == EXPECTED_FUNCTIONS[identifier], "function-purpose")
        require(function["runtime"] == "consumer" and function["failure"] == "block", "function-boundary")
        dependencies = function["depends_on"]
        require(isinstance(dependencies, list) and all(isinstance(item, str) for item in dependencies), "dependency-shape")
        require(len(set(dependencies)) == len(dependencies) and all(item in EXPECTED_FUNCTIONS for item in dependencies), "dependency-target")
        graph[identifier] = dependencies
    require(set(graph) == set(EXPECTED_FUNCTIONS), "function-coverage")
    visited, visiting = set(), set()

    def visit(identifier: str) -> None:
        require(identifier not in visiting, "dependency-cycle")
        if identifier in visited:
            return
        visiting.add(identifier)
        for dependency in graph[identifier]:
            visit(dependency)
        visiting.remove(identifier)
        visited.add(identifier)

    for identifier in graph:
        visit(identifier)
    require(graph["WF-03"] == ["WF-02"] and graph["WF-04"] == ["WF-02", "WF-03"] and graph["WF-05"] == ["WF-04"] and graph["WF-06"] == ["WF-05"] and graph["WF-07"] == ["WF-06"], "required-stage-dependency")
    profiles = data["profiles"]
    require(isinstance(profiles, dict) and set(profiles) == PROFILES, "profile-coverage")
    for name, profile in profiles.items():
        require(isinstance(profile, dict) and set(profile) == {"artifact_publication"}, "profile-shape")
        value = profile["artifact_publication"]
        require(type(value) is bool or value == "repository-policy", "profile-publication")
        if name in {"repository_profile", "shared_assets"}:
            require(value is False, "non-publishing-profile")
    exact(data["review"], {
        "authority": "protected-base", "matrix": "existing-author-and-risk-policy",
        "release_app": "exact-revision-codex", "other_authors": "copilot-when-required-by-policy",
        "unclassified_input": "block", "local_ai_review": False, "dual_review": False,
        "budget_or_provider_failure": "block", "fallback": False, "reuse_stale_review": False,
        "request_identity": ["repository", "pull_request", "base_sha", "head_sha", "policy_sha", "input_digest"],
    }, "review-policy")
    exact(data["promotion"], {
        "source_branch": "develop", "target_branch": "main", "prepare_automatically": True,
        "single_flight": ["repository", "target_branch"], "grant_human_approval": False,
        "head_change_invalidates_checks": True,
    }, "promotion-policy")
    exact(data["authorization"], {
        "classic_pr_approval_count": 0, "normal_environment": "normal-release-promotion-approval",
        "normal_human_approvals": 1, "normal_self_approval": True,
        "duplicate_approval_for_same_operation": False,
        "security_path": "existing-technical-authorization", "security_human_actions": 0,
        "administrative_bypass": False,
    }, "single-person-authorization")
    exact(data["privacy"], {
        "execution": "consumer-visibility", "credential_scope": "explicit-consumer-permissions",
        "inherit_all_secrets": False, "execute_candidate_for_authorization": False,
        "public_content": "pre-publication-validation", "private_tracker_metadata": "prohibited",
    }, "privacy-boundary")
    exact(data["evidence"], {
        "develop": "native-checks-and-reviews", "durable_package": "main-promotion-only",
        "archive": "existing-private-s3-compatible-store", "retention_years": 7,
        "immutable_retention_required": True, "verify_artifact_before_release_acceptance": True,
        "archive_unavailable": "block-release-acceptance",
    }, "evidence-policy")
    exact(data["rollout"], {
        "stages": ["central-source-and-management", "private-distribution", "collection-reference", "additional-profiles", "remaining-fleet"],
        "reference_changes_without_correction": 3, "canary_required": True,
        "live_acceptance_required": True, "poc_until_scope_accepted": True,
        "rollback": "last-accepted-immutable-source",
    }, "rollout-policy")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    try:
        data = json.loads(args.path.read_text(encoding="utf-8"))
        validate(data)
    except (OSError, UnicodeError, json.JSONDecodeError):
        print("Workflow target rejected: unreadable-json")
        return 1
    except ContractError as error:
        print(f"Workflow target rejected: {error}")
        return 1
    print("Workflow target specification valid; activation remains inactive. No live authorization granted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
