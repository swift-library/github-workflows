import json
import subprocess
import sys
import unittest

from test_organization import ROOT, load_script

ci = load_script('ci_result', 'check-ci.py')


class CIResultTests(unittest.TestCase):
    def test_all_dependencies_must_succeed(self):
        needs = {name: {'result': 'success'}
                 for name in ('checks', 'validate', 'policy', 'fixtures', 'demo-fixture')}
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
