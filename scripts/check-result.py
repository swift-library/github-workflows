#!/usr/bin/env python3
"""Require success for declared jobs and verify the actual minimum compiler."""

import io
import json
import os
import subprocess
import sys
import zipfile


def failures(needs, declared):
    return [name for name, job in needs.items()
            if job['result'] != 'success' and not (job['result'] == 'skipped' and name not in declared)]


def verify_minimum(records, names, minimum):
    observed = [record['name'] for record in records]
    if sorted(observed) != sorted(names):
        raise ValueError('Compiler version reports must cover every declared compiler exactly once')
    versions = [record['version'] for record in records]
    if any(not isinstance(v, list) or len(v) != 3 or any(type(part) is not int or part < 0 for part in v) for v in versions):
        raise ValueError('Invalid compiler version report')
    expected = tuple(map(int, minimum.split('.')))
    actual = min(map(tuple, versions))
    if actual[:len(expected)] != expected:
        raise ValueError('minimum_swift must equal the oldest tested compiler')


def compiler_records(repository, run_id, execution):
    pages = json.loads(subprocess.check_output(['gh', 'api', f'repos/{repository}/actions/runs/{run_id}/artifacts?per_page=100', '--paginate', '--slurp'], text=True))
    artifacts = [item for page in pages for item in page['artifacts']
                 if item['name'].startswith('compiler-' + execution + '-')]
    records = []
    for artifact in artifacts:
        data = subprocess.check_output(['gh', 'api', f'repos/{repository}/actions/artifacts/{artifact["id"]}/zip'])
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            files = archive.infolist()
            if len(files) != 1 or files[0].file_size > 4096:
                raise ValueError('Invalid compiler version archive')
            records.append(json.loads(archive.read(files[0])))
    return records


if __name__ == '__main__':
    failed = failures(json.loads(os.environ['NEEDS']), json.loads(os.environ['DECLARED']))
    if failed:
        sys.exit('Validation did not succeed: ' + ', '.join(failed))
    if os.environ.get('MINIMUM_SWIFT'):
        records = compiler_records(os.environ['GITHUB_REPOSITORY'], os.environ['GITHUB_RUN_ID'], os.environ['EXECUTION'])
        verify_minimum(records, [entry['name'] for entry in json.loads(os.environ['COMPILERS'])['include']], os.environ['MINIMUM_SWIFT'])
    print('All declared validation jobs succeeded')
