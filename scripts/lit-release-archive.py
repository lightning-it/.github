#!/usr/bin/env python3
"""Store exact release-package bytes in Hetzner S3; never authorize a release."""
from __future__ import annotations

import argparse
import base64
import calendar
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

MAX_PACKAGE_BYTES = 50 * 1024 * 1024
MAX_METADATA_BYTES = 65536
ENDPOINTS = {"fsn1.your-objectstorage.com", "nbg1.your-objectstorage.com", "hel1.your-objectstorage.com"}
SHA256 = re.compile(r"[0-9a-f]{64}")
SHA = re.compile(r"[0-9a-f]{40}")
REPOSITORY = re.compile(r"lightning-it/(?:\.github|[A-Za-z0-9_-]+)")


class ArchiveError(ValueError):
    """Safe category only: no credentials, endpoint, payload or resource locator."""


class PreconditionFailed(ArchiveError):
    pass


def require(condition: bool, category: str) -> None:
    if not condition:
        raise ArchiveError(category)


@dataclass(frozen=True, repr=False)
class Identity:
    access_key: str
    secret_key: str


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ArchiveError("redirect-prohibited")


class Store:
    def __init__(self, endpoint: str, bucket: str, identities: dict[str, Identity], sse_key: str):
        require(endpoint in ENDPOINTS, "endpoint-not-approved")
        require(re.fullmatch(r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]", bucket) is not None, "bucket-shape")
        require(set(identities) == {"writer", "reader", "reviewer"}, "role-set")
        require(all(isinstance(item.access_key, str) and re.fullmatch(r"[A-Za-z0-9_-]+", item.access_key) is not None
                    and isinstance(item.secret_key, str) and bool(item.secret_key) and not any(character.isspace() for character in item.secret_key)
                    for item in identities.values()), "role-credentials-shape")
        require(len({item.access_key for item in identities.values()}) == 3, "roles-not-separated")
        try:
            raw = base64.b64decode(sse_key, validate=True)
        except (ValueError, TypeError):
            raise ArchiveError("encryption-key-shape") from None
        require(len(raw) == 32, "encryption-key-shape")
        self.endpoint, self.bucket, self.identities = endpoint, bucket, identities
        self.region = endpoint.split(".")[0]
        self.encryption = {
            "x-amz-server-side-encryption-customer-algorithm": "AES256",
            "x-amz-server-side-encryption-customer-key": sse_key,
            "x-amz-server-side-encryption-customer-key-md5": base64.b64encode(hashlib.md5(raw).digest()).decode(),
        }
        self.opener = urllib.request.build_opener(NoRedirect())

    def request(self, role, method, key, *, query=None, headers=None, body=b"", response_limit=MAX_METADATA_BYTES):
        identity = self.identities[role]
        host = self.bucket + "." + self.endpoint
        uri = "/" + urllib.parse.quote(key, safe="/-_.~")
        query = "&".join(urllib.parse.quote(k, safe="-_.~") + "=" + urllib.parse.quote(v, safe="-_.~") for k, v in sorted((query or {}).items()))
        now = datetime.now(timezone.utc)
        stamp, day = now.strftime("%Y%m%dT%H%M%SZ"), now.strftime("%Y%m%d")
        digest = hashlib.sha256(body).hexdigest()
        hdr = {k.lower(): v.strip() for k, v in (headers or {}).items()}
        hdr.update({"host": host, "x-amz-date": stamp, "x-amz-content-sha256": digest})
        signed = ";".join(sorted(hdr))
        canonical = "\n".join([method, uri, query, "".join(k + ":" + hdr[k] + "\n" for k in sorted(hdr)), signed, digest])
        scope = day + "/" + self.region + "/s3/aws4_request"
        to_sign = "AWS4-HMAC-SHA256\n" + stamp + "\n" + scope + "\n" + hashlib.sha256(canonical.encode()).hexdigest()
        signing = ("AWS4" + identity.secret_key).encode()
        for part in (day, self.region, "s3", "aws4_request"):
            signing = hmac.new(signing, part.encode(), hashlib.sha256).digest()
        signature = hmac.new(signing, to_sign.encode(), hashlib.sha256).hexdigest()
        hdr["authorization"] = "AWS4-HMAC-SHA256 Credential=" + identity.access_key + "/" + scope + ", SignedHeaders=" + signed + ", Signature=" + signature
        request = urllib.request.Request("https://" + host + uri + ("?" + query if query else ""), data=body if method == "PUT" else None, headers=hdr, method=method)
        try:
            with self.opener.open(request, timeout=45) as response:
                payload = response.read(response_limit + 1)
                require(len(payload) <= response_limit, "response-size")
                return {k.lower(): v for k, v in response.headers.items()}, payload
        except urllib.error.HTTPError as error:
            # Response bodies may contain private resource identifiers. Do not log them.
            if error.code == 412:
                raise PreconditionFailed("object-already-exists") from None
            raise ArchiveError("provider-http-" + str(error.code)) from None
        except (OSError, TimeoutError):
            raise ArchiveError("provider-transport-failure") from None


def seven_years_after(now: datetime) -> datetime:
    require(now.tzinfo is not None and now.utcoffset() is not None, "timestamp-timezone")
    year = now.year + 7
    # Round leap-day expiry forward: a seven-year period must never be shortened.
    if now.month == 2 and now.day == 29 and not calendar.isleap(year):
        return now.replace(year=year, month=3, day=1)
    return now.replace(year=year)


def retention_date(payload: bytes) -> datetime:
    try:
        root = ET.fromstring(payload)
        values = {}
        for item in root.iter():
            tag = item.tag.rsplit("}", 1)[-1]
            if tag in {"Mode", "RetainUntilDate"}:
                require(tag not in values, "ambiguous-retention")
                values[tag] = item.text
        require(values.get("Mode") == "COMPLIANCE", "retention-mode")
        until = datetime.fromisoformat(values["RetainUntilDate"].replace("Z", "+00:00"))
        require(until.tzinfo is not None, "retention-timezone")
        return until
    except (ET.ParseError, KeyError, TypeError, AttributeError, ValueError) as error:
        if isinstance(error, ArchiveError):
            raise
        raise ArchiveError("retention-response") from None


def archive(store: Store, package: bytes, *, repository: str, promotion: int, head: str, expected_digest: str, now: datetime) -> dict:
    """Storage integrity only. The protected caller owns package provenance/approval."""
    require(REPOSITORY.fullmatch(repository) is not None, "repository-shape")
    require(type(promotion) is int and promotion > 0, "promotion-shape")
    require(SHA.fullmatch(head) is not None, "head-shape")
    require(SHA256.fullmatch(expected_digest) is not None, "package-digest-shape")
    require(0 < len(package) <= MAX_PACKAGE_BYTES, "package-size")
    require(hashlib.sha256(package).hexdigest() == expected_digest, "package-digest-mismatch")
    required_until = seven_years_after(now).replace(microsecond=0)
    key = f"runs/github-release/v1/{repository}/{promotion}/{head}/{expected_digest}.json"
    headers = {**store.encryption, "content-type": "application/json", "content-md5": base64.b64encode(hashlib.md5(package).digest()).decode(),
               "if-none-match": "*", "x-amz-object-lock-mode": "COMPLIANCE", "x-amz-object-lock-retain-until-date": required_until.strftime("%Y-%m-%dT%H:%M:%SZ")}
    try:
        response, _ = store.request("writer", "PUT", key, headers=headers, body=package)
        version = response.get("x-amz-version-id")
    except PreconditionFailed:
        # A duplicate may reuse only an exactly matching, still locked version.
        response, _ = store.request("reader", "HEAD", key, headers=store.encryption)
        version = response.get("x-amz-version-id")
        try:
            created = parsedate_to_datetime(response["last-modified"])
        except (KeyError, TypeError, ValueError):
            raise ArchiveError("object-creation-time-missing") from None
        require(created.tzinfo is not None and created <= now, "object-creation-time-invalid")
        required_until = seven_years_after(created).replace(microsecond=0)
    require(isinstance(version, str) and bool(version) and len(version) <= 1024 and version != "null", "object-version-missing")
    query = {"versionId": version}
    _, actual = store.request("reader", "GET", key, query=query, headers=store.encryption, response_limit=MAX_PACKAGE_BYTES)
    require(hashlib.sha256(actual).hexdigest() == expected_digest, "archived-digest-mismatch")
    _, locked = store.request("reviewer", "GET", key, query={**query, "retention": ""})
    until = retention_date(locked)
    require(until >= required_until and until > now, "retention-too-short")
    return {"schema_version": 1, "repository": repository, "promotion": promotion, "head_sha": head,
            "package_sha256": expected_digest, "key": key, "version_id": version,
            "retention_mode": "COMPLIANCE", "retain_until": until.isoformat(), "release_authorized": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--promotion", type=int, required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--receipt", type=Path, required=True, help="Private consumer-local receipt, never stdout")
    args = parser.parse_args()
    try:
        identities = {role: Identity(os.environ["LIT_ARCHIVE_" + role.upper() + "_ACCESS_KEY_ID"], os.environ["LIT_ARCHIVE_" + role.upper() + "_SECRET_ACCESS_KEY"]) for role in ("writer", "reader", "reviewer")}
        store = Store(os.environ["LIT_ARCHIVE_ENDPOINT"], os.environ["LIT_ARCHIVE_BUCKET"], identities, os.environ["LIT_ARCHIVE_SSE_C_KEY_B64"])
        require(args.package.is_file() and not args.package.is_symlink(), "package-regular-file")
        with args.package.open("rb") as stream:
            package = stream.read(MAX_PACKAGE_BYTES + 1)
        result = archive(store, package, repository=args.repository, promotion=args.promotion, head=args.head, expected_digest=args.expected_sha256, now=datetime.now(timezone.utc))
        # Exclusive creation prevents overwriting/following an attacker-selected receipt.
        descriptor = os.open(args.receipt, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            json.dump(result, stream, sort_keys=True)
            stream.write("\n")
    except KeyError:
        print("Archive rejected: required-private-configuration-missing")
        return 1
    except ArchiveError as error:
        print("Archive rejected: " + str(error))
        return 1
    except OSError:
        print("Archive rejected: local-file-failure")
        return 1
    print("Archive version, digest and seven-year compliance retention verified; release authorization is separate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
