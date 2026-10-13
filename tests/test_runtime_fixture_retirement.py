"""One exact historical removal must never authorize new or live key content."""

import json
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest import mock

class RuntimeFixtureRetirementTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).resolve().parents[1] / 'scripts/lit-push-ready.py'
        spec = importlib.util.spec_from_file_location('fixture_retirement_engine', path)
        self.module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = self.module
        self.addCleanup(sys.modules.pop, spec.name, None)
        spec.loader.exec_module(self.module)
        encoded = Path(__file__).with_name("li150-streaming-retirement-base.hex")
        self.base = bytes.fromhex(encoded.read_text().strip()).decode("utf-8")
        self.line = self.base.splitlines()[27]
        self.replacement = '            "-----BEGIN " + "OPENSSH PRIVATE KEY-----",'
        self.head = self.base.replace(self.line + "\n", self.replacement + "\n", 1)
        self.path = "tests/test_push_ready_streaming.py"
        self.change = SimpleNamespace(
            paths=[self.path], base_tip="a" * 40, head_commit="b" * 40,
            base_commit="c" * 40,
        )

    def authorize(self, *, base=None, head=None, manifest=None, merge_base=None, modes=None):
        blobs = {
            self.change.base_tip: self.base if base is None else base,
            self.change.base_commit: (
                self.base if base is None else base
            ) if merge_base is None else merge_base,
            self.change.head_commit: self.head if head is None else head,
        }
        with mock.patch.object(
            self.module, "repository_blob_at_commit",
            side_effect=lambda commit, path, **kwargs: blobs[commit],
        ), mock.patch.object(
            self.module, "secret_fixture_manifest_at_commit", return_value=manifest or {}
        ), mock.patch.object(
            self.module, "git_tree_entry",
            side_effect=lambda commit, path: (
                f"{(modes or {}).get(commit, '100644')} blob {'d' * 40}\t{path}\0"
            ),
        ):
            return self.module.bootstrap_secret_fixture_manifest(self.change)

    def test_actual_archived_blob_has_exact_runtime_only_replacement(self):
        proof = self.authorize()
        self.assertIsInstance(proof, self.module.RetiredFixtureLines)
        self.assertEqual({self.path}, set(proof))
        self.assertEqual({28}, set(proof[self.path]))
        patch = (
            f"diff --git a/{self.path} b/{self.path}\n"
            f"--- a/{self.path}\n+++ b/{self.path}\n@@ -28 +28 @@\n"
            f"-{self.line}\n+{self.replacement}\n"
        )
        self.assertEqual(0, self.module.scan_chunks(
            self.module.filtered_scan_chunks([patch], proof, diff=True)
        ))

    def test_changed_base_blob_is_not_authorized(self):
        with self.assertRaisesRegex(RuntimeError, "base blob"):
            self.authorize(base=self.base + "\n")

    def test_live_base_cannot_substitute_for_the_deleted_line_diff_base(self):
        with self.assertRaisesRegex(RuntimeError, "base blob"):
            self.authorize(merge_base=self.base + "\n")

    def test_mode_changes_on_any_bound_revision_are_not_authorized(self):
        for commit in (self.change.base_tip, self.change.base_commit, self.change.head_commit):
            for mode in ("100755", "120000", "040000"):
                with self.subTest(commit=commit, mode=mode):
                    with self.assertRaisesRegex(RuntimeError, "tree mode"):
                        self.authorize(modes={commit: mode})

    def test_unrelated_path_is_not_authorized(self):
        self.change.paths = ["tests/other.py"]
        with self.assertRaisesRegex(RuntimeError, "exact source"):
            self.authorize()

    def test_added_key_material_or_other_edit_rejects_the_whole_replacement(self):
        with self.assertRaisesRegex(RuntimeError, "exact runtime composition"):
            self.authorize(head=self.head + "extra content\n")

    def test_retained_or_reintroduced_header_is_not_authorized(self):
        with self.assertRaisesRegex(RuntimeError, "exact runtime composition"):
            self.authorize(head=self.base)

    def test_second_use_after_retirement_is_not_authorized(self):
        with self.assertRaisesRegex(RuntimeError, "base blob"):
            self.authorize(base=self.head, head=self.head)

    def test_an_existing_manifest_cannot_be_combined_with_retirement(self):
        with self.assertRaisesRegex(RuntimeError, "no base manifest"):
            self.authorize(manifest={self.path: {28: ("digest", self.line)}})

    def test_head_content_never_receives_the_historical_exception(self):
        proof = self.authorize()
        self.assertTrue(self.module.scan_chunks(self.module.filtered_scan_chunks(
            [self.base], proof, path=self.path
        )) & 1)
        added = (
            f"diff --git a/{self.path} b/{self.path}\n"
            f"--- a/{self.path}\n+++ b/{self.path}\n@@ -28 +28 @@\n"
            f"+{self.line}\n"
        )
        self.assertTrue(self.module.scan_chunks(self.module.filtered_scan_chunks(
            [added], proof, diff=True
        )) & 1)

    def test_active_pem_entry_still_cannot_mask_key_content(self):
        manifest = {"version": 1, "fixtures": [{
            "path": self.path, "line_hex": self.line.encode().hex(),
            "line_number": 28, "purpose": "synthetic-test-fixture",
        }]}
        documented = self.module.parse_secret_fixture_manifest(json.dumps(manifest))
        self.assertTrue(self.module.scan_chunks(self.module.filtered_scan_chunks(
            [self.base], documented, path=self.path
        )) & 1)
