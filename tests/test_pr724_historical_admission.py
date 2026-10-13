"""Authenticate the owner-approved historical receipt at the real verifier entry."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest
from unittest import mock

from test_promotion_evidence import MODULE

FIXTURE = Path(__file__).parent / "fixtures" / "pr724-historical-admission.json"
BASE = "94dff2e6880afb7821441ab4c4b8bbd64dc3b6ac"
HEAD = "7daee000ad2bdda7928f803906c592f7e374f08c"
MERGE = "89869f9e2a987fd59706863c04b46da8d5a693bc"


class Pr724HistoricalAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.records = json.loads(FIXTURE.read_text())
        self.arguments = {
            "repository": "lightning-it/.github", "pull": self.records["pull"],
            "pull_number": 724, "base_sha": BASE, "head_sha": HEAD,
            "producer_run_id": 38336319411,
        }

    def api(self, arguments):
        route = arguments[-1].removeprefix("repos/lightning-it/.github/")
        names = {
            "actions/runs/38336319411": "run",
            "actions/runs/38336319411/attempts/2/jobs?per_page=100": "jobs",
            "actions/runs/38336320280": "quality",
            "actions/runs/38336320280/attempts/1/jobs?per_page=100": "quality-jobs",
            f"commits/{HEAD}": "head", f"commits/{MERGE}": "merge",
            f"compare/{BASE}...{HEAD}": "compare",
        }
        self.assertIn(route, names)
        self.assertEqual(arguments[0], "api")
        return self.records[names[route]]

    def admission(self):
        with mock.patch.object(MODULE, "gh_json", side_effect=self.api):
            return MODULE.validate_pr724_historical_admission(
                self.records["check"], **self.arguments
            )

    def test_native_receipt_passes_real_bound_review_entry_and_marks_exception(self):
        with mock.patch.object(MODULE, "gh_json", side_effect=self.api):
            receipt = MODULE.bound_review_check(
                [{"check_runs": [self.records["check"]]}],
                repository=self.arguments["repository"], pull=self.records["pull"],
                pull_number=724, base_sha=BASE, head_sha=HEAD,
            )
        self.assertEqual(receipt["check_id"], 115097708345)
        self.assertEqual(receipt["historical_exception"],
                         "owner-authorized-pr724-three-timeouts-2026-10-13")
        self.assertEqual(receipt["historical_findings_count"], 0)

    def test_other_repository_pr_revision_or_producer_cannot_use_receipt(self):
        for field, value in (("repository", "lightning-it/other"), ("pull_number", 725),
                             ("base_sha", "1" * 40), ("head_sha", "2" * 40),
                             ("producer_run_id", 38336319412)):
            with self.subTest(field=field):
                original = self.arguments[field]
                self.arguments[field] = value
                with self.assertRaises(MODULE.EvidenceError):
                    self.admission()
                self.arguments[field] = original

    def test_mutated_native_contract_fails_closed(self):
        mutations = [
            ("pull", ("number",), 725), ("pull", ("state",), "open"),
            ("pull", ("merge_commit_sha",), "3" * 40),
            ("pull", ("merged_at",), "2026-10-13T02:34:36Z"),
            ("pull", ("user", "id"), 1), ("pull", ("user", "type"), "User"),
            ("pull", ("head", "repo", "full_name"), "attacker/.github"),
            ("check", ("id",), 115097708346), ("check", ("conclusion",), "failure"),
            ("check", ("app", "id"), 1), ("check", ("head_sha",), "2" * 40),
            ("check", ("completed_at",), "2026-10-13T03:00:00Z"),
            ("run", ("actor", "login"), "attacker"), ("run", ("actor", "id"), 1),
            ("run", ("actor", "type"), "Bot"),
            ("run", ("triggering_actor", "login"), "attacker"),
            ("run", ("run_attempt",), 1), ("run", ("run_attempt",), 3),
            ("run", ("id",), 38336319411.0),
            ("run", ("actor", "id"), 76040632.0),
            ("run", ("conclusion",), "failure"), ("run", ("head_sha",), "2" * 40),
            ("run", ("repository", "full_name"), "attacker/.github"),
            ("jobs", ("total_count",), 5),
            ("jobs", ("jobs", 0, "run_id"), 38336319411.0),
            ("jobs", ("jobs", 0, "conclusion"), "failure"),
            ("jobs", ("jobs", 1, "id"), 115097581154),
            ("jobs", ("jobs", 2, "conclusion"), "success"),
            ("quality", ("conclusion",), "failure"),
            ("quality", ("run_attempt",), True),
            ("quality-jobs", ("jobs", 0, "run_attempt"), True),
            ("quality-jobs", ("jobs", 0, "head_sha"), "2" * 40),
            ("merge", ("parents", 0, "sha"), HEAD),
            ("merge", ("commit", "tree", "sha"), "3" * 40),
            ("compare", ("merge_base_commit", "sha"), "1" * 40),
            ("compare", ("behind_by",), False),
            ("compare", ("files", 0, "filename"), "unrelated.yml"),
            ("compare", ("files", 0, "patch"), "changed timeout"),
            ("compare", ("files", 1, "additions"), True),
            ("compare", ("files", 1, "deletions"), False),
        ]
        original = copy.deepcopy(self.records)
        for record, path, value in mutations:
            with self.subTest(record=record, path=path, value=value):
                self.records = copy.deepcopy(original)
                self.arguments["pull"] = self.records["pull"]
                target = self.records[record]
                for part in path[:-1]:
                    target = target[part]
                target[path[-1]] = value
                with self.assertRaises(MODULE.EvidenceError):
                    self.admission()

    def test_missing_or_extra_summary_fields_are_rejected(self):
        original = json.loads(self.records["check"]["output"]["summary"])
        for altered in (dict(original, extra=True), {k: v for k, v in original.items() if k != "controller_sha"}):
            with self.subTest(summary=altered):
                self.records["check"]["output"]["summary"] = json.dumps(altered)
                with self.assertRaises(MODULE.EvidenceError):
                    self.admission()


if __name__ == "__main__":
    unittest.main()
