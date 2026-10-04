# LI-219 event finalization contract (not operationalized)

The owner-authorized no-rerun continuation selects the dedicated App migration
described in [the follow-on architecture and CAS/outbox proposal](li219-app-finalizer-migration.md).
That proposal preserves the existing required gates and remains unactivated.

Task profile — Work item: LI-219; risk: high; model/reasoning: frontier/high;
rationale: organization-wide Required-Workflow provenance and event ordering;
escalate only if: ruleset, check identity, App identity, or provenance changes.

## Scope and status

The pure model in `scripts/required-review-state.py` specifies the asynchronous
reservation lifecycle independently of GitHub credentials and workflow runners.
It is not invoked by a workflow, does not publish checks, and does not change
the existing protection. Its tests are design evidence, not protected reference
run evidence or completion of LI-219. Production polling is unchanged.

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

[triggers]: https://docs.github.com/en/enterprise-cloud@latest/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets#supported-event-triggers
