# LI-219 event finalization contract

Task profile — Work item: LI-219; risk: high; model/reasoning: frontier/high;
rationale: organization-wide Required-Workflow provenance and event ordering;
escalate only if: ruleset, check identity, App identity, or provenance changes.

## Selected implementation, 2026-10-05

The owner has selected option 1 below: retain Required-Workflow authority and
permit one event-bound verifier re-evaluation. The implementation candidate
uses the existing protected producer, refresh and rerun helper. It does not
activate the separate App/S3 authority proposal. The small native Git CAS store
only consumes operations under the retained Required-Workflow authority. The historical pure-model and
platform analysis below remains applicable; its statement that production
polling is unchanged describes the earlier design-only revision.

The review request job runs only on attempt 1. The owner-approved amendment
added on 2026-10-05 to [REP-40 page 2878440201, version 12][rep40] and
[REP-60 page 2887909377, version 13][rep60] permits the scoped project-rule
exception recorded in `AGENTS.md`. Only the exact three enabled pilots below
may request review on `synchronize` for a genuinely new head of a ready,
same-repository PR authored and updated by `litroc`. This is not a blanket
supersession of the default prohibition. In that enabled path the protected job
records and reads back the durable head CAS claim **before** its single request. A consumed claim prevents another
request even after an uncertain response. An already-pending, PR-scoped
reviewer is not relabelled as a new head's request. `edited`, `labeled`, draft
PRs and attempt 2 cannot request AI review. An unavailable review leaves
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

The event mode is **disabled by default**. All five components compute the same
condition: repository variable `LI219_EVENT_MODE` equals `enabled` AND the
repository is exactly `lightning-it/.github`, `lightning-it/shared-assets-lit`
or `lightning-it/ansible-collection-supplementary`. An absent variable, every
other value and every non-pilot repository use the legacy wait windows
(40 review, 20 thread, 450 neutral-evidence and 60 producer observations).
The human early-admission route and the completion/schedule adapter are also
gated. Deactivated refresh/helper jobs retain their old mutation path and
helper concurrency group. Never change this variable with writers in flight.

In enabled pilots, producer, refresh and helper share the repository-ID/head
concurrency lane. Native review listeners have contents-read and dispatch only
locators. The refresh writer runs exclusively by bot dispatch from the protected
default branch; the helper runs by bot dispatch from the protected base branch.
These writer jobs have contents-write. The AI request job is separately bounded
to the existing protected pull_request_target source and exact litroc actor;
the owner explicitly accepts its static job permission ceiling of contents-write
under this scoped mandate, while content mutation is
possible only inside the enabled pilot branch. No PR checkout is executed and
no token is passed to the data ref or stored in its commits.

Each pilot uses the fixed `refs/heads/lit-review-operations` data ref. Its root
commit contains only `manifest.json`: schema 1, repository name, string native
repository ID and the fixed ref. The writer never creates or repairs this ref.
Missing bootstrap, invalid manifest and ambiguous API results fail closed.
Source commit, manifest and operation record are read using the same immutable
commit OID. Operations occupy `operations/<sha256(operation-key)>.json`.
The record binds schema, repository/name-ID, action, operation key, claimant run
and attempt 1, and immutable protected workflow source SHA.

A rerun key binds PR, base, head and target run within that repository store.
The separate AI-request key binds native repository ID, PR and head; base drift
and a fresh producer run never create a new request entitlement for that head.
Existing current-head review and PR-scoped pending request remain read-only
no-ops. In enabled pilots, check-run and comment markers are projections, never
exclusivity locks. Disabled/default mode and non-pilots use no CAS: send the
legacy request first, then publish its marker only after a successful response
or confirmed pending reviewer readback. An interrupted pre-request execution
leaves no marker. An uncertain response without confirmation sends no retry
and creates no legacy marker; it does not gain the pilot's atomic consumption
guarantee. A lost marker response uses bounded readback without another POST.

A writer may make **one** `createCommitOnBranch(expectedHeadOid)` attempt against
the exact snapshot. Only an unambiguous successful response with the expected
single parent, followed by an exact immutable record readback, permits the
subsequent single effect POST. A conflict or uncertain CAS response performs up
to three readbacks and sends no effect, including when it discovers its own
record. A later worker that sees an old ref snapshot loses against the server's
current ref. An existing record cannot authorize another effect; crashes after
claim remain consumed and blocked for diagnosis. An uncertain rerun or AI request
response is never retried. This provides at-most-one send, not guaranteed delivery.

The Required verifier checks that the check projection matches the Git record,
that its commit belongs to the retained data-ref history, and that the record's
workflow source and claimant match the fully validated protected native run.
The data contains operational consumption metadata only, not duplicate AI or
release evidence. Required-Workflow authority and native acceptance remain
unchanged. No App, S3 store, token or ruleset bypass is introduced.

`contents: write` is repository-scoped; it cannot be granted only for this ref.
The fixed path and protected code constrain this writer. Protection against
unrelated already privileged workflows is not implied. Root must prevent data
ref deletion/non-fast-forward rewrites without granting an Actions-App bypass
on code branches. Preserve all records; no expiry cleanup or compaction exists.

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

## 2026-10-05 size-policy amendment

The owner's later size-policy authorization removes blanket diff-byte gates
from normal Copilot PR admission and cumulative promotion admission. Local
Push-ready constructs the complete diff and runs the full deterministic
profile regardless of its byte size. The default 500000-byte notice is advisory;
there is no automatic splitting, truncation, skipped check, or extra AI request.
This is independent of the three-pilot event authorization above.

Push-ready configuration version 2 now writes `review.warn_diff_bytes` (positive
integer or null to disable notices). Old `review.max_diff_bytes` positive
integers remain readable but are not enforced or reused as warning thresholds;
without an explicit new key, the warning threshold is 500000. Mixed keys are
accepted for staged distribution; the new warning key wins. Deploy the new
engine before writing the new-only configuration to downstream repositories.
An older engine remains fail-closed on the new-only configuration. Promotion
policy version 2 accepts either the historical `maximum_bytes: 199999` review
shape (deprecated, no byte gate) or `warn_diff_bytes` with the unchanged format
and minimum fields. The checked-in provisional, non-authorizing promotion
policy remains inactive. Policy hashes and operation keys still bind the full
policy; old acceptance evidence is not rewritten.

Resource protections retain their own meaning: configuration/instruction reads,
untracked fingerprints, safe regular-file reads, JSON/tree metadata, bounded
inventory collection and command timeouts still fail closed. The historical
Own-MLX metadata v5 / receipt v4 byte contract and inactive feature-main-prestage
contract are not migrated by this change. A new Own-MLX producer/consumer
version must bind model and tokenizer identity, complete rendered input
(instructions, policy, prompt, schema, full diff and tool framing/results),
context capacity and explicit output/reasoning reserve before its first model
call. Unknown or exceeded token budgets block that call. The direct Own-MLX codex-action path now fails before any new model call;
reuse of validated historical receipts remains available. Source/Governance owns
that coordinated migration; no character-to-token heuristic or larger byte
constant stands in for it. Native exact-head acceptance remains mandatory.

[triggers]: https://docs.github.com/en/enterprise-cloud@latest/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets#supported-event-triggers

[rep40]: https://wiki.cloud.l-it.io/wiki/spaces/LIT/pages/2878440201
[rep60]: https://wiki.cloud.l-it.io/wiki/spaces/LIT/pages/2887909377
