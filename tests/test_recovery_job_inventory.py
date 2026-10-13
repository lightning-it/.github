"""Full native refresh ledgers: validate every job before writer selection."""
import copy
import itertools
import json
import os
from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / '.github/workflows/supplementary-current-revision-required.yml'
HEAD = 'a' * 40


class RecoveryJobInventoryTests(unittest.TestCase):
    def setUp(self):
        self.workflow = WORKFLOW.read_text()
        self.ordering = textwrap.dedent(self.workflow.split('cat >"${ordering}" <<\'JQ\'\n', 1)[1].split('\n          JQ', 1)[0])
        self.refresh = {'id': 500, 'event': 'pull_request_review',
                        'created_at': '2026-10-05T18:00:00Z', 'updated_at': '2026-10-05T18:00:10Z'}
        self.effect = {'name': 'Rerun the canonical protected gate when needed', 'number': 3,
                       'status': 'completed', 'conclusion': 'success',
                       'started_at': '2026-10-05T18:00:04Z', 'completed_at': '2026-10-05T18:00:07Z'}
        self.materialize = {'name': 'Materialize the protected operation claim', 'number': 2,
                            'status': 'completed', 'conclusion': 'success',
                            'started_at': '2026-10-05T18:00:02Z', 'completed_at': '2026-10-05T18:00:03Z'}
        self.writer = {'id': 55, 'run_id': 500, 'run_attempt': 1, 'head_sha': HEAD,
                       'name': 'Refresh canonical Copilot review gate', 'status': 'completed', 'conclusion': 'success',
                       'runner_id': 77, 'started_at': '2026-10-05T18:00:01Z', 'completed_at': '2026-10-05T18:00:09Z',
                       'steps': [self.materialize, self.effect]}

    def jobs(self, event):
        return [copy.deepcopy(self.writer), *[{'id': 56 + n, 'run_id': 500, 'run_attempt': 1, 'head_sha': HEAD,
                 'name': name, 'status': 'completed', 'conclusion': 'skipped', 'runner_id': None, 'steps': []}
                for n, name in enumerate(('Locate protected review refresh',
                                         'Inactive legacy writer' if event else 'Inactive event writer'))]]

    def accepted(self, jobs, event=False, pages=None, refresh=None, caller=False):
        pages = [{'total_count': len(jobs), 'jobs': jobs}] if pages is None else pages
        refresh = {**self.refresh, 'event': 'workflow_dispatch' if event else 'pull_request_review', **(refresh or {})}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'native-recovery-ordering.jq'
            path.write_text(self.ordering)
            if caller:
                # Execute the actual legacy caller's inventory read and filter invocation.
                marker = '              refresh_run="$(jq -c \'.[0]\' <<<"${refresh_runs}")"'
                call = self.workflow.split(marker, 1)[1].split('                <<<"${refresh_jobs}" >/dev/null', 1)[0]
                call = textwrap.dedent(marker + call + '                <<<"${refresh_jobs}" >/dev/null')
                script = 'set -euo pipefail\ngh() { printf %s "${PAGES}"; }\n' + call
                result = subprocess.run(['bash', '-c', script], capture_output=True, text=True, check=False,
                    env={**os.environ, 'PAGES': json.dumps(pages), 'RUNNER_TEMP': tmp,
                         'refresh_runs': json.dumps([refresh]), 'EVENT_HEAD': HEAD,
                         'first_verifier_completed_at': '2026-10-05T18:00:00Z', 'REPOSITORY': 'lightning-it/.github',
                         'producer': json.dumps({'run_started_at': '2026-10-05T18:00:06Z'})})
            else:
                result = subprocess.run(['jq', '-e', '--arg', 'head', HEAD,
                    '--arg', 'failed_at', '2026-10-05T18:00:00Z',
                    '--arg', 'producer_started_at', '2026-10-05T18:00:06Z',
                    '--argjson', 'refresh', json.dumps(refresh), '--argjson', 'event_claim', json.dumps(event),
                    '-f', str(path)], input=json.dumps(pages), capture_output=True, text=True, check=False)
        return result.returncode == 0

    def test_complete_three_job_pilot_and_legacy_ledgers_in_any_order(self):
        for event in (True, False):
            for jobs in itertools.permutations(self.jobs(event)):
                with self.subTest(event=event, order=[j['name'] for j in jobs]):
                    self.assertTrue(self.accepted(jobs, event))
        jobs = self.jobs(False)
        self.assertTrue(self.accepted(jobs, caller=True))
        pages = [{'total_count': 3, 'jobs': jobs[:1]}, {'total_count': 3, 'jobs': jobs[1:]}]
        self.assertTrue(self.accepted(jobs, pages=pages, caller=True))

    def test_raw_inactive_expression_names_remain_bound_runnerless_skips(self):
        import yaml
        source = yaml.safe_load((ROOT / '.github/workflows/copilot-review-refresh.yml').read_text())
        for event, role in ((False, 'refresh-canonical-gate'), (True, 'legacy-refresh')):
            jobs = self.jobs(event)
            jobs[2]['name'] = source['jobs'][role]['name'][4:-3]
            self.assertTrue(self.accepted(jobs, event, caller=not event))
            for field, value in (('runner_id', 7), ('steps', [self.effect]), ('conclusion', 'success'),
                                 ('name', jobs[2]['name'] + ' unexpected'), ('run_attempt', 2)):
                mutated = copy.deepcopy(jobs)
                mutated[2][field] = value
                self.assertFalse(self.accepted(mutated, event))

    def test_inventory_must_be_complete_consistent_and_unique(self):
        for event in (True, False):
            jobs = self.jobs(event)
            for pages in ([], {}, [None], [{'jobs': jobs}],
                          [{'total_count': 4, 'jobs': jobs}], [{'total_count': 2, 'jobs': jobs}],
                          [{'total_count': '3', 'jobs': jobs}], [{'total_count': 3, 'jobs': jobs[:2]}],
                          [{'total_count': 1, 'jobs': jobs[:1]}],
                          [{'total_count': 3, 'jobs': [jobs[0], jobs[1], jobs[1]]}],
                          [{'total_count': 3, 'jobs': jobs[:1]}, {'total_count': 2, 'jobs': jobs[1:]}],
                          [{'total_count': 3, 'jobs': jobs}, {'total_count': 3, 'jobs': []}]):
                with self.subTest(event=event, pages=pages):
                    self.assertFalse(self.accepted(jobs, event, pages=pages))

    def test_every_sibling_is_bound_and_only_expected_runnerless_skips_are_allowed(self):
        for event in (True, False):
            for index in range(3):
                for field, values in {'id': [0, 0.5, '56', None, 55 if index else 56],
                                      'run_id': [501, '500', None], 'run_attempt': [2, '1', None],
                                      'head_sha': ['b' * 40, None], 'name': ['foreign', None]}.items():
                    for value in values:
                        jobs = self.jobs(event)
                        jobs[index][field] = value
                        with self.subTest(event=event, index=index, field=field, value=value):
                            self.assertFalse(self.accepted(jobs, event))
            for index in (1, 2):
                for field, values in {'status': ['queued', 'in_progress', None],
                                      'conclusion': ['failure', 'success', 'cancelled', None],
                                      'runner_id': [0, 12, '0'], 'steps': [None, [self.effect]],
                                      'name': ['Inactive event writer' if event else 'Inactive legacy writer']}.items():
                    for value in values:
                        jobs = self.jobs(event)
                        jobs[index][field] = value
                        with self.subTest(event=event, index=index, field=field, value=value):
                            self.assertFalse(self.accepted(jobs, event))
                jobs = self.jobs(event)
                del jobs[index]['runner_id']
                self.assertFalse(self.accepted(jobs, event))
            jobs = self.jobs(event)
            jobs[1] = {**jobs[0], 'id': 99}
            self.assertFalse(self.accepted(jobs, event))
            self.assertFalse(self.accepted(self.jobs(event), event, refresh={'event': 'push'}))
        jobs = self.jobs(False)
        jobs[2]['conclusion'] = 'failure'
        self.assertFalse(self.accepted(jobs, caller=True))

    def test_step_three_requires_the_successful_materializer_before_effect(self):
        for event in (True, False):
            for changes in ({'number': 1}, {'number': '2'}, {'status': 'queued'}, {'conclusion': 'failure'},
                            {'started_at': '2026-10-05T18:00:00Z'}, {'completed_at': '2026-10-05T18:00:05Z'}):
                jobs = self.jobs(event)
                jobs[0]['steps'][0].update(changes)
                self.assertFalse(self.accepted(jobs, event))
            for steps in ([self.effect], [self.materialize, self.materialize, self.effect],
                          [self.materialize, {**self.effect, 'number': 2}],
                          [self.materialize, self.effect, self.effect]):
                jobs = self.jobs(event)
                jobs[0]['steps'] = steps
                self.assertFalse(self.accepted(jobs, event))

    def test_actual_refresh_source_has_the_three_expected_jobs_and_steps(self):
        import yaml
        refresh = yaml.safe_load((ROOT / '.github/workflows/copilot-review-refresh.yml').read_text())
        jobs = refresh['jobs']
        self.assertEqual({'forward-review-event', 'refresh-canonical-gate', 'legacy-refresh'}, set(jobs))
        self.assertEqual('Locate protected review refresh', jobs['forward-review-event']['name'])
        for job_id, inactive in (('refresh-canonical-gate', 'Inactive event writer'), ('legacy-refresh', 'Inactive legacy writer')):
            self.assertIn(inactive, jobs[job_id]['name'])
            self.assertIn('Refresh canonical Copilot review gate', jobs[job_id]['name'])
            self.assertEqual(['Materialize the protected operation claim', 'Rerun the canonical protected gate when needed'],
                             [step['name'] for step in jobs[job_id]['steps']])
