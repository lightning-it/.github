# ModuLix validation lanes

This organization-wide guidance applies to ModuLix source repositories and central
validation. It does not change the `.github` repository's own
`repository_profile` classification, test profiles, or release behavior.

The authoritative decisions are:

- [MLX-10 distributed test ownership](https://lit.atlassian.net/wiki/spaces/LIT/pages/2886566105)
- [MLX-40 release evidence](https://lit.atlassian.net/wiki/spaces/LIT/pages/2886926524)
- [MLX-70 asynchronous Heavy execution](https://lit.atlassian.net/wiki/spaces/LIT/pages/2893119515)

## Ownership and triggers

- Source pull requests run Static/Build, Unit/Contract, and impact-selected Tiny checks without privileged infrastructure.
- `modulix-validation` owns Heavy and Application Acceptance scheduling, protected runners, secrets, cleanup, and evidence.
- Application Acceptance starts only after successful Heavy validation.
- Releases verify evidence for the exact immutable candidate instead of synchronously repeating Heavy and Application Acceptance.
- Missing, expired, revoked, or mismatched evidence fails closed and requires central manual validation.
- Pull-request authors identify affected profiles, but the validated central policy is authoritative and the declaration never authorizes privileged execution of untrusted code.

Required GitHub Actions checks provide technical gate evidence; they cannot
approve a pull-request review. REP-70 applies to protected deployment
environments and does not change pull-request review policy. Required human
approval counts may be zero; required conversation resolution remains a
separate branch/ruleset control.

Source repositories keep reusable role tests and environment-neutral scenarios.
They do not add source-owned Heavy or Application Acceptance schedules.

## Stable contexts and names

Stable source-repository contexts are:

- `develop`: `Collection / Fast`
- `main`: `Collection / Fast` and `Collection / Release Evidence`

Job names describe what actually happened. A skipped, delegated, compatibility,
or no-op adapter must not use a name that implies Heavy or Application
Acceptance executed. Those profile names belong to real central runs in
`modulix-validation`. Temporary migration aliases must be identifiable as
compatibility checks and removed after the stable aggregates report on both
protected branches.

## Evidence and exceptions

The default evidence freshness ceiling is 36 hours. Evidence binds the full
source SHA and immutable tree or artifact digest, tested component and image
identities, policy and matrix identities, workflow SHA, executed cells and
results, timestamps, cleanup result, run identity, and tamper-resistant
provenance. Any bound identity change invalidates reuse.

Exceptions require a control ID, reason, owner, approver, linked ADR,
compensating controls, start date, expiry date, and review date. Source-owned
Heavy schedules or synchronous PR Heavy/Application execution without a current
exception are not permitted.

## Enforcement

The policy is enforced and regression-tested in the implementation repositories:

- [`shared-assets-lit#590`](https://github.com/lightning-it/shared-assets-lit/issues/590): versioned policy schema, renderer, templates, and contract tests.
- [`modulix-validation#134`](https://github.com/lightning-it/modulix-validation/issues/134): central orchestration, evidence schema, semantic verification, cleanup, and failure-path tests.
- [`ansible-collection-supplementary#554`](https://github.com/lightning-it/ansible-collection-supplementary/issues/554): pilot Fast Lane, semantic impact selection, and removal of source-owned Heavy scheduling.
- [`github-management-lit#180`](https://github.com/lightning-it/github-management-lit/issues/180): branch-specific required contexts, invalid-context rejection, and live drift detection.

Cross-repository governance and check-name semantics are tracked in
[LI-118](https://lit.atlassian.net/browse/LI-118).
