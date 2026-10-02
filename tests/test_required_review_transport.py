"""Bounded single-object GET transport tests; all network responses are mocked."""

from concurrent.futures import ThreadPoolExecutor
import http.client
import importlib.util
import io
import json
from pathlib import Path
import signal
import time
import unittest
from unittest import mock
import urllib.error


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("transport", ROOT / "scripts/required-review-transport.py")
TRANSPORT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TRANSPORT)


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.reader = TRANSPORT.GitHubReader()
        self.response = mock.MagicMock()
        self.response.__enter__.return_value.status = 200
        self.response.__enter__.return_value.read.return_value = b'{"id":7,"number":7}'
        self.reader.opener.open = mock.Mock(return_value=self.response)
        self.env = mock.patch.dict(TRANSPORT.os.environ, {"GH_TOKEN": "unit-test-placeholder"})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_only_three_fixed_repo_get_routes_and_bounded_read_are_available(self):
        for resource, path in (("pull", "pulls"), ("run", "actions/runs"), ("check", "check-runs")):
            self.assertEqual(7, self.reader.read(resource, 7)["id"])
            request = self.reader.opener.open.call_args.args[0]
            self.assertEqual("GET", request.method)
            self.assertIsNone(request.data)
            self.assertEqual(f"https://api.github.com/repos/lightning-it/.github/{path}/7", request.full_url)
            self.response.__enter__.return_value.read.assert_called_with(2 * 1024 * 1024 + 1)
        self.assertEqual(3, self.reader.requests)

    def test_arbitrary_paths_mutations_and_invalid_identifiers_never_reach_network(self):
        for resource in ("https://evil.invalid", "../pulls", "pull?x=y", "graphql", "PATCH", [], None):
            with self.assertRaises(TRANSPORT.ReadFailure):
                self.reader.read(resource, 7)
        for identifier in (True, 0, -1, "7", 2 ** 63):
            with self.assertRaises(TRANSPORT.ReadFailure):
                self.reader.read("pull", identifier)
        self.reader.opener.open.assert_not_called()

    def test_proxy_inheritance_is_disabled_and_redirect_refused(self):
        with mock.patch.object(TRANSPORT.urllib.request, "build_opener") as build:
            TRANSPORT.GitHubReader()
        self.assertEqual({}, build.call_args.args[0].proxies)
        self.assertIsInstance(build.call_args.args[1], TRANSPORT.NoRedirect)
        with self.assertRaisesRegex(TRANSPORT.ReadFailure, "redirect-refused"):
            TRANSPORT.NoRedirect().redirect_request(None, None, 302, "", {}, "https://evil.invalid")

    def test_request_time_and_byte_limits_fail_closed(self):
        self.reader.max_requests = 1
        self.reader.read("pull", 7)
        with self.assertRaisesRegex(TRANSPORT.ReadFailure, "request-budget-exhausted"):
            self.reader.read("pull", 7)
        self.assertEqual(1, self.reader.opener.open.call_count)
        self.reader.max_requests = 100
        self.reader.expires = time.monotonic() - 1
        with self.assertRaisesRegex(TRANSPORT.ReadFailure, "time-budget-exhausted"):
            self.reader.read("pull", 7)
        self.assertEqual(1, self.reader.opener.open.call_count)
        self.reader.expires = time.monotonic() + 90
        self.reader.max_bytes = 4
        with self.assertRaisesRegex(TRANSPORT.ReadFailure, "response-byte-limit"):
            self.reader.read("pull", 7)

    def test_invalid_constructor_limits_and_missing_token_fail_before_io(self):
        for key in ("max_seconds", "max_requests", "max_bytes"):
            for value in (True, 0, -1, 2 ** 63, "1"):
                with self.assertRaisesRegex(TRANSPORT.ReadFailure, "invalid-budget"):
                    TRANSPORT.GitHubReader(**{key: value})
        with mock.patch.dict(TRANSPORT.os.environ, {"GH_TOKEN": " "}):
            with self.assertRaisesRegex(TRANSPORT.ReadFailure, "token-missing"):
                self.reader.read("pull", 7)
        self.reader.opener.open.assert_not_called()

    def test_response_identity_http_status_and_invalid_json_reject(self):
        for raw in (b'[]', b'{"number":8}', b'{"number":true}', b'{"number":7,"number":7}',
                    b'{"number":7,"x":NaN}', b'{"number":7,"x":1e999}', b"private-invalid-json"):
            self.response.__enter__.return_value.read.return_value = raw
            with self.assertRaises(TRANSPORT.ReadFailure):
                self.reader.read("pull", 7)
        self.response.__enter__.return_value.status = 201
        with self.assertRaisesRegex(TRANSPORT.ReadFailure, "unexpected-http-status"):
            self.reader.read("pull", 7)

    def test_incomplete_read_and_ordinary_transport_exceptions_are_sanitized(self):
        for error in (http.client.IncompleteRead(b"private-partial-response"),
                      http.client.RemoteDisconnected("private-response"),
                      urllib.error.URLError("private-host"), OSError("private-detail"),
                      ValueError("private-detail")):
            self.response.__enter__.return_value.read.side_effect = error
            with self.assertRaisesRegex(TRANSPORT.ReadFailure, "^read-failed$"):
                self.reader.read("pull", 7)
        self.assertEqual(5, self.reader.opener.open.call_count)  # no retry

    def test_cli_truncated_response_is_structured_and_never_leaks_input(self):
        self.response.__enter__.return_value.read.side_effect = http.client.IncompleteRead(b"private-partial")
        with mock.patch("sys.argv", ["reader", "pull", "7"]), \
                mock.patch.object(TRANSPORT, "GitHubReader", return_value=self.reader), \
                mock.patch("sys.stdout", new_callable=io.StringIO) as output:
            self.assertEqual(1, TRANSPORT.main())
        result = json.loads(output.getvalue())
        self.assertEqual("li219-readonly-rejection/v1", result["schema"])
        self.assertEqual("read-failed", result["reason"])
        self.assertNotIn("private", output.getvalue())
        self.assertNotIn("Traceback", output.getvalue())

    def test_cli_success_is_advisory_and_constructor_failure_is_structured(self):
        with mock.patch("sys.argv", ["reader", "pull", "7"]), \
                mock.patch.object(TRANSPORT, "GitHubReader", return_value=self.reader), \
                mock.patch("sys.stdout", new_callable=io.StringIO) as output:
            self.assertEqual(0, TRANSPORT.main())
        result = json.loads(output.getvalue())
        self.assertEqual("none", result["authority"])
        self.assertEqual(0, result["writes"])
        self.assertEqual(1, result["api_requests"])
        self.assertNotIn("unit-test-placeholder", output.getvalue())
        with mock.patch("sys.argv", ["reader", "pull", "7"]), \
                mock.patch.object(TRANSPORT, "GitHubReader", side_effect=RuntimeError("private")), \
                mock.patch("sys.stdout", new_callable=io.StringIO) as output:
            self.assertEqual(1, TRANSPORT.main())
        self.assertEqual("read-failed", json.loads(output.getvalue())["reason"])

    def test_continuously_progressing_response_is_actively_interrupted(self):
        self.reader.expires = time.monotonic() + 1
        chunks, completed = [], []
        def dribble(size):
            end = time.monotonic() + 3
            while time.monotonic() < end:
                chunks.append(b" ")
                time.sleep(.01)
            completed.append(True)
            return b'{"number":7}'
        self.response.__enter__.return_value.read.side_effect = dribble
        previous = signal.getsignal(signal.SIGALRM)
        with self.assertRaisesRegex(TRANSPORT.ReadFailure, "time-budget-exhausted"):
            self.reader.read("pull", 7)
        self.assertTrue(chunks)
        self.assertEqual([], completed)
        self.assertEqual((0.0, 0.0), signal.getitimer(signal.ITIMER_REAL))
        self.assertEqual(previous, signal.getsignal(signal.SIGALRM))

    def test_deadline_interrupts_connect_and_parse_and_restores_handler(self):
        for phase in ("connect", "parse"):
            self.reader.expires = time.monotonic() + 1
            def delayed(*args, **kwargs):
                time.sleep(3)
                self.fail("deadline failed to interrupt " + phase)
            previous = signal.getsignal(signal.SIGALRM)
            target = self.reader.opener if phase == "connect" else TRANSPORT.json
            attribute = "open" if phase == "connect" else "loads"
            with mock.patch.object(target, attribute, side_effect=delayed):
                with self.assertRaisesRegex(TRANSPORT.ReadFailure, "time-budget-exhausted"):
                    self.reader.read("pull", 7)
            self.assertEqual((0.0, 0.0), signal.getitimer(signal.ITIMER_REAL))
            self.assertEqual(previous, signal.getsignal(signal.SIGALRM))

    def test_late_parsed_response_cannot_pass_even_with_no_timer_delivery(self):
        self.reader.expires = 90
        clock = [0]
        def late_json(*args, **kwargs):
            clock[0] = 90
            return {"number": 7}
        with mock.patch.object(TRANSPORT.time, "monotonic", side_effect=lambda: clock[0]), \
                mock.patch.object(TRANSPORT.json, "loads", side_effect=late_json):
            with self.assertRaisesRegex(TRANSPORT.ReadFailure, "time-budget-exhausted"):
                self.reader.read("pull", 7)

    def test_unsupported_runtime_competing_timer_and_worker_thread_fail_closed(self):
        with mock.patch.object(TRANSPORT, "signal", object()):
            with self.assertRaisesRegex(TRANSPORT.ReadFailure, "deadline-unavailable"):
                self.reader.read("pull", 7)
        with mock.patch.object(signal, "getitimer", return_value=(1.0, 0.0)):
            with self.assertRaisesRegex(TRANSPORT.ReadFailure, "deadline-in-use"):
                self.reader.read("pull", 7)
        with ThreadPoolExecutor(max_workers=1) as pool:
            with self.assertRaisesRegex(TRANSPORT.ReadFailure, "deadline-unavailable"):
                pool.submit(self.reader.read, "pull", 7).result()
        self.reader.opener.open.assert_not_called()

    def test_control_signals_propagate_and_cleanup_runs(self):
        previous = signal.getsignal(signal.SIGALRM)
        self.response.__enter__.return_value.read.side_effect = KeyboardInterrupt
        with mock.patch("sys.argv", ["reader", "pull", "7"]), \
                mock.patch.object(TRANSPORT, "GitHubReader", return_value=self.reader):
            with self.assertRaises(KeyboardInterrupt):
                TRANSPORT.main()
        self.assertEqual((0.0, 0.0), signal.getitimer(signal.ITIMER_REAL))
        self.assertEqual(previous, signal.getsignal(signal.SIGALRM))


if __name__ == "__main__":
    unittest.main()
