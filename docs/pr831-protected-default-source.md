# Protected default source for the historical controller repair

PR #831 installs the owner-approved historical #724 admission into protected
main. GitHub executes the ordinary current-revision workflow from protected
default branch develop. The old source binder only allowed source = target base
or a develop-to-main promotion, so this narrow main repair failed before its
ordinary review and policy evidence could be verified.

The source transition admits only `.github` PR #831, main base
`8bbbbeaa5bec36034fceebc029ec6c327d87bd5c`, head
`13fe6c651c2c8ef807c196755915de8331d26f3a`, and the exact `litroc` identity.
The candidate is one commit changing four files, with native current-head
Copilot review `5506015243` reporting zero open findings. Its candidate code
is never executed by the trusted verifier.

Both entry and final acceptance authenticate the live protected develop source
SHA and its ancestry from `18f65689d3b6ea6ad8f1da72b662d2f212fc0411`, the
unchanged protected main base, and the exact open same-repository PR/branch.
The source validator is copied from the immutable protected workflow, not from
candidate data. The ordinary native review, Required, reservation and final
metadata contracts remain mandatory. Other PRs and source transitions retain
their existing rejection behavior; the usual attempt and AI-request limits
are unchanged.

Tests execute that same source-binding shell function with read-only fixtures
and reject wrong actors, references, repositories, revisions, forks, source or
target protection drift, source ancestry drift, draft/closed PRs and changed
candidate scope. No workflow or ruleset is bypassed or weakened.
