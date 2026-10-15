# Source-owned common quality

The common Required Workflow executes repository-independent checks from its
immutable native defining source. Existing product tests, repository quality,
security checks and review requirements remain mandatory. This adds a job to
the existing workflow; it does not restore any retired repair chain.

The source-only preparation container authenticates the native Required Workflow,
current PR head/base and protected consumer policy. It reads the repository type
from the protected base. It has a read token and no candidate checkout mount.
The separate validation container receives the resulting bounded policy and
candidate checkout as read-only data. It has no token, network or service socket.
Both use the digest-pinned Devtools image in `scripts/run-common-quality.sh`.

The immutable source supplies both the quality engine and Markdown code validator.
A candidate cannot substitute its validator or select another repository type.
Ansible examples use a source-owned configuration outside the candidate tree.
The final control requires the native common-quality job to succeed. Failure,
skipping or cancellation cannot authorize a merge. A promotion's human approval
also waits for this job. One person can still perform the native approval.

Product tests continue in their repository; these common checks do not replace
them. Terraform profiles that need provider downloads remain blocked by this
offline common entry point until their applicable isolated dependency supply is
qualified. Such a profile must not be enabled fleet-wide on the basis of the
reference repository alone.

The new implementation becomes authoritative only after protected integration,
management admission of its immutable source and native qualification. A local
file or successful local test does not enable a private rollout. Reproducible
local execution of this source-owned entry point and the private canary remain
separate rollout acceptance items; existing local Devtools profiles stay usable.
