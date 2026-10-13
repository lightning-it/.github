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
                contracts.CopilotReviewRefreshTests._rfn("validate_refresh_owner_run"),
                contracts.CopilotReviewRefreshTests._rfn("va"),
                "oa() { printf '%s\\n' \"${OWNER_RUN}\"; }",
                'va "${CHECK}"',
            ))
            extra = {
                "CHECK": json.dumps(check), "BASE_REF": "develop",
                "HEAD_REF": "fix/final", "PR_AUTHOR": "litroc",
                "current_external_kind": "copilot", "owner_run_id": "88",
                "OWNER_RUN": json.dumps(drift.get("owner_run", {
                    "id": 77, "event": "pull_request_target",
                    "path": ".github/workflows/copilot-review.yml",
                    "name": "Current revision review gate", "run_attempt": 1,
                    "head_branch": "fix/final", "head_sha": self.head,
                    "repository": {"full_name": self.repository},
                    "head_repository": {"full_name": self.repository},
                    "pull_requests": [{"number": self.owner,
                        "base": {"sha": self.base},
                        "head": {"sha": self.head, "ref": "fix/final"}}],
                })),
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
                 "REPOSITORY": self.repository, "HEAD_REPOSITORY": self.repository,
                 "hr": self.repository, **extra},
        )

    def test_refresh_and_rerun_bind_original_owner_fail_closed(self) -> None:
        owner = self._pr(self.owner, "closed")
        rejected = (
            {**owner, "state": "open"},
            {**owner, "merged_at": "2026-10-05T00:00:00Z"},
            {**owner, "head": {**owner["head"], "ref": "other"}},
            {**owner, "head": {**owner["head"],
                               "repo": {"full_name": "other/fork"}}},
        )
        for consumer in ("refresh", "rerun"):
            accepted = self._run(consumer, owner)
            self.assertEqual(0, accepted.returncode, accepted.stderr)
            for drifted_owner in rejected:
                self.assertNotEqual(0, self._run(consumer, drifted_owner).returncode)
            summary = {**self.summary, "pull_request_number": self.current}
            self.assertNotEqual(
                0, self._run(consumer, owner, summary=summary).returncode
            )

    def test_refresh_rejects_forged_predecessor_run(self) -> None:
        result = self._run("refresh", self._pr(self.owner, "closed"),
                           owner_run={"id": 88})
        self.assertNotEqual(0, result.returncode)

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
