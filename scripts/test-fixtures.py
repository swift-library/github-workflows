#!/usr/bin/env python3
"""Exercise real commands and assert that each negative fixture fails its intended job."""

import argparse
import importlib.machinery
import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys

from swift_package_config import load, matrices

ROOT = Path(__file__).resolve().parents[1]
loader = importlib.machinery.SourceFileLoader('validation', str(ROOT / 'scripts/run-validation.py'))
spec = importlib.util.spec_from_loader(loader.name, loader)
validation = importlib.util.module_from_spec(spec)
loader.exec_module(validation)
CASES = {
    'format': ('format', '[Spacing]'),
    'test': ('compiler', 'Incorrect greeting'),
    'release-build': ('compiler', 'Release build fixture'),
    'linux': ('linux', 'Linux fixture'),
    'apple-build': ('apple', 'Apple build fixture'),
    'docs': ('docs', 'missingSymbol'),
    'command': ('commands', None),
}


def exercise(name, job, *, failure=None):
    destination = ROOT / '.build/fixture-tests' / name
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(ROOT / 'fixtures' / name, destination, ignore=shutil.ignore_patterns('.build', '.swiftpm'))
    log = destination / '.build/execution.log'
    log.parent.mkdir(parents=True, exist_ok=True)
    config = load(destination)
    entry = matrices(config)[job][0]
    command = [sys.executable, str(ROOT / 'scripts/run-validation.py'), job, '--root', str(destination)]
    with log.open('w') as stream:
        result = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT)
    text = log.read_text()
    if failure is None:
        if result.returncode:
            raise ValueError(f'{name}/{job} unexpectedly failed:\n{text}')
    elif result.returncode == 0 or (failure and failure not in text):
        raise ValueError(f'{name}/{job} did not fail for its intended reason:\n{text}')
    print(f'PASS {name}/{job}: ' + ('expected failure' if failure is not None else 'success'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('group', choices=('macos', 'linux', 'apple', 'demo'))
    args = parser.parse_args()
    if args.group == 'demo':
        print('EXPECTED-UNAVAILABLE: pin the recording-only presentation action before running demo fixtures')
        return 77
    jobs = {'macos': ['format', 'compiler', 'docs', 'commands'], 'linux': ['linux'], 'apple': ['apple']}[args.group]
    for job in jobs:
        exercise('passing', job)
    if 'docs' in jobs:
        exercise('docs-multiple-targets', 'docs')
    if 'apple' in jobs:
        exercise('apple-plugin', 'apple')
    for name, (job, marker) in CASES.items():
        if job in jobs:
            exercise(name, job, failure=marker or '')
    return 0


if __name__ == '__main__':
    sys.exit(main())
