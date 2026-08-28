#!/usr/bin/env python3
"""Validate the terminal state of one bound Release-App producer snapshot."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any


MAX_PAYLOAD_BYTES = 1_000_000


class VerificationError(RuntimeError):
    """The producer snapshot violates the protected workflow contract."""


def verify_producer_state(payload: Any, *, evidence_ready: bool) -> None:
    if not isinstance(payload, dict):
        raise VerificationError("producer payload must be an object")

    status = payload.get("status")
    conclusion = payload.get("conclusion")
    if status == "completed" and conclusion == "success":
        return
    if evidence_ready and status == "in_progress" and conclusion is None:
        return
    raise VerificationError(
        "producer must be completed/success, or evidence-bound "
        "in_progress/null"
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--evidence-ready",
        choices=("false", "true"),
        required=True,
    )
    return parser.parse_args(argv)


def read_payload() -> Any:
    raw = sys.stdin.buffer.read(MAX_PAYLOAD_BYTES + 1)
    if len(raw) > MAX_PAYLOAD_BYTES:
        raise VerificationError("producer payload is too large")
    try:
        return json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise VerificationError("producer payload must be valid JSON") from error


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        verify_producer_state(
            read_payload(), evidence_ready=args.evidence_ready == "true"
        )
    except VerificationError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
