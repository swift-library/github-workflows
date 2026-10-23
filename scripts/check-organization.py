#!/usr/bin/env python3
"""Validate local standards, public membership and declared GitHub settings."""

import argparse
from http.client import HTTPException
import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / "scripts"))
import settings


def read_catalog(root=ROOT):
    """Read the fields needed for membership; the profile workflow owns the schema."""
    catalog = json.loads((root / "profile/catalog.json").read_text(encoding="utf-8"))
    try:
        login = catalog["organization"]["login"]
        groups = catalog["groups"]
        if not isinstance(login, str) or not login or not isinstance(groups, list):
            raise ValueError("expected organization.login and groups")
        for group in groups:
            entries = group["repositories"]
            if not isinstance(entries, list):
                raise ValueError("expected group repositories")
            for entry in entries:
                if not isinstance(entry["name"], str) or not entry["name"]:
                    raise ValueError("expected repository name")
    except (KeyError, TypeError) as error:
        raise ValueError("cannot read catalog membership fields") from error
    return catalog


def fetch_repositories(organization, token=None, *, opener=urlopen):
    if token and any(character.isspace() or not character.isprintable() for character in token):
        raise ValueError("GITHUB_TOKEN must not contain whitespace or control characters")
    endpoint = f"https://api.github.com/orgs/{quote(organization, safe='')}/repos"
    url = endpoint + "?type=public&per_page=100"
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "organization-profile-check"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    repositories = []
    visited = set()
    while url:
        if url in visited:
            raise ValueError("GitHub API pagination repeated a page")
        visited.add(url)
        try:
            with opener(Request(url, headers=headers), timeout=30) as response:
                page = json.load(response)
                links = response.headers.get("Link", "")
        except (HTTPException, OSError, ValueError):
            # Request exceptions can contain authorization headers.
            raise ValueError("could not read GitHub API: request or response failed") from None
        if not isinstance(page, list) or any(
            not isinstance(repository, dict)
            or not isinstance(repository.get("name"), str)
            or not repository["name"]
            or not isinstance(repository.get("archived"), bool)
            or not isinstance(repository.get("private"), bool)
            or not isinstance(repository.get("fork"), bool)
            for repository in page
        ):
            raise ValueError("GitHub API returned an invalid repository list")
        repositories.extend(page)
        next_link = re.search(r'<([^>]+)>;\s*rel="next"', links)
        url = next_link.group(1) if next_link else None
        if url:
            parsed = urlsplit(url)
            if (parsed.scheme, parsed.netloc, parsed.path) != (
                "https", "api.github.com", urlsplit(endpoint).path
            ):
                raise ValueError("GitHub API pagination points outside the repository endpoint")
    return repositories


def compare_membership(catalog, repositories, standard_repository=".github"):
    # Forks are upstream source lines, not the organization's own products.
    expected = {
        repository["name"]
        for repository in repositories
        if not repository["private"]
        and not repository["archived"]
        and not repository["fork"]
        and repository["name"] != standard_repository
    }
    actual = {
        repository["name"]
        for group in catalog["groups"]
        for repository in group["repositories"]
    }
    differences = []
    if expected - actual:
        differences.append("missing from catalog: " + ", ".join(sorted(expected - actual)))
    if actual - expected:
        differences.append("extra in catalog: " + ", ".join(sorted(actual - expected)))
    if differences:
        raise ValueError("; ".join(differences))


def compare_about(catalog, repositories, standard_repository=".github"):
    live = {repository["name"]: repository for repository in repositories}
    entries = [(standard_repository, catalog["organization"])] + [
        (entry["name"], entry) for group in catalog["groups"] for entry in group["repositories"]
    ]
    differences = []
    for name, entry in entries:
        if not isinstance(entry.get("about"), str) or not entry["about"]:
            differences.append(f"{name}: catalog about is missing or invalid")
        elif name not in live:
            differences.append(f"{name}: live repository is missing")
        elif "description" not in live[name]:
            differences.append(f"{name}: live description is unavailable")
        elif entry["about"] != live[name]["description"]:
            differences.append(f"{name}: catalog {entry['about']!r}; live {live[name]['description']!r}")
    if differences:
        raise ValueError("; ".join(differences))


def main(argv=None, *, root=ROOT):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=root)
    parser.add_argument('--organization', required=True)
    parser.add_argument('--standard-repository', required=True)
    parser.add_argument('--members', default='all', help='all or newline-separated repository names')
    parser.add_argument('--mode', choices=('public', 'online'), default='public')
    args = parser.parse_args(argv)
    try:
        catalog = read_catalog(args.root)
        declaration = settings.load_declaration(args.root)
        if catalog['organization']['login'] != args.organization:
            raise ValueError('Catalog organization differs from the requested organization')
        prefix = args.organization + '/'
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', args.standard_repository):
            raise ValueError('Expected a standard owner/repository identity')
        standard = args.standard_repository.split('/')[1]
        selected = None if args.members == 'all' else set(args.members.split())
        if selected is not None:
            selected = {name if '/' in name else prefix + name for name in selected}
            if not selected or not selected <= declaration['repositories'].keys():
                raise ValueError('Member selection contains an undeclared repository')
        live = fetch_repositories(args.organization, os.environ.get('GITHUB_TOKEN'))
        # Membership is always checked against the complete inventory. Selection
        # restricts About and administrative observations, never hides new members.
        compare_membership(catalog, live, standard)
        print('PASS repository membership')
        if selected is not None:
            catalog = {**catalog, 'groups': [
                {**group, 'repositories': [item for item in group['repositories'] if prefix + item['name'] in selected]}
                for group in catalog['groups']]}
        compare_about(catalog, live, standard)
        print('PASS repository about')
        if args.mode == 'public':
            return 0
        findings = settings.check_online(declaration) if selected is None else [
            finding for name, member in declaration['repositories'].items() if name in selected
            for finding in settings.check_repository(name, member, declaration)]
        for finding in findings:
            print(finding)
        if any(finding.startswith('UNKNOWN ') for finding in findings):
            return 2
        return int(any(finding.startswith(('DRIFT ', 'GAP ')) for finding in findings))
    except (OSError, ValueError, KeyError, TypeError) as error:
        print('FAIL organization: ' + ' '.join(str(error).splitlines()))
        return 1


if __name__ == '__main__':
    sys.exit(main())
