#!/usr/bin/env python3
"""Read-only operator check for native approval holds and duplicate review deliveries.

This supplements mandatory repository gates; it never approves, reruns, reviews,
merges or deletes anything. Keep cross-repository output in the private operator
context. Default-branch callbacks are intentionally not filtered by PR head.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
from collections import defaultdict
from urllib.parse import urlencode

COPILOT = 'dynamic/agents/copilot-pull-request-reviewer'
METADATA = {'delivery-operations.yml', 'review-events.yml', 'copilot-review-refresh.yml',
            'review-event-reconcile.yml', 'review-request-continuation.yml',
            'codex-copilot-remediation.yml', 'current-revision-rerun.yml'}


def get(path):
    return json.loads(subprocess.check_output(['gh', 'api', '--method', 'GET', path]))


def timestamp(value):
    parsed = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('An explicit timezone is required')
    return parsed


def summarize(run):
    return {key: run.get(key) for key in
            ('id', 'path', 'event', 'status', 'conclusion', 'head_sha', 'run_attempt', 'html_url')}


def audit(api, repository, since):
    timestamp(since)
    runs, seen = [], set()
    for page in range(1, 11):
        query = urlencode({'created': '>=' + since, 'per_page': 100, 'page': page})
        response = api(f'repos/{repository}/actions/runs?{query}')
        rows = response['workflow_runs']
        for run in rows:
            if run['id'] in seen or timestamp(run['created_at']) < timestamp(since):
                raise ValueError('Native run inventory changed or escaped the time window')
            seen.add(run['id'])
        runs.extend(rows)
        if len(rows) < 100:
            if len(runs) != response['total_count']:
                raise ValueError('Native run inventory is incomplete; inspect before completion')
            break
    else:
        raise ValueError('Bounded inventory exceeded; inspect before completion')
    holds, active, deliveries = [], [], defaultdict(list)
    for run in runs:
        if run.get('conclusion') == 'action_required' or run.get('status') == 'waiting':
            holds.append(summarize(run))
        if (run.get('path', '').rsplit('/', 1)[-1] in METADATA
                and run.get('status') != 'completed'):
            active.append(summarize(run))
        if run.get('path') == COPILOT:
            deliveries[run['head_sha']].append(run)
    multiple = [summarize(run) for group in deliveries.values()
                if len(group) > 1 or any(r.get('run_attempt', 1) > 1 for r in group)
                for run in group]
    # A second native run is an inspection signal, not proof of a second bill.
    return {'repository': repository, 'since': since, 'head_filter_used': False,
            'approval_holds': holds, 'active_metadata': active,
            'review_deliveries_to_inspect': multiple,
            'auxiliary_clear': not (holds or active or multiple)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository', action='append', required=True)
    window = parser.add_mutually_exclusive_group(required=True)
    window.add_argument('--since', help='Inclusive ISO timestamp with timezone')
    window.add_argument('--pull', type=int, help='Use this PR creation time; one repository only')
    args = parser.parse_args()
    repos = list(dict.fromkeys(args.repository))
    if any(not re.fullmatch(r'lightning-it/[A-Za-z0-9_.-]+', repo) for repo in repos):
        parser.error('Only explicit Lightning IT repositories are supported')
    if args.pull is not None and (args.pull <= 0 or len(repos) != 1):
        parser.error('--pull needs one repository and a positive PR number')
    if os.environ.get('GITHUB_ACTIONS') == 'true' and any(
            repo != os.environ.get('GITHUB_REPOSITORY') for repo in repos):
        parser.error('Cross-repository output belongs in the private operator context')
    pull = get(f'repos/{repos[0]}/pulls/{args.pull}') if args.pull else None
    since = pull['created_at'] if pull else args.since
    results = [audit(get, repo, since) for repo in repos]
    if pull:
        current = get(f'repos/{repos[0]}/pulls/{args.pull}')
        def subject(value):
            return (value['state'], value['draft'], *[(value[side]['sha'], value[side]['ref'],
                    value[side]['repo']['id']) for side in ('head', 'base')])
        if subject(current) != subject(pull):
            raise ValueError('PR changed during observation; inspect the new state')
    print(json.dumps({'required_gates_replaced': False, 'results': results}))
    return 0 if all(result['auxiliary_clear'] for result in results) else 2


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, KeyError, subprocess.CalledProcessError) as error:
        print(json.dumps({'auxiliary_clear': False, 'error': type(error).__name__}))
        raise SystemExit(1) from None
