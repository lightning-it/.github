"""One source-owned first-policy Git delta; never candidate code or admission."""
from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from workflow_control import RELEASE, digest, identity, policy_value, require, sha

REPOSITORY = "lightning-it/container-ee-wunder-devtools-ubi9"
REPOSITORY_ID = 1110305651
POLICY = ".lit/workflow-control.json"
DESCRIPTOR = Path(__file__).resolve().parents[1] / ".lit/devtools-first-policy.json"


@dataclass(frozen=True)
class FirstPolicy:
    """Process-local protected-source result, never a consumer JSON flag."""
    source: str
    head: str | None
    purpose: str
    descriptor_digest: str


def blob(payload):
    return hashlib.sha1(b"blob " + str(len(payload)).encode() + b"\0" + payload).hexdigest()


def descriptor():
    value = json.loads(DESCRIPTOR.read_bytes())
    require(value.get("version") == 1 and value.get("repository") == REPOSITORY
            and type(value.get("repository_id")) is int and value["repository_id"] == REPOSITORY_ID,
            "devtools-descriptor-identity")
    # Only the descriptor's independently accepted protected Shared source is
    # bound here; a draft or candidate policy never supplies that authority.
    require(value["shared_source"]["status"] == "accepted-protected-source",
            "devtools-shared-source-not-accepted")
    sha(value["shared_source"]["accepted_sha"])
    return value


def commit(api, revision, expected=None):
    value = api.call(f"repos/{REPOSITORY}/git/commits/{sha(revision)}")
    require(value.get("sha") == revision and type(value.get("tree")) is dict
            and type(value.get("parents")) is list, "devtools-commit-shape")
    record = {"sha": revision, "tree": sha(value["tree"].get("sha")),
              "parents": [sha(item.get("sha")) for item in value["parents"]]}
    if expected is not None:
        require(record == expected, "devtools-historical-graph-drift")
    return record


def tree(api, tree_sha):
    """Authenticate a COMPLETE recursive tree, including every directory hash."""
    value = api.call(f"repos/{REPOSITORY}/git/trees/{sha(tree_sha)}?recursive=1")
    require(value.get("sha") == tree_sha and value.get("truncated") is False
            and type(value.get("tree")) is list and len(value["tree"]) <= 100000,
            "devtools-complete-tree-required")
    entries, children = {}, {}
    for item in value["tree"]:
        path = item.get("path")
        require(type(path) is str and path and not path.startswith("/")
                and str(PurePosixPath(path)) == path and ".." not in PurePosixPath(path).parts
                and "\\" not in path and all(32 <= ord(c) != 127 for c in path)
                and path not in entries, "devtools-tree-path")
        kind, mode = item.get("type"), item.get("mode")
        require((kind == "tree" and mode == "040000")
                or (kind == "blob" and mode in {"100644", "100755"}), "devtools-tree-mode")
        entries[path] = (mode, sha(item.get("sha")))
        parent, _, name = path.rpartition("/")
        children.setdefault(parent, []).append((name, kind, mode, item["sha"]))
    for path in entries:
        parent = path.rpartition("/")[0]
        require(not parent or parent in entries and entries[parent][0] == "040000",
                "devtools-tree-parent")
    for directory in ("", *(p for p, entry in entries.items() if entry[0] == "040000")):
        payload = b"".join(mode.lstrip("0").encode() + b" " + name.encode() + b"\0" + bytes.fromhex(oid)
                           for name, kind, mode, oid in sorted(children.get(directory, []),
                           key=lambda item: (item[0] + ("/" if item[1] == "tree" else "")).encode()))
        actual = hashlib.sha1(b"tree " + str(len(payload)).encode() + b"\0" + payload).hexdigest()
        require(actual == (tree_sha if not directory else entries[directory][1]),
                "devtools-tree-incomplete-or-drifted")
    return {path: entry for path, entry in entries.items() if entry[0] != "040000"}


def base_tree(api, base):
    repository = api.call(f"repos/{REPOSITORY}")
    require(repository.get("full_name") == REPOSITORY and type(repository.get("id")) is int
            and repository["id"] == REPOSITORY_ID, "devtools-repository-identity")
    return tree(api, commit(api, base)["tree"])


def expected_tree(value, before, source):
    changes = value["changes"]
    require(type(changes) is list and len(changes) == 18
            and len({item["path"] for item in changes}) == 18, "devtools-exact-manifest")
    require(".lit/managed-assets.json" not in before, "devtools-inventory-must-remain-absent")
    expected = dict(before)
    for item in changes:
        path = item["path"]
        predecessor = item["before"]
        require(before.get(path) == (None if predecessor is None else
                (predecessor["mode"], predecessor["blob"])), "devtools-predecessor-drift")
        if item["operation"] == "delete":
            del expected[path]
        elif "after" in item:
            expected[path] = (item["after"]["mode"], item["after"]["blob"])
        else:
            require(path == ".github/workflows/delivery-operations.yml"
                    and value["adapter_template"].count("__DEFINING_COMMON_SHA__") == 1,
                    "devtools-static-adapter-render")
            payload = value["adapter_template"].replace("__DEFINING_COMMON_SHA__", sha(source)).encode()
            expected[path] = (item["after_mode"], blob(payload))
    for item in value["preserve_workflows"]:
        require(expected.get(item["path"]) == (item["mode"], item["blob"]),
                "devtools-product-workflow-drift")
    require(json.loads(value["policy_payload"]) == value["policy"]
            and value["policy"]["artifact_publication"] is True
            and expected.get(POLICY) == ("100644", blob(value["policy_payload"].encode())),
            "devtools-source-policy-binding")
    return expected


def first_main_baseline(api, value):
    commit(api, value["main"]["sha"], value["main"])
    for historical in value["historical_metadata_graph"]:
        commit(api, historical["sha"], historical)
    develop = tree(api, value["develop"]["tree"])
    main = tree(api, value["main"]["tree"])
    require({path for path in main.keys() | develop.keys() if main.get(path) != develop.get(path)}
            == {".lit/main-ancestry.json"}, "devtools-historical-metadata-only")
    return develop


def policy(api, repo, base, source, pull):
    if repo != REPOSITORY:
        return None
    # Membership is only an early read of immutable source-owned data, never
    # acceptance. Every later base uses the ordinary protected policy reader.
    known = json.loads(DESCRIPTOR.read_bytes())
    if base not in {known["develop"]["sha"], known["main"]["sha"]}:
        return None
    before = base_tree(api, base)
    if POLICY in before:
        return None  # Existing installed-policy semantics stay with the reader.
    require(pull is not None and pull["base"]["sha"] == base
            and pull["base"]["repo"]["full_name"] == repo
            and pull["head"]["repo"]["full_name"] == repo
            and all(type(pull[side]["repo"].get("id")) is int
                    and pull[side]["repo"]["id"] == REPOSITORY_ID for side in ("base", "head")),
            "devtools-bootstrap-pull-context-required")
    value = descriptor()
    reference = api.call(f"repos/{repo}/git/ref/heads/{pull['base']['ref']}")
    require(reference.get("ref") == f"refs/heads/{pull['base']['ref']}"
            and reference.get("object", {}).get("sha") == base,
            "devtools-protected-base-moved")
    if pull["base"]["ref"] == "develop":
        require(base == value["develop"]["sha"] and identity(pull["user"])
                == ("litroc", 76040632, "User"), "devtools-bootstrap-human-develop-required")
        require(commit(api, base)["tree"] == value["develop"]["tree"], "devtools-protected-base-tree")
    else:
        require(pull["base"]["ref"] == "main" and base == value["main"]["sha"]
                and pull["head"]["ref"] == "develop" and identity(pull["user"]) == RELEASE,
                "devtools-first-main-shape")
        before = first_main_baseline(api, value)
    head = sha(pull["head"]["sha"])
    require(tree(api, commit(api, head)["tree"]) == expected_tree(value, before, source),
            "devtools-exact-eighteen-path-delta")
    result = copy.deepcopy(value["policy"])
    result["_devtools_first_policy"] = FirstPolicy(sha(source), head, "native", digest(value))
    return result


def preparation_policy(api, repo, source):
    """A protected preparer must call explicitly; this does not approve a tree."""
    require(repo == REPOSITORY, "devtools-preparation-target")
    value = descriptor()
    reference = api.call(f"repos/{repo}/git/ref/heads/main")
    require(reference.get("ref") == "refs/heads/main"
            and reference.get("object", {}).get("sha") == value["main"]["sha"],
            "devtools-protected-base-moved")
    require(base_tree(api, value["main"]["sha"]).get(POLICY) is None,
            "devtools-first-main-policy-already-installed")
    first_main_baseline(api, value)
    result = copy.deepcopy(value["policy"])
    result["_devtools_first_policy"] = FirstPolicy(sha(source), None, "prepare", digest(value))
    return policy_value(result, repo, source)


def promotion_context(api, repo, pull, config):
    context = config.get("_devtools_first_policy")
    if type(context) is not FirstPolicy:
        return None
    require(repo == REPOSITORY, "devtools-context-target")
    value = descriptor()
    require(context.descriptor_digest == digest(value), "devtools-context-descriptor-drift")
    if context.purpose == "prepare":
        # This is only planned SHA validation. It proves no hypothetical App
        # author, native approval, PR creation or permission to perform effects.
        require(set(pull) == {"base", "head"} and set(pull["base"]) == {"sha"}
                and set(pull["head"]) == {"sha"} and context.head is None
                and pull["base"]["sha"] == value["main"]["sha"],
                "devtools-planned-promotion-shape")
        reference = api.call(f"repos/{repo}/git/ref/heads/main")
        require(reference.get("ref") == "refs/heads/main"
                and reference.get("object", {}).get("sha") == value["main"]["sha"],
                "devtools-protected-base-moved")
        base_tree(api, pull["base"]["sha"])
        before = first_main_baseline(api, value)
        head = sha(pull["head"]["sha"])
        require(tree(api, commit(api, head)["tree"]) == expected_tree(value, before, context.source),
                "devtools-exact-eighteen-path-delta")
        return value
    require(context.purpose == "native" and context.head == pull["head"]["sha"]
            and "user" in pull and "repo" in pull["base"] and "repo" in pull["head"],
            "devtools-native-promotion-context")
    validated = policy(api, repo, pull["base"]["sha"], context.source, pull)
    require(isinstance(validated.get("_devtools_first_policy"), FirstPolicy),
            "devtools-first-main-context")
    return value
