# Workflow target catalog

Version: **1.0.0**. Status: **defined, runtime migration pending**.
The [process contract](workflow-target.md) remains authoritative. This catalog
assigns its functions to concrete entry points; it does not activate them.

## Common source

The target uses these five source workflow files in `lightning-it/.github`:

| Source path | Purpose and functions | Trigger and result | Delivery state |
| --- | --- | --- | --- |
| `.github/workflows/repository-quality.yml` | Validate this source repository; WF-01/02 | PR, protected push or manual run; deterministic profile result | Existing and active |
| `.github/workflows/openssf-scorecard.yml` | Assess repository posture; WF-02 | Existing schedule, relevant setting change or manual run; posture report | Existing and active |
| `.github/workflows/change-control-required.yml` | Common protected current-revision policy; WF-02/03/05 | Native required-workflow PR events; verify current quality/security and the existing author/risk review route; bind normal release approval to the exact promotion | Reference implementation delivered in source; native admission pending |
| `.github/workflows/delivery-operations.yml` | Prepare promotion/branch-sync PRs and finalize release archives; WF-04/07, verification support for WF-06 | Trusted native delivery events through an immutable consumer call; one PR per repository/target and one final archive package per accepted promotion | Metadata receiver implemented for reference; promotion/archive jobs pending |
| `.github/workflows/review-events.yml` | Unprivileged review-event signal; WF-03 support | Native review/comment activity; checkout-free signal only | Reference implementation; no acceptance authority |

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

## Implementation boundary: protected reference control

The initial source implements native Copilot, governed Renovate, ancestry and
promotion-evidence verification. The Release-App Codex route remains explicitly
blocked until its separate complete-request transport qualification is integrated.
It never falls back to Copilot. Promotion preparation, release/archive operations
and private distribution remain unadmitted; this is no production-ready scope.

Only the native Required Workflow namespace may authorize. The defining-job SHA
selects the independently admitted source; an ordinary candidate workflow or a
check name cannot replace it. Classification persists one complete immutable
operation binding. Later steps must still match; oversized serialized metadata
is rejected before any funded effect. A source cutover skips older approval
records rather than mistaking them for the current source.

### Separate native review evidence and live conversation enforcement

The pure Copilot frame/finding validator is retained from protected source
`e698e4313c0aa9de39403788aab2566005200365`; no retired controllers are restored.
It validates the actual native raw and rendered report, rejects unknown/error
frames and body-only previously missed findings, and binds counted findings to
authenticated native comments. The completed native service run must identify
the exact PR/base/head; another PR sharing a head cannot consume this request.

The admitted native CCR v2 frame does not publish a file counter. Do not claim
100% file coverage or invent that metric. An explicit file-count report must
match the actual changed-file count; partial or contradictory reports block.
The [Copilot service excludes some file types](https://docs.github.com/en/copilot/reference/review-excluded-files); product quality and
security checks still cover their applicable functions. Complete materialized
Codex input remains its separate protected review contract.

GitHub's active native PR rule enforces resolved conversations directly at
merge time. This handles resolve and unresolve without a missing Actions thread
event, a custom human permission engine or a new repair/polling chain. The
common verifier requires that live native guard and zero mandatory classic
human/CODEOWNER/last-push approvals. Native GitHub permissions control who can
resolve a conversation. One authorized person can perform all human actions.
The AI evidence job does not falsely claim that a cached thread state is current.

### Events, funding and promotion evidence

The checkout-free, permission-free `review-events.yml` signals supported review,
body-edit and comment activity to the protected/default-branch receiver. Before
acceptance, the candidate must retain that exact independently frozen signal.
Queued receiver concurrency includes the native producer workflow ID, so a
same-display-name candidate workflow cannot replace a trusted invalidation.
The receiver loads one literal immutable helper and refreshes only original
native jobs; it cannot publish acceptance or retry an unknown funded request.

Metadata changes reclassify the original snapshot. Delivered reviews skip
funding; draft-to-ready may start a never-funded request. Native attempt history
rejects consumed or unknown funding slots. The final verifier rereads applicable
review evidence after quality. An unchanged promotion may reuse the actual
native approval from an earlier attempt of the same run, with no second person
or duplicate approval. Failed, missing or changed inputs remain blocking.

For merged ingress, GitHub may remove its old live PR association. Only the
native Required Workflow's persisted operation/proof matched to the actual
merged PR may replace that association. Git object reads stream both pipes under
the existing physical/cgroup/process memory contract and kill child groups on
overflow/deadline; a large change is never truncated into an admissible change.
Distribution file listings must equal the live changed-file count before a
manifest can be accepted; API truncation cannot grant an exemption.

These small records remain native Actions evidence, not a second durable develop
release package. The one seven-year package belongs to accepted main promotion.
Actual private behavior, native source admission and positive/negative staged
acceptance remain required. Local tests and source presence alone grant none.
