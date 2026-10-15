"""Bounded data-only Git object reads for native ingress and ancestry."""
from __future__ import annotations

import hashlib
import json
import os
import selectors
import signal
import subprocess
import tempfile
import time
from pathlib import Path

import single_review_resources as resources
from workflow_control import (
    API,
    ControlError,
    binding,
    canonical,
    live_pull,
    require,
    sha,
    source_identity,
)


def capture(command, *, environment, limit, timeout=120):
    """Consume both pipes incrementally; overflow kills the entire child group."""
    require(type(limit) is int and limit > 0, "git-memory-admission")
    process = subprocess.Popen(command, env=environment, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, start_new_session=True)
    output = bytearray()
    consumed = 0
    deadline = time.monotonic() + timeout
    complete = False
    try:
        with selectors.DefaultSelector() as selector:
            for stream in (process.stdout, process.stderr):
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                require(remaining > 0, "git-deadline")
                for key, _ in selector.select(min(remaining, 1)):
                    # At most one extra byte is ever allocated beyond admission.
                    data = os.read(key.fileobj.fileno(), min(65536, limit - consumed + 1))
                    if not data:
                        selector.unregister(key.fileobj)
                        continue
                    consumed += len(data)
                    require(consumed <= limit, "git-output-exceeds-memory-admission")
                    if key.fileobj is process.stdout:
                        output.extend(data)
            require(process.wait(timeout=max(0.01, deadline - time.monotonic())) == 0, "git-integration-unavailable")
        complete = True
        return bytes(output)
    except subprocess.TimeoutExpired as error:
        raise ControlError("git-deadline") from error
    finally:
        if not complete:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        process.wait()
        process.stdout.close()
        process.stderr.close()


def git(directory, *args, binary=False):
    environment = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
                   "GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_COUNT": "0"}
    payload = capture(["git", "--git-dir", str(directory), *args], environment=environment,
                      limit=resources.wire_limit())
    return payload if binary else payload.decode().strip()


def instructions(directory, base):
    entries = git(directory, "ls-tree", "-rz", "--full-tree", base, binary=True).split(b"\0")
    files = []
    for entry in entries:
        if not entry:
            continue
        metadata, raw_path = entry.split(b"\t", 1)
        path = raw_path.decode("utf-8")
        if not (Path(path).name == "AGENTS.md" or path == ".github/copilot-instructions.md"
                or path.startswith(".github/instructions/") and path.endswith(".instructions.md")):
            continue
        mode, kind, blob = metadata.decode().split()
        require(mode in {"100644", "100755"} and kind == "blob", "instruction-not-regular")
        payload = git(directory, "cat-file", "blob", blob, binary=True)
        files.append({"path": path, "blob_sha": blob, "sha256": hashlib.sha256(payload).hexdigest(),
                      "content": payload.decode("utf-8")})
    return {"version": 1, "source_sha": base, "files": sorted(files, key=lambda f: f["path"])}


def materialize(api, repo, pull, source, destination):
    expected = binding(pull)
    base, head = expected["base"], expected["head"]
    require(not destination.exists(), "subject-already-exists")
    with tempfile.TemporaryDirectory(prefix="review-objects-", dir=os.environ.get("RUNNER_TEMP")) as temp:
        objects = Path(temp) / "objects.git"
        result = subprocess.run(["git", "init", "--bare", str(objects)], capture_output=True, check=False, timeout=30)
        require(result.returncode == 0, "git-init-failed")
        git(objects, "config", "credential.helper", "!gh auth git-credential")
        git(objects, "fetch", "--quiet", "--no-tags", "--no-recurse-submodules",
            f"https://github.com/{repo}.git", f"{base}:refs/review/base", f"{head}:refs/review/head")
        require(git(objects, "rev-parse", "refs/review/base") == base
                and git(objects, "rev-parse", "refs/review/head") == head, "git-fetch-drift")
        merge_base = sha(git(objects, "merge-base", "--all", base, head))
        tree = sha(git(objects, "merge-tree", "--write-tree", base, head))
        payload = git(objects, "diff", "--binary", "--full-index", "--no-color", "--no-ext-diff", "--no-textconv",
                      f"{base}^{{tree}}", tree, binary=True)
        require(payload, "empty-review-subject")
        bundle = instructions(objects, base)
    live_pull(api, repo, pull["number"], expected)
    root = Path(__file__).resolve().parents[1]
    prompt = (root / ".github/codex/prompts/review-exact-head.md").read_bytes()
    schema = (root / ".github/codex/schemas/exact-head-review.schema.json").read_bytes()
    metadata = {"schema_version": 7, "repository": repo, "pull_request": pull["number"],
                "base_sha": base, "head_sha": head, "merge_base_sha": merge_base,
                "integration_tree_sha": tree, "diff_sha256": hashlib.sha256(payload).hexdigest(),
                "review_bytes": len(payload), "central_source_sha": source,
                # The retained gateway schema calls the protected consumer
                # instruction revision trusted_workflow_sha. Central code is
                # independently bound above and by native job identity.
                "trusted_workflow_sha": base, "review_instructions": bundle,
                "instructions_sha256": hashlib.sha256(canonical(bundle)).hexdigest(),
                "prompt_sha256": hashlib.sha256(prompt).hexdigest(), "schema_sha256": hashlib.sha256(schema).hexdigest(),
                "source_assets": {file.name: hashlib.sha256(file.read_bytes()).hexdigest()
                                  for file in sorted(root.joinpath("scripts").glob("*.py"))}}
    metadata["input_sha256"] = hashlib.sha256(canonical(metadata)).hexdigest()
    destination.mkdir(mode=0o700)
    for name, data in (("change.patch", payload), ("review-metadata.json", canonical(metadata)),
                       ("review-prompt.md", prompt), ("review-schema.json", schema)):
        descriptor = os.open(destination / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400)
        with os.fdopen(descriptor, "wb") as file:
            file.write(data)
    return metadata


def bound_pull(api, repo, event, source, operation):
    require(operation.get("source_sha") == source, "materialization-operation-source")
    expected = operation["binding"]
    require(expected["base"] == event["pull_request"]["base"]["sha"]
            and expected["head"] == event["pull_request"]["head"]["sha"], "stale-materialization-event")
    return live_pull(api, repo, event["pull_request"]["number"], expected)


if __name__ == "__main__":
    api = API()
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    repo = os.environ["GITHUB_REPOSITORY"]
    source = source_identity(json.loads(os.environ["NATIVE_JOB"]))
    operation = json.loads(Path("control-operation.json").read_bytes())
    pull = bound_pull(api, repo, event, source, operation)
    materialize(api, repo, pull, source, Path("exact-revision-review"))
