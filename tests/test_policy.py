import os
import json
from contextlib import redirect_stdout
from io import BytesIO, StringIO
from pathlib import Path
import shutil
import subprocess
import sys
import textwrap
import unittest
from unittest import mock
from urllib.error import URLError

from test_organization import ROOT, load_script


policy = load_script('policy', 'check-policy.py')
_check = policy.check

def check_with_dependabot(event, name):
    return _check(event, name, dependabot_exception=True)

policy.check = check_with_dependabot


def dependabot_metadata(sha):
    return {'sha': sha, 'author': {'login': 'dependabot[bot]', 'type': 'Bot'},
            'committer': {'login': 'web-flow', 'type': 'User'},
            'commit': {'verification': {'verified': True, 'reason': 'valid'}}}


def github_response(metadata):
    return BytesIO(json.dumps(metadata).encode())


class PolicyTests(unittest.TestCase):
    def test_subject_syntax_and_allowed_types(self):
        for kind in policy.TYPES.split('|'):
            self.assertEqual(policy.message_findings('commit', kind + '(cli)!: improve behavior'), [])
        for subject in ('Initial commit', 'feat:no space', 'feature: text', 'fix: ', 'fix(): text', 'fix: text '):
            self.assertTrue(policy.message_findings('commit', subject), subject)

    def test_attribution_in_body_and_legitimate_product_names(self):
        self.assertEqual(policy.message_findings('commit', 'feat: support Codex and Claude\n\nKeep notices.'), [])
        for trailer in ('Co-authored-by', 'Generated-by', 'Signed-off-by', 'Assisted-by'):
            self.assertTrue(policy.message_findings('commit', 'fix: change\n\n' + trailer + ': someone'))

    def test_dependabot_exception_is_exact_and_preserves_other_trailer_bans(self):
        signoff = policy.DEPENDABOT_SIGNOFF
        for trailer in (signoff.lower(), ' ' + signoff, signoff + ' ', signoff + '\r',
                        signoff.replace('support@github.com', 'someone@example.com'),
                        'Co-authored-by: someone', 'Generated-by: tool', 'Generated-with: tool',
                        'Made-with: tool', 'Assisted-by: tool', 'Powered-by: tool'):
            with self.subTest(trailer=trailer):
                self.assertTrue(policy.message_findings(
                    'commit', 'chore(deps): update\n\n' + signoff + '\n' + trailer, dependabot=True))
        self.assertTrue(policy.message_findings('PR title', 'chore: update\n' + signoff))
        self.assertTrue(policy.added_findings('@@ -0,0 +1 @@\n+' + signoff + '\n'))

    def test_only_added_lines_are_scanned(self):
        patch = 'diff --git a/file b/file\n--- a/file\n+++ b/file\n@@ -1,2 +1 @@\n-<<<<<<< old\n-Generated-by: old\n+Useful documentation about Codex\n'
        self.assertEqual(policy.added_findings(patch, allow_terms={'codex'}), [])
        patch += '@@ -10 +10,3 @@\n+<<<<<<< bad\n+=======\n+Generated-by: tool\n'
        findings = policy.added_findings(patch, allow_terms={'codex'})
        self.assertEqual(len(findings), 3)
        self.assertTrue(any('b/file:12' in line for line in findings))

    def test_event_ranges_reject_bad_or_unsupported_inputs(self):
        for event, name in (({}, 'schedule'), ({'deleted': True}, 'push'),
                            ({'before': 'not-a-sha', 'after': 'a' * 40}, 'push')):
            with self.assertRaises((ValueError, KeyError)):
                policy.source_range(event, name)

    def test_dispatch_requires_a_full_nonzero_github_sha(self):
        for environment in ({}, {'GITHUB_SHA': ''}, {'GITHUB_SHA': 'not-a-sha'},
                            {'GITHUB_SHA': 'a' * 39}, {'GITHUB_SHA': policy.ZERO}):
            with self.subTest(environment=environment), mock.patch.dict(os.environ, environment, clear=True):
                with self.assertRaises((ValueError, KeyError)):
                    policy.source_range({}, 'workflow_dispatch')


class GitRangeTests(unittest.TestCase):
    def setUp(self):
        self.root = ROOT / '.build/test-policy'
        self.root.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, self.root)
        self.git('init', '-q', '--initial-branch=main')
        self.git('config', 'user.name', 'Policy fixture')
        self.git('config', 'user.email', 'fixture@example.invalid')
        self.git('config', 'commit.gpgsign', 'false')
        (self.root / 'file').write_text('old content\n')
        self.base = self.commit('Initial legacy commit')
        self.git('update-ref', 'refs/remotes/origin/main', self.base)
        original = policy.git
        def git(*arguments):
            return original('-C', str(self.root), *arguments)
        self.patch = mock.patch.object(policy, 'git', side_effect=git)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.cwd = Path.cwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, self.cwd)

    def git(self, *arguments):
        return subprocess.check_output(['git', '-C', str(self.root), *arguments], text=True).strip()

    def commit(self, message):
        self.git('add', '.')
        self.git('commit', '-q', '-m', message)
        return self.git('rev-parse', 'HEAD')

    def event(self, head, title='fix: update content'):
        return {'repository': {'full_name': 'owner/member'},
                'pull_request': {'base': {'sha': self.base}, 'head': {'sha': head}, 'title': title}}

    def push_event(self, head, before, branch='topic', **values):
        return {'repository': {'full_name': 'owner/member', 'default_branch': 'main'},
                'ref': 'refs/heads/' + branch, 'before': before, 'after': head, **values}

    def check_push(self, event):
        output = StringIO()
        with redirect_stdout(output):
            findings = policy.check(event, 'push')
        return findings, output.getvalue()

    def dependency_update(self):
        (self.root / 'file').write_text('updated dependency\n')
        self.git('config', 'user.name', 'dependabot[bot]')
        self.git('config', 'user.email', '49699333+dependabot[bot]@users.noreply.github.com')
        return self.commit('chore(deps): bump dependency from 1.0 to 1.1\n\n' + policy.DEPENDABOT_SIGNOFF)

    def dispatch(self, head):
        event_file = self.root / 'event.json'
        event_file.write_text(json.dumps({'repository': {'full_name': 'owner/member'},
                                          'ref': 'main', 'inputs': {}}))
        self.addCleanup(event_file.unlink, missing_ok=True)
        with mock.patch.dict(os.environ, {'GITHUB_SHA': head}):
            findings = policy.check({}, 'workflow_dispatch')
        return subprocess.CompletedProcess([], int(bool(findings)), '\n'.join(findings), '')

    def test_dispatch_validates_selected_head_without_rescanning_history(self):
        (self.root / 'file').write_text('valid change\n')
        head = self.commit('fix: update content')
        (self.root / 'file').write_text('later change\n')
        self.commit('Invalid later subject')
        result = self.dispatch(head)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, '')

    def test_dispatch_rejects_invalid_subject_on_root_commit(self):
        result = self.dispatch(self.base)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(self.base + ': expected a Conventional Commit subject', result.stdout)
        self.assertNotIn('PR title', result.stdout)

    def test_dispatch_rejects_forbidden_trailers(self):
        (self.root / 'file').write_text('updated content\n')
        head = self.commit('fix: update content\n\nGenerated-by: tool')
        result = self.dispatch(head)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(head + ': forbidden attribution trailer', result.stdout)
        self.assertNotIn('PR title', result.stdout)

    def test_default_branch_push_checks_entire_range_without_pr_title(self):
        (self.root / 'file').write_text('first change\n')
        first = self.commit('Invalid subject')
        (self.root / 'file').write_text('second change  \n')
        head = self.commit('fix: update content\n\nGenerated-by: tool')
        event = {'repository': {'full_name': 'owner/member', 'default_branch': 'main'},
                 'ref': 'refs/heads/main', 'before': self.base, 'after': head}
        self.git('update-ref', 'refs/remotes/origin/main', head)
        findings, output = self.check_push(event)
        self.assertTrue(any(first + ': expected a Conventional Commit subject' in line for line in findings))
        self.assertIn(head + ': forbidden attribution trailer', findings)
        self.assertTrue(any('whitespace error' in line for line in findings))
        self.assertFalse(any('PR title' in line for line in findings))
        self.assertIn('validating 2 commits in ' + self.base + '..' + head, output)

    @mock.patch.dict(os.environ, {'GH_TOKEN': 'test-token'})
    def test_authenticated_dependabot_update_passes_on_pr_push_and_dispatch(self):
        head = self.dependency_update()
        events = ((self.event(head), 'pull_request'),
                  (self.push_event(head, self.base), 'push'),
                  ({'repository': {'full_name': 'owner/member'}, 'ref': 'main'}, 'workflow_dispatch'))
        for event, name in events:
            with self.subTest(event=name), mock.patch.dict(os.environ, {'GITHUB_SHA': head}), mock.patch.object(
                policy, 'urlopen', return_value=github_response(dependabot_metadata(head))
            ) as get:
                self.assertEqual(policy.check(event, name), [])
                request = get.call_args.args[0]
                self.assertEqual(request.full_url, 'https://api.github.com/repos/owner/member/commits/' + head)
                self.assertEqual(request.get_method(), 'GET')
                self.assertEqual(request.get_header('Authorization'), 'Bearer test-token')

    @mock.patch.dict(os.environ, {'GH_TOKEN': 'test-token'})
    def test_same_signoff_fails_without_authenticated_dependabot_authorship(self):
        head = self.dependency_update()
        variants = [
            {'author': {'login': 'contributor', 'type': 'User'}},
            {'author': {'login': 'dependabot[bot]', 'type': 'User'}},
            {'author': None}, {'author': 'dependabot[bot]'},
            {'committer': {'login': 'contributor', 'type': 'User'}},
            {'commit': {'verification': {'verified': False, 'reason': 'unsigned'}}},
            {'commit': {'verification': {'verified': True, 'reason': 'invalid'}}},
            {'commit': {'verification': None}}, {'commit': None},
            {'sha': 'a' * 40},
        ]
        for changed in variants:
            with self.subTest(metadata=changed), mock.patch.object(
                policy, 'urlopen', return_value=github_response({**dependabot_metadata(head), **changed})
            ):
                self.assertEqual(policy.check(self.event(head), 'pull_request'),
                                 [head + ': forbidden attribution trailer'])

    def test_commit_message_carriage_return_does_not_match_exact_signoff(self):
        (self.root / 'file').write_text('updated dependency\n')
        self.git('add', '.')
        self.git('commit', '-q', '--cleanup=verbatim', '-m',
                 'chore(deps): update dependency\n\n' + policy.DEPENDABOT_SIGNOFF + '\r\n')
        head = self.git('rev-parse', 'HEAD')
        with mock.patch.object(policy, 'authenticated_dependabot_commit') as authenticate:
            self.assertEqual(policy.check(self.event(head), 'pull_request'),
                             [head + ': forbidden attribution trailer'])
            authenticate.assert_not_called()

    @mock.patch.dict(os.environ, {'GH_TOKEN': 'test-token'})
    def test_dependabot_pr_does_not_exempt_another_authors_commit(self):
        first = self.dependency_update()
        self.git('config', 'user.name', 'Contributor')
        self.git('config', 'user.email', 'contributor@example.invalid')
        (self.root / 'file').write_text('another dependency update\n')
        second = self.commit('chore(deps): update another dependency\n\n' + policy.DEPENDABOT_SIGNOFF)
        other = {**dependabot_metadata(second), 'author': {'login': 'contributor', 'type': 'User'}}
        event = self.event(second)
        event['pull_request']['user'] = {'login': 'dependabot[bot]', 'type': 'Bot'}
        with mock.patch.object(policy, 'urlopen', side_effect=[
            github_response(dependabot_metadata(first)), github_response(other)
        ]) as get:
            self.assertEqual(policy.check(event, 'pull_request'), [second + ': forbidden attribution trailer'])
            self.assertEqual(get.call_count, 2)

    @mock.patch.dict(os.environ, {'GH_TOKEN': 'test-token'})
    def test_dependabot_authentication_fails_closed_when_unavailable_or_malformed(self):
        head = self.dependency_update()
        with mock.patch.object(policy, 'urlopen', side_effect=URLError('unavailable')):
            with self.assertRaises(URLError):
                policy.check(self.event(head), 'pull_request')
        with mock.patch.object(policy, 'urlopen', return_value=github_response([])):
            self.assertTrue(policy.check(self.event(head), 'pull_request'))
        with mock.patch.object(policy, 'urlopen', return_value=BytesIO(b'not JSON')):
            with self.assertRaises(ValueError):
                policy.check(self.event(head), 'pull_request')
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(KeyError):
                policy.check(self.event(head), 'pull_request')

    def test_new_branch_does_not_rescan_legacy_ancestors(self):
        (self.root / 'file').write_text('new content\n')
        head = self.commit('fix: update content')
        event = self.push_event(head, policy.ZERO)
        self.assertEqual(policy.check(event, 'push'), [])

    def test_feature_force_push_ignores_missing_before(self):
        (self.root / 'file').write_text('new content  \n')
        head = self.commit('Invalid rebased subject')
        findings, output = self.check_push(self.push_event(head, 'f' * 40))
        self.assertIn(head + ': expected a Conventional Commit subject (' + policy.TYPES + ')', findings)
        self.assertTrue(any('whitespace error' in finding for finding in findings))
        self.assertIn(self.base + '..' + head, output)

    def test_rebased_feature_excludes_commits_already_on_default_branch(self):
        (self.root / 'file').write_text('published content\n')
        published = self.commit('Published legacy subject')
        self.git('update-ref', 'refs/remotes/origin/main', published)
        (self.root / 'file').write_text('rebased feature content\n')
        head = self.commit('fix: update feature')
        findings, output = self.check_push(self.push_event(head, self.base))
        self.assertEqual(findings, [])
        self.assertIn(published + '..' + head, output)

    def test_default_force_push_excludes_history_reachable_from_previous_tip(self):
        (self.root / 'file').write_text('published content\n')
        published = self.commit('Published legacy subject')
        (self.root / 'file').write_text('old tip\n')
        before = self.commit('Old legacy tip')
        self.git('checkout', '-q', '-b', 'replacement', published)
        (self.root / 'file').write_text('replacement content  \n')
        head = self.commit('Invalid replacement subject')
        self.git('update-ref', 'refs/remotes/origin/main', head)
        findings, output = self.check_push(self.push_event(head, before, 'main', forced=True))
        self.assertEqual(sum('Conventional Commit' in finding for finding in findings), 1)
        self.assertTrue(any(finding.startswith(head + ':') for finding in findings))
        self.assertTrue(any('whitespace error' in finding for finding in findings))
        self.assertIn(before + '..' + head, output)

    def test_default_push_fetches_missing_previous_tip(self):
        remote = ROOT / '.build/test-policy-remote'
        self.addCleanup(shutil.rmtree, remote)
        self.git('init', '-q', '--bare', str(remote))
        self.git('remote', 'add', 'origin', str(remote))
        before = self.git('commit-tree', 'HEAD^{tree}', '-p', self.base, '-m', 'Old legacy tip')
        self.git('push', '-q', 'origin', before + ':refs/heads/previous')
        self.git('update-ref', '-d', 'refs/remotes/origin/previous')
        self.git('prune', '--expire=now')
        self.assertNotEqual(subprocess.run(
            ['git', 'cat-file', '-e', before], capture_output=True).returncode, 0)
        (self.root / 'file').write_text('replacement content\n')
        head = self.commit('fix: replace default tip')
        self.git('update-ref', 'refs/remotes/origin/main', head)
        findings, output = self.check_push(self.push_event(head, before, 'main', forced=True))
        self.assertEqual(findings, [])
        self.assertIn(before + '..' + head, output)
        self.assertEqual(self.git('rev-parse', before + '^{commit}'), before)

    def test_default_push_without_previous_tip_checks_only_head_and_its_added_lines(self):
        (self.root / 'file').write_text('older content\n')
        self.commit('Older legacy subject')
        (self.root / 'file').write_text('replacement content  \n')
        head = self.commit('Invalid replacement subject')
        self.git('update-ref', 'refs/remotes/origin/main', head)
        for before in ('f' * 40, policy.ZERO):
            with self.subTest(before=before):
                findings, output = self.check_push(self.push_event(head, before, 'main'))
                self.assertEqual(sum('Conventional Commit' in finding for finding in findings), 1)
                self.assertTrue(any(finding.startswith(head + ':') for finding in findings))
                self.assertTrue(any('whitespace error' in finding for finding in findings))
                self.assertIn('only ' + head, output)

    def test_new_default_branch_root_commit_checks_added_lines(self):
        self.git('checkout', '-q', '--orphan', 'new-default')
        (self.root / 'file').write_text('root content  \n')
        head = self.commit('fix: create default branch')
        findings, output = self.check_push(self.push_event(head, policy.ZERO, 'main'))
        self.assertTrue(any('whitespace error' in finding for finding in findings))
        self.assertIn('only ' + head, output)

    def test_branch_deletion_skips_without_accessing_git(self):
        with mock.patch.object(policy, 'git', side_effect=AssertionError('Git must not run')):
            findings, output = self.check_push(self.push_event(policy.ZERO, 'f' * 40, deleted=True))
        self.assertEqual(findings, [])
        self.assertIn('::notice::', output)
        self.assertIn('deletion', output)

    def test_new_orphan_feature_branch_checks_all_its_commits(self):
        self.git('checkout', '-q', '--orphan', 'orphan-topic')
        (self.root / 'file').write_text('new root content  \n')
        head = self.commit('Invalid orphan subject')
        findings, output = self.check_push(self.push_event(head, policy.ZERO))
        self.assertTrue(any(finding.startswith(head + ':') for finding in findings))
        self.assertTrue(any('whitespace error' in finding for finding in findings))
        self.assertIn(self.base + '..' + head, output)

    def test_title_commit_whitespace_and_conflict_failures(self):
        (self.root / 'file').write_text('bad whitespace  \n<<<<<<< branch\n')
        head = self.commit('Invalid subject\n\nGenerated-by: tool')
        findings = policy.check(self.event(head, 'Bad title'), 'pull_request')
        for reason in ('PR title', 'Conventional Commit', 'attribution', 'whitespace', 'conflict marker'):
            self.assertTrue(any(reason in line for line in findings), reason)

    def test_pr_merge_base_ignores_independent_base_branch_additions(self):
        self.git('checkout', '-q', '-b', 'topic')
        (self.root / 'topic').write_text('safe content\n')
        head = self.commit('feat: add content')
        self.git('checkout', '-q', 'main')
        (self.root / 'base-only').write_text('not part of PR  \n')
        self.base = self.commit('chore: update base')
        self.assertEqual(policy.check(self.event(head), 'pull_request'), [])

    def test_feature_push_checks_commits_against_default_and_added_lines_from_merge_base(self):
        self.git('checkout', '-q', '-b', 'topic')
        (self.root / 'topic').write_text('safe content\n')
        head = self.commit('feat: add content')
        self.git('checkout', '-q', 'main')
        (self.root / 'base-only').write_text('independent change\n')
        self.commit('chore: update base')
        self.git('update-ref', 'refs/remotes/origin/main', 'HEAD')
        event = self.push_event(head, policy.ZERO)
        base, _ = policy.source_range(event, 'push')
        self.assertEqual(base, self.git('rev-parse', 'refs/remotes/origin/main'))
        self.assertEqual(policy.check(event, 'push'), [])

    def test_attributes_cannot_hide_text_or_disable_whitespace_policy(self):
        (self.root / '.gitattributes').write_text('* -diff -whitespace\n')
        (self.root / 'file').write_text('trailing spaces  \n<<<<<<< branch\nGenerated-by: tool\n\n')
        head = self.commit('test: add attribute fixture')
        findings = policy.check(self.event(head), 'pull_request')
        for reason in ('whitespace', 'conflict marker', 'attribution', 'blank line at end'):
            self.assertTrue(any(reason in finding for finding in findings), reason)

    def test_agents_instruction_files_are_tracked_and_other_agent_files_stay_private(self):
        (self.root / '.agent/instructions/shared').mkdir(parents=True)
        (self.root / '.agent/instructions/shared/route.md').write_text('---\ndescription: Route changes.\n---\n## Route\n')
        (self.root / '.agent/agents.json').write_text('{"instructions": {"agents": ["claude-code", "codex"]}}\n')
        (self.root / '.agent/agents.resolved').write_text('{"instructions": {"chatgpt": {}}}\n')
        head = self.commit('docs: declare agent instructions')
        self.assertEqual(policy.check(self.event(head, 'docs: declare agent instructions'), 'pull_request'), [])
        (self.root / '.agent/plans').mkdir()
        (self.root / '.agent/plans/task.md').write_text('plan\n')
        (self.root / '.agent/cache').mkdir()
        (self.root / '.agent/cache/state').write_text('state\n')
        private = ('.agent/instructions/shared/.agent/cache/state', '.agent/instructions/.workspace/notes.md',
                   '.agent/instructions/PLANS.md', 'plugin/.agent/agents.json', '.agent/agents.json.bak')
        for path in private:
            (self.root / path).parent.mkdir(parents=True, exist_ok=True)
            (self.root / path).write_text('state\n')
        head = self.commit('docs: add private state')
        findings = policy.check(self.event(head, 'docs: add private state'), 'pull_request')
        for path in ('.agent/plans/task.md', '.agent/cache/state', *private):
            self.assertIn(f'{path}: private execution file', findings)

    def test_instruction_units_still_need_permitted_product_terms(self):
        (self.root / '.agent/instructions').mkdir(parents=True)
        (self.root / '.agent/instructions/guide.md').write_text('# Guide\n\nAsk Codex.\n')
        head = self.commit('docs: add guide')
        findings = policy.check(self.event(head, 'docs: add guide'), 'pull_request')
        self.assertTrue(any('unapproved product/tool term: Codex' in finding for finding in findings))

    def test_binary_content_is_not_interpreted_as_text(self):
        (self.root / 'image').write_bytes(b'\x00\n<<<<<<< bytes\nGenerated-by: bytes  \n')
        head = self.commit('test: add binary fixture')
        self.assertEqual(policy.check(self.event(head), 'pull_request'), [])

    def test_filename_pathspec_characters_cannot_hide_added_lines(self):
        (self.root / '[a]').write_text('trailing whitespace  \n')
        (self.root / 'a').write_text('safe content\n')
        head = self.commit('test: add wildcard filename fixture')
        self.assertTrue(any('whitespace' in finding for finding in policy.check(self.event(head), 'pull_request')))

    def test_gitlinks_are_not_treated_as_text_blobs(self):
        self.git('update-index', '--add', '--cacheinfo', '160000,' + self.base + ',dependency')
        self.git('commit', '-q', '-m', 'test: add gitlink fixture')
        head = self.git('rev-parse', 'HEAD')
        self.assertEqual(policy.check(self.event(head), 'pull_request'), [])
