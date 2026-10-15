"""Protected change control. Never imports or executes consumer candidate code.

Native Required Workflows bind the immutable source; all operations run inside
that consumer. Native run/job records reserve funded effects, independently of
candidate-authored checks or editable PR comments. Unknown outcomes fail closed.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import quote

SOURCE = "lightning-it/.github"
WORKFLOW = ".github/workflows/change-control-required.yml"
RELEASE = ("lightning-it-release-automation[bot]", 307565056, "Bot")
SYNC = ("lightning-it-shared-assets-sync[bot]", 307342877, "Bot")
RENOVATE = ("renovate[bot]", 29139614, "Bot")
COPILOT = "copilot-pull-request-reviewer[bot]"
VERSION = "workflow-control/v1"


class ControlError(RuntimeError):
    """Missing, stale, unsuccessful or ambiguous native evidence."""


def require(condition, message):
    if not condition:
        raise ControlError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def sha(value):
    require(type(value) is str and re.fullmatch(r"[0-9a-f]{40}", value), "invalid-revision")
    return value


class API:
    """No mutation retry; errors never echo provider bodies or private paths."""
    def call(self, path, *, method="GET", data=None):
        require(not path.startswith(("/", "http")), "api-path")
        command = ["gh", "api", "--method", method, path]
        if data is not None:
            command += ["--input", "-"]
        result = subprocess.run(command, input=canonical(data) if data is not None else None,
                                capture_output=True, timeout=60, check=False)
        require(result.returncode == 0, "native-api-unavailable")
        try:
            return json.loads(result.stdout)
        except ValueError as error:
            raise ControlError("native-api-malformed") from error

    def pages(self, path, key=None):
        result = []
        separator = "&" if "?" in path else "?"
        for page in range(1, 101):
            payload = self.call(f"{path}{separator}per_page=100&page={page}")
            items = payload[key] if key else payload
            require(type(items) is list, "native-pagination-shape")
            result.extend(items)
            if len(items) < 100:
                if key and "total_count" in payload:
                    require(len(result) == payload["total_count"], "native-pagination-drift")
                return result
        raise ControlError("native-pagination-incomplete")

    def file(self, repo, path, revision):
        sha(revision)
        value = self.call(f"repos/{repo}/contents/{quote(path, safe='/')}?ref={revision}")
        require(value.get("type") == "file" and value.get("path") == path
                and value.get("encoding") == "base64", "protected-file-shape")
        data = base64.b64decode(value["content"].replace("\n", ""), validate=True)
        blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        require(blob == value["sha"], "protected-file-digest")
        return data


def source_identity(job, expected_path=WORKFLOW):
    require(job.get("workflow_repository") == SOURCE, "untrusted-source-repository")
    require(job.get("workflow_file_path") == expected_path, "untrusted-source-path")
    require(type(job.get("check_run_id")) is int and job["check_run_id"] > 0, "native-job-missing")
    return sha(job.get("workflow_sha"))


def identity(user):
    return user.get("login"), user.get("id"), user.get("type")


def binding(pull):
    return {"number": pull["number"], "base": sha(pull["base"]["sha"]),
            "head": sha(pull["head"]["sha"]), "base_ref": pull["base"]["ref"],
            "head_ref": pull["head"]["ref"], "head_repository": (pull["head"].get("repo") or {}).get("full_name"),
            "author": identity(pull["user"]), "title": pull["title"], "body": pull.get("body"),
            "labels": sorted(label["name"] for label in pull["labels"]), "draft": pull["draft"]}


def live_pull(api, repo, number, expected=None):
    value = api.call(f"repos/{repo}/pulls/{number}")
    require(value["number"] == number and value["state"] == "open" and not value["draft"], "pull-not-reviewable")
    require(value["base"]["repo"]["full_name"] == repo
            and value["base"]["ref"] in {"develop", "main"}, "unsupported-target")
    if expected is not None:
        require(binding(value) == expected, "stale-not-applicable")
    return value


def classify(pull, repo):
    author = identity(pull["user"])
    same = (pull["head"].get("repo") or {}).get("full_name") == repo
    head, base = pull["head"]["ref"], pull["base"]["ref"]
    if author == RELEASE and same and head == "develop" and base == "main":
        return "promotion"
    if (same and base == "develop" and head.startswith("backmerge/") and head.endswith("-main")
            and (author == RELEASE or repo == SOURCE and author == SYNC)):
        return "ancestry"
    if author == RELEASE:
        require(same, "release-app-fork-forbidden")
        return "codex"
    if author == RENOVATE:
        labels = {label["name"] for label in pull["labels"]}
        if same and base == "develop" and head.startswith("renovate/") and {"renovate", "dependencies", "safe-automerge"} <= labels and "breaking-update" not in labels:
            return "renovate"
        return "copilot"
    if author == SYNC:
        require(same and base == "develop", "distribution-shape")
        return "distribution"
    require(pull["user"].get("type") == "User", "unclassified-automation")
    return "copilot"


def policy(api, repo, base):
    value = json.loads(api.file(repo, ".lit/workflow-control.json", base))
    require(value.get("version") == 1 and value.get("repository") == repo, "protected-policy-shape")
    require(value.get("mode") in {"reference", "enforce"}, "scope-not-admitted")
    require(type(value.get("quality")) is list and value["quality"], "quality-policy-missing")
    for item in value["quality"]:
        require(set(item) == {"workflow", "job"} and item["workflow"].startswith(".github/workflows/"), "quality-policy-entry")
    return value


def native_run_source(run, source_sha, *, path=WORKFLOW):
    refs = run.get("referenced_workflows", [])
    wanted = f"{SOURCE}/{path}@"
    return any(type(ref) is dict and ref.get("path", "").startswith(wanted)
               and ref.get("sha") == source_sha for ref in refs)


def native_jobs(api, repo, run):
    items = api.pages(f"repos/{repo}/actions/runs/{run['id']}/attempts/{run['run_attempt']}/jobs", "jobs")
    require(all(item.get("run_id") == run["id"] for item in items), "job-run-drift")
    return items


def check_quality(api, repo, pull, config):
    checks = api.pages(f"repos/{repo}/commits/{pull['head']['sha']}/check-runs?filter=latest", "check_runs")
    proof = []
    for required in config["quality"]:
        matches = [item for item in checks if item.get("name") == required["job"]
                   and item.get("app", {}).get("id") == 15368]
        require(len(matches) == 1, "quality-check-missing-or-ambiguous")
        check = matches[0]
        require(check.get("status") == "completed", "quality-pending")
        require(check.get("conclusion") == "success", "quality-not-successful")
        match = re.fullmatch(rf"https://github.com/{re.escape(repo)}/actions/runs/([1-9][0-9]*)/job/([1-9][0-9]*)", check.get("details_url", ""))
        require(match is not None, "quality-job-origin")
        run = api.call(f"repos/{repo}/actions/runs/{match[1]}")
        require(run["path"] == required["workflow"] and run["head_sha"] == pull["head"]["sha"]
                and run["event"] in {"pull_request", "push"}, "quality-workflow-origin")
        require(any(job["id"] == int(match[2]) and job.get("check_run_url", "").endswith(f"/{check['id']}")
                    and job["conclusion"] == "success" for job in native_jobs(api, repo, run)), "quality-native-job")
        proof.append({"check": check["id"], "run": run["id"], "attempt": run["run_attempt"]})
    return proof


def copilot_review(api, repo, pull):
    reviews = api.pages(f"repos/{repo}/pulls/{pull['number']}/reviews")
    selected = [r for r in reviews if r.get("commit_id") == pull["head"]["sha"]
                and r.get("user", {}).get("id") == 175728472
                and r.get("user", {}).get("type") == "Bot"
                and r.get("user", {}).get("login") in {COPILOT, COPILOT.removesuffix("[bot]"), "Copilot"}]
    if not selected:
        return None
    require(len(selected) == 1, "copilot-review-ambiguous")
    review = selected[0]
    require(review["state"] in {"COMMENTED", "APPROVED"}, "copilot-review-not-accepted")
    comments = api.pages(f"repos/{repo}/pulls/{pull['number']}/reviews/{review['id']}/comments")
    # No finding is silently waved through. A changed revision gets a new review;
    # a resolved finding requires the documented maintainer evidence contract.
    require(not comments, "copilot-findings-require-resolution")
    normalized = re.sub(r"\s+", "", (review.get("body") or "").lower()).replace("can't", "cannot")
    require(normalized and not any(marker in normalized for marker in (
        "unabletoreview", "cannotreview", "nofileswerereviewed", "encounteredanerror",
        "quotaexceed", "quotaexhaust", "premiumrequest", "suppressedcomment")), "copilot-provider-failure")
    return {"id": review["id"], "head": review["commit_id"], "state": review["state"]}


def reserve_request(api, repo, pull, source_sha, run_id, attempt):
    require(attempt == 1, "funded-effect-rerun-forbidden")
    run = api.call(f"repos/{repo}/actions/runs/{run_id}")
    require(native_run_source(run, source_sha) and run["head_sha"] == pull["head"]["sha"], "request-origin")
    runs = api.pages(f"repos/{repo}/actions/runs?head_sha={pull['head']['sha']}", "workflow_runs")
    owners = [r for r in runs if native_run_source(r, source_sha)
              and any(pr.get("number") == pull["number"] for pr in r.get("pull_requests", []))]
    require(owners and min(r["id"] for r in owners) == run_id, "request-slot-already-consumed")
    # The first native workflow run is the durable reservation, before POST.
    # A failed or lost POST response never leads to another automatic request.
    return run_id


def check_renovate(api, repo, pull):
    events = api.pages(f"repos/{repo}/issues/{pull['number']}/events")
    policy_events = [e for e in events if e.get("event") in {"labeled", "unlabeled"}
                     and e.get("label", {}).get("name") in {"safe-automerge", "breaking-update"}]
    safe = [e for e in policy_events if e["label"]["name"] == "safe-automerge"]
    require(safe and safe[-1]["event"] == "labeled" and all(identity(e.get("actor", {})) == RENOVATE for e in safe)
            and not any(e["label"]["name"] == "breaking-update" and e["event"] == "labeled" for e in policy_events), "renovate-policy-provenance")
    return {"kind": "policy-bound-renovate", "label_events": [e["id"] for e in policy_events]}


def check_native_control(api, repo, pull, config):
    """Authenticate the entire native required run, not a caller-authored name."""
    sources = config.get("accepted_sources", [])
    require(type(sources) is list and sources, "accepted-source-lineage-missing")
    for value in sources:
        sha(value)
    runs = api.pages(f"repos/{repo}/actions/runs?head_sha={pull['head']['sha']}", "workflow_runs")
    candidates = []
    for run in runs:
        if not any(native_run_source(run, source) for source in sources):
            continue
        associations = [p for p in run.get("pull_requests", []) if p.get("number") == pull["number"]]
        if len(associations) != 1:
            continue
        associated = associations[0]
        if associated.get("base", {}).get("sha") != pull["base"]["sha"] or associated.get("head", {}).get("sha") != pull["head"]["sha"]:
            continue
        candidates.append(run)
    require(candidates, "ingress-protected-run-missing")
    selected = max(candidates, key=lambda run: (run["id"], run["run_attempt"]))
    require(selected["status"] == "completed" and selected["conclusion"] == "success", "ingress-protected-run-not-successful")
    jobs = native_jobs(api, repo, selected)
    gate = [j for j in jobs if j["name"] == "Current revision review"]
    require(len(gate) == 1 and gate[0]["conclusion"] == "success", "ingress-protected-job-missing")
    return {"run": selected["id"], "attempt": selected["run_attempt"], "job": gate[0]["id"], "head": pull["head"]["sha"]}


def promotion_ingress(api, repo, pull, config):
    # Full first-parent graph avoids GitHub compare's display truncation and
    # duplicate PR attribution of feature commits. Every integration has one PR.
    import tempfile

    from workflow_subject import git
    base, head = pull["base"]["sha"], pull["head"]["sha"]
    with tempfile.TemporaryDirectory(prefix="promotion-objects-", dir=os.environ.get("RUNNER_TEMP")) as temp:
        objects = Path(temp) / "objects.git"
        result = subprocess.run(["git", "init", "--bare", str(objects)], capture_output=True, timeout=30, check=False)
        require(result.returncode == 0, "promotion-git-init")
        git(objects, "config", "credential.helper", "!gh auth git-credential")
        git(objects, "fetch", "--quiet", "--no-tags", "--no-recurse-submodules",
            f"https://github.com/{repo}.git", f"{base}:refs/review/base", f"{head}:refs/review/head")
        ancestor = git(objects, "merge-base", "--all", base, head)
        require(ancestor == base, "promotion-needs-main-ancestry")
        commits = git(objects, "rev-list", "--reverse", "--first-parent", f"{base}..{head}").splitlines()
        require(commits and len(commits) <= 10000, "promotion-ingress-empty-or-unbounded")
        proof = []
        for commit in commits:
            pulls = api.pages(f"repos/{repo}/commits/{commit}/pulls")
            matches = [p for p in pulls if p.get("merged_at") and p.get("merge_commit_sha") == commit
                       and p.get("base", {}).get("ref") == "develop"]
            require(len(matches) == 1, "promotion-unattributed-ingress")
            ingress = api.call(f"repos/{repo}/pulls/{matches[0]['number']}")
            require(ingress["merged_at"] and ingress["merge_commit_sha"] == commit, "ingress-association-drift")
            proof.append({"pull": ingress["number"], "merge": commit,
                          "control": check_native_control(api, repo, ingress, config)})
        tree = sha(git(objects, "merge-tree", "--write-tree", base, head))
        payload = git(objects, "diff", "--binary", "--full-index", "--no-ext-diff", "--no-textconv",
                      f"{base}^{{tree}}", tree, binary=True)
    return {"base": base, "head": head, "integration_tree": tree,
            "diff_sha256": hashlib.sha256(payload).hexdigest(), "ingress": proof}


def ancestry_evidence(api, repo, pull, config):
    import tempfile

    from workflow_subject import git
    base, head = pull["base"]["sha"], pull["head"]["sha"]
    current_main = sha(api.call(f"repos/{repo}/git/ref/heads/main")["object"]["sha"])
    component = repo.split("/", 1)[1].lstrip(".")
    require(pull["head"]["ref"] == f"backmerge/{component}-{current_main[:12]}-{base[:12]}-main"
            and pull["title"] == f"chore(governance): record main ancestry before {current_main[:12]}", "ancestry-exact-operation")
    with tempfile.TemporaryDirectory(prefix="ancestry-objects-", dir=os.environ.get("RUNNER_TEMP")) as temp:
        objects = Path(temp) / "objects.git"
        result = subprocess.run(["git", "init", "--bare", str(objects)], capture_output=True, timeout=30, check=False)
        require(result.returncode == 0, "ancestry-git-init")
        git(objects, "config", "credential.helper", "!gh auth git-credential")
        git(objects, "fetch", "--quiet", "--no-tags", "--no-recurse-submodules",
            f"https://github.com/{repo}.git", base, head, current_main)
        require(git(objects, "show", "-s", "--format=%P", head).split() == [base, current_main], "ancestry-parent-shape")
        require(git(objects, "rev-parse", f"{head}^{{tree}}") == git(objects, "rev-parse", f"{base}^{{tree}}"), "ancestry-content-change")
    return {"main": current_main, "head": head, "unchanged_tree": True}


def distribution_evidence(api, repo, pull, config):
    # New distributor receipts are candidate data until the independently
    # accepted private source run and exact rendered file manifest agree.
    marker = "<!-- lit-distribution/v1 "
    body = pull.get("body") or ""
    require(body.count(marker) == 1, "distribution-receipt-missing")
    encoded = body.split(marker, 1)[1].split(" -->", 1)[0]
    receipt = json.loads(encoded)
    require(set(receipt) == {"source", "source_sha", "run", "files"}, "distribution-receipt-shape")
    allowed = config.get("distribution_sources", [])
    require(receipt["source"] == "lightning-it/shared-assets-lit" and receipt["source_sha"] in allowed, "distribution-source-not-accepted")
    run = api.call(f"repos/{receipt['source']}/actions/runs/{receipt['run']}")
    require(run["head_sha"] == receipt["source_sha"] and run["head_branch"] == "main"
            and run["status"] == "completed" and run["conclusion"] == "success"
            and run["path"] == ".github/workflows/sync-repository-quality-repos.yml", "distribution-native-source")
    files = api.pages(f"repos/{repo}/pulls/{pull['number']}/files")
    manifest = receipt["files"]
    require(type(manifest) is list and len(manifest) == len(files), "distribution-full-coverage")
    actual = []
    for file in files:
        require(file["status"] in {"added", "modified"} and not file.get("previous_filename"), "distribution-change-kind")
        content = api.file(repo, file["filename"], pull["head"]["sha"])
        actual.append({"path": file["filename"], "sha256": hashlib.sha256(content).hexdigest()})
    require(sorted(actual, key=lambda f: f["path"]) == sorted(manifest, key=lambda f: f["path"]), "distribution-manifest-drift")
    # Verify the actual source-run-produced manifest artifact, not a PR assertion.
    artifacts = api.pages(f"repos/{receipt['source']}/actions/runs/{run['id']}/artifacts", "artifacts")
    expected_name = "distribution-" + repo.split("/", 1)[1]
    artifacts = [a for a in artifacts if a["name"] == expected_name and not a["expired"]]
    require(len(artifacts) == 1, "distribution-source-manifest-missing")
    import tempfile
    with tempfile.TemporaryDirectory(prefix="distribution-manifest-") as temp:
        result = subprocess.run(["gh", "run", "download", str(run["id"]), "--repo", receipt["source"],
                                 "--name", expected_name, "--dir", temp], capture_output=True, timeout=60, check=False)
        require(result.returncode == 0, "distribution-manifest-unavailable")
        records = list(Path(temp).glob("*.json"))
        require(len(records) == 1 and json.loads(records[0].read_text()) == receipt, "distribution-source-manifest-drift")
    return {"source_run": run["id"], "source_sha": receipt["source_sha"], "manifest_sha256": digest(manifest)}


def output(name, value):
    require(re.fullmatch(r"[a-z_]+", name) and "\n" not in str(value), "output-shape")
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as file:
        file.write(f"{name}={value}\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("classify", "review", "finalize", "reserve-codex", "verify-codex"))
    args = parser.parse_args()
    api = API()
    repo = os.environ["GITHUB_REPOSITORY"]
    require(re.fullmatch(r"lightning-it/[A-Za-z0-9_.-]+", repo), "consumer-repository")
    source_sha = source_identity(json.loads(os.environ["NATIVE_JOB"]))
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    number = event.get("pull_request", {}).get("number")
    require(type(number) is int and number > 0, "pull-event-required")
    pull = live_pull(api, repo, number)
    expected = binding(pull)
    require(pull["head"]["sha"] == event["pull_request"]["head"]["sha"]
            and pull["base"]["sha"] == event["pull_request"]["base"]["sha"], "stale-event")
    config = policy(api, repo, pull["base"]["sha"])
    route = classify(pull, repo)
    if args.operation == "classify":
        output("route", route)
        output("base", pull["base"]["sha"])
        output("head", pull["head"]["sha"])
        return
    if args.operation == "reserve-codex":
        require(route == "codex", "codex-identity-required")
        reserve_request(api, repo, pull, source_sha, int(os.environ["GITHUB_RUN_ID"]), int(os.environ["GITHUB_RUN_ATTEMPT"]))
        live_pull(api, repo, number, expected)
        return
    if args.operation == "verify-codex":
        require(route == "codex", "codex-identity-required")
        import exact_revision_gateway as gateway
        directory = Path("exact-revision-review")
        metadata = json.loads((directory / "review-metadata.json").read_text())
        require(metadata["base_sha"] == expected["base"] and metadata["head_sha"] == expected["head"]
                and metadata["central_source_sha"] == source_sha, "codex-subject-drift")
        result = json.loads((directory / "result.json").read_text())
        gateway.validate_result(result, metadata)
        require(result["verdict"] == "PASS" and not result["findings"], "codex-findings-or-failure")
        live_pull(api, repo, number, expected)
        print("Protected exact-revision Codex result verified.")
        return
    if args.operation == "review":
        require(route != "codex", "codex-job-required")
        review = None
        if route == "copilot":
            review = copilot_review(api, repo, pull)
            if review is None and identity(pull["user"]) == ("litroc", 76040632, "User"):
                requested = api.call(f"repos/{repo}/pulls/{number}/requested_reviewers")
                if not any(u.get("login") in {COPILOT, COPILOT.removesuffix("[bot]")} for u in requested["users"]):
                    reserve_request(api, repo, pull, source_sha, int(os.environ["GITHUB_RUN_ID"]), int(os.environ["GITHUB_RUN_ATTEMPT"]))
                    live_pull(api, repo, number, expected)
                    api.call(f"repos/{repo}/pulls/{number}/requested_reviewers", method="POST", data={"reviewers": [COPILOT]})
            for _ in range(80):
                live_pull(api, repo, number, expected)
                review = copilot_review(api, repo, pull)
                if review:
                    break
                time.sleep(15)
            require(review is not None, "current-copilot-review-missing")
        elif route == "renovate":
            review = check_renovate(api, repo, pull)
        elif route == "promotion":
            review = promotion_ingress(api, repo, pull, config)
        elif route == "ancestry":
            review = ancestry_evidence(api, repo, pull, config)
        elif route == "distribution":
            review = distribution_evidence(api, repo, pull, config)
        else:
            raise ControlError("unclassified-review-route")
        live_pull(api, repo, number, expected)
        # Native job is the authoritative result; no synthetic successful check.
        print(f"Verified {route} for exact current revision; native evidence retained.")
        return
    require(os.environ.get("REVIEW_RESULT") == "success", "review-job-not-successful")
    if route == "promotion":
        require(os.environ.get("APPROVAL_RESULT") == "success", "native-human-approval-required")
        promotion_ingress(api, repo, pull, config)
    for observation in range(80):
        live_pull(api, repo, number, expected)
        try:
            check_quality(api, repo, pull, config)
            break
        except ControlError as error:
            if str(error) not in {"quality-check-missing-or-ambiguous", "quality-pending"} or observation == 79:
                raise
            time.sleep(15)
    live_pull(api, repo, number, expected)
    print("Protected current-revision control passed.")


if __name__ == "__main__":
    try:
        main()
    except (ControlError, KeyError, ValueError, OSError, subprocess.SubprocessError) as error:
        print(f"Protected control blocked: {type(error).__name__}: {error if isinstance(error, ControlError) else 'required evidence unavailable'}", file=sys.stderr)
        raise SystemExit(1) from None
