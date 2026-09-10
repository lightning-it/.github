#!/usr/bin/env python3
"""Build a bounded inventory from two stable local page-file reads."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
import sys
import time
from pathlib import Path
from typing import Any


JSON = dict[str, Any]
SHA256 = re.compile(r"^[0-9a-f]{64}$")
SAFE_CURSOR = re.compile(r"^[ -~]{1,512}$")
KINDS = {"history", "reservations", "runs"}
HARD_MAX_BYTES, HARD_MAX_PAGES, HARD_MAX_RECORDS, HARD_MAX_ELAPSED_MS = (
    64 * 1024 * 1024, 1000, 10000, 300000
)


class ContractError(ValueError):
    """A fail-closed local inventory contract violation."""


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ContractError(reason)


def exact_keys(value: Any, expected: set[str], label: str) -> JSON:
    require(type(value) is dict, f"{label}-not-object")
    require(set(value) == expected, f"{label}-keys")
    return value


def integer(
    value: Any, label: str, minimum: int = 0, maximum: int | None = None
) -> int:
    require(type(value) is int and value >= minimum, label)
    if maximum is not None:
        require(value <= maximum, f"{label}-too-large")
    return value


def canonical(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def digest(value: Any) -> str:
    return digest_bytes(canonical(value))


def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> JSON:
    value: JSON = {}
    for key, item in pairs:
        require(key not in value, "page-duplicate-key")
        value[key] = item
    return value


def reject_nonstandard_constant(_: str) -> None:
    raise ContractError("page-not-canonical-json")


def load_json(path_text: str, maximum_bytes: int) -> tuple[Any, bytes]:
    path = Path(path_text)
    metadata = path.lstat()
    require(stat.S_ISREG(metadata.st_mode), "page-not-regular")
    require(metadata.st_size <= maximum_bytes, "page-byte-limit")
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise ContractError("page-read-failed") from error
    require(len(raw) == metadata.st_size, "page-size-drift")
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_nonstandard_constant,
        )
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise ContractError("page-not-json") from error
    require(raw == canonical(value), "page-not-canonical-json")
    return value, raw


def cursor(value: Any, label: str) -> str | None:
    if value is None:
        return None
    require(type(value) is str and SAFE_CURSOR.fullmatch(value), label)
    return value


def record_identity(kind: str, record: Any) -> Any:
    require(type(record) is dict, "page-record-not-object")
    if kind == "history":
        identity = record.get("pr_number")
        require(type(identity) is int and identity > 0, "history-record-identity")
        return identity
    if kind == "runs":
        run_id = record.get("run_id")
        attempt = record.get("attempt")
        require(type(run_id) is int and run_id > 0, "run-record-identity")
        require(type(attempt) is int and attempt > 0, "run-attempt-identity")
        return run_id, attempt
    check_run_id = record.get("check_run_id")
    external_id = record.get("external_id")
    require(type(check_run_id) is int and check_run_id > 0, "reservation-record-identity")
    require(type(external_id) is str and external_id, "reservation-external-identity")
    return check_run_id, external_id


def normalize_read(kind: str, read_value: Any, *, maximum_bytes: int,
                   maximum_pages: int, maximum_records: int,
                   deadline: float) -> tuple[list[JSON], list[JSON], int]:
    read = exact_keys(read_value, {"complete", "pages"}, "inventory-read")
    require(read["complete"] is True, "inventory-read-incomplete")
    pages_value = read["pages"]
    require(type(pages_value) is list, "inventory-pages-not-list")
    require(len(pages_value) <= maximum_pages, "inventory-page-limit")
    pages: list[JSON] = []
    total_bytes = 0
    for page_value in pages_value:
        require(time.monotonic() <= deadline, "inventory-deadline")
        page = exact_keys(page_value, {"cursor", "next_cursor", "number", "path"}, "inventory-page")
        number = integer(page["number"], "inventory-page-number", minimum=1)
        remaining = maximum_bytes - total_bytes
        require(remaining >= 0, "inventory-byte-limit")
        records, raw = load_json(page["path"], remaining)
        require(type(records) is list, "page-not-array")
        total_bytes += len(raw)
        require(total_bytes <= maximum_bytes, "inventory-byte-limit")
        pages.append(
            {
                "cursor": cursor(page["cursor"], "inventory-page-cursor"),
                "next_cursor": cursor(page["next_cursor"], "inventory-page-next-cursor"),
                "number": number,
                "raw_sha256": digest_bytes(raw),
                "records": records,
                "response_bytes": len(raw),
            }
        )
    pages.sort(key=lambda item: item["number"])
    require([page["number"] for page in pages] == list(range(1, len(pages) + 1)),
            "inventory-page-sequence")
    if pages:
        require(pages[0]["cursor"] is None, "inventory-first-cursor")
        require(pages[-1]["next_cursor"] is None, "inventory-last-cursor")
        for left, right in zip(pages, pages[1:]):
            require(left["next_cursor"] is not None, "inventory-cursor-truncated")
            require(left["next_cursor"] == right["cursor"], "inventory-cursor-chain")
    records = [record for page in pages for record in page["records"]]
    require(len(records) <= maximum_records, "inventory-record-limit")
    identities: set[Any] = set()
    for record in records:
        identity = record_identity(kind, record)
        require(identity not in identities, "inventory-record-duplicate")
        identities.add(identity)
    normalized_records = sorted(records, key=canonical)
    return normalized_records, pages, total_bytes


def collect(manifest_value: Any, *, kind: str, maximum_bytes: int,
            maximum_elapsed_ms: int, maximum_pages: int,
            maximum_records: int) -> JSON:
    require(kind in KINDS, "inventory-kind")
    integer(maximum_bytes, "maximum-bytes", minimum=1, maximum=HARD_MAX_BYTES)
    integer(maximum_elapsed_ms, "maximum-elapsed-ms", minimum=1,
            maximum=HARD_MAX_ELAPSED_MS)
    integer(maximum_pages, "maximum-pages", minimum=1, maximum=HARD_MAX_PAGES)
    integer(maximum_records, "maximum-records", minimum=1, maximum=HARD_MAX_RECORDS)
    manifest = exact_keys(manifest_value, {"reads", "source"}, "manifest")
    reads = manifest["reads"]
    require(type(reads) is list and len(reads) == 2, "stable-read-count")
    started = time.monotonic()
    deadline = started + (maximum_elapsed_ms / 1000)
    normalized_reads = []
    transport_reads = []
    for read_value in reads:
        records, pages, response_bytes = normalize_read(
            kind, read_value, maximum_bytes=maximum_bytes,
            maximum_pages=maximum_pages, maximum_records=maximum_records,
            deadline=deadline)
        normalized_reads.append(records)
        transport_reads.append((pages, response_bytes))
    require(normalized_reads[0] == normalized_reads[1], "inventory-unstable")
    elapsed_ms = int((time.monotonic() - started) * 1000)
    require(elapsed_ms <= maximum_elapsed_ms, "inventory-deadline")
    pages, response_bytes = transport_reads[0]
    source = manifest["source"]
    require(type(source) is dict, "inventory-source-not-object")
    semantic = {"records": normalized_reads[0], "source": source}
    return {
        "collector": "release-promotion-inventory-v1",
        "complete": True,
        "elapsed_ms": elapsed_ms,
        "page_count": len(pages),
        "pages": pages,
        "read_count": 2,
        "record_count": len(normalized_reads[0]),
        "response_bytes": response_bytes,
        "semantic_sha256": digest(semantic),
        "source": source,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--kind", choices=sorted(KINDS), required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--max-bytes", required=True, type=int)
    parser.add_argument("--max-elapsed-ms", required=True, type=int)
    parser.add_argument("--max-pages", required=True, type=int)
    parser.add_argument("--max-records", required=True, type=int)
    arguments = parser.parse_args(argv)
    try:
        manifest, _ = load_json(arguments.manifest, 8 * 1024 * 1024)
        result = collect(manifest, kind=arguments.kind,
                         maximum_bytes=arguments.max_bytes,
                         maximum_elapsed_ms=arguments.max_elapsed_ms,
                         maximum_pages=arguments.max_pages,
                         maximum_records=arguments.max_records)
    except (ContractError, OSError) as error:
        result = {"disposition": "blocked", "reason": str(error), "schema_version": 1}
        sys.stdout.buffer.write(canonical(result))
        return 1
    sys.stdout.buffer.write(canonical(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
