"""Storage-boundary regressions; no credentials or network required."""
import base64
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
import hashlib
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock
import urllib.error

SPEC = importlib.util.spec_from_file_location("release_archive", Path(__file__).resolve().parents[1] / "scripts/lit-release-archive.py")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)
NOW = datetime(2026, 10, 14, 12, 0, 0, tzinfo=timezone.utc)
PACKAGE = b'{"qualification_only":true}\n'
DIGEST = hashlib.sha256(PACKAGE).hexdigest()
HEAD = "a" * 40
UNTIL = MODULE.seven_years_after(NOW) + timedelta(days=1)


class FakeStore:
    encryption = {"x-amz-server-side-encryption-customer-key": "test-only"}

    def __init__(self, *, duplicate=False, body=PACKAGE, mode="COMPLIANCE", until=UNTIL):
        self.duplicate, self.body, self.mode, self.until = duplicate, body, mode, until
        self.calls = []
        self.version = "immutable-version"

    def request(self, role, method, key, **kwargs):
        self.calls.append((role, method, key, kwargs))
        if method == "PUT":
            return {"x-amz-version-id": self.version}, b""
        if method == "HEAD":
            return {"x-amz-version-id": self.version, "last-modified": format_datetime(NOW)}, b""
        if "retention" in kwargs.get("query", {}):
            return {}, f'<Retention><Mode>{self.mode}</Mode><RetainUntilDate>{self.until.isoformat()}</RetainUntilDate></Retention>'.encode()
        return {}, self.body


class ReleaseArchiveTests(unittest.TestCase):
    def archive(self, store=None, **changes):
        args = dict(repository="lightning-it/.github", promotion=123, head=HEAD, expected_digest=DIGEST, reservation="b" * 32, operation="create", now=NOW)
        args.update(changes)
        return MODULE.archive(store or FakeStore(), PACKAGE, **args)

    def test_exact_version_digest_and_compliance_are_independently_verified(self):
        store = FakeStore()
        receipt = self.archive(store)
        self.assertFalse(receipt["release_authorized"])
        self.assertEqual("immutable-version", receipt["version_id"])
        self.assertEqual([("writer", "PUT"), ("reader", "GET"), ("reviewer", "GET")], [(a, b) for a, b, _, _ in store.calls])
        put = store.calls[0][3]
        self.assertNotIn("if-none-match", put["headers"])
        self.assertEqual("COMPLIANCE", put["headers"]["x-amz-object-lock-mode"])
        self.assertEqual(PACKAGE, put["body"])
        self.assertTrue(all(item[3]["query"]["versionId"] == "immutable-version" for item in store.calls[1:]))

    def test_duplicate_reuses_only_matching_still_locked_original_version(self):
        store = FakeStore(duplicate=True)
        result = self.archive(store, operation="verify-existing", now=NOW + timedelta(hours=1))
        self.assertEqual("immutable-version", result["version_id"])
        self.assertEqual(["HEAD", "GET", "GET"], [item[1] for item in store.calls])
        self.assertEqual(0, sum(item[1] == "PUT" for item in store.calls))

    def test_unavailable_head_is_blocking_without_any_upload_retry(self):
        store = FakeStore()
        store.request = Mock(side_effect=MODULE.ArchiveError("provider-http-403"))
        with self.assertRaisesRegex(MODULE.ArchiveError, "provider-http-403"):
            self.archive(store, operation="verify-existing")
        self.assertEqual(1, store.request.call_count)
        self.assertEqual(("reader", "HEAD"), store.request.call_args.args[:2])

    def test_missing_reservation_or_unknown_operation_stops_before_any_cloud_call(self):
        for changes in ({"reservation": ""}, {"reservation": "../../escape"}, {"operation": "retry-create"}):
            store = FakeStore()
            with self.subTest(changes=changes), self.assertRaises(MODULE.ArchiveError):
                self.archive(store, **changes)
            self.assertEqual([], store.calls)

    def test_digest_mismatch_stops_before_cloud_write(self):
        store = FakeStore()
        with self.assertRaisesRegex(MODULE.ArchiveError, "package-digest-mismatch"):
            self.archive(store, expected_digest="0" * 64)
        self.assertEqual([], store.calls)

    def test_readback_cannot_substitute_other_package(self):
        for duplicate in (False, True):
            with self.subTest(duplicate=duplicate), self.assertRaisesRegex(MODULE.ArchiveError, "archived-digest-mismatch"):
                self.archive(FakeStore(duplicate=duplicate, body=b"different"), operation="verify-existing" if duplicate else "create")

    def test_governance_short_or_expired_retention_cannot_pass(self):
        for changes in ({"mode": "GOVERNANCE"}, {"until": UNTIL - timedelta(seconds=1)}, {"until": NOW}):
            with self.subTest(changes=changes), self.assertRaises(MODULE.ArchiveError):
                self.archive(FakeStore(**changes))

    def test_null_missing_and_overlong_version_cannot_pass(self):
        for version in (None, "", "null", "x" * 1025):
            store = FakeStore(); store.version = version
            with self.subTest(version=version), self.assertRaisesRegex(MODULE.ArchiveError, "object-version-missing"):
                self.archive(store)

    def test_leap_day_retention_rounds_forward(self):
        self.assertEqual(datetime(2031, 3, 1, tzinfo=timezone.utc), MODULE.seven_years_after(datetime(2024, 2, 29, tzinfo=timezone.utc)))

    def test_unknown_region_or_same_role_identity_is_rejected(self):
        identities = {role: MODULE.Identity(role, "test-only") for role in ("writer", "reader", "reviewer")}
        key = base64.b64encode(b"x" * 32).decode()
        with self.assertRaisesRegex(MODULE.ArchiveError, "endpoint-not-approved"):
            MODULE.Store("attacker.example", "fixture-bucket", identities, key)
        identities["reader"] = identities["writer"]
        with self.assertRaisesRegex(MODULE.ArchiveError, "roles-not-separated"):
            MODULE.Store("fsn1.your-objectstorage.com", "fixture-bucket", identities, key)

    def test_signed_transport_uses_tls_and_never_places_credentials_in_url(self):
        identities = {role: MODULE.Identity(role + "-id", role + "-secret") for role in ("writer", "reader", "reviewer")}
        store = MODULE.Store("fsn1.your-objectstorage.com", "fixture-bucket", identities, base64.b64encode(b"x" * 32).decode())
        response = Mock(); response.headers = {"x-amz-version-id": "v1"}; response.read.return_value = b""
        store.opener = Mock(); store.opener.open.return_value.__enter__ = Mock(return_value=response)
        store.opener.open.return_value.__exit__ = Mock(return_value=False)
        store.request("writer", "PUT", "runs/a file", body=b"fixture")
        request = store.opener.open.call_args.args[0]
        self.assertEqual("https://fixture-bucket.fsn1.your-objectstorage.com/runs/a%20file", request.full_url)
        self.assertNotIn("secret", request.full_url)
        self.assertIn("Credential=writer-id/", request.get_header("Authorization"))
        self.assertEqual(45, store.opener.open.call_args.kwargs["timeout"])

    def test_provider_errors_are_safe_and_not_retried(self):
        identities = {role: MODULE.Identity(role, "sensitive-secret") for role in ("writer", "reader", "reviewer")}
        store = MODULE.Store("fsn1.your-objectstorage.com", "fixture-bucket", identities, base64.b64encode(b"x" * 32).decode())
        store.opener = Mock()
        store.opener.open.side_effect = urllib.error.HTTPError("https://private-resource", 403, "sensitive-provider-body", {}, None)
        with self.assertRaisesRegex(MODULE.ArchiveError, "^provider-http-403$"):
            store.request("writer", "PUT", "runs/x", body=b"fixture")
        self.assertEqual(1, store.opener.open.call_count)

    def test_redirect_and_ambiguous_retention_are_rejected(self):
        with self.assertRaisesRegex(MODULE.ArchiveError, "redirect-prohibited"):
            MODULE.NoRedirect().redirect_request(None, None, 307, "", {}, "https://attacker.example")
        with self.assertRaisesRegex(MODULE.ArchiveError, "ambiguous-retention"):
            MODULE.retention_date(b"<Retention><Mode>COMPLIANCE</Mode><Mode>GOVERNANCE</Mode></Retention>")
