from __future__ import annotations

import runpy
import unittest
from unittest import mock
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ChangedPathsTests(unittest.TestCase):
    def setUp(self) -> None:
        namespace = runpy.run_path(str(ROOT / "scripts" / "lit-push-ready.py"))
        self.changed_paths = namespace["changed_paths"]

    def test_parses_spaces_and_rename_source_without_porcelain_arrows(self) -> None:
        status = (
            " M ordinary path.txt\0"
            "R  safe-destination.txt\0"
            "secrets/source-token.txt\0"
        )
        with mock.patch.dict(
            self.changed_paths.__globals__,
            {"git_output": mock.Mock(return_value=status)},
        ):
            self.assertCountEqual(
                [
                    "ordinary path.txt",
                    "safe-destination.txt",
                    "secrets/source-token.txt",
                ],
                self.changed_paths(),
            )

    def test_rejects_rename_without_source_path(self) -> None:
        with mock.patch.dict(
            self.changed_paths.__globals__,
            {"git_output": mock.Mock(return_value="R  destination.txt\0")},
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "rename/copy status is missing its paired path",
            ):
                self.changed_paths()


class GovernedRemoteTests(unittest.TestCase):
    def setUp(self) -> None:
        namespace = runpy.run_path(str(ROOT / "scripts" / "lit-push-ready.py"))
        self.governed_remote = namespace["governed_push_remote_from_url"]

    def test_accepts_github_profile_https_and_ssh_remotes(self) -> None:
        for url in (
            "https://github.com/lightning-it/.github.git",
            "ssh://git@github.com/lightning-it/.github.git",
            "git@github.com:lightning-it/.github.git",
        ):
            with self.subTest(url=url):
                remote = self.governed_remote("origin", url)
                self.assertEqual("lightning-it/.github", remote["repository"])
                self.assertEqual("github.com", remote["host"])

    def test_rejects_other_dot_prefixed_repository_names(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "Lightning IT repository"):
            self.governed_remote(
                "origin", "https://github.com/lightning-it/.github-private.git"
            )


if __name__ == "__main__":
    unittest.main()
