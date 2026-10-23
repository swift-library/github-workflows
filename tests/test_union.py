import contextlib
import copy
import io
import json
import unittest
from unittest.mock import patch

from test_organization import ROOT, checks, committed_catalog, load_script
policy = load_script('union_policy', 'check-policy.py')


class UnionTests(unittest.TestCase):
    def test_product_exception_does_not_exempt_attribution_or_private_paths(self):
        self.assertEqual(policy.content_findings('x', 1, 'Support Codex', {'codex'}), [])
        self.assertTrue(policy.content_findings('x', 1, 'Support Codex', set()))
        self.assertTrue(policy.content_findings('x', 1, '/'+ 'Users' + '/fixture/source', set()))
        self.assertTrue(policy.content_findings('x', 1, 'Generated' + ' with a tool', set()))

    def test_commit_signature_and_identity(self):
        record = {'commit': {'committer': {'email': policy.OWNER_EMAIL}, 'verification': {'verified': True}}}
        self.assertEqual(policy.commit_findings('a' * 40, record), [])
        record['commit']['verification']['verified'] = False
        self.assertTrue(policy.commit_findings('a' * 40, record))
        record['commit']['committer']['email'] = 'unknown@example.test'
        self.assertEqual(len(policy.commit_findings('a' * 40, record)), 2)


class OrganizationModesTests(unittest.TestCase):
    def invoke(self, mode='public', members='all', findings=()):
        catalog = committed_catalog()
        live = [{'name': item['name'], 'description': item['about'], 'private': False, 'archived': False, 'fork': False}
                for group in catalog['groups'] for item in group['repositories']]
        live.append({'name': '.github', 'description': catalog['organization']['about'], 'private': False, 'archived': False, 'fork': False})
        with contextlib.redirect_stdout(io.StringIO()), patch.object(checks, 'fetch_repositories', return_value=live), patch.object(checks.settings, 'check_online', return_value=list(findings)) as online, patch.object(checks.settings, 'check_repository', return_value=list(findings)) as member:
            status = checks.main(['--declaration-root', str(ROOT / 'fixtures/organization'), '--organization', 'example-org',
                                 '--catalog-repository', 'example-org/.github', '--mode', mode, '--members', members])
        return status, online, member

    def test_public_avoids_admin_endpoints(self):
        status, online, member = self.invoke()
        self.assertEqual(status, 0)
        online.assert_not_called()
        member.assert_not_called()

    def test_online_status_and_selection(self):
        for findings, status in (([], 0), (['DRIFT field'], 1), (['GAP rulesets'], 1), (['UNKNOWN field'], 2)):
            self.assertEqual(self.invoke('online', findings=findings)[0], status)
        status, online, member = self.invoke('online', members='core')
        self.assertEqual(status, 0)
        online.assert_not_called()
        self.assertEqual(member.call_args.args[0], 'example-org/core')
        self.assertEqual(self.invoke(members='missing')[0], 1)

    def test_catalog_repository_name_is_an_input(self):
        catalog = committed_catalog()
        live = [{'name': item['name'], 'description': item['about'], 'private': False, 'archived': False, 'fork': False}
                for group in catalog['groups'] for item in group['repositories']]
        live.append({'name': 'standard', 'description': catalog['organization']['about'], 'private': False, 'archived': False, 'fork': False})
        checks.compare_membership(catalog, live, 'standard')
        checks.compare_about(catalog, live, 'standard')


class CheckerSourceTests(unittest.TestCase):
    def test_policy_can_check_its_own_source(self):
        source = (ROOT / 'scripts/check-policy.py').read_text()
        patch_text = '@@ -0,0 +1 @@\n' + '\n'.join('+' + line for line in source.splitlines())
        self.assertEqual(policy.added_findings(patch_text, allow_terms={'chatgpt', 'codex', 'cursor', 'claude'}), [])


class SplitOrganizationTests(unittest.TestCase):
    def test_separate_catalog_and_declaration_filter_other_organizations(self):
        from pathlib import Path
        import tempfile
        parent = ROOT / '.build/organization-tests'
        parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent) as directory:
            declaration_root = Path(directory) / 'declaration'
            catalog_root = Path(directory) / 'catalog'
            declaration_root.mkdir()
            (catalog_root / 'profile').mkdir(parents=True)
            declaration = checks.settings.load_declaration(ROOT / 'fixtures/organization')
            expected = copy.deepcopy(declaration)
            declaration['repositories']['other-org/core'] = copy.deepcopy(
                declaration['repositories']['example-org/core'])
            (declaration_root / 'MAINTENANCE.md').write_text(
                '<!-- settings-declaration -->\n```json\n' + json.dumps(declaration) + '\n```\n')
            catalog = committed_catalog()
            (catalog_root / 'profile/catalog.json').write_text(json.dumps(catalog))
            live = [{'name': item['name'], 'description': item['about'],
                     'private': False, 'archived': False, 'fork': False}
                    for group in catalog['groups'] for item in group['repositories']]
            live.append({'name': '.github', 'description': catalog['organization']['about'],
                         'private': False, 'archived': False, 'fork': False})
            args = ['--declaration-root', str(declaration_root), '--catalog-root', str(catalog_root),
                    '--organization', 'example-org', '--catalog-repository', 'example-org/.github',
                    '--mode', 'online']
            with contextlib.redirect_stdout(io.StringIO()), \
                    patch.object(checks, 'fetch_repositories', return_value=live) as fetch, \
                    patch.object(checks.settings, 'check_online', return_value=[]) as online, \
                    patch.object(checks.settings, 'check_repository', return_value=[]) as member:
                self.assertEqual(checks.main(args), 0)
                online.assert_called_once_with(expected)
                self.assertEqual(fetch.call_args.args[0], 'example-org')
                self.assertEqual(checks.main([*args, '--members', 'core']), 0)
                self.assertEqual(member.call_args.args[0], 'example-org/core')
                self.assertEqual(member.call_args.args[2], expected)
                member.reset_mock()
                self.assertEqual(checks.main([*args, '--members', 'other-org/core']), 1)
                member.assert_not_called()

            only_other = copy.deepcopy(declaration)
            only_other['repositories'] = {'other-org/core': declaration['repositories']['other-org/core']}
            (declaration_root / 'MAINTENANCE.md').write_text(
                '<!-- settings-declaration -->\n```json\n' + json.dumps(only_other) + '\n```\n')
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()), \
                    patch.object(checks, 'fetch_repositories', return_value=live), \
                    patch.object(checks.settings, 'check_online', return_value=[]) as online:
                self.assertEqual(checks.main(args), 1)
                online.assert_not_called()

    def test_workflow_requires_both_resolved_revisions_to_be_full_shas(self):
        import subprocess
        source = (ROOT / '.github/workflows/organization.yml').read_text()
        script = source.split('      run: |\n', 1)[1].split('    - ', 1)[0]
        for declaration, catalog, mode, status in (
            ('a' * 40, 'b' * 40, 'public', 0), ('a' * 40, 'b' * 40, 'online', 0),
            ('main', 'b' * 40, 'public', 1), ('a' * 40, 'main', 'public', 1),
            ('', 'b' * 40, 'public', 1), ('a' * 40, '', 'public', 1),
            ('a' * 40, 'b' * 40, 'invalid', 1),
        ):
            with self.subTest(declaration=declaration, catalog=catalog, mode=mode):
                result = subprocess.run(['bash', '-euo', 'pipefail', '-c', script],
                                        env={'DECLARATION_REVISION': declaration,
                                             'CATALOG_REVISION': catalog, 'MODE': mode})
                self.assertEqual(result.returncode, status)
