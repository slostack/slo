# T1 identity and token-format extraction

Status: **READY for bounded-slice handoff**, not complete T1/Feature 94 approval. Implemented and tested; repository lint remains unwaived and failing. No independent review claimed.

## Scope and authority

Read unchanged `routing.md` and `scope-plan.md` T1, supplied AGENTS/CLAUDE, root RESEARCH, scoped Python/shared ownership/testing/cadence guidance, and canonical `/root/Code/specifications/projects/slo/specifications/94-slo-tui-redesign/herdr/tasks.md` T1 and attachment C27. Contracts: B 7.6 exact formatter and Herdr-only identity; C 7.3 complete validator closure and 7.13 canonical predicate. No source specification, shared evidence, DAO, activation, provider, Herdr executable, global state, other worktree, commit or agent dispatch was changed by this worker.

Owned files:
- `src/agents/slo_agent/sessions/identity.py`
- `src/agents/slo_agent/sessions/token_format.py`
- `src/cli/headless_request.py`
- `src/tui/widgets/usage_status_bar.py`
- `tests/agents/slo_agent/test_session_identity.py`
- `tests/agents/slo_agent/test_token_format.py`
- This receipt and its private-to-this-slice `t1-identity-format-logs/` directory.

The parallel DAO/isolation changes visible in the worktree are not this worker's edits. Shared documentation updates remain with integration ownership.

## Requirement map

| Requirement | Implementation and evidence |
|---|---|
| R16 / C 7.3 complete closure | Validator, slug regex, path guard, normalizer, UUID parser and UUID import moved together into identity.py. CLI imports the same function object. Environment fallback/request parsing stays in CLI. Extraction tests assert lower-layer ownership and absence of old private CLI closure. |
| Ordinary compatibility | Existing headless-request suite plus new normalization/error cases: UUID case, compact/braced/URN forms, non-v4 UUID, whitespace, mixed-case slug, dot slug, empty, slash/backslash, traversal, spaces, Unicode and NUL. Existing exception text and ordering retained. The historical UUID4 wording is not version enforcement. |
| C 7.13 / C27 one strict predicate | `is_canonical_uuid_session_id(*, value: str)` calls the same `_try_parse_uuid`; exact canonical equality, no normalization or second parser. Canonical non-v4 and nil accepted; uppercase/compact/braces/URN/whitespace/slug/malformed refused. No logging. Herdr callers are later tasks, not activated here. |
| B5 / B 7.6 exact half-up arithmetic | `CompactTokenFormatter.format` and `_format_one_decimal` own the unchanged integer arithmetic. Both footer private entry points delegate. Tests cover 0, 999/1000, decimal ties and just-below ties, 9999/10000, 12500, 999999/1000000, 9999999/10000000, million ties and signed-64 maximum. Monkeypatch tests prove both delegates use the shared owner. |
| Dependency direction | Both new modules are pure stdlib/support code, with no CLI/Textual/Herdr imports. Existing CLI and footer import downward. |
| Regression | Existing mounted footer/Faux prompt, headless request, CLI, headless runner, dispatch and plugin-footer tests pass. Full default suite and smoke pass. |

## Execution environment

CWD `/root/Code/slo-94-herdr-integration/slo`.
`pyenv which python`: `/root/.pyenv/versions/slo-harness/bin/python`;
`python --version`: Python 3.11.7; `make test-env`: `fallback`; all exit 0.
No environment activation or installation. Targeted commands used this subprocess-only reviewed fallback:

```bash
export SLO_ENV=test SLO_ROOT_DIR="$PWD" SLO_APP_DIR="$PWD" SLO_APP_NAME=slo SLO_LOG_FORMAT=text SLO_DEFAULT_MODEL_NAME=gpt-5.4 SLO_AUTO_VISUALIZE=0 SLO_ANTHROPIC_API_KEY=ci-placeholder-tests-are-fully-mocked COLUMNS=120 LINES=40 SLO_HERDR_DISABLED=1
```

Existing test isolation supplies temporary homes and terminal guard. No new executable stubs were authored here. Full suite exercised existing stubs; both `dpkg -V coreutils` outputs are zero bytes.

## Test-first receipts

All logs below are under `docs/implementation/94-herdr/t1-identity-format-logs/`. Commands redirected complete stdout/stderr to the named log; reported exits are the pytest/make command exits (the reporting shell itself returned 0). Each test increment preceded implementation, then the surrounding module ran green before the next increment. Closure movement is 26 executable lines; predicate is one executable line; formatter/delegation move is under 50 executable lines. Existing docstrings were moved intact, so textual file length exceeds executable increment size.

Common pytest prefix: `PYTHONPATH="$PWD" poetry run pytest -m 'not e2e'`.

| Order | Exact arguments following prefix | Log | Exit/result |
|---|---|---|---|
| 1 RED | `tests/agents/slo_agent/test_session_identity.py` | identity-red.log | 2; collection ImportError: identity absent |
| 2 GREEN | `tests/agents/slo_agent/test_session_identity.py tests/cli/test_headless_request.py` | identity-green.log | 0; 43 passed, 1 warning |
| 3 RED | `tests/agents/slo_agent/test_session_identity.py` | canonical-red.log | 1; 12 failed, 17 passed, 1 warning; predicate absent |
| 4 GREEN | `tests/agents/slo_agent/test_session_identity.py tests/cli/test_headless_request.py` | canonical-green.log | 0; 55 passed, 1 warning |
| 5 RED | `tests/agents/slo_agent/test_token_format.py` | format-red.log | 2; collection ModuleNotFoundError: token_format absent |
| 6 GREEN | `tests/agents/slo_agent/test_token_format.py tests/tui/test_usage_status_bar.py` | format-green.log | 0; 41 passed, 3 warnings |
| 7 post-Black regression | `tests/agents/slo_agent/test_session_identity.py tests/agents/slo_agent/test_token_format.py tests/cli/test_headless_request.py tests/cli/test_headless.py tests/cli/test_app.py tests/cli/test_typer_dispatch.py tests/tui/test_usage_status_bar.py tests/tui/test_usage_status_bar_plugins.py` | regression.log | 0; 188 passed, 5 warnings |

Exact formatting commands (both exit 0; logs black-format.log and black-check.log):

```bash
poetry run black src/agents/slo_agent/sessions/identity.py src/agents/slo_agent/sessions/token_format.py src/cli/headless_request.py src/tui/widgets/usage_status_bar.py tests/agents/slo_agent/test_session_identity.py tests/agents/slo_agent/test_token_format.py
poetry run black --check src/agents/slo_agent/sessions/identity.py src/agents/slo_agent/sessions/token_format.py src/cli/headless_request.py src/tui/widgets/usage_status_bar.py tests/agents/slo_agent/test_session_identity.py tests/agents/slo_agent/test_token_format.py
```

| Exact command | Log | Exit/result |
|---|---|---|
| `make test` | full-test.log; full-test.exit | 0; 6357 passed, 19 deselected, 412 warnings, 463.64s |
| `make smoke` | smoke.log | 0; 282 passed, 2 warnings |
| `make lint` | lint.log | 2; mypy: **348 errors in 66 files (checked 692 source files)** |
| `dpkg -V coreutils` after regression | coreutils.log | 0; silent |
| `dpkg -V coreutils` after full suite | coreutils-after-full.log | 0; silent |
| `git diff --check -- src/cli/headless_request.py src/tui/widgets/usage_status_bar.py` | tool output | 0; silent |

Lint is NOT green and NOT waived. Supplied historical baseline was 301 errors; this concurrent-worktree observation is 348. No diagnostic names any of this slice's six Python files. The difference has not been independently attributed and must not be called baseline-only. Complete output is retained, ending with `tests/cli/test_headless.py:808: error: Cannot assign to a method [method-assign]` and Make Error 1. Full-suite evidence includes concurrently present foundation work and is not a frozen integrated-feature receipt. No source/test edits in this slice followed those gates; this documentation records their actual results.

## Review and handoff

Reviewed exact CLI/footer diff and complete new support modules: only dependency ownership changes, one canonical predicate, preserved arithmetic/errors, no reverse import or environment relocation. New tests assert compatibility ownership and observable boundary values; existing footer/headless tests were run unchanged rather than rewriting them. No active integration or live compatibility claim. Full T1 still needs the other foundation lanes and later integrated review.

Supplied accounting preserved: turn 1 active; dispatch 7 consumed, 13 remaining of 20; unlimited turns; retries 0. This worker spawned no agents and does not increment workflow-completion counts.
