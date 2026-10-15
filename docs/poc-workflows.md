# Workflow operation during the POC

Owner decision: LI-319, 2026-10-15. This supersedes the former mandatory
AI review and historical evidence process while a replacement is developed.

A contributor opens a pull request; Repository Quality runs deterministic tests
and lint. Existing CodeQL and OpenSSF checks remain. One authorized person can
merge the change. A develop-to-main update uses an ordinary pull request.

The repository retains only `repository-quality.yml` and
`openssf-scorecard.yml`. GitHub-managed scanning services are separate from these
files. Automatic AI review, remediation, repeated verification, promotion,
backmerge and their private evidence packages are retired. Their old native run
history is retained. There is no replacement POC orchestration platform.

The former central Required Workflows are no longer required by the organization
and are removed here only after that obligation was retired. Other repositories
continue their own build, test, security and publishing workflows. Private
repository execution and credentials remain private. Shared Assets must not
recreate the retired files.

Production governance must be introduced as a separate explicit rollout. The POC
provides no claim of production governance or reconstructed historical approval.
