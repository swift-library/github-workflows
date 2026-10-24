#!/usr/bin/env python3
"""Publish a template repository's generated files from its producers' latest releases."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile


BLOCK = re.compile(r"<!-- template-composition -->\s*```json\n(.*?)\n```", re.S)
REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
RELEASE = re.compile(r"v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)")
PLACEHOLDER = re.compile(r"\{([a-z]+)\}")
PLACEHOLDERS = frozenset({"template", "output", "declaration"})
GITHUB_URL = re.compile(
    r"(?:https://github\.com/|ssh://git@github\.com/|git@github\.com:)"
    r"(?P<repository>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?/?"
)


class PublishError(Exception):
    pass


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise PublishError(f"template composition: duplicate key {key!r}")
        result[key] = value
    return result


def relative_path(value, label):
    if not isinstance(value, str) or not value:
        raise PublishError(f"{label}: expected a relative path")
    path = Path(value)
    # Case-insensitive file systems resolve .GIT to the repository metadata too.
    if (path.is_absolute() or ".." in path.parts or path.as_posix() != value
            or any(part.casefold() == ".git" for part in path.parts)):
        raise PublishError(f"{label}: {value!r} must be a normalized path inside the repository")
    return path


def validate_composition(value):
    if not isinstance(value, dict) or set(value) != {"schema", "template", "generators"} or value["schema"] != 1:
        raise PublishError("template composition: expected schema 1 with template and generators")
    if not isinstance(value["template"], str) or not REPOSITORY.fullmatch(value["template"]):
        raise PublishError("template composition: template must be owner/name")
    generators = value["generators"]
    if not isinstance(generators, list) or not generators:
        raise PublishError("template composition: generators must be a nonempty list")
    # Keyed by case-folded path so that declarations stay distinct on case-insensitive file systems.
    targets = {}
    for index, generator in enumerate(generators):
        label = f"generators[{index}]"
        if not isinstance(generator, dict) or set(generator) != {"repository", "command", "files"}:
            raise PublishError(f"{label}: expected repository, command and files")
        if not isinstance(generator["repository"], str) or not REPOSITORY.fullmatch(generator["repository"]):
            raise PublishError(f"{label}.repository: expected owner/name")
        command = generator["command"]
        if not isinstance(command, list) or not command or not all(isinstance(arg, str) and arg for arg in command):
            raise PublishError(f"{label}.command: expected a nonempty list of arguments")
        unknown = {name for arg in command for name in PLACEHOLDER.findall(arg)} - PLACEHOLDERS
        if unknown:
            raise PublishError(f"{label}.command: unknown placeholders {sorted(unknown)}")
        files = generator["files"]
        if not isinstance(files, dict) or not files:
            raise PublishError(f"{label}.files: expected a nonempty map of template path to generated path")
        for target, produced in files.items():
            relative_path(target, f"{label}.files")
            relative_path(produced, f"{label}.files[{target!r}]")
            if target.casefold() in targets:
                raise PublishError(f"{label}.files: {target!r} is declared more than once, ignoring case")
            targets[target.casefold()] = target
    for folded, target in targets.items():
        for parent in Path(folded).parents:
            if parent.as_posix() in targets:
                raise PublishError(
                    f"template composition: {target!r} is inside the declared file {targets[parent.as_posix()]!r}"
                )


def load_composition(root):
    try:
        text = (root / "MAINTENANCE.md").read_text(encoding="utf-8")
    except OSError as error:
        raise PublishError(f"{root}: cannot read MAINTENANCE.md: {error}") from error
    blocks = BLOCK.findall(text)
    if len(blocks) != 1:
        raise PublishError("MAINTENANCE.md must contain one template-composition JSON block")
    try:
        value = json.loads(blocks[0], object_pairs_hook=unique_object)
    except ValueError as error:
        raise PublishError(f"template composition: {error}") from error
    validate_composition(value)
    return value


def run(arguments, *, cwd=None):
    result = subprocess.run(arguments, cwd=cwd, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if result.returncode:
        raise PublishError(f"{shlex.join(map(str, arguments))} exited {result.returncode}: {result.stderr.strip()}")
    return result.stdout


def git(*arguments, cwd=None):
    return run(["git", *arguments], cwd=cwd)


def gh(*arguments):
    return run(["gh", *arguments])


def source_url(repository):
    return f"https://github.com/{repository}.git"


def latest_release(url):
    """Return the highest vMAJOR.MINOR.PATCH tag and the commit it names."""
    commits = {}
    for line in git("ls-remote", "--tags", url, "refs/tags/v*").splitlines():
        commit, _, ref = line.partition("\t")
        name = ref.removeprefix("refs/tags/")
        peeled = name.endswith("^{}")
        name = name.removesuffix("^{}")
        # An annotated tag lists its tag object first and then the peeled commit.
        if RELEASE.fullmatch(name) and (peeled or name not in commits):
            commits[name] = commit
    if not commits:
        raise PublishError(f"{url}: no vMAJOR.MINOR.PATCH release tag")
    tag = max(commits, key=lambda name: tuple(map(int, RELEASE.fullmatch(name).groups())))
    return tag, commits[tag]


def fetch_release(url, tag, commit, destination):
    git("-c", "advice.detachedHead=false", "clone", "--quiet", "--depth", "1", "--branch", tag, url, str(destination))
    head = git("rev-parse", "HEAD", cwd=destination).strip()
    if head != commit:
        raise PublishError(f"{url} {tag}: checked out {head}, expected {commit}")


def generate(generator, source, values, output):
    arguments = [
        PLACEHOLDER.sub(lambda match: str(values[match.group(1)]), argument)
        for argument in generator["command"]
    ]
    run(arguments, cwd=source)
    produced = {
        path.relative_to(output).as_posix()
        for path in output.rglob("*") if path.is_file() or path.is_symlink()
    }
    expected = set(generator["files"].values())
    if produced != expected:
        missing = ", ".join(sorted(expected - produced)) or "none"
        undeclared = ", ".join(sorted(produced - expected)) or "none"
        raise PublishError(
            f"{generator['repository']}: generated files differ from the declaration "
            f"(missing: {missing}; undeclared: {undeclared})"
        )
    for produced_path in expected:
        if (output / produced_path).is_symlink():
            raise PublishError(f"{generator['repository']}: {produced_path} is a symbolic link")


def check_destinations(template, targets):
    root = template.resolve()
    for target in targets:
        destination = template / target
        for relative in (Path(target), *Path(target).parents):
            if (template / relative).is_symlink():
                raise PublishError(f"{destination}: path crosses a symbolic link")
        for parent in Path(target).parents:
            if (template / parent).exists() and not (template / parent).is_dir():
                raise PublishError(f"{destination}: {template / parent} must be a directory")
        if not destination.resolve().is_relative_to(root):
            raise PublishError(f"{destination}: must stay inside {template}")
        if destination.exists() and not destination.is_file():
            raise PublishError(f"{destination}: must be a regular file")


def differences(template, files, output):
    return sorted(
        target for target, produced in files.items()
        if not (template / target).is_file()
        or (template / target).read_bytes() != (output / produced).read_bytes()
    )


def write(template, files, output, targets):
    for target in targets:
        destination = template / target
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((output / files[target]).read_bytes())


def require_clean(checkout):
    if git("status", "--porcelain", "--untracked-files=all", cwd=checkout):
        raise PublishError(f"{checkout}: working tree has uncommitted changes")


def remote_default(checkout):
    branch = commit = None
    for line in git("ls-remote", "--symref", "origin", "HEAD", cwd=checkout).splitlines():
        value, _, ref = line.partition("\t")
        if ref != "HEAD":
            continue
        if value.startswith("ref: refs/heads/"):
            branch = value.removeprefix("ref: refs/heads/")
        else:
            commit = value
    if not branch or not commit:
        raise PublishError(f"{checkout}: cannot read the default branch of origin")
    return branch, commit


def require_current(checkout):
    branch, commit = remote_default(checkout)
    head = git("rev-parse", "HEAD", cwd=checkout).strip()
    if head != commit:
        raise PublishError(f"{checkout}: HEAD {head} is not origin's {branch} head {commit}")


def require_origin(checkout, repository):
    """Require every URL origin fetches from or pushes to, after rewriting, to be the template on GitHub."""
    urls = (git("remote", "get-url", "--all", "origin", cwd=checkout).splitlines()
            + git("remote", "get-url", "--push", "--all", "origin", cwd=checkout).splitlines())
    for url in urls:
        match = GITHUB_URL.fullmatch(url)
        if match is None or match["repository"].lower() != repository.lower():
            raise PublishError(f"{checkout}: origin uses {url}, which is not github.com/{repository}")


def publication_branch(declaration_commit, sources):
    digest = hashlib.sha256(
        "\n".join([declaration_commit, *(f"{name} {commit}" for name, (_, commit) in sorted(sources.items()))]).encode()
    ).hexdigest()
    return "chore/publish-" + digest[:12]


def existing_branch(template, branch):
    """Return whether the publication branch exists in the template checkout and on origin."""
    local = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"], cwd=template,
        capture_output=True, stdin=subprocess.DEVNULL,
    ).returncode == 0
    remote = bool(git("ls-remote", "--heads", "origin", f"refs/heads/{branch}", cwd=template).strip())
    return local, remote


def start_over(template, base, branch):
    """Describe how to delete a publication branch so that the same command publishes again."""
    local, remote = existing_branch(template, branch)
    checkout = shlex.quote(str(template))
    commands = []
    if local:
        commands += [f"git -C {checkout} switch {shlex.quote(base)}", f"git -C {checkout} branch -D {branch}"]
    if remote:
        commands.append(f"git -C {checkout} push origin --delete {branch}")
    return "Delete the publication branch, then run the same command again:\n" + "\n".join(
        f"  {command}" for command in commands
    )


def pull_request_text(sources, declaration_commit, changed):
    title = "chore: publish " + ", ".join(f"{name} {sources[name][0]}" for name in sources if changed[name])
    rows = "\n".join(
        f"| {name} | {tag} | `{commit}` | "
        + (", ".join(f"`{path}`" for path in changed[name]) or "none")
        + " |"
        for name, (tag, commit) in sources.items()
    )
    body = (
        f"Generated files from each producer's latest release, as declared at `{declaration_commit}`.\n\n"
        "| Producer | Release | Commit | Changed files |\n| --- | --- | --- | --- |\n"
        f"{rows}\n\n"
        "Generated paths are changed in their producer and arrive through its next release.\n"
    )
    return title, body


def pull_request(template, repository, base, branch, title, body):
    head = git("rev-parse", "HEAD", cwd=template).strip()
    try:
        git("push", "--quiet", "origin", f"HEAD:refs/heads/{branch}", cwd=template)
        url = gh("pr", "create", "-R", repository, "--base", base, "--head", branch,
                 "--title", title, "--body", body).strip()
    except PublishError as error:
        raise PublishError(f"{error}\n{start_over(template, base, branch)}") from error
    print(url)
    if gh("api", f"repos/{repository}", "--jq", ".allow_auto_merge").strip() != "true":
        print(f"auto-merge is disabled for {repository}; merge after the required checks pass")
        return
    try:
        gh("pr", "merge", url, "--auto", "--squash", "--body", "", "--match-head-commit", head)
    except PublishError as error:
        raise PublishError(f"{error}\n{url} is open; merge it after the required checks pass") from error
    print("auto-merge requested")


def publish(declaration, template, *, write_only=False):
    composition = load_composition(declaration)
    repository = composition["template"]
    generators = composition["generators"]
    require_clean(declaration)
    require_clean(template)
    require_origin(template, repository)
    if not write_only:
        require_current(declaration)
    declaration_commit = git("rev-parse", "HEAD", cwd=declaration).strip()
    # Every generator from one repository runs from that repository's single release.
    sources = {name: latest_release(source_url(name)) for name in dict.fromkeys(g["repository"] for g in generators)}
    for name, (tag, commit) in sources.items():
        print(f"{name} {tag} {commit}")
    if not write_only:
        branch = publication_branch(declaration_commit, sources)
        base, _ = remote_default(template)
        if any(existing_branch(template, branch)):
            raise PublishError(
                f"branch {branch} already exists: these releases were published before. "
                + start_over(template, base, branch)
            )
        require_current(template)
    check_destinations(template, [target for generator in generators for target in generator["files"]])
    with tempfile.TemporaryDirectory(prefix="publish-template-") as temporary:
        root = Path(temporary)
        checkouts = {name: root / f"source-{index}" for index, name in enumerate(sources)}
        for name, checkout in checkouts.items():
            fetch_release(source_url(name), *sources[name], checkout)
        outputs = []
        for index, generator in enumerate(generators):
            output = root / f"output-{index}"
            output.mkdir()
            generate(generator, checkouts[generator["repository"]], {
                "template": template.resolve(), "output": output, "declaration": declaration.resolve(),
            }, output)
            outputs.append(output)
        pending = [differences(template, generator["files"], output) for generator, output in zip(generators, outputs)]
        for generator, output, targets in zip(generators, outputs, pending):
            write(template, generator["files"], output, targets)
    changed = {name: [] for name in sources}
    for generator, targets in zip(generators, pending):
        changed[generator["repository"]] += targets
    changed = {name: sorted(paths) for name, paths in changed.items()}
    for name in sources:
        print(f"{name}: " + (", ".join(changed[name]) or "current"))
    if not any(changed.values()):
        print(f"{repository} is current")
        return 0
    if write_only:
        return 0
    title, body = pull_request_text(sources, declaration_commit, changed)
    git("switch", "--quiet", "-c", branch, cwd=template)
    git("add", "--", *[path for paths in changed.values() for path in paths], cwd=template)
    git("commit", "--quiet", "-S", "-m", title, "-m",
        "\n".join(f"{name} {tag} {commit}" for name, (tag, commit) in sources.items()), cwd=template)
    pull_request(template, repository, base, branch, title, body)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--declaration", type=Path, required=True,
        help="checkout of the repository whose MAINTENANCE.md declares the template composition",
    )
    parser.add_argument("--template", type=Path, required=True, help="checkout of the template repository")
    parser.add_argument(
        "--write-only", action="store_true",
        help="write the generated files into the template checkout without a commit or pull request",
    )
    args = parser.parse_args(argv)
    try:
        return publish(args.declaration, args.template, write_only=args.write_only)
    except (PublishError, OSError) as error:
        print(f"publish-template: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
