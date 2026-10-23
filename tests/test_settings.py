import contextlib
import copy
import io
import json
import re
import subprocess
import unittest
from unittest import mock

from test_organization import ROOT, checks


settings = checks.settings


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.declaration = settings.load_declaration(ROOT / "fixtures/organization")
        self.name = 'example-org/core'
        self.member = self.declaration['repositories'][self.name]
        self.rulesets = settings.expected_rulesets(self.declaration, self.member)
        self.metadata = {**self.declaration['defaults']['repository'], **{
            key: self.member[key] for key in ('default_branch', 'description', 'topics')},
            'visibility': 'public'}
        self.token = copy.deepcopy(self.declaration['defaults']['workflow_token'])

    def get(self, path, *, paginate=False):
        if '/rulesets?' in path:
            self.assertTrue(paginate)
            return [[{'id': index + 1} for index in range(len(self.rulesets))]]
        if '/rulesets/' in path:
            return self.rulesets[int(path.split('/rulesets/')[1].split('?')[0]) - 1]
        if path.endswith('/actions/permissions/workflow'):
            return self.token
        if path.endswith('/private-vulnerability-reporting'):
            return {'enabled': True}
        return self.metadata

    def check(self, get=None):
        return settings.check_repository(self.name, self.member, self.declaration, get or self.get)

    def test_table_and_declaration_agree(self):
        text = (ROOT / 'fixtures/organization/MAINTENANCE.md').read_text()
        table = re.findall(r'^\| `([^`]+/[^`]+)` \| (`policy / policy`.*?) \| (.*?) \|$', text, re.M)
        self.assertEqual({row[0] for row in table}, self.declaration['repositories'].keys())
        for name, contexts, tags in table:
            member = self.declaration['repositories'][name]
            self.assertEqual(re.findall(r'`([^`]+)`', contexts), member['required_checks'])
            for pattern in member['release_tag_patterns']:
                self.assertIn('`' + pattern.removeprefix('refs/tags/') + '`', tags)
            if not member['release_tag_patterns']:
                self.assertEqual(tags, 'None')

    def test_matching_settings_allow_server_metadata_and_set_reordering(self):
        for rule in self.rulesets:
            rule['id'] = 123
            rule['rules'].reverse()
        self.metadata['topics'] = list(reversed(self.metadata['topics']))
        self.assertEqual(self.check(), [f'PASS {self.name} settings'])

    def test_merge_token_reporting_and_metadata_drift_are_specific(self):
        self.metadata['allow_merge_commit'] = True
        self.metadata['description'] = 'Different description'
        self.metadata['topics'] = []
        self.token['can_approve_pull_request_reviews'] = True
        def get(path, **kwargs):
            return {'enabled': False} if path.endswith('private-vulnerability-reporting') else self.get(path, **kwargs)
        findings = self.check(get)
        self.assertEqual(len(findings), 5)
        for field in ('allow_merge_commit', 'description', 'topics', 'can_approve_pull_request_reviews', 'enabled'):
            self.assertTrue(any(field + ': expected' in finding for finding in findings), field)

    def test_private_member_profile_reports_its_declared_gap(self):
        self.name = 'example-org/.github-private'
        self.member = self.declaration['repositories'][self.name]
        self.metadata.update({key: self.member[key] for key in ('default_branch', 'description', 'topics')},
                             visibility='private')
        requested = []
        def get(path, **kwargs):
            requested.append(path)
            return self.get(path, **kwargs)
        findings = self.check(get)
        self.assertEqual(findings, [f"GAP {self.name}.rulesets: {self.member['enforcement_gap']}"])
        self.assertFalse(any('private-vulnerability-reporting' in path or '/rulesets' in path
                             for path in requested))
        self.metadata['visibility'] = 'public'
        self.assertTrue(any('visibility: expected "private"' in finding for finding in self.check()))

    def test_visibility_and_gap_declarations_are_validated(self):
        for mutation in (lambda m: m.update(visibility='internal'),
                         lambda m: m.update(enforcement_gap='Plan limitation.'),
                         lambda m: m.update(visibility='private', enforcement_gap=' ')):
            value = copy.deepcopy(self.declaration)
            mutation(value['repositories'][self.name])
            with self.assertRaises(ValueError):
                settings.validate_declaration(value)

    def test_public_membership_excludes_declared_private_repositories(self):
        def get(path, **kwargs):
            organization = path.split('/')[1]
            names = [name for name, member in self.declaration['repositories'].items()
                     if name.startswith(organization + '/') and member.get('visibility', 'public') == 'public']
            return [[{'full_name': name, 'private': False, 'archived': False} for name in names]
                    + [{'full_name': organization + '/.github-private', 'private': True, 'archived': False}]]
        with mock.patch.object(settings, 'check_repository', return_value=[]):
            self.assertEqual(settings.check_online(self.declaration, get), [])

    def test_ruleset_parameters_are_checked_beyond_names(self):
        branch = self.rulesets[0]
        branch['enforcement'] = 'disabled'
        branch['bypass_actors'] = [{'actor_type': 'RepositoryRole', 'actor_id': 5, 'bypass_mode': 'always'}]
        branch['conditions']['ref_name']['exclude'] = ['refs/heads/master']
        for rule in branch['rules']:
            if rule['type'] == 'pull_request':
                rule['parameters']['required_approving_review_count'] = 1
                rule['parameters']['required_review_thread_resolution'] = False
            if rule['type'] == 'required_status_checks':
                rule['parameters']['required_status_checks'][0]['integration_id'] = None
        self.rulesets[1]['conditions']['ref_name']['include'] = ['refs/tags/v*']
        findings = self.check()
        for field in ('enforcement', 'bypass_actors', 'exclude', 'required_approving_review_count',
                      'required_review_thread_resolution', 'required_status_checks', 'include'):
            self.assertTrue(any(field in finding for finding in findings), field)

    def test_missing_extra_and_duplicate_rules_fail(self):
        for mutation in (lambda rules: rules.pop(), lambda rules: rules.append({'type': 'creation'}),
                         lambda rules: rules.append(copy.deepcopy(rules[0]))):
            self.setUp()
            mutation(self.rulesets[0]['rules'])
            self.assertTrue(any('rule_types' in finding for finding in self.check()))

    def test_missing_rulesets_and_no_tag_requirement_on_taps(self):
        self.rulesets = []
        self.assertEqual(len(self.check()), 1)
        self.assertIn('expected ["Default branch", "Release tags"]; observed []', self.check()[0])
        self.member = self.declaration['repositories']['example-org/homebrew-tap']
        self.assertEqual(len(settings.expected_rulesets(self.declaration, self.member)), 1)

    def test_unavailable_endpoint_does_not_hide_other_drift(self):
        self.metadata['description'] = 'Drift'
        def get(path, **kwargs):
            if path.endswith('permissions/workflow'):
                raise settings.Unavailable('HTTP 403')
            return self.get(path, **kwargs)
        findings = self.check(get)
        self.assertTrue(any(line.startswith('UNKNOWN ') and 'workflow_token' in line for line in findings))
        self.assertTrue(any(line.startswith('DRIFT ') and 'description' in line for line in findings))

    def test_missing_fields_and_invalid_ruleset_inventory_are_unknown(self):
        del self.metadata['allow_merge_commit']
        self.assertTrue(any('UNKNOWN' in line and 'allow_merge_commit' in line for line in self.check()))
        def get(path, **kwargs):
            return [[{}]] if '/rulesets?' in path else self.get(path, **kwargs)
        self.assertTrue(any('UNKNOWN' in line and 'rulesets' in line for line in self.check(get)))
        self.rulesets[0]['rules'][0]['type'] = 42
        self.assertTrue(any('UNKNOWN' in line and '.rules' in line for line in self.check()))

    def test_actual_declaration_values_drive_comparison(self):
        self.declaration['defaults']['workflow_token']['default_workflow_permissions'] = 'write'
        self.assertTrue(any('expected "write"; observed "read"' in line for line in self.check()))

    def test_incomplete_or_duplicate_declarations_are_rejected(self):
        for mutation in (lambda d: d.update(repositories={}),
                         lambda d: d.update(defaults=None),
                         lambda d: d['defaults'].pop('repository'),
                         lambda d: d['defaults']['repository'].update(allow_merge_commit='false'),
                         lambda d: d['repositories'][self.name].update(required_checks=[]),
                         lambda d: d['repositories'][self.name].update(release_tag_patterns=['v*'])):
            value = copy.deepcopy(self.declaration)
            mutation(value)
            with self.assertRaises(ValueError):
                settings.validate_declaration(value)
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            json.loads('{"schema":1,"schema":1}', object_pairs_hook=settings.unique_object)

    def test_paginated_inventory_covers_every_member_and_reports_undeclared_repos(self):
        def get(path, **kwargs):
            organization = path.split('/')[1]
            names = [name for name in self.declaration['repositories'] if name.startswith(organization + '/')]
            return [[{'full_name': name, 'private': False, 'archived': False}] for name in names + [organization + '/new']]
        with mock.patch.object(settings, 'check_repository', return_value=[]) as check:
            findings = settings.check_online(self.declaration, get)
        self.assertEqual(check.call_count, len(self.declaration['repositories']))
        self.assertEqual(len(findings), 1)
        self.assertTrue(all('public_members' in line and '/new' in line for line in findings))

    def test_get_transport_never_mutates_and_sanitizes_errors(self):
        response = subprocess.CompletedProcess([], 0, stdout='{"enabled":true}', stderr='')
        with mock.patch.object(settings.subprocess, 'run', return_value=response) as run:
            self.assertEqual(settings.api('repos/example/tool/private-vulnerability-reporting'), {'enabled': True})
        command = run.call_args.args[0]
        self.assertEqual(command[command.index('--method') + 1], 'GET')
        self.assertNotIn('--input', command)
        response = subprocess.CompletedProcess([], 1, stdout='{"status":"403"}', stderr='secret-token-never-log')
        with mock.patch.object(settings.subprocess, 'run', return_value=response):
            with self.assertRaisesRegex(settings.Unavailable, 'HTTP 403') as failure:
                settings.api('repos/example/tool')
        self.assertNotIn('secret-token', str(failure.exception))
