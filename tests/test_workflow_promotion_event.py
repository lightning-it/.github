"""A successful audit alone must never authorize private promotion preparation."""
import copy
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import workflow_promotion_event as event

REPO = "lightning-it/shared-assets-lit"
IDENTIFIER = 1120841013
HEAD, BASE, ADAPTER = "a" * 40, "b" * 40, "c" * 40


class PromotionEventTests(unittest.TestCase):
    def fixture(self):
        entry = event.target(REPO)
        env = {"GITHUB_REPOSITORY": REPO, "GITHUB_REPOSITORY_ID": str(IDENTIFIER),
               "GITHUB_EVENT_NAME": "workflow_run", "GITHUB_REF": "refs/heads/develop",
               "GITHUB_WORKFLOW_REF": f"{REPO}/{event.DELIVERY}@refs/heads/develop",
               "NATIVE_JOB": json.dumps({"workflow_repository": event.SOURCE,
                   "workflow_file_path": event.DELIVERY, "workflow_sha": ADAPTER, "check_run_id": 55})}
        signal = {"action": "completed", "workflow_run": {"id": 42, "head_sha": HEAD}}
        run = {"id": 42, "workflow_id": 7, "name": entry["workflow_name"], "path": entry["workflow"],
               "workflow_url": f"https://api.github.com/repos/{REPO}/actions/workflows/7",
               "event": "push", "head_branch": "develop", "run_attempt": 1, "head_sha": HEAD,
               "status": "completed", "conclusion": "success",
               "repository": {"id": IDENTIFIER, "private": True}, "head_repository": {"id": IDENTIFIER}}
        branch = {"name": "develop", "protected": True, "commit": {"sha": HEAD}}
        job = {"name": entry["job"], "status": "completed", "conclusion": "success", "run_id": 42, "head_sha": HEAD}
        pull = {"number": 9, "merged_at": "2026-10-17T00:00:00Z", "merged": True,
                "state": "closed", "merge_commit_sha": HEAD,
                "base": {"ref": "develop", "sha": BASE, "repo": {"id": IDENTIFIER}}}
        binding = {"repository_id": 1112629689, "path": event.WORKFLOW,
                   "sha": entry["source_sha"], "ref": "refs/heads/main"}
        rule = {"name": "WF-1 central review / shared-assets", "enforcement": "evaluate", "bypass_actors": [],
                "source_type": "Organization", "source": "lightning-it", "target": "branch",
                "conditions": {"repository_id": {"repository_ids": [IDENTIFIER]},
                               "ref_name": {"include": ["refs/heads/develop", "refs/heads/main"], "exclude": []}},
                "rules": [{"type": "workflows", "parameters": {"do_not_enforce_on_create": False,
                           "workflows": [binding]}}]}
        state = {"run": run, "branch": branch, "jobs": [job], "pulls": [pull], "pull": pull, "rule": rule}
        api = Mock()
        def call(path):
            if path.endswith("/actions/runs/42"): return copy.deepcopy(state["run"])
            if path.endswith("/actions/workflows/repository-quality.yml"): return {"id": 7, "path": entry["workflow"]}
            if path.endswith("/branches/develop"): return copy.deepcopy(state["branch"])
            if path.endswith("/rulesets/12"): return copy.deepcopy(state["rule"])
            if path.endswith("/pulls/9"): return copy.deepcopy(state["pull"])
            self.fail(path)
        def pages(path, key=None):
            if path.endswith("/jobs?filter=latest"): return copy.deepcopy(state["jobs"])
            if path.endswith("/rulesets?includes_parents=true"): return [{"id": 12, "name": rule["name"]}]
            if path.endswith("/commits/" + HEAD + "/pulls"): return copy.deepcopy(state["pulls"])
            self.fail(path)
        api.call.side_effect, api.pages.side_effect = call, pages
        api.file.return_value = f"uses: {event.SOURCE}/{event.DELIVERY}@{ADAPTER}".encode()
        return api, signal, env, state

    def test_real_producer_and_independent_control_admit_only_the_exact_current_head(self):
        api, signal, env, state = self.fixture()
        with patch.object(event, "policy", return_value={}) as policy, \
                patch.object(event, "check_native_control", return_value={"source_sha": event.target(REPO)["source_sha"]}) as verify:
            self.assertEqual(HEAD, event.current_head(api, signal, env))
        policy.assert_called_once_with(api, REPO, BASE, event.target(REPO)["source_sha"])
        verify.assert_called_once_with(api, REPO, state["pull"], {})
        self.assertTrue(all("method" not in call.kwargs for call in api.call.call_args_list))

    def test_passing_audit_with_missing_or_wrong_native_control_never_admits(self):
        for failure in (True, False):
            api, signal, env, _ = self.fixture()
            with self.subTest(failure=failure), patch.object(event, "policy", return_value={}), \
                    patch.object(event, "check_native_control", side_effect=event.ControlError("missing") if failure else None,
                                 return_value={"source_sha": "f" * 40}), self.assertRaises(event.ControlError):
                event.current_head(api, signal, env)

    def test_stale_events_stop_before_evidence_or_credentials(self):
        api, signal, env, state = self.fixture()
        state["branch"]["commit"]["sha"] = "d" * 40
        with patch.object(event, "check_native_control") as verify:
            self.assertIsNone(event.current_head(api, signal, env))
        api.pages.assert_not_called()
        verify.assert_not_called()

    def test_advancing_develop_during_control_verification_is_a_noop(self):
        api, signal, env, state = self.fixture()
        def verify(*_):
            state["branch"]["commit"]["sha"] = "d" * 40
            return {"source_sha": event.target(REPO)["source_sha"]}
        with patch.object(event, "policy", return_value={}), patch.object(event, "check_native_control", side_effect=verify):
            self.assertIsNone(event.current_head(api, signal, env))

    def test_pr_fork_failed_rerun_required_quality_alias_and_other_workflows_are_rejected(self):
        for change in ({"event": "pull_request"}, {"head_branch": "main"}, {"run_attempt": 2},
                       {"conclusion": "failure"}, {"conclusion": "skipped"}, {"status": "in_progress"},
                       {"head_repository": {"id": 42}}, {"repository": {"id": IDENTIFIER, "private": False}},
                       {"workflow_id": 9}, {"path": ".github/workflows/other.yml"},
                       {"workflow_url": f"https://api.github.com/repos/{REPO}/actions/required_workflows/7"}):
            api, signal, env, state = self.fixture()
            state["run"].update(change)
            with self.subTest(change=change), self.assertRaises(event.ControlError):
                event.current_head(api, signal, env)
            api.pages.assert_not_called()

    def test_foreign_missing_or_widened_selection_blocks_before_native_proof(self):
        for change in ("target", "source", "bypass", "disabled"):
            api, signal, env, state = self.fixture()
            rule = state["rule"]
            if change == "target": rule["conditions"]["repository_id"]["repository_ids"].append(42)
            elif change == "source": rule["rules"][0]["parameters"]["workflows"][0]["sha"] = "f" * 40
            elif change == "bypass": rule["bypass_actors"] = [{"actor_id": 1}]
            else: rule["enforcement"] = "disabled"
            with self.subTest(change=change), patch.object(event, "check_native_control") as verify, \
                    self.assertRaises(event.ControlError):
                event.current_head(api, signal, env)
            verify.assert_not_called()

    def test_unknown_consumers_and_candidate_receivers_have_no_api_access(self):
        for change in ({"GITHUB_REPOSITORY": "contributor/fork"}, {"GITHUB_REPOSITORY_ID": "42"},
                       {"GITHUB_EVENT_NAME": "pull_request_target"}, {"GITHUB_REF": "refs/pull/9/merge"},
                       {"GITHUB_WORKFLOW_REF": f"{REPO}/{event.DELIVERY}@refs/heads/main"}):
            api, signal, env, _ = self.fixture()
            env.update(change)
            with self.subTest(change=change), self.assertRaises(event.ControlError):
                event.current_head(api, signal, env)
            api.call.assert_not_called()


if __name__ == "__main__":
    unittest.main()
