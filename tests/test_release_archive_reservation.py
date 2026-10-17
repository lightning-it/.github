"""Permanent CAS survives run/artifact expiry and ambiguous responses."""
import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock
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
