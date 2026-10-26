# Changelog

## Unreleased

- `policy.yml` accepts the agents CLI's tracked instruction files: `.agent/instructions/`, `.agent/agents.json` and `.agent/agents.resolved`. Other `.agent/` paths stay private execution files. The declaration and lock may name agent IDs such as `codex` without an allowed product term.

## 0.1.0

- Add reusable `swift-package.yml` validation for formatting, compilers with default traits, additional trait sets on the first compiler, Linux, Apple platforms, DocC, terminal demo recording, and repository commands.
- Add `swift-package-release.yml` to verify accepted commits and signed tags and publish changelog release notes.
- Add `policy.yml` source checks and `organization.yml` membership, metadata, and settings checks.
- Add the `select-toolchain` action to select installed Xcode versions and optionally install official Swift releases.
- Add package template publication from producer releases through `scripts/publish-template.py` (#4).
