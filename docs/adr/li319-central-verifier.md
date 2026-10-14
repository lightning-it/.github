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
run, original native review and exact protected-source job binding. Cancellation
after a successful approval job does not consume another human approval; the
current technical verifier still runs and rejects failed evidence. Lost or
ambiguous evidence fails closed. History is not rewritten or converted to PASS.
The bounded discovery window does not authorize a blind repeat when exhausted.
Changed inputs require a newly reviewed authorization. No AI request is made.

The workflow's normal branch filters suppress duplicate local runs; organization
Required Workflows ignore those filters. The new source must be installed on
protected main before ruleset adoption. Candidate code is never executable
controller input. The previous external repository trust boundary is explicitly
replaced by this native single-person authorization and protected source.

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
