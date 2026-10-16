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
One initial containment check rejects symlinks and paths escaping the checkout
before any common legacy reader runs. The candidate cannot make those readers
validate the immutable source's compliant documents instead of its own files.
The final control requires the native common-quality job to succeed. Failure,
skipping or cancellation cannot authorize a merge. A promotion's human approval
also waits for this job. One person can still perform the native approval.

Common quality also runs for draft PRs, just as product CI does. It authenticates
the open current head/base but grants no review or merge approval. The independent
review and finalization paths still reject drafts. Moving a draft to ready can
therefore refresh those metadata-sensitive jobs without leaving a failed sibling
quality job behind or requesting another paid review for the same subject.

Product tests continue in their repository; these common checks do not replace
them. Terraform profiles remain blocked until their applicable isolated provider
supply and complete protected semantic validation are natively qualified. Such a profile must not be enabled fleet-wide on the basis of the
reference repository alone.

The new implementation becomes authoritative only after protected integration,
management admission of its immutable source and native qualification. A local
file or successful local test does not enable a private rollout. Reproducible
local execution of this source-owned entry point and the private canary remain
separate rollout acceptance items; existing local Devtools profiles stay usable.

Terraform uses a separate dependency-supply boundary. Offline extraction reads
only literal lockfile coordinates, versions and hashes, admits provider addresses
already present at the exact protected base, and emits canonical dependency-only
inputs. Comments, private configuration and scripts are not included. A fresh
network-enabled container receives only those generated provider inputs and the
public immutable source. It runs Terraform's provider-mirror command, with no
candidate/base checkout, policy file, credentials or provider execution. New
provider addresses require independent onboarding; unknown hosts or malformed
locks block. No private module download is silently enabled.

The actual candidate validation remains network-free, credential-free and
source-owned. Its only provider installation method is the read-only mirror;
there is no direct registry fallback. It runs complete `terraform init` with
backend disabled and `terraform validate`, including each policy validation
root. Existing lockfiles are read-only; unlocked local submodules can create a
temporary lock using only the supplied providers. All workspaces are disposable
copies outside the read-only checkout. A replaced candidate validator that always
returns success cannot make semantically invalid HCL pass this protected check.
The ordinary product validation remains separately mandatory.
