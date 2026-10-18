"""A successful audit alone must never authorize private promotion preparation."""
import copy
import json
import sys
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import workflow_promotion_event as event

REPO = "lightning-it/shared-assets-lit"
IDENTIFIER = 1120841013
SUPPLEMENTARY = "lightning-it/ansible-collection-supplementary"
HEAD, BASE, ADAPTER = "a" * 40, "b" * 40, "c" * 40

# Anonymized historical API form only; no future D1 or native acceptance.
SUPPLEMENTARY_SHAPE = {'description': 'Anonymized API shape from public Collection CI run 39099542751 and Fast job 117596230526. '
                'Run/job IDs, hashes and PR linkage are synthetic. This is not a D1 qualification or native '
                'acceptance receipt.',
 'run': {'id': 42,
         'workflow_id': 214182490,
         'name': 'Collection CI',
         'path': '.github/workflows/collection-ci.yml',
         'workflow_url': 'https://api.github.com/repos/lightning-it/ansible-collection-supplementary/actions/workflows/214182490',
         'event': 'push',
         'head_branch': 'develop',
         'run_attempt': 1,
         'head_sha': 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
         'status': 'completed',
         'conclusion': 'success',
         'repository': {'id': 1103407173, 'private': False},
         'head_repository': {'id': 1103407173}},
 'job': {'id': 101,
         'run_attempt': 1,
         'name': 'Collection / Fast',
         'status': 'completed',
         'conclusion': 'success',
         'run_id': 42,
         'head_sha': 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'}}


class PromotionEventTests(unittest.TestCase):
    def test_private_receiver_checks_the_proof_before_its_only_management_token(self):
        import yaml
        value = yaml.safe_load((Path(__file__).resolve().parents[1] / event.DELIVERY).read_bytes())
        self.assertEqual(["Repository review events"], value[True]["workflow_run"]["workflows"])
        steps = value["jobs"]["prepare"]["steps"]
        self.assertLess(next(i for i, step in enumerate(steps) if step.get("id") == "signal"),
                        next(i for i, step in enumerate(steps) if step.get("id") == "app"))
        token = next(step for step in steps if step.get("id") == "app")
        self.assertEqual("github-management-lit", token["with"]["repositories"])
        self.assertEqual("write", token["with"]["permission-actions"])
        self.assertFalse(value[True]["workflow_call"]["secrets"]["RELEASE_AUTOMATION_APP_PRIVATE_KEY"]["required"])
        self.assertIn("--expected-head", steps[-1]["run"])
        self.assertIn("runtime_develop_sha", steps[-1]["run"])
        self.assertRegex(steps[0]["with"]["ref"], r"^[0-9a-f]{40}$")
        self.assertFalse(steps[0]["with"]["persist-credentials"])
        self.assertEqual({"contents": "read", "actions": "read", "pull-requests": "read"},
                         value["jobs"]["prepare"]["permissions"])
        self.assertEqual({"RELEASE_AUTOMATION_APP_PRIVATE_KEY"},
                         set(value[True]["workflow_call"]["secrets"]))
        guard = value["jobs"]["prepare"]["if"]
        for repository, producer in ((REPO, "Repository policy audit"), (SUPPLEMENTARY, "Collection CI")):
            self.assertIn(f"github.repository == '{repository}'", guard)
            self.assertIn(f"github.event.workflow_run.name == '{producer}'", guard)
        self.assertEqual(1, steps[-1]["run"].count("gh api --method POST"))
        self.assertNotIn("GH_MANAGEMENT_TOKEN", str(steps))

    def fixture(self, repository=REPO):
        entry = event.target(repository)
        identifier = entry["repository_id"]
        env = {"GITHUB_REPOSITORY": repository, "GITHUB_REPOSITORY_ID": str(identifier),
               "GITHUB_EVENT_NAME": "workflow_run", "GITHUB_REF": "refs/heads/develop",
               "GITHUB_WORKFLOW_REF": f"{repository}/{event.DELIVERY}@refs/heads/develop",
               "NATIVE_JOB": json.dumps({"workflow_repository": event.SOURCE,
                   "workflow_file_path": event.DELIVERY, "workflow_sha": ADAPTER, "check_run_id": 55})}
        signal = {"action": "completed", "workflow_run": {"id": 42, "head_sha": HEAD}}
        run = {"id": 42, "workflow_id": entry["workflow_id"], "name": entry["workflow_name"], "path": entry["workflow"],
               "workflow_url": f"https://api.github.com/repos/{repository}/actions/workflows/{entry['workflow_id']}",
               "event": "push", "head_branch": "develop", "run_attempt": 1, "head_sha": HEAD,
               "status": "completed", "conclusion": "success",
               "repository": {"id": identifier, "private": entry["private"]}, "head_repository": {"id": identifier}}
        if repository == SUPPLEMENTARY:
            fixture = copy.deepcopy(SUPPLEMENTARY_SHAPE)
            run = fixture["run"]
        branch = {"name": "develop", "protected": True, "commit": {"sha": HEAD}}
        job = {"id": 101, "run_attempt": 1, "name": entry["job"], "status": "completed", "conclusion": "success", "run_id": 42, "head_sha": HEAD}
        if repository == SUPPLEMENTARY:
            job = fixture["job"]
        pull = {"number": 9, "merged_at": "2026-10-17T00:00:00Z", "merged": True,
                "state": "closed", "merge_commit_sha": HEAD,
                "base": {"ref": "develop", "sha": BASE, "repo": {"id": identifier}}}
        state = {"run": run, "branch": branch, "jobs": [job], "pulls": [pull], "pull": pull}
        api = Mock()
        def call(path):
            if path.endswith("/actions/runs/42"): return copy.deepcopy(state["run"])
            if path.endswith("/actions/workflows/" + entry["workflow"].rsplit("/", 1)[1]):
                return {"id": entry["workflow_id"], "path": entry["workflow"]}
            if path.endswith("/branches/develop"): return copy.deepcopy(state["branch"])
            if path.endswith("/pulls/9"): return copy.deepcopy(state["pull"])
            self.fail(path)
        def pages(path, key=None):
            if path.endswith("/jobs?filter=latest"): return copy.deepcopy(state["jobs"])
            if path.endswith("/commits/" + HEAD + "/pulls"): return copy.deepcopy(state["pulls"])
            self.fail(path)
        api.call.side_effect, api.pages.side_effect = call, pages
        api.file.return_value = f"uses: {event.SOURCE}/{event.DELIVERY}@{ADAPTER}".encode()
        return api, signal, env, state

    def test_real_producer_and_independent_control_locate_only_the_exact_current_head(self):
        api, signal, env, state = self.fixture()
        with patch.object(event, "policy", return_value={}) as policy, \
                patch.object(event, "check_native_control", return_value={"source_sha": event.target(REPO)["source_sha"]}) as verify:
            self.assertEqual(HEAD, event.current_head(api, signal, env))
        policy.assert_called_once_with(api, REPO, BASE, event.target(REPO)["source_sha"])
        verify.assert_called_once_with(api, REPO, state["pull"], {})
        self.assertTrue(all("method" not in call.kwargs for call in api.call.call_args_list))

    def test_unprojected_evaluate_rule_does_not_replace_actual_native_ingress(self):
        api, signal, env, _ = self.fixture()
        original_pages = api.pages.side_effect
        def active_parent_projection(path, key=None):
            if path.endswith("/rulesets?includes_parents=true"):
                return []
            return original_pages(path, key)
        api.pages.side_effect = active_parent_projection
        with patch.object(event, "policy", return_value={}), patch.object(event, "check_native_control",
                return_value={"source_sha": event.target(REPO)["source_sha"]}) as verify:
            self.assertEqual(HEAD, event.current_head(api, signal, env))
        verify.assert_called_once()
        self.assertFalse(any("/rulesets" in call.args[0]
                             for call in api.call.call_args_list + api.pages.call_args_list))

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

    def test_unknown_consumers_and_candidate_receivers_have_no_api_access(self):
        for change in ({"GITHUB_REPOSITORY": "contributor/fork"}, {"GITHUB_REPOSITORY_ID": "42"},
                       {"GITHUB_EVENT_NAME": "pull_request_target"}, {"GITHUB_REF": "refs/pull/9/merge"},
                       {"GITHUB_WORKFLOW_REF": f"{REPO}/{event.DELIVERY}@refs/heads/main"}):
            api, signal, env, _ = self.fixture()
            env.update(change)
            with self.subTest(change=change), self.assertRaises(event.ControlError):
                event.current_head(api, signal, env)
            api.call.assert_not_called()


    def test_public_collection_profile_uses_native_ci_shape_and_independent_ingress(self):
        api, signal, env, state = self.fixture(SUPPLEMENTARY)
        with patch.object(event, "policy", return_value={}) as policy, \
                patch.object(event, "check_native_control", return_value={"source_sha": event.target(SUPPLEMENTARY)["source_sha"]}) as verify:
            self.assertEqual(HEAD, event.current_head(api, signal, env))
        policy.assert_called_once_with(api, SUPPLEMENTARY, BASE, event.target(SUPPLEMENTARY)["source_sha"])
        verify.assert_called_once_with(api, SUPPLEMENTARY, state["pull"], {})
        self.assertIn(f"repos/{SUPPLEMENTARY}/actions/workflows/collection-ci.yml",
                      [call.args[0] for call in api.call.call_args_list])
        self.assertTrue(all("method" not in call.kwargs for call in api.call.call_args_list))

    def test_registry_cannot_expand_or_relabel_receiver_authority(self):
        registry = json.loads((Path(__file__).resolve().parents[1] / ".lit/promotion-event-targets.json").read_bytes())
        malformed = [registry | {"version": True}, registry | {"targets": registry["targets"][:1]},
                     registry | {"targets": [registry["targets"][0]] * 2}]
        for change in ({"repository": "lightning-it/ansible-collection-ubuntu"}, {"repository_id": 42},
                       {"private": True}, {"private": 0}, {"workflow_id": 214182490.0}, {"workflow_id": 7}, {"scope": "fleet"},
                       {"source_sha": HEAD}, {"workflow": ".github/workflows/release-prepare.yml"},
                       {"job": "Collection / Build and Install"}, {"extra": "authority"}):
            value = copy.deepcopy(registry)
            value["targets"][1].update(change)
            malformed.append(value)
        for value in malformed:
            api, signal, env, _ = self.fixture(SUPPLEMENTARY)
            with self.subTest(value=value), patch.object(Path, "read_bytes", return_value=json.dumps(value).encode()), \
                    self.assertRaises(event.ControlError):
                event.current_head(api, signal, env)
            api.call.assert_not_called()
            api.pages.assert_not_called()

    def test_public_producer_identity_visibility_and_attempt_fail_closed(self):
        for change in ({"event": "pull_request"}, {"event": "workflow_dispatch"}, {"head_branch": "main"},
                       {"run_attempt": True}, {"run_attempt": 0}, {"run_attempt": -1}, {"run_attempt": 2},
                       {"conclusion": "failure"}, {"conclusion": "skipped"}, {"status": "in_progress"},
                       {"repository": {"id": 1103407173, "private": True}},
                       {"repository": {"id": 42, "private": False}}, {"head_repository": {"id": 42}},
                       {"workflow_id": 214182490.0}, {"workflow_id": 307348847}, {"name": "Repository policy audit"},
                       {"path": ".github/workflows/release-prepare.yml"},
                       {"workflow_url": f"https://api.github.com/repos/{SUPPLEMENTARY}/actions/required_workflows/214182490"},
                       {"head_sha": BASE}):
            api, signal, env, state = self.fixture(SUPPLEMENTARY)
            state["run"].update(change)
            with self.subTest(change=change), self.assertRaises(event.ControlError):
                event.current_head(api, signal, env)
            api.pages.assert_not_called()

    def test_fast_job_is_unique_and_bound_to_exact_run_head_and_attempt(self):
        for repository in (REPO, SUPPLEMENTARY):
            for change in (None, "duplicate", {"id": True}, {"id": 0}, {"run_id": 43}, {"head_sha": BASE},
                           {"run_attempt": True}, {"run_attempt": 0}, {"run_attempt": -1}, {"run_attempt": 2},
                           {"name": "Collection / Build and Install"}, {"conclusion": "failure"},
                           {"conclusion": "skipped"}, {"status": "in_progress"}):
                api, signal, env, state = self.fixture(repository)
                if change is None: state["jobs"] = []
                elif change == "duplicate": state["jobs"] *= 2
                else: state["jobs"][0].update(change)
                with self.subTest(repository=repository, change=change), patch.object(event, "check_native_control") as proof, \
                        self.assertRaisesRegex(event.ControlError, "job-required"):
                    event.current_head(api, signal, env)
                proof.assert_not_called()

    def test_public_ingress_and_defining_source_cannot_be_substituted(self):
        for defect in ("missing", "duplicate", "other-repo", "wrong-merge", "not-merged", "adapter", "proof", "no-proof"):
            api, signal, env, state = self.fixture(SUPPLEMENTARY)
            if defect == "missing": state["pulls"] = []
            elif defect == "duplicate": state["pulls"] *= 2
            elif defect == "other-repo": state["pull"]["base"]["repo"]["id"] = 42
            elif defect == "wrong-merge": state["pull"]["merge_commit_sha"] = BASE
            elif defect == "not-merged": state["pull"]["merged"] = False
            elif defect == "adapter": api.file.return_value = f"uses: {event.SOURCE}/{event.DELIVERY}@main".encode()
            with self.subTest(defect=defect), patch.object(event, "policy", return_value={}), \
                    patch.object(event, "check_native_control",
                                 return_value={"source_sha": HEAD if defect == "proof" else event.target(SUPPLEMENTARY)["source_sha"]},
                                 side_effect=event.ControlError("missing-native-proof") if defect == "no-proof" else None), \
                    self.assertRaises(event.ControlError):
                event.current_head(api, signal, env)
            self.assertTrue(all("method" not in call.kwargs for call in api.call.call_args_list))

    def test_public_producer_or_tip_drift_during_proof_never_returns_dispatch_head(self):
        for defect in ("producer", "tip", "protection"):
            api, signal, env, state = self.fixture(SUPPLEMENTARY)
            def verify(*_):
                if defect == "producer": state["run"]["run_attempt"] = 2
                elif defect == "tip": state["branch"]["commit"]["sha"] = BASE
                else: state["branch"]["protected"] = False
                return {"source_sha": event.target(SUPPLEMENTARY)["source_sha"]}
            with self.subTest(defect=defect), patch.object(event, "policy", return_value={}), \
                    patch.object(event, "check_native_control", side_effect=verify):
                if defect == "tip": self.assertIsNone(event.current_head(api, signal, env))
                else:
                    with self.assertRaises(event.ControlError): event.current_head(api, signal, env)
            self.assertTrue(all("method" not in call.kwargs for call in api.call.call_args_list))

    def test_existing_dispatch_shell_is_single_write_and_stale_or_uncertain_outcome_never_retries(self):
        import yaml
        workflow = yaml.safe_load((Path(__file__).resolve().parents[1] / event.DELIVERY).read_bytes())
        script = workflow["jobs"]["prepare"]["steps"][-1]["run"]
        for outcome in ("current", "stale", "unknown", "proof-failed"):
            with self.subTest(outcome=outcome), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                # Stand-ins provide only helper output and capture the outgoing CLI call.
                # The independent helper tests above exercise native evidence validation.
                helper = root / "python3"
                helper.write_text("#!/bin/sh\n[ \"$OUTCOME\" != proof-failed ] || exit 1\n"
                                  "[ \"$OUTCOME\" = stale ] || printf '%s\\n' \"$EXPECTED_HEAD\"\n")
                dispatch = root / "gh"
                dispatch.write_text("#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$CALL_LOG\"\n"
                                    "[ \"$OUTCOME\" != unknown ]\n")
                helper.chmod(0o700); dispatch.chmod(0o700)
                log = root / "calls"
                result = subprocess.run(["bash", "-c", script], cwd=root, capture_output=True, text=True,
                    env={**os.environ, "BASH_ENV": "", "ENV": "", "PATH": str(root) + os.pathsep + os.environ["PATH"],
                         "OUTCOME": outcome, "EXPECTED_HEAD": HEAD, "GITHUB_REPOSITORY": SUPPLEMENTARY,
                         "SOURCE_READ_TOKEN": "synthetic-read-token", "CALL_LOG": str(log)})
                calls = log.read_text().splitlines() if log.exists() else []
                self.assertEqual(0 if outcome in {"stale", "proof-failed"} else 1, len(calls), result.stderr)
                self.assertEqual(outcome in {"current", "stale"}, result.returncode == 0, result.stderr)
                if calls:
                    self.assertEqual("api --method POST repos/lightning-it/github-management-lit/actions/workflows/terraform-github-management.yml/dispatches --input promotion-dispatch.json", calls[0])
                    self.assertEqual({"ref": "main", "inputs": {"operation": "native-promotion-prepare",
                        "repository": "ansible-collection-supplementary", "policy_group": "repository_quality",
                        "runtime_develop_sha": HEAD}}, json.loads((root / "promotion-dispatch.json").read_bytes()))

if __name__ == "__main__":
    unittest.main()
