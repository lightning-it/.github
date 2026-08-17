---
id: adr-rep60-main-controller-bootstrap-20260817
title: REP-60 protected-main controller bootstrap
description: Records the immutable one-time transition that installs the protected current-revision controller on main.
slug: /adr/rep60-main-controller-bootstrap-20260817/
document:
  status: maintained
  approval_status: approved
  version: "1.0"
  classification: PUBLIC
  owner: Lightning IT Documentation Maintainers
  approver: Lightning IT Product Owners
  audience:
    - repository maintainers
    - platform engineers
    - security reviewers
  last_reviewed: "2026-08-17"
  review_cadence: annual
---

# ADR: REP-60 protected-main controller bootstrap

- Status: Accepted for one-time transition
- Date: 2026-08-17
- Scope: Supplementary protected current-revision controller bootstrap

## Scope

This record covers only the first promotion of the protected Supplementary
current-revision controller from `develop` to `main` in
`lightning-it/ansible-collection-supplementary`.

The live promotion is pull request `#776`, authored by
`lightning-it-release-automation[bot]`, and is frozen to:

- base `01afb46890e6d7ac6008e8ed478aa6af91e1b19b`;
- head `7a6cadc2c1048daec4a69ff0f71441b6ff257416`;
- head tree `7c19ce8303b313b2911e2f8abd075a7b5b2fecd6`;
- source pull request `#759` and its signed merge commit at the frozen head.

The protected controller assets at that immutable head are:

- `.github/workflows/copilot-review.yml` blob
  `47a6579c29beb9a8cb452da7f3715fb50c6c7933`;
- `.github/workflows/release-bot-exact-head-review.yml` blob
  `4332028591a4f251f213b6aba35106ea95c4ac01`;
- `.github/workflows/current-revision-rerun.yml` blob
  `22ceb959bcafdc1a2c215261b2622c8aa1fc743d`;
- `scripts/materialize-exact-revision-review.py` blob
  `f394a820a9c0922d8e7187dbd1b8aca3bf13db61`.

Before promoting the organization trust-root change, protected `.github`
`main` commit `b671844d753f504dc2ef731e9411669d755d530b` is recorded as the second parent
of ancestry merge `db63df9825d3b7c209cc328615f63bf44777eeb3`. That merge has the same tree as
its protected `develop` first parent:
`4e7831ac3d962efc6abcaa94bf6d1650cffe3919`.

## One-time transition

The organization-owned required workflow contains a temporary transition that
can match only the immutable pull request, base, head, tree, merge provenance,
source pull request, and four controller blob IDs listed in its source. It also
requires zero Copilot reviews and zero Exact-Revision Codex results for the
transition head.

The transition performs no AI call. Its neutral check evidence states:

- `temporary=true`;
- `acceptance_evidence=false`;
- `review_path="immutable one-time controller bootstrap; no AI"`.

At most one retry of the same workflow run may reuse that neutral check. Reuse
is allowed only when its GitHub Actions app identity, head, external binding,
successful conclusion, title, and complete evidence summary match exactly;
multiple or mismatched checks fail closed.

The first live preflight, required-workflow run `32026210862`, stopped before
creating transition evidence because GitHub's compare API returns a null
`head_commit` for an identical comparison. The controller therefore accepts a
null `head_commit` only when the protected source and workflow SHAs are equal,
the status is `identical`, and both ahead/behind counts are zero. For an
`ahead` result it still requires a positive ahead count, zero behind count,
and the exact source SHA as `head_commit`. The failed preflight is not
acceptance evidence and did not authorize a merge.

After that correction reached the protected source, required-workflow run
`32027540880` also failed closed before creating a reservation or transition
check on both its initial attempt and its single permitted retry. Because the
original monolithic step exposed no safe stage marker, the controller now
emits only a fixed, non-sensitive failure-stage name and records the same stage
in a failed reservation summary when one already exists. It never prints bound
payloads, credentials, prompts, or review content. Both attempts remain
non-acceptance evidence and did not authorize a merge.

This is a fail-closed installation step, not an MLX-90 or REP-60 operational
acceptance result. It does not authorize another pull request, base, head,
author, repository, or workflow revision.

## Mandatory completion

After `#776` reaches protected `main` through a normal merge commit:

1. remove the temporary transition and its regression assertions;
2. retain the neutral `Current revision review` ruleset requirement and the
   organization-owned required workflow without bypass actors;
3. remove the repository bootstrap aliases;
4. create a fresh Release-App-owned promotion through the protected pipeline;
5. prove that Draft causes no Copilot or Codex execution;
6. transition to Ready exactly once;
7. require exactly one protected MLX-90 §7.2 Exact-Revision Codex result and
   one verified neutral current-revision result for the frozen live head;
8. merge only after every required gate succeeds normally.

Local AI review and Copilot dual-review are prohibited. Human/internal pull
requests may use the pipeline Copilot path under the approved Lightning IT cost
boundary; external contributors must supply their own eligible review path.
