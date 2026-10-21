# Turn 1 continuation — baseline gate blocker

Verdict: FAILED preconditions. No production implementation, no T1 completion,
no independent review or completion assessment.

The original baseline.md receipt is preserved unchanged. This continuation ran
in /root/Code/slo-94-herdr-integration/slo at HEAD
d0e3a756689f2675e5507034d43cd8b272d3c6b8 on feature-94-herdr-integration.
Only the evidence directory was untracked before execution.

## Environment and safety

Read AGENTS.md fully (1–510, 511–1013), CLAUDE.md fully, docs/RESEARCH.md
fully (1–330, 331–633), committed workflows/code-test-review.md and
workflows/SKILL.md. Read installed engineering-routing, engineering-testing,
engineering-ownership, coding-rules and code-test-loop skills. No completed
routing or specification-ingestion claim is made.

Read Makefile, tests/conftest.py, tests/state_isolation.py and FakeBin's
construction/writer section in tests/cli/test_install.py. Searched command
symlink call sites. FakeBin uses regular passthrough wrappers, resolves ancestry
before executable writes, rejects symlink replacement, and unlinks existing
regular files. Collection creates a suite-owned temporary SLO_HOME; per-test
fixtures isolate HOME/auth/config and preserve the suite-wide terminal spawn
blocker. No fixture changes were made. No development env was sourced.
The Makefile fallback supplies a synthetic Anthropic credential.

`pyenv which python` returned /root/.pyenv/versions/slo-harness/bin/python;
`python --version` and `poetry run python --version` returned Python 3.11.7.
`make test-env` returned fallback. No interpreter install/config change occurred.
`test -x /root/.local/bin/herdr && stat -c '%F %a %n' /root/.local/bin/herdr`
returned regular file 755 /root/.local/bin/herdr. It was not executed; this is
availability only, not protocol compatibility or live acceptance.

Read KB os/ROLE.md and os/README.md before host integrity inspection.
`dpkg -V coreutils` printed nothing before execution and after both test gates;
post-suite outputs and exits are retained. No host fault observed.

## Executed gates

Each baseline-{test,smoke,lint,black}.command contains the exact command;
matching .log contains combined stdout/stderr and .exit contains its exit.
Commands ran directly in the worktree using its Makefile and pyenv environment.

| Gate | Exit | Result |
|---|---:|---|
| make test | 0 | 6272 passed, 19 deselected, 408 warnings, 466.80s |
| make smoke | 0 | 278 passed, 2 warnings, 2.70s |
| make lint | 2 | mypy: 301 errors in 64 files, 682 files checked |
| scoped Black --check | 1 | 5 files would be reformatted; 185 unchanged |

The scoped Black command covers existing CLI, session and TUI owners plus CLI
and TUI tests; it is not a finalized whole-feature scope selection.

## Diagnosed blocker

Required static baseline gates are not green at the unchanged feature base.
Mypy failures include absent PyYAML typing stubs, incompatible registry kind
Literal typing, nullable history-node access, Textual renderable union member
access and existing Typer override/test method-assignment errors. This is not
just a missing executable or one environment flag: the retained full output
contains source and test typing failures across 64 files.

Black identifies exactly:
- src/tui/authentication/auth_screen.py
- tests/cli/test_openrouter_terminal_lifetime.py
- tests/cli/test_wheel_contents.py
- tests/tui/test_openrouter_reasoning_presentation_recovery.py
- tests/tui/test_openrouter_picker.py

No Herdr changes existed when these commands ran. Historical feature waivers
are not applied to this task. Repair would require source/test edits (or an
explicitly approved baseline exception), outside this preconditions-only scope.
No package installation, formatting rewrite, test disabling or config workaround
was attempted. Request direction on carrying these as accepted baseline debt
versus separately authorizing repair before declaring preconditions READY.

## Remaining work (not misrepresented as done)

Full installed manifest/config-tier resolution, project KB entry consultation,
Python/Typer/Textual/Faux/service/DAO/test recipe selection and frozen routing.md
remain outstanding. All seven source specifications, accepted reviews and exact
attachments still require full ingestion; scope-plan.md is not yet authored.
Runtime reasoning/timeouts remain orchestrator-owned and are NOT this blocker.
The successful baseline receipts can be reused at this unchanged base; the
static failures cannot be called green. No source specs or other worktrees were
modified; no agent was spawned and no commit/push occurred.
