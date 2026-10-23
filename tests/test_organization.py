import contextlib
import copy
from http.client import IncompleteRead
import importlib.machinery
import importlib.util
import io
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import traceback
import unittest
from unittest import mock
from urllib.error import URLError


# Keep test imports from creating unignored bytecode beside repository sources.
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]


def load_script(name, filename):
    loader = importlib.machinery.SourceFileLoader(name, str(ROOT / "scripts" / filename))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


checks = load_script("profile_checks", "check-organization.py")


def committed_catalog():
    return json.loads((ROOT / "fixtures/organization/profile/catalog.json").read_text(encoding="utf-8"))


def repository(name, *, archived=False, private=False, fork=False):
    return {"name": name, "archived": archived, "private": private, "fork": fork}


class Response(io.BytesIO):
    def __init__(self, payload, link=""):
        super().__init__(json.dumps(payload).encode("utf-8"))
        self.headers = {"Link": link}


class MembershipTests(unittest.TestCase):
    def setUp(self):
        self.catalog = committed_catalog()
        self.repositories = [
            repository(item["name"])
            for group in self.catalog["groups"] for item in group["repositories"]
        ]

    def test_matching_membership_excludes_archived_private_forks_and_profile(self):
        checks.compare_membership(self.catalog, self.repositories + [
            repository(".github"), repository("old", archived=True), repository("secret", private=True),
            repository("upstream", fork=True),
        ])

    def test_missing_and_extra_are_reported_together(self):
        expected_extra = self.repositories[0]["name"]
        with self.assertRaisesRegex(
            ValueError, f"missing from catalog: alpha, zeta; extra in catalog: {expected_extra}"
        ):
            checks.compare_membership(self.catalog, self.repositories[1:] + [repository("zeta"), repository("alpha")])

    def test_archived_or_profile_in_catalog_is_extra(self):
        for name, archived in (("old", True), (".github", False)):
            with self.subTest(name=name):
                catalog = copy.deepcopy(self.catalog)
                catalog["groups"][0]["repositories"].append({"name": name, "outcome": "Example.", "icon": "https://example.test/icon.svg"})
                with self.assertRaisesRegex(ValueError, "extra in catalog: " + re.escape(name)):
                    checks.compare_membership(catalog, self.repositories + [repository(name, archived=archived)])

    def test_fork_in_catalog_is_extra(self):
        catalog = copy.deepcopy(self.catalog)
        catalog["groups"][0]["repositories"].append({"name": "upstream", "outcome": "Example.", "icon": "https://example.test/icon.svg"})
        with self.assertRaisesRegex(ValueError, "extra in catalog: upstream"):
            checks.compare_membership(catalog, self.repositories + [repository("upstream", fork=True)])

    def test_pagination_and_authorization_with_injected_responses(self):
        first = "https://api.github.com/orgs/example-org/repos?type=public&per_page=100"
        second = first + "&page=2"
        opener = mock.Mock(side_effect=[
            Response(self.repositories[:1], f'<{second}>; rel="last", <{second}>; rel="next"'),
            Response(self.repositories[1:] + [repository(".github")]),
        ])
        fetched = checks.fetch_repositories("example-org", "test-token", opener=opener)
        checks.compare_membership(self.catalog, fetched)
        self.assertEqual(len(fetched), len(self.repositories) + 1)
        self.assertEqual([call.args[0].full_url for call in opener.call_args_list], [first, second])
        for call in opener.call_args_list:
            self.assertEqual(call.args[0].get_header("Authorization"), "Bearer test-token")
            self.assertEqual(call.kwargs, {"timeout": 30})

    def test_no_authorization_header_without_token(self):
        opener = mock.Mock(return_value=Response([]))
        self.assertEqual(checks.fetch_repositories("example-org", opener=opener), [])
        self.assertIsNone(opener.call_args.args[0].get_header("Authorization"))

    def test_api_failure_is_explicit(self):
        opener = mock.Mock(side_effect=URLError("unreachable"))
        with self.assertRaisesRegex(ValueError, "^could not read GitHub API: request or response failed$"):
            checks.fetch_repositories("example-org", opener=opener)

    def test_interrupted_response_is_reported_as_api_failure(self):
        response = Response([])
        response.read = mock.Mock(side_effect=IncompleteRead(b"[", 12))
        with self.assertRaisesRegex(ValueError, "^could not read GitHub API: request or response failed$"):
            checks.fetch_repositories("example-org", opener=mock.Mock(return_value=response))

    def test_request_exception_traceback_does_not_echo_headers(self):
        token = "test-token-never-log"
        for failure in (
            ValueError(f"Invalid header value {('Bearer ' + token).encode()!r}"),
            URLError(f"Authorization: Bearer {token}"),
            IncompleteRead(token.encode(), 12),
        ):
            with self.subTest(failure=type(failure).__name__):
                opener = mock.Mock(side_effect=failure)
                try:
                    checks.fetch_repositories("example-org", token, opener=opener)
                except ValueError as error:
                    formatted = "".join(traceback.format_exception(type(error), error, error.__traceback__))
                    self.assertNotIn(token, formatted)
                    self.assertNotIn("Authorization", formatted)
                    self.assertIn("could not read GitHub API: request or response failed", formatted)
                else:
                    self.fail("Expected a safe request failure")

    def test_invalid_api_payloads_fail(self):
        for payload in ({"message": "error"}, [None], [{"name": "missing-flags"}]):
            with self.subTest(payload=payload):
                with self.assertRaisesRegex(ValueError, "invalid repository list"):
                    checks.fetch_repositories("example-org", opener=mock.Mock(return_value=Response(payload)))

    def test_pagination_rejects_external_endpoint_and_cycles(self):
        for url, message in (
            ("https://example.com/repos", "outside the repository endpoint"),
            ("https://api.github.com/orgs/example-org/repos?type=public&per_page=100", "repeated a page"),
        ):
            with self.subTest(url=url):
                opener = mock.Mock(return_value=Response([], f'<{url}>; rel="next"'))
                with self.assertRaisesRegex(ValueError, message):
                    checks.fetch_repositories("example-org", "test-token", opener=opener)
                self.assertEqual(opener.call_count, 1)


class AboutTests(unittest.TestCase):
    def setUp(self):
        self.catalog = committed_catalog()
        self.repositories = [
            {**repository(entry["name"]), "description": entry["about"]}
            for group in self.catalog["groups"] for entry in group["repositories"]
        ] + [{**repository(".github"), "description": self.catalog["organization"]["about"]}]

    def test_live_descriptions_match_every_catalog_about(self):
        checks.compare_about(self.catalog, self.repositories)

    def test_all_differences_include_the_organization(self):
        for entry in self.repositories:
            entry["description"] = "Different."
        with self.assertRaises(ValueError) as failure:
            checks.compare_about(self.catalog, self.repositories)
        message = str(failure.exception)
        for entry in self.repositories:
            self.assertIn(entry["name"] + ": catalog ", message)
        self.assertEqual(message.count("live 'Different.'"), len(self.repositories))

    def test_missing_repository_description_or_about_fails(self):
        for change, expected in (
            (lambda: self.repositories.pop(), ".github: live repository is missing"),
            (lambda: self.repositories[-1].pop("description"), ".github: live description is unavailable"),
            (lambda: self.repositories[-1].update(description=None), "live None"),
            (lambda: self.catalog["organization"].pop("about"), ".github: catalog about is missing"),
        ):
            with self.subTest(expected=expected):
                self.setUp()
                change()
                with self.assertRaisesRegex(ValueError, re.escape(expected)):
                    checks.compare_about(self.catalog, self.repositories)

    def test_comparison_is_verbatim(self):
        self.repositories[-1]["description"] += " "
        with self.assertRaises(ValueError):
            checks.compare_about(self.catalog, self.repositories)


class CatalogReadTests(unittest.TestCase):
    def setUp(self):
        self.root = ROOT / ".build/test-catalog"
        (self.root / "profile").mkdir(parents=True)
        self.addCleanup(shutil.rmtree, self.root)

    def test_read_only_needs_membership_fields(self):
        value = {"organization": {"login": "example"}, "groups": [
            {"repositories": [{"name": "tool"}]}
        ]}
        (self.root / "profile/catalog.json").write_text(json.dumps(value))
        self.assertEqual(checks.read_catalog(self.root), value)

    def test_unreadable_membership_fields_fail(self):
        for value in (None, {}, {"organization": {"login": "example"}, "groups": {}},
                      {"organization": {"login": "example"}, "groups": [{"repositories": [None]}]},
                      {"organization": {"login": "example"}, "groups": [{"repositories": [{"name": 1}]}]}):
            with self.subTest(value=value):
                (self.root / "profile/catalog.json").write_text(json.dumps(value))
                with self.assertRaises(ValueError):
                    checks.read_catalog(self.root)


class OrganizationCLITests(unittest.TestCase):
    def test_mismatched_organization_reports_rejection(self):
        result = subprocess.run([
            sys.executable, str(ROOT / 'scripts/check-organization.py'),
            '--declaration-root', str(ROOT / 'fixtures/organization'), '--organization', 'fixture-other-org',
            '--catalog-repository', 'example-org/standard', '--mode', 'public',
        ], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(result.stdout.strip(),
                         'FAIL organization: Catalog organization differs from the requested organization')
