"""Pure native Copilot frame/finding validation, retained from accepted source.
No API calls, workflows, provider effects or publication authority.
"""
from __future__ import annotations

import hashlib
import html
import itertools
import re
import unicodedata
from array import array
from bisect import bisect_left, bisect_right
from html.parser import HTMLParser
from typing import Any, ClassVar

JSON = dict[str, Any]


SHA = re.compile(r"^[0-9a-f]{40}$")


PULL_REQUEST_REVIEW_NODE_ID = re.compile(r"^PRR_[A-Za-z0-9_+=/-]{4,252}$")


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


MAX_REVIEW_COMMENTS_PER_REVIEW = 1000


MAX_ASSESSMENT_CHARACTERS = 4096


ASSESSMENT_IGNORABLE = re.compile(
    r"[\u00ad\u034f\u061c\u115f-\u1160\u17b4-\u17b5\u180b-\u180f"
    r"\u200b-\u200f\u202a-\u202e\u2060-\u206f\u3164\ufe00-\ufe0f"
    r"\ufeff\uffa0\ufff0-\ufff8\U0001bca0-\U0001bca3"
    r"\U0001d173-\U0001d17a\U000e0000-\U000e0fff]"
)


class EvidenceError(ValueError):
    """A promotion evidence invariant failed closed."""


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise EvidenceError(reason)


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


def copilot_quote_line(original: str) -> tuple[str, int]:
    """Consume quote prefixes once, with a fresh tab stop after each marker."""
    cursor = 0
    depth = 0
    while True:
        indentation = 0
        while cursor < len(original) and original[cursor] in " \t":
            indentation += 1 if original[cursor] == " " else 4 - indentation % 4
            cursor += 1
        if indentation > 3 or cursor == len(original) or original[cursor] != ">":
            return " " * indentation + original[cursor:], depth
        cursor += 1
        if cursor < len(original) and original[cursor] in " \t":
            cursor += 1
        depth += 1


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
        line, depth = copilot_quote_line(original)
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


def copilot_code_span_index(source: str) -> tuple[array, array, array, array]:
    """Index exact closing runs, including queries inside failed openers."""
    widths = array("i", [0]) * len(source)
    closings = array("i", [-1]) * len(source)
    nearest: dict[int, int] = {}
    position = len(source) - 1
    while position >= 0:
        if source[position] != "`":
            position -= 1
            continue
        stop = position + 1
        while position >= 0 and source[position] == "`":
            position -= 1
        start = position + 1
        for cursor in range(start, stop):
            width = stop - cursor
            widths[cursor] = width
            closings[cursor] = nearest.get(width, -1)
        nearest[stop - start] = start
    line_starts = array("i", [0])
    line_starts.extend(match.end() for match in re.finditer(r"\n", source))
    breaks = array("i", (match.start() for match in re.finditer(
        r"[\n\r\v\f\x1c-\x1e\x85\u2028\u2029]", source)))
    return widths, closings, line_starts, breaks


def copilot_code_span_end(source: str, position: int,
                          index: tuple[array, array, array, array] | None = None,
                          budget: list[int] | None = None) -> int:
    if index is None:
        index = copilot_code_span_index(source)
    width, closing = index[0][position], index[1][position]
    if closing < 0:
        return -1
    stop = closing + width
    beginning = index[2][bisect_right(index[2], position) - 1]
    boundary = bisect_left(index[3], beginning)
    if boundary == len(index[3]) or index[3][boundary] >= closing:
        return stop
    if budget is not None:
        require(closing - beginning <= budget[0], "producer-review-binding")
        budget[0] -= closing - beginning
    paragraph = source[beginning:closing].splitlines()
    if any(copilot_paragraph_interrupts(previous, line)
           for previous, line in itertools.pairwise(paragraph)):
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


def copilot_bracket_ends(source: str, *, shadow: list[str] | None = None,
                         code_end: Any = None) -> array:
    """Pair brackets once, retaining the caller's literal/escape policy."""
    ends = array("i", [-1]) * len(source)
    stack = array("i")
    position = 0
    while position < len(source):
        if source[position] == "\\":
            position += 2
            continue
        if code_end is not None and source[position] == "`":
            ticks, end = code_end(position)
            if end >= 0:
                position = end + ticks
                continue
        char = shadow[position] if shadow is not None else source[position]
        if char == "[":
            stack.append(position)
        elif char == "]" and stack:
            ends[stack.pop()] = position
        position += 1
    return ends


def copilot_parenthesis_ends(source: str, *, title_at_any_depth: bool) -> array:
    """Index each independent destination scan, including failed outer quotes.

    Backward suffix states preserve scans that start inside an earlier quoted
    region. A global delimiter stack would incorrectly inherit that region.
    Compact integer arrays keep the index proportional to the input size.
    """
    top = array("i", [-1]) * (len(source) + 2)
    nested = top if title_at_any_depth else array("i", [-1]) * (len(source) + 2)
    states = ((top, True),) if title_at_any_depth else ((nested, False), (top, True))
    quotes = {char: (-1, -1) for char in "\"'>"}
    for position in range(len(source) - 1, -1, -1):
        char = source[position]
        for state, allow_title in states:
            if char == "\\":
                end = state[position + 2]
            elif char == ")":
                end = position
            elif char == "(":
                closing = nested[position + 1]
                end = state[closing + 1] if closing >= 0 else -1
            elif char == "<" or (allow_title and char in "\"'" and position > 0 and (
                    source[position - 1].isspace() if title_at_any_depth
                    else source[position - 1] in " \t\r\n")):
                closing = quotes[">" if char == "<" else char][0]
                end = state[closing + 1] if closing >= 0 else -1
            else:
                end = state[position + 1]
            state[position] = end
        for quote, (next_one, next_two) in quotes.items():
            closing = next_two if char == "\\" else (position if char == quote else next_one)
            quotes[quote] = (closing, next_one)
    return top


def copilot_known_reference(source: str, start: int, stop: int, references: set[str],
                             budget: list[int], *, decode_entities: bool = False) -> bool:
    """Bound aggregate label copying/normalization as well as delimiter scans."""
    if not references:
        return False
    width = max(0, stop - start)
    require(width <= budget[0], "producer-review-binding")
    budget[0] -= width
    label = source[start:stop]
    if decode_entities:
        label = html.unescape(label)
    return " ".join(label.split()).casefold() in references


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
    code_index = copilot_code_span_index(source) if "`" in source else None
    code_budget = [32 * len(source) + 4096]

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
            stop = copilot_code_span_end(source, position, code_index, code_budget)
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
            tag = re.match(r" {0,3}<(script|pre|style|textarea)(?=[ \t/>]|$)", raw, re.IGNORECASE)
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
            if html_block != "blank" and re.search(html_block, raw, re.IGNORECASE):
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
    bracket_ends = copilot_bracket_ends(source, shadow=shadow)
    reference_budget = [32 * len(source) + 4096]
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
            end = bracket_ends[start]
            if end >= 0 and not source.startswith("(", end + 1):
                target = end + 1
                label_end = copilot_reference_label_end(source, target) if source.startswith("[", target) else -1
                # Collapsed labels are explicitly empty, unlike definitions.
                if source.startswith("[]", target):
                    label_end = target + 1
                label_start, label_stop = ((target + 1, label_end)
                                          if label_end > target + 1 else (start + 1, end))
                if copilot_known_reference(source, label_start, label_stop,
                                            references, reference_budget):
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
    opener_buckets: dict[tuple[str, int, bool], list[dict[str, Any]]] = {}
    tag_pattern = re.compile(r"</?[A-Za-z](?:\"[^\"]*\"|'[^']*'|[^'\">])*>")
    delimiter_pattern = re.compile(r"\*+|_+|~+")
    literal_depth = 0
    bracket_ends = copilot_bracket_ends(source)
    parenthesis_ends: array | None = None
    code_index = copilot_code_span_index(source) if "`" in source else None
    code_budget = [32 * len(source) + 4096]

    def drop_opener() -> None:
        opener = openers.pop()
        bucket = opener_buckets[opener["bucket"]]
        bucket.pop()
        if not bucket:
            del opener_buckets[opener["bucket"]]

    def punctuation(char: str) -> bool:
        return bool(char) and (unicodedata.category(char).startswith("P")
                               or re.fullmatch(r"[!-/:-@\[-`{-~]", char) is not None)

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
                end = re.search(r"</" + name + r"[ \t]*>", source[tag.end():], re.IGNORECASE)
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
            end = copilot_code_span_end(source, position, code_index, code_budget)
            if end >= 0:
                position = end
                continue
        if char == "[":
            end = bracket_ends[position]
            target_end = -1
            if end >= 0 and source.startswith("(", end + 1):
                if parenthesis_ends is None:
                    parenthesis_ends = copilot_parenthesis_ends(source, title_at_any_depth=True)
                target_end = parenthesis_ends[end + 2]
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
        width = delimiter_pattern.match(source, position).end() - position
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
            # Eligibility has a constant number of classes. Every member of
            # a bucket shares the same rule-of-three/tilde result; inspect
            # only its newest live opener, then pick the nearest globally.
            for bucket in opener_buckets.values():
                opener = bucket[-1]
                if opener["char"] != char:
                    continue
                if char == "~" and opener["remaining"] != remaining:
                    continue
                if char != "~" and (opener["can_close"] or can_open) and (
                    (opener["width"] + width) % 3 == 0
                    and (opener["width"] % 3 or width % 3)
                ):
                    continue
                if found is None or opener["index"] > found:
                    found = opener["index"]
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
            while len(openers) > found + 1:
                drop_opener()
            if not opener["remaining"]:
                drop_opener()
        if can_open and remaining:
            key = (char, width if char == "~" else width % 3, can_close)
            opener = {"char": char, "start": position + width - remaining,
                      "remaining": remaining, "width": width, "can_close": can_close,
                      "index": len(openers), "bucket": key}
            openers.append(opener)
            opener_buckets.setdefault(key, []).append(opener)
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
                tag = re.match(r" {0,3}<(script|pre|style|textarea)(?=[ \t/>]|$)", raw, re.IGNORECASE)
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
            if raw_block != "blank" and re.search(raw_block, raw, re.IGNORECASE):
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
    code_index = copilot_code_span_index(source) if "`" in source else None
    code_budget = [32 * len(source) + 4096]
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
            stop = copilot_code_span_end(source, position, code_index, code_budget)
            if stop >= 0:
                masked.append(literal)
                position = stop
                continue
            # An unmatched delimiter is visible punctuation, not authority for
            # the later inline lexer to quote across already established blocks.
            masked.append(literal)
            position += code_index[0][position]
            continue
        masked.append(source[position])
        position += 1

    class HeadingText(HTMLParser):
        blocks: ClassVar[set[str]] = {"summary", "details", "p", "div", "li", "ul", "ol", "table",
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


def copilot_rendered_has_missed_heading(body_html: Any) -> bool:
    """Inspect the provider's rendered review without interpreting Markdown again.

    This representation must accompany the raw body in the authenticated native
    review response. Container scopes and sanitized HTML belong to GitHub's
    renderer; the raw frame parser remains an independent admission constraint.
    """
    source = text(body_html, "producer-review-rendered-body")
    require(len(source.encode("utf-8")) <= MAX_API_BYTES,
            "producer-review-rendered-body-too-large")

    class RenderedHeadingText(HTMLParser):
        voids: ClassVar[set[str]] = {"area", "base", "br", "col", "embed", "hr", "img", "input",
                 "link", "meta", "param", "source", "track", "wbr"}
        blocks: ClassVar[set[str]] = {"summary", "details", "p", "div", "li", "ul", "ol", "table",
                  "tr", "td", "th", "blockquote", "hr", "pre",
                  "h1", "h2", "h3", "h4", "h5", "h6"}

        def __init__(self) -> None:
            super().__init__(convert_charrefs=True)
            self.parts: list[str] = []
            self.stack: list[str] = []
            self.code_depth = 0
            self.hidden_depth = 0

        def boundary(self, tag: str) -> None:
            if not self.hidden_depth:
                if tag == "br":
                    self.parts.append("\n")
                elif tag in self.blocks or review_raw_html_block_start(
                    f"<{tag}>", interrupt_only=True,
                ):
                    self.parts.append("\n\ufffd\n")

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            self.boundary(tag)
            if tag not in self.voids:
                self.stack.append(tag)
            if tag in {"code", "pre"}:
                self.code_depth += 1
            if tag in {"script", "style"}:
                self.hidden_depth += 1
            if tag == "img" and self.code_depth and not self.hidden_depth:
                self.parts.append("\ufffc")

        def handle_endtag(self, tag: str) -> None:
            require(bool(self.stack) and self.stack[-1] == tag,
                    "producer-review-rendered-html")
            self.stack.pop()
            if tag in {"code", "pre"}:
                self.code_depth -= 1
            if tag in {"script", "style"}:
                self.hidden_depth -= 1
            self.boundary(tag)

        def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            self.handle_starttag(tag, attrs)
            if tag not in self.voids:
                self.handle_endtag(tag)

        def handle_data(self, data: str) -> None:
            if self.hidden_depth:
                return
            visible = ASSESSMENT_IGNORABLE.sub("", data)
            if self.code_depth and visible.strip():
                self.parts.append("\ufffc")
            else:
                self.parts.append(visible)

        def handle_decl(self, decl: str) -> None:
            require(False, "producer-review-rendered-html")

        def unknown_decl(self, data: str) -> None:
            require(False, "producer-review-rendered-html")

        def handle_pi(self, data: str) -> None:
            require(False, "producer-review-rendered-html")

    parser = RenderedHeadingText()
    try:
        parser.feed(source)
        parser.close()
    except (ValueError, AssertionError) as error:
        if isinstance(error, EvidenceError):
            raise
        raise EvidenceError("producer-review-rendered-html") from error
    require(not parser.stack and not parser.rawdata,
            "producer-review-rendered-html")
    return re.search(
        r"(?im)^[^\S\r\n]*(?:previously\s+missed(?:\s*\([^()]*\))?"
        r"|[0-9]+\s+previously\s+missed)[^\S\r\n]*$", "".join(parser.parts),
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
    code_index = copilot_code_span_index(text) if "`" in text else None

    def code_end(position: int) -> tuple[int, int]:
        return code_index[0][position], code_index[1][position]

    bracket_ends = copilot_bracket_ends(text, code_end=code_end)
    parenthesis_ends: array | None = None
    reference_budget = [32 * len(text) + 4096]
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
            end = bracket_ends[label_start]
            if end >= 0:
                if text.startswith("[^", label_start):
                    # A definition elsewhere renders only a footnote marker;
                    # its source label is never introductory assessment prose.
                    position = end + 1
                    continue
                destination = end + 1
                if destination < len(text) and text[destination] == "(":
                    if parenthesis_ends is None:
                        parenthesis_ends = copilot_parenthesis_ends(text, title_at_any_depth=False)
                    target_end = parenthesis_ends[destination + 1]
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
                    target_end = bracket_ends[reference]
                    require(target_end >= 0 or not strict_links, "producer-review-binding")
                    ref_start, ref_stop = ((reference + 1, target_end)
                                           if target_end > reference + 1 else (label_start + 1, end))
                    known_reference = target_end >= 0 and (
                        references is None or copilot_known_reference(
                            text, ref_start, ref_stop, references, reference_budget, decode_entities=True,
                        )
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
                elif references is not None and copilot_known_reference(
                    text, label_start + 1, end, references, reference_budget, decode_entities=True,
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
        (verdict != "### 🟢 Approval recommended" or count == 0)
        and (verdict != "### 🟡 Changes recommended" or count > 0),
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
            for previous, line in itertools.pairwise(assessment_source)
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


def bind_copilot_review_findings(
    pages: list[Any], *, repository: str, pull_number: int, head_sha: str
) -> JSON:
    """Retain native findings across both producer association routes."""
    native_reviews: dict[str, JSON] = {}
    for page in pages:
        for item in exact_array(page, "finding-review-page"):
            review = exact_object(item, "finding-review")
            actor = exact_object(review.get("user"), "finding-review-user")
            if (actor.get("login") not in {COPILOT_REVIEWER_LOGIN, COPILOT_REVIEWER_LOGIN.removesuffix("[bot]"), "Copilot"}
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
    require(not copilot_rendered_has_missed_heading(review.get("body_html")),
            "producer-review-binding")
    targets: list[int] | None = None
    if count and "## Copilot review overview" not in body.splitlines():
        lines = [line for line in body.splitlines() if line]
        summary = f"<summary><strong>{count} open {'finding' if count == 1 else 'findings'}</strong></summary>"
        start = lines.index(summary) + 1
        entries = lines[start:lines.index("</details>", start)]
        if any("discussion_r" in line or "](" in line
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


def validate_reported_file_coverage(body: str, changed_files: Any) -> None:
    """Validate a file count when the native intro actually reports one.

    The admitted CCR v2 format does not publish that metric. A known complete
    native frame is retained as its existing service contract; no number is
    invented. Explicit partial or contradictory file-count reports fail closed.
    """
    lines, _ = copilot_frame_control_lines(body)
    boundary = next((i for i, line in enumerate(lines)
                     if line in {"**0 open findings**", "<details open>"}), len(lines))
    intro = " ".join(assessment_visible_text("\n".join(lines[2:boundary])).split())
    for reviewed, total in re.findall(r"\bCopilot reviewed ([0-9]+) out of ([0-9]+) changed files\b", intro, re.IGNORECASE):
        require(type(changed_files) is int and changed_files > 0
                and int(reviewed) == int(total) == changed_files, "copilot-explicit-file-coverage-incomplete")
