"""Permanent CAS survives run/artifact expiry and ambiguous responses."""
import copy
from datetime import timedelta
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch
from test_release_archive import MODULE as STORAGE, FakeStore, PACKAGE, NOW

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import release_archive_reservation as reservation
from workflow_control import ControlError, digest

REPO = "lightning-it/archive-fixture"
SUBJECT = {"version": 1, "repository_id": 21, "promotion": 22, "head_sha": "a" * 40, "target": "main"}
AUTHORITY = {"run": 23, "attempt": 1, "management_sha": "b" * 40, "workflow_blob": "c" * 40, "helper_sha": "d" * 40}


class FakeGit:
    def __init__(self):
        self.rule = reservation.rule_payload() | {"id": 25, "source_type": "Repository", "source": REPO}
        self.tags, self.refs, self.calls = {}, {}, []
        self.unknown = False

    def request(self, method, path, data=None):
        self.calls.append((method, path, copy.deepcopy(data)))
        base = "repos/" + REPO
        if method in {"PATCH", "DELETE"} and "/git/refs/tags/release-archive/v1/" in path:
            return 422, {"message": "Repository rule violations found for ref"}
        if path == base:
            return 200, {"full_name": REPO, "private": True, "archived": False}
        if path == base + "/rulesets/25":
            return 200, copy.deepcopy(self.rule)
        if method == "GET" and "/git/ref/" in path:
            name = "refs/" + path.split("/git/ref/", 1)[1]
            return (200, self.refs[name]) if name in self.refs else (404, {})
        if method == "GET" and "/git/tags/" in path:
            return 200, self.tags[path.rsplit("/", 1)[-1]]
        if method == "POST" and path.endswith("/git/tags"):
            identifier = digest(data)[:40]
            self.tags[identifier] = {"sha": identifier, "tag": data["tag"], "message": data["message"],
                                     "object": {"sha": data["object"], "type": data["type"]}}
            return 201, self.tags[identifier]
        if method == "POST" and path.endswith("/git/refs"):
            if data["ref"] in self.refs:
                return 422, {}
            self.refs[data["ref"]] = {"ref": data["ref"], "object": {"sha": data["sha"], "type": "tag"}}
            if self.unknown:
                raise ControlError("archive-native-outcome-unknown")
            return 201, self.refs[data["ref"]]
        raise AssertionError((method, path))


class ReservationTests(unittest.TestCase):
    def setUp(self):
        self.api = FakeGit()
        self.store = reservation.Reservations(self.api, REPO, 25)

    def claim(self, **changes):
        args = {"subject": SUBJECT, "package_sha256": "e" * 64, "package_bytes": 123, "authority": AUTHORITY}
        args.update(changes)
        return self.store.claim(**args)

    def test_integer_version_one_preserves_operation_and_single_claim(self):
        subject = SUBJECT | {"version": 1}
        self.assertEqual(digest(SUBJECT), reservation.operation(subject))
        record, mode = self.claim(subject=subject)
        self.assertEqual("create", mode)
        self.assertEqual(digest(SUBJECT), record["operation"])
        self.assertEqual((record, "verify-existing"), self.claim(subject=subject))
        self.assertEqual(1, len(self.api.refs))

    def test_malformed_versions_never_hash_or_create_a_claim(self):
        for version in (True, False, 1.0, 0.0, "1", None, 0, 2):
            subject = SUBJECT | {"version": version}
            with self.subTest(version=version, value_type=type(version).__name__):
                with patch.object(reservation, "digest") as operation_digest:
                    with self.assertRaisesRegex(ControlError, "archive-operation-subject"):
                        reservation.operation(subject)
                    operation_digest.assert_not_called()
                with self.assertRaisesRegex(ControlError, "archive-operation-subject"):
                    self.claim(subject=subject)
                self.assertEqual({}, self.api.tags)
                self.assertEqual({}, self.api.refs)
                self.assertFalse(any(method != "GET" for method, _, _ in self.api.calls))

    def test_malformed_versions_stop_delivery_before_build_or_claim(self):
        for version in (True, 1.0):
            cloud = FakeStore()
            build, validate = Mock(return_value=PACKAGE), Mock()
            with self.subTest(version=version, value_type=type(version).__name__), \
                 self.assertRaisesRegex(ControlError, "archive-operation-subject"):
                reservation.deliver(self.store, STORAGE, cloud, SUBJECT | {"version": version},
                                    AUTHORITY, build, validate, NOW)
            build.assert_not_called()
            validate.assert_not_called()
            self.assertEqual({}, self.api.tags)
            self.assertEqual({}, self.api.refs)
            self.assertEqual([], cloud.calls)

    def test_expired_actions_artifacts_do_not_rebuild_or_upload_on_replay(self):
        cloud = FakeStore()
        build, validate = Mock(return_value=PACKAGE), Mock()
        first = reservation.deliver(self.store, STORAGE, cloud, SUBJECT, AUTHORITY, build, validate, NOW)
        build.side_effect = AssertionError("expired Actions input must not be fetched")
        second = reservation.deliver(self.store, STORAGE, cloud, SUBJECT, AUTHORITY | {"run": 99}, build, validate, NOW)
        self.assertEqual("create", first[2])
        self.assertEqual("verify-existing", second[2])
        self.assertEqual(first[:2], second[:2])
        self.assertEqual(1, build.call_count)
        self.assertEqual(1, sum(call[1] == "PUT" for call in cloud.calls))

    def test_ambiguous_put_stays_consumed_and_recovers_without_second_put(self):
        cloud = FakeStore()
        request = cloud.request
        def ambiguous(role, method, key, **kwargs):
            response = request(role, method, key, **kwargs)
            if method == "PUT":
                raise STORAGE.ArchiveError("provider-transport-failure")
            return response
        cloud.request = ambiguous
        build = Mock(return_value=PACKAGE)
        with self.assertRaisesRegex(STORAGE.ArchiveError, "provider-transport-failure"):
            reservation.deliver(self.store, STORAGE, cloud, SUBJECT, AUTHORITY, build, Mock(), NOW)
        build.side_effect = AssertionError("no rebuild")
        result = reservation.deliver(self.store, STORAGE, cloud, SUBJECT, AUTHORITY, build, Mock(), NOW)
        self.assertEqual("verify-existing", result[2])
        self.assertEqual(1, sum(call[1] == "PUT" for call in cloud.calls))

    def test_retention_extension_replays_original_receipt_without_any_write(self):
        cloud = FakeStore()
        build = Mock(return_value=PACKAGE)
        first = reservation.deliver(self.store, STORAGE, cloud, SUBJECT, AUTHORITY, build, Mock(), NOW)
        original_refs, original_tags = copy.deepcopy(self.api.refs), copy.deepcopy(self.api.tags)
        cloud.until += timedelta(days=365)
        cloud.calls.clear()
        self.api.calls.clear()
        build.side_effect = AssertionError("replay must not rebuild")
        second = reservation.deliver(self.store, STORAGE, cloud, SUBJECT, AUTHORITY, build, Mock(), NOW)
        self.assertEqual("verify-existing", second[2])
        self.assertEqual(first[:2], second[:2])
        self.assertEqual(original_refs, self.api.refs)
        self.assertEqual(original_tags, self.api.tags)
        self.assertTrue(all(method == "GET" for method, _, _ in self.api.calls))
        self.assertTrue(all(call[1] in {"GET", "HEAD"} for call in cloud.calls))
        self.assertTrue(all(call[3]["query"]["versionId"] == cloud.version for call in cloud.calls))

    def test_retention_decrease_conflicts_even_above_seven_year_minimum(self):
        cloud = FakeStore()
        reservation.deliver(self.store, STORAGE, cloud, SUBJECT, AUTHORITY, lambda: PACKAGE, Mock(), NOW)
        cloud.until -= timedelta(hours=1)
        cloud.calls.clear()
        with self.assertRaisesRegex(ControlError, "archive-receipt-conflict"):
            reservation.deliver(self.store, STORAGE, cloud, SUBJECT, AUTHORITY, Mock(), Mock(), NOW)
        self.assertTrue(all(call[1] in {"GET", "HEAD"} for call in cloud.calls))

    def test_extended_retention_never_relaxes_other_receipt_fields(self):
        cloud = FakeStore()
        _, first, _ = reservation.deliver(self.store, STORAGE, cloud, SUBJECT, AUTHORITY, lambda: PACKAGE, Mock(), NOW)
        record = self.store.read(first["operation"], "reservation")
        extended = first["storage"] | {"retain_until": (cloud.until + timedelta(days=365)).isoformat()}
        for field, value in (("version_id", "replacement"), ("package_sha256", "f" * 64),
                             ("key", "different-key"), ("repository", "lightning-it/other"),
                             ("promotion", 99), ("head_sha", "f" * 40),
                             ("retention_mode", "GOVERNANCE"), ("release_authorized", True)):
            with self.subTest(field=field), self.assertRaises(ControlError):
                self.store.finish(record, extended | {field: value})
        self.assertEqual(first, self.store.read(first["operation"], "receipt"))

    def test_changed_retention_must_be_a_timezone_aware_timestamp(self):
        cloud = FakeStore()
        _, first, _ = reservation.deliver(self.store, STORAGE, cloud, SUBJECT, AUTHORITY, lambda: PACKAGE, Mock(), NOW)
        record = self.store.read(first["operation"], "reservation")
        for value in (None, 1, "invalid", "2039-01-01", "2039-01-01T00:00:00"):
            with self.subTest(value=value), self.assertRaisesRegex(ControlError, "archive-receipt-conflict"):
                self.store.finish(record, first["storage"] | {"retain_until": value})

    def test_invalid_package_stops_before_claim_and_before_s3(self):
        cloud = FakeStore()
        validate = Mock(side_effect=ControlError("incomplete-profile"))
        with self.assertRaisesRegex(ControlError, "incomplete-profile"):
            reservation.deliver(self.store, STORAGE, cloud, SUBJECT, AUTHORITY, lambda: PACKAGE, validate, NOW)
        self.assertEqual({}, self.api.refs)
        self.assertEqual([], cloud.calls)

    def test_native_negative_checks_precede_put_and_permission_errors_do_not_pass(self):
        cloud = FakeStore()
        request = self.api.request
        def permission_error(method, path, data=None):
            if method == "PATCH":
                return 403, {"message": "Forbidden"}
            return request(method, path, data)
        self.api.request = permission_error
        with self.assertRaisesRegex(ControlError, "archive-native-ref-denial-unproven"):
            reservation.deliver(self.store, STORAGE, cloud, SUBJECT, AUTHORITY, lambda: PACKAGE, Mock(), NOW)
        self.assertEqual([], cloud.calls)
        self.assertTrue(self.api.refs)

    def test_selectors_cover_only_the_two_approved_ref_suffixes(self):
        # GitHub File.fnmatch FNM_PATHNAME does not let * span a slash.
        import re
        patterns = [re.compile("^" + re.escape(value).replace(r"\*", "[^/]*") + "$")
                    for value in reservation.rule_payload()["conditions"]["ref_name"]["include"]]
        prefix = "refs/tags/" + reservation.PREFIX + "a" * 64
        for suffix in ("/reservation", "/receipt"):
            self.assertTrue(any(pattern.fullmatch(prefix + suffix) for pattern in patterns))
        for name in (prefix, prefix + "/extra/reservation", prefix + "/other", "refs/tags/v1.2.3"):
            self.assertFalse(any(pattern.fullmatch(name) for pattern in patterns))

    def test_only_confirmed_first_ref_create_grants_one_upload(self):
        first, mode = self.claim()
        self.assertEqual("create", mode)
        second, mode = self.claim(authority=AUTHORITY | {"run": 99, "attempt": 2})
        self.assertEqual("verify-existing", mode)
        self.assertEqual(first, second)
        self.assertEqual(1, sum(method == "POST" and path.endswith("/git/refs") for method, path, _ in self.api.calls))
        self.assertTrue(all("/actions/" not in path for _, path, _ in self.api.calls))

    def test_unknown_claim_response_never_grants_create_on_reentry(self):
        self.api.unknown = True
        with self.assertRaisesRegex(ControlError, "outcome-unknown"):
            self.claim()
        self.api.unknown = False
        _, mode = self.claim()
        self.assertEqual("verify-existing", mode)

    def test_package_change_cannot_obtain_a_different_operation_key(self):
        self.claim()
        for change in ({"package_sha256": "f" * 64}, {"package_bytes": 124}):
            with self.subTest(change=change), self.assertRaisesRegex(ControlError, "reservation-conflict"):
                self.claim(**change)
        self.assertEqual(1, len(self.api.refs))

    def test_immutable_policy_must_match_before_any_mutation(self):
        original = copy.deepcopy(self.api.rule)
        for changes in ({"enforcement": "evaluate"}, {"bypass_actors": [{"actor_type": "Team", "actor_id": 1}]},
                        {"rules": [{"type": "deletion"}]}, {"conditions": {"ref_name": {"include": ["refs/tags/**"], "exclude": []}}}):
            self.api.rule = original | changes
            with self.assertRaisesRegex(ControlError, "reservation-protection"):
                self.claim()
        self.assertFalse(any(method == "POST" for method, _, _ in self.api.calls))

    def test_changed_policy_after_claim_consumes_without_granting_upload(self):
        original = self.api.request
        def change_after_create(method, path, data=None):
            result = original(method, path, data)
            if method == "POST" and path.endswith("/git/refs"):
                self.api.rule["enforcement"] = "disabled"
            return result
        self.api.request = change_after_create
        with self.assertRaisesRegex(ControlError, "reservation-protection"):
            self.claim()
        self.assertEqual(1, len(self.api.refs))

    def test_receipt_is_append_only_and_version_pinned(self):
        record, _ = self.claim()
        storage = {"reservation": record["reservation"], "package_sha256": record["package_sha256"],
                   "retention_mode": "COMPLIANCE", "version_id": "original"}
        first = self.store.finish(record, storage)
        self.assertEqual(first, self.store.finish(record, storage))
        with self.assertRaisesRegex(ControlError, "receipt-conflict"):
            self.store.finish(record, storage | {"version_id": "new-version"})
        self.assertEqual(2, len(self.api.refs))

    def test_ambiguous_receipt_creation_is_reconciled_without_new_storage_write(self):
        record, _ = self.claim()
        storage = {"reservation": record["reservation"], "package_sha256": record["package_sha256"],
                   "retention_mode": "COMPLIANCE", "version_id": "original"}
        self.api.unknown = True
        with self.assertRaisesRegex(ControlError, "outcome-unknown"):
            self.store.finish(record, storage)
        self.api.unknown = False
        result = self.store.finish(record, storage)
        self.assertEqual("original", result["storage"]["version_id"])
        self.assertEqual(2, len(self.api.refs))

    def test_noncanonical_or_redirected_record_is_blocking(self):
        record, _ = self.claim()
        key = record["operation"]
        name = "refs/tags/" + reservation.PREFIX + key + "/reservation"
        tag = self.api.tags[self.api.refs[name]["object"]["sha"]]
        tag["message"] += " "
        with self.assertRaisesRegex(ControlError, "reservation-record"):
            self.claim()


if __name__ == "__main__":
    unittest.main()
