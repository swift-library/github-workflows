# Shared GitHub workflows

Reusable validation, source policy, release publication and organization checks
for Swift packages, and publication of a package template. Required member checks are exactly **`policy / policy`** and
**`validate / result`**.

## Job catalog

| Workflow / job | Behavior |
| --- | --- |
| `swift-package.yml` / `configure` | Schema-validates `.github/swift-package.json` and emits matrices. Unknown or duplicate keys fail. |
| `compiler` | Each compiler runs every test configuration and one release build with default traits. The first compiler also tests each additional trait set in every test configuration, with no additional release build. Verifies the selected Swift version. |
| `format` | Strict recursive Swift formatting using the repository's `.swift-format`, on the last compiler. |
| `linux` | Runs every test configuration with default traits in each digest-pinned Swift Docker image. |
| `apple` | Builds each generic iOS, tvOS, watchOS or visionOS destination, skipping plugin and macro validation for non-interactive CI. Optional tests use the SDK-matching simulator runtime, downloading it only when the runner lacks it, and create/delete a matching simulator. |
| `docs` | Builds the whole package once, emitting public symbol graphs with extension blocks, then converts each target's DocC archive with warnings as errors. |
| `demo` | Builds the release executable and checks a fresh terminal recording through the presentation action's recording-only mode. |
| `commands` | Runs each repository command in its own job in the member checkout. |
| `result` | Requires every declared job to succeed. Only undeclared optional jobs may be skipped; failures and cancellation fail the aggregate. |
| `policy.yml` / `policy` | Checks commit verification/identity, Conventional Commit messages and PR title, attribution, added lines, private paths and permitted product terms. Validates version declarations when `.github/release.json` exists. |
| `swift-package-release.yml` / `verify`, `publish` | Verifies the accepted commit and signed annotated tag; validates version/changelog; publishes notes without assets. Only `publish` writes contents. |
| `organization.yml` / `organization` | Compares catalog membership, About descriptions and, in online mode, declared repository settings. All API requests are reads. |

## Configuration

`swift-package.yml` has no inputs. The configuration is in the caller checkout.
See [the JSON Schema](schemas/swift-package.schema.json).

| Key | Meaning / default |
| --- | --- |
| `compilers` (required) | Nonempty `{name, runner, xcode, swift?}` array, with the minimum compiler first by convention. Xcode must be installed on the runner. `swift` installs an official release after selecting Xcode. |
| `format` | `{paths}`; defaults to `Package.swift`, `Sources`, `Tests`, relative to the package directory. `.swift-format` lives at the repository root. |
| `package_directory` | Package root inside the repository; default `.`. |
| `test_configurations` | Nonempty list of `debug` and/or `release`; default `["debug"]`. |
| `build_system` | `native` or `xcode`, passed to SwiftPM commands. Omission uses SwiftPM's default. |
| `traits` | Additional trait sets tested in every test configuration on the first compiler only, e.g. `[["default"], [], ["Experimental", "default"]]`. `default` enables SwiftPM default traits; an empty set disables them. Omission means no additional sets. |
| `environment` | String map exported to validation commands. The terminal script declares its own sandbox environment. |
| `platforms.linux` | Nonempty array of `{name, image}` with `@sha256:<64 hex digits>` image references. Tests use default traits only. |
| `platforms.apple` | Nonempty array of `{name, platform, scheme, test?, runner?, xcode?}`. Platform is `iOS`, `tvOS`, `watchOS` or `visionOS`; test defaults to false. |
| `docs` | `{targets, traits?}` for packages shipping DocC. Catalogs live under each target path reported by SwiftPM. `traits` is one trait set for the documentation build, e.g. `["Experimental", "default"]`; omission uses default traits. |
| `demo` | `{product, script?}`; script defaults to `.github/assets/terminal/script.yml`, relative to the repository. `recording.json` and optional `fixture/` live beside the script. |
| `commands` | Nonempty `{name, run, runner?, xcode?}` array. Shell is Bash with `-euo pipefail`. Put repository checks in lowercase `scripts/`. |
| `timeout_minutes` | Integer from 1 through 360; default 45. |

Apple and command entries default to the last compiler's runner and toolchain.
An explicit Xcode override uses that Xcode's bundled Swift. Docs and demo also
use the last compiler. Package and script paths must stay inside the checkout.

Every macOS `swift build` and `swift test` invocation uses `--disable-index-store`
alongside any configured build-system flags; CI does not use the index. Linux
keeps the index store because XCTest discovers tests through it.

The documentation build emits graphs for library and executable modules.
Each declared target's DocC conversion receives only its main graph and
extension graphs. A missing main graph fails the job and names the target.

When `release.json` exists, the lowest actual compiler must match its
`minimum_swift` (major/minor declarations accept patch updates). Each compiler
reports its selected version; the aggregate checks all compiler identities and
the minimum. Names are labels and may be arbitrary. An explicit `swift` version
is also checked against the selected compiler. These one-day CI artifacts only
transfer compiler versions between jobs; the release workflow never reads or
publishes them.

```json
{
  "compilers": [
    {"name": "macos-26-swift-6.3", "runner": "macos-26", "xcode": "26.6"}
  ],
  "commands": [{"name": "specification", "run": "scripts/check-spec"}]
}
```

## Calling validation and policy

```yaml
name: CI
on:
  push:
  pull_request:
    types: [opened, edited, synchronize, reopened]
permissions:
  contents: read
  actions: read
jobs:
  policy:
    uses: swift-library/github-workflows/.github/workflows/policy.yml@<full-sha> # vX.Y.Z
    with:
      allow-terms: ''
      dependabot-exception: false
  validate:
    uses: swift-library/github-workflows/.github/workflows/swift-package.yml@<full-sha> # vX.Y.Z
```

`allow-terms` is a newline-separated, case-insensitive product-name allowlist.
It does not exempt attribution or private execution paths. The optional
Dependabot exception permits only its exact signoff after GitHub authenticates
the verified bot author and web-flow signer. Policy retains the family owner
identity `10173746+showxu@users.noreply.github.com` and GitHub's web committer.

## Calling release

Keep `.github/release.json` with `repository`, `version_file`, `version_pattern`,
`changelog`, `minimum_swift` and `platforms`. `version_pattern` must extract one
SemVer declaration. Changelog entries use `## X.Y.Z` with nonempty notes. The
signed annotated tag is `vX.Y.Z` and its message is `<repository-name> X.Y.Z`.
The tagger is the family owner; GitHub verification and the owner's signing
keys authenticate the signature. The same accepted commit is checked again
immediately before publication.

```yaml
name: Release
on:
  push:
    tags: ['v*']
permissions:
  contents: read
  actions: read
jobs:
  validate:
    uses: swift-library/github-workflows/.github/workflows/swift-package.yml@<full-sha> # vX.Y.Z
  release:
    needs: validate
    permissions:
      contents: write
    uses: swift-library/github-workflows/.github/workflows/swift-package-release.yml@<full-sha> # vX.Y.Z
    with:
      tag: ${{ github.ref_name }}
      accepted_commit: ${{ github.sha }}
```

Release jobs restore/save no caches, build no source and set no concurrency
policy that could cancel queued releases. Existing releases must have identical
notes and no assets; otherwise publication fails. Callers must also preserve
running and queued releases.

## Organization checks

Inputs are `organization`, `declaration-repository`, `declaration-revision`,
`catalog-repository`, `catalog-revision`, `members` (default `all`, or
newline-separated names), and `mode` (`public` or `online`, default `public`).
The declaration repository supplies `MAINTENANCE.md` with its
`settings-declaration` JSON block. The catalog repository supplies
`profile/catalog.json` with organization/group membership and About text.
Each `catalog-*` input defaults to its corresponding `declaration-*` input.
Both resolved revisions must be full commit SHAs. Only declaration members in
the requested organization are checked; members in other organizations are ignored.

`swift-library` and `agents-tools` use their own `.github` repository for both
inputs. `skill-cli` uses a pinned `agents-tools/.github` declaration and its own
catalog at the commit under test:

```yaml
jobs:
  organization:
    permissions:
      contents: read
    uses: agents-tools/github-workflows/.github/workflows/organization.yml@<full-sha> # vX.Y.Z
    with:
      organization: skill-cli
      declaration-repository: agents-tools/.github
      declaration-revision: <full-declaration-sha>
      catalog-repository: skill-cli/.github
      catalog-revision: ${{ github.sha }}
```

Public mode compares active public, non-fork membership and About descriptions.
Member selection narrows About/settings checks but still detects new members.
Online mode additionally reads merge settings, token permissions, vulnerability
reporting and complete branch/tag rulesets. Unknown observations fail with exit
2; drift or declared enforcement gaps fail with exit 1.

Online callers pass `secrets.organization-token`: a token with Administration
read access to the selected repositories. The caller's ordinary `GITHUB_TOKEN`
is sufficient for public observations, but cannot read all administrative
settings across an organization. The optional secret is used only by the check.

## Package template publication

`scripts/publish-template.py` publishes a template repository's generated files
from their producers' releases. The declaration repository's `MAINTENANCE.md`
declares them in one `template-composition` JSON block: `schema` 1, the
`template` repository as `owner/name`, and `generators`, each with a producer
`repository`, a `command` and a `files` map from template path to generated path.

```sh
python3 scripts/publish-template.py --declaration <declaration-checkout> --template <template-checkout>
```

For each producer the script clones the highest `vMAJOR.MINOR.PATCH` tag, ignoring
pre-releases; every generator from one repository runs from that one release.
Each command runs from the release checkout's root, with `{template}`, `{output}`
and `{declaration}` replaced by the template checkout, an empty output directory
and the declaration checkout. The generated files must be exactly the declared
`files` values. The script writes only declared template paths, and writes
nothing unless every generator succeeds.

Both checkouts must be clean. The template's origin must name the declared
template on GitHub, and must push where it fetches. Unless `--write-only` is
given, both checkouts must also be at their origin's default branch head. When
files change, the script commits them with a signature on
`chore/publish-<digest>`, where the digest covers the declaration and producer
commits. It pushes that branch, opens one pull request that lists each
producer's release, commit and changed files, and leaves the template checkout
on that branch. When the template allows auto-merge, it requests a squash merge
of the pushed head. If the branch already exists, locally or on origin, the run
stops before writing anything. A failed push, pull request or auto-merge request
reports the command that completes it. `--write-only` writes the files without a
commit or pull request. Runs need `git`, `gh` authenticated to push to the
template and open pull requests, signing configured in the template checkout,
and each generator's own tools.

No workflow calls the script: opening a pull request in another repository
needs an App credential, so a maintainer runs it with their own credentials
after each producer release.

## Pins and implementation revision

Pin reusable workflows by full commit SHA; add a version comment at the family
release. Third-party actions are pinned by full SHA with version comments.
The toolchain action can also be called directly at the same repository pin.

Reusable workflows check out their own scripts separately from the member.
The checkout uses GitHub's
[`job.workflow_repository` and `job.workflow_sha`](https://docs.github.com/en/actions/reference/workflows-and-actions/contexts#job-context)
to select the repository and exact commit defining each job. The same workflow
files work from `swift-library/github-workflows` and
`agents-tools/github-workflows`. Validation requires `actions: read` to retrieve
compiler-version artifacts for the aggregate check.

## Terminal demo

The presentation action has one reference, in `swift-package.yml`. Demo fixture
setup reads that pin with `scripts/check-ci.py --demo-revision` and installs the
toolchain's declared Node version and locked dependencies. Demo checks use
`recording-only: true` to compare the committed recording with fresh CLI output.
The member's `environment` applies to the demo build. The recorder constructs
the child's environment from its sandbox defaults and the terminal script's
`env`, so every environment value needed to reproduce the demo belongs in that
script.

On drift, the action writes the regenerated `recording.json` to a dedicated
runner temporary directory. The failed matrix entry uploads it as a
`demo-recording-<execution>-<index>` artifact retained for seven days. Download and
commit that file beside the script when the output change is intended.

## Local validation

```sh
python3 -m venv .build/venv
. .build/venv/bin/activate
python3 -m pip install -r requirements.txt
actionlint
python3 -m unittest discover -s tests
python3 scripts/swift_package_config.py --root fixtures/passing
python3 scripts/test-fixtures.py macos
python3 scripts/test-fixtures.py apple
python3 scripts/test-fixtures.py linux
```

For local demo fixtures, place the presentation scripts package from the revision
printed below in `.build/presentation-toolchain`, and put the Node version from
its `.node-version` on `PATH`:

```sh
python3 scripts/check-ci.py --demo-revision
npm ci --ignore-scripts --omit=dev --prefix .build/presentation-toolchain
python3 scripts/test-fixtures.py demo --toolchain .build/presentation-toolchain
```

macOS runs require Xcode/Swift; Linux fixture runs require Docker. The unit
suite validates every package fixture against the schema, exercises compiler
matrices, version/tag trust, policy, organization API responses, aggregate
failure behavior and template publication against local repositories. The command harness requires passing fixtures to succeed and
negative fixtures to fail for their intended reason. Builds and logs live under
ignored `.build/`.
The macOS fixtures include documented library and executable targets with
dependencies, a cross-module extension and trait-gated API. The Apple fixtures
include an iOS library that consumes Swift source generated by a local build
tool plugin.
The demo fixtures build both release executables and check their recordings with
the pinned toolchain. `passing` must match; `demo-drift` must exit 1 with a
changed-step diagnostic and recording diff. Build and toolchain errors fail the
harness. Regenerate the passing recording with the same toolchain's
`node <toolchain>/src/cli.ts terminal record --script <script.yml> --executable <built-cli> --out <recording.json>`.

CI calls the validation and policy workflows with passing fixture packages.
The root configuration targets `fixtures/passing` and declares every validation
job type. The scripts exercise each job's rejection path against failing
fixtures on its matching runner. A failing reusable-workflow call cannot be an
expected outcome without failing the run. Release and organization workflows
are covered by actionlint and unit tests and exercised by their consumers;
CI does not call them. The CI aggregate requires every dependency to succeed.
