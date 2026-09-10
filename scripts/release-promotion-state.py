#!/usr/bin/env python3
"""Transport-free REP-120 C1 operation, inventory, and lease classifier."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


JSON = dict[str, Any]
SHA1 = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
NAME = re.compile(r"^[A-Z][A-Z0-9_]{2,127}$")
POLICY_EPOCH = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
RFC3339 = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")
SAFE_CURSOR = re.compile(r"^[ -~]{1,512}$")
CANONICAL_DIFF_FORMAT = "git-diff-binary-full-index-no-renames-v1"
EXPECTED_REPOSITORY = "lightning-it/.github"
EXPECTED_SOURCE_REF = "refs/heads/develop"
EXPECTED_TARGET_REF = "refs/heads/main"
EXPECTED_WORKFLOW = ".github/workflows/reconcile-develop-to-main.yml"
RESERVATION_CHECK_NAME = "release-reconciliation / reservation"
ATTEMPT2_ACTION_BY_STAGE = {
    "dispatched": "reservation-finalize",
    "pr-created": "downstream-dispatch",
    "reserved": "promotion-pr-create",
}
RUNTIME_INPUT_PATHS = tuple(
    sorted(
        (
            ".github/workflows/reconcile-develop-to-main.yml",
            ".lit/release-reconciliation-policy.json",
            "scripts/release-promotion-history.sh",
            "scripts/release-promotion-inventory.py",
            "scripts/release-promotion-preflight-bind.sh",
            "scripts/release-promotion-preflight-revalidate.sh",
            "scripts/release-promotion-preflight.sh",
            "scripts/release-promotion-state.py",
        )
    )
)


class ContractError(ValueError):
    """A fail-closed contract violation."""


def canonical(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ContractError(reason)


def exact_keys(value: Any, expected: set[str], label: str) -> JSON:
    require(type(value) is dict, f"{label}-not-object")
    require(set(value) == expected, f"{label}-keys")
    return value


def integer(
    value: Any, label: str, minimum: int = 1, maximum: int | None = None
) -> int:
    require(type(value) is int and value >= minimum, label)
    if maximum is not None:
        require(value <= maximum, f"{label}-too-large")
    return value


def string(value: Any, pattern: re.Pattern[str], label: str) -> str:
    require(type(value) is str and pattern.fullmatch(value) is not None, label)
    return value


def timestamp(value: Any, label: str) -> datetime:
    text = string(value, RFC3339, label)
    parsed = datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ")
    return parsed.replace(tzinfo=timezone.utc)


def timestamp_not_future(value: Any, now: datetime, label: str) -> datetime:
    parsed = timestamp(value, label)
    require(parsed <= now, f"{label}-future")
    return parsed


def timestamp_text(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def normalized_string_list(value: Any, label: str) -> list[str]:
    require(type(value) is list, f"{label}-not-list")
    require(all(type(item) is str and item for item in value), f"{label}-item")
    require(len(value) == len(set(value)), f"{label}-duplicate")
    return sorted(value)


def load_json(path_text: str) -> Any:
    path = Path(path_text)
    metadata = path.lstat()
    require(stat.S_ISREG(metadata.st_mode), "input-not-regular")
    require(metadata.st_size <= 8 * 1024 * 1024, "input-too-large")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ContractError("input-not-canonical-json") from error


def normalize_reviewers(value: Any, label: str) -> list[JSON]:
    require(type(value) is list and value, f"{label}-not-list")
    normalized: list[JSON] = []
    identities: set[tuple[str, int]] = set()
    for reviewer_value in value:
        reviewer = exact_keys(reviewer_value, {"id", "type"}, label)
        reviewer_id = integer(reviewer["id"], f"{label}-id")
        require(reviewer["type"] in {"Team", "User"}, f"{label}-type")
        identity = (reviewer["type"], reviewer_id)
        require(identity not in identities, f"{label}-duplicate")
        identities.add(identity)
        normalized.append({"id": reviewer_id, "type": reviewer["type"]})
    return sorted(normalized, key=lambda item: (item["type"], item["id"]))


def validate_policy(policy: Any) -> JSON:
    require(type(policy) is dict, "policy-not-object")
    if policy.get("lifecycle") == "provisional-pre-d1-pre-s0":
        exact_keys(
            policy,
            {"issue", "lifecycle", "mutation_authority", "reason", "schema_version"},
            "provisional-policy",
        )
        require(policy["schema_version"] == 1, "policy-schema")
        require(policy["issue"] == 564, "policy-issue")
        require(policy["mutation_authority"] is False, "provisional-authority")
        require(type(policy["reason"]) is str and policy["reason"], "policy-reason")
        raise ContractError("policy-not-materialized")

    policy = exact_keys(
        policy,
        {
            "environment",
            "issue",
            "lease",
            "lifecycle",
            "operation_class",
            "policy_epoch",
            "repository",
            "repository_id",
            "review",
            "schema_version",
            "source_ref",
            "target_ref",
            "workflow_id",
            "workflow_path",
        },
        "policy",
    )
    require(policy["schema_version"] == 2, "policy-schema")
    require(policy["issue"] == 564, "policy-issue")
    require(policy["lifecycle"] == "default-off", "policy-lifecycle")
    require(policy["repository"] == EXPECTED_REPOSITORY, "policy-repository")
    integer(policy["repository_id"], "policy-repository-id")
    integer(policy["workflow_id"], "policy-workflow-id")
    require(policy["source_ref"] == EXPECTED_SOURCE_REF, "policy-source-ref")
    require(policy["target_ref"] == EXPECTED_TARGET_REF, "policy-target-ref")
    require(
        policy["operation_class"] == "develop-to-main-promotion",
        "policy-operation-class",
    )
    string(policy["policy_epoch"], POLICY_EPOCH, "policy-epoch")
    require(policy["workflow_path"] == EXPECTED_WORKFLOW, "policy-workflow")

    environment = exact_keys(
        policy["environment"],
        {
            "client_id",
            "client_id_variable_name",
            "deployment_branch_policy",
            "enablement_variable_name",
            "name",
            "prevent_self_review",
            "reviewers",
            "secret_name",
        },
        "policy-environment",
    )
    require(environment["name"] == "release-reconciliation-v1", "environment-name")
    require(environment["prevent_self_review"] is True, "prevent-self-review")
    require(type(environment["client_id"]) is str and environment["client_id"], "client-id")
    string(environment["client_id_variable_name"], NAME, "client-id-variable")
    string(environment["enablement_variable_name"], NAME, "enablement-variable")
    string(environment["secret_name"], NAME, "environment-secret")
    branch_policy = exact_keys(
        environment["deployment_branch_policy"],
        {"custom_branch_policies", "protected_branches"},
        "policy-branch-policy",
    )
    require(branch_policy["protected_branches"] is True, "protected-branches")
    require(branch_policy["custom_branch_policies"] is False, "custom-branches")
    reviewers = normalize_reviewers(environment["reviewers"], "policy-reviewer")
    require(reviewers == environment["reviewers"], "policy-reviewer-order")

    lease = exact_keys(
        policy["lease"],
        {
            "max_inventory_bytes",
            "max_inventory_elapsed_ms",
            "max_inventory_pages",
            "max_inventory_records",
            "ttl_seconds",
        },
        "policy-lease",
    )
    integer(lease["ttl_seconds"], "lease-ttl", maximum=604800)
    integer(
        lease["max_inventory_records"],
        "inventory-record-limit",
        maximum=10000,
    )
    integer(
        lease["max_inventory_bytes"],
        "inventory-byte-limit",
        maximum=64 * 1024 * 1024,
    )
    integer(lease["max_inventory_pages"], "inventory-page-limit", maximum=1000)
    integer(
        lease["max_inventory_elapsed_ms"],
        "inventory-elapsed-limit",
        maximum=300000,
    )

    review = exact_keys(
        policy["review"],
        {"canonical_diff_format", "maximum_bytes", "minimum_bytes"},
        "policy-review",
    )
    require(review["canonical_diff_format"] == CANONICAL_DIFF_FORMAT, "review-format")
    require(review["minimum_bytes"] == 1, "review-minimum")
    require(review["maximum_bytes"] == 199999, "review-maximum")
    require(b"TBD" not in canonical(policy), "policy-tbd")
    return policy


def normalize_variable(
    value: Any, expected_scope: str, label: str
) -> JSON:
    record = exact_keys(value, {"present", "scope", "value"}, label)
    require(record["scope"] == expected_scope, f"{label}-scope")
    require(type(record["present"]) is bool, f"{label}-presence")
    if record["present"]:
        require(type(record["value"]) is str, f"{label}-value")
    else:
        require(record["value"] is None, f"{label}-absent-value")
    return {
        "present": record["present"],
        "scope": expected_scope,
        "value": record["value"],
    }


def normalize_configuration(
    policy: JSON, configuration_value: Any
) -> tuple[str, str, JSON]:
    configuration = exact_keys(
        configuration_value,
        {
            "environment",
            "environment_secret_names",
            "organization_enablement",
            "organization_secret_names",
            "repository_client_id",
            "repository_enablement",
            "repository_secret_names",
        },
        "configuration",
    )
    expected = policy["environment"]
    repository_enablement = normalize_variable(
        configuration["repository_enablement"],
        "repository",
        "repository-enablement",
    )
    organization_enablement = normalize_variable(
        configuration["organization_enablement"],
        "organization",
        "organization-enablement",
    )
    if repository_enablement["present"]:
        require(
            repository_enablement["value"] in {"false", "true"},
            "repository-variable-malformed",
        )
    if organization_enablement["present"]:
        require(
            organization_enablement["value"] in {"false", "true"},
            "organization-variable-malformed",
        )
    enablement_snapshot = {
        "organization_enablement": organization_enablement,
        "repository_enablement": repository_enablement,
    }
    if not repository_enablement["present"]:
        return "noop", "repository-variable-absent", enablement_snapshot
    if repository_enablement["value"] == "false":
        return "noop", "repository-variable-false", enablement_snapshot

    client_id = normalize_variable(
        configuration["repository_client_id"],
        "repository",
        "repository-client-id",
    )
    require(client_id["present"] is True, "client-id-absent")
    require(client_id["value"] == expected["client_id"], "client-id-drift")

    actual_environment = exact_keys(
        configuration["environment"],
        {"deployment_branch_policy", "name", "prevent_self_review", "reviewers"},
        "environment",
    )
    branch_policy = exact_keys(
        actual_environment["deployment_branch_policy"],
        {"custom_branch_policies", "protected_branches"},
        "environment-branch-policy",
    )
    reviewers = normalize_reviewers(actual_environment["reviewers"], "environment-reviewer")
    normalized_environment = {
        "deployment_branch_policy": {
            "custom_branch_policies": branch_policy["custom_branch_policies"],
            "protected_branches": branch_policy["protected_branches"],
        },
        "name": actual_environment["name"],
        "prevent_self_review": actual_environment["prevent_self_review"],
        "reviewers": reviewers,
    }
    comparable_expected = {
        "deployment_branch_policy": expected["deployment_branch_policy"],
        "name": expected["name"],
        "prevent_self_review": expected["prevent_self_review"],
        "reviewers": expected["reviewers"],
    }
    require(normalized_environment == comparable_expected, "environment-drift")

    environment_secrets = normalized_string_list(
        configuration["environment_secret_names"], "environment-secrets"
    )
    repository_secrets = normalized_string_list(
        configuration["repository_secret_names"], "repository-secrets"
    )
    organization_secrets = normalized_string_list(
        configuration["organization_secret_names"], "organization-secrets"
    )
    secret_name = expected["secret_name"]
    require(secret_name in environment_secrets, "environment-secret-absent")
    require(secret_name not in repository_secrets, "repository-secret-collision")
    require(secret_name not in organization_secrets, "organization-secret-collision")

    normalized = {
        "environment": normalized_environment,
        "environment_secret_names": environment_secrets,
        "organization_enablement": organization_enablement,
        "organization_secret_names": organization_secrets,
        "repository_client_id": client_id,
        "repository_enablement": repository_enablement,
        "repository_secret_names": repository_secrets,
    }
    return "mutate", "configuration-exact", normalized


def normalize_discovery(
    policy: JSON, event: JSON, value: Any
) -> JSON:
    discovery = exact_keys(
        value,
        {"has_content_delta", "merge_base_sha", "source_sha", "target_base_sha"},
        "discovery",
    )
    require(type(discovery["has_content_delta"]) is bool, "discovery-delta-type")
    for field in ("merge_base_sha", "source_sha", "target_base_sha"):
        string(discovery[field], SHA1, f"discovery-{field}")
    require(discovery["source_sha"] == event["run_sha"], "discovery-source-drift")
    return dict(discovery)


def normalize_runtime_inputs(value: Any) -> list[dict[str, str]]:
    require(type(value) is list, "runtime-inputs-not-list")
    normalized: list[dict[str, str]] = []
    paths: set[str] = set()
    for input_value in value:
        runtime_input = exact_keys(input_value, {"blob", "mode", "path"}, "runtime-input")
        require(type(runtime_input["path"]) is str, "runtime-input-path")
        require(runtime_input["path"] not in paths, "runtime-input-path-duplicate")
        paths.add(runtime_input["path"])
        string(runtime_input["blob"], SHA1, "runtime-input-blob")
        require(runtime_input["mode"] == "100644", "runtime-input-mode")
        normalized.append(
            {
                "blob": runtime_input["blob"],
                "mode": runtime_input["mode"],
                "path": runtime_input["path"],
            }
        )
    require(paths == set(RUNTIME_INPUT_PATHS), "runtime-input-path-set")
    return sorted(normalized, key=lambda item: item["path"])


def operation_record(policy: JSON, snapshot: JSON) -> JSON:
    git = exact_keys(
        snapshot["git"],
        {
            "candidate_sha",
            "integration_tree",
            "merge_base_sha",
            "patch_bytes",
            "patch_format",
            "patch_sha256",
            "projection_sha256",
            "runtime_inputs",
            "source_sha",
            "target_base_sha",
            "unsafe_delta",
        },
        "git",
    )
    for field in (
        "candidate_sha",
        "integration_tree",
        "merge_base_sha",
        "source_sha",
        "target_base_sha",
    ):
        string(git[field], SHA1, f"git-{field}")
    string(git["patch_sha256"], SHA256, "patch-digest")
    string(git["projection_sha256"], SHA256, "projection-digest")
    require(git["source_sha"] == snapshot["event"]["run_sha"], "source-run-drift")
    discovery = snapshot["discovery"]
    require(git["source_sha"] == discovery["source_sha"], "review-source-drift")
    require(
        git["merge_base_sha"] == discovery["merge_base_sha"],
        "review-merge-base-drift",
    )
    require(
        git["target_base_sha"] == discovery["target_base_sha"],
        "review-target-base-drift",
    )
    require(git["patch_format"] == CANONICAL_DIFF_FORMAT, "patch-format")
    require(type(git["unsafe_delta"]) is bool, "unsafe-delta-type")
    require(git["unsafe_delta"] is False, "unsafe-delta")
    patch_bytes = integer(git["patch_bytes"], "patch-empty")
    require(patch_bytes <= policy["review"]["maximum_bytes"], "patch-oversized")
    runtime_inputs = normalize_runtime_inputs(git["runtime_inputs"])
    return {
        "candidate_sha": git["candidate_sha"],
        "integration_tree": git["integration_tree"],
        "merge_base_sha": git["merge_base_sha"],
        "operation_class": policy["operation_class"],
        "patch_bytes": patch_bytes,
        "patch_format": git["patch_format"],
        "patch_sha256": git["patch_sha256"],
        "policy_epoch": policy["policy_epoch"],
        "projection_sha256": git["projection_sha256"],
        "repository_id": policy["repository_id"],
        "runtime_inputs": runtime_inputs,
        "source_ref": policy["source_ref"],
        "source_sha": git["source_sha"],
        "target_base_sha": git["target_base_sha"],
        "target_ref": policy["target_ref"],
        "workflow_id": policy["workflow_id"],
        "workflow_path": policy["workflow_path"],
    }


def normalize_cursor(value: Any, label: str) -> str | None:
    if value is None:
        return None
    return string(value, SAFE_CURSOR, label)


def normalize_inventory(
    value: Any,
    label: str,
    policy: JSON,
    normalize_source: Any,
    normalize_record: Any,
) -> tuple[list[JSON], str, JSON]:
    inventory = exact_keys(
        value,
        {
            "collector",
            "complete",
            "elapsed_ms",
            "page_count",
            "pages",
            "read_count",
            "record_count",
            "response_bytes",
            "semantic_sha256",
            "source",
        },
        label,
    )
    require(
        inventory["collector"] == "release-promotion-inventory-v1",
        f"{label}-collector",
    )
    require(inventory["complete"] is True, f"{label}-incomplete")
    require(inventory["read_count"] == 2, f"{label}-stable-read-count")
    string(inventory["semantic_sha256"], SHA256, f"{label}-semantic-digest")
    bounds = policy["lease"]
    elapsed_ms = integer(inventory["elapsed_ms"], f"{label}-elapsed", minimum=0)
    require(
        elapsed_ms <= bounds["max_inventory_elapsed_ms"],
        f"{label}-elapsed-limit",
    )
    page_count = integer(inventory["page_count"], f"{label}-page-count", minimum=0)
    require(page_count <= bounds["max_inventory_pages"], f"{label}-page-limit")
    record_count = integer(
        inventory["record_count"], f"{label}-record-count", minimum=0
    )
    require(record_count <= bounds["max_inventory_records"], f"{label}-record-limit")
    response_bytes = integer(
        inventory["response_bytes"], f"{label}-response-bytes", minimum=0
    )
    require(response_bytes <= bounds["max_inventory_bytes"], f"{label}-byte-limit")
    source = normalize_source(inventory["source"])
    pages_value = inventory["pages"]
    require(type(pages_value) is list, f"{label}-pages-not-list")
    require(len(pages_value) == page_count, f"{label}-page-count-mismatch")

    pages: list[JSON] = []
    for page_value in pages_value:
        page = exact_keys(
            page_value,
            {
                "cursor",
                "next_cursor",
                "number",
                "raw_sha256",
                "records",
                "response_bytes",
            },
            f"{label}-page",
        )
        number = integer(page["number"], f"{label}-page-number")
        records = page["records"]
        require(type(records) is list, f"{label}-page-records")
        pages.append(
            {
                "cursor": normalize_cursor(page["cursor"], f"{label}-cursor"),
                "next_cursor": normalize_cursor(
                    page["next_cursor"], f"{label}-next-cursor"
                ),
                "number": number,
                "raw_sha256": string(
                    page["raw_sha256"], SHA256, f"{label}-page-raw-digest"
                ),
                "records": records,
                "response_bytes": integer(
                    page["response_bytes"],
                    f"{label}-page-response-bytes",
                    minimum=0,
                ),
            }
        )
    pages.sort(key=lambda item: item["number"])
    require(
        [page["number"] for page in pages] == list(range(1, page_count + 1)),
        f"{label}-page-sequence",
    )
    if pages:
        require(pages[0]["cursor"] is None, f"{label}-first-cursor")
        require(pages[-1]["next_cursor"] is None, f"{label}-last-cursor")
        for left, right in zip(pages, pages[1:]):
            require(left["next_cursor"] is not None, f"{label}-cursor-truncated")
            require(
                left["next_cursor"] == right["cursor"], f"{label}-cursor-chain"
            )
        cursors = [page["cursor"] for page in pages[1:]]
        require(len(cursors) == len(set(cursors)), f"{label}-cursor-duplicate")
    require(
        sum(page["response_bytes"] for page in pages) == response_bytes,
        f"{label}-response-byte-mismatch",
    )
    require(
        sum(len(page["records"]) for page in pages) == record_count,
        f"{label}-record-count-mismatch",
    )

    normalized_records: list[JSON] = []
    identities: set[Any] = set()
    for page in pages:
        for record_value in page["records"]:
            identity, record = normalize_record(record_value)
            require(identity not in identities, f"{label}-record-duplicate")
            identities.add(identity)
            normalized_records.append(record)
    normalized_records.sort(key=canonical)
    normalized_inventory = {"records": normalized_records, "source": source}
    semantic_sha256 = digest(normalized_inventory)
    require(
        inventory["semantic_sha256"] == semantic_sha256,
        f"{label}-semantic-mismatch",
    )
    return normalized_records, semantic_sha256, normalized_inventory


def history_source(policy: JSON, value: Any) -> JSON:
    source = exact_keys(value, {"endpoint", "repository_id", "state"}, "history-source")
    require(source["endpoint"] == f"repos/{EXPECTED_REPOSITORY}/pulls", "history-endpoint")
    require(source["repository_id"] == policy["repository_id"], "history-repository")
    require(source["state"] == "all", "history-state-filter")
    return dict(source)


def history_record(
    policy: JSON, now: datetime, value: Any
) -> tuple[int, JSON]:
    record = exact_keys(
        value,
        {
            "base_ref",
            "base_sha",
            "body_sha256",
            "created_at",
            "dispatch_state",
            "draft",
            "head_ref",
            "head_sha",
            "merged_at",
            "operation_key",
            "pr_number",
            "repository_id",
            "run_attempt",
            "run_id",
            "state",
        },
        "history-record",
    )
    integer(record["pr_number"], "history-pr-number")
    integer(record["run_id"], "history-run-id")
    integer(record["run_attempt"], "history-run-attempt")
    require(record["repository_id"] == policy["repository_id"], "history-record-repository")
    require(record["base_ref"] == policy["target_ref"], "history-base-ref")
    require(record["head_ref"] == policy["source_ref"], "history-head-ref")
    string(record["base_sha"], SHA1, "history-base-sha")
    string(record["head_sha"], SHA1, "history-head-sha")
    string(record["body_sha256"], SHA256, "history-body-digest")
    string(record["operation_key"], SHA256, "history-operation-key")
    timestamp_not_future(record["created_at"], now, "history-created-at")
    require(type(record["draft"]) is bool, "history-draft")
    require(record["state"] in {"closed", "open"}, "history-pr-state")
    require(
        record["dispatch_state"] in {"failed", "pending", "succeeded"},
        "history-dispatch-state",
    )
    if record["merged_at"] is not None:
        timestamp_not_future(record["merged_at"], now, "history-merged-at")
    normalized = dict(record)
    return record["pr_number"], normalized


def classify_history(
    records: list[JSON],
    operation: JSON,
    operation_key: str,
    event: JSON,
) -> tuple[str, int | None, JSON | None]:
    matching = [record for record in records if record["operation_key"] == operation_key]
    require(len(matching) <= 1, "history-operation-duplicate")
    if not matching:
        return "mutate", None, None
    record = matching[0]
    require(record["head_sha"] == operation["source_sha"], "history-head-drift")
    require(record["run_id"] == event["run_id"], "history-owner-run")
    require(record["run_attempt"] == 1, "history-owner-attempt")
    if record["state"] == "open":
        require(record["merged_at"] is None, "history-open-merged")
        require(record["draft"] is False, "history-open-draft")
        require(
            record["base_sha"] == operation["target_base_sha"], "history-base-drift"
        )
        if event["run_attempt"] == 2 and record["dispatch_state"] in {
            "pending",
            "succeeded",
        }:
            return "recovery-candidate", record["pr_number"], dict(record)
        if record["dispatch_state"] == "pending":
            return "pending", record["pr_number"], dict(record)
        require(record["dispatch_state"] == "succeeded", "history-open-dispatch")
        return "active", record["pr_number"], dict(record)
    require(record["state"] == "closed", "history-unhandled")
    return "consumed", record["pr_number"], dict(record)


def history_pr_state(record: JSON | None) -> str:
    if record is None:
        return "absent"
    if record["state"] == "open":
        return "open"
    require(record["state"] == "closed", "history-unhandled")
    return "merged" if record["merged_at"] is not None else "closed"


def validate_reservation_history(
    reservation: JSON,
    matching_history: JSON | None,
) -> None:
    state = reservation["materialized_state"]
    expected_pr_state = history_pr_state(matching_history)
    require(
        state["pr_state"] == expected_pr_state,
        "reservation-history-pr-state-drift",
    )

    if matching_history is None:
        require(
            state["downstream_state"] == "not-dispatched",
            "reservation-history-dispatch-drift",
        )
        require(
            state["stage"] == "reserved"
            or (
                state["state"] == "completed"
                and state["stage"] == "finalized"
                and state["terminal_disposition"] == "noop"
            ),
            "reservation-history-required",
        )
        return

    require(state["stage"] != "reserved", "reservation-history-stage-drift")
    history_dispatch = matching_history["dispatch_state"]

    if state["state"] in {"cancelled", "completed"}:
        if state["stage"] == "pr-created":
            require(
                history_dispatch == "pending"
                and state["downstream_state"] == "not-dispatched",
                "reservation-history-dispatch-drift",
            )
        else:
            require(
                state["stage"] in {"dispatched", "finalized"}
                and state["downstream_state"] == history_dispatch,
                "reservation-history-dispatch-drift",
            )
        expected_terminal = (
            "active" if expected_pr_state == "open" else "consumed"
        )
        require(
            state["terminal_disposition"] == expected_terminal,
            "reservation-history-terminal-drift",
        )
        return

    allowed_cross_states = {
        "pr-created": {("not-dispatched", "pending")},
        "dispatched": {
            ("pending", "pending"),
            ("pending", "succeeded"),
            ("succeeded", "succeeded"),
            ("unknown", "pending"),
            ("unknown", "succeeded"),
        },
    }
    require(
        state["stage"] in allowed_cross_states,
        "reservation-history-stage-drift",
    )
    require(
        (state["downstream_state"], history_dispatch)
        in allowed_cross_states[state["stage"]],
        "reservation-history-dispatch-drift",
    )


def run_source(policy: JSON, value: Any) -> JSON:
    source = exact_keys(
        value,
        {"endpoint", "event", "ref", "repository_id", "workflow_id", "workflow_path"},
        "run-source",
    )
    require(source["endpoint"] == "actions/workflow-runs", "run-endpoint")
    require(source["repository_id"] == policy["repository_id"], "run-source-repository")
    require(source["workflow_id"] == policy["workflow_id"], "run-source-workflow-id")
    require(source["workflow_path"] == policy["workflow_path"], "run-source-workflow")
    require(source["event"] == "push", "run-source-event")
    require(source["ref"] == policy["source_ref"], "run-source-ref")
    return dict(source)


def run_record(
    policy: JSON, now: datetime, value: Any
) -> tuple[tuple[int, int], JSON]:
    record = exact_keys(
        value,
        {
            "attempt",
            "conclusion",
            "created_at",
            "event",
            "head_sha",
            "operation_key",
            "ref",
            "repository_id",
            "run_id",
            "status",
            "workflow_id",
            "workflow_path",
        },
        "run-record",
    )
    run_id = integer(record["run_id"], "run-id")
    attempt = integer(record["attempt"], "run-attempt", maximum=2)
    timestamp_not_future(record["created_at"], now, "run-created-at")
    string(record["head_sha"], SHA1, "run-head")
    string(record["operation_key"], SHA256, "run-operation-key")
    require(record["repository_id"] == policy["repository_id"], "run-repository")
    require(record["workflow_id"] == policy["workflow_id"], "run-workflow-id")
    require(record["workflow_path"] == policy["workflow_path"], "run-workflow")
    require(record["event"] == "push", "run-event")
    require(record["ref"] == policy["source_ref"], "run-ref")
    require(
        record["status"]
        in {"completed", "in_progress", "pending", "queued", "requested", "waiting"},
        "run-status",
    )
    if record["status"] == "completed":
        require(
            record["conclusion"]
            in {
                "action_required",
                "cancelled",
                "failure",
                "skipped",
                "stale",
                "success",
                "timed_out",
            },
            "run-conclusion",
        )
    else:
        require(record["conclusion"] is None, "nonterminal-run-conclusion")
    return (run_id, attempt), dict(record)


def source_identity(policy: JSON, event: JSON) -> JSON:
    return {
        "head_sha": event["run_sha"],
        "ref": policy["source_ref"],
        "repository_id": policy["repository_id"],
        "workflow_id": policy["workflow_id"],
        "workflow_path": policy["workflow_path"],
    }


def reservation_external_id(operation_key: str) -> str:
    string(operation_key, SHA256, "reservation-operation-key")
    return f"lit-release-reconciliation-v1:{operation_key}"


def reservation_source(
    policy: JSON, event: JSON, value: Any
) -> JSON:
    source = exact_keys(
        value,
        {"check_name", "endpoint", "head_sha", "repository_id"},
        "reservation-source",
    )
    require(source["check_name"] == RESERVATION_CHECK_NAME, "reservation-check-name")
    require(source["endpoint"] == "checks/runs", "reservation-endpoint")
    require(source["head_sha"] == event["run_sha"], "reservation-source-head")
    require(source["repository_id"] == policy["repository_id"], "reservation-source-repository")
    return dict(source)


def reservation_record(
    policy: JSON, event: JSON, now: datetime, value: Any
) -> tuple[int, JSON]:
    record = exact_keys(
        value,
        {
            "check_run_id",
            "external_id",
            "materialized_state",
            "readback_sha256",
        },
        "reservation-record",
    )
    check_run_id = integer(record["check_run_id"], "reservation-check-run-id")
    state = exact_keys(
        record["materialized_state"],
        {
            "created_at",
            "downstream_state",
            "last_intent_sha256",
            "lease_expires_at",
            "operation_key",
            "owner_run_attempt",
            "owner_run_created_at",
            "owner_run_id",
            "pr_state",
            "source_identity",
            "stage",
            "state",
            "terminal_disposition",
        },
        "reservation-state",
    )
    string(state["operation_key"], SHA256, "reservation-key")
    require(
        record["external_id"] == reservation_external_id(state["operation_key"]),
        "reservation-external-id",
    )
    string(record["readback_sha256"], SHA256, "reservation-readback-digest")
    readback_projection = {
        "check_run_id": check_run_id,
        "external_id": record["external_id"],
        "materialized_state": state,
    }
    require(
        record["readback_sha256"] == digest(readback_projection),
        "reservation-readback-mismatch",
    )
    owner_run_id = integer(state["owner_run_id"], "reservation-owner")
    owner_attempt = integer(
        state["owner_run_attempt"], "reservation-owner-attempt", maximum=2
    )
    owner_created = timestamp_not_future(
        state["owner_run_created_at"], now, "reservation-owner-created-at"
    )
    created = timestamp_not_future(
        state["created_at"], now, "reservation-created-at"
    )
    require(owner_created <= created, "reservation-created-before-owner")
    expiry = timestamp(state["lease_expires_at"], "reservation-expiry")
    require(
        expiry
        == owner_created + timedelta(seconds=policy["lease"]["ttl_seconds"]),
        "reservation-expiry-drift",
    )
    require(created < expiry, "reservation-created-after-expiry")
    expected_source = source_identity(policy, event)
    actual_source = exact_keys(
        state["source_identity"],
        {"head_sha", "ref", "repository_id", "workflow_id", "workflow_path"},
        "reservation-source-identity",
    )
    require(actual_source == expected_source, "reservation-source-identity-drift")
    require(
        state["stage"] in {"dispatched", "finalized", "pr-created", "reserved"},
        "reservation-stage",
    )
    require(
        state["pr_state"] in {"absent", "closed", "merged", "open"},
        "reservation-pr-state",
    )
    require(
        state["downstream_state"]
        in {"failed", "not-dispatched", "pending", "succeeded", "unknown"},
        "reservation-downstream-state",
    )
    if state["stage"] == "reserved":
        require(state["pr_state"] == "absent", "reserved-pr-state")
        require(
            state["downstream_state"] == "not-dispatched",
            "reserved-downstream-state",
        )
        string(state["last_intent_sha256"], SHA256, "reserved-last-intent")
    elif state["stage"] == "pr-created":
        require(state["pr_state"] in {"closed", "open"}, "pr-created-pr-state")
        require(
            state["downstream_state"] == "not-dispatched",
            "pr-created-downstream-state",
        )
        string(state["last_intent_sha256"], SHA256, "pr-created-last-intent")
    elif state["stage"] == "dispatched":
        require(state["pr_state"] in {"closed", "open"}, "dispatched-pr-state")
        require(
            state["downstream_state"]
            in {"failed", "pending", "succeeded", "unknown"},
            "dispatched-downstream-state",
        )
        string(state["last_intent_sha256"], SHA256, "dispatched-last-intent")
    else:
        string(state["last_intent_sha256"], SHA256, "finalized-last-intent")
    require(
        state["state"] in {"cancelled", "completed", "leased", "orphaned"},
        "reservation-state-value",
    )
    terminal = state["terminal_disposition"]
    if state["state"] == "completed":
        require(state["stage"] == "finalized", "completed-stage")
        require(terminal in {"active", "consumed", "noop"}, "terminal-disposition")
        completed_states = {
            "active": {("open", "pending"), ("open", "succeeded")},
            "consumed": {
                ("closed", "failed"),
                ("closed", "succeeded"),
                ("merged", "succeeded"),
            },
            "noop": {("absent", "not-dispatched")},
        }
        require(
            (state["pr_state"], state["downstream_state"])
            in completed_states[terminal],
            "completed-terminal-state",
        )
    elif state["state"] == "cancelled":
        require(state["stage"] != "finalized", "cancelled-stage")
        derived_terminal = "active" if state["pr_state"] == "open" else "consumed"
        require(terminal == derived_terminal, "cancelled-disposition")
    else:
        require(terminal is None, "nonterminal-disposition")
        if state["state"] == "orphaned":
            require(state["stage"] in ATTEMPT2_ACTION_BY_STAGE, "orphan-stage")
    normalized = {
        "check_run_id": check_run_id,
        "external_id": record["external_id"],
        "materialized_state": {
            **dict(state),
            "source_identity": dict(actual_source),
        },
        "readback_sha256": record["readback_sha256"],
    }
    return check_run_id, normalized


def attempt_authorization_id(core: JSON) -> str:
    return digest(
        {
            "core": core,
            "kind": "release-reconciliation-attempt-2-authority",
            "schema_version": 1,
        }
    )


def validate_attempt_authorization(
    value: Any,
    policy: JSON,
    event: JSON,
    operation_key: str,
    orphan: JSON,
    predecessor: JSON,
    now: datetime,
) -> JSON:
    authorization = exact_keys(
        value,
        {
            "authorization_id",
            "check_run_id",
            "core",
            "external_id",
            "issuer",
            "readback_sha256",
            "used",
        },
        "attempt-authorization",
    )
    core = exact_keys(
        authorization["core"],
        {
            "allowed_action",
            "attempt",
            "created_at",
            "expires_at",
            "operation_key",
            "prior_intent_sha256",
            "prior_attempt",
            "prior_run_sha256",
            "run_id",
            "source_identity",
            "state_digest",
        },
        "attempt-authorization-core",
    )
    string(authorization["authorization_id"], SHA256, "attempt-authorization-id")
    require(
        authorization["authorization_id"] == attempt_authorization_id(core),
        "attempt-authorization-digest",
    )
    check_run_id = integer(
        authorization["check_run_id"], "attempt-authorization-check-run-id"
    )
    expected_external_id = (
        "lit-release-attempt-2-v1:" + authorization["authorization_id"]
    )
    require(
        authorization["external_id"] == expected_external_id,
        "attempt-authorization-external-id",
    )
    require(
        authorization["issuer"]
        == "release-reconciliation-attempt-authority-v1",
        "attempt-authorization-issuer",
    )
    require(type(authorization["used"]) is bool, "attempt-authorization-used")
    string(
        authorization["readback_sha256"],
        SHA256,
        "attempt-authorization-readback-digest",
    )
    readback_projection = {
        "authorization_id": authorization["authorization_id"],
        "check_run_id": check_run_id,
        "core": core,
        "external_id": authorization["external_id"],
        "issuer": authorization["issuer"],
        "used": authorization["used"],
    }
    require(
        authorization["readback_sha256"] == digest(readback_projection),
        "attempt-authorization-readback-mismatch",
    )
    require(core["attempt"] == 2, "attempt-authorization-attempt")
    require(core["prior_attempt"] == 1, "attempt-authorization-prior-attempt")
    require(
        core["prior_run_sha256"] == digest(predecessor),
        "attempt-authorization-prior-run",
    )
    require(core["run_id"] == event["run_id"], "attempt-authorization-run")
    require(core["operation_key"] == operation_key, "attempt-authorization-operation")
    require(
        core["state_digest"] == orphan["readback_sha256"],
        "attempt-authorization-state",
    )
    orphan_state = orphan["materialized_state"]
    require(
        core["allowed_action"] == ATTEMPT2_ACTION_BY_STAGE[orphan_state["stage"]],
        "attempt-authorization-action",
    )
    require(
        core["prior_intent_sha256"] == orphan_state["last_intent_sha256"],
        "attempt-authorization-prior-intent",
    )
    string(core["prior_intent_sha256"], SHA256, "attempt-authorization-prior-intent")
    created = timestamp_not_future(
        core["created_at"], now, "attempt-authorization-created-at"
    )
    expires = timestamp(core["expires_at"], "attempt-authorization-expires-at")
    require(created < expires, "attempt-authorization-window")
    require(now < expires, "attempt-authorization-expired")
    expected_source = source_identity(policy, event)
    actual_source = exact_keys(
        core["source_identity"],
        {"head_sha", "ref", "repository_id", "workflow_id", "workflow_path"},
        "attempt-authorization-source",
    )
    require(actual_source == expected_source, "attempt-authorization-source-drift")
    return {
        "authorization_id": authorization["authorization_id"],
        "check_run_id": check_run_id,
        "core": {**dict(core), "source_identity": dict(actual_source)},
        "external_id": authorization["external_id"],
        "issuer": authorization["issuer"],
        "readback_sha256": authorization["readback_sha256"],
        "used": authorization["used"],
    }


def lease_output(
    policy: JSON,
    event: JSON,
    current: JSON,
    operation_key: str,
    snapshot_now: str,
    reservation: JSON | None,
) -> JSON:
    owner_created = timestamp(current["created_at"], "current-created-at")
    expires = owner_created + timedelta(seconds=policy["lease"]["ttl_seconds"])
    if reservation is None:
        check_run_id = None
        created_at = snapshot_now
        external_id = reservation_external_id(operation_key)
    else:
        state = reservation["materialized_state"]
        check_run_id = reservation["check_run_id"]
        created_at = state["created_at"]
        external_id = reservation["external_id"]
    return {
        "check_run_id": check_run_id,
        "created_at": created_at,
        "expires_at": timestamp_text(expires),
        "external_id": external_id,
        "operation_key": operation_key,
        "owner_run_attempt": event["run_attempt"],
        "owner_run_created_at": current["created_at"],
        "owner_run_id": event["run_id"],
        "source_identity": source_identity(policy, event),
    }


def terminal_reservation_result(
    reservation: JSON,
    operation_key: str,
    reason: str,
) -> JSON:
    state = reservation["materialized_state"]
    return {
        "check_run_id": reservation["check_run_id"],
        "disposition": state["terminal_disposition"],
        "external_id": reservation["external_id"],
        "operation_key": operation_key,
        "reason": reason,
        "reservation_readback_sha256": reservation["readback_sha256"],
        "schema_version": 2,
    }


def classify(policy_value: Any, snapshot_value: Any) -> JSON:
    policy = validate_policy(policy_value)
    snapshot = exact_keys(
        snapshot_value,
        {
            "attempt_authorization",
            "configuration",
            "discovery",
            "event",
            "git",
            "history",
            "now",
            "repository",
            "reservations",
            "runs",
            "schema_version",
        },
        "snapshot",
    )
    require(snapshot["schema_version"] == 2, "snapshot-schema")
    now = timestamp(snapshot["now"], "snapshot-now")
    repository = exact_keys(snapshot["repository"], {"full_name", "id"}, "repository")
    require(repository["full_name"] == policy["repository"], "repository-name")
    require(repository["id"] == policy["repository_id"], "repository-id")
    event = exact_keys(
        snapshot["event"],
        {
            "name",
            "ref",
            "ref_protected",
            "run_attempt",
            "run_id",
            "run_sha",
            "workflow_id",
            "workflow_path",
        },
        "event",
    )
    require(event["name"] == "push", "event-name")
    require(event["ref"] == policy["source_ref"], "event-ref")
    require(event["ref_protected"] is True, "event-ref-unprotected")
    require(event["run_attempt"] in {1, 2}, "event-attempt")
    integer(event["run_id"], "event-run-id")
    string(event["run_sha"], SHA1, "event-run-sha")
    require(event["workflow_id"] == policy["workflow_id"], "event-workflow-id")
    require(event["workflow_path"] == policy["workflow_path"], "event-workflow")
    discovery = normalize_discovery(policy, event, snapshot["discovery"])
    snapshot["discovery"] = discovery

    if discovery["has_content_delta"] is False:
        require(snapshot["git"] is None, "no-delta-review-present")
        require(snapshot["history"] is None, "no-delta-history-present")
        require(snapshot["runs"] is None, "no-delta-runs-present")
        require(snapshot["reservations"] is None, "no-delta-reservations-present")
        require(
            snapshot["attempt_authorization"] is None,
            "no-delta-attempt-authorization",
        )
        return {
            "discovery_sha256": digest(discovery),
            "disposition": "noop",
            "reason": "no-content-delta",
            "schema_version": 2,
        }

    configuration_disposition, configuration_reason, configuration = (
        normalize_configuration(policy, snapshot["configuration"])
    )
    configuration_sha256 = digest(configuration)
    if configuration_disposition == "noop":
        return {
            "configuration_sha256": configuration_sha256,
            "disposition": "noop",
            "reason": configuration_reason,
            "schema_version": 2,
        }

    operation = operation_record(policy, snapshot)
    operation_key = digest(operation)

    history_records, history_sha256, _ = normalize_inventory(
        snapshot["history"],
        "history-inventory",
        policy,
        lambda value: history_source(policy, value),
        lambda value: history_record(policy, now, value),
    )
    require(
        len({record["operation_key"] for record in history_records})
        == len(history_records),
        "history-operation-key-duplicate",
    )
    history_disposition, pr_number, matching_history = classify_history(
        history_records, operation, operation_key, event
    )

    reservation_records, reservation_inventory_sha256, _ = normalize_inventory(
        snapshot["reservations"],
        "reservation-inventory",
        policy,
        lambda value: reservation_source(policy, event, value),
        lambda value: reservation_record(policy, event, now, value),
    )
    require(
        len({record["external_id"] for record in reservation_records})
        == len(reservation_records),
        "reservation-external-id-duplicate",
    )
    external_id = reservation_external_id(operation_key)
    matching = [
        record
        for record in reservation_records
        if record["external_id"] == external_id
    ]
    require(len(matching) <= 1, "reservation-duplicate")
    reservation = matching[0] if matching else None
    if reservation is not None:
        if reservation["materialized_state"]["state"] == "orphaned":
            require(
                event["run_attempt"] == 2,
                "orphan-attempt-2-authority-required",
            )
        validate_reservation_history(reservation, matching_history)

    if history_disposition in {"active", "consumed"} and (
        reservation is None
        or reservation["materialized_state"]["state"]
        not in {"cancelled", "completed"}
    ):
        return {
            "disposition": history_disposition,
            "history_sha256": history_sha256,
            "operation_key": operation_key,
            "pr_number": pr_number,
            "reason": "terminal-history",
            "schema_version": 2,
        }
    if history_disposition == "pending" and (
        reservation is None
        or reservation["materialized_state"]["state"]
        not in {"cancelled", "completed"}
    ):
        raise ContractError("history-dispatch-pending")

    run_records, run_inventory_sha256, _ = normalize_inventory(
        snapshot["runs"],
        "run-inventory",
        policy,
        lambda value: run_source(policy, value),
        lambda value: run_record(policy, now, value),
    )
    current = [
        record
        for record in run_records
        if record["run_id"] == event["run_id"]
        and record["attempt"] == event["run_attempt"]
    ]
    require(len(current) == 1, "current-run-count")
    current_record = current[0]
    require(current_record["head_sha"] == event["run_sha"], "current-run-head")
    require(current_record["operation_key"] == operation_key, "current-run-operation")
    predecessor = None
    if event["run_attempt"] == 2:
        require(current_record["status"] == "in_progress", "attempt-2-not-running")
        prior = [
            record
            for record in run_records
            if record["run_id"] == event["run_id"] and record["attempt"] == 1
        ]
        require(len(prior) == 1, "attempt-2-predecessor-count")
        predecessor = prior[0]
        require(
            predecessor["status"] == "completed"
            and predecessor["conclusion"] == "cancelled",
            "attempt-2-predecessor-not-cancelled",
        )
        require(predecessor["head_sha"] == event["run_sha"], "attempt-2-predecessor-head")
        require(
            predecessor["operation_key"] == operation_key,
            "attempt-2-predecessor-operation",
        )
    elif current_record["status"] == "completed":
        require(current_record["conclusion"] == "cancelled", "current-run-status")
    else:
        require(current_record["status"] == "in_progress", "current-run-status")

    nonterminal = [record for record in run_records if record["status"] != "completed"]
    same_key = [
        record for record in nonterminal if record["operation_key"] == operation_key
    ]
    if current_record["status"] != "completed":
        require(
            len(same_key) == 1
            and same_key[0]["run_id"] == event["run_id"]
            and same_key[0]["attempt"] == event["run_attempt"],
            "duplicate-run",
        )
    newer = [
        record
        for record in nonterminal
        if (record["run_id"], record["attempt"])
        > (event["run_id"], event["run_attempt"])
    ]
    require(not newer, "superseded-by-newer-run")
    older = [
        record
        for record in nonterminal
        if (record["run_id"], record["attempt"])
        < (event["run_id"], event["run_attempt"])
    ]
    require(not older, "capacity-owned-by-older-run")

    created_at = timestamp(current_record["created_at"], "current-created-at")
    expires_at = created_at + timedelta(seconds=policy["lease"]["ttl_seconds"])
    if current_record["status"] != "completed":
        require(now < expires_at, "lease-expired")

    if current_record["status"] == "completed" and not matching:
        require(event["run_attempt"] == 1, "cancelled-attempt")
        require(snapshot["attempt_authorization"] is None, "unexpected-attempt-authorization")
        return {
            "disposition": "consumed",
            "operation_key": operation_key,
            "reason": "cancelled-before-reservation",
            "run_inventory_sha256": run_inventory_sha256,
            "schema_version": 2,
        }

    if reservation is not None:
        state = reservation["materialized_state"]
        owner = [
            record
            for record in run_records
            if record["run_id"] == state["owner_run_id"]
            and record["attempt"] == state["owner_run_attempt"]
        ]
        require(len(owner) == 1, "reservation-owner-run-count")
        owner_record = owner[0]
        require(owner_record["head_sha"] == event["run_sha"], "reservation-owner-head")
        require(owner_record["operation_key"] == operation_key, "reservation-owner-operation")
        require(
            owner_record["created_at"] == state["owner_run_created_at"],
            "reservation-owner-created-at-drift",
        )
        allowed_owners = {(event["run_id"], event["run_attempt"])}
        if predecessor is not None:
            allowed_owners.add((predecessor["run_id"], predecessor["attempt"]))
        require(
            (state["owner_run_id"], state["owner_run_attempt"]) in allowed_owners,
            "reservation-owner-provenance",
        )
        if state["state"] == "completed":
            require(
                snapshot["attempt_authorization"] is None,
                "terminal-attempt-authorization",
            )
            return terminal_reservation_result(
                reservation, operation_key, "terminal-reservation"
            )
        if state["state"] == "cancelled":
            require(
                owner_record["status"] == "completed"
                and owner_record["conclusion"] == "cancelled",
                "cancelled-owner-not-cancelled",
            )
            require(
                snapshot["attempt_authorization"] is None,
                "cancelled-attempt-authorization",
            )
            reason_by_stage = {
                "reserved": "cancelled-after-reservation",
                "pr-created": "cancelled-after-pr-create",
                "dispatched": "cancelled-after-dispatch",
            }
            return terminal_reservation_result(
                reservation, operation_key, reason_by_stage[state["stage"]]
            )
        if state["state"] == "orphaned":
            require(event["run_attempt"] == 2, "orphan-attempt-2-authority-required")
            require(predecessor is not None, "orphan-predecessor-required")
            require(
                state["owner_run_id"] == predecessor["run_id"]
                and state["owner_run_attempt"] == predecessor["attempt"],
                "orphan-owner-not-predecessor",
            )
            if state["stage"] == "reserved":
                require(
                    matching_history is None,
                    "reserved-orphan-history-present",
                )
            else:
                require(
                    history_disposition == "recovery-candidate"
                    and matching_history is not None,
                    "orphan-history-required",
                )
            authorization = validate_attempt_authorization(
                snapshot["attempt_authorization"],
                policy,
                event,
                operation_key,
                reservation,
                predecessor,
                now,
            )
            next_action = (
                authorization["core"]["allowed_action"]
                if authorization["used"]
                else "attempt-authorization-consume"
            )
            return {
                "attempt_authorization_sha256": authorization["authorization_id"],
                "attempt_authorization_check_run_id": authorization["check_run_id"],
                "attempt_authorization_external_id": authorization["external_id"],
                "attempt_two_action": next_action,
                "authorized_after_consume_action": authorization["core"]["allowed_action"],
                "attempt_authorization_consumed": authorization["used"],
                "configuration_sha256": configuration_sha256,
                "disposition": "mutate",
                "history_sha256": history_sha256,
                "history_pr_number": pr_number,
                "history_dispatch_state": (
                    matching_history["dispatch_state"]
                    if matching_history is not None
                    else None
                ),
                "lease": lease_output(
                    policy,
                    event,
                    current_record,
                    operation_key,
                    snapshot["now"],
                    reservation,
                ),
                "operation": operation,
                "operation_key": operation_key,
                "reason": "attempt-2-authorized-orphan",
                "reservation_inventory_sha256": reservation_inventory_sha256,
                "run_inventory_sha256": run_inventory_sha256,
                "schema_version": 2,
            }
        require(state["state"] == "leased", "reservation-state-unhandled")
        require(current_record["status"] == "in_progress", "leased-owner-not-running")
        require(state["owner_run_id"] == event["run_id"], "reservation-owner-drift")
        require(
            state["owner_run_attempt"] == event["run_attempt"],
            "reservation-owner-attempt-drift",
        )
        require(
            state["owner_run_created_at"] == current_record["created_at"],
            "reservation-owner-created-at-drift",
        )
        require(state["lease_expires_at"] == timestamp_text(expires_at), "reservation-expiry-drift")
        require(event["run_attempt"] == 1, "leased-attempt-2")
        require(
            snapshot["attempt_authorization"] is None,
            "unexpected-attempt-authorization",
        )
        reason = "lease-owned"
    else:
        require(event["run_attempt"] == 1, "attempt-2-orphan-required")
        require(
            snapshot["attempt_authorization"] is None,
            "unexpected-attempt-authorization",
        )
        require(current_record["status"] == "in_progress", "reservation-owner-not-running")
        reason = "reservation-required"

    return {
        "configuration_sha256": configuration_sha256,
        "disposition": "mutate",
        "history_sha256": history_sha256,
        "lease": lease_output(
            policy,
            event,
            current_record,
            operation_key,
            snapshot["now"],
            reservation,
        ),
        "operation": operation,
        "operation_key": operation_key,
        "reason": reason,
        "reservation_inventory_sha256": reservation_inventory_sha256,
        "run_inventory_sha256": run_inventory_sha256,
        "schema_version": 2,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", required=True)
    parser.add_argument("--snapshot", required=True)
    arguments = parser.parse_args(argv)
    try:
        result = classify(load_json(arguments.policy), load_json(arguments.snapshot))
    except (ContractError, OSError) as error:
        result = {"disposition": "blocked", "reason": str(error), "schema_version": 2}
        sys.stdout.buffer.write(canonical(result))
        return 1
    sys.stdout.buffer.write(canonical(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
