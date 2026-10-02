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
REST/GraphQL; findings, unavailable/empty content, post-evidence edits, stale
heads, reruns, pagination gaps, duplicate IDs and snapshot drift reject. A
missing request marker is valid for a pre-existing review; corresponding
request-based latency stays null. Existing terminal native reservations are
observed, never overwritten. Later native failure observations remain visible
through LI-226's failure-OR deduplication even when earlier latency is retained.

The pure state contract supplies a deterministic operation key/evidence digest
and permits only monotonic job visibility. No durable CAS or exactly-once
delivery is claimed: repeated events yield the same advisory decision, with
offline telemetry deduplication. `would_finalize: success` describes a state
simulation, never authorization to publish success.

## Bounded sweeper and explicit legacy limits

The sweeper inventories only current heads of open develop PRs (at most 20).
For an expired pending v3 reservation it binds check app, PR, head, base and
admission run/attempt/actor/repository, then independently re-reads the check,
current PR and admission run. Drift rejects the whole result. Terminal checks
are never expiry candidates. Its advisory expiry results include reservation
and admission digests; it cannot finalize anything.

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
