# Read-only event adapter and bounded shadow sweeper

LI-228 is owner-authorized split C of LI-219. It integrates the accepted pure
state contract, LI-226 telemetry and LI-227 bounded transport. It does not
resurrect the closed PR #722, transfer required-check authority or implement a
writer. Every output declares `authority: none` and `writes: 0`.

## Default-off execution boundary

The committed `.lit/required-review-shadow.json` remains `lifecycle: inactive`.
An inactive CLI invocation performs zero API requests, does not read the event
file and does not instantiate a credential-bearing reader. Both workflows also
require the repository variable `LI219_EVENT_SHADOW` to equal `true`; the active
CLI independently requires that same value. This change neither sets the
variable nor changes the protected policy to `shadow`. Activation requires a
separate decision and protected change. Unknown lifecycle values, including a
writer mode, reject.

The workflow-run observer and six-hour scheduled sweeper check out the immutable
default-branch workflow SHA, never a PR head. Their existing GitHub token has
only Actions, checks, contents and pull-request read permissions. Their pinned
Devtools container has read-only source/event mounts, no Docker socket, dropped
capabilities, a non-root user and explicit network access solely for these
reads. Nothing requests reviews, retries a workflow, creates credentials,
publishes a check or persists an evidence package. The required production
workflow and its synchronous runner wait remain unchanged.

The explicit CLI is:

```text
python3 scripts/required-review-shadow.py --event workflow_run --event-path EVENT.json
python3 scripts/required-review-shadow.py --event schedule --event-path EVENT.json
```

Do not enable the feature to run tests. Deterministic fixtures exercise the
shadow branch entirely offline in the pinned Devtools image.

## Read provenance and fail-closed decisions

The fixed-repository API adapter allows only enumerated REST GET routes and one
source-owned GraphQL query for review bodies/edit times and resolved threads.
It accepts no arbitrary URL, query, mutation or repository selector. It reuses
LI-227's private bounded I/O kernel, including redirect/proxy refusal, active
POSIX absolute transport deadline, truncated-body checks and sanitized errors.
The public LI-227 single-object CLI and route contract are unchanged.

Two uncached authoritative snapshots bind the producer run/attempt, exact PR
head/base, protected develop tip, controller ancestry, required-workflow rule,
actor, admission run, native neutral result, current-head Copilot review,
complete resolved threads and critical job steps. Webhook identity fields must
match a fresh native run. Review bodies and edit timestamps must agree across
REST/GraphQL; unresolved findings, unavailable/empty content, post-evidence edits, stale
heads, reruns, pagination gaps, duplicate IDs and snapshot drift reject. A
missing request marker is valid for a pre-existing review; corresponding
request-based latency stays null. Existing terminal native reservations are
observed, never overwritten. Later native failure observations remain visible
through LI-226's failure-OR deduplication even when earlier latency is retained.

The completed `workflow_run` path requires producer `completed/success` on the
dispatch read and both independent observation reads; a regression to queued or
in-progress rejects. Job visibility may still lag by at least 180 seconds:
successful critical job steps remain usable while their enclosing job is not
yet terminal. Run completion and job visibility are validated separately.

Neutral summaries accept exactly the protected producer's eight legacy-v6 keys:
`schema`, `base_sha`, `head_sha`, `controller_sha`, `pull_request_number`,
`producer_run_id`, `review_path` and `run_url`. Schema is integer `4`, PR/run IDs
are positive integers, and `review_path` must be exactly
`applicable Copilot or governed automation exemption`. Missing/extra keys,
numeric floats, booleans, alternate paths and expanded summaries reject.
Supporting another producer schema requires a separate verified contract change.

Both observer and sweeper require the admission run's exact native display title
`Protected current revision PR #<number> <action> <head>`, with a positive integer
PR number and one of the protected workflow's `opened`, `synchronize`, `reopened`,
`ready_for_review` or `edited` actions. This is the native workflow run-name
binding, not the editable pull-request title. Independently, the same run read
must include exactly one numeric `pull_requests` association matching the PR
number, base/head SHA, base/head ref and both repository IDs/API URLs. Missing,
empty, ambiguous or mismatched associations reject; there is no title-only
fallback. These checks add no requests and preserve the 99-request sweep bound.
The admission helper validates both expected SHAs as exactly 40 lowercase hex
characters and the expected head ref before reading the run. Head refs use a
conservative 1–255 character ASCII subset: an initial letter, digit or underscore,
followed by letters, digits, underscores, dots, hyphens or slashes. Empty path
components, dot-prefixed components, `.lock` suffixes, `..`, a final dot and the
exact reserved name `HEAD` reject; lowercase and mixed-case variants remain valid.
This also excludes controls, whitespace, `@{` and Git's special ref characters;
no trimming, coercion or normalization is performed.

Overview finding counts and recommendations may be historical after resolution;
they are not an additional rejection gate. As in the native v6 producer, live
thread resolution is authoritative. Substantive content, unavailable-review
markers, REST/GraphQL agreement and post-evidence edit checks remain mandatory.

The pure state contract supplies a deterministic operation key/evidence digest
and permits only monotonic job visibility. No durable CAS or exactly-once
delivery is claimed: repeated events yield the same advisory decision, with
offline telemetry deduplication. `would_finalize: success` describes a state
simulation, never authorization to publish success.

## Bounded sweeper and explicit legacy limits

The sweeper inventories only current heads of open develop PRs (at most 14).
The worst case uses 99 requests: one PR inventory page plus 14 PRs times three
check inventory pages and four revalidation reads. A fifteenth PR rejects
immediately after PR inventory, before per-PR reads; the transport's existing
100-request cap still applies.
For an expired pending v3 reservation it binds check app, PR, head, base and
admission run/attempt/actor/repository, then independently re-reads the check,
current PR and admission run. Drift rejects the whole result. Terminal checks
are never expiry candidates. Its advisory expiry results include reservation
and admission digests; it cannot finalize anything.

The sweeper requires head and base SHAs to be strings containing exactly 40
lowercase hexadecimal characters before reading check inventories or selecting
reservations. Missing or malformed base evidence rejects even when there are no
reservations; a valid base with no matching reservation yields no expiry.

Both paths select the exact PR/base/head reservation scope before uniqueness
and provenance validation. Commit inventories can contain terminal reservations
for another PR or an older base; these are outside the selected scope, never
used as authorization and never emitted as this PR's expiry candidates. Exact
scope duplicates and forged check provenance still reject. The native protected
verifier retains ownership of its additional foreign-reservation checks.

Legacy v3 reservations do not preserve the historical controller/ruleset
binding required by a future protected writer. The sweep therefore explicitly
reports `historical_controller_binding: unavailable-in-legacy-v3` and
`complete_global_inventory: false`. Superseded heads, closed PRs and orphaned
reservations are not covered. A future writer requires separately authorized
admission/store ownership, durable inventory, CAS and an authority-migration
decision; this adapter is not that migration.

Per invocation the shared reader caps transport at 90 seconds, 100 requests and
2 MiB per response. REST lists are bounded to three pages of 100, with duplicate
and completeness checks; GraphQL connections exceeding 100 reject instead of
claiming complete evidence. Exhaustion produces a structured rejection, no
partial success and no retry. These intentionally conservative limits may
reject valid large PR histories; that is not a reason to bypass them.

## Verification and measurements

`test_required_review_shadow.py` exercises real normalization with deterministic
GitHub fixtures: a 180-second finalization delay, duplicate delivery, manual
pre-existing review, stale/out-of-order and edited evidence, reverse job state,
pagination/identity drift, expired reservations, bounded API routes, transport
failure sanitization and inactive zero-request behavior. The accepted state,
telemetry and transport regression suites run alongside it.

Observations expose request→review, review→neutral, neutral→observer and
reservation→observer seconds plus known terminal job minutes. Skipped jobs
cost zero; unfinished jobs and missing request markers remain unknown rather
than invented zeroes. These are shadow measurements, not demonstrated runner
savings. Production performance acceptance and LI-219 completion remain open
until a separately approved rollout supplies native before/after evidence.
