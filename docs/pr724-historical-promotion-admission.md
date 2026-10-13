# Historical PR #724 admission

On 2026-10-13 the repository owner explicitly authorized promotion recognition
of the historical Required-Workflow exception used to merge `.github` PR #724.
This authorization is limited to that immutable receipt. It grants no general
managed-sync actor exception, extra review request, retry or protection bypass.

The accepted diff against `94dff2e6880afb7821441ab4c4b8bbd64dc3b6ac` is exactly
three additions: Scorecard job timeouts of 60 and 10 minutes and a guarded
Renovate job timeout of 10 minutes. Head
`7daee000ad2bdda7928f803906c592f7e374f08c` was merged as
`89869f9e2a987fd59706863c04b46da8d5a693bc` at `2026-10-13T02:34:35Z`.

The ordinary ingress verifier expects the PR author to be the producer actor
and admits attempt 2 only for Copilot. This historical managed-sync PR instead
has the exact Sync-App author and `litroc` as actor and triggering actor of
successful native producer `38336319411`, attempt 2. Review check
`115097708345` records its deterministic managed-distribution policy result.
Native quality run `38336320280`, attempt 1, passed on the exact head.

`validate_pr724_historical_admission` independently binds:

- repository, PR, author, canonical branch, title, base, head and merge;
- the existing GitHub Actions review check and its exact eight-field summary;
- producer and quality run identities, revisions, successful terminal results,
  timestamps and complete native job inventories;
- ordered merge parents and the content-identical merge tree;
- the exact two-file, three-timeout delta, including blob and patch hashes.

The output includes
`historical_exception: owner-authorized-pr724-three-timeouts-2026-10-13`.
Historical failed Required Checks remain failed. This admission is explicitly
an owner-authorized historical exception, not a claim that those checks passed.
All other PRs retain the existing producer validation. Live review threads are
still checked by the ordinary promotion collector and rechecked before final
acceptance. No new AI review or duplicate per-ingress evidence package is made.

The public native-data fixture exercises the real review-selection entry point.
Negative cases cover revision, identity, attempt, provider, timing, job topology,
parent/tree, summary and diff mutation. After any mismatch or missing evidence,
the admission fails closed. The failed promotion #830 is not retried unchanged;
a corrected protected controller and a new genuine develop revision are needed.
