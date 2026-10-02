"""Bounded read-only GitHub JSON transport; Linux/POSIX main-thread execution only."""

import argparse
from contextlib import contextmanager
import json
import math
import os
import signal
import time
import urllib.request


REPOSITORY = "lightning-it/.github"
ORIGIN = "https://api.github.com"
ROUTES = {"pull": ("pulls", "number"), "run": ("actions/runs", "id"),
          "check": ("check-runs", "id")}


class ReadFailure(RuntimeError):
    """Source-owned invariant identifier, never external response text."""


def require(condition, reason):
    if not condition:
        raise ReadFailure(reason)


def pairs(items):
    result = {}
    for key, value in items:
        require(key not in result, "duplicate-json-key")
        result[key] = value
    return result


def constant(value):
    raise ReadFailure("nonstandard-json-number")


def number(raw):
    value = float(raw)
    require(math.isfinite(value), "nonstandard-json-number")
    return value


@contextmanager
def deadline(expires):
    require(all(hasattr(signal, name) for name in (
        "SIGALRM", "ITIMER_REAL", "getitimer", "setitimer")), "deadline-unavailable")
    require(signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0), "deadline-in-use")
    def expired(signum, frame):
        raise ReadFailure("time-budget-exhausted")
    try:
        previous = signal.signal(signal.SIGALRM, expired)
    except (ValueError, OSError):
        raise ReadFailure("deadline-unavailable") from None
    try:
        remaining = expires - time.monotonic()
        require(remaining > 0, "time-budget-exhausted")
        signal.setitimer(signal.ITIMER_REAL, remaining)
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ReadFailure("redirect-refused")


class GitHubReader:
    """No retries, pagination, arbitrary endpoints, writes, or authority decisions."""
    def __init__(self, max_seconds=90, max_requests=100, max_bytes=2 * 1024 * 1024):
        for value, maximum in ((max_seconds, 90), (max_requests, 100),
                               (max_bytes, 2 * 1024 * 1024)):
            require(type(value) is int and 1 <= value <= maximum, "invalid-budget")
        self.expires = time.monotonic() + max_seconds
        self.max_requests = max_requests
        self.max_bytes = max_bytes
        self.requests = 0
        # Never inherit a proxy endpoint from the caller's environment.
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def read(self, resource, identifier):
        require(type(resource) is str and resource in ROUTES, "unsupported-resource")
        require(type(identifier) is int and 1 <= identifier <= 2 ** 63 - 1, "invalid-identifier")
        require(self.requests < self.max_requests, "request-budget-exhausted")
        token = os.environ.get("GH_TOKEN", "")
        require(bool(token.strip()), "token-missing")
        route, identity = ROUTES[resource]
        request = urllib.request.Request(
            f"{ORIGIN}/repos/{REPOSITORY}/{route}/{identifier}", method="GET",
            headers={"Authorization": "Bearer " + token,
                     "Accept": "application/vnd.github+json",
                     "X-GitHub-Api-Version": "2022-11-28"})
        try:
            with deadline(self.expires):
                remaining = self.expires - time.monotonic()
                require(remaining > 0, "time-budget-exhausted")
                self.requests += 1
                with self.opener.open(request, timeout=min(10, remaining)) as response:
                    require(response.status == 200, "unexpected-http-status")
                    raw = response.read(self.max_bytes + 1)
                require(len(raw) <= self.max_bytes, "response-byte-limit")
                payload = json.loads(raw, object_pairs_hook=pairs, parse_constant=constant,
                                     parse_float=number)
                require(type(payload) is dict and type(payload.get(identity)) is int
                        and payload[identity] == identifier, "response-identity")
                require(time.monotonic() < self.expires, "time-budget-exhausted")
        except ReadFailure:
            raise
        except Exception:
            # Includes http.client.IncompleteRead and other ordinary transport
            # or JSON failures. BaseException control signals remain untouched.
            raise ReadFailure("read-failed") from None
        require(time.monotonic() < self.expires, "time-budget-exhausted")
        return payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("resource", choices=tuple(ROUTES))
    parser.add_argument("identifier", type=int)
    args = parser.parse_args()
    try:
        reader = GitHubReader()
        payload = reader.read(args.resource, args.identifier)
        result = {"schema": "li219-readonly-response/v1", "authority": "none", "writes": 0,
                  "repository": REPOSITORY, "resource": args.resource,
                  "identifier": args.identifier, "api_requests": reader.requests, "data": payload}
        # Serialization failures must pass through the same sanitized boundary.
        encoded = json.dumps(result, sort_keys=True, allow_nan=False)
    except Exception as error:
        reason = str(error) if isinstance(error, ReadFailure) else "read-failed"
        print(json.dumps({"schema": "li219-readonly-rejection/v1", "authority": "none",
                          "writes": 0, "reason": reason}, sort_keys=True))
        return 1
    print(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
