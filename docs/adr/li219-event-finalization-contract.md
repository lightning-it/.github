# LI-219 event finalization contract (not operationalized)

Task profile — Work item: LI-219; risk: high; model/reasoning: frontier/high;
rationale: organization-wide Required-Workflow provenance and event ordering;
escalate only if: ruleset, check identity, App identity, or provenance changes.

## Scope and status

The pure model in `scripts/required-review-state.py` specifies the asynchronous
reservation lifecycle independently of GitHub credentials and workflow runners.
The default-off event adapter can invoke it for read-only shadow observations.
It does not publish checks or change existing protection. Its tests are design
and adapter evidence, not protected reference-run evidence or completion of
LI-219. Production polling is unchanged.

Admission creates a pending record. A later event is only a locator for two
authoritative reads; complete matching evidence can propose one terminal
transition. A separate expiry operation can propose failure for the exact
expired reservation. Neither operation requests a review, pushes, reruns a
workflow, sleeps, or performs an API mutation.

## Binding and storage contract

The operation key identifies repository ID, PR number, head, and producer run.
The record additionally freezes repository name, base, controller revision,
ruleset digest, actor ID, producer attempt, admission run, reviewer ID, and PR
metadata digest. An altered binding cannot admit a second record under the same
operation key. Check IDs are immutable. Terminal states are absorbing.

The future protected adapter must supply normalized reads from the existing
authoritative validators, including the exact expected policy step name. Raw
webhook content, arbitrary check summaries, and user-provided JSON are not
authority. It must verify complete pagination, unique job selection, the
producer's full terminal job inventory, actor/App identity, workflow path and
protected source, review content and chronology, thread completeness, and
current ruleset provenance before calling this model. The model covers the
normalized lifecycle subset; it does not replace those validators or generalize
the Copilot review branch to bot/promotion evidence.

The two reads must independently revalidate the current PR, metadata, review,
threads, producer, controller, and ruleset. Terminal job visibility may advance
from `in_progress` to `completed/success`; the evidence itself must not change.
Both critical steps must occur exactly once and be `completed/success`.
Missing, duplicate, unsuccessful, queued, or foreign evidence is rejected.

The adapter needs a serialized durable store with compare-and-swap semantics,
complete reservation inventory, and read-back after a write. GitHub check
`external_id` alone is not uniqueness or a distributed lock. The model's
`compare_and_swap` function demonstrates the precondition; it is not a storage
implementation. Event finalizer and sweeper must use the same serialization
key. An uncertain mutation response must be reconciled by reading the exact
record before any further write. API writes cannot be made exactly once by this
pure model; a future adapter must prove one effective terminal transition.

An old event cannot update the new head's check. Sweeping an old reservation
can fail only its own bound check ID. Expiry is an operational failure, never an
authorization to request another AI review. The TTL is supplied by future
protected policy, not by the event or PR author.

## Verified platform and protection boundary

Read-only GitHub API observations on 2026-10-02:

| Target | Active authority | Required source |
| --- | --- | --- |
| `.github`, main/develop | Organization ruleset `21200954`, no bypass actors | Repository `1103407173` (`ansible-collection-supplementary`), `main`, `.github/workflows/dot-github-current-revision-required.yml` |
| `shared-assets-lit`, develop | Organization ruleset `20938748` | Repository `1112629689` (`.github`), `main`, `.github/workflows/supplementary-current-revision-required.yml` |
| `.github`, main/develop | Repository ruleset `19045511` | Strict `repository / quality`, integration `15368`; no separate reservation check requirement |

These observations are reproducible with read-only `gh api` calls:

```sh
gh api repos/lightning-it/.github/rulesets/21200954
gh api repos/lightning-it/.github/rulesets/19045511
gh api repos/lightning-it/.github/rules/branches/develop
gh api repos/lightning-it/shared-assets-lit/rules/branches/develop
gh api repositories/1103407173
```

The central workflow at base commit
`892dd30255e76a71e0aa8921beb3ee842efca773` was inspected locally. Its final
`required-current-revision-workflow` job requires a successful verifier route.
A pending custom check is not a substitute for that workflow run.

[GitHub's documented Required-Workflow triggers][triggers] are `pull_request`,
`pull_request_target`, and `merge_group`, with default activities only.
`workflow_run` and `pull_request_review` can wake ordinary listeners but do not
by themselves satisfy the existing ruleset run.

Therefore admission cannot simply exit successfully while an optional check
remains pending: that would remove the existing review enforcement. Admission
also cannot exit failed and expect an unrelated listener to replace its run.
No such shortcut is implemented.

## Required rollout decision

Choose and independently verify one platform-supported authority contract before
wiring the model into production:

1. Preserve the existing Required-Workflow authority and explicitly permit one
   event-triggered, fully bound verifier re-evaluation. This retains the run
   relationship but needs a deliberate exception to LI-219's no-rerun target;
   duplicate and uncertain dispatch outcomes must be bounded and reconciled.
2. Authorize an authority migration in a separate reviewed plan. A mandatory,
   App-bound asynchronous result must continue blocking merge during admission,
   delay, missing events, expiry, drift, and service failure. Check names,
   provenance, credential scopes, strict base behavior, and the cross-repository
   Required Workflow need live positive/negative canaries before cutover.

Neither option is authorized or activated by this change. No ruleset, token,
credential, environment, check identity, or required source is mutated.

## Verification and remaining acceptance

The deterministic tests simulate an event arriving 180 seconds after admission
while the job remains `in_progress`, successful terminal visibility 180 seconds
later, duplicate and out-of-order delivery, concurrent finalizers and sweeper,
all binding drift fields, stale heads, failed/missing/duplicate critical steps,
review changes, unresolved threads, malformed types, and an expired reservation.

```sh
scripts/wunder-devtools-ee.sh python3 -m unittest discover \
  -s tests -p test_required_review_state.py -v
```

Before operational acceptance, the adapter, event listener, protected storage,
scheduled sweeper, native Required-Workflow relationship, and three protected
reference runs (`.github`, Shared Assets, representative consumer) remain to be
implemented and verified. Measure runner job seconds, request-to-review,
review-to-verifier, total latency median/P95, and false negatives over matched
before/after cohorts. No after-rollout measurement exists yet; local simulated
time must never be reported as a live latency reduction.

## Default-off event integration after PR 718

The feature branch based on protected `develop@3d06b53e57e1209ce008453e24375ed9e7410b01`
adds executable integration artifacts:

- `required-review-event-shadow.yml` receives completed producer `workflow_run`
  events. It checks out only `github.workflow_sha`, never a producer/PR head.
- `required-review-sweeper-shadow.yml` independently audits native reservations
  every six hours, with a bounded inventory and no waiting runner.
- `scripts/required-review-events.py` reads GitHub REST and fixed read-only
  GraphQL queries, performs independent snapshots, and emits JSON observations
  to native Actions logs. Its fixed-origin transport refuses redirects, writes,
  arbitrary queries, oversized responses, duplicate JSON keys, incomplete
  pagination, and request/time-budget exhaustion. It makes no retry or sleep.
- `.lit/required-review-events.json` ships with `lifecycle: inactive`.
  Both workflows additionally require `LI219_EVENT_SHADOW == true`. Neither
  switch is changed by this work. Setting lifecycle to `active` is rejected;
  there is deliberately no writer mode.

All workflow permissions are read-only; only the ephemeral read-scoped Actions
token enters the digest-pinned container. No credential is stored. Ordinary
hosted-runner bridge networking is the explicit minimum needed for GitHub API
reads; the container is read-only, capability-dropped and socket-free. No PR
content is executed, no check is published, and no AI endpoint is called.

The first integration scope is `.github`, same-repository `litroc` ingress into
`develop`, producer attempt one. Other identities, forks, bot exemptions,
promotions, ambiguous native reservations, and unsupported run shapes reject
closed. Existing native `v3` reservations do not freeze all new LI-219 bindings.
The adapter therefore reconstructs **observational** bindings from two live
reads; `would_finalize: success` means a shadow candidate, not admission proof,
not complete legacy job-topology verification, and never write authorization.
Every record explicitly includes `authority: none` and `writes: 0`.

Read-back of PR 718 confirms the distinction: native reservation check
`110916661461` points through its v3 external ID to admission run `37030434380`.
That run reports `supplementary-current-revision-required.yml`, repository
`1112629689`, `pull_request_target`, attempt one, and actor/triggering actor
`litroc` (`76040632`). It is separate from the cross-repository ruleset workflow
`dot-github-current-revision-required.yml`. The observer validates both roles
without treating either one as a replacement for the other.

The separate sweep covers current heads of at most 20 open `develop` PRs. It
re-reads each exact expired check before reporting an expiry candidate. It does
not claim a global ledger: abandoned heads and closed PRs require the future
durable admission inventory. Its output explicitly sets
`complete_global_inventory: false`. Inventory overflow is an error, not an
empty-success result. No reservation is failed by this observer.

Native-log telemetry includes request-to-review, review-to-neutral-result,
neutral-result-to-observer, admission-to-observer, and terminal producer-job
seconds/minutes. A preexisting/manual review may legitimately have no native
request marker; request-based timings then remain `null`. Present markers must
be unique and Actions-authored. Reviews need positive content even when an old
native result already succeeded; empty, whitespace-only, transport-marker-only,
and unavailability-marker content fails closed. Incomplete job timings remain
`null`, never zero; skipped jobs use zero without requiring time fields. The pure
`summarize` helper deduplicates operation keys, reports sample counts, median and
nearest-rank P95, and flags native failures with currently ready evidence for
investigation. Those flags are not verified false negatives; the measured false
negative rate remains unknown. Validated-shadow-only cohorts are not a fleet
population and cannot prove a before/after improvement.

The adapter tests drive the real normalization and decision functions through
bounded fake GitHub responses, including a 180-second delayed event, two-read
drift, stale/foreign identities, status regression, critical-step failures,
pagination rejection, event deduplication, read-only transport, inactive
zero-call behavior and sweeper drift. Full live rollout remains blocked by the
authority decision, durable admission/CAS storage, global sweep inventory,
full producer-topology validation, and protected reference runs. This change
does not remove any of those gates or assert production-ready finalization.

[triggers]: https://docs.github.com/en/enterprise-cloud@latest/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets#supported-event-triggers
