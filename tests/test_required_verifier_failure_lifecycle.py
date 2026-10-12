"""Exercise the real reservation finalizers, including explicit shell exits."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


class RequiredVerifierFailureLifecycleTests(unittest.TestCase):
    @staticmethod
    def production_finalizers() -> list[str]:
        workflow = yaml.safe_load(
            (
                ROOT / ".github/workflows/supplementary-current-revision-required.yml"
            ).read_text()
        )
        scripts = [
            step.get("run", "")
            for job in workflow["jobs"].values()
            for step in job.get("steps", [])
        ]
        traps = [
            line.strip()
            for script in scripts
            for line in script.splitlines()
            if line.strip().startswith("trap finalize_failure ")
        ]
        if len(traps) != 2:
            raise AssertionError("Both owned reservation traps must remain present")
        finalizers = []
        for script in scripts:
            if "finalize_failure() {" not in script:
                continue
            start = script.index("finalize_failure() {")
            end = script.index("\n}", start) + 2
            finalizers.append(script[start:end] + "\n" + traps[len(finalizers)])
        if len(finalizers) != 2:
            raise AssertionError(
                "Both protected reservation finalizers must be exercised"
            )
        return finalizers

    def exercise(self, finalizer: str, terminal: str) -> tuple[int, list[str], str]:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            script = directory / "fixture.sh"
            # The fake API records mutation arguments only. It provides no proof,
            # review acceptance, or success result for the protected controller.
            script.write_text(
                "set -euo pipefail\n"
                "gh() { printf '%s\\n' \"$@\" >mutation.txt; }\n"
                "reservation_id=1001\nRESERVATION_ID=1001\n"
                "failure_stage=permanent-producer-inventory\n"
                + finalizer
                + "\n"
                + terminal
                + "\n"
            )
            result = subprocess.run(
                ["bash", str(script)],
                cwd=directory,
                env={
                    **os.environ,
                    "REPOSITORY": "lightning-it/.github",
                    "PR_NUMBER": "820",
                    "EVENT_HEAD": "a" * 40,
                },
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )
            record = directory / "mutation.txt"
            return (
                result.returncode,
                record.read_text().splitlines() if record.exists() else [],
                result.stdout + result.stderr,
            )

    def assert_failure(self, finalizer: str, terminal: str, expected_code: int) -> None:
        code, mutation, output = self.exercise(finalizer, terminal)
        self.assertEqual(code, expected_code, output)
        self.assertEqual(
            mutation[:4],
            ["api", "--method", "PATCH", "repos/lightning-it/.github/check-runs/1001"],
        )
        self.assertIn("status=completed", mutation)
        self.assertIn("conclusion=failure", mutation)
        self.assertNotIn("conclusion=success", mutation)
        self.assertIn("stage permanent-producer-inventory", " ".join(mutation))
        # No raw producer document or credential is present in this controlled fixture.
        self.assertNotIn("PRIVATE_CANARY", json.dumps(mutation) + output)

    def test_explicit_failure_exit_completes_both_owned_reservations(self):
        for finalizer in self.production_finalizers():
            with self.subTest(finalizer=finalizer[:45]):
                self.assert_failure(finalizer, "exit 17", 17)

    def test_errexit_completes_both_owned_reservations(self):
        for finalizer in self.production_finalizers():
            with self.subTest(finalizer=finalizer[:45]):
                self.assert_failure(finalizer, "false", 1)

    def test_success_handoff_does_not_publish_a_failure(self):
        for finalizer in self.production_finalizers():
            with self.subTest(finalizer=finalizer[:45]):
                code, mutation, output = self.exercise(finalizer, "exit 0")
                self.assertEqual(code, 0, output)
                self.assertEqual(mutation, [])


if __name__ == "__main__":
    unittest.main()
