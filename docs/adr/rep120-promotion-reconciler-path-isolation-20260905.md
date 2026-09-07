---
id: adr-rep120-promotion-reconciler-path-isolation-20260905
title: REP-120 default-off promotion reconciler and capability isolation
description: Defines the proposed repository-local replacement for the retired hourly promoter, its capability boundaries, and its evidence-gated rollout.
slug: /adr/rep120-promotion-reconciler-path-isolation-20260905/
document:
  status: maintained
  approval_status: proposed
  version: "4.0"
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
- Evidence cutoff: `2026-09-07T15:23:12Z`

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
| R4 — one aggregate required check | Normative target acknowledged; live migration and leaf retirement remain open outside this repository-local controller |
| R5 — one-way workflow DAG | Normative source-first target acknowledged; the live reciprocal `.github <-> Supplementary` authority cycle remains open |
| R6 — complete bounded review units | Exact `1..199999` interval retained; current 324,868-byte single promotion is rejected; D1/A1/C1 and a sealed Coverage Manifest remain pending |
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

### 5. Complete bounded materialization sequence

The stale worktree is not rebased or published. A fresh sequence starts from
the exact protected refs and uses normal protected merges only:

| Unit | Complete ownership | Current diagnostic | Required transition |
| --- | --- | --- | --- |
| D1 | This one ADR path, with current recovery state and explicit open gates | Final D1 bytes/digest must be recorded later in an external immutable receipt after an immutable head exists, avoiding a self-referential hash | Review and merge normally to protected `main`, then protected backmerge |
| A1 | `.github/workflows/current-revision-rerun.yml`, `.github/workflows/supplementary-current-revision-required.yml`, `tests/test_copilot_review_refresh.py`, and `tests/test_supplementary_required_workflow.py` | 156,595 bytes; SHA-256 `7e0d76ecff0989c9bdf3103bb4e77c771b684208b24b5d047978b5bced1cc4b6` for the currently measured blobs | Ruleset/DAG impact review, normal protected `main` merge, exact readback, then protected backmerge |
| C1 | Delete the legacy workflow; add the successor workflow and all four `scripts/release-promotion-*.sh` helpers; update `tests/test_release_app_promoter.py` | Stale code-only develop delta: 176,657 bytes / `983700569ba9d881b5ddf81f2b71e4057e508186a5d85c801d67ca4f069c68df`; post-A1 promotion proxy: 152,332 bytes / `ec8415e909765f763b4ac72bb86ba346f2c1e554ae99e3384c248b1b36c35321` | Fresh current-base implementation, exact tests, normal protected `develop` merge with enablement absent, bounded protected promotion to `main`, then protected backmerge |

The order is strict:

`D1 -> D1 backmerge -> A1 -> A1 backmerge -> C1 -> exact protected promotion -> final backmerge`.

The A1 receipt is reusable only while its four source and base blobs remain
unchanged. Both C1 values are diagnostics, not final receipts: required test
updates and new ancestry evidence change the bytes and digest. The immutable C1
head must reproduce fresh develop-relative and main-relative inputs, each in
`1..199999` bytes. At 200,000 bytes or more the unit stops; no assertion,
documentation, or source byte is dropped to make it fit.

A machine-readable Coverage Manifest must bind protected bases, heads, merge
bases, integration trees, total input, every path and hunk, unit bytes and
digests, policy/prompt/schema digests, workflow authority, review/check receipts,
merge receipts, and byte-identical reconstruction. Every textual byte is owned
exactly once; gaps, overlap, truncation, stale evidence, binary content, or a
zero-byte unit blocks aggregate success.

### 6. Explicitly deferred convergence work

This ADR decides only the proposed `.github` repository-local default-off
controller and capability boundary. The following remain open and cannot be
inferred from D1, A1, or C1:

- replacement of the live reciprocal `.github <-> Supplementary` Required-
  Workflow polling with the approved one-way source-first DAG;
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
The repository-local push trigger here must not be misrepresented as their
implementation.

## Acceptance gates

This ADR remains Proposed / Implementation Pending until all applicable gates
are supported by immutable evidence:

1. D1, A1, and C1 each have complete, non-overlapping Coverage Manifest entries
   and current-head independent review.
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
- REP-120 canonical bounded-idempotent orchestration decision
- Generic bounded-review-unit and Coverage Manifest authority
- Source-first DAG and aggregate-gate migration plan
- GitHub documentation for workflow triggers, concurrency, Environments,
  workflow reruns, variables/secrets, and App installation tokens
