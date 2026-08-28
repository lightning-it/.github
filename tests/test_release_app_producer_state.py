from __future__ import annotations

import importlib.util
import pathlib
import subprocess
import sys
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify-release-app-producer-state.py"
SPEC = importlib.util.spec_from_file_location(
    "release_app_producer_state", SCRIPT
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot load Release-App producer-state verifier")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class ReleaseAppProducerStateTests(unittest.TestCase):
    def test_completed_success_is_always_accepted(self) -> None:
        payload = {"status": "completed", "conclusion": "success"}
        for evidence_ready in (False, True):
            with self.subTest(evidence_ready=evidence_ready):
                MODULE.verify_producer_state(
                    payload, evidence_ready=evidence_ready
                )

    def test_in_progress_requires_bound_evidence(self) -> None:
        payload = {"status": "in_progress", "conclusion": None}
        MODULE.verify_producer_state(payload, evidence_ready=True)
        with self.assertRaisesRegex(
            MODULE.VerificationError, "evidence-bound"
        ):
            MODULE.verify_producer_state(payload, evidence_ready=False)

    def test_every_other_state_fails_closed(self) -> None:
        rejected = (
            {"status": "queued", "conclusion": None},
            {"status": "completed", "conclusion": "failure"},
            {"status": "completed", "conclusion": None},
            {"status": "in_progress", "conclusion": "success"},
            {"status": 1, "conclusion": "success"},
            {"conclusion": "success"},
            [],
        )
        for payload in rejected:
            with self.subTest(payload=payload):
                with self.assertRaises(MODULE.VerificationError):
                    MODULE.verify_producer_state(
                        payload, evidence_ready=True
                    )

    def test_cli_rejects_invalid_json(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--evidence-ready", "false"],
            input="not-json",
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(1, result.returncode)
        self.assertIn("producer payload must be valid JSON", result.stderr)


if __name__ == "__main__":
    unittest.main()
