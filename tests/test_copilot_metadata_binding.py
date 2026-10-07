"""Execute the real producer steps and feed their summary to native recovery."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml
import test_native_verifier_retry as native

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
    d['writes'].append(method)
    if method == 'POST':
        d['check'] = {'id':79,'app':{'id':15368,'slug':'github-actions'},
                      'output':{},'details_url':None,'completed_at':'2026-10-07T00:00:00Z'}
    for key, value in fields.items():
        if key.startswith('output['):
            d['check']['output'][key[7:-1]] = value
        else:
            d['check'][key] = value
    result = d['check']
    if d.get('drift_after_post'):
        d['metadata']['lastEditedAt'] = '2026-10-07T00:01:00Z'
elif '/branches/' in route:
    result = {'commit':{'sha':d['base']}}
elif '/compare/' in route:
    result = {'status':'identical'}
elif '/actions/runs/' in route:
    result = {'event':'pull_request_target','name':'Current revision review gate',
        'path':'.github/workflows/copilot-review.yml','head_branch':'fix/test','head_sha':d['head'],
        'repository':{'full_name':d['repo']},'head_repository':{'full_name':d['repo']}}
elif '/pulls/' in route:
    result = d['pr']
elif '/commits/' in route:
    rows = [] if d['check'] is None else [d['check']]
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
                    'GITHUB_RUN_ID':'77','OWNER_RUN_ID':'77','EVENT_BASE':self.base,'EVENT_HEAD':self.head,
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
                self.assertEqual(['POST','PATCH'], self.data['writes'])

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

    def test_all_run_blocks_stay_below_actionlint_pipe_guard(self):
        for job in self.workflow['jobs'].values():
            for step in job.get('steps',[]):
                self.assertLess(len(step.get('run','').encode()), 64500, step.get('name'))


if __name__ == '__main__':
    unittest.main()
