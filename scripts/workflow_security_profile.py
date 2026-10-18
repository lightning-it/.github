"""Source-owned, data-only Security Main admission. No producer is admitted by default."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from workflow_control import (MAX_OPERATION_BYTES, RELEASE, ControlError, artifact_record, binding, canonical,
                              check_native_control, digest, identity, live_pull, native_jobs, require, sha)

PROFILE = "release-app-security/v1"
MARKER = "<!-- lit-security-premerge/v1 "
FILENAME = "security-premerge-proof.json"
REGISTRY = Path(__file__).resolve().parents[1] / ".lit/workflow-security-producers.json"
MATERIAL_MAX = 1024 * 1024
# One bounded packet plus 64 KiB for the native ZIP container overhead. This
# bounds reported download size, not expansion performed by the existing gh CLI.
MAX_ARTIFACT_BYTES = MAX_OPERATION_BYTES + 65536
HEX = re.compile(r"[0-9a-f]{64}")
SEMVER = re.compile(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)")
TUPLE_KEYS = {"number", "base", "head", "base_ref", "head_ref", "head_repository", "author"}
PACKET_KEYS = {"version", "profile", "kind", "repository", "repository_id", "binding", "integration_tree",
               "diff_sha256", "chain_id", "evidence_id", "fixed_version", "acceptance_profile", "issued_at",
               "expires_at", "revoked", "producer", "materials"}
ENTRY_KEYS = {"id", "repository", "repository_id", "kind", "source_sha", "workflow", "workflow_blob", "job",
              "files", "acceptance_profiles", "environment", "expires_at", "revoked"}
GENERATED = {"galaxy.yml", "CHANGELOG.rst", "changelogs/changelog.yaml", "changelogs/.plugin-cache.yaml",
             "changelogs/release-preparation.json"}


def exact(value, keys, category):
    require(type(value) is dict and set(value) == set(keys), category)
    return value


def integer(value):
    return type(value) is int and value > 0


def timestamp(value):
    require(type(value) is str and value.endswith("Z"), "security-time-shape")
    result = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    require(result.tzinfo is not None, "security-time-zone")
    return result


def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "security-duplicate-json-key")
        result[key] = value
    return result


def decode(raw, *, canonical_required=False, maximum=MAX_OPERATION_BYTES):
    require(type(maximum) is int and 0 < maximum <= MATERIAL_MAX
            and type(raw) is bytes and 0 < len(raw) <= maximum, "security-json-resource-bound")
    # The native artifact reader already preflights its allocation. Apply the
    # same existing resource admission to registry and small material documents.
    import single_review_resources as resources
    limits = resources.memory_contract()
    require(len(raw) <= limits["max_wire_bytes"], "security-json-resource-bound")
    resources.preflight_json(raw, limits["max_json_nodes"], limits["max_json_depth"])
    import math
    def reject_constant(_value):
        raise ControlError("security-nonfinite-json")
    def finite_float(token):
        number = float(token)
        require(math.isfinite(number), "security-nonfinite-json")
        return number
    value = json.loads(raw, object_pairs_hook=unique, parse_constant=reject_constant, parse_float=finite_float)
    if canonical_required:
        require(canonical(value) == raw, "security-noncanonical-proof")
    return value


def registry():
    require(REGISTRY.is_file() and not REGISTRY.is_symlink(), "security-source-registry-required")
    value = exact(decode(REGISTRY.read_bytes()), {"version", "producers"}, "security-registry-shape")
    require(type(value["version"]) is int and value["version"] == 1 and type(value["producers"]) is list,
            "security-registry-version")
    identifiers = set()
    for entry in value["producers"]:
        exact(entry, ENTRY_KEYS, "security-producer-binding-shape")
        require(type(entry["id"]) is str and re.fullmatch(r"[a-z0-9][a-z0-9-]{2,95}", entry["id"])
                and entry["id"] not in identifiers, "security-producer-binding-duplicate")
        identifiers.add(entry["id"])
        require(re.fullmatch(r"lightning-it/[A-Za-z0-9_.-]+", entry["repository"])
                and integer(entry["repository_id"]) and entry["kind"] in {"intake", "preparation"},
                "security-producer-target")
        sha(entry["source_sha"]); sha(entry["workflow_blob"])
        require(entry["workflow"] == ".github/workflows/" + (
            "security-release-intake.yml" if entry["kind"] == "intake" else "release-prepare.yml")
            and type(entry["job"]) is str and entry["job"]
            and entry["environment"] == "mlx90-security-promotion-authorization", "security-producer-profile")
        require(type(entry["files"]) is dict and entry["workflow"] in entry["files"]
                and all(safe_path(path) and type(value) is str and HEX.fullmatch(value)
                        for path, value in entry["files"].items()), "security-producer-files")
        require(type(entry["acceptance_profiles"]) is list and entry["acceptance_profiles"]
                and all(type(item) is str and item for item in entry["acceptance_profiles"]), "security-domain-profiles")
        require(type(entry["revoked"]) is bool, "security-producer-revocation-shape")
        timestamp(entry["expires_at"])
    return value["producers"]


def validate_policy(config, repo):
    if "security_profile" not in config:
        return
    require(config["security_profile"] == PROFILE, "security-profile-unknown")
    require(any(entry["repository"] == repo for entry in registry()), "security-producer-not-admitted")


def safe_path(path):
    return (type(path) is str and path and not path.startswith("/") and "\\" not in path
            and all(part not in {"", ".", ".."} for part in path.split("/")))


def subject(pull):
    value = binding(pull)
    return {key: value[key] for key in TUPLE_KEYS}


def security_shape(pull, repo):
    head = pull["head"]["ref"]
    return (pull["base"]["ref"] == "main" and identity(pull["user"]) == RELEASE
            and pull["head"].get("repo", {}).get("full_name") == repo
            and (re.fullmatch(r"security-release/MLX90-[A-Z0-9][A-Z0-9._-]{2,127}", head)
                 or re.fullmatch(r"release/v" + SEMVER.pattern, head)))


@dataclass(frozen=True)
class VerifiedSecurity:
    record: dict

    def summary(self):
        return json.loads(canonical(self.record))


def permits(evidence, repo, pull):
    return (type(evidence) is VerifiedSecurity and evidence.record.get("repository") == repo
            and evidence.record.get("binding") == subject(pull))


def packet_shape(packet, entry, repo, pull, locator, now):
    exact(packet, PACKET_KEYS, "security-proof-shape")
    require(type(packet["version"]) is int and packet["version"] == 1 and packet["profile"] == PROFILE
            and packet["repository"] == repo and packet["repository_id"] == entry["repository_id"]
            and packet["kind"] == entry["kind"] and canonical(packet["binding"]) == canonical(subject(pull))
            and set(packet["binding"]) == TUPLE_KEYS, "security-proof-subject")
    exact(packet["producer"], {"id", "run", "attempt", "job", "source_sha"}, "security-proof-producer")
    require(all(packet["producer"][key] == locator[key] for key in ("id", "run", "attempt"))
            and integer(packet["producer"]["run"]) and integer(packet["producer"]["attempt"])
            and integer(packet["producer"]["job"]) and packet["producer"]["source_sha"] == pull["base"]["sha"],
            "security-proof-native-locator")
    sha(packet["integration_tree"])
    require(type(packet["diff_sha256"]) is str and HEX.fullmatch(packet["diff_sha256"])
            and re.fullmatch(r"sha256:[0-9a-f]{64}", packet["chain_id"])
            and re.fullmatch(r"MLX90-[A-Z0-9][A-Z0-9._-]{2,127}", packet["evidence_id"])
            and SEMVER.fullmatch(packet["fixed_version"])
            and packet["acceptance_profile"] in entry["acceptance_profiles"], "security-proof-release-binding")
    issued, expires = timestamp(packet["issued_at"]), timestamp(packet["expires_at"])
    require(packet["revoked"] is False and issued <= now < expires,
            "security-proof-expired-or-revoked")
    expected = (f"security-release/{packet['evidence_id']}" if entry["kind"] == "intake"
                else f"release/v{packet['fixed_version']}")
    require(pull["head"]["ref"] == expected, "security-proof-head-shape")
    materials = packet["materials"]
    require(type(materials) is list and 3 <= len(materials) <= 259, "security-material-count")
    observed = set()
    for item in materials:
        exact(item, {"role", "at", "path", "sha256"}, "security-material-shape")
        require(item["role"] in {"receipt", "metadata", "intake", "fragment"} and item["at"] in {"base", "head"}
                and safe_path(item["path"]) and HEX.fullmatch(item["sha256"])
                and item["path"] not in observed, "security-material-duplicate-or-path")
        observed.add(item["path"])
    require(sum(item["role"] == "receipt" for item in materials) == 1
            and sum(item["role"] == "metadata" for item in materials) == 1
            and any(item["role"] == "fragment" for item in materials), "security-material-roles")
    return issued


def generation(api, repo, entry, run):
    runs = api.pages(f"repos/{repo}/actions/runs?head_sha={run['head_sha']}", "workflow_runs")
    relevant = [item for item in runs if item.get("workflow_id") == run["workflow_id"]
                and item.get("head_sha") == run["head_sha"] and item.get("head_branch") == "main"]
    require(len(relevant) == 1 and all(relevant[0].get(key) == run.get(key) for key in (
        "id", "run_attempt", "status", "conclusion", "head_sha", "path", "workflow_id")),
        "security-producer-generation-drift-or-duplicate")


def producer(api, repo, pull, entry, locator):
    require(entry["revoked"] is False and datetime.now(UTC) < timestamp(entry["expires_at"]),
            "security-producer-expired-or-revoked")
    repository = api.call(f"repos/{repo}")
    require(repository.get("id") == entry["repository_id"] and not repository.get("archived")
            and not repository.get("disabled"), "security-native-repository")
    base = api.call(f"repos/{repo}/branches/main")
    require(base.get("protected") is True and base.get("commit", {}).get("sha") == pull["base"]["sha"],
            "security-protected-main-drift")
    run = api.call(f"repos/{repo}/actions/runs/{locator['run']}")
    workflow = api.call(f"repos/{repo}/actions/workflows/{entry['workflow'].rsplit('/', 1)[1]}")
    require(integer(run.get("id")) and integer(run.get("run_attempt"))
            and run.get("id") == locator["run"] and run.get("run_attempt") == locator["attempt"]
            and run.get("repository", {}).get("id") == entry["repository_id"]
            and run.get("head_repository", {}).get("id") == entry["repository_id"]
            and run.get("head_sha") == pull["base"]["sha"] and run.get("head_branch") == "main"
            and run.get("path") == entry["workflow"] and workflow.get("path") == entry["workflow"]
            and integer(workflow.get("id")) and workflow.get("state") == "active"
            and run.get("workflow_id") == workflow["id"]
            and run.get("event") == ("workflow_dispatch" if entry["kind"] == "intake" else "push")
            and identity(run.get("actor", {})) == RELEASE and identity(run.get("triggering_actor", {})) == RELEASE
            and run.get("status") == "completed" and run.get("conclusion") == "success", "security-native-producer")
    ancestry = api.call(f"repos/{repo}/compare/{entry['source_sha']}...{run['head_sha']}")
    require(ancestry.get("status") in {"identical", "ahead"}, "security-producer-source-not-integrated")
    for path, expected in entry["files"].items():
        raw = api.file(repo, path, run["head_sha"])
        require(hashlib.sha256(raw).hexdigest() == expected, "security-producer-code-drift")
        if path == entry["workflow"]:
            blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
            require(blob == entry["workflow_blob"], "security-producer-workflow-blob")
    jobs = native_jobs(api, repo, run)
    selected = [job for job in jobs if job.get("name") == entry["job"]]
    require(len(selected) == 1 and selected[0].get("status") == "completed"
            and selected[0].get("conclusion") == "success", "security-native-producer-job")
    generation(api, repo, entry, run)
    return run, selected[0]


def git_materials(repo, pull, packet, entry):
    """Never check out, import, or execute consumer files."""
    from workflow_subject import fetch_objects, git
    with tempfile.TemporaryDirectory(prefix="security-proof-", dir=os.environ.get("RUNNER_TEMP")) as temp:
        objects = Path(temp) / "objects.git"
        result = subprocess.run(["git", "init", "--bare", str(objects)], capture_output=True, timeout=30, check=False)
        require(result.returncode == 0, "security-git-init")
        base, head = pull["base"]["sha"], pull["head"]["sha"]
        fetch_objects(objects, repo, f"{base}:refs/review/base", f"{head}:refs/review/head")
        require(git(objects, "rev-parse", "refs/review/base") == base
                and git(objects, "rev-parse", "refs/review/head") == head
                and git(objects, "show", "-s", "--format=%P", head) == base, "security-git-parent")
        expected_identity = f"{RELEASE[0]} <307565056+{RELEASE[0]}@users.noreply.github.com>"
        require(all(git(objects, "show", "-s", f"--format={field}", head) == expected_identity
                    for field in ("%an <%ae>", "%cn <%ce>")), "security-git-app-identity")
        tree = sha(git(objects, "merge-tree", "--write-tree", base, head))
        diff_args = ("diff", "--binary", "--full-index", "--no-color", "--no-ext-diff", "--no-textconv",
                     f"{base}^{{tree}}", tree)
        payload = git(objects, *diff_args, binary=True)
        require(tree == packet["integration_tree"] and payload
                and hashlib.sha256(payload).hexdigest() == packet["diff_sha256"], "security-full-git-subject")
        materials = {}
        for item in packet["materials"]:
            revision = base if item["at"] == "base" else head
            file_entry = git(objects, "ls-tree", "-z", revision, "--", item["path"], binary=True)
            require(file_entry.count(b"\0") == 1 and file_entry.startswith(b"100644 blob "), "security-material-mode")
            blob = sha(file_entry.split(b"\t", 1)[0].split()[2].decode("ascii"))
            from single_review_resources import wire_limit
            size = int(git(objects, "cat-file", "-s", blob))
            require(0 < size <= min(MATERIAL_MAX, wire_limit()), "security-material-size")
            raw = git(objects, "cat-file", "blob", blob, binary=True)
            require(len(raw) == size, "security-material-size-drift")
            require(hashlib.sha256(raw).hexdigest() == item["sha256"], "security-material-digest")
            materials[item["path"]] = raw if item["role"] == "fragment" else decode(raw, maximum=MATERIAL_MAX)
        profiles_path = ".lit/security-release-profiles.json"
        require(git(objects, "ls-tree", "-z", base, "--", profiles_path, binary=True).startswith(b"100644 blob "),
                "security-protected-domain-profiles-mode")
        domain = decode(git(objects, "show", f"{base}:{profiles_path}", binary=True))
        require(domain.get("schemaVersion") == 1 and domain.get("profiles", {}).get(
            packet["acceptance_profile"], {}).get("releaseEligible") is True, "security-domain-profile-not-release-eligible")
        receipt_path = next(item["path"] for item in packet["materials"] if item["role"] == "receipt")
        candidate = git(objects, *diff_args, "--", ".", f":(exclude){receipt_path}", binary=True)
        changed = git(objects, "diff", "--name-status", "--no-renames", base, head).splitlines()
        changes = [line.split("\t") for line in changed]
        require(not any(len(change) != 2 or change[1] in set(entry["files"]) | {
            profiles_path, ".lit/workflow-control.json"} for change in changes), "security-authority-file-changed")
        if packet["kind"] == "preparation":
            parents = git(objects, "show", "-s", "--format=%P", base).split()
            require(len(parents) == 2 and git(objects, "rev-parse", f"{base}^{{tree}}")
                    == git(objects, "rev-parse", f"{parents[1]}^{{tree}}"), "security-prior-intake-merge-tree")
            materials["_base_parents"] = parents
            versions = []
            for revision in (base, head):
                raw = git(objects, "show", f"{revision}:galaxy.yml", binary=True).decode("utf-8")
                matches = re.findall(r"(?m)^version:\s*[\"']?([0-9]+\.[0-9]+\.[0-9]+)[\"']?\s*$", raw)
                require(len(matches) == 1 and SEMVER.fullmatch(matches[0]), "security-galaxy-version-shape")
                versions.append(matches[0])
            materials["_versions"] = versions
        return materials, hashlib.sha256(candidate).hexdigest(), changes


def material_contract(packet, documents, candidate_diff, changes):
    version = packet["fixed_version"]
    roles = {}
    for item in packet["materials"]:
        roles.setdefault(item["role"], []).append(item)
    require(len(roles.get("receipt", [])) == 1 and len(roles.get("metadata", [])) == 1
            and roles.get("fragment"), "security-material-roles")
    receipt_item, metadata_item = roles["receipt"][0], roles["metadata"][0]
    metadata_path = f".lit/security-releases/{version}.json"
    intake_path = f".lit/security-release-intakes/{version}.json"
    require(metadata_item["path"] == metadata_path and metadata_item["at"] == "head", "security-metadata-location")
    metadata = documents[metadata_path]
    require(type(metadata) is dict and metadata.get("schemaVersion") == 1
            and metadata.get("evidenceId") == packet["evidence_id"] and metadata.get("fixedVersion") == version
            and metadata.get("acceptanceProfile") == packet["acceptance_profile"], "security-metadata-binding")
    validity = metadata.get("validity", {})
    now = datetime.now(UTC)
    require(validity.get("revoked") is False and timestamp(validity.get("notBefore")) <= now
            < timestamp(validity.get("expiresAt")), "security-metadata-expired-or-revoked")
    receipt = documents[receipt_item["path"]]
    if packet["kind"] == "intake":
        require(set(roles) == {"receipt", "metadata", "fragment"} and receipt_item["path"] == intake_path
                and receipt_item["at"] == "head" and all(item["at"] == "head" for item in roles["fragment"]),
                "security-intake-materials")
        intake = receipt
        require(["A", intake_path] in changes, "security-intake-receipt-not-new")
    else:
        require(set(roles) == {"receipt", "metadata", "intake", "fragment"} and len(roles["intake"]) == 1
                and roles["intake"][0]["path"] == intake_path and roles["intake"][0]["at"] == "base"
                and receipt_item["path"] == "changelogs/release-preparation.json" and receipt_item["at"] == "head"
                and all(item["at"] == "base" for item in roles["fragment"]), "security-preparation-materials")
        intake = documents[intake_path]
        require(type(receipt) is dict and receipt.get("schema_version") == 2
                and receipt.get("release_mode") == "security" and receipt.get("chain_id") == packet["chain_id"]
                and receipt.get("next_version") == version and receipt.get("base_sha") == packet["binding"]["base"]
                and receipt.get("repository") == packet["repository"]
                and receipt.get("repository_id") == str(packet["repository_id"]), "security-preparation-binding")
        require(receipt.get("preparer") == {"login": RELEASE[0], "account_id": str(RELEASE[1]),
                "email": f"307565056+{RELEASE[0]}@users.noreply.github.com"}, "security-preparation-app")
        expected_fragments = [{"path": item["path"].removeprefix("changelogs/fragments/"), "sha256": item["sha256"]}
                              for item in roles["fragment"]]
        actual_fragments = receipt.get("fragments")
        require(type(actual_fragments) is list and all(type(item) is dict and set(item) == {"path", "sha256"}
                for item in actual_fragments) and sorted(actual_fragments, key=lambda item: item["path"])
                == sorted(expected_fragments, key=lambda item: item["path"]), "security-preparation-fragments")
        current_version = documents["_versions"][0]
        major, minor, patch = (int(value) for value in current_version.split("."))
        require(documents["_versions"][1] == version and receipt.get("current_version") == current_version
                and version == f"{major}.{minor}.{patch + 1}", "security-preparation-patch-version")
        security = receipt.get("security", {})
        intake_item = roles["intake"][0]
        require(security.get("evidence_id") == packet["evidence_id"]
                and security.get("metadata_path") == metadata_path
                and security.get("metadata_sha256") == "sha256:" + metadata_item["sha256"]
                and security.get("intake_receipt_path") == intake_path
                and security.get("intake_receipt_sha256") == "sha256:" + intake_item["sha256"]
                and security.get("human_actions") == 0, "security-preparation-security-binding")
        workflow = receipt.get("workflow", {})
        require(workflow.get("source_sha") == packet["binding"]["base"]
                and workflow.get("run_id") == str(packet["producer"]["run"])
                and workflow.get("run_attempt") == str(packet["producer"]["attempt"])
                and workflow.get("path") == ".github/workflows/release-prepare.yml"
                and workflow.get("ref") == packet["repository"] + "/.github/workflows/release-prepare.yml@refs/heads/main"
                and workflow.get("event") == "push" and workflow.get("git_ref") == "refs/heads/main"
                and workflow.get("actor") == RELEASE[0], "security-preparation-controller-binding")
        allowed = GENERATED | {item["path"] for item in roles["fragment"]}
        require(all(len(change) == 2 and (change[1] in GENERATED and change[0] in {"A", "M"}
                    or change == ["D", change[1]] and change[1] in allowed - GENERATED) for change in changes)
                and all(["D", item["path"]] in changes for item in roles["fragment"])
                and all(any(change[1] == path for change in changes) for path in GENERATED),
                "security-preparation-extra-or-missing-path")
    require(type(intake) is dict and intake.get("schemaVersion") == 2 and intake.get("chainId") == packet["chain_id"],
            "security-intake-binding")
    request, verified = intake.get("request", {}), intake.get("verified", {})
    require(request.get("schemaVersion") == 2 and verified.get("schemaVersion") == 2,
            "security-intake-version")
    sha(request.get("baseSha")); sha(request.get("candidateHeadSha"))
    require(request.get("candidateBaseSha") == request["baseSha"]
            and re.fullmatch(r"sha256:[0-9a-f]{64}", request.get("candidateDiffSha256", "")),
            "security-intake-candidate-shape")
    automation = intake.get("automation", {})
    require(automation.get("login") == RELEASE[0] and automation.get("accountId") == str(RELEASE[1])
            and automation.get("type") == RELEASE[2] and automation.get("slug") == "lightning-it-release-automation",
            "security-intake-app")
    for key, expected in (("repository", packet["repository"]), ("repositoryId", str(packet["repository_id"])),
                          ("chainId", packet["chain_id"]), ("evidenceId", packet["evidence_id"]),
                          ("fixedVersion", version), ("acceptanceProfile", packet["acceptance_profile"])):
        require(request.get(key) == expected, "security-intake-request-binding")
    require(request.get("event") == "mlx90-security-release" and request.get("humanActions") == 0
            and timestamp(request.get("issuedAt")) <= now < timestamp(request.get("expiresAt")),
            "security-intake-event-or-validity")
    for key in ("chainId", "baseSha", "candidateBaseSha", "candidateHeadSha", "evidenceId", "fixedVersion",
                "acceptanceProfile", "candidateDiffSha256", "metadataSha256"):
        require(verified.get(key) == request.get(key), "security-intake-verified-binding")
    require(request.get("metadataSha256") == "sha256:" + metadata_item["sha256"], "security-intake-metadata-digest")
    fragments = roles["fragment"]
    bound = [item for item in fragments if item["path"] == verified.get("changelogFragmentPath")]
    require((packet["kind"] != "intake" or len(fragments) == 1) and len(bound) == 1
            and all(re.fullmatch(r"changelogs/fragments/[A-Za-z0-9][A-Za-z0-9._-]*\.ya?ml", item["path"])
                    for item in fragments)
            and verified.get("changelogFragmentSha256") == "sha256:" + bound[0]["sha256"],
            "security-intake-fragment-digest")
    require(packet["issued_at"] == request.get("issuedAt") and packet["expires_at"] == request.get("expiresAt"),
            "security-request-envelope-time-binding")
    chain = {key: request.get(key) for key in ("repository", "repositoryId", "baseSha", "candidateHeadSha",
             "candidateDiffSha256", "evidenceId", "fixedVersion", "acceptanceProfile")}
    require("sha256:" + digest(chain) == packet["chain_id"], "security-intake-chain-digest")
    if packet["kind"] == "intake":
        require(request.get("baseSha") == packet["binding"]["base"]
                and request.get("candidateDiffSha256") == "sha256:" + candidate_diff
                and verified.get("changedPaths") == sorted(change[1] for change in changes if change[1] != intake_path),
                "security-intake-complete-candidate-diff")
        controller = intake.get("controller", {})
        require(controller.get("sourceSha") == packet["binding"]["base"]
                and controller.get("runId") == str(packet["producer"]["run"])
                and controller.get("runAttempt") == str(packet["producer"]["attempt"])
                and controller.get("path") == ".github/workflows/security-release-intake.yml"
                and controller.get("ref") == packet["repository"] + "/.github/workflows/security-release-intake.yml@refs/heads/main"
                and controller.get("event") == "workflow_dispatch" and controller.get("gitRef") == "refs/heads/main"
                and controller.get("actor") == RELEASE[0] and controller.get("triggeringActor") == RELEASE[0],
                "security-intake-controller-binding")


def prior_intake(api, repo, pull, config, packet, documents):
    """A historical receipt is not acceptance: require actual common intake control."""
    if packet["kind"] != "preparation":
        return
    receipt = documents[f".lit/security-release-intakes/{packet['fixed_version']}.json"]
    parents = documents["_base_parents"]
    require(parents[0] == receipt["request"]["baseSha"], "security-prior-intake-base")
    candidates = api.pages(f"repos/{repo}/commits/{pull['base']['sha']}/pulls")
    matches = [item for item in candidates if item.get("merged_at")
               and item.get("merge_commit_sha") == pull["base"]["sha"]]
    require(len(matches) == 1, "security-prior-intake-pr-ambiguous")
    intake = api.call(f"repos/{repo}/pulls/{matches[0]['number']}")
    require(intake.get("merged") is True and intake.get("state") == "closed"
            and intake.get("merge_commit_sha") == pull["base"]["sha"]
            and intake["base"]["sha"] == parents[0] and intake["head"]["sha"] == parents[1]
            and intake["base"]["ref"] == "main"
            and intake["head"]["ref"] == f"security-release/{packet['evidence_id']}"
            and intake["head"].get("repo", {}).get("full_name") == repo
            and identity(intake["user"]) == RELEASE, "security-prior-intake-pr-binding")
    native = check_native_control(api, repo, intake, config)
    run = api.call(f"repos/{repo}/actions/runs/{native['run']}")
    proof = artifact_record(api, repo, run, f"control-proof-{native['attempt']}", "control-proof.json")
    risk = proof.get("security", {})
    require(proof.get("route") == "codex" and risk.get("profile") == PROFILE
            and risk.get("kind") == "intake" and risk.get("binding") == subject(intake),
            "security-prior-intake-independent-proof")


def _authorize(api, repo, pull, config):
    if pull["base"]["ref"] != "main" or pull["head"]["ref"] == "develop":
        return None
    require(config.get("security_profile") == PROFILE, "security-main-profile-required")
    require(identity(pull["user"]) == RELEASE and pull["head"].get("repo", {}).get("full_name") == repo,
            "security-exact-same-repository-app")
    body = pull.get("body") or ""
    require(body.count(MARKER) == 1, "security-producer-locator-required")
    suffix = body.split(MARKER, 1)[1]
    require(" -->" in suffix, "security-producer-locator-shape")
    locator = exact(decode(suffix.split(" -->", 1)[0].encode()), {"producer", "run", "attempt"}, "security-locator-shape")
    locator = {"id": locator["producer"], "run": locator["run"], "attempt": locator["attempt"]}
    require(integer(locator["run"]) and integer(locator["attempt"]) and locator["attempt"] <= 32, "security-locator-identity")
    entries = [entry for entry in registry() if entry["id"] == locator["id"] and entry["repository"] == repo]
    require(len(entries) == 1, "security-producer-not-admitted")
    entry = entries[0]
    run, job = producer(api, repo, pull, entry, locator)
    packet = artifact_record(api, repo, run, f"security-premerge-{locator['attempt']}", FILENAME)
    issued = packet_shape(packet, entry, repo, pull, locator, datetime.now(UTC))
    require(packet["producer"]["job"] == job.get("id") and issued <= timestamp(job["completed_at"]),
            "security-proof-job-time-binding")
    environment = api.call(f"repos/{repo}/environments/{entry['environment']}")
    require(environment.get("name") == entry["environment"] and environment.get("can_admins_bypass") is False
            and type(environment.get("protection_rules")) is list
            and not any(rule.get("type") in {"required_reviewers", "wait_timer"}
                        for rule in environment["protection_rules"]), "security-reviewer-free-environment")
    documents, candidate_diff, changes = git_materials(repo, pull, packet, entry)
    material_contract(packet, documents, candidate_diff, changes)
    prior_intake(api, repo, pull, config, packet, documents)
    live_pull(api, repo, pull["number"], binding(pull))
    current, current_job = producer(api, repo, pull, entry, locator)
    require(current == run and current_job == job, "security-native-producer-changed")
    # Final generation read follows all mutable subject/producer reads; no I/O
    # after this selector can hide a newly started or failed producer generation.
    generation(api, repo, entry, run)
    proof = VerifiedSecurity({"profile": PROFILE, "kind": entry["kind"], "repository": repo,
                             "binding": subject(pull), "producer": packet["producer"],
                             "proof_sha256": digest(packet), "registry_sha256": digest(entry)})
    validity = documents[f".lit/security-releases/{packet['fixed_version']}.json"]["validity"]
    now = datetime.now(UTC)
    require(timestamp(packet["issued_at"]) <= now < timestamp(packet["expires_at"])
            and timestamp(validity["notBefore"]) <= now < timestamp(validity["expiresAt"])
            and now < timestamp(entry["expires_at"]), "security-final-validity-expired")
    return proof


def authorize(api, repo, pull, config):
    try:
        return _authorize(api, repo, pull, config)
    except (KeyError, TypeError, AttributeError, StopIteration, UnicodeError, ValueError) as error:
        raise ControlError("security-malformed-proof") from error
