# LI-259 bounded native verifier recovery

Status: implemented locally; disabled by default. Protected rollout and native
acceptance remain required before activation. LI-216 and LI-219 are complete.

## Evidence and resource decision

The native job [111948671870](https://github.com/lightning-it/.github/actions/runs/37365237738/job/111948671870)
was cancelled after 901 seconds with `runner_id=0`, an empty runner name, no
steps, and exactly one failure annotation: “The job was not acquired by Runner
of type hosted even after multiple attempts”. Its other annotations were
notices. This job is a classification reference, not an eligible verifier.
The associated GitHub Actions incident `3q1yb5m7ltvb` began at
2026-10-05T19:11:58Z and was still being investigated 39 minutes later.

A runnerless published check is not this failure. Source run `37466071703`,
attempt 2, job `112280367959` was such a projection; executable job
`112280258443` failed deterministically at `permanent-producer-binding`.
Likewise Source run `37483905482`, attempt 2, job `112342391651` had a runner
and failed in verification. Both remain ineligible. The successful deterministic
producer rerun `37484055639`, attempt 2, is a binding reference; this change
does not extend the producer's budget.

| Bound | Value | Reason |
| --- | --- | --- |
| Additional technical attempts | Native attempts 3 and 4 only | Two separated recovery opportunities, then stop |
| Cooldown before attempt 3 | 20 minutes after failed attempt 2 | Longer than the observed 901-second acquisition failure |
| Cooldown before attempt 4 | 40 minutes after failed attempt 3 | Reduce pressure during the observed longer incident |
| Total budget | 180 minutes from the prospective seal | Includes acquisition windows, cooldowns, scheduler delay and a 60-minute verifier |
| Remaining time at dispatch | At least 60 minutes | Reserve the existing verifier job's full timeout |
| Scheduler interval | 10 minutes | Reuse bounded periodic observation without a sleeping runner |

These are conservative resource limits, not a measured success rate or a
GitHub platform maximum. Two 15-minute failed acquisition windows, 20/40-minute
cooldowns, up to two 10-minute scheduling delays and a 60-minute successful
verification fit within 170 minutes. The 180-minute deadline leaves 10 minutes
for control-plane work. A late scheduler never extends that deadline. The
receiver checks it again immediately before acceptance.

## Scope and authorization

Both `LI219_EVENT_MODE=enabled` and `LI259_INFRA_RETRY=enabled` are required.
Only the three existing pilots and ready same-repository `litroc` PRs qualify.
Only `supplementary-current-revision-required.yml` is wired: the native Required
Workflow for Source/Port and the local protected verifier in `.github`.
The separate `dot-github-current-revision-required.yml` cross-controller is
explicitly ineligible until its source owner ships its own coupled adapter.

The existing helper seals the contract **before attempt 2** and repeats the
binding after consuming the original LI-219 event claim. The seal records the
unchanged review and inline content, resolved thread inventory, successful
neutral check, producer run/attempt, native receiver identity, PR/base/head,
controller sources, complete policy-code hashes and input hash. A successful
native marker in attempt 1 binds the receiver's actual immutable source and
PR/base/head even when GitHub's run DTO has an empty PR projection. No such
marker or seal can be added retroactively to old runs.
Pre-rollout runs without the marker retain the original LI-219 attempt-two
route, without a new seed or any additional technical entitlement.

The claim is stored in the existing protected `lit-review-operations` Git ref:

- `li259/<native-run>/seed.json`: prospective contract and original claimant.
- `li259/<native-run>/attempt-3.json` and `attempt-4.json`: individually consumed
  technical slots, classified native cause, claimant, contract hash and time.
- `li259/<native-run>/terminal.json`: terminal drift, deterministic failure,
  successful verification or exhausted budget, with native attempt and deadline.

The original `li219-verifier-operation` remains distinct and mandatory. Every
technical slot uses one Git expected-head CAS and immutable record readback.
A loser, ambiguous CAS response, or unconfirmed rerun response sends no second
effect. An unresolved slot remains permanently GET-only, even after expiry or
drift, until native observation establishes that its attempt occurred. The
pre-effect consumed record also covers crashes between claim and POST.
No successor run or fresh event resets the clock or replenishes slots.

Candidate-local contract drift, including a rerun of the original event helper,
is durably terminal before a technical claim; the schedule then processes the
next candidate. After a technical CAS, drift leaves the consumed slot permanently
GET-only and the sweep continues without another write or rerun POST. Unavailable
API evidence, incomplete or duplicate inventories, and an unconfirmed terminal
record still abort the whole sweep. The handoff function resides in the existing
materialized guard so the consuming workflow step stays below the 64,500-byte
actionlint pipe limit without changing its authorization sequence.

## Native classification and receiver

Classification requires the authenticated native execution job, its exact
check-run ID, GitHub Actions app, bound run/attempt/head, hosted label,
`cancelled` conclusion, integer runner ID zero, empty runner name and steps,
complete annotation inventory and the exact single failure reason above.
Unknown failure text, a null runner ID, code execution, quota, review, identity,
permissions, policy errors or independent failed jobs never authorize recovery.

The only effect is the native **job** rerun endpoint for the existing verifier.
GitHub also reruns its dependent deterministic final gate. It does not restart
the producer, review-request job, other workflow writers or create a revision.
The receiver authenticates the seed, original event consumption, all technical
claims, native previous causes and current complete contract before any writer
in that job. It repeats this check immediately before publishing success.
Missing claims, source changes, review edits, unresolved threads, stale base or
head and expired time all fail closed. Native Required-Workflow acceptance is
still authoritative; journal entries never publish or substitute a PASS.

## Governance and rollout

This is the precise proposed REP-40/REP-60 amendment: retain the one event-driven
reevaluation, and add only these separately claimed, bounded infrastructure
attempts under an identical contract. For affected REP-120 clauses, add these
operational consumption records to the existing protected journal retention;
they are neither review evidence nor a second release-evidence package. Do not
rewrite historical native evidence or widen reviewer/funding/merge authority.
Record the matching narrow amendments in those governance pages before enablement.

1. Review and merge the coupled Python controller, protected launcher, helper,
   receiver, scheduler and tests through the ordinary protected pipeline.
2. Promote the exact receiver and both Python modules to protected `.github`
   `main`; synchronize the helper/controller assets to the pilot sources. Keep
   the flag disabled during rollout. Inconsistent controller versions fail closed.
3. Verify that the fixed journal ref remains protected and no temporary project
   permission or ruleset bypass remains. Grant no additional AI entitlement.
4. Enable Source or Port first, only after the Required receiver and its source-marker step
   are present. A new ordinary reviewed PR must create the prospective seal
   before its existing attempt 2; older unsealed runs stay ineligible.
5. Capture genuine native positive/negative references under that controller:
   classified attempt-2 acquisition failure followed by a successful 3, duplicate
   delivery without another effect, deterministic failure remaining terminal,
   unchanged head/review ID and zero additional review-request jobs.
6. Expand to the other wired pilots after those references pass. Keep `.github`
   disabled until the external cross-controller and its handoff consumer can
   authenticate the local verifier's consumed technical attempt. Adapt and
   independently verify that separate coupled path before enabling it there.

Rollback disables `LI259_INFRA_RETRY`; existing records are retained. Attempts
above 2 then fail closed at receiver entry and cannot publish acceptance.
No local test or historical incident is represented as a new native rollout
acceptance. Native acceptance and governance-page changes remain deployment
steps, outside this local implementation commit.
