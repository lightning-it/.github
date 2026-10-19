# Root CodeQL merge protection

The active repository rule [Root CodeQL merge protection, 25408994](https://github.com/lightning-it/.github/rules/25408994)
applies to `develop` and `main` in this repository. Its exclusions and bypass
actor lists are empty. The rule was applied on 19 October 2026; its native
runtime qualification is recorded separately from its configuration delivery.

## Current analysis and findings are separate gates

Both `Analyze (actions)` and `Analyze (python)` must succeed for the current
revision. Their required status identities are bound to GitHub Actions App
`15368`, with strict up-to-date checks. A missing, queued, running, failed or
cancelled analysis does not satisfy these required checks. A successful analysis
of an older head does not satisfy a replacement head. Run the genuine scanner
for the revised code; do not synthesize check results or reuse stale evidence.

The native code-scanning rule additionally requires `CodeQL` with
`alerts_threshold = "errors"` and
`security_alerts_threshold = "high_or_higher"`. A successful analysis job means
that the scanner executed; its result can still contain a blocking finding.
PR-related High/Critical security findings and general Error alerts meet these
thresholds. The scanner-result check and the analysis jobs have different native
identities; a green analysis job does not dismiss its findings.

## GitHub's PR-related scope

[GitHub's code-scanning merge-protection contract](https://docs.github.com/en/code-security/concepts/code-scanning/merge-protection)
defines which findings affect a pull request. In particular, all lines identified
by an alert must appear in that PR's diff. This gate is not a claim that every
historical repository alert blocks every PR. GitHub excludes merge queue groups and Dependabot pull requests analyzed by
default setup from its native code-scanning merge protection. The separately
required Analyze status checks remain a distinct control; inspect the applicable
platform behavior before extending this scope. Do not turn a missing
analysis or an unknown native result into acceptance.

## Ordinary delivery and human approval

Finish the actual change, pass the pinned deterministic quality profile and use
the ordinary Develop PR and Main promotion described in the
[operator guide](protected-runtime-operations.md). Keep existing quality,
current-revision review and genuine one-person normal approval requirements.
The scanner rule does not select a workflow source or activate an evaluated
review rule. Scorecard separately assesses repository and supply-chain posture;
it neither supplies CodeQL analyses nor replaces the review requirement.

An authorized human may review the exact operation in chat and explicitly
confirm it. The agent may then submit that decision through the existing native
approval mechanism under an eligible identity, with honest delegation
provenance and a readback of the outcome. Approval remains bound to the presented
head/run/environment and plan; changed operations need a new confirmation. See
[the repository instructions](../AGENTS.md#owner-authorized-chat-approval-delegation).

## Qualification and recovery

Use bounded unmerged Draft PRs for controlled scanner counterexamples. Retain
actual heads, runs, analyses, alerts and scanner-specific required/failing
signals; Draft status alone is insufficient evidence of scanner enforcement.
Never merge a deliberately vulnerable fixture, fabricate passing checks or
request additional model reviews for these qualification PRs. Keep failed and
cancelled run history.

Acceptance additionally needs a real ordinary Develop/Main change with current
successful analyses and its genuine normal approval. A negative case that is
allowed, or inconclusive scanner-specific evidence, leaves acceptance open.
Any rollback of this new rule must use the existing protected management
plan/apply route and preserve the other protections.
