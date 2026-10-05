# LI-150: verification ownership and optional review requests

Status: proposed controller correction; protected acceptance is pending.

## Observed failure

Controller PR 785's correction head had a real, non-skipped `Verify current
revision policy` job, while its `Request Copilot review for current revision`
job was skipped on synchronize. Producer run 37337518846 failed with
`producer-owner-e-missing` before it could verify the corrected head's review.
The requester skip is required by the existing funding boundary.

## Proposed eligible-set correction

For the Copilot ownership mode, retain the exact requester job and original
attempt identity checks, including unique job ID, run ID, head, attempt and
valid state/conclusion. A valid skipped requester does not disqualify its
non-skipped verification job. The requester describes whether this run may
request a paid review; the verification job owns acceptance of native evidence.

The main controller and review-refresh consumer must use byte-identical owner
guards. Both continue selecting the minimum native run ID from the exact
PR/base/head candidate set, with two stable uncached observations. Missing,
ambiguous, malformed or foreign requester/verification jobs still fail closed.
Skipped verification jobs remain ineligible.

The review request triggers, author and entitlement checks, one-request-per-head
limit, review predicates, resolved-thread checks and Required results are
unchanged. Ownership alone does not claim that a review exists or that it passes.
No workflow rerun, review retry, identity fallback or synthetic success is added.

## Failure and migration behavior

A failed eligible owner remains the owner when a later requester runs. This
correction does not transfer ownership to a successful later run or revive a
terminal failed owner. Existing heads with terminal owners remain fail-closed;
they are not retroactively accepted by this proposal. Activation requires normal
review and protected promotion, followed by an independent correction-head
canary under the deployed controller.

This is a separate predecessor work item because PR 785 already consumed its
one review correction push. Its reservation patch and existing head are held.

## Deterministic verification

Executed guard fixtures cover a skipped requester with live verification,
skipped verification rejection, missing requester, foreign requester head,
terminal-owner retention and original-attempt requester binding. All three
guard uses run the same fixtures. Existing duplicate, foreign PR/base/head,
attempt, pagination and unstable-snapshot tests remain required. Native review
and Required checks must pass before this proposed contract is accepted.
