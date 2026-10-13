"""Execute the protected-source binder with read-only native API fixtures."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import subprocess
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/supplementary-current-revision-required.yml"
BASE = "8bbbbeaa5bec36034fceebc029ec6c327d87bd5c"
HEAD = "13fe6c651c2c8ef807c196755915de8331d26f3a"
SOURCE = "2" * 40
ANCHOR = "18f65689d3b6ea6ad8f1da72b662d2f212fc0411"


class Pr831ControllerSourceTests(unittest.TestCase):
    def setUp(self):
        workflow = WORKFLOW.read_text()
        self.helper = textwrap.dedent(workflow.split(
            "# pr831-protected-default-source: start\n", 1
        )[1].split("# pr831-protected-default-source: end", 1)[0])
        self.values = {
            "REPOSITORY": "lightning-it/.github", "PR_NUMBER": "831",
            "EVENT_BASE": BASE, "EVENT_HEAD": HEAD,
            "EVENT_SENDER_LOGIN": "litroc", "EVENT_SENDER_ID": "76040632",
            "EVENT_SENDER_TYPE": "User", "WORKFLOW_SHA": SOURCE,
            "WORKFLOW_REF": "lightning-it/.github/.github/workflows/supplementary-current-revision-required.yml@refs/heads/develop",
        }
        self.records = {
            "REPO": {"full_name": "lightning-it/.github", "default_branch": "develop",
                     "archived": False, "disabled": False},
            "DEVELOP": {"name": "develop", "protected": True, "commit": {"sha": SOURCE}},
            "MAIN": {"name": "main", "protected": True, "commit": {"sha": BASE}},
            "PR": {"number": 831, "state": "open", "draft": False,
                   "user": {"login": "litroc", "id": 76040632, "type": "User"},
                   "base": {"ref": "main", "sha": BASE, "repo": {"full_name": "lightning-it/.github"}},
                   "head": {"ref": "fix/promotion-pr724-receipt", "sha": HEAD,
                            "repo": {"full_name": "lightning-it/.github"}},
                   "changed_files": 4, "commits": 1},
            "ANCESTRY": {"base_commit": {"sha": ANCHOR}, "merge_base_commit": {"sha": ANCHOR},
                         "behind_by": 0, "status": "ahead", "total_commits": 1,
                         "ahead_by": 1, "commits": [{"sha": SOURCE}]},
        }

    def execute(self):
        fake_api = '''
gh() {
  test "$1" = api || return 1
  case "$2" in
    repos/lightning-it/.github) printf '%s' "$FIXTURE_REPO" ;;
    repos/lightning-it/.github/branches/develop) printf '%s' "$FIXTURE_DEVELOP" ;;
    repos/lightning-it/.github/branches/main) printf '%s' "$FIXTURE_MAIN" ;;
    repos/lightning-it/.github/pulls/831) printf '%s' "$FIXTURE_PR" ;;
    repos/lightning-it/.github/compare/*) printf '%s' "$FIXTURE_ANCESTRY" ;;
    *) return 1 ;;
  esac
}
'''
        environment = dict(os.environ, **self.values)
        environment.update({f"FIXTURE_{key}": json.dumps(value)
                            for key, value in self.records.items()})
        return subprocess.run(["bash", "-c", "set -euo pipefail\n" + fake_api
                               + self.helper + "\npr831_protected_default_source\n"],
                              env=environment, capture_output=True, text=True, timeout=10).returncode

    def test_exact_main_repair_accepts_protected_default_controller(self):
        self.assertEqual(self.execute(), 0)

    def test_other_event_tuple_or_controller_reference_is_rejected(self):
        for field, value in (("REPOSITORY", "lightning-it/other"), ("PR_NUMBER", "832"),
                             ("EVENT_BASE", "1" * 40), ("EVENT_HEAD", "3" * 40),
                             ("EVENT_SENDER_LOGIN", "attacker"), ("EVENT_SENDER_ID", "1"),
                             ("EVENT_SENDER_TYPE", "Bot"),
                             ("WORKFLOW_REF", "candidate/workflow@refs/heads/fix"),
                             ("WORKFLOW_SHA", "4" * 40)):
            with self.subTest(field=field):
                original = self.values[field]
                self.values[field] = value
                self.assertNotEqual(self.execute(), 0)
                self.values[field] = original

    def test_live_source_target_and_pr_drift_fail_closed(self):
        original = copy.deepcopy(self.records)
        for record, path, value in (
            ("REPO", ("default_branch",), "main"), ("REPO", ("disabled",), True),
            ("DEVELOP", ("protected",), False), ("DEVELOP", ("commit", "sha"), "4" * 40),
            ("MAIN", ("protected",), False), ("MAIN", ("commit", "sha"), "1" * 40),
            ("PR", ("state",), "closed"), ("PR", ("draft",), True),
            ("PR", ("user", "id"), 1), ("PR", ("user", "type"), "Bot"),
            ("PR", ("base", "ref"), "develop"), ("PR", ("head", "sha"), "3" * 40),
            ("PR", ("head", "repo", "full_name"), "attacker/.github"),
            ("PR", ("head", "ref"), "fix/other"), ("PR", ("changed_files",), 5),
            ("ANCESTRY", ("merge_base_commit", "sha"), "1" * 40),
            ("ANCESTRY", ("behind_by",), 1), ("ANCESTRY", ("status",), "diverged"),
            ("ANCESTRY", ("commits",), [{"sha": "4" * 40}]),
            ("ANCESTRY", ("commits",), []), ("ANCESTRY", ("total_commits",), 101),
            ("ANCESTRY", ("total_commits",), "1"), ("ANCESTRY", ("ahead_by",), 2),
        ):
            with self.subTest(record=record, path=path):
                self.records = copy.deepcopy(original)
                target = self.records[record]
                for part in path[:-1]:
                    target = target[part]
                target[path[-1]] = value
                self.assertNotEqual(self.execute(), 0)

    def test_final_acceptance_reuses_the_same_live_source_validator(self):
        workflow = WORKFLOW.read_text()
        final = workflow.split("- name: Rebind and finalize the protected result", 1)[1]
        self.assertIn("steps.protected-source.outputs.pr831_main_repair", final)
        self.assertIn('source "${RUNNER_TEMP}/pr831-protected-default-source.sh"', final)
        self.assertIn("pr831_protected_default_source", final)
        self.assertLess(final.index("pr831_protected_default_source"), final.index('final_pr="$(gh api'))


if __name__ == "__main__":
    unittest.main()
