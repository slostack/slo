# 96.a.2 routing record — read-only preflight

**Status:** setup dispatch 1. No workflow turn started, no product code changed, no test executed.
**Repository:** `/root/Code/slo-message-queue/slo` (application root); git root `/root/Code/slo-message-queue`.
**Branch/HEAD:** `message-queue` / `82c3f5c6de9345af34a673a3d975366ca8c1624c` (`durable-composer Complete durable submission and regression fixes`).
**Authoritative task source:** `/root/Code/specifications/projects/slo/specifications/96-agent-message-queue/96.a.2-cooperative-provider-and-tool-yield.md` (1309 lines, read in full in this preflight), plus `overview.md` §2–7 and `request.md` §4.3–6/10–11. A.1/A.3/C.1 were treated as read-only context; no revised A.2 sibling was substituted.

## 1. Active skill root and discovery limits

- `SLO_SKILL_DIR` and `SLO_SKILLS_DIR` both resolve to
  `/root/.local/share/pipx/venvs/slo/lib/python3.11/site-packages/skills`.
- `skills/INDEX.md` exists and was read. It states it is **not** the complete installed catalog.
- No stable runtime manifest file was found at `/root/.slo` or under the installed skill root. `/root/.slo/recovery-snapshots/*/manifest.json` files are recovery snapshots, not skill manifests. Therefore no claim is made that a runtime manifest exists.
- Installed user skills visible at `/root/.slo/user_skills/`: `code-diff-viewer`, `present-as-pdf-book`. Both are unrelated to A.2 and are not selected.
- Skill/override comparison therefore has this limit: the bundled INDEX and the visible user-skill directory were checked, but no authoritative runtime manifest was available to enumerate every override. No user override was used to waive a bundled rule.

## 2. Selected sources and tiers

Tier labels are routing provenance, not implementation evidence.

| Tier | Selected absolute source(s) | Concrete rule carried forward |
|---|---|---|
| Project / task | `/root/Code/slo-message-queue/slo/README.md` (architecture, runtime chain, ch. 4.7, 4.12, 5.6, 8, 9, Maintainer Reference); `/root/Code/slo-message-queue/slo/SLO.md`; A.2 spec; overview; request | One session-owned scheduler/queue, one agent live-context writer; real journey from editor/client/session through SQLite/history; no new daemon, SQL schema, dependencies, or framework; preserve unrelated dirty work |
| Workflow | `skills/orchestration/workflows/code-test-review.md`; `skills/orchestration/workflows/SKILL.md` | Code+Test -> independent read-only early review -> hardening/full gates -> independent final review -> independent completion. Never skip a gate; never replace full suite with a focused total; 60 turns/20 dispatches per turn; initial + 3 failed-execution retries only; never retry an abort |
| Shared engineering | `skills/engineering/engineering-routing/SKILL.md`, `engineering-testing/SKILL.md`, `engineering-ownership/SKILL.md` | Scoped routing; real boundaries; one owner per resource/lifecycle; evidence must name command/cwd/env/exit/counts; unavailable gate is BLOCKED, not green |
| Overarching coding | `skills/coding/solution-design/SKILL.md`, `coding-rules/SKILL.md`, `naming-and-clarity/SKILL.md`, `test-verification-policy/SKILL.md`, `declarative-method-structure/SKILL.md` | Deep cohesive module/seam; Tell-don't-ask; flat declarative steps; intent-revealing domain names; journey first; real DB/files; mocks only third-party APIs; injected stubs otherwise; end-to-end sparingly |
| Python root | `skills/languages/python/python-conventions/SKILL.md`; `named-arguments-and-type-hints/SKILL.md`; `method-docstrings/SKILL.md`; `declarative-method-structure/SKILL.md` | Python 3.11, explicit parameter/return types, keyword calls for multi-argument calls, Google-style behavioral/error/lifetime docstrings, coherent ~8-line decomposition signal, no FastAPI/SQLAlchemy/DBOS/Celery acquisition |
| Agent/graph recipes | `skills/languages/python/build-react-agent-with-langgraph/SKILL.md`; `build-agent-tools/SKILL.md`; `build-application-services/SKILL.md`; `graph-gateway-invoke-convention/SKILL.md`; `test-graphs-and-agents/SKILL.md`; `test-app-services/SKILL.md` | Preserve the existing one-shot graph/invoke gateway; typed state and boundaries; real graph/session tests with FauxChatModel; no second graph driver or test DSL |
| TUI recipe | `skills/tui/build-textual-tuis/SKILL.md` (plus README ch. 3/4/8 and KB TUI notes) | App/router/renderer/widget boundaries; Pilot drives the real app; no scraping internals; no new visual panel/process for A.2 |
| Knowledge base | `/root/Code/KnowledgeBase/KB/Welcome.md`; `KB/slo/README.md`; `KB/slo/tui-cli-session.md`; `KB/slo/gotchas.md`; `KB/slo/message-hierarchy-and-control-flow.md`; `KB/slo/operational-reference.md` | A.1 composer is local and currently `supported_priorities={'normal'}`; `AIMessageChunk` is live UX, completed `AIMessage` is truth; history paths are `sessions/{dao,service}.py` and `history/{filesystem_store,tree_store}.py`; read `tests.env` only if readable |

## 3. Stack and scope decision

- **In scope:** Python 3.11 / `asyncio` / Pydantic 2 / LangGraph 0.4 + LangChain 0.3 / Textual 8 + Rich / stdlib SQLite / flat and tree JSONL history.
- **No new:** SQL table, column, index, version or migration; Python dependency; FastAPI/ORM/Postgres/Alembic/Go/TypeScript/Vue; IPC, attached composer, Inbox retirement, replacement supervisor/pool, A.3 pending protocol, C.1 duplicate modules, generic plugin registry.
- **No docs edits:** no writes to `slo/SLO.md`, `slo/docs/`, `RESEARCH.md`, the repository KB copy, or existing durable-composer reports. Only these four task-local evidence files are written.
- **Preservation:** the pre-existing dirty `SLO.md`, untracked `docs/`, and all `release-evidence/96-durable-composer/*.md` files remain untouched. `preflight-blocker.md` is byte-preserved (SHA-256 `10fe2372f972374580d6071578c543edad98fd811a43ce2b0857cdb282183638`).

## 4. Current code dependencies verified statically

These are source facts, not acceptance evidence.

| Dependency | Current state at HEAD |
|---|---|
| `src/tui/app.py` | Host input controller exists; `supported_priorities=frozenset({"normal"})` at line 1144; `on_prompt_input_component_submitted` line 2371; `_submit_durable_draft` line 2752; `_submit_messaging_steer` line 2785 |
| `src/tui/components/prompt_input/component.py` | `Submitted` line 181, key handling line 487, `build_draft_submission` line 984, `_handle_draft_submission` line 1031; no semantic priority yet |
| `src/agents/slo_agent/messaging/client.py` | Client already accepts both priorities by default (line 111); composer narrows to normal |
| `src/agents/slo_agent/sessions/service.py` | A.1 owner `start_messaging` 915, `_start_messaging_owned` 935, `_run_message_scheduler` 995, `take_one` 1147, `commit_applied` 1235, `_build_agent` 2685, `_ensure_agent_ready` 7286, `_stream_prompt_with_retries` 6796, `_run_attempt_lifecycle` 5827, `_derive_next_attempt_plan` 6324, `_dispatch_event` 8162 |
| `src/agents/slo_agent/agent.py` | `invoke` 1374, `_stream_graph_turn` 702, `_execute_iteration_with_retry` 920, `_react_loop` 1011, `_close_graph_stream` 838, `_apply_message_boundary` 1114, `_should_loop_continue` 879, `_decide_iteration_recovery` 1178; no A.2 control/policy |
| `src/agents/slo_agent/watchdog_timer.py` | `WatchDogTimer.invoke(*, graph_stream)` at line 61 returns raw item; deadline/tool-suspension state exists; no urgent/yield race |
| `src/agents/slo_agent/graph/service.py` | `_make_agent_node` 169, `_make_tool_node` 254, `_select_tool_executor` 373, `build_slo_agent` 412; no control/policy |
| `src/agents/slo_agent/tool_execution/executors.py` | `ToolExecutor` 35, base `execute` 58, `_invoke_one` 70, `_prepare_output_update_transport` 216, sequential 275, concurrent 294; no yield guards |
| `src/agents/slo_agent/tool_execution/dao.py` | Existing execution DAOs exist; `yield_policy.py` and A.2 carriers are absent |
| History | `SessionHistoryStoreProtocol` has `append_event`, `append_message_application_once`, `application_evidence`; both stores implement them. `MessageContractReconciler.reconcile` 43; projector `context_events` 113 / `_context_event_slice` 136; transcript `TranscriptEntryDAO` 47 / `ReplayEntryProjector` 447; runtime `TraceEventKind` 33 lacks `run_retrying`; stream kinds include `run_retrying` but no yield/interruption kinds |
| A.1 tests | `tests/agents/slo_agent/messaging/` has real client/delivery/queue/store/ownership journeys; `tests/integration/` currently has no `test_messaging_yield.py` |

## 5. Environment and verification commands

Read-only checks performed in this preflight:

```bash
cd /root/Code/slo-message-queue/slo
test -r environments/tests.env          # absent -> Makefile fallback
/root/.pyenv/versions/slo-harness/bin/python -c '...'  # 3.11.7, pytest 9.0.3, xdist 3.8.0, PyYAML 6.0.3, mypy 1.20.2, Black 26.5.1
poetry env info                          # no project virtualenv; Python 3.11.7, Path NA
poetry run python -c '...'              # /root/.pyenv/versions/3.11.7/bin/python, 3.11.7
readlink -f /root/.pyenv/versions/slo-harness/bin/python
                                        # /root/.pyenv/versions/3.11.7/bin/python3.11
```

**Verified mapping:** `slo-harness` resolves to the same CPython 3.11.7 binary that Poetry uses. Poetry reports no project virtualenv and skips virtualenv creation; no package or environment change was made. No `environments/tests.env` is readable, so the tracked Makefile fallback is the only environment contract.

**Safe focused development pattern after implementation (not run in this preflight):**

```bash
cd /root/Code/slo-message-queue/slo
export SLO_ENV=test SLO_ROOT_DIR="$PWD" SLO_APP_DIR="$PWD" SLO_APP_NAME=slo
export SLO_LOG_FORMAT=text SLO_DEFAULT_MODEL_NAME=gpt-5.4
export SLO_AUTO_VISUALIZE=0 SLO_HERDR_DISABLED=1
export SLO_ANTHROPIC_API_KEY=ci-placeholder-tests-are-fully-mocked
export COLUMNS=120 LINES=40 PYTHONDONTWRITEBYTECODE=1
PYTHONPATH="$PWD" poetry run pytest -p no:cacheprovider -m 'not e2e' \
  tests/agents/slo_agent/history/test_message_contract_reconciler.py \
  tests/agents/slo_agent/history/test_transcript.py \
  tests/agents/slo_agent/test_watchdog_timer.py
```

New A.2 test files must be audited for executable-fixture creation before they are run. See `safety-audit.md` for the exact focused-command boundary.

**Unsafe/blocked gates (do not run, do not substitute):**

```bash
make test PYTEST_WORKERS=6     # BLOCKED: full non-e2e suite executes unauthorized executable fixtures/subprocesses
make test-serial              # same complete suite, also BLOCKED
make lint                     # static, proposed; baseline unverified
black --check <changed paths> # static, proposed; baseline unverified
```

**No baseline counts exist.** No test, collect-only, lint, Black, or feature run was executed in this assignment. Every baseline/gate claim below is labeled UNVERIFIED.

## 6. Open decisions and limits

1. **Milestone shape:** recommended M1 is T1 + T2 only (history/strict-settlement foundation plus the silent-provider vertical path through real local client/session/SQLite/history), with the host still normal-only. Tools (T3) and TUI activation (T4) follow only after M1 evidence. This keeps activation coherent and avoids a partially-urgent composer.
2. **Cancellation registry:** no initial `cancel_confirmed` built-in registration. All built-ins/plugins/thread-backed work/spawn defer. The policy/port seam exists, but the safe default is defer.
3. **History-disabled sessions:** must expose the same transient joins/strict pairing/control gates while making no durable interruption/recovery claim. This is a required test branch, not a fallback for durable storage failure.
4. **No full-suite substitute:** `make test PYTEST_WORKERS=6` remains required. A focused total, affected suite, or selected files cannot stand in for it. No skip/xfail/baseline waiver is approved.
5. **Focused-test consent boundary:** the operator's narrow consent names only `tests/cli/test_deploy_install_worker.py`. This preflight does not broaden that exception. Proposed A.2 focused tests create no executable fixtures, but execution of any other existing test module must be re-audited and explicitly treated as safe before running; the full suite stays blocked.
6. **Static-gate baseline:** `make lint` and `black --check` have not been run. Their current baseline is unverified; later findings must be separated into baseline vs introduced, and no autoformat of unrelated dirty work is allowed.
7. **Review independence:** early review is read-only and does not run tests; final review and completion are independent later `gpt-6.1-sol` high-reasoning assignments. Author evidence and self-check do not substitute.
8. **Model fallback:** Code+Test primary is the exact assigned DeepSeek model with default reasoning. `gpt-6.1-sol` medium is permissible only after concrete OpenRouter token/quota exhaustion; unknown-model or unrelated errors are reported, not substituted.

## 7. Routing verdict

The selected set is sufficient and scoped. No FastAPI, ORM, Alembic, Go, TypeScript, Vue, or new test-harness guidance was loaded. The only unresolved routing limit is the unavailable exhaustive runtime manifest noted in §1. This limit does not block implementation; it does block any claim that every installed override was enumerated.
