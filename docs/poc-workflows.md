# Process and workflow purpose during the POC

Owner decision: LI-319, 2026-10-15. This supersedes the former mandatory
AI review and historical evidence process while a replacement is developed.

The process determines the workflows we need. For every workflow, record its
purpose, consumer, trigger, owner role, required output and failure handling.
Keep a needed function or provide a working simpler replacement. If a needed
function is undocumented, document it in the existing process pages and here.
Remove a workflow when its function is no longer needed. Missing documentation
alone does not establish that a function is unnecessary. Check callers before
removing or disabling a receiver; update templates so it is not recreated.

The canonical process is [SCC-70 Delivery and Setup](https://lit.atlassian.net/wiki/spaces/LIT/pages/2897347190).
[SCC-41](https://lit.atlassian.net/wiki/spaces/LIT/pages/2935095298) describes
orchestration and [SCC-40](https://lit.atlassian.net/wiki/spaces/LIT/pages/2897805754)
describes review. The decision and implementation task is
[LI-319](https://lit.atlassian.net/browse/LI-319). Earlier requirements remain
historical where this explicit temporary decision supersedes them.

## Current process

A contributor opens a pull request; Repository Quality runs deterministic tests
and lint. Existing CodeQL and OpenSSF checks remain. One authorized person can
merge the change. A develop-to-main update uses an ordinary pull request.
Product repositories then run their own required release preparation, builds,
tests, signing and publishing as applicable. Public shared definitions do not
grant access to private repositories or move private credentials or execution
into this public repository. Private work uses its own authorized identity and
permissions. This repository itself has no artifact publishing target.

## Current workflow functions

| Object | Purpose and consumer | Trigger and result | Current decision |
| --- | --- | --- | --- |
| `repository-quality.yml` | Validate this repository's structure, documentation and deterministic checks | Pull requests, pushes to develop/main, manual dispatch; runs the pinned repository-quality profile | Keep for the POC; failures must be fixed before merging |
| `openssf-scorecard.yml` | Assess repository security practices | Weekly schedule, branch protection changes, manual dispatch; records SARIF and uploads to code scanning | Keep for the POC; inspect failures and findings |
| GitHub-managed CodeQL | Source security analysis where supported | GitHub-managed scanning configuration; code scanning results | Keep; a service, not an additional YAML file |
| GitHub-managed Copilot registration | Optional AI review service | A request can start a review; a historical Actions entry can remain | No mandatory review and no automatic review-request chain in the POC |

The repository maintainers operate these checks and handle failures. Shared
Assets remains the canonical source for the managed Scorecard template; the
repository-quality profile executes locally in this repository. Neither current
YAML needs Supplementary as its central verifier or evidence source.

## Retired implementations and replacements

These are the 13 files removed from this repository under the temporary POC
decision. Their former functions were partly required by the old process;
removal does not mean they were never needed.

| Removed files | Former function | Current replacement or exception |
| --- | --- | --- |
| `copilot-review.yml`, `copilot-review-refresh.yml`, `release-bot-exact-head-review.yml` | Request and refresh AI reviews | No mandatory AI gate in this repository; a still-needed release caller in another repository must retain a functioning receiver until replaced |
| `dot-github-current-revision-required.yml`, `supplementary-current-revision-required.yml` | Enforce central current-revision evidence | Former organization requirements retired for the POC; ordinary repository CI remains |
| `current-revision-rerun.yml`, `review-event-reconcile.yml`, `review-infrastructure-retry.yml` | Recover and reconcile the former evidence chain | Retired with that chain; actual CI failures are still investigated |
| `codex-copilot-remediation.yml` | Automatically repair review findings | Contributor fixes actual findings through an ordinary PR |
| `renovate-guarded-automerge.yml`, `shared-assets-guarded-automerge.yml` | Automatically merge dependency and shared-file updates | One authorized person handles ordinary PRs with applicable CI |
| `promote-develop-to-main.yml`, `sync-main-to-develop.yml` | Automatic promotion and branch synchronization | Ordinary PRs handled by one authorized person |

Outside this repository, retired files and generator templates are not yet all
removed. Their cleanup remains open in LI-319. The confirmed Supplementary
release-preparation caller still needs its dispatch-only exact-head helper;
that receiver was restored after an overbroad shutdown. It does not restore
organization-wide mandatory AI review. A future change must simplify the caller
and receiver together before removing that release dependency.

## History and future governance

The repository retains only `repository-quality.yml` and
`openssf-scorecard.yml`. GitHub-managed scanning services are separate from these
files. Automatic AI review, remediation, repeated verification, promotion,
backmerge and their private evidence packages are retired. The owner separately
authorized deletion of obsolete Actions history in this repository; cleanup is
in progress. Current quality and security run history is retained. Git commit
history is unchanged. There is no replacement POC orchestration platform.

The former central Required Workflows are no longer required by the organization
and are removed here only after that obligation was retired. Other repositories
continue their own build, test, security and publishing workflows. Private
repository execution and credentials remain private. Shared Assets must not
recreate the retired files.

Production governance must be introduced as a separate explicit rollout. The POC
provides no claim of production governance or reconstructed historical approval.
The permanent necessity of individual workflow files will be decided in that
rollout; this register records current POC operation and explicit open work.
