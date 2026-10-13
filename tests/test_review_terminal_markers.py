"""Keep normal review admission aligned with canonical terminal markers."""
import ast
import json
import os
from pathlib import Path
import re
import subprocess
import textwrap
import unittest

from tests import test_copilot_review_refresh as contracts
from tests.test_review_event_reconcile import EVENT

ROOT = Path(__file__).resolve().parents[1]
HEAD = 'b' * 40


def producer_function(name):
    source = (ROOT / '.github/workflows/copilot-review.yml').read_text()
    start = source.index(f'          {name}() {{\n')
    end = source.index('\n          }\n', start) + len('\n          }\n')
    return textwrap.dedent(source[start:end])


class TerminalMarkerParityTests(unittest.TestCase):
    def test_python_and_required_jq_contractions_preserve_cannot_and_existing_negations(self):
        phrases = ("I can't review this pull request.", "I can’t review this pull request.",
                   "I can't review any files.", "I can’t review any files.",
                   "Copilot wasn't able to review any files.", "Copilot isn’t able to review any files.")
        for path, function, markers in (
                ('scripts/review_request_continuation.py', 'normalize', 'FAILURE_MARKERS'),
                ('scripts/review_request_provenance.py', 'normalize', 'FAILURE_MARKERS'),
                ('scripts/verify-promotion-evidence.py', 'normalized_review_text', 'COPILOT_REVIEW_FAILURE_MARKERS'),
                ('scripts/verify-main-trust-root-bootstrap.py', 'normalized_review_text', 'REJECTED_REVIEW_MARKERS')):
            tree = ast.parse((ROOT / path).read_text())
            selected = [node for node in tree.body if
                        (isinstance(node, ast.FunctionDef) and node.name == function) or
                        (isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
                         and node.targets[0].id == markers)]
            namespace = {'re': re}
            exec(compile(ast.Module(body=selected, type_ignores=[]), path, 'exec'), namespace)
            for phrase in phrases:
                with self.subTest(path=path, phrase=phrase):
                    value = namespace[function](phrase)
                    self.assertTrue(any(marker in value for marker in namespace[markers]))
                    if phrase.startswith('I can'):
                        self.assertIn('cannotreview', value)
        required = (ROOT / '.github/workflows/supplementary-current-revision-required.yml').read_text()
        pipelines = re.findall(r'ascii_downcase\s*\|\s*(gsub\("can.*?gsub\("\\\\s";\s*""\))', required)
        self.assertEqual(3, len(pipelines))
        for pipeline in pipelines:
            for phrase in phrases:
                result = subprocess.run(['jq', '-er', 'ascii_downcase | ' + pipeline],
                                        input=json.dumps(phrase), capture_output=True, text=True, check=False)
                self.assertEqual(0, result.returncode, result.stderr)
                if phrase.startswith('I can'):
                    self.assertIn('cannotreview', result.stdout)
                else:
                    self.assertIn('notabletoreviewanyfiles', result.stdout)

    def test_canonical_markers_are_rejected_by_all_actual_admission_predicates(self):
        source = ast.parse((ROOT / 'scripts/verify-promotion-evidence.py').read_text())
        canonical = next(ast.literal_eval(node.value) for node in source.body
                         if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name)
                         and target.id == 'COPILOT_REVIEW_FAILURE_MARKERS' for target in node.targets))
        self.assertEqual(canonical, tuple(re.sub(r'\s', '', marker) for marker in EVENT.MARKERS))
        required = (ROOT / '.github/workflows/supplementary-current-revision-required.yml').read_text()
        marker_arrays = re.findall(r'\["unabletoreviewthispullrequest".*?"encounteredanerror"\]', required, re.S)
        self.assertEqual(3, len(marker_arrays))
        for marker_array in marker_arrays:
            self.assertEqual(canonical, tuple(json.loads(marker_array)))
        env = {**os.environ, 'REPOSITORY': 'lightning-it/.github', 'PR_NUMBER': '23',
               'HEAD_SHA': HEAD, 'EXPECTED_HEAD': HEAD, 'current_external_kind': 'copilot',
               'reviewer': 'copilot-pull-request-reviewer[bot]', 'review_comments_query': 'fixture',
               'UNABLE_REVIEW_MARKER': 'unable to review this pull request',
               'NO_FILES_REVIEW_MARKER': 'was not able to review any files',
               'QUOTA_EXHAUSTED_MARKER': 'quota exhausted', 'QUOTA_EXCEEDED_MARKER': 'quota exceeded',
               'SUPPRESSED_COMMENTS_MARKER': 'suppressed comments'}
        initial = 'gh() { printf %s "${REVIEWS}"; }\n' + producer_function('review_exists_for_head') + '\nreview_exists_for_head\n'
        producer = 'graphql() { printf %s "${RESPONSE}"; }\n' + producer_function('review_comments_clean') + '\nreview_comments_clean 17 "${HEAD_SHA}"\n'
        refresh = r'''oa() {
  case "$*" in
    *'/comments?'*) printf %s "${COMMENTS}" ;;
    *'/reviews?'*) printf %s "${REVIEWS}" ;;
    *) printf %s "${REVIEW}" ;;
  esac
}
''' + contracts.CopilotReviewRefreshTests._rfn('usable_current_review') + '\nusable_current_review\n'
        for marker in (*EVENT.MARKERS, "I can't review this pull request.",
                       "I can’t review this pull request.", "I can't review any files.",
                       "I can’t review any files.", 'Review complete.'):
            for inline in (False, True):
                value = marker.upper().replace(' ', '\n')
                body = '' if inline else value
                comment_nodes = [{'body': value}] if inline else []
                review = {'id': 17, 'commit_id': HEAD, 'body': body,
                          'state': 'COMMENTED', 'user': {'login': env['reviewer']}}
                payload = {'data': {'node': {'body': body, 'commit': {'oid': HEAD},
                           'pullRequest': {'headRefOid': HEAD},
                           'comments': {'nodes': comment_nodes, 'pageInfo': {'hasNextPage': False}}}}}
                case_env = {**env, 'REVIEW': json.dumps(review), 'REVIEWS': json.dumps([[review]]),
                            'COMMENTS': json.dumps([comment_nodes]), 'RESPONSE': json.dumps(payload)}
                accepted = marker == 'Review complete.'
                self.assertEqual(accepted, EVENT.clean_review(review, comment_nodes, HEAD))
                for name, script in [('producer', producer), ('refresh', refresh), *([] if inline else [('request', initial)])]:
                    with self.subTest(marker=marker, inline=inline, consumer=name):
                        result = subprocess.run(['bash', '-eu', '-c', script], env=case_env,
                                                capture_output=True, text=True, check=False)
                        self.assertEqual(0 if accepted or name == "request" else 1, result.returncode, result.stderr)


if __name__ == '__main__':
    unittest.main()
