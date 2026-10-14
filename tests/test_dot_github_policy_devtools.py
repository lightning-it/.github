"""Exercise the real protected shell/managed Devtools execution boundary."""

import ast
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DISPATCHER = "scripts/dot-github-policy-devtools.sh"


class ProtectedDispatcherTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.source = Path(self.temporary.name)
        (self.source / "scripts").mkdir()
        self.bin = self.source / "bin"
        self.bin.mkdir()
        for path in (DISPATCHER, "scripts/wunder-devtools-ee.sh"):
            shutil.copyfile(ROOT / path, self.source / path)
        self.record = self.source / "docker-call.json"
        self.output = self.source / "gha-output"
        docker = self.bin / "docker"
        docker.write_text(f'''#!{sys.executable}
import json, os, pathlib, sys
if sys.argv[1] == "info":
    raise SystemExit(0)
pathlib.Path({str(self.record)!r}).write_text(json.dumps({{"argv": sys.argv[1:], "environment": dict(os.environ)}}))
if sys.argv[-1] == "preflight":
    print("binding=" + "a" * 64 + "\\nreuse-run=")
else:
    print("LI319_APPROVAL_BINDING=" + "a" * 64)
''')
        docker.chmod(0o755)

    def run_dispatcher(self, mode, **changes):
        environment = dict(os.environ, PATH=str(self.bin) + os.pathsep + os.environ["PATH"],
            GITHUB_ACTIONS="true", REPOSITORY="lightning-it/.github", GH_TOKEN="fixture-token",
            GITHUB_OUTPUT=str(self.output), OPENAI_API_KEY="unused",
            WUNDER_DEVTOOLS_PRIVILEGED="1", WUNDER_DEVTOOLS_DOCKER_SOCKET="required",
            EVENT_TITLE_JSON=json.dumps("A title with $(unsafe) and `unsafe`"))
        environment.update(changes)
        return subprocess.run(["bash", str(self.source / DISPATCHER), mode], env=environment,
                              capture_output=True, text=True, check=False)

    def test_every_mode_uses_pinned_readonly_socket_free_managed_adapter(self):
        engine = ast.parse((ROOT / "scripts/lit-push-ready.py").read_text())
        image = next(ast.literal_eval(n.value) for n in engine.body if isinstance(n, ast.Assign)
                     and any(isinstance(t, ast.Name) and t.id == "COPILOT_DEVTOOL_IMAGE" for t in n.targets))
        for mode in ("preflight", "approve", "verify"):
            with self.subTest(mode=mode):
                result = self.run_dispatcher(mode)
                self.assertEqual(result.returncode, 0, result.stderr)
                call = json.loads(self.record.read_text())
                argv = call["argv"]
                self.assertIn(image, argv)
                self.assertIn("--read-only", argv)
                self.assertEqual(argv[argv.index("--network") + 1], "bridge")
                self.assertEqual(argv[argv.index("--cap-drop") + 1], "ALL")
                self.assertIn("no-new-privileges=true", argv)
                self.assertIn("--user", argv)
                self.assertNotIn("--privileged", argv)
                self.assertNotIn("--cap-add", argv)
                self.assertFalse(any("docker.sock" in arg for arg in argv))
                self.assertIn("GH_TOKEN=fixture-token", argv)
                self.assertFalse(any("OPENAI_API_KEY" in arg for arg in argv))
                self.assertNotIn("OPENAI_API_KEY", call["environment"])
                self.assertIn('EVENT_TITLE_JSON="A title with $(unsafe) and `unsafe`"', argv)
                self.assertTrue(any(arg.endswith(":/workspace:ro") for arg in argv))
                self.assertIn("GITHUB_OUTPUT=/tmp/wunder/policy-output", argv)
        self.assertEqual(self.output.read_text(), "binding=" + "a" * 64 + "\nreuse-run=\n")

    def test_unknown_mode_and_non_native_or_wrong_target_never_start_container(self):
        for mode, changes in (("arbitrary", {}), ("verify", {"GITHUB_ACTIONS": "false"}),
                              ("verify", {"REPOSITORY": "lightning-it/other"})):
            with self.subTest(mode=mode, changes=changes):
                self.assertNotEqual(self.run_dispatcher(mode, **changes).returncode, 0)
                self.assertFalse(self.record.exists())

    def test_all_native_jobs_use_protected_dispatcher_without_automatic_cancellation(self):
        workflow = yaml.safe_load((ROOT / ".github/workflows/dot-github-current-revision-required.yml").read_text())
        self.assertIs(workflow["concurrency"]["cancel-in-progress"], False)
        for job_id, job in workflow["jobs"].items():
            checkout = job["steps"][0]["with"]
            self.assertEqual(checkout["repository"], "lightning-it/.github")
            expected_ref = 'refs/heads/main' if job_id == 'metadata' else "${{ github.workflow_sha }}"
            self.assertEqual(checkout["ref"], expected_ref)
            self.assertIn(DISPATCHER, checkout["sparse-checkout"].splitlines())
            self.assertIn("scripts/wunder-devtools-ee.sh", checkout["sparse-checkout"].splitlines())
            run = job["steps"][1]["run"]
            self.assertTrue(run.startswith("bash protected-source/" + DISPATCHER + " "))
            self.assertNotIn("python3", run)


if __name__ == "__main__":
    unittest.main()
