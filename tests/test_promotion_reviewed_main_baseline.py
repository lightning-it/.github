from __future__ import annotations

import importlib.util
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parents[1] / "scripts" / "verify-promotion-evidence.py"
)
SPEC = importlib.util.spec_from_file_location("reviewed_main_baseline", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ReviewedMainIngressBaselineTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.repository = Path(temporary.name).resolve()
        self.environment = {
            name: value
            for name, value in os.environ.items()
            if not name.startswith("GIT_")
        }
        self.environment.update(
            {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}
        )
        self.git("init", "--quiet", "-b", "develop")
        self.write("policy", "old\n")
        self.previous = self.commit("protected develop")
        self.git("checkout", "--quiet", "--orphan", "unrelated")
        self.git("rm", "--quiet", "--force", "policy")
        self.write("unrelated", "separate history\n")
        self.unrelated = self.commit("unrelated protected revision")
        self.git("checkout", "--quiet", "-b", "main", self.previous)
        self.write("release", "published\n")
        self.main = self.commit("protected main")
        self.git("checkout", "--quiet", "-b", "feature")
        self.write("policy", "reviewed\n")
        self.head = self.commit("reviewed feature based on main")
        self.git("checkout", "--quiet", "develop")
        self.git("merge", "--quiet", "--no-ff", "feature", "-m", "protected merge")
        self.merge = self.git("rev-parse", "HEAD")
        self.pull = {
            "title": "fix(policy): reviewed current-main ingress",
            "user": {"login": "litroc", "id": 76040632, "type": "User"},
            "head": {"ref": "fix/reviewed-current-main"},
        }

    def git(self, *arguments: str) -> str:
        return subprocess.check_output(
            [
                "git",
                "-c",
                "user.name=test",
                "-c",
                "user.email=test@example.test",
                *arguments,
            ],
            cwd=self.repository,
            env=self.environment,
            text=True,
            stderr=subprocess.PIPE,
        ).strip()

    def write(self, path: str, value: str) -> None:
        (self.repository / path).write_text(value, encoding="utf-8")

    def commit(self, message: str) -> str:
        self.git("add", "--all")
        self.git("commit", "--quiet", "-m", message)
        return self.git("rev-parse", "HEAD")

    def validate(self, *, merge_sha: str | None = None) -> None:
        MODULE.validate_reviewed_main_ingress_baseline(
            self.repository,
            repository="lightning-it/example",
            expected_main=self.main,
            merge={
                "base_sha": self.previous,
                "head_sha": self.head,
                "merge_sha": merge_sha or self.merge,
            },
            pull=self.pull,
        )

    def test_reviewed_feature_head_can_supply_current_main_ancestry(self) -> None:
        self.validate()
        self.assertEqual(
            "copilot",
            MODULE.expected_evidence_kind(self.pull, repository="lightning-it/example"),
        )

    def test_automation_identity_cannot_claim_normal_reviewed_baseline(self) -> None:
        self.pull["user"] = {
            "login": MODULE.RELEASE_APP_LOGIN,
            "id": MODULE.RELEASE_APP_ID,
            "type": "Bot",
        }
        with self.assertRaisesRegex(
            MODULE.EvidenceError, "reviewed-main-baseline-review-kind"
        ):
            self.validate()

    def test_baseline_requires_exact_main_introduction(self) -> None:
        original = self.previous
        self.previous = self.main
        with self.assertRaisesRegex(
            MODULE.EvidenceError, "reviewed-main-baseline-main-introduction"
        ):
            self.validate()
        self.previous = original
        self.main = self.unrelated
        with self.assertRaisesRegex(
            MODULE.EvidenceError, "reviewed-main-baseline-main-introduction"
        ):
            self.validate()

    def test_merge_resolution_cannot_change_reviewed_head_tree(self) -> None:
        self.write("policy", "unreviewed merge resolution\n")
        changed_merge = self.commit("change merge result")
        with self.assertRaisesRegex(
            MODULE.EvidenceError, "reviewed-main-baseline-merge-tree-differs"
        ):
            self.validate(merge_sha=changed_merge)


if __name__ == "__main__":
    unittest.main()
