# 96.a.2 preflight — BLOCKED pending executable-fixture consent

## Authority and baseline

- S1: Exact implementation source: `/root/Code/specifications/projects/slo/specifications/96-agent-message-queue/96.a.2-cooperative-provider-and-tool-yield.md`. No revised sibling substituted. Initial reading covered sections 1–3.5 and 4–9; referenced prerequisite reading/routing remains incomplete because safety preflight blocked progress.
- S2: User request: implement ONLY A.2, preserve unrelated edits, no commit/push/merge/PR, no package/environment/infrastructure changes; prohibit DeepSeek modification of ANY bin files/directories or executable/binary artifacts, including indirect test/script mutation; stop for consent if required.
- W1: Authoritative installed `orchestration/workflows/code-test-review.md` and shared `orchestration/workflows/SKILL.md`, read in full from skills root below. Required pipeline: runnable Code+Test milestone → independent read-only early feedback (no reviewer test execution) → acceptance-ready Code+Test/full/static gates → independent final review → independent completion check. Cannot replace required full suite with selected totals.
- Repository: `/root/Code/slo-message-queue/slo`; dedicated branch `message-queue`; HEAD verified `82c3f5c6de9345af34a673a3d975366ca8c1624c` (completed durable-composer baseline).
- Preexisting dirty/untracked work: `SLO.md`, `docs/`, numerous `release-evidence/96-durable-composer/*.md` handoffs. Preserve all. No product code changed during this preflight.
- `SLO_SKILLS_DIR` and `SLO_SKILL_DIR` both resolve to `/root/.local/share/pipx/venvs/slo/lib/python3.11/site-packages/skills`; no alias conflict. Installed guidance governs this task. Current explicit user authorization for task-local release evidence supersedes historical external-KB-only location advice; no docs edits authorized.

## Safety blocker B1

Source inspected directly: `tests/cli/test_deploy_install_worker.py:14–49`.

`_write_stub_tools` creates `root / 'bin'`, writes `bin/curl` as a shell stub, and calls `curl.chmod(0o755)`. `_run_deploy` invokes it with `root=tmp_path`. This unmarked test module belongs to the project's required default non-E2E suite. The paths are disposable but the user prohibition explicitly includes any bin directories and executable artifacts; temp ownership is not an implicit exception.

Read-only search also found executable-fixture creation/chmod in `tests/conftest.py`, `tests/cli/test_install.py`, `test_update.py`, `test_isolated_launcher.py`, and others. This is not an exhaustive safety certification.

**Closure decision required:** Does the operator authorize existing tests to create/change disposable fake command executables and bin directories only within their own verified temp roots, while preserving the ban on installed/system executables and all other bin/artifact changes? Scope must be explicit before any affected test execution. Do not bypass via a different model or waive/exclude tests. If consent is denied, the full gate is blocked unless the operator authorizes another compliant verification contract.

No executable-fixture tests, baseline pytest, full suite, formatting, lint, or runtime feature tests were run. No bin files changed. No sub-agent dispatched because the blocking consent requirement was discovered before Step 1.

## Preliminary routing/acceptance contract (not complete)

Stack from project manifest/spec: Python 3.11, asyncio, Pydantic 2, LangChain/LangGraph, Textual/Rich, SQLite, real flat/tree history adapters. No new dependency or SQL schema change. Generic routing/testing/ownership and overarching solution-design/coding-rules/naming/test-verification policies read; Python root, named-arguments/type-hints, declarative specialization and docstring guidance inspected. Remaining applicable recipes, override manifest, required owner code and prerequisite references must be read before implementation. Root SLO.md read; root AGENTS.md/CLAUDE.md and docs/RESEARCH.md absent in inspected paths. README relevant architecture/testing/maintainer sections inspected; KB Welcome/Slo index read. Do not claim completed routing from this partial record.

Stable source acceptance IDs from S1 §9.1, all OPEN/unverified:

| ID | Required outcome / principal risk |
|---|---|
| A1 / AC01 | Silent provider urgent delivery via real client/session/SQLite; joined reader before next provider request |
| A2 / AC02 | Default-defer actual effects/results retained, no inferred rollback |
| A3 / AC03 | Sequential/concurrent exact ordered tool pairing, no abandoned starts |
| A4 / AC04 | Cancellation acknowledgement matrix, one callback, joined handles, actual result wins |
| A5 / AC05 | Original child pool/spawn aggregate preserved; no A.3 pending protocol |
| A6 / AC06 | Mounted normal/urgent keys/fallbacks/slash precedence and visible interruption |
| A7 / AC07 | Newer high-water only, cached slots/retry cursor, one boundary advance |
| A8 | Both-adapter append-once/no-start/raw validation/crash uncertainty fails closed |
| A9 | Multiple correlated interruptions survive replay/export; no private-context leakage |
| A10 | Read/abort/deadline/yield precedence, repeated cancellation and close joins |
| A11 | Binding/factory/rebuild/retry/shutdown ownership, no extra claims/provider calls |
| A12 | Concrete capability identity, strict live guard, result status and atomic compaction |
| A13 | Urgent immutable draft/unknown-outcome preservation, no downgrade |
| A14 | Real offloaded leaf permits editing and paint; two themes × three specified sizes |

S1 §§3.5 and 5.4 also require bounded nonblocking observer publication and actual offload joins; these are A.2 obligations, not an authorization to implement B.2/C.1. No IPC, attached composer, Inbox retirement, arbitrary rollback, replacement supervisor/pool, SQL migration or ASCII-tree work.

## Verification contract discovered (not executed)

- Cwd: repository root above. No readable `environments/tests.env` exists; inspect again on continuation. Makefile fallback provides synthetic test variables; never source development credentials.
- Existing approved interpreter verified by read-only import command: `/root/.pyenv/versions/slo-harness/bin/python`, Python 3.11.7; pytest 9.0.3, xdist 3.8.0, PyYAML 6.0.3, mypy 1.20.2, Black 26.5.1 import successfully. No packages installed/changed. Poetry mapping needs explicit verification before use; `PYENV_VERSION=slo-harness poetry env info -p` printed no path in the combined diagnostic command, so do not infer a verified mapping.
- Project full gate: `make test PYTEST_WORKERS=6`, invoking `PYTHONPATH="$PWD" poetry run pytest -n 6 -m 'not e2e'` under reviewed fallback environment. This is the complete project non-E2E contract; existing `e2e` exclusion is tracked policy, not newly added. Full counts/skips/warnings unknown for current task, not inherited from earlier feature.
- Static gate: `make lint` (`poetry run mypy src/ tests/`). Black check scoped to relevant changed paths plus project requirements, preserving unrelated baseline.
- Focused commands/scenario paths: S1 §9.2, to be instantiated and safety-reviewed after consent and recipe reading. New files do not yet exist.
- Required evidence: RED/GREEN receipts, exact cwd/env/command/exit/counts/exclusions/warnings; real entry-to-persistence outcomes and forbidden effects. No approved baseline exception, skip, xfail or scope deferral.

## Models, counters and next step

Requested orchestration/review/completion: `gpt-6.1-sol`, reasoning high. Code+Test primary exactly `openrouter:deepseek/deepseek-v4.1-flash-1017`, supported default reasoning. Fallback `gpt-6.1-sol`, reasoning medium ONLY after concrete OpenRouter token/quota exhaustion; unknown-model/unrelated errors are not fallback permission. Child model support has not been probed; no model substitution or fallback used. The running orchestrator's model cannot be reconfigured by shell exports or tool parameters.

Effective limits: 60 workflow turns started / 20 dispatch calls per turn; initial+3 failed-execution retries; never retry an abort. No historic 8/6 cap. Counts: 0 turns started, 0 completed, 0 partial; 0 dispatch calls; 0 retries. Setup blocked before Step 1; review/completion not run and not claimed.

Next authorized action: obtain B1 consent. Then finish prerequisite/routing reads and safety audit, persist complete contract, verify exact primary-model support through real dispatch, and start bounded test-first milestone assignments returning well before the 3h parent inactivity threshold. Never launch nested detached orchestration, change watchdog infrastructure, or commit/push without new authorization.
