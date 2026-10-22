# Slo Codebase Index

CI repair fan-in (2026-10-21): [integrated gates](docs/implementation/94-herdr/ci-repair-integrated-gates.md).
Full10508/smoke296/lint852/Black17 pass; independent Review/Completion and CI pending.
Pin model-policy and terminal-width inputs in affected fixtures, not operator
environment files. Explicitly select `VIRTUAL_ENV` for Poetry: `pyenv which python`
alone does not prove which interpreter `poetry run` uses. Live Herdr remains deferred.


Acquisition170: [bounded correction](docs/implementation/94-herdr/acquisition-owner-170.md).
Failed pane acquisition can retain a lease without usable admission. Reporter final
cleanup/evidence now reads sequence-owner truth, not `_lease_held`. Native-lock/load
rollback matrix covers reporter and session drain; core1229/surrounds969 and scoped
statics pass. Author bounded READY only; fresh full gates and independent core
verification still required. Live USER-DEFERRED; compatibility UNVERIFIED.

Core168: [final author gates](docs/implementation/94-herdr/final-core-gates-168.md). Finite public-API documentation
audit complete; full8727/smoke288/lint813 and exact chapter/surrounding/Black
gates pass on unchanged1063 comprehensive inputs. Intermediate default drain
remains distinct from final disposal evidence; null final cleanup is independent.
Author READY OFFLINE only; independent core/wiring/harness/full review and fresh
Completion remain pending. Live USER-DEFERRED, compatibility UNVERIFIED.

Close167: [bounded regression receipt](docs/implementation/94-herdr/close-regression-167.md).
Final gateway failures cannot inherit intermediate default drained evidence.
Null final cleanup independently proves no resources rather than retrying its
intermediate close; session retains prior uncertainty. Focused/surrounding426
pass, scoped static5 clean. Full gates and R161-4 API ledger remain next;
feature REVISE, live DEFERRED/compatibility UNVERIFIED.

Core165: [contract correction receipt](docs/implementation/94-herdr/core-contracts-165.md).
Intermediate reporter close reports remote/sticky defects, not normal lease
retention; only final session close grants disposal evidence. Session aggregation
preserves all uncertainty. Owned1113/surrounds745 pass; public API documentation
expanded but exhaustive R161-4 audit remains pending. Combined assignment REVISE;
full make gates and independent re-review remain separate.

Core164: [bounded R161-1/2 receipt](docs/implementation/94-herdr/core-owner-164.md).
Restore stores retain one lease across operation cleanup failure; overlapping
operations/cleanup refuse nonblocking. Reporter final drain includes that owner.
An ambiguous close is never retried on its raw descriptor: same inode is not
same generation. Proven absence clears resources but not prior cleanup uncertainty.
R161-3/4 and independent re-review remain pending; no full-suite/live claim.

Revision160 integration: [receipt](docs/implementation/94-herdr/integration-revision-160.md).
Do not reload `sessions.service` merely to refresh config in tests: it replaces the
session class while headless/TUI consumers retain the old import, so later build
patches miss their target. Reload config only; retain a class-identity regression.
Exact combined1835 and full8680 now pass; independent Review/Completion pending.

Current revision156: [docs/implementation/94-herdr/profile-revision-156.md](docs/implementation/94-herdr/profile-revision-156.md) corrects the captured metadata-profile
connection to session publication. Validated activation profile is retained by the
session; events never reread it. Composed interactive/headless profile tests and
full8675/smoke288/lint805 pass. Independent review155 remains unfinished (R155-2);
fresh Completion pending; live user-deferred/compatibility UNVERIFIED. Earlier
154 readiness below is historical author evidence, not independent approval.

This root-level index is the project memory entry required for feature work. The
maintained runtime owner map and easy-to-break rules live in the knowledge base at
KB `slo/codebase-index.md` (moved there from the former `docs/RESEARCH.md`); read
that page before planning or changing a feature.

## Optional Herdr integration

Current author checkpoint: [integrated154](docs/implementation/94-herdr/integrated-gates-154.md)
marks T1–T6 **Code+Test READY USER-APPROVED OFFLINE**: full8667, smoke288,
exact chapter/surrounding gates, clean full lint804 and Black214; unchanged843-input
manifest. Independent full-feature Review and fresh Completion remain pending.
Live installed-launcher/native-restart/version/panes/paint/TTL/release acceptance is
explicitly user-deferred; compatibility UNVERIFIED. Older static-red/live-blocking
status below is historical. No global ordinary-tool redactor is promised.

Read runtime owners and acceptance boundaries in KB `slo/codebase-index.md` → "Feature 94 Herdr — runtime ownership and acceptance boundary"
and setup/privacy/retention/rollback in KB `slo/install-guide.md` → "Optional Herdr integration".
Session supplies private immutable capture; reporter owns save association and
transport admission; app owns lifetime and viewer task registration. Restore is
exact saved policy with current history, using the same SLO_HOME/default history
and plain installed Slo, not automatic prompt replay. Records have no automatic GC.
Claimed inbox refusal requires investigation before explicit resubmission. Herdr
0.9.2+ compatibility and live pane/restart evidence remain unproven; static failures
are unwaived. Current [T6 accounting correction151](docs/implementation/94-herdr/t6-accounting-fix-151.md)
proves the observer must count terminal return OR cancellation, not only returned
DAOs: real transport cancellation joins resources and completes owner accounting
before raising. Deterministic replacement coverage and full8653/D091669 pass.
The bounded fix is READY OFFLINE; overall T6 remains REVISE for unwaived lint281/58
and outstanding independent/live gates. No independent/live approval is claimed.
See historical [T6 docs/static diagnosis](docs/implementation/94-herdr/t6-docs-static-121.md).

## Rate-limit preflight

- `src/agents/slo_agent/sessions/service.py` owns session-local request and token
  windows, advisory preflight waits, cooldown status, and the provider-stream
  boundary.
- `src/agents/slo_agent/sessions/dao.py` holds immutable session-scoped data
  carriers.
- Local rate-limit calculations are advisory. Provider outcomes remain the source
  of truth for request-size, context, quota, and rate-limit decisions. Each successful
  `PreflightDecisionDAO` owns the exact estimate reused for local accounting and redacted
  provider-limit observations; failed local preflight writes no accounting.
- `preflight_bypassed` and `provider_limit_observed` are audit-only history events,
  excluded from model replay. A confirmed initial context overflow retries only after
  committed compaction; a no-op/failed compaction, a second or visible failure, and HTTP
  413 do not retry.

## Installer launcher finalization

- `install.sh` discovers the authoritative pipx root only through `pipx environment --value PIPX_HOME`; an exported `PIPX_HOME` must never be used as a recovery fallback.
- The isolated-launcher finalizer treats `mktemp` output as hostile until its canonical parent is exactly the validated pipx `venvs/slo/bin` directory and its filename remains a `.slo.*` stage. Revalidate before stage write, file fsync, chmod, activation, and cleanup; cleanup must not delete a rejected external path.
- The release Docker matrix supplies `SLO_INSTALL_SMOKE_IMAGE`; `tests/cli/test_install_smoke.py` validates and runs exactly that supported image, and the repository-parent mount exposes its helper at `/src/slo/tests/cli/install_smoke_container.sh`.

## Feature 87 skills reorganization integration

- Authored skills now follow ownership boundaries: generic coding/engineering rules stay generic, while Python, Go, TypeScript, and frontend recipes own language/framework requirements. Removed non-declarative `skills/coding/` redirects are fully mapped in the attempt-2 worker ledger; old paths must not be treated as active recipes.
- `skills/coding/declarative-method-structure/SKILL.md` is the active shared owner with Python/Go/TypeScript specializations. Its historical source is explicitly reconstructed/evidence-based rather than claimed byte-for-byte; the complete old forwarder is preserved in the external attempt-2 ledger.
- `skills/INDEX.md` is generated only by `make refresh-skills` or `make build-skill-index`. Packaging checks enumerate the current filesystem so untracked authored skills are included and deleted files excluded.
- Active links to removed redirects must be distinguished from fixture paths, source examples, generated index text, and historical inventory/ledger records. Final integration evidence: `/root/Code/specifications/projects/slo/specifications/87-skills-reorganization/attempt-2/final-integration-ledger-20261011T185600Z.md`.

## Feature 95 scoped skill maintenance

- Workflow definitions and orchestration skills now live in `skills/orchestration/`;
  names and runtime user/workflow override precedence are unchanged. In the
  original relocation baseline, the six moved files retained base content except
  frontmatter group and relocation references. Subsequently accepted mode-removal
  and headless reasoning amendments intentionally changed five moved bodies:
  the four workflow resources and the headless guide. The relocation-only claim
  is historical, not a description of those final amended bodies.
- The scheduled TUI skills are explicitly frozen except for the repaired headless
  pointer to `skills/orchestration/headless-orchestration/SKILL.md`; reference
  validation no longer exempts the old link. In
  `tests/agents/skills/test_orchestration_relocation.py`, normalization covers
  only that exact source/target pair: the repaired link is mapped back to its
  old path before hashing, retaining the original historical hash rather than
  repinning the changed body.
- Context gathering is an on-request, language-neutral evidence companion;
  unavailable sources are not empty findings. Solution-design's vertical addendum
  refines its existing document contract without authorizing a design exercise.

## Feature 94 TUI session controls

- The native TUI shows owned workflow sessions in one "Ongoing workflow tasks" list below
  the editor. Enter or click opens a 5-second live progress modal, and a confirmed
  "Abort child…" stops one child. Herdr is excluded.
- Single owners: `TaskPreview` labels, `ProcessRegistry.commit_terminal` terminal winners,
  one `WorkflowProgressCoordinator` timer, `DetachedWorkflowAppService` as the list/progress
  and abort gateway, and `SubAgentPool.abort_child` as the only child stopper. Execution
  identity lives only in additive `*.v1.json` siblings, so released readers and rollback stay
  safe.
- Owner map, easy-to-break rules and rollback: KB `slo/codebase-index.md`
  "Feature 94 — TUI session controls".

## Feature 96 A.1 messaging (private partial module, not activated)

- `messaging/ownership.py` owns only an execution lease; the caller must join
  execution/history/store writers before release. Persistent lock traversal is
  descriptor-relative/no-follow; ephemeral exclusion is process-local. Repeated
  cancellation and concurrent release waiters join one owned cleanup task.
- `messaging/store.py` owns a dedicated SQLite worker. A shield alone does not
  join cancellation: worker futures and startup/close tasks must settle before
  their callers can drop barriers. SQLite `executescript` implicitly commits a
  preceding BEGIN; atomic schema creation starts BEGIN inside the script.
- This package is incomplete and unsafe to activate yet. Store path/WAL/SHM
  containment, schema/cross-record validation, local recovery, exact event
  evidence and paging remain open. Queue/client/delivery remain skeletons.
  Current bounded evidence and finite remainder:
  `docs/implementation/96-a1-messaging/change2-retry1.md` (REVISE).

## Verification

- Focused session-rate-limit coverage is under
  `tests/agents/slo_agent/test_session_rate_limits.py` and
  `tests/agents/slo_agent/test_session.py`.
- Use `make test` for the non-E2E suite and `make lint` for static checking.

# Operational reference

Exact values, commands, decision rules and how-tos consolidated on 2026-10-21 from the
removed `AGENTS.md` and `docs/` guides. Architecture and ownership live in `README.md`;
long-form guides live in the knowledge base (KB `slo/install-guide.md`,
`slo/headless-guide.md`, `slo/scheduler-guide.md`). Conflicting defaults were resolved
against source: bash timeout 1800 s, child concurrency 6.

## Development environment and commands

- Python 3.11.7 via pyenv virtualenv named `slo`; `pyproject.toml` requires `>=3.11,<3.12`. Never system Python (macOS default 3.9).
- One-time setup: `pyenv virtualenv 3.11.7 slo && (cd slo && pyenv local slo)`; `.python-version` auto-activates on `cd`.
- Install: `poetry install` (not `--no-root`) with the venv active; `poetry.toml` has `virtualenvs.create=false`.
- Non-interactive shells: verify `which python` → `~/.pyenv/versions/slo/bin/python` before running anything.
- `make test` — sources a readable `environments/tests.env`, else exports the tracked Makefile fallback (`SLO_ENV=test`, `SLO_DEFAULT_MODEL_NAME=gpt-5.4`, `SLO_AUTO_VISUALIZE=0`, `SLO_HERDR_DISABLED=1`, placeholder `SLO_ANTHROPIC_API_KEY`, `COLUMNS=120`, `LINES=40`); always forces `SLO_HERDR_DISABLED=1`; runs `pytest -m "not e2e"`.
- `make test-env` — prints `tests.env` or `fallback`; creates nothing.
- `make smoke` — smoke-only `tests/test_smoke.py`, same environment selection.
- `make lint` — `poetry run mypy src/ tests/`.
- `make format` — `poetry run black src/ tests/` (line length 110).
- `make build-skill-index` / `make refresh-skills` — regenerate `skills/INDEX.md` from committed `SKILL.md` files (same builder).
- `make install` — `install.sh` → pipx install, then finalise `~/.slo/shell/` managed environment file.
- e2e only with real credentials intentionally in scope: `pytest -m e2e`.
- `asyncio_mode = "auto"` in `pyproject.toml`.

## Test-suite guards

- Default gate `pytest -m "not e2e"` set in `pyproject.toml` `addopts`.
- `SLO_AUTO_VISUALIZE=0` comes from `environments/tests.env` or the Makefile fallback (covers `make test`); CI sets the same variables in `.gitlab-ci.yml`.
- Autouse fixture `_never_spawn_real_terminals` in `tests/conftest.py` stubs `VisualizerLauncher._default_spawn` (covers bare `pytest`).
- Regression test: `tests/tui/test_visualizer_launcher.py::TestSuiteNeverSpawnsRealTerminals`.
- Any test reaching `VisualizerLauncher.launch()` (via `sub_agent_spawned` or a `launch_workflow` tool result through `SloTUI._render_event`) must patch `VisualizerLauncher.launch` or inject `spawn=`.
- Manual smoke: quit every `slo visualize` process/window opened.
- Markdown selection coverage: `test_markdown_content_compiler.py`, `test_user_message_block.py`, `test_selection_scroll_highlight.py`, `test_selection_copy.py`, `test_selection_copy_e2e.py`.
- Mirror regression: `tests/cli/test_update_mirror.py`, `tests/cli/test_install_mirror.py`.
- Skills reorganization fixtures: `tests/agents/skills/fixtures/reorganization/`.

## Orchestrator and headless timeouts

- `SLO_STREAM_INACTIVITY_TIMEOUT_SECONDS` default `10800` (3 h) — orchestrator's own stream guard; ceiling per blocking `spawn_sub_agents` phase. [src: config/cfg.py, spawn_tool.py]
- `SLO_SUBAGENT_INACTIVITY_TIMEOUT_SECONDS` default `7200` (2 h) between child stdout lines; alias `SLO_SUBAGENT_INACTIVITY_TIMEOUT`. [src: orchestrator/process.py]
- Rule: parent guard strictly greater than child guard.
- Export before the orchestrator starts, in its launching shell:
  - `export SLO_STREAM_INACTIVITY_TIMEOUT_SECONDS=10800`
  - `export SLO_SUBAGENT_INACTIVITY_TIMEOUT_SECONDS=7200`
- AGENTS.md also said "or re-export via a `bash` tool call before the first `spawn_sub_agents`"; the shipped orchestrator prompt (`spawn_tool.py`) states a Bash tool export cannot change the running orchestrator → do not rely on it.
- Hang symptom: `TimeoutError: main agent stream produced no events for <N>s; treated as hung`.
- Trigger example: long Go `go test -race ./...` gates. Mitigation: split phases.
- `SLO_HEADLESS_HEARTBEAT_SECONDS` default `15` (stderr-only `headless_status`; states `healthy` / `degraded` / `silent`; advisory only). [src: cli/headless_watchdog.py]
- Cancellation: SIGTERM → grace → SIGKILL → reap; one cached terminal result.
- `SubAgentResultDAO` additive redacted fields: `failure_code`, `partial_output_committed`, `attempts`, `safe_message`.
- KB background: `slo/headless-workflow-orchestration.md` → "Long-running phases / slow test suites".

## Provider stream transport policy (spec 70)

- `SLO_PROVIDER_STREAM_FIRST_PROGRESS_TIMEOUT_SECONDS` default `300`.
- `SLO_PROVIDER_STREAM_IDLE_TIMEOUT_SECONDS` default `300`.
- `SLO_PROVIDER_STREAM_RECONNECT_DELAY_SECONDS` default `1.0`.
- Decisions: `RETRY_FRESH_CONNECTION` (pre-commit) / `DO_NOT_REPLAY` (after committed output).
- Pre-commit known transport failure → `STREAM_DISCONNECTED`; ModelPool may switch only before first chunk; audit text `provider_stream_disconnected`.
- `stream_reconnecting` history event: diagnostic only, excluded from replay.

## Workflow budgets (prompt rules, not runtime counters)

- 60 workflow turns started per task (partial turns count).
- 20 dispatch calls per workflow turn (retries included) → at most 1,200 calls per task.
- Failed tasks: 3 retries after the initial attempt. Aborted tasks: never retried.
- New revision turn resets only its dispatch count (not task-wide turns or failed-task retries).
- Resume and takeover preserve counts.
- Explicit user instructions override turn/dispatch budgets (higher, lower, unlimited); record effective limits, keep consumed counts.
- Runtime child concurrency: `SLO_SUBAGENT_MAX_CONCURRENCY` default `6` (separate limit). [src: config/cfg.py]
- Advance on verified phase verdicts/artifacts, not process exit.
- Source of counting rules: `skills/orchestration/workflows/SKILL.md#workflow-turns-and-limits`.

## Workflow / skill routing decision rules

- "workflow" or named workflow → load from `skills/orchestration/workflows/`.
  - Code-Test-Review → `skills/orchestration/workflows/code-test-review.md`.
  - Specification Development → `skills/orchestration/workflows/specification-development.md`.
- Never substitute `skills/coding/code-test-loop/SKILL.md` (Step 1 only; skips Step 2 Code Review, Step 3 Completion Check).
- "dynamic workflows" / "dyanmic workflows" → in-session, `spawn_sub_agents`, blocking.
- Detach qualifiers "headless" / "detached" / "independent", or "in the background" / "without blocking" → exactly one `launch_workflow`; a detached orchestrator never calls `launch_workflow`.
- Monitoring a TUI-launched workflow → `skills/tui/tui-scheduled-workflows/SKILL.md`.
- Generic TUI schedules (interval / cron / one-shot) → `skills/tui/tui-scheduled-operations/SKILL.md`.
- HTML explanation → `skills/design-and-analysis/explain-with-html/SKILL.md`; prerequisites `solution-design`, `coding-rules`, `code-design-principles`; render with `present-as-single-page`; no implementation or sub-agent dispatch authority.
- Non-trivial tasks route via `skills/engineering/engineering-routing/SKILL.md`: shared policy → language root → component/test recipe → framework → project contracts.
- Skill loader merge order: bundled → user skills → user workflows, by name (user wins).
- `SLO_CODE_PROMPTS_DIR`: no longer used.
- Skills: 14 groups (`orientation`, `design-and-analysis`, `coding`, `git-ops`, `cli`, `tui`, `integration-tests`, `frontend-vue`, `presentation`, `user-content`, `engineering`, `languages`, `samples`, `orchestration`); AGENTS.md counted 188 skills (layout tree said 186).
- INDEX entry fields: `name`, `description`, `when_to_use`, `Path:`; frontmatter adds `group`, `kind`.

## System prompt assembly

- Section order: 1 role line (`ROLE_LINE`) → 2 tools block (`TOOL_PROMPT_SNIPPETS`) → 3 custom tools note → 4 guidelines → 5 skills block → 6 KB block (`KB_BLOCK_TEMPLATE`) → 7 `append_system_prompt` → 8 project context (`<project_instructions path=…>`) → 9 date → 10 cwd → 11 optional `Current workspace folders:`.
- Skills fallback recovery order: `$SLO_SKILLS_DIR` → `$SLO_HOME/skills` → `pipx runpip slo show slo` → `<Location>/skills`.
- Project context filenames: `SLO.md`, `AGENTS.md`, `CLAUDE.md`, `docs/RESEARCH.md` [src: project_context/service.py]; deepest copy per filename wins within the cwd walk; workspace-folder walks add unique paths after.
- B1 (tools block rendered `(none)`): resolved in source — `SloAgent.__init__` passes `list(_build_result.tools)`.

## Knowledge base resolution

- Precedence: `SLO_KB_DIR` → `KB_DIR` → `$SLO_HOME/KnowledgeBase/KB`; file value resolves to its directory; never created.
- Entry points: `Welcome.md`, `index.md`, `Index.md`, `Home.md`.
- `~/.slo/shell/environment.sh` sets `SLO_KB_DIR` only when unset (from `KB_DIR`, else `$SLO_HOME/KnowledgeBase/KB`).

## Credentials and OAuth

- Resolver precedence: 1 env (`SLO_ANTHROPIC_API_KEY`, `SLO_OPENAI_API_KEY`, `SLO_KIMI_FOR_CODING_API_KEY`) → 2 `~/.slo/global/authentication.json` → 3 `~/.claude/.credentials.json` (Anthropic only).
- `SLO_OAUTH_TIMEOUT_SECONDS` (callback) default `60`. [src: config/cfg.py]
- `SLO_OAUTH_MANUAL_TIMEOUT_SECONDS` (browser/manual attempt) default `900`. [src]
- `SLO_OAUTH_DEVICE_TIMEOUT_SECONDS` (device attempt) default `900`. [src]
- `OAuthLoginMethod`: `BROWSER_AUTHORIZATION`, `DEVICE_AUTHORIZATION`.
- `BrowserHost`: no `webbrowser` call unless macOS/Windows or one of `DISPLAY`, `WAYLAND_DISPLAY`, `BROWSER` is set.

## Kimi For Coding

- Enum `ProviderName.KIMI_FOR_CODING`; env `SLO_KIMI_FOR_CODING_API_KEY`.
- Models: `kimi-for-coding`, `kimi-k3`, `kimi-for-coding-highspeed`; `moonshot-*` aliases still resolve (not advertised).
- Builder `LLMFactory._build_kimi_for_coding_chat_openai`: `base_url="https://api.kimi.com/coding/v1"`, `max_retries=0`, `supports_explicit_caching=False`.
- K3 reasoning: levels `low`, `high`, `xhigh`; `off`/`minimal` → `low`; `medium` → `high`; `xhigh` → provider effort `max`. Only enabled K3 reasoning adds top-level `reasoning_effort`.
- `kimi-for-coding`, `kimi-for-coding-highspeed`: off-only.
- Never emitted: `thinking`, OpenAI `reasoning`, `use_responses_api`, `output_version`.

## ModelPool and provider error classification

- `ModelPoolEntryDAO.cooldown_seconds` default `300` (credit); `rate_limit_cooldown_seconds` default `60` (rate-limit + transient).
- `ModelPoolDAO.entries` `min_length=2`.
- Selection: lowest priority value not cooling.
- Switchable kinds: `CREDIT_EXHAUSTED`, `RATE_LIMITED`, `TRANSIENT_PROVIDER_FAILURE`; `OTHER` re-raises; `_astream` switches only before first chunk.
- All cooling → `AllModelsExhaustedError`.
- Pool config sources: `SLO_MODEL_POOL` or `UserPreferencesDAO.default_model_pool`; parser `config/model_pool_config.py::parse_model_pool_config`; threaded via `SessionConfigDAO.model_pool_dao`.
- `create_pool` forwards: `temperature`, `streaming`, `max_retries`, `max_tokens`, `model_kwargs`, `session_id`, `reasoning_level`; adapter `adapt_chatgpt_backend_request`.
- Status/code → kind:

| Provider | CREDIT_EXHAUSTED | RATE_LIMITED | TRANSIENT_PROVIDER_FAILURE |
|---|---|---|---|
| Anthropic | 402, or "credit balance"/"billing" | 429 | 529 |
| Kimi For Coding | 402 | 429 | 500, 502, 503, 529 |
| OpenAI | code `insufficient_quota`, `billing_hard_limit_reached` | 429 | 500, 502, 503; status-less "our servers are currently overloaded" |

- Text fallback (no status): `"rate limit"` / `"429"` in message → `RATE_LIMITED`.
- `CreditExhaustionPolicy` = backward-compatible alias of `ProviderErrorClassifier`.

## Rate limiting and retry

- `ModelRateLimitPolicyDAO` fields: `requests_per_minute`, `tokens_per_minute`, `automatic_retry_attempts`, `local_retry_wait_cap_seconds`; source `MODEL_DEFAULTS` in `config/ai_model_config.py` (from the model catalog).
- `retry_plan_from_error()` → `RateLimitRetryPlanDAO(wait_seconds, retryable)`.
- Preflight: RPM may wait; TPM advisory; empty-window oversized request emits `preflight_bypassed` and still sends; degraded preflight records no local attempt; estimate reused, never re-estimated.
- Iteration retry only when the iteration emitted no visible output; retryable kinds `RATE_LIMITED`, `TRANSIENT_PROVIDER_FAILURE`; `AllModelsExhaustedError` retryable within budget; no injected policy → no retry.
- Overflow backstop (spec 46.a.2) plan: `overflow_retry`, `persist_user_message=False`, `excluded_turn_ids=[failed turn]`, `preflight_compaction_mode="skip"`; one shot.
- Compaction event kinds: `compaction_started`, `compaction_completed`, `compaction_failed`, `compaction_retrying`.
- Terminal (no recovery): committed output, second overflow on retry, HTTP 413 / `REQUEST_BODY_TOO_LARGE`.

## Session history on-disk layout

- Root: `~/.slo/sessions/history/<session_id>/`.
- `session.json` (atomic temp+rename; `session_name`, `session_name_key`), `tree.json` (default), `transcript.md` (derived), `orchestrator.json`, `fleet.json`, `abort_request.json`.
- `child-control.v1/capability.json`; `child-control.v1/<run_id>/{requests,receipts}/<request_id>.json`.
- `children/<child_session_id>/status.json`; `children/<child_session_id>/execution.v1.json`.
- `execution-index.v1.json` (beside `fleet.json`).
- Workflow handles: `<owner_session>/workflows/wf-*.json`.
- Legacy flat store: `events.jsonl` instead of `tree.json`.
- Closed released shapes: `status.json`, `fleet.json`, `spawn_context.json`; execution identity only in `*.v1.json`.
- Token estimate: `ceil(chars / 4)`; lifecycle events 0.
- `--resume` resolution order: exact `session_id` → normalized `session_name_key`.
- Per-prompt persistence steps: ensure dir → load history → persist `run_started` + `user_message` → forward trace → terminal event.
- Workflow handle transitions: `stalled`/`failed` → (`/workflows resume`, flock-protected) `launching` → (fresh self-report) `running`.

## Child abort and session list (feature 94)

- `ChildAbortStore` capacity: 256 requests per run, under run-scoped `admission.lock`.
- `TaskPreview`: 150 code points including `…`.
- `WorkflowProgressCoordinator` timer: 5.0 s, single flight; progress modal refresh every 5 s.
- `ChildAbortSubmission` not-confirmed notice after 30 s.
- `PromptInput` min/max height 3/17.
- `ChildAbortController` only for attached pool with explicit `--notify-session`; closed before final fleet drain.
- Requests/receipts never deleted, backfilled or migrated.

## TUI constants

- `ThinkingSpinner` glyph frame interval 0.08 s; verb rotation `interval_seconds` default 1.5 s.
- Compact token format examples: `6.0k`, `12k`, `1.0M` (tokens only).
- Copy chords: `ctrl+shift+c` / `meta+c` (visible); `ctrl+shift+m` / `meta+shift+m` (raw Markdown).
- Visualizer panes: `ctrl+←/→` list width, `ctrl+↑/↓` diagnostics height.
- `SLO_AUTO_VISUALIZE=0` disables auto-launch; `SLO_VISUALIZER_TERMINAL_APP` selects emulator.
- Theme tokens: `user-msg-bg`, `tool-pending-bg`, `tool-success-bg`, `tool-error-bg`, `thinking-text`, `md-heading`, `border-muted`.

## Plugins

- Load order: `~/.slo/plugins/plugins/<plugin-id>/` → `.slo/plugins/` (trusted) → `--plugin` paths.
- Import namespace: `slo_plugin_<namespace>`.
- `SLO_PLUGINS_DISABLED=1` disables all tiers.
- Dog-food: `--plugin plugins/bash_live_output/plugin.py`.
- Streaming event kind: `tool_output_update`.

## Specification artifacts

- Feature requests: `feature-requests/`.
- Spec root: `readlink specifications`.
- Primary doc `overview.md`; sub-specs `<spec-number>.<letter>.<index>-<title>.md`; never `request.md`.

## Commit / branch conventions

- Branch: `feature-<detail_in_snake_case>` or lowercase JIRA ID, from `main`.
- Title: `<JIRA-ID or topic> <one-line description>` ≤ 72 chars; body lists core changes and files; `Co-Authored-By:` footer with AI pairing.

## Install and update

- Install mechanism: isolated pipx app built from Git: `pipx install --force --python <python3.11> "git+https://gitlab.com/core-27/slo.git@<ref>#subdirectory=slo"`. Package lives in the repo's `slo/` subdirectory (repo root has no `pyproject.toml`), hence `#subdirectory=slo`.
- Code vs data: pipx owns code (venv + `slo` on `PATH`); `~/.slo` (`SLO_HOME`) is runtime data only (sessions, logs, `global/authentication.json`). Install/upgrade/uninstall never touch sessions, credentials, user skills, user workflows or a legacy `~/.slo/skills` tree; no checkout or skills copy is created in `~/.slo`.
- Installer-owned files: `$HOME/.slo/shell/environment.sh` (mode `0644`, non-secret, markers `# >>> slo managed environment >>>` / `# <<< slo managed environment <<<`) plus one bounded source block in each of `.bash_profile`, `.bashrc`, `.zshenv`, `.profile`.
- `install.sh` steps (idempotent; each step no-op when satisfied):
  1. Toolchain. macOS: Homebrew → pipx → pyenv → Python 3.11.x → git. Debian/Ubuntu: apt (git + pyenv build deps) → pyenv (git clone) → Python 3.11.x → pipx (apt; `pip --user` fallback on older distros).
  2. Resolve `SLO_HOME` (default `~/.slo`), ensure it exists (data dir, not a checkout).
  3. `pipx install --force --python <absolute interpreter> "git+…@<ref>#subdirectory=slo"`.
  4. Only after pipx success: finalize shell environment, then finalize the isolated launcher.
- Shell-environment finalization:
  1. Skills dir from metadata only: `pipx runpip slo show slo` → `Location:` → `<Location>/skills`; must contain readable `INDEX.md`. Any failure aborts non-zero before any file changes; no guessing of Python version, pipx root or checkout path.
  2. Atomically write `environment.sh` with defaults only: `SLO_HOME`=`$HOME/.slo`; `SLO_SKILLS_DIR`=validated vendored skills path; `SLO_KB_DIR`=`$KB_DIR`, else `$SLO_HOME/KnowledgeBase/KB` (variable only; dir never created). Pre-exported values always win.
  3. Startup-file source block only sources the managed file behind a readable guard; never contains the resolved path. Unrecognised files, symlinks, malformed/duplicate markers: refused, never overwritten.
- Coverage boundary: sterile processes (`env -i sh -c …`, `bash --noprofile --norc -c …`, cron, services, GUI launchers) do not get defaults; they use `config/cfg.py` fallback: skills = explicit env → populated legacy `$SLO_HOME/skills` → package-adjacent tree; KB = `SLO_KB_DIR` → `KB_DIR` → `$SLO_HOME/KnowledgeBase/KB`; or set `SLO_HOME`/`SLO_SKILLS_DIR` explicitly.
- Launcher finalization: wrapper retains `<venv>/bin/python` even if symlinked outside the venv, but only after executing it proves `sys.prefix` == validated venv root. Refuses outer venv-root symlinks, malformed/cyclic interpreter chains, altered launchers, unsafe artifacts.
- Launcher semantics: generated POSIX wrapper runs venv python with `-I` against `slo-entry` trampoline; `PYTHONPATH`/`PYTHONHOME` cannot select modules before Slo imports. Import isolation only: `os.environ` (incl. `SLO_*`, credentials) remains. Slo never reads/changes a project's `.envrc`.
- Internal children (sub-agent, detached workflow, workflow resume): `sys.executable -I -m src.cli` with sanitized child environment; Slo must be installed in that interpreter (dev: editable install; cwd/`PYTHONPATH` insufficient). `-I` does not propagate to project interpreters launched by tools. Scheduler uses the installed wrapper. Visualizer trusted source fallback is checkout-only, no `PYTHONPATH` forwarding.
- Installer env vars:
  - `SLO_REPO_URL` = `https://gitlab.com/core-27/slo.git` (primary).
  - `SLO_REPO_FALLBACK_URL` = `https://github.com/slostack/slo.git` only for the official primary; `''` disables; custom primaries get no default mirror.
  - `SLO_REF` = `main` (branch/tag/commit; source-of-truth selector).
  - `SLO_VERSION` unset; `dev` → `main`; any other value overrides `SLO_REF`. Unset: hosted/published `SLO_REF`.
  - `SLO_REPO_SUBDIR` = `slo` (empty for root-level project).
  - `SLO_PYTHON_VERSION` = `3.11.7`.
  - `SLO_OS_RELEASE_FILE` = `/etc/os-release` (test-only).
  - `bash install.sh --development` ≡ `SLO_REF=main`.
- Mirror fallback decision: pipx fails → bounded `git ls-remote` probe; primary inaccessible → retry ONCE from mirror with same ref, interpreter, subdir. Primary reachable → build/dependency/missing-ref failures returned, no retry. Both fail → install fails, no launcher/shell finalization. Identical primary/fallback never retried. Missing ref on mirror = error (no other version). Fallback covers code fetch only, not installer download or toolchain/dependency services.
- Git limits: probe deadline 30 s; HTTP fetch aborts after 30 s below 1 byte/s (respects existing `GIT_HTTP_LOW_SPEED_LIMIT`/`GIT_HTTP_LOW_SPEED_TIME`); terminal prompting disabled.
- Credentials: no API tokens read/embedded/persisted; existing Git credential helpers work; legacy deploy-token vars and `GITHUB_SLOSTACK_TOKEN` not used. Anonymous fallback requires public `slostack/slo`; private mirror needs pre-existing Git read auth; GitLab mirror deploy key authorizes pushes only.
- Mirror E2E smoke: `SLO_MIRROR_INSTALL_E2E=1 poetry run pytest -o addopts='' tests/cli/test_install_mirror_e2e.py -m e2e -v` (network; Python 3.11 + pipx preinstalled; disposable HOME/pipx roots).
- Local run: `bash install.sh`; pin with `SLO_REF=v0.3.2`.
- Hosted install: Cloudflare Worker on `get-slo.sh` serves script at `/` and `/install.sh`: `curl -fsSL https://get-slo.sh/install.sh | bash` (pinned: `… | SLO_REF=v0.3.2 bash`). Hosted default ref baked at deploy via `PUBLISH_SLO_REF=v0.3.2`; user `SLO_REF` still overrides; bump stable channel by redeploying with newer tag.
- `deploy-install-worker.sh` (operator, curl to Cloudflare API, no wrangler/Node): 1) verify token reaches account Workers; 2) fetch public `install.sh` from GitLab `core-27/slo@<SLO_SOURCE_REF>` (default `main`) or local file via `INSTALL_SH`; 3) optional `PUBLISH_SLO_REF`; 4) base64-embed in Worker, upload; 5) bind hostname (auto proxied DNS) or enable `*.workers.dev`. Credential `CF_API_TOKEN` only. Permissions: Account → Workers Scripts: Edit; custom domain also Zone → Zone: Read, DNS: Edit, Workers Routes: Edit (target zone).
- `slo update` (pipx reinstall, same mechanism/auth, GitLab first + same fallback; honors `SLO_REPO_URL`/`SLO_REPO_FALLBACK_URL`):
  - `slo update` → latest release tag `vX.Y.Z` via `git ls-remote --tags --refs`; on primary failure/timeout retries tag lookup on mirror; highest numeric tag; reachable primary with no tags = error.
  - `slo update --development` → `main`; `slo update --ref <ref>` → explicit ref; both keep ref when switching sources.
  - After success, always runs `<Location>/install.sh --finalize-launcher`; then if any of `SLO_HOME`, `SLO_SKILLS_DIR`, `SLO_KB_DIR` (or `KB_DIR`) is missing runs `<Location>/install.sh --finalize-environment`; else shell files untouched. Existing vars never changed; warns if existing `SLO_SKILLS_DIR` lacks `INDEX.md` or differs from installed skills.
  - Manual refresh: `bash <Location>/install.sh --finalize-environment` (`Location` from `pipx runpip slo show slo`). Re-running hosted installer also upgrades.
- Direct `pipx install|upgrade|reinstall` regenerates plain scripts, skips launcher finalization; unsupported as repair → re-run matching tagged public installer. Downgrade to pre-82.a restores plain launcher (no `slo-entry`).
- Uninstall: `pipx uninstall slo`; `~/.slo` data survives; managed env file/source blocks are inert and removable by hand.
- Troubleshooting:
  - `Could not parse uv version … (rc=127)` → broken `uv` pyenv shim; auto-fallback `PIPX_DEFAULT_BACKEND=pip` (or set it).
  - `pyenv: python3.11: command not found` → installer passes absolute `$(pyenv root)/versions/<ver>/bin/python3.11`.
  - `ERROR: The Python ssl extension was not compiled` (Linux) → `slo_ensure_build_deps` apt-installs `libssl-dev` et al. on Debian/Ubuntu; other distros install pyenv build deps manually.
  - `neither setup.py nor pyproject.toml found` → `#subdirectory=slo` / `SLO_REPO_SUBDIR`.
  - Cloudflare `10000 Authentication error` on `/accounts/<id>/workers/...` → add Account → Workers Scripts: Edit + account scope.
  - Wrong build runs → `~/.pyenv/shims/slo` shadows `~/.local/bin/slo`; run `~/.local/bin/slo` or `<venv>/bin/pip uninstall slo && pyenv rehash`.

Source: KB slo/install-guide.md

## Headless runs

- Command: `slo run [OPTIONS]`. Stdout is always JSONL, one validated `AgentStreamEventDAO` per line (`src/agents/slo_agent/events/stream.py`).
- Flags:
  - `--prompt/-p` required (only way to pass a prompt).
  - `--json` compatibility no-op.
  - `--model` default `None`; fallback: `UserPreferencesStore` (`~/.slo/global/preferences.json`) → `cfg("DEFAULT_MODEL_NAME")`. Unknown model fails at session build.
  - `--reasoning` `off|minimal|low|medium|high|xhigh`; clamped to model range with warning.
  - `--cwd` default `$PWD`; relative resolved to absolute; root for all filesystem tools.
  - `--enable-history` default off; required for later `--resume`.
  - `--resume <id|unique name>` implies `--enable-history`; resolved via `FilesystemSessionHistoryStore.resolve_session_reference()` (exact UUID, then unique name); ambiguous name → error; missing session → error.
  - `--session-id` UUID4 or `[A-Za-z0-9._-]+`; beats `SLO_SESSION_ID`; invalid → error (no silent fallback).
  - `--workspace <file.code-workspace>`: each folder's `SLO.md`/`AGENTS.md`/`CLAUDE.md` added to system prompt.
  - `--system-prompt-file` replaces default prompt; `--append-system-prompt-file` appends after it; both may be passed: replace first, then append.
  - `--system-prompt-b64` base64 prompt; decodes and replaces session system prompt (subprocess-safe).
  - `--orchestrator/--no-orchestrator` default off; attaches `SubAgentPool` (adds `spawn_sub_agents`), injects `DEFAULT_ORCHESTRATOR_SYSTEM_PROMPT` when no `--system-prompt-file`.
  - `--notify-session <id>`: durable inbox receiving `workflow_started`, per-phase updates, terminal synthesis (set by `launch_workflow`); absent → no notifier/inbox writes.
- Session id precedence: `--resume` → `--session-id` → `SLO_SESSION_ID` → fresh `uuid4()` in `SloAgentSession.build()`.
- Model selection precedence (incl. OpenRouter): explicit `--model` → configured pool → resumed route → saved default → cfg default. Explicit model clears configured pool. `--resume` reuses persisted routed-model metadata unless `--model` given.
- OpenRouter: `--model 'openrouter:<exact-remote-id>'`; `openrouter:` names credential/transport provider regardless of vendor segment; strict preparation gateway; route absent from authenticated catalog → safe failure, never default substitution. Credential: `SLO_OPENROUTER_API_KEY` then stored credential; never in args. Detached trusted children receive exactly that env var as the one secret exception. Public stdout/stderr must not carry OpenRouter reasoning/continuation metadata or raw provider errors.
- Reasoning: `kimi-k3` always on: supports `low|high|xhigh` → provider effort `low|high|max`; `off`/`minimal` → `low`; `medium` → `high`. `kimi-for-coding`, `kimi-for-coding-highspeed` off-only (no reasoning field).
- Exit codes: `run_completed` → 0; `run_failed` (or any other terminal) → 1; `run_aborted` (SIGINT, SIGTERM/`timeout`, orchestrator cancel) → 2. Last stdout line is always the terminal event.
- Stdout event fields: `kind`, `iteration` (from 0), `block_id`, `content_index`, `delta`, `content`, `tool_name`, `tool_call_id`, `tool_input`, `tool_arguments_delta`, `redacted`, `metadata` (`metadata.wait_seconds` on `run_retrying`).
- Event kinds: `thinking_start|delta|end`; `text_start|delta|end`; `tool_call_start|delta|end`, `tool_result`; terminal `run_completed|run_aborted|run_failed`; `run_retrying`, `steering_applied`, `compaction_started|completed|failed|retrying`, `compaction_advised` (256k advisory threshold, display-only), `recovery_started|succeeded|exhausted`; `sub_agent_spawned|completed|failed|aborted` (fields `sub_agent_id`, `task_id`, `content` top-level).
- Stderr: `HeadlessLifecycleEventDAO` JSONL fields `kind`, `session_id`, `message`, `payload`, `timestamp_utc`; kinds `headless_session_started`, `headless_session_resolved`, `headless_orchestrator_attached`, `headless_run_completed`, `headless_run_failed`, `headless_run_aborted`, `headless_child_stderr`.
- Heartbeat: `HeadlessRunner` watchdog thread writes stderr `headless_status` every `SLO_HEADLESS_HEARTBEAT_SECONDS` (15); payload only `phase`, `last_event_age_seconds`, `attempt`; states `healthy|degraded|silent` advisory; never cancels a child.
- History layout (default `TreeBasedFileSystemSessionHistoryStore`): `$SLO_HOME/sessions/history/<session_id>/{session.json, tree.json, transcript.md}`; legacy `FilesystemSessionHistoryStore` uses `events.jsonl` instead of `tree.json` only when explicitly selected. `--enable-history` needed on every invocation to persist.
- Stream recovery: disconnect before committed output → one fresh-connection reconnect (new request). After committed text/thinking/tool call → no replay/mid-stream switch; session starts continuation turns up to `SLO_PROVIDER_STREAM_CONTINUATION_MAX_ATTEMPTS` (5) total, instructing agent to inspect worktree first. Terminal failure envelope: `failure_code`, `partial_output_committed`, `attempts`, `safe_message`.
- Bash tool: default timeout `SLO_BASH_DEFAULT_TIMEOUT_SECONDS` = 1800 (`_DEFAULT_BASH_TIMEOUT_SECONDS`, `src/agents/tools/bash.py`); `0` disables; exceeded → SIGKILL + error. Reap grace `SLO_BASH_TEARDOWN_GRACE_SECONDS` = 5. Model may pass per-call `timeout`.
- Wall clock: `timeout 300 slo run …` → SIGTERM → `run_aborted`, exit 2; `timeout -k 15 300 …` adds SIGKILL after 15 s.
- SDK retries: `LLMFactory.create` `max_retries=3`; Kimi For Coding `max_retries=0`; not env-configurable (edit `src/agents/base.py`).
- Other env defaults: `SLO_HOME`=`~/.slo`; `SLO_OAUTH_TIMEOUT_SECONDS`=60 (loopback callback); `SLO_OAUTH_MANUAL_TIMEOUT_SECONDS`=900 (whole browser attempt incl. paste); `SLO_OAUTH_DEVICE_TIMEOUT_SECONDS`=900; `SLO_PROVIDER_STREAM_FIRST_PROGRESS_TIMEOUT_SECONDS`=300; `SLO_PROVIDER_STREAM_IDLE_TIMEOUT_SECONDS`=300; `SLO_PROVIDER_STREAM_RECONNECT_DELAY_SECONDS`=1.0 (jittered base); `DEFAULT_MODEL_NAME`; `ANTHROPIC_API_KEY`; `KIMI_FOR_CODING_API_KEY`; `SLO_MODEL_CATALOG_OVERRIDES_FILE`.
- How-to recipes: final answer `| jq -r 'select(.kind == "run_completed") | .content'`; live deltas `| jq -j 'select(.kind == "text_delta") | .delta'`; tool counts `| jq -r 'select(.kind == "tool_call_end") | .tool_name' | sort | uniq -c | sort -rn`; multi-step shared context: same `SLO_SESSION_ID` + `--enable-history` per step.
- Troubleshooting: no output → empty prompt / missing `~/.slo/global/authentication.json`; first event `run_failed` → read stderr, check model in `config/ai_model_config.py`; history not shared → `--enable-history` each call + same `SLO_SESSION_ID`; pool not switching → `echo "$SLO_MODEL_POOL" | jq .`, distinct priorities (ties resolve in list order), look for `run_retrying`.

Source: KB slo/headless-guide.md

## Model pool

- `SLO_MODEL_POOL` JSON array (or user preference `default_model_pool` in `~/.slo/global/preferences.json`). Entry fields: `model_name` (required, catalog-known), `provider` (required: `anthropic|openai|kimi_for_coding`), `priority` (default 0; lower first), `cooldown_seconds` (default 300; credit exhaustion / non-rate-limit switchable), `rate_limit_cooldown_seconds` (default 60; 429, 500, 502, 503, 529).
- Behavior: highest-priority non-cooled entry → on switchable error (credit, rate limit, 5xx) cool it → retry same request on next entry → all cooled: wait for shortest cooldown and retry → `run_retrying` with `metadata.wait_seconds` per retry.

Source: KB slo/headless-guide.md

## Workflow orchestration

- Orchestrator mode = `SloAgentSession` + `SubAgentPool` (`spawn_sub_agents`); each child is a separate `slo run` process.
- Pool limits: `SLO_SUBAGENT_MAX_CONCURRENCY` = 6 (`config/cfg.py`); `SLO_SUBAGENT_MAX_TASKS` = 8 per `spawn_sub_agents` call.
- Inactivity guards: `SLO_STREAM_INACTIVITY_TIMEOUT_SECONDS` = 10800 (orchestrator's own LLM stream; do not lower); `SLO_SUBAGENT_INACTIVITY_TIMEOUT_SECONDS` = 7200 (alias `SLO_SUBAGENT_INACTIVITY_TIMEOUT`; child stdout inactivity; sole child-cancellation authority; heartbeats never shorten it). Cancellation: SIGTERM → grace → SIGKILL → reap.
- Child captures: `$SLO_HOME/sessions/history/<parent>/children/<child>/stdout.jsonl` and `stderr.jsonl` (diagnostic); pool children always get pool-assigned `--session-id` + `--enable-history`, so canonical `tree.json` exists.
- Child `cwd` set per task by orchestrator. Child system prompt passed as `--system-prompt-b64` (`SubAgentTaskDAO.system_prompt`).
- Detached workflow files under `$SLO_HOME/sessions/history/`: `<owner>/workflows/wf-xxxx.json` (TUI handle), `<orch>/orchestrator.json` (HeadlessRunner heartbeat), `<orch>/fleet.json` (SubAgentPool), `<orch>/abort_request.json` (TUI abort), `<orch>/children/<child>/status.json` (terminal result).
- Resume: TUI `/workflows resume <workflow-id>` for `stalled`/`failed` → relaunch with original orchestrator history; handle → `launching` (new pid) → `running` after first fresh heartbeat.
- Default orchestrator prompt rules: spawn only on explicit parallel request; "dynamic workflows"/"dyanmic workflows" without detach qualifier = in-session `spawn_sub_agents`; "headless"/"detached"/"independent" or "in the background"/"without blocking" → `launch_workflow`; detached orchestrator never calls `launch_workflow`. Sub-task prompts self-contained; chain mode `{previous}` placeholder; retry failed/aborted sub-agent once with corrected params; synthesize `answer` fields, no raw JSON; named workflows read from `skills/orchestration/workflows/<name>.md`.
- How-to (shell): `SLO_STREAM_INACTIVITY_TIMEOUT_SECONDS=10800 SLO_SUBAGENT_INACTIVITY_TIMEOUT_SECONDS=7200 SLO_SUBAGENT_MAX_CONCURRENCY=6 python -m src.cli run -p "$(cat prompt.txt)" --orchestrator --enable-history --session-id <id> --cwd <proj> --json > wf.jsonl 2> wf.err &`; watch `slo visualize --session <id> --follow`; then `jq -r 'select(.kind == "run_completed") | .content' wf.jsonl`.
- `slo visualize`: `--session/-s` required (id or unique name of parent); `--follow/--no-follow` default follow (stops at parent terminal state); `--refresh-seconds` 1.0 (`SLO_VISUALIZER_REFRESH_SECONDS`); `--tree-format textual|markdown|html`. Keys: ↑/↓ navigate, Enter select, `r` refresh, `f` toggle follow, `d` toggle Diagnostics (stderr) pane, `q` quit. Status icons ⏳ running, ✓ completed, ✗ failed, ⊘ aborted, ◌ pending. Child discovery = `sub_agent_spawned` events ∪ scan of `children/`, deduplicated. Read-only.
- Troubleshooting: "No sub-agents found" → parent lacked `--enable-history`, wrong id, or no spawn yet (`r`). Hung orchestrator → stuck child queues others when concurrency low; inspect child `stderr.jsonl`.

Source: KB slo/headless-guide.md

## Scheduler

- Not a daemon: OS scheduler invokes `slo schedule execute --name <schedule-id>`; macOS `launchd`, Linux `cron`.
- On-disk: `$SLO_HOME/schedules/<schedule_id>/schedule.md` (definition: name, trigger, prompt, cwd, model, session_mode, continuous policy); `state.json` (last run time/status/session id/delivery path/delivery state, run count); `runs/<run_id>.json` (immutable per-fire record); OS logs `$SLO_HOME/schedules/logs/` (outer invocation only).
- Delivery paths: `fresh_headless`, `resume_headless`, `session_inbox`, `none`. States: `executed`, `queued`, `coalesced`, `skipped_disabled`, `skipped_overlapping` (no `skipped_exception`).
- Decision rule: fresh → new headless run. Continuous → resolve target (explicit reference → `last_session_id` → seed `schedule-<schedule_id>`); target leased by live TUI → `session_inbox` enqueue (never a second writer); exists but not leased → `resume_headless` (`--resume`); first schedule-owned fire → `fresh_headless` with `--enable-history --session-id <seeded>`; unknown slug reference may be seeded as that exact id.
- Coalescing: `none` (default) | `latest_by_key`: newer fire replaces pending inbox item with same `coalescing_key` → `delivery_state=coalesced`, `coalesced_fire_count`. Applies only to inbox path.
- Overlap: one filesystem lock per schedule fire (`fire_lock.py`) → `skipped_overlapping`.
- Headless argv: `slo run --prompt "<prompt>" --json [--cwd …] [--model …] [--resume <ref>] [--enable-history --session-id <id>]`; never `--orchestrator`.
- Model: persisted `--model` forwarded to `slo run --model`; same precedence as headless; explicit scheduled model clears pool; OpenRouter `openrouter:<id>` works; credentials never in definitions/args.
- `slo schedule add` options: `--name` (req), `--prompt` (req), exactly one of `--cron` (5-field) | `--interval-seconds` | `--run-at` (ISO8601), `--tz` (default `UTC`), `--cwd`, `--model`, `--session-mode fresh|continuous` (default `fresh`), `--session-reference`, `--coalescing-mode none|latest_by_key` (default `none`), `--coalescing-key`. Validation: `fresh` forbids `--session-reference`, non-default coalescing mode, `--coalescing-key`; `--coalescing-key` requires `latest_by_key`.
- Other commands: `edit` (`--name` existing id/normalized name + `--schedule-name` new name; same options; preserves id); `list` (Name | Mode | Trigger | Target Session | Installed | Last Delivery); `show --name`; `execute --name` (canonical; `run` alias); `install`/`uninstall --name`; `reports --name` (`<run_id> | <delivery_path> | <delivery_state>`); `show-report --name --run-id` (delivery_path, delivery_state, session_id, target_session_id, coalesced_fire_count); `cleanup --name [--keep 100]` keeps newest N by recorded `started_at` (not UUID order).
- Run record fields: `run_id`, `started_at`, `finished_at`, `status`, `delivery_path`, `delivery_state`, `session_id`, `target_session_id`, `exit_code`, `summary`, `stdout_summary`, `stderr_summary`, `skipped_reason`, `coalesced_fire_count`.
- launchd: plist `~/Library/LaunchAgents/com.slo.schedule.<name_key>.plist` runs `slo schedule execute --name <schedule_id>`; supports cron + interval; not one-shot/calendar.
- cron: user crontab marker block `# slo-schedule:<id>` / `<cron> <slo> schedule execute --name <id> >> <stdout-log> 2>> <stderr-log>` / `# /slo-schedule:<id>`; cron triggers only.
- CLI trigger creation: cron, interval, one-shot; `CalendarTriggerDAO` exists in storage/list but no CLI builder.
- TUI side: history-backed session acquires lease, renews on heartbeat, polls inbox only when idle, claims next pending message, renders note/notice, starts normal prompt turn for `chat_turn`, acknowledges message. Maildir-like inbox (`src/agents/slo_agent/history/inbox/`).
- How-tos: create `slo schedule add --name … --prompt … --cron "0 18 * * *"`; install `slo schedule install --name …`; test now `slo schedule execute --name …`; inspect `slo schedule reports` / `show-report`; prune `slo schedule cleanup --keep 25`; remove from OS `slo schedule uninstall --name …`. Validate inbox path: keep `slo --resume <ref>` open, run `execute`, expect `session_inbox` queued/coalesced record.
- Code owners: CLI `src/cli/schedule/app.py`; model/store `src/scheduling/dao.py`, `store.py`; runtime `src/scheduling/runtime/{executor,dao,reporting,cleanup,session_target_resolver,fire_lock,subprocess_runner}.py` (`ScheduleExecutor`, `ScheduleExecutionOutcomeDAO`, `ScheduleReportWriter`, `ScheduleSubprocessRunner`); OS `src/scheduling/os/{integration,launchd,cron,executable_locator,logs,status}.py`; inbox/lease `SessionInboxStore`, `SessionOwnershipLeaseStore`.

Source: KB slo/scheduler-guide.md
