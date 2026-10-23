# Member configuration mapping

The JSON files in `fixtures/members/` are schema-checked migration examples
for the thirteen inventory members with `release.json` and `ci.include`.
Their compiler entries, runner/Xcode selections, explicit Swift installations,
Docker digests and timeout maxima come from the member declarations. They are
dry evaluations, not adopted member configurations or claims that the members
have passed the new workflow. Repository-specific scripts must be migrated to
lowercase `scripts/` by their owners.

Every example runs format, tests and a release build. A former `strict-format`
entry becomes `format`; the last compiler supplies its runner and toolchain.
One timeout applies to every job, so differing old entry limits map to their
maximum. DocC catalogs identify eligible targets; declaring their validation is
an explicit member decision.

| Member | Existing `ci.include` → shared configuration | Repository work and limits |
| --- | --- | --- |
| swift-appstoreconnect | `macos-15-swift-6.3-minimum`, `macos-26-swift-6.3` → 2 compilers; `strict-format` → format; native build system; four trait sets; 240-minute timeout; `appstoreconnect` demo | Specification, generation and ReleaseTools tests → commands. Experimental DocC graph extraction, normalization and archive merging remain `scripts/check-docs`: `docs.targets` alone cannot preserve those semantics. CLI/completion assertions belong in tests or focused commands. |
| swift-benchmark | `macos-15-swift-6.0`, `macos-26-swift-6.3` → 2 compilers; `strict-format` → format | Documentation dependency-pin and CLI/plugin assertions require extraction into tests or a repository command. Its six DocC targets are expressible. |
| swift-book | No `.github/` or release matrix | No existing matrix to evaluate. Its cold-process and maintenance measurements can be repository commands after it adopts a compiler declaration. |
| swift-codex | `macos-15-swift-6.2`, `macos-26-swift-6.3` → 2 compilers; `repository-quality` → format, 11 DocC targets and focused commands; 90-minute timeout | Schema, dependency-license inventory, repository checks and cooperative-pool stress tests remain commands. The old combined quality wrapper must be split. |
| swift-data-writable | `macos-15-swift-6.2`, `macos-26-swift-6.3` → 2 compilers; `strict-format` → format; SwiftDataWritable → docs | Direct iOS/tvOS/watchOS package schemes → apple; `test: true` prepares the SDK-matching simulator. ReleaseTools and manifest-floor assertions remain commands/tests. |
| swift-gyb | `macos-15-swift-6.0`, `macos-26-swift-6.3` → 2 compilers; `linux-swift-6.2` → digest-pinned Linux | GYB Python self-test → command. Formatting and release build become mandatory. |
| swift-interface-distiller | `macos-26-swift-6.3` → compiler with native build system; `linux-swift-6.3` → Linux host command | The signed host-toolchain bootstrap is not a Docker-image option. It needs a focused `scripts/check-linux`, or adoption of a digest-pinned image. InterfaceDistiller → docs; interface-distiller → demo. CLI/schema/report assertions remain tests/commands. Add `.swift-format`. |
| swift-json-schema | `macos-15-swift-6.2`, `macos-26-swift-6.3` → 2 compilers; `strict-format` → format including Benchmarks; `linux-swift-6.2` → declared image | Five documentation targets → docs. Container prerequisite installation is not a shared option: choose a suitable pinned image or a repository command. CLI/compliance assertions remain tests/commands. |
| swift-package-template | `macos-15-swift-6.0`, `macos-26-swift-6.3` → 2 compilers; `strict-format` → format | No repository wrapper is required. |
| swift-pdf | `macos-15-swift-6.2`, `macos-26-swift-6.3` → 2 compilers; `strict-format` → format; PDF → docs | Direct iOS tests and visionOS build → apple. Overload-topic coverage and snippet type-checking remain commands. Hosted-runner recovery, process sampling and generation-by-generation simulator matrices are not shared options. |
| swift-redux | `macos-15-swift-6.0`, `macos-26-swift-6.3` → 2 compilers; `ios-build` → apple scheme `swift-redux-Package` | Format runs automatically. A DocC target can be declared separately. |
| swift-semver | `macos-15-swift-6.0`, `macos-26-swift-6.3` → 2 compilers; `strict-format` → format; `linux-swift-6.0` → same image digest | Public parsing/range/Codable assertions belong in package tests. |
| swift-sh | `macos-15-swift-6.3`, `macos-26-swift-6.3` → 2 compilers, retaining Swift 6.3.3 installation; `strict-format` → format including Examples; `linux-swift-6.3` → same image digest | swift-sh → demo. Inline dependency execution, help/version/error assertions belong in package tests or focused commands. |
| swift-userdefault | `macos-15-swift-6.0`, `macos-26-swift-6.3` → 2 compilers; `ios-build` → apple; debug and release test configurations | `-skipPackagePluginValidation` is not a shared apple option; retain a repository command if still required. Release build and format run automatically. |
| swift-library/skills | No release matrix; collection CI | Not a Swift package caller. Keep native collection/plugin/export jobs and call policy independently. |
| swift-library/homebrew-tap | No release matrix; tap workflows | Not a Swift package caller. Reuse `actions/select-toolchain` where needed; retain tap checks. |
| skill-cli/cli | No release matrix in the inventory | No existing `ci.include` to evaluate. Behavioral parity is a repository command if the package adopts validation. |
| agents-tools/homebrew-tap | No release matrix; Homebrew checks | Not a Swift package caller. Retain formula style/audit/install/test jobs. |

The former `macos-15-swift-6.2-syntax-minimum` entry in swift-json-schema is
outside this contract. Consumer builds, dependency-minimum builds, public
interface comparisons and execution-evidence publication have no mapping.
Their removal does not remove the package behavior assertions that belong in
ordinary tests.

The examples deliberately do not call old all-in-one wrappers to preserve
those excluded checks. Custom commands illustrated here still require the
member owner to separate their retained behavior and update internal paths.
No retained package-specific assertion requires another shared configuration
key: `commands` is the extension point. The items described above as absent
shared options cannot be represented by the built-in jobs alone.
