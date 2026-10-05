# LI-219 event finalization contract

Task profile — Work item: LI-219; risk: high; model/reasoning: frontier/high;
rationale: organization-wide Required-Workflow provenance and event ordering;
escalate only if: ruleset, check identity, App identity, or provenance changes.

## Selected implementation, 2026-10-05

The owner has selected option 1 below: retain Required-Workflow authority and
permit one event-bound verifier re-evaluation. The implementation candidate
uses the existing protected producer, refresh and rerun helper. It does not
activate the separate App/journal proposal. The historical pure-model and
platform analysis below remains applicable; its statement that production
polling is unchanged describes the earlier design-only revision.

The review request job runs only on attempt 1. An unavailable review leaves
the initial verifier failed and merge-blocking after one observation. A later
review event, producer completion or scheduled reconciliation resumes the same
PR and head. It never requests another AI review. Re-running the producer run
re-evaluates its policy/publication and dispatch jobs; the AI-request job is
skipped, and the Required verifier checks the retained successful first-attempt
request and single native request timeline. The Required Workflow itself and
the independent dot-github Required job retain their single re-evaluation limit.

`review-event-reconcile.yml` runs from the immutable default-branch controller
source on completion and every ten minutes. Its inputs are locators, not
authority. Refresh hydrates them from the live API; existing current-head,
review-content, thread, owner and source checks run before mutation. The helper
continues to verify the complete protected producer and reservation bindings.
The Required verifier accepts a separately checked receipt for a protected
dispatch, including controller ancestry and exact native job/step ordering.
This also permits an event queued before the initial failure to execute after
that job has ended. Historical native review-event evidence remains supported.

Producer, refresh and helper share the same repository-ID/head concurrency
group with cancellation disabled and the full pending queue retained. Before
an effective rerun, the sole active writer creates a native `Review event
operation` consumption marker, bound to PR, base, head and target run. It reads
the marker back before sending the rerun. A later worker finding that marker
never sends another rerun POST. Ambiguous marker creation is read back at most
three times; ambiguous rerun delivery is reconciled from native run attempts,
without repeating the mutation. Duplicate/malformed marker inventory blocks.

This is serialized ownership, **not a GitHub Checks CAS or external-ID uniqueness
guarantee**. Its production guarantee depends on the shared Actions concurrency
lane and complete native API inventory. A crash after claim but before delivery,
or persistently ambiguous API visibility, deliberately remains blocked and
requires diagnosis. It is not reported as a successful review or live acceptance.
The marker is operational native history, not a duplicate release-evidence
package and not a replacement required check.

Reservations expire seven days after the original run creation time. Expiry
prevents refresh/helper claims and leaves the original required failure
blocking. Missing events can be reconciled within that interval; expiry never
authorizes another review. No pending custom check is used to weaken admission.

The predecessor evidence run and current PR's elected rerun owner are separate
identities. Reused evidence remains bound to the closed, unmerged predecessor
PR and original run; invalidation and current-PR retry ownership stay with the
current PR. Regression fixtures use different run IDs for those roles.

Deployment requires the canonical Shared Assets workflow/template changes,
distribution of the reconciler and script, the protected `.github` Required
source update, and the independently protected dot-github source rollout.
Local tests do not prove any of those live transitions. Operational acceptance
still requires delayed-review, missing-event, duplicate/uncertain-response and
stale-head canaries on `.github`, Shared Assets and one representative consumer.
Median/P95 and false-negative rates must be measured from actual protected runs.

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
