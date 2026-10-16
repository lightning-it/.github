"""Actual HTTPResponse short-read behavior; no socket or provider calls."""
import http.client
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import bounded_review_transport as transport
from bounded_review import ReviewError


class TransportFramingTests(unittest.TestCase):
    def response(self, body, framing):
        wire = b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n' + framing + b'\r\n' + body
        class Socket:
            def makefile(self, *_args):
                return io.BytesIO(wire)
        response = http.client.HTTPResponse(Socket())
        response.begin()
        return response

    def fetch(self, response):
        class Connection:
            def __init__(self, *_args, **_kwargs):
                pass
            def request(self, *_args):
                pass
            def getresponse(self):
                return response
            def close(self):
                response.close()
        with patch.object(transport.http.client, 'HTTPSConnection', Connection):
            return transport.fetch_once({'input': 'bound'}, 'fixture', 1, counting=True, response_byte_limit=4096)

    def test_valid_count_or_result_json_with_short_fixed_body_is_rejected(self):
        for body in (b'{"object":"response.input_tokens","input_tokens":10}', b'{"status":"completed","output":[]}'):
            with self.subTest(body=body), self.assertRaisesRegex(ReviewError, 'transport-incomplete-response'):
                self.fetch(self.response(body, b'Content-Length: ' + str(len(body) + 20).encode() + b'\r\n'))

    def test_complete_fixed_and_chunked_json_preserve_exact_bytes(self):
        body = b'{"object":"response.input_tokens","input_tokens":10}'
        self.assertEqual(body, self.fetch(self.response(body, b'Content-Length: ' + str(len(body)).encode() + b'\r\n')))
        chunks = hex(len(body))[2:].encode() + b'\r\n' + body + b'\r\n0\r\n\r\n'
        self.assertEqual(body, self.fetch(self.response(chunks, b'Transfer-Encoding: chunked\r\n')))

    def test_only_explicit_transient_service_status_has_recoverable_category(self):
        for status in (429, 500, 502, 503, 504, 400, 401, 403):
            response = self.response(b'{}', b'Content-Length: 2\r\n')
            response.status = status
            expected = 'transport-service-unavailable' if status in (429, 500, 502, 503, 504) else 'transport-upstream-status'
            with self.subTest(status=status), self.assertRaisesRegex(ReviewError, expected): self.fetch(response)

    def test_worker_preserves_only_the_sanitized_service_category(self):
        from unittest.mock import Mock
        payload = transport.canonical({'request': {'input': 'bound'}, 'credential': 'fixture', 'timeout_ms': 1, 'counting': True})
        for reason, expected in (('transport-service-unavailable', 75), ('transport-upstream-status', 1)):
            with patch.object(transport.sys, 'stdin', Mock(buffer=io.BytesIO(payload))), \
                    patch.object(transport, 'fetch_once', side_effect=ReviewError(reason)):
                self.assertEqual(transport.worker(), expected)

    def test_malformed_duplicate_or_conflicting_framing_never_reaches_json_decode(self):
        for headers in (b'Content-Length: unknown\r\n', b'Content-Length: 2\r\nContent-Length: 2\r\n',
                        b'Content-Length: 2\r\nTransfer-Encoding: chunked\r\n'):
            with self.subTest(headers=headers), self.assertRaises(ReviewError):
                self.fetch(self.response(b'{}', headers))


if __name__ == '__main__':
    unittest.main()
