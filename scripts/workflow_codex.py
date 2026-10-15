"""Native producer authentication for the protected exact-revision review.

Cached evidence is installed only for an authenticated native producer. The
gateway then compares the actual complete client request before returning the
original response bytes; metadata alone never grants cross-run acceptance.
"""
from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

from workflow_control import (
    MAX_PROOF_BYTES,
    binding,
    canonical,
    digest,
    native_required,
    operation_record,
    require,
)

EXPORT_STEP = "Export protected native Codex evidence"
COLLECT_STEP = "Collect and verify the protected model receipt"


def validate_record(record, wire, metadata, source):
    import exact_revision_gateway as gateway

    require(record.get("version") == 1 and record.get("source_sha") == source
            and record.get("metadata_sha256") == digest(metadata)
            and metadata.get("central_source_sha") == source, "codex-native-input-binding")
    receipt = record.get("receipt", {})
    require(record.get("response_sha256") == gateway.review.sha(wire)
            and receipt.get("response_sha256") == record["response_sha256"], "codex-native-wire-binding")
    provider = receipt.get("provider", {})
    hashes = provider.get("request_sha256")
    require(provider.get("request_count") == 1 and type(hashes) is list and len(hashes) == 1
            and type(hashes[0]) is str and re.fullmatch(r"[0-9a-f]{64}", hashes[0])
            and provider.get("model") == gateway.config.profile()["model"], "codex-native-complete-request")
    result = receipt.get("result")
    gateway.validate_result(result, metadata)
    require(result["verdict"] == "PASS" and not result["findings"], "codex-native-findings-or-failure")
    return record


def download(api, repo, run, name, artifacts):
    import bounded_review_transport as transport
    import single_review_resources as resources
    from workflow_proofs import read_native_json
    matches = [a for a in artifacts if a.get("name") == name and a.get("expired") is False]
    require(len(matches) == 1 and type(matches[0].get("size_in_bytes")) is int
            and 0 < matches[0]["size_in_bytes"] <= MAX_PROOF_BYTES, "codex-native-artifact-admission")
    with tempfile.TemporaryDirectory(prefix="native-codex-") as temp:
        result = subprocess.run(["gh", "run", "download", str(run["id"]), "--repo", repo,
                                 "--name", name, "--dir", temp], capture_output=True, timeout=60, check=False)
        require(result.returncode == 0, "codex-native-artifact-unavailable")
        directory = Path(temp)
        require({p.name for p in directory.iterdir()} == {"provider-native.json", "provider-response.bin"},
                "codex-native-artifact-files")
        record = read_native_json(directory / "provider-native.json", MAX_PROOF_BYTES)
        path = directory / "provider-response.bin"
        maximum = min(MAX_PROOF_BYTES, resources.wire_limit(), transport.MAX_RESPONSE_BYTES)
        require(path.is_file() and not path.is_symlink() and 0 < path.stat().st_size <= maximum,
                "codex-native-artifact-file-bound")
        return record, path.read_bytes()


def native_evidence(api, repo, pull, metadata, source, *, only_run=None):
    if only_run is None:
        runs = api.pages(f"repos/{repo}/actions/runs?head_sha={pull['head']['sha']}", "workflow_runs")
    else:
        runs = [only_run]
    for run in sorted(runs, key=lambda r: r["id"], reverse=True):
        if not native_required(run, repo) or run.get("head_sha") != pull["head"]["sha"]:
            continue
        associations = [p for p in run.get("pull_requests", []) if p.get("number") == pull["number"]
                        and p.get("base", {}).get("sha") == pull["base"]["sha"]
                        and p.get("head", {}).get("sha") == pull["head"]["sha"]]
        if len(associations) != 1:
            continue
        artifacts = api.pages(f"repos/{repo}/actions/runs/{run['id']}/artifacts", "artifacts")
        names = [a["name"] for a in artifacts if re.fullmatch(r"codex-receipt-[1-9][0-9]*", a["name"])
                 and a.get("expired") is False]
        if not names:
            continue
        operation = operation_record(api, repo, run)
        if operation.get("source_sha") != source or operation.get("binding") != binding(pull):
            continue
        latest = None
        for attempt in range(run["run_attempt"], 0, -1):
            jobs = api.pages(f"repos/{repo}/actions/runs/{run['id']}/attempts/{attempt}/jobs", "jobs")
            producers = [j for j in jobs if j.get("run_id") == run["id"]
                         and j.get("name") == "Protected current revision"
                         and not (j.get("conclusion") == "skipped"
                                  and all(s.get("conclusion") == "skipped" for s in j.get("steps", [])))]
            require(len(producers) <= 1, "codex-native-producer-ambiguous")
            if producers:
                latest = (attempt, producers[0])
                break
        if latest is None:
            continue
        attempt, job = latest
        successful = (job.get("conclusion") == "success"
                      and all(any(s.get("name") == step and s.get("conclusion") == "success"
                                  for s in job.get("steps", [])) for step in (EXPORT_STEP, COLLECT_STEP)))
        if only_run is not None:
            require(successful, "codex-latest-native-producer-not-successful")
        if not successful:
            continue
        name = f"codex-receipt-{attempt}"
        if name not in names:
            continue
        record, wire = download(api, repo, run, name, artifacts)
        if record.get("source_sha") != source or record.get("metadata_sha256") != digest(metadata):
            continue
        validate_record(record, wire, metadata, source)
        producer = {"repository": repo, "pull_request": pull["number"],
                    "run": run["id"], "attempt": attempt, "job": job["id"]}
        return record | {"producer": producer}, wire
    return None


def prepare(api, repo, pull, metadata, source, directory):
    cached = native_evidence(api, repo, pull, metadata, source)
    if cached is None:
        return False
    record, wire = cached
    for name, payload in (("reuse-candidate.json", canonical(record)), ("reuse-response.bin", wire)):
        with (directory / name).open("xb") as destination:
            destination.write(payload)
    return True


def current_evidence(api, repo, pull, metadata, source, native):
    found = native_evidence(api, repo, pull, metadata, source, only_run=native)
    require(found is not None, "codex-current-native-producer-required")
    record, _wire = found
    return {"producer": record["producer"], "metadata_sha256": record["metadata_sha256"],
            "response_sha256": record["response_sha256"],
            "request_sha256": record["receipt"]["provider"]["request_sha256"],
            "result": record["receipt"]["result"], "replayed": record["receipt"].get("replayed", False)}
