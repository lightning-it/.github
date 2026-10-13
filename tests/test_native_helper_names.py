"""Native skipped helper names retain expressions; never relax writer authority."""
import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / '.github/workflows/supplementary-current-revision-required.yml'


class NativeHelperNameTests(unittest.TestCase):
    def test_saved_native_job_through_terminal_and_bootstrap_callers(self):
        workflow = WORKFLOW.read_text()
        job = json.loads((ROOT / 'tests/fixtures/native-inactive-producer-job.json').read_text())
        classifier = textwrap.dedent(workflow.split('cat >"${classifier}" <<\'JQ\'\n', 1)[1].split('\n          JQ', 1)[0])
        terminal = workflow.split('                terminal_job_inventory="$(jq -c \\\n', 1)[1].split('                if [ "$(jq', 1)[0]
        terminal = 'terminal_job_inventory="$(jq -c \\\n' + textwrap.dedent(terminal)
        bootstrap = workflow.split('              raw_producer_jobs="${producer_jobs}"\n', 1)[1].split('              producer_job_count=', 1)[0]
        bootstrap = textwrap.dedent(bootstrap) + '\ntest "$(jq length <<<"${producer_jobs}")" -eq 0\n'
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'terminal-producer-inventory.jq').write_text(classifier)
            env = {**os.environ, 'RUNNER_TEMP': tmp, 'REPOSITORY': 'lightning-it/shared-assets-lit',
                   'EVENT_HEAD': job['head_sha'], 'producer_run_id': str(job['run_id']),
                   'producer_id': str(job['run_id']), 'producer_run_attempt': '1',
                   'LI219_EVENT_MODE': 'disabled', 'pr': '{"user":{"type":"User"}}',
                   'd': '^Request protected verifier re-evaluation( / (Diagnose Release-App reusable context and fail closed|Re-run the one protected verifier attempt))?$'}
            variants = [({}, True), *[({key: value}, False) for key, value in (
                ('run_id', 1), ('run_attempt', 2), ('head_sha', '0' * 40),
                ('run_url', 'https://api.github.com/repos/foreign/repo/actions/runs/37457283768'),
                ('workflow_name', 'Unknown producer'), ('runner_id', 42), ('steps', [{'name': 'effect'}]),
                ('name', job['name'] + ' unexpected'), ('status', 'in_progress'), ('conclusion', 'failure'))]]
            for changes, accepted in variants:
                row = {**copy.deepcopy(job), **changes}
                for consumer, script in (('terminal', terminal), ('bootstrap', bootstrap)):
                    with self.subTest(consumer=consumer, changes=changes):
                        case_env = {**env, 'producer_jobs_pages': json.dumps([{'jobs': [row]}]),
                                    'raw_producer_jobs': json.dumps([row])}
                        result = subprocess.run(['bash', '-euo', 'pipefail', '-c', script], env=case_env,
                                                text=True, capture_output=True, check=False)
                        # In-progress rows are not terminal evidence at all.
                        if consumer == 'terminal' and changes.get('status') == 'in_progress':
                            continue
                        self.assertEqual(accepted, result.returncode == 0, result.stderr)
            # Two aliases of the same inert role may never add a second allowance.
            rows = [job, {**job, 'id': job['id'] + 1, 'name': 'Request protected verifier re-evaluation / Inactive event writer'}]
            result = subprocess.run(['bash', '-euo', 'pipefail', '-c', terminal], env={**env,
                'producer_jobs_pages': json.dumps([{'jobs': rows}])}, text=True, capture_output=True, check=False)
            self.assertNotEqual(0, result.returncode)
