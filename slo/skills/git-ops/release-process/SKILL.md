---
name: release-process
description: Step-by-step process for releasing a new version of slo — bump version, create MR, merge to main, tag release, publish installer.
when_to_use: Load this skill when the user asks to "create a release", "release vX.Y.Z", "bump the version", or "run the release process".
group: git-ops
kind: skill
---

# Slo Release Process

## Skill summary

- **Name:** `release-process`
- **Description:** Step-by-step process for releasing a new version of slo — bump version, create MR, merge to main, tag release, publish installer.
- **When to use:** Load when the user asks to "create a release", "release vX.Y.Z", "bump the version", or "run the release process".
- **Group:** `git-ops`
- **Kind:** `skill`

## Examples

- The user asks: "Create a release as v0.6.0 with release notes."
- The user asks: "Bump the version and publish the installer."
- The user asks: "Run the release process for v0.5.5."

## Guidance

## Version alignment rule

The git tag (`vX.Y.Z`) **MUST** match the `version` field in `pyproject.toml`.
`slo --version` reads from the installed package metadata, which is populated from
`pyproject.toml` at install time. Mismatches cause `slo --version` to report the
wrong version even after `slo update`.

## Workflow

### Step 1 — Bump the version in pyproject.toml

Determine the new version using semantic versioning:

| Bump type | When |
|---|---|
| PATCH (x.y.**Z**) | Bug fixes, no API or behaviour changes |
| MINOR (x.**Y**.z) | New features, backwards-compatible |
| MAJOR (**X**.y.z) | Breaking changes |

1. Edit `slo/pyproject.toml`: change `version = "x.y.z"` to the new version.
2. Create a feature branch: `git checkout -b release/vX.Y.Z`
3. Commit: `git commit -m "chore: bump version to vX.Y.Z"`

### Step 2 — Create and merge an MR

1. Push the branch: `git push origin release/vX.Y.Z`
2. Create a GitLab MR targeting `main` (include release notes in the description).
3. Merge the MR after CI passes.

### Step 3 — Tag and create the GitLab release

Ensure `main` is up to date, then run:

```bash
make release VERSION=vX.Y.Z
```

This creates an annotated git tag and publishes a GitLab release via the API in one step.
Requires `SLO_GITLAB_PERSONAL_ACCESS_TOKEN` in `environments/development.env`.

### Step 4 — Publish the installer

```bash
make publish-installer
```

This bakes the new tag as `PUBLISH_SLO_REF` into the Cloudflare Worker that serves
`install.sh` at `get-slo.sh`. Requires Cloudflare credentials in `environments/development.env`.

## Automation helpers

| Command | What it does |
|---|---|
| `make release VERSION=vX.Y.Z` | Annotated tag + GitLab release via API |
| `make publish-installer` | Publishes `install.sh` pinned to the latest tag |

## Release checklist

- [ ] `pyproject.toml` version bumped to `vX.Y.Z`
- [ ] Feature branch created, committed, and pushed
- [ ] MR created and merged to `main`
- [ ] `make release VERSION=vX.Y.Z` completed successfully
- [ ] `make publish-installer` completed successfully
- [ ] Verified: `slo update` installs the new version on a test machine

## Non-Negotiables

- Never create the release tag before the version-bump MR is merged to `main`.
- The git tag version must match `pyproject.toml` exactly — no `v` prefix inside the file.
- Always run `make publish-installer` after tagging so the hosted installer reflects the new version.
