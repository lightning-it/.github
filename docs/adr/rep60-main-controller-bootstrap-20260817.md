---
id: adr-rep60-main-controller-bootstrap-20260817
title: REP-60 protected-main controller bootstrap
description: Records the immutable one-time transition that installs the protected current-revision controller on main.
slug: /adr/rep60-main-controller-bootstrap-20260817/
document:
  status: maintained
  approval_status: approved
  version: "1.8"
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

The live promotion is pull request `#777`, authored by
`lightning-it-release-automation[bot]`, and is frozen to:

- base `01afb46890e6d7ac6008e8ed478aa6af91e1b19b`;
- head `2070d78360b497ed954cfe8de3fb616b99841943`;
- head tree `f9f953cabdeaea4a106c3390cf9cabbacfbad574`;
- source pull request `#782` and its signed merge commit at the frozen head.

The protected controller assets at that immutable head are:

- `.github/workflows/copilot-review.yml` blob
  `32eafe4b11587356b74f89d7aa88177a4578608b`;
- `.github/workflows/release-bot-exact-head-review.yml` blob
  `9566f3d997d41274c7e2e7c01ffb0b7711b842ba`;
- `.github/workflows/current-revision-rerun.yml` blob
  `30640b54850481349d3fbd3f80d2ebe513c7e1e4`;
- `.github/workflows/rep60-bootstrap-app-rearm.yml` blob
  `dff67484aca33e111657c233c799c55a9a089321`;
- `scripts/materialize-exact-revision-review.py` blob
  `f394a820a9c0922d8e7187dbd1b8aca3bf13db61`.

The superseded pre-refresh staging attempt recorded protected `.github` `main`
commit `b671844d753f504dc2ef731e9411669d755d530b` as the second parent of ancestry
merge `db63df9825d3b7c209cc328615f63bf44777eeb3`, with protected `develop` tree
`4e7831ac3d962efc6abcaa94bf6d1650cffe3919`. Those identifiers are retained
only as historical evidence. They are not the authoritative ancestry repair
for the refreshed transition and cannot authorize its promotion.

## One-time transition

The organization-owned required workflow contains a temporary transition that
can match only the immutable pull request, base, head, tree, merge provenance,
source pull request, and five controller blob IDs listed in its source. It also
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

Required-workflow run `32029954436` then failed closed at the fixed
`live-pr-binding` stage on both its initial attempt and its single permitted
retry. The live PR fields were correctly typed and still matched the immutable
base and head. The failure came from applying `jq -e` directly to the valid
boolean value `false` for a ready PR's draft field: `jq -e` reports that value
with a failing process status. The binding now validates the boolean type and
then converts the value to the literal string `false` or `true` before the
separate ready-state assertion. Both failed attempts remain non-acceptance
evidence and did not authorize a merge.

After those corrections reached the protected source, required-workflow run
`32030767687` verified the immutable transition for PR `#776` and created
exactly one temporary neutral check. Its evidence explicitly recorded
`temporary=true`, `acceptance_evidence=false`, and `no AI`; no Copilot review
or Exact-Revision Codex result existed. The PR was not merged because its
normal promotion Environment run had been triggered by `litroc`, while the
Environment correctly enforces `prevent_self_review=true`. PR `#776` was
closed without merge. Protected workflow run `32031952789` then used the
Release App to open replacement PR `#777` with the identical immutable base,
head, tree, and bot author. The transition is now additionally bound to that
exact PR number and to the Release App as both workflow actor and triggering
actor. The PR `#776` check remains historical non-acceptance evidence and
cannot authorize PR `#777`.

The protected `develop` head subsequently advanced only through normally
reviewed staging fixes `#779`, `#780`, `#781`, and `#782`. The frozen
transition is therefore refreshed to signed merge
`2070d78360b497ed954cfe8de3fb616b99841943`, its complete tree, exact
77-commit ancestry from the unchanged `main` base, source PR `#782`, and the
five final controller blobs above. PR `#782` was reviewed on exact head
`73156874fd8bfd1560e340c0cd470bebfe6c35f8` by Copilot review `4956284255`,
passed protected Required-Workflow run `32089403801`, and merged normally.
Earlier frozen heads no longer match and cannot authorize PR `#777`.

Before promoting this refreshed organization trust-root, protected `.github`
`main` commit `4fd42d4ce2de3d09c317c530e875bf8670adbe46` is recorded as the second parent
of ancestry merge `b4947507bc2ecec7a14650476649cd09fd9f525d`. Its first parent is protected
`develop` commit `49c0a80776a407d09850c431ac135cd46b954d80`; the merge preserves that first
parent's exact tree `e373262d5a661fe8c1caa5e7a321aa8a39a4c812`. The ancestry merge is promoted
only through a normal reviewed pull request.

After that source reached protected organization `main`, a manual retry of
required-workflow run `32081327743` failed closed because GitHub correctly
recorded `litroc`, rather than the Release App, as the retrying actor. Protected
Release-App rearm run `32083913911` then emitted a new App-authored event, and
required-workflow run `32083932536` verified the immutable transition without
an AI call. Its API-created evidence check `95552404766` was correctly bound,
green, and associated with PR `#777`, but GitHub's merge API still reported the
same Required Status Check as expected. The API-created check therefore remains
evidence input only. The organization Required-Workflow job itself now owns the
native `Current revision review` context, while its verifier selects producer
evidence by protected external-ID namespace and excludes its own job check.
This retains the visible neutral name, prevents a candidate check name from
becoming the trust root, and makes GitHub's native ruleset evaluation the final
merge boundary.

The native context exposed one further fail-closed bootstrap dependency on
Supplementary PR `#782`: the protected human and Release-App producers still
selected every same-named check before validating their own external ID. A
native Required-Workflow job therefore prevented either producer from
publishing its evidence. PR `#782` is frozen to base
`5f212688fd6b18a1f90b9c9e8cb2cf6b60c53c0c`, head
`73156874fd8bfd1560e340c0cd470bebfe6c35f8`, tree
`f9f953cabdeaea4a106c3390cf9cabbacfbad574`, its exact four-commit ancestry,
and its six changed blob IDs. Copilot review `4956145369` reviewed the prior
functional head and reported no new comments; the earlier finding is fixed and
its thread is resolved. The final commit contains only Ruff's canonical quote
normalization. Copilot review `4956284255` reviewed that exact final head and
reported no new review comments. Its two suppressed observations about the
`rep60-main-bootstrap:v1:` namespace are disproved by protected live check
`95552404766` and the organization Required Workflow, which respectively use
and produce that exact external-ID prefix. No unresolved Copilot thread exists.

The organization-owned Required Workflow retains two distinct, immutable
bootstrap transitions. The human transition for PR `#782` is bound only to
that PR/base/head/tree/files/review tuple. It created temporary,
review-bound evidence solely to install the producer-side external-ID
filtering and superseded the completed PR `#780` repair. It can no longer
match because PR `#782` is merged while that transition requires PR `#782` to
remain open. The separate Release-App transition is bound only to PR `#777`
and its frozen Supplementary base/head/controller provenance. Neither
transition can match another PR or revision. Remove both transitions and
their regression assertions immediately after PR `#777` reaches `main`. No
local AI is used.

This is a fail-closed installation step, not an MLX-90 or REP-60 operational
acceptance result. It does not authorize another pull request, base, head,
author, repository, or workflow revision.

## Mandatory completion

After `#777` reaches protected `main` through a normal merge commit:

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
