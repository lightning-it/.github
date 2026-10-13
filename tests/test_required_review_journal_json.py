"""Offline parser regressions; no workflow, network or production evidence."""

import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "required_review_journal_json", ROOT / "scripts/required-review-journal-json.py")
J = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(J)


class JournalJsonTests(unittest.TestCase):
    def rejected(self, raw, reason):
        with self.assertRaisesRegex(J.JournalRejected, "^" + reason + "$"):
            J.parsed(raw)

    def test_plain_values_and_utf8_are_preserved(self):
        for value in ({"records": {}, "counter": 7, "enabled": True},
                      [None, False, -7, "München"], None, True, 42, "text"):
            with self.subTest(value=value):
                self.assertEqual(J.parsed(json.dumps(value, ensure_ascii=False).encode()), value)

    def test_byte_limit_is_inclusive_and_requires_exact_bytes(self):
        self.assertEqual(J.parsed(b"0" + b" " * (J.MAX_BYTES - 1)), 0)
        self.rejected(b"0" + b" " * J.MAX_BYTES, "journal-byte-limit")
        for value in ("{}", bytearray(b"{}"), memoryview(b"{}"), None):
            with self.subTest(value=value):
                self.rejected(value, "journal-byte-limit")

    def test_container_depth_limit_is_inclusive(self):
        for opening, closing, levels in ((b"[", b"]", J.MAX_DEPTH),
                                         (b'{"key":', b"}", J.MAX_DEPTH),
                                         (b'{"key":[', b"]}", J.MAX_DEPTH // 2)):
            with self.subTest(opening=opening):
                J.parsed(opening * levels + b"0" + closing * levels)
                self.rejected(opening * (levels + 1) + b"0" + closing * (levels + 1),
                              "journal-depth-limit")

    def test_original_4001_byte_nested_input_is_rejected_before_decoder(self):
        raw = b"[" * 2000 + b"0" + b"]" * 2000
        self.assertEqual(len(raw), 4001)
        with patch.object(J.json, "loads") as decoder:
            self.rejected(raw, "journal-depth-limit")
            decoder.assert_not_called()

    def test_brackets_quotes_and_escapes_in_strings_do_not_add_depth(self):
        value = {"[" * 2000: '[{]}"\\' * 2000, "escaped": '\\"[[[', "end": "\\"}
        self.assertEqual(J.parsed(json.dumps(value).encode()), value)
        raw = json.dumps("[" * 2000).encode()
        self.assertEqual(J.parsed(raw), "[" * 2000)

    def test_decoder_recursion_error_is_a_fixed_rejection(self):
        with patch.object(J.json, "loads", side_effect=RecursionError("untrusted detail")):
            self.rejected(b"{}", "journal-json")

    def test_duplicate_keys_are_rejected_including_escaped_aliases(self):
        for raw in (b'{"a":1,"a":2}', b'{"a":1,"\\u0061":2}',
                    b'{"outer":{"a":1,"a":2}}'):
            with self.subTest(raw=raw):
                self.rejected(raw, "duplicate-json-key")

    def test_noninteger_numbers_and_constants_are_rejected(self):
        for raw in (b"1.0", b"1e3", b"NaN", b"Infinity", b"-Infinity", b"[2.5]"):
            with self.subTest(raw=raw):
                self.rejected(raw, "noninteger-json-number")

    def test_malformed_json_and_non_utf8_are_fixed_rejections(self):
        for raw in (b"", b"{", b"[}", b"][]", b'{"a":1,}', b'"unterminated',
                    b'"\\x"', b'"\x00"', b'"\xff"', b"{} trailing",
                    "{}".encode("utf-16")):
            with self.subTest(raw=raw):
                self.rejected(raw, "journal-json")


if __name__ == "__main__":
    unittest.main()
