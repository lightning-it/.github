"""Permanent archive claims in the existing private consumer's immutable tags.

Only a confirmed first ref creation grants one create in that invocation. A
conflict or uncertain response grants none; there is no mutation retry. A later
invocation can claim only if no earlier ref was created, in which case no prior
invocation could have obtained upload authority. An unknown S3 PUT always has
an already durable claim, so every later invocation remains read-only.
"""
from __future__ import annotations

from datetime import datetime
import json
import hashlib
import re
import subprocess
from urllib.parse import quote

from workflow_control import ControlError, canonical, digest, require, sha

PREFIX = "release-archive/v1/"
RULE_NAME = "Release archive immutable references"
REF_PATTERNS = ["refs/tags/" + PREFIX + "*/" + kind for kind in ("reservation", "receipt")]


def rule_payload():
    return {"name": RULE_NAME, "target": "tag", "enforcement": "active", "bypass_actors": [],
            "conditions": {"ref_name": {"include": REF_PATTERNS, "exclude": []}},
            "rules": [{"type": "update"}, {"type": "deletion"}]}


class NativeAPI:
    """Preserve HTTP status for atomic creation; never retry or print responses."""
    def request(self, method, path, data=None):
        require(method in {"GET", "POST", "PATCH", "DELETE"} and path.startswith("repos/lightning-it/")
                and not any(c.isspace() for c in path), "archive-native-api-path")
        if method in {"PATCH", "DELETE"}:
            require(re.fullmatch(r"repos/lightning-it/[A-Za-z0-9_.-]+/git/refs/tags/release-archive/v1/[0-9a-f]{64}/reservation", path),
                    "archive-negative-test-scope")
        command = ["gh", "api", "--include", "--method", method, path]
        if data is not None:
            command += ["--input", "-"]
        try:
            result = subprocess.run(command, input=canonical(data) if data is not None else None,
                                    capture_output=True, timeout=60, check=False)
        except (OSError, subprocess.TimeoutExpired):
            raise ControlError("archive-native-outcome-unknown") from None
        output = result.stdout.replace(b"\r\n", b"\n")
        header, separator, body = output.partition(b"\n\n")
        status = re.match(rb"HTTP/\S+ ([0-9]{3})(?: |\n)", header)
        require(separator and status, "archive-native-outcome-unknown")
        status = int(status[1])
        require(result.returncode == 0 or status >= 400, "archive-native-outcome-unknown")
        try:
            return status, json.loads(body)
        except ValueError:
            raise ControlError("archive-native-response-unreadable") from None


def operation(subject):
    require(type(subject) is dict and set(subject) == {"version", "repository_id", "promotion", "head_sha", "target"}
            and type(subject["version"]) is int and subject["version"] == 1 and subject["target"] == "main"
            and all(type(subject[key]) is int and subject[key] > 0 for key in ("repository_id", "promotion")),
            "archive-operation-subject")
    sha(subject["head_sha"])
    return digest(subject)


class Reservations:
    def __init__(self, api, repository, ruleset_id):
        require(type(repository) is str and re.fullmatch(r"lightning-it/[A-Za-z0-9_.-]+", repository)
                and type(ruleset_id) is int and ruleset_id > 0, "archive-reservation-scope")
        self.api, self.repository, self.ruleset_id = api, repository, ruleset_id
        self.base = "repos/" + repository

    def verify_anchor(self, anchor):
        require(type(anchor) is dict and set(anchor) == {"repository_id", "commit_sha"}
                and type(anchor["repository_id"]) is int and anchor["repository_id"] > 0,
                "archive-anchor-shape")
        commit = sha(anchor["commit_sha"])
        status, repo = self.api.request("GET", self.base)
        require(status == 200 and repo.get("full_name") == self.repository
                and type(repo.get("id")) is int and repo["id"] == anchor["repository_id"]
                and repo.get("private") is True and repo.get("archived") is False,
                "archive-anchor-repository")
        status, obj = self.api.request("GET", self.base + "/git/commits/" + commit)
        require(status == 200 and obj.get("sha") == commit, "archive-anchor-commit")

    def protection(self):
        status, repo = self.api.request("GET", self.base)
        require(status == 200 and repo.get("full_name") == self.repository and repo.get("private") is True
                and repo.get("archived") is False, "archive-private-reservation-repository")
        status, rule = self.api.request("GET", f"{self.base}/rulesets/{self.ruleset_id}")
        expected = rule_payload()
        require(status == 200 and rule.get("id") == self.ruleset_id
                and rule.get("source_type") == "Repository" and rule.get("source") == self.repository
                and all(rule.get(key) == expected[key] for key in ("name", "target", "enforcement", "bypass_actors", "conditions"))
                and sorted(rule.get("rules", []), key=lambda item: item.get("type", ""))
                == sorted(expected["rules"], key=lambda item: item["type"]), "archive-reservation-protection")
        return digest(expected)

    def read(self, key, kind):
        require(re.fullmatch(r"[0-9a-f]{64}", key) and kind in {"reservation", "receipt"}, "archive-ref-shape")
        name = PREFIX + key + "/" + kind
        status, ref = self.api.request("GET", self.base + "/git/ref/tags/" + quote(name, safe="/"))
        if status == 404:
            return None
        require(status == 200 and ref.get("ref") == "refs/tags/" + name
                and ref.get("object", {}).get("type") == "tag", "archive-reservation-ref")
        object_sha = sha(ref["object"].get("sha"))
        status, tag = self.api.request("GET", self.base + "/git/tags/" + object_sha)
        require(status == 200 and tag.get("sha") == object_sha and tag.get("tag") == name
                and tag.get("object", {}).get("type") == "commit", "archive-reservation-tag")
        try:
            record = json.loads(tag.get("message", ""))
        except ValueError:
            raise ControlError("archive-reservation-record") from None
        require(type(record) is dict and canonical(record).decode() + "\n" == tag["message"]
                and record.get("kind") == kind and record.get("operation") == key
                and type(record.get("anchor")) is dict
                and tag["object"].get("sha") == record["anchor"].get("commit_sha"), "archive-reservation-record")
        return record

    def create(self, key, kind, record):
        """One CAS attempt; uncertainty never becomes fresh create authority."""
        self.verify_anchor(record.get("anchor"))
        name = PREFIX + key + "/" + kind
        status, tag = self.api.request("POST", self.base + "/git/tags",
                                      {"tag": name, "message": canonical(record).decode() + "\n",
                                       "object": record["anchor"]["commit_sha"], "type": "commit"})
        require(status == 201 and tag.get("tag") == name, "archive-tag-create-not-confirmed")
        object_sha = sha(tag.get("sha"))
        status, ref = self.api.request("POST", self.base + "/git/refs",
                                      {"ref": "refs/tags/" + name, "sha": object_sha})
        if status in {409, 422}:
            return False
        require(status == 201 and ref.get("ref") == "refs/tags/" + name
                and ref.get("object", {}).get("sha") == object_sha, "archive-ref-create-not-confirmed")
        require(self.read(key, kind) == record, "archive-created-ref-readback")
        return True

    def claim(self, subject, package_sha256, package_bytes, authority):
        policy = self.protection()
        key = operation(subject)
        anchor = {"repository_id": subject["repository_id"], "commit_sha": subject["head_sha"]}
        self.verify_anchor(anchor)
        require(type(package_sha256) is str and re.fullmatch(r"[0-9a-f]{64}", package_sha256)
                and type(package_bytes) is int and 0 < package_bytes <= 50 * 1024 * 1024,
                "archive-reservation-package")
        require(type(authority) is dict and all(type(authority.get(name)) is int and authority[name] > 0
                for name in ("run", "attempt")), "archive-reservation-authority")
        for field in ("management_sha", "workflow_blob", "helper_sha"):
            sha(authority.get(field))
        expected = {"version": 1, "kind": "reservation", "operation": key, "subject": subject,
                    "package_sha256": package_sha256, "package_bytes": package_bytes,
                    "reservation": key[:32], "policy_sha256": policy, "anchor": anchor}
        record = expected | {"authority": authority, "management_sha": authority["management_sha"]}
        existing = self.read(key, "reservation")
        if existing is None:
            created = self.create(key, "reservation", record)
            if created:
                # Re-read protection immediately before returning one create authority.
                require(self.protection() == policy, "archive-protection-changed")
                return record, "create"
            existing = self.read(key, "reservation")
        require(existing is not None and all(existing.get(k) == v for k, v in expected.items())
                and type(existing.get("authority")) is dict
                and existing.get("management_sha") == existing["authority"].get("management_sha"),
                "archive-reservation-conflict")
        return existing, "verify-existing"

    def finish(self, reservation, storage):
        self.protection()
        key = reservation["operation"]
        require(self.read(key, "reservation") == reservation, "archive-reservation-changed")
        require(storage.get("package_sha256") == reservation["package_sha256"]
                and storage.get("reservation") == reservation["reservation"]
                and storage.get("retention_mode") == "COMPLIANCE"
                and type(storage.get("version_id")) is str and storage["version_id"] not in {"", "null"},
                "archive-storage-receipt")
        record = {"version": 1, "kind": "receipt", "operation": key,
                  "anchor": reservation["anchor"],
                  "management_sha": reservation["management_sha"],
                  "reservation_sha256": digest(reservation), "storage": storage}
        existing = self.read(key, "receipt")
        if existing is None and self.create(key, "receipt", record):
            return record
        existing = self.read(key, "receipt")
        if existing != record:
            # Retention may legitimately grow on the same immutable version.
            # Keep the original receipt; every other binding must remain exact.
            try:
                original_until = existing["storage"]["retain_until"]
                before = datetime.fromisoformat(original_until)
                after = datetime.fromisoformat(storage["retain_until"])
            except (KeyError, TypeError, ValueError):
                raise ControlError("archive-receipt-conflict") from None
            require(before.tzinfo is not None and after.tzinfo is not None and after >= before
                    and existing == record | {"storage": storage | {"retain_until": original_until}},
                    "archive-receipt-conflict")
        return existing

    def verify_denials(self, record):
        """Prove protection on this actual claim before its first object PUT.

        A successful mutation or ambiguous/non-rule error blocks the upload.
        Neither a second tag namespace nor a disposable S3 object is needed.
        """
        self.protection()
        key = record["operation"]
        require(self.read(key, "reservation") == record, "archive-negative-original-claim")
        path = self.base + "/git/refs/tags/" + PREFIX + key + "/reservation"
        for method, data in (("PATCH", {"sha": record["anchor"]["commit_sha"], "force": True}), ("DELETE", None)):
            status, result = self.api.request(method, path, data)
            require(status == 422 and "rule violations" in str(result.get("message", "")).lower(),
                    "archive-native-ref-denial-unproven")
            require(self.read(key, "reservation") == record, "archive-native-ref-mutated")
        self.protection()


def deliver(reservations, storage, store, subject, authority, build, validate, now):
    """One durable claim; replay restores before touching ephemeral producers.

    The protected consumer supplies profile-specific construction and validation.
    Neither an expired artifact nor a missing object can reset this operation.
    """
    policy = reservations.protection()
    key = operation(subject)
    existing = reservations.read(key, "reservation")
    if existing is None:
        package = build()
        require(type(package) is bytes, "archive-package-bytes")
        validate(package)
        existing, mode = reservations.claim(subject, hashlib.sha256(package).hexdigest(), len(package), authority)
    else:
        # Reuse claim validation without rebuilding historical payloads.
        existing, mode = reservations.claim(subject, existing.get("package_sha256"), existing.get("package_bytes"), authority)
    require(existing["policy_sha256"] == policy, "archive-protection-changed")
    arguments = dict(repository=reservations.repository, promotion=subject["promotion"],
                     head=subject["head_sha"], expected_digest=existing["package_sha256"],
                     reservation=existing["reservation"], now=now)
    if mode == "create":
        reservations.verify_denials(existing)
        result = storage.archive(store, package, operation="create", **arguments)
    else:
        receipt = reservations.read(key, "receipt")
        if receipt is not None:
            require(receipt.get("reservation_sha256") == digest(existing)
                    and receipt.get("anchor") == existing["anchor"], "archive-receipt-reservation")
        version = receipt["storage"]["version_id"] if receipt else None
        package, result = storage.restore(store, expected_bytes=existing["package_bytes"],
                                          expected_version=version, **arguments)
        validate(package)
    receipt = reservations.finish(existing, result)
    return package, receipt, mode
