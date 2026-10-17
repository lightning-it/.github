# Release package ingress component

`scripts/release_package_ingress.py` implements the first bounded packaging step
of WF-07. The protected finalizer supplies an authenticated promotion proof and
its independently obtained canonical SHA-256. `assemble` retrieves each exact
`control-proof-<attempt>` reference in that proof, checks the native successful
attempt/job, accepted source/proof digest and actual merged PR, then
writes the complete proof into a private component. It preserves the original
promotion proof, including its recorded native approval, without requesting a
review or granting approval. REST job responses do not expose the runner's
defining-source context: source authority comes from the authenticated promotion
reference and matching full proof, not fabricated REST source fields.

The reference's `proof_sha256` uses the existing `workflow_control.canonical`
JSON representation. It is not a ZIP digest or the hash of arbitrary JSON
formatting. The component receipt separately hashes its exact output bytes.
Historical accepted attempts are read explicitly; a newer attempt cannot be
silently substituted. Each downloaded proof uses the existing native reader's
memory admission. Only one full ingress proof is retained at a time, output is
streamed with a total 50 MiB ceiling, and missing, expired, changed or excessive
evidence fails closed. A private temporary file is published only after complete
validation using an atomic no-overwrite link. The caller provides a trusted
private destination directory and admits the initial promotion proof using the
existing native JSON reader before calling this module.

`scripts/workflow_archive.py` adds the full native review payload per ingress.
For Codex it downloads the exact accepted producer's receipt and original
response bytes, verifies the accepted metadata, complete request hash, result
and response digest, and stores the full response as base64. The current native
receipt publishes a request hash, not the raw client request; the component
records that limitation explicitly. For Copilot it retains the matching full
Markdown/HTML report, native service run and referenced finding comments. The
accepted report-body digest must still match. Finding-comment IDs are bound by
the existing proof, but historical comment-byte hashes are not; these comments
are labeled as retrieval-time snapshots. Governed exemptions preserve their
actual evidence without manufacturing a model review.

This is a component, not a complete accepted release package. Its output carries
`complete_release: false`. Raw request preservation where required, product
build/scan/SBOM/signature/provenance and published-byte verification where
applicable, final integration verification, the permanent one-write reservation,
shared serialization, S3 delivery/read-back, and native acceptance remain the
finalizer's responsibility. No workflow invokes this component yet. Root has no
product publishing target; its governance proof cannot establish an artifact
release acceptance for a product repository.

An expiring Actions artifact or a missing/unknown S3 lookup cannot grant a new
write. The native caller must bind a persistent reservation to the exact original
producer run/attempt and package digest before any create. All duplicate runs and
retries must only verify that reservation. This module intentionally has no
reservation creation fallback, S3 write, automatic review request or new workflow.
