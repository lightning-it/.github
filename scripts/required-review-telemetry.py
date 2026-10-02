"""Offline advisory summaries of bounded LI-219 observation JSON; no network or writes."""

import argparse
import json
import math
from pathlib import Path
import re
import sys


MAX_BYTES = 8 * 1024 * 1024
MAX_SAMPLES = 10000
MAX_VALUE = 10 ** 12
METRICS = ("producer_job_seconds", "request_to_review_seconds",
           "review_to_neutral_seconds", "neutral_to_observer_seconds",
           "request_to_observer_seconds")
FAILURE = "native_failure_with_ready_evidence"


class InvalidTelemetry(ValueError):
    """Only fixed, source-owned identifiers may be exposed to the CLI."""


def require(condition, reason):
    if not condition:
        raise InvalidTelemetry(reason)


def pairs(items):
    result = {}
    for key, value in items:
        require(key not in result, "duplicate-json-key")
        result[key] = value
    return result


def constant(value):
    raise InvalidTelemetry("nonstandard-json-number")


def normalize(item):
    require(type(item) is dict, "observation-shape")
    require(item.get("schema") == "li219-shadow-observation/v1"
            and item.get("authority") == "none"
            and type(item.get("writes")) is int and item["writes"] == 0,
            "observation-schema")
    for field in ("operation_key", "binding_digest"):
        require(type(item.get(field)) is str
                and re.fullmatch(r"[0-9a-f]{64}", item[field]), "operation-binding")
    require(type(item.get("observed_at")) is int
            and 0 <= item["observed_at"] <= MAX_VALUE, "observation-time")
    metrics = item.get("metrics")
    require(type(metrics) is dict and type(metrics.get(FAILURE)) is bool, "metrics-shape")
    values = {}
    for name in METRICS:
        value = metrics.get(name)
        require(value is None or (type(value) in (int, float)
                and 0 <= value <= MAX_VALUE), "metrics-value")
        # Missing and explicit null remain unknown; canonical numeric values
        # make equal-time tie-breaking independent of integer/float spelling.
        values[name] = None if value is None else float(value)
    return {"operation_key": item["operation_key"], "binding_digest": item["binding_digest"],
            "observed_at": item["observed_at"], "metrics": values,
            "native_failure": metrics[FAILURE]}


def summarize(observations):
    require(type(observations) is list and len(observations) <= MAX_SAMPLES, "sample-limit")
    unique = {}
    failures = set()
    for raw in observations:
        item = normalize(raw)
        key = item["operation_key"]
        if item["native_failure"]:
            failures.add(key)
        rank = (item["observed_at"], json.dumps(item["metrics"], sort_keys=True))
        if key in unique:
            previous_rank, previous = unique[key]
            require(previous["binding_digest"] == item["binding_digest"], "binding-drift")
            if rank >= previous_rank:
                continue
        unique[key] = (rank, item)
    statistics = {}
    for name in METRICS:
        values = sorted(item["metrics"][name] for _, item in unique.values()
                        if item["metrics"][name] is not None)
        statistics[name] = {
            "observed_samples": len(values),
            "median": None if not values else
                (values[(len(values) - 1) // 2] + values[len(values) // 2]) / 2,
            "p95": None if not values else values[math.ceil(len(values) * .95) - 1],
        }
    return {"schema": "li219-offline-telemetry/v1", "authority": "none", "writes": 0,
            "unique_operations": len(unique), "statistics": statistics,
            "native_failure_with_ready_evidence_count": len(failures),
            "candidate_rate": len(failures) / len(unique) if unique else None,
            "measured_false_negative_rate": None,
            "cohort": "provided-advisory-observations-only"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="JSON array file, or - for standard input")
    args = parser.parse_args()
    try:
        if args.input == "-":
            raw = sys.stdin.buffer.read(MAX_BYTES + 1)
        else:
            with Path(args.input).open("rb") as source:
                raw = source.read(MAX_BYTES + 1)
        require(len(raw) <= MAX_BYTES, "input-byte-limit")
        result = summarize(json.loads(raw, object_pairs_hook=pairs, parse_constant=constant))
    except Exception as error:
        # Never print an external exception message, input, path, or traceback.
        reason = str(error) if isinstance(error, InvalidTelemetry) else "invalid-input"
        result = {"schema": "li219-offline-telemetry-rejection/v1",
                  "authority": "none", "writes": 0, "reason": reason}
        print(json.dumps(result, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
