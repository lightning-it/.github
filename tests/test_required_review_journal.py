"""Offline CAS/outbox fault injection; never production Acceptance evidence."""

import base64
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "required_review_journal", ROOT / "scripts/required-review-journal.py")
J = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(J)
STEP = "Verify current Copilot review and resolved findings"
CONFIG = {"store_repository": "lightning-it/test-journal", "store_repository_id": 800,
          "app_id": 900, "generation": "f" * 64}


class NativeGitHub:
    """Model GitHub's atomic expectedHeadOid boundary and ambiguous responses."""

    def __init__(self):
        self.oid = "1" * 40
        self.document = J.empty(CONFIG)
        self.calls = []
        self.sequence = 1
        self.before_commit = None
        self.after_commit = None
        self.after_read = None
        self.response_mutation = None
        self.lose_reply = False
        self.fail_commit = False

    def call(self, query, variables):
        self.calls.append((query, deepcopy(variables)))
        if query == J.READ:
            assert variables == {"owner": "lightning-it", "name": "test-journal", "ref": J.REF}
            raw = J.encoded(self.document)
            blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
            response = {"data": {"repository": {
                "databaseId": 800, "nameWithOwner": "lightning-it/test-journal", "isPrivate": True,
                "ref": {"name": "li219-reservations", "target": {
                    "__typename": "Commit", "oid": self.oid, "tree": {"entries": [{
                        "name": J.FILE, "mode": 33188, "type": "blob", "object": {
                            "oid": blob, "byteSize": len(raw), "isTruncated": False,
                            "text": raw.decode(),
                        }}]}}}}}}
            if self.response_mutation:
                self.response_mutation(response)
            if self.after_read:
                callback, self.after_read = self.after_read, None
                callback()
            return response
        assert query == J.COMMIT
        request = variables["input"]
        assert request["branch"] == {"repositoryNameWithOwner": "lightning-it/test-journal",
                                    "branchName": "li219-reservations"}
        assert set(request["fileChanges"]) == {"additions"}
        assert len(request["fileChanges"]["additions"]) == 1
        assert request["fileChanges"]["additions"][0]["path"] == J.FILE
        if self.before_commit:
            callback, self.before_commit = self.before_commit, None
            callback()
        if self.fail_commit or request["expectedHeadOid"] != self.oid:
            return {"errors": [{"message": "CAS rejected"}]}
        self.document = json.loads(base64.b64decode(request["fileChanges"]["additions"][0]["contents"]))
        self.sequence += 1
        self.oid = f"{self.sequence:040x}"
        lose_reply, self.lose_reply = self.lose_reply, False
        if self.after_commit:
            callback, self.after_commit = self.after_commit, None
            callback()
        if lose_reply:
            raise TimeoutError("response unavailable")
        return {"data": {"createCommitOnBranch": {"commit": {"oid": self.oid},
                "ref": {"name": "li219-reservations", "target": {"oid": self.oid}}}}}


class Checks:
    def __init__(self, entry, proof):
        record = entry["record"]
        self.repo = record["binding"]["repository"]
        self.proof = deepcopy(proof)
        self.check = {"id": record["check_id"], "name": J.CONTEXT,
                      "head_sha": record["binding"]["head"], "app": {"id": entry["app_id"]},
                      "external_id": entry["external_id"], "status": "in_progress", "conclusion": None}
        self.writes = []
        self.reads = 0
        self.evidence_reads = 0
        self.lose_reply = False
        self.fail_write = False
        self.before_patch = None

    def read(self, repository, check_id):
        assert repository == self.repo and check_id == self.check["id"]
        self.reads += 1
        return deepcopy(self.check)

    def evidence(self, identity):
        self.evidence_reads += 1
        return deepcopy(self.proof)

    def patch(self, repository, check_id, payload):
        assert repository == self.repo and check_id == self.check["id"]
        self.writes.append((repository, check_id, deepcopy(payload)))
        if self.before_patch:
            callback, self.before_patch = self.before_patch, None
            callback()
        if self.fail_write:
            raise TimeoutError("outcome unavailable")
        self.check.update(deepcopy(payload))
        if self.lose_reply:
            self.lose_reply = False
            raise TimeoutError("response unavailable")


class RequiredReviewJournalTests(unittest.TestCase):
    def setUp(self):
        self.server = NativeGitHub()
        self.store = J.GitHubJournal(CONFIG, self.server.call)
        self.finalizer = J.Finalizer(self.store)
        self.identity = {"repository": "lightning-it/example", "repository_id": 100,
                         "pr": 7, "base": "a" * 40, "head": "b" * 40,
                         "controller": "c" * 40, "ruleset_digest": "d" * 64,
                         "actor_id": 101, "producer_run": 200, "producer_attempt": 1,
                         "admission_run": 201, "reviewer_id": 102, "metadata_digest": "e" * 64}
        self.proof = {"binding": deepcopy(self.identity), "pr_open": True, "draft": False,
                      "unresolved_threads": 0,
                      "job": {"id": 400, "run_id": 200, "run_attempt": 1,
                              "head_sha": "b" * 40, "status": "in_progress", "conclusion": None,
                              "steps": [{"name": name, "status": "completed", "conclusion": "success"}
                                        for name in (STEP, "Publish bound neutral result")]},
                      "review": {"id": 500, "reviewer_id": 102, "head": "b" * 40, "state": "COMMENTED"}}
        self.entry = self.finalizer.admit(self.identity, 300, 1000, 3600)
        self.key = self.entry["record"]["key"]
        self.checks = Checks(self.entry, self.proof)

    def finish(self, **overrides):
        values = {"identity": self.identity, "first_read": self.proof, "final_read": self.proof,
                  "policy_step": STEP, "now": 1180}
        values.update(overrides)
        return self.finalizer.finalize(**values)

    def writes(self):
        return [variables for query, variables in self.server.calls if query == J.COMMIT]

    def test_180_second_visibility_delay_and_delivery_without_polling(self):
        finished = self.finish()
        self.assertEqual(finished["record"]["state"], "success")
        self.assertEqual(self.proof["job"]["status"], "in_progress")
        self.finalizer.deliver(self.key, self.checks)
        self.assertEqual(len(self.checks.writes), 1)
        self.assertEqual(self.checks.evidence_reads, 2)
        self.assertEqual(self.checks.check["conclusion"], "success")
        self.assertTrue(self.server.document["records"][self.key]["delivered"])

    def test_restart_duplicate_delivery_and_terminal_visibility_are_idempotent(self):
        first = self.finish()
        self.finalizer.deliver(self.key, self.checks)
        restarted = J.Finalizer(J.GitHubJournal(CONFIG, self.server.call))
        terminal = deepcopy(self.proof)
        terminal["job"].update(status="completed", conclusion="success")
        restarted.finalize(self.identity, terminal, terminal, STEP, 5000)
        restarted.deliver(self.key, self.checks)
        self.assertEqual(len(self.checks.writes), 1)
        self.assertEqual(first["outbox"], self.server.document["records"][self.key]["outbox"])

    def test_lost_cas_reply_reconciles_without_second_commit(self):
        self.server.lose_reply = True
        before = len(self.writes())
        self.finish()
        self.assertEqual(len(self.writes()) - before, 1)

    def test_rejected_cas_does_not_dispatch_a_check(self):
        self.server.fail_commit = True
        with self.assertRaisesRegex(ValueError, "write-unconfirmed"):
            self.finish()
        self.assertEqual(self.server.document["records"][self.key]["record"]["state"], "pending")
        self.assertEqual(self.checks.writes, [])

    def test_successful_cas_survives_a_concurrent_unrelated_admission(self):
        newer = dict(self.identity, producer_run=210)
        self.server.after_commit = lambda: self.finalizer.admit(newer, 301, 1100, 3600)
        result = self.finish()
        self.assertEqual(result["record"]["state"], "success")
        self.assertEqual(len(self.server.document["records"]), 2)
        self.finalizer.deliver(self.key, self.checks)
        self.assertEqual(len(self.checks.writes), 1)

    def test_lost_commit_reply_survives_concurrent_delivery_receipt(self):
        self.server.lose_reply = True
        self.server.after_commit = lambda: self.finalizer.deliver(self.key, self.checks)
        result = self.finish()
        self.assertTrue(result["delivered"])
        self.assertEqual(len(self.checks.writes), 1)

    def test_successful_admission_can_read_back_its_later_terminal_state(self):
        newer = dict(self.identity, producer_run=210)
        key = J.STATE.operation_key(newer)
        self.server.after_commit = lambda: self.finalizer.expire(key, 301, 4700)
        result = self.finalizer.admit(newer, 301, 1100, 3600)
        self.assertEqual(result["record"]["state"], "failure")

    def test_successor_readback_cannot_erase_a_preexisting_terminal_outbox(self):
        self.finish()
        before = self.store.snapshot()["journal"]
        for mutation in (
            lambda d: d["records"].clear(),
            lambda d: d["records"].update({self.key: deepcopy(self.entry)}),
        ):
            candidate = deepcopy(before)
            mutation(candidate)
            with self.assertRaisesRegex(ValueError, "journal-write-unconfirmed"):
                J.preserves(before, candidate, CONFIG)

    def test_competing_finalizer_and_sweeper_only_one_decision_wins(self):
        self.server.before_commit = lambda: self.finalizer.expire(self.key, 300, 4600)
        with self.assertRaisesRegex(ValueError, "write-unconfirmed"):
            self.finish()
        self.finalizer.deliver(self.key, self.checks)
        self.assertEqual(self.checks.check["conclusion"], "failure")
        self.assertEqual(len(self.checks.writes), 1)
        self.assertEqual(self.checks.evidence_reads, 0)

    def test_duplicate_finalizers_do_not_rewrite_outbox(self):
        self.server.before_commit = lambda: self.finish(now=1181)
        with self.assertRaisesRegex(ValueError, "write-unconfirmed"):
            self.finish()
        winner = deepcopy(self.server.document["records"][self.key]["outbox"])
        self.finish(now=1200)
        self.assertEqual(winner, self.server.document["records"][self.key]["outbox"])

    def test_concurrent_deliveries_can_only_send_identical_terminal_payloads(self):
        self.finish()
        self.checks.before_patch = lambda: self.finalizer.deliver(self.key, self.checks)
        self.finalizer.deliver(self.key, self.checks)
        self.assertEqual(len(self.checks.writes), 2)
        self.assertEqual(self.checks.writes[0], self.checks.writes[1])
        self.assertTrue(self.server.document["records"][self.key]["delivered"])

    def test_lost_check_reply_is_reconciled_before_receipt(self):
        self.finish()
        self.checks.lose_reply = True
        self.finalizer.deliver(self.key, self.checks)
        self.assertEqual(len(self.checks.writes), 1)
        self.assertGreaterEqual(self.checks.reads, 2)

    def test_unmaterialized_write_stays_in_outbox_and_does_not_retry_in_process(self):
        self.finish()
        self.checks.fail_write = True
        with self.assertRaisesRegex(ValueError, "check-write-unconfirmed"):
            self.finalizer.deliver(self.key, self.checks)
        self.assertEqual(len(self.checks.writes), 1)
        self.assertFalse(self.server.document["records"][self.key]["delivered"])
        self.assertEqual(self.finalizer.sweep(5000)["undelivered"], [self.key])

    def test_conflicting_completed_check_is_never_overwritten(self):
        self.finish()
        self.checks.check.update(status="completed", conclusion="failure")
        with self.assertRaisesRegex(ValueError, "check-terminal-conflict"):
            self.finalizer.deliver(self.key, self.checks)
        self.assertEqual(self.checks.writes, [])

    def test_ownership_drift_cannot_write_any_check(self):
        self.finish()
        original = deepcopy(self.checks.check)
        for field, value in (("app", {"id": 900.0}), ("app", {"id": 901}),
                             ("head_sha", "c" * 40), ("name", "other"),
                             ("external_id", "foreign")):
            with self.subTest(field=field, value=value):
                self.checks.check = dict(original, **{field: value})
                with self.assertRaisesRegex(ValueError, "ownership-drift"):
                    self.finalizer.deliver(self.key, self.checks)
        self.assertEqual(self.checks.writes, [])

    def test_post_seal_head_base_controller_actor_attempt_and_review_drift_block(self):
        self.finish()
        for field in J.STATE.BINDING_FIELDS:
            with self.subTest(field=field):
                self.checks.proof = deepcopy(self.proof)
                prior = self.checks.proof["binding"][field]
                self.checks.proof["binding"][field] = prior + 1 if type(prior) is int else "0" + prior[1:]
                with self.assertRaisesRegex(ValueError, "delivery-evidence-drift"):
                    self.finalizer.deliver(self.key, self.checks)
        self.checks.proof = deepcopy(self.proof)
        self.checks.proof["unresolved_threads"] = 1
        with self.assertRaisesRegex(ValueError, "delivery-evidence-drift"):
            self.finalizer.deliver(self.key, self.checks)
        self.assertEqual(self.checks.writes, [])

    def test_bad_job_state_after_seal_cannot_publish(self):
        self.finish()
        for state, conclusion in (("queued", None), ("completed", "failure"), (None, None)):
            self.checks.proof["job"].update(status=state, conclusion=conclusion)
            with self.assertRaisesRegex(ValueError, "delivery-job-state"):
                self.finalizer.deliver(self.key, self.checks)
        self.assertEqual(self.checks.writes, [])

    def test_delivery_visibility_may_advance_but_cannot_regress(self):
        self.finish()
        terminal = deepcopy(self.proof)
        terminal["job"].update(status="completed", conclusion="success")
        reads = iter((terminal, self.proof))
        self.checks.evidence = lambda identity: deepcopy(next(reads))
        with self.assertRaisesRegex(ValueError, "delivery-job-regressed"):
            self.finalizer.deliver(self.key, self.checks)
        self.assertEqual(self.checks.writes, [])
        reads = iter((self.proof, terminal))
        self.finalizer.deliver(self.key, self.checks)
        self.assertEqual(self.checks.check["conclusion"], "success")

    def test_sweeper_inventory_keeps_closed_and_superseded_reservations(self):
        newer = dict(self.identity, head="9" * 40, producer_run=210)
        self.finalizer.admit(newer, 301, 2000, 3600)
        inventory = self.finalizer.sweep(5000)
        self.assertEqual(inventory["expired"], [self.key])
        self.assertTrue(inventory["complete_owned_inventory"])
        self.assertEqual(inventory["legacy_inventory"], "not-adopted")
        self.finalizer.expire(self.key, 300, 5000)
        self.finalizer.deliver(self.key, self.checks)
        self.assertTrue(all(check_id == 300 for _, check_id, _ in self.checks.writes))
        newer_entry = self.server.document["records"][J.STATE.operation_key(newer)]
        self.assertEqual(newer_entry["record"]["state"], "pending")

    def test_duplicate_admission_and_rebinding_are_rejected_correctly(self):
        before = len(self.writes())
        self.assertEqual(self.entry, self.finalizer.admit(self.identity, 300, 1100, 3600))
        self.assertEqual(len(self.writes()), before)
        for identity, check in ((dict(self.identity, base="1" * 40), 300), (self.identity, 301)):
            with self.assertRaisesRegex(ValueError, "admission-drift"):
                self.finalizer.admit(identity, check, 1100, 3600)

    def test_check_id_cannot_be_owned_by_two_operations(self):
        with self.assertRaisesRegex(ValueError, "check-reused"):
            self.finalizer.admit(dict(self.identity, producer_run=202), 300, 1100, 3600)

    def test_malformed_or_incomplete_store_does_not_yield_inventory(self):
        for mutate in (
            lambda r: r["data"]["repository"].update(databaseId=800.0),
            lambda r: r["data"]["repository"].update(isPrivate=False),
            lambda r: r["data"]["repository"]["ref"].update(name="main"),
            lambda r: r["data"]["repository"]["ref"]["target"]["tree"].update(entries=[]),
            lambda r: r["data"]["repository"]["ref"]["target"]["tree"]["entries"][0].update(mode=40960),
            lambda r: r["data"]["repository"]["ref"]["target"]["tree"]["entries"][0]["object"].update(isTruncated=True),
            lambda r: r["data"]["repository"]["ref"]["target"]["tree"]["entries"][0]["object"].update(oid="0" * 40),
            lambda r: r.update(errors=[{"message": "partial data"}]),
        ):
            with self.subTest(mutation=mutate):
                self.server.response_mutation = mutate
                with self.assertRaises(ValueError):
                    self.finalizer.sweep(5000)

    def test_legacy_records_generation_drift_and_duplicate_json_are_rejected(self):
        original = deepcopy(self.server.document)
        self.server.document["schema"] = "rep60-required-workflow:v3"
        with self.assertRaisesRegex(ValueError, "journal-configuration"):
            self.store.snapshot()
        self.server.document = original
        self.store.config["generation"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "journal-configuration"):
            self.store.snapshot()
        for raw in (b'{"x":1,"x":2}', b'{"x":1.0}', b'{"x":NaN}'):
            with self.assertRaises(ValueError):
                J.parsed(raw)

    def test_falsey_malformed_graphql_errors_never_authorize_a_write(self):
        before = len(self.writes())
        for errors in (None, False, 0, 0.0, "", {}, []):
            with self.subTest(errors=errors):
                self.server.response_mutation = lambda response: response.update(errors=errors)
                with self.assertRaisesRegex(ValueError, "store-response"):
                    self.finish()
        self.assertEqual(len(self.writes()), before)
        self.assertEqual(self.checks.writes, [])

    def test_store_uses_accepted_bounded_parser_before_any_transition(self):
        self.assertIs(J.parsed, J.JSON.parsed)
        self.assertIs(J.JournalRejected, J.JSON.JournalRejected)
        self.assertEqual(J.MAX_BYTES, J.JSON.MAX_BYTES)
        raw = b"[" * 2000 + b"0" + b"]" * 2000

        def deep_blob(response):
            blob = response["data"]["repository"]["ref"]["target"]["tree"]["entries"][0]["object"]
            blob.update(text=raw.decode(), byteSize=len(raw), oid=hashlib.sha1(
                b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest())

        self.server.response_mutation = deep_blob
        before = len(self.writes())
        for action in (lambda: self.finalizer.sweep(5000), self.finish):
            with self.assertRaisesRegex(J.JournalRejected, "^journal-depth-limit$"):
                action()
        self.assertEqual(len(self.writes()), before)
        self.assertEqual(self.checks.writes, [])

    def test_no_deletion_reopening_payload_mutation_or_receipt_shortcut(self):
        self.finish()
        self.finalizer.deliver(self.key, self.checks)
        before = self.store.snapshot()
        for mutation in (
            lambda d: d["records"].clear(),
            lambda d: d["records"].update({self.key: deepcopy(self.entry)}),
            lambda d: d["records"][self.key]["outbox"]["payload"].update(conclusion="failure"),
            lambda d: d["records"][self.key].update(delivered=False),
        ):
            candidate = deepcopy(before["journal"])
            mutation(candidate)
            with self.assertRaises(ValueError):
                self.store.swap(before, candidate)

    def test_capacity_is_fail_closed_without_dropping_owned_orphans(self):
        original = J.MAX_RECORDS
        try:
            J.MAX_RECORDS = 1
            with self.assertRaisesRegex(ValueError, "journal-record-limit"):
                self.finalizer.admit(dict(self.identity, producer_run=202), 301, 1100, 3600)
            self.assertEqual(self.finalizer.sweep(5000)["expired"], [self.key])
        finally:
            J.MAX_RECORDS = original

    def test_missing_or_failed_critical_step_never_seals(self):
        for steps in ([], [{"name": STEP, "status": "completed", "conclusion": "failure"}]):
            proof = deepcopy(self.proof)
            proof["job"]["steps"] = steps
            with self.assertRaises(ValueError):
                self.finish(first_read=proof, final_read=proof)
        self.assertIsNone(self.server.document["records"][self.key]["outbox"])


if __name__ == "__main__":
    unittest.main()
