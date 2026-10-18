# Operating protected change control

This runbook describes the reference procedure. Repository adoption and fleet
release acceptance remain separate decisions; source tests alone do not admit a
repository. Existing quality, security and product publishing checks remain
required throughout the transition.

## Use one review controller across repositories

Disable the additional Codex Cloud `Review code` / `Automatic review` in each
repository's shared settings, including newly connected repositories. The
centrally governed author/risk route remains responsible for the required code
review. Repository settings override personal preferences; onboarding must check
the explicit repository setting rather than rely on a person's preference.

Keep existing separate security reviews active. If their trigger was `Whenever
code review runs`, use `On PR open` so disabling the extra code review does not
silently disable that security review. This changes neither the mandatory CI
checks nor the normal one-person human approval contract.

## Finish native review delivery in every repository

Apply the same completion procedure to every connected repository, including
those still in the documented POC transition. Use GitHub's native Actions,
review and deployment state; keep private observations in the private context.

1. Wait for the prescribed reviewer to publish the complete result for the
   current finalized input. A completed Copilot service run can precede review
   publication. Resolve actual findings and finish the current mandatory gates.
2. Inspect the review's native signal runs and their following delivery receivers
   across the repository. Include callbacks on the default branch; filtering only
   by the PR commit misses these. GitHub can require genuine maintainer approval
   at both stages. Confirm each relevant receiver has actually arrived and
   finished; an empty pending list alone does not establish that.
3. Complete the relevant native approvals with the same authorized person before
   integration, then inspect the resulting delivery. Identify an unknown or stale
   operation before acting on it. A superseded never-executed callback is history,
   not a reason to purchase another review or reuse acceptance from an older input.

Keep the author/risk matrix, current-revision quality/security checks and normal
one-person release approval. Prepare at most one promotion per repository and
target. Before broad rollout, verify that obsolete callers and generator copies
are removed without removing product tests, releases or separate security review.
A native run list is an observation, not an independent approval or proof that all
asynchronous callbacks have arrived. No extra completion controller is required.

## Finish an ordinary change

1. Prepare the change and run the repository's digest-pinned deterministic
   quality profile. Local validation never calls an AI reviewer.
2. Use a pull request into `develop`. Finish corrections before marking a draft
   ready for review. A synchronization validates the new code but does not by
   itself authorize another funded review.
3. The externally selected native Required Workflow chooses the applicable
   author route. The permitted human route uses native Copilot evidence; the
   exact Release App uses the protected Codex route. Unknown identities,
   incomplete evidence and provider or budget failures block that route.
4. Resolve actual findings, complete the current revision's required checks and
   merge normally. A prior head's result never approves the replacement head.
   Repeated metadata events must not request an additional review of unchanged
   input. Do not fabricate a successful check or switch review identities.

Classic human, CODEOWNER and last-push approvals do not require another person.
Open review conversations remain a native merge condition. The applicable AI
review and technical checks still need to succeed.

### Finalize a correction to an already ready PR

Finish the correction, run the deterministic profile and push the finalized
head. Wait until GitHub has created the native synchronization run for that exact
head. If that existing PR was already ready, perform one real Draft-to-Ready
transition after that run's creation time, in a later timestamp second; equal-second
ordering is deliberately unknown and blocks funding. A completed test does not replace
this explicit finalization. `head-not-finalized-for-funded-review` means that
the native workflow blocked before spending a request; waiting or requesting
another review does not finalize the head. The metadata receiver refreshes the
original verifier after the actual Ready transition. Observe that run rather
than repeatedly marking Ready or rerunning all jobs.

The metadata receiver retains an event until the entire selected native workflow
has finished, including parallel common quality and a final job that may not yet
exist. A completed review job alone does not make GitHub's rerun API available.
While waiting, a closed PR or changed head stops the obsolete event immediately.
The receiver makes one rerun request after completion; it never retries a write
or turns a timeout into review or release acceptance.

After the final Ready transition, first observe any independent Security review
that it has already started. Invoke the exact supported native Security fallback
only if the finalized head has no current or pending Security review, with one
durable request reservation. For qualification, finish intentional Draft/Ready
counterexamples before considering that fallback. Requesting a fallback and then
marking Ready again can start another Security review. This does not change the
prescribed code-review route or enable additional automatic Codex code reviews.

## Approve a normal main promotion

The current protected `main` commit must be an ancestor of the proposed
`develop` head. A normal Main merge creates a new commit; its content being
present in Develop does not establish that ancestry. Before finalizing the next
real change, integrate the current Main into that change's branch and merge it
through the ordinary reviewed Develop PR. Resolve actual conflicts explicitly;
never replace Develop's tree with Main's tree or bypass the ancestry check.
When only history needs convergence and both protected trees agree, the
existing bounded App ancestry operation can prepare its unchanged-tree PR.

If preparation reports content convergence or the reference bootstrap stops
before creating a PR, inspect the actual protected tips and merge base first.
Retain the failed preparation; after a regular ancestry integration, prepare a
fresh plan bound to the new tips through the existing management operation.
This grants no review, merge or normal release approval and adds no retry chain.

The Root reference prepares promotion in a dependent job of Repository Quality.
GitHub admits that job only after the quality job succeeds on the first native
push attempt to protected Develop. PR/fork runs, manual runs and reruns cannot
use the preparation job. The job executes no repository checkout, verifies the
current protected Develop head before credentials and rechecks it immediately
before dispatch. Its App token has Actions write access only to Management.
The review-event receiver no longer subscribes to Repository Quality; ordinary
PR quality completion therefore creates no empty delivery run. Actual review
and PR metadata events retain their existing protected receiver. Preparation
does not approve, merge, change settings or request an AI review.

The Main-bound Management receiver independently checks its target, admitted
source, protected tips and native ingress. An existing identical App PR is
returned unchanged. An open foreign operation, duplicate or closed exact head
blocks; closed promotions for older heads remain history. Its old periodic
observer is removed by the paired Management deployment. A delivered event
adapter alone does not prove receiver success or removal of that timer; confirm
both native results before declaring the replacement accepted. Explicit native
dispatch remains an operator action for a documented blocked transition, with
no automatic paid-request retry.
Other consumers require their own scoped adoption; merely installing a public
caller does not enable this Root-only reference route for them.

The Release App prepares one ordinary `develop` to `main` pull request. The
protected control verifies the integrated changes' native acceptance evidence;
it does not buy another AI review of the cumulative diff. Preparation grants no
human approval.

After the technical review reaches its approval boundary, an authorized person
reviews the exact current operation through GitHub's native deployment review.
The normal environment allows that person to approve an operation they started.
The final control rechecks the current base, head and authorization. It can reuse
that same real approval for the same unchanged operation; a different operation
must not inherit it. There is no administrator merge bypass.

A merely evaluated ruleset cannot enforce this procedure. A deliberately admitted
scope needs an active native requirement bound to an immutable, previously
qualified central source. Candidate code must not select its own verifier.

## Handle a blocked operation

Use the actual current run and failure category to identify the failed condition.
A missing review, exhausted budget, stale tuple, unsuccessful test or security
scan is a blocking state. Restore the missing capability or correct the change,
then follow the governed current-revision path. Do not manually spend another
provider request, use an older successful run or restore retired recovery chains.

Metadata receivers refresh the original protected verifier from actual current
state. Their successful completion is not review or release acceptance. For the protected
Codex route, a native provider receipt must still bind the complete actual request
and its response. Copilot instead requires its authenticated native GitHub service
run, current App review and review comments. These are distinct evidence formats.

Ordinary issue comments are not acceptance inputs and no longer trigger the
receiver. Actual pull-request metadata and unprivileged review signals still
refresh the protected control. Before a merge, wait for the complete current
required run and relevant receivers to finish; individual older green checks do
not prove that a newly started verifier has finished.

Historical ingress has a separate merge boundary. A genuine completed native
success before the merge may be referenced if every later failed attempt is
independently proven to have failed only because that same pull request was
already merged and closed. The exact full operation snapshots must match, and
the sole failed native job/step and its bounded native log must establish that
closure occurred after the merge. Preserve the successful attempt reference and
each later failed attempt explicitly. Unknown, semantic, pre-merge, provider,
budget or metadata failures block; an open or pending change never uses this
historical path. The full accepted binding must still equal the merged PR metadata;
the native merge and closure events must rule out draft conversion or manual
closure since the successful attempt began. Runner timestamps alone do not
establish the cause. The entire second reported by merged_at is ambiguous and
rejected. Authenticate operation bindings before taking the final generation
snapshot; its selector performs no further artifact I/O and rejects unseen
unassociated generations. Take that snapshot as the final network read, after
refreshing both referenced subjects. Re-read the
referenced PR, its merge identity, the current native run and newest generation
after all proof reads; changed metadata, attempts, origins or generations block.
No failed attempt is relabeled successful.

## Keep consumer information in its proper context

Common source definitions are public. Private repository contents, explicit
credentials, model results and internal evidence locators stay in the private
consumer. Callers pin the admitted immutable source and pass only the secrets
needed by the applicable operation. Public collaboration content contains no
private tracker references or internal resource configuration.

A main promotion needs its one complete durable release-evidence package and
verified seven-year immutable retention before release acceptance. Ordinary
`develop` pull requests retain native GitHub evidence and do not create duplicate
durable release packages. Product repositories also retain their applicable
artifact scans, signatures, provenance and verification of published bytes.

## One explicitly approved service-failure recovery

Ordinary first reviews keep their existing budget. A terminal protected Codex
service failure with no delivered result may receive exactly one additional
attempt after an explicit owner request and genuine native one-person approval.
The original provider outcome stays unknown and its allocation is not refunded,
erased or described as free. A second terminal failure blocks again.

The owner posts one `lit-review-recovery/v1` JSON comment binding repository,
pull number, exact head/base, failed native run and attempt. The existing common
quality job verifies this request against the actual native failure and defining
source. A comment cannot grant authority. Only the existing normal approval
Environment, with one eligible user and self approval allowed, authorizes the
additional review allocation. This use of that Environment grants no release
approval; a normal Main promotion still needs its own genuine approval.

Quality now finishes before the review can spend a request. The existing review
job requires the native approval only for a valid recovery request. Native
funding history spans all source/workflow generations: another consumed slot,
a prior delivered result, stale binding, missing authority or changed request
blocks. Reruns cannot obtain another allocation. An already successful complete
request may still replay its original response bytes without new funding or
another recovery approval. The native recovery artifact records the old unknown
allocation and actual new approval; full durable release archival stays separate.

For newly produced failures, the root-owned gateway exports a source/subject-bound
outcome even when the action fails. Explicit transient HTTP429/5xx failures have
a sanitized category; deterministic request errors remain ineligible. Any saved
gateway response or receipt blocks another model allocation, even if its later
collection or artifact upload failed. Completed fully skipped jobs are proven
no-spend. A successful prior result passes the quality preflight to the existing
authenticated replay path, which still cannot fund a cache miss.

Failure records distinguish fixed source-owned HTTP authentication/request,
TLS, network, framing and timeout categories. They also bind the failed phase:
count, token admission, model response, response validation or settlement.
Worker exit codes carry no response body, headers, credential or exception text.
The client's generic high-demand message alone never establishes an upstream
service outage. Older generic failure records cannot be retrospectively decoded.
These diagnostics grant no retry, refund, successful review or release authority.

The single response uses the documented model output capacity, including its
reasoning tokens, rather than an 8192-token cutoff that can consume the entire
output allowance without producing the final review packet. The existing
50-minute overall review policy supplies one shared absolute deadline to token
counting, inference and collection; workers do not receive fresh per-step time
budgets. The native job remains limited to 55 minutes. One request and the
existing one-dollar reservation ceiling remain enforced before model access.

The old immutable source did not export this outcome. The separately commissioned
historical recovery therefore requires an explicit `legacy_unknown_outcome_sha256`
acknowledgment of its exact native high-demand/failure log, that specific accepted
old source, and the same real native approval. Whether an unretained provider
result or cost exists remains unknown; this is an acknowledged historical
exception, not retrospective proof or a fallback for newly produced failures.

No workflow file, retry loop, scheduled task or independent repair controller is
added. Deployment and qualification of this capability remain separate from
this source description. A source upgrade never itself resets a consumed slot.

## Explicit event profiles and independent promotion admission

The LI-357 Shared Assets receiver uses its existing private policy-audit Develop
push completion as a locator. The protected immutable event helper binds its
reviewed target profile, native producer identity, successful named audit job,
protected still-current Develop and the exact receiver source. It then invokes
the same independent native-control verifier used for promotion ingress. A
successful audit without that actual accepted ingress proof grants no dispatch.
Source selection, private execution and approval remain independent boundaries.
Repository rule APIs may omit a genuine organization Evaluate rule, and the
repository ruleset endpoint may return 404 for it. Such missing projections stay
unknown; they are never interpreted as an empty scope or bypass list, nor used
to infer selection. The actual independently selected native Required ingress
is the only evidence locator here. It grants no rule authorization. The receiver
has no administrative credential and grants only a non-authorizing dispatch;
protected Management alone authenticates the complete current rule before effects.

Only after this check may the existing Release App mint an actions-write token
for Management alone. A second full read-only event/proof check precedes its
one dispatch, carrying the exact expected Develop revision. Management selects
its reviewed target configuration, creates a token for that repository alone
and independently authenticates the selected source, all ingress and both tips.
For Shared preparation, the existing Management administration environment first
requires its genuine approval. Its existing private management credential reads
the complete organization-owned rule, including an explicitly empty bypass list;
that exact rule snapshot is rechecked before every PR/ref effect. The secret
never crosses into Shared or Source, and Release App permissions do not expand.
Unknown or changed full rules block preparation. Stale, duplicated or consumed
operations fail or observe their existing PR; no new review, rerun or approval
is created by the event receiver. Normal Main approval remains genuine and
separate. Shared's first evaluation/qualification/enforcement and end-to-end
event acceptance must be observed privately before claiming active operation.
This changes neither Root's quality-job preparation nor its event triggers,
and grants no native scope, archive or fleet admission.

The public Supplementary receiver profile is separately fixed to repository ID
`1103407173`, visibility `public`, `Collection CI` workflow ID `214182490` at
`.github/workflows/collection-ci.yml`, and `Collection / Fast`. Shared remains
fixed to private repository ID `1120841013`, workflow ID `307348847`, and its
existing audit job. Workflow and job names alone cannot substitute for those
native identities. Only a completed successful first-attempt Develop push can
locate evidence. Job IDs are read from that exact run; a missing, duplicate,
failed or foreign-generation job blocks before credentials.

This closed profile does not activate Supplementary's native scope. Its caller
must separately adopt the actually accepted immutable common delivery source
and explicitly pass only the existing Release App key. The existing delivery
adapter can add `Collection CI` completion and a separate promotion call; review
signals keep their own refresh route. No new workflow, timer or credential is
needed. The schema-3 preparation must first merge normally to Develop, then its
actual Develop CI and independent native ingress must pass. A preparation-run
success or receipt JSON alone is not this completion evidence. The fixture
`tests/fixtures/promotion-supplementary-producer-shape.json` is an anonymized
historical API shape, not qualification of a future prepared Develop revision.

The dispatch remains `native-promotion-prepare` with `repository_quality` and
exact `runtime_develop_sha`. Protected Management already has the explicit
Supplementary target and must independently validate its existing administration
approval, current complete organization rule, admitted proof source and protected
tips before any PR/ref effect. Neither the receiver profile nor the schema-3
receipt can replace those checks, ordinary Main approval or release eligibility.
An unknown dispatch outcome is terminal; no POST retry is introduced. Other
Collections remain unprofiled until their actual identities and independent
Management contract have been reviewed and accepted.
