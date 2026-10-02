# Read-only review transport

`scripts/required-review-transport.py` provides an independent standard-library
`GitHubReader` and explicit CLI. It reads exactly one pull request, Actions run,
or check-run object from `https://api.github.com/repos/lightning-it/.github`.
It has no dependency on the closed PR #722 observer, policy or workflows.

The CLI arguments are `pull`, `run`, or `check`, followed by a positive integer
identifier. The caller supplies an existing `GH_TOKEN` with only the necessary
read access in an explicitly network-enabled execution environment. The script
never creates, mints or prints credentials. Do not change the default offline
Devtools boundary or install a token in CI merely to use this component.
All repository tests run mocked and offline in the pinned Devtools image.

The importable API is `GitHubReader(...).read(resource, identifier)`. Arbitrary
URLs, repository selectors, paths, query strings, methods and GraphQL are not
accepted. Requests are GET-only, environment proxies are disabled, and every
redirect is rejected. The response must be HTTP 200 and its numeric `number`
(pull) or `id` (run/check) must match the request. This is transport-level
identity only, **not** provenance, review, completeness or merge authorization.

Per reader instance, defaults/hard maxima are 90 seconds, 100 requests and 2 MiB
per response. Constructor arguments can reduce these positive integer budgets.
No retry or pagination is implemented. A CLI invocation performs one request;
an importer can reuse a reader for multiple requests within the same budget.

Linux/POSIX main-thread execution is mandatory. An absolute process real-time
signal timer actively interrupts connect, continuously progressing body reads
and JSON parsing; it is not merely a socket idle timeout. Missing signal
support, a worker thread, a blocked SIGALRM, a competing active timer or exhausted
budget fails closed before network access. The caller's signal mask is never
changed. The previous signal handler is restored and the
timer disarmed on success, ordinary errors and control-signal propagation.
The expiration handler also disarms and restores state before raising, including
when the timer interrupts the normal cleanup itself.
The caller must not share the process timer or signal handler while a read is
in progress. This API is deliberately not a concurrent transport.

Malformed/truncated responses, including `http.client.IncompleteRead`, become
source-owned `ReadFailure` identifiers. A known Content-Length must be completely
consumed before the response is closed; a short bounded read cannot pass merely
because its prefix is valid JSON. Duplicate JSON keys, non-finite numbers,
response size overflow and identity drift reject. Ordinary exceptions at the
CLI boundary produce `li219-readonly-rejection/v1`, exit 1, no traceback and no
external error body/path. `BaseException` control signals remain unmasked.
Successful JSON contains the requested response, so callers must handle that
data with the same confidentiality as the source repository. It never contains
the request token added by this transport.

All output states `authority: none`, `writes: 0`. Nothing publishes checks,
requests reviews, enables an observer, changes a ruleset, or activates a
workflow. LI-227 is split B of the owner-approved LI-219 decomposition, begun
only after LI-226's protected merge. Observer integration belongs to separate
LI-228; protected writers and production measurements remain unimplemented.

LI-228's separate `required-review-shadow-api.py` reuses the private bounded
`_read_json` I/O kernel after selecting its own closed read route or fixed
GraphQL query. This does not expand the public single-object CLI above. See
[the default-off integration boundary](required-review-shadow.md); neither
module implements a writer or accepts arbitrary caller-supplied network routes.
