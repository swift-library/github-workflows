import json
import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from test_organization import ROOT, load_script
release = load_script('release', 'verify-release.py')
ci = load_script('ci_result', 'check-ci.py')


class ReleaseTests(unittest.TestCase):
    def test_invalid_tag_or_commit_rejects_before_remote_operations(self):
        for tag, commit in [('v1.2.3', 'short'), ('fixture-invalid-tag', 'a' * 40)]:
            with patch.object(release, 'api') as api, self.assertRaises(ValueError):
                release.authenticate(ROOT, 'example/package', tag, commit, ROOT / '.build/release-tests')
            api.assert_not_called()

    def test_github_tag_identity_and_signature_fail_closed(self):
        record = {'tagger': {'email': '10173746+showxu@users.noreply.github.com'},
                  'verification': {'verified': True}, 'object': {'type': 'commit', 'sha': 'a' * 40}}
        cases = [
            {**record, 'tagger': {'email': 'unknown@example.test'}},
            {**record, 'verification': {'verified': False}},
            {**record, 'object': {'type': 'commit', 'sha': 'b' * 40}},
        ]
        for value in cases:
            with self.subTest(value=value), patch.object(release.subprocess, 'check_output', side_effect=['a' * 40, 'tag', 'a' * 40, 'c' * 40]), patch.object(release, 'api', return_value=value), self.assertRaises(ValueError):
                release.authenticate(ROOT, 'example/package', 'v1.2.3', 'a' * 40, ROOT / '.build/release-tests')

    def test_expected_workflow_failures_do_not_accept_bootstrap_failures(self):
        needs = {name: {'result': 'failure'} for name in ci.REJECTIONS}
        needs['checks'] = {'result': 'success'}
        jobs = [{'name': name + ' / ' + job, 'steps': [{'name': step, 'conclusion': 'failure'}]}
                for name, (job, step) in ci.REJECTIONS.items()]
        ci.check(needs, jobs)
        jobs[0]['steps'][0]['name'] = 'Resolve the executing reusable workflow revision'
        with self.assertRaises(ValueError):
            ci.check(needs, jobs)


class PublicationTests(unittest.TestCase):
    def exercise(self, existing=None):
        import tempfile
        output = ROOT / '.build/publication-tests'
        output.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=output)
        self.addCleanup(temporary.cleanup)
        scratch = Path(temporary.name)
        calls = []
        def run(command, **kwargs):
            calls.append(command)
            if '--require-clean' in command:
                (scratch / 'notes.md').write_text('Shipped behavior.\n')
                return subprocess.CompletedProcess(command, 0)
            if command[:3] == ['gh', 'release', 'view']:
                return subprocess.CompletedProcess(command, 1 if existing is None else 0,
                                                   stdout=json.dumps(existing))
            return subprocess.CompletedProcess(command, 0)
        argv = ['verify-release.py', '--root', str(ROOT), '--repository', 'example/package',
                '--tag', 'v1.2.3', '--accepted-commit', 'a' * 40, '--scratch', str(scratch), '--publish']
        with patch.object(release, 'authenticate') as authenticate, patch.object(release.os.sys, 'argv', argv), patch.object(release.subprocess, 'run', side_effect=run):
            release.main()
        authenticate.assert_called_once()
        return calls

    def test_publication_uses_validated_notes_and_no_assets(self):
        calls = self.exercise()
        self.assertIn('--tag', calls[0])
        self.assertIn('--require-clean', calls[0])
        create = calls[-1]
        self.assertEqual(create[:3], ['gh', 'release', 'create'])
        self.assertIn('--verify-tag', create)
        self.assertIn('--notes-file', create)
        self.assertFalse(any('upload' in command for command in calls))

    def test_existing_release_notes_and_assets_are_immutable(self):
        good = {'body': 'Shipped behavior.', 'assets': [], 'isDraft': False}
        self.assertEqual(len(self.exercise(good)), 2)
        calls = self.exercise({**good, 'isDraft': True})
        self.assertEqual(calls[-1][:3], ['gh', 'release', 'edit'])
        for changed in ({'body': 'Different.'}, {'assets': [{'name': 'unexpected'}]}):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                self.exercise({**good, **changed})
