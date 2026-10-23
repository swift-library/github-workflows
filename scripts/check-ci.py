#!/usr/bin/env python3
"""Resolve CI dependencies and require every CI job to succeed."""

import argparse
import json
import os
from pathlib import Path
import re


def check(needs):
    for name, result in needs.items():
        if result['result'] != 'success':
            raise ValueError(f'{name}: expected success, got {result["result"]}')


def demo_revision():
    workflow = Path(__file__).resolve().parents[1] / '.github/workflows/swift-package.yml'
    pins = re.findall(r'^\s*- uses: showxu/skills/skills/github-readme-design/scripts@(\S+)',
                      workflow.read_text(), re.MULTILINE)
    if len(pins) != 1 or not re.fullmatch(r'[0-9a-f]{40}', pins[0]) or int(pins[0], 16) == 0:
        raise ValueError('Expected one demo action pinned to a nonzero full SHA')
    return pins[0]


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--demo-revision', action='store_true', help='Print the demo action revision for fixture setup')
    args = parser.parse_args()
    if args.demo_revision:
        print(demo_revision())
    else:
        check(json.loads(os.environ['NEEDS']))
        print('All CI checks passed')
