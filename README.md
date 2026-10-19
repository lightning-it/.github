# .github

This public repository owns the common workflow definitions. The Root reference
has an active protected Main control; other repositories keep their documented
POC transition until their own scope is explicitly admitted and accepted.
Installing a caller or changing these files does not activate a private scope.

The process is defined in the [workflow target](docs/workflow-target.md),
[entry-point catalog](docs/workflow-target-catalog.md) and
[operator guide](docs/protected-runtime-operations.md). The
[POC description](docs/poc-workflows.md) remains historical transition guidance
for scopes that have not migrated; it does not waive active native requirements.
Repository quality, security and applicable product release checks remain required.

For changes entering the admitted Root Main route, prepare locally, submit a PR,
and complete the current checks and prescribed ingress AI review before Main
promotion. Unadmitted scopes retain the ordinary POC contribution process; this
does not introduce a universal review gate for every ordinary PR. Relevant successful Develop quality signals
the preparation of at most one Main PR. Preparation grants no approval. One
authorized person can grant the actual normal release approval, including their
own operation, after its current technical checks pass. Private consumers keep
their code, sensitive configuration, validation credentials and results private.
The public Root reference sends only a bounded preparation request with a
short-lived dispatch token; it reads no private implementation or approval data.

These organization-wide controls implement the accepted
[repository topology ADR](https://lit.atlassian.net/wiki/spaces/LIT/pages/2878636297),
[branching and release governance ADR](https://lit.atlassian.net/wiki/spaces/LIT/pages/2878603438),
[mandatory CI and artifact assurance ADR](https://lit.atlassian.net/wiki/spaces/LIT/pages/2878636340),
[secure SDLC standard](https://lit.atlassian.net/wiki/spaces/LIT/pages/2887778335),
[quality gates](https://lit.atlassian.net/wiki/spaces/LIT/pages/2887123058), and
[software supply-chain assurance standard](https://lit.atlassian.net/wiki/spaces/LIT/pages/2887024876).

<!-- BEGIN LIT_SHARED_RELEASE_MODEL -->

## Release and Quality Model

This repository follows the Lightning IT shared release and quality model.

See [RELEASE.md](./RELEASE.md) for:

- branch and release flow
- required quality checks
- test matrix
- release evidence
- artifact publishing
- supported repository-specific release behavior

Repository classification: **Repository Profile**.
Required test profiles: `markdown, repository-profile`.
Publishing targets: `none`.

## Supported and Tested Platforms

| Platform / Product |                  Status | Validation         |
| ------------------ | ----------------------: | ------------------ |
| ubuntu-latest      |               Supported | Repository quality |
| github-profile     | Tested where applicable | Repository quality |

<!-- END LIT_SHARED_RELEASE_MODEL -->

<!-- BEGIN LIT_QUALITY_BADGES -->

[![CI](https://github.com/lightning-it/.github/actions/workflows/repository-quality.yml/badge.svg?branch=develop)](https://github.com/lightning-it/.github/actions/workflows/repository-quality.yml)
[![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/lightning-it/.github/badge)](https://scorecard.dev/viewer/?uri=github.com/lightning-it/.github)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)

<!-- END LIT_QUALITY_BADGES -->

`.github` is managed by the Lightning IT shared release and quality model.

## Features

- Public common quality, current-revision review and delivery definitions.
- Explicit scope admission, one-person normal approval and private consumer boundaries.
- Standard release, testing and security documentation.

## Documentation

- [RELEASE.md](./RELEASE.md)
- [TESTING.md](./TESTING.md)
- [ModuLix validation lanes](./MODULIX-VALIDATION.md)
- [SECURITY.md](./SECURITY.md)
- [Root CodeQL merge protection](docs/root-codeql-merge-protection.md)

## Security

See [SECURITY.md](./SECURITY.md) for supported versions and vulnerability reporting.

## Contributing

See [CONTRIBUTING.md](./CONTRIBUTING.md) for contribution and review expectations.

<!-- BEGIN LIT_RELEASE_QUALITY_MODEL -->

## Release and Quality Model

This repository follows the Lightning IT shared release and quality model.
The README shows the current supported and tested matrix.
Exact per-version validation proof is stored with each GitHub Release as `release-evidence.md` and `release-evidence.json`.
Releases are created from the protected `main` branch after a reviewed `develop -> main` release promotion.
Repository checks validate the managed structure, documentation, and release model for this repository type.

See:

- [RELEASE.md](./RELEASE.md)
- [TESTING.md](./TESTING.md)
- [GitHub Releases](../../releases)

Repository classification: **Repository Profile**.
Required test profiles: `markdown, repository-profile`.
Publishing targets: `none`.

<!-- END LIT_RELEASE_QUALITY_MODEL -->

<!-- BEGIN LIT_COMPATIBILITY_MATRIX -->

## Compatibility Matrix

| Platform / Product | Status | Validation |
|---|---:|---|
| ubuntu-latest | Supported | Repository quality |
| github-profile | Tested where applicable | Repository quality |

Validation proof for each released version is stored in the corresponding GitHub Release evidence.

<!-- END LIT_COMPATIBILITY_MATRIX -->

## Release Evidence

This repository does not publish product artifacts by default. A Main promotion
still needs its one complete audit package and verified seven-year immutable
retention before full release acceptance. Native GitHub artifacts or storage
qualification alone do not prove that archive. The complete native archive
producer remains a separate rollout acceptance item; the Root reference is not
a claim of completed fleet production acceptance. Develop PRs keep native GitHub
evidence and do not create duplicate durable release packages.
The evidence records:

- tested matrix combinations
- GitHub Actions run links
- artifact references
- publish status
- security scan status

See [GitHub Releases](../../releases), [RELEASE.md](./RELEASE.md), and [TESTING.md](./TESTING.md) for the release process and validation model.
