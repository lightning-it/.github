# LI-219 dedicated App finalizer migration

Task profile — Work item: LI-219; risk: high; model/reasoning: inherited
Codex/high for authority and concurrency; rationale: changing a required
review authority needs provenance and race analysis; escalate only if:
App scope, check identity, protected source or ruleset provenance changes.

Status: implementation proposal for protected review. The owner has authorized
continuing LI-219 with the smallest safe architecture and without a workflow
rerun exception. This selects option 2 of the
[existing contract](li219-event-finalization-contract.md): a dedicated App-bound
asynchronous check. It does not activate that authority or mark LI-219 complete.

## Authority and provisioning

The neutral context remains `Current revision review`. A new dedicated App must
be the explicitly required integration for that context. The current required
workflows, quality checks, strict base policy and resolved-thread requirement
remain enforced during implementation and protected positive/negative canaries.
Only after exact acceptance may the old synchronous verifier become a protected
admission workflow. Admission success alone must never make a PR mergeable.
The source workflow for `.github` remains independently cross-protected.

The read-only installation inventory on 2026-10-04 found no dedicated finalizer
App. Release App `4355159` / installation `148019054` has `checks: read`.
REP-60 section 7 forbids adding Checks or Administration rights to that App.
The existing release/sync keys will not be reused for the finalizer.

Required new capabilities are deliberately separate:

| Boundary | Capability |
| --- | --- |
| Finalizer App | Checks write; Actions, contents, pull requests and metadata read on exactly `.github`, `shared-assets-lit`, and the selected consumer |
| Journal App | Contents write and metadata read on one private operational journal repository only |
| Management controller | Existing environment-scoped governance authority; neither runtime App receives administration, secrets or ruleset permissions |

A separate Journal App avoids granting code-write permissions to the finalizer
on governed source repositories. Installation tokens are short-lived and
restricted to their exact repository and permission set. Keys belong only to
the protected controller environment; they must not be copied into candidate
workflows, local validation or repository-wide secrets. The journal contains
identifiers, lifecycle state and hashes, never reviewer bodies or release
evidence packages. REP-60's native develop-PR evidence lifecycle is unchanged.

`github-management-lit` owns API-backed governance. Its direct
`scripts/apply-automated-review-governance.sh` entrypoint is retired; the protected
`terraform-github-management.yml` performs checksum-bound plan/apply through
`github-management-administration`, with its explicit environment reviewer gate,
exact main SHA and no administrator bypass. The current workflow has no LI-219
App/journal provisioning operation. That operation requires a normal reviewed
management change, then a concrete protected plan. Existing user authorization
selects this architecture; the GitHub environment gate remains a real platform
precondition, not a substitute approval inferred from this document.

App IDs, installation IDs, controller environment, private journal repository
ID, generation digest and the exact management ruleset patch must be live-bound
by that plan. None is invented here. The reference implementation accepts a
strict bound configuration but has no production configuration or token lookup.

## CAS and immutable terminal writes

`scripts/required-review-journal.py` adds a concrete GraphQL journal adapter and
an injectable terminal-check outbox. It is not imported by any workflow and does
not construct an HTTP transport. Its deterministic tests inject both transports.
The adapter's only mutation is `createCommitOnBranch` on the exact private
`refs/heads/li219-reservations` data branch, replacing `reservations.json` with
`expectedHeadOid` equal to the fully validated previous snapshot. This is a
server-enforced CAS; neither force pushes nor a best-effort lease are used.

The complete root tree must contain exactly one regular file. Repository ID,
name, private visibility, ref, commit OID, blob type/mode, byte size, truncation,
Git blob hash, strict JSON, generation and every record are checked. The first
version supports up to 512 records and 1 MiB; either bound fails closed. It never
drops history to make room. This is a bounded reference implementation, not an
unbounded fleet storage claim. Capacity/partitioning must be resolved before
production activation, preserving operation tombstones and complete inventory.

GraphQL success must omit `errors`; falsey malformed values and partial data
reject. CAS read-back may observe a later concurrent state: reconciliation
validates that every intended record, immutable binding and terminal payload is
preserved and that receipts never regress. Another writer's valid admission or
delivery receipt does not turn an already durable CAS into a false failure.

Each operation key binds repository ID, PR, head and producer run. The accepted
transition model retains base, controller, ruleset digest, actor, run attempt,
admission, reviewer and metadata bindings. App ID, check ID, generation and
external ID remain immutable. One check ID cannot belong to two records in the
same repository. Legacy reservations are never silently adopted.

Admission currently accepts an already authenticated, exactly owned pending
check. A separately protected admission adapter must durably claim creation
before its first `POST /check-runs`, bind the one returned check ID, and reconcile
an uncertain creation response through complete exact-scope native inventory.
It must never retry uncertain creation because `external_id` is not unique.
That creation protocol and its transport are not implemented by this library.
The library cannot therefore be activated as a complete admission service.

Finalizer and expiry compete through the same journal CAS. The winning terminal
record and its exact output payload are committed together. Terminal states
and payloads are absorbing. A receipt may advance only from undelivered to
delivered. A lost response triggers one independent read-back; it does not
trigger a write retry or polling loop.

Delivery first reads the exact check and verifies its App, external ID, name,
head and immutable check ID. A conflicting completed result is never patched.
Before a success write, two independent complete normalized authority reads must
still match the sealed evidence digest. Changed head, base, controller, actor,
attempt, review or threads block that write. The terminal job may still be
`in_progress` with both critical steps successful. The final store read also
must retain the same terminal record and payload.

Concurrent deliverers can each issue the same terminal PATCH after observing a
pending check. GitHub Checks provides no write CAS; therefore this design claims
one **effective terminal decision**, not exactly one HTTP request. All such
PATCHes contain the same completion time, conclusion and evidence summary and
target the same bound check ID. No worker can acquire a lease and publish the
opposite conclusion after another worker seals the decision. An unconfirmed
write stays in the outbox for the next natural event or scheduled reconciliation.
It is read back before any later attempt. No dispatch or workflow rerun is used.

The injected transports are part of the future protected trust boundary. They
must enforce exact installation/token scope, complete provenance normalization,
fixed routes, response and time budgets, and redirect/proxy refusal. Passing
caller-authored dictionaries or an arbitrary callback is not production
authorization. Missing transports/credentials cannot fall back to personal
tokens, the release App, or a GitHub Actions context with a different identity.

## Inventory, cutover and rollback

Sweeping reads all owned journal entries, including reservations whose PR has
closed or whose head is superseded. It does not start from the open-PR list.
Each expiry uses a fresh CAS and can fail only that reservation's old check ID.
The output explicitly says `complete_owned_inventory: true` and
`legacy_inventory: not-adopted`; it never claims a complete legacy inventory.
Historical v3 checks lack controller/ruleset ownership and need a separately
enumerated quarantine report, with no guessed writer authority.

The management plan must add the mandatory App-bound context while all existing
required gates still apply. Independently verify absence/pending/failure/foreign
App/stale-head checks block merge. A fresh protected positive and negative
reference PR in each target must exercise native admission, event delivery,
terminal writes and orphan expiry. Only then may a separately exact-bound
change replace synchronous verification with admission and remove its polling.
The old gate and new App check must overlap during cutover and rollback; no
optional context can substitute for the existing authority.

The event listener uses successful producer completion only as a locator. Its
protected adapter must preserve the existing two-read provenance checks and
support every allowed review path. The present Copilot normalization cannot be
relabelled as bot/promotion authorization. A missing event is handled by bounded
scheduled reconciliation from the owned journal, never a long-lived runner.

## Acceptance and measurement still required

The offline suite injects 180-second job visibility delay, finalizer/expiry
races, duplicate and out-of-order events, lost CAS/check responses, restart,
concurrent identical deliveries, stale bindings, failed steps, foreign checks,
corrupt/truncated storage and complete owned-orphan inventory. Run it in the
digest-pinned Devtools image:

```sh
scripts/wunder-devtools-ee.sh python3 -m unittest discover \
  -s tests -p test_required_review_journal.py -v
```

These fixtures are neither live GitHub CAS evidence nor production Acceptance.
No App was created, no secret installed, no reservation changed and no ruleset
modified by this component's introduction. LI-219 stays In Progress until the
protected adapter/creation protocol, provisioning, production canaries and
matched before/after measurements are complete.

Before cutover, preregister two contiguous matched 24-hour cohorts per target,
including failures and unknowns, and require at least 30 comparable operations
per cohort before estimating P95. Report nearest-rank P95, median, deduplicated
job minutes and confirmed timing false-negative numerator/decidable denominator;
unknowns stay explicit. Proposed acceptance is zero confirmed timing-induced
false negatives, zero binding bypasses and no increase in median/P95 total
latency; any different operational threshold requires an explicit recorded
decision. Sparse cohorts extend the observation window; they do not fabricate
a rate. The existing three-case baseline remains diagnostic only.

## Platform references

- [Required-workflow supported events](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets#supported-event-triggers)
- [Atomic commit creation and expectedHeadOid](https://docs.github.com/en/graphql/reference/commits#createcommitonbranch)
- [Checks API ownership and permissions](https://docs.github.com/en/rest/checks/runs)
- [REP-60](https://lit.atlassian.net/wiki/spaces/LIT/pages/2887909377)
