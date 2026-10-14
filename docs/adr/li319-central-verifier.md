# LI-319: public central verifier with one-person authorization

Status: Owner authorized; native cutover and acceptance pending.

The public `.github` repository owns the organization Required Workflow sources.
The reciprocal verifier previously sourced from Supplementary moves here with
its technical evidence checks intact. Ruleset 21200954 changes source only after
the new gate is natively evaluated and additionally enforced. Ruleset 20938748
and all its consumers remain protected. No new repository is created.

## Approval contract

A single authorized human, including the author or workflow initiator, may
approve the exact revision through `dot-github-policy-approval`. Native reviewer
identity is `litroc` (GitHub ID 76040632). The environment requires that user,
allows self-review, disallows administrative bypass and permits protected
branches only. Classic human/CODEOWNER/last-push approvals must not add a second
person. The organization Required Workflow still blocks technical failures.

Admission binds PR, head, base, metadata, reviewer policy and protected source
before waiting and rechecks them after approval and final evidence validation.
Successful identical native authorizations can be reused from their authenticated
run, original native review and successful protected preflight binding. An
interruption after native approval does not consume another human approval; the
current technical verifier still runs and rejects failed evidence. Lost or
ambiguous evidence fails closed. History is not rewritten or converted to PASS.
The bounded discovery window does not authorize a blind repeat when exhausted.
Changed inputs require a newly reviewed authorization. No AI request is made.

The successful native preflight emits one protected-source SHA receipt and one
exact-revision binding marker. Reuse and management adoption authenticate that
native Required Workflow job and its actual source receipt; a target develop
base is not substituted for the controller loaded from protected main. Missing,
changed or duplicate receipts block reuse. Source/current-main drift still
invalidates approval. The supported five-event contract matches existing
locators, and the final job allows 18 minutes for the inherited bounded waits.
A well-formed receipt for another source is discarded so the new revision can
request fresh native admission; missing or ambiguous receipt evidence blocks
admission. The same original technical recovery cannot cross a source change.

Producer compatibility retains the established current Human, deterministic
ancestry, Renovate, provenance-bound managed-sync v6 and protected Release-App
v4 contracts. Automation identities and schema fields are validated explicitly.
The Release-App review job may finish while its downstream receiver handoff
still runs; that successful bound job is required instead of creating a cyclic
whole-run wait. One complete typed job-inventory boundary binds IDs, run,
attempt and head for ordinary, release and aggregated promotion evidence.
Copilot v6 evidence may retain its original owner PR when an exact successor
reuses a closed, unmerged predecessor. The authenticated owner number, ready
state, same author, Base/Head SHA/ref/repository and owner metadata revision
must match the established contract; owner drift blocks the final reread.
This preserves existing review consumption instead of requesting another AI
review. Current PR approval remains independently bound to its own revision.
Established v5 Copilot and ancestry evidence retains its authenticated version,
producer and existing optional owner-number schema; no obsolete evidence gains
new authority. A bounded final-only attempt-2 recovery preserves the original
attempt-1 preflight and native human approval for exact duplicate-event reuse.
The cache revalidates that original binding, bot recovery and sole attempt-2
job rather than asking the same person to approve the same revision again.

Required Workflow event filters do not create native metadata runs. The same
YAML therefore has two roles: protected pull_request_target alone requests
human authorization; the pull_request job `dot-github / approved metadata`
creates its native mandatory check before any fallible setup. Native default
activities run both roles. Local edited/labeled/unlabeled events run only the
read-only metadata job, which authenticates an unchanged genuine native human
authorization, reruns current technical checks and rebinds the final revision.
It never requests human approval or AI inference. Queueing, checkout, container,
API, timeout or cancellation failures leave the required native context blocking.
The target-event slot uses the distinct name
"Inactive metadata audit for target event"; it never publishes the required
metadata name through a skipped job.
No custom check-result publication or write token is needed.

Native log transport compatibility is tested through the actual CLI argument
parser installed in the digest-pinned Devtools runtime. A reviewer or host CLI
version is not substituted for that runtime. Color bytes are captured internally;
source and digest receipts still require unique exact native markers.

An immutable producer that already failed its neutral publication cannot be
replaced by a later successful locator-only workflow. Close/reopen preserves the
original review budget and cannot turn that failed publisher into new evidence.
Retain Ready state while investigating a finding that needs no source change;
use Draft when correcting a confirmed defect. Existing protected recovery must
authenticate the original owner and its remaining slot. If that path is absent,
only a meaningful new implementation or regression change merits a new revision;
never use empty commits or rewrite a failed native record to reset a budget.

With the existing LI-219 pilot disabled, the legacy requester admits `opened`
and `ready_for_review`, and does not fund requests on `synchronize`. Stage a
meaningful new head while the PR is Draft, then mark that verified head Ready
once. Pushing a new head while Ready can elect a synchronize owner that waits
for a request its own event cannot fund; a later Ready locator cannot replace
that immutable owner. Keep this protocol until the separately reviewed workflow
consolidation changes its producer/requester contract atomically.

Log-read failures report only a bounded error category (GitHub HTTP status,
unsupported arguments, terminal-control rejection or CLI exit). Raw stderr and
signed redirect URLs are never printed. No diagnostic authorizes a retry,
another human approval or weakened evidence checks.

The complete candidate workflow orchestration must semantically match current
protected main, including every job, event gate, token permission, dependency,
checkout and dispatcher. This single comparison replaces partial job field
allowlists. Python helpers always come from protected main during authorization;
normal proposed helper changes are tested separately before adoption. Future
YAML orchestration changes require a separately reviewed staged source-version
transition. The Root-only ruleset requires
both the native workflow and the App-15368 metadata job. Private Management binds
the latest real metadata job/run, four-role job inventory, protected source and
digest receipts, and original genuinely approved human canary run. Changed
metadata requests fresh admission through reopening; unchanged authorization is
reused even after a technical timeout. Independent technical/funding constraints
may require a meaningful new revision, never a forbidden same-head AI repeat.

The existing protected bot may recover the failed final technical job once
(native attempt 2). Admission and approval jobs remain first-attempt only.
The receiver requires the exact native ruleset run and PR tuple, bot triggering
identity, complete four-job first-attempt evidence (metadata skipped), a successful original
preflight with its unchanged binding marker, and a failed original final job.
It then revalidates native human approval and all current technical evidence.
Neither a new approval nor further retry attempts are granted by this recovery.

The target-event filters suppress local admission; local PR metadata activities
run only the native metadata audit. Organization Required Workflows ignore event
filters and run both default-event roles. The new source must be installed on
protected main before ruleset adoption. Candidate code is never executable
controller input. The previous external repository trust boundary is explicitly
replaced by this native single-person authorization and protected source.

All four policy jobs use the existing digest-pinned, read-only, socket-free
Devtools adapter through one protected shell dispatcher. Its explicit API network
and read-only native Actions token scopes do not grant private administration,
check-result writing or AI credentials. Native ruleset events are opened/synchronize/reopened; serialized
concurrency retains the native gate without unsupported automatic cancellation.

## Migration and rollback

Keep the old Supplementary source through evaluation and overlapping active
enforcement. Only then remove the old ruleset binding and its files/generators.
If adoption fails, restore a verified working old mandatory binding before
removing the new one. Save exact prior settings and protected refs. Keep
Collection, private target, promotion, security and release checks unchanged.

Settings remain owned by GitHub Management; shared templates remain owned by
Shared Assets. Private target evidence stays private. Native PRs, source commits,
review history and live settings are acceptance evidence; this document alone
is not native acceptance. Future multi-person requirements are a separate
policy change, not enabled by this amendment.

### Operator acceptance sequence

1. Freeze the delivered public `main` source SHA. Run the private protected
   Management `central-verifier-transition` operation with stage `prepare`
   and that exact SHA. Record its native run, approval and successful readback.
   Preparation creates the approval environment and an Evaluate rule while
   keeping the original Supplementary rule active.
2. Open a normal, technically reviewed `.github` PR without modifying the
   central workflow orchestration. Keep its base, head and metadata unchanged
   throughout acceptance. Record the genuine native Required Workflow target
   run, original human approval, protected-source receipt and binding digest.
   Independently require the successful native PR metadata job with the same
   source, digest and original approval-run receipt.
3. Run `enforce` through protected Management with the frozen source SHA and
   accepted target-run ID. Read back both active protections. Run `cutover`
   with the same accepted evidence and read back the original rule's new
   `.github/main` source and removal of the temporary rule. These are distinct
   administrative operations; each can be approved by the same authorized
   person. Never replace a real native approval with a chat statement.
4. Confirm that rule 20938748 and all its consumer repositories retain their
   existing source, and that both protected Root branches retain strict native
   quality checks, zero human PR reviewers and no administrative bypass.
   Only after this acceptance retire the former Supplementary source files,
   their callers and distribution generators.
5. Deliver the workflow consolidations separately. Recount current files and
   active/disabled registry entries after protected delivery; historical run
   entries are retained and are not the current-file inventory.

Before cutover, a failed or interrupted canary leaves the original mandatory
source in place. Resume with authenticated unchanged human authorization and
current technical checks, or investigate the concrete failure. If the frozen
source or PR tuple changes, collect fresh bound acceptance evidence before
administrative adoption. Jira LI-319 and the linked Confluence controls record
the actual stage and readbacks, including delegation when the operator explicitly
asks an agent to execute a genuine native approval on their behalf.

## Workflow consolidation acceptance

### Delivered-source acceptance record

The acceptance PR is a normal documentation change, not a replacement verifier
or an artificial review-budget reset. Before administrative adoption, record the
delivered protected source separately from the candidate head and protected base.
The original target run must complete its preflight, genuine environment approval
and technical verifier successfully on its first attempt. The separate native PR
metadata job must then publish the same source, revision digest and original
approval-run ID. A green target run alone is insufficient.

The operator must retain the unchanged acceptance PR until Management has read
both native receipts for `enforce` and `cutover`. Record each administrative run
and its genuine approval independently; the same authorized person can perform
all three operations. Record delegated execution explicitly when the person has
authorized an agent to perform the real GitHub review. Do not describe delegation
as a personal UI click. Keep failed earlier source trials as diagnostic history,
and never substitute them for the delivered-source acceptance receipts.

The owner additionally requires a substantially smaller current workflow-file
inventory and no disabled standalone workflow files. Necessary manual release,
recovery and guarded automation functions must be bundled with their admission
and identity checks intact; unused functions must be removed with their callers
and regeneration sources. Disabled pilots must not become enabled incidentally.
Historical Actions entries and execution evidence may remain visible on GitHub.
The source cutover alone does not complete this acceptance criterion.


Automatic final-only bot recovery retains the existing failure-only dispatcher
contract. A technical timeout preserves genuine unchanged human authorization
for a later normal event, but does not grant a new timeout rerun path. This
receiver never advertises an automatic effect that its dispatcher cannot issue.
Promotion discovery filters genuine evidence by exact PR/base/head before
choosing the newest current result. A check for an old base attached to the
same develop head remains unavailable during bounded polling, rather than
aborting a fresh promotion or masking a failed newest current result.

The established ancestry exemption retains both exact native publisher pairs:
Shared Assets App 307342877 and Release App 307565056. Versions v5 and v6 still
require the same protected main, exact branch/title, two ordered parents and
the sole ancestry-proof file; mixed login/ID pairs and numeric aliases reject.

A candidate-local metadata success is never sufficient authorization. The
independent native Required Workflow from protected main calls the complete
candidate orchestration comparison before preflight output or human admission.
Changing the workflow requires a new Git head and its mandatory target event;
that event rejects forged local metadata steps. With an unchanged accepted
head, the workflow bytes are immutable while metadata-only edits run the
already bound audit. The actual protected preflight entrypoint regression runs
the source, live revision, environment and document validators without
authorization-helper stubs: unchanged document accepts and a forged local
always-successful metadata job rejects before binding output.

### Observed single-person authorization and unchanged reuse

The pre-cutover native trial used the protected source
`1472399a503146f092d6aa68000e76ccae705c96`. Its genuine environment review on
run `38579107091` was performed under the explicitly authorized account `litroc`.
The subsequent unchanged target run `38580956567` completed successfully while
its approval job `115911076071` was skipped because the original authorization
was authenticated and reused. Independent metadata run `38580954817` also
completed successfully. This demonstrates the native one-person path and avoids
a second authorization for an unchanged revision; it is historical trial
acceptance, not evidence for a later source version.

The compatibility fix separately preserves a normal reopened producer whose
existing exact-head review is reused without an active request job. The native
request role must be runnerless and step-free with its exact run URL and workflow
identity; all review, policy, source, revision and chronology checks still apply.
A failed request, active request or unverifiable original review cannot inherit
that exception. Technical verification never obtains another AI request slot.

After delivering that fix, freeze the new protected main source and collect a
fresh original native target plus independent metadata receipt before adoption.
Keep that acceptance revision open throughout the distinct private enforce and
cutover operations. Their approvals may all be performed by the same authorized
person; current technical failures remain independently blocking.


## First workflow consolidation package

After native source cutover, Root's deferred first-request continuation moves
into `copilot-review-refresh.yml`, using distinct locator and consumer jobs and
an explicit `operation=continue` dispatch. The existing refresh jobs do not run
for that dispatch. Credential scopes, protected-base/source binding, the original
request CAS key, first-attempt restriction and one-request budget remain intact.
The native evidence reader authenticates the new workflow identity and requires
all unrelated jobs to be inert. Historical two-job continuation evidence retains
its exact old identity and source; it is not rewritten as a new successful run.
The delayed-event reconciler retains both old and current locator histories and
the same ten-minute cooldown, preventing migration from restoring a dispatch slot.
Other pilot repositories retain their adopted source path until template adoption.
Pilot flags stay unchanged; publication alone does not activate a pilot.

## Owner-approved bounded historical promotion recognition

On 2026-10-14 the owner expressly accepted exactly two already integrated
historical Renovate ingress cases whose successful native producer was triggered
by the maintainer rather than the PR's Renovate author. Their old failed Required
runs remain failed. The public reader stores only opaque immutable tuple digests;
private PR metadata and contents remain in the private target and tracking pages.
The binding includes the repository, PR, base/head, merge/time, native check,
original producer, complete summary, actor/trigger and first attempt. All other
source, metadata, label, native-check and chronology checks still apply. Unmatched
identities, changed tuples, new attempts and all future ingress keep the ordinary
strict author identity. The resulting promotion still needs every current
technical gate and the genuine native one-person authorization. This is no
synthetic check, retry grant, new review request or retrospective Required PASS.

### Default-mode refresh source correction

Native Copilot review 5524790626 completed on e698 with zero findings. The
The Root default-mode refresh failed without an effective mutation. Native
metadata proves that its review event materialized the synthetic PR merge
source, which its existing source guard correctly rejects in favor of protected
Develop and its exact Base SHA. The exact first failure line was not traced.
No producer rerun or AI request occurred. The rejected native result remains.

Root now forwards review locators in default mode as well as pilot mode. The
Root default route uses the existing CAS-scoped canonical consumer, which
accepts only a first-attempt protected branch dispatch from github-actions[bot],
with the explicit continuation operation excluded.
The existing live protected-branch/source, PR tuple, native review, actor,
content/thread, original-producer and retry-budget guards are unchanged.
Copilot's native event alias is admitted only at the read-only locator; the
protected consumer still requires the canonical Copilot identity from API data.
Non-Root default behavior remains unchanged. Neither activation flag is enabled,
no new AI request entitlement is added, and the PR merge source is never admitted
as a mutation authority. The original e698 acceptance evidence stays historical;
the corrected final head requires normal fresh review and technical checks.

The independent Copilot finding at c40 identified the downstream provenance
reader that still expected a direct review-event writer. The corrected Root
default consumer now uses the existing durable verifier-operation CAS receipt
and its write-scoped job; the separate non-Root legacy consumer keeps its
original permissions and behavior. No repository pilot flag is enabled. The
reader authenticates the receipt, complete journal snapshot, protected source
and branch, exact PR/base/head/producer, chronology and all five native jobs.
The original default-mode Bot request must lie inside the source-bound original
requester effect step. Other contributors/default repositories keep their
existing funding-origin rules. The original single technical retry remains
bounded by its consumed operation; no AI request opportunity is restored.

The complete late-review regression executes the actual protected reader and
request-origin entry points with disabled pilot mode. It rejects changed
actors, trigger actors, source/head/base, PR locator, attempt, claim, active
companion jobs and original request timing or identity. Fixtures are offline
contract evidence, never a native GitHub PASS or proof of Main delivery.

The operation-claim shell implementation is synchronized in all three native
callers (request, refresh and protected reevaluation). Their existing equality
and uncertain-effect tests remain mandatory. The LI-319 Root default exception
is also explicit in AGENTS.md and its bound Copilot instructions. A regression
executes the real claim implementation twice against the same journal: only one
technical CAS/effect is accepted, no AI request occurs, and actor, trigger,
protection or attempt drift produces no mutation.


Following the second native finding, the default exception is deliberately
simplified to one existing write-scoped consumer. The shared claim function
requires both the native protected refresh workflow ref and
`GITHUB_JOB=refresh-canonical-gate` in Root default mode. Legacy reevaluation
helpers keep contents/checks read permissions and execute their original
non-journal path; no new helper writer or evidence authority is introduced.
The regression exercises their actual selected job/source with the real claim
function and rejects any API access. This bounded correction is recorded in
LI-319 rather than creating an equivalent blind successor or resetting review
budgets.
