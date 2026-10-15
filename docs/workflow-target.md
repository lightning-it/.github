# Safe workflow target

Contract version: **1.0.0**. Status: **defined, inactive**.

Concrete entry points and their delivery states are assigned in the
[workflow target catalog](workflow-target-catalog.md).

The owner adopted a safe long-term target. The POC operating procedure remains
in force until each migration scope passes its actual acceptance. Publishing
this specification neither enables mandatory AI review nor changes rulesets,
permissions, environments or existing release workflows.

## Process contracts

| ID | Function | Required outcome and failure behavior |
| --- | --- | --- |
| WF-01 | Local quality | Deterministic checks in the pinned Devtools image; no local AI review; actual failures stop push-ready |
| WF-02 | PR quality and security | Applicable tests, dependency/secret/security checks and source scanning on the actual current revision; missing or skipped required work cannot pass |
| WF-03 | Protected current-revision review | Existing author/risk matrix chooses the permitted Copilot or exact Release-App Codex path; stale results, unknown classification, budget or provider failures block |
| WF-04 | Promotion preparation | Automatically prepare or update one develop-to-main PR per repository and target branch; duplicate events do not create duplicate PRs or reviews |
| WF-05 | Release authorization | One authorized person can approve their own normal operation; no second classic PR reviewer; the separately governed technical Security path remains reviewer-free |
| WF-06 | Artifact assurance and publication | Applicable build/install tests, scans, SBOM, provenance and signatures; verify the actual published bytes before claiming release acceptance |
| WF-07 | Release and audit archive | Native evidence for develop PRs; one durable package at main promotion; seven years of verified immutable retention in the existing private Hetzner S3 evidence store |

These are process functions, not a requirement for seven independent workflow
files. Non-publishing repository types do not acquire an artificial artifact
or signature requirement. Their applicable governance evidence remains distinct
from product release artifacts.

## Source, execution and trust boundaries

This public repository is the common verification source. Consumer repositories
reference accepted immutable commits. Product tests and publishing remain in
their product repository. Private runs, credentials and outputs retain their
consumer's private boundary; explicit permissions replace blanket secret
inheritance. Distribution tools propagate callers and configuration, without
maintaining a second independent common verifier.

The accepted protected base controls authorization, reviewer policy and source
bindings. Candidate code cannot select or execute its own authorization policy.
Changes to the common authority must be checked by the previously accepted
source. There is no central verifier dependency on a Collection repository.

The author/risk matrix remains authoritative, with no blanket dual review.
Only a permitted finalized candidate can incur a review request. Identity binds
repository, PR, base, head, policy and complete input digest. A new head requires
new applicable checks; duplicate delivery of an unchanged request does not grant
another request. Service or budget failures are visible blocking states without
an automatic provider, identity or billing fallback.

A pure develop-to-main promotion verifies the complete native ingress-review
evidence under the existing lifecycle policy; it does not request a second AI
review of the cumulative diff. New unreviewed ingress or changed input cannot
be disguised as already reviewed promotion content.

Public collaboration content must be checked before publication. Public
definitions and messages contain no private tracker identifiers, private URLs,
credentials or internal consumer configuration. The internal process register
contains the private implementation and acceptance references.

## Migration and acceptance

Each current workflow, service, inherited requirement, caller and generator is
mapped to a function and a disposition: keep, replace/consolidate, remove or add.
Missing documentation alone does not justify removal. Keep a needed receiver
until its callers have a functioning replacement; migrate generators with it.
File presence and a proposed disposition do not prove operational acceptance.

Roll out central source and management first, followed by private distribution,
the Collection reference, additional profiles and the remaining fleet. Require
a working reference, three real changes without required corrections, a bounded
canary and bounded waves. Do not manufacture empty changes as acceptance runs.

Acceptance covers a complete one-person normal path, separately authorized
Security behavior, real test/security/review failures, stale revisions,
duplicate events, private output boundaries, source/ruleset/generator cycles,
artifact verification and actual immutable archive retention. An unavailable
archive blocks the corresponding release acceptance; short-lived Actions
artifacts are not a substitute for seven-year retention.

Roll back to the last accepted immutable source. The POC exception ends only
for a scope that actually passed and was deliberately activated. Legacy
recovery controllers are not restored merely because the target retains their
underlying required review function.

## Machine-readable interface

`.lit/workflow-target.json` declares the target functions, profiles and fixed
boundaries. `scripts/lit-workflow-contract.py` validates it as part of the pinned
repository-quality profile. It is an offline specification validator: it does
not write GitHub checks, call a reviewer, authorize a release, grant permissions
or prove live acceptance. Its output reports safe diagnostic categories only.

The contract deliberately remains `defined` and `inactive`. Actual rollout
requires separately implemented and tested source, consumer, management and
native acceptance paths. Changing a JSON status field is not activation.

## Release archive adapter

`scripts/lit-release-archive.py` stores a protected caller's already assembled
release package in the existing private Hetzner S3 store. It checks the expected
SHA-256 before upload, sets seven calendar years of per-version COMPLIANCE
retention and verifies the exact returned version through separate read and
retention-review credentials. A repeated serialized call may verify only the
existing reserved object with its original full retention still intact. The adapter
never changes bucket policy/defaults, deletes objects, retries uncertain writes
or grants release authorization.

The private consumer supplies `LIT_ARCHIVE_ENDPOINT`, `LIT_ARCHIVE_BUCKET`,
`LIT_ARCHIVE_SSE_C_KEY_B64` and distinct `LIT_ARCHIVE_{WRITER,READER,REVIEWER}_ACCESS_KEY_ID`
and `LIT_ARCHIVE_{WRITER,READER,REVIEWER}_SECRET_ACCESS_KEY` values. Credentials stay
in process memory. The receipt contains the private object/version locator and
must remain in the consumer's private execution context. Standard output reports
safe categories only. Do not inherit all consumer secrets.

This storage adapter does not establish native review, approval, package
completeness, artifact authenticity or long-term encryption-key recovery. The
protected promotion producer must verify these before accepting a release.
No workflow invokes this adapter yet; adding its source does not activate the
target or qualify a repository for rollout.

Hetzner does not guarantee conditional PUT/DELETE on versioned buckets. The
adapter therefore uses normal PUT plus exact-version GET; `verify-existing`
uses HEAD/GET and never writes. Without bucket-list rights, a nonexistent object
returns 403 rather than a reliable absence signal. No failed lookup is treated
as permission to upload.

The protected caller must persist one unique `--reservation` before invoking
`--operation create` exactly once, and serialize the whole operation in one
shared concurrency group per consumer repository and target branch. Duplicate
or interrupted deliveries use `--operation verify-existing` with that same
reservation. Missing/ambiguous state or uncertain writes block; they never
trigger another create automatically. The adapter is only a storage primitive,
not a reservation authority or atomic multi-writer coordinator. The native
reservation/serialization producer remains an explicit rollout prerequisite.
