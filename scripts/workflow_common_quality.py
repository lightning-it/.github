"""Source-owned common checks; credentials and candidate validation stay apart."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

# Isolated Python never imports from the candidate working directory.
SOURCE_DIRECTORY = Path(__file__).resolve().parent
sys.path.insert(0, str(SOURCE_DIRECTORY))
from workflow_control import API, ControlError, canonical, native_required, policy, require, sha, source_identity


def metadata(raw, repository):
    import yaml

    require(0 < len(raw) <= 16384, "common-quality-metadata-bound")
    value = yaml.safe_load(raw)
    require(type(value) is dict and value.get("schema_version") == 1
            and value.get("repository") == repository.split("/", 1)[1], "common-quality-repository-identity")
    kind = value.get("repository_type")
    require(type(kind) is str and re.fullmatch(r"[a-z][a-z0-9_]{0,63}", kind),
            "common-quality-protected-profile-required")
    return value


def prepare(api, env):
    repository = env["GITHUB_REPOSITORY"]
    require(re.fullmatch(r"lightning-it/[A-Za-z0-9_.-]+", repository), "common-quality-consumer")
    source = source_identity(json.loads(env["NATIVE_JOB"]))
    run = api.call(f"repos/{repository}/actions/runs/{env['GITHUB_RUN_ID']}")
    require(native_required(run, repository), "common-quality-native-required-origin")
    number = int(env["NATIVE_PULL_NUMBER"])
    # Like product CI, common quality also runs on drafts. It grants no review
    # or merge authority. The independent review/finalization path keeps its
    # strict live_pull() draft rejection, including after metadata refresh.
    pull = api.call(f"repos/{repository}/pulls/{number}")
    require(pull["number"] == number and pull["state"] == "open"
            and pull["base"]["repo"]["full_name"] == repository
            and pull["base"]["ref"] in {"develop", "main"}, "common-quality-open-subject-required")
    require(pull["head"]["sha"] == sha(env["NATIVE_HEAD"])
            and pull["base"]["sha"] == sha(env["NATIVE_BASE"]), "common-quality-stale-event")
    policy(api, repository, pull["base"]["sha"], source)
    protected = metadata(api.file(repository, ".lit/repository.yml", pull["base"]["sha"]), repository)
    return {"version": 1, "repository": repository, "source_sha": source,
            "head": pull["head"]["sha"], "base": pull["base"]["sha"],
            "repository_type": protected["repository_type"]}


def validate(record):
    require(type(record) is dict and set(record) == {
        "version", "repository", "source_sha", "head", "base", "repository_type"
    } and record["version"] == 1, "common-quality-policy-shape")
    for key in ("source_sha", "head", "base"):
        sha(record[key])
    require(not os.environ.get("GH_TOKEN") and not os.environ.get("GITHUB_TOKEN"),
            "common-quality-validator-must-not-receive-credentials")
    current = subprocess.check_output(["git", "-c", f"safe.directory={Path.cwd()}",
                                       "rev-parse", "HEAD"], text=True).strip()
    require(current == record["head"], "common-quality-checkout-head")
    path = Path(".lit/repository.yml")
    require(not path.is_symlink() and path.is_file()
            and Path.cwd().resolve() in path.resolve().parents,
            "common-quality-regular-metadata-required")
    subject = metadata(path.read_bytes(), record["repository"])
    require(subject["repository_type"] == record["repository_type"],
            "candidate-cannot-select-weaker-quality-profile")
    spec = importlib.util.spec_from_file_location("immutable_quality", SOURCE_DIRECTORY / "lit-repository-quality.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.run_checks(subject, source_owned=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("prepare", "validate"))
    parser.add_argument("--policy", type=Path, required=True)
    args = parser.parse_args()
    if args.operation == "prepare":
        args.policy.write_bytes(canonical(prepare(API(), os.environ)))
        return 0
    require(args.policy.is_file() and not args.policy.is_symlink()
            and 0 < args.policy.stat().st_size <= 16384, "common-quality-policy-file-bound")
    return validate(json.loads(args.policy.read_bytes()))


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ControlError, KeyError, ValueError, OSError, subprocess.SubprocessError):
        print("Source common quality blocked: protected inputs or checks unavailable.", file=sys.stderr)
        raise SystemExit(1) from None
