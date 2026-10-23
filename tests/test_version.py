# SPDX-License-Identifier: Apache-2.0 WITH Swift-exception
"""Exercise shared version declarations and cryptographic tag acceptance."""

import importlib.machinery
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
loader = importlib.machinery.SourceFileLoader('versions', str(ROOT / 'scripts/validate-version'))
spec = importlib.util.spec_from_loader(loader.name, loader)
versions = importlib.util.module_from_spec(spec)
loader.exec_module(versions)


class VersionTests(unittest.TestCase):
    def setUp(self):
        output = ROOT / '.build/version-tests'
        output.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=output)
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.git('init', '-q')
        self.git('config', 'user.name', 'Fixture')
        self.git('config', 'user.email', 'fixture@example.test')
        self.git('config', 'commit.gpgsign', 'false')
        self.git('config', 'tag.gpgsign', 'false')
        self.git('config', 'core.hooksPath', '/dev/null')
        (self.root / '.gitignore').write_text('.build/\n')
        (self.root / '.github').mkdir()
        (self.root / 'Package.swift').write_text('// swift-tools-version: 6.0\n')
        (self.root / 'VERSION').write_text('1.2.3\n')
        (self.root / 'CHANGELOG.md').write_text('# Changelog\n\n## Unreleased\n\n## 1.2.3\n\nValidate input.\n')
        self.config = {
            'repository': 'example/package', 'version_file': 'VERSION',
            'version_pattern': r'^([^\n]+)\n?$', 'changelog': 'CHANGELOG.md',
            'minimum_swift': '6.0',
            'platforms': ['macOS'],
        }
        self.compilers = [{'name': 'macos-swift-6.0'}, {'name': 'macos-swift-6.3'}]
        self.write_config()
        self.git('add', '.')
        self.git('commit', '-qm', 'feat: validate input')

    def git(self, *args):
        return versions.git(self.root, *args)

    def write_config(self):
        (self.root / '.github/release.json').write_text(json.dumps(self.config))
        (self.root / '.github/swift-package.json').write_text(json.dumps({'compilers': [
            {'runner': 'macos-26', 'xcode': '26.6', **item} for item in self.compilers]}))

    def test_version_notes_and_clean_source(self):
        result, notes = versions.validate(self.root, require_clean=True)
        self.assertEqual(result['version'], '1.2.3')
        self.assertEqual(result['minimum_swift'], '6.0')
        self.assertEqual(result['commit'], self.git('rev-parse', 'HEAD'))
        self.assertEqual(notes, 'Validate input.')
        (self.root / 'VERSION').write_text('1.2.4\n')
        with self.assertRaisesRegex(ValueError, 'Changelog'):
            versions.validate(self.root)
        (self.root / 'VERSION').write_text('1.2.3\n')
        (self.root / 'new.txt').write_text('uncommitted')
        with self.assertRaisesRegex(ValueError, 'clean committed'):
            versions.validate(self.root, require_clean=True)

    def test_compiler_contract(self):
        self.compilers = [{'name': 'oldest'}, {'name': 'latest'}]
        self.write_config()
        versions.validate(self.root)
        self.config['minimum_swift'] = '6.1'
        self.write_config()
        with self.assertRaisesRegex(ValueError, 'swift-tools-version'):
            versions.validate(self.root)

    def test_lightweight_tag_rejected(self):
        self.git('tag', 'v1.2.3')
        with self.assertRaisesRegex(ValueError, 'signed and annotated'):
            versions.validate(self.root, tag='v1.2.3')

    def test_unsigned_annotated_tag_rejected(self):
        self.git('tag', '-a', 'v1.2.3', '-m', 'package 1.2.3')
        with self.assertRaises(subprocess.CalledProcessError):
            versions.validate(self.root, tag='v1.2.3')

    def test_signed_tag_identity_and_trust(self):
        build = self.root / '.build'
        build.mkdir()
        key = build / 'signing-key'
        subprocess.run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(key)], check=True)
        signers = build / 'allowed-signers'
        signers.write_text('fixture@example.test ' + key.with_suffix('.pub').read_text())
        self.git('config', 'gpg.format', 'ssh')
        self.git('config', 'user.signingkey', str(key))
        self.git('config', 'gpg.ssh.allowedSignersFile', str(signers))
        self.git('tag', '-s', 'v1.2.3', '-m', 'package 1.2.3')
        versions.validate(self.root, tag='v1.2.3', require_clean=True)
        signers.write_text('')
        with self.assertRaises(subprocess.CalledProcessError):
            versions.validate(self.root, tag='v1.2.3')
        signers.write_text('fixture@example.test ' + key.with_suffix('.pub').read_text())
        self.git('commit', '--allow-empty', '-qm', 'fix: validate request')
        with self.assertRaisesRegex(ValueError, 'candidate commit'):
            versions.validate(self.root, tag='v1.2.3')
        with self.assertRaisesRegex(ValueError, 'Tag must match'):
            versions.validate(self.root, tag='v1.2.4')


if __name__ == '__main__':
    unittest.main()
