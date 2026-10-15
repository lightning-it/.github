# Operating protected change control

This runbook describes the reference procedure. Repository adoption and fleet
release acceptance remain separate decisions; source tests alone do not admit a
repository. Existing quality, security and product publishing checks remain
required throughout the transition.

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

## Approve a normal main promotion

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
state. Their successful completion is not review or release acceptance. A native
provider receipt must still bind the complete actual request and its response.

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
