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

The Root reference's existing delivery entry point observes completion of Repository Quality.
Only a successful native push for the actual current protected Develop head
can signal preparation; PR/fork runs, stale heads, skipped checks and producer
reruns cannot do so. The immutable helper verifies this before credential use
and rechecks the revision immediately before dispatch. It does not approve,
merge, change settings or request an AI review.

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
