"""Bounded UTF-8 JSON decoding for the LI-219 journal; no I/O or authority.

The future journal adapter validates the decoded schema separately. Container
depth is bounded before the recursive decoder runs; strings do not add depth.
"""

import json


MAX_BYTES = 1024 * 1024
MAX_DEPTH = 32


class JournalRejected(ValueError):
    """A fixed source-owned invariant identifier, never external input text."""


def pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise JournalRejected("duplicate-json-key")
        result[key] = value
    return result


def no_number(value):
    raise JournalRejected("noninteger-json-number")


def bounded_depth(text):
    """Scan iteratively; json.loads remains responsible for JSON grammar."""
    depth = 0
    quoted = False
    escaped = False
    for character in text:
        if quoted:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                quoted = False
        elif character == '"':
            quoted = True
        elif character in "[{":
            depth += 1
            if depth > MAX_DEPTH:
                raise JournalRejected("journal-depth-limit")
        elif character in "]}":
            depth -= 1
            if depth < 0:
                raise JournalRejected("journal-json")


def parsed(raw):
    """Decode at most 1 MiB of UTF-8 JSON with at most 32 nested containers."""
    if type(raw) is not bytes or len(raw) > MAX_BYTES:
        raise JournalRejected("journal-byte-limit")
    try:
        text = raw.decode("utf-8")
        bounded_depth(text)
        return json.loads(text, object_pairs_hook=pairs, parse_float=no_number,
                          parse_constant=no_number)
    except JournalRejected:
        raise
    except (ValueError, UnicodeError, RecursionError):
        raise JournalRejected("journal-json") from None
