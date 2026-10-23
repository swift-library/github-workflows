import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from test_organization import ROOT, load_script
sys.path.insert(0, str(ROOT / 'scripts'))
import swift_package_config as config
runner = load_script('validation', 'run-validation.py')
result = load_script('result', 'check-result.py')


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.value = {'compilers': [{'name': 'macos-swift-6.0', 'runner': 'macos-15', 'xcode': '16.2'},
                                    {'name': 'macos-swift-6.3', 'runner': 'macos-26', 'xcode': '26.6'}]}

    def test_minimal_defaults_and_latest_formatter(self):
        output = config.outputs(config.validate(self.value))
        self.assertEqual(output['timeout'], 45)
        self.assertEqual(output['declared'], ['configure', 'compiler', 'format'])
        self.assertEqual(output['format']['include'][0]['xcode'], '26.6')
        self.assertFalse(output['linux_declared'])
        self.assertEqual(output['linux'], {'include': []})

    def test_schema_rejects_unknown_and_invalid_values(self):
        for extra in ({'unknown': {}}, {'compilers': []}, {'timeout_minutes': True},
                      {'timeout_minutes': 0}, {'timeout_minutes': 361}, {'format': {'extra': []}},
                      {'platforms': {'linux': [{'name': 'linux', 'image': 'swift:latest'}]}},
                      {'platforms': {'apple': [{'name': 'mac', 'platform': 'macOS', 'scheme': 'X'}]}},
                      {'traits': [['default', 'default']]}, {'environment': {'KEY': 1}},
                      {'package_directory': '../outside'}, {'format': {'paths': ['/outside']}},
                      {'test_configurations': ['fast']}, {'build_system': 'other'}):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                config.validate({**self.value, **extra})

    def test_docs_traits_accepts_one_trait_set(self):
        for traits in ([], ['default'], ['Experimental', 'default']):
            with self.subTest(traits=traits):
                config.validate({**self.value, 'docs': {'targets': ['Fixture'], 'traits': traits}})
        for traits in ('Experimental', [['Experimental']], ['Feature', 'Feature'], ['--help'], [1]):
            with self.subTest(traits=traits), self.assertRaises(ValueError):
                config.validate({**self.value, 'docs': {'targets': ['Fixture'], 'traits': traits}})

    def test_all_options_and_runner_overrides(self):
        value = config.load(ROOT / 'fixtures/passing')
        value.update(test_configurations=['debug', 'release'], build_system='native',
                     traits=[['default'], ['Experimental', 'default'], []], environment={'KEY': 'value'},
                     timeout_minutes=360)
        value['commands'][0].update(runner='ubuntu-24.04', xcode='26.0.1')
        output = config.outputs(config.validate(value))
        self.assertEqual(len(output['declared']), 8)
        self.assertEqual(output['commands']['include'][0]['runner'], 'ubuntu-24.04')
        self.assertEqual(output['apple']['include'][0]['xcode'], '26.6')

    def test_every_fixture_schema_and_matrix(self):
        paths = list((ROOT / 'fixtures').glob('*/.github/swift-package.json'))
        self.assertEqual(len(paths), 11)
        declared_counts = {'docs-multiple-targets': 4, 'apple-plugin': 4}
        for path in paths:
            with self.subTest(fixture=path.parent.parent.name):
                self.assertEqual(len(config.outputs(config.load(path.parent.parent))['declared']),
                                 declared_counts.get(path.parent.parent.name, 8))
        config.load(ROOT)

    def test_repository_ci_runs_the_passing_demo(self):
        value = config.load(ROOT)
        self.assertTrue(config.outputs(value)['demo_declared'])
        self.assertEqual(value['demo']['product'], 'fixture-cli')
        self.assertEqual(value['demo']['script'], 'fixtures/passing/.github/assets/terminal/script.yml')

    def test_empty_release_minimum_fails_configuration(self):
        import subprocess
        output = ROOT / '.build/config-tests'
        output.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=output) as temporary:
            root = Path(temporary)
            (root / '.github').mkdir()
            (root / '.github/swift-package.json').write_text(json.dumps(self.value))
            (root / '.github/release.json').write_text('{"minimum_swift":""}')
            process = subprocess.run([sys.executable, str(ROOT / 'scripts/swift_package_config.py'), '--root', str(root)], capture_output=True, text=True)
            self.assertNotEqual(process.returncode, 0)
            self.assertIn('Expected a Swift', process.stderr)

    def test_duplicate_keys_and_names(self):
        with self.assertRaises(ValueError):
            json.loads('{"x": 1, "x": 2}', object_pairs_hook=config.unique_object)
        self.value['compilers'].append(self.value['compilers'][0])
        with self.assertRaises(ValueError):
            config.validate(self.value)

    def test_symlink_escape_and_arbitrary_compiler_labels(self):
        output = ROOT / '.build/config-tests'
        output.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=output) as temporary:
            root = Path(temporary)
            (root / '.github').mkdir()
            (root / '.github/release.json').write_text('{"minimum_swift":"6.0"}')
            config.validate(self.value, root)
            (root / '.github/release.json').write_text('{"minimum_swift":"6.1"}')
            config.validate(self.value, root)
            (root / 'outside').symlink_to(root.parent, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, 'escapes'):
                config.validate({**self.value, 'package_directory': 'outside'}, root)


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.root = ROOT / 'fixtures/passing'
        self.config = config.load(self.root)

    def test_format_paths_are_existing_package_paths_after_option_terminator(self):
        self.config['package_directory'] = 'Sources'
        self.config['format'] = {'paths': ['Fixture']}
        with patch.object(runner, 'run') as run:
            runner.execute(self.root, 'format', {}, self.config)
        self.assertEqual(run.call_args.args[0][-2:], ['--', self.root / 'Sources/Fixture'])

    def test_format_rejects_missing_option_and_escaping_paths_before_running(self):
        for path in ('--help', 'missing', '../outside'):
            with self.subTest(path=path), patch.object(runner, 'run') as run:
                self.config['format'] = {'paths': [path]}
                with self.assertRaisesRegex(ValueError, 'does not exist|escapes'):
                    runner.execute(self.root, 'format', {}, self.config)
                run.assert_not_called()

    def test_simulator_uses_an_installed_runtime_without_downloading(self):
        inventory = json.dumps({'runtimes': [{
            'isAvailable': True, 'name': 'iOS 26.5', 'version': '26.5',
            'identifier': 'com.apple.CoreSimulator.SimRuntime.iOS-26-5',
            'supportedDeviceTypes': [{'name': 'iPhone 17', 'identifier': 'iPhone-17'}]}]})

        def respond(command, cwd, environment, capture=False):
            if '--show-sdk-version' in command:
                return '26.5\n'
            if command[:3] == ['xcrun', 'simctl', 'list']:
                return inventory
            return 'device-id\n'

        with patch.object(runner, 'run', side_effect=respond) as run:
            device = runner.simulator({'platform': 'iOS'}, self.root, {})
        self.assertEqual(device, 'device-id')
        self.assertFalse(any('-downloadPlatform' in call.args[0] for call in run.call_args_list))

    def test_simulator_downloads_the_platform_only_when_no_runtime_matches(self):
        listings = iter([json.dumps({'runtimes': []}), json.dumps({'runtimes': [{
            'isAvailable': True, 'name': 'iOS 26.5', 'version': '26.5', 'identifier': 'runtime',
            'supportedDeviceTypes': [{'name': 'iPhone 17', 'identifier': 'iPhone-17'}]}]})])

        def respond(command, cwd, environment, capture=False):
            if '--show-sdk-version' in command:
                return '26.5\n'
            if command[:3] == ['xcrun', 'simctl', 'list']:
                return next(listings)
            return 'device-id\n'

        with patch.object(runner, 'run', side_effect=respond) as run:
            runner.simulator({'platform': 'iOS'}, self.root, {})
        downloads = [call.args[0] for call in run.call_args_list if '-downloadPlatform' in call.args[0]]
        self.assertEqual(len(downloads), 1)

    def test_compiler_runs_every_test_configuration_and_builds_every_trait(self):
        self.config.update(test_configurations=['debug', 'release'], traits=[['default'], ['Feature', 'default'], []], build_system='native', environment={'VALUE': 'declared'})
        with patch.object(runner, 'run') as run:
            runner.execute(self.root, 'compiler', {}, self.config)
        commands = [call.args[0] for call in run.call_args_list]
        self.assertEqual(len(commands), 9)
        self.assertEqual(sum(c[:2] == ['swift', 'test'] for c in commands), 6)
        self.assertTrue(all('--build-system' in c for c in commands))
        self.assertIn('Feature,default', commands[3])
        self.assertIn('--disable-default-traits', commands[-1])
        self.assertEqual(run.call_args.args[2]['VALUE'], 'declared')

    def test_linux_uses_digest_and_exports_environment(self):
        self.config['environment'] = {'CUSTOM': 'value'}
        entry = self.config['platforms']['linux'][0]
        with patch.object(runner, 'run') as run:
            runner.execute(self.root, 'linux', entry, self.config)
        command = run.call_args.args[0]
        self.assertEqual(command[:3], ['docker', 'run', '--rm'])
        self.assertIn(entry['image'], command)
        self.assertIn('CUSTOM', command)
        self.assertEqual(command[-4:], ['swift', 'test', '-c', 'debug'])

    def test_command_executes_in_checkout_not_package_subdirectory(self):
        self.config['package_directory'] = 'Sources'
        with patch.object(runner, 'run') as run:
            runner.execute(self.root, 'commands', {'run': 'scripts/check'}, self.config)
        self.assertEqual(run.call_args.args[1], self.root)
        self.assertEqual(run.call_args.args[0], ['bash', '-euo', 'pipefail', '-c', 'scripts/check'])

    def test_apple_cleanup_runs_when_tests_fail(self):
        entry = {**self.config['platforms']['apple'][0], 'test': True}
        import subprocess
        def execute(command, *args, **kwargs):
            if command[-1] == 'test':
                raise subprocess.CalledProcessError(1, command)
        with patch.object(runner, 'run', side_effect=execute) as run, patch.object(runner, 'simulator', return_value='device'):
            with self.assertRaises(subprocess.CalledProcessError):
                runner.execute(self.root, 'apple', entry, self.config)
        self.assertEqual(run.call_args.args[0], ['xcrun', 'simctl', 'delete', 'device'])

    def test_every_xcodebuild_skips_plugin_and_macro_validation(self):
        inventory = {'runtimes': [{
            'isAvailable': True, 'name': 'iOS 18.0', 'version': '18.0',
            'identifier': 'runtime',
            'supportedDeviceTypes': [{'name': 'iPhone 16', 'identifier': 'phone'}],
        }]}

        def execute(command, *args, **kwargs):
            if command[:2] == ['xcrun', '--sdk']:
                return '18.0\n'
            if command[:3] == ['xcrun', 'simctl', 'list']:
                return json.dumps(inventory)
            if command[:3] == ['xcrun', 'simctl', 'create']:
                return 'device\n'

        for tests in (False, True):
            with self.subTest(tests=tests), patch.object(runner, 'run', side_effect=execute) as run:
                entry = {**self.config['platforms']['apple'][0], 'test': tests}
                runner.execute(self.root, 'apple', entry, self.config)
                commands = [call.args[0] for call in run.call_args_list if call.args[0][0] == 'xcodebuild']
                self.assertEqual(len(commands), 2 if tests else 1)
                self.assertIn('generic/platform=iOS', commands[0])
                for command in commands:
                    self.assertIn('-skipPackagePluginValidation', command)
                    self.assertIn('-skipMacroValidation', command)

    def test_docs_converts_only_the_targets_own_symbol_graphs(self):
        parent = ROOT / '.build/config-tests'
        parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent) as directory:
            root = Path(directory)
            targets = ['Feature', 'FeatureCore', 'Hyphen-Feature']
            modules = {'Feature': 'Feature', 'FeatureCore': 'FeatureCore', 'Hyphen-Feature': 'Hyphen_Feature'}
            self.config['docs'] = {'targets': targets, 'traits': ['Experimental', 'default']}
            self.config['build_system'] = 'native'
            catalogs = {name: root / 'Libraries' / name / (name + '.docc') for name in targets}
            for catalog in catalogs.values():
                catalog.mkdir(parents=True)
            converted = []
            builds = []
            trait_flags = ['--traits', 'Experimental,default']

            def execute(command, *args, **kwargs):
                if command[:2] == ['swift', 'package']:
                    self.assertEqual(command[2:4], ['--build-system', 'native'])
                if 'describe' in command:
                    return json.dumps({'targets': [{'name': name, 'c99name': module,
                                                    'path': 'Libraries/' + name}
                                                   for name, module in modules.items()]})
                elif command[:2] == ['swift', 'build']:
                    symbols = root / '.build/symbol-graphs'
                    self.assertEqual(command, [
                        'swift', 'build', '--build-system', 'native', *trait_flags,
                        '-Xswiftc', '-emit-symbol-graph', '-Xswiftc', '-emit-symbol-graph-dir',
                        '-Xswiftc', symbols, '-Xswiftc', '-emit-extension-block-symbols'])
                    builds.append(command)
                    self.assertTrue(symbols.is_dir())
                    for module in [*modules.values(), 'MacroImplementation']:
                        for suffix in ('.symbols.json', '@Swift.symbols.json'):
                            (symbols / (module + suffix)).write_text(module + suffix)
                    (symbols / 'Feature.symbols.json.backup').write_text('backup')
                else:
                    self.assertEqual(command[:3], ['xcrun', 'docc', 'convert'])
                    target = command[command.index('--fallback-display-name') + 1]
                    symbols = Path(command[command.index('--additional-symbol-graph-dir') + 1])
                    expected = {modules[target] + '.symbols.json', modules[target] + '@Swift.symbols.json'}
                    self.assertEqual({path.name for path in symbols.iterdir()}, expected)
                    for path in symbols.iterdir():
                        self.assertEqual(path.read_text(), path.name)
                    self.assertIn(catalogs[target], command)
                    self.assertIn('--warnings-as-errors', command)
                    converted.append(target)

            with patch.object(runner, 'run', side_effect=execute):
                runner.execute(root, 'docs', {}, self.config)
                for target in targets:
                    (root / '.build/docc' / target / 'symbols/Stale.symbols.json').write_text('stale')
                runner.execute(root, 'docs', {}, self.config)
                del self.config['docs']['traits']
                trait_flags = []
                runner.execute(root, 'docs', {}, self.config)
                self.config['docs']['traits'] = []
                trait_flags = ['--disable-default-traits']
                runner.execute(root, 'docs', {}, self.config)
            self.assertEqual(converted, targets * 4)
            self.assertEqual(len(builds), 4)

    def test_docs_missing_main_graph_names_the_declared_target(self):
        parent = ROOT / '.build/config-tests'
        parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent) as directory:
            root = Path(directory)
            self.config['docs'] = {'targets': ['Hyphen-Feature']}
            description = json.dumps({'targets': [{'name': 'Hyphen-Feature',
                                                   'c99name': 'Hyphen_Feature', 'path': 'Sources/Feature'}]})
            with patch.object(runner, 'run', side_effect=[description, None]) as run:
                with self.assertRaisesRegex(ValueError, 'No main symbol graph.*Hyphen-Feature'):
                    runner.execute(root, 'docs', {}, self.config)
            self.assertEqual(run.call_count, 2)

    def test_aggregate_rejects_declared_skip_failure_and_cancellation(self):
        declared = ['configure', 'compiler', 'format']
        needs = {key: {'result': 'success'} for key in declared}
        needs['docs'] = {'result': 'skipped'}
        self.assertEqual(result.failures(needs, declared), [])
        for outcome in ('failure', 'cancelled', 'skipped'):
            needs['compiler']['result'] = outcome
            self.assertEqual(result.failures(needs, declared), ['compiler'])
        needs['compiler']['result'] = 'success'
        needs['docs']['result'] = 'failure'
        self.assertEqual(result.failures(needs, declared), ['docs'])


class DemoStagingTests(unittest.TestCase):
    def test_custom_demo_script_is_staged_with_its_recording_and_fixture(self):
        parent = ROOT / '.build/demo-tests'
        parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent) as directory:
            root = Path(directory)
            assets = root / 'assets'
            (assets / 'fixture').mkdir(parents=True)
            (assets / 'custom.yml').write_text('title: Custom\n')
            (assets / 'recording.json').write_text('{}\n')
            (assets / 'fixture/input').write_text('input')
            staged = runner.prepare_demo(root, assets / 'custom.yml')
            self.assertEqual((staged / 'script.yml').read_text(), 'title: Custom\n')
            self.assertEqual((staged / 'fixture/input').read_text(), 'input')
            self.assertEqual((assets / 'recording.json').read_text(), '{}\n')


class ToolchainTests(unittest.TestCase):
    def test_actual_version_and_arbitrary_names(self):
        toolchain = load_script('toolchain', 'verify-toolchain.py')
        entry = {'name': 'minimum', 'xcode': '26.6'}
        self.assertEqual(toolchain.verify(entry, 'Apple Swift version 6.3.3', '6.0'), (6, 3, 3))
        with self.assertRaisesRegex(ValueError, 'below'):
            toolchain.verify(entry, 'Swift version 5.9.2', '6.0')
        entry = {'name': 'minimum', 'swift': '6.0.3'}
        with self.assertRaises(ValueError):
            toolchain.verify(entry, 'Swift version 6.0.2')

    def test_minimum_uses_all_actual_reports_not_labels(self):
        reports = [{'name': 'oldest', 'version': [6, 0, 3]}, {'name': 'latest', 'version': [6, 3, 3]}]
        result.verify_minimum(reports, ['oldest', 'latest'], '6.0')
        for changed in (reports[1:], reports + reports[:1], [{'name': 'oldest', 'version': [6, 2, 0]}, reports[1]]):
            with self.subTest(reports=changed), self.assertRaises(ValueError):
                result.verify_minimum(changed, ['oldest', 'latest'], '6.0')
        with self.assertRaises(ValueError):
            result.verify_minimum(reports, ['oldest', 'latest'], '6.0.2')
