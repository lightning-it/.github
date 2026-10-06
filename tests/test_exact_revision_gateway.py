"""Exercise the single-review protected gateway without any provider traffic."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import exact_revision_gateway as gateway


class SingleReviewGatewayTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name) / "review"
        self.directory.mkdir(mode=0o700)
        self.root = Path(self.temporary.name) / "installed"
        self.payload = b"diff --git a/a b/a\n--- a/a\n+++ b/a\n@@ -1 +1 @@\n-old\n+new\n"
        prompt = (ROOT / ".github/codex/prompts/review-exact-head.md").read_bytes()
        schema = (ROOT / ".github/codex/schemas/exact-head-review.schema.json").read_bytes()
        self.metadata = {key: "a" * (64 if key.endswith("sha256") else 40) for key in gateway.BINDINGS}
        self.metadata.update(diff_sha256=gateway.review.sha(self.payload), review_bytes=len(self.payload),
                             prompt_sha256=gateway.review.sha(prompt), schema_sha256=gateway.review.sha(schema))
        for name, data in (("change.patch", self.payload), ("review-prompt.md", prompt),
                           ("review-schema.json", schema), ("review-metadata.json", gateway.review.canonical(self.metadata))):
            (self.directory / name).write_bytes(data)
        gateway.prepare(self.root, self.directory, 42, os.getuid())
        self.state, self.prompt = gateway.context(self.root, 42, uid=os.getuid())
        self.reviewer = gateway.Reviewer(self.state, self.prompt, self.root / "public")
        self.result = {key: self.metadata[key] for key in gateway.BINDINGS}
        self.result.update(verdict="PASS", summary="No findings", findings=[])

    def request(self):
        return {"model": gateway.config.profile()["model"], "input": self.prompt,
                "instructions": "Protected action instructions", "tools": [],
                "text": {"format": {"type": "json_schema", "name": "review", "schema": {"type": "object"}}}}

    def response(self):
        return {"id": "resp_fixture", "model": gateway.config.profile()["model"], "status": "completed",
                "service_tier": "default", "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
                "output": [{"type": "message", "role": "assistant", "status": "completed",
                            "content": [{"type": "output_text", "text": json.dumps(self.result)}]}]}

    def test_full_context_count_precedes_paid_call_and_root_receipt_wins(self):
        calls = []
        def worker(request, credential, deadline, *, counting=False):
            calls.append((counting, copy.deepcopy(request)))
            if counting:
                return gateway.review.canonical({"object": "response.input_tokens", "input_tokens": 10})
            return gateway.review.canonical(self.response())
        # Real transport + budget; only fixed-network worker is simulated.
        with patch.object(gateway.transport, "run_worker", side_effect=worker):
            self.reviewer.submit(self.request(), "fixture-secret")
        self.assertEqual([item[0] for item in calls], [True, False])
        self.assertEqual(calls[0][1], gateway.transport.count_request(calls[1][1]))
        self.assertIn(self.payload.decode(), calls[0][1]["input"])
        self.assertEqual(calls[1][1]["truncation"], "disabled")
        (self.directory / "result.json").write_text('{"verdict":"forged"}')
        original = gateway.read_owned
        with patch.object(gateway, "root_for", return_value=self.root), patch.object(gateway, "read_owned", wraps=gateway.read_owned) as read:
            # Non-root tests exercise the same checks using the test owner.
            read.side_effect = lambda p, uid, size: original(p, os.getuid(), size)
            with patch.object(gateway, "owned_directory", side_effect=lambda p, uid: None):
                gateway.collect(self.directory, 42)
        self.assertEqual(json.loads((self.directory / "result.json").read_text()), self.result)
        self.assertNotIn("fixture-secret", (self.root / "public/receipt.json").read_text())
        with patch.object(gateway.transport, "run_worker") as worker, self.assertRaises(gateway.review.ReviewError):
            self.reviewer.submit(self.request(), "fixture-secret")
        worker.assert_not_called()

    def test_over_budget_never_calls_response_endpoint(self):
        def worker(request, credential, deadline, *, counting=False):
            self.assertTrue(counting)
            return gateway.review.canonical({"object": "response.input_tokens", "input_tokens": 400_001})
        with patch.object(gateway.transport, "run_worker", side_effect=worker) as worker, self.assertRaises(gateway.review.ReviewError):
            self.reviewer.submit(self.request(), "fixture")
        self.assertEqual(worker.call_count, 1)
        self.assertTrue((self.root / "public/failure.json").exists())
        self.assertFalse((self.root / "public/receipt.json").exists())

    def test_unknown_response_terminal_no_second_count_or_model(self):
        def worker(request, credential, deadline, *, counting=False):
            if counting:
                return gateway.review.canonical({"object": "response.input_tokens", "input_tokens": 10})
            raise TimeoutError
        with patch.object(gateway.transport, "run_worker", side_effect=worker) as worker:
            with self.assertRaises(TimeoutError):
                self.reviewer.submit(self.request(), "fixture")
            with self.assertRaises(gateway.review.ReviewError):
                self.reviewer.submit(self.request(), "fixture")
        self.assertEqual(worker.call_count, 2)
        self.assertEqual(json.loads((self.root / "public/failure.json").read_text())["provider_state"], "unknown")

    def test_missing_full_input_blocks_before_count(self):
        with patch.object(gateway.transport, "run_worker") as worker, self.assertRaises(gateway.review.ReviewError):
            self.reviewer.submit({"model": gateway.config.profile()["model"], "input": "summary only"}, "fixture")
        worker.assert_not_called()

    def test_malformed_or_wrong_binding_never_yields_receipt(self):
        self.result["head_sha"] = "b" * 40
        def worker(request, credential, deadline, *, counting=False):
            return gateway.review.canonical({"object": "response.input_tokens", "input_tokens": 10} if counting else self.response())
        with patch.object(gateway.transport, "run_worker", side_effect=worker), self.assertRaises(gateway.review.ReviewError):
            self.reviewer.submit(self.request(), "fixture")
        self.assertFalse((self.root / "public/receipt.json").exists())

    def test_protected_closure_drift_rejected(self):
        path = self.root / "code/bounded_review_config.py"
        path.chmod(0o644)
        path.write_text("changed")
        with self.assertRaises(gateway.review.ReviewError):
            gateway.context(self.root, 42, uid=os.getuid())

    def test_omitted_default_and_explicit_single_use_actual_shell_gateway(self):
        import yaml
        workflow = yaml.safe_load((ROOT / ".github/workflows/release-bot-exact-head-review.yml").read_text())
        inputs = workflow.get("on", workflow.get(True))["workflow_dispatch"]["inputs"]
        self.assertEqual(inputs["bounded_mode"]["default"], "single")
        steps = workflow["jobs"]["exact-revision-codex-review"]["steps"]
        install = next(step for step in steps if step.get("id") == "bounded-subject")
        self.assertNotIn("!= ''", install["if"])
        self.assertIn("exact_revision_gateway.py install", install["run"])
        self.assertNotIn("bounded_review_controller.py", install["run"].split("else")[0])
        barrier = next(step for step in steps if step["name"].startswith("Require complete-request"))
        for value, expected in (("", 1), ("false", 1), ("true", 0)):
            result = subprocess.run(["bash", "-c", barrier["run"]], env={**os.environ, "BUDGETED_GATEWAY_INSTALLED": value}, capture_output=True)
            self.assertEqual(result.returncode, expected)
        for name in gateway.CLOSURE:
            if (ROOT / "default/scripts").is_dir():
                self.assertEqual((ROOT / "scripts" / name).read_bytes(), (ROOT / "default/scripts" / name).read_bytes())

    def test_default_and_single_execute_install_shell_without_unit_dispatch(self):
        import yaml
        workflow = yaml.safe_load((ROOT / '.github/workflows/release-bot-exact-head-review.yml').read_text())
        job = workflow['jobs']['exact-revision-codex-review']
        self.assertIn("|| 'single'", job['env']['BOUNDED_MODE'])
        steps = job['steps']
        shell = next(step['run'] for step in steps if step.get('id') == 'bounded-subject')
        binary = Path(self.temporary.name) / 'bin'
        binary.mkdir()
        for name, text in {
            'sudo': '#!/bin/bash\nprintf "%s\\n" "$*" >>"$CALLS"\n',
            'python3': '#!/bin/bash\nexit 99\n',
            'jq': '#!/bin/bash\necho 42555\n',
        }.items():
            (binary / name).write_text(text)
            (binary / name).chmod(0o755)
        default = workflow.get('on', workflow.get(True))['workflow_dispatch']['inputs']['bounded_mode']['default']
        for mode in (default, 'single'):
            calls = Path(self.temporary.name) / 'install-calls'
            output = Path(self.temporary.name) / 'install-output'
            calls.write_text('')
            output.write_text('')
            result = subprocess.run(['bash', '-c', shell], text=True, capture_output=True,
                                    env={**os.environ, 'PATH': str(binary) + os.pathsep + os.environ['PATH'],
                                         'BOUNDED_MODE': mode, 'GITHUB_RUN_ID': '42',
                                         'CALLS': str(calls), 'GITHUB_OUTPUT': str(output)})
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(calls.read_text().splitlines(),
                             ['-n python3 -E -s trusted-controller/exact_revision_gateway.py install --run-id 42'])
            self.assertIn('endpoint=http://127.0.0.1:42555/responses', output.read_text())
            self.assertIn('installed=true', output.read_text())

    def test_actual_fleet_copy_blocks_install_complete_closure(self):
        workflows = ('sync-ee-containers.yml', 'sync-ansible-collections.yml',
                     'sync-ansible-inventories.yml', 'sync-playbook-runbook-repos.yml')
        for name in workflows:
            path = ROOT / '.github/workflows' / name
            if not path.exists():
                continue
            text = path.read_text()
            start = text.index('python3 "${SRC_DEFAULT}/../scripts/sync-exact-review-assets.py"')
            shell = text[start:].split('--target .', 1)[0] + '--target .'
            target = Path(self.temporary.name) / name
            target.mkdir()
            result = subprocess.run(['bash', '-euc', shell], cwd=target, capture_output=True,
                                    env={**os.environ, 'SRC_DEFAULT': str(ROOT / 'default')})
            self.assertEqual(result.returncode, 0, result.stderr)
            for asset in gateway.CLOSURE:
                self.assertEqual((target / 'scripts' / asset).read_bytes(), (ROOT / 'scripts' / asset).read_bytes())

    def test_actual_production_dispatchers_select_single(self):
        import re
        for path in (ROOT / '.github/workflows').glob('*.yml'):
            text = path.read_text()
            if path.name == 'release-bot-exact-head-review.yml':
                continue
            for dispatch in re.finditer(r'gh workflow run release-bot-exact-head-review.yml (?:\\\n[^\n]+)+', text):
                command = dispatch.group()
                self.assertIn('-f bounded_mode=single', command, path.name)
                self.assertNotIn('bounded_mode=parent', command)
