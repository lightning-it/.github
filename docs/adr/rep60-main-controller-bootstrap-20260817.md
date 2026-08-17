# REP-60 protected-main controller bootstrap — 2026-08-17

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
requires zero Copilot reviews and zero Exact-Revision Codex result for the
transition head.

The transition performs no AI call. Its neutral check evidence states:

- `temporary=true`;
- `acceptance_evidence=false`;
- `review_path="immutable one-time controller bootstrap; no AI"`.

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
