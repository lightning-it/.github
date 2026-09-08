---
id: adr-rep120-promotion-reconciler-path-isolation-20260905
title: REP-120 default-off promotion reconciler and capability isolation
description: Defines the proposed repository-local replacement for the still-present legacy hourly promoter, its capability boundaries, and its evidence-gated rollout.
slug: /adr/rep120-promotion-reconciler-path-isolation-20260905/
document:
  status: maintained
  approval_status: proposed
  version: "6.0"
  classification: PUBLIC
  owner: Lightning IT Documentation Maintainers
  approver: Lightning IT Product Owners
  audience:
    - repository maintainers
    - platform engineers
    - security reviewers
  last_reviewed: "2026-09-08"
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
- Evidence cutoff: `2026-09-08T03:03:47Z`

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

A final read-only CAS at `2026-09-08T02:31:18Z` confirmed the same protected
refs, PR tuple, two Required failures, Rulesets and clean local successor. That
receipt made no mutation and granted no lifecycle authority. Subsequent local
S0 materialization then exposed a cryptographic self-reference in Version 5.0:
the protected policy was required to embed the ordered P4 source/destination
blob table while P4 also owned that policy's `active -> consumed` blob change.
Embedding the policy's own raw blob, or a manifest digest whose bytes embed
that raw blob, cannot be materialized without a forbidden hash fixed point.
The same cycle exists transitively if the Core embeds a Git-tree, diff, unit,
series, or reconstruction commitment whose bytes include the actual policy.
Version 5.0 and its preflight-v2 tuple therefore remain historical local
evidence and are **NO-GO for execution**. This Version 6.0 is a normal local
successor; it is not an amend and is not yet protected evidence.

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
| R5 — one-way workflow DAG | Private `shared-assets-lit` cannot protect public `.github`; a separately selected and authorized public execution proxy is required; the live reciprocal `.github <-> Supplementary` cycle remains open |
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
`main`, manually rerun, closed/reopened, force-pushed, or bypassed. The owner
has authorized exactly one bounded lifecycle through fresh review: Draft,
retarget to protected `develop`, merge the action-time exact protected
`develop` into the clean corrected-ADR branch without amend or rebase, verify
ordered parents/result tree, make one normal push, mark Ready, and obtain one
fresh current-head review. A pinned local validation plus a fresh action-time
CAS and versioned preflight must pass before the Draft mutation; any tuple
drift invalidates the preflight. This authority ends at fresh review. It does
not authorize an old rerun, reopen, force-push, bypass, intermediate review
request or the later protected merge. After green Required checks and review,
the eventual normal merge/readback to `develop` remains a separately authorized
transition. This ADR remains Proposed and Implementation Pending after that
future merge.

The earlier authorization for PR #575's one Draft-to-Ready transition is
consumed and cannot authorize PR #576. The PR #576 authorization is recorded in
`issue564-owner-decisions-20260908-v1.md`; it uses one Draft-to-Ready cycle so
retarget, ADR correction, and the action-time protected-develop merge into the
branch produce one final reviewable successor head rather than multiple
intermediate review requests.

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
Authorization Manifest Core for the complete main series seal every unit
ID/order, every logical predecessor/result boundary, every ordinary
source/destination blob and mode transition, the sole normalized policy
transition, per-unit limit, maximum unit count, terminal unit, and logical
reconstruction digest. It contains no future runtime claim or direct/transitive
actual-policy-derived Git commitment. The protected
policy contains the exact Core digest and runtime envelope, but never embeds
the ordered unit table or a raw hash of itself.
The one-path activation PR has its own Coverage Manifest entry, exact current-
head review, Required checks, normal protected merge, and source/tree readback.
Here, one-path means that only the protected policy path changes. The
`inactive -> active` transition may also populate the sealed series ID, epoch,
expiry, principals, and exact Core digest; it must not change a workflow,
helper, or test.

Manifest sealing also requires both terminal P4 phases to be freshly projected.
P4-M's Required-Workflow source, coupled test and consumed target-main policy
are indivisible; P4-D is the mandatory protected-develop finalization, not a
partition escape. Each canonical review input must independently be
`1..199999`. If either is `0` or at least `200000`, activation is NO-GO: the
policy remains `inactive` and S0 is redesigned before a replacement Core is
sealed.

S0 is a temporary, protected, read-only bridge for serial bounded
feature-to-`main` pre-stage PRs. It contains no PR/SHA/run-specific exception.
Its policy is read only from the exact current protected
`develop@WORKFLOW_SHA` and binds schema, series ID, epoch, expiry, repository,
source/target refs, a `prestage/` prefix, allowed author/App classes, the exact
Authorization Manifest Core digest, canonical diff format, byte ceiling, and
the exact monotonic state enum `inactive -> active -> consumed`. The Core, not
the policy, binds the exact starting-main commit/tree and maximum unit count.
`consumed` is globally absorbing for the repository: the bounded authority
ledger is enumerated before activation/reservation, and no later Core, series,
tree, blob, base, source, expiry or replay can create another active root.

The complete ordered unit and ordinary path/blob/mode table lives only in the
separately attested Core. Each projected target-main content boundary uses a
domain-separated `rep120-logical-content-tree-v1` projection over the complete
closed recursive target-main leaf inventory, including unchanged paths, from
NUL-delimited full-tree Git enumeration under the bound object format. Missing,
extra, duplicate, unparseable or unsupported entries reject. Every ordinary
entry retains exact presence, path, mode and raw Git blob. The sole policy entry
retains presence, path, mode, state, normalization schema and normalized digest,
never its actual Git blob. Absence is explicit. The projection SHA-256 is never
represented as a Git tree OID.

Each target-main unit uses a domain-separated
`rep120-logical-review-input-v1` projection over its logical predecessor/result,
ordered changes, exact source-path commitments and review contract. The Core
does not claim future full protected-develop commits or trees. P1 resolves its
source only from the protected Activation Receipt; later units resolve source
from the immediately preceding backmerge receipt. P1 uses the Core's exact
starting-main commit/tree; later bases resolve from the preceding main
Execution Receipt. Live protected refs must equal those receipt-derived values.

Future `.lit/main-ancestry.json` blobs contain future merge SHAs and are never
presealed. The Core binds their one closed derivation schema, exact path/mode,
repository, canonical serializer and parent roles. Runtime derives `main_sha`
from the prior verified main merge and `develop_parent_sha` from the exact
protected-develop prestate, then receipts the bytes/blob, two parents, result
tree and signature. The ancestry file is excluded from P1-P4 target-main
ownership and preserved from the main base; this is an explicit dynamic
backmerge rule, not a coverage gap or second normalized policy path.

Every Core predecessor/result, unit, series and final commitment is computed
solely from domain-separated logical records. No raw Git tree, diff, unit/total
digest, byte count or reconstruction commitment whose bytes contain the Core
digest is a Core field. Each logical review input is constructed with synthetic
Git objects; textual replacement inside an actual diff is forbidden.

All policy, Core, logical projection, Coverage and receipt JSON uses
`rep120-canonical-json-v1`: strict duplicate-free UTF-8 without BOM, RFC 8785
JCS bytes and exactly one terminal LF. Raw policy bytes must already equal that
serialization before substitution. Each semantic SHA-256 hashes its ASCII
domain/schema tag, one NUL byte, and the canonical bytes.

Policy normalization replaces only `authorization_manifest_sha256` with
exactly 64 lowercase zeroes after the raw canonical-byte and closed-schema
checks, then hashes the same canonical serialization under domain
`rep120-normalized-policy-v1`. No pretty-print, key order, escape, number,
encoding or other byte variant is normalized into acceptance.
The 64-zero value is reserved exclusively for offline construction and
normalization. Every accepted real Core semantic digest must be non-sentinel;
a real Core whose digest equals the reserved value rejects.

For P4 the Core separates three tuples: protected-develop source is present
`active`/`100644` with its normalized digest; target-main predecessor is
explicitly absent because P1-P3 do not own the policy path; target-main result
is present `consumed`/`100644` with its normalized digest. Semantic
source-to-candidate derivation preserves the selected Core SHA and every field
except `active -> consumed`; the actual target-main Git diff is independently
`absent -> consumed`. They are never conflated. Any unexpected main policy,
second normalized path, alternative sentinel/schema, or raw policy commitment
inside the Core fails closed.

Construction order is templates/logical projections -> Core bytes ->
domain-separated Core semantic SHA-256 -> authoritative Core
create-if-absent/index-CAS/readback -> Core attestation/readback -> actual
policies/Git objects -> post-Core Coverage bytes/semantic digest ->
authoritative Coverage create-if-absent/index-CAS/readback -> Coverage
attestation/readback -> Activation eligibility. Both authoritative store
readback and proof readback must succeed before the successor step. Actual
policy blobs, activation and target-main P1-P4-M diffs/Git trees are
deterministic outputs, never Core inputs.

The unique authoritatively stored and separately attested post-Core Coverage
Manifest is a deterministic materialization receipt, not discretionary
authority. It binds the Core and attestation, exact preactivation
source/starting-base refs/commits/trees,
selected raw active/consumed policy bytes/blobs, actual target-main review
inputs/lengths/digests and projected result trees, derivation schemas and every
logical-to-actual mapping. It contains no invented future source, merge,
backmerge or P4-D commit/tree. Those values exist only in the later protected
Activation, Execution and backmerge receipt chain.

The Core and policy contain no Coverage digest/ID/attestation ID or other
actual-policy-derived value. The protected verifier derives one expected record
identity, rejects zero/multiple/conflicting valid records, recomputes every
value, and never selects the latest. Coverage and the Activation Receipt pin
the exact selected Core and raw active policy blob. Every unit must descend from
that root with the same Core. Swapping only the policy field to another valid
Core, including one with identical normalized policy digests, rejects.

Every Activation, Execution, backmerge, pending and Closure record must pass
the same authoritative append/readback and attestation/readback gate before
its successor. The P4 Execution Receipt binds both phases without collapsing
them: all P4-M
pending/protected-main source, destination, diff, merge, parent, tree and
signature values, plus all P4-D reviewed-candidate `H` and protected-merge `Q`
source, destination, diff, ordered-parent, tree and signature values. The
Closure Manifest binds those plural actual values and the complete verified
chain. Coverage, Activation, Execution, backmerge and Closure records are never
referenced back from the policy or Core.

For each target-main S0 candidate from P1 through P4-M, the protected workflow
binds an open, non-draft,
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
| P3 | Remaining protected-develop divergence, excluding `.lit/main-ancestry.json` and including C1 only in complete semantic workflow/helper/test units | Finishes all non-P4 target-main blobs that still require active S0 |
| P4-M | `supplementary-current-revision-required.yml`, `test_supplementary_required_workflow.py`, and target-main consumed policy | Unsplittable main phase of the single terminal P4 unit |
| P4-D | Exact terminal protected-develop merge: deterministic policy add/add resolution to same-Core `consumed` plus derived ancestry record | Mandatory finalization phase under the same P4 reservation; not P5 |

The Core encodes exactly `ordered_units=[P1,P2,P3,P4]`, so maximum logical
unit count is four. P4 alone has closed ordered `phases=[P4-M,P4-D]`; the
target-main Coverage list contains P4-M, never P4-D. A separate closed
lifecycle-record count covers Activation, each ordinary main/backmerge receipt,
P4 pending, P4-D, the P4 Receipt and Closure. P4-D is neither a fifth unit nor
an optional phase.

Before each successor unit, the prior normal protected `main` merge is read
back and normally backmerged to protected `develop`; all unit inputs are then
freshly recalculated and parallel main units are forbidden. Ordinary backmerges
derive only the ancestry record. P4-D is the sole exception to the generic
`ours` content strategy: it must also deterministically resolve the expected
active/consumed add/add policy conflict to the exact same-Core consumed bytes.

P4 is one indivisible terminal state machine under one non-releasing
reservation: `ready -> P4-M merged/read back -> terminal-finalization-pending ->
P4-D merged/read back -> P4 receipt -> Closure`. Both P4-M and P4-D have their
own complete `1..199999` current-head review input, Required checks and normal
protected merge. P4-D cannot carry any P4-M content and no P5 exists.

The Core's domain-separated `rep120-p4d-review-projection-v1` uses four exact,
pairwise-distinct, construction-only 40-byte ASCII ancestry role tokens:
`PRIOR_MAIN______________________________`,
`PRIOR_DEVELOP___________________________`,
`P4_MAIN_________________________________`, and
`P4_DEVELOP______________________________`. The predecessor ancestry blob uses
the first pair and the result ancestry blob the second pair, preserving the
two-field delta. None is a hexadecimal Git object ID; runtime rejects every
token in every ancestry field. The projection constructs its old active-policy
and new consumed-policy entries using the same sole normalized-policy rule and
exactly 64 lowercase zeroes for `authorization_manifest_sha256`; it never uses
actual Core-bearing policy bytes. Synthetic blobs/diff are built from canonical
projected bytes, never by text replacement, and the Core binds the exact
synthetic diff SHA-256 and byte count.

For runtime P4-D, `D` is the exact protected-develop prestate and `M` the exact
protected P4-M main merge. Mapping the four verified ancestry roles and both
verified policy states back into the construction projection must reproduce
the Core-bound SHA-256 and byte count. The reviewed current-head candidate
merge `H` has ordered parents `[D,M]` and the exact derived tree. The normal
protected PR merge `Q` has ordered parents `[D,H]` and `Q.tree == H.tree`;
fast-forward, squash, rebase and parent reordering reject. Both `H` and `Q`
receive exact OID, ordered-parent, tree and signature readback. Preactivation
fit failure blocks activation; a runtime failure after activation remains
fail-closed in live or `terminal-finalization-pending` state.

After P4-M, a composite-sealed pending record binds its exact protected main
merge, parents, tree and signature. P4-D is ineligible until both its
authoritative store readback and attestation readback succeed. Live main
matching the terminal Coverage target
blocks every new S0 reservation even if that record's attestation is delayed.
Only the identical derived P4-D head may recover a failed finalization; no
intervening main/develop commit, rollback, new series or reactivation is valid.
S0 becomes permanently fail-closed only after P4-D changes protected develop
from the exact authorized active blob to consumed and the terminal receipt/
Closure chain verifies.

P4-M is opened only after every declared target blob outside its own ownership
has reached protected `main`. Its Required Workflow, test and consumed policy
arrive atomically. After P4-D and Closure no part of this series remains: S0 is
globally absorbing `consumed`, and C1 is not deferred to another feature-to-main
pre-stage. Before every activation/reservation the bounded repository authority
ledger rejects a prior consumed/Closure state, a second activation root or a
same-Core `consumed -> active` attempt. A later exact protected
`develop -> main` promotion is new work and cannot finish or reopen this series.

The pre-S0 D1-plus-four-path diagnostic was 178,477 bytes and left only 21,522
bytes of margin. It is not reusable after S0. Every unit is freshly
reconstructed with `git-diff-binary-full-index-no-renames-v1`, independently
reviewed, and accepted only at `1..199999`. At 200,000 bytes or more it stops
and is split by whole workflow/test pairs; no source, assertion, documentation,
or evidence byte is removed to fit.

The pre-activation Authorization Manifest Core binds the ordered unit DAG,
target-main logical predecessor/result projections, receipt-derived source/base
roles, disjoint path/hunk ownership, every authorized ordinary
path/presence/raw-blob/mode, the sole normalized policy path, logical review
inputs, the exact ancestry/P4-D derivation schemas, policy/prompt/schema/workflow
authority, zero gaps/overlap, and final logical target state. The post-Core
Coverage Manifest binds every immediately derivable target-main Git object and
raw review input; it never invents future commits/trees. Each runtime phase
creates and CAS-links an immutable authoritative receipt hash-chained to the
Core and predecessor, reads it back, then attests and reads back its proof
before any successor. It records actual base/head/integration tree, review,
checks, normal merge, signature, parents/tree, and protected backmerge.
After P4-D, a Closure Manifest binds the complete receipt chain and proves final
byte-identical reconstruction. Preparatory and activation units have their own
canonical `1..199999` receipts. A future runtime claim in the Core, a broken
chain, zero-byte, stale, missing, overlapping, truncated, or unsafe content
blocks success.

The manifests and receipts never become later `.github` commits. The accepted
DEC-IA01 architecture makes an external conditional-write/WORM store the
authoritative series store; GitHub attestations and Sigstore are independent
proof/transparency and export layers, not the sole series authority. Before S0
activation, the separately selected and authorized public execution proxy must
provide a protected evidence-finalizer workflow on its protected default
branch. It has
read-only access to `.github` and all source repositories. Its GitHub mutation
permissions are limited to `id-token:write` and `attestations:write`; OIDC must
yield a short-lived, exact-workflow/ref/repository-bound session for the chosen
external writer role. That role may only create the exact series record and
conditionally advance its exact index. It cannot delete, shorten retention,
change Object Lock/legal hold, bucket policy, public access, encryption key,
identity policy or another series.

The external append contract has two independent write-once boundaries. An
exact logical record key is created with provider-enforced create-if-absent;
an existing byte-identical record is a verified idempotent no-op and an
existing divergent record rejects. The closed per-series index is then advanced
only with provider-enforced exact-predecessor conditional write against the
fully enumerated current object/version; missing, stale, ambiguous, forked,
gapped, duplicate, delete-marker or uncertain state rejects until authoritative
readback resolves it. Process-local concurrency is defense in depth and never
substitutes for provider CAS. Versioning and Object Lock Compliance retain each
record and every index version for seven years; mandatory encryption uses the
accepted customer-controlled key profile. Readback verifies object key,
version ID, validator, canonical bytes, semantic digest, checksum, encryption,
retention mode/until, legal-hold state, complete version pagination and exact
record/index linkage. Only that successful authoritative readback permits the
attestation write and proof readback for the same semantic record.

A commit-SHA-pinned `actions/attest` also signs a custom in-toto predicate
containing the complete canonical record. The subject name is
`rep120:<target-repository-id>:<series-id>:<record-id>`. For every record,
including the Core, `subject.digest.sha256` is exactly
`SHA256(ASCII domain tag || 0x00 || canonical record bytes)`; the predicate
carries or lets the verifier reconstruct that exact tag and those exact bytes.
The Core record ID and subject name are externally assigned or derived only
from pre-Core fields, never from the Core digest if the identifier is embedded
in the Core. A record never embeds its own object version/validator,
attestation ID, transparency-log index or bundle locator. Those values belong
to its external seal envelope and may be bound by the next record; terminal
verification queries them directly. The public proxy causes the proof bundle to be stored both by
GitHub and in the immutable Sigstore Public Good transparency log. Validity
requires an OIDC certificate for the exact proxy repository ID, protected
workflow path/ref, and source commit.

Append uses one non-cancelling concurrency group per series plus the external
create-only/conditional-write contract above. The finalizer reconstructs
evidence from protected GitHub state and the complete authoritative store: an
identical record is an idempotent no-op; the exact next record is appended once;
any conflicting digest or signer, duplicate logical record, stale validator,
gap, fork or out-of-order unit fails closed. Readback must verify the external
record/index/version/retention chain and the GitHub attestation, custom
predicate, subject, signature, OIDC identity, transparency-log inclusion,
attestation ID, log index and bundle digest. After P4 the same finalizer builds,
authoritatively appends and reads back, then attests and reads back the Closure
Manifest from protected read-only state and the complete receipt chain. It
performs no source, target, PR, branch, Ruleset, check, release or content
mutation.

This authority/proof stack is a P0 pre-activation gate, not an assumed service.
Qualification order is fixed: first read-only test the existing PGE Hetzner
Object Storage FND without inheriting its product acceptance; if any required
conditional-write, seven-year Compliance WORM, versioning, key-custody, OIDC,
enumeration, export/recovery or negative-canary property is absent or unprovable,
prepare the AWS S3 fallback in `eu-central-1` with Object Lock enabled from
bucket creation, Versioning, seven-year Compliance default retention, a
customer-managed KMS key and exact GitHub OIDC trust. Cloudflare R2 may be an
export/mirror but cannot be the sole accepted authority while S3 Object Lock
and the required KMS contract are absent. Exact provider/account/project,
region, bucket/resource ID, endpoint, key ID, role/principal and OIDC subject
must be resource-bound and canary-read back before activation. Check output, an
expiring Actions artifact alone, Jira, Confluence, GitHub or Sigstore may index,
attest or copy receipts but do not replace the external WORM/CAS trust anchor.

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
6. The acyclic S0 constructor reproducibly proves templates/logical projections
   -> Core bytes/digest -> authoritative Core append/CAS/readback -> Core
   attestation/readback -> actual policies/Git objects -> Coverage bytes/digest
   -> authoritative Coverage append/CAS/readback -> Coverage
   attestation/readback -> Activation ordering. Every later receipt/pending/
   Closure repeats both seal layers before its successor. Tests reject a
   record containing its own store/proof metadata, noncanonical raw JSON,
   an unhashed domain tag, every direct/transitive self-reference, duplicate
   key, alternative role token, a real Core digest equal to the reserved
   sentinel, second normalized path, alternate-Core policy substitution or
   conflicting Coverage/activation root. They separately prove
   P4-M absent-main-to-consumed versus active-source-to-consumed semantics,
   receipt-derived source/backmerge state, all four distinct P4-D ancestry role
   tokens, normalized P4-D policy projection, exact synthetic diff digest/size,
   the `H=[D,M]` and `Q=[D,H]` parent topology with equal result trees, both P4
   byte limits, durable terminal pending, deterministic P4-D resolution and
   global post-Closure absorption.
7. The external authoritative store passes exact provider/resource/OIDC/key/
   retention readback, create-if-absent and stale-predecessor race negatives,
   seven-year Compliance-WORM/delete negatives, exhaustive version pagination,
   uncertain-outcome recovery and independent export/reconstruction; GitHub/
   Sigstore proof mirrors match the authoritative bytes.
8. The one-way DAG and single aggregate gate are live and the reciprocal cycle
   and superseded leaf requirements are absent.
9. Cleanup, three references including Collection-to-Container, canary, and
   fleet evidence pass their independent acceptance gates.
10. Only then may the maintained ADR set be considered for a separately reviewed
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
- PR #576 live CAS pre-read through `2026-09-08T02:31:18Z`, local receipt
  SHA-256 `cf2604201f72ea7c1988226214f41212d13dbf1f38c1cc63fd16145332608734`
- Owner decision receipt for DEC-PR576-LIFECYCLE-01 and DEC-IA01, local
  SHA-256 `99971258ca48af486393cb7c41d4f62e59f4a5211783f32b43e8073c6346dca7`
- S0 policy self-reference decision v1, local SHA-256
  `30e620cf00297f132598166c7517931af89a01a2fd85757fcffc6f3a11008518`
- Fresh residual materialization plan v3, local SHA-256
  `539d91fc78801c346de381e8cb7ce10f6814f435a3be145d7f667b9c368a175a`
- Independent exact acyclic-decision review v1, local SHA-256
  `2ce754e0e9290adb842efbc297d5fa9d9aa80d1bdb24ec6ebec06249bf0a2689`
- S0 provisional prebuild receipt v1, local SHA-256
  `9b6aa18a2a7f16eb4521967ca2b802e4f07628d821e5a9df30946efd64f80022`
- IA-01 provider read-only inventory v1, local SHA-256
  `90d95bc67154aa44eddfa97cb3a01adb25d13452fcf604c69139e2c2b166c495`
- REP-120 canonical bounded-idempotent orchestration decision
- Generic bounded-review-unit and Coverage Manifest authority
- Source-first DAG and aggregate-gate migration plan
- GitHub artifact-attestation trust model and public Sigstore transparency-log
  behavior: <https://docs.github.com/en/actions/concepts/security/artifact-attestations>
- GitHub `actions/attest` custom-predicate, subject-digest, permission, and
  bundle contract: <https://github.com/actions/attest>
- Hetzner Object Lock/Compliance and supported-action profiles:
  <https://docs.hetzner.com/storage/object-storage/howto-protect-objects/protect-object-lock-retention/>
  and <https://docs.hetzner.com/storage/object-storage/supported-actions/>
- Cloudflare R2 S3 compatibility profile:
  <https://developers.cloudflare.com/r2/api/s3/api/>
- AWS S3 conditional-write and Object Lock profiles:
  <https://docs.aws.amazon.com/AmazonS3/latest/userguide/conditional-writes.html>
  and <https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-lock.html>
- GitHub documentation for workflow triggers, concurrency, Environments,
  workflow reruns, variables/secrets, and App installation tokens
