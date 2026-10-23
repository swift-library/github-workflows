#!/usr/bin/env python3
"""Check that the selected compiler matches the member's version declaration."""

import json
import os
import re
import subprocess
from pathlib import Path

from swift_package_config import inside, load, read_json, version


def verify(entry, output, minimum=None):
    match = re.search(r'Swift version ([0-9]+\.[0-9]+(?:\.[0-9]+)?)', output)
    if not match:
        raise ValueError('Unable to identify the selected Swift compiler')
    actual = version(match[1])
    expected = entry.get('swift')
    if expected and actual[:len(expected.split('.'))] != version(expected)[:len(expected.split('.'))]:
        raise ValueError(f'Selected Swift {match[1]} does not match declared Swift {expected}')
    if minimum and actual < version(minimum):
        raise ValueError('Selected Swift is below minimum_swift')
    return actual


if __name__ == '__main__':
    root = Path('member')
    release = root / '.github/release.json'
    minimum = read_json(release)['minimum_swift'] if release.exists() else None
    config = load(root)
    environment = {**os.environ, **config.get('environment', {})}
    output = subprocess.check_output(['swift', '--version'], text=True, env=environment,
                                     cwd=inside(root, config.get('package_directory', '.')))
    entry = json.loads(os.environ['ENTRY'])
    actual = verify(entry, output, minimum)
    if os.environ.get('COMPILER_RECORD'):
        record = Path(os.environ['COMPILER_RECORD'])
        record.parent.mkdir(parents=True, exist_ok=True)
        record.write_text(json.dumps({'name': entry['name'], 'version': list(actual)}) + '\n')
