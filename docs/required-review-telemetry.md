# Offline review telemetry

`scripts/required-review-telemetry.py` is an independent offline JSON reducer.
It needs no observer installation, GitHub access, token, network or workflow.
It does not verify native evidence or authorize checks, review or merge.
The read-only LI-219 integration in closed PR #722 is not a dependency.

Run it in pinned Devtools against a JSON array of observation records:

```sh
scripts/wunder-devtools-ee.sh python3 scripts/required-review-telemetry.py observations.json
```

The script also accepts `-` for standard input. It reads at most 8 MiB plus
one overflow-detection byte and accepts at most 10,000 observations. It writes
only its JSON result to stdout; malformed input returns a sanitized rejection
and exit code 1, without exposing file paths or input text.

Each observation contains:

- `schema: "li219-shadow-observation/v1"`, `authority: "none"`, integer `writes: 0`;
- lowercase 64-character SHA-256 strings `operation_key` and `binding_digest`;
- integer `observed_at` (Unix seconds, zero through 10^12);
- `metrics.native_failure_with_ready_evidence` as a required boolean;
- optional non-negative finite measurements (at most 10^12 seconds):
  `producer_job_seconds`, `request_to_review_seconds`, `review_to_neutral_seconds`,
  `neutral_to_observer_seconds`, `request_to_observer_seconds`.

Missing measurements and explicit null both mean unknown, never zero.
Other observation/metric metadata is ignored; this is a projection of supplied
advisory observations, not an authenticity or full event-schema validator.
The input owner is responsible for producing comparable, correctly bound data.

For each operation, all binding digests must agree. The earliest observation
supplies latency measurements; missing earliest values are not backfilled.
Equal timestamps are broken deterministically by the lexicographically smallest
sorted-key JSON of normalized measured values (numbers normalized to floats).
This tie-break is reproducibility only, not a claim of better sample quality.
The failure flag is OR-ed across **all** observations, independently of which
latency sample is selected. Thus a later native failure cannot disappear during
deduplication. Every duplicate is validated before it can be discarded.

Statistics use one selected sample per operation: ordinary median and
nearest-rank P95, with a separate observed-sample count for each metric.
The candidate rate counts unique operations with any supplied failure flag,
divided by all unique operations; an empty cohort yields null. It is **not** a
measured false-negative rate (that field always remains null). No rollout,
live latency reduction, production acceptance or activation is implied.

This is LI-226, the first owner-authorized independent split of LI-219. LI-227
owns transport/structured errors and must start only after this split completes.
Observer assembly, protected writers and operational measurements remain out
of scope; existing required checks and production polling are untouched.
