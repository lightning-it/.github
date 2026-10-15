# Workflow target catalog

Version: **1.0.0**. Status: **defined, runtime migration pending**.
The [process contract](workflow-target.md) remains authoritative. This catalog
assigns its functions to concrete entry points; it does not activate them.

## Common source

The target uses these four source workflow files in `lightning-it/.github`:

| Source path | Purpose and functions | Trigger and result | Delivery state |
| --- | --- | --- | --- |
| `.github/workflows/repository-quality.yml` | Validate this source repository; WF-01/02 | PR, protected push or manual run; deterministic profile result | Existing and active |
| `.github/workflows/openssf-scorecard.yml` | Assess repository posture; WF-02 | Existing schedule, relevant setting change or manual run; posture report | Existing and active |
| `.github/workflows/change-control-required.yml` | Common protected current-revision policy; WF-02/03/05 | Native required-workflow PR events; verify current quality/security and the existing author/risk review route; bind normal release approval to the exact promotion | Reference implementation delivered in source; native admission pending |
| `.github/workflows/delivery-operations.yml` | Prepare promotion/branch-sync PRs and finalize release archives; WF-04/07, verification support for WF-06 | Trusted native delivery events through an immutable consumer call; one PR per repository/target and one final archive package per accepted promotion | Metadata receiver implemented for reference; promotion/archive jobs pending |

This is the initial implementation assignment. A necessary additional entry
point requires an explained function, caller and ownership change in the
versioned catalog; a smaller file count never replaces functional acceptance.
CodeQL and the native reviewer services remain separately classified GitHub
services. They are not additional repository YAML definitions.

## Consumer boundary

The required change-control workflow runs in the consumer's visibility and
permission context. Management binds the accepted immutable source. Source
changes are checked by the previously accepted policy; a candidate cannot
select its own authorization implementation.

Consumers keep their applicable product tests, build, installation, scans,
signing and publishing in their own repositories. A small `delivery.yml`
caller selects the accepted immutable `delivery-operations.yml` source with
explicit inputs and secrets. Private configuration/results stay private.
Shared Assets distributes those callers and configuration. Its distribution
entry point consolidates existing type-specific distributors only after their
real consumer behavior is verified. It does not install verifier code into the
public source or maintain another independent common verification engine.

## Change control and review

The common change-control entry point owns classification, applicable quality
and security evidence, current-head review, and final gate reporting as jobs
or protected modules. Applicable human reviews stay native Copilot; the exact
authorized Release App retains its protected Codex route. Existing governed
exemptions and separately approved bounded pilots must be preserved explicitly.
No generic second AI review, automatic remediation or provider retry is added.

A pure main promotion verifies native acceptance of every ingress change. It
never obtains a cumulative second AI review. Normal human authorization uses
one native approval with self-approval enabled and zero mandatory classic PR
approvals. The technical Security route remains separately authorized.

A missing review, unresolved finding, unknown identity, failed quality/security
result, stale tuple or exhausted provider budget blocks the applicable path.
A new head invalidates the relevant results. Duplicate events cannot reserve
another funded request for the same finalized head.

## Promotion and archive lifecycle

Delivery operations prepare or update one develop-to-main PR. They grant no
human approval. Branch reconciliation also uses a normal PR: an unprotected
integration branch joins both protected tips and proves the resulting tree,
without direct writes to protected branches. Source-only ancestry joins are
not real product changes for reference acceptance.

After the authorized release, the protected finalizer collects complete native
ingress, approval, test/security, integration and applicable published-artifact
proofs. Develop PRs retain their native history without a duplicate durable
release package. Product publishing failures and archive failures remain
visible failures; already published artifacts are not described as unpublished.
Release acceptance requires the complete final package and its verified archive.

The finalizer must persist one unique archive reservation before its single
create attempt and serialize every archive entry point for the same consumer
repository/target. Duplicate or interrupted delivery verifies that reserved
object read-only. An uncertain write or unavailable lookup never triggers
another create automatically. The existing Hetzner storage primitive is
`scripts/lit-release-archive.py`; it is not the reservation authority.

## Coupled replacement and acceptance

Legacy review, refresh, rerun and repair entry points migrate together to
change control. Legacy promotion/authorization/backmerge paths migrate together
to delivery operations. Technical helper code is retained as bounded jobs or
modules where needed. Remove an old receiver only after every actual caller
and generator has a functioning replacement; the current Collection release
helper is subject to that rule.

Activation remains blocked until source/management, private distribution and
the Collection reference have actual positive and negative acceptance. Require
one-person normal release, stale/failed/missing evidence rejection, duplicate
request/PR prevention, private output boundaries, no dependency cycles, exact
published-artifact verification and immutable archive retention. Then require
three real changes without necessary correction, a bounded canary and waves.
The POC transition ends only for the accepted scope.

## Implementation boundary: protected change control

`change-control-required.yml` now supplies the common reference runtime. It
loads code from the native defining workflow SHA, never consumer candidate
code. Management still has to admit that immutable source as a Required
Workflow; the existence of this file grants no production acceptance.

The reference source implements the author matrix, native current-head Copilot
verification, one native-run reservation before a funded request, the retained
isolated complete-request-budget Codex gateway, strict Renovate provenance,
exact ancestry checks and aggregated native ingress verification. The normal
promotion job uses the one-person approval environment, followed by a fresh
current-tuple and quality check. Unknown identity, stale metadata, findings,
failed checks and ambiguous request outcomes block.

Distribution receipt verification requires the protected source-run-produced
full file manifest. Existing distributors must be migrated jointly before that
route is admitted; an App author or PR body alone never grants an exemption.
The empty reference accepted-source list deliberately grants no promotion.
Delivery operations, private wiring and native staged acceptance remain open
until their actual implementation and observed results are recorded here.

The reference also includes the metadata-only job in `delivery-operations.yml`.
It refreshes the original native Required Workflow's final verifier after review
or PR metadata activity. It cannot publish acceptance or retry a consumed model
request. A draft-to-ready event may start an original review job only after the
complete native attempt history proves that no funding step ever started.
Promotion creation and archive finalization in this entry point remain pending.

Only the top-level native Required Workflow namespace may authorize a change;
`change-control-required.yml` has no reusable candidate-callable entry point.
The native defining-job context is supported on GitHub.com and was observed in
run 38684126267; a sanitized fixture records that observation. These context
fields alone do not make a candidate source trusted. Native source/run origin,
exact associations and the accepted central lineage remain independent guards.

Classification persists one operation snapshot in native GitHub Actions state.
Every later review step, subject materialization and final verifier must match
that complete snapshot. A changed head cannot be reviewed under an older
reservation. The final gate revalidates the applicable review after quality and
requires a configured self-approvable native environment plus an actual human
approval for promotion. The same unchanged operation can reuse its verified
native approval without demanding a second person or duplicate approval.

These small native controller records stay within GitHub's check/run history;
they are not a second develop release package or a WORM archive. The one durable
seven-year release package still belongs exclusively to accepted main promotion.
Native proof availability and private consumer behavior remain actual rollout
acceptance criteria; reference code and local tests do not establish them.
