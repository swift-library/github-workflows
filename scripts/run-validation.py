#!/usr/bin/env python3
"""Execute one declared validation job in the member checkout."""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from swift_package_config import inside, load, matrices

XCODEBUILD = ['xcodebuild', '-skipPackagePluginValidation', '-skipMacroValidation']


def run(command, cwd, environment, *, capture=False):
    print('+ ' + ' '.join(map(str, command)), flush=True)
    return subprocess.run(list(map(str, command)), cwd=cwd, env=environment, check=True,
                          text=True, stdout=subprocess.PIPE if capture else None).stdout


def swift_flags(config, traits=None):
    flags = []
    if 'build_system' in config:
        flags += ['--build-system', config['build_system']]
    if traits is not None:
        flags += ['--traits', ','.join(traits)] if traits else ['--disable-default-traits']
    return flags


def simulator(entry, root, environment):
    platform = entry['platform']
    sdk = {'iOS': 'iphonesimulator', 'tvOS': 'appletvsimulator',
           'watchOS': 'watchsimulator', 'visionOS': 'xrsimulator'}[platform]
    expected = run(['xcrun', '--sdk', sdk, '--show-sdk-version'], root, environment, capture=True).strip()
    run([*XCODEBUILD, '-downloadPlatform', platform], root, environment)
    inventory = json.loads(run(['xcrun', 'simctl', 'list', '-j'], root, environment, capture=True))
    runtimes = [item for item in inventory['runtimes'] if item.get('isAvailable')
                and item['name'].startswith(platform + ' ') and item['version'] == expected]
    if not runtimes:
        raise ValueError('No available simulator runtime matching ' + platform + ' ' + expected)
    runtime = runtimes[-1]
    family = {'iOS': 'iPhone', 'tvOS': 'Apple TV', 'watchOS': 'Apple Watch', 'visionOS': 'Apple Vision'}[platform]
    devices = [item for item in runtime.get('supportedDeviceTypes', []) if item['name'].startswith(family)]
    if not devices:
        raise ValueError('No matching simulator device type for ' + platform)
    return run(['xcrun', 'simctl', 'create', 'shared-validation', devices[-1]['identifier'],
                runtime['identifier']], root, environment, capture=True).strip()


def prepare_demo(root, script):
    assets = root / '.build/demo'
    if assets.exists():
        shutil.rmtree(assets)
    assets.mkdir(parents=True)
    shutil.copyfile(script, assets / 'script.yml')
    shutil.copyfile(script.parent / 'recording.json', assets / 'recording.json')
    fixture = script.parent / 'fixture'
    if fixture.exists():
        shutil.copytree(fixture, assets / 'fixture', symlinks=True)
    return assets


def execute(root, job, entry, config=None):
    root = Path(root).resolve()
    config = config or load(root)
    package = inside(root, config.get('package_directory', '.'))
    environment = {**os.environ, **config.get('environment', {})}
    traits = config.get('traits', [None])
    configurations = config.get('test_configurations', ['debug'])
    if job in {'compiler', 'linux'}:
        for trait_set in traits:
            flags = swift_flags(config, trait_set)
            for configuration in configurations:
                command = ['swift', 'test', '-c', configuration, *flags]
                if job == 'linux':
                    command = ['docker', 'run', '--rm', '-v', str(root) + ':/workspace',
                               '-w', '/workspace/' + config.get('package_directory', '.'),
                               *[value for key in config.get('environment', {}) for value in ('-e', key)],
                               entry['image'], *command]
                run(command, package, environment)
            if job == 'compiler':
                run(['swift', 'build', '-c', 'release', *flags], package, environment)
    elif job == 'format':
        paths = [inside(package, path) for path in config.get('format', {}).get(
            'paths', ['Package.swift', 'Sources', 'Tests'])]
        for path in paths:
            if not path.exists():
                raise ValueError('Formatting path does not exist: ' + str(path))
        run(['swift', 'format', 'lint', '--strict', '--recursive', '--configuration',
             str(root / '.swift-format'), '--', *paths], package, environment)
    elif job == 'apple':
        command = [*XCODEBUILD, '-scheme', entry['scheme'], '-derivedDataPath', str(package / '.build/apple'),
                   '-destination', 'generic/platform=' + entry['platform'], 'CODE_SIGNING_ALLOWED=NO']
        run([*command, 'build'], package, environment)
        if entry.get('test', False):
            device = simulator(entry, package, environment)
            try:
                run(['xcrun', 'simctl', 'bootstatus', device, '-b'], package, environment)
                run([*XCODEBUILD, '-scheme', entry['scheme'], '-destination', 'id=' + device,
                     '-derivedDataPath', str(package / '.build/apple'), 'test'], package, environment)
            finally:
                run(['xcrun', 'simctl', 'delete', device], package, environment)
    elif job == 'docs':
        description = json.loads(run(['swift', 'package', 'describe', '--type', 'json'],
                                     package, environment, capture=True))
        modules = {target['name']: target['c99name'] for target in description['targets']}
        for target in config['docs']['targets']:
            output = package / '.build/docc' / target
            all_symbols = output / 'all-symbols'
            all_symbols.mkdir(parents=True, exist_ok=True)
            run(['swift', 'build', '--target', target, *swift_flags(config), '-Xswiftc', '-emit-symbol-graph',
                 '-Xswiftc', '-emit-symbol-graph-dir', '-Xswiftc', str(all_symbols)], package, environment)
            # SwiftPM also emits dependency graphs; each DocC conversion owns one module.
            symbols = output / 'symbols'
            if symbols.exists():
                shutil.rmtree(symbols)
            symbols.mkdir()
            module = modules[target]
            for graph in [all_symbols / (module + '.symbols.json'), *all_symbols.glob(module + '@*.symbols.json')]:
                shutil.copyfile(graph, symbols / graph.name)
            catalogs = list((package / 'Sources' / target).glob('*.docc'))
            if len(catalogs) > 1:
                raise ValueError('Expected at most one documentation catalog per target')
            run(['xcrun', 'docc', 'convert', *catalogs, '--additional-symbol-graph-dir', symbols,
                 '--fallback-display-name', target, '--fallback-bundle-identifier', target,
                 '--fallback-bundle-version', '0.0.0', '--warnings-as-errors',
                 '--output-path', output / (target + '.doccarchive')], package, environment)
    elif job == 'demo':
        run(['swift', 'build', '-c', 'release', '--product', config['demo']['product'], *swift_flags(config)], package, environment)
        binary = run(['swift', 'build', '-c', 'release', '--show-bin-path', *swift_flags(config)], package, environment, capture=True).strip()
        script = inside(root, config['demo'].get('script', '.github/assets/terminal/script.yml'))
        assets = prepare_demo(root, script)
        with open(os.environ['GITHUB_OUTPUT'], 'a') as stream:
            print('demo_assets=' + str(assets), file=stream)
            print('demo_executable=' + str(Path(binary) / config['demo']['product']), file=stream)
        with open(os.environ['GITHUB_PATH'], 'a') as stream:
            print(binary, file=stream)
    elif job == 'commands':
        run(['bash', '-euo', 'pipefail', '-c', entry['run']], root, environment)
    else:
        raise ValueError('Unknown validation job: ' + job)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('job', choices=('compiler', 'format', 'linux', 'apple', 'docs', 'demo', 'commands'))
    parser.add_argument('--root', type=Path, default=Path.cwd())
    parser.add_argument('--entry', default='{}')
    args = parser.parse_args()
    config = load(args.root)
    entry = json.loads(args.entry)
    if not entry:
        entry = matrices(config)[args.job][0]
    execute(args.root, args.job, entry, config)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        sys.exit(str(error))
