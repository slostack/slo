# B153 executed commands

Cwd `/root/Code/slo-94-herdr-integration/slo`. For all Python commands:

```sh
export VIRTUAL_ENV=/root/.pyenv/versions/slo-harness
export PATH=/root/.pyenv/versions/slo-harness/bin:$PATH
export PYENV_VERSION=slo-harness
R=docs/implementation/94-herdr/static-B-153-receipts
P=docs/implementation/94-herdr/t6-audit-static-plan-142-receipts
```

Initial red.log:
`poetry run mypy --no-incremental --cache-dir "$R/mypy-cache" --follow-imports=silent $(cat "$P/B-fixtures.files")`

Timeout red.log:
`poetry run mypy --no-incremental --follow-imports=silent tests/auth/test_oauth_flow.py`

Incremental tests all use `bash docs/implementation/94-herdr/t1-dao-check.sh <module>`:

| log | module |
|---|---|
| compaction.log | tests/agents/slo_agent/compaction/test_compacted_session_updater.py |
| device.log | tests/auth/providers/test_openai_codex_device_authorization.py |
| oauth.log, oauth-final.log | tests/auth/test_oauth_flow.py |
| screen.log | tests/tui/authentication/test_auth_screen.py |
| headless.log | tests/tui/authentication/test_authentication_headless_e2e.py |

screen-mypy.log: `poetry run mypy --no-incremental --follow-imports=silent tests/tui/authentication/test_auth_screen.py`

green.log and final-mypy.log:
`poetry run mypy --no-incremental --cache-dir "$R/mypy-cache" --follow-imports=silent $(cat "$P/B-fixtures.files") src/auth/oauth_flow.py`

final-tests.log:
`bash docs/implementation/94-herdr/t1-dao-check.sh $(cat "$P/B-fixtures.tests") tests/auth/test_device_authorization.py tests/tui/authentication/widgets tests/tui/authentication/test_authentication_device_e2e.py`

compaction-surrounding.log:
`bash docs/implementation/94-herdr/t1-dao-check.sh tests/agents/slo_agent/compaction`

Formatting: `poetry run black $(cat "$P/B-fixtures.files") src/auth/oauth_flow.py` (two reformatted, four unchanged).

black.log:
`poetry run black --check $(cat "$P/B-fixtures.files") src/auth/oauth_flow.py`

After each test: `dpkg -V coreutils` (silent, exit0); final executions persisted in coreutils.log and coreutils-surrounding.log with exit files.

Read-only final review: `git diff -- <five B paths> src/auth/oauth_flow.py` and `git diff --check -- <same six paths>` (silent exit0).
