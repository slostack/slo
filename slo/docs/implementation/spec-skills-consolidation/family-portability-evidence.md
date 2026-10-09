# Mandatory specification family and portable discovery

## Authorized change

The follow-up explicitly removes document-mode selection and the earlier tiny-feature
and partial-family exceptions. Every feature now requires overview.md/product framing
and separate standalone engineering sub-specs. A targeted revision retains and checks
the existing family. Lightweight execution tickets link to, never replace, sub-specs.
This supersedes the historical compatibility mapping, not unrelated safeguards.
Manual/auto workflow confirmation modes are unchanged. Workflows remain separate.

## Changes

- Canonical authoring, independent verification, task breakdown and specification
  workflow use one mandatory family contract. Missing parts block readiness.
- Artifact-path anchor renamed; all linked callers and regression checks migrated.
- Skill discovery follows config.cfg SKILLS_LOCATION / SKILLS_DIR, USER_SKILLS_DIR
  and USER_WORKFLOWS_DIR, their supported environment overrides and catalog file_path.
  No assumed pipx layout, Python version, username or OS-specific skill installation.
- Artifact defaults use the resolved Slo home; explicit user and project overrides
  retain precedence. No new environment variables or runtime resolver were added.
- Orientation and operational callers updated; packaged granularity sample no longer
  reintroduces document modes or developer-specific absolute repository paths.
- Existing historical test logs are execution evidence, not portable instructions.

## Test-first evidence

- family-portability-red.log: 5 expected failures, 9 passing before guidance changes.
- family-sample-red.log: expected old sample mode failure.
- family-sample-path-red.log: expected host-specific sample path failure.
- Final surrounding command: SLO_ENV=test PYTHONPATH=. poetry run pytest -q
  tests/agents/skills tests/agents/slo_agent/test_skills_loader.py tests/config/test_cfg.py
  Result: 88 passed, 2 warnings (family-portability-surrounding.log).
- Final full command: make test. Result: 5317 passed, 18 deselected, 201 warnings,
  exit 0 (family-portability-full.log and family-portability-full.exit).
- Generated index: make build-skill-index; registry parity and relative link/anchor
  checks pass. Scoped Black check and git diff --check pass.

Independent re-review and fresh completion assessment remain pending. No approval,
commit, push or publication is claimed. No personal skill files were changed.

Publication preparation: trailing whitespace in archived logs was removed for Git
whitespace checks. Test results and exit receipts are unchanged; logs are not
byte-for-byte terminal captures. Research summaries now reflect the required family.
