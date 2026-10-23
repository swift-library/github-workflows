#!/usr/bin/env python3
"""Exercise real commands and assert that each negative fixture fails its intended job."""

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
CASES = {
    'format': ('format', '[Spacing]'),
    'test': ('compiler', 'Incorrect greeting'),
    'release-build': ('compiler', 'Release build fixture'),
    'linux': ('linux', 'Linux fixture'),
    'apple-build': ('apple', 'Apple build fixture'),
    'docs': ('docs', 'missingSymbol'),
    'command': ('commands', None),
    'demo-drift': ('demo', 'recording.json: changed step 1: fixture-cli'),
}


def exercise(name, job, *, failure=None, toolchain=None):
    destination = ROOT / '.build/fixture-tests' / name
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(ROOT / 'fixtures' / name, destination, ignore=shutil.ignore_patterns('.build', '.swiftpm'))
    log = destination / '.build/execution.log'
    log.parent.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, str(ROOT / 'scripts/run-validation.py'), job, '--root', str(destination)]
    environment = dict(os.environ)
    if job == 'demo':
        environment.update(GITHUB_OUTPUT=str(log.parent / 'outputs'), GITHUB_PATH=str(log.parent / 'path'))
    with log.open('w') as stream:
        result = subprocess.run(command, env=environment, stdout=stream, stderr=subprocess.STDOUT)
        if job == 'demo':
            if result.returncode:
                raise ValueError(f'{name}/demo build unexpectedly failed:\n{log.read_text()}')
            outputs = dict(line.split('=', 1) for line in Path(environment['GITHUB_OUTPUT']).read_text().splitlines())
            result = subprocess.run(['node', str(toolchain / 'src/cli.ts'), 'terminal', 'check', '--recording-only',
                                     '--assets', outputs['demo_assets'], '--executable', outputs['demo_executable']],
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            stream.write(result.stdout)
    text = result.stdout if job == 'demo' else log.read_text()
    if failure is None:
        if result.returncode:
            raise ValueError(f'{name}/{job} unexpectedly failed:\n{text}')
    elif (result.returncode == 0 or (failure and failure not in text)
          or (job == 'demo' and (result.returncode != 1
              or f'--- {outputs["demo_assets"]}/recording.json\n+++ regenerated/' not in text))):
        raise ValueError(f'{name}/{job} did not fail for its intended reason:\n{text}')
    print(f'PASS {name}/{job}: ' + ('expected failure' if failure is not None else 'success'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('group', choices=('macos', 'linux', 'apple', 'demo'))
    parser.add_argument('--toolchain', type=Path, help='Installed presentation scripts directory at the demo action revision')
    args = parser.parse_args()
    if args.group == 'demo':
        if args.toolchain is None or not (args.toolchain / 'src/cli.ts').is_file():
            parser.error('demo requires --toolchain with src/cli.ts')
        args.toolchain = args.toolchain.resolve()
    jobs = {'macos': ['format', 'compiler', 'docs', 'commands'], 'linux': ['linux'],
            'apple': ['apple'], 'demo': ['demo']}[args.group]
    for job in jobs:
        exercise('passing', job, toolchain=args.toolchain)
    if 'docs' in jobs:
        exercise('docs-multiple-targets', 'docs')
    if 'apple' in jobs:
        exercise('apple-plugin', 'apple')
    for name, (job, marker) in CASES.items():
        if job in jobs:
            exercise(name, job, failure=marker or '', toolchain=args.toolchain)
    return 0


if __name__ == '__main__':
    sys.exit(main())
