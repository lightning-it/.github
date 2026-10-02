"""Inert LI-219 transition model; no GitHub writes or production caller.

Inputs are normalized, authoritative reads from a future protected adapter,
never event payloads or PR-controlled documents. This model does not verify
GitHub provenance or authorize a check mutation. See the companion design.
"""

from copy import deepcopy
import hashlib
import json
import re


BINDING_FIELDS = {
    "repository", "repository_id", "pr", "base", "head", "controller",
    "ruleset_digest", "actor_id", "producer_run", "producer_attempt",
    "admission_run", "reviewer_id", "metadata_digest",
}
IDENTIFIERS = {
    "repository_id", "pr", "actor_id", "producer_run", "producer_attempt",
    "admission_run", "reviewer_id",
}


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def positive(value):
    return type(value) is int and value > 0


def digest(value):
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode()).hexdigest()


def binding(value):
    require(type(value) is dict and set(value) == BINDING_FIELDS,
            "binding-shape")
    for key in IDENTIFIERS:
        require(positive(value[key]), "binding-" + key)
    require(value["producer_attempt"] == 1, "producer-attempt")
    require(type(value["repository"]) is str and re.fullmatch(
        r"lightning-it/[A-Za-z0-9_.-]+", value["repository"]), "repository")
    for key in ("base", "head", "controller", "ruleset_digest", "metadata_digest"):
        size = 64 if key.endswith("digest") else 40
        require(type(value[key]) is str and re.fullmatch(
            rf"[0-9a-f]{{{size}}}", value[key]), "binding-" + key)
    return value


def operation_key(value):
    value = binding(value)
    # Base/controller changes cannot admit a second record for the same run.
    return digest({key: value[key] for key in (
        "repository_id", "pr", "head", "producer_run",
    )})


def record(value):
    require(type(value) is dict and set(value) == {
        "schema", "key", "binding", "check_id", "created", "expires",
        "version", "state", "reason", "evidence_digest",
    }, "record-shape")
    require(value["schema"] == "li219-transition-model/v1", "record-schema")
    require(value["key"] == operation_key(value["binding"]), "record-key")
    for field in ("check_id", "created", "expires", "version"):
        require(positive(value[field]), "record-" + field)
    require(value["expires"] > value["created"], "record-expiry")
    require(value["state"] in ("pending", "success", "failure"), "record-state")
    if value["state"] == "pending":
        require(value["version"] == 1 and value["reason"] == "admitted"
                and value["evidence_digest"] is None, "pending-record")
    else:
        require(value["version"] == 2, "terminal-version")
        if value["state"] == "success":
            require(value["reason"] == "verified"
                    and type(value["evidence_digest"]) is str
                    and re.fullmatch(r"[0-9a-f]{64}", value["evidence_digest"]),
                    "success-record")
        else:
            require(value["reason"] == "expired"
                    and value["evidence_digest"] is None, "failure-record")
    return value


def admit(identity, check_id, now, ttl, existing=None):
    """Plan admission after a complete, serialized reservation inventory read."""
    identity = binding(identity)
    require(positive(check_id) and positive(now) and positive(ttl), "admission")
    if existing is not None:
        record(existing)
        require(existing["binding"] == identity
                and existing["check_id"] == check_id, "admission-drift")
        return deepcopy(existing)
    return record({
        "schema": "li219-transition-model/v1", "key": operation_key(identity),
        "binding": deepcopy(identity), "check_id": check_id,
        "created": now, "expires": now + ttl, "version": 1,
        "state": "pending", "reason": "admitted", "evidence_digest": None,
    })


def evidence(value, identity, policy_step):
    """Validate normalized evidence; live provenance remains the adapter's job."""
    require(type(value) is dict and set(value) == {
        "binding", "pr_open", "draft", "job", "review", "unresolved_threads",
    }, "evidence-shape")
    require(binding(value["binding"]) == identity, "evidence-binding-drift")
    require(value["pr_open"] is True and value["draft"] is False, "pr-state")
    require(type(value["unresolved_threads"]) is int
            and value["unresolved_threads"] == 0, "unresolved-threads")
    job = value["job"]
    require(type(job) is dict and set(job) == {
        "id", "run_id", "run_attempt", "head_sha", "status", "conclusion", "steps",
    }, "job-shape")
    require(positive(job["id"]) and type(job["run_id"]) is int
            and job["run_id"] == identity["producer_run"]
            and type(job["run_attempt"]) is int
            and job["run_attempt"] == identity["producer_attempt"]
            and job["head_sha"] == identity["head"], "job-binding")
    require((job["status"], job["conclusion"]) in (
        ("in_progress", None), ("completed", "success"),
    ), "job-not-successful")
    require(type(policy_step) is str and bool(policy_step)
            and policy_step != "Publish bound neutral result", "policy-step")
    require(type(job["steps"]) is list, "steps-shape")
    selected = []
    for step in job["steps"]:
        require(type(step) is dict and set(step) == {
            "name", "status", "conclusion",
        } and type(step["name"]) is str, "step-shape")
        if step["name"] in (policy_step, "Publish bound neutral result"):
            require(step["status"] == "completed" and step["conclusion"] == "success",
                    "critical-step-not-successful")
            selected.append(step["name"])
    require(sorted(selected) == sorted([policy_step, "Publish bound neutral result"]),
            "critical-step-missing-or-duplicate")
    review = value["review"]
    require(type(review) is dict and set(review) == {
        "id", "reviewer_id", "head", "state",
    }, "review-shape")
    require(positive(review["id"]) and type(review["reviewer_id"]) is int
            and review["reviewer_id"] == identity["reviewer_id"]
            and review["head"] == identity["head"]
            and review["state"] in ("APPROVED", "COMMENTED"), "review-binding")
    return value


def finalize(reservation, event_identity, first_read, final_read, policy_step, now):
    """Return a CAS candidate. Only the adapter can atomically persist it.

    Events are locators, not proof. Both evidence arguments must be independent
    authoritative reads. Rejected events never turn a current check red.
    """
    reservation = record(reservation)
    identity = reservation["binding"]
    require(binding(event_identity) == identity, "event-binding-drift")
    require(positive(now) and now >= reservation["created"], "clock")
    if reservation["state"] != "pending":
        return deepcopy(reservation)
    require(now < reservation["expires"], "expired-awaiting-sweeper")
    evidence(first_read, identity, policy_step)
    evidence(final_read, identity, policy_step)
    # Terminal job visibility may advance between reads without evidence drift.
    first_state = (first_read["job"]["status"], first_read["job"]["conclusion"])
    final_state = (final_read["job"]["status"], final_read["job"]["conclusion"])
    require(first_state == final_state or (first_state == ("in_progress", None)
            and final_state == ("completed", "success")), "job-visibility-regressed")

    def stable(value):
        normalized = deepcopy(value)
        normalized["job"].pop("status")
        normalized["job"].pop("conclusion")
        return normalized
    require(stable(first_read) == stable(final_read), "final-read-drift")
    candidate = deepcopy(reservation)
    candidate.update(state="success", reason="verified", version=2,
                     evidence_digest=digest(stable(final_read)))
    return record(candidate)


def sweep(reservation, current_check_id, now):
    """Plan expiry of only this exact reservation, never a new head's check."""
    reservation = record(reservation)
    require(positive(current_check_id)
            and current_check_id == reservation["check_id"], "sweeper-check-drift")
    require(positive(now) and now >= reservation["created"], "clock")
    candidate = deepcopy(reservation)
    if candidate["state"] == "pending" and now >= candidate["expires"]:
        candidate.update(state="failure", reason="expired", version=2)
    return record(candidate)


def compare_and_swap(current, expected, candidate):
    """Pure model of serialized storage, not a distributed lock implementation."""
    record(current)
    record(expected)
    record(candidate)
    require(current == expected, "reservation-concurrently-changed")
    require(candidate["binding"] == current["binding"]
            and candidate["check_id"] == current["check_id"]
            and candidate["created"] == current["created"]
            and candidate["expires"] == current["expires"], "candidate-drift")
    require(candidate == current or (current["state"] == "pending"
            and candidate["state"] in ("success", "failure")), "terminal-is-absorbing")
    return deepcopy(candidate)
