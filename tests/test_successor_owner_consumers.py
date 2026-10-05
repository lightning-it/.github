import json
import os
from pathlib import Path
import subprocess
import unittest

from tests import test_copilot_review_refresh as contracts


REQUIRED = Path(__file__).resolve().parents[1] / (
    ".github/workflows/supplementary-current-revision-required.yml"
)


class SuccessorOwnerConsumerTests(unittest.TestCase):
    base, head = "a" * 40, "b" * 40
    current, owner = 123, 119
    repository = "lightning-it/.github"

    def setUp(self) -> None:
        self.producer_url = f"https://github.example/{self.repository}/actions/runs/77"
        self.summary = {
            "schema": 4, "base_sha": self.base, "head_sha": self.head,
            "pull_request_number": self.owner, "producer_run_id": 77,
            "run_url": self.producer_url,
        }
        self.external_id = (
            f"mlx90-current-revision:copilot:v6:{self.owner}:77:"
            f"{self.base}:{self.head}"
        )

    def _pr(self, number: int, state: str) -> dict[str, object]:
        return {
            "number": number, "state": state, "draft": False, "merged_at": None,
            "user": {"login": "litroc"},
            "base": {"ref": "develop", "sha": self.base,
                     "repo": {"full_name": self.repository}},
            "head": {"ref": "fix/final", "sha": self.head,
                     "repo": {"full_name": self.repository}},
        }

    def _run(self, consumer: str, owner: dict[str, object], **drift: object):
        summary = drift.get("summary", self.summary)
        external_id = drift.get("external_id", self.external_id)
        if consumer == "refresh":
            check = [{"external_id": external_id,
                      "output": {"summary": json.dumps(summary)}}]
            script = "\n".join((
                "set -euo pipefail",
                contracts.CopilotReviewRefreshTests._rfn("va"),
                "oa() { printf '%s\\n' \"${OWNER_PR}\"; }",
                'va "${CHECK}"',
            ))
            extra = {
                "CHECK": json.dumps(check), "BASE_REF": "develop",
                "HEAD_REF": "fix/final", "PR_AUTHOR": "litroc",
                "current_external_kind": "copilot", "owner_run_id": "77",
            }
        else:
            current_pr = self._pr(self.current, "open")
            script = "\n".join((
                "set -euo pipefail",
                "bounded_gh_api() { printf '%s\\n' \"${OWNER_PR}\"; }",
                'neutral_external_id="${EXTERNAL_ID}"', "producer_id=77",
                'neutral_summary="${SUMMARY}"', 'producer_url="${PRODUCER_URL}"',
                'pr="${CURRENT_PR}"',
                contracts.CopilotReviewRefreshTests._rerun_owner_binding_guard(),
                "validate_evidence_owner",
            ))
            extra = {
                "CURRENT_PR": json.dumps(current_pr), "EXPECTED_BASE": self.base,
                "EXPECTED_HEAD": self.head, "EXTERNAL_ID": str(external_id),
                "PRODUCER_URL": self.producer_url, "SUMMARY": json.dumps(summary),
                "author": "litroc", "base_ref": "develop", "head_ref": "fix/final",
            }
        return subprocess.run(
            ["bash", "-c", script], text=True, capture_output=True, check=False,
            env={**os.environ, "PATH": contracts.TEST_TOOL_PATH,
                 "BASE_SHA": self.base, "HEAD_SHA": self.head,
                 "OWNER_PR": json.dumps(owner), "PR_NUMBER": str(self.current),
                 "REPOSITORY": self.repository, **extra},
        )

    def test_refresh_and_rerun_bind_original_owner_fail_closed(self) -> None:
        owner = self._pr(self.owner, "closed")
        rejected = (
            {**owner, "state": "open"},
            {**owner, "merged_at": "2026-10-05T00:00:00Z"},
            {**owner, "head": {**owner["head"], "ref": "other"}},
        )
        for consumer in ("refresh", "rerun"):
            self.assertEqual(0, self._run(consumer, owner).returncode)
            for drifted_owner in rejected:
                self.assertNotEqual(0, self._run(consumer, drifted_owner).returncode)
            summary = {**self.summary, "pull_request_number": self.current}
            self.assertNotEqual(
                0, self._run(consumer, owner, summary=summary).returncode
            )

    def test_required_verifier_binds_owner_and_current_successor(self) -> None:
        workflow = REQUIRED.read_text(encoding="utf-8")

        def jq(name: str, payload: object, *args: str) -> int:
            filt = workflow.split(f'          cat >"${{{name}}}" <<\'JQ\'\n', 1)[1]
            filt = filt.split("\n          JQ\n", 1)[0]
            return subprocess.run(
                ["jq", "-e", *args, filt], input=json.dumps(payload), text=True,
                capture_output=True, check=False,
                env={**os.environ, "PATH": contracts.TEST_TOOL_PATH},
            ).returncode

        owner = self._pr(self.owner, "closed")
        args = ("--argjson", "current", json.dumps(self._pr(self.current, "open")),
                "--argjson", "owner", str(self.owner))
        self.assertEqual(0, jq("owner_pr_filter", owner, *args))
        self.assertNotEqual(0, jq("owner_pr_filter", {**owner, "state": "open"}, *args))
        run = {"head_branch": "fix/final", "pull_requests": [
            {"number": self.owner, "head": {"ref": "fix/final"}}]}
        args = ("--argjson", "owner", str(self.owner))
        self.assertEqual(0, jq("owner_run_filter", run, *args))
        run["pull_requests"][0]["number"] = self.current
        self.assertNotEqual(0, jq("owner_run_filter", run, *args))
        args = ("--arg", "version", "v6", "--argjson", "owner", str(self.owner))
        self.assertEqual(0, jq("owner_summary_filter", self.summary, *args))
        summary = {**self.summary, "pull_request_number": self.current}
        self.assertNotEqual(0, jq("owner_summary_filter", summary, *args))


if __name__ == "__main__":
    unittest.main()
