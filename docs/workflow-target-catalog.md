# Workflow target catalog

Version: **1.1.0**. Status: **public reference qualified; private rollout and complete release archive pending**.
The [process contract](workflow-target.md) remains authoritative. This catalog
assigns its functions to concrete entry points; it does not activate them.

## Common source

The target uses these five source workflow files in `lightning-it/.github`:

| Source path | Purpose and functions | Trigger and result | Delivery state |
| --- | --- | --- | --- |
| `.github/workflows/repository-quality.yml` | Validate this source repository; WF-01/02 | PR, protected push or manual run; deterministic profile result | Existing and active |
| `.github/workflows/openssf-scorecard.yml` | Assess repository posture; WF-02 | Existing schedule, relevant setting change or manual run; posture report | Existing and active |
| `.github/workflows/change-control-required.yml` | Common protected current-revision policy; WF-02/03/05 | Native required-workflow PR events; verify current quality/security and the existing author/risk review route; bind normal release approval to the exact promotion | Root reference natively qualified and selected at immutable source `6845abfda6069e33b3939736c88177dabc9bf315`; private admission pending |
| `.github/workflows/delivery-operations.yml` | Refresh original native control and signal relevant integrated changes; WF-03/04 support | Review/metadata invalidation; successful native quality of a current protected Develop push dispatches Main-bound preparation | Root event adapter implemented; native event acceptance and timer retirement are separately recorded. An unadmitted consumer has no acceptance authority; full archive producer pending |
| `.github/workflows/review-events.yml` | Unprivileged review-event signal; WF-03 support | Native review/comment activity; checkout-free signal only | Delivered; no acceptance authority |

The protected management entry point owns privileged PR preparation. The
existing consumer delivery workflow signals it directly after successful native
quality for the actual current protected Develop push. It checks the native
repository, workflow, event, revision and successful quality job before loading
the existing App credential. It rechecks freshness before dispatch; stale events
do nothing. PR and fork runs, failed/skipped checks, other workflows and manual
producer reruns cannot signal preparation. No timer is required in the target.
The App token allows only Actions dispatch in Management; it cannot mutate source
contents or authorize a release. The protected Main preparer independently
checks current target tips, its single-target App token, admitted source and
native ingress evidence, then creates or returns at most one PR. It
cannot approve or merge its own PR and cannot change branch rules. In the real
[ancestry operation 888](https://github.com/lightning-it/.github/pull/888),
one native preparation created exactly one App PR and the second returned that
same unchanged PR. Required control, source quality and CodeQL passed before
a regular merge preserved both parents and the exact Develop tree, without a
model request. This qualifies the ancestry/idempotence case only. Normal content
promotion, private scopes, full archive production and staged rollout still
require their own actual acceptance. The old Management cron and its observer
are retired in the paired Management change; source presence alone does not
prove that both sides have been deployed. This event route adds no workflow
file or AI review. Its behavior follows GitHub's
[workflow completion event](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#workflow_run)
and explicit workflow-dispatch model.

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

The protected common Terraform path runs full init/validate itself; a candidate-owned
product-validator replacement cannot substitute for it. Dependency downloads
receive only canonical provider metadata admitted against the protected base;
private candidate validation stays offline and credential-free.

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

The [operator runbook](protected-runtime-operations.md) explains finalization,
normal one-person approval, blocked operations and consumer privacy.

## Promotion and archive lifecycle

The protected management preparer creates at most one develop-to-main PR using
the admitted public verifier definitions. It grants no human approval. Branch reconciliation also uses a normal PR: an unprotected
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

The source implements native Copilot, governed Renovate, ancestry and
promotion-evidence verification. The next reference includes the exact
Release-App Codex route with its isolated complete-request gateway. That source
still requires separate native qualification and admission; it never falls back
to Copilot. Promotion preparation, release/archive operations and private
distribution remain unadmitted; this is no production-ready scope.

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

The source-owned generated-lock registry contains exactly one descriptor for
`lightning-it/container-ee-wunder-devtools-ubi9`. It binds published Shared Assets
`v1.52.5` (`6c14231ff7a484cae8def33d3d2ac4a9b4733473`) and Target tree
`dca77eb5067263307ba830a2c4e53d36046e0760`. Its descriptor SHA256 is
`941118bdf54271158df6cfb2972934b68328fe6cd8b95f4a3b29c812236b6b60`.
The canonical five-file manifest is
`e0256a9a1fb2ad8eb47c5f02fcf68647e040d47910aa2b7c14796270dccbfeb8`. This declaration
becomes effective only after the reviewed Common commit is independently
selected through native Management. All other targets and exclusions remain
rejected. Candidate labels, comments, environment values and consumer
configuration cannot register or override these hashes.

The narrow protocol records the named lock as **not reviewed by Copilot**; it
never invents complete file coverage. Its source-owned descriptor binds the
whole Target Git tree and every canonical package/lock/workspace/build input's
mode, Git blob, size and SHA256. The controller resolves the head commit's actual
`tree.sha`; a commit ID is not a tree ID. Any changed tree needs a newly reviewed
descriptor. Source authenticity is an externally reviewed admission fact, not a
claim of runtime private-repository access. Private evidence stays with its
existing authorized reader; public source retains only permitted immutable
metadata/hashes and sanitized fixtures, with no new cross-repository credential.

The observed native exclusion rendering is parsed strictly and retained in the
ordinary version1 `copilot` proof's additive `evidence` member. Unknown paths,
reasons, counts, duplicate sections, malformed or contradictory native frames and
findings still block. Before final acceptance, the existing current-PR/base/head
native product checks must all succeed, including the complete frozen-install
container build and Trivy. The exact admitted product tree binds pinned pnpm,
package/workspace integrity configuration and execution seams; Common does not
introduce a second generic lock/SRI validator. A descriptor is neither a review
budget reset nor release/architecture qualification. Legacy proof envelopes and
promotion ingress consumers retain their existing source/binding/route checks
and whole-proof digest. No workflow or provider retry is added; source publication
alone does not activate the descriptor in a consumer.

GitHub's active native PR rule enforces resolved conversations directly at
merge time. This handles resolve and unresolve without a missing Actions thread
event, a custom human permission engine or a new repair/polling chain. The
common verifier requires that live native guard and zero mandatory classic
human/CODEOWNER/last-push approvals. Native GitHub permissions control who can
resolve a conversation. One authorized person can perform all human actions.
The AI evidence job does not falsely claim that a cached thread state is current.

Native report publication may finish after its service run: the observed run
38705673721 ended four seconds before review 5530268361 was submitted. Its
`updated_at` is therefore not a review-publication deadline. The verifier still
requires one successful same-PR/current-head native service producer and one
authenticated complete App review. The observed blue native verdict can carry
nonzero findings; those findings remain bound to their native conversations.
Explicit file-coverage prose is normalized for rendered whitespace, so wrapping
a partial report cannot turn it into an absent report.

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

The promotion verifier reads and authenticates one native ingress proof at a
time under fresh physical/cgroup/JSON admission. It discards the full decoded
proof and retains its source, run, attempt, artifact name, route and SHA-256.
The compact references share a remaining byte/node reservation. Full release
packaging is a separate producer: it must retrieve the exact referenced bytes,
verify their digests and stream them into the one final package. References are
not a substitute for that package or its seven-year archive acceptance.

These small records remain native Actions evidence, not a second durable develop
release package. The one seven-year package belongs to accepted main promotion.
Actual private behavior, native source admission and positive/negative staged
acceptance remain required. Local tests and source presence alone grant none.

### Protected exact-revision runtime

The common source materializes the complete Git integration and protected base
instructions as data. Candidate code is never imported or executed by the
review controller. The existing pinned Codex Action uses the bounded loopback
gateway and protected model/token/cost profile. Root-owned source and receipts,
read-only client execution, prestarted deterministic collection and privilege
removal preserve the existing SINGLE boundary. No engine or sudo is restored
after the client drops privileges.

SINGLE binds a complete inline review to one model response. The gateway sets
`tool_choice: none` in the actual counted and forwarded request, and uses the
same policy when authenticating replay. It retains the complete client tool
schemas in the request identity. An unexpected provider tool-call response is
terminal and is never delivered to the agent for execution. The general bounded
transport keeps its separately governed tool-capable behavior; this restriction
applies explicitly to the protected SINGLE caller. No second request is granted.
The [Responses API tool-choice contract](https://developers.openai.com/api/docs/guides/function-calling#tool-choice)
defines this mode independently of prompt wording.

A native successful producer may supply a cached response only for identical
complete metadata and the same immutable central source. The protected gateway
also compares the actual normalized client request, including instructions and
tools, before replaying the original real response bytes. That path performs
zero new counting or inference calls. Changed inputs, failed/unknown reservations
or unauthenticated producers block. Native evidence carries digests and real
response bytes separately, without duplicating the full instruction bundle.
Finalization requires the current native run's successful collection/export;
an arbitrary earlier metadata match cannot authorize it.

Finalization selects the latest actually executed producer attempt. A newer
failure, cancellation, pending execution or missing receipt cannot fall back to
an earlier success. A verifier-only rerun may inherit the last actual successful
producer. The model-visible workspace is constant across isolated hosted jobs;
the real run ID remains in root-owned state. Session cache hints are omitted
from both the forwarded request and its hash. Model-visible context, instructions,
tools and input remain bound; any changed review context still blocks replay.

Fresh user, developer and system messages also omit their client-generated
history IDs from both the actual forwarded body and its hash. The pinned Codex
0.160.0 client assigns UUID-based IDs to those messages in each session and
retains prefixed IDs on the wire. Their roles, order and complete contents remain
unchanged and hash-bound. Assistant IDs and tool-call/reference IDs are retained.
Existing server conversations and previous-response references remain forbidden.
See the pinned client's
[history ID assignment](https://github.com/openai/codex/blob/rust-v0.160.0/codex-rs/core/src/session/mod.rs#L3473)
and [wire preparation](https://github.com/openai/codex/blob/rust-v0.160.0/codex-rs/core/src/client.rs#L1010).

A failed client step reports only a source-allowlisted category from the sealed
gateway failure receipt. It exposes no request, response, headers, credentials or
arbitrary exception text. This diagnostic cannot change the failed conclusion,
perform a provider request or authorize a retry.

Git fetch preserves ancestry while filtering historical blobs; only needed
current diff and instruction blobs load lazily. A non-UTF-8 textual patch is
represented reversibly as a JSON string mapping code points to original bytes.
Its original byte length/digest remains bound. Gateway installation and these
preflight checks complete before reserving an inference slot.

Opening or reopening a nondraft final head can request its one paid review.
Intermediate synchronization cannot fund review until a native ready transition
after that head's run explicitly finalizes it. A stale native generation cannot
spend a later ready event. Draft-to-ready refreshes the original classification;
attempt history still forbids a second consumed request.

The authorizing YAML excludes ordinary branch-triggered invocations while
remaining active for the native ruleset source. GitHub documents that ruleset
execution ignores event filters, including `branches-ignore`. Native reference
testing must confirm this behavior before source admission; the filter grants
no skipped-check acceptance and no candidate workflow-call authority.


## Preserve accepted proof lineage across source updates

The externally selected central source explicitly retains its immutable proof
predecessors in `.lit/workflow-source-lineage.json`. Its policy reader derives
accepted native proof sources from that protected central list. The reference
consumer's `accepted_sources` remains empty, so the previously selected immutable
reader can still process a new base before cutover or during rollback. Legacy
consumer entries, if present, must be a subset of the selected central allowlist;
they cannot nominate an unknown source or select the current verifier.

A new verifier must not invalidate authentic current-tuple ingress proofs merely
because their previously selected producer was an earlier retained version.
Revision, native producer, route, complete evidence and success checks still
apply; failed or stale results never become accepted predecessors.

A source update is reviewed and integrated through the prior selected source.
Management then admits the new immutable source through its exact reviewed native
plan. A candidate's lineage file has no effect on the authority judging that
candidate. This two-stage transition preserves old valid evidence without letting
a candidate select or authorize its own verifier.

Management source-advance planning validates the central lineage without
requiring consumer entries to preselect their judge. The protected native
reference preparation checks the selected predecessor and forward-only source
ancestry before changing the main rule. The existing rule remains active until
the exact reviewed transition is applied; caller installation alone grants no
scope adoption.


A replay candidate is not current acceptance. An authenticated prior successful
provider response may be installed while the new producer is pending or after a
pre-provider metadata failure. The gateway still compares the entire actual new
client request before returning those exact original bytes, without another
provider call. Final acceptance separately requires the latest actual native
producer to finish collection and export successfully; a failed or pending
current producer cannot fall back to an older successful acceptance.


Common Terraform checks run offline and without credentials. They validate the
protected repository type, required HCL layout and formatting. Provider install
and semantic `terraform validate` remain mandatory in the separately verified
native product-quality workflow declared by the protected consumer policy. The
ordinary repository validator continues to run init and validate; a successful
common format check cannot replace a failed product gate.

Installing the metadata caller does not activate a POC repository. When both its
native common run and an enforced common workflow rule are absent, the helper
makes no change and grants no acceptance. Once an enforced rule exists, a missing
native run remains an error; existing evaluate runs are still refreshed normally.

The metadata receiver pins its reviewed helper to an immutable ancestor of this
source update, including the nonauthorizing behavior for unadmitted consumers.
It can only refresh the original independently selected native control; it does
not admit its helper as a verifier or alter the previously accepted source that
judges this update. Consumer calls to this source therefore use the same fixed
helper without copying private configuration or control code downstream.

### Exact owner-accepted Shared Assets PR 2658 generated lock

This candidate contains one **owner-accepted, exact-subject descriptor** in
`SOURCE_GENERATED_LOCK_ADMISSIONS`. It becomes effective only through a genuinely
admitted protected Common source. The owner decision alone does not select a
verifier or authorize merge/publication. Consumer metadata cannot register a case.
The separately retained owner receipt has SHA256
`bfeb42e955ad11fcf38313662515b968b4534a8efecdb87d82a7555f0a362f44`;
the accepted qualification projection has canonical SHA256
`c9bb5b0d12b29b09c3665b086b76f0c89791ce20af2998f463a8d674d299fea2`
and file SHA256
`e380856715f009caa1ab65662afad5d9b30f539d51870d0af102815a1e774c53`.
The original human message is
`chat:01a16039-c39f-77f0-9331-67822ff31eb3/01a1607a-a0da-7760-978a-b49759ef467a`.
That decision accepted the evidence only; registration/publication require their
own actual authority and the normal protections.

The separate proposed Source case binds repository
`lightning-it/shared-assets-lit`, PR `2658`, head
`965a9d188af3212fa556644ac2fb54fe15a3a3ff`, base
`b500e5ded3c4117b53516d97e385e4e8147b2ebc`, whole Git tree
`ae6b8b7c79cc26a23f4c05c5c2a4063895d3891e`, and only
`container/overrides/container-ee-wunder-devtools-ubi9/container-toolchain/pnpm-lock.yaml`.
The lock is regular mode `100644`, blob
`a347fcd4fe10e9a9debaefeac852fa56e2e2b033`, 205506 bytes, SHA256
`3a665ed8f2b2780823664a4cac84d8c236b5e147cc21970ae667124cd1fa0ecf`.
All five manifest/workspace/lock/build/Renovate inputs and all seven actual
changed paths remain bound. Other repositories, PRs, branches, identities,
versions, input bytes, additional exclusions and successor heads are ineligible.
The existing Devtools consumer admission is separate and unchanged.

The original trusted review `5606349606` and service `39677277582` remain bound,
including raw-body SHA256
`4fddbee83d801df5000924042edec0f4322d4e727b1a1b124c5ea1985f016229`.
Its lock remains **not reviewed by Copilot**. A future separately qualified
artifact supplement may describe only that exact exclusion; it never invents
complete Copilot coverage, edits the review or reserves another funded request.
Ordinary findings, conversations, current quality/security checks and authority
remain required. Source artifact coverage is recorded separately from Devtools
coverage, and receives current quality evidence only from the normal finalizer.

The one authorized isolated proof, plan SHA256
`72e555fc811c2c242e01b9bd68a8f7fa7fb23b42a3d71ed1c30df7373849fc30`,
completed with one container and one generation, no retries. Node 24.19.0 and
pnpm 11.23.0 in the pinned v1.18.0 tooling EE regenerated from the protected
b500 baseline lock and final manifest/workspace. Output was byte-identical to
this lock. Registry metadata, declared SRI and actual tarball SHA512 matched for
markdown-it 14.3.3, markdown-it 15.0.3 and argparse 3.0.3. Input hashes stayed
unchanged and owned scratch/container cleanup completed. Original receipt SHA256
`7d0f3f45b39ba8f1dcd77428309780e9c08acc831819ecc65e474e671ca18172`,
execution log SHA256
`21c6ed822100c78609c3895525e63bb50dbeefa9059c52e8baaac9768ff24a9b`,
and host envelope SHA256
`5f53c1e5a6e2cd3b09aca1220cc3bae3e198bae990b83d5dcb1fcd50c4e5b1ed`
remain with the authorized private reader. These are local proof facts, not a
published runtime, native policy approval or all-architecture acceptance.

This exact descriptor records the independently inspected, exact-schema
projection and the separately verified explicit owner acceptance of its digest.
The acceptance reference is an externally verified owner fact retained in the
protected Common source; it is not candidate-controlled JSON, a PR label, a
runtime permission engine or a claim that a native human approval occurred.
The descriptor-binding unit test checks the literal registry entry against the
accepted digest. Native API behavior fixtures are synthetic. The separate local
composition harness uses the unchanged literal entry, saved original review and
five original input byte streams; its HTTP/native-run/job/approval metadata are
still offline fixtures. Test counts, exact target hashes and results belong in
the versioned execution receipt, not an inferred native acceptance. A technical
PASS alone never authorizes registration. Failed, missing or incomplete proof,
or mismatched subject/input/plan bindings, cannot qualify this case. "Stale" here
means a binding mismatch; the qualifier implements no general wall-clock TTL.

Activation/publication is outside this local grant. It still needs a real
protected Common publication satisfying its actual Main requirements, an exact
separately authorized Management source-selection plan for Source rule
`25310560`, compatible delivery-receiver admission and an actual supported
native evaluation. An AI-free policy-publication route has not been established.
Old failed runs remain failed; no manual rerun or fake check is introduced.
Main/release holds and the consumed one-review budget remain unchanged.
