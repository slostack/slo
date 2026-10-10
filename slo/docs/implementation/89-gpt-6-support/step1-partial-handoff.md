# Feature 89 Step 1 — partial implementation handoff

## Verdict

NOT READY. Execution budget ended during 89.a.1. Concrete catalog/reasoning code and tests are retained. No b/d/c/e implementation, full suite, mypy, independent review or completion assessment is claimed. Do not install this partial tree: newly visible seed rows are not yet protected by factory/session enforcement.

Branch remains feature-gpt_6_support at ea8601c53f04fa06a0baeeb47d385c44cc9a5364; no commits, pushes, merges, application installs or provider inference.

## Implemented

- dao.py: strict seed-owned supports_chatgpt_codex/requires_responses_api; record-owned backend rejection and reasoning-override compatibility.
- seed.py: three distinct exact GPT entries, medium default and seven-level profiles; baseline Astra flags remain True/False.
- discovery.py: override guard before profile assignment.
- store.py: both flags excluded at raw provider-cache JSON writer only.
- reasoning_capabilities.py/openai_codex.py: explicit disabled effort survives; disabled summary is omitted, legacy absent effort remains omitted.

## Changed source/test files (application-relative)

1. src/agents/model_catalog/dao.py
2. src/agents/model_catalog/discovery.py
3. src/agents/model_catalog/seed.py
4. src/agents/model_catalog/store.py
5. src/agents/providers/openai_codex.py
6. src/agents/reasoning_capabilities.py
7. tests/agents/model_catalog/test_backend_eligibility.py (new)
8. tests/agents/model_catalog/test_cache_file_separation.py
9. tests/agents/model_catalog/test_model_catalog_overrides.py
10. tests/agents/model_catalog/test_model_catalog_seed.py
11. tests/agents/test_feature89_reasoning.py (new)

Black reformatted one pre-existing field in dao.py as part of changed-file formatting. The old Astra-only exclusion in the legacy-profile test now excludes the three new entries too; every previously covered legacy row still has the same assertions, and all new rows have exact positive assertions.

## Actual environment and isolation

Created dependency-only venv using `/root/.pyenv/versions/3.11.7/bin/python -m venv --copies .f89-evidence/venv`. No application installation. Installed exact pins for all 87 poetry.lock distributions into that worktree-owned venv, with isolated pip, no cache, HOME and TMPDIR within .f89-evidence. Provision log/exit: `.f89-evidence/provision.log`, `.exit` (0). Requirements are `.f89-evidence/requirements.txt`.

`.f89-evidence/versions.json` records interpreter and all 87 locked/actual version pairs; all matched. OpenAI 2.38.0, langchain-openai 0.3.35, langchain-core 0.3.86, Pydantic 2.13.4, httpx 0.28.1, Textual 8.2.8, Python 3.11.7.

Clean checkout has no environments/tests.env. Rather than reading another worktree or user env, `.f89-evidence/tests.env` contains the nonsecret Makefile fallback test settings. `.f89-evidence/run-test.sh` runs env -i with synthetic HOME/SLO_HOME, worktree TMPDIR/PYTHONPATH and sources that file before importing pytest. Root conftest's pre-import state isolation and per-test autouse isolation remain active. No live keys inherited. No real terminal spawn. New writer test verifies resolved containment beneath its fixture root before writing. No command-stub suite was run; read-only `dpkg -V coreutils` nevertheless returned 0 with empty output (`coreutils-integrity.log/.exit`).

Do NOT stage .f89-evidence wholesale: it contains the disposable venv and temp roots in addition to receipts.

## Red/green receipts

All below live in `.f89-evidence/`, each with `.command`, `.log`, `.exit`. The runner records the exact expanded pytest invocation; its script records environment setup.

| Receipt | Actual result |
|---|---|
| a-record-red | 24 failed, 6 passed, exit 1 (new error/record API absent) |
| a-record-green | 30 passed, exit 0 |
| a-record-surrounding | 362 passed, exit 0 |
| a-writer-red | 1 failed, 20 deselected, exit 1 (flags leaked to disk) |
| a-writer-green | 21 passed, exit 0 |
| a-writer-surrounding | 363 passed, exit 0 |
| a-seed-red | 3 failed, 33 deselected, exit 1 (missing IDs) |
| a-seed-green | 1 failed, 35 passed, exit 1 (old Astra-only test scope) |
| a-seed-surrounding | 1 failed, 481 passed, exit 1 (same test scope) |
| a-seed-surrounding-corrected | 482 passed, exit 0 |
| a-reasoning-red | 3 failed, 21 passed, exit 1 (disabled effort lost) |
| a-reasoning-green | 112 passed, exit 0 |
| a-reasoning-surrounding | 423 passed, exit 0 |
| a-override-red | 5 failed, 7 passed, 12 deselected, exit 1 (controls accepted) |
| a-override-green | 24 passed, exit 0 |
| a-override-surrounding | 378 passed, exit 0 |
| a-final-focused | 598 passed, 3 warnings, exit 0 after formatting and guard spy |

Final focused command:

```sh
bash .f89-evidence/run-test.sh a-final-focused -q tests/agents/model_catalog tests/agents/test_feature89_reasoning.py tests/agents/test_reasoning_capabilities.py tests/agents/test_ai_model_config.py tests/auth/test_provider_for_model.py tests/agents/providers/test_openai_codex.py tests/agents/test_base.py
```

Black check of all 11 changed/new Python files passed (`black-check.log/.exit`, 0). `git diff --check` passed. Full non-E2E and make lint NOT RUN. No static waiver claimed.

## Acceptance map — deliberately partial

- AC1: exact seed values tested; source AST duplicate registration/default projection proof still needed.
- AC2: 21 resolution/payload cells tested, plus disabled-summary/absent/inconsistent payload branches; full prescribed defaults/highest/invalid and frozen legacy matrix not finished.
- AC5: pure record conjunction tested across every provider/auth/permission combination; no factory/session credential enforcement yet.
- AC8: strict booleans, five schema-valid override controls (delegating record-guard spy) and all seven default-only changes tested; cold/refresh publication failure, merge/alias/removal matrix still needed.
- AC11: actual writer all-provider-slice field omission and memory copy tested; real frozen pre-feature schema-2 reader and released-reader coexistence NOT done.
- AC3/4/6/7/9/10/12/13/14/15: not established. Existing affected regression passes are not full acceptance.

## Precise next steps

1. Finish a.1 tests: source registration/default projection, both flag memory paths, cold invalid override leaves snapshot unset, failed refresh keeps publication/cache, DAO-invalid candidates never reach guard, real frozen schema2 writer compatibility.
2. Load remaining applicable provider/client, session/application-service, TUI, graph-test and documentation skills before editing those layers. Always-on typing/declarative/docstring/test-policy/code-loop and domain/test-domain skills were loaded. All seven specs and formal workflow fully read. Repo instructions/docs RESEARCH were in context; root RESEARCH read explicitly. KB Welcome/index/gotchas/catalog architecture/fork consulted; initial combined KB read truncated (README and gotchas reread separately), so reread architecture-overview fully before expanding design.
3. b.1 test-first: sole sanitizer, strict adapter, same captured credential factory guard, legacy temperature oracle against frozen source, complete real SDK tool cycles all 21 cells. Do not deploy visible seed before this.
4. d.1 generic absent/null predicate and literal Jev fixture/lifecycle tests.
5. c.1 atomic selection/pre-refresh eligibility and snapshot-pinned mounted UI.
6. e.1 composed tool/resume/pool/headless/compatibility; full inspected-safe non-E2E/static gates; independent review then fresh assessment by later agents.

No specs or shared KB were written. Durable worktree memory records this incomplete seam rather than claiming released support. The only environment deviation is the explicitly documented clean-checkout synthetic tests.env equivalent. Time/context budget, not a safety or dependency failure, stopped implementation.
