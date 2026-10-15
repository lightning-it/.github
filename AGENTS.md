# Lightning IT POC contribution guidance

This owner-authorized POC policy supersedes the former REP-60 / LI-219 / LI-259
review, evidence, retry and promotion requirements for this repository.

- Use a normal pull request. One authorized person may author and merge it.
  No second person, mandatory Copilot/Codex review, or environment approval is
  required for an ordinary repository change.
- Keep repository quality, tests, security scanning and dependency checks.
  Fix actual failures; do not fabricate passing results.
- Run deterministic lint, tests and build commands through the existing
  digest-pinned Lightning IT Devtools wrapper. Local validation never calls AI.
- Keep private repository contents and credentials out of public logs or files.
- Keep credentials narrowly scoped and third-party Actions pinned to immutable
  commits. Do not weaken release publishing permissions as part of this POC.
- Do not restore automatic review requests, remediation, evidence aggregation,
  review recovery, or promotion/backmerge controllers. Those mechanisms were
  retired by the owner under LI-319 on 2026-10-15.
- Merge develop to main through an ordinary pull request when needed. Historical
  run records and consumed review state remain historical; they are not current
  POC acceptance requirements.
- Any future mandatory review/governance rollout requires an explicit new
  decision and migration. This POC policy does not claim production readiness.

## Owner-approved safe-target migration

The owner has now explicitly commissioned the safe target described in
`docs/workflow-target.md` and `docs/workflow-target-catalog.md`. That decision
authorizes implementing the new common control and delivery entry points; it
does not authorize reactivating the retired controller chains.

The initial `.lit/workflow-control.json` is a reference-scope configuration.
Its configuration alone grants no promotion or release acceptance; current
authority comes only from the externally selected native Required Workflow source.
Management admits an immutable source only after its native positive and
negative reference checks. The existing POC remains the operating transition
until that scoped cutover is actually accepted. Preserve all existing quality,
security and applicable publishing checks throughout the migration.

One authorized person must be able to complete every human approval, including
self-approval of a normal release. Do not require a second person or synthesize
human approval. The common runtime executes in the consumer's visibility and
uses only explicitly scoped secrets. Local validation remains deterministic.
