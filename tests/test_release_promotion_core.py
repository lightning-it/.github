from __future__ import annotations

import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import types
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "scripts/release-promotion-state.py"
INVENTORY_PATH = ROOT / "scripts/release-promotion-inventory.py"
POLICY_PATH = ROOT / ".lit/release-reconciliation-policy.json"
CORE_HELPERS = ("scripts/release-promotion-history.sh",
                "scripts/release-promotion-inventory.py",
                "scripts/release-promotion-preflight-bind.sh",
                "scripts/release-promotion-preflight-revalidate.sh",
                "scripts/release-promotion-preflight.sh",
                "scripts/release-promotion-state.py")


def load_module(path: Path, name):
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise AssertionError(f"cannot import {path}")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


STATE = load_module(STATE_PATH, "release_promotion_state")
INVENTORY = load_module(INVENTORY_PATH, "release_promotion_inventory")


class StateFixture(unittest.TestCase):
    def policy(self):
        return {
            "environment": {
                "client_id": "123456",
                "client_id_variable_name": "RELEASE_RECONCILIATION_APP_CLIENT_ID",
                "deployment_branch_policy": {
                    "custom_branch_policies": False,
                    "protected_branches": True,
                },
                "enablement_variable_name": "RELEASE_RECONCILIATION_ENABLED",
                "name": "release-reconciliation-v1",
                "prevent_self_review": True,
                "reviewers": [
                    {"id": 4321, "type": "Team"},
                    {"id": 5678, "type": "User"},
                ],
                "secret_name": "RELEASE_RECONCILIATION_APP_PRIVATE_KEY",
            },
            "issue": 564,
            "lease": {"max_inventory_bytes": 1048576,
                      "max_inventory_elapsed_ms": 30000,
                      "max_inventory_pages": 10, "max_inventory_records": 100,
                      "ttl_seconds": 3600},
            "lifecycle": "default-off",
            "operation_class": "develop-to-main-promotion",
            "policy_epoch": "rep120-c1-v2",
            "repository": "lightning-it/.github",
            "repository_id": 123456789,
            "review": {"canonical_diff_format": "git-diff-binary-full-index-no-renames-v1",
                       "maximum_bytes": 199999, "minimum_bytes": 1},
            "schema_version": 2,
            "source_ref": "refs/heads/develop",
            "target_ref": "refs/heads/main",
            "workflow_id": 987654,
            "workflow_path": ".github/workflows/reconcile-develop-to-main.yml",
        }

    @staticmethod
    def page_list(records, sizes=None, *, reverse_pages=False):
        if sizes is None:
            sizes = [len(records)]
        if sum(sizes) != len(records):
            raise AssertionError("page sizes do not cover records")
        pages = []
        offset = 0
        for number, size in enumerate(sizes, start=1):
            chunk = copy.deepcopy(records[offset : offset + size])
            offset += size
            pages.append(
                {
                    "cursor": None if number == 1 else f"cursor-{number}",
                    "next_cursor": None if number == len(sizes) else f"cursor-{number + 1}",
                    "number": number,
                    "raw_sha256": STATE.digest(chunk),
                    "records": chunk,
                    "response_bytes": 10 + len(chunk),
                }
            )
        if reverse_pages:
            pages.reverse()
        return pages

    def inventory(self, source, records, sizes=None, *, reverse_pages=False):
        pages = self.page_list(records, sizes, reverse_pages=reverse_pages)
        normalized_records = sorted(copy.deepcopy(records), key=STATE.canonical)
        return {
            "collector": "release-promotion-inventory-v1",
            "complete": True,
            "elapsed_ms": 10,
            "page_count": len(pages),
            "pages": pages,
            "read_count": 2,
            "record_count": len(records),
            "response_bytes": sum(int(page["response_bytes"]) for page in pages),
            "semantic_sha256": STATE.digest({"records": normalized_records, "source": source}),
            "source": copy.deepcopy(source),
        }

    @staticmethod
    def history_source(policy):
        return {
            "endpoint": "repos/lightning-it/.github/pulls",
            "repository_id": policy["repository_id"],
            "state": "all",
        }

    @staticmethod
    def run_source(policy):
        return {
            "endpoint": "actions/workflow-runs",
            "event": "push",
            "ref": policy["source_ref"],
            "repository_id": policy["repository_id"],
            "workflow_id": policy["workflow_id"],
            "workflow_path": policy["workflow_path"],
        }

    @staticmethod
    def reservation_source(policy, head_sha="a" * 40):
        return {
            "check_name": "release-reconciliation / reservation",
            "endpoint": "checks/runs",
            "head_sha": head_sha,
            "repository_id": policy["repository_id"],
        }

    @staticmethod
    def runtime_inputs():
        return [
            {
                "blob": f"{index + 1:x}" * 40,
                "mode": "100644",
                "path": path,
            }
            for index, path in enumerate(STATE.RUNTIME_INPUT_PATHS)
        ]

    def current_run(self, policy, operation_key, *, attempt=1, conclusion=None,
                    created_at="2026-09-07T12:00:00Z", run_id=100,
                    status="in_progress"):
        return {
            "attempt": attempt,
            "conclusion": conclusion,
            "created_at": created_at,
            "event": "push",
            "head_sha": "a" * 40,
            "operation_key": operation_key,
            "ref": policy["source_ref"],
            "repository_id": policy["repository_id"],
            "run_id": run_id,
            "status": status,
            "workflow_id": policy["workflow_id"],
            "workflow_path": policy["workflow_path"],
        }

    def snapshot(self, policy=None):
        policy = policy or self.policy()
        environment = policy["environment"]
        snapshot = {
            "attempt_authorization": None,
            "configuration": {
                "environment": {
                    "deployment_branch_policy": copy.deepcopy(
                        environment["deployment_branch_policy"]
                    ),
                    "name": environment["name"],
                    "prevent_self_review": environment["prevent_self_review"],
                    "reviewers": copy.deepcopy(environment["reviewers"]),
                },
                "environment_secret_names": ["AUXILIARY_ENVIRONMENT_SECRET", environment["secret_name"]],
                "organization_enablement": {"present": False, "scope": "organization", "value": None},
                "organization_secret_names": ["UNRELATED_ORG_SECRET"],
                "repository_client_id": {"present": True, "scope": "repository",
                                         "value": environment["client_id"]},
                "repository_enablement": {"present": True, "scope": "repository", "value": "true"},
                "repository_secret_names": ["UNRELATED_REPO_SECRET"],
            },
            "discovery": {
                "has_content_delta": True,
                "merge_base_sha": "b" * 40,
                "source_sha": "a" * 40,
                "target_base_sha": "c" * 40,
            },
            "event": {
                "name": "push",
                "ref": policy["source_ref"],
                "ref_protected": True,
                "run_attempt": 1,
                "run_id": 100,
                "run_sha": "a" * 40,
                "workflow_id": policy["workflow_id"],
                "workflow_path": policy["workflow_path"],
            },
            "git": {
                "candidate_sha": "d" * 40,
                "integration_tree": "e" * 40,
                "merge_base_sha": "b" * 40,
                "patch_bytes": 199999,
                "patch_format": "git-diff-binary-full-index-no-renames-v1",
                "patch_sha256": "f" * 64,
                "projection_sha256": "1" * 64,
                "runtime_inputs": self.runtime_inputs(),
                "source_sha": "a" * 40,
                "target_base_sha": "c" * 40,
                "unsafe_delta": False,
            },
            "history": self.inventory(self.history_source(policy), []),
            "now": "2026-09-07T12:30:00Z",
            "repository": {"full_name": "lightning-it/.github", "id": policy["repository_id"]},
            "reservations": self.inventory(self.reservation_source(policy), []),
            "runs": None,
            "schema_version": 2,
        }
        operation_key = STATE.digest(STATE.operation_record(policy, snapshot))
        snapshot["runs"] = self.inventory(self.run_source(policy),
                                           [self.current_run(policy, operation_key)])
        return snapshot

    @staticmethod
    def first_record(snapshot, inventory_name):
        inventory = snapshot[inventory_name]
        pages = inventory["pages"]
        records = pages[0]["records"]
        return records[0]

    def operation_key(self, policy, snapshot):
        return STATE.digest(STATE.operation_record(policy, snapshot))

    def refresh_operation_key(self, policy, snapshot):
        operation_key = self.operation_key(policy, snapshot)
        record = self.first_record(snapshot, "runs")
        record["operation_key"] = operation_key
        self.refresh_inventory_semantic(snapshot, "runs")
        return operation_key

    @staticmethod
    def refresh_inventory_semantic(snapshot, name):
        inventory = snapshot[name]
        pages = inventory["pages"]
        records = [record for page in pages for record in page["records"]]
        inventory["semantic_sha256"] = STATE.digest({
            "records": sorted(copy.deepcopy(records), key=STATE.canonical),
            "source": inventory["source"],
        })

    def replace_inventory(
        self,
        snapshot,
        name,
        records,
        sizes = None,
        *,
        reverse_pages=False,
    ):
        current = snapshot[name]
        source = current["source"]
        snapshot[name] = self.inventory(
            source,
            records,
            sizes,
            reverse_pages=reverse_pages,
        )

    def history_record(
        self,
        policy,
        operation_key,
        *,
        dispatch_state="succeeded",
        merged_at=None,
        number=575,
        state="open",
    ):
        return {
            "base_ref": policy["target_ref"],
            "base_sha": "c" * 40,
            "body_sha256": "2" * 64,
            "created_at": "2026-09-07T12:10:00Z",
            "dispatch_state": dispatch_state,
            "draft": False,
            "head_ref": policy["source_ref"],
            "head_sha": "a" * 40,
            "merged_at": merged_at,
            "operation_key": operation_key,
            "pr_number": number,
            "repository_id": policy["repository_id"],
            "run_attempt": 1,
            "run_id": 100,
            "state": state,
        }

    def reservation_record(
        self,
        policy,
        snapshot,
        *,
        check_run_id=700,
        downstream_state=None,
        operation_key=None,
        owner_attempt=1,
        owner_run_id=100,
        pr_state=None,
        stage="reserved",
        state="leased",
        terminal_disposition=None,
    ):
        event = snapshot["event"]
        operation_key = operation_key or self.operation_key(policy, snapshot)
        owner_created_at = "2026-09-07T12:00:00Z"
        stage_evidence = {
            "reserved": {"downstream_state": "not-dispatched", "last_intent_sha256": "2" * 64,
                         "pr_state": "absent"},
            "pr-created": {"downstream_state": "not-dispatched", "last_intent_sha256": "3" * 64,
                           "pr_state": "open"},
            "dispatched": {"downstream_state": "unknown", "last_intent_sha256": "4" * 64,
                           "pr_state": "open"},
            "finalized": {"downstream_state": "succeeded", "last_intent_sha256": "5" * 64,
                          "pr_state": "open"},
        }[stage]
        if downstream_state is not None:
            stage_evidence["downstream_state"] = downstream_state
        if pr_state is not None:
            stage_evidence["pr_state"] = pr_state
        materialized_state = {
            "created_at": "2026-09-07T12:05:00Z",
            **stage_evidence,
            "lease_expires_at": "2026-09-07T13:00:00Z",
            "operation_key": operation_key,
            "owner_run_attempt": owner_attempt,
            "owner_run_created_at": owner_created_at,
            "owner_run_id": owner_run_id,
            "source_identity": STATE.source_identity(policy, event),
            "stage": stage,
            "state": state,
            "terminal_disposition": terminal_disposition,
        }
        projection = {"check_run_id": check_run_id,
                      "external_id": STATE.reservation_external_id(operation_key),
                      "materialized_state": materialized_state}
        return {**projection, "readback_sha256": STATE.digest(projection)}

    def attempt_authorization(self, policy, snapshot, orphan, predecessor):
        event = snapshot["event"]
        operation_key = self.operation_key(policy, snapshot)
        orphan_state = orphan["materialized_state"]
        core = {
            "allowed_action": STATE.ATTEMPT2_ACTION_BY_STAGE[orphan_state["stage"]],
            "attempt": 2,
            "created_at": "2026-09-07T12:20:00Z",
            "expires_at": "2026-09-07T12:50:00Z",
            "operation_key": operation_key,
            "prior_intent_sha256": orphan_state["last_intent_sha256"],
            "prior_attempt": 1,
            "prior_run_sha256": STATE.digest(predecessor),
            "run_id": event["run_id"],
            "source_identity": STATE.source_identity(policy, event),
            "state_digest": orphan["readback_sha256"],
        }
        authorization = {
            "authorization_id": "",
            "check_run_id": 900,
            "core": core,
            "external_id": "",
            "issuer": "release-reconciliation-attempt-authority-v1",
            "readback_sha256": "",
            "used": False,
        }
        self.seal_attempt_authorization(authorization)
        return authorization

    @staticmethod
    def seal_attempt_authorization(authorization):
        authorization_id = STATE.attempt_authorization_id(authorization["core"])
        authorization["authorization_id"] = authorization_id
        authorization["external_id"] = f"lit-release-attempt-2-v1:{authorization_id}"
        authorization["readback_sha256"] = STATE.digest({
            key: authorization[key]
            for key in ("authorization_id", "check_run_id", "core", "external_id", "issuer", "used")
        })

    @staticmethod
    def seal_reservation(reservation):
        reservation["readback_sha256"] = STATE.digest(
            {
                key: reservation[key]
                for key in ("check_run_id", "external_id", "materialized_state")
            }
        )

    def assert_blocked(self, reason, policy, snapshot):
        with self.assertRaisesRegex(STATE.ContractError, reason):
            STATE.classify(policy, snapshot)

    @staticmethod
    def set_path(value, path, replacement):
        for key in path[:-1]:
            value = value[key]
        value[path[-1]] = replacement


class ReleasePromotionCanonicalStateTests(StateFixture):
    def test_raw_duplicate_input_keys_block_before_normalization(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "duplicate.json"
            path.write_text('{"issue":564,"issue":565}\n', encoding="utf-8")
            with self.assertRaisesRegex(
                STATE.ContractError, "input-duplicate-key"
            ):
                STATE.load_json(str(path))

    def test_noncanonical_input_encoding_blocks(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "noncanonical.json"
            for raw in ('{"issue": 564}\n', "NaN\n"):
                with self.subTest(raw=raw):
                    path.write_text(raw, encoding="utf-8")
                    with self.assertRaisesRegex(
                        STATE.ContractError, "input-not-canonical-json"
                    ):
                        STATE.load_json(str(path))

    def test_input_stat_error_has_a_stable_contract_reason(self):
        for error in (FileNotFoundError(2, "OS-SENTINEL", "/private/sentinel"),
                      PermissionError(13, "OS-SENTINEL", "/private/sentinel")):
            with self.subTest(error=type(error).__name__), mock.patch.object(
                STATE.Path, "lstat", side_effect=error
            ), self.assertRaises(STATE.ContractError) as caught:
                STATE.load_json("/private/sentinel")
            self.assertEqual("input-stat-failed", str(caught.exception))

    def test_provisional_policy_remains_explicitly_non_authorizing(self):
        policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
        self.assertEqual("provisional-pre-d1-pre-s0", policy["lifecycle"])
        self.assertIs(False, policy["mutation_authority"])
        with self.assertRaisesRegex(STATE.ContractError, "policy-not-materialized"):
            STATE.classify(policy, {})

    def test_exact_snapshot_yields_complete_operation_and_lease(self):
        policy = self.policy()
        snapshot = self.snapshot(policy)
        result = STATE.classify(policy, snapshot)
        operation_key = self.operation_key(policy, snapshot)
        self.assertEqual("mutate", result["disposition"])
        self.assertEqual("reservation-required", result["reason"])
        self.assertEqual(operation_key, result["operation_key"])
        expected_lease = {
            "check_run_id": None, "created_at": "2026-09-07T12:30:00Z",
            "expires_at": "2026-09-07T13:00:00Z",
            "external_id": STATE.reservation_external_id(operation_key),
            "operation_key": operation_key, "owner_run_attempt": 1,
            "owner_run_created_at": "2026-09-07T12:00:00Z", "owner_run_id": 100,
            "source_identity": STATE.source_identity(policy, snapshot["event"]),
        }
        self.assertEqual(expected_lease, result["lease"])
        self.assertEqual(
            list(STATE.RUNTIME_INPUT_PATHS),
            [item["path"] for item in result["operation"]["runtime_inputs"]],
        )

    def test_configuration_normalization_is_permutation_invariant(self):
        policy = self.policy()
        first = self.snapshot(policy)
        second = copy.deepcopy(first)
        configuration = second["configuration"]
        environment = configuration["environment"]
        environment["reviewers"].reverse()
        configuration["environment_secret_names"].reverse()
        configuration["repository_secret_names"].reverse()
        configuration["organization_secret_names"].reverse()
        first_result = STATE.classify(policy, first)
        second_result = STATE.classify(policy, second)
        self.assertEqual(
            first_result["configuration_sha256"],
            second_result["configuration_sha256"],
        )
        self.assertEqual(first_result["operation_key"], second_result["operation_key"])
        self.assertEqual(first_result["disposition"], second_result["disposition"])

    def test_repository_enablement_is_exact_and_repository_scoped(self):
        policy = self.policy()
        for present, value, disposition, reason in (
            (False, None, "noop", "repository-variable-absent"),
            (True, "false", "noop", "repository-variable-false"),
            (True, "true", "mutate", "reservation-required"),
        ):
            with self.subTest(present=present, value=value):
                snapshot = self.snapshot(policy)
                configuration = snapshot["configuration"]
                configuration["repository_enablement"] = {
                    "present": present,
                    "scope": "repository",
                    "value": value,
                }
                result = STATE.classify(policy, snapshot)
                self.assertEqual(disposition, result["disposition"])
                self.assertEqual(reason, result["reason"])
        organization_only = self.snapshot(policy)
        configuration = organization_only["configuration"]
        configuration["repository_enablement"] = {
            "present": False,
            "scope": "repository",
            "value": None,
        }
        configuration["organization_enablement"] = {
            "present": True,
            "scope": "organization",
            "value": "true",
        }
        result = STATE.classify(policy, organization_only)
        self.assertEqual("noop", result["disposition"])
        self.assertEqual("repository-variable-absent", result["reason"])
        for field in (
            "environment",
            "environment_secret_names",
            "organization_secret_names",
            "repository_client_id",
            "repository_secret_names",
        ):
            configuration[field] = None
        result = STATE.classify(policy, organization_only)
        self.assertEqual("noop", result["disposition"])
        self.assertEqual("repository-variable-absent", result["reason"])
        for malformed in ("TRUE", "1", "yes", "", 1, True):
            with self.subTest(malformed=malformed):
                snapshot = self.snapshot(policy)
                configuration = snapshot["configuration"]
                record = configuration["repository_enablement"]
                record["value"] = malformed
                self.assert_blocked(
                    "repository-variable-malformed|repository-enablement-value",
                    policy,
                    snapshot,
                )

    def test_configuration_drift_and_secret_scope_fail_closed(self):
        policy = self.policy()
        changes = (
            ("environment", ("environment", "name"), "wrong", "environment-drift"),
            (
                "branch",
                ("environment", "deployment_branch_policy", "protected_branches"),
                False,
                "environment-drift",
            ),
            (
                "reviewer",
                ("environment", "reviewers", 0, "id"),
                9999,
                "environment-drift",
            ),
            (
                "client",
                ("repository_client_id", "value"),
                "654321",
                "client-id-drift",
            ),
        )
        for name, path, value, reason in changes:
            with self.subTest(name=name):
                snapshot = self.snapshot(policy)
                configuration = snapshot["configuration"]
                target: object = configuration
                for component in path[:-1]:
                    target = target[component]
                target[path[-1]] = value
                self.assert_blocked(reason, policy, snapshot)
        for field, value, reason in (
            ("environment_secret_names", [], "environment-secret-absent"),
            (
                "repository_secret_names",
                ["RELEASE_RECONCILIATION_APP_PRIVATE_KEY"],
                "repository-secret-collision",
            ),
            (
                "organization_secret_names",
                ["RELEASE_RECONCILIATION_APP_PRIVATE_KEY"],
                "organization-secret-collision",
            ),
        ):
            with self.subTest(field=field):
                snapshot = self.snapshot(policy)
                configuration = snapshot["configuration"]
                configuration[field] = value
                self.assert_blocked(reason, policy, snapshot)

    def test_page_order_boundaries_and_record_order_do_not_change_digests(
        self,
    ):
        policy = self.policy()
        first = self.snapshot(policy)
        operation_key = self.operation_key(policy, first)
        completed_runs = [
            self.current_run(policy, key * 64, run_id=run_id,
                             status="completed", conclusion=conclusion)
            for key, run_id, conclusion in (("8", 80, "success"),
                                             ("9", 90, "failure"))
        ]
        current = self.first_record(first, "runs")
        self.replace_inventory(first, "runs", [copy.deepcopy(current), *completed_runs], [1, 2])
        histories = [
            self.history_record(policy, "6" * 64, number=560, state="closed"),
            self.history_record(policy, "7" * 64, number=561, state="closed"),
        ]
        reservations = [
            self.reservation_record(
                policy,
                first,
                check_run_id=check_id,
                downstream_state=downstream,
                operation_key=key * 64,
                pr_state=pr_state,
                stage="finalized",
                state="completed",
                terminal_disposition=terminal,
            )
            for check_id, key, terminal, pr_state, downstream in (
                (680, "4", "consumed", "closed", "succeeded"),
                (690, "5", "noop", "absent", "not-dispatched"),
            )
        ]
        for name, records in (("history", histories), ("reservations", reservations)):
            self.replace_inventory(first, name, records, [1, 1])

        second = self.snapshot(policy)
        current = self.first_record(second, "runs")
        self.replace_inventory(second, "runs",
                               [*reversed(completed_runs), copy.deepcopy(current)],
                               [2, 1], reverse_pages=True)
        self.replace_inventory(second, "history", list(reversed(histories)),
                               [2], reverse_pages=True)
        self.replace_inventory(second, "reservations", list(reversed(reservations)), [2])
        first_result = STATE.classify(policy, first)
        second_result = STATE.classify(policy, second)
        self.assertEqual(operation_key, first_result["operation_key"])
        for field in (
            "configuration_sha256",
            "history_sha256",
            "reservation_inventory_sha256",
            "run_inventory_sha256",
        ):
            self.assertEqual(first_result[field], second_result[field], field)

    def test_inventory_transport_bounds_and_chain_fail_closed(self):
        policy = self.policy()
        labels = {
            "history": "history-inventory",
            "runs": "run-inventory",
            "reservations": "reservation-inventory",
        }
        mutations = (
            ("incomplete", lambda item: item.update(complete=False), "incomplete"),
            (
                "elapsed",
                lambda item: item.update(elapsed_ms=30001),
                "elapsed-limit",
            ),
            (
                "bytes",
                lambda item: item.update(response_bytes=1048577),
                "byte-limit",
            ),
            (
                "pages",
                lambda item: item.update(page_count=11),
                "page-limit",
            ),
            (
                "records",
                lambda item: item.update(record_count=101),
                "record-limit",
            ),
        )
        for inventory_name, label in labels.items():
            for name, mutate, reason in mutations:
                with self.subTest(inventory=inventory_name, boundary=name):
                    snapshot = self.snapshot(policy)
                    inventory = snapshot[inventory_name]
                    mutate(inventory)
                    self.assert_blocked(
                        f"{label}-{reason}", policy, snapshot
                    )
            with self.subTest(inventory=inventory_name, boundary="cursor"):
                snapshot = self.snapshot(policy)
                inventory = snapshot[inventory_name]
                pages = inventory["pages"]
                pages.append(
                    {
                        "cursor": "wrong",
                        "next_cursor": None,
                        "number": 2,
                        "raw_sha256": "0" * 64,
                        "records": [],
                        "response_bytes": 0,
                    }
                )
                inventory["page_count"] = 2
                self.assert_blocked(
                    f"{label}-cursor-(chain|truncated)", policy, snapshot
                )


class ReleasePromotionOperationTests(StateFixture):
    def test_every_operation_scalar_is_independently_bound(self):
        policy = self.policy()
        baseline = self.snapshot(policy)
        baseline_key = self.operation_key(policy, baseline)
        git_changes = (
            ("candidate_sha", "2" * 40),
            ("integration_tree", "3" * 40),
            ("patch_bytes", 12345),
            ("patch_sha256", "4" * 64),
            ("projection_sha256", "5" * 64),
        )
        for field, value in git_changes:
            with self.subTest(field=field):
                snapshot = copy.deepcopy(baseline)
                git = snapshot["git"]
                git[field] = value
                self.assertNotEqual(
                    baseline_key, self.operation_key(policy, snapshot)
                )
        for field, value in (
            ("merge_base_sha", "6" * 40),
            ("target_base_sha", "7" * 40),
        ):
            with self.subTest(field=field):
                snapshot = copy.deepcopy(baseline)
                git = snapshot["git"]
                discovery = snapshot["discovery"]
                git[field] = value
                discovery[field] = value
                self.assertNotEqual(
                    baseline_key, self.operation_key(policy, snapshot)
                )
        source = copy.deepcopy(baseline)
        git = source["git"]
        discovery = source["discovery"]
        event = source["event"]
        git["source_sha"] = "8" * 40
        discovery["source_sha"] = "8" * 40
        event["run_sha"] = "8" * 40
        self.assertNotEqual(baseline_key, self.operation_key(policy, source))

        for field, value in (
            ("repository_id", 999),
            ("target_ref", "refs/heads/release"),
            ("source_ref", "refs/heads/trunk"),
            ("operation_class", "other-operation"),
            ("policy_epoch", "rep120-c1-v3"),
            ("workflow_id", 111),
            ("workflow_path", ".github/workflows/other.yml"),
        ):
            with self.subTest(policy_field=field):
                changed_policy = copy.deepcopy(policy)
                changed_policy[field] = value
                self.assertNotEqual(
                    baseline_key,
                    STATE.digest(
                        STATE.operation_record(changed_policy, baseline)
                    ),
                )

    def test_each_runtime_blob_is_bound_and_input_order_is_canonical(self):
        policy = self.policy()
        baseline = self.snapshot(policy)
        baseline_key = self.operation_key(policy, baseline)
        git = baseline["git"]
        inputs = git["runtime_inputs"]
        permuted = copy.deepcopy(baseline)
        permuted_git = permuted["git"]
        permuted_git["runtime_inputs"].reverse()
        self.assertEqual(baseline_key, self.operation_key(policy, permuted))
        for index in range(len(inputs)):
            with self.subTest(path=inputs[index]["path"]):
                snapshot = copy.deepcopy(baseline)
                candidate_git = snapshot["git"]
                candidate_inputs = candidate_git["runtime_inputs"]
                candidate_inputs[index]["blob"] = "f" * 40
                self.assertNotEqual(
                    baseline_key, self.operation_key(policy, snapshot)
                )
        wrong_path = copy.deepcopy(baseline)
        wrong_path["git"]["runtime_inputs"][0]["path"] = "scripts/substitute.py"
        with self.assertRaisesRegex(STATE.ContractError, "runtime-input-path-set"):
            self.operation_key(policy, wrong_path)
        wrong_mode = copy.deepcopy(baseline)
        wrong_mode["git"]["runtime_inputs"][0]["mode"] = "100755"
        with self.assertRaisesRegex(STATE.ContractError, "runtime-input-mode"):
            self.operation_key(policy, wrong_mode)
        duplicate = copy.deepcopy(baseline)
        duplicate["git"]["runtime_inputs"][1]["path"] = (
            duplicate["git"]["runtime_inputs"][0]["path"]
        )
        with self.assertRaisesRegex(
            STATE.ContractError, "runtime-input-path-duplicate"
        ):
            self.operation_key(policy, duplicate)

    def test_independent_substitution_is_rejected_not_silently_coupled(self):
        policy = self.policy()
        for field, value, reason in (
            ("source_sha", "2" * 40, "source-run-drift"),
            ("merge_base_sha", "3" * 40, "review-merge-base-drift"),
            ("target_base_sha", "4" * 40, "review-target-base-drift"),
        ):
            with self.subTest(field=field):
                snapshot = self.snapshot(policy)
                git = snapshot["git"]
                git[field] = value
                with self.assertRaisesRegex(STATE.ContractError, reason):
                    self.operation_key(policy, snapshot)
        candidate = self.snapshot(policy)
        candidate["git"]["candidate_sha"] = "5" * 40
        self.assertIsInstance(self.operation_key(policy, candidate), str)
        tree = self.snapshot(policy)
        tree["git"]["integration_tree"] = "6" * 40
        self.assertIsInstance(self.operation_key(policy, tree), str)

    def test_discovery_no_delta_and_zero_byte_review_are_distinct(self):
        policy = self.policy()
        no_delta = self.snapshot(policy)
        discovery = no_delta["discovery"]
        discovery["has_content_delta"] = False
        for field in (
            "git",
            "history",
            "reservations",
            "runs",
            "attempt_authorization",
        ):
            no_delta[field] = None
        result = STATE.classify(policy, no_delta)
        self.assertEqual("noop", result["disposition"])
        self.assertEqual("no-content-delta", result["reason"])

        smuggled_review = copy.deepcopy(no_delta)
        smuggled_review["git"] = {"patch_bytes": 0}
        self.assert_blocked("no-delta-review-present", policy, smuggled_review)

        zero_review = self.snapshot(policy)
        zero_review["git"]["patch_bytes"] = 0
        self.assert_blocked("patch-empty", policy, zero_review)

    def test_review_boundaries_and_unsafe_inputs_are_exact(self):
        policy = self.policy()
        for size in (1, 199999):
            with self.subTest(accepted=size):
                snapshot = self.snapshot(policy)
                snapshot["git"]["patch_bytes"] = size
                self.refresh_operation_key(policy, snapshot)
                self.assertEqual(
                    "mutate", STATE.classify(policy, snapshot)["disposition"]
                )
        for size in (200000, 228508):
            with self.subTest(rejected=size):
                snapshot = self.snapshot(policy)
                snapshot["git"]["patch_bytes"] = size
                self.assert_blocked("patch-oversized", policy, snapshot)
        for field, value, reason in (
            ("unsafe_delta", True, "unsafe-delta"),
            ("patch_format", "truncated", "patch-format"),
            ("patch_sha256", "not-a-digest", "patch-digest"),
        ):
            with self.subTest(field=field):
                snapshot = self.snapshot(policy)
                snapshot["git"][field] = value
                self.assert_blocked(reason, policy, snapshot)

    def test_policy_rejects_recursive_tbd_and_noncanonical_reviewer_order(
        self,
    ):
        tbd = self.policy()
        tbd["environment"]["client_id"] = "TBD"
        with self.assertRaisesRegex(STATE.ContractError, "policy-tbd"):
            STATE.validate_policy(tbd)
        reviewers = self.policy()
        reviewers["environment"]["reviewers"].reverse()
        with self.assertRaisesRegex(STATE.ContractError, "policy-reviewer-order"):
            STATE.validate_policy(reviewers)


class ReleasePromotionHistoryAndRunTests(StateFixture):
    def test_history_is_computed_from_canonical_records(self):
        policy = self.policy()
        for state, dispatch, disposition in (
            ("open", "succeeded", "active"),
            ("closed", "failed", "consumed"),
            ("closed", "succeeded", "consumed"),
        ):
            with self.subTest(state=state, dispatch=dispatch):
                snapshot = self.snapshot(policy)
                operation_key = self.operation_key(policy, snapshot)
                record = self.history_record(
                    policy,
                    operation_key,
                    dispatch_state=dispatch,
                    state=state,
                )
                self.replace_inventory(snapshot, "history", [record])
                result = STATE.classify(policy, snapshot)
                self.assertEqual(disposition, result["disposition"])
                self.assertEqual("terminal-history", result["reason"])
                self.assertEqual(575, result["pr_number"])

    def test_history_operation_owner_and_pending_are_exact(self):
        policy = self.policy()
        cases = (
            ("run_id", 101, "history-owner-run"),
            ("run_attempt", 2, "history-owner-attempt"),
            ("head_sha", "2" * 40, "history-head-drift"),
            ("base_sha", "3" * 40, "history-base-drift"),
            ("dispatch_state", "pending", "history-dispatch-pending"),
        )
        for field, value, reason in cases:
            with self.subTest(field=field):
                snapshot = self.snapshot(policy)
                operation_key = self.operation_key(policy, snapshot)
                record = self.history_record(policy, operation_key)
                record[field] = value
                self.replace_inventory(snapshot, "history", [record])
                self.assert_blocked(reason, policy, snapshot)
        duplicate = self.snapshot(policy)
        operation_key = self.operation_key(policy, duplicate)
        records = [
            self.history_record(policy, operation_key, number=575),
            self.history_record(policy, operation_key, number=576),
        ]
        self.replace_inventory(duplicate, "history", records)
        self.assert_blocked("history-operation-key-duplicate", policy, duplicate)

    def test_run_identity_source_and_future_time_are_exact(self):
        policy = self.policy()
        cases = (
            ("repository_id", 1, "run-repository"),
            ("workflow_id", 1, "run-workflow-id"),
            ("workflow_path", "other.yml", "run-workflow"),
            ("event", "schedule", "run-event"),
            ("ref", "refs/heads/main", "run-ref"),
            ("head_sha", "2" * 40, "current-run-head"),
            ("created_at", "2026-09-07T12:31:00Z", "run-created-at-future"),
        )
        for field, value, reason in cases:
            with self.subTest(field=field):
                snapshot = self.snapshot(policy)
                record = self.first_record(snapshot, "runs")
                record[field] = value
                self.refresh_inventory_semantic(snapshot, "runs")
                self.assert_blocked(reason, policy, snapshot)

    def test_duplicate_newer_older_expired_and_attempt_three_block(self):
        policy = self.policy()
        for name, mutate, reason in (
            (
                "expired",
                lambda value: value.update(now="2026-09-07T13:00:00Z"),
                "lease-expired",
            ),
            (
                "attempt-three",
                lambda value: value["event"].update(run_attempt=3),
                "event-attempt",
            ),
        ):
            with self.subTest(name=name):
                snapshot = self.snapshot(policy)
                mutate(snapshot)
                self.assert_blocked(reason, policy, snapshot)
        for name, run_id, operation_key, reason in (
            ("duplicate", 101, None, "duplicate-run"),
            ("newer", 101, "8" * 64, "superseded-by-newer-run"),
            ("older", 99, "9" * 64, "capacity-owned-by-older-run"),
        ):
            with self.subTest(name=name):
                snapshot = self.snapshot(policy)
                current = self.first_record(snapshot, "runs")
                other = copy.deepcopy(current)
                other["run_id"] = run_id
                if operation_key is not None:
                    other["operation_key"] = operation_key
                self.replace_inventory(snapshot, "runs", [current, other])
                self.assert_blocked(reason, policy, snapshot)

    def test_same_run_id_attempts_are_distinct_but_duplicate_tuple_blocks(
        self,
    ):
        policy = self.policy()
        snapshot = self.snapshot(policy)
        current = self.first_record(snapshot, "runs")
        prior = copy.deepcopy(current)
        prior["attempt"] = 2
        prior["status"] = "completed"
        prior["conclusion"] = "cancelled"
        self.replace_inventory(snapshot, "runs", [current, prior])
        self.assertEqual("mutate", STATE.classify(policy, snapshot)["disposition"])
        duplicate = copy.deepcopy(snapshot)
        current = self.first_record(duplicate, "runs")
        self.replace_inventory(duplicate, "runs", [current, copy.deepcopy(current)])
        self.assert_blocked("run-inventory-record-duplicate", policy, duplicate)


class ReleasePromotionReservationTests(StateFixture):
    def test_owned_reservation_binds_complete_lease_and_readback(self):
        policy = self.policy()
        snapshot = self.snapshot(policy)
        reservation = self.reservation_record(policy, snapshot)
        self.replace_inventory(snapshot, "reservations", [reservation])
        result = STATE.classify(policy, snapshot)
        self.assertEqual("lease-owned", result["reason"])
        self.assertEqual(700, result["lease"]["check_run_id"])
        self.assertEqual(
            reservation["external_id"], result["lease"]["external_id"]
        )
        self.assertEqual(
            "2026-09-07T12:05:00Z", result["lease"]["created_at"]
        )
        self.assertEqual(1, result["lease"]["owner_run_attempt"])
        self.assertEqual(
            STATE.source_identity(policy, snapshot["event"]),
            result["lease"]["source_identity"],
        )

    def test_terminal_reservation_requires_byte_exact_readback(self):
        policy = self.policy()
        snapshot = self.snapshot(policy)
        terminal = self.reservation_record(
            policy,
            snapshot,
            stage="finalized",
            state="completed",
            terminal_disposition="active",
        )
        self.replace_inventory(
            snapshot,
            "history",
            [self.history_record(policy, self.operation_key(policy, snapshot))],
        )
        self.replace_inventory(snapshot, "reservations", [terminal])
        result = STATE.classify(policy, snapshot)
        self.assertEqual("active", result["disposition"])
        self.assertEqual("terminal-reservation", result["reason"])
        self.assertEqual(
            terminal["readback_sha256"],
            result["reservation_readback_sha256"],
        )
        state_fields = (
            ("owner_run_id", 101),
            ("owner_run_attempt", 2),
            ("created_at", "2026-09-07T12:06:00Z"),
            ("downstream_state", "failed"),
            ("last_intent_sha256", "6" * 64),
            ("lease_expires_at", "2026-09-07T13:01:00Z"),
            ("operation_key", "2" * 64),
            ("pr_state", "closed"),
            ("stage", "reserved"),
            ("terminal_disposition", "consumed"),
        )
        for field, value in state_fields:
            with self.subTest(field=field):
                hostile = self.snapshot(policy)
                changed = copy.deepcopy(terminal)
                changed["materialized_state"][field] = value
                self.replace_inventory(hostile, "reservations", [changed])
                self.assert_blocked(
                    "reservation-readback-mismatch|reservation-external-id",
                    policy,
                    hostile,
                )

    def test_reservation_identity_time_and_source_substitutions_block(self):
        policy = self.policy()
        cases = (
            ("external", ("external_id",), "wrong", "reservation-external-id", False),
            ("check", ("check_run_id",), 0, "reservation-check-run-id", False),
            ("positive-check-substitution", ("check_run_id",), 701, "reservation-readback-mismatch", False),
            ("readback", ("readback_sha256",), "0" * 64, "reservation-readback-mismatch", False),
            ("future-owner", ("materialized_state", "owner_run_created_at"), "2026-09-07T12:31:00Z", "reservation-owner-created-at-future", True),
            ("future-create", ("materialized_state", "created_at"), "2026-09-07T12:31:00Z", "reservation-created-at-future", True),
            ("source", ("materialized_state", "source_identity", "repository_id"), 1, "reservation-source-identity-drift", True),
        )
        for name, path, value, reason, reseal in cases:
            with self.subTest(name=name):
                snapshot = self.snapshot(policy)
                reservation = self.reservation_record(policy, snapshot)
                self.set_path(reservation, path, value)
                if reseal:
                    self.seal_reservation(reservation)
                self.replace_inventory(snapshot, "reservations", [reservation])
                self.assert_blocked(reason, policy, snapshot)

    def test_reservation_inventory_is_complete_bounded_and_unique(self):
        policy = self.policy()
        snapshot = self.snapshot(policy)
        one = self.reservation_record(
            policy, snapshot, operation_key="2" * 64, check_run_id=701
        )
        two = self.reservation_record(
            policy, snapshot, operation_key="3" * 64, check_run_id=702
        )
        self.replace_inventory(snapshot, "reservations", [one, two], [1, 1])
        first = STATE.classify(policy, snapshot)
        permuted = self.snapshot(policy)
        self.replace_inventory(
            permuted,
            "reservations",
            [two, one],
            [2],
            reverse_pages=True,
        )
        second = STATE.classify(policy, permuted)
        self.assertEqual(
            first["reservation_inventory_sha256"],
            second["reservation_inventory_sha256"],
        )
        duplicate = self.snapshot(policy)
        self.replace_inventory(duplicate, "reservations", [one, copy.deepcopy(one)])
        self.assert_blocked(
            "reservation-inventory-record-duplicate", policy, duplicate
        )

    def cancelled_snapshot(
        self,
        policy,
        *,
        stage,
        terminal_disposition="consumed",
    ):
        snapshot = self.snapshot(policy)
        run = self.first_record(snapshot, "runs")
        run["status"] = "completed"
        run["conclusion"] = "cancelled"
        self.refresh_inventory_semantic(snapshot, "runs")
        if stage is not None:
            reservation = self.reservation_record(
                policy,
                snapshot,
                downstream_state=("succeeded" if stage == "dispatched" else None),
                stage=stage,
                state="cancelled",
                terminal_disposition=terminal_disposition,
            )
            if stage != "reserved":
                self.replace_inventory(
                    snapshot,
                    "history",
                    [
                        self.history_record(
                            policy,
                            self.operation_key(policy, snapshot),
                            dispatch_state=(
                                "pending" if stage == "pr-created" else "succeeded"
                            ),
                        )
                    ],
                )
            self.replace_inventory(snapshot, "reservations", [reservation])
        return snapshot

    def test_cancellation_stages_are_terminal_and_never_successors(self):
        policy = self.policy()
        cases = (
            (None, "consumed", "cancelled-before-reservation"),
            ("reserved", "consumed", "cancelled-after-reservation"),
            ("pr-created", "active", "cancelled-after-pr-create"),
            ("dispatched", "active", "cancelled-after-dispatch"),
        )
        for stage, disposition, reason in cases:
            with self.subTest(stage=stage):
                snapshot = self.cancelled_snapshot(
                    policy,
                    stage=stage,
                    terminal_disposition=disposition,
                )
                result = STATE.classify(policy, snapshot)
                self.assertEqual(disposition, result["disposition"])
                self.assertEqual(reason, result["reason"])
                self.assertNotIn("successor", STATE.canonical(result).decode())

    def attempt_two_snapshot(
        self,
        policy,
        stage="dispatched",
    ):
        snapshot = self.snapshot(policy)
        event = snapshot["event"]
        event["run_attempt"] = 2
        current = self.first_record(snapshot, "runs")
        current["attempt"] = 2
        prior = copy.deepcopy(current)
        prior["attempt"] = 1
        prior["status"] = "completed"
        prior["conclusion"] = "cancelled"
        self.replace_inventory(snapshot, "runs", [prior, current], [1, 1])
        history_dispatch = {
            "dispatched": "succeeded",
            "pr-created": "pending",
            "reserved": None,
        }[stage]
        if history_dispatch is not None:
            self.replace_inventory(
                snapshot,
                "history",
                [
                    self.history_record(
                        policy,
                        self.operation_key(policy, snapshot),
                        dispatch_state=history_dispatch,
                    )
                ],
            )
        orphan = self.reservation_record(
            policy,
            snapshot,
            owner_attempt=1,
            stage=stage,
            state="orphaned",
        )
        self.replace_inventory(snapshot, "reservations", [orphan])
        snapshot["attempt_authorization"] = self.attempt_authorization(
            policy, snapshot, orphan, prior
        )
        return snapshot, orphan

    def test_orphan_requires_exact_immutable_attempt_two_authority(self):
        policy = self.policy()
        snapshot = self.snapshot(policy)
        orphan = self.reservation_record(
            policy,
            snapshot,
            stage="dispatched",
            state="orphaned",
        )
        self.replace_inventory(snapshot, "reservations", [orphan])
        self.assert_blocked(
            "orphan-attempt-2-authority-required", policy, snapshot
        )

        for stage, action in STATE.ATTEMPT2_ACTION_BY_STAGE.items():
            with self.subTest(stage=stage):
                authorized, _ = self.attempt_two_snapshot(policy, stage)
                result = STATE.classify(policy, authorized)
                self.assertEqual("mutate", result["disposition"])
                self.assertEqual("attempt-2-authorized-orphan", result["reason"])
                self.assertEqual(2, result["lease"]["owner_run_attempt"])
                self.assertEqual(700, result["lease"]["check_run_id"])
                self.assertEqual(
                    "attempt-authorization-consume", result["attempt_two_action"]
                )
                self.assertIs(False, result["attempt_authorization_consumed"])
                self.assertEqual(action, result["authorized_after_consume_action"])
                authorization = authorized["attempt_authorization"]
                authorization["used"] = True
                self.seal_attempt_authorization(authorization)
                consumed = STATE.classify(policy, authorized)
                self.assertIs(True, consumed["attempt_authorization_consumed"])
                self.assertEqual(action, consumed["attempt_two_action"])

    def test_complete_history_defers_only_exact_attempt_two_recovery(self):
        policy = self.policy()
        cases = (
            ("pr-created", "pending", "downstream-dispatch"),
            ("dispatched", "pending", "reservation-finalize"),
            ("dispatched", "succeeded", "reservation-finalize"),
        )
        for stage, dispatch_state, recovery_action in cases:
            with self.subTest(stage=stage, dispatch=dispatch_state):
                snapshot, _ = self.attempt_two_snapshot(policy, stage)
                history = self.history_record(
                    policy,
                    self.operation_key(policy, snapshot),
                    dispatch_state=dispatch_state,
                )
                self.replace_inventory(snapshot, "history", [history])
                consume = STATE.classify(policy, snapshot)
                self.assertEqual("mutate", consume["disposition"])
                self.assertEqual(
                    "attempt-authorization-consume", consume["attempt_two_action"]
                )
                self.assertEqual(575, consume["history_pr_number"])
                self.assertEqual(
                    dispatch_state, consume["history_dispatch_state"]
                )
                authorization = snapshot["attempt_authorization"]
                authorization["used"] = True
                self.seal_attempt_authorization(authorization)
                recover = STATE.classify(policy, snapshot)
                self.assertEqual(recovery_action, recover["attempt_two_action"])
                self.assertIs(True, recover["attempt_authorization_consumed"])

    def test_orphan_pr_state_is_exactly_bound_before_authority_consumption(self):
        policy = self.policy()
        for stage, dispatch_state in (
            ("pr-created", "pending"),
            ("dispatched", "pending"),
            ("dispatched", "succeeded"),
        ):
            with self.subTest(stage=stage, dispatch=dispatch_state):
                snapshot, orphan = self.attempt_two_snapshot(policy, stage)
                history = self.history_record(
                    policy,
                    self.operation_key(policy, snapshot),
                    dispatch_state=dispatch_state,
                )
                self.replace_inventory(snapshot, "history", [history])
                orphan["materialized_state"]["pr_state"] = "closed"
                self.seal_reservation(orphan)
                self.replace_inventory(snapshot, "reservations", [orphan])
                predecessor = next(
                    record
                    for page in snapshot["runs"]["pages"]
                    for record in page["records"]
                    if record["attempt"] == 1
                )
                snapshot["attempt_authorization"] = self.attempt_authorization(
                    policy, snapshot, orphan, predecessor
                )
                self.assert_blocked(
                    "reservation-history-pr-state-drift", policy, snapshot
                )

    def test_completed_terminal_history_cross_state_is_exact(self):
        policy = self.policy()
        cases = (
            ("open", "open", None, "active"),
            ("closed", "closed", None, "consumed"),
            (
                "merged",
                "closed",
                "2026-09-07T12:20:00Z",
                "consumed",
            ),
        )
        for pr_state, history_state, merged_at, disposition in cases:
            with self.subTest(pr_state=pr_state):
                snapshot = self.snapshot(policy)
                terminal = self.reservation_record(
                    policy,
                    snapshot,
                    downstream_state="succeeded",
                    pr_state=pr_state,
                    stage="finalized",
                    state="completed",
                    terminal_disposition=disposition,
                )
                history = self.history_record(
                    policy,
                    self.operation_key(policy, snapshot),
                    dispatch_state="succeeded",
                    merged_at=merged_at,
                    state=history_state,
                )
                self.replace_inventory(snapshot, "history", [history])
                self.replace_inventory(snapshot, "reservations", [terminal])
                result = STATE.classify(policy, snapshot)
                self.assertEqual(disposition, result["disposition"])
                self.assertEqual("terminal-reservation", result["reason"])

        hostile = (
            ("closed", "open", None, "consumed"),
            ("open", "closed", None, "active"),
            ("closed", "closed", "2026-09-07T12:20:00Z", "consumed"),
            ("merged", "closed", None, "consumed"),
        )
        for pr_state, history_state, merged_at, disposition in hostile:
            with self.subTest(hostile_pr_state=pr_state, merged_at=merged_at):
                snapshot = self.snapshot(policy)
                terminal = self.reservation_record(
                    policy,
                    snapshot,
                    downstream_state="succeeded",
                    pr_state=pr_state,
                    stage="finalized",
                    state="completed",
                    terminal_disposition=disposition,
                )
                history = self.history_record(
                    policy,
                    self.operation_key(policy, snapshot),
                    merged_at=merged_at,
                    state=history_state,
                )
                self.replace_inventory(snapshot, "history", [history])
                self.replace_inventory(snapshot, "reservations", [terminal])
                self.assert_blocked(
                    "reservation-history-pr-state-drift", policy, snapshot
                )

    def test_terminal_dispatch_and_cancelled_cross_state_fail_closed(self):
        policy = self.policy()

        completed = self.snapshot(policy)
        terminal = self.reservation_record(
            policy,
            completed,
            downstream_state="pending",
            stage="finalized",
            state="completed",
            terminal_disposition="active",
        )
        self.replace_inventory(
            completed,
            "history",
            [self.history_record(policy, self.operation_key(policy, completed))],
        )
        self.replace_inventory(completed, "reservations", [terminal])
        self.assert_blocked(
            "reservation-history-dispatch-drift", policy, completed
        )

        for stage, pr_state, history_state, dispatch_state, disposition in (
            ("pr-created", "closed", "closed", "pending", "consumed"),
            ("dispatched", "closed", "closed", "succeeded", "consumed"),
        ):
            with self.subTest(cancelled_stage=stage):
                snapshot = self.snapshot(policy)
                run = self.first_record(snapshot, "runs")
                run.update(status="completed", conclusion="cancelled")
                self.refresh_inventory_semantic(snapshot, "runs")
                reservation = self.reservation_record(
                    policy,
                    snapshot,
                    downstream_state=(
                        "not-dispatched" if stage == "pr-created" else dispatch_state
                    ),
                    pr_state=pr_state,
                    stage=stage,
                    state="cancelled",
                    terminal_disposition=disposition,
                )
                history = self.history_record(
                    policy,
                    self.operation_key(policy, snapshot),
                    dispatch_state=dispatch_state,
                    state=history_state,
                )
                self.replace_inventory(snapshot, "history", [history])
                self.replace_inventory(snapshot, "reservations", [reservation])
                result = STATE.classify(policy, snapshot)
                self.assertEqual(disposition, result["disposition"])
                self.assertTrue(result["reason"].startswith("cancelled-after-"))

                contradictory = copy.deepcopy(snapshot)
                history = self.history_record(
                    policy,
                    self.operation_key(policy, contradictory),
                    dispatch_state=dispatch_state,
                    state="open",
                )
                self.replace_inventory(contradictory, "history", [history])
                self.assert_blocked(
                    "reservation-history-pr-state-drift", policy, contradictory
                )

    def test_attempt_two_terminal_reservations_short_circuit_without_authority(self):
        policy = self.policy()
        for terminal_state, disposition in (
            ("completed", "active"),
            ("cancelled", "active"),
        ):
            with self.subTest(terminal_state=terminal_state):
                snapshot, _ = self.attempt_two_snapshot(policy, "dispatched")
                snapshot["attempt_authorization"] = None
                terminal = self.reservation_record(
                    policy,
                    snapshot,
                    downstream_state="succeeded",
                    owner_attempt=1,
                    stage=("finalized" if terminal_state == "completed" else "dispatched"),
                    state=terminal_state,
                    terminal_disposition=disposition,
                )
                self.replace_inventory(snapshot, "reservations", [terminal])
                result = STATE.classify(policy, snapshot)
                self.assertEqual("active", result["disposition"])
                expected_reason = (
                    "terminal-reservation"
                    if terminal_state == "completed"
                    else "cancelled-after-dispatch"
                )
                self.assertEqual(expected_reason, result["reason"])

    def test_recovery_history_foreign_terminal_replay_and_ambiguity_block(self):
        policy = self.policy()

        for stage in ("pr-created", "dispatched"):
            with self.subTest(case="missing", stage=stage):
                snapshot, _ = self.attempt_two_snapshot(policy, stage)
                self.replace_inventory(snapshot, "history", [])
                self.assert_blocked(
                    "reservation-history-pr-state-drift", policy, snapshot
                )

        wrong_stage, _ = self.attempt_two_snapshot(policy, "pr-created")
        history = self.history_record(
            policy,
            self.operation_key(policy, wrong_stage),
            dispatch_state="succeeded",
        )
        self.replace_inventory(wrong_stage, "history", [history])
        self.assert_blocked(
            "reservation-history-dispatch-drift", policy, wrong_stage
        )

        failed, _ = self.attempt_two_snapshot(policy, "dispatched")
        history = self.history_record(
            policy,
            self.operation_key(policy, failed),
            dispatch_state="failed",
        )
        self.replace_inventory(failed, "history", [history])
        self.assert_blocked("history-open-dispatch", policy, failed)

        cross_state, orphan = self.attempt_two_snapshot(policy, "dispatched")
        orphan["materialized_state"]["downstream_state"] = "failed"
        self.seal_reservation(orphan)
        self.replace_inventory(cross_state, "reservations", [orphan])
        self.assert_blocked(
            "reservation-history-dispatch-drift", policy, cross_state
        )

        reserved, _ = self.attempt_two_snapshot(policy, "reserved")
        history = self.history_record(
            policy,
            self.operation_key(policy, reserved),
            dispatch_state="pending",
        )
        self.replace_inventory(reserved, "history", [history])
        self.assert_blocked(
            "reservation-history-pr-state-drift", policy, reserved
        )

        foreign, _ = self.attempt_two_snapshot(policy, "pr-created")
        history = self.history_record(
            policy,
            self.operation_key(policy, foreign),
            dispatch_state="pending",
        )
        history["run_id"] = 999
        self.replace_inventory(foreign, "history", [history])
        self.assert_blocked("history-owner-run", policy, foreign)

        replay, _ = self.attempt_two_snapshot(policy, "pr-created")
        operation_key = self.operation_key(policy, replay)
        self.replace_inventory(
            replay,
            "history",
            [
                self.history_record(
                    policy, operation_key, dispatch_state="pending", number=575
                ),
                self.history_record(
                    policy, operation_key, dispatch_state="pending", number=576
                ),
            ],
        )
        self.assert_blocked("history-operation-key-duplicate", policy, replay)

        terminal, orphan = self.attempt_two_snapshot(policy, "dispatched")
        history = self.history_record(
            policy,
            self.operation_key(policy, terminal),
            dispatch_state="succeeded",
            state="closed",
        )
        orphan["materialized_state"]["pr_state"] = "closed"
        self.seal_reservation(orphan)
        self.replace_inventory(terminal, "reservations", [orphan])
        self.replace_inventory(terminal, "history", [history])
        result = STATE.classify(policy, terminal)
        self.assertEqual("consumed", result["disposition"])
        self.assertEqual("terminal-history", result["reason"])
        self.assertNotIn("attempt_two_action", result)

    def test_hostile_attempt_two_authority_and_attempt_three_block(self):
        policy = self.policy()
        authorization = ("attempt_authorization",)
        core = authorization + ("core",)
        cases = (
            ("missing", authorization, None, "attempt-authorization-not-object", False),
            ("used", authorization + ("used",), True, "attempt-authorization-readback-mismatch", False),
            ("issuer", authorization + ("issuer",), "untrusted", "attempt-authorization-issuer", False),
            ("check-id", authorization + ("check_run_id",), 901, "attempt-authorization-readback-mismatch", False),
            ("external-id", authorization + ("external_id",), "wrong", "attempt-authorization-external-id", False),
            ("wrong-state", core + ("state_digest",), "0" * 64, "attempt-authorization-state", True),
            ("wrong-action", core + ("allowed_action",), "downstream-dispatch", "attempt-authorization-action", True),
            ("wrong-prior-intent", core + ("prior_intent_sha256",), "0" * 64, "attempt-authorization-prior-intent", True),
            ("wrong-prior-run", core + ("prior_run_sha256",), "0" * 64, "attempt-authorization-prior-run", True),
            ("expired", core + ("expires_at",), "2026-09-07T12:25:00Z", "attempt-authorization-expired", True),
            ("future", core + ("created_at",), "2026-09-07T12:31:00Z", "attempt-authorization-created-at-future", True),
        )
        for name, path, value, reason, reseal in cases:
            with self.subTest(name=name):
                snapshot, _ = self.attempt_two_snapshot(policy)
                self.set_path(snapshot, path, value)
                if reseal:
                    self.seal_attempt_authorization(snapshot["attempt_authorization"])
                self.assert_blocked(reason, policy, snapshot)

    def test_attempt_two_and_terminal_owner_hostile_replays_block(self):
        policy = self.policy()

        completed, _ = self.attempt_two_snapshot(policy)
        current = next(
            record
            for page in completed["runs"]["pages"]
            for record in page["records"]
            if record["attempt"] == 2
        )
        current.update(status="completed", conclusion="cancelled")
        self.refresh_inventory_semantic(completed, "runs")
        self.assert_blocked("attempt-2-not-running", policy, completed)

        missing, _ = self.attempt_two_snapshot(policy)
        current = next(
            record
            for page in missing["runs"]["pages"]
            for record in page["records"]
            if record["attempt"] == 2
        )
        self.replace_inventory(missing, "runs", [current])
        self.assert_blocked("attempt-2-predecessor-count", policy, missing)

        foreign, orphan = self.attempt_two_snapshot(policy)
        orphan["materialized_state"]["owner_run_id"] = 999
        self.seal_reservation(orphan)
        self.replace_inventory(foreign, "reservations", [orphan])
        self.assert_blocked("reservation-owner-run-count", policy, foreign)

        reclaimed, orphan = self.attempt_two_snapshot(policy)
        orphan["materialized_state"]["owner_run_attempt"] = 2
        self.seal_reservation(orphan)
        self.replace_inventory(reclaimed, "reservations", [orphan])
        self.assert_blocked("orphan-owner-not-predecessor", policy, reclaimed)

        terminal = self.snapshot(policy)
        impossible = self.reservation_record(
            policy,
            terminal,
            downstream_state="unknown",
            pr_state="absent",
            stage="finalized",
            state="completed",
            terminal_disposition="active",
        )
        self.replace_inventory(terminal, "reservations", [impossible])
        self.assert_blocked("completed-terminal-state", policy, terminal)

        foreign_terminal = self.snapshot(policy)
        impossible = self.reservation_record(
            policy,
            foreign_terminal,
            owner_run_id=999,
            stage="finalized",
            state="completed",
            terminal_disposition="active",
        )
        self.replace_inventory(
            foreign_terminal,
            "history",
            [
                self.history_record(
                    policy, self.operation_key(policy, foreign_terminal)
                )
            ],
        )
        self.replace_inventory(foreign_terminal, "reservations", [impossible])
        self.assert_blocked("reservation-owner-run-count", policy, foreign_terminal)

        attempt_three, _ = self.attempt_two_snapshot(policy)
        attempt_three["event"]["run_attempt"] = 3
        self.assert_blocked("event-attempt", policy, attempt_three)


class ReleasePromotionInventoryCollectorTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.counter = 0

    def page_file(self, records):
        self.counter += 1
        path = self.root / f"page-{self.counter}.json"
        raw = INVENTORY.canonical(records)
        path.write_bytes(raw)
        return str(path), len(raw)

    def read(
        self, chunks
    ):
        pages = []
        total = 0
        for number, records in enumerate(chunks, start=1):
            path, size = self.page_file(records)
            total += size
            pages.append(
                {
                    "cursor": None if number == 1 else f"cursor-{number}",
                    "next_cursor": (
                        None
                        if number == len(chunks)
                        else f"cursor-{number + 1}"
                    ),
                    "number": number,
                    "path": path,
                }
            )
        return {"complete": True, "pages": pages}, total

    def manifest(
        self,
        first_chunks,
        second_chunks,
    ):
        first, first_bytes = self.read(first_chunks)
        second, second_bytes = self.read(second_chunks)
        return (
            {
                "reads": [first, second],
                "source": {
                    "endpoint": "actions/workflow-runs",
                    "repository_id": 123456789,
                },
            },
            max(first_bytes, second_bytes),
        )

    @staticmethod
    def run_record(run_id, attempt=1):
        return {
            "attempt": attempt,
            "operation_key": "a" * 64,
            "run_id": run_id,
        }

    def collect(
        self,
        manifest,
        *,
        maximum_bytes=1024,
        maximum_pages=10,
        maximum_records=100,
    ):
        return INVENTORY.collect(
            manifest,
            kind="runs",
            maximum_bytes=maximum_bytes,
            maximum_elapsed_ms=30000,
            maximum_pages=maximum_pages,
            maximum_records=maximum_records,
        )

    def test_two_complete_reads_allow_page_and_record_permutation(self):
        one = self.run_record(1)
        two = self.run_record(2)
        manifest, _ = self.manifest([[one], [two]], [[two, one]])
        result = self.collect(manifest)
        self.assertEqual(2, result["read_count"])
        self.assertEqual(2, result["page_count"])
        self.assertEqual(2, result["record_count"])
        self.assertEqual(
            INVENTORY.digest(
                {
                    "records": sorted([one, two], key=INVENTORY.canonical),
                    "source": manifest["source"],
                }
            ),
            result["semantic_sha256"],
        )

    def test_actual_bytes_pages_and_records_have_exact_boundaries(self):
        one = self.run_record(1)
        two = self.run_record(2)
        manifest, exact_bytes = self.manifest([[one], [two]], [[two], [one]])
        result = self.collect(
            manifest,
            maximum_bytes=exact_bytes,
            maximum_pages=2,
            maximum_records=2,
        )
        self.assertEqual(exact_bytes, result["response_bytes"])
        for field, kwargs, reason in (
            ("bytes", {"maximum_bytes": exact_bytes - 1}, "page-byte-limit|inventory-byte-limit"),
            ("pages", {"maximum_pages": 1}, "inventory-page-limit"),
            ("records", {"maximum_records": 1}, "inventory-record-limit"),
        ):
            with self.subTest(field=field):
                with self.assertRaisesRegex(INVENTORY.ContractError, reason):
                    self.collect(manifest, **kwargs)

    def test_incomplete_unstable_duplicate_and_symlink_pages_block(self):
        record = self.run_record(1)
        other = self.run_record(2)
        incomplete, _ = self.manifest([[record]], [[record]])
        incomplete["reads"][1]["complete"] = False
        with self.assertRaisesRegex(
            INVENTORY.ContractError, "inventory-read-incomplete"
        ):
            self.collect(incomplete)

        unstable, _ = self.manifest([[record]], [[other]])
        with self.assertRaisesRegex(INVENTORY.ContractError, "inventory-unstable"):
            self.collect(unstable)

        duplicate, _ = self.manifest(
            [[record, copy.deepcopy(record)]],
            [[record, copy.deepcopy(record)]],
        )
        with self.assertRaisesRegex(
            INVENTORY.ContractError, "inventory-record-duplicate"
        ):
            self.collect(duplicate)

        linked, _ = self.manifest([[record]], [[record]])
        page = linked["reads"][0]["pages"][0]
        original = Path(page["path"])
        symlink = self.root / "linked-page.json"
        symlink.symlink_to(original)
        page["path"] = str(symlink)
        with self.assertRaisesRegex(INVENTORY.ContractError, "page-not-regular"):
            self.collect(linked)

    def test_raw_duplicate_page_keys_block_before_normalization(self):
        path = self.root / "duplicate-page.json"
        path.write_text(
            '[{"attempt":1,"run_id":1,"run_id":2}]', encoding="utf-8"
        )
        with self.assertRaisesRegex(
            INVENTORY.ContractError, "page-duplicate-key"
        ):
            INVENTORY.load_json(str(path), 1024)

    def test_noncanonical_page_encoding_blocks(self):
        path = self.root / "noncanonical-page.json"
        for raw in ('[{"run_id": 1}]\n', "NaN\n"):
            with self.subTest(raw=raw):
                path.write_text(raw, encoding="utf-8")
                with self.assertRaisesRegex(
                    INVENTORY.ContractError, "page-not-canonical-json"
                ):
                    INVENTORY.load_json(str(path), 1024)

    def test_page_stat_error_has_a_stable_contract_reason(self):
        for error in (FileNotFoundError(2, "OS-SENTINEL", "/private/sentinel"),
                      PermissionError(13, "OS-SENTINEL", "/private/sentinel")):
            with self.subTest(error=type(error).__name__), mock.patch.object(
                INVENTORY.Path, "lstat", side_effect=error
            ), self.assertRaises(INVENTORY.ContractError) as caught:
                INVENTORY.load_json("/private/sentinel", 1024)
            self.assertEqual("page-stat-failed", str(caught.exception))

    def test_exactly_two_reads_and_complete_cursor_chain_are_mandatory(self):
        record = self.run_record(1)
        manifest, _ = self.manifest([[record]], [[record]])
        manifest["reads"] = manifest["reads"][:1]
        with self.assertRaisesRegex(INVENTORY.ContractError, "stable-read-count"):
            self.collect(manifest)
        truncated, _ = self.manifest(
            [[record], [self.run_record(2)]],
            [[record], [self.run_record(2)]],
        )
        truncated["reads"][0]["pages"][0]["next_cursor"] = None
        with self.assertRaisesRegex(
            INVENTORY.ContractError, "inventory-cursor-truncated"
        ):
            self.collect(truncated)


class ReleasePromotionHistoryCollectorTests(unittest.TestCase):
    operation_key = "a" * 64

    def run_history(self, pages, *, api_failure=False, deadline=5,
                    max_bytes=1048576, max_pages=10, max_records=100,
                    runner_temp_kind="valid", sleep_seconds=0):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        output = root / "output"
        output.write_text("", encoding="utf-8")
        fake_gh = root / "gh"
        fake_gh.write_text(
            """#!/usr/bin/env bash
set -e
test "$*" = "api --paginate --slurp repos/lightning-it/.github/pulls?state=all&per_page=100"
if [ "$HISTORY_API_FAILURE" = true ]; then exit 42; fi
if [ "$HISTORY_SLEEP_SECONDS" -gt 0 ]; then sleep "$HISTORY_SLEEP_SECONDS"; fi
printf '%s\n' "$HISTORY_PAGES"
""",
            encoding="utf-8",
        )
        fake_gh.chmod(0o755)
        runner_temp = temporary.name
        if runner_temp_kind == "unset":
            runner_temp = None
        elif runner_temp_kind == "relative":
            runner_temp = "relative-runner-temp"
        elif runner_temp_kind == "missing":
            runner_temp = str(root / "missing-runner-temp")
        elif runner_temp_kind == "symlink":
            target = root / "runner-temp-target"
            target.mkdir(mode=0o700)
            linked = root / "runner-temp-link"
            linked.symlink_to(target, target_is_directory=True)
            runner_temp = str(linked)
        elif runner_temp_kind == "unsafe-mode":
            unsafe = root / "unsafe-runner-temp"
            unsafe.mkdir(mode=0o700)
            unsafe.chmod(0o777)
            runner_temp = str(unsafe)
        elif runner_temp_kind != "valid":
            raise AssertionError(f"unknown runner temp kind: {runner_temp_kind}")
        environment = {
            **os.environ,
            "EXPECTED_BASE_SHA": "1" * 40,
            "EXPECTED_HEAD_SHA": "2" * 40,
            "GH_TOKEN": "read-only-fixture-token",
            "GITHUB_OUTPUT": str(output),
            "HISTORY_API_FAILURE": "true" if api_failure else "false",
            "HISTORY_DEADLINE_SECONDS": str(deadline),
            "HISTORY_MAX_BYTES": str(max_bytes),
            "HISTORY_MAX_PAGES": str(max_pages),
            "HISTORY_MAX_RECORDS": str(max_records),
            "HISTORY_PAGES": json.dumps(pages, separators=(",", ":")),
            "HISTORY_SLEEP_SECONDS": str(sleep_seconds),
            "OPERATION_KEY": self.operation_key,
            "OWNER_RUN_ATTEMPT": "1",
            "OWNER_RUN_ID": "12345",
            "PATH": f"{root}:{os.environ['PATH']}",
            "REPOSITORY": "lightning-it/.github",
        }
        if runner_temp is not None:
            environment["RUNNER_TEMP"] = runner_temp
        else:
            environment.pop("RUNNER_TEMP", None)
        result = subprocess.run(["bash", "scripts/release-promotion-history.sh"],
            cwd=ROOT, text=True, capture_output=True, check=False,
            env=environment,
        )
        outputs = dict(line.split("=", 1)
                       for line in output.read_text(encoding="utf-8").splitlines())
        return result, outputs

    def test_collector_requires_a_private_absolute_runner_temp(self):
        cases = (
            ("unset", "required"),
            ("relative", "absolute"),
            ("missing", "real directory"),
            ("symlink", "real directory"),
            ("unsafe-mode", "group- or world-writable"),
        )
        for kind, message in cases:
            with self.subTest(kind=kind):
                result, outputs = self.run_history(
                    [[]], runner_temp_kind=kind
                )
                self.assertNotEqual(0, result.returncode)
                self.assertEqual("blocked", outputs["disposition"])
                self.assertIn(message, result.stderr)

    def promotion_record(self, *, dispatch="succeeded", number=575,
                         operation_key=None, run_id=12345, state="open"):
        operation_key = operation_key or self.operation_key
        return {
            "base": {"ref": "main", "repo": {"full_name": "lightning-it/.github"},
                     "sha": "1" * 40},
            "body": "\n".join((f"<!-- lit-promotion-head:{'2' * 40} -->",
                                f"<!-- lit-promotion-operation:{operation_key} -->",
                                f"<!-- lit-promotion-run:{run_id}:1 -->",
                                f"<!-- lit-promotion-dispatch-{dispatch}:{'1' * 40}:{'2' * 40} -->")),
            "draft": False,
            "head": {"ref": "develop", "repo": {"full_name": "lightning-it/.github"},
                     "sha": "2" * 40},
            "merged_at": None,
            "number": number,
            "state": state,
            "title": "chore(release): promote develop to main",
            "user": {"login": "lightning-it-release-automation[bot]"},
        }

    def test_collector_is_read_only_bounded_and_page_order_invariant(self):
        empty, outputs = self.run_history([[]])
        self.assertEqual(0, empty.returncode, empty.stderr)
        self.assertEqual("mutate", outputs["disposition"])
        record = self.promotion_record()
        one, one_outputs = self.run_history([[record]])
        multiple, multiple_outputs = self.run_history([[], [record]])
        self.assertEqual(0, one.returncode, one.stderr)
        self.assertEqual(0, multiple.returncode, multiple.stderr)
        self.assertEqual("active", one_outputs["disposition"])
        self.assertEqual(one_outputs["history_sha256"], multiple_outputs["history_sha256"])
        source = (ROOT / CORE_HELPERS[0]).read_text(encoding="utf-8")
        self.assertNotIn("--method", source)
        self.assertNotIn("gh pr ", source)
        self.assertIn("HISTORY_MAX_BYTES", source)
        self.assertIn("HISTORY_MAX_PAGES", source)
        self.assertIn("HISTORY_MAX_RECORDS", source)
        self.assertIn("HISTORY_DEADLINE_SECONDS", source)

    def test_collector_accepts_exact_byte_limit_and_blocks_limit_plus_one(self):
        pages = [[]]
        payload_bytes = len((json.dumps(pages, separators=(",", ":")) + "\n").encode())
        exact, _ = self.run_history(pages, max_bytes=payload_bytes)
        self.assertEqual(0, exact.returncode, exact.stderr)
        over, outputs = self.run_history(pages, max_bytes=payload_bytes - 1)
        self.assertNotEqual(0, over.returncode)
        self.assertEqual("blocked", outputs["disposition"])
        self.assertIn("raw-byte bound", over.stderr)

    def test_collector_page_record_deadline_and_api_bounds_block(self):
        record = self.promotion_record()
        cases = (
            ("page", lambda: self.run_history([[], [record]], max_pages=1), "page bound"),
            ("record", lambda: self.run_history([[record, self.promotion_record(number=576)]],
                                                 max_records=1), "record bound"),
            ("deadline", lambda: self.run_history([[]], deadline=1, sleep_seconds=2),
             "unavailable or timed out"),
            ("api", lambda: self.run_history([[]], api_failure=True), "unavailable or timed out"),
        )
        for name, invoke, message in cases:
            with self.subTest(name=name):
                result, outputs = invoke()
                self.assertNotEqual(0, result.returncode)
                self.assertEqual("blocked", outputs["disposition"])
                self.assertIn(message, result.stderr)

    def test_operation_and_owner_markers_are_exact(self):
        for record in (
            self.promotion_record(operation_key="b" * 64),
            self.promotion_record(run_id=999),
        ):
            with self.subTest(body=record["body"]):
                result, outputs = self.run_history([[record]])
                self.assertNotEqual(0, result.returncode)
                self.assertEqual("blocked", outputs["disposition"])


class ReleasePromotionInertBoundaryTests(unittest.TestCase):
    def test_helpers_are_regular_nonexecutable_and_unreferenced(self):
        workflows = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted((ROOT / ".github/workflows").glob("*.y*ml"))
        )
        for relative_path in CORE_HELPERS:
            with self.subTest(path=relative_path):
                helper = ROOT / relative_path
                self.assertTrue(helper.is_file())
                self.assertFalse(helper.is_symlink())
                self.assertEqual(0o644, helper.stat().st_mode & 0o777)
                self.assertNotIn(Path(relative_path).name, workflows)
        self.assertNotIn(POLICY_PATH.name, workflows)

    def test_deterministic_classifiers_have_no_network_or_process_client(
        self,
    ):
        forbidden = (
            "import requests",
            "import socket",
            "import subprocess",
            "urllib",
            "gh api",
            "curl ",
        )
        for path in (INVENTORY_PATH, STATE_PATH):
            source = path.read_text(encoding="utf-8")
            with self.subTest(path=path.name):
                for token in forbidden:
                    self.assertNotIn(token, source)

    def test_binder_names_every_runtime_input_and_binds_one_digest(self):
        binder = (
            ROOT / "scripts/release-promotion-preflight-bind.sh"
        ).read_text(encoding="utf-8")
        for path in STATE.RUNTIME_INPUT_PATHS:
            with self.subTest(path=path):
                self.assertIn(path, binder)
        self.assertNotIn("scripts/release-promotion-write-once.py", binder)
        self.assertIn("ADMITTED_RUNTIME_INPUTS_SHA256", binder)
        self.assertIn("REVALIDATED_RUNTIME_INPUTS_SHA256", binder)
        self.assertIn('test "${mode}" = 100644', binder)

    def test_shell_admission_is_first_attempt_and_review_bounded(self):
        preflight = (ROOT / "scripts/release-promotion-preflight.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn('[ "${EVENT_NAME}" = push ]', preflight)
        self.assertIn('[ "${RUN_ATTEMPT}" = 1 ]', preflight)
        self.assertIn('[ "${promotion_patch_bytes}" -lt 200000 ]', preflight)
        self.assertIn('[ "${promotion_patch_bytes}" -eq 0 ]', preflight)
        self.assertIn("unset GH_TOKEN GITHUB_TOKEN", preflight)
        self.assertNotIn("${RUNNER_TEMP:-/tmp}", preflight)
        self.assertEqual(3, preflight.count('mktemp "${RUNNER_TEMP}/'))
        self.assertIn("validate_runner_temp", preflight)
        self.assertIn('projection_listing_file=""', preflight)
        self.assertIn('projection_file=""', preflight)
        self.assertIn('[ -n "${GITHUB_STEP_SUMMARY:-}" ]', preflight)

        history = (
            ROOT / "scripts/release-promotion-history.sh"
        ).read_text(encoding="utf-8")
        dependency_contracts = (
            (history, {"awk", "gh", "head", "jq", "mktemp", "rm",
                       "sha256sum", "stat", "timeout", "wc"}),
            (preflight, {"awk", "git", "grep", "jq", "mktemp", "rm",
                         "sha256sum", "stat", "tr", "wc"}),
        )
        for source, expected_commands in dependency_contracts:
            guard = next(
                line for line in source.splitlines()
                if line.startswith("for command_name in ")
            )
            declared_commands = set(
                guard.removeprefix("for command_name in ")
                .removesuffix("; do")
                .split()
            )
            self.assertEqual(expected_commands, declared_commands)

    def test_shell_guards_fail_closed_with_explicit_diagnostics(self):
        for script, diagnostic in (
            ("release-promotion-preflight.sh", "requires a GitHub output path"),
            ("release-promotion-preflight-revalidate.sh", "revalidation revision is malformed"),
        ):
            with self.subTest(script=script):
                result = subprocess.run(
                    ["bash", f"scripts/{script}"], cwd=ROOT, text=True,
                    capture_output=True, env={"PATH": os.environ["PATH"]},
                )
                self.assertNotEqual(0, result.returncode)
                self.assertIn(diagnostic, result.stderr)
                self.assertNotIn("unbound variable", result.stderr)
        source = (ROOT / "scripts/release-promotion-preflight-revalidate.sh").read_text()
        self.assertEqual(7, source.count("|| fail_closed"))
        for diagnostic in "admitted controller blob is malformed|admitted controller tree entry is unreadable|admitted controller tree binding does not match|local controller is not a regular non-symlink file|local controller bytes are unreadable|local controller bytes do not match the admitted blob".split("|"):
            self.assertIn(diagnostic, source)


if __name__ == "__main__":
    unittest.main()
