#!/usr/bin/env python3
"""Validate fenced YAML, shell, and Ansible examples in supplied Markdown."""

from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    import yaml
except ImportError as error:
    raise SystemExit(
        "PyYAML is required for fail-closed embedded YAML validation; run "
        "the repository-local `scripts/lit-ci-profile.sh repository-quality` "
        "profile so the locked Devtools dependency set is used"
    ) from error

SCRIPT = Path(__file__).resolve()
DISTRIBUTED_ROOT = SCRIPT.parents[1]
SHARED_ROOT = SCRIPT.parents[2]
ROOT = (
    SHARED_ROOT
    if DISTRIBUTED_ROOT.name == "default"
    and (
        (SHARED_ROOT / ".git").exists()
        or (SHARED_ROOT / "release-model" / "repositories.yml").is_file()
    )
    else DISTRIBUTED_ROOT
)
FENCE = re.compile(
    r"^[ \t]*`{3,}[ \t]*(yaml|yml|bash|sh|shell|ansible)\b[^\r\n]*\r?\n"
    r"(.*?)^[ \t]*`{3,}[ \t]*$",
    re.IGNORECASE | re.MULTILINE | re.DOTALL,
)
VALIDATOR_TIMEOUT_SECONDS = 60


def validator_candidate(
    temporary: Path,
    kind: str,
    markdown_path: str,
    fence_index: int,
    suffix: str,
) -> Path:
    path_digest = hashlib.sha256(
        markdown_path.encode("utf-8", errors="surrogateescape")
    ).hexdigest()[:12]
    return temporary / f"{kind}-{path_digest}-{fence_index}.{suffix}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", type=Path)
    parser.add_argument("--isolated", action="store_true")
    parser.add_argument("paths", nargs="+")
    args = parser.parse_args()
    root = args.repository_root if args.repository_root is not None else ROOT
    if not root.is_absolute() or not root.is_dir() or root.is_symlink():
        parser.error("repository root must be an absolute regular directory")
    failures: list[str] = []
    with tempfile.TemporaryDirectory() as temporary:
        temp = Path(temporary)
        for name in args.paths:
            relative_path = Path(name)
            if (
                not name
                or relative_path.is_absolute()
                or ".." in relative_path.parts
                or relative_path.as_posix() != name
            ):
                failures.append(
                    f"{name}: Markdown path must be normalized and repository-relative"
                )
                continue
            path = root / relative_path
            if not path.is_file() or path.suffix.lower() != ".md":
                continue
            try:
                source = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as error:
                failures.append(f"{name}: cannot read Markdown as UTF-8: {error}")
                continue
            for index, match in enumerate(FENCE.finditer(source), 1):
                language, content = match.groups()
                language = language.lower()
                label = f"{name}:fence-{index}"
                if language in {"yaml", "yml", "ansible"}:
                    try:
                        for _document in yaml.safe_load_all(content):
                            pass
                    except yaml.YAMLError as error:
                        failures.append(f"{label}: invalid YAML: {error}")
                    if language == "ansible":
                        ansible_lint = shutil.which("ansible-lint")
                        if not ansible_lint:
                            failures.append(
                                f"{label}: ansible-lint is required for Ansible fences"
                            )
                            continue
                        candidate = validator_candidate(
                            temp,
                            "ansible",
                            name,
                            index,
                            "yml",
                        )
                        candidate.write_text(content, encoding="utf-8")
                        command = [ansible_lint, str(candidate)]
                        if args.isolated:
                            lint_config = temp / "source-owned-ansible-lint.yml"
                            lint_config.write_text("{}\n", encoding="utf-8")
                            command = [ansible_lint, "--offline", "-c", str(lint_config), str(candidate)]
                        try:
                            result = subprocess.run(
                                command,
                                cwd=temp if args.isolated else root,
                                text=True,
                                encoding="utf-8",
                                errors="replace",
                                capture_output=True,
                                timeout=VALIDATOR_TIMEOUT_SECONDS,
                            )
                        except subprocess.TimeoutExpired:
                            failures.append(
                                f"{label}: ansible-lint timed out after "
                                f"{VALIDATOR_TIMEOUT_SECONDS} seconds"
                            )
                            continue
                        if result.returncode:
                            details = "\n".join(
                                output.strip()
                                for output in (result.stdout, result.stderr)
                                if output.strip()
                            )
                            failures.append(
                                f"{label}: ansible-lint failed\n{details}".rstrip()
                            )
                else:
                    shellcheck = shutil.which("shellcheck")
                    if not shellcheck:
                        failures.append(
                            f"{label}: ShellCheck is required for shell fences"
                        )
                        continue
                    candidate = validator_candidate(
                        temp,
                        "shell",
                        name,
                        index,
                        "sh",
                    )
                    interpreter = "bash" if language == "bash" else "sh"
                    candidate.write_text(
                        f"#!/usr/bin/env {interpreter}\n" + content,
                        encoding="utf-8",
                    )
                    try:
                        result = subprocess.run(
                            [shellcheck, "-x", str(candidate)],
                            cwd=root,
                            text=True,
                            encoding="utf-8",
                            errors="replace",
                            capture_output=True,
                            timeout=VALIDATOR_TIMEOUT_SECONDS,
                        )
                    except subprocess.TimeoutExpired:
                        failures.append(
                            f"{label}: ShellCheck timed out after "
                            f"{VALIDATOR_TIMEOUT_SECONDS} seconds"
                        )
                        continue
                    if result.returncode:
                        details = "\n".join(
                            output.strip()
                            for output in (result.stdout, result.stderr)
                            if output.strip()
                        )
                        failures.append(
                            f"{label}: ShellCheck failed\n{details}".rstrip()
                        )
    for failure in failures:
        print(f"ERROR: {failure}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
