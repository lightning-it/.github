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
            self.assertEqual(
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
                "rename/copy status is missing its source path",
            ):
                self.changed_paths()


if __name__ == "__main__":
    unittest.main()
