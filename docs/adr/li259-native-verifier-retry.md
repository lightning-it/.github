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

The repository-owned Core Copilot producer captures this same metadata revision
before selecting review evidence. Its authenticated GraphQL input must match
the immutable event repository/PR/base/head/title/body, and the edit revision
must not be newer than the event. Selected reviews must strictly postdate that
edit; equal second-resolution timestamps cannot establish the order.
Event update, live edit and review-submission timestamps share one strict
calendar parser: parse and format back to the identical UTC string under
explicit `TZ=UTC` and `LC_ALL=C`. Invalid calendar dates, leap seconds,
offsets and fractional seconds fail closed; only an unedited live PR may use
null. This keeps the producer aligned with the native `proof.epoch` contract
without depending on the runner's local timezone.
The ordinary schema-4 summary includes the bound revision. Every neutral
POST/PATCH and final publication acceptance revalidates it, including the
existing invalidation/reuse paths; no retry may recapture a newer baseline.
Source already carries its own producer binding and remains unchanged.

Every snapshot reads live GraphQL `lastEditedAt` together with repository,
PR number, base/head OIDs and title/body, and binds those inputs to the REST
snapshot. The revision must be an explicit null or valid UTC timestamp and
must equal the successful neutral schema-4 `pull_request_last_edited_at`.
The seed seals that revision; pre-POST and receiver snapshots compare it again.
Editing then restoring the original title/body therefore cannot reuse older
neutral evidence. Drift before a technical claim closes the candidate; drift
after claim consumes the slot without another POST. Missing or partial native
metadata responses abort the sweep. Existing seeds are never upgraded in place.

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

Before attempt two, the seed also freezes the scheduler workflow ID and an
observed native `run_number` frontier. Each technical slot belongs only to the
first native scheduler run created after its immutable failure-completion plus
cooldown boundary. The complete run-number sequence after that frontier must
be contiguous; a hidden or deleted run cannot be skipped to elect another
owner. Native reruns retain their run number and never restore authority.
The owner is checked before CAS, again before the job POST, and by the receiver.
This independent native identity remains observable even when a Git CAS times
out before its commit or readback is visible: every later scheduler is GET-only,
including after contract drift or budget expiry. A delayed Git commit does not
authorize a replacement POST. The first native owner may consume availability
without executing a CAS (for example cancellation or a failure earlier in the
sweep); this is an intentional fail-closed tradeoff, not another retry budget.

The marker-free legacy fallback also re-reads the complete live PR after the
attempt-one jobs GET. It cannot return a successful fallback if head, base or
other live bindings changed while determining that the old run is unsealed.

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

Publication and compatibility follow-up: neutral results are first written as
bound `completed/failure` records and promoted only after exact readback and
fresh live validation. An unknown create is resolved by GET only; exactly one
matching provisional result may then receive a bound PATCH, never another POST.
Missing or ambiguous outcomes stop. Attempt two may create only if the native
attempt-one publisher was skipped; otherwise it may only reuse an existing
bound result. Promotion races revoke the exact owned result, including old-head
results. An unavailable readback fails the producer; consumers still require its
successful native job. No extra review request is authorized.

Metadata GraphQL envelopes accept an absent `errors` member or an empty array
only. Acquisition completion is compared with its fresh observation clock,
without shifting the sealed deadline. Optional sealing leaves non-LI-259
authors/repositories and the recognized marker-free historical single Required
verifier on their original attempt-two path, without a seed. Snapshots and
receivers retain strict LI-259 author, source, job and contract validation.

The Core ordinary Copilot producer now emits the exact metadata-bound nine-key
schema-4/v6 summary. Promotion recognizes that form in addition to its unchanged
legacy eight-key and expanded thirteen-key contracts. The new form is Copilot
only and rebinds `pull_request_last_edited_at` through GraphQL; arbitrary partial
expanded forms remain invalid. The Core read-only shadow accepts its existing
eight-key form and this exact nine-key form, with live metadata equality and
strict review-after-edit ordering. Its formerly unsupported expanded form stays
unsupported. No evidence is rewritten and no review is requested.

The Required Workflow's thirteen-key Renovate and historical bootstrap validators
retain their separate contracts. Its eight-key PR-568 recovery records bind fixed
historical native IDs and also remain unchanged. Source has no local copy of the
Core promotion or shadow validator: the protected Core controller owns them.
Source root/default and generated rerun helpers already recognize an exact
nine-key historical supplementary cutover; their repository, manifest and
producer-blob limits stay intact. General Source producers still emit thirteen
keys. The Source port manifest records the updated Core consumer commit.

Metadata-bound Copilot review identity and strict review-after-edit ordering are
validated before the native run/PR association branches diverge. A populated
native `pull_requests` association cannot substitute for review chronology.
Both associated and unassociated paths require a later review when the bound
metadata revision is non-null; null retains its existing semantics. The
unassociated sparse path still checks review comments, and expanded evidence
still binds its explicit review ID. The shadow already applies chronology
unconditionally after reading the bound native review and GraphQL revision.
