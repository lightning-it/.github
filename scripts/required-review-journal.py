"""LI-219 CAS journal and terminal outbox, without a workflow or credentials.

The protected adapter supplies authoritative normalized evidence and transports.
This component never treats event JSON as evidence, creates a check, requests a
review, reruns a workflow, or changes required-check authority.
"""

import base64
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "journal_state", ROOT / "scripts/required-review-state.py")
STATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(STATE)

SCHEMA = "li219-journal/v1"
CONTEXT = "Current revision review"
FILE = "reservations.json"
REF = "refs/heads/li219-reservations"
MAX_BYTES = 1024 * 1024
MAX_RECORDS = 512
READ = """query($owner:String!,$name:String!,$ref:String!){
repository(owner:$owner,name:$name){databaseId nameWithOwner isPrivate
ref(qualifiedName:$ref){name target{__typename ... on Commit{oid tree{
entries{name mode type object{... on Blob{oid byteSize isTruncated text}}}
}}}}}}"""
COMMIT = """mutation($input:CreateCommitOnBranchInput!){
createCommitOnBranch(input:$input){commit{oid} ref{name target{oid}}}}"""


class JournalRejected(ValueError):
    """A fixed source-owned invariant identifier."""


def require(condition, reason):
    if not condition:
        raise JournalRejected(reason)


def hex_string(value, length):
    return type(value) is str and re.fullmatch(rf"[0-9a-f]{{{length}}}", value) is not None


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("ascii")


def pairs(items):
    result = {}
    for key, value in items:
        require(key not in result, "duplicate-json-key")
        result[key] = value
    return result


def no_number(value):
    raise JournalRejected("noninteger-json-number")


def parsed(raw):
    require(type(raw) is bytes and len(raw) <= MAX_BYTES, "journal-byte-limit")
    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_float=no_number,
                          parse_constant=no_number)
    except JournalRejected:
        raise
    except (ValueError, UnicodeError):
        raise JournalRejected("journal-json") from None


def configuration(value):
    require(type(value) is dict and set(value) == {
        "store_repository", "store_repository_id", "app_id", "generation",
    }, "configuration-shape")
    require(type(value["store_repository"]) is str and re.fullmatch(
        r"lightning-it/[A-Za-z0-9_.-]+", value["store_repository"]), "store-repository")
    for key in ("store_repository_id", "app_id"):
        require(STATE.positive(value[key]), "configuration-" + key)
    require(hex_string(value["generation"], 64), "configuration-generation")
    return value


def timestamp(epoch):
    require(STATE.positive(epoch), "terminal-clock")
    try:
        return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (OverflowError, OSError, ValueError):
        raise JournalRejected("terminal-clock") from None


def payload(record, completed):
    """Only this deterministic payload may be published for a sealed record."""
    STATE.record(record)
    require(record["state"] in ("success", "failure"), "outbox-nonterminal")
    summary = {
        "schema": "li219-terminal/v1", "operation": record["key"],
        "binding_digest": STATE.digest(record["binding"]),
        "evidence_digest": record["evidence_digest"], "reason": record["reason"],
    }
    return {"status": "completed", "conclusion": record["state"],
            "completed_at": timestamp(completed),
            "output": {"title": "LI-219 " + record["reason"],
                       "summary": encoded(summary).decode("ascii")}}


def item(value, config):
    require(type(value) is dict and set(value) == {
        "record", "app_id", "external_id", "outbox", "delivered",
    }, "item-shape")
    record = STATE.record(value["record"])
    require(STATE.positive(value["app_id"]) and value["app_id"] == config["app_id"],
            "item-app")
    require(value["external_id"] == "li219:v1:" + config["generation"] + ":" + record["key"],
            "item-external-id")
    require(type(value["delivered"]) is bool, "item-delivered")
    outbox = value["outbox"]
    if record["state"] == "pending":
        require(outbox is None and value["delivered"] is False, "pending-outbox")
    else:
        require(type(outbox) is dict and set(outbox) == {"completed", "payload", "digest"},
                "outbox-shape")
        require(STATE.positive(outbox["completed"])
                and outbox["completed"] >= record["created"], "outbox-clock")
        if record["state"] == "success":
            require(outbox["completed"] < record["expires"], "outbox-expired-success")
        else:
            require(outbox["completed"] >= record["expires"], "outbox-early-expiry")
        require(outbox["payload"] == payload(record, outbox["completed"]), "outbox-payload")
        require(outbox["digest"] == STATE.digest(outbox["payload"]), "outbox-digest")
    return value


def journal(value, config):
    configuration(config)
    require(type(value) is dict and set(value) == {"schema", "configuration", "records"},
            "journal-shape")
    require(value["schema"] == SCHEMA and value["configuration"] == config,
            "journal-configuration")
    records = value["records"]
    require(type(records) is dict and len(records) <= MAX_RECORDS, "journal-record-limit")
    checks = set()
    for key, entry in records.items():
        item(entry, config)
        record = entry["record"]
        require(key == record["key"], "journal-key")
        check = (record["binding"]["repository_id"], record["check_id"])
        require(check not in checks, "journal-check-reused")
        checks.add(check)
    require(len(encoded(value)) <= MAX_BYTES, "journal-byte-limit")
    return value


def empty(config):
    return journal({"schema": SCHEMA, "configuration": deepcopy(config), "records": {}}, config)


def transition(previous, candidate, config):
    """Validate one append/transition/receipt; no deletion, rebinding or reopening."""
    journal(previous, config)
    journal(candidate, config)
    before, after = previous["records"], candidate["records"]
    require(set(before) <= set(after), "journal-deletion")
    changed = [key for key in after if after[key] != before.get(key)]
    require(len(changed) == 1, "journal-one-transition")
    key = changed[0]
    if key not in before:
        require(after[key]["record"]["state"] == "pending", "admission-nonpending")
        return
    old, new = before[key], after[key]
    require(old["app_id"] == new["app_id"] and old["external_id"] == new["external_id"],
            "item-ownership-drift")
    STATE.compare_and_swap(old["record"], old["record"], new["record"])
    if old["outbox"] is None:
        require(new["outbox"] is not None and new["delivered"] is False, "seal-transition")
    else:
        require(old["record"] == new["record"] and old["outbox"] == new["outbox"]
                and old["delivered"] is False and new["delivered"] is True,
                "outbox-is-immutable")


class GitHubJournal:
    """A single private data branch, using GitHub's expectedHeadOid CAS.

    call(query, variables) is the future protected, budgeted GraphQL transport.
    It must reject redirects, GraphQL errors, oversized replies and unknown
    credentials. The journal owns both query strings and the only writable file.
    There is no CLI or environment-token fallback.
    """

    def __init__(self, config, call):
        self.config = deepcopy(configuration(config))
        self.call = call

    def snapshot(self):
        owner, name = self.config["store_repository"].split("/")
        response = self.call(READ, {"owner": owner, "name": name, "ref": REF})
        require(type(response) is dict and not response.get("errors"), "store-response")
        try:
            repo = response["data"]["repository"]
            require(repo["nameWithOwner"] == self.config["store_repository"]
                    and STATE.positive(repo["databaseId"])
                    and repo["databaseId"] == self.config["store_repository_id"]
                    and repo["isPrivate"] is True, "store-identity")
            ref = repo["ref"]
            require(ref["name"] == REF.removeprefix("refs/heads/"), "store-ref")
            commit = ref["target"]
            require(commit["__typename"] == "Commit" and hex_string(commit["oid"], 40),
                    "store-commit")
            entries = commit["tree"]["entries"]
            require(type(entries) is list and len(entries) == 1, "store-tree")
            entry = entries[0]
            require(entry["name"] == FILE and type(entry["mode"]) is int
                    and entry["mode"] == 33188 and entry["type"] == "blob", "store-file")
            blob = entry["object"]
            require(type(blob["text"]) is str and blob["isTruncated"] is False,
                    "store-blob-truncated")
            raw = blob["text"].encode("utf-8")
            require(type(blob["byteSize"]) is int and blob["byteSize"] == len(raw)
                    and len(raw) <= MAX_BYTES, "store-blob-size")
            sha = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
            require(blob["oid"] == sha, "store-blob-hash")
            result = journal(parsed(raw), self.config)
            return {"oid": commit["oid"], "journal": result}
        except (KeyError, TypeError, AttributeError, UnicodeError):
            raise JournalRejected("store-shape") from None

    def swap(self, expected, candidate):
        require(type(expected) is dict and set(expected) == {"oid", "journal"}
                and hex_string(expected["oid"], 40), "snapshot-shape")
        transition(expected["journal"], candidate, self.config)
        # An exact prior read is mandatory even when the remote CAS later loses.
        require(self.snapshot() == expected, "journal-concurrently-changed")
        variables = {"input": {
            "branch": {"repositoryNameWithOwner": self.config["store_repository"],
                       "branchName": REF.removeprefix("refs/heads/")},
            "expectedHeadOid": expected["oid"],
            "message": {"headline": "LI-219 reservation " + STATE.digest(candidate)},
            "fileChanges": {"additions": [{"path": FILE,
                "contents": base64.b64encode(encoded(candidate)).decode("ascii")} ]},
        }}
        try:
            self.call(COMMIT, variables)
        except Exception:
            # An unknown response never licenses a second write. Always read back.
            pass
        observed = self.snapshot()
        require(observed["oid"] != expected["oid"] and observed["journal"] == candidate,
                "journal-write-unconfirmed")
        return observed


class Finalizer:
    """Serialized state and idempotent exact-check writes, never raw authorization.

    The caller must first authenticate the protected controller and independently
    normalize complete evidence with the authoritative validators. An untrusted
    caller supplying dictionaries cannot become a production writer through this
    class. Both finalizer and sweeper use this same journal and terminal outbox.
    """

    def __init__(self, store):
        self.store = store

    def admit(self, identity, check_id, now, ttl):
        record = STATE.admit(identity, check_id, now, ttl)
        snapshot = self.store.snapshot()
        entries = snapshot["journal"]["records"]
        prior = entries.get(record["key"])
        if prior is not None:
            STATE.admit(identity, check_id, now, ttl, prior["record"])
            return deepcopy(prior)
        candidate = deepcopy(snapshot["journal"])
        config = self.store.config
        candidate["records"][record["key"]] = {
            "record": record, "app_id": config["app_id"],
            "external_id": "li219:v1:" + config["generation"] + ":" + record["key"],
            "outbox": None, "delivered": False,
        }
        committed = self.store.swap(snapshot, candidate)
        return deepcopy(committed["journal"]["records"][record["key"]])

    def seal(self, key, decide, now):
        require(hex_string(key, 64), "operation-key")
        snapshot = self.store.snapshot()
        require(key in snapshot["journal"]["records"], "operation-missing")
        current = snapshot["journal"]["records"][key]
        selected = decide(deepcopy(current["record"]))
        STATE.compare_and_swap(current["record"], current["record"], selected)
        if selected == current["record"]:
            return deepcopy(current)
        candidate = deepcopy(snapshot["journal"])
        entry = candidate["records"][key]
        entry["record"] = selected
        terminal = payload(selected, now)
        entry["outbox"] = {"completed": now, "payload": terminal,
                           "digest": STATE.digest(terminal)}
        committed = self.store.swap(snapshot, candidate)
        return deepcopy(committed["journal"]["records"][key])

    def finalize(self, identity, first_read, final_read, policy_step, now):
        return self.seal(STATE.operation_key(identity), lambda current: STATE.finalize(
            current, identity, first_read, final_read, policy_step, now), now)

    def sweep(self, now):
        """Inventory all owned records, including closed PRs and superseded heads.

        One bounded snapshot only, independent of GitHub's open-PR inventory.
        Returns locators; expire() performs a fresh CAS for each reservation.
        """
        require(STATE.positive(now), "sweep-clock")
        snapshot = self.store.snapshot()
        return {"store_oid": snapshot["oid"], "scope": "owned-journal-only",
                "legacy_inventory": "not-adopted", "complete_owned_inventory": True,
                "expired": sorted(key for key, entry in snapshot["journal"]["records"].items()
                                  if entry["record"]["state"] == "pending"
                                  and now >= entry["record"]["expires"]),
                "undelivered": sorted(key for key, entry in snapshot["journal"]["records"].items()
                                      if entry["outbox"] is not None and not entry["delivered"])}

    def expire(self, key, check_id, now):
        return self.seal(key, lambda current: STATE.sweep(current, check_id, now), now)

    def deliver(self, key, checks):
        """Reconcile first, PATCH once, then independently read the exact check.

        checks.read(repository, id) / checks.patch(repository, id, payload) are
        protected App transports, not webhooks. All deliveries for one operation
        send identical bytes: there is no takeover lease or competing decision.
        """
        require(hex_string(key, 64), "operation-key")
        snapshot = self.store.snapshot()
        require(key in snapshot["journal"]["records"], "operation-missing")
        entry = snapshot["journal"]["records"][key]
        require(entry["outbox"] is not None, "outbox-missing")
        record = entry["record"]
        repo, check_id = record["binding"]["repository"], record["check_id"]
        expected = entry["outbox"]["payload"]

        def observed_terminal():
            check = checks.read(repo, check_id)
            require(type(check) is dict and STATE.positive(check.get("id"))
                    and check["id"] == check_id and check.get("name") == CONTEXT
                    and check.get("head_sha") == record["binding"]["head"]
                    and check.get("external_id") == entry["external_id"]
                    and type(check.get("app")) is dict
                    and STATE.positive(check["app"].get("id"))
                    and check["app"]["id"] == entry["app_id"], "check-ownership-drift")
            if check.get("status") == "completed":
                require(all(check.get(field) == value for field, value in expected.items()
                            if field != "output")
                        and type(check.get("output")) is dict
                        and all(check["output"].get(field) == value
                                for field, value in expected["output"].items()),
                        "check-terminal-conflict")
                return True
            require(check.get("status") in ("queued", "in_progress")
                    and check.get("conclusion") is None and entry["delivered"] is False,
                    "check-state")
            return False

        if not observed_terminal():
            # Last fence: only the immutable committed terminal outbox can write.
            current = self.store.snapshot()["journal"]["records"].get(key)
            require(current is not None and current["record"] == record
                    and current["outbox"] == entry["outbox"]
                    and current["app_id"] == entry["app_id"]
                    and current["external_id"] == entry["external_id"], "outbox-fence")
            if record["state"] == "success":
                # A durable success proposal is not perpetual write authority.
                # The protected adapter repeats its complete authoritative read;
                # webhook fields and a cached pre-seal snapshot are insufficient.
                for _ in range(2):
                    proof = checks.evidence(deepcopy(record["binding"]))
                    require(type(proof) is dict and type(proof.get("job")) is dict,
                            "delivery-evidence-shape")
                    require((proof["job"].get("status"), proof["job"].get("conclusion"))
                            in (("in_progress", None), ("completed", "success")),
                            "delivery-job-state")
                    stable = deepcopy(proof)
                    stable["job"].pop("status", None)
                    stable["job"].pop("conclusion", None)
                    require(STATE.digest(stable) == record["evidence_digest"],
                            "delivery-evidence-drift")
            try:
                checks.patch(repo, check_id, deepcopy(expected))
            except Exception:
                pass
            require(observed_terminal(), "check-write-unconfirmed")
        if not entry["delivered"]:
            latest = self.store.snapshot()
            current = latest["journal"]["records"][key]
            require(current["record"] == record and current["outbox"] == entry["outbox"],
                    "outbox-fence")
            if not current["delivered"]:
                candidate = deepcopy(latest["journal"])
                candidate["records"][key]["delivered"] = True
                self.store.swap(latest, candidate)
        return {"operation": key, "check_id": check_id, "delivered": True,
                "outbox_digest": entry["outbox"]["digest"]}
