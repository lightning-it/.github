"""Security regressions for the protected exact-revision materializer."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MATERIALIZER = ROOT / "scripts/materialize-exact-revision-review.py"


def load_materializer() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(
        "materialize_exact_revision_review",
        MATERIALIZER,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load the exact-revision materializer")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ExactRevisionMaterializerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = load_materializer()

    def test_external_commands_are_bounded(self) -> None:
        with (
            mock.patch.object(
                self.module.subprocess,
                "run",
                side_effect=subprocess.TimeoutExpired(["gh", "api"], 120),
            ),
            self.assertRaisesRegex(
                self.module.MaterializationError,
                "timed out after 120 seconds",
            ),
        ):
            self.module.run(["gh", "api"], environment={})

    def test_protected_reader_rejects_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "target"
            target.write_text("{}\n", encoding="utf-8")
            link = Path(temporary) / "link"
            link.symlink_to(target)
            with self.assertRaisesRegex(
                self.module.MaterializationError,
                "unavailable",
            ):
                self.module.protected_asset_bytes(link, "test asset")

    def test_protected_writer_rejects_replacement_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "target"
            target.write_text("unchanged", encoding="utf-8")
            link = Path(temporary) / "link"
            link.symlink_to(target)
            with self.assertRaisesRegex(
                self.module.MaterializationError,
                "cannot be opened safely",
            ):
                self.module.write_owned_regular_file(link, b"replacement", "test")
            self.assertEqual("unchanged", target.read_text(encoding="utf-8"))

    def test_protected_writer_overrides_restrictive_umask(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "asset"
            previous = os.umask(0o777)
            try:
                self.module.write_owned_regular_file(path, b"protected", "test")
            finally:
                os.umask(previous)
            self.assertEqual(0o600, path.stat().st_mode & 0o777)
            self.assertEqual(b"protected", path.read_bytes())

    def test_metadata_binding_rejects_non_object(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            review = Path(temporary)
            (review / "review-metadata.json").write_text("[]\n", encoding="utf-8")
            with self.assertRaisesRegex(
                self.module.MaterializationError,
                "must be a JSON object",
            ):
                self.module.bind_assets(review, {})


if __name__ == "__main__":
    unittest.main()
