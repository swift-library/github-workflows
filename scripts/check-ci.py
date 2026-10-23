#!/usr/bin/env python3
"""Accept negative workflow calls only when the intended rejection step failed."""

import json
import os
import subprocess
import sys

REJECTIONS = {
    'release-rejection': ('verify', 'Verify accepted release'),
    'organization-rejection': ('organization', 'Validate standard revision'),
}


def check(needs, jobs):
    for name, result in needs.items():
        expected = 'failure' if name in REJECTIONS else 'success'
        if result['result'] != expected:
            raise ValueError(f'{name}: expected {expected}, got {result["result"]}')
    for caller, (job_name, step_name) in REJECTIONS.items():
        matches = [job for job in jobs if job['name'] == caller + ' / ' + job_name]
        if len(matches) != 1:
            raise ValueError('Cannot identify rejection job: ' + caller)
        failed = [step['name'] for step in matches[0]['steps'] if step.get('conclusion') == 'failure']
        if failed != [step_name]:
            raise ValueError(f'{caller}: unexpected failure step {failed}')


if __name__ == '__main__':
    pages = json.loads(subprocess.check_output([
        'gh', 'api', f'repos/{os.environ["GITHUB_REPOSITORY"]}/actions/runs/{os.environ["GITHUB_RUN_ID"]}/attempts/{os.environ["GITHUB_RUN_ATTEMPT"]}/jobs?per_page=100',
        '--paginate', '--slurp'], text=True))
    check(json.loads(os.environ['NEEDS']), [job for page in pages for job in page['jobs']])
    print('All CI checks and expected rejection paths passed')
