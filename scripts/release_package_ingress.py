"""Rehydrate accepted ingress references; this component cannot authorize a release.

The caller authenticates the promotion proof and supplies its expected canonical
digest. Review payloads, product evidence, reservation and S3 delivery remain the
finalizer's responsibility. No workflow calls this component yet.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

from workflow_control import (
    MAX_PROOF_BYTES, artifact_record, digest, native_jobs,
    native_required, require, sha,
)


def positive(value):
    return type(value) is int and value > 0


def references(promotion):
    """Check the published compact contract before any remote retrieval."""
    require(type(promotion) is dict and promotion.get("version") == 1
            and promotion.get("route") == "promotion", "package-promotion-proof")
    bound, evidence = promotion.get("binding"), promotion.get("evidence")
    require(type(bound) is dict and type(evidence) is dict, "package-promotion-binding")
    require(positive(bound.get("number")) and bound.get("base_ref") == "main"
            and bound.get("head_ref") == "develop"
            and evidence.get("base") == sha(bound.get("base"))
            and evidence.get("head") == sha(bound.get("head")), "package-promotion-binding")
    sha(promotion.get("source_sha"))
    sha(evidence.get("integration_tree"))
    items = evidence.get("ingress")
    require(type(items) is list and 0 < len(items) <= 10000, "package-ingress-count")
    pulls, merges = set(), set()
    for item in items:
        require(type(item) is dict and positive(item.get("pull")), "package-ingress-reference")
        merge = sha(item.get("merge"))
        require(item["pull"] not in pulls and merge not in merges, "package-duplicate-ingress")
        pulls.add(item["pull"])
        merges.add(merge)
        control = item.get("control")
        require(type(control) is dict and all(positive(control.get(key)) for key in ("run", "attempt", "job")),
                "package-control-reference")
        require(control.get("artifact") == f"control-proof-{control['attempt']}"
                and control.get("route") in {"copilot", "codex", "ancestry", "distribution", "renovate"}
                and type(control.get("proof_sha256")) is str
                and re.fullmatch(r"[0-9a-f]{64}", control["proof_sha256"]), "package-control-reference")
        sha(control.get("head"))
        sha(control.get("source_sha"))
    return items


def retrieve(api, repository, reference):
    """Read the named historical attempt, never the latest attempt's proof."""
    control = reference["control"]
    run = api.call(f"repos/{repository}/actions/runs/{control['run']}/attempts/{control['attempt']}")
    require(native_required(run, repository) and run.get("id") == control["run"]
            and run.get("run_attempt") == control["attempt"] and run.get("head_sha") == control["head"]
            and run.get("status") == "completed" and run.get("conclusion") == "success",
            "package-native-attempt")
    jobs = [job for job in native_jobs(api, repository, run) if job.get("id") == control["job"]]
    require(len(jobs) == 1 and jobs[0].get("name") == "Current revision review"
            and jobs[0].get("conclusion") == "success", "package-native-job")
    proof = artifact_record(api, repository, run, control["artifact"], "control-proof.json")
    # REST jobs lack the runner's defining-source context. Preserve the source
    # authenticated by the accepted promotion reference, not guessed REST fields.
    # The producer hashes canonical JSON, not ZIP or pretty-printed file bytes.
    require(digest(proof) == control["proof_sha256"], "package-ingress-digest")
    require(type(proof) is dict and proof.get("version") == 1
            and proof.get("source_sha") == control["source_sha"]
            and proof.get("route") == control["route"], "package-ingress-proof")
    bound = proof.get("binding")
    require(type(bound) is dict and bound.get("number") == reference["pull"]
            and bound.get("head") == control["head"] and bound.get("base_ref") == "develop",
            "package-ingress-binding")
    pull = api.call(f"repos/{repository}/pulls/{reference['pull']}")
    require(pull.get("number") == reference["pull"] and pull.get("merged") is True
            and pull.get("merge_commit_sha") == reference["merge"]
            and pull.get("base", {}).get("repo", {}).get("full_name") == repository
            and pull.get("base", {}).get("ref") == "develop"
            and pull.get("head", {}).get("sha") == control["head"], "package-merged-ingress")
    return proof


def assemble(api, repository, promotion, expected_digest, destination: Path, *, maximum=MAX_PROOF_BYTES, review_loader=None):
    """Write a complete component atomically, with bounded sequential proof reads.

    Destination must be in the caller's private, trusted output directory. A
    failure preserves an existing destination and removes our incomplete file.
    The returned digest covers the exact component bytes, including final LF.
    """
    require(type(repository) is str and re.fullmatch(r"lightning-it/[A-Za-z0-9_.-]+", repository),
            "package-repository")
    require(type(maximum) is int and 0 < maximum <= MAX_PROOF_BYTES, "package-size-limit")
    require(type(expected_digest) is str and re.fullmatch(r"[0-9a-f]{64}", expected_digest)
            and digest(promotion) == expected_digest, "package-promotion-digest")
    items = references(promotion)
    require(promotion["binding"].get("head_repository") == repository, "package-repository-binding")
    require(not destination.exists() and not destination.is_symlink(), "package-output-exists")
    descriptor, temporary = tempfile.mkstemp(prefix=".release-ingress-", dir=destination.parent)
    size, checksum = 0, hashlib.sha256()
    try:
        with os.fdopen(descriptor, "wb") as stream:
            def write(payload):
                nonlocal size
                require(size + len(payload) <= maximum, "package-size-limit")
                stream.write(payload)
                checksum.update(payload)
                size += len(payload)

            def value(record):
                # Match workflow_control.canonical without allocating another
                # complete proof or retaining earlier decoded proof records.
                for chunk in json.JSONEncoder(sort_keys=True, separators=(",", ":"), ensure_ascii=True).iterencode(record):
                    write(chunk.encode())

            write(b'{"component":"release-ingress/v1","complete_release":false,"promotion":')
            value(promotion)
            write(b',"ingress":[')
            for index, reference in enumerate(items):
                if index:
                    write(b",")
                write(b'{"reference":')
                value(reference)
                write(b',"proof":')
                proof = retrieve(api, repository, reference)
                value(proof)
                if review_loader is not None:
                    write(b',"review":')
                    review = review_loader(api, repository, reference, proof)
                    value(review)
                    del review
                del proof
                write(b"}")
            write(b"]}\n")
            stream.flush()
            os.fsync(stream.fileno())
        # Atomic no-clobber publication; rename/replace would overwrite evidence.
        os.link(temporary, destination)
        return {"component": "release-ingress/v1", "sha256": checksum.hexdigest(),
                "bytes": size, "ingress_count": len(items), "complete_release": False}
    finally:
        os.unlink(temporary)
