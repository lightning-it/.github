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
        if "retention" in (kwargs.get("query") or {}):
            return {}, f'<Retention><Mode>{self.mode}</Mode><RetainUntilDate>{self.until.isoformat()}</RetainUntilDate></Retention>'.encode()
        return {"x-amz-version-id": self.version}, self.body


class ReleaseArchiveTests(unittest.TestCase):
    def restore(self, store, **changes):
        args = dict(repository="lightning-it/.github", promotion=123, head=HEAD,
                    expected_digest=DIGEST, reservation="b" * 32, expected_bytes=len(PACKAGE),
                    now=NOW, expected_version="immutable-version")
        args.update(changes)
        return MODULE.restore(store, **args)

    def test_restore_after_artifact_expiry_uses_only_original_object_reads(self):
        store = FakeStore()
        package, receipt = self.restore(store)
        self.assertEqual(PACKAGE, package)
        self.assertEqual(store.version, receipt["version_id"])
        self.assertTrue(all(call[1] in {"GET", "HEAD"} for call in store.calls))
        self.assertTrue(all(call[3]["query"]["versionId"] == store.version for call in store.calls))

    def test_consumed_claim_without_receipt_can_only_recover_matching_bytes(self):
        store = FakeStore()
        package, _receipt = self.restore(store, expected_version=None)
        self.assertEqual(PACKAGE, package)
        self.assertTrue(all(call[1] != "PUT" for call in store.calls))
        with self.assertRaisesRegex(MODULE.ArchiveError, "archived-digest-mismatch"):
            self.restore(FakeStore(body=b"substituted"), expected_version=None)

    def test_restore_mismatch_or_404_never_recreates_package(self):
        store = FakeStore()
        with self.assertRaisesRegex(MODULE.ArchiveError, "object-version-drift"):
            self.restore(store, expected_version="wrong")
        self.assertEqual(1, len(store.calls))
        store.request = Mock(side_effect=MODULE.ArchiveError("provider-http-404"))
        with self.assertRaisesRegex(MODULE.ArchiveError, "provider-http-404"):
            self.restore(store)
        self.assertEqual(1, store.request.call_count)

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

    def test_persistent_receipt_pins_every_read_to_original_version(self):
        store = FakeStore()
        self.archive(store, operation="verify-existing", expected_version=store.version)
        self.assertTrue(all(call[3]["query"]["versionId"] == store.version for call in store.calls))
        self.assertFalse(any(call[1] == "PUT" for call in store.calls))

    def test_changed_latest_version_cannot_replace_persisted_version(self):
        store = FakeStore()
        with self.assertRaisesRegex(MODULE.ArchiveError, "object-version-drift"):
            self.archive(store, operation="verify-existing", expected_version="original-version")
        self.assertEqual(["HEAD"], [call[1] for call in store.calls])

    def test_version_pin_cannot_enable_create_or_null_version(self):
        for changes in ({"expected_version": "original"}, {"operation": "verify-existing", "expected_version": "null"}):
            store = FakeStore()
            with self.assertRaisesRegex(MODULE.ArchiveError, "expected-version-shape"):
                self.archive(store, **changes)
            self.assertEqual([], store.calls)

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
