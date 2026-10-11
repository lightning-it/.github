#!/usr/bin/env python3
"""Verify native ingress evidence for an exact develop-to-main promotion.

The verifier intentionally does not review the cumulative promotion diff again.
It proves that the protected develop first-parent history in the promotion range
consists only of GitHub merge commits whose exact PR heads already carry one
successful, bound ``Current revision review`` result and no unresolved review
conversations. The existing main tip is bound through one separately validated
ancestry boundary or a metadata-only release backsync with ordinary native review.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import json
import os
import re
import select
import socket
import socketserver
import stat
import subprocess
import sys
import tempfile
import time
import unicodedata
import urllib.parse
from collections.abc import Iterable
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

JSON = dict[str, Any]
SHA = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
PULL_REQUEST_REVIEW_NODE_ID = re.compile(r"^PRR_[A-Za-z0-9_+=/-]{4,252}$")
V6_EXTERNAL_ID = re.compile(
    r"^mlx90-current-revision:"
    r"(?P<kind>copilot|managed-sync|ancestry-backmerge|renovate):v6:"
    r"(?P<pr>[1-9][0-9]*):(?P<run>[1-9][0-9]*):"
    r"(?P<base>[0-9a-f]{40}):(?P<head>[0-9a-f]{40})$"
)
V5_EXTERNAL_ID = re.compile(
    r"^mlx90-current-revision:"
    r"(?P<kind>copilot|ancestry-backmerge):v5:"
    r"(?P<run>[1-9][0-9]*):"
    r"(?P<base>[0-9a-f]{40}):(?P<head>[0-9a-f]{40})$"
)
V4_EXTERNAL_ID = re.compile(
    r"^mlx90-current-revision:v4:(?P<run>[1-9][0-9]*):" r"(?P<input>[0-9a-f]{64})$"
)
RELEASE_APP_LOGIN = "lightning-it-release-automation[bot]"
RELEASE_APP_ID = 307565056
SYNC_APP_LOGIN = "lightning-it-shared-assets-sync[bot]"
SYNC_APP_ID = 307342877
RENOVATE_APP_LOGIN = "renovate[bot]"
RENOVATE_APP_ID = 29139614
GITHUB_ACTIONS_LOGIN = "github-actions[bot]"
GITHUB_ACTIONS_ID = 41898282
COPILOT_REVIEWER_LOGIN = "copilot-pull-request-reviewer[bot]"
COPILOT_REVIEWER_ID = 175728472
COPILOT_REVIEW_FAILURE_MARKERS = (
    "unabletoreviewthispullrequest", "cannotreviewthispullrequest", "cannotreviewanyfiles",
    "notabletoreviewthispullrequest", "wasnotabletoreviewthispullrequest",
    "nofilestoreview", "nofileswerereviewed",
    "wasnotabletoreviewanyfiles",
    "notabletoreviewanyfiles",
    "unabletoreviewanyfiles",
    "premiumrequestquota",
    "premiumrequestsquota",
    "quotaexhausted",
    "quotaexceeded",
    "suppressedcomments",
    "encounteredanerror",
)
MAX_API_BYTES = 16 * 1024 * 1024
MAX_FIRST_PARENT_MERGES = 900
MAX_THREADS_PER_PULL = 1000
MAX_REVIEWS_PER_PULL = 1000
MAX_REVIEW_COMMENTS_PER_REVIEW = 1000
MAX_ASSESSMENT_CHARACTERS = 4096
# Unicode 17 Default_Ignorable_Code_Point; apply after entity/code normalization.
# https://www.unicode.org/Public/17.0.0/ucd/DerivedCoreProperties.txt
ASSESSMENT_IGNORABLE = re.compile(
    r"[\u00ad\u034f\u061c\u115f-\u1160\u17b4-\u17b5\u180b-\u180f"
    r"\u200b-\u200f\u202a-\u202e\u2060-\u206f\u3164\ufe00-\ufe0f"
    r"\ufeff\uffa0\ufff0-\ufff8\U0001bca0-\U0001bca3"
    r"\U0001d173-\U0001d17a\U000e0000-\U000e0fff]"
)
GH_JSON_MAX_ATTEMPTS = 3
GH_JSON_TRANSIENT_ERRORS = ("command-failed:gh:unexpected end of JSON input",)
GITHUB_API_PROXY_PORT = 8080
MAX_PROXY_HEADER_BYTES = 8192


class EvidenceError(ValueError):
    """A promotion evidence invariant failed closed."""


def inactive_producer_helper(job: JSON, repository: str, run_id: int,
                             attempt: int, head: str) -> bool:
    """Recognize only the protected helper's native runnerless skipped role."""
    names = (
        'Request protected verifier re-evaluation / Inactive event writer',
        'Request protected verifier re-evaluation / Inactive legacy writer',
        'Request protected verifier re-evaluation / (vars.LI219_EVENT_MODE == \'enabled\' && contains(fromJSON(\'["lightning-it/.github","lightning-it/shared-assets-lit","lightning-it/ansible-collection-supplementary"]\'), github.repository)) && \'Re-run the one protected verifier attempt\' || \'Inactive event writer\'',
        'Request protected verifier re-evaluation / (vars.LI219_EVENT_MODE == \'enabled\' && contains(fromJSON(\'["lightning-it/.github","lightning-it/shared-assets-lit","lightning-it/ansible-collection-supplementary"]\'), github.repository)) && \'Inactive legacy writer\' || \'Re-run the one protected verifier attempt\'',
        'Request protected verifier re-evaluation / (vars.LI219_EVENT_MODE == \'enabled\' && contains(fromJSON(\'["lightning-it/.github","lightning-it/shared-assets-lit","lightning-it/ansible-collection-supplementary"]\'), github.repository)) && github.event_name == \'workflow_dispatch\' && inputs.producer_run_attempt > 0 && \'Re-run the one protected verifier attempt\' || \'Inactive event writer\'',
        'Request protected verifier re-evaluation / (vars.LI219_EVENT_MODE == \'enabled\' && contains(fromJSON(\'["lightning-it/.github","lightning-it/shared-assets-lit","lightning-it/ansible-collection-supplementary"]\'), github.repository)) && github.event_name == \'workflow_dispatch\' && inputs.producer_run_attempt > 0 && \'Inactive legacy writer\' || \'Re-run the one protected verifier attempt\'',
    )
    return (
        isinstance(job, dict)
        and job.get("name") in names
        and job.get("status") == "completed"
        and job.get("conclusion") == "skipped"
        and "runner_id" in job and job["runner_id"] is None
        and job.get("steps") == []
        and type(job.get("run_id")) is int and job["run_id"] == run_id
        and type(job.get("run_attempt")) is int and job["run_attempt"] == attempt
        and job.get("head_sha") == head
        and job.get("workflow_name") == "Current revision review gate"
        and job.get("run_url") == f"https://api.github.com/repos/{repository}/actions/runs/{run_id}"
    )


def validate_github_api_connect_request(payload: bytes) -> None:
    """Accept only one exact HTTPS CONNECT request for api.github.com."""
    require(
        0 < len(payload) <= MAX_PROXY_HEADER_BYTES,
        "github-api-proxy-request-size",
    )
    require(
        payload.endswith(b"\r\n\r\n") and payload.count(b"\r\n\r\n") == 1,
        "github-api-proxy-request-framing",
    )
    try:
        lines = payload[:-4].decode("ascii", errors="strict").split("\r\n")
    except UnicodeDecodeError as error:
        raise EvidenceError("github-api-proxy-request-encoding") from error
    require(
        bool(lines) and lines[0] == "CONNECT api.github.com:443 HTTP/1.1",
        "github-api-proxy-target",
    )
    hosts: list[str] = []
    for line in lines[1:]:
        require(bool(line) and not line[0].isspace(), "github-api-proxy-header")
        name, separator, value = line.partition(":")
        require(
            separator == ":"
            and re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", name) is not None,
            "github-api-proxy-header",
        )
        require("\r" not in value and "\n" not in value, "github-api-proxy-header")
        if name.lower() == "host":
            hosts.append(value.strip())
        require(name.lower() != "proxy-authorization", "github-api-proxy-auth")
    require(hosts == ["api.github.com:443"], "github-api-proxy-host")


class GithubApiProxyHandler(socketserver.BaseRequestHandler):
    """Minimal token-blind CONNECT relay restricted to GitHub's API host."""

    def handle(self) -> None:
        self.request.settimeout(15)
        payload = b""
        while b"\r\n\r\n" not in payload:
            block = self.request.recv(
                min(4096, MAX_PROXY_HEADER_BYTES + 1 - len(payload))
            )
            if not block:
                return
            payload += block
            if len(payload) > MAX_PROXY_HEADER_BYTES:
                return
        try:
            validate_github_api_connect_request(payload)
            upstream = socket.create_connection(("api.github.com", 443), timeout=15)
        except (EvidenceError, OSError):
            self.request.sendall(b"HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n")
            return
        with upstream:
            upstream.settimeout(300)
            self.request.sendall(
                b"HTTP/1.1 200 Connection Established\r\nConnection: close\r\n\r\n"
            )
            sockets = [self.request, upstream]
            while sockets:
                readable, _, exceptional = select.select(sockets, [], sockets, 300)
                if exceptional or not readable:
                    return
                for source in readable:
                    target = upstream if source is self.request else self.request
                    try:
                        block = source.recv(65536)
                    except OSError:
                        return
                    if not block:
                        return
                    target.sendall(block)


class GithubApiProxyServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = False
    daemon_threads = True


def serve_github_api_proxy() -> None:
    require(not os.environ.get("GH_TOKEN"), "github-api-proxy-gh-token")
    require(not os.environ.get("GITHUB_TOKEN"), "github-api-proxy-github-token")
    with GithubApiProxyServer(
        ("0.0.0.0", GITHUB_API_PROXY_PORT), GithubApiProxyHandler
    ) as server:
        print("github-api-proxy-ready", flush=True)
        server.serve_forever()


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise EvidenceError(reason)


def canonical(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> JSON:
    value: JSON = {}
    for key, item in pairs:
        require(key not in value, "check-summary-duplicate-key")
        value[key] = item
    return value


def reject_nonstandard_constant(_: str) -> None:
    raise EvidenceError("check-summary-nonstandard-constant")


def exact_object(value: Any, label: str) -> JSON:
    require(type(value) is dict, f"{label}-not-object")
    return value


def exact_array(value: Any, label: str) -> list[Any]:
    require(type(value) is list, f"{label}-not-array")
    return value


def text(value: Any, label: str) -> str:
    require(type(value) is str and bool(value), f"{label}-not-string")
    return value


def normalized_review_text(value: str) -> str:
    return re.sub(
        r"\s+",
        "",
        value.lower().replace("can't", "cannot").replace("can’t", "cannot").replace("n't", " not").replace("n’t", " not"),
    )


def copilot_severity_icons() -> set[str]:
    prefix = "https://github.githubassets.com/static/images/icons/copilot-code-review/"
    return {
        '<picture><source media="(prefers-color-scheme: dark)" '
        f'srcset="{prefix}{severity}-v2-dark.svg">'
        '<source media="(prefers-color-scheme: light)" '
        f'srcset="{prefix}{severity}-v2-light.svg">'
        f'<img src="{prefix}{severity}-v2-light.png" '
        f'alt="{severity.title()} severity" width="62" height="18" '
        'align="texttop"></picture>'
        for severity in ("high", "medium", "low")
    }


def copilot_frame_control_lines(body: str) -> tuple[list[str], bool]:
    """Exclude fenced literals from frame discovery, preserving their bounds.

    The owned-section parser still sees every opening and closing fence and
    rejects fences outside an admitted section. The original native body is
    unchanged for its authenticated evidence digest and thread binding.
    """
    lines: list[str] = []
    has_fences = False
    fence: tuple[str, int] | None = None
    comment = False
    for line in body.splitlines():
        if fence is not None:
            closing = re.fullmatch(
                r" {0,3}" + re.escape(fence[0]) + "{" + str(fence[1]) + r",}[ \t]*",
                line,
            )
            lines.append(line if closing else "")
            if closing:
                fence = None
            continue
        opening = None if comment else re.fullmatch(r" {0,3}(`{3,}|~{3,})(.*)", line)
        if opening and not (opening.group(1)[0] == "`" and "`" in opening.group(2)):
            fence = (opening.group(1)[0], len(opening.group(1)))
            has_fences = True
            # The info string is literal too, including apparent comments.
            # Retain the actual fence width for the owned-section parser.
            lines.append(opening.group(1))
            continue
        # Backticks quoted in a live comment cannot hide a later live verdict.
        if comment or "<!--" in line:
            for token in re.findall(r"<!--|--!?>", line):
                if comment:
                    if token in {"-->", "--!>"}:
                        comment = False
                elif token == "<!--":
                    comment = True
            lines.append(line)
            continue
        lines.append(line)
    require(fence is None, "producer-review-binding")
    return lines, has_fences


def copilot_container_lines(lines: list[str]) -> list[str]:
    """Expose block syntax inside quote/list containers, not indented code."""
    result: list[str] = []
    list_indent = 0
    list_kind = ""
    quote_depth = 0
    paragraph = False
    previous = ""
    blank = True
    for original in lines:
        leading = re.match(r"[ \t]*", original).group()
        line = leading.expandtabs(4) + original[len(leading):]
        depth = 0
        while re.match(r"^ {0,3}>", line):
            line = re.sub(r"^ {0,3}>[ \t]?", "", line, count=1)
            leading = re.match(r"[ \t]*", line).group()
            line = leading.expandtabs(4) + line[len(leading):]
            depth += 1
        if depth > quote_depth:
            # A new container interrupts the outer paragraph before its
            # indentation/marker is removed from the projection.
            result.append("")
            paragraph = False
        if depth:
            quote_depth = depth
        elif not line.strip() or copilot_paragraph_interrupts(previous, line):
            quote_depth = 0
        indentation = len(line) - len(line.lstrip(" "))
        old_indent, old_kind = list_indent, list_kind
        if list_indent and indentation >= list_indent:
            line = line[list_indent:]
        elif line.strip() and (blank or copilot_paragraph_interrupts(previous, line)):
            list_indent = 0
        item = re.match(r"^ {0,3}([-+*]|[0-9]{1,9}[.)])([ \t]+)(?=\S)", line)
        same_list = bool(item and old_indent and indentation < old_indent
                         and item.group(1)[-1] == old_kind)
        if item and (not paragraph or not item.group(1)[0].isdigit()
                     or item.group(1)[:-1] == "1" or same_list):
            result.append("")
            paragraph = False
            # More than four padding spaces start indented code in a list;
            # only the first space belongs to that container's marker.
            width = item.end() - max(0, len(item.group(2)) - 1) if len(item.group(2)) > 4 else item.end()
            list_indent += width
            list_kind = item.group(1)[-1]
            line = line[width:]
        result.append(line)
        blank = not line.strip()
        paragraph = bool(line.strip()) and not copilot_paragraph_interrupts(previous, line)
        previous = line if paragraph else ""
    return result


def copilot_paragraph_interrupts(previous: str, line: str) -> bool:
    """GFM blocks that terminate inline code's paragraph context."""
    if not line.strip():
        return True
    if re.match(r"^ {0,3}(?:#{1,6}(?:[ \t]|$)|>|[-+*][ \t]+\S|1[.)][ \t]+\S)", line):
        return True
    if any(re.fullmatch(r" {0,3}(?:" + re.escape(char) + r"[ \t]*){3,}", line)
           for char in "*_-"):
        return True
    if previous.strip() and re.fullmatch(r" {0,3}(?:=+|-+)[ \t]*", line):
        return True
    fence = re.fullmatch(r" {0,3}(`{3,}|~{3,})(.*)", line)
    if fence and not (fence.group(1)[0] == "`" and "`" in fence.group(2)):
        return True
    return (review_raw_html_block_start(line, interrupt_only=True)
            or assessment_table_header(previous, line))


def copilot_code_span_end(source: str, position: int) -> int:
    ticks = re.match(r"`+", source[position:]).group()
    end = re.search(r"(?<!`)" + ticks + r"(?!`)", source[position + len(ticks):])
    if end is None:
        return -1
    stop = position + len(ticks) + end.end()
    paragraph = source[source.rfind("\n", 0, position) + 1:stop - len(ticks)].splitlines()
    if any(copilot_paragraph_interrupts(previous, line)
           for previous, line in zip(paragraph, paragraph[1:])):
        return -1
    return stop


def copilot_reference_label_end(source: str, position: int) -> int:
    """Definition/reference identifiers preserve escapes and entity spelling."""
    cursor = position + 1
    while cursor < len(source) and cursor - position <= 1000:
        char = source[cursor]
        if char == "\\" and cursor + 1 < len(source) and re.fullmatch(r"[!-/:-@\[-`{-~]", source[cursor + 1]):
            cursor += 2
            continue
        if char == "[":
            return -1
        if char == "]":
            label = source[position + 1:cursor]
            return cursor if label.strip() and not re.search(r"\n[ \t]*\n", label) else -1
        cursor += 1
    return -1


def copilot_reference_definition(source: str, position: int) -> tuple[str, int] | None:
    end = copilot_reference_label_end(source, position)
    if end < 0 or not source.startswith(":", end + 1):
        return None
    cursor = end + 2
    while cursor < len(source) and source[cursor] in " \t":
        cursor += 1
    if cursor < len(source) and source[cursor] == "\n":
        cursor += 1
        while cursor < len(source) and source[cursor] in " \t":
            cursor += 1
    start = cursor
    if cursor < len(source) and source[cursor] == "<":
        cursor += 1
        while cursor < len(source) and source[cursor] not in "\n<>":
            if source[cursor] == "\\" and cursor + 1 < len(source) and source[cursor + 1] in "\\<>":
                cursor += 1
            cursor += 1
        if cursor >= len(source) or source[cursor] != ">":
            return None
        cursor += 1
    else:
        nesting = 0
        while cursor < len(source) and ord(source[cursor]) > 32 and ord(source[cursor]) != 127:
            char = source[cursor]
            if char == "\\" and cursor + 1 < len(source) and re.fullmatch(r"[!-/:-@\[-`{-~]", source[cursor + 1]):
                cursor += 2
                continue
            if char == "(":
                nesting += 1
            elif char == ")":
                nesting -= 1
                if nesting < 0:
                    return None
            cursor += 1
        if cursor == start or nesting:
            return None
    destination_end = cursor
    while cursor < len(source) and source[cursor] in " \t":
        cursor += 1
    next_line = cursor < len(source) and source[cursor] == "\n"
    if next_line:
        cursor += 1
        while cursor < len(source) and source[cursor] in " \t":
            cursor += 1
    if cursor < len(source) and source[cursor] in "\"'(" and cursor > destination_end:
        closing = ")" if source[cursor] == "(" else source[cursor]
        title = cursor + 1
        while title < len(source):
            if source[title] == "\\" and title + 1 < len(source) and re.fullmatch(
                r"[!-/:-@\[-`{-~]", source[title + 1]
            ):
                title += 2
                continue
            if source[title] == closing:
                title += 1
                while title < len(source) and source[title] in " \t":
                    title += 1
                if title == len(source) or source[title] == "\n":
                    return " ".join(source[position + 1:end].split()).casefold(), title
                break
            if (closing == ")" and source[title] == "(") or re.compile(r"\n[ \t]*\n").match(source, title):
                break
            title += 1
    if not next_line and cursor < len(source) and source[cursor] != "\n":
        return None
    # An invalid title on the following line remains ordinary paragraph text;
    # it does not invalidate the already complete destination line.
    return " ".join(source[position + 1:end].split()).casefold(), source.find("\n", destination_end) if next_line else cursor


def copilot_reference_text(source: str) -> str:
    """Resolve only valid reference links before literal/HTML normalization."""
    shadow = list(source)

    def conceal(start: int, stop: int) -> None:
        for cursor in range(start, stop):
            if source[cursor] != "\n":
                shadow[cursor] = "\ufffc"

    position = 0
    html_tag = re.compile(r"</?[A-Za-z](?:\"[^\"]*\"|'[^']*'|[^'\">])*>")
    while position < len(source):
        if source[position] == "\\":
            position += 2
            continue
        if source.startswith("<!--", position):
            end = re.search(r"--!?>", source[position + 4:])
            stop = position + 4 + end.end() if end else len(source)
            conceal(position, stop)
            position = stop
            continue
        tag = html_tag.match(source, position)
        if tag:
            stop = position + len(tag.group())
            conceal(position, stop)
            position = stop
            continue
        if source[position] == "`":
            stop = copilot_code_span_end(source, position)
            if stop >= 0:
                conceal(position, stop)
                position = stop
                continue
        position += 1
    references: set[str] = set()
    removed: list[tuple[int, int]] = []
    literals: list[tuple[int, int]] = []
    offset = 0
    paragraph = False
    previous = ""
    indented = False
    html_block: str | None = None
    for line in source.splitlines(keepends=True):
        raw = line.rstrip("\n")
        projected = "".join(shadow[offset:offset + len(raw)])
        if removed and offset < removed[-1][1]:
            offset += len(line)
            continue
        if indented and raw.strip() and not raw.startswith("    "):
            indented = False
        if html_block is not None and html_block == "blank" and not raw.strip():
            html_block = None
        if html_block is None and re.match(r"^ {0,3}<!--", raw):
            html_block = r"--!?>"
        if html_block is None and review_raw_html_block_start(raw):
            tag = re.match(r" {0,3}<(script|pre|style|textarea)(?=[ \t/>]|$)", raw, re.I)
            if tag:
                html_block = r"</" + tag.group(1) + r"[ \t]*>"
            elif raw.lstrip().startswith("<?"):
                html_block = r"\?>"
            elif raw.lstrip().startswith("<![CDATA["):
                html_block = r"\]\]>"
            elif raw.lstrip().startswith("<!"):
                html_block = r">"
            elif not paragraph or review_raw_html_block_start(raw, interrupt_only=True):
                html_block = "blank"
        if html_block is not None:
            conceal(offset, offset + len(raw))
            if html_block != "blank" and re.search(html_block, raw, re.I):
                html_block = None
            paragraph = False
        elif indented or (not paragraph and raw.startswith("    ")):
            indented = True
            literals.append((offset, offset + len(raw)))
            conceal(offset, offset + len(raw))
            paragraph = False
        elif not paragraph:
            beginning = re.match(r" {0,3}(?=\[)", projected)
            definition = copilot_reference_definition(source, offset + beginning.end()) if beginning else None
            if definition:
                label, stop = definition
                references.add(label)
                removed.append((offset, stop))
                conceal(offset, stop)
            else:
                paragraph = bool(projected.strip()) and not copilot_paragraph_interrupts(previous, projected)
        else:
            paragraph = bool(projected.strip()) and not copilot_paragraph_interrupts(previous, projected)
        previous = projected if paragraph else ""
        offset += len(line)
    output = list(source)
    for start, stop in removed:
        for cursor in range(start, stop):
            if source[cursor] != "\n":
                output[cursor] = " "
    for start, stop in literals:
        for cursor in range(start, stop):
            output[cursor] = "\ufffc"
    source = "".join(output)
    rendered: list[str] = []
    position = 0
    while position < len(source):
        if source[position] == "\\":
            rendered.append(source[position:position + 2])
            position += 2
            continue
        image = source.startswith("![", position)
        start = position + int(image)
        if source[start] == "[" and shadow[start] == "[":
            nesting, end = 1, start + 1
            while end < len(source) and nesting:
                if source[end] == "\\":
                    end += 2
                    continue
                if shadow[end] == "[":
                    nesting += 1
                elif shadow[end] == "]":
                    nesting -= 1
                if nesting:
                    end += 1
            if end < len(source) and not source.startswith("(", end + 1):
                target = end + 1
                label_end = copilot_reference_label_end(source, target) if source.startswith("[", target) else -1
                # Collapsed labels are explicitly empty, unlike definitions.
                if source.startswith("[]", target):
                    label_end = target + 1
                label = source[target + 1:label_end] if label_end >= 0 else ""
                label = label or source[start + 1:end]
                if " ".join(label.split()).casefold() in references:
                    # Preserve the label's inline-parser scope: delimiters in
                    # a link label cannot pair with delimiters outside it.
                    rendered.append("\ufffc" if image else "[" + source[start + 1:end] + "]()")
                    position = label_end + 1 if label_end >= 0 else end + 1
                    continue
        rendered.append(source[position])
        position += 1
    return "".join(rendered)


def copilot_inline_emphasis(source: str, depth: int = 0) -> str:
    """Remove consumed GFM delimiters, keeping literal and residual runs."""
    require(depth <= 8, "producer-review-binding")
    removed: set[int] = set()
    replacements: dict[int, tuple[int, str]] = {}
    openers: list[dict[str, Any]] = []
    tag_pattern = re.compile(r"</?[A-Za-z](?:\"[^\"]*\"|'[^']*'|[^'\">])*>")
    literal_depth = 0

    def punctuation(char: str) -> bool:
        return bool(char) and (unicodedata.category(char).startswith("P")
                               or re.fullmatch(r"[!-/:-@\[-`{-~]", char) is not None)

    def balanced_end(start: int, opening: str, closing: str) -> int:
        nesting, cursor = 1, start + 1
        quoted: str | None = None
        while cursor < len(source):
            char = source[cursor]
            if char == "\\":
                cursor += 2
                continue
            if quoted is not None:
                if char == quoted:
                    quoted = None
            elif opening == "(" and (char == "<" or (
                    char in "\"'" and source[cursor - 1].isspace())):
                quoted = ">" if char == "<" else char
            elif char == opening:
                nesting += 1
            elif char == closing:
                nesting -= 1
                if not nesting:
                    return cursor
            cursor += 1
        return -1

    position = 0
    while position < len(source):
        char = source[position]
        if char == "\\":
            position += 2
            continue
        if source.startswith("<!--", position):
            end = re.search(r"--!?>", source[position + 4:])
            position = position + 4 + end.end() if end else len(source)
            continue
        tag = tag_pattern.match(source, position)
        if tag:
            name = re.match(r"</?([A-Za-z][A-Za-z0-9-]*)", tag.group()).group(1).lower()
            if name in {"script", "style"} and not tag.group().startswith("</"):
                end = re.search(r"</" + name + r"[ \t]*>", source[tag.end():], re.I)
                position = tag.end() + end.end() if end else len(source)
                continue
            if name in {"code", "pre"}:
                literal_depth += -int(bool(literal_depth)) if tag.group().startswith("</") else 1
            position = tag.end()
            continue
        if literal_depth:
            position += 1
            continue
        if char == "`":
            end = copilot_code_span_end(source, position)
            if end >= 0:
                position = end
                continue
        if char == "[":
            end = balanced_end(position, "[", "]")
            target_end = (balanced_end(end + 1, "(", ")")
                          if end >= 0 and source.startswith("(", end + 1) else -1)
            if target_end >= 0:
                if end > position + 1:
                    replacements[position + 1] = (
                        end, copilot_inline_emphasis(source[position + 1:end], depth + 1),
                    )
                position = target_end + 1
                continue
        if char not in "*_~":
            position += 1
            continue
        width = len(re.match(re.escape(char) + "+", source[position:]).group())
        before = source[position - 1] if position else ""
        after = source[position + width] if position + width < len(source) else ""
        before_space, after_space = not before or before.isspace(), not after or after.isspace()
        before_punct, after_punct = punctuation(before), punctuation(after)
        left = not after_space and (not after_punct or before_space or before_punct)
        right = not before_space and (not before_punct or after_space or after_punct)
        can_open = left and (char != "_" or not right or before_punct)
        can_close = right and (char != "_" or not left or after_punct)
        if char == "~" and width not in {1, 2}:
            position += width
            continue
        remaining = width
        while can_close and remaining:
            found = None
            for index in range(len(openers) - 1, -1, -1):
                opener = openers[index]
                if opener["char"] != char:
                    continue
                if char == "~" and opener["remaining"] != remaining:
                    continue
                if char != "~" and (opener["can_close"] or can_open) and (
                    (opener["width"] + width) % 3 == 0
                    and (opener["width"] % 3 or width % 3)
                ):
                    continue
                found = index
                break
            if found is None:
                break
            opener = openers[found]
            used = remaining if char == "~" else min(2, opener["remaining"], remaining)
            removed.update(range(opener["start"] + opener["remaining"] - used,
                                 opener["start"] + opener["remaining"]))
            removed.update(range(position + width - remaining,
                                 position + width - remaining + used))
            opener["remaining"] -= used
            remaining -= used
            del openers[found + 1:]
            if not opener["remaining"]:
                openers.pop()
        if can_open and remaining:
            openers.append({"char": char, "start": position + width - remaining,
                            "remaining": remaining, "width": width, "can_close": can_close})
        position += width
    output: list[str] = []
    position = 0
    while position < len(source):
        if position in replacements:
            position, replacement = replacements[position]
            output.append(replacement)
        elif position not in removed:
            output.append(source[position])
            position += 1
        else:
            position += 1
    return "".join(output)


def copilot_heading_markup(source: str) -> str:
    """Keep block boundaries and raw-HTML literal markup before rendering."""
    boundary = "\n\ufffd\n"
    output: list[str] = []
    paragraph: list[str] = []
    raw_block: str | None = None
    previous = ""

    def flush() -> None:
        if paragraph:
            output.append(copilot_inline_emphasis("".join(paragraph)))
            paragraph.clear()

    for line in source.splitlines(keepends=True):
        raw = line.rstrip("\n")
        if raw_block == "blank" and not raw.strip():
            raw_block = None
        if raw_block is None:
            if re.match(r"^ {0,3}<!--", raw):
                raw_block = r"--!?>"
            elif review_raw_html_block_start(raw) and (
                not paragraph or review_raw_html_block_start(raw, interrupt_only=True)
            ):
                tag = re.match(r" {0,3}<(script|pre|style|textarea)(?=[ \t/>]|$)", raw, re.I)
                if tag:
                    raw_block = r"</" + tag.group(1) + r"[ \t]*>"
                elif raw.lstrip().startswith("<?"):
                    raw_block = r"\?>"
                elif raw.lstrip().startswith("<![CDATA["):
                    raw_block = r"\]\]>"
                elif raw.lstrip().startswith("<!"):
                    raw_block = r">"
                else:
                    raw_block = "blank"
        if raw_block is not None:
            if paragraph:
                flush()
                output.append(boundary)
            output.append(line)
            if raw_block != "blank" and re.search(raw_block, raw, re.I):
                raw_block = None
                output.append(boundary)
            previous = ""
        elif not raw.strip():
            flush()
            output.append(boundary)
            previous = ""
        elif copilot_paragraph_interrupts(previous, raw):
            flush()
            output.extend((boundary, copilot_inline_emphasis(line), boundary))
            previous = ""
        else:
            paragraph.append(line)
            previous = raw
    flush()
    return "".join(output)


def copilot_has_missed_heading(lines: list[str]) -> bool:
    """Recognize visible actionable headings without interpreting quoted code.

    Strip actual HTML wrappers before decoding entities, so encoded tag text
    remains literal. Keep code and escaped punctuation as non-heading content;
    comments and link destinations cannot hide or supply heading words.
    """
    normalized = "\n".join(copilot_container_lines(lines))
    projected, _ = copilot_frame_control_lines(normalized)
    source = copilot_reference_text("\n".join(projected))
    literal = "\ufffc"
    masked: list[str] = []
    html_tag = re.compile(r"</?[A-Za-z](?:\"[^\"]*\"|'[^']*'|[^'\">])*>")
    angle_destination = re.compile(r"<(?:[A-Za-z][A-Za-z0-9+.-]{1,31}:[^<>\s]*|[^<>\s]+@[^<>\s]+)>")
    position = 0
    while position < len(source):
        if source.startswith("<!--", position):
            end = re.search(r"--!?>", source[position + 4:])
            stop = position + 4 + end.end() if end else len(source)
            comment = source[position:stop]
            prefix = source[source.rfind("\n", 0, position) + 1:position]
            # An inline comment cannot cross a blank paragraph boundary.
            # GitHub renders that source literally, unlike a block comment.
            if prefix.strip() and re.search(r"\n[ \t]*\n", comment):
                masked.append(html.escape(comment, quote=False))
            else:
                masked.append(comment)
            position = stop
            continue
        destination = angle_destination.match(source, position)
        if destination:
            masked.append(html.escape(destination.group(), quote=False))
            position += len(destination.group())
            continue
        tag = html_tag.match(source, position)
        if tag:
            masked.append(tag.group())
            position += len(tag.group())
            continue
        if source[position] == "\\" and position + 1 < len(source) and re.fullmatch(
            r"[!-/:-@\[-`{-~]", source[position + 1]
        ):
            masked.append(literal)
            position += 2
            continue
        if source[position] == "`":
            stop = copilot_code_span_end(source, position)
            if stop >= 0:
                masked.append(literal)
                position = stop
                continue
            # An unmatched delimiter is visible punctuation, not authority for
            # the later inline lexer to quote across already established blocks.
            masked.append(literal)
            position += len(re.match(r"`+", source[position:]).group())
            continue
        masked.append(source[position])
        position += 1

    class HeadingText(HTMLParser):
        blocks = {"summary", "details", "p", "div", "li", "ul", "ol", "table",
                  "tr", "td", "th", "blockquote", "hr", "pre",
                  "h1", "h2", "h3", "h4", "h5", "h6"}

        def __init__(self) -> None:
            super().__init__(convert_charrefs=False)
            self.parts: list[str] = []
            self.code_depth = 0
            self.hidden_depth = 0

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            if tag in {"code", "pre"}:
                self.code_depth += 1
            if tag in {"script", "style"}:
                self.hidden_depth += 1
            if tag == "img" and self.code_depth and not self.hidden_depth:
                self.parts.append(literal)
            if tag == "br":
                self.parts.append("\n")
            elif tag not in {"script", "style"} and (
                tag in self.blocks or review_raw_html_block_start(f"<{tag}>", interrupt_only=True)
            ):
                self.parts.append("\n\ufffd\n")

        def handle_endtag(self, tag: str) -> None:
            if tag in {"code", "pre"} and self.code_depth:
                self.code_depth -= 1
            if tag in {"script", "style"} and self.hidden_depth:
                self.hidden_depth -= 1
            if tag == "br":
                self.parts.append("\n")
            elif tag not in {"script", "style"} and (
                tag in self.blocks or review_raw_html_block_start(f"<{tag}>", interrupt_only=True)
            ):
                self.parts.append("\n\ufffd\n")

        def handle_data(self, data: str) -> None:
            if self.hidden_depth:
                return
            if self.code_depth:
                visible = ASSESSMENT_IGNORABLE.sub("", html.unescape(data))
                if visible.strip():
                    self.parts.append(literal)
                elif visible:
                    # Empty wrappers cannot hide a heading, while actual
                    # whitespace still separates its rendered words. Canonical
                    # spacing also preserves entity-encoded edge whitespace.
                    self.parts.append(" ")
            else:
                self.parts.append(data)

        def handle_entityref(self, name: str) -> None:
            self.handle_data(f"&{name};")

        def handle_charref(self, name: str) -> None:
            self.handle_data(f"&#{name};")

    parser = HeadingText()
    parser.feed(copilot_heading_markup("".join(masked)))
    parser.close()
    rendered = "".join(parser.parts)
    # Raw emphasis and ATX headings are markup; entity-encoded punctuation is
    # decoded only afterward and consequently remains literal punctuation.
    rendered = re.sub(r"(?m)^ {0,3}(?:>[ \t]?)+", "", rendered)
    rendered = re.sub(r"(?m)^ {0,3}(?:[-+*]|[0-9]{1,9}[.)])[ \t]+", "", rendered)
    rendered = re.sub(r"(?m)^ {0,3}#{1,6}[ \t]+(.*?)(?:[ \t]+#+[ \t]*)?$",
                      r"\1", rendered)
    rendered = rendered.replace("<", literal).replace(">", literal)
    rendered = assessment_visible_text(
        rendered, strict_links=False, references=set(),
    )
    return re.search(
        r"(?im)^[ \t]*(?:previously\s+missed(?:\s*\([^()]*\))?"
        r"|[0-9]+\s+previously\s+missed)[ \t]*$", rendered,
    ) is not None


def historical_copilot_findings_count(body: str) -> int:
    lines, has_fences = copilot_frame_control_lines(body)
    require(not copilot_has_missed_heading(lines), "producer-review-binding")
    headings = [line for line in lines if "## copilot review overview" in line.lower()]
    verdicts = [line for line in lines if "### " in line]
    require(
        len(verdicts) <= 1
        and all(verdict in {
            "### 🟢 Approval recommended",
            "### 🟡 Changes recommended",
            "### 🔵 Needs a closer look",
        } for verdict in verdicts),
        "producer-review-binding",
    )
    if not headings:
        require(len(verdicts) == 1, "producer-review-binding")
        return current_copilot_findings_count(lines, verdicts[0])
    # Legacy frames have no admitted section that owns fenced literals.
    # Reject actual fences, preserving tick prose and commented delimiters.
    require(not has_fences, "producer-review-binding")
    require(headings == ["## Copilot review overview"], "producer-review-binding")
    require(
        not any("open finding" in line.lower() for line in lines
                if "**" in line or "<summary" in line.lower()),
        "producer-review-binding",
    )
    fields = [line for line in lines if "**findings:**" in line.lower()]
    require(len(fields) == 1, "producer-review-binding")
    if fields[0] == "**Findings:** None":
        return 0
    require(
        fields[0].startswith("**Findings:** "), "producer-review-binding"
    )
    groups = fields[0].removeprefix("**Findings:** ").split(" · ")
    require(1 <= len(groups) <= 3, "producer-review-binding")
    supported_icons = copilot_severity_icons()
    count = 0
    observed_icons: set[str] = set()
    for group in groups:
        match = re.fullmatch(
            r"(?P<count>[1-9][0-9]*)(?: (?P<icon><picture>.*</picture>))?",
            group,
        )
        require(match is not None, "producer-review-binding")
        icon = match.group("icon")
        require(
            (icon is None and len(groups) == 1)
            or (icon in supported_icons and icon not in observed_icons),
            "producer-review-binding",
        )
        if icon is not None:
            observed_icons.add(icon)
        count += int(match.group("count"))
    return count


def assessment_visible_text(text: str, depth: int = 0, *, strict_links: bool = True,
                            references: set[str] | None = None,
                            heading_markup: bool = False) -> str:
    """Count prose, not entity names, link targets/titles or image metadata.

    This is deliberately limited to inline syntax in the admitted native
    paragraph. Backslash escapes and code spans retain their literal text;
    only ordinary text decodes character references. Unbalanced destinations
    and excessive nesting cannot establish assessment evidence.
    """
    require(depth <= 8, "producer-review-binding")
    if heading_markup:
        text = copilot_inline_emphasis(text)

    def code_end(position: int) -> tuple[int, int]:
        ticks = re.match(r"`+", text[position:]).group()
        close = re.search(r"(?<!`)" + ticks + r"(?!`)", text[position + len(ticks):])
        return len(ticks), (position + len(ticks) + close.start() if close else -1)

    def balanced_end(position: int, opener: str, closer: str) -> int:
        nesting = 1
        cursor = position + 1
        quoted = None
        while cursor < len(text):
            if text[cursor] == "\\":
                cursor += 2
                continue
            if opener == "(":
                if quoted is not None:
                    if text[cursor] == quoted:
                        quoted = None
                    cursor += 1
                    continue
                if text[cursor] == "<" or (
                    text[cursor] in ('"', "'") and nesting == 1
                    and text[cursor - 1] in " \t\r\n"
                ):
                    quoted = ">" if text[cursor] == "<" else text[cursor]
                    cursor += 1
                    continue
            if opener == "[" and text[cursor] == "`":
                ticks, end = code_end(cursor)
                if end >= 0:
                    cursor = end + ticks
                    continue
            if text[cursor] == opener:
                nesting += 1
            elif text[cursor] == closer:
                nesting -= 1
                if nesting == 0:
                    return cursor
            cursor += 1
        return -1

    visible = []
    position = 0
    while position < len(text):
        char = text[position]
        if char == "\\" and position + 1 < len(text) and re.fullmatch(
            r"[!-/:-@\[-`{-~]", text[position + 1]
        ):
            visible.append(text[position + 1])
            position += 2
            continue
        if char == "`":
            ticks, end = code_end(position)
            if end >= 0:
                visible.append(text[position + ticks:end])
                position = end + ticks
                continue
        image = text.startswith("![", position)
        label_start = position + (1 if image else 0)
        if text[label_start] == "[":
            end = balanced_end(label_start, "[", "]")
            if end >= 0:
                if text.startswith("[^", label_start):
                    # A definition elsewhere renders only a footnote marker;
                    # its source label is never introductory assessment prose.
                    position = end + 1
                    continue
                destination = end + 1
                if destination < len(text) and text[destination] == "(":
                    target_end = balanced_end(destination, "(", ")")
                    require(target_end >= 0 or not strict_links, "producer-review-binding")
                    if target_end >= 0:
                        if not image:
                            visible.append(assessment_visible_text(
                                text[label_start + 1:end], depth + 1,
                                strict_links=strict_links, references=references,
                                heading_markup=heading_markup,
                            ))
                        position = target_end + 1
                        continue
                reference = destination
                while reference < len(text) and text[reference] in " \t":
                    reference += 1
                if reference < len(text) and text[reference] == "[":
                    target_end = balanced_end(reference, "[", "]")
                    require(target_end >= 0 or not strict_links, "producer-review-binding")
                    reference_label = text[reference + 1:target_end] or text[label_start + 1:end]
                    known_reference = references is None or (
                        " ".join(html.unescape(reference_label).split()).casefold() in references
                    )
                    if target_end >= 0 and known_reference:
                        if not image:
                            visible.append(assessment_visible_text(
                                text[label_start + 1:end], depth + 1,
                                strict_links=strict_links, references=references,
                                heading_markup=heading_markup,
                            ))
                        position = target_end + 1
                        continue
                elif references is not None and (
                    " ".join(html.unescape(text[label_start + 1:end]).split()).casefold()
                    in references
                ):
                    if not image:
                        visible.append(assessment_visible_text(
                            text[label_start + 1:end], depth + 1,
                            strict_links=strict_links, references=references,
                            heading_markup=heading_markup,
                        ))
                    position = end + 1
                    continue
                if image:
                    # A shortcut image may resolve against definitions elsewhere
                    # in the frame. Its alt text cannot establish visible prose.
                    position = end + 1
                    continue
        if char == "&":
            entity = re.match(r"&(?:[A-Za-z][A-Za-z0-9]{1,31}|#[0-9]{1,7}|#[xX][0-9A-Fa-f]{1,6});", text[position:])
            if entity:
                visible.append(html.unescape(entity.group()))
                position += len(entity.group())
                continue
        # Angle destinations have already been consumed by the link lexer.
        # Raw HTML cannot lend its tag name to assessment prose; escapes/code
        # and decoded character references still retain actual literal text.
        require(char not in "<>", "producer-review-binding")
        visible.append(char)
        position += 1
    return ASSESSMENT_IGNORABLE.sub("", "".join(visible))


def review_raw_html_block_start(line: str, *, interrupt_only: bool = False) -> bool:
    """Identify raw GFM blocks while retaining inline HTML paragraph prose."""
    raw = line.removeprefix(" " * min(len(line) - len(line.lstrip(" ")), 3))
    if interrupt_only:
        if raw.startswith(("<!--", "<?", "<![CDATA[")) or re.match(r"<![A-Z]", raw):
            return True
    elif raw.startswith(("<?", "<!")) and not raw.startswith("<!--"):
        return True
    tag = re.match(r"</?([A-Za-z][A-Za-z0-9-]*)(?=[ \t/>]|$)", raw)
    if tag is None:
        return False
    # GFM block types 1/6 can interrupt paragraphs, including partial tags.
    # Type 7 needs a whole tag on its own line. Do not reject inline <strong>
    # prose merely because the paragraph begins with an HTML tag.
    block_tags = {
        "script", "pre", "style", "textarea", "address", "article", "aside",
        "base", "basefont", "blockquote", "body", "caption", "center", "col",
        "colgroup", "dd", "details", "dialog", "dir", "div", "dl", "dt",
        "fieldset", "figcaption", "figure", "footer", "form", "frame", "frameset",
        "h1", "h2", "h3", "h4", "h5", "h6", "head", "header", "hr", "html",
        "iframe", "legend", "li", "link", "main", "menu", "menuitem", "nav",
        "noframes", "ol", "optgroup", "option", "p", "param", "section", "source",
        "summary", "table", "tbody", "td", "tfoot", "th", "thead", "title", "tr",
        "track", "ul",
    }
    if tag.group(1).lower() in block_tags:
        return True
    if interrupt_only:
        return False
    quote = None
    for position in range(tag.end(), len(raw)):
        char = raw[position]
        if quote is not None:
            if char == quote:
                quote = None
        elif char in {"'", '"'}:
            quote = char
        elif char == ">":
            return not raw[position + 1:].strip()
        elif char == "<":
            return False
    return False


def assessment_table_header(previous: str, delimiter: str) -> bool:
    """Recognize GFM table headers without changing literal paragraph prose."""
    if not previous:
        return False
    cells = delimiter.strip().split("|")
    if cells and not cells[0]:
        cells = cells[1:]
    if cells and not cells[-1]:
        cells = cells[:-1]
    if not cells or any(re.fullmatch(r":?-+:?", cell.strip()) is None for cell in cells):
        return False
    # GFM splits raw pipes before parsing inline code; escaped pipes alone
    # remain cell content. Count delimiters linearly, including escape parity.
    header = previous.strip()
    columns = 1
    escaped = False
    trailing_pipe = False
    for char in header:
        trailing_pipe = False
        if escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == "|":
            columns += 1
            trailing_pipe = True
    columns -= int(header.startswith("|")) + int(trailing_pipe)
    return columns == len(cells)


def current_copilot_findings_count(lines: list[str], verdict: str) -> int:
    # Only the two observed native CCR renderings are admitted. Counts remain
    # submission-time metadata; exact review binding and live thread coverage
    # are independently required by the caller.
    nonempty = [line for line in lines if line]
    require(
        nonempty[:2] == ["<!-- ccr-overview-v2 -->", verdict]
        and not any("**findings:**" in line.lower() for line in lines),
        "producer-review-binding",
    )
    fields = [line for line in lines if "open finding" in line.lower()
              and ("**" in line or "<summary" in line.lower())]
    require(len(fields) == 1, "producer-review-binding")
    if fields[0] == "**0 open findings**":
        count = 0
    else:
        match = re.fullmatch(
            r"<summary><strong>([1-9][0-9]{0,3}) open (finding|findings)"
            r"</strong></summary>", fields[0],
        )
        require(match is not None, "producer-review-binding")
        count = int(match.group(1))
        require(
            count <= MAX_REVIEW_COMMENTS_PER_REVIEW
            and match.group(2) == ("finding" if count == 1 else "findings"),
            "producer-review-binding",
        )
        position = nonempty.index(fields[0])
        require(
            position > 0 and nonempty[position - 1] == "<details open>"
            and "</details>" in nonempty[position + 1:],
            "producer-review-binding",
        )
    require(
        (verdict == "### 🟡 Changes recommended") == (count > 0),
        "producer-review-binding",
    )
    # Both observed current renderings include an introductory assessment and
    # a terminal effort footer. The compact native rendering may omit What
    # changed, so that section alone cannot prove a complete overview.
    footer = "🧠 **Review effort:** Balanced"
    # GitHub optionally appends this fixed informational tip to the native
    # frame. Admit only its observed platform rendering, never arbitrary tail.
    if len(nonempty) >= 3 and nonempty[-3:-1] == [footer, "---"]:
        appendix = (
            r'💡 <a href="/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/new/(?:develop|main)'
            r'\?filename=\.github/skills/code-review/SKILL\.md" '
            r'class="Link--inTextBlock" target="_blank" rel="noopener noreferrer">'
            r'Add a `code-review` agent skill</a> or configure MCP servers for '
            r'context-aware, tailored reviews\. <a href="https://docs\.github\.com/'
            r'copilot/how-tos/use-copilot-agents/request-a-code-review/use-code-review'
            r'\?tool=webui#mcp-servers-and-agent-skills" class="Link--inTextBlock" '
            r'target="_blank" rel="noopener noreferrer">Learn more in the docs\.</a>'
        )
        require(re.fullmatch(appendix, nonempty[-1]) is not None, "producer-review-binding")
        nonempty = nonempty[:-2]
    require(
        [line for line in lines if "**review effort:**" in line.lower()] == [footer]
        and nonempty[-1] == footer,
        "producer-review-binding",
    )
    field_position = nonempty.index(fields[0])
    assessment_lines = nonempty[2:field_position - (1 if count else 0)]
    # Keep original adjacency: GFM table delimiters transform the preceding
    # line into a header, but a blank-separated literal is still a paragraph.
    # Only the intro must be prose; native owned sections may contain tables.
    assessment_source = lines[lines.index(verdict) + 1:lines.index(fields[0])]
    require(
        bool(assessment_lines)
        # Bound only the intro parser, never truncate the native review/diff.
        and sum(len(line) + 1 for line in assessment_lines) <= MAX_ASSESSMENT_CHARACTERS
        and re.search(r"[^\W_]", assessment_visible_text("\n".join(assessment_lines)))
        and not re.search(r"(?m)^\[(?:\\.|[^\[\]\\]){1,999}\]:", "\n".join(assessment_lines))
        and not any(
            assessment_table_header(previous, line)
            for previous, line in zip(assessment_source, assessment_source[1:])
        )
        and all(
            line == line.strip()
            and not re.fullmatch(r"[-=]+|(?:[ \t]*[-*_]){3,}[ \t]*", line)
            and not line.startswith(("#", "**", "```", "~~~", "🧠", "|", ">"))
            and not re.match(r"[-*+]\s", line)
            and not re.match(r"[0-9]+[.)]\s", line)
            for line in assessment_lines
        ),
        "producer-review-binding",
    )
    supported_summaries = {
        "<summary><strong>What changed in this PR</strong></summary>"
    }
    missed_summary = None
    missed_count = 0
    if count:
        supported_summaries.add(fields[0])
    # Resolved sections are history. Previously missed entries are newly
    # surfaced findings, even when the overview reports zero open findings.
    # The all-PR thread inventory cannot bind body-only entries to this review.
    history_patterns = {
        "Resolved since last review": (
            r"(?:Resolved since last review \(([1-9][0-9]{0,3})\)"
            r"|([1-9][0-9]{0,3}) resolved since last review)"
        ),
        "Previously missed": r"Previously missed \(([1-9][0-9]{0,3})\)",
    }
    for label, pattern in history_patterns.items():
        sections = [line for line in lines if label.lower() in line.lower()
                    and "<summary" in line.lower()]
        require(len(sections) <= 1, "producer-review-binding")
        if sections:
            match = re.fullmatch(
                rf"<summary><strong>{pattern}</strong></summary>", sections[0],
            )
            require(match is not None, "producer-review-binding")
            history_count = int(next(group for group in match.groups() if group is not None))
            require(history_count <= MAX_REVIEW_COMMENTS_PER_REVIEW, "producer-review-binding")
            position = nonempty.index(sections[0])
            require(
                position > 0 and nonempty[position - 1] == "<details>"
                and "</details>" in nonempty[position + 1:],
                "producer-review-binding",
            )
            supported_summaries.add(sections[0])
            if label == "Previously missed":
                missed_summary = sections[0]
                missed_count = history_count
    # Every block must own exactly one supported summary. The observed native
    # Previously missed rendering alone nests individual severity/title blocks;
    # ordinary overview/history blocks may not nest or borrow another summary.
    blocks: list[JSON] = []
    seen_summaries: set[str] = set()
    supported_icons = copilot_severity_icons()
    fence: tuple[str, int] | None = None
    comment = False
    for position, line in enumerate(nonempty):
        # Literal content inside an owned section cannot close that section
        # or supply the authoritative footer. Preserve ordinary closed code
        # examples/comments without interpreting their quoted frame markers.
        if fence is not None:
            if re.fullmatch(r" {0,3}" + re.escape(fence[0]) + "{" + str(fence[1]) + r",}[ \t]*", line):
                fence = None
            continue
        child_summary = re.fullmatch(
            r"<summary>(<picture>.*</picture>) ([^<>]+)</summary>", line
        )
        if not comment and review_raw_html_block_start(line):
            # Own only exact native control tags. Check before the comment
            # lexer: a raw block opener followed by a comment still owns every
            # apparent closing tag/footer until its own GFM terminator.
            require(
                line in {"<details>", "<details open>", "</details>"}
                or line in supported_summaries
                or (child_summary is not None and child_summary.group(1) in supported_icons),
                "producer-review-binding",
            )
        if comment or (blocks and "<!--" in line):
            require(blocks and blocks[-1]["summary"] is not None, "producer-review-binding")
            # A closed comment may be followed by another opener on the same
            # line. Only closers end a live comment; nested openers are literal.
            for token in re.findall(r"<!--|--!?>", line):
                if comment:
                    if token in {"-->", "--!>"}:
                        comment = False
                elif token == "<!--":
                    comment = True
            continue
        opening = re.fullmatch(r" {0,3}(`{3,}|~{3,})(.*)", line)
        if opening and not (opening.group(1)[0] == "`" and "`" in opening.group(2)):
            require(blocks and blocks[-1]["summary"] is not None, "producer-review-binding")
            fence = (opening.group(1)[0], len(opening.group(1)))
            continue
        require(
            not (not blocks and line.lstrip().startswith(("```", "~~~"))),
            "producer-review-binding",
        )
        marker_line = line.lower()
        if "<details" in marker_line:
            require(line in {"<details>", "<details open>"}, "producer-review-binding")
            require(
                not blocks or (
                    len(blocks) == 1 and missed_summary is not None
                    and blocks[0]["summary"] == missed_summary
                    and line == "<details>"
                ),
                "producer-review-binding",
            )
            blocks.append({"opening": line, "summary": None, "children": 0})
        elif "<summary" in marker_line or "</summary" in marker_line:
            require(blocks and blocks[-1]["summary"] is None, "producer-review-binding")
            if len(blocks) == 1:
                require(
                    line in supported_summaries and line not in seen_summaries
                    and blocks[-1]["opening"] == (
                        "<details open>" if count and line == fields[0] else "<details>"
                    ),
                    "producer-review-binding",
                )
                seen_summaries.add(line)
            else:
                require(
                    child_summary is not None and child_summary.group(1) in supported_icons,
                    "producer-review-binding",
                )
                blocks[0]["children"] += 1
                require(blocks[0]["children"] <= missed_count, "producer-review-binding")
            blocks[-1]["summary"] = line
        elif "</details" in marker_line:
            require(
                line == "</details>" and blocks and blocks[-1]["summary"] is not None,
                "producer-review-binding",
            )
            block = blocks.pop()
            if block["summary"] == missed_summary:
                require(block["children"] == missed_count, "producer-review-binding")
        elif line in {"**0 open findings**", footer}:
            require(not blocks, "producer-review-binding")
        elif blocks:
            require(blocks[-1]["summary"] is not None, "producer-review-binding")
        else:
            # The prefix was checked as introductory prose. After findings,
            # only an owned native section or the terminal footer is legal.
            require(position < field_position, "producer-review-binding")
    require(not blocks and fence is None and not comment, "producer-review-binding")
    require(missed_count == 0, "producer-review-binding")
    return count


def integer(value: Any, label: str) -> int:
    require(type(value) is int and value > 0, f"{label}-not-positive-integer")
    return value


def sha(value: Any, label: str) -> str:
    result = text(value, label)
    require(SHA.fullmatch(result) is not None, f"{label}-not-sha")
    return result


def timestamp(value: Any, label: str) -> dt.datetime:
    raw = text(value, label)
    try:
        parsed = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as error:
        raise EvidenceError(f"{label}-not-timestamp") from error
    require(parsed.tzinfo is not None, f"{label}-missing-timezone")
    return parsed


def clean_environment() -> dict[str, str]:
    environment = os.environ.copy()
    for name in (
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_COMMON_DIR",
        "GIT_DIR",
        "GIT_INDEX_FILE",
        "GIT_OBJECT_DIRECTORY",
        "GIT_WORK_TREE",
    ):
        environment.pop(name, None)
    environment.update(
        {
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "LC_ALL": "C",
        }
    )
    return environment


def run(
    arguments: list[str],
    *,
    cwd: Path | None = None,
    input_text: str | None = None,
) -> str:
    completed = subprocess.run(
        arguments,
        cwd=cwd,
        env=clean_environment(),
        input=input_text,
        text=True,
        capture_output=True,
        check=False,
        timeout=90,
    )
    if completed.returncode != 0:
        stderr = completed.stderr.strip()
        raise EvidenceError(f"command-failed:{arguments[0]}:{stderr[:500]}")
    require(
        len(completed.stdout.encode("utf-8")) <= MAX_API_BYTES,
        "command-output-too-large",
    )
    return completed.stdout


def git(arguments: list[str], repository: Path) -> str:
    return run(["git", *arguments], cwd=repository).strip()


def git_raw(arguments: list[str], repository: Path) -> bytes:
    """Read exact Git bytes, without whitespace or newline normalization."""
    completed = subprocess.run(
        ["git", *arguments],
        cwd=repository,
        env=clean_environment(),
        text=False,
        capture_output=True,
        check=False,
        timeout=90,
    )
    require(completed.returncode == 0, "git-raw-read-failed")
    require(len(completed.stdout) <= MAX_API_BYTES, "command-output-too-large")
    return completed.stdout


def git_paths(arguments: list[str], repository: Path) -> list[str]:
    """Decode NUL-delimited paths losslessly for literal Git arguments."""
    return [os.fsdecode(path) for path in git_raw(arguments, repository).split(b"\0") if path]


def is_ancestor(repository: Path, ancestor: str, descendant: str) -> bool:
    completed = subprocess.run(
        ["git", "merge-base", "--is-ancestor", ancestor, descendant],
        cwd=repository,
        env=clean_environment(),
        capture_output=True,
        check=False,
        timeout=30,
    )
    require(completed.returncode in (0, 1), "ancestry-check-failed")
    return completed.returncode == 0


def gh_json(arguments: list[str]) -> Any:
    require(bool(os.environ.get("GH_TOKEN")), "gh-token-missing")
    require(bool(arguments) and arguments[0] == "api", "gh-json-read-command")
    for attempt in range(GH_JSON_MAX_ATTEMPTS):
        try:
            raw = run(["gh", *arguments])
        except EvidenceError as error:
            transient = str(error) in GH_JSON_TRANSIENT_ERRORS
            if not transient or attempt + 1 == GH_JSON_MAX_ATTEMPTS:
                raise
            time.sleep(0.25 * (2**attempt))
            continue
        try:
            return json.loads(
                raw,
                object_pairs_hook=reject_duplicate_keys,
                parse_constant=reject_nonstandard_constant,
            )
        except EvidenceError:
            raise
        except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
            raise EvidenceError("github-response-not-json") from error
    raise AssertionError("bounded GitHub JSON attempts exhausted")


def validate_live_promotion(
    pull: Any,
    *,
    repository: str,
    pull_number: int,
    expected_base: str,
    expected_head: str,
) -> JSON:
    value = exact_object(pull, "promotion")
    base = exact_object(value.get("base"), "promotion-base")
    head = exact_object(value.get("head"), "promotion-head")
    author = exact_object(value.get("user"), "promotion-author")
    base_repo = exact_object(base.get("repo"), "promotion-base-repository")
    head_repo = exact_object(head.get("repo"), "promotion-head-repository")
    require(
        integer(value.get("number"), "promotion-number") == pull_number,
        "promotion-number",
    )
    require(value.get("state") == "open", "promotion-not-open")
    require(value.get("draft") is False, "promotion-not-ready")
    require(
        value.get("title") == "chore(release): promote develop to main",
        "promotion-title",
    )
    require(author.get("login") == RELEASE_APP_LOGIN, "promotion-author-login")
    require(
        integer(author.get("id"), "promotion-author-id") == RELEASE_APP_ID,
        "promotion-author-id",
    )
    require(author.get("type") == "Bot", "promotion-author-type")
    require(base.get("ref") == "main", "promotion-base-ref")
    require(base.get("sha") == expected_base, "promotion-base-sha")
    require(base_repo.get("full_name") == repository, "promotion-base-repository")
    require(head.get("ref") == "develop", "promotion-head-ref")
    require(head.get("sha") == expected_head, "promotion-head-sha")
    require(head_repo.get("full_name") == repository, "promotion-head-repository")
    return value


def validate_protected_ref_tips(
    repository: str, *, expected_base: str, expected_head: str
) -> None:
    for ref, expected_sha in (("main", expected_base), ("develop", expected_head)):
        branch = exact_object(
            gh_json(["api", f"repos/{repository}/branches/{ref}"]),
            f"final-{ref}-branch",
        )
        commit = exact_object(branch.get("commit"), f"final-{ref}-commit")
        require(branch.get("name") == ref, f"final-{ref}-name")
        require(branch.get("protected") is True, f"final-{ref}-not-protected")
        require(commit.get("sha") == expected_sha, f"final-{ref}-moved")


def validate_repository_path(value: Path) -> Path:
    require(value.is_absolute(), "repository-path-not-absolute")
    metadata = value.lstat()
    require(not value.is_symlink(), "repository-path-symlink")
    require(stat.S_ISDIR(metadata.st_mode), "repository-path-not-directory")
    resolved = value.resolve(strict=True)
    require(resolved == value, "repository-path-not-canonical")
    return resolved


def promotion_body_sha256(value: JSON) -> str:
    body = text(value.get("body"), "promotion-body")
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def promotion_binding(value: JSON) -> JSON:
    """Return only the trust-boundary fields that must stay exact."""
    base = exact_object(value.get("base"), "promotion-binding-base")
    head = exact_object(value.get("head"), "promotion-binding-head")
    author = exact_object(value.get("user"), "promotion-binding-author")
    return {
        "number": value.get("number"),
        "state": value.get("state"),
        "draft": value.get("draft"),
        "title": value.get("title"),
        "body": value.get("body"),
        "author": {
            "login": author.get("login"),
            "id": author.get("id"),
            "type": author.get("type"),
        },
        "base": {"ref": base.get("ref"), "sha": base.get("sha")},
        "head": {"ref": head.get("ref"), "sha": head.get("sha")},
    }


def first_parent_merges(
    repository_path: Path, expected_base: str, expected_head: str
) -> tuple[str, str, list[JSON]]:
    require(
        repository_path.is_dir() and not repository_path.is_symlink(), "repository-path"
    )
    require(
        git(["status", "--porcelain=v1", "--untracked-files=no"], repository_path)
        == "",
        "repository-dirty",
    )
    for revision, label in ((expected_base, "base"), (expected_head, "head")):
        require(
            git(["cat-file", "-t", revision], repository_path) == "commit",
            f"{label}-not-commit",
        )
    run(
        ["git", "merge-base", "--is-ancestor", expected_base, expected_head],
        cwd=repository_path,
    )
    require(
        git(["merge-base", "--all", expected_base, expected_head], repository_path)
        == expected_base,
        "merge-base-not-exact-main",
    )
    integration_tree = sha(
        git(["rev-parse", f"{expected_head}^{{tree}}"], repository_path),
        "integration-tree",
    )
    revisions = [
        line
        for line in git(
            [
                "rev-list",
                "--first-parent",
                "--reverse",
                f"{expected_base}..{expected_head}",
            ],
            repository_path,
        ).splitlines()
        if line
    ]
    require(bool(revisions), "promotion-history-empty")
    require(len(revisions) <= MAX_FIRST_PARENT_MERGES, "promotion-history-too-large")
    previous: str | None = None
    history_anchor = ""
    merges: list[JSON] = []
    for revision in revisions:
        commit = sha(revision, "merge-commit")
        parents = git(["show", "-s", "--format=%P", commit], repository_path).split()
        require(len(parents) == 2, "non-merge-first-parent-commit")
        if previous is None:
            history_anchor = sha(parents[0], "history-anchor")
        else:
            require(parents[0] == previous, "first-parent-chain-drift")
        require(SHA.fullmatch(parents[1]) is not None, "merge-head-not-sha")
        merges.append(
            {"base_sha": parents[0], "head_sha": parents[1], "merge_sha": commit}
        )
        previous = commit
    require(previous == expected_head, "first-parent-tip-drift")
    return history_anchor, integration_tree, merges


def select_ingress_pull(
    pulls: Any,
    *,
    repository: str,
    merge_sha: str,
    head_sha: str,
    expected_number: int | None = None,
) -> JSON:
    candidates = []
    for item in exact_array(pulls, "associated-pulls"):
        pull = exact_object(item, "associated-pull")
        base = exact_object(pull.get("base"), "associated-pull-base")
        head = exact_object(pull.get("head"), "associated-pull-head")
        base_repo = exact_object(base.get("repo"), "associated-pull-base-repository")
        head_repo = exact_object(head.get("repo"), "associated-pull-head-repository")
        if (
            pull.get("state") == "closed"
            and pull.get("merged_at") is not None
            and pull.get("merge_commit_sha") == merge_sha
            and base.get("ref") == "develop"
            and base_repo.get("full_name") == repository
            and head_repo.get("full_name") == repository
            and head.get("sha") == head_sha
        ):
            candidates.append(pull)
    require(len(candidates) == 1, "associated-pull-not-unique")
    candidate = candidates[0]
    candidate_number = integer(candidate.get("number"), "associated-pull-number")
    if expected_number is not None:
        require(candidate_number == expected_number, "associated-pull-number-mismatch")
    timestamp(candidate.get("merged_at"), "associated-pull-merged-at")
    return candidate


def flatten_pull_pages(value: Any) -> list[JSON]:
    pages = exact_array(value, "associated-pull-pages")
    pulls: list[JSON] = []
    for page in pages:
        pulls.extend(
            exact_object(item, "associated-pull")
            for item in exact_array(page, "associated-pull-page")
        )
    require(len(pulls) <= 1000, "associated-pull-inventory-too-large")
    return pulls


def check_pages(value: Any) -> list[JSON]:
    pages = exact_array(value, "check-pages")
    runs: list[JSON] = []
    for page in pages:
        page_value = exact_object(page, "check-page")
        page_runs = exact_array(page_value.get("check_runs"), "check-runs")
        runs.extend(exact_object(item, "check-run") for item in page_runs)
    require(len(runs) <= 1000, "check-run-inventory-too-large")
    ids = [integer(item.get("id"), "check-run-id") for item in runs]
    require(len(ids) == len(set(ids)), "check-run-duplicate")
    return runs


def expected_evidence_kind(pull: JSON, *, repository: str) -> str:
    user = exact_object(pull.get("user"), "associated-pull-user")
    login = text(user.get("login"), "associated-pull-user-login")
    integer(user.get("id"), "associated-pull-user-id")
    user_type = text(user.get("type"), "associated-pull-user-type")
    head = exact_object(pull.get("head"), "associated-pull-head")
    head_ref = text(head.get("ref"), "associated-pull-head-ref")
    title = text(pull.get("title"), "associated-pull-title")
    ancestry = (
        head_ref.startswith("backmerge/")
        and head_ref.endswith("-main")
        and title.startswith("chore(governance): record main ancestry before ")
    )
    if ancestry:
        require(
            (
                login == RELEASE_APP_LOGIN
                and user.get("id") == RELEASE_APP_ID
                and user_type == "Bot"
            )
            or (
                repository == "lightning-it/.github"
                and login == SYNC_APP_LOGIN
                and user.get("id") == SYNC_APP_ID
                and user_type == "Bot"
            ),
            "ancestry-backmerge-author",
        )
        return "ancestry-backmerge"
    if login == RELEASE_APP_LOGIN:
        require(
            user.get("id") == RELEASE_APP_ID and user_type == "Bot",
            "release-app-identity",
        )
        return "release-app"
    if login == SYNC_APP_LOGIN:
        require(
            user.get("id") == SYNC_APP_ID and user_type == "Bot",
            "managed-sync-identity",
        )
        return "managed-sync"
    if login == RENOVATE_APP_LOGIN:
        require(
            user.get("id") == RENOVATE_APP_ID and user_type == "Bot",
            "renovate-identity",
        )
        return "renovate"
    require(user_type == "User", "copilot-ingress-author-type")
    return "copilot"


def is_authorized_ancestry_boundary(
    pull: Any,
    *,
    repository: str,
    expected_main: str,
    previous_develop: str,
) -> bool:
    """Return whether an ingress PR is the exact controller-created backmerge."""

    try:
        value = exact_object(pull, "ancestry-boundary-pull")
        user = exact_object(value.get("user"), "ancestry-boundary-user")
        base = exact_object(value.get("base"), "ancestry-boundary-base")
        head = exact_object(value.get("head"), "ancestry-boundary-head")
        base_repo = exact_object(base.get("repo"), "ancestry-boundary-base-repository")
        head_repo = exact_object(head.get("repo"), "ancestry-boundary-head-repository")
        repository_name = repository.split("/", 1)[1]
        branch_component = (
            repository_name[1:] if repository_name.startswith(".") else repository_name
        )
        expected_ref = (
            f"backmerge/{branch_component}-{expected_main[:12]}-"
            f"{previous_develop[:12]}-main"
        )
        user_id = integer(user.get("id"), "ancestry-boundary-user-id")
        identity = (
            user.get("login"),
            user_id,
            user.get("type"),
        )
        allowed_identities = {(RELEASE_APP_LOGIN, RELEASE_APP_ID, "Bot")}
        if repository == "lightning-it/.github":
            allowed_identities.add((SYNC_APP_LOGIN, SYNC_APP_ID, "Bot"))
        return (
            base.get("ref") == "develop"
            and base_repo.get("full_name") == repository
            and head_repo.get("full_name") == repository
            and head.get("ref") == expected_ref
            and value.get("title")
            == f"chore(governance): record main ancestry before {expected_main[:12]}"
            and identity in allowed_identities
        )
    except (EvidenceError, IndexError):
        return False


def has_exact_ancestry_merge_parents(
    repository_path: Path,
    *,
    head_sha: str,
    previous_develop: str,
    expected_main: str,
) -> bool:
    parents = git(["show", "-s", "--format=%P", head_sha], repository_path).split()
    return parents == [previous_develop, expected_main]


def ancestry_merge_main(
    repository_path: Path,
    *,
    head_sha: str,
    previous_develop: str,
) -> str | None:
    """Return the historical main parent of an exact two-parent backmerge."""

    parents = git(["show", "-s", "--format=%P", head_sha], repository_path).split()
    if (
        len(parents) != 2
        or parents[0] != previous_develop
        or SHA.fullmatch(parents[1]) is None
    ):
        return None
    return parents[1]


def validate_ancestry_boundary_content(
    repository_path: Path,
    *,
    repository: str,
    head_sha: str,
    previous_develop: str,
    expected_main: str,
) -> None:
    evidence_path = ".lit/main-ancestry.json"
    changed = git(
        [
            "diff",
            "--no-renames",
            "--name-only",
            previous_develop,
            head_sha,
            "--",
        ],
        repository_path,
    ).splitlines()
    require(changed == [evidence_path], "ancestry-boundary-content-scope")
    require(
        git(["show", "-s", "--format=%s", head_sha], repository_path)
        == "merge: preserve develop tree and main ancestry",
        "ancestry-boundary-subject",
    )
    raw = git(["show", f"{head_sha}:{evidence_path}"], repository_path)
    try:
        evidence = exact_object(
            json.loads(
                raw,
                object_pairs_hook=reject_duplicate_keys,
                parse_constant=reject_nonstandard_constant,
            ),
            "ancestry-boundary-evidence",
        )
    except (json.JSONDecodeError, RecursionError) as error:
        raise EvidenceError("ancestry-boundary-evidence-not-json") from error
    require(
        set(evidence)
        == {
            "develop_parent_sha",
            "main_sha",
            "purpose",
            "repository",
            "schema_version",
        },
        "ancestry-boundary-evidence",
    )
    require(
        integer(evidence.get("schema_version"), "ancestry-boundary-schema") == 1,
        "ancestry-boundary-schema",
    )
    require(
        sha(evidence.get("main_sha"), "ancestry-boundary-main") == expected_main,
        "ancestry-boundary-main",
    )
    require(
        sha(evidence.get("develop_parent_sha"), "ancestry-boundary-develop")
        == previous_develop,
        "ancestry-boundary-develop",
    )
    require(
        text(evidence.get("repository"), "ancestry-boundary-repository") == repository,
        "ancestry-boundary-repository",
    )
    require(
        text(evidence.get("purpose"), "ancestry-boundary-purpose")
        == "Bind the reviewed main ancestry backmerge.",
        "ancestry-boundary-purpose",
    )
    tree_entry = git(
        ["ls-tree", head_sha, "--", evidence_path], repository_path
    ).split()
    require(
        len(tree_entry) == 4
        and tree_entry[0] == "100644"
        and tree_entry[1] == "blob"
        and SHA.fullmatch(tree_entry[2]) is not None
        and tree_entry[3] == evidence_path,
        "ancestry-boundary-evidence-mode",
    )


def classify_ingress_position(index: int, baseline_boundary: int) -> tuple[bool, bool]:
    require(type(index) is int and index >= 0, "ingress-index")
    require(
        type(baseline_boundary) is int and baseline_boundary >= 0,
        "baseline-boundary-index",
    )
    return index == baseline_boundary, index > baseline_boundary


def validate_reviewed_release_baseline(
    repository_path: Path,
    *,
    repository: str,
    expected_main: str,
    merge: JSON,
    pull: JSON,
) -> None:
    """Bind a metadata-only backsync; this never grants an AI-review exemption."""

    head = exact_object(pull.get("head"), "release-baseline-head")
    reference = text(head.get("ref"), "release-baseline-ref")
    match = re.fullmatch(
        r"backsync/release-v((?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*))"
        r"-(to-develop|[a-z]{2,12}[1-9][0-9]{0,8}-current-base)",
        reference,
    )
    require(match is not None, "release-baseline-ref")
    assert match is not None
    version = match.group(1)
    reviewed_successor = match.group(2) != "to-develop"
    controller_title = f"chore: sync v{version} release back to develop"
    successor_title = f"chore: preserve v{version} release ancestry on current develop"
    require(
        pull.get("title") in ((successor_title,) if reviewed_successor else (
            f"chore(release): sync v{version} back to develop",
            controller_title,
        )),
        "release-baseline-title",
    )
    evidence_kind = expected_evidence_kind(pull, repository=repository)
    require(
        evidence_kind in {"copilot", "release-app"},
        "release-baseline-review-kind",
    )
    # A human-reviewed, content-identical current-base successor is not an App
    # dispatch or an ancestry-only exemption. Its full current-head Copilot,
    # threads, native checks, and exact release-content proof remain mandatory.
    if reviewed_successor:
        require(evidence_kind == "copilot", "release-baseline-successor-review-kind")
    # The existing release-back-sync producer uses this exact alternate title.
    # It still needs the authenticated App identity and ordinary review proof.
    if pull.get("title") == controller_title:
        require(evidence_kind == "release-app", "release-baseline-title-author")
    previous = sha(merge.get("base_sha"), "release-baseline-previous")
    head_sha = sha(merge.get("head_sha"), "release-baseline-head-sha")
    merge_sha = sha(merge.get("merge_sha"), "release-baseline-merge-sha")
    require(
        not is_ancestor(repository_path, expected_main, previous)
        and is_ancestor(repository_path, expected_main, head_sha)
        and is_ancestor(repository_path, previous, head_sha),
        "release-baseline-main-introduction",
    )
    require(
        git(["rev-parse", f"{merge_sha}^{{tree}}"], repository_path)
        == git(["rev-parse", f"{head_sha}^{{tree}}"], repository_path),
        "release-baseline-merge-tree-differs",
    )
    diff_options = [
        "--literal-pathspecs", "diff", "--no-ext-diff", "--no-textconv",
        "--no-renames", "--name-only", "-z",
    ]
    changed = git_paths([*diff_options, previous, head_sha, "--"], repository_path)
    metadata_paths = {
        "galaxy.yml",
        "CHANGELOG.rst",
        "changelogs/changelog.yaml",
        "changelogs/.plugin-cache.yaml",
        "changelogs/release-preparation.json",
    }
    common = sha(
        git(["merge-base", "--all", expected_main, previous], repository_path),
        "release-baseline-common-ancestor",
    )
    consumed_fragments = {
        path
        for path in git_paths(
            [*diff_options, "--diff-filter=D", common, expected_main, "--", "changelogs/fragments/"],
            repository_path,
        )
        if re.fullmatch(r"changelogs/fragments/[^/]+\.ya?ml", path)
    }
    # Check release-consumed fragments even when restoring a previous blob makes
    # them disappear from the previous..head diff. New develop fragments stay.
    for path in sorted(consumed_fragments):
        require(
            not git_raw(["--literal-pathspecs", "ls-tree", "-z", head_sha, "--", path], repository_path),
            "release-baseline-consumed-fragment-retained",
        )
    require("galaxy.yml" in changed, "release-baseline-version-missing")
    for path in changed:
        fragment = re.fullmatch(r"changelogs/fragments/[^/]+\.ya?ml", path)
        require(path in metadata_paths or fragment is not None, "release-baseline-content-scope")
        entry = git_raw(["--literal-pathspecs", "ls-tree", "-z", head_sha, "--", path], repository_path)
        if fragment is not None:
            require(not entry, "release-baseline-fragment-not-removed")
            require(path in consumed_fragments, "release-baseline-fragment-not-consumed")
        else:
            require(
                re.fullmatch(rb"100644 blob [0-9a-f]{40}\t" + re.escape(path.encode("ascii")) + rb"\0", entry) is not None,
                "release-baseline-metadata-mode",
            )
    require(
        git_raw([*diff_options, expected_main, head_sha, "--", *sorted(metadata_paths)], repository_path) == b"",
        "release-baseline-not-exact-main-metadata",
    )
    previous_galaxy = git_raw(["cat-file", "blob", f"{previous}:galaxy.yml"], repository_path)
    current_galaxy = git_raw(["cat-file", "blob", f"{head_sha}:galaxy.yml"], repository_path)
    # Leave the original LF/CRLF terminator outside the version substitution.
    version_pattern = rb"^version: [0-9]+\.[0-9]+\.[0-9]+(?=\r?$)"
    require(
        re.findall(version_pattern, current_galaxy, re.MULTILINE) == [f"version: {version}".encode("ascii")]
        and len(re.findall(version_pattern, previous_galaxy, re.MULTILINE)) == 1
        and re.sub(version_pattern, b"version: <bound>", previous_galaxy, flags=re.MULTILINE)
        == re.sub(version_pattern, b"version: <bound>", current_galaxy, flags=re.MULTILINE),
        "release-baseline-galaxy-not-version-only",
    )


def review_summary(check: JSON) -> JSON:
    output = exact_object(check.get("output"), "check-output")
    raw = text(output.get("summary"), "check-summary")
    try:
        return exact_object(
            json.loads(
                raw,
                object_pairs_hook=reject_duplicate_keys,
                parse_constant=reject_nonstandard_constant,
            ),
            "check-summary-json",
        )
    except (json.JSONDecodeError, RecursionError) as error:
        raise EvidenceError("check-summary-not-json") from error


def validate_renovate_policy(pull: JSON, summary: JSON, *, repository: str) -> None:
    base = exact_object(pull.get("base"), "renovate-base")
    head = exact_object(pull.get("head"), "renovate-head")
    head_repo = exact_object(head.get("repo"), "renovate-head-repository")
    labels = exact_array(pull.get("labels"), "renovate-labels")
    names = [
        text(exact_object(item, "renovate-label").get("name"), "renovate-label-name")
        for item in labels
    ]
    require(len(names) == len(set(names)), "renovate-label-duplicate")
    require(base.get("ref") == "develop", "renovate-base-ref")
    require(
        text(head.get("ref"), "renovate-head-ref").startswith("renovate/"),
        "renovate-head-ref",
    )
    require(head_repo.get("full_name") == repository, "renovate-head-repository")
    require(
        {"renovate", "dependencies", "safe-automerge"}.issubset(names),
        "renovate-required-labels",
    )
    require("breaking-update" not in names, "renovate-breaking-label")
    labels_json = json.dumps(
        sorted(names), ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    require(
        hashlib.sha256(labels_json).hexdigest()
        == summary.get("pull_request_labels_sha256"),
        "renovate-labels-mutated",
    )
    last_edited_at = pull.get("last_edited_at")
    require(
        last_edited_at is None or type(last_edited_at) is str,
        "renovate-live-last-edited-at",
    )
    require(
        last_edited_at == summary.get("pull_request_last_edited_at"),
        "renovate-last-edited-at-mutated",
    )


PULL_EDIT_QUERY = """
query($owner:String!,$name:String!,$number:Int!){
  repository(owner:$owner,name:$name){
    pullRequest(number:$number){number lastEditedAt}
  }
}
"""


def validate_review_edit_revision(
    summary: JSON, *, repository: str, pull_number: int
) -> None:
    """Rebind the exact metadata revision in sparse and expanded v6 evidence."""
    owner, name = repository.split("/", 1)
    payload = exact_object(
        gh_json(
            [
                "api",
                "graphql",
                "-f",
                f"query={PULL_EDIT_QUERY}",
                "-F",
                f"owner={owner}",
                "-F",
                f"name={name}",
                "-F",
                f"number={pull_number}",
            ]
        ),
        "review-summary-edit-response",
    )
    require("errors" not in payload or type(payload["errors"]) is list
            and not payload["errors"], "review-summary-edit-response-errors")
    data = exact_object(payload.get("data"), "review-summary-edit-data")
    live_repository = exact_object(
        data.get("repository"), "review-summary-edit-repository"
    )
    live_pull = exact_object(
        live_repository.get("pullRequest"), "review-summary-edit-pull"
    )
    require(
        integer(live_pull.get("number"), "review-summary-edit-pull-number")
        == pull_number,
        "review-summary-edit-pull-number",
    )
    require("lastEditedAt" in live_pull, "review-summary-live-last-edited-at")
    last_edited_at = live_pull.get("lastEditedAt")
    if last_edited_at is not None:
        timestamp(last_edited_at, "review-summary-live-last-edited-at")
    require(
        last_edited_at == summary.get("pull_request_last_edited_at"),
        "review-summary-last-edited-at-mutated",
    )


def validate_expanded_review_metadata(
    pull: JSON,
    summary: JSON,
    *,
    repository: str,
    pull_number: int,
    evidence_kind: str,
) -> None:
    head = exact_object(pull.get("head"), "review-summary-head")
    head_repo = exact_object(head.get("repo"), "review-summary-head-repository")
    require(
        head_repo.get("full_name") == repository
        and summary.get("head_repository") == repository,
        "review-summary-head-repository",
    )
    labels = exact_array(pull.get("labels"), "review-summary-labels")
    names = [
        text(
            exact_object(item, "review-summary-label").get("name"),
            "review-summary-label-name",
        )
        for item in labels
    ]
    require(len(names) == len(set(names)), "review-summary-label-duplicate")
    labels_json = json.dumps(
        sorted(names), ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    labels_sha256 = text(
        summary.get("pull_request_labels_sha256"),
        "review-summary-labels-sha256",
    )
    require(
        SHA256.fullmatch(labels_sha256) is not None
        and hashlib.sha256(labels_json).hexdigest() == labels_sha256,
        "review-summary-labels-mutated",
    )
    validate_review_edit_revision(summary, repository=repository, pull_number=pull_number)
    if evidence_kind == "copilot":
        review_id = text(summary.get("review_id"), "review-summary-review-id")
        require(
            PULL_REQUEST_REVIEW_NODE_ID.fullmatch(review_id) is not None,
            "review-summary-review-id",
        )
    else:
        require(evidence_kind == "managed-sync", "review-summary-expanded-kind")
        require(summary.get("review_id") is None, "managed-sync-review-id")


def validate_bound_review_identity(
    *, repository: str, pull_number: int, head_sha: str, summary: JSON,
    check_completed_at: Any,
) -> list[Any]:
    review_pages = exact_array(
        gh_json(
            [
                "api",
                "--paginate",
                "--slurp",
                f"repos/{repository}/pulls/{pull_number}/reviews?per_page=100",
            ]
        ),
        "review-summary-review-pages",
    )
    review_ids: list[int] = []
    review_node_ids: list[str] = []
    current_reviews: list[JSON] = []
    for page in review_pages:
        for item in exact_array(page, "review-summary-review-page"):
            review = exact_object(item, "review-summary-live-review")
            review_ids.append(
                integer(review.get("id"), "review-summary-live-review-id")
            )
            review_node_ids.append(
                text(review.get("node_id"), "review-summary-live-review-node-id")
            )
            require(
                len(review_ids) <= MAX_REVIEWS_PER_PULL,
                "review-summary-review-inventory-too-large",
            )
            reviewer = exact_object(
                review.get("user"), "review-summary-live-review-user"
            )
            if (
                reviewer.get("login") == COPILOT_REVIEWER_LOGIN
                and integer(
                    reviewer.get("id"), "review-summary-live-review-user-id"
                )
                == COPILOT_REVIEWER_ID
                and reviewer.get("type") == "Bot"
                and review.get("commit_id") == head_sha
                and review.get("state") in {"COMMENTED", "APPROVED"}
            ):
                current_reviews.append(review)
    require(
        len(review_ids) == len(set(review_ids))
        and len(review_node_ids) == len(set(review_node_ids)),
        "review-summary-live-review-duplicate",
    )
    require(
        len(current_reviews) == 1
        and ("review_id" not in summary
             or current_reviews[0].get("node_id") == summary["review_id"]),
        ("review-summary-review-binding" if "review_id" in summary
         else "producer-current-copilot-review-not-unique"),
    )
    # Association proves ownership, not that this review existed when the
    # producer accepted it. Reject late replacements before either route.
    submitted = timestamp(
        current_reviews[0].get("submitted_at"), "producer-review-submitted-at"
    )
    require(
        submitted <= timestamp(check_completed_at, "candidate-check-completed-at"),
        "producer-review-binding",
    )
    edited = summary.get("pull_request_last_edited_at")
    if edited is not None:
        require(
            submitted > timestamp(edited, "review-summary-last-edited-at"),
            "review-summary-review-after-edit",
        )
    return review_pages


def bind_copilot_review_findings(
    pages: list[Any], *, repository: str, pull_number: int, head_sha: str
) -> JSON:
    """Retain native findings across both producer association routes."""
    native_reviews: dict[str, JSON] = {}
    for page in pages:
        for item in exact_array(page, "finding-review-page"):
            review = exact_object(item, "finding-review")
            actor = exact_object(review.get("user"), "finding-review-user")
            if (actor.get("login") != COPILOT_REVIEWER_LOGIN
                    or type(actor.get("id")) is not int
                    or actor.get("id") != COPILOT_REVIEWER_ID
                    or actor.get("type") != "Bot"
                    or review.get("state") not in {"COMMENTED", "APPROVED"}):
                continue
            node_id = text(review.get("node_id"), "finding-review-node-id")
            require(PULL_REQUEST_REVIEW_NODE_ID.fullmatch(node_id) is not None,
                    "producer-review-thread-coverage")
            native_reviews[node_id] = {
                "id": integer(review.get("id"), "finding-review-id"),
                "head_sha": sha(review.get("commit_id"), "finding-review-head"),
                "submitted_at": text(review.get("submitted_at"), "finding-review-submitted"),
            }
    current = [review for page in pages for review in page
               if review.get("node_id") in native_reviews
               and review.get("commit_id") == head_sha]
    require(len(current) == 1, "producer-current-copilot-review-not-unique")
    review = current[0]
    body = text(review.get("body"), "producer-review-body")
    require(body.startswith("<!-- ccr-overview-v2 -->")
            and not any(marker in normalized_review_text(body)
                        for marker in COPILOT_REVIEW_FAILURE_MARKERS),
            "producer-review-binding")
    count = historical_copilot_findings_count(body)
    targets: list[int] | None = None
    if count and "## Copilot review overview" not in body.splitlines():
        lines = [line for line in body.splitlines() if line]
        summary = f"<summary><strong>{count} open {'finding' if count == 1 else 'findings'}</strong></summary>"
        start = lines.index(summary) + 1
        entries = lines[start:lines.index("</details>", start)]
        if any("discussion_r" in line or "https://github.com/" in line
               for line in entries):
            targets = []
            for line in entries:
                match = re.fullmatch(
                    r"- (?:(<picture>.*</picture>) )?\[[^\r\n]+\]"
                    + r"\(https://github\.com/" + re.escape(repository)
                    + r"/pull/" + str(pull_number)
                    + r"#discussion_r([1-9][0-9]{0,19})\)(?: · New)?", line,
                )
                require(match is not None and (match.group(1) is None
                        or match.group(1) in copilot_severity_icons()),
                        "producer-review-thread-coverage")
                # Native titles are Markdown labels and can contain severity
                # brackets or inline code. Authority comes from the unique
                # same-PR target, never from the title's display text.
                require(len(re.findall(
                    r"https://github\.com/[^\s()]+#discussion_r[0-9]+", line,
                )) == 1, "producer-review-thread-coverage")
                targets.append(int(match.group(2)))
            require(len(targets) == count and len(set(targets)) == count,
                    "producer-review-thread-coverage")
    return {
        "review_id": review["node_id"], "review_database_id": review["id"],
        "review_body_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
        "historical_findings_count": count,
        "finding_comment_ids": targets, "native_reviews": native_reviews,
    }


def validate_producer_run(
    check: JSON,
    *,
    repository: str,
    pull: JSON,
    pull_number: int,
    base_sha: str,
    head_sha: str,
    evidence_kind: str,
    evidence_version: str,
    producer_run_id: int,
    copilot_binding: JSON | None = None,
) -> tuple[JSON, int]:
    check_id = integer(check.get("id"), "check-id")
    require(
        check.get("details_url") == f"https://github.com/{repository}/runs/{check_id}",
        "check-details-url",
    )
    user = exact_object(pull.get("user"), "associated-pull-user")
    author = text(user.get("login"), "associated-pull-user-login")
    author_id = integer(user.get("id"), "associated-pull-user-id")
    author_type = text(user.get("type"), "associated-pull-user-type")
    require(author_type in {"User", "Bot"}, "associated-pull-user-type")
    base = exact_object(pull.get("base"), "associated-pull-base")
    head = exact_object(pull.get("head"), "associated-pull-head")
    base_ref = text(base.get("ref"), "associated-pull-base-ref")
    head_ref = text(head.get("ref"), "associated-pull-head-ref")
    summary = review_summary(check)
    run_url = f"https://github.com/{repository}/actions/runs/{producer_run_id}"
    require(summary.get("schema") == 4, "review-summary-schema")
    require(summary.get("base_sha") == base_sha, "review-summary-base")
    require(summary.get("head_sha") == head_sha, "review-summary-head")
    if evidence_version == "v5":
        require(
            "pull_request_number" not in summary
            or integer(
                summary.get("pull_request_number"),
                "review-summary-pull-request",
            )
            == pull_number,
            "review-summary-pull-request",
        )
    else:
        require(
            integer(
                summary.get("pull_request_number"),
                "review-summary-pull-request",
            )
            == pull_number,
            "review-summary-pull-request",
        )
    require(
        integer(summary.get("producer_run_id"), "review-summary-producer")
        == producer_run_id,
        "review-summary-producer",
    )
    require(summary.get("run_url") == run_url, "review-summary-run-url")
    repository_state: JSON | None = None
    bound_review_pages: list[Any] | None = None
    if evidence_kind != "release-app":
        expected_paths = {
            "copilot": "applicable Copilot or governed automation exemption",
            "managed-sync": (
                "deterministic provenance-bound managed distribution exemption"
            ),
            "ancestry-backmerge": ("deterministic evidence-bound ancestry exemption"),
            "renovate": "deterministic policy-bound Renovate exemption",
        }
        require(
            summary.get("review_path") == expected_paths[evidence_kind],
            "review-summary-path",
        )
        if evidence_kind == "renovate":
            expected_keys = {
                "base_sha",
                "controller_ref",
                "controller_sha",
                "head_repository",
                "head_sha",
                "producer_run_id",
                "pull_request_labels_sha256",
                "pull_request_last_edited_at",
                "pull_request_number",
                "review_id",
                "review_path",
                "run_url",
                "schema",
            }
            require(set(summary) == expected_keys, "renovate-review-summary-schema")
            require(
                summary.get("head_repository") == repository,
                "review-summary-head-repository",
            )
            require(summary.get("review_id") is None, "renovate-review-id")
            require(
                SHA256.fullmatch(
                    text(
                        summary.get("pull_request_labels_sha256"),
                        "renovate-labels-sha256",
                    )
                )
                is not None,
                "renovate-labels-sha256",
            )
            require(
                summary.get("pull_request_last_edited_at") is None
                or type(summary.get("pull_request_last_edited_at")) is str,
                "renovate-last-edited-at",
            )
            validate_renovate_policy(pull, summary, repository=repository)
        elif evidence_version == "v6":
            legacy_v6_keys = {
                "base_sha",
                "controller_sha",
                "head_sha",
                "producer_run_id",
                "pull_request_number",
                "review_path",
                "run_url",
                "schema",
            }
            metadata_v6_keys = legacy_v6_keys | {"pull_request_last_edited_at"}
            expanded_v6_keys = legacy_v6_keys | {
                "controller_ref",
                "head_repository",
                "pull_request_labels_sha256",
                "pull_request_last_edited_at",
                "review_id",
            }
            require(
                set(summary) in (legacy_v6_keys, metadata_v6_keys, expanded_v6_keys),
                "review-summary-schema",
            )
            if set(summary) == metadata_v6_keys:
                require(evidence_kind == "copilot", "review-summary-metadata-kind")
                validate_review_edit_revision(
                    summary, repository=repository, pull_number=pull_number
                )
            if set(summary) == expanded_v6_keys:
                require(
                    evidence_kind in {"copilot", "managed-sync"},
                    "review-summary-expanded-kind",
                )
                validate_expanded_review_metadata(
                    pull,
                    summary,
                    repository=repository,
                    pull_number=pull_number,
                    evidence_kind=evidence_kind,
                )
        else:
            require(evidence_version == "v5", "review-summary-version")
            expected_v5_keys = {
                "base_sha",
                "controller_sha",
                "head_sha",
                "producer_run_id",
                "review_path",
                "run_url",
                "schema",
            }
            require(
                set(summary)
                in (
                    expected_v5_keys,
                    expected_v5_keys | {"pull_request_number"},
                ),
                "review-summary-schema",
            )

        controller_sha = sha(summary.get("controller_sha"), "controller-sha")
        repository_state = exact_object(
            gh_json(["api", f"repos/{repository}"]), "controller-repository"
        )
        controller_ref = text(repository_state.get("default_branch"), "controller-ref")
        if evidence_kind == "renovate" or "controller_ref" in summary:
            require(
                summary.get("controller_ref") == controller_ref,
                "review-summary-controller-ref",
            )
        encoded_ref = urllib.parse.quote(controller_ref, safe="")
        controller_branch = exact_object(
            gh_json(["api", f"repos/{repository}/branches/{encoded_ref}"]),
            "controller-branch",
        )
        controller_commit = exact_object(
            controller_branch.get("commit"), "controller-branch-commit"
        )
        controller_head = sha(controller_commit.get("sha"), "controller-head")
        ancestry = exact_object(
            gh_json(
                [
                    "api",
                    f"repos/{repository}/compare/{controller_sha}...{controller_head}",
                ]
            ),
            "controller-ancestry",
        )
        merge_base = exact_object(
            ancestry.get("merge_base_commit"), "controller-merge-base"
        )
        require(
            ancestry.get("status") == "identical"
            or (
                ancestry.get("status") == "ahead"
                and ancestry.get("behind_by") == 0
                and merge_base.get("sha") == controller_sha
            ),
            "controller-not-protected-ancestor",
        )

    run = exact_object(
        gh_json(["api", f"repos/{repository}/actions/runs/{producer_run_id}"]),
        "producer-run",
    )
    require(run.get("id") == producer_run_id, "producer-run-id")
    require(run.get("html_url") == run_url, "producer-run-url")
    actor = exact_object(run.get("actor"), "producer-run-actor")
    triggering = exact_object(
        run.get("triggering_actor"), "producer-run-triggering-actor"
    )
    attempt = integer(run.get("run_attempt"), "producer-run-attempt")
    require(
        actor.get("login") == author
        and integer(actor.get("id"), "producer-run-actor-id") == author_id
        and actor.get("type") == author_type,
        "producer-run-actor-identity",
    )
    if evidence_kind == "copilot" and attempt == 2:
        require(
            triggering.get("login") == GITHUB_ACTIONS_LOGIN
            and integer(triggering.get("id"), "producer-run-triggering-actor-id")
            == GITHUB_ACTIONS_ID
            and triggering.get("type") == "Bot",
            "producer-run-triggering-actor-identity",
        )
    else:
        require(
            triggering.get("login") == author
            and integer(triggering.get("id"), "producer-run-triggering-actor-id")
            == author_id
            and triggering.get("type") == author_type,
            "producer-run-triggering-actor-identity",
        )
    require(run.get("status") == "completed", "producer-run-status")
    failed_handoff_producer = False
    if evidence_kind == "release-app":
        require(run.get("conclusion") == "success", "producer-run-conclusion")
        require(attempt == 1, "release-producer-run-attempt")
        require(run.get("event") == "workflow_dispatch", "release-producer-event")
        require(
            run.get("path") == ".github/workflows/release-bot-exact-head-review.yml",
            "release-producer-workflow",
        )
        require(run.get("head_branch") == base_ref, "release-producer-branch")
        require(run.get("head_sha") == base_sha, "release-producer-head")
        require(
            run.get("display_title")
            == f"Exact-Revision Codex PR #{pull_number} {base_sha}..{head_sha}",
            "release-producer-title",
        )
    else:
        require(attempt in {1, 2}, "producer-run-attempt")
        require(
            attempt == 1 or evidence_kind == "copilot",
            "producer-rerun-kind",
        )
        require(run.get("event") == "pull_request_target", "producer-event")
        require(
            run.get("path") == ".github/workflows/copilot-review.yml",
            "producer-workflow",
        )
        require(run.get("name") == "Current revision review gate", "producer-name")
        require(run.get("head_branch") == head_ref, "producer-branch")
        require(run.get("head_sha") == head_sha, "producer-head")
        if run.get("conclusion") != "success":
            require(
                evidence_kind in {"copilot", "managed-sync"}
                and evidence_version == "v6"
                and attempt == 1
                and run.get("conclusion") == "failure",
                "producer-run-conclusion",
            )
            job_inventory = exact_object(
                gh_json(
                    [
                        "api",
                        f"repos/{repository}/actions/runs/{producer_run_id}/jobs"
                        "?filter=all&per_page=100",
                    ]
                ),
                "producer-run-jobs",
            )
            jobs = exact_array(job_inventory.get("jobs"), "producer-run-jobs")
            total_count = job_inventory.get("total_count")
            require(
                type(total_count) is int and total_count == len(jobs)
                and len(jobs) in {5, 6},
                "producer-run-job-count",
            )
            # Keep raw native rows intact and exclude only one proven inert sibling.
            inactive_jobs = [job for job in jobs if inactive_producer_helper(
                job, repository, producer_run_id, attempt, head_sha)]
            require(len(inactive_jobs) <= 1, "producer-inactive-helper-count")
            if inactive_jobs:
                inactive_id = integer(inactive_jobs[0].get("id"), "producer-inactive-helper-id")
                require(sum(isinstance(job, dict) and job.get("id") == inactive_id
                            for job in jobs) == 1, "producer-inactive-helper-duplicate")
            jobs = [job for job in jobs if job not in inactive_jobs]
            require(len(jobs) == 5, "producer-run-job-count")
            # A managed sync publishes deterministic native evidence instead of
            # requesting Copilot. Its separate finalizer handoff must succeed;
            # only the later verifier helper may account for a failed producer.
            expected_jobs = {
                "Request Copilot review for current revision": (
                    "skipped" if evidence_kind == "managed-sync" else "success"
                ),
                "Verify current revision policy": "success",
                "Classify protected main trust-root handoff": "skipped",
                (
                    "Request protected verifier re-evaluation / "
                    "Re-run the one protected verifier attempt"
                ): "failure",
                "Dispatch protected managed-sync finalizer re-evaluation": (
                    "success" if evidence_kind == "managed-sync" else "skipped"
                ),
            }
            observed_jobs: dict[str, JSON] = {}
            job_ids: list[int] = []
            for item in jobs:
                job = exact_object(item, "producer-run-job")
                job_id = integer(job.get("id"), "producer-run-job-id")
                name = text(job.get("name"), "producer-run-job-name")
                require(
                    name in expected_jobs
                    and name not in observed_jobs
                    and integer(job.get("run_id"), "producer-run-job-run-id")
                    == producer_run_id
                    and integer(
                        job.get("run_attempt"), "producer-run-job-run-attempt"
                    )
                    == attempt
                    and sha(job.get("head_sha"), "producer-run-job-head")
                    == head_sha
                    and job.get("status") == "completed"
                    and job.get("conclusion") == expected_jobs[name],
                    "producer-run-job-binding",
                )
                job_ids.append(job_id)
                observed_jobs[name] = job
            require(
                len(job_ids) == len(set(job_ids))
                and set(observed_jobs) == set(expected_jobs),
                "producer-run-job-topology",
            )
            failed_handoff = observed_jobs[
                "Request protected verifier re-evaluation / "
                "Re-run the one protected verifier attempt"
            ]
            policy_started = timestamp(
                observed_jobs["Verify current revision policy"].get("started_at"),
                "producer-policy-started-at",
            )
            policy_completed = timestamp(
                observed_jobs["Verify current revision policy"].get("completed_at"),
                "producer-policy-completed-at",
            )
            check_completed = timestamp(
                check.get("completed_at"), "candidate-check-completed-at"
            )
            handoff_started = timestamp(
                failed_handoff.get("started_at"),
                "producer-failed-handoff-started-at",
            )
            handoff_completed = timestamp(
                failed_handoff.get("completed_at"),
                "producer-failed-handoff-completed-at",
            )
            run_updated = timestamp(run.get("updated_at"), "producer-run-updated-at")
            merged_at = timestamp(pull.get("merged_at"), "producer-pull-merged-at")
            # A completed run's updated_at can briefly lag its terminal job
            # snapshot across GitHub API replicas. Recover only that one
            # ordering gap, with two identical read-only terminal run reads.
            # Every other run field must remain identical.
            if (
                policy_started
                <= policy_completed
                <= handoff_started
                <= handoff_completed
                and policy_started <= check_completed <= merged_at
                and handoff_completed > run_updated
                and run_updated <= merged_at
            ):
                original_binding = canonical(
                    {key: value for key, value in run.items() if key != "updated_at"}
                )
                stable_update = None
                for _ in range(2):
                    refreshed_run = exact_object(
                        gh_json(["api", f"repos/{repository}/actions/runs/{producer_run_id}"]),
                        "producer-run-convergence",
                    )
                    require(
                        canonical(
                            {
                                key: value
                                for key, value in refreshed_run.items()
                                if key != "updated_at"
                            }
                        )
                        == original_binding,
                        "producer-run-convergence-identity",
                    )
                    refreshed_update = timestamp(
                        refreshed_run.get("updated_at"), "producer-run-convergence-updated-at"
                    )
                    require(refreshed_update >= run_updated, "producer-run-convergence-rollback")
                    if stable_update is not None:
                        require(refreshed_update == stable_update, "producer-run-convergence-unstable")
                    stable_update = refreshed_update
                require(stable_update is not None, "producer-run-convergence-missing")
                run_updated = stable_update
            require(
                policy_started
                <= policy_completed
                <= handoff_started
                <= handoff_completed
                <= run_updated
                <= merged_at
                and policy_started <= check_completed <= merged_at,
                "producer-post-evidence-failure-order",
            )
            failed_handoff_producer = True
        if evidence_kind == "copilot":
            bound_review_pages = validate_bound_review_identity(
                repository=repository,
                pull_number=pull_number,
                head_sha=head_sha,
                summary=summary,
                check_completed_at=check.get("completed_at"),
            )
            native_binding = bind_copilot_review_findings(
                bound_review_pages, repository=repository,
                pull_number=pull_number, head_sha=head_sha,
            )
            if copilot_binding is not None:
                copilot_binding.update(native_binding)
        require(repository_state is not None, "producer-repository-state")
        repository_id = integer(repository_state.get("id"), "producer-repository-id")
        repository_name = repository.split("/", 1)[1]
        repository_url = f"https://api.github.com/repos/{repository}"
        associations = exact_array(
            run.get("pull_requests"), "producer-run-pull-requests"
        )
        if not associations:
            require(
                evidence_kind in {"copilot", "renovate"}
                or (evidence_kind == "managed-sync" and "review_id" in summary),
                "producer-empty-association-kind",
            )
            suite_id = integer(
                run.get("check_suite_id"), "producer-run-check-suite-id"
            )
            # GitHub may reuse a neutral Checks API result from an earlier suite
            # when a successor PR has the same head. Treat that check only as an
            # untrusted locator: the exact provider run, PR, merge, native review,
            # and completion chronology are authenticated independently below.
            suite = exact_object(
                gh_json(["api", f"repos/{repository}/check-suites/{suite_id}"]),
                "producer-check-suite",
            )
            suite_app = exact_object(suite.get("app"), "producer-check-suite-app")
            require(
                integer(suite.get("id"), "producer-check-suite-id") == suite_id,
                "producer-check-suite-id",
            )
            require(
                integer(suite_app.get("id"), "producer-check-suite-app-id") == 15368
                and suite_app.get("slug") == "github-actions",
                "producer-check-suite-app",
            )
            # The suite is only an untrusted locator. Its aggregate conclusion
            # can be red because it also contains unrelated verifier jobs; the
            # exact producer run and review evidence are validated separately.
            require(
                suite.get("status") == "completed",
                "producer-check-suite-result",
            )
            require(
                suite.get("head_branch") == head_ref
                and suite.get("head_sha") == head_sha,
                "producer-check-suite-head-binding",
            )
            require(
                integer(pull.get("number"), "producer-pull-number") == pull_number,
                "producer-pull-number",
            )
            require(
                pull.get("state") == "closed" and pull.get("merged_at") is not None,
                "producer-pull-not-merged",
            )
            merged_at = timestamp(
                pull.get("merged_at"), "producer-pull-merged-at"
            )
            pull_base = exact_object(pull.get("base"), "producer-pull-base")
            pull_head = exact_object(pull.get("head"), "producer-pull-head")
            pull_base_repo = exact_object(
                pull_base.get("repo"), "producer-pull-base-repository"
            )
            pull_head_repo = exact_object(
                pull_head.get("repo"), "producer-pull-head-repository"
            )
            require(
                pull_base.get("ref") == "develop"
                and pull_base.get("sha") == base_sha
                and pull_base_repo.get("full_name") == repository
                and pull_head.get("ref") == head_ref
                and pull_head.get("sha") == head_sha
                and pull_head_repo.get("full_name") == repository,
                "producer-pull-revision-binding",
            )
            merge_sha = sha(pull.get("merge_commit_sha"), "producer-pull-merge")
            merge = exact_object(
                gh_json(["api", f"repos/{repository}/commits/{merge_sha}"]),
                "producer-pull-merge-commit",
            )
            parents = exact_array(
                merge.get("parents"), "producer-pull-merge-parents"
            )
            require(len(parents) == 2, "producer-pull-merge-binding")
            parent_shas = [
                sha(
                    exact_object(parent, f"producer-pull-merge-parent-{index}").get(
                        "sha"
                    ),
                    f"producer-pull-merge-parent-{index}-sha",
                )
                for index, parent in enumerate(parents)
            ]
            require(
                merge.get("sha") == merge_sha
                and parent_shas == [base_sha, head_sha],
                "producer-pull-merge-binding",
            )
            if evidence_kind == "managed-sync":
                run_created = timestamp(
                    run.get("created_at"), "producer-run-created-at"
                )
                run_updated = timestamp(
                    run.get("updated_at"), "producer-run-updated-at"
                )
                check_completed = timestamp(
                    check.get("completed_at"), "candidate-check-completed-at"
                )
                require(
                    run_created
                    <= check_completed
                    <= merged_at,
                    "producer-managed-sync-time-binding",
                )
                require(
                    run_created <= run_updated <= merged_at
                    and (
                        failed_handoff_producer or check_completed <= run_updated
                    ),
                    "producer-managed-sync-time-binding",
                )
                return summary, 0
            if evidence_kind == "renovate":
                run_created = timestamp(
                    run.get("created_at"), "producer-run-created-at"
                )
                run_updated = timestamp(
                    run.get("updated_at"), "producer-run-updated-at"
                )
                check_completed = timestamp(
                    check.get("completed_at"), "candidate-check-completed-at"
                )
                require(
                    run_created
                    <= check_completed
                    <= run_updated
                    <= merged_at,
                    "producer-renovate-time-binding",
                )
                return summary, 0
            if bound_review_pages is None:
                review_pages = exact_array(
                    gh_json(
                        [
                            "api",
                            "--paginate",
                            "--slurp",
                            f"repos/{repository}/pulls/{pull_number}/reviews?per_page=100",
                        ]
                    ),
                    "producer-review-pages",
                )
            else:
                review_pages = bound_review_pages
            run_created = timestamp(run.get("created_at"), "producer-run-created-at")
            run_updated = timestamp(run.get("updated_at"), "producer-run-updated-at")
            check_completed = timestamp(
                check.get("completed_at"), "candidate-check-completed-at"
            )
            require(run_created <= run_updated, "producer-run-time-order")
            current_reviews: list[JSON] = []
            review_ids: list[int] = []
            historical_findings_count = 0
            for page in review_pages:
                for item in exact_array(page, "producer-review-page"):
                    review = exact_object(item, "producer-review")
                    review_id = integer(review.get("id"), "producer-review-id")
                    review_ids.append(review_id)
                    require(
                        len(review_ids) <= MAX_REVIEWS_PER_PULL,
                        "producer-review-inventory-too-large",
                    )
                    reviewer = exact_object(review.get("user"), "producer-review-user")
                    if not (
                        reviewer.get("login") == COPILOT_REVIEWER_LOGIN
                        and integer(reviewer.get("id"), "producer-review-user-id")
                        == COPILOT_REVIEWER_ID
                        and reviewer.get("type") == "Bot"
                        and review.get("commit_id") == head_sha
                    ):
                        continue
                    submitted = timestamp(
                        review.get("submitted_at"), "producer-review-submitted-at"
                    )
                    body = text(review.get("body"), "producer-review-body")
                    require(
                        (
                            review.get("state") in {"COMMENTED", "APPROVED"}
                            and submitted <= check_completed
                            and run_created
                            <= check_completed
                            <= merged_at
                            and run_updated <= merged_at
                            and (
                                failed_handoff_producer
                                or check_completed <= run_updated
                            )
                            and body.startswith("<!-- ccr-overview-v2 -->")
                        ),
                        "producer-review-binding",
                    )
                    historical_findings_count = historical_copilot_findings_count(
                        body
                    )
                    normalized_body = normalized_review_text(body)
                    require(
                        not any(
                            marker in normalized_body
                            for marker in COPILOT_REVIEW_FAILURE_MARKERS
                        ),
                        "producer-review-binding",
                    )
                    if "review_id" not in summary:
                        comment_pages = exact_array(
                            gh_json(
                                [
                                    "api",
                                    "--paginate",
                                    "--slurp",
                                    f"repos/{repository}/pulls/{pull_number}/reviews/"
                                    f"{review_id}/comments?per_page=100",
                                ]
                            ),
                            "producer-review-comment-pages",
                        )
                        review_texts: list[str] = []
                        comment_ids: list[int] = []
                        for comment_page in comment_pages:
                            for comment_item in exact_array(
                                comment_page, "producer-review-comment-page"
                            ):
                                comment = exact_object(
                                    comment_item, "producer-review-comment"
                                )
                                comment_ids.append(
                                    integer(
                                        comment.get("id"),
                                        "producer-review-comment-id",
                                    )
                                )
                                require(
                                    len(comment_ids)
                                    <= MAX_REVIEW_COMMENTS_PER_REVIEW,
                                    "producer-review-comment-inventory-too-large",
                                )
                                review_texts.append(
                                    text(
                                        comment.get("body"),
                                        "producer-review-comment-body",
                                    )
                                )
                        require(
                            len(comment_ids) == len(set(comment_ids)),
                            "producer-review-comment-duplicate",
                        )
                        normalized_texts = [
                            normalized_review_text(value) for value in review_texts
                        ]
                        require(
                            not any(
                                marker in normalized
                                for normalized in normalized_texts
                                for marker in COPILOT_REVIEW_FAILURE_MARKERS
                            ),
                            "producer-review-binding",
                        )
                        # Historical overview counts are a submission-time
                        # snapshot. The caller separately validates every
                        # live review thread after this exact review binding.
                    # Expanded v6 evidence binds the exact native review ID in
                    # the protected producer result. Its overview counts are a
                    # historical rendering and may still mention a finding
                    # after its live thread was resolved. The independently
                    # revalidated thread inventory below is authoritative.
                    current_reviews.append(review)
            require(
                len(review_ids) == len(set(review_ids)),
                "producer-review-duplicate",
            )
            require(
                len(current_reviews) == 1,
                "producer-current-copilot-review-not-unique",
            )
            if "review_id" in summary:
                require(
                    current_reviews[0].get("node_id") == summary.get("review_id"),
                    "review-summary-review-binding",
                )
            return summary, historical_findings_count
        require(len(associations) == 1, "producer-run-pull-request-count")
        association = exact_object(associations[0], "producer-run-pull-request")
        association_base = exact_object(
            association.get("base"), "producer-run-pull-request-base"
        )
        association_head = exact_object(
            association.get("head"), "producer-run-pull-request-head"
        )
        for label, value, expected_ref, expected_sha in (
            ("base", association_base, base_ref, base_sha),
            ("head", association_head, head_ref, head_sha),
        ):
            association_repository = exact_object(
                value.get("repo"),
                f"producer-run-pull-request-{label}-repository",
            )
            require(
                value.get("ref") == expected_ref
                and value.get("sha") == expected_sha
                and integer(
                    association_repository.get("id"),
                    f"producer-run-pull-request-{label}-repository-id",
                )
                == repository_id
                and association_repository.get("name") == repository_name
                and association_repository.get("url") == repository_url,
                f"producer-run-pull-request-{label}-binding",
            )
        require(
            integer(association.get("number"), "producer-run-pull-request-number")
            == pull_number
            and association.get("url") == f"{repository_url}/pulls/{pull_number}",
            "producer-run-pull-request-binding",
        )
    return summary, (native_binding["historical_findings_count"]
                     if evidence_kind == "copilot" else 0)


def bound_review_check(
    pages: Any,
    *,
    repository: str,
    pull: JSON,
    pull_number: int,
    base_sha: str,
    head_sha: str,
    merge_base_sha: str | None = None,
) -> JSON:
    expected_kind = expected_evidence_kind(pull, repository=repository)
    v6_titles = {
        "ancestry-backmerge": "Current revision deterministic exemption passed",
        "copilot": "Current revision review passed",
        "managed-sync": "Current revision managed distribution exemption passed",
        "renovate": "Current revision Renovate exemption passed",
    }
    matches: list[JSON] = []
    for check in check_pages(pages):
        app = exact_object(check.get("app"), "check-app")
        if not (
            check.get("name") == "Current revision review"
            and integer(app.get("id"), "check-app-id") == 15368
            and app.get("slug") == "github-actions"
            and check.get("head_sha") == head_sha
            and check.get("status") == "completed"
            and check.get("conclusion") == "success"
        ):
            continue
        external_id = text(check.get("external_id"), "check-external-id")
        output = exact_object(check.get("output"), "check-output")
        output_title = text(output.get("title"), "check-output-title")
        v6 = V6_EXTERNAL_ID.fullmatch(external_id)
        if v6 is not None:
            if (
                expected_kind == v6.group("kind")
                and int(v6.group("pr")) == pull_number
                and v6.group("base") == base_sha
                and v6.group("head") == head_sha
                and output_title == v6_titles[expected_kind]
            ):
                native_binding: JSON = {}
                summary, historical_findings_count = validate_producer_run(
                    check,
                    repository=repository,
                    pull=pull,
                    pull_number=pull_number,
                    base_sha=base_sha,
                    head_sha=head_sha,
                    evidence_kind=v6.group("kind"),
                    evidence_version="v6",
                    copilot_binding=native_binding,
                    producer_run_id=int(v6.group("run")),
                )
                match = {
                    "check_id": integer(check.get("id"), "check-id"),
                    "evidence_kind": v6.group("kind"),
                    "evidence_version": "v6",
                    "external_id": external_id,
                    "producer_run_id": int(v6.group("run")),
                    "summary_sha256": digest(summary),
                    "historical_findings_count": historical_findings_count,
                }
                if native_binding:
                    match["copilot_binding"] = native_binding
                matches.append(match)
            continue
        v5 = V5_EXTERNAL_ID.fullmatch(external_id)
        if v5 is not None:
            if (
                expected_kind == v5.group("kind")
                and v5.group("base") == base_sha
                and v5.group("head") == head_sha
                and output_title == "Current revision review passed"
            ):
                native_binding: JSON = {}
                summary, historical_findings_count = validate_producer_run(
                    check,
                    repository=repository,
                    pull=pull,
                    pull_number=pull_number,
                    base_sha=base_sha,
                    head_sha=head_sha,
                    evidence_kind=v5.group("kind"),
                    evidence_version="v5",
                    copilot_binding=native_binding,
                    producer_run_id=int(v5.group("run")),
                )
                match = {
                    "check_id": integer(check.get("id"), "check-id"),
                    "evidence_kind": v5.group("kind"),
                    "evidence_version": "v5",
                    "external_id": external_id,
                    "producer_run_id": int(v5.group("run")),
                    "summary_sha256": digest(summary),
                    "historical_findings_count": historical_findings_count,
                }
                if native_binding:
                    match["copilot_binding"] = native_binding
                matches.append(match)
            continue
        v4 = V4_EXTERNAL_ID.fullmatch(external_id)
        if (
            v4 is None
            or expected_kind != "release-app"
            or output_title != "Protected Exact-Revision Codex review passed"
        ):
            continue
        require(merge_base_sha is not None, "expected-review-merge-base-missing")
        expected_merge_base = sha(merge_base_sha, "expected-review-merge-base")
        evidence = review_summary(check)
        expected_v4_keys = {
            "base_sha",
            "diff_sha256",
            "head_sha",
            "input_sha256",
            "integration_tree_sha",
            "merge_base_sha",
            "producer_run_id",
            "pull_request_number",
            "run_url",
            "schema",
            "workflow_sha",
        }
        if (
            set(evidence) == expected_v4_keys
            and evidence.get("schema") == 4
            and integer(
                evidence.get("pull_request_number"),
                "review-summary-pull-request",
            )
            == pull_number
            and evidence.get("base_sha") == base_sha
            and evidence.get("head_sha") == head_sha
            and integer(
                evidence.get("producer_run_id"),
                "review-summary-producer",
            )
            == int(v4.group("run"))
            and evidence.get("input_sha256") == v4.group("input")
            and evidence.get("workflow_sha") == base_sha
            and sha(evidence.get("merge_base_sha"), "review-summary-merge-base")
            == expected_merge_base
            and SHA.fullmatch(
                text(
                    evidence.get("integration_tree_sha"),
                    "review-summary-integration-tree",
                )
            )
            is not None
            and SHA256.fullmatch(
                text(evidence.get("diff_sha256"), "review-summary-diff-sha256")
            )
            is not None
        ):
            summary, historical_findings_count = validate_producer_run(
                check,
                repository=repository,
                pull=pull,
                pull_number=pull_number,
                base_sha=base_sha,
                head_sha=head_sha,
                evidence_kind="release-app",
                evidence_version="v4",
                producer_run_id=int(v4.group("run")),
            )
            match = {
                "check_id": integer(check.get("id"), "check-id"),
                "evidence_kind": "release-app",
                "evidence_version": "v4",
                "external_id": external_id,
                "producer_run_id": int(v4.group("run")),
                "summary_sha256": digest(summary),
                "historical_findings_count": historical_findings_count,
            }
            matches.append(match)
    # GitHub can retain both the policy job's native check and an identical
    # protected-verifier publication for the same producer. Validate every
    # candidate above, then reconcile only byte-equivalent semantic evidence.
    # Distinct producer, version, summary or finding evidence remains
    # ambiguous and therefore fails closed.
    semantic_bindings = {
        canonical({key: value for key, value in match.items() if key != "check_id"})
        for match in matches
    }
    require(len(semantic_bindings) == 1, "bound-current-revision-check-not-unique")
    return max(matches, key=lambda match: match["check_id"])


def validate_review_threads(connection: Any) -> JSON:
    value = exact_object(connection, "review-threads")
    nodes = exact_array(value.get("nodes"), "review-thread-nodes")
    page_info = exact_object(value.get("pageInfo"), "review-thread-page-info")
    require(
        page_info.get("hasNextPage") is False, "review-thread-pagination-incomplete"
    )
    unresolved = 0
    thread_ids: list[str] = []
    for item in nodes:
        thread = exact_object(item, "review-thread")
        thread_id = text(thread.get("id"), "review-thread-id")
        require(len(thread_id) <= 256, "review-thread-id-too-long")
        thread_ids.append(thread_id)
        require(type(thread.get("isResolved")) is bool, "review-thread-resolution")
        if thread["isResolved"] is False:
            unresolved += 1
    require(unresolved == 0, "unresolved-review-thread")
    require(len(thread_ids) == len(set(thread_ids)), "review-thread-id-duplicate")
    return {
        "resolved_thread_ids": sorted(thread_ids),
        "unresolved_threads": unresolved,
    }


THREAD_QUERY = """
query($owner:String!,$name:String!,$number:Int!,$after:String){
  repository(owner:$owner,name:$name){
    pullRequest(number:$number){
      number
      reviewThreads(first:100,after:$after){
        nodes{id isResolved comments(first:1){
          nodes{id databaseId pullRequestReview{id databaseId}}
        }}
        pageInfo{hasNextPage endCursor}
      }
    }
  }
}
"""


def collect_review_threads(repository: str, pull_number: int) -> JSON:
    owner, name = repository.split("/", 1)
    after: str | None = None
    nodes: list[JSON] = []
    while True:
        arguments = [
            "api",
            "graphql",
            "-f",
            f"query={THREAD_QUERY}",
            "-F",
            f"owner={owner}",
            "-F",
            f"name={name}",
            "-F",
            f"number={pull_number}",
        ]
        if after is not None:
            arguments.extend(["-F", f"after={after}"])
        payload = exact_object(gh_json(arguments), "thread-response")
        errors = payload.get("errors")
        require(errors is None or errors == [], "thread-response-errors")
        data = exact_object(payload.get("data"), "thread-data")
        repo = exact_object(data.get("repository"), "thread-repository")
        pull = exact_object(repo.get("pullRequest"), "thread-pull")
        require(
            integer(pull.get("number"), "thread-pull-number") == pull_number,
            "thread-pull-number",
        )
        connection = exact_object(pull.get("reviewThreads"), "thread-connection")
        page_nodes = exact_array(connection.get("nodes"), "thread-page-nodes")
        nodes.extend(exact_object(node, "thread-node") for node in page_nodes)
        require(len(nodes) <= MAX_THREADS_PER_PULL, "review-thread-inventory-too-large")
        page_info = exact_object(connection.get("pageInfo"), "thread-page-info")
        has_next = page_info.get("hasNextPage")
        require(type(has_next) is bool, "thread-has-next-page")
        if not has_next:
            return {"nodes": nodes, "pageInfo": {"hasNextPage": False}}
        cursor = page_info.get("endCursor")
        require(type(cursor) is str and 0 < len(cursor) <= 512, "thread-cursor")
        require(cursor != after, "thread-cursor-cycle")
        after = cursor


def collect_bound_ingress_evidence(
    *,
    repository: str,
    pull: JSON,
    pull_number: int,
    base_sha: str,
    head_sha: str,
    merge_base_sha: str | None = None,
) -> JSON:
    require(
        expected_evidence_kind(pull, repository=repository) != "ancestry-backmerge",
        "ancestry-backmerge-not-structural-boundary",
    )
    checks = gh_json(
        [
            "api",
            "--paginate",
            "--slurp",
            (
                f"repos/{repository}/commits/{head_sha}/check-runs"
                "?check_name=Current%20revision%20review&filter=all&per_page=100"
            ),
        ]
    )
    review = bound_review_check(
        checks,
        repository=repository,
        pull=pull,
        pull_number=pull_number,
        base_sha=base_sha,
        head_sha=head_sha,
        merge_base_sha=merge_base_sha,
    )
    connection = collect_review_threads(repository, pull_number)
    threads = validate_review_threads(connection)
    if review["evidence_kind"] == "copilot":
        binding = exact_object(review.pop("copilot_binding", None), "copilot-binding")
        threads["copilot_finding_binding"] = bind_copilot_live_threads(
            binding, connection, repository=repository,
            pull_number=pull_number, head_sha=head_sha,
        )
    return {"review": review, "threads": threads}


def bind_copilot_live_threads(
    binding: JSON, connection: JSON, *, repository: str,
    pull_number: int, head_sha: str,
) -> JSON:
    """Cover counted and current findings with native resolved root comments."""
    roots: dict[int, JSON] = {}
    root_node_ids: set[str] = set()
    for thread in connection["nodes"]:
        comments = exact_array(exact_object(thread.get("comments"),
                              "thread-root-comments").get("nodes"), "thread-root-nodes")
        require(len(comments) == 1, "producer-review-thread-coverage")
        root = exact_object(comments[0], "thread-root")
        comment_id = integer(root.get("databaseId"), "thread-root-id")
        node_id = text(root.get("id"), "thread-root-node-id")
        require(len(node_id) <= 256 and comment_id not in roots
                and node_id not in root_node_ids, "producer-review-thread-coverage")
        root_node_ids.add(node_id)
        roots[comment_id] = {
            "comment_id": comment_id, "comment_node_id": node_id,
            "thread_id": thread["id"], "review": root.get("pullRequestReview"),
        }
    pages = exact_array(gh_json([
        "api", "--paginate", "--slurp",
        f"repos/{repository}/pulls/{pull_number}/reviews/"
        f"{binding['review_database_id']}/comments?per_page=100",
    ]), "finding-comment-pages")
    current_ids: list[int] = []
    for page in pages:
        for item in exact_array(page, "finding-comment-page"):
            comment = exact_object(item, "finding-comment")
            comment_id = integer(comment.get("id"), "finding-comment-id")
            current_ids.append(comment_id)
            require(len(current_ids) <= MAX_REVIEW_COMMENTS_PER_REVIEW
                    and integer(comment.get("pull_request_review_id"), "finding-comment-review-id")
                    == binding["review_database_id"]
                    and comment.get("original_commit_id") == head_sha,
                    "producer-review-thread-coverage")
            require(not any(marker in normalized_review_text(
                        text(comment.get("body"), "finding-comment-body"))
                        for marker in COPILOT_REVIEW_FAILURE_MARKERS),
                    "producer-review-binding")
            root = roots.get(comment_id)
            require(root is not None
                    and root["comment_node_id"] == comment.get("node_id")
                    and root["review"] == {
                        "id": binding["review_id"],
                        "databaseId": binding["review_database_id"],
                    }, "producer-review-thread-coverage")
    require(len(current_ids) == len(set(current_ids)), "producer-review-thread-coverage")
    targets = binding["finding_comment_ids"]
    if targets is None:
        # Legacy/unlinked counts cannot borrow arbitrary old PR threads. A
        # carried finding is admissible only when the exact current body links it.
        require(not binding["historical_findings_count"]
                or len(current_ids) == binding["historical_findings_count"],
                "producer-review-thread-coverage")
        targets = current_ids
    required = sorted(set(targets) | set(current_ids))
    authenticated: list[JSON] = []
    current_review = binding["native_reviews"][binding["review_id"]]
    for comment_id in required:
        root = roots.get(comment_id)
        require(root is not None, "producer-review-thread-coverage")
        owner = exact_object(root["review"], "finding-root-review")
        native = binding["native_reviews"].get(owner.get("id"))
        require(native is not None
                and integer(owner.get("databaseId"), "finding-root-review-id") == native["id"]
                and timestamp(native["submitted_at"], "finding-review-submitted")
                <= timestamp(current_review["submitted_at"], "current-review-submitted"),
                "producer-review-thread-coverage")
        authenticated.append({**root, "review_head_sha": native["head_sha"]})
    return {
        "review_id": binding["review_id"],
        "review_body_sha256": binding["review_body_sha256"],
        "finding_comment_ids": sorted(targets),
        "current_comment_ids": sorted(current_ids),
        "resolved_roots": authenticated,
    }


def private_runtime_directory() -> Path:
    runner_temp = Path(os.environ.get("RUNNER_TEMP", ""))
    require(runner_temp.is_absolute(), "runner-temp-not-absolute")
    metadata = runner_temp.lstat()
    require(
        stat.S_ISDIR(metadata.st_mode) and not runner_temp.is_symlink(),
        "runner-temp-unsafe",
    )
    require(metadata.st_uid == os.geteuid(), "runner-temp-owner")
    require(metadata.st_mode & 0o022 == 0, "runner-temp-mode")
    require(
        os.access(runner_temp, os.R_OK | os.W_OK | os.X_OK),
        "runner-temp-access",
    )
    return runner_temp


def compute_diff(repository_path: Path, base_sha: str, head_sha: str) -> JSON:
    runner_temp = private_runtime_directory()
    descriptor, name = tempfile.mkstemp(prefix="promotion-diff.", dir=runner_temp)
    path = Path(name)
    try:
        path.unlink()
        with os.fdopen(descriptor, "w+b") as stream:
            completed = subprocess.run(
                [
                    "git",
                    "diff",
                    "--binary",
                    "--full-index",
                    "--no-renames",
                    "--no-color",
                    "--no-ext-diff",
                    "--no-textconv",
                    f"{base_sha}^{{tree}}",
                    f"{head_sha}^{{tree}}",
                    "--",
                ],
                cwd=repository_path,
                env=clean_environment(),
                stdout=stream,
                stderr=subprocess.PIPE,
                check=False,
                timeout=180,
            )
            require(completed.returncode == 0, "promotion-diff-failed")
            stream.flush()
            size = stream.tell()
            require(size > 0, "promotion-diff-empty")
            stream.seek(0)
            hasher = hashlib.sha256()
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                hasher.update(block)
        return {"bytes": size, "sha256": hasher.hexdigest()}
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass


def verify(arguments: argparse.Namespace) -> JSON:
    require(
        re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", arguments.repository)
        is not None,
        "repository",
    )
    require(arguments.repository.startswith("lightning-it/"), "repository-owner")
    require(arguments.base_ref == "main", "base-ref")
    require(arguments.head_ref == "develop", "head-ref")
    expected_base = sha(arguments.expected_base, "expected-base")
    expected_head = sha(arguments.expected_head, "expected-head")
    controller_sha = sha(arguments.controller_sha, "controller-sha")
    expected_body_sha256 = text(arguments.expected_body_sha256, "expected-body-sha256")
    require(
        SHA256.fullmatch(expected_body_sha256) is not None,
        "expected-body-sha256",
    )
    pull_number = integer(arguments.pull_request, "pull-request")
    repository_path = validate_repository_path(arguments.repository_path)

    live_pull = gh_json(["api", f"repos/{arguments.repository}/pulls/{pull_number}"])
    validate_live_promotion(
        live_pull,
        repository=arguments.repository,
        pull_number=pull_number,
        expected_base=expected_base,
        expected_head=expected_head,
    )
    require(
        promotion_body_sha256(live_pull) == expected_body_sha256,
        "promotion-event-body-mismatch",
    )
    baseline_commit = exact_object(
        gh_json(["api", f"repos/{arguments.repository}/commits/{expected_base}"]),
        "baseline-commit",
    )
    require(baseline_commit.get("sha") == expected_base, "baseline-commit-sha")
    baseline_verification = exact_object(
        exact_object(baseline_commit.get("commit"), "baseline-git-commit").get(
            "verification"
        ),
        "baseline-verification",
    )
    require(baseline_verification.get("verified") is True, "baseline-not-verified")
    require(
        baseline_verification.get("reason") == "valid", "baseline-verification-reason"
    )
    baseline_committer = exact_object(
        exact_object(baseline_commit.get("commit"), "baseline-git-commit").get(
            "committer"
        ),
        "baseline-committer",
    )
    baseline_time_raw = text(baseline_committer.get("date"), "baseline-date")
    timestamp(baseline_time_raw, "baseline-date")
    history_anchor, integration_tree, merges = first_parent_merges(
        repository_path, expected_base, expected_head
    )
    diff = compute_diff(repository_path, expected_base, expected_head)
    ingress_inventory: list[tuple[JSON, JSON]] = []
    for merge in merges:
        associated_pages = gh_json(
            [
                "api",
                "--paginate",
                "--slurp",
                "-H",
                "Accept: application/vnd.github+json",
                f"repos/{arguments.repository}/commits/{merge['merge_sha']}/pulls?per_page=100",
            ]
        )
        pull = select_ingress_pull(
            flatten_pull_pages(associated_pages),
            repository=arguments.repository,
            merge_sha=merge["merge_sha"],
            head_sha=merge["head_sha"],
        )
        ingress_inventory.append((merge, pull))

    baseline_candidates = [
        index
        for index, (merge, pull) in enumerate(ingress_inventory)
        if is_ancestor(repository_path, expected_base, merge["head_sha"])
        and has_exact_ancestry_merge_parents(
            repository_path,
            head_sha=merge["head_sha"],
            previous_develop=merge["base_sha"],
            expected_main=expected_base,
        )
        and is_authorized_ancestry_boundary(
            pull,
            repository=arguments.repository,
            expected_main=expected_base,
            previous_develop=merge["base_sha"],
        )
    ]
    reviewed_release_boundary: int | None = None
    if not baseline_candidates:
        # A protected release-metadata PR can introduce main without using the
        # ancestry-only controller. Keep its normal review and thread evidence.
        baseline_candidates = [
            index
            for index, (merge, _pull) in enumerate(ingress_inventory)
            if not is_ancestor(repository_path, expected_base, merge["base_sha"])
            and is_ancestor(repository_path, expected_base, merge["head_sha"])
        ]
        require(len(baseline_candidates) == 1, "baseline-reconciliation-not-unique")
        reviewed_release_boundary = baseline_candidates[0]
        release_merge, release_pull = ingress_inventory[reviewed_release_boundary]
        validate_reviewed_release_baseline(
            repository_path,
            repository=arguments.repository,
            expected_main=expected_base,
            merge=release_merge,
            pull=release_pull,
        )
    require(len(baseline_candidates) == 1, "baseline-reconciliation-not-unique")
    baseline_boundary = baseline_candidates[0]

    structural_boundaries: dict[int, str] = {}
    for index, (merge, pull) in enumerate(ingress_inventory):
        historical_main = ancestry_merge_main(
            repository_path,
            head_sha=merge["head_sha"],
            previous_develop=merge["base_sha"],
        )
        if historical_main is None or not is_authorized_ancestry_boundary(
            pull,
            repository=arguments.repository,
            expected_main=historical_main,
            previous_develop=merge["base_sha"],
        ):
            continue
        validate_ancestry_boundary_content(
            repository_path,
            repository=arguments.repository,
            head_sha=merge["head_sha"],
            previous_develop=merge["base_sha"],
            expected_main=historical_main,
        )
        structural_boundaries[index] = historical_main
    require(
        structural_boundaries.get(baseline_boundary) == expected_base
        or reviewed_release_boundary == baseline_boundary,
        "baseline-reconciliation-not-structural",
    )

    ingress: list[JSON] = []
    for index, (merge, pull) in enumerate(ingress_inventory):
        number = integer(pull.get("number"), "ingress-pull-number")
        merged_at = text(pull.get("merged_at"), "ingress-merged-at")
        timestamp(merged_at, "ingress-merged-at")
        _, post_baseline = classify_ingress_position(index, baseline_boundary)
        ancestry_boundary = index in structural_boundaries
        if post_baseline:
            require(
                is_ancestor(repository_path, expected_base, merge["head_sha"]),
                "post-baseline-ingress-lost-main-ancestry",
            )
        review: JSON | None = None
        threads: JSON | None = None
        if not ancestry_boundary:
            try:
                ingress_merge_base = sha(
                    git(
                        ["merge-base", "--all", merge["base_sha"], merge["head_sha"]],
                        repository_path,
                    ),
                    "ingress-merge-base",
                )
                bound = collect_bound_ingress_evidence(
                    repository=arguments.repository,
                    pull=pull,
                    pull_number=number,
                    base_sha=merge["base_sha"],
                    head_sha=merge["head_sha"],
                    merge_base_sha=ingress_merge_base,
                )
                review = bound["review"]
                threads = bound["threads"]
            except EvidenceError as error:
                raise EvidenceError(f"ingress-pr-{number}:{error}") from error
        ingress.append(
            {
                **merge,
                "pull_request": number,
                "merged_at": merged_at,
                "ancestry_boundary": ancestry_boundary,
                "baseline_reconciliation": index == baseline_boundary,
                "post_baseline": post_baseline,
                "review": review,
                "threads": threads,
            }
        )
    post_baseline_count = sum(item["post_baseline"] is True for item in ingress)
    # A reviewed feature may precede the backsync that introduces main. All
    # first-parent merges here are outside main and retain their exact native
    # acceptance evidence, regardless of position. Reconciliation alone must
    # never qualify as a new change to promote.
    reviewed_change_count = sum(
        not item["ancestry_boundary"] and not item["baseline_reconciliation"]
        for item in ingress
    )
    require(reviewed_change_count > 0, "no-reviewed-change-ingress")

    # Finish every other mutable remote read before taking the final ingress
    # snapshot. No network operation is permitted between this snapshot and
    # constructing the evidence package.
    live_pull_after = gh_json(
        ["api", f"repos/{arguments.repository}/pulls/{pull_number}"]
    )
    validate_live_promotion(
        live_pull_after,
        repository=arguments.repository,
        pull_number=pull_number,
        expected_base=expected_base,
        expected_head=expected_head,
    )
    require(
        promotion_body_sha256(live_pull_after) == expected_body_sha256,
        "promotion-event-body-mismatch",
    )
    require(
        canonical(promotion_binding(live_pull_after))
        == canonical(promotion_binding(live_pull)),
        "promotion-mutated-during-verification",
    )
    validate_protected_ref_tips(
        arguments.repository,
        expected_base=expected_base,
        expected_head=expected_head,
    )

    # Re-read every mutable ingress acceptance binding after all other remote
    # validation. The package below is built from these final values, while the
    # comparisons retain the earlier observation as a race detector.
    for item in ingress:
        ancestry_boundary = item.get("ancestry_boundary") is True
        number = integer(item.get("pull_request"), "revalidation-pull-number")
        try:
            live_ingress = gh_json(
                ["api", f"repos/{arguments.repository}/pulls/{number}"]
            )
            refreshed_pull = select_ingress_pull(
                [live_ingress],
                repository=arguments.repository,
                merge_sha=sha(item.get("merge_sha"), "revalidation-merge-sha"),
                head_sha=sha(item.get("head_sha"), "revalidation-head-sha"),
                expected_number=number,
            )
            require(
                text(refreshed_pull.get("merged_at"), "revalidation-merged-at")
                == item["merged_at"],
                "ingress-merge-mutated-during-verification",
            )
            if reviewed_release_boundary is not None and number == ingress[reviewed_release_boundary]["pull_request"]:
                validate_reviewed_release_baseline(
                    repository_path,
                    repository=arguments.repository,
                    expected_main=expected_base,
                    merge=item,
                    pull=refreshed_pull,
                )
            if ancestry_boundary:
                historical_main = ancestry_merge_main(
                    repository_path,
                    head_sha=sha(item.get("head_sha"), "revalidation-head-sha"),
                    previous_develop=sha(
                        item.get("base_sha"), "revalidation-base-sha"
                    ),
                )
                require(
                    historical_main is not None,
                    "ancestry-boundary-parents-mutated-during-verification",
                )
                require(
                    is_authorized_ancestry_boundary(
                        refreshed_pull,
                        repository=arguments.repository,
                        expected_main=historical_main,
                        previous_develop=sha(
                            item.get("base_sha"), "revalidation-base-sha"
                        ),
                    ),
                    "ancestry-boundary-mutated-during-verification",
                )
                continue
            refreshed = collect_bound_ingress_evidence(
                repository=arguments.repository,
                pull=refreshed_pull,
                pull_number=number,
                base_sha=sha(item.get("base_sha"), "revalidation-base-sha"),
                head_sha=sha(item.get("head_sha"), "revalidation-head-sha"),
                merge_base_sha=sha(
                    git(
                        [
                            "merge-base",
                            "--all",
                            sha(item.get("base_sha"), "revalidation-base-sha"),
                            sha(item.get("head_sha"), "revalidation-head-sha"),
                        ],
                        repository_path,
                    ),
                    "revalidation-merge-base",
                ),
            )
            require(
                canonical(refreshed["review"]) == canonical(item["review"])
                and canonical(refreshed["threads"]) == canonical(item["threads"]),
                "ingress-evidence-mutated-during-verification",
            )
            item["review"] = refreshed["review"]
            item["threads"] = refreshed["threads"]
        except EvidenceError as error:
            raise EvidenceError(f"ingress-pr-{number}:{error}") from error

    evidence = {
        "schema_version": 1,
        "repository": arguments.repository,
        "pull_request": pull_number,
        "base_ref": "main",
        "base_sha": expected_base,
        "head_ref": "develop",
        "head_sha": expected_head,
        "merge_base_sha": expected_base,
        "baseline_committer_date": baseline_time_raw,
        "history_anchor_sha": history_anchor,
        "integration_tree_sha": integration_tree,
        "diff": diff,
        "controller_sha": controller_sha,
        "ingress_count": len(ingress),
        "post_baseline_ingress_count": post_baseline_count,
        "reviewed_change_ingress_count": reviewed_change_count,
        "ingress": ingress,
    }
    return {**evidence, "evidence_sha256": digest(evidence)}


def write_output(path: Path, value: JSON) -> None:
    runner_temp = private_runtime_directory()
    require(path.is_absolute(), "output-not-absolute")
    require(path.parent == runner_temp, "output-outside-runner-temp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        payload = canonical(value)
        written = 0
        while written < len(payload):
            count = os.write(descriptor, payload[written:])
            require(count > 0, "output-short-write")
            written += count
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def parse_arguments(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True)
    parser.add_argument("--pull-request", required=True, type=int)
    parser.add_argument("--base-ref", required=True)
    parser.add_argument("--head-ref", required=True)
    parser.add_argument("--expected-base", required=True)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--controller-sha", required=True)
    parser.add_argument("--expected-body-sha256", required=True)
    parser.add_argument("--repository-path", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args(argv)


def main() -> int:
    if sys.argv[1:] == ["--serve-github-api-proxy"]:
        try:
            serve_github_api_proxy()
        except (EvidenceError, OSError) as error:
            print(f"promotion-evidence-proxy: {error}", file=sys.stderr)
            return 1
        return 0
    arguments = parse_arguments()
    try:
        result = verify(arguments)
        write_output(arguments.output, result)
    except (EvidenceError, OSError, subprocess.SubprocessError) as error:
        print(f"promotion-evidence: {error}", file=sys.stderr)
        return 1
    print(canonical(result).decode("utf-8"), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
