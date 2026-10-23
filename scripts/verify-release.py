#!/usr/bin/env python3
"""Authenticate a release tag and prepare notes from its accepted source."""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess


def api(path):
    return json.loads(subprocess.check_output(['gh', 'api', '--method', 'GET', path], text=True))


def authenticate(root, repository, tag, accepted, scratch):
    if not re.fullmatch(r'[0-9a-f]{40}', accepted):
        raise ValueError('accepted_commit must be a full commit SHA')
    if not re.fullmatch(r'v[0-9]+\.[0-9]+\.[0-9]+(?:-(?:alpha|beta|rc)\.[1-9][0-9]*)?', tag):
        raise ValueError('Expected a release version tag')
    def git(*args):
        return subprocess.check_output(['git', '-C', str(root), *args], text=True).strip()
    if git('rev-parse', 'HEAD') != accepted:
        raise ValueError('Checkout does not match accepted_commit')
    ref = 'refs/tags/' + tag
    if git('cat-file', '-t', ref) != 'tag' or git('rev-parse', ref + '^{commit}') != accepted:
        raise ValueError('Annotated release tag must resolve to accepted_commit')
    record = api(f'repos/{repository}/git/tags/' + git('rev-parse', ref))
    if record['tagger']['email'].lower() != '10173746+showxu@users.noreply.github.com':
        raise ValueError('Unexpected release tagger identity')
    if not record.get('verification', {}).get('verified'):
        raise ValueError('Release tag signature is not verified by GitHub')
    if record['object']['type'] != 'commit' or record['object']['sha'] != accepted:
        raise ValueError('GitHub tag identity differs from the accepted commit')
    scratch.mkdir(parents=True, exist_ok=True)
    if '-----BEGIN SSH SIGNATURE-----' in git('cat-file', 'tag', ref):
        keys = api('users/showxu/ssh_signing_keys')
        signers = scratch / 'allowed-signers'
        signers.write_text(''.join(record['tagger']['email'] + ' ' + key['key'] + '\n' for key in keys))
        os.environ.update(GIT_CONFIG_COUNT='1', GIT_CONFIG_KEY_0='gpg.ssh.allowedSignersFile', GIT_CONFIG_VALUE_0=str(signers))
    else:
        os.environ['GNUPGHOME'] = str(scratch / 'gnupg')
        Path(os.environ['GNUPGHOME']).mkdir(mode=0o700, exist_ok=True)
        for key in api('users/showxu/gpg_keys'):
            subprocess.run(['gpg', '--batch', '--import'], input=key['raw_key'], text=True, check=True)
    declaration = json.loads((root / '.github/release.json').read_text())
    if declaration['repository'] != repository:
        raise ValueError('Release declaration does not identify the caller repository')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--repository', required=True)
    parser.add_argument('--tag', required=True)
    parser.add_argument('--accepted-commit', required=True)
    parser.add_argument('--scratch', type=Path, required=True)
    parser.add_argument('--publish', action='store_true')
    args = parser.parse_args()
    root, scratch = args.root.resolve(), args.scratch.resolve()
    authenticate(root, args.repository, args.tag, args.accepted_commit, scratch)
    notes = scratch / 'notes.md'
    subprocess.run([os.sys.executable, str(Path(__file__).with_name('validate-version')), '--root', str(root),
                    '--tag', args.tag, '--require-clean', '--notes', str(notes)], check=True)
    if args.publish:
        existing = subprocess.run(['gh', 'release', 'view', args.tag, '--repo', args.repository,
                                   '--json', 'body,isDraft,assets'], capture_output=True, text=True)
        if existing.returncode == 0:
            release = json.loads(existing.stdout)
            if release['body'].strip() != notes.read_text().strip() or release['assets']:
                raise ValueError('Existing release differs from the accepted notes or has assets')
            if release['isDraft']:
                subprocess.run(['gh', 'release', 'edit', args.tag, '--repo', args.repository, '--draft=false'], check=True)
        else:
            subprocess.run(['gh', 'release', 'create', args.tag, '--repo', args.repository, '--verify-tag',
                            '--title', args.tag, '--notes-file', str(notes),
                            *(['--prerelease'] if '-' in args.tag else [])], check=True)


if __name__ == '__main__':
    main()
