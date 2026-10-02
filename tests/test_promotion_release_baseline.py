from __future__ import annotations

import importlib.util
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "verify-promotion-evidence.py"
SPEC = importlib.util.spec_from_file_location("release_baseline_evidence", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ReviewedReleaseBaselineTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.repository = Path(temporary.name).resolve()
        self.environment = {
            name: value for name, value in os.environ.items() if not name.startswith("GIT_")
        }
        self.environment.update({"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"})
        self.git("init", "--quiet", "-b", "initial")
        self.write("galaxy.yml", "namespace: lit\nname: example\nversion: 1.13.0\n")
        self.write("CHANGELOG.rst", "old release\n")
        self.fragments = ["fix.yml", "123.fix.yml", "[a].yaml", "fix with space.yml"]
        for fragment in self.fragments:
            self.write(f"changelogs/fragments/{fragment}", "bugfixes: [fix]\n")
        self.write("roles/example/tasks/main.yml", "---\n[]\n")
        initial = self.commit("initial")
        self.git("checkout", "--quiet", "-b", "main")
        self.write("galaxy.yml", "namespace: lit\nname: example\nversion: 1.14.0\n")
        self.write("CHANGELOG.rst", "published release\n")
        for fragment in self.fragments:
            (self.repository / f"changelogs/fragments/{fragment}").unlink()
        self.main = self.commit("published release metadata")
        self.git("checkout", "--quiet", "-b", "develop", initial)
        self.write("roles/example/tasks/main.yml", "---\n- name: Preserved feature\n  ansible.builtin.debug:\n    msg: feature\n")
        self.write("changelogs/fragments/a.yaml", "bugfixes: [not released yet]\n")
        self.previous = self.commit("feature remains in develop")
        self.git("checkout", "--quiet", "-b", "backsync", self.main)
        self.git("merge", "--quiet", "--no-ff", self.previous, "-m", "merge protected develop into backsync")
        self.head = self.git("rev-parse", "HEAD")
        self.pull = {
            "title": "chore(release): sync v1.14.0 back to develop",
            "user": {"login": "litroc", "id": 76040632, "type": "User"},
            "head": {"ref": "backsync/release-v1.14.0-to-develop"},
        }

    def git(self, *arguments: str) -> str:
        return subprocess.check_output(
            ["git", "-c", "user.name=test", "-c", "user.email=test@example.test", *arguments],
            cwd=self.repository,
            env=self.environment,
            text=True,
            stderr=subprocess.PIPE,
        ).strip()

    def write(self, path: str, value: str) -> None:
        target = self.repository / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(value, encoding="utf-8")

    def commit(self, message: str) -> str:
        self.git("add", "--all")
        self.git("commit", "--quiet", "-m", message)
        return self.git("rev-parse", "HEAD")

    def validate(self, *, merge_sha: str | None = None) -> None:
        MODULE.validate_reviewed_release_baseline(
            self.repository,
            repository="lightning-it/example",
            expected_main=self.main,
            merge={"base_sha": self.previous, "head_sha": self.head, "merge_sha": merge_sha or self.head},
            pull=self.pull,
        )

    def test_real_git_backsync_binds_main_without_discarding_develop_feature(self) -> None:
        self.validate()
        self.assertEqual("copilot", MODULE.expected_evidence_kind(self.pull, repository="lightning-it/example"))
        self.assertIn("Preserved feature", self.git("show", f"{self.head}:roles/example/tasks/main.yml"))
        self.assertEqual("bugfixes: [not released yet]", self.git("show", f"{self.head}:changelogs/fragments/a.yaml"))

    def test_retained_consumed_fragment_is_rejected_even_when_absent_from_diff(self) -> None:
        for fragment in self.fragments:
            with self.subTest(fragment=fragment):
                path = f"changelogs/fragments/{fragment}"
                self.write(path, "bugfixes: [fix]\n")
                self.head = self.commit("restore unchanged released fragment")
                self.assertEqual("", self.git("--literal-pathspecs", "diff", "--name-only", self.previous, self.head, "--", path))
                with self.assertRaisesRegex(MODULE.EvidenceError, "release-baseline-consumed-fragment-retained"):
                    self.validate()
                (self.repository / path).unlink()
                self.head = self.commit("remove consumed fragment again")

    def test_develop_only_fragment_cannot_be_deleted(self) -> None:
        (self.repository / "changelogs/fragments/a.yaml").unlink()
        self.head = self.commit("delete unreleased develop fragment")
        with self.assertRaisesRegex(MODULE.EvidenceError, "release-baseline-fragment-not-consumed"):
            self.validate()

    def test_unchanged_old_metadata_cannot_escape_main_comparison(self) -> None:
        self.write("CHANGELOG.rst", "old release\n")
        self.head = self.commit("restore previous changelog")
        self.assertEqual("", self.git("diff", "--name-only", self.previous, self.head, "--", "CHANGELOG.rst"))
        with self.assertRaisesRegex(MODULE.EvidenceError, "release-baseline-not-exact-main-metadata"):
            self.validate()

    def test_runtime_content_in_backsync_is_rejected(self) -> None:
        self.write("roles/example/tasks/main.yml", "---\n[]\n")
        self.head = self.commit("unrelated runtime change")
        with self.assertRaisesRegex(MODULE.EvidenceError, "release-baseline-content-scope"):
            self.validate()

    def test_merge_resolution_cannot_introduce_unreviewed_content(self) -> None:
        reviewed_head = self.head
        self.write("roles/example/tasks/main.yml", "---\n[]\n")
        changed_merge = self.commit("unreviewed merge resolution")
        self.assertEqual(reviewed_head, self.head)
        with self.assertRaisesRegex(MODULE.EvidenceError, "release-baseline-merge-tree-differs"):
            self.validate(merge_sha=changed_merge)

    def test_mismatching_main_metadata_is_rejected(self) -> None:
        self.write("CHANGELOG.rst", "not the main release\n")
        self.head = self.commit("tampered release metadata")
        with self.assertRaisesRegex(MODULE.EvidenceError, "release-baseline-not-exact-main-metadata"):
            self.validate()

    def test_retained_or_new_fragment_is_rejected(self) -> None:
        self.write("changelogs/fragments/extra.yml", "bugfixes: [extra]\n")
        self.head = self.commit("extra fragment")
        with self.assertRaisesRegex(MODULE.EvidenceError, "release-baseline-fragment-not-removed"):
            self.validate()

    def test_symlink_metadata_is_rejected(self) -> None:
        target = self.repository / "CHANGELOG.rst"
        target.unlink()
        target.symlink_to("galaxy.yml")
        self.head = self.commit("symlink instead of release metadata")
        with self.assertRaisesRegex(MODULE.EvidenceError, "release-baseline-metadata-mode"):
            self.validate()

    def test_unbound_branch_title_version_or_author_is_rejected(self) -> None:
        for field, value, expected in (
            ("ref", "fix/release-metadata", "release-baseline-ref"),
            ("ref", "backsync/release-v1.15.0-to-develop", "release-baseline-title"),
            ("title", "chore: metadata", "release-baseline-title"),
            ("user", {"login": "unknown[bot]", "id": 123, "type": "Bot"}, "copilot-ingress-author-type"),
        ):
            with self.subTest(field=field, value=value):
                destination = self.pull["head"] if field == "ref" else self.pull
                original = destination[field]
                destination[field] = value
                try:
                    with self.assertRaisesRegex(MODULE.EvidenceError, expected):
                        self.validate()
                finally:
                    destination[field] = original

    def test_already_ancestral_or_missing_main_is_rejected(self) -> None:
        original = self.previous
        self.previous = self.main
        with self.assertRaisesRegex(MODULE.EvidenceError, "release-baseline-main-introduction"):
            self.validate()
        self.previous = original
        self.head = original
        with self.assertRaisesRegex(MODULE.EvidenceError, "release-baseline-main-introduction"):
            self.validate()

    def test_non_version_galaxy_changes_are_rejected_even_if_equal_to_main(self) -> None:
        self.git("checkout", "--quiet", "main")
        self.write("galaxy.yml", "namespace: lit\nname: different\nversion: 1.14.0\n")
        self.main = self.commit("different collection identity")
        self.git("checkout", "--quiet", "backsync")
        self.git("merge", "--quiet", "--no-ff", self.main, "-m", "merge changed main")
        self.head = self.git("rev-parse", "HEAD")
        with self.assertRaisesRegex(MODULE.EvidenceError, "release-baseline-galaxy-not-version-only"):
            self.validate()

    def test_galaxy_whitespace_changes_are_rejected_even_if_equal_to_main(self) -> None:
        canonical = b"namespace: lit\nname: example\nversion: 1.14.0\n"
        for content in (
            b"\n" + canonical,
            canonical + b"\n",
            canonical.rstrip(b"\n"),
            canonical + b" \t",
            canonical.replace(b"\n", b"\r\n"),
        ):
            with self.subTest(content=content):
                self.git("checkout", "--quiet", "main")
                (self.repository / "galaxy.yml").write_bytes(content)
                self.main = self.commit("change release whitespace")
                self.git("checkout", "--quiet", "backsync")
                self.git("merge", "--quiet", "--no-ff", self.main, "-m", "merge changed main")
                self.head = self.git("rev-parse", "HEAD")
                with self.assertRaisesRegex(MODULE.EvidenceError, "release-baseline-galaxy-not-version-only"):
                    self.validate()

    def test_git_blob_preserves_bytes_and_fails_closed(self) -> None:
        content = b"\r\nunchanged: \xff\r\n \t\n"
        (self.repository / "bytes.yml").write_bytes(content)
        revision = self.commit("byte-preserving fixture")
        self.assertEqual(content, MODULE.git_blob(f"{revision}:bytes.yml", self.repository))
        with self.assertRaisesRegex(MODULE.EvidenceError, "git-blob-read-failed"):
            MODULE.git_blob(f"{revision}:missing.yml", self.repository)
        with mock.patch.object(MODULE, "MAX_API_BYTES", len(content) - 1):
            with self.assertRaisesRegex(MODULE.EvidenceError, "command-output-too-large"):
                MODULE.git_blob(f"{revision}:bytes.yml", self.repository)


if __name__ == "__main__":
    unittest.main()
