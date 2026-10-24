import json
import subprocess
import sys
import unittest
from unittest.mock import patch

from test_organization import ROOT, load_script

ci = load_script('ci_result', 'check-ci.py')


class CIResultTests(unittest.TestCase):
    def test_all_dependencies_must_succeed(self):
        needs = {name: {'result': 'success'}
                 for name in ('checks', 'validate', 'fixtures', 'demo-fixture')}
        ci.check(needs)
        for name in needs:
            for result in ('failure', 'cancelled', 'skipped'):
                with self.subTest(name=name, result=result):
                    changed = {**needs, name: {'result': result}}
                    with self.assertRaisesRegex(ValueError, f'{name}: expected success, got {result}'):
                        ci.check(changed)

    def test_cli_requires_only_needs(self):
        for result, status, message in (
            ('success', 0, 'All CI checks passed'),
            ('failure', 1, 'checks: expected success, got failure'),
        ):
            with self.subTest(result=result):
                process = subprocess.run([
                    sys.executable, str(ROOT / 'scripts/check-ci.py'),
                ], env={'NEEDS': json.dumps({'checks': {'result': result}})},
                    capture_output=True, text=True, timeout=10)
                self.assertEqual(process.returncode, status, process.stdout + process.stderr)
                self.assertIn(message, process.stdout + process.stderr)


class DemoRevisionTests(unittest.TestCase):
    def test_reads_the_single_demo_action_pin(self):
        revision = 'a' * 40
        source = f'    - uses: showxu/skills/skills/github-readme-design/scripts@{revision}\n'
        with patch.object(ci.Path, 'read_text', return_value=source):
            self.assertEqual(ci.demo_revision(), revision)

    def test_rejects_missing_mutable_duplicate_and_zero_pins(self):
        action = '    - uses: showxu/skills/skills/github-readme-design/scripts@'
        for source in ('', action + 'main\n', action + '0' * 40 + '\n',
                       (action + 'a' * 40 + '\n') * 2):
            with self.subTest(source=source), patch.object(ci.Path, 'read_text', return_value=source):
                with self.assertRaisesRegex(ValueError, 'one demo action pinned to a nonzero full SHA'):
                    ci.demo_revision()

    def test_cli_reads_pin_without_needs(self):
        process = subprocess.run([sys.executable, str(ROOT / 'scripts/check-ci.py'), '--demo-revision'],
                                 env={}, capture_output=True, text=True, timeout=10)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(process.stdout.strip(), ci.demo_revision())
