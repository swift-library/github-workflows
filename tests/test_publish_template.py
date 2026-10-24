import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


# Keep test imports from creating unignored bytecode beside repository sources.
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/publish-template.py"


def load_script():
    loader = importlib.machinery.SourceFileLoader("publish_template", str(SCRIPT))
    spec = importlib.util.spec_from_loader("publish_template", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


publisher = load_script()

GENERATOR = """\
import sys
from pathlib import Path

version = Path("VERSION").read_text().strip()
template, output, mode = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
name = (template / "Package.swift").read_text().splitlines()[0]
if mode in ("guide", "extra"):
    (output / "Guide.md").write_text(f"guide {version} for {name}\\n")
if mode in ("mark", "extra"):
    (output / "logo").mkdir()
    design = Path(sys.argv[4]).joinpath("DESIGN.md").read_text().strip()
    (output / "logo/mark.txt").write_text(f"mark {version} from {design}\\n")
"""

GH = """\
import json
import os
import sys

with open(os.environ["GH_LOG"], "a") as log:
    log.write(json.dumps(sys.argv[1:]) + "\\n")
if sys.argv[1:3] == ["pr", "create"]:
    print("https://github.com/example/template/pull/1")
elif sys.argv[1] == "api":
    print(os.environ.get("AUTO_MERGE", "false"))
"""


def composition(*generators, template="example/template"):
    return {"schema": 1, "template": template, "generators": list(generators)}


def generator(mode, files, repository="example/generators"):
    command = ["python3", "generate.py", "{template}", "{output}", mode, "{declaration}"]
    return {"repository": repository, "command": command, "files": files}


GUIDE = generator("guide", {"Docs/Guide.md": "Guide.md"})
MARK = generator("mark", {"Assets/Mark.txt": "logo/mark.txt"})


class PublishTemplateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.remotes = self.root / "remotes"
        self.gh_log = self.root / "gh.log"
        key = self.root / "signing-key"
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)], check=True)
        config = self.root / "gitconfig"
        config.write_text(
            "[user]\n\tname = Example\n\temail = example@example.com\n"
            f"\tsigningkey = {key}\n[gpg]\n\tformat = ssh\n[init]\n\tdefaultBranch = master\n"
            f'[url "file://{self.remotes}/"]\n\tinsteadOf = https://github.com/\n'
        )
        bin_directory = self.root / "bin"
        bin_directory.mkdir()
        stub = bin_directory / "gh"
        stub.write_text(f"#!{sys.executable}\n{GH}")
        stub.chmod(0o755)
        self.env = {
            **os.environ, "HOME": str(self.root), "GIT_CONFIG_GLOBAL": str(config),
            "GIT_CONFIG_NOSYSTEM": "1", "GH_LOG": str(self.gh_log),
            "PATH": f"{bin_directory}{os.pathsep}{os.environ['PATH']}",
        }
        self.producer = self.repository("example/generators", {"generate.py": GENERATOR, "VERSION": "0.1.0\n"})
        self.release(self.producer, "v0.1.0", annotated=True)
        self.commit(self.producer, {"VERSION": "0.2.0\n"})
        self.release(self.producer, "v0.2.0")
        self.commit(self.producer, {"VERSION": "0.10.0\n"})
        self.release(self.producer, "v0.10.0", annotated=True)
        self.commit(self.producer, {"VERSION": "1.0.0-rc.1\n"})
        self.release(self.producer, "v1.0.0-rc.1", annotated=True)
        self.commit(self.producer, {"VERSION": "unreleased\n"})
        self.template = self.repository("example/template", {
            "Package.swift": "// example-template\n", "Docs/Guide.md": "old guide\n", "Keep.md": "kept\n",
        })
        self.declare(composition(GUIDE, MARK))

    def tearDown(self):
        self.temporary.cleanup()

    def git(self, *arguments, cwd):
        return subprocess.run(
            ["git", *arguments], cwd=cwd, env=self.env, check=True, capture_output=True, text=True,
        ).stdout

    def commit(self, checkout, files):
        for name, text in files.items():
            path = checkout / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        self.git("add", "-A", cwd=checkout)
        self.git("commit", "-q", "-m", "chore: update", cwd=checkout)
        self.git("push", "-q", "origin", "HEAD:master", cwd=checkout)

    def repository(self, name, files):
        bare = self.remotes / f"{name}.git"
        self.git("init", "-q", "--bare", str(bare), cwd=self.root)
        checkout = self.root / "checkouts" / name
        checkout.parent.mkdir(parents=True, exist_ok=True)
        self.git("clone", "-q", f"https://github.com/{name}.git", str(checkout), cwd=self.root)
        self.commit(checkout, files)
        return checkout

    def release(self, checkout, tag, *, annotated=False):
        self.git("tag", *(["-a", "-m", tag] if annotated else []), tag, cwd=checkout)
        self.git("push", "-q", "origin", tag, cwd=checkout)

    def declare(self, value, *, design="design 1"):
        files = {
            "MAINTENANCE.md": "# Maintenance\n\n<!-- template-composition -->\n```json\n"
            + json.dumps(value, indent=2) + "\n```\n",
            "DESIGN.md": design + "\n",
        }
        if hasattr(self, "declaration"):
            self.commit(self.declaration, files)
        else:
            self.declaration = self.repository("example/.github", files)

    def publish(self, *arguments, expected=0, env=None):
        result = subprocess.run(
            [sys.executable, "-B", str(SCRIPT), "--declaration", str(self.declaration),
             "--template", str(self.template), *arguments],
            env={**self.env, **(env or {})}, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result

    def gh_calls(self):
        if not self.gh_log.exists():
            return []
        return [json.loads(line) for line in self.gh_log.read_text().splitlines()]

    def test_latest_release_is_the_highest_stable_version(self):
        with mock.patch.dict(os.environ, self.env, clear=True):
            tag, commit = publisher.latest_release("https://github.com/example/generators.git")
        self.assertEqual(tag, "v0.10.0")
        self.assertEqual(commit, self.git("rev-parse", "v0.10.0^{commit}", cwd=self.producer).strip())

    def test_write_only_regenerates_declared_files_from_one_release(self):
        head = self.git("rev-parse", "HEAD", cwd=self.template)
        result = self.publish("--write-only")
        self.assertEqual(
            (self.template / "Docs/Guide.md").read_text(), "guide 0.10.0 for // example-template\n",
        )
        self.assertEqual((self.template / "Assets/Mark.txt").read_text(), "mark 0.10.0 from design 1\n")
        self.assertEqual((self.template / "Keep.md").read_text(), "kept\n")
        self.assertEqual((self.template / "Package.swift").read_text(), "// example-template\n")
        self.assertEqual(result.stdout.count("example/generators v0.10.0"), 1)
        self.assertIn("Assets/Mark.txt, Docs/Guide.md", result.stdout)
        self.assertEqual(self.git("rev-parse", "HEAD", cwd=self.template), head)
        self.assertEqual(self.gh_calls(), [])

    def test_current_template_needs_no_pull_request(self):
        self.publish("--write-only")
        self.git("add", "-A", cwd=self.template)
        self.git("commit", "-q", "-m", "chore: publish", cwd=self.template)
        self.git("push", "-q", "origin", "HEAD:master", cwd=self.template)
        result = self.publish()
        self.assertIn("example/template is current", result.stdout)
        self.assertEqual(self.gh_calls(), [])

    def test_publish_opens_one_signed_pull_request(self):
        result = self.publish()
        calls = self.gh_calls()
        self.assertEqual(len(calls), 2, calls)
        create, api = calls
        branch = create[7]
        self.assertEqual(create, [
            "pr", "create", "-R", "example/template", "--base", "master", "--head", branch,
            "--title", "chore: publish example/generators v0.10.0", "--body", create[11],
        ])
        self.assertRegex(branch, r"^chore/publish-[0-9a-f]{12}$")
        self.assertIn("| example/generators | v0.10.0 |", create[11])
        self.assertEqual(api, ["api", "repos/example/template", "--jq", ".allow_auto_merge"])
        self.assertIn("auto-merge is disabled for example/template", result.stdout)
        bare = self.remotes / "example/template.git"
        published = self.git("rev-parse", f"refs/heads/{branch}", cwd=bare).strip()
        self.assertIn("gpgsig", self.git("cat-file", "commit", published, cwd=bare))
        changed = self.git("diff", "--name-only", "master", published, cwd=bare).split()
        self.assertEqual(changed, ["Assets/Mark.txt", "Docs/Guide.md"])

    def test_publish_requests_auto_merge_when_the_template_allows_it(self):
        self.publish(env={"AUTO_MERGE": "true"})
        merge = self.gh_calls()[2]
        head = self.git("rev-parse", "HEAD", cwd=self.template).strip()
        self.assertEqual(merge, [
            "pr", "merge", "https://github.com/example/template/pull/1", "--auto", "--squash",
            "--body", "", "--match-head-commit", head,
        ])

    def test_undeclared_generated_file_fails_before_writing(self):
        self.declare(composition(generator("extra", {"Docs/Guide.md": "Guide.md"})))
        result = self.publish("--write-only", expected=1)
        self.assertIn("undeclared: logo/mark.txt", result.stderr)
        self.assertEqual((self.template / "Docs/Guide.md").read_text(), "old guide\n")

    def test_missing_generated_file_fails_before_writing(self):
        self.declare(composition(GUIDE, generator("none", {"Assets/Mark.txt": "logo/mark.txt"})))
        result = self.publish("--write-only", expected=1)
        self.assertIn("missing: logo/mark.txt", result.stderr)
        self.assertEqual((self.template / "Docs/Guide.md").read_text(), "old guide\n")

    def test_dirty_template_fails_before_generating(self):
        (self.template / "Keep.md").write_text("local edit\n")
        result = self.publish("--write-only", expected=1)
        self.assertIn("uncommitted changes", result.stderr)
        self.assertEqual((self.template / "Docs/Guide.md").read_text(), "old guide\n")

    def test_stale_template_fails_before_publishing(self):
        other = self.root / "other"
        self.git("clone", "-q", "https://github.com/example/template.git", str(other), cwd=self.root)
        self.commit(other, {"Keep.md": "newer\n"})
        result = self.publish(expected=1)
        self.assertIn("is not origin's master head", result.stderr)
        self.assertEqual(self.gh_calls(), [])

    def test_template_origin_must_match_the_declaration(self):
        self.declare(composition(GUIDE, template="example/other"))
        result = self.publish("--write-only", expected=1)
        self.assertIn("is not example/other", result.stderr)

    def test_producer_without_release_tag_fails(self):
        self.repository("example/untagged", {"generate.py": GENERATOR, "VERSION": "0\n"})
        self.declare(composition(generator("guide", {"Docs/Guide.md": "Guide.md"}, "example/untagged")))
        result = self.publish("--write-only", expected=1)
        self.assertIn("no vMAJOR.MINOR.PATCH release tag", result.stderr)

    def test_symlinked_destination_fails_before_writing(self):
        (self.template / "Docs/Guide.md").unlink()
        (self.template / "Docs/Guide.md").symlink_to(self.root / "outside.md")
        self.git("add", "-A", cwd=self.template)
        self.git("commit", "-q", "-m", "chore: link", cwd=self.template)
        result = self.publish("--write-only", expected=1)
        self.assertIn("symbolic link", result.stderr)
        self.assertFalse((self.root / "outside.md").exists())

    def test_composition_must_be_well_formed(self):
        cases = {
            "unknown placeholder": composition({**GUIDE, "command": ["python3", "{source}"]}),
            "parent path": composition({**GUIDE, "files": {"../Guide.md": "Guide.md"}}),
            "unnormalized path": composition({**GUIDE, "files": {"./Guide.md": "Guide.md"}}),
            "git path": composition({**GUIDE, "files": {".git/config": "Guide.md"}}),
            "duplicate target": composition(GUIDE, {**MARK, "files": {"Docs/Guide.md": "logo/mark.txt"}}),
            "missing key": {"schema": 1, "template": "example/template"},
            "extra key": composition({**GUIDE, "path": "x"}),
            "bad repository": composition({**GUIDE, "repository": "generators"}),
            "empty command": composition({**GUIDE, "command": []}),
            "unknown schema": {**composition(GUIDE), "schema": 2},
        }
        for name, value in cases.items():
            with self.subTest(name):
                with self.assertRaises(publisher.PublishError):
                    publisher.validate_composition(value)
        publisher.validate_composition(composition(GUIDE, MARK))

    def test_duplicate_json_key_is_rejected(self):
        maintenance = self.declaration / "MAINTENANCE.md"
        maintenance.write_text(maintenance.read_text().replace('"schema": 1,', '"schema": 1,\n  "schema": 1,'))
        with self.assertRaisesRegex(publisher.PublishError, "duplicate key 'schema'"):
            publisher.load_composition(self.declaration)


if __name__ == "__main__":
    unittest.main()
