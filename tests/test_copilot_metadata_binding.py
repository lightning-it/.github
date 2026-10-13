"""Execute the real producer steps and feed their summary to native recovery."""
import json
import hashlib
import os
from pathlib import Path
import subprocess
import shlex
import tempfile
import unittest
from unittest import mock

import yaml
import test_native_verifier_retry as native
import test_promotion_evidence as promotion

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / '.github/workflows/copilot-review.yml'
GH = r'''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
p = Path(os.environ['FIXTURE'])
d = json.loads(p.read_text())
a = sys.argv[1:]
method = a[a.index('--method')+1] if '--method' in a else 'GET'
route = next(x for x in a if x == 'graphql' or x.startswith('repos/'))
fields = dict(x.split('=',1) for x in a if '=' in x)
query = fields.get('query','')
if route == 'graphql':
    if 'lastEditedAt' in query:
        d['metadata_reads'] += 1
        if d.get('drift_on_read') == d['metadata_reads']:
            d['metadata']['lastEditedAt'] = '2026-10-07T00:01:00Z'
        result = {'data': {'repository': {'nameWithOwner': d['repo'], 'pullRequest': d['metadata']}}}
    elif 'reviews(last:' in query:
        d['review_queries'] = d.get('review_queries', 0) + 1
        result = {'data': {'repository': {'pullRequest': {'headRefOid': d['head'], 'reviews': {
            'nodes': [{'id':'R17','author':{'login':'copilot-pull-request-reviewer'},
                      'commit':{'oid':d['head']},'state':'APPROVED','submittedAt':d['submitted']}],
            'pageInfo': {'hasPreviousPage':False}}}}}}
        if d.get('drift_during_review'):
            d['metadata']['lastEditedAt'] = '2026-10-07T00:01:00Z'
    elif 'node(id:' in query:
        result = {'data': {'node': {'body':'Review complete.', 'commit': {'oid':d['head']},
            'pullRequest': {'headRefOid':d['head']}, 'comments': {'nodes':[], 'pageInfo':{'hasNextPage':False}}}}}
    elif 'reviewThreads' in query:
        result = {'data': {'repository': {'pullRequest': {'headRefOid':d['head'],
                  'reviewThreads':{'nodes':[],'pageInfo':{'hasNextPage':False}}}}}}
    else:
        raise AssertionError(query)
elif method in ('POST','PATCH'):
    if method == 'PATCH' and 'output[title]' in fields and 'output[summary]' not in fields:
        print('"summary" wasn\'t supplied. (HTTP 422)', file=sys.stderr)
        sys.exit(1)
    d['writes'].append(method)
    d.setdefault('write_conclusions', []).append(fields.get('conclusion'))
    if method == 'POST' and d.get('unknown_post') == 'absent':
        p.write_text(json.dumps(d))
        sys.exit(1)
    if method == 'POST':
        d['check'] = {'id':79,'app':{'id':15368,'slug':'github-actions'},
                      'output':{},'details_url':None,'completed_at':'2026-10-07T00:00:00Z'}
    for key, value in fields.items():
        if key.startswith('output['):
            d['check']['output'][key[7:-1]] = value
        else:
            d['check'][key] = value
    result = d['check']
    if d.get('drift_after_post') or (fields.get('conclusion') == 'success' and d.get('drift_after_promotion')):
        d['metadata']['lastEditedAt'] = '2026-10-07T00:01:00Z'
    if (method == 'POST' and d.get('unknown_post')) or (fields.get('conclusion') == 'success' and d.get('unknown_promotion')):
        p.write_text(json.dumps(d))
        sys.exit(1)
elif '/branches/' in route:
    result = {'commit':{'sha':d['base']}}
elif '/compare/' in route:
    result = {'status':'identical'}
elif '/attempts/1/jobs?' in route:
    result = [{'total_count':1,'jobs':[{'id':78,'run_id':77,'run_attempt':1,'head_sha':d['head'],
        'name':'Verify current revision policy','status':'completed','steps':[
          {'name':'Publish bound neutral result','status':'completed','conclusion':d.get('previous_publish','failure')}]}]}]
elif d.get('renovate_handoff') and '/actions/runs/' in route and '/jobs?' in route:
    result = [{'jobs': [{'run_id':77,'head_sha':d['head'],'run_attempt':1,
        'name':'Verify current revision policy','status':'completed','conclusion':'success',
        'steps':[{'name':n,'status':'completed','conclusion':'success'} for n in
                 ('Accept trusted automation exemption','Publish bound neutral result')]},
        *[{'run_id':77,'head_sha':d['head'],'run_attempt':1,'name':n,
           'status':'completed','conclusion':'skipped'} for n in
          ('Request Copilot review for current revision','Request protected verifier re-evaluation')]]}]
elif '/actions/runs/' in route:
    result = {'event':'pull_request_target','name':'Current revision review gate',
        'path':'.github/workflows/copilot-review.yml','head_branch':d['pr']['head']['ref'],'head_sha':d['head'],
        'repository':{'full_name':d['repo']},'head_repository':{'full_name':d['repo']}}
    if d.get('renovate_handoff'):
        result.update(id=77,run_attempt=1,status='completed',conclusion='success',
                      actor={'login':'renovate[bot]'},triggering_actor={'login':'renovate[bot]'},
                      html_url='https://github.com/'+d['repo']+'/actions/runs/77')
elif '/reviews?' in route:
    result = [[]]
elif route == 'repos/' + d['repo']:
    result = {'default_branch':'develop'}
elif '/pulls/' in route:
    result = d['pr']
elif '/commits/' in route:
    rows = [] if d['check'] is None else [d['check']]
    if d.get('unknown_post') == 'ambiguous' and rows:
        rows.append({**rows[0], 'id':80})
    result = [{'total_count':len(rows),'check_runs':rows}]
elif '/check-runs/' in route:
    result = d['check']
else:
    raise AssertionError(a)
p.write_text(json.dumps(d))
print(d['base'] if '--jq' in a else json.dumps(result))
'''


class ProducerMetadataTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.tmp = Path(temp.name)
        self.repo, self.base, self.head = 'lightning-it/.github', 'c' * 40, 'b' * 40
        self.pr = {'number':23,'state':'open','draft':False,'title':'Fix','body':'Review this',
                   'updated_at':'2026-10-07T00:00:00Z','user':{'login':'litroc'},
                   'base':{'sha':self.base,'ref':'develop','repo':{'full_name':self.repo}},
                   'head':{'sha':self.head,'ref':'fix/test','repo':{'full_name':self.repo}}}
        self.data = {'repo':self.repo,'base':self.base,'head':self.head,'pr':self.pr,'writes':[],
                     'check':None,'metadata_reads':0,'submitted':'2026-10-07T00:00:00Z',
                     'metadata':{'number':23,'state':'OPEN','isDraft':False,'baseRefOid':self.base,
                                 'headRefOid':self.head,'headRepository':{'nameWithOwner':self.repo},
                                 'title':'Fix','body':'Review this','lastEditedAt':None}}
        self.fixture = self.tmp / 'fixture.json'
        self.save()
        event = self.tmp / 'event.json'
        event.write_text(json.dumps({'number':23,'repository':{'full_name':self.repo},'pull_request':self.pr}))
        binary = self.tmp / 'bin'
        binary.mkdir()
        (binary / 'gh').write_text(GH)
        (binary / 'gh').chmod(0o755)
        (binary / 'sleep').write_text('#!/bin/sh\nexit 0\n')
        (binary / 'sleep').chmod(0o755)
        (self.tmp / 'current-revision-producer-owner.sh').write_text('eo() { printf 77; }\n')
        self.env = {**os.environ,'PATH':str(binary) + ':' + os.environ['PATH'],
                    'FIXTURE':str(self.fixture),'RUNNER_TEMP':str(self.tmp),'GITHUB_EVENT_PATH':str(event),
                    'GITHUB_OUTPUT':str(self.tmp/'output'),'PR_NUMBER':'23','REPOSITORY':self.repo,
                    'GITHUB_REPOSITORY':self.repo,'GITHUB_SERVER_URL':'https://github.com',
                    'GITHUB_RUN_ID':'77','GITHUB_RUN_ATTEMPT':'1','OWNER_RUN_ID':'77','EVENT_BASE':self.base,'EVENT_HEAD':self.head,
                    'EVENT_HEAD_REF':'fix/test','EVENT_HEAD_REPOSITORY':self.repo,'DEFAULT_BRANCH':'develop',
                    'TRUSTED_WORKFLOW_SHA':self.base,
                    'TRUSTED_WORKFLOW_REF':self.repo+'/.github/workflows/copilot-review.yml@refs/heads/develop',
                    'TRUSTED_KIND':'none','LI219_EVENT_MODE':'enabled',
                    'COPILOT_REVIEWER_LOGIN':'copilot-pull-request-reviewer',
                    'UNABLE_REVIEW_MARKER':'unable to review this pull request',
                    'NO_FILES_REVIEW_MARKER':'was not able to review any files',
                    'QUOTA_EXHAUSTED_MARKER':'quota exhausted','QUOTA_EXCEEDED_MARKER':'quota exceeded',
                    'SUPPRESSED_COMMENTS_MARKER':'suppressed comments'}
        self.workflow = yaml.safe_load(WORKFLOW.read_text())
        self.steps = {step['name']:step['run'] for step in
                      self.workflow['jobs']['verify-current-revision-policy']['steps'] if 'run' in step}

    def save(self):
        self.fixture.write_text(json.dumps(self.data))

    def execute(self, step, succeeds=True):
        result = subprocess.run(['bash','-c',self.steps[step]], env=self.env, text=True,
                                capture_output=True, timeout=30)
        self.data = json.loads(self.fixture.read_text())
        if succeeds:
            self.assertEqual(0, result.returncode, result.stderr + result.stdout)
        elif succeeds is False:
            self.assertNotEqual(0, result.returncode, result.stderr + result.stdout)
        return result

    def capture(self, succeeds=True):
        return self.execute('Bind Copilot input metadata revision', succeeds)

    def configure_renovate(self, edited=None):
        self.pr['user']['login'] = 'renovate[bot]'
        self.pr['user']['type'] = 'Bot'
        self.pr['head']['ref'] = 'renovate/github-actions'
        self.pr['labels'] = [{'name': name} for name in
                             ('dependencies', 'renovate', 'safe-automerge')]
        self.data['metadata']['lastEditedAt'] = edited
        self.env.update(TRUSTED_KIND='renovate', EVENT_HEAD_REF='renovate/github-actions',
                        LI219_EVENT_MODE='disabled')
        Path(self.env['GITHUB_EVENT_PATH']).write_text(json.dumps(
            {'number':23, 'repository':{'full_name':self.repo}, 'pull_request':self.pr}))
        self.save()

    def test_renovate_publishes_graphql_revision_without_a_rest_edit_field(self):
        for edited in (None, '2026-10-06T23:59:00Z'):
            with self.subTest(edited=edited):
                self.setUp()
                self.configure_renovate(edited)
                self.assertNotIn('last_edited_at', self.pr)
                self.capture()
                self.publish()
                summary = json.loads(self.data['check']['output']['summary'])
                self.assertEqual(13, len(summary))
                self.assertEqual(edited, summary['pull_request_last_edited_at'])
                self.assertEqual('Renovate title SHA-256: ' + hashlib.sha256(self.pr['title'].encode()).hexdigest(),
                                 self.data['check']['output']['text'])
                self.assertEqual('deterministic policy-bound Renovate exemption',
                                 summary['review_path'])
                self.assertIsNone(summary['review_id'])
                self.assertEqual('success', self.data['check']['conclusion'])
                self.assertGreaterEqual(self.data['metadata_reads'], 3)
                self.assertEqual(0, self.data.get('review_queries', 0))

    def prepare_renovate_handoff(self, edited):
        self.configure_renovate(edited)
        self.capture()
        self.publish()
        self.data['renovate_handoff'] = True
        self.save()
        required = yaml.safe_load((ROOT / '.github/workflows/supplementary-current-revision-required.yml').read_text())
        self.required_steps = {step['name']:step['run'] for job in required['jobs'].values()
                               for step in job.get('steps', []) if 'run' in step}
        self.steps['required-reader'] = self.required_steps['Prepare protected Renovate metadata reader']
        self.steps['required-handoff'] = self.required_steps['Validate one deterministic Renovate producer handoff']
        finalizer = self.required_steps['Rebind and finalize the protected result']
        self.steps['required-final-rebind'] = ('set -euo pipefail\nfinal_pr=' + shlex.quote(json.dumps(self.pr)) + '\n' +
            'if [ "${PRODUCER_KIND}" = renovate ]; then' +
            finalizer.split('if [ "${PRODUCER_KIND}" = renovate ]; then', 1)[1].split(
                "failure_stage='permanent-finalization'", 1)[0])
        self.env.update(PRODUCER_RUN_ID='77', PRODUCER_KIND='renovate')
        self.execute('required-reader')

    def test_renovate_producer_to_required_handoff_and_final_rebind(self):
        for edited in (None, '2026-10-06T23:59:00Z'):
            with self.subTest(edited=edited):
                self.setUp()
                self.prepare_renovate_handoff(edited)
                self.execute('required-handoff')
                outputs = dict(line.split('=', 1) for line in Path(self.env['GITHUB_OUTPUT']).read_text().splitlines())
                self.assertEqual(edited, json.loads(outputs['last_edited_at']))
                self.env.update(RENOVATE_LAST_EDITED_AT=outputs['last_edited_at'],
                                RENOVATE_TITLE_SHA256=outputs['title_sha256'],
                                RENOVATE_LABELS_SHA256=outputs['labels_sha256'])
                self.execute('required-final-rebind')
                self.data['metadata']['lastEditedAt'] = '2026-10-06T23:59:30Z'
                self.save()
                self.execute('required-final-rebind', False)
                self.assertEqual(0, self.data.get('review_queries', 0))

    def test_renovate_title_only_drift_rejects_handoff_and_final_rebind(self):
        for edited in (None, '2026-10-06T23:59:00Z'):
            for stage in ('required-handoff', 'required-final-rebind'):
                with self.subTest(edited=edited, stage=stage):
                    self.setUp()
                    self.prepare_renovate_handoff(edited)
                    if stage == 'required-final-rebind':
                        self.execute('required-handoff')
                        outputs = dict(line.split('=', 1) for line in Path(self.env['GITHUB_OUTPUT']).read_text().splitlines())
                        self.env.update(RENOVATE_LAST_EDITED_AT=outputs['last_edited_at'],
                                        RENOVATE_TITLE_SHA256=outputs['title_sha256'],
                                        RENOVATE_LABELS_SHA256=outputs['labels_sha256'])
                    old_pr = shlex.quote(json.dumps(self.pr))
                    self.pr['title'] = 'Renamed Renovate pull request'
                    self.data['metadata']['title'] = self.pr['title']
                    self.steps['required-final-rebind'] = self.steps['required-final-rebind'].replace(
                        'final_pr=' + old_pr, 'final_pr=' + shlex.quote(json.dumps(self.pr)), 1)
                    self.save()
                    self.execute(stage, False)
                    self.assertEqual(edited, self.data['metadata']['lastEditedAt'])
                    self.assertEqual(0, self.data.get('review_queries', 0))

    def test_renovate_handoff_rejects_missing_or_malformed_native_title_binding(self):
        for text in (None, '', 'Renovate title SHA-256: ' + '0' * 64, {}):
            with self.subTest(text=text):
                self.setUp()
                self.prepare_renovate_handoff(None)
                if text is None:
                    del self.data['check']['output']['text']
                else:
                    self.data['check']['output']['text'] = text
                self.save()
                self.execute('required-handoff', False)

    def test_renovate_existing_check_receives_the_bound_title_hash(self):
        for prior_text in (None, 'Renovate title SHA-256: ' + '0' * 64):
            with self.subTest(prior_text=prior_text):
                self.setUp()
                self.configure_renovate()
                self.capture()
                self.publish()
                if prior_text is None:
                    del self.data['check']['output']['text']
                else:
                    self.data['check']['output']['text'] = prior_text
                self.save()
                self.publish()
                self.assertEqual('success', self.data['check']['conclusion'])
                self.assertEqual('Renovate title SHA-256: ' + hashlib.sha256(self.pr['title'].encode()).hexdigest(),
                                 self.data['check']['output']['text'])
                self.assertEqual(1, self.data['writes'].count('POST'))
                self.assertEqual(0, self.data.get('review_queries', 0))

    def test_renovate_required_handoff_rejects_invalid_drifting_or_missing_metadata(self):
        for edited in ('invalid', False, {}, '2026-10-07T00:01:00Z', 'missing', '2026-10-06T23:59:30Z'):
            with self.subTest(edited=edited):
                self.setUp()
                self.prepare_renovate_handoff('2026-10-06T23:59:00Z')
                self.data['metadata']['lastEditedAt'] = edited
                if edited == 'missing':
                    del self.data['metadata']['lastEditedAt']
                self.save()
                self.execute('required-handoff', False)
                self.assertNotIn('verified=true', Path(self.env['GITHUB_OUTPUT']).read_text())

    def test_renovate_rejects_invalid_or_missing_graphql_revision(self):
        for edited in ('invalid', False, [], {}, '2026-10-07T00:01:00Z', 'missing'):
            with self.subTest(edited=edited):
                self.setUp()
                self.configure_renovate(edited)
                if edited == 'missing':
                    del self.data['metadata']['lastEditedAt']
                    self.save()
                self.capture(False)
                self.assertEqual([], self.data['writes'])

    def test_renovate_metadata_drift_rejects_or_revokes_publication(self):
        for phase in ('before', 'after_post', 'after_promotion'):
            with self.subTest(phase=phase):
                self.setUp()
                self.configure_renovate()
                self.capture()
                if phase == 'before':
                    self.data['metadata']['lastEditedAt'] = '2026-10-07T00:01:00Z'
                else:
                    self.data['drift_' + phase] = True
                self.save()
                self.publish(False)
                if phase == 'before':
                    self.assertEqual([], self.data['writes'])
                else:
                    self.assertEqual('failure', self.data['check']['conclusion'])

    def verify(self, succeeds=True):
        return self.execute('Verify current Copilot review and resolved findings', succeeds)

    def publish(self, succeeds=True):
        return self.execute('Publish bound neutral result', succeeds)

    def producer_to_receiver(self):
        outcome = {'summary': None, 'sealed': False, 'reruns': 0, 'received': False}
        captured = self.execute('Bind Copilot input metadata revision', succeeds=None)
        if captured.returncode != 0:
            return outcome
        # Match Actions step ordering: a failed verifier cannot publish.
        verified = self.execute('Verify current Copilot review and resolved findings', succeeds=None)
        if verified.returncode != 0:
            return outcome
        self.publish()
        summary = self.data['check']['output']['summary']
        outcome['summary'] = summary
        fixture = native.NativeRetryTests(methodName='runTest')
        fixture.setUp()
        try:
            fixture.last_edited_at = self.data['metadata']['lastEditedAt']
            fixture.review['submitted_at'] = self.data['submitted']
            fixture.neutral['completed_at'] = self.data['check']['completed_at']
            fixture.neutral['output']['summary'] = summary
            fixture.prime()
            outcome['sealed'] = 'li259/99/seed.json' in fixture.snapshots[fixture.oid]
            self.assertEqual('dispatched', fixture.recover())
            outcome['reruns'] = len(fixture.effects)
            fixture.receive()
            outcome['received'] = True
        finally:
            fixture.doCleanups()
        return outcome

    def test_equal_metadata_and_review_timestamp_cannot_enter_retry_pipeline(self):
        self.data['metadata']['lastEditedAt'] = self.data['submitted']
        self.save()
        self.assertEqual({'summary': None, 'sealed': False, 'reruns': 0, 'received': False},
                         self.producer_to_receiver())
        self.assertEqual([], self.data['writes'])

    def set_timestamp_input(self, field, value):
        if field == 'event':
            event_path = Path(self.env['GITHUB_EVENT_PATH'])
            event = json.loads(event_path.read_text())
            event['pull_request']['updated_at'] = value
            event_path.write_text(json.dumps(event))
        elif field == 'metadata':
            self.data['metadata']['lastEditedAt'] = value
        else:
            self.data['submitted'] = value
        self.save()

    def test_impossible_calendar_event_cannot_enter_retry_pipeline(self):
        self.set_timestamp_input('event', '2026-00-01T00:00:00Z')
        self.assertEqual({'summary': None, 'sealed': False, 'reruns': 0, 'received': False},
                         self.producer_to_receiver())
        self.assertEqual([], self.data['writes'])

    def test_all_three_timestamps_reject_invalid_calendar_and_format_in_any_timezone(self):
        invalid = ('2026-00-01T00:00:00Z', '2026-13-01T00:00:00Z', '2026-01-00T00:00:00Z',
                   '2026-04-31T00:00:00Z', '2025-02-29T00:00:00Z', '2026-01-01T24:00:00Z',
                   '2026-01-01T00:60:00Z', '2026-01-01T00:00:60Z', '0000-01-01T00:00:00Z',
                   '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00.000Z')
        for timezone in ('UTC', 'America/Toronto'):
            for field in ('event', 'metadata', 'review'):
                for value in invalid:
                    with self.subTest(timezone=timezone, field=field, value=value):
                        self.setUp()
                        self.env['TZ'] = timezone
                        self.set_timestamp_input(field, value)
                        with self.assertRaises(ValueError):
                            native.RETRY.proof.epoch(value)
                        self.assertEqual({'summary': None, 'sealed': False, 'reruns': 0, 'received': False},
                                         self.producer_to_receiver())
                        self.assertEqual([], self.data['writes'])

    def test_valid_leap_day_and_summer_utc_survive_non_utc_host_timezone(self):
        for timezone in ('UTC', 'America/Toronto'):
            for day in ('2024-02-29', '2026-07-01'):
                with self.subTest(timezone=timezone, day=day):
                    self.setUp()
                    self.env['TZ'] = timezone
                    self.set_timestamp_input('event', day + 'T12:00:00Z')
                    self.set_timestamp_input('metadata', day + 'T11:59:59Z')
                    self.set_timestamp_input('review', day + 'T12:00:00Z')
                    outcome = self.producer_to_receiver()
                    self.assertEqual(day + 'T11:59:59Z',
                                     json.loads(outcome['summary'])['pull_request_last_edited_at'])
                    self.assertTrue(outcome['sealed'])
                    self.assertEqual(1, outcome['reruns'])
                    self.assertTrue(outcome['received'])

    def test_real_producer_summary_is_accepted_by_native_seal_and_receiver(self):
        for edited in (None, '2026-10-06T23:59:00Z', '2026-10-06T23:59:59Z'):
            with self.subTest(revision=edited):
                self.setUp()
                self.data['metadata']['lastEditedAt'] = edited
                self.save()
                outcome = self.producer_to_receiver()
                self.assertEqual(edited, json.loads(outcome['summary'])['pull_request_last_edited_at'])
                self.assertTrue(outcome['sealed'])
                self.assertEqual(1, outcome['reruns'])
                self.assertTrue(outcome['received'])
                self.assertEqual(['POST','PATCH','PATCH'], self.data['writes'])

    def test_actual_producer_summary_passes_promotion_without_rewriting_evidence(self):
        for edited in (None, '2026-10-07T00:03:59Z'):
            with self.subTest(edited=edited):
                self.setUp()
                self.data['metadata']['lastEditedAt'] = edited
                self.data['submitted'] = '2026-10-07T00:04:00Z'
                self.set_timestamp_input('event', '2026-10-07T00:04:00Z')
                self.save()
                binary = self.tmp/'bin'/'date'
                binary.write_text("#!/bin/sh\nprintf '2026-10-07T00:04:30Z\n'\n")
                binary.chmod(0o755)
                self.capture()
                self.verify()
                self.publish()
                raw = self.data['check']['output']['summary']
                self.assertEqual(9, len(json.loads(raw)))
                # Adapt only native fixtures to this real producer's tuple;
                # its emitted summary and check are passed through unchanged.
                def bound(value):
                    if isinstance(value, dict):
                        return {k: bound(v) for k, v in value.items()}
                    if isinstance(value, list):
                        return [bound(v) for v in value]
                    if type(value) is int:
                        return {17:23, 88:77}.get(value, value)
                    if isinstance(value, str):
                        return (value.replace(promotion.BASE, self.base).replace(promotion.HEAD, self.head)
                                .replace('5'*40, self.base).replace('lightning-it/example', self.repo)
                                .replace('/runs/88', '/runs/77').replace('/pulls/17', '/pulls/23')
                                .replace('fix/exact-ingress', 'fix/test').replace('2026-09-27', '2026-10-07')
                                .replace('example', '.github'))
                    return value
                for associated in (True, False):
                    native_run = promotion.producer_run()
                    if not associated:
                        native_run['pull_requests'] = []
                    delegate = promotion.evidence_api(native_run)
                    def api(args):
                        translated = [v.replace(self.repo, 'lightning-it/example')
                                      .replace('/runs/77', '/runs/88').replace('/pulls/23', '/pulls/17')
                                      .replace('/compare/'+self.base, '/compare/'+'5'*40) for v in args]
                        result = bound(delegate(translated))
                        if args[:2] == ['api','graphql']:
                            result['data']['repository']['pullRequest']['lastEditedAt'] = edited
                        return result
                    with mock.patch.object(promotion.MODULE, 'gh_json', side_effect=api):
                        accepted = promotion.MODULE.bound_review_check(
                            [{'check_runs':[self.data['check']]}], repository=self.repo,
                            pull=bound(promotion.ingress_pull()), pull_number=23,
                            base_sha=self.base, head_sha=self.head)
                    self.assertEqual(promotion.MODULE.digest(json.loads(raw)), accepted["summary_sha256"])
                    self.assertEqual(0, accepted["historical_findings_count"])

    def test_capture_rejects_missing_revision_and_event_input_drift(self):
        for field, value in (('lastEditedAt','missing'),('lastEditedAt','2026-10-07T00:01:00Z'),
                             ('lastEditedAt','invalid'),('lastEditedAt',False),
                             ('headRepository',{'nameWithOwner':'untrusted/fork'}),
                             ('number',24),('title','Edited'),('body','Edited'),
                             ('headRefOid','e'*40),('baseRefOid','e'*40)):
            with self.subTest(field=field,value=value):
                self.setUp()
                if value == 'missing':
                    del self.data['metadata'][field]
                else:
                    self.data['metadata'][field] = value
                self.save()
                self.capture(False)
                self.assertEqual([], self.data['writes'])

    def test_edit_revert_after_capture_and_during_review_rejects_before_publication(self):
        for during in (False,True):
            with self.subTest(during_review=during):
                self.setUp()
                self.capture()
                if during:
                    self.data['drift_during_review'] = True
                else:
                    self.data['metadata']['lastEditedAt'] = '2026-10-07T00:01:00Z'
                self.save()
                self.verify(False)
                self.assertEqual([], self.data['writes'])

    def test_review_predating_bound_edit_is_not_accepted(self):
        self.data['metadata']['lastEditedAt'] = '2026-10-06T23:59:00Z'
        self.data['submitted'] = '2026-10-06T23:58:59Z'
        self.save()
        self.capture()
        self.verify(False)
        self.assertEqual([], self.data['writes'])

    def test_edit_revert_immediately_before_post_or_patch_never_writes(self):
        for existing in (False,True):
            with self.subTest(existing_check=existing):
                self.setUp()
                self.capture()
                self.verify()
                if existing:
                    self.publish()
                self.data['writes'] = []
                self.data['drift_on_read'] = self.data['metadata_reads'] + 2
                self.save()
                self.publish(False)
                self.assertEqual([], self.data['writes'])

    def test_edit_revert_after_post_blocks_followup_patch_and_success(self):
        self.capture()
        self.verify()
        self.data['drift_after_post'] = True
        self.save()
        self.publish(False)
        self.assertEqual(['POST'], self.data['writes'])
        self.assertEqual('failure', self.data['check']['conclusion'])

    def test_drift_during_success_promotion_revokes_the_exact_owned_result(self):
        self.capture()
        self.verify()
        self.data['drift_after_promotion'] = True
        self.save()
        self.publish(False)
        self.assertEqual('failure', self.data['check']['conclusion'])
        self.assertEqual(['failure', None, 'success', 'failure'], self.data['write_conclusions'])

    def test_unknown_create_is_resolved_only_by_exact_readback(self):
        for outcome in ('materialized', 'absent', 'ambiguous'):
            with self.subTest(outcome=outcome):
                self.setUp()
                self.capture()
                self.verify()
                self.data['unknown_post'] = outcome
                self.save()
                self.publish(outcome == 'materialized')
                self.assertEqual(1, self.data['writes'].count('POST'))
                if outcome == 'materialized':
                    self.assertEqual('success', self.data['check']['conclusion'])
                    self.assertEqual(['POST', 'PATCH', 'PATCH'], self.data['writes'])
                else:
                    self.assertEqual(['POST'], self.data['writes'])
                # A later authorized verification attempt never retries the create.
                self.env['GITHUB_RUN_ATTEMPT'] = '2'
                self.publish(outcome == 'materialized')
                self.assertEqual(1, self.data['writes'].count('POST'))

    def test_pending_owned_result_can_resume_without_new_post(self):
        self.capture()
        self.verify()
        self.data['drift_after_post'] = True
        self.save()
        self.publish(False)
        self.data['drift_after_post'] = False
        self.data['metadata']['lastEditedAt'] = None
        self.save()
        self.env['GITHUB_RUN_ATTEMPT'] = '2'
        self.publish()
        self.assertEqual(1, self.data['writes'].count('POST'))
        self.assertEqual('success', self.data['check']['conclusion'])

    def test_attempt_two_can_create_only_when_native_publisher_was_skipped(self):
        self.capture()
        self.verify()
        self.env['GITHUB_RUN_ATTEMPT'] = '2'
        self.data['previous_publish'] = 'skipped'
        self.save()
        self.publish()
        self.assertEqual(1, self.data['writes'].count('POST'))

    def test_unknown_success_patch_uses_readback_without_repeating_write(self):
        self.capture()
        self.verify()
        self.data['unknown_promotion'] = True
        self.save()
        self.publish()
        self.assertEqual(['POST', 'PATCH', 'PATCH'], self.data['writes'])
        self.assertEqual('success', self.data['check']['conclusion'])

    def test_all_run_blocks_stay_below_actionlint_pipe_guard(self):
        for job in self.workflow['jobs'].values():
            for step in job.get('steps',[]):
                self.assertLess(len(step.get('run','').encode()), 64500, step.get('name'))


if __name__ == '__main__':
    unittest.main()
