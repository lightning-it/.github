"""Collect full accepted review evidence for the future protected archive caller.

Read only. This module neither reserves a write nor uploads to S3. In particular,
an absent/expired GitHub artifact is never authority for a new archive operation.
"""
from __future__ import annotations

import base64
import hashlib

import release_package_ingress as ingress
from workflow_control import digest, native_jobs, native_required, require
import workflow_codex


def codex_review(api, repository, reference, proof):
    evidence = proof["evidence"]
    producer = evidence.get("producer", {})
    control = reference["control"]
    require(producer.get("repository") == repository and producer.get("pull_request") == reference["pull"]
            and producer.get("run") == control["run"] and ingress.positive(producer.get("attempt"))
            and producer["attempt"] <= control["attempt"]
            and ingress.positive(producer.get("job")), "archive-codex-producer-binding")
    run = api.call(f"repos/{repository}/actions/runs/{producer['run']}/attempts/{producer['attempt']}")
    require(native_required(run, repository) and run.get("id") == producer["run"]
            and run.get("run_attempt") == producer["attempt"] and run.get("head_sha") == control["head"]
            # A successful verifier-only rerun may inherit this producer even
            # when another job made its original attempt fail. Ingress retrieval
            # separately requires the accepted control attempt to succeed.
            and run.get("status") == "completed",
            "archive-codex-native-attempt")
    jobs = [job for job in native_jobs(api, repository, run) if job.get("id") == producer["job"]]
    require(len(jobs) == 1 and jobs[0].get("name") == "Protected current revision"
            and workflow_codex.successful_producer(jobs[0]), "archive-codex-native-producer")
    artifacts = api.pages(f"repos/{repository}/actions/runs/{producer['run']}/artifacts", "artifacts")
    record, response = workflow_codex.download(api, repository, run, f"codex-receipt-{producer['attempt']}", artifacts)
    receipt = record.get("receipt", {})
    provider = receipt.get("provider", {})
    response_digest = hashlib.sha256(response).hexdigest()
    require(record.get("version") == 1 and record.get("source_sha") == proof["source_sha"]
            and record.get("metadata_sha256") == evidence.get("metadata_sha256")
            and record.get("response_sha256") == response_digest == evidence.get("response_sha256")
            and receipt.get("response_sha256") == response_digest
            and provider.get("request_count") == 1
            and provider.get("request_sha256") == evidence.get("request_sha256")
            and digest(receipt.get("result")) == digest(evidence.get("result")),
            "archive-codex-full-receipt-binding")
    return {"kind": "codex-native-receipt", "producer": producer, "record": record,
            "response_encoding": "base64", "response": base64.b64encode(response).decode("ascii"),
            "response_sha256": response_digest,
            "request_payload_available": False}


def copilot_review(api, repository, reference, proof):
    evidence = proof["evidence"]
    identifier = evidence.get("id")
    frame = evidence.get("frame", {})
    require(ingress.positive(identifier) and frame.get("review_database_id") == identifier
            and ingress.positive(evidence.get("service_run")), "archive-copilot-reference")
    # The existing API reader requests the full native Markdown/HTML format for
    # this list. Do not call the single-review endpoint and lose rendered body.
    reviews = api.pages(f"repos/{repository}/pulls/{reference['pull']}/reviews")
    matches = [review for review in reviews if review.get("id") == identifier]
    require(len(matches) == 1, "archive-copilot-review-missing")
    review = matches[0]
    require(review.get("user", {}).get("id") == 175728472 and review.get("user", {}).get("type") == "Bot"
            and review.get("commit_id") == reference["control"]["head"]
            and review.get("node_id") == frame.get("review_id")
            and review.get("state") == evidence.get("state")
            and type(review.get("body")) is str
            and hashlib.sha256(review["body"].encode()).hexdigest() == frame.get("review_body_sha256"),
            "archive-copilot-full-review-binding")
    run = api.call(f"repos/{repository}/actions/runs/{evidence['service_run']}")
    require(run.get("id") == evidence["service_run"] and run.get("event") == "dynamic"
            and run.get("path") == "dynamic/agents/copilot-pull-request-reviewer"
            and run.get("head_sha") == reference["control"]["head"]
            and run.get("status") == "completed" and run.get("conclusion") == "success",
            "archive-copilot-service-run")
    identifiers = evidence.get("finding_comment_ids")
    require(type(identifiers) is list and all(ingress.positive(item) for item in identifiers)
            and len(set(identifiers)) == len(identifiers), "archive-copilot-comment-reference")
    comments = []
    if identifiers:
        available = api.pages(f"repos/{repository}/pulls/{reference['pull']}/comments")
        for identifier in identifiers:
            matches = [comment for comment in available if comment.get("id") == identifier]
            require(len(matches) == 1 and matches[0].get("user", {}).get("id") == 175728472
                    and matches[0].get("user", {}).get("type") == "Bot"
                    and type(matches[0].get("body")) is str, "archive-copilot-comment-missing")
            comments.append(matches[0])
    return {"kind": "copilot-native-report", "review": review, "service_run": run,
            "referenced_comments": comments,
            # The accepted proof binds comment IDs, not their historical bytes.
            "comment_snapshot": "retrieval-time; historical-byte-digests-unavailable"}


def collect_review(api, repository, reference, proof):
    if proof["route"] == "codex":
        return codex_review(api, repository, reference, proof)
    if proof["route"] == "copilot":
        return copilot_review(api, repository, reference, proof)
    require(proof["route"] in {"renovate", "ancestry", "distribution"}, "archive-review-route")
    return {"kind": "governed-exemption", "route": proof["route"], "evidence": proof["evidence"]}


def assemble(api, repository, promotion, expected_digest, destination, *, maximum=ingress.MAX_PROOF_BYTES):
    return ingress.assemble(api, repository, promotion, expected_digest, destination,
                            maximum=maximum, review_loader=collect_review)
