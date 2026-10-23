#!/usr/bin/env python3
"""Validate a member declaration and emit the shared workflow's job matrices."""

import argparse
import json
from pathlib import Path
import re
import sys
import uuid

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
JOBS = ('compiler', 'format', 'linux', 'apple', 'docs', 'demo', 'commands')


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('Duplicate configuration key: ' + key)
        value[key] = item
    return value


def read_json(path):
    return json.loads(Path(path).read_text(), object_pairs_hook=unique_object)


def version(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]+\.[0-9]+(?:\.[0-9]+)?', value):
        raise ValueError('Expected a Swift major.minor or major.minor.patch version')
    return tuple(map(int, value.split('.'))) + (0,) * (3 - len(value.split('.')))



def inside(root, relative):
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError('Configuration path escapes the repository: ' + relative)
    return path


def validate(config, root=None):
    schema = read_json(ROOT / 'schemas/swift-package.schema.json')
    errors = sorted(Draft202012Validator(schema).iter_errors(config), key=lambda e: str(e.json_path))
    if errors:
        raise ValueError('; '.join(f'{e.json_path}: {e.message}' for e in errors))
    for entries in (config['compilers'], config.get('commands', []),
                    *config.get('platforms', {}).values()):
        names = [entry['name'] for entry in entries]
        if len(names) != len(set(names)):
            raise ValueError('Matrix names must be unique within each job')
    if root is not None:
        root = Path(root).resolve()
        package = inside(root, config.get('package_directory', '.'))
        for path in config.get('format', {}).get('paths', ['Package.swift', 'Sources', 'Tests']):
            inside(package, path)
        if 'demo' in config:
            inside(root, config['demo'].get('script', '.github/assets/terminal/script.yml'))
    return config


def load(root):
    root = Path(root).resolve()
    return validate(read_json(root / '.github/swift-package.json'), root)


def matrices(config):
    latest = config['compilers'][-1]
    default = {key: latest.get(key, '') for key in ('runner', 'xcode', 'swift')}
    result = {'compiler': config['compilers'], 'format': [{**default, 'name': 'format'}]}
    platforms = config.get('platforms', {})
    result['linux'] = platforms.get('linux', [])
    result['apple'] = [{**default, **entry} for entry in platforms.get('apple', [])]
    for job in ('docs', 'demo'):
        result[job] = [{**default, 'name': job, **config[job]}] if job in config else []
    result['commands'] = [{**default, **entry} for entry in config.get('commands', [])]
    # An explicit Xcode override uses that Xcode's bundled compiler unless the
    # compiler entry itself requested the supplemental toolchain.
    for job in ('apple', 'commands'):
        for original, entry in zip(platforms.get(job, []) if job == 'apple' else config.get(job, []), result[job]):
            if 'xcode' in original:
                entry['swift'] = ''
    return result


def outputs(config):
    result = {'timeout': config.get('timeout_minutes', 45),
              'declared': ['configure', *[job for job, entries in matrices(config).items() if entries]]}
    for job, entries in matrices(config).items():
        result[job] = {'include': entries}
        result[job + '_declared'] = bool(entries)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path.cwd())
    parser.add_argument('--github-output', type=Path)
    args = parser.parse_args()
    result = outputs(load(args.root))
    release = args.root / '.github/release.json'
    result['minimum'] = read_json(release)['minimum_swift'] if release.exists() else ''
    if release.exists():
        version(result['minimum'])
    result['execution'] = uuid.uuid4().hex
    if args.github_output:
        with args.github_output.open('a') as stream:
            for key, value in result.items():
                print(key + '=' + (value if isinstance(value, str) else json.dumps(value, separators=(',', ':'))), file=stream)
    else:
        print(json.dumps(result, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError) as error:
        sys.exit('Configuration: ' + str(error))
