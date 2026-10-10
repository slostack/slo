# Feature 89 — dispatch 3 local release preparation

## Verdict

Bounded local release preparation is implemented and behaviorally green.
**REVISE — no STEP1READY, release approval or completion claim.** Static gates
remain unwaived. Independent review is reserved for dispatch 4; completion model
assignment is still missing. No subagents, staging, commit, push, MR, merge, tag,
publication, deployment, installation or upgrade occurred. Specifications and the
other main checkout were not modified.

## Exact bounded edits

- Repository-root `.gitlab-ci.yml`: default conjunctive tags `mgr-01`, `shared`;
  explicit macOS tags repeat both and retain `macos`. Includes, scripts, rules,
  privileged Docker service requirement and release dependency order unchanged.
- `slo/pyproject.toml`: canonical version `0.21.0` → `0.21.1`; lock unchanged.
- `slo/CHANGELOG.md`: unreleased candidate notes for dual Platform/subscription
  GPT-6 Luna/Sol/6.1 Sol, authenticated Jev, snapshot/reasoning/transport and
  persistence fixes, and explicit offline/not-approved boundary.
- `slo/tests/test_feature89_release_preparation.py`: version/notes agreement and
  CI default/explicit-capability tag guards, including prohibition of explicit
  tags on bridge jobs. No bridge exists in the inspected local configuration.

Existing dirty Feature 89 work is retained. HEAD remains
`ea8601c53f04fa06a0baeeb47d385c44cc9a5364` on `feature-gpt_6_support`.
Fetched `origin/main` is `0a918a93b4233dfe2d14880e63a85174805f9caa`, two ahead.
Its specification-skill consolidation does not touch these release files.
The shared RESEARCH files have independent upstream append-only documentation;
no upstream integration, reset, rebase, checkout or merge was attempted.

## Fresh executed evidence

Receipts are under `slo/.f89-evidence/release3-*`, **excluded from prospective
staging**. Each test/static command has a `.command`, `.log` and `.exit` receipt.
The existing env-i runner uses synthetic credentials and isolated HOME/SLO_HOME,
TMPDIR and pre-import/per-test state containment. No real provider history,
credentials, inference or terminal smoke was used.

| Gate | Actual result |
|---|---|
| Red release regression | 2 failed: old version and missing CI default tags |
| Focused release/version/automation | 34 passed, 1 warning; exit 0 |
| Full non-E2E after source/test/config edits | **6142 passed, 18 deselected, 406 warnings in 451.26s; exit 0** |
| Black changed Python paths | 41 files unchanged; exit 0 |
| Full Black | **13 would reformat**, 655 unchanged; exit 1 |
| Full mypy src/ tests/ | **296 errors in 59 files**, 668 checked; exit 1 |
| Frozen HEAD mypy | 296 errors in 59 files, 654 checked; exit 1 |
| Frozen HEAD Black | 19 would reformat, 635 unchanged; exit 1 |
| git diff --check | exit 0 |
| dpkg -V coreutils after suite | empty output; exit 0 |

`release3-static-comparison.json` compares full mypy diagnostic multisets
(path/message/error-code/multiplicity, removing shifted line numbers only):
**zero added and zero removed** versus exact git-archived HEAD. Current Black
failures remain the prior 13-path set, not a waiver. Full raw diagnostics are
retained in `release3-mypy.log` and `release3-black.log`; the frozen receipts
retain all baseline output. `release3-versions.log` records installed/locked
versions without installing or updating the existing environment.

## Server verification boundary

The documented local `environments/development.env` is absent. Only the needed
GitLab/Cloudflare environment field names were queried; no values were printed.
No credentials were available through those checked mechanisms. Conventional
sibling/root development.env candidates were also absent (existence checks only).
`release3-server.json` records this. Authenticated tag/release collision clearance,
project runner details, protected-ref/variable readiness, Cloudflare Workers
access and official project merged-CI lint remain **unverified**, not failed local
implementation prerequisites. Dispatch 2's anonymous no-tag observation is not
upgraded to authenticated clearance.

Public GitLab Security/Secret-Detection template was fetched read-only: it
includes Jobs/Secret-Detection; that public template defines `.secret-analyzer`
and `secret_detection`, neither with explicit tags or disabled default
inheritance. Thus they inherit the two local default tags. Snapshots are
`release3-secret-template.yml` and `release3-secret-jobs.yml`. This is public
master template inspection, **not** the deployed GitLab merged-config result.
No manual job or bridge appears in those inspected templates. Official lint and
all-runner capability verification must still precede release; especially macOS
requires all three tags and Docker needs privileged service capability.

The installed release skill/KB contain historical direct-publication guidance.
Actual Makefile and deploy script control: `make release` checks out/pulls main,
creates/pushes a tag; the tag pipeline publishes, verifies and creates the release.
None was executed. Missing server evidence never prevented the local edits/tests.

## Remaining blockers

1. Unwaived full Black and mypy failures; no broad baseline repair was attempted.
2. Fresh independent Feature 89 plus release-prep review in reserved dispatch 4.
3. Operator assignment and subsequent fresh completion assessment.
4. Authenticated collision clearance, official merged CI lint and eligible
   runners/privileged Docker/macOS/protected-release capability checks.
5. Upstream integration and post-integration gates before any eventual delivery.

No live entitlement or installation/deployment success follows from these tests.
