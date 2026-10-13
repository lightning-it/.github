"""Offline reducer and CLI regressions; no GitHub or unmerged adapter dependency."""

from copy import deepcopy
import importlib.util
import io
import itertools
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/required-review-telemetry.py"
SPEC = importlib.util.spec_from_file_location("telemetry", SCRIPT)
TELEMETRY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TELEMETRY)


def sample(time=100, latency=10, failure=False, key="a" * 64):
    return {"schema": "li219-shadow-observation/v1", "authority": "none", "writes": 0,
            "operation_key": key, "binding_digest": "b" * 64, "observed_at": time,
            "metrics": {**dict.fromkeys(TELEMETRY.METRICS, latency),
                        TELEMETRY.FAILURE: failure}}


class TelemetryTests(unittest.TestCase):
    def test_later_failure_is_preserved_in_every_order_with_earliest_latency(self):
        first, later = sample(), sample(time=130, latency=40, failure=True)
        for observations in itertools.permutations([first, later, first]):
            result = TELEMETRY.summarize(list(observations))
            self.assertEqual(1, result["unique_operations"])
            self.assertEqual(1, result["native_failure_with_ready_evidence_count"])
            self.assertEqual(1, result["candidate_rate"])
            self.assertEqual({"observed_samples": 1, "median": 10, "p95": 10},
                             result["statistics"]["request_to_review_seconds"])

    def test_equal_time_tie_is_deterministic_and_failure_is_operation_level(self):
        items = [sample(latency=None), sample(latency=30), sample(latency=10, failure=True)]
        expected = TELEMETRY.summarize(items)
        for permutation in itertools.permutations(items):
            self.assertEqual(expected, TELEMETRY.summarize(list(permutation)))
        self.assertEqual(1, expected["native_failure_with_ready_evidence_count"])

    def test_missing_and_null_metrics_are_unknown_and_empty_cohort_has_no_rate(self):
        item = sample()
        item["metrics"] = {TELEMETRY.FAILURE: False, "producer_job_seconds": None}
        result = TELEMETRY.summarize([item])
        for statistic in result["statistics"].values():
            self.assertEqual({"observed_samples": 0, "median": None, "p95": None}, statistic)
        empty = TELEMETRY.summarize([])
        self.assertIsNone(empty["candidate_rate"])
        self.assertIsNone(empty["measured_false_negative_rate"])
        self.assertEqual("none", result["authority"])
        self.assertEqual(0, result["writes"])

    def test_missing_earliest_metric_is_not_backfilled_from_later(self):
        result = TELEMETRY.summarize([sample(latency=None), sample(time=110, latency=5)])
        self.assertEqual(0, result["statistics"]["producer_job_seconds"]["observed_samples"])

    def test_median_p95_and_candidate_rate_use_unique_operations(self):
        items = [sample(latency=n, key=f"{n:064x}", failure=n == 20) for n in range(1, 21)]
        result = TELEMETRY.summarize(items + items)
        self.assertEqual({"observed_samples": 20, "median": 10.5, "p95": 19},
                         result["statistics"]["producer_job_seconds"])
        self.assertEqual(.05, result["candidate_rate"])

    def test_binding_drift_rejects_even_when_later_sample_would_be_discarded(self):
        item = sample(time=130)
        item["binding_digest"] = "c" * 64
        with self.assertRaisesRegex(ValueError, "binding-drift"):
            TELEMETRY.summarize([sample(), item])

    def test_malformed_discarded_duplicate_is_still_rejected(self):
        item = sample(time=130, latency=-1)
        with self.assertRaisesRegex(ValueError, "metrics-value"):
            TELEMETRY.summarize([sample(), item])

    def test_strict_shapes_and_authority_reject(self):
        for key, value in (("schema", "other"), ("authority", "writer"), ("writes", False),
                           ("writes", 1), ("operation_key", "not-a-digest"),
                           ("binding_digest", 1), ("observed_at", True),
                           ("observed_at", -1), ("observed_at", 10 ** 100),
                           ("metrics", [])):
            item = sample()
            item[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                TELEMETRY.summarize([item])
        for value in (None, "true", 1):
            item = sample()
            item["metrics"][TELEMETRY.FAILURE] = value
            with self.assertRaises(ValueError):
                TELEMETRY.summarize([item])
        for value in ({}, None, [None], [sample()] * (TELEMETRY.MAX_SAMPLES + 1)):
            with self.assertRaises(ValueError):
                TELEMETRY.summarize(value)

    def test_metrics_are_finite_bounded_numbers_not_booleans_or_strings(self):
        for value in (True, "1", -1, float("nan"), float("inf"), 10 ** 1000, [], {}):
            with self.subTest(value=type(value).__name__), self.assertRaises(ValueError):
                TELEMETRY.summarize([sample(latency=value)])
        self.assertEqual(TELEMETRY.summarize([sample(latency=1)]),
                         TELEMETRY.summarize([sample(latency=1.0)]))

    def test_reducer_does_not_mutate_caller_input(self):
        observations = [sample(), sample(failure=True)]
        before = deepcopy(observations)
        TELEMETRY.summarize(observations)
        self.assertEqual(before, observations)

    def cli(self, raw):
        return subprocess.run([sys.executable, str(SCRIPT), "-"], input=raw,
                              capture_output=True, timeout=10, check=False)

    def test_cli_reads_stdin_without_adapter_and_reports_only_advisory_metrics(self):
        result = self.cli(json.dumps([sample(), sample(time=130, failure=True)]).encode())
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(b"", result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual("li219-offline-telemetry/v1", output["schema"])
        self.assertEqual(1, output["native_failure_with_ready_evidence_count"])
        self.assertIsNone(output["measured_false_negative_rate"])

    def test_cli_rejects_malformed_duplicate_nonfinite_and_oversized_json(self):
        for raw in (b"secret-invalid-json", b'{"x":1,"x":2}', b'[NaN]',
                    b'[' * 2000, b'[]' + b' ' * TELEMETRY.MAX_BYTES):
            with self.subTest(size=len(raw)):
                result = self.cli(raw)
                self.assertEqual(1, result.returncode)
                self.assertEqual(b"", result.stderr)
                output = json.loads(result.stdout)
                self.assertEqual("li219-offline-telemetry-rejection/v1", output["schema"])
                self.assertNotIn("secret", result.stdout.decode())

    def test_cli_file_read_is_bounded_and_external_exception_is_sanitized(self):
        with mock.patch("sys.argv", [str(SCRIPT), "/private-input"]), \
                mock.patch.object(Path, "open", return_value=io.BytesIO(b"[]")) as opened, \
                mock.patch("sys.stdout", new_callable=io.StringIO) as output:
            self.assertEqual(0, TELEMETRY.main())
            opened.assert_called_once_with("rb")
            self.assertEqual(0, json.loads(output.getvalue())["unique_operations"])
        with mock.patch("sys.argv", [str(SCRIPT), "/private-input"]), \
                mock.patch.object(Path, "open", side_effect=OSError("secret-path")), \
                mock.patch("sys.stdout", new_callable=io.StringIO) as output:
            self.assertEqual(1, TELEMETRY.main())
            self.assertEqual("invalid-input", json.loads(output.getvalue())["reason"])
            self.assertNotIn("secret", output.getvalue())

    def test_cli_does_not_swallow_control_signals(self):
        with mock.patch("sys.argv", [str(SCRIPT), "/unused"]), \
                mock.patch.object(Path, "open", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                TELEMETRY.main()


if __name__ == "__main__":
    unittest.main()
