import contextlib
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from test_organization import ROOT, load_script

fixtures = load_script('fixture_tests', 'test-fixtures.py')


class DemoFixtureTests(unittest.TestCase):
    def exercise(self, name, status, output, *, build_status=0):
        parent = ROOT / '.build/demo-tests'
        parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent) as directory:
            root = Path(directory)
            (root / 'fixtures' / name).mkdir(parents=True)
            toolchain = root / 'toolchain'
            assets = root / 'assets'
            executable = root / 'bin/fixture-cli'
            calls = []

            def run(command, **kwargs):
                calls.append(command)
                if len(calls) == 1:
                    self.assertEqual(command[2:4], ['demo', '--root'])
                    self.assertNotEqual(kwargs['env']['GITHUB_OUTPUT'], kwargs['env']['GITHUB_PATH'])
                    Path(kwargs['env']['GITHUB_OUTPUT']).write_text(
                        f'demo_assets={assets}\ndemo_executable={executable}\n')
                    return subprocess.CompletedProcess(command, build_status)
                self.assertEqual(command, ['node', str(toolchain / 'src/cli.ts'), 'terminal', 'check',
                                          '--recording-only', '--assets', str(assets),
                                          '--executable', str(executable)])
                return subprocess.CompletedProcess(command, status, output.replace('{assets}', str(assets)))

            failure = fixtures.CASES[name][1] if name in fixtures.CASES else None
            with patch.object(fixtures, 'ROOT', root), patch.object(fixtures.subprocess, 'run', side_effect=run), \
                    contextlib.redirect_stdout(io.StringIO()):
                fixtures.exercise(name, 'demo', failure=failure, toolchain=toolchain)
            self.assertEqual(len(calls), 2)

    def test_matching_demo_passes(self):
        self.exercise('passing', 0, 'recording.json matches\n')

    def test_passing_demo_rejects_drift(self):
        with self.assertRaisesRegex(ValueError, 'passing/demo unexpectedly failed'):
            self.exercise('passing', 1, 'recording.json: changed step 1: fixture-cli\n')

    def test_drift_requires_exit_one_changed_step_and_recording_diff(self):
        difference = ('recording.json: changed step 1: fixture-cli\n'
                      '--- {assets}/recording.json\n+++ regenerated/{assets}/recording.json\n')
        self.exercise('demo-drift', 1, difference)
        for status, output in ((0, difference), (2, difference), (1, 'Node failed'),
                               (1, 'recording.json: changed step 1: fixture-cli\n')):
            with self.subTest(status=status, output=output):
                with self.assertRaisesRegex(ValueError, 'demo-drift/demo did not fail for its intended reason'):
                    self.exercise('demo-drift', status, output)

    def test_build_failure_cannot_count_as_drift(self):
        with self.assertRaisesRegex(ValueError, 'demo-drift/demo build unexpectedly failed'):
            self.exercise('demo-drift', 1, '', build_status=1)

    def test_demo_requires_an_installed_toolchain(self):
        process = subprocess.run([sys.executable, str(ROOT / 'scripts/test-fixtures.py'), 'demo'],
                                 capture_output=True, text=True, timeout=10)
        self.assertEqual(process.returncode, 2)
        self.assertIn('demo requires --toolchain with src/cli.ts', process.stderr)


class CommandFixtureTests(unittest.TestCase):
    def test_command_rejection_requires_its_marker(self):
        parent = ROOT / '.build/command-tests'
        parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent) as directory:
            root = Path(directory)
            (root / 'fixtures/command').mkdir(parents=True)
            marker = fixtures.CASES['command'][1]
            for status, output, accepted in ((42, marker, True), (0, marker, False),
                                              (42, 'Unrelated command error', False)):
                def run(command, **kwargs):
                    kwargs['stdout'].write(output)
                    return subprocess.CompletedProcess(command, status)
                with self.subTest(status=status, output=output), \
                        patch.object(fixtures, 'ROOT', root), \
                        patch.object(fixtures.subprocess, 'run', side_effect=run), \
                        contextlib.redirect_stdout(io.StringIO()):
                    if accepted:
                        fixtures.exercise('command', 'commands', failure=marker)
                    else:
                        with self.assertRaisesRegex(ValueError, 'did not fail for its intended reason'):
                            fixtures.exercise('command', 'commands', failure=marker)
