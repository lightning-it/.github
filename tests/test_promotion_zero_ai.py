"""Full native promotion aggregation using real Git and read-only API fixtures."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from tests import test_promotion_evidence as evidence


class PromotionZeroAiTests(unittest.TestCase):
    def test_full_verifier_uses_native_ingress_and_never_requests_review(self):
        module = evidence.MODULE
        repository = "lightning-it/.github"
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory).resolve()
            target = runtime / "repository"
            target.mkdir()
            environment = {
                **os.environ,
                "GIT_CONFIG_GLOBAL": "/dev/null",
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_AUTHOR_NAME": "Fixture",
                "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
                "GIT_COMMITTER_NAME": "Fixture",
                "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
            }

            def git(*args, input=None):
                return subprocess.check_output(
                    ["git", *args],
                    cwd=target,
                    env=environment,
                    text=True,
                    input=input,
                    stderr=subprocess.DEVNULL,
                ).strip()

            git("init", "--quiet")
            (target / "tracked").write_text("initial\n")
            git("add", ".")
            tree = git("write-tree")
            common = git("commit-tree", tree, input="common\n")
            main = git("commit-tree", tree, "-p", common, input="protected release\n")
            (target / ".lit").mkdir()
            (target / ".lit/main-ancestry.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "repository": repository,
                        "main_sha": main,
                        "develop_parent_sha": common,
                        "purpose": "Bind the reviewed main ancestry backmerge.",
                    }
                )
            )
            git("add", ".")
            tree = git("write-tree")
            inner = git(
                "commit-tree",
                tree,
                "-p",
                common,
                "-p",
                main,
                input="merge: preserve develop tree and main ancestry\n",
            )
            baseline = git(
                "commit-tree",
                tree,
                "-p",
                common,
                "-p",
                inner,
                input="Merge pull request #10\n",
            )
            (target / "tracked").write_text("reviewed ingress\n")
            git("add", ".")
            tree = git("write-tree")
            feature = git(
                "commit-tree", tree, "-p", baseline, input="fix: exact ingress\n"
            )
            head = git(
                "commit-tree",
                tree,
                "-p",
                baseline,
                "-p",
                feature,
                input="Merge pull request #17\n",
            )
            git("update-ref", "refs/heads/main", main)
            git("update-ref", "refs/heads/develop", head)
            git("checkout", "--quiet", "develop")
            body = "\n".join(
                (
                    f"<!-- lit-promotion-head:{head} -->",
                    "<!-- lit-promotion-run:901:1 -->",
                    f"<!-- lit-promotion-evidence-ready:{main}:{head} -->",
                    "<!-- lit-protected-promotion:v2 -->",
                    "Automated protected promotion of changes already reviewed on develop.",
                    "The organization Required Workflow aggregates exact ingress evidence; "
                    "it does not request a second AI review of the cumulative diff.",
                )
            )
            replacements = {
                evidence.BASE: baseline,
                evidence.HEAD: feature,
                evidence.MERGE: head,
                "lightning-it/example": repository,
                '"example"': '".github"',
            }

            def replace(value, reverse=False):
                raw = json.dumps(value)
                for old, new in replacements.items():
                    raw = raw.replace(new, old) if reverse else raw.replace(old, new)
                return json.loads(raw)

            current = replace(evidence.promotion())
            current["body"] = body
            current["base"]["sha"] = main
            current["head"]["sha"] = head
            ingress = replace(evidence.ingress_pull())
            ingress["labels"] = []
            boundary = replace(
                evidence.ingress_pull(
                    login="lightning-it-release-automation[bot]",
                    user_id=307565056,
                    user_type="Bot",
                )
            )
            boundary.update(
                {
                    "number": 10,
                    "merge_commit_sha": baseline,
                    "title": f"chore(governance): record main ancestry before {main[:12]}",
                }
            )
            boundary["base"]["sha"] = common
            boundary["head"].update(
                {
                    "sha": inner,
                    "ref": f"backmerge/github-{main[:12]}-{common[:12]}-main",
                }
            )
            check = replace(
                evidence.check_run(
                    f"mlx90-current-revision:copilot:v6:17:88:{evidence.BASE}:{evidence.HEAD}",
                    evidence.expanded_v6_summary(),
                )
            )
            delegate = evidence.evidence_api(evidence.producer_run())
            calls = []
            missing_review = False
            unresolved = False

            def api(args):
                calls.append(args)
                self.assertEqual("api", args[0])
                self.assertNotIn("--method", args)
                endpoint = args[-1]
                if args[:2] == ["api", "graphql"] and any(
                    "reviewThreads" in arg for arg in args
                ):
                    return {
                        "data": {
                            "repository": {
                                "pullRequest": {
                                    "number": 17,
                                    "reviewThreads": {
                                        "nodes": [
                                            {
                                                "id": "PRRT_unresolved",
                                                "isResolved": False,
                                            }
                                        ]
                                        if unresolved
                                        else [],
                                        "pageInfo": {
                                            "hasNextPage": False,
                                            "endCursor": None,
                                        },
                                    },
                                }
                            }
                        }
                    }
                if endpoint == f"repos/{repository}/pulls/41":
                    return current
                if endpoint == f"repos/{repository}/commits/{main}":
                    return {
                        "sha": main,
                        "commit": {
                            "verification": {"verified": True, "reason": "valid"},
                            "committer": {"date": "2026-09-27T00:00:00Z"},
                        },
                    }
                if (
                    endpoint
                    == f"repos/{repository}/commits/{baseline}/pulls?per_page=100"
                ):
                    return [[boundary]]
                if endpoint == f"repos/{repository}/commits/{head}/pulls?per_page=100":
                    return [[ingress]]
                if endpoint == f"repos/{repository}/pulls/10":
                    return boundary
                if endpoint == f"repos/{repository}/pulls/17":
                    return ingress
                if endpoint == f"repos/{repository}/branches/main":
                    return {"name": "main", "protected": True, "commit": {"sha": main}}
                if endpoint == f"repos/{repository}/branches/develop":
                    return {
                        "name": "develop",
                        "protected": True,
                        "commit": {"sha": head},
                    }
                if endpoint == f"repos/{repository}/compare/{'5' * 40}...{head}":
                    return {
                        "status": "ahead",
                        "behind_by": 0,
                        "merge_base_commit": {"sha": "5" * 40},
                    }
                if "check-runs?check_name=" in endpoint:
                    return [{"check_runs": [] if missing_review else [check]}]
                return replace(delegate(replace(args, reverse=True)))

            arguments = module.argparse.Namespace(
                repository=repository,
                pull_request=41,
                base_ref="main",
                head_ref="develop",
                expected_base=main,
                expected_head=head,
                controller_sha="5" * 40,
                expected_body_sha256=hashlib.sha256(body.encode()).hexdigest(),
                repository_path=target,
                output=runtime / "evidence.json",
            )
            # Only the remote transport is replaced. Every Git, history, policy,
            # author, review, thread, coverage, hash and revalidation helper runs.
            with (
                mock.patch.dict(os.environ, {"RUNNER_TEMP": str(runtime)}),
                mock.patch.object(module, "gh_json", side_effect=api),
            ):
                result = module.verify(arguments)
                self.assertEqual(2, result["ingress_count"])
                self.assertEqual(1, result["reviewed_change_ingress_count"])
                self.assertIsNone(result["ingress"][0]["review"])
                self.assertEqual(99, result["ingress"][1]["review"]["check_id"])
                module.write_output(arguments.output, result)
                self.assertEqual(result, json.loads(arguments.output.read_text()))
                missing_review = True
                with self.assertRaisesRegex(
                    module.EvidenceError, "bound-current-revision-check-not-unique"
                ):
                    module.verify(arguments)
                missing_review = False
                unresolved = True
                with self.assertRaisesRegex(
                    module.EvidenceError, "unresolved-review-thread"
                ):
                    module.verify(arguments)
            self.assertGreater(len(calls), 10)
            self.assertNotIn("promotion_review", result)
            patch = subprocess.check_output(
                [
                    "git",
                    "diff",
                    "--binary",
                    "--full-index",
                    "--no-renames",
                    "--no-color",
                    "--no-ext-diff",
                    "--no-textconv",
                    f"{main}^{{tree}}",
                    f"{head}^{{tree}}",
                    "--",
                ],
                cwd=target,
                env=environment,
            )
            self.assertEqual(len(patch), result["diff"]["bytes"])
            self.assertEqual(
                hashlib.sha256(patch).hexdigest(), result["diff"]["sha256"]
            )
            print(
                "PROMOTION_ZERO_AI_NATIVE_PROBE="
                + json.dumps(
                    {
                        "ingress_count": result["ingress_count"],
                        "reviewed_change_ingress_count": result[
                            "reviewed_change_ingress_count"
                        ],
                        "diff": result["diff"],
                        "authorization_helper_stubs": 0,
                        "actual_git_history": True,
                        "fixture_read_requests": len(calls),
                        "new_model_calls": 0,
                        "missing_review_rejected": True,
                        "unresolved_thread_rejected": True,
                    },
                    sort_keys=True,
                )
            )


if __name__ == "__main__":
    unittest.main()
