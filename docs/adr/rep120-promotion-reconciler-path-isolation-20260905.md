---
id: adr-rep120-promotion-reconciler-path-isolation-20260905
title: REP-120 default-off promotion reconciler and capability isolation
description: Defines the proposed repository-local replacement for the retired hourly promoter, its capability boundaries, and its evidence-gated rollout.
slug: /adr/rep120-promotion-reconciler-path-isolation-20260905/
document:
  status: maintained
  approval_status: proposed
  version: "5.0"
  classification: PUBLIC
  owner: Lightning IT Documentation Maintainers
  approver: Lightning IT Product Owners
  audience:
    - repository maintainers
    - platform engineers
    - security reviewers
  last_reviewed: "2026-09-07"
  review_cadence: annual
---

# ADR: REP-120 default-off promotion reconciler and capability isolation

- Decision status: **Proposed**
- Implementation status: **Pending**
- Technical acceptance: **Open / Inconclusive / fail-closed**
- Operationalized: **No**
- Scope: `lightning-it/.github` protected `develop` to `main`
  reconciliation
- Recovery owner: issue `lightning-it/.github#564`
- Evidence cutoff: `2026-09-07T16:33:29Z`

This maintained repository ADR is an implementation companion to the canonical
REP-120 decision. It records the intended repository-local controller and the
current recovery boundary. It is not evidence that the controller, credential
cutover, cross-repository architecture, references, canary, or fleet rollout
has been accepted.

## Context

The legacy workflow `.github/workflows/promote-develop-to-main.yml`, still
present on protected `develop` at the evidence cutoff, contains an hourly
schedule and a manual-dispatch entry. It can mint a write-capable token before
proving that protected `main` and `develop` require a promotion and before
proving that the exact protected `develop` revision is neither active nor
already consumed. Its non-cancelling concurrency can leave an older run in
control after a newer event exists. Separate incident evidence also records
promotion workflows in other repositories waiting at an approval Environment
before deduplication. This repository-local legacy workflow does not itself
declare that Environment, but it is part of the same non-convergent promotion
model.

Workflow removal from current refs is not sufficient containment. GitHub can
rerun a completed workflow against its historical workflow revision. The old
credential names are also used outside this repository, so recovery must not
globally revoke, corrupt, or replace their organization-level values.

The same old names are not exclusively write credentials.
`.github/workflows/supplementary-current-revision-required.yml` uses
`RELEASE_AUTOMATION_APP_CLIENT_ID` and
`RELEASE_AUTOMATION_APP_PRIVATE_KEY` for restricted reads of
`lightning-it/shared-assets-lit` and `.github`. Substituting an invalid value
would break a required workflow. The safe design separates source-read and
successor-write capabilities.

## Current protected recovery evidence

The bounded recovery through PR #575 is complete as recovery history, but it
does not implement this ADR:

| Transition | Protected result | Evidence boundary |
| --- | --- | --- |
| PR #565 | Initial bounded recovery stage merged normally to protected `main` as `2edd5190c88bf32e009848d85df664c29fb4eab6` | Historical prerequisite only |
| PR #566 | Exact PR #565 source-binding correction merged normally to protected `develop` | Recovery verifier transition only |
| PR #567 | Exact PR #565 main ancestry returned normally to protected `develop` as `5c549450321b5c7182ef452977d9587ff1f7f14c` | Protected backmerge evidence only |
| PR #568 | Four-path pre-stage merged normally to `main` as signed merge `caa39d79c8fafe71cc3f51951ba493f6a9fc6ef1`, tree `0f3ff650c0d8da4ec2606bc32afd365dfc88e15c` | Bounded pre-stage evidence; not permanent-controller acceptance |
| PRs #569–#572 | PR #568 source, recovery-source, schema, and producer-materialization transitions merged normally to protected `develop` | Bounded verifier recovery only; no reusable permanent authority |
| PR #573 | Exact PR #568 main ancestry returned normally to protected `develop` | Protected backmerge evidence only |
| PR #574 | Helper rerun/materialization transition hardened by normal protected merge `b0622e97c14d0a7c2a4858672c01bdbbf4ce4d0b` | Current-revision helper fix only |
| PR #575 | Consumed PR #568 authority retired by normal protected merge `842bd4b9c055241380f0e86ec91bdfc3c3e1a6c5`, tree `5cb946132623fd1f022fe7e3ecebb8da3aa13f85` | Recovery closed through PR #575; permanent work remains pending |
| PR #576 | ADR-only head `8742039b717abc57dbb8c92bbc740f6a2f959f9b` opened against `main`; repository Required run `34143008702` and cross-Required run `34143008743` failed | Fail-closed proof that the earlier feature-to-`main` D1 sequence is invalid; no merge authority |

PR #575 used exactly one owner-authorized `Draft -> Ready` transition to obtain
a current-head review. That current-head path automatically dispatched
protected helper run `34135580015`, which caused Required-Workflow run
`34126349996` to move from failed attempt 1 to successful attempt 2. This was an
automatic consequence of the newly authorized current-head lifecycle event,
not an operator command to rerun an old workflow. The operator did not issue
`gh run rerun`, reopen a closed PR, force-push, edit a ruleset, change a
credential, or use an admin/bypass merge. Auxiliary Copilot-triggered workflows
that were blocked by the existing approval policy were not treated as required
checks and were not rerun.

The PR #575 merge has ordered parents
`[b0622e97c14d0a7c2a4858672c01bdbbf4ce4d0b,
26841ed35a723fd0352eae98dfb64c5fd7c8996d]`. Its tree equals the reviewed PR
head tree. Post-merge repository-quality and CodeQL runs succeeded on the exact
protected merge. These facts prove the bounded recovery transition only.

PR #576 then supplied new negative evidence. Its protected default-branch
workflow ran from `develop@842bd4b9...`, while its event base was
`main@caa39d79...` and its feature head was `8742039b...`. The generic source
contract accepted neither feature-to-`develop` (`WORKFLOW_SHA == EVENT_BASE`)
nor exact protected `develop`-to-`main` (`WORKFLOW_SHA == EVENT_HEAD` and head
ref `develop`). Run `34143008702` therefore failed at
`protected-source-binding` before creating a `Protected current-revision
verifier` reservation. Automatic helper `34143164872` observed no reservation,
timed out, and performed no rerun. Independent cross-run `34143008743` then
failed after its bounded wait. No operator initiated a rerun, reopen,
force-push, Ruleset edit, bypass, or merge.

The PR remains open and blocked. Its successful current-head review, Quality,
and CodeQL results cannot override either Required failure. The earlier
D1-direct-to-`main` materialization sequence is retired rather than repaired by
another one-time PR/SHA tuple.

## Historical over-limit evidence

The first eight-path successor draft produced result tree
`63052e396fdd2e3dccfcc3ff7bd148954a31b566`. Its canonical local delta from
then-protected `develop@5c549450321b5c7182ef452977d9587ff1f7f14c` was
166,907 bytes with SHA-256
`d752c7dee0e95cf0c4ba69f00f9d01827e9c1a28c7dfffea4aad3e2a60e93e4c`.
That was not the promotion input. The complete then-protected
`main@2edd5190c88bf32e009848d85df664c29fb4eab6` to candidate input was
228,508 bytes with SHA-256
`1f075b5e56d69435cf56734e404ca5d5a3fb944122649882e137e74befa9fab5`.
It exceeded the `1..199999` compatibility interval and remains immutable
negative evidence. It must not be retried, truncated, re-labelled, or reused as
review evidence for a later head.

After PR #575, overlaying the still-stale eight candidate paths on the protected
`develop` content tree is 192,598 bytes with SHA-256
`8b70d1aae65abf27dd7423791a4db85cbcfddbaa9a54cabcc314d4aea0d37402`.
That diagnostic is below 200,000 bytes but remains **NO-GO**: its ADR and test
assertions are stale, it has only 7,401 bytes of margin, and it is not the
promotion input. The D1 starting protected `main` at the evidence cutoff,
`caa39d79c8fafe71cc3f51951ba493f6a9fc6ef1`, to the same conceptual final
target is 324,868 bytes over 12 paths, SHA-256
`7fdcf035b5b2ea25874ab20babb228b26cd7d70bd51bd705c35006443753df30`.
That single promotion input is a hard **NO-GO**.

All byte receipts in this section use
`git-diff-binary-full-index-no-renames-v1`: binary/full-index, no renames, no
color, no external diff, and no text conversion. A changed base, head, path,
hunk, policy, or format invalidates the corresponding receipt.

## Eight-measure status at this decision boundary

| Measure | Decision and current state |
| --- | --- |
| R1 — stop hourly self-dispatch | C1 proposes deleting the legacy scheduled/manual workflow and installing a push-only successor; not implemented |
| R2 — deduplicate before approval | Admission and two read-only history observations are designed to finish no-op/active/consumed states before the Environment; not implemented |
| R3 — at most one waiter per repository/SHA | Static concurrency, first-attempt binding, exact markers, and one live operation owner are designed here; not implemented or canary-proven |
| R4 — one aggregate required check | Corrected target is one source-bound `promotion / aggregate` job plus a strict status-check rule requiring that same visible context; live canary and leaf retirement remain open |
| R5 — one-way workflow DAG | Private `shared-assets-lit` cannot protect public `.github`; a separately authorized public execution proxy is required; the live reciprocal `.github <-> Supplementary` cycle remains open |
| R6 — complete bounded review units | Exact `1..199999` interval retained; current 204,877-byte `main..develop` and the 324,868-byte conceptual target are rejected; D1/S0/serial main units/C1 and a sealed Coverage Manifest remain pending |
| R7 — controlled cleanup | Stale run, branch, and worktree retention/deletion plan and evidence remain open |
| R8 — three clean references before fleet | Three consecutive references, including Collection-to-Container, then bounded canary and fleet rollout remain open |

## Decision

### 1. Default-off, push-only successor

The proposed successor path is
`.github/workflows/reconcile-develop-to-main.yml`. It has exactly one trigger:
a push to protected `develop`. It has no schedule and no `workflow_dispatch`
entry. Installation therefore cannot recreate hourly same-revision wakeups or
allow manual dispatch of the controller.

Installation does not enable mutation. The repository variable
`RELEASE_RECONCILIATION_ENABLED` is absent by default. Only the exact repository
value `true` is accepted. An absent, false, differently cased, padded, malformed,
organization-scoped, or Environment-scoped value must not reach the approval
Environment, secret resolution, or token mint. The variable remains absent
through code installation and is created only for an approved bounded canary
after every credential and Environment gate below passes.

Every job is bound to `lightning-it/.github`, `refs/heads/develop`, a protected
ref, the exact push SHA, and run attempt 1. All events use the static concurrency
group `release-reconciliation-lightning-it-dot-github` with
`cancel-in-progress: true`. The operation contract binds boolean enablement,
the fixed operation key, run owner, source SHA, and a 3,600-second lease. A
queued duplicate, a second non-terminal owner, a newer event, cancellation,
expiration, malformed ledger, or source drift fails closed.

Trusted-token merges that emit no push are not repaired with a schedule or
repository-local polling. Their successor trigger belongs to the separately
reviewed one-way event DAG.

### 2. Read-only admission before authority

Admission has only `contents:read` and `pull-requests:read`. It uses the
digest-pinned Devtools runtime to:

- refresh protected refs without persisted Git credentials;
- bind exact `main`, `develop`, merge base, merge tree, controller blobs, and a
  complete tree projection;
- reject symlink, submodule, rename, binary, unsafe-mode, or worktree drift;
- construct the complete canonical protected `main` to target review input;
- accept only complete text input of `1..199999` bytes; and
- finish identical content and an exact evidence-bound ancestry-only backmerge
  as successful no-ops.

A read-only history classifier then returns exactly one of `mutate`, `active`,
or `consumed`. Exact active or consumed revisions stop before the Environment.
Ambiguous, foreign-owned, malformed, pending, or otherwise unhandled history
fails closed.

A second read-only job repeats the complete preflight and history
classification. It binds every output and the normalized relevant-history
digest to admission. Neither read-only job can resolve the successor private
key or mint an App token.

Before this controller is considered permanent, its all-history pagination and
workflow-run inventory must also pass deterministic large/multi-page fixtures
with an explicit runtime and memory budget. Safe timeout failure alone is not
evidence of operational convergence.

### 3. Environment-gated mutation and exact review

The mutation job is eligible only when both read-only jobs return `mutate` for
the same bound history. It is the only job that references the
`release-reconciliation-v1` Environment.

After the Environment wait and before token minting, the job repeats full
admission, verifies exact enablement, reads both protected branch tips, validates
the live run/lease inventory, and repeats history classification. It repeats
history classification again before the first PR mutation.

The successor may create only one exact same-repository `develop` to `main` PR.
The body binds one head marker, one first-attempt run marker, and one dispatch
state marker. The controller never merges the PR, never uses admin mode, never
force-pushes, never silently retries a consumed head, and never substitutes a
partial review. A newly created exact PR receives one protected exact-revision
review dispatch. A uniquely bound create attempt that fails or is cancelled is
tombstoned and closed fail-closed; malformed or ambiguous history is not
automatically repaired.

### 4. Credential capability isolation

The effective `.github` values under the old
`RELEASE_AUTOMATION_APP_*` names remain valid until their current consumers and
historical rerun horizon are safely retired. After proving there is no
Environment-level override, those names may be shadowed at repository scope by
a dedicated Source App with only:

- `actions:read` and `contents:read` on
  `lightning-it/shared-assets-lit`;
- `contents:read` on `lightning-it/.github`; and
- no pull-request, contents-write, actions-write, checks-write,
  administration, or organization-write permission.

This decision never globally revokes, deletes, rotates, corrupts, or replaces
the organization Release key. Any fleet-wide retirement needs its own complete
consumer inventory and rollout decision.

The successor write capability uses separate repository variable
`RELEASE_RECONCILIATION_APP_CLIENT_ID` and Environment-only secret
`RELEASE_RECONCILIATION_APP_PRIVATE_KEY`. Exact live probes must bind App slug,
App ID, installation ID, repository selection, granted permissions, token
response, successful required reads, and rejected writes. The named Environment
must exist and its protection rules must be read back before any enabled run;
GitHub otherwise creates a referenced missing Environment without the intended
protection or secret.

During cutover, operators must inventory and drain every non-terminal run that
could resolve the old pair, prevent a new eligible run between the zero-run
observation and both repository-local writes, validate both Source-App values
as one pair, and retain rollback to a valid read-only pair. The shadow stays for
the complete documented historical rerun horizon plus installation-token drain.
A later eligible historical run or possible token mint restarts that drain.

### 5. Corrected bounded materialization and source bootstrap

The stale worktree is not rebased or published. PR #576 is not merged to
`main`, manually rerun, closed/reopened, force-pushed, or bypassed. Subject to a
separate, explicit PR-#576 lifecycle authorization, it is retargeted to
protected `develop`. The corrected ADR is first stored as a normal successor
commit on a clean local branch. After retarget, that clean branch normally
merges the exact current protected `develop` commit with no amend or rebase;
the ordered merge parents and result tree are verified before one normal push.
The resulting new base/head tuple is reviewed once and normally merged to
`develop`. This ADR remains Proposed and Implementation Pending after that
merge.

The earlier authorization for PR #575's one Draft-to-Ready transition is
consumed and cannot authorize PR #576. The intended PR #576 lifecycle uses one
Draft-to-Ready cycle so retarget, ADR correction, and protected-develop merge
produce one final reviewable successor head rather than multiple intermediate
review requests.

After D1 is protected on `develop`, S0 is installed by normal protected PRs on
`develop`. The bridge implementation changes
`.github/workflows/supplementary-current-revision-required.yml` and its coupled
`tests/test_supplementary_required_workflow.py`; a separate protected activation
policy at `.lit/feature-main-prestage-policy.json` starts in canonical state
`inactive`. Before it can transition to `active`, the S0 implementation must be
merged/read back and C1 must be installed default-off on protected `develop`
with `RELEASE_RECONCILIATION_ENABLED` absent. C1 is one complete workflow/
helper/test unit, or newly reviewed semantic workflow/test pairs if its fresh
develop-relative input reaches `200000`. Only then may an immutable
Authorization Manifest for the complete main series seal every unit ID/order,
starting main tree, allowed source/destination blob and mode transition,
per-unit limit, maximum unit count, terminal unit, and reconstruction digest.
It contains no future runtime claim.
The one-path activation PR has its own Coverage Manifest entry, exact current-
head review, Required checks, normal protected merge, and source/tree readback.

Manifest sealing also requires the exact projected P4 input to be freshly
proven in `1..199999` canonical bytes. P4's Required-Workflow source, coupled
test, and `active -> consumed` transition are indivisible. If their combined
projection is `0` or at least `200000`, activation is NO-GO: the policy remains
`inactive` and S0 is redesigned before any replacement manifest is sealed.

S0 is a temporary, protected, read-only bridge for serial bounded
feature-to-`main` pre-stage PRs. It contains no PR/SHA/run-specific exception.
Its policy is read only from the exact current protected
`develop@WORKFLOW_SHA` and binds schema, series ID, epoch, expiry, starting main
tree, repository, `main`, a `prestage/` prefix, allowed author/App classes,
ordered allowed units and path/blob/mode transitions, canonical diff format,
maximum unit count, byte ceiling, and the exact monotonic state enum
`inactive -> active -> consumed`. `consumed` is absorbing under every later
tree, blob, base, source, expiry, or replay condition.

For each candidate the protected workflow binds an open, non-draft,
same-repository PR; exact live protected main base and develop source; supported
default Required-Workflow event and first attempt; ancestry; conflict-free
integration tree; complete path/blob/mode projection; and exactly one canonical
manifest occurrence whose values match the base, head, integration tree,
ordered projection, blobs, modes, SHA-256, and complete canonical diff in
`1..199999` bytes. Fork, source/base drift, unsafe mode, rename, binary,
symlink, submodule, gap, overlap, truncation, duplicate
reservation, malformed manifest, unexpected author/App, or PR-controlled
execution fails closed. The deep verifier has read-only permissions and
references no secret, Environment, token mint, PR/content write, dispatch, or
rerun. A PR-body manifest is evidence input, never the protected authorization
by itself.

An isolated reservation/finalization job has only the reads needed for
elementary source/PR binding plus `checks:write`. It idempotently creates or
resumes one canonical `external_id` before any long producer wait. An always-
running finalizer rebinds that exact check and terminally writes success or
failure; it has no other mutation authority. The deep verifier never waits on
the downstream cross-verifier or its helper. Tests cover the exact
`1`/`199999` accept and `0`/`200000` reject boundaries plus every identity,
source, tree, projection, manifest, mode, duplication, expiry, unit-order, and
disablement failure.

Main materialization is serial and freshly remeasured:

| Unit | Complete ownership | Transition role |
| --- | --- | --- |
| P1 | This ADR copied byte-for-byte from protected `develop` | First bootstrap unit, not the later operational canary |
| P2 | `current-revision-rerun.yml` with `test_copilot_review_refresh.py` | Whole workflow/test pair |
| P3 | Remaining protected-develop divergence, including C1 only in complete semantic workflow/helper/test units | Finishes all units that still require active S0 |
| P4 | `supplementary-current-revision-required.yml`, `test_supplementary_required_workflow.py`, and the sole policy transition `active -> consumed` | Whole source/test/policy pair and final bridge shutdown after sealed coverage |

Before each successor unit, the prior normal protected `main` merge is read
back and normally backmerged to protected `develop`; all unit inputs are then
freshly recalculated and parallel main units are forbidden. S0 becomes
permanently fail-closed only through the sole `active -> consumed` transition
in P4 after the ordered manifest proves complete coverage and byte-identical
reconstruction. Raw tree equality alone is not a safe shutdown signal because
`.lit/main-ancestry.json` changes on backmerges and later unrelated divergence
must never reactivate the bridge.

P4 is opened only after every declared target blob not owned by P4 itself has
already reached protected `main`. Its own Required-Workflow, test, and
`consumed` policy blobs arrive atomically through P4. After P4 no part of this
series remains: S0 is absorbing `consumed`, and C1 is not deferred to another
feature-to-main pre-stage. A later exact protected `develop -> main` promotion
belongs to new, independently reviewed work and cannot finish or reopen this
series.

The pre-S0 D1-plus-four-path diagnostic was 178,477 bytes and left only 21,522
bytes of margin. It is not reusable after S0. Every unit is freshly
reconstructed with `git-diff-binary-full-index-no-renames-v1`, independently
reviewed, and accepted only at `1..199999`. At 200,000 bytes or more it stops
and is split by whole workflow/test pairs; no source, assertion, documentation,
or evidence byte is removed to fit.

The pre-activation Authorization Manifest binds the ordered unit DAG, projected
predecessor/result content trees, disjoint path/hunk ownership, every authorized
path/blob/mode, exact unit and total bytes/digests, policy/prompt/schema/
workflow authority, zero gaps/overlap, and the final target tree. Each runtime
unit appends an immutable Execution Receipt hash-chained to the Authorization
Manifest and preceding receipt, recording actual base/head/integration tree,
review, checks, normal merge, signature, parents/tree, and protected backmerge.
After P4, a Closure Manifest binds the complete receipt chain and proves final
byte-identical reconstruction. Preparatory and activation units have their own
canonical `1..199999` receipts. A future claim in the Authorization Manifest,
broken chain, zero-byte, stale, missing, overlapping, truncated, or unsafe
content blocks success.

The manifests and receipts never become later `.github` commits. Before S0
activation, the separately authorized public execution proxy must provide a
protected evidence-finalizer workflow on its protected default branch. It has
read-only access to `.github` and all source repositories; its only writes are
`id-token:write` and `attestations:write` to the proxy repository's GitHub
artifact-attestation store. A commit-SHA-pinned `actions/attest` signs a custom
in-toto predicate containing the complete canonical record. The subject name is
`rep120:<target-repository-id>:<series-id>:<record-id>` and its subject digest is
the record's SHA-256. The public proxy causes the bundle to be stored both by
GitHub and in the immutable Sigstore Public Good transparency log. Validity
requires an OIDC certificate for the exact proxy repository ID, protected
workflow path/ref, and source commit.

Append uses one non-cancelling concurrency group per series and strict compare-
and-swap against the verified attested chain tip. The finalizer reconstructs
evidence from protected GitHub state: an identical record is an idempotent
no-op; the exact next record is appended once; any conflicting digest or signer,
duplicate logical record, gap, or out-of-order unit fails closed. Readback must
verify the GitHub attestation, custom predicate, subject, signature, OIDC
identity, transparency-log inclusion, attestation ID, log index, and bundle
digest. After P4 the same finalizer builds and attests the Closure Manifest from
read-only protected state and the complete receipt chain. It performs no source,
target, PR, branch, Ruleset, check, release, or content mutation.

This evidence sink is a P0 pre-activation gate, not an assumed service. The
exact public proxy repository ID/name, Ruleset, protected workflow blob, pinned
action digest, predicate schema, OIDC claims, API readback, public-log inclusion,
duplicate/conflict rejection, and retention/export procedure must be canary-
proven first. Check output, an expiring Actions artifact alone, Jira, and
Confluence may index or copy the receipts but are not the immutable trust anchor.

### 6. Explicitly deferred convergence work

This ADR decides only the proposed `.github` repository-local default-off
controller and capability boundary. The following remain open and cannot be
inferred from D1, S0, any P unit, or C1:

- replacement of the live reciprocal `.github <-> Supplementary` Required-
  Workflow polling through a separately authorized, public, protected,
  secret-free execution proxy; private `shared-assets-lit` remains the authoring
  root but is never a public target's runtime source;
- migration to one stable aggregate required-check context and removal of
  superseded leaf requirements;
- Source-App and successor-App creation, scope verification, Environment
  protection, secret/variable cutover, rollback, rerun-horizon retention, and
  token drain;
- controlled stale run, branch, and worktree cleanup with preservation rules;
- three consecutive clean reference changes, including a complete
  Collection-to-Container release path;
- bounded canary evidence with exact telemetry and zero unauthorized human or
  bypass action;
- small-batch fleet rollout, rollback observation, final fleet reconciliation,
  and evidence acceptance; and
- final ADR status promotion, technical acceptance, ISMS acceptance, or any
  certification claim.

The intended one-way DAG and aggregate check are separate protected changes.
The aggregate target is one visible `promotion / aggregate` job: a protected
public-proxy Required Workflow supplies source authenticity, and a repository
required-status rule requires that same context from GitHub Actions App ID
`15368` with strict base freshness. The old `repository / quality` requirement
and Supplementary gate remain until an additive Evaluate/Active canary proves
one job satisfies both mechanisms and becomes stale after a base advance.

Ruleset workflows directly re-evaluate only `opened`, `synchronize`, and
`reopened`; GitHub ignores their `types` filters. Because this system supports
Draft and mutable authority state, a separate protected, non-required listener
is mandatory. It authorizes at most one bounded rerun for a new exact
Ready/edited state digest, under an immutable authorization and minimal rights;
it cannot request another review or emit the aggregate itself. If that contract
is not separately accepted, Draft support is removed and promotion PRs must be
opened ready and converge within the initial aggregate window.

The repository-local push trigger and temporary S0 bridge must not be
misrepresented as implementation of the permanent DAG or aggregate.

## Acceptance gates

This ADR remains Proposed / Implementation Pending until all applicable gates
are supported by immutable evidence:

1. D1, S0 implementation, S0 activation, every P unit, and C1 have complete,
   non-overlapping Coverage Manifest entries and current-head independent
   review.
2. Every branch transition is a normal protected merge with exact parent, tree,
   signature, ruleset, and no-bypass readback.
3. C1 is installed with `RELEASE_RECONCILIATION_ENABLED` absent and creates no
   Environment wait, secret access, token, PR, or review dispatch.
4. Credential, precedence, Environment, permission, drain, historical-rerun,
   and rollback probes pass before the bounded canary.
5. Enabled no-delta, active-head, consumed-head, duplicate-event, newer-event,
   cancellation, timeout, pagination, malformed-history, source-drift, and
   over-limit cases converge or fail closed exactly as decided.
6. The one-way DAG and single aggregate gate are live and the reciprocal cycle
   and superseded leaf requirements are absent.
7. Cleanup, three references including Collection-to-Container, canary, and
   fleet evidence pass their independent acceptance gates.
8. Only then may the maintained ADR set be considered for a separately reviewed
   status promotion. No implementation step promotes its own status.

## Consequences

- Hourly and manual repository-local self-dispatch are removed from current
  refs once C1 is merged, while historical rerun exposure remains explicitly
  controlled rather than denied.
- No-op and duplicate decisions occur before approval or write authority.
- One static lease and exact history markers bound each repository/SHA to at
  most one eligible mutation owner.
- Source-read and successor-write capabilities are separated without breaking
  the current Supplementary reader or mutating the organization key by default.
- Complete review inputs remain bounded without truncation; sequential
  pre-staging and Coverage Manifest reconstruction make large recovery explicit.
- The design adds implementation and evidence cost. That cost is accepted in
  preference to hidden polling, ambiguous ownership, stale review reuse, or
  protection bypass.

## Evidence references

- Issue `lightning-it/.github#564`
- Protected recovery PRs `lightning-it/.github#565` through `#575`, including
  source-binding PR #566 and transition PRs #569–#572
- PR #575 protected merge receipt and independent readback
- PR #576 fail-closed receipt; Required runs `34143008702` and `34143008743`;
  automatic no-rerun helper `34143164872`
- REP-120 canonical bounded-idempotent orchestration decision
- Generic bounded-review-unit and Coverage Manifest authority
- Source-first DAG and aggregate-gate migration plan
- GitHub artifact-attestation trust model and public Sigstore transparency-log
  behavior: <https://docs.github.com/en/actions/concepts/security/artifact-attestations>
- GitHub `actions/attest` custom-predicate, subject-digest, permission, and
  bundle contract: <https://github.com/actions/attest>
- GitHub documentation for workflow triggers, concurrency, Environments,
  workflow reruns, variables/secrets, and App installation tokens
