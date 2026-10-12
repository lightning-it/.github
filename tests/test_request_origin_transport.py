"""Execute the production shell transport without a GitHub call or proof bypass."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


class RequestOriginTransportTests(unittest.TestCase):
    @staticmethod
    def production_function() -> str:
        workflow = yaml.safe_load(
            (
                ROOT / ".github/workflows/supplementary-current-revision-required.yml"
            ).read_text()
        )
        scripts = [
            step.get("run", "")
            for job in workflow["jobs"].values()
            for step in job.get("steps", [])
            if "verify_request_origin() {" in step.get("run", "")
        ]
        if len(scripts) != 1:
            raise AssertionError(
                "The authoritative request-origin transport must be unique"
            )
        script = scripts[0]
        return script[
            script.index("verify_request_origin() {") : script.index(
                "verify_event_recovery() {"
            )
        ]

    def exercise(
        self, documents: dict[str, object], *, extra_document: bool = False
    ) -> tuple[int, dict[str, object] | None, str]:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            for name, document in documents.items():
                suffix = "\n{}" if extra_document and name == "first" else ""
                (directory / name).write_text(json.dumps(document) + suffix)
            output = directory / "received.json"
            script = directory / "transport.sh"
            script.write_text(
                "set -euo pipefail\n"
                "attempt_one=$(cat first)\nproducer=$(cat producer)\n"
                "attempt_one_jobs=$(cat jobs)\ntl=$(cat timeline)\n"
                # This receiver checks only transport. The unchanged protected
                # origin verifier separately owns authorization and API proof.
                "run_request_proof() { cat >received.json; }\n"
                + self.production_function()
                + '\nverify_request_origin "$tl"\n'
            )
            # Execute only the exact production fragment and isolated fixture inputs.
            result = subprocess.run(
                ["bash", str(script)],
                cwd=directory,
                env={
                    **os.environ,
                    "LI219_EVENT_MODE": "enabled",
                    "author": "litroc",
                    "recovery_status": "0",
                    "REPOSITORY": "lightning-it/shared-assets-lit",
                    "GITHUB_REPOSITORY_ID": "1234",
                    "EVENT_HEAD": "a" * 40,
                    "EVENT_BASE": "b" * 40,
                    "controller_sha": "c" * 40,
                    "controller_branch": "develop",
                    "controller_head": "c" * 40,
                    "base_ref": "develop",
                    "review_submitted_at": "2026-10-12T04:34:20Z",
                    "owner_pr_number": "2520",
                    "producer_run_id": "38204125577",
                },
                text=True,
                capture_output=True,
                check=False,
                timeout=30,
            )
            received = (
                json.loads(output.read_text())
                if output.exists() and output.stat().st_size
                else None
            )
            return result.returncode, received, result.stderr

    def test_large_valid_documents_reach_the_existing_origin_proof_without_truncation(
        self,
    ) -> None:
        for oversized in ("first", "producer", "jobs", "timeline"):
            with self.subTest(oversized=oversized):
                documents: dict[str, object] = {
                    "first": {"id": 38204125577},
                    "producer": {"created_at": "2026-10-12T04:31:19Z"},
                    "jobs": {
                        "jobs": [
                            {"name": "Request Copilot review for current revision"}
                        ]
                    },
                    "timeline": [
                        [{"event": "issue_comment", "body": "Transport canary"}]
                    ],
                }
                if oversized == "timeline":
                    documents[oversized] = [
                        [{"event": "issue_comment", "body": "T" * 300000}]
                    ]
                else:
                    assert isinstance(documents[oversized], dict)
                    documents[oversized]["transport_canary"] = "T" * 300000
                code, received, stderr = self.exercise(documents)
                self.assertEqual(code, 0, stderr[-2000:])
                self.assertIsNotNone(received)
                assert received is not None
                for name, document in documents.items():
                    self.assertEqual(received[name], document)
                self.assertEqual(received["owner"], 2520)
                self.assertEqual(received["run_id"], 38204125577)
                self.assertEqual(received["head"], "a" * 40)
                self.assertEqual(received["base"], "b" * 40)
                self.assertEqual(received["controller"], "c" * 40)
                self.assertEqual(
                    received["repository"], "lightning-it/shared-assets-lit"
                )

    def test_extra_json_document_is_rejected_before_origin_proof_receives_a_payload(
        self,
    ) -> None:
        code, received, stderr = self.exercise(
            {
                "first": {},
                "producer": {"created_at": "2026-10-12T04:31:19Z"},
                "jobs": {},
                "timeline": [[]],
            },
            extra_document=True,
        )
        self.assertNotEqual(code, 0)
        self.assertIsNone(received)
        self.assertIn("request-origin transport document count is invalid", stderr)

    def test_existing_contributor_request_route_does_not_enter_event_recovery(
        self,
    ) -> None:
        code, received, stderr = self.exercise(
            {
                "first": {},
                "producer": {"created_at": "2026-10-12T04:31:19Z"},
                "jobs": {},
                "timeline": [
                    [
                        {
                            "event": "review_requested",
                            "actor": {"login": "litroc"},
                            "requested_reviewer": {"login": "Copilot"},
                            "created_at": "2026-10-12T04:32:00Z",
                        }
                    ]
                ],
            }
        )
        self.assertEqual(code, 0, stderr)
        self.assertIsNone(received)


if __name__ == "__main__":
    unittest.main()
