# Lightning IT contribution guidance

## Pull requests

- Every pull request must request review from GitHub Copilot (`copilot-pull-request-reviewer[bot]`).
- Treat Copilot findings as actionable review comments: reproduce the issue, fix it, and add a regression test where practical.
- Do not dismiss a finding without documenting why it is a false positive in the pull request.
- A pull request is mergeable only after all required automated checks pass and
  all review conversations are resolved. Lightning IT currently requires zero
  human or CODEOWNER approvals under LIT-ENG-ADR-REP-70; do not infer a human
  approval requirement from CODEOWNERS presence.
- Keep changes scoped; do not make unrelated formatting or dependency changes while addressing review feedback.

## Security and fail-closed behavior

- Validate external/API input types explicitly; do not silently coerce malformed values.
- Prefer least-privilege credentials and pin third-party Actions to immutable commit SHAs.
- Add tests for authorization, secret scope, and failure paths when changing governance or release automation.

<!-- LIT AI task governance: start -->

## AI model and token governance

Apply `LIT-GEN-GDR-GOV-30-Budget-Conscious-AI-Model-Selection` to every
substantive Codex or ChatGPT-assisted task. Before investigation, planning, tool
use, implementation, or delegation, record a compact task profile in the task
chat: work item, risk (`low`, `normal`, or `high`), smallest sufficient
model/reasoning choice, rationale, and a concrete escalation condition.

- Use the balanced, lowest reliable capability by default. Escalate to a
  premium/frontier model or higher reasoning only for a high-risk decision,
  complex architecture/debugging/dependencies, or a documented focused failure
  of the standard approach. Restrict that escalation to the difficult subtask.
- Never use Speed Mode. Do not replace verification with a more expensive model
  or sacrifice quality to reduce elapsed time.
- Retrieve only relevant issue, files, logs, and source records; avoid broad
  repository or chat-history loading, speculative analysis, and unbounded retry
  loops. Delegate only independent, bounded work that reduces total effort.
- For GitHub or Jira work, include the task profile in the issue/task record
  when AI assistance materially affects execution. Close with verification and
  remaining risks; preserve durable decisions in Confluence, Jira, or GitHub.

<!-- LIT AI task governance: end -->
