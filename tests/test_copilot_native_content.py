"""Retained native Copilot frame regressions; no API/provider/controller calls."""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import copilot_native_content as MODULE

ROOT = Path(__file__).resolve().parents[1]

SCRIPT = Path(MODULE.__file__)

CURRENT_COPILOT_OVERVIEW = (
    "<!-- ccr-overview-v2 -->\n\n"
    "### 🔵 Needs a closer look\n\n"
    "Final confidence depends on protected live credential and GitHub inventory "
    "behavior that mocked tests cannot verify.\n\n"
    "**0 open findings**\n\n"
    "<details>\n"
    "<summary><strong>What changed in this PR</strong></summary>\n\n"
    "Enables the guarded, read-only Terraform creation preview.\n"
    "</details>\n\n"
    "🧠 **Review effort:** Balanced\n"
)

def overview_with_tail(body, tail):
    footer = "🧠 **Review effort:** Balanced\n"
    if body.endswith(footer):
        return body.removesuffix(footer) + tail + "\n" + footer
    return body + tail

CURRENT_COPILOT_OPEN_FINDING = (
    "<details open>\n"
    "<summary><strong>1 open finding</strong></summary>\n\n"
    "- Finding recorded in its native review thread.\n"
    "</details>"
)

COPILOT_RESOLVED_HISTORY = (
    "<details>\n"
    "<summary><strong>Resolved since last review (1)</strong></summary>\n\n"
    "- Finding from the earlier review.\n"
    "</details>\n"
)

CURRENT_COPILOT_RESOLVED_HISTORY = COPILOT_RESOLVED_HISTORY.replace(
    "Resolved since last review (1)", "1 resolved since last review"
)

COPILOT_MEDIUM_ICON = (
    '<picture><source media="(prefers-color-scheme: dark)" '
    'srcset="https://github.githubassets.com/static/images/icons/'
    'copilot-code-review/medium-v2-dark.svg">'
    '<source media="(prefers-color-scheme: light)" '
    'srcset="https://github.githubassets.com/static/images/icons/'
    'copilot-code-review/medium-v2-light.svg">'
    '<img src="https://github.githubassets.com/static/images/icons/'
    'copilot-code-review/medium-v2-light.png" alt="Medium severity" '
    'width="62" height="18" align="texttop"></picture>'
)

COPILOT_PREVIOUSLY_MISSED_HISTORY = (
    "<details>\n"
    "<summary><strong>Previously missed (1)</strong></summary>\n\n"
    "In code that hasn't changed since last review\n\n"
    "<details>\n"
    f"<summary>{COPILOT_MEDIUM_ICON} Add subprocess coverage for import paths</summary>\n\n"
    "The existing-resource import paths need regression coverage.\n"
    "</details>\n</details>\n"
)

class NativeFrameTests(unittest.TestCase):
    def test_current_copilot_overview_rejects_previously_missed_findings(self) -> None:
        for verdict in ("🔵 Needs a closer look", "🟢 Approval recommended"):
            body = CURRENT_COPILOT_OVERVIEW.replace("🔵 Needs a closer look", verdict)
            for resolved in ("", COPILOT_RESOLVED_HISTORY, CURRENT_COPILOT_RESOLVED_HISTORY):
                with self.subTest(verdict=verdict, resolved=resolved), self.assertRaisesRegex(MODULE.EvidenceError, "producer-review-binding"):
                    MODULE.historical_copilot_findings_count(
                        overview_with_tail(body, resolved + COPILOT_PREVIOUSLY_MISSED_HISTORY)
                    )
        open_body = CURRENT_COPILOT_OVERVIEW.replace(
            "🔵 Needs a closer look", "🟡 Changes recommended"
        ).replace("**0 open findings**", CURRENT_COPILOT_OPEN_FINDING)
        with self.assertRaisesRegex(MODULE.EvidenceError, "producer-review-binding"):
            MODULE.historical_copilot_findings_count(
                overview_with_tail(open_body, COPILOT_PREVIOUSLY_MISSED_HISTORY)
            )

    def test_quote_projection_preserves_tabs_and_indented_literals(self) -> None:
        for source, projected in (
            ('>\t> ordinary text', ['', 'ordinary text']),
            ('> \t> ordinary text', ['', '    > ordinary text']),
            ('\t> ordinary text', ['    > ordinary text']),
            ('   >\t > ordinary text', ['', 'ordinary text']),
            ('>\t\tcode', ['', '    code']),
            ('> - item', ['', '', 'item']),
            ('>   > text', ['', 'text']),
        ):
            with self.subTest(source=source):
                self.assertEqual(projected, MODULE.copilot_container_lines([source]))
        self.assertEqual(['', '', 'item', 'continuation', '', 'outside'],
                         MODULE.copilot_container_lines(
                             ['> - item', '>   continuation', '', 'outside']))

    def test_link_matching_work_is_bounded(self) -> None:
        functions = (
            MODULE.copilot_reference_text, MODULE.copilot_inline_emphasis,
            lambda text: MODULE.assessment_visible_text(text, strict_links=False, references=set()),
            lambda text: MODULE.copilot_has_missed_heading([text]),
        )
        for count in (128, 1024):
            for source in ('[' * count, '[a](' * count, '[' * count + ']' * count,
                           '[' + '`' * count):
                for function in functions:
                    events = 0
                    budget = 512 * len(source) + 8192

                    def trace(frame, event, arg, budget=budget):
                        nonlocal events
                        if frame.f_code.co_filename != str(SCRIPT):
                            return None
                        if event == 'line':
                            events += 1
                            if events > budget:
                                raise AssertionError('link parsing exceeded linear work budget')
                        return trace

                    with self.subTest(count=count, source=source[:12], function=function):
                        previous = sys.gettrace()
                        try:
                            sys.settrace(trace)
                            result = function(source)
                        finally:
                            sys.settrace(previous)
                        self.assertEqual(False if type(result) is bool else source, result)
                        self.assertLessEqual(events, budget)

    def test_link_indexes_preserve_literal_and_quote_policies(self) -> None:
        # Parenthesis scans start independently even inside an earlier failed
        # destination's quoted region. Quotes at nested depth differ by caller.
        def previous_end(text, start, any_depth):
            nesting, cursor, quoted = 1, start + 1, None
            while cursor < len(text):
                char = text[cursor]
                if char == '\\':
                    cursor += 2
                    continue
                if quoted is not None:
                    if char == quoted:
                        quoted = None
                elif char == '<' or (char in '\"\'' and (
                        text[cursor - 1].isspace() if any_depth
                        else nesting == 1 and text[cursor - 1] in ' \t\r\n')):
                    quoted = '>' if char == '<' else char
                elif char == '(':
                    nesting += 1
                elif char == ')':
                    nesting -= 1
                    if not nesting:
                        return cursor
                cursor += 1
            return -1

        for text in ('(url "title)")', '(url <target)> tail)', '(outer (x "t)") end)',
                     '(url "failed [x](ok)', '(url <failed [x](ok)', '(a\\)b)',
                     '(url\u00a0"title)")', '(outer (x\u00a0\'t)\') end)',
                     '[x](u "t\\\")") [y](v)', '(' * 64 + ')' * 64):
            for any_depth in (False, True):
                ends = MODULE.copilot_parenthesis_ends(text, title_at_any_depth=any_depth)
                for start, char in enumerate(text):
                    if char == '(':
                        with self.subTest(text=text, any_depth=any_depth, start=start):
                            self.assertEqual(previous_end(text, start, any_depth), ends[start + 1])
        text = '[a `]` b](u)'
        self.assertEqual('[a `]` b](u)', MODULE.copilot_inline_emphasis(text))
        self.assertEqual('a ] b', MODULE.assessment_visible_text(text))
        self.assertEqual('[x\\[y]', MODULE.copilot_reference_text('[x\\[y]'))
        self.assertEqual('[outer[inner]]()', MODULE.copilot_reference_text(
            '[outer[inner]][r]\n\n[r]: /x').splitlines()[0])
        self.assertEqual('\ufffc', MODULE.copilot_reference_text(
            '![outer[inner]][r]\n\n[r]: /x').splitlines()[0])
        spaced = 'a' + ' ' * 2000 + 'b'
        self.assertEqual('[' + spaced + ']()', MODULE.copilot_reference_text(
            '[' + spaced + ']\n\n[a b]: /x').splitlines()[0])

    def test_nested_unknown_reference_normalization_is_bounded(self) -> None:
        source = '[' * 1024 + ']' * 1024
        for function in (lambda text: MODULE.copilot_reference_text(text + '\n\n[r]: /x'),
                         lambda text: MODULE.assessment_visible_text(
                             text, strict_links=False, references={'r'})):
            with self.assertRaisesRegex(MODULE.EvidenceError, 'producer-review-binding'):
                function(source)
        # Ordinary reference lookups, including long whitespace, remain valid.
        self.assertEqual('a' + ' ' * 2000 + 'b', MODULE.assessment_visible_text(
            '[a' + ' ' * 2000 + 'b]', references={'a b'}))

    def test_code_run_index_preserves_each_independent_start(self) -> None:
        for text in ('`a`', '```unmatched', '```a``b`', '`a``b`c``',
                     '``a\\`b``', '`a\n\nb`', '`a\n- b`', '`a\n  b`'):
            index = MODULE.copilot_code_span_index(text)
            for position, char in enumerate(text):
                if char != '`':
                    continue
                ticks = re.match(r'`+', text[position:]).group()
                close = re.search(
                    r'(?<!`)' + ticks + r'(?!`)', text[position + len(ticks):])
                closing = position + len(ticks) + close.start() if close else -1
                with self.subTest(text=text, position=position):
                    self.assertEqual(len(ticks), index[0][position])
                    self.assertEqual(closing, index[1][position])
        for text, expected in (('`a\n\nb`', -1), ('`a\n- b`', -1),
                               ('`a\n  b`', len('`a\n  b`'))):
            self.assertEqual(expected, MODULE.copilot_code_span_end(text, 0))
        text = '`a\n\nb`'
        with self.assertRaisesRegex(MODULE.EvidenceError, 'producer-review-binding'):
            MODULE.copilot_code_span_end(text, 0, MODULE.copilot_code_span_index(text), [0])
        # Many ordinary spans on a single line do not repeatedly copy its prefix.
        text = ' '.join(['`x`'] * 128)
        self.assertEqual(text, MODULE.copilot_reference_text(text))
        self.assertEqual(text, MODULE.copilot_inline_emphasis(text))
        self.assertEqual(' '.join(['x'] * 128), MODULE.assessment_visible_text(text))

    def test_delimiter_matching_work_is_bounded(self) -> None:
        # Count executed matcher lines rather than relying on machine speed.
        # Cross-character and rule-of-three mismatches must not rescan all
        # previously unmatched openers, including inside a visible link label.
        for count in (64, 512):
            for source, expected in (
                (('*a ' * count) + ('a_ ' * count),
                 ('*a ' * count) + ('a_ ' * count)),
                (('_a ' * count) + ('a* ' * count),
                 ('_a ' * count) + ('a* ' * count)),
                (('*a ' * count) + ('a**b ' * count),
                 ('*a ' * count) + ('ab ' * count)),
            ):
                for linked in (False, True):
                    text = f'[{source}](x)' if linked else source
                    events = 0
                    budget = (640 if linked else 320) * count + 2048

                    def trace(frame, event, arg, budget=budget):
                        nonlocal events
                        if frame.f_code is not MODULE.copilot_inline_emphasis.__code__:
                            return None
                        if event == 'line':
                            events += 1
                            if events > budget:
                                raise AssertionError('delimiter matching exceeded linear work budget')
                        return trace

                    with self.subTest(count=count, linked=linked, source=source[:12]):
                        previous = sys.gettrace()
                        try:
                            sys.settrace(trace)
                            result = MODULE.copilot_inline_emphasis(text)
                        finally:
                            sys.settrace(previous)
                        self.assertEqual(f'[{expected}](x)' if linked else expected, result)
                        self.assertLessEqual(events, budget)

    def test_delimiter_index_preserves_partial_and_intervening_runs(self) -> None:
        for source, expected in (
            ('*a _b c* d_', 'a _b c d_'),
            ('*a **b* c**', 'a b c'),
            ('***a** b*', 'a b'),
            ('a*b c**', 'a*b c**'),
            ('~~a ~b c~~ d~', 'a ~b c d~'),
            ('*a _b c_ d*', 'a b c d'),
        ):
            with self.subTest(source=source):
                self.assertEqual(expected, MODULE.copilot_inline_emphasis(source))

    def test_current_copilot_overview_counts_only_submission_findings(self) -> None:
        for verdict in ("🔵 Needs a closer look", "🟢 Approval recommended"):
            body = CURRENT_COPILOT_OVERVIEW.replace("🔵 Needs a closer look", verdict)
            for history in (
                "", COPILOT_RESOLVED_HISTORY, CURRENT_COPILOT_RESOLVED_HISTORY,
            ):
                with self.subTest(verdict=verdict, history=history):
                    self.assertEqual(
                        0, MODULE.historical_copilot_findings_count(overview_with_tail(body, history))
                    )
        open_body = CURRENT_COPILOT_OVERVIEW.replace(
            "🔵 Needs a closer look", "🟡 Changes recommended"
        ).replace("**0 open findings**", CURRENT_COPILOT_OPEN_FINDING)
        for count in (1, 2):
            body = open_body.replace(
                "1 open finding</strong>",
                f"{count} open {'finding' if count == 1 else 'findings'}</strong>",
            )
            with self.subTest(count=count):
                self.assertEqual(count, MODULE.historical_copilot_findings_count(body))

    def test_current_copilot_overview_rejects_unknown_or_conflicting_fields(self) -> None:
        body = CURRENT_COPILOT_OVERVIEW
        open_body = body.replace("**0 open findings**", CURRENT_COPILOT_OPEN_FINDING)
        for invalid in (
            body.replace("<!-- ccr-overview-v2 -->", "<!-- ccr-overview-v3 -->"),
            body.replace("🔵 Needs a closer look", "Unknown verdict"),
            body.replace("🔵 Needs a closer look", "🟡 Changes recommended"),
            body.replace("### 🔵", "prefix ### 🔵"),
            body + "\n### 🟢 Approval recommended",
            body + "\n### 🔵 Needs a closer look",
            body + "\nprefix ### 🟢 Approval recommended",
            body + "\n## Copilot review overview",
            body + "\n**Findings:** None",
            body + "\n**FINDINGS:** 1",
            body + "\n**0 open findings**",
            body + "\n" + CURRENT_COPILOT_OPEN_FINDING,
            body + "\n" + CURRENT_COPILOT_OPEN_FINDING.upper(),
            body.replace("**0 open findings**", "**0 open finding**"),
            body.replace("**0 open findings**", "**2 open findings**"),
            body.replace("**0 open findings**", "**unknown open findings**"),
            body.replace("**0 open findings**", "prefix **0 open findings**"),
            body.replace("**0 open findings**", "**0 open findings** extra"),
            body.replace("**0 open findings**", ""),
            body.replace("</details>", ""),
            body + "\n</details>",
            body.replace("What changed in this PR", "Unknown findings (1)"),
            body + "\n<summary><strong>What changed in this PR</strong></summary>",
            body.replace("**0 open findings**", "<details>\n**0 open findings**\n</details>"),
            body + "\n<details>\n</details>",
            body + "\n<details>\n<summary>Unknown section</summary>\n</details>",
            body + "\n<DETAILS>\n<SUMMARY>Unknown section</SUMMARY>\n</DETAILS>",
            body + "\n<DeTaIlS>\n<SuMmArY>Unknown section</SuMmArY>\n</DeTaIlS>",
            body + "\n" + COPILOT_RESOLVED_HISTORY.upper(),
            body + "\n<details>\nbody without summary\n</details>",
            body.replace("</details>", "</details invalid>\n</details>"),
            body.replace("</details>", "<details>\n</details>\n</details>"),
            body.replace("</details>", COPILOT_RESOLVED_HISTORY + "</details>"),
            body.replace("</details>", "<summary>Unknown</summary>\n</details>"),
            open_body.replace("1 open finding", "0 open findings"),
            open_body.replace("1 open finding", "01 open finding"),
            open_body.replace("1 open finding", "-1 open finding"),
            open_body.replace("1 open finding", "1 open findings"),
            open_body.replace("1 open finding", "2 open finding"),
            open_body.replace("1 open finding", "1001 open findings"),
            open_body.replace("1 open finding", "unknown open finding"),
            open_body.replace("<details open>", "<details>"),
            open_body.replace("🔵 Needs a closer look", "🟢 Approval recommended"),
            overview_with_tail(body, COPILOT_RESOLVED_HISTORY * 2),
            overview_with_tail(body, COPILOT_RESOLVED_HISTORY + CURRENT_COPILOT_RESOLVED_HISTORY),
            overview_with_tail(body, CURRENT_COPILOT_RESOLVED_HISTORY.replace("1 resolved", "0 resolved")),
            overview_with_tail(body, CURRENT_COPILOT_RESOLVED_HISTORY.replace("1 resolved", "unknown resolved")),
            overview_with_tail(body, CURRENT_COPILOT_RESOLVED_HISTORY.replace("1 resolved", "01 resolved")),
            overview_with_tail(body, COPILOT_RESOLVED_HISTORY.replace("(1)", "(unknown)")),
            overview_with_tail(body, COPILOT_RESOLVED_HISTORY.replace("(1)", "(0)")),
            overview_with_tail(body, COPILOT_RESOLVED_HISTORY.replace("<details>", "<details open>")),
            overview_with_tail(body, COPILOT_PREVIOUSLY_MISSED_HISTORY.replace("(1)", "(2)")),
            overview_with_tail(body, COPILOT_PREVIOUSLY_MISSED_HISTORY.replace(COPILOT_MEDIUM_ICON, "<picture>unknown</picture>")),
            overview_with_tail(body, COPILOT_RESOLVED_HISTORY.replace("- Finding from the earlier review.", COPILOT_PREVIOUSLY_MISSED_HISTORY)),
            overview_with_tail(body, COPILOT_PREVIOUSLY_MISSED_HISTORY.replace(
                "</details>\n</details>", "<details>\n</details>\n</details>\n</details>"
            )),
        ):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(MODULE.EvidenceError, "producer-review-binding"):
                MODULE.historical_copilot_findings_count(invalid)

    def test_legacy_copilot_overview_rejects_fenced_controls_and_empty_fences(self) -> None:
        original = "## Copilot review overview\n**Findings:** None\n"
        for payload in (
            "", "**Findings:** 1", "## Copilot review overview",
            "**0 open findings**", "### Unsupported verdict",
            "<summary><strong>Previously missed (1)</strong></summary>",
            "1 previously missed",
        ):
            for opening, closing in (("```", "```"), ("~~~~text", "~~~~~")):
                with self.assertRaisesRegex(MODULE.EvidenceError, "producer-review-binding"):
                    MODULE.historical_copilot_findings_count(
                        original + f"{opening}\n{payload}\n{closing}\n"
                    )

if __name__ == "__main__":
    unittest.main()
