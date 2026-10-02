"""Deterministic LI-219 model tests; these are not GitHub acceptance evidence."""

from copy import deepcopy
import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "required_review_state", ROOT / "scripts/required-review-state.py",
)
MODEL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODEL)
POLICY_STEP = "Verify bound current revision policy"


class RequiredReviewStateTests(unittest.TestCase):
    def setUp(self):
        self.identity = {
            "repository": "lightning-it/example", "repository_id": 100,
            "pr": 7, "base": "a" * 40, "head": "b" * 40,
            "controller": "c" * 40, "ruleset_digest": "d" * 64,
            "actor_id": 101, "producer_run": 200, "producer_attempt": 1,
            "admission_run": 201, "reviewer_id": 102,
            "metadata_digest": "e" * 64,
        }
        self.reservation = MODEL.admit(self.identity, 300, 1000, 3600)
        self.proof = {
            "binding": deepcopy(self.identity), "pr_open": True, "draft": False,
            "unresolved_threads": 0,
            "job": {
                "id": 400, "run_id": 200, "run_attempt": 1,
                "head_sha": "b" * 40, "status": "in_progress", "conclusion": None,
                "steps": [
                    {"name": POLICY_STEP, "status": "completed", "conclusion": "success"},
                    {"name": "Publish bound neutral result", "status": "completed",
                     "conclusion": "success"},
                ],
            },
            "review": {"id": 500, "reviewer_id": 102, "head": "b" * 40,
                       "state": "COMMENTED"},
        }

    def finish(self, proof=None, final_read=None, event=None, now=1180, record=None):
        proof = self.proof if proof is None else proof
        return MODEL.finalize(
            self.reservation if record is None else record,
            self.identity if event is None else event,
            proof, proof if final_read is None else final_read, POLICY_STEP, now,
        )

    def test_180_second_job_finalization_delay_does_not_need_polling(self):
        # The first event is evaluated once, 180 seconds after admission.
        # GitHub still reports in_progress although both critical steps passed.
        result = self.finish(now=1180)
        self.assertEqual(result["state"], "success")
        self.assertEqual(self.reservation["state"], "pending")
        terminal = deepcopy(self.proof)
        terminal["job"].update(status="completed", conclusion="success")
        self.assertEqual(result, self.finish(terminal, now=1360, record=result))

    def test_terminal_visibility_can_advance_between_reads(self):
        terminal = deepcopy(self.proof)
        terminal["job"].update(status="completed", conclusion="success")
        self.assertEqual(self.finish(), self.finish(final_read=terminal))
        self.assertEqual(self.finish(), self.finish(terminal, final_read=terminal))

    def test_terminal_visibility_cannot_regress_between_reads(self):
        terminal = deepcopy(self.proof)
        terminal["job"].update(status="completed", conclusion="success")
        original = deepcopy(self.reservation)
        with self.assertRaisesRegex(ValueError, "job-visibility-regressed"):
            self.finish(terminal, final_read=self.proof)
        self.assertEqual(original, self.reservation)

    def test_duplicate_and_out_of_order_events_are_absorbing(self):
        first = self.finish()
        for time in (1180, 1200, 9000):
            self.assertEqual(first, self.finish(record=first, now=time))
        self.assertEqual(first, MODEL.sweep(first, 300, 9000))

    def test_concurrent_finalizers_can_commit_only_once(self):
        first = self.finish()
        current = MODEL.compare_and_swap(self.reservation, self.reservation, first)
        with self.assertRaisesRegex(ValueError, "concurrently-changed"):
            MODEL.compare_and_swap(current, self.reservation, self.finish())
        self.assertEqual(current, self.finish(record=current))

    def test_sweeper_and_finalizer_race_is_compare_and_swap_guarded(self):
        expired = MODEL.sweep(self.reservation, 300, 4600)
        committed = MODEL.compare_and_swap(self.reservation, self.reservation, expired)
        with self.assertRaisesRegex(ValueError, "concurrently-changed"):
            MODEL.compare_and_swap(committed, self.reservation, self.finish())
        self.assertEqual(committed, self.finish(record=committed, now=4700))

    def test_sweeper_closes_only_expired_exact_check(self):
        self.assertEqual(self.reservation, MODEL.sweep(self.reservation, 300, 4599))
        expired = MODEL.sweep(self.reservation, 300, 4600)
        self.assertEqual("failure", expired["state"])
        self.assertEqual(expired, MODEL.sweep(expired, 300, 5000))
        with self.assertRaisesRegex(ValueError, "check-drift"):
            MODEL.sweep(self.reservation, 301, 5000)
        with self.assertRaisesRegex(ValueError, "awaiting-sweeper"):
            self.finish(now=4600)

    def test_every_binding_drift_is_rejected_without_mutation(self):
        for field, original in self.identity.items():
            changed = deepcopy(self.identity)
            changed[field] = original + 1 if type(original) is int else (
                "lightning-it/other" if field == "repository" else "f" * len(original)
            )
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    self.finish(event=changed)
                proof = deepcopy(self.proof)
                proof["binding"] = changed
                with self.assertRaises(ValueError):
                    self.finish(proof)
                self.assertEqual("pending", self.reservation["state"])

    def test_stale_head_event_cannot_change_new_head_check(self):
        stale = deepcopy(self.identity)
        stale["head"] = "f" * 40
        with self.assertRaisesRegex(ValueError, "event-binding-drift"):
            self.finish(event=stale)
        self.assertEqual(300, self.reservation["check_id"])
        self.assertEqual("pending", self.reservation["state"])

    def test_admission_is_idempotent_but_not_a_second_run_with_drift(self):
        self.assertEqual(self.reservation, MODEL.admit(
            self.identity, 300, 1300, 100, existing=self.reservation,
        ))
        for field in ("base", "controller", "ruleset_digest"):
            changed = deepcopy(self.identity)
            changed[field] = "f" * len(changed[field])
            self.assertEqual(MODEL.operation_key(changed), self.reservation["key"])
            with self.assertRaisesRegex(ValueError, "admission-drift"):
                MODEL.admit(changed, 300, 1300, 3600, existing=self.reservation)

    def test_failed_missing_duplicate_and_incomplete_critical_steps_reject(self):
        for index in (0, 1):
            for status, conclusion in (("completed", "failure"), ("in_progress", None),
                                       ("completed", "skipped"), ("queued", None)):
                proof = deepcopy(self.proof)
                proof["job"]["steps"][index].update(status=status, conclusion=conclusion)
                with self.subTest(index=index, status=status, conclusion=conclusion):
                    with self.assertRaisesRegex(ValueError, "critical-step"):
                        self.finish(proof)
            missing = deepcopy(self.proof)
            del missing["job"]["steps"][index]
            with self.assertRaisesRegex(ValueError, "missing-or-duplicate"):
                self.finish(missing)
            duplicate = deepcopy(self.proof)
            duplicate["job"]["steps"].append(duplicate["job"]["steps"][index])
            with self.assertRaisesRegex(ValueError, "missing-or-duplicate"):
                self.finish(duplicate)

    def test_failed_queued_or_foreign_job_rejects(self):
        for status, conclusion in (("queued", None), ("completed", "failure"),
                                   ("completed", "cancelled"), ("in_progress", "success")):
            proof = deepcopy(self.proof)
            proof["job"].update(status=status, conclusion=conclusion)
            with self.assertRaisesRegex(ValueError, "not-successful"):
                self.finish(proof)
        for field, value in (("run_id", 201), ("run_attempt", 2), ("head_sha", "f" * 40)):
            proof = deepcopy(self.proof)
            proof["job"][field] = value
            with self.assertRaisesRegex(ValueError, "job-binding"):
                self.finish(proof)

    def test_review_and_thread_drift_rejects(self):
        for field, value in (("reviewer_id", 999), ("head", "f" * 40),
                             ("state", "DISMISSED"), ("state", "CHANGES_REQUESTED")):
            proof = deepcopy(self.proof)
            proof["review"][field] = value
            with self.assertRaisesRegex(ValueError, "review-binding"):
                self.finish(proof)
        for count in (1, False, "0", None):
            proof = deepcopy(self.proof)
            proof["unresolved_threads"] = count
            with self.assertRaisesRegex(ValueError, "unresolved-threads"):
                self.finish(proof)
        changed = deepcopy(self.proof)
        changed["review"]["id"] += 1
        with self.assertRaisesRegex(ValueError, "final-read-drift"):
            self.finish(final_read=changed)

    def test_closed_or_draft_pr_rejects(self):
        for field, value in (("pr_open", False), ("draft", True), ("draft", 0)):
            proof = deepcopy(self.proof)
            proof[field] = value
            with self.assertRaisesRegex(ValueError, "pr-state"):
                self.finish(proof)

    def test_malformed_identity_types_reject(self):
        for field in MODEL.IDENTIFIERS:
            for bad in (True, 0, -1, "1", None, 1.0):
                identity = deepcopy(self.identity)
                identity[field] = bad
                with self.subTest(field=field, bad=bad):
                    with self.assertRaises(ValueError):
                        MODEL.admit(identity, 300, 1000, 3600)
        malformed = deepcopy(self.identity)
        malformed["untrusted"] = True
        with self.assertRaisesRegex(ValueError, "binding-shape"):
            MODEL.operation_key(malformed)

    def test_cas_cannot_replace_check_binding_or_terminal_state(self):
        success = self.finish()
        changed = deepcopy(success)
        changed["check_id"] += 1
        with self.assertRaisesRegex(ValueError, "candidate-drift"):
            MODEL.compare_and_swap(self.reservation, self.reservation, changed)
        with self.assertRaisesRegex(ValueError, "terminal-is-absorbing"):
            MODEL.compare_and_swap(success, success, self.reservation)


if __name__ == "__main__":
    unittest.main()
