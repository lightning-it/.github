# Closed Security Main foundation (LTN344 #15486)

This Source-only foundation is connected to the existing protected controller.
It activates no consumer and admits **zero producers**:
the hand-maintained `SOURCE_REGISTRY` data literal in
`scripts/workflow_security_profile.py` is `{version:1,producers:[]}`. Its canonical
JSON passes the same bounded strict decoder and schema validation, yielding
detached data; no external registry file or Product Python is loaded. Changes
to this authority require native review of the Source module. No example
producer, consumer JSON, branch name, receipt or successful local fixture is
runtime acceptance. Control proof source, delivery adapter lineage and Product
producer revisions remain separate immutable bindings.

The exact optional protected-base policy selector is
`"security_profile":"release-app-security/v1"`. Absent means unchanged default
routing. Unknown/malformed selectors or an unregistered producer fail closed.
A genuine Source-verified Security proof can admit only exact same-repository
Release App `security-release/MLX90-* -> main` intake or Security
`release/v<stable-version> -> main` preparation. Both retain the **complete
existing `codex` route**, native request reservation, budget/gateway, current
response and quality checks. Normal Develop→Main remains `promotion` and retains
its genuine native one-person approval. No general App exception exists.

The read-only `workflow_security_profile.py` validates independent actual native
run/workflow/job, App actor and triggering actor, exact repository ID, attempt,
protected Main base, registered immutable workflow blob and complete helper
closure, successful unambiguous latest producer generation, and a native artifact.
It uses existing bounded native artifact parsing and data-only Git object helpers.
It never checks out/imports/executes Product Python. Strict packet decoding rejects
duplicate keys, noncanonical JSON, oversized data, malformed/unknown/expired/
revoked profiles, stale tuple/diff/tree/materials and unknown producer code.
Producer and live PR are re-read; final native generation enumeration follows
all evidence reads. Finalization independently repeats proof validation after
review/quality reads, before writing the final native acceptance proof.

A prospective Source-owned registry entry has exact keys:
`id, repository, repository_id, kind, source_sha, workflow, workflow_blob, job,
files, acceptance_profiles, environment, expires_at, revoked`. `files` maps the
workflow and complete immutable helper closure paths to SHA256. `source_sha`
must be integrated on protected Main; actual producer source may descend from
it only with identical registered bytes. `kind` is intake/preparation, workflow
is the corresponding existing protected workflow, and environment is the exact
reviewer-free `mlx90-security-promotion-authorization`. Registry admission needs
reviewed final producer bytes and real native qualification; none is supplied.

The fixed emitter protocol is `lit-security-premerge/v1`: one PR-body locator
`<!-- lit-security-premerge/v1 {"producer":"ID","run":N,"attempt":N} -->`, one
artifact `security-premerge-ATTEMPT`, file `security-premerge-proof.json`.
Maximum is the existing 262144-byte operation bound, canonical compact sorted
UTF-8 JSON without a newline. Packet fields are exactly `version, profile, kind,
repository, repository_id, binding, integration_tree, diff_sha256, chain_id,
evidence_id, fixed_version, acceptance_profile, issued_at, expires_at, revoked,
producer, materials`. `binding` is the existing immutable seven-field PR tuple;
producer keys are `id, run, attempt, job, source_sha`. Material keys are
`role, at, path, sha256`; roles receipt/metadata/fragment and preparation-only
intake, at base/head, with plain64hex SHA256. The producer timestamps bind the
original valid v2 request envelope, never a refreshed authorization lifetime.

Packet and material bounds are separate. Every listed regular mode100644 Git
material is admitted using `cat-file -s` before its blob is read: nonempty,
at most1048576 bytes (matching the Product emitter), and within the unchanged
dynamic wire-memory limit. The byte count is verified again after reading.
Only material JSON uses that larger per-file decoder bound; packet and small
Source registry remain capped at262144. Existing memory, JSON-node and depth
admission applies unchanged; this grants no larger review or funding budget.

For this new Security artifact only, actual native `size_in_bytes` must be a
positive integer at most327680 before download (262144 packet bytes plus65536
container-overhead allowance), also within the existing wire-memory limit.
After the existing `gh run download`, the directory must contain exactly the
named regular, non-symlink JSON file, with no extra file or directory, including
hidden entries. Strict parsing independently enforces the original packet bound.
Legacy artifact behavior is unchanged. The metadata bound limits reported
download size; it does not prove a bound on expansion performed by `gh` before
the directory/packet checks. No new ZIP extractor or claimed ZIP-bomb guarantee
is introduced. The empty producer registry and required independent native
qualification remain closed boundaries before any runtime adoption.

Source recomputes the full binary integration diff, exact tree, regular-file
modes/material digests, v2 chain and metadata bindings, protected-base release-
eligible domain profile, and candidate diff excluding only the new intake
receipt. Preparation additionally requires exact patch-version progression,
only the five generated release files and declared consumed fragments, and
actual previous common Security intake acceptance. A historical POC receipt or
an ordinary Codex result without a Security intake proof does not qualify.
Authority/profile/producer files cannot change inside this privileged patch.
One-time receipt-only recovery is deliberately unsupported; no controlled model
recovery or additional funding contract is added here.

The existing `common-quality` job calls `workflow_recovery.py plan` before the
primary review controller. That planner first authenticates the native Required
run and exact PR association. For these exact App/Main forms only, a known
protected-base selector validated against the immutable Source registry returns
`NONE` when no recovery request exists. This withdraws recovery/funding only;
it does not classify or accept a Security proof. An existing recovery request,
unknown selector or empty registry fails closed. The primary controller then
calls the full independent producer/Git validator before `reserve-codex`, and
calls it again after review/quality evidence during `finalize`.

Risk profile/producer proof digests bind the operation and final proof. Schema7
review metadata is unchanged: it already binds Source/base/head and complete
review subject. The runtime producer packet is **not** claimed to be model input.
No budget schema, gateway, funding or workflow file changes are made.

Producer-only cutover can withdraw a legacy paid dispatch when the protected
Main selector is exactly known; that selector grants no common admission. The
producer emits and completes without waiting for merge. Only separately reviewed
registry bindings and actual native proof can allow common funding. Fresh heads,
original one-consume accounting and serial Root integration are prerequisites;
previous paid heads cannot be relabeled or funded again. Product release checks,
post-Main Sigstore/attestations, Security evidence, archive and publication/consumer
acceptance remain separate. No S3/Nexus or qualification is simulated.
