# Testing

This repository uses the Lightning IT shared test model.

## Test Profiles

- `markdown`
- `repository-profile`

## Supported Matrix

Operating systems and runners:

- `ubuntu-latest`

Products and runtimes:

- `github-profile`

## When Tests Run

- Normal pull requests run the declared test profiles relevant to changed files.
- Renovate and verified shared-assets or repository-quality synchronization pull requests target `develop` and may auto-merge only after required checks pass.
- `develop` to `main` promotion pull requests run the strongest validation profile for this repository.
- Trusted `main` release workflows build and publish artifacts only after validation succeeds.

## Protected Trust-Root Promotion

Promote an organization-owned required-workflow source in this order: merge the
source change normally to protected `develop`, promote it normally to protected
`main`, verify the exact `main` source commit, and only then activate a ruleset
that requires it. A candidate branch or an unpromoted `develop` workflow must
never validate itself.

Promotion uses exact current branch heads and normal merge commits, without a
bypass, force-push, or direct protected-branch write. If `main` is not already
an ancestor of `develop`, repair ancestry in a separately reviewed two-parent
merge before promotion. A zero-file or unavailable AI response is not a review
PASS.

For protected current-revision evidence, a custom check's canonical
`/runs/<check-id>` URL identifies only that check object; it is not sufficient
for producer provenance. Schema-v4 evidence also binds the exact GitHub Actions
producer run ID in the external ID and summary. The organization-owned required
workflow must query that run and verify its repository, event, workflow path,
protected base, candidate head, actor, conclusion, and schema before it can pass.
The verifier reservation separately embeds its own required-workflow run ID in
a v2 external ID; its details URL remains the canonical `/runs/<check-id>` URL.

## Local Commands

Run the managed repository-policy checks:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install PyYAML==6.0.3
.venv/bin/python scripts/lit-repository-quality.py
.venv/bin/python scripts/lit-push-ready.py push-ready
```

Run the repository-specific commands declared in
`.lit/push-ready.json` and the required CI workflow named in
`.lit/repository.yml`. Do not substitute unrelated toolchains.

Heavy Incus execution is not required for this repository. Do not report an Incus run as part of its acceptance evidence.

## Interpreting GitHub Actions

The GitHub Actions matrix is the primary dashboard. Job names should expose the repository class, OS/runtime where applicable, and profile, for example `repository / quality`.

Release evidence is generated during trusted release workflows and attached to or linked from GitHub Releases where the repository publishes release artifacts.
