# Changelog

## [Unreleased]

## [0.16.5] — 2026-09-14

**Subscription sign-in now shows its instructions: the OpenAI device code and
verification URL render, and every authorization URL is a clickable link.**

### Fixed

- **The authentication modal never showed any OAuth instructions.**
  `AuthenticationScreen` defaulted its factory to the `OAuthFlowFactory`
  *class*, not an instance. Calling it with keyword arguments raised
  `TypeError` inside a fire-and-forget `asyncio` task, so every browser
  and device attempt stayed on "Preparing sign-in instructions…" with
  no URL, no code and no error. The factory now exposes `__call__`
  (delegating to `for_provider`), the screen defaults to
  `OAuthFlowFactory()`, and the start task has a done-callback that
  paints a safe error and discards the response channel on failure.
- **OpenAI device authorization rejected the live payload.** OpenAI's
  `deviceauth/usercode` endpoint returns `interval` as text (`"5"`,
  confirmed against the live endpoint on 2026-09-14). The provider
  accepted only `int` and raised a protocol error before presenting the
  verification URL and user code. It now accepts an int or trimmed
  decimal text, and rejects bool, negative, float, non-decimal, null and
  missing values. Device endpoints are provider properties, so tests
  serve a live-shaped payload from a local HTTP server instead of
  monkeypatching.
- **Start failures are visible.** A failed device start paints its safe
  error inside the modal at 80×24 instead of disappearing.
- **Opening a browser can no longer freeze the TUI.** `webbrowser.open`
  ran synchronously on the event loop; on a Linux host without a
  graphical session it can start a console browser that takes over the
  terminal. The new `BrowserHost` skips opening on headless hosts
  (only `darwin`/`win32` or a set `DISPLAY`/`WAYLAND_DISPLAY`/`BROWSER`
  count as graphical). Elsewhere the open runs concurrently off the loop,
  so it never holds back a pasted authorization response.

### Added

- **Clickable authorization links.** A single `AuthorizationLink` widget
  (a thin subclass of Textual's `Link`) renders the browser authorization
  URL for every browser-capable provider (Anthropic, OpenAI) and the
  device verification URL. The painted text carries an OSC 8 hyperlink,
  so terminals can Cmd/Ctrl-click it even over SSH. Click or Enter calls
  `SloTUI.open_url` on a best-effort basis. The URL still wraps at 80
  columns, stays selectable and markup-safe, and is never logged. The
  loopback redirect URI stays plain text.
- **Painted-output regression tests.** The E2E tests drive the real
  screen → factory → flow → provider stack and assert what the compositor
  painted (text and link targets), not widget state. Against the pre-fix
  commit they fail. An opt-in `@pytest.mark.e2e` live smoke paints real
  OpenAI device instructions and cancels before approval.

## [0.16.4] — 2026-09-11

**Fixed a blank green tool block flashing into the transcript before a tool call streamed any arguments.**

### Fixed

- **Empty `tool_call_delta` events no longer mount a blank `ToolExecutionBlock`.**
  The assistant-chunk normalizer can emit a `tool_call_delta` that carries
  neither argument JSON nor parsed input — the provider's tool-call
  announcement chunk. `TranscriptProjector` called `_ensure_tool_block`
  unconditionally on every delta, so that announcement mounted a green
  tool-execution block with an empty headline moments before the real
  arguments arrived. The delta branch now mirrors the existing content
  guards on `thinking_delta` / `text_delta` / `tool_call_start`: a delta
  with no `tool_arguments_delta` and no `tool_input` is dropped, and the
  block first appears when real tool data arrives (a contentful delta or
  `tool_call_end`), fully formed. Non-streaming providers that send one
  shot of pre-parsed `tool_input` still mount immediately.

### Added

- **Plugin extensions with streaming tool output (spec 75).** Plugins can
  ship their own tools, widgets, and renderers; streaming-capable tools
  publish in-progress output snapshots to the live tool block.
- **Bundled plugins now ship inside the wheel** — a packaging fix so a
  `pipx install` carries the plugin tree instead of an empty directory.

### Removed

- **Mermaid chart cards (spec 77) reverted.** The fence-rendering feature
  landed on `main` and was backed out in the same window; `main` carries
  neither the feature nor a behaviour change from it.

### Fixed (release tooling)

- **`publish-installer` points at `slo/install.sh`** — the monorepo layout
  moved the installer into the `slo/` package directory and the publish
  job still fetched the old root path.

### Tests

- Regression test: an announcement-only `tool_call_delta` mounts nothing,
  writes nothing, and records nothing; the following `tool_call_end`
  mounts exactly one block with the full parsed input.
- Plugin renderer overrides no longer leak between tests.

## [0.16.3] — 2026-09-06

**Fixed a broken install: `slo` crashed on startup on every clean machine.**

### Fixed

- **`ModuleNotFoundError: No module named 'click'` on a fresh `pipx install`.**
  `src/cli/app.py` imported `click` directly while never declaring it as a
  dependency — it arrived transitively via `typer`. Typer 0.20 vendored Click as
  `typer._click` and dropped the `click` distribution, so a clean install got no
  `click` at all and every `slo` invocation died on import. The import is gone;
  the group context is now annotated `typer.Context`, which is the class Typer
  actually passes. Declaring `click` would have been wrong — it installs a
  *different* Click than the one Typer uses.
  Dev machines were unaffected because the dev-group `black` pulls `click` in.

### Changed

- **Declared five dependencies that were only reaching the wheel transitively** —
  `pyyaml`, `rich`, `anthropic`, `openai`, and `httpcore` are all imported
  directly by shipped code.
- **Narrowed `typer` to `>=0.26,<0.28`.** `pipx` resolves from `[project]
  dependencies`, never from `poetry.lock`, so the previous `>=0.12,<1.0` range
  shipped users a Typer the suite had never exercised — that gap is what let the
  vendored-Click change through.

### Verification

- Added `tests/cli/test_declared_dependencies.py`: an AST walk over `src/` and
  `config/` asserting every third-party import is declared, plus a guard that no
  shipped module imports `click`. It runs in the default suite — the existing
  installer smoke test carries the `e2e` marker that CI's `-m 'not e2e'`
  deselects, which is why this reached a release.
- Confirmed end to end with a clean `pipx install` in a `debian:12` container
  (Python 3.11, Typer 0.27.2, no `click` present): `slo --version`, `slo --help`,
  `slo schedule list`, and `slo run --help` all succeed, and importing every
  module under `src` reports nothing missing.

## [0.16.2] — 2026-09-04

**Expanded TUI transcript retention.**

### Changed

- Increased `TRANSCRIPT_WINDOW_SIZE` from 80 to 500, retaining up to 500 mounted
  transcript children before history-backed eviction begins.

### Verification

- Added a regression assertion that pins the production transcript window at 500.



## [0.16.1] — 2026-09-04

**Reliable provider-progress timing around local tool execution.**

### Added

- **`WatchDogTimer`** — a per-stream provider-progress watchdog that owns the
  first-progress/idle deadline state and tracks local tool calls through their
  completed results.

### Fixed

- **Slow local tools no longer look like stalled provider streams.** A tool-call
  stream can emit an empty assistant closure chunk before LangGraph returns the
  tool result. Previously that chunk could re-arm the provider idle timer while
  local work was still in flight, causing an erroneous provider timeout and
  recovery attempt. Provider timing now remains suspended until every observed
  `tool_result` balances its `tool_call_start`.

### Changed

- The default provider first-progress and idle deadlines are both now **300
  seconds** (previously 90 and 120 seconds), reducing false stall detection for
  valid slow-to-start or sparse streams. Operators can override either value
  with `SLO_PROVIDER_STREAM_FIRST_PROGRESS_TIMEOUT_SECONDS` and
  `SLO_PROVIDER_STREAM_IDLE_TIMEOUT_SECONDS`.
- The default `bash` tool timeout is now **1,800 seconds (30 minutes)**
  (previously 600 seconds). `SLO_BASH_DEFAULT_TIMEOUT_SECONDS` continues to
  override that fallback; an explicit tool-call timeout still takes precedence,
  and `0` disables the default ceiling.
- Headless, orchestration, README, and knowledge-base documentation now
  distinguish provider-read deadlines from independently bounded local tool
  execution.

### Verification

- Full non-E2E suite: **3,615 passed, 6 deselected**.
- Added watchdog unit coverage for first-progress and idle failures, stream
  completion, non-timeout propagation, and multiple in-flight tools, plus the
  graph-level delayed-tool-result regression.


## [0.16.0] — 2026-09-04

**Resilient detached workflows and evolved TUI experience.**

### Added

- **Durable detached-workflow supervision (spec 71).** Orchestrator, fleet,
  abort-request, and child terminal-status records are now persisted atomically.
  The TUI can reconcile lifecycle state, show fleet and cleanup diagnostics, and
  resume stalled or failed workflows in place with `/workflows resume <workflow-id>`.
- Advisory headless heartbeat telemetry, watchdog diagnostics, incremental
  visualizer capture tails, process liveness probing, and safe relaunch support.
- TUI transcript improvements: dedicated thinking blocks, one-deep queued prompts,
  terminal-native selection/copy surfaces, clearer tool-state styling, and improved
  visualizer/transcript streaming.

### Fixed

- **Headless workflow supervision (spec 71).** Detached workflows now use
  durable orchestrator, fleet, abort-request, and child-status evidence rather
  than a stale-heartbeat kill window. Child stdout inactivity is the only
  cancellation authority; advisory heartbeat liveness is surfaced as healthy,
  degraded, or silent and cleanup reaps every child.

### Added

- **`/workflows resume <workflow-id>`.** Relaunches stalled or failed detached
  workflows against their original orchestrator session history, appending the
  existing captures and returning the durable handle to `launching` until its
  next fresh self-report confirms `running`.

### Removed

- The retired stale-heartbeat multiplier configuration; operators no longer
  tune a second child-cancellation clock.

### Changed

- Child stdout inactivity remains the sole cancellation authority; heartbeat
  evidence is advisory (`healthy`, `degraded`, or `silent`) rather than a second
  kill clock.
- Cleanup now reaps confirmed children and protects against PID reuse and stale
  cross-process state.
- Expanded timeout, reconciliation, cleanup, relaunch, visualizer, TUI, and
  provider-policy regression coverage, together with headless-operation docs.


## [0.15.5] — 2026-08-31

**Provider stream-disconnection recovery.**

### Added

- Typed provider stream-disconnection classification and a one-shot,
  pre-commit fresh-connection retry path.
- Provider stream first-progress and idle deadlines, plus headless child
  heartbeat supervision and typed failure-envelope fields.
- Deterministic recovery, ModelPool, session, subprocess, and Textual TUI
  regression coverage.

### Fixed

- A long-running local tool or sub-agent wait no longer trips the provider
  stream idle deadline.
- The TUI now receives and renders the safe `stream_reconnecting` boundary
  before a fresh provider request begins.

---

## [0.15.4] — 2026-09-08

**Quiet CLI startup.**

### Fixed

- Removed routine model-catalog startup log records from the interactive CLI
  launch path, so they do not print before the TUI takes over the terminal.
- Suppressed LangGraph's known `allowed_objects` pending-deprecation warning at
  CLI startup while leaving unrelated dependency warnings visible.

---

## [0.15.3] — 2026-09-08

**Credential-free self-updates.**

### Fixed

- `slo update` now always uses the public repository URL and never injects
  `SLO_USERNAME`, `SLO_TOKEN`, deploy-token aliases, or personal-access-token
  variables into the pipx VCS requirement. This matches the public installer
  behavior introduced in v0.15.2 and prevents credentials from appearing in
  update output or process arguments.

---

## [0.15.2] — 2026-09-08

**Public, credential-free installer distribution.**

### Changed

- The Cloudflare Worker deployment helper now retrieves the canonical public
  `install.sh` directly from GitLab without an operator GitLab token.
- The hosted installer uses the public repository URL and never injects,
  persists, or exposes deploy-token/PAT credentials, including when legacy
  credential variables remain in an installer's environment.
- Docker installer smoke coverage now validates the public path without
  forwarding deployment credentials.
- Installation documentation and command examples now use the credential-free
  `curl -fsSL https://get-slo.sh/install.sh | bash` flow.

### Removed

- Deploy-token and personal-access-token handling from `install.sh` and the
  Cloudflare installer deployment flow.

---

## [0.15.0] — 2026-08-28

**Clean-room Git diff viewer, terminal-safe transcript copying, and safe large-image reads.**

Three feature streams land together in this minor release. The TUI gains a
focused `/diff` review screen backed by an extractable clean-room diff core and a
matching `show_git_diff` agent tool. Transcript text becomes copyable in
terminals where Textual could not previously select nested Markdown renderables,
at the cost of a `textual >= 8.2.7` floor. The `read` tool now bounds image
payloads before they reach the provider and stores a compact image reference in
durable history instead of stringified base64.

### Added

- **`/diff <repository-relative-path>` slash command and `GitDiffScreen`** — opens a
  full-screen, read-only review of one session-workdir file against `HEAD`. The
  default unified layout uses high-contrast red removed rows and green added rows,
  scrolls vertically, and keeps an optional synchronized side-by-side mode (`s`),
  wrapping (`w`), accessible line annotations (`a`), and `Escape` to return to the
  transcript.
- **Clean-room `slodiff` core** (`src/tui/slodiff/model.py`, `src/tui/slodiff/view.py`) —
  an extractable diff model and Textual widget built only from stdlib `difflib` plus
  Textual, with syntax highlighting and inline replacement spans. No third-party diff
  library is vendored or imported.
- **`GitDiffContentService`** (`src/tui/git_diff_content_service.py`) — safe
  HEAD-versus-worktree content loader that resolves nested Git roots against the
  session workdir, accepts UTF-8 text up to 1 MB per side, and rejects absolute
  paths, `..` traversal, and `.git` paths.
- **`show_git_diff` agent tool** (`src/agents/tools/show_git_diff.py`) — returns the
  same validated before/after content as JSON, raising the default bundle from 9 to
  10 tools. The tool is process-working-directory scoped; `/diff` is
  session-workdir scoped. Neither surface modifies the repository. A vendored
  `skills/tui/slodiff/SKILL.md` documents usage.
- **Per-response Copy control on assistant transcript blocks** — a right-aligned
  control on every assistant block copies the full agent response even in terminals
  where nested Markdown renderables cannot be selected. It stays disabled until an
  answer arrives, copies only the raw response, activates by click or Enter/Space,
  and shows transient "Copied" feedback. Implemented as a `Static`-based interactive
  control rather than a Textual `Button`, because affected terminal backends painted
  the button frame but not its label.
- **Drag-select auto-copy for transcript text** — releasing a mouse drag over the
  transcript copies the selected range with no keystroke. Delivery tries the local
  clipboard (`pyperclip`) first and always falls back to an OSC 52 escape, so copy
  works locally and over SSH/tmux. The existing `ctrl+shift+c` / `meta+c` binding
  still copies the focused block, prompt selection, or visible transcript, and now
  also emits OSC 52.
- **`LiteralTextStatic`** (`src/tui/widgets/literal_text_static.py`) — a `Static`
  with `markup=False` used for every plain-text transcript surface, so type hints
  (`list[str]`), timestamps, JSON, and regex spans render literally.
- **In-memory image resizing in the `read` tool** — JPEG, PNG, GIF, and WebP inputs
  are bounded to a 1568 px longest edge with aspect ratio preserved before base64
  encoding. Images already within the bound retain their original bytes, and source
  files are never modified.
- **`ImageResizeResult` and `ToolResultDAO`** — keep the live multimodal image block
  separate from a durable image reference. The executor attaches the reference to
  `ToolMessage` metadata.

### Changed

- **`textual` floor raised to `>=8.2.7,<9.0.0`** (from `>=0.74,<1.0`) — required for
  Textual's native selection API. A consequence of that version is that `Static`
  treats `[...]` in a string as console markup, which is why plain-text transcript
  surfaces now route through `LiteralTextStatic`.
- **`pyperclip (>=1.11.0,<2.0.0)` added as a dependency** — local clipboard delivery
  for the copy paths, with OSC 52 as the always-present fallback.
- **Durable history stores a compact image reference** — history tracing persists
  `[image attached: <name>, <WxH>, ref <absolute_path>]` instead of stringified
  base64. Resumed sessions keep a useful reference without inflating context or
  token estimates; projector and token-estimator behavior are unchanged.
- **`AGENTS.md`, `README.md`, and `docs/RESEARCH.md`** — updated for the 10-tool
  default bundle, the `/diff` command, the `slodiff` layout, the copy behavior and
  its `textual` pin, and the image-read/durable-history contract.

### Fixed

- **Oversized image reads fail cleanly instead of being rejected by the provider** —
  the 5 MiB encoded-image limit is enforced. A dense image still over the limit after
  resizing gets one JPEG fallback re-encode; if the fallback is still over the limit,
  the read returns a clear error rather than emitting a payload the provider will
  reject.
- **Empty agent responses cannot be copied** — the Copy control is guarded against
  activation before an answer exists, and restores its label after transient
  feedback.

### Verification

- Default suite green: 3,173 tests passed; 323 feature and impacted tests passed;
  feature-scoped Black and mypy checks passed.
- New coverage includes `tests/tui/slodiff/test_model.py`,
  `tests/tui/slodiff/test_view.py`, `tests/tui/test_git_diff_content_service.py`,
  `tests/tui/test_git_diff_screen.py`, `tests/tui/test_slodiff_import_regression.py`
  (startup import containment), `tests/agents/tools/test_show_git_diff.py`,
  `tests/tui/test_selection_copy.py`, `tests/tui/test_selection_copy_e2e.py`,
  `tests/tui/test_literal_text_static.py`, `tests/tui/test_textual_version.py`,
  `tests/agents/tools/test_image_content.py`, and
  `tests/agents/slo_agent/test_agent_image_history.py`.

## [0.14.18] — 2026-08-16

### Added
- Context-window inspection and manual compaction, including projector-faithful usage snapshots, model capacity handling, transactional history compaction, and `/context-window` and `/compact` commands.
- TUI usage footer support and bounded context-window refresh behavior.

### Fixed
- Preserved replay history cursors during transcript hydration.
- Fixed a transcript-window liveness leak that could delete the user's active message.

All notable changes to **slo** are documented here. This project adheres to
[Semantic Versioning](https://semver.org/) (pre-1.0: minor versions may carry
breaking changes).

## [0.14.17] — 2026-08-15

**Unified provider-error classification for transient-failure retries.**

Slo could not recover from OpenAI's status-less "Our servers are currently overloaded" `APIError`. On a single-model session the iteration-retry predicate matched only `"rate limit"` / `"429"` text and never consulted the shared error classifier, so the overload error fell through to LLM recovery — the log showed `run_recovering` → same overloaded model → `run_failed` instead of a bounded delayed retry. All three failure paths (single-model iteration retry, `ModelPool` route-switching, and `RecoveryPolicy`) now share one classifier.

### Fixed

- **Status-less OpenAI overload errors take a bounded delayed retry** — the OpenAI classifier maps the stable overload wording (`"our servers are currently overloaded"`) to `TRANSIENT_PROVIDER_FAILURE` when the SDK exposes no HTTP status. The session now emits `run_retrying` and, after the configured budget (2 retries → 3 attempts), a terminal `run_failed` — never a `run_recovering` observation routed back to the overloaded model.
- **Single-model sessions can classify provider errors at all** — `SloAgentSession._resolve_active_provider` resolves a single model's provider via `provider_for_model` rather than reading only a pool's `active_provider`, so sessions without a `ModelPool` reach the classifier.
- **Text-only rate limits still classify correctly** — `_classify_by_message_text` restores the provider-agnostic `"rate limit"` / `"429"` heuristic as a last-resort fallback after status-code checks. Folding the old string predicate into the classifier (rather than deleting it) prevents the two regressions this unification would otherwise introduce.

### Changed

- **`CreditExhaustionPolicy` → `ProviderErrorClassifier`** — renamed to reflect the widened taxonomy, which now owns credit exhaustion, rate limits, and transient provider failures. The old name is retained as a backward-compatible alias.
- **`_is_iteration_retryable_error` taxonomy-driven** — `RATE_LIMITED`, `TRANSIENT_PROVIDER_FAILURE`, and `AllModelsExhaustedError` are treated as wait-and-retry; `CREDIT_EXHAUSTED`, auth, and validation failures stay terminal. The no-replay-after-visible-output guard is preserved.
- **`AGENTS.md`** — provider-error handling section updated to describe the unified classifier.

### Verification

- Full non-E2E suite green, including new coverage in `test_credit_exhaustion_policy.py`, `test_recovery_policy.py`, `test_pool_fallback_e2e.py`, and `test_session_rate_limits.py`.

## [0.14.16] — 2026-08-04

**Model catalog spec-54: Claude Opus 4.8, Sonnet 4.6, Haiku 4.5, and 1M-context variants.**

Introduces four first-class Anthropic model entries aligned to spec-54, a `ModelCatalogService` API-model-name resolution layer, and comprehensive test coverage. The provider default shifts to `claude-opus-4-8-1m-context` (1M input context window). Existing sessions that stored a model name continue to work via the catalog alias mechanism.

### Added

- **Four spec-54 first-class model entries** — `claude-opus-4-8`, `claude-opus-4-8-1m-context`, `claude-sonnet-4-6-1m-context`, and `claude-haiku-4-5` are now registered in `SeedModelCatalog` with canonical names, display names, runtime profiles, and reasoning-level support flags.
- **`ModelCatalogEntryDAO.api_model_name`** — optional field that records the provider API model ID when it differs from the canonical Slo model name. `claude-opus-4-8-1m-context` and `claude-sonnet-4-6-1m-context` send their base model IDs (`claude-opus-4-8` / `claude-sonnet-4-6`) to Anthropic; `claude-haiku-4-5` sends the dated ID `claude-haiku-4-5-20251001`.
- **`ModelCatalogService.api_model_name_for`** — resolves a canonical name or known alias to the API model ID that must be sent to the provider. Raises `ValueError` on unknown names, supporting both API-key and Claude Code OAuth lanes.
- **1M-context runtime profiles** — `claude-opus-4-8-1m-context` and `claude-sonnet-4-6-1m-context` expose a 1,000,000-token context window; base variants stay at 200K. Opus variants carry the 128K output ceiling; Sonnet 1M and Haiku carry 64K.
- **`xhigh` reasoning support flags** — both Opus 4.8 variants support `xhigh`; Sonnet 1M and Haiku 4.5 do not.
- **Anthropic provider default updated** — `provider_default_models()` now returns `claude-opus-4-8-1m-context` as the Anthropic landing model.
- **TUI picker updated** — `model_suggestion_entries` and `model_catalog` surfaces include all four spec-54 entries with correct display names.
- **`_build_anthropic` API-model-name resolution** — `LLMFactory` resolves the catalog API model name before constructing the LangChain chat object, so 1M-context and dated-API variants are sent to Anthropic with the correct model string.
- **Full test suite for spec-54** — `test_model_catalog_seed.py`, `test_model_catalog_service.py`, `test_ai_model_config.py`, `test_base.py`, `test_provider_for_model.py`, and `test_model_catalog.py` cover catalog entries, display names, runtime profiles, API-model-name resolution, alias inheritance, `LLMFactory` integration, TUI picker projection, and provider-default landing model.

### Changed

- **`MODEL_DEFAULTS`** (`agents/base.py`) — extended with spec-54 context-window and max-token entries for all four new models.
- **`environments/.env.template`** — model-related example values updated to reference spec-54 model names.
- **CLI `--model` help text** — example updated to `claude-opus-4-8`.

### Verification

- All spec-54 model tests pass alongside the existing suite.
- `ModelCatalogService.api_model_name_for` resolves correctly for API-key and Claude Code OAuth lanes.
- `git diff --check` passes.

## [0.14.15] — 2026-08-04

**Transcript window reliability: untruncated user turns, force-revealed submits, and lazy scrollback.**

Fixes the regressions exposed when a long Textual transcript exceeds its mounted-widget window, while retaining the bounded live-rendering behavior introduced in v0.14.13. User prompts now remain fully readable, prompt submission reliably returns the viewport to the live end of the transcript, and scrolling to the top can lazily restore older evicted session history.

### Fixed

- **User turns never collapse or truncate** — `UserMessageBlock` now has a single full-text render path. The global expand/collapse control deliberately leaves user blocks unchanged, including newly submitted and replayed turns after collapse-all has been selected.
- **Submitted prompts are always visible** — a deliberate user submission clears history-browsing mode, force-reveals the new block, and keeps the follow latch armed through the post-layout bottom pin. This prevents an evicted/live-stream transcript from leaving a newly submitted prompt below a stranded viewport.
- **Follow-state race at assistant and tool mounts** — assistant and tool blocks capture the follow decision before mounting and transcript-window enforcement, then restore it afterward. The snapshot therefore reflects whether the user was following before new content changed the scroll geometry.
- **Long-workflow timeout defaults** — the orchestrator stream inactivity default is now **10,800 seconds (3 hours)** and the child sub-agent stdout inactivity default is **7,200 seconds (2 hours)**. Runtime consumers, documentation, orchestration prompts, and default-value regression tests now agree.
- **Detached-launch test isolation** — normal launch-path tests explicitly clear inherited `SLO_WORKFLOW_ID`; depth-guard tests continue to assert that nested detached launches are refused.

### Added

- **Lazy scroll-to-top history loading** — `TranscriptScroll` emits a typed near-top crossing message that starts a single-flight history load. The TUI re-reads ordered `TranscriptEntryDAO` history, prepends the batch immediately before the canonical entry cursor in chronological order, restores the scroll anchor after layout, and updates/removes the earlier-history summary accurately.
- **Back-scroll mode** — loading older history suspends normal top eviction until the user submits another prompt or clears the transcript, so requested scrollback is not immediately evicted again.
- **Complete replay prepend support** — `before=` insertion is propagated through user, assistant, tool, turn-separator, note, adapter, and raw transcript write paths, preserving transcript ordering for every replayed entry shape.
- **Regression coverage for small transcript windows** — focused Textual tests reduce `TRANSCRIPT_WINDOW_SIZE` to exercise eviction quickly and cover collapse immunity, stranded-viewport recovery, continued streaming follow, canonical cursor/batching behavior, single-flight loading, anchor preservation, summary lifecycle, back-scroll resets, and replayed separator/note placement.

### Verification

- `2955 passed, 4 deselected` — complete non-E2E test suite.
- Targeted mypy checks pass for changed timeout/orchestration runtime modules.
- `git diff --check` passes.

## [0.14.14] — 2026-08-02

**Clarified the `feature-specifications` skill: dual-mode specs by default + readability mandate.**

Documentation-only update to `skills/design-and-analysis/feature-specifications/SKILL.md`. No runtime or code behaviour changes.

### Changed

- **Default workflow reformatted** — the pre-hook → skill → post-hook sequence is now a bulleted `**Default workflow:**` block instead of an inline sentence, so the mandatory ordering is easy to scan.
- **Spec mode selection is now dual-mode by default** — every non-trivial feature specification must include **both** Mode A (business / product) and Mode B components unless the user explicitly asks for only one. Single-mode selection remains available on request and must still be recorded in the PRE-Hook Context Bundle. This replaces the previous "choose exactly one mode before drafting" rule.
- **Readability mandate added to the O'Reilly-chapter opening rule** — specs must mix narrative, numbered steps, ASCII diagrams, and tables to orient the reader; avoid silent code dumps or silent prose; and every behavioural claim must be grounded in a real code sample with a `file:line` citation. The document is explicitly framed as being for both the user and the AI, emphasising clarity.

## [0.14.12] — 2026-07-26

**Tolerant `spawn_sub_agents` task parsing (sub-spec 58.a) + TUI performance root-cause analysis.**

Fixes a class of orchestrator failures where the LLM emits a malformed `tasks_json` argument for `spawn_sub_agents` — a valid JSON array followed by trailing content, a double-encoded string, a markdown-fenced block, two concatenated arrays, or duplicate task ids. Previously `json.loads` rejected the entire payload with `JSONDecodeError: Extra data`, failing the whole sub-agent batch even though the intended tasks were recoverable. The orchestrator now recovers the intended tasks, records which tolerances it applied, and only errors when no task object can be salvaged.

### Added

- **Tolerant `tasks_json` parser** (`orchestrator/task_payload.py`, sub-spec 58.a) — a pure text-to-dicts layer, `parse_tasks_json` → `TasksJsonParseDAO`, that strips markdown JSON fences, decodes double-encoded strings, ignores trailing prose after a complete array, merges two concatenated arrays, drops duplicate task ids (keeping the first), and returns human-readable `recovery_notes` for every tolerance applied. It errors cleanly on empty input, non-JSON garbage, or JSON with no objects. The module knows nothing about `SubAgentTaskDAO` or the pool, so it stays independently testable.
- **`SubAgentTaskResolutionDAO`** (`orchestrator/dao.py`) — typed result of resolving `spawn_sub_agents` input into validated tasks: `tasks`, `recovery_notes`, and `error` (set only when the input cannot be resolved into tasks).
- **TUI performance root-cause analysis** (`docs/tui-performance-degradation.md`) — a standalone write-up of why the Textual TUI slows down as a conversation grows (an unbounded, non-virtualized transcript that forces an O(N) full compositor reflow on every keystroke and streamed token, plus an O(m²) Rich Markdown re-parse while streaming a single answer), grounded in framework-level `file:line` citations against Textual 0.89.1.

### Changed

- **`spawn_sub_agents` argument resolution** (`orchestrator/spawn_tool.py`) — `resolve_sub_agent_tasks` now accepts either a native `tasks` array or a legacy `tasks_json` string, builds `SubAgentTaskDAO`s from the tolerantly-parsed dicts, surfaces recovery notes, and follows error-JSON-never-raise semantics on every failure path. The OpenAI tool schema exposes the nested-array `tasks` shape, and neither task input is required.

### Tests

- New `test_task_payload.py` (the tolerant-parse matrix: clean array, single-object wrap, markdown-fence strip, double-encoded decode, trailing-prose ignore, concatenated-array merge, duplicate-id drop, and the empty / garbage / no-object error paths) and `test_spawn_tool_schema.py` (native array vs `tasks_json` string, neither-required, and the nested-array OpenAI tool shape); expanded `test_spawn_tool.py`, `test_workflow_routing_e2e.py` (native-tasks dispatch + corrupt-`tasks_json` recovery scenarios), and `test_default_orchestrator_prompt.py`.

## [0.14.11] — 2026-07-22

**Explicit orchestrator routing (spec 56) + non-blocking dynamic workflows (spec 57).**

**Spec 56** restores "dynamic workflows" to sync in-session execution and introduces the detach qualifier as the only route to `launch_workflow`. An unqualified "dynamic workflows" request now blocks the TUI and runs the workflow phases in the current session via `spawn_sub_agents`; only a request carrying an explicit detach qualifier — the word "headless", "detached", or "independent" applied to the dynamic-workflows request or to a named workflow ("headless dynamic workflows", "detached dynamic workflows", "independent dynamic workflows", or detach wording "in the background" / "without blocking") — routes to a single `launch_workflow` call. Detached orchestrators no longer receive `launch_workflow` (structural guard) and refuse recursion via `SLO_WORKFLOW_ID` (depth guard), closing the three-level cascade observed in session `7222023f-db7a-4d68-98b6-013551e101c6`.

**Spec 57** built the headless-workflow machinery: the `launch_workflow` tool, the workflow handle registry, the `WorkflowNotifier`, the TUI receive path, and the `/workflows` slash command — all described below.

### Refactored

- **Detached-workflow TUI receive path** — split the previously app-local lifecycle logic into `src/tui/workflows/`:
  - `dao.py` validates lifecycle payloads and `launch_workflow` results into typed data and UI effects without Textual, filesystem, or launcher side effects;
  - `service.py` (`DetachedWorkflowAppService`) reconciles and advances durable workflow handles, maintains the live-workflow cache used by resume hints, and returns typed effects;
  - `renderer.py` (`DetachedWorkflowRenderer`) owns visualizer launch de-duplication, launcher calls, and success/fallback transcript notices through narrow Protocol ports.
  `SloTUI` now composes these collaborators and routes events rather than parsing workflow JSON, changing handles, or launching detached visualizers itself.
- **Receive-path resilience and regression coverage** — malformed/error launch JSON, malformed lifecycle payloads, missing handles, illegal transitions, and handle-store failures are safe no-effect paths that do not interrupt inbox delivery. Terminal lifecycle events reset only the visualizer launch guard, allowing later workflow runs to launch a fresh window without opening one at terminal delivery.
- **Operator-facing lifecycle documentation** — clarified that inbox delivery requires enabled filesystem-backed session history because detached processes write the cross-process inbox; expanded `SessionOwnershipLeaseStore` documentation to explain acquire/renew/release, expiry, and TUI hand-off behavior.

### Added

- **`launch_workflow` tool** (`orchestrator/launch_tool.py`) — detached spawn
  with `start_new_session=True`, non-secret `SLO_*` env allowlist,
  handle-file-before-spawn crash safety, live-workflow cap
  (`SLO_MAX_DETACHED_WORKFLOWS`, default 2), and error-JSON-never-raise
  semantics on every failure path (capture files, spawn, handle writes). An
  operator abort landing mid-spawn is honoured by reaping the fresh process
  group. Depth guard: refuses (error JSON, no spawn) when `SLO_WORKFLOW_ID` is
  present in the process environment.
- **Workflow handle registry** (`orchestrator/workflow_registry.py`) —
  `WorkflowHandleDAO` + `WorkflowHandleStore` (atomic 0600/0700 writes,
  legal-transition table, pid-liveness `reconcile` with a 30 s launch grace
  window, path-safe workflow ids) and the read-only `workflow_status` tool.
- **`WorkflowNotifier` + `slo run --notify-session <sid>`**
  (`orchestrator/notifier.py`, `cli/headless.py`) — the headless runner taps
  its own event stream and enqueues durable inbox messages: `workflow_started`
  and per-phase `workflow_phase_update` as `context_note`, terminal
  `workflow_completed`/`workflow_failed` as `chat_turn`. Enqueue failures are
  swallowed; without the flag, headless behaviour is byte-identical.
- **`context_note` delivery mode + `workflow_update` history events** — claimed
  notes render a `⊛` line AND persist a synthetic completed turn (idempotent on
  inbox `message_id`) that `SessionHistoryProjector` includes in model context
  as `[workflow update] …`, in true chronological position, surviving
  `--resume` (resume context is golden-equal to live context). New session API
  `SloAgentSession.record_workflow_update`.
- **TUI receive path** (`tui/app.py`) — visualizer retargeted to the
  orchestrator's session id from the `launch_workflow` tool result (fallback:
  the `workflow_started` note on resume), one window per orchestrator session;
  claimed notes advance the durable handle state; mount-time reconcile; the
  exit hint lists live workflows; `^C`/`/abort` keep today's
  current-turn-only meaning.
- **`/workflows` slash command** (`/wf`) — reconciled list, `abort <id>`
  (SIGTERM to the process group, SIGKILL escalation after 5 s), `dismiss <id>`
  for stalled workflows. `WorkflowCommandService` refuses non-positive pids so
  a never-patched handle can never signal the TUI's own process group.
- **Kill switch** `SLO_DETACHED_WORKFLOWS=0` keeps all dynamic-workflow
  requests in-session via `spawn_sub_agents`.

### Changed

- `SloAgentSession.attach_sub_agent_pool` accepts a `spawn_tools` list;
  `OrchestratorSessionBootstrap.attach` gains `headless: bool = False`; when
  `headless=True` (the `HeadlessRunner --orchestrator` path) `_build_workflow_tools`
  returns `[]` so detached orchestrators structurally cannot call `launch_workflow`
  or `workflow_status`; TUI call site is unchanged and keeps all three tools.
- Orchestrator prompts rewritten (spec 56): unqualified "dynamic workflows" runs
  in-session via `spawn_sub_agents`; only a detach-qualified request routes to
  `launch_workflow`; routing documented across `spawn_tool.py`,
  `launch_tool.py`, `AGENTS.md`, `CLAUDE.md`, `skills/INDEX.md`,
  headless-orchestration / workflows / orchestrator `SKILL.md` files, and
  `docs/SLO_HEADLESS_README.md`.
- Test harness safety: `environments/tests.env` sets `SLO_AUTO_VISUALIZE=0`
  and an autouse fixture in `tests/conftest.py` stubs
  `VisualizerLauncher._default_spawn`, so no test run can ever open real
  terminal windows on the developer's machine (regression-tested).

### Tests

- ~130 new tests across the handle store, launch tool, notifier, headless tap,
  context delivery/projection/replay, TUI receive path, and `/workflows`
  service + router; full suite 2801 passing.

## [0.14.10] — 2026-07-19

**Longer inactivity timeouts for slow, large-context model calls.** The two
inactivity watchdogs that guard against genuinely hung streams were raised so
that legitimately slow turns — big prompts, slow time-to-first-token, long
tool/model lanes — are no longer misclassified as hangs and killed mid-turn.

### Changed

- **`STREAM_INACTIVITY_TIMEOUT_SECONDS` default raised `2400` → `4800`** (40 → 80
  minutes). This is the orchestrator's / main agent's own LLM-stream inactivity
  guard. Overridable via `SLO_STREAM_INACTIVITY_TIMEOUT_SECONDS`. Updated in
  `config/cfg.py` and the `_DEFAULT_STREAM_INACTIVITY_TIMEOUT_SECONDS` fallback
  in `src/agents/slo_agent/sessions/service.py`.
- **`SUBAGENT_INACTIVITY_TIMEOUT_SECONDS` default raised `1800` → `3600`** (30 → 60
  minutes). This is the child sub-agent stdout inactivity guard
  (`CHILD_INACTIVITY_TIMEOUT_SECONDS`). Overridable via
  `SLO_SUBAGENT_INACTIVITY_TIMEOUT_SECONDS` (alias
  `SLO_SUBAGENT_INACTIVITY_TIMEOUT`). Updated in `config/cfg.py` and
  `src/agents/slo_agent/orchestrator/process.py`.
- Both values remain env-overridable; only the shipped defaults changed.
- Synced the shipped-default documentation to the new values: the orchestrator
  runtime prompt (`orchestrator/spawn_tool.py`), `README.md`,
  `docs/SLO_HEADLESS_README.md`, the `headless-orchestration` skill, and
  `scripts/validate_recovery.py`.

### Tests

- Updated the shipped-default assertions in `tests/config/test_cfg.py`,
  `tests/agents/slo_agent/orchestrator/test_process.py`, and
  `tests/agents/slo_agent/test_session.py` to expect `4800.0` / `3600.0`.

## [0.14.9] — 2026-07-19

**Automatic live visualization + a richer, resizable workflow visualizer.** When
an orchestrator-backed TUI session spawns its first sub-agent, Slo now opens
`slo visualize` in a separate terminal window automatically and keeps it following
the run — operators no longer have to notice a workflow went headless and open the
viewer by hand. The visualizer UI itself was reworked from an MVP into a themed,
keyboard-resizable, markdown-rendering surface that mirrors the main TUI.

### Added

- **Auto-launch of the workflow visualizer** (`src/tui/visualizer_launcher.py`):
  - New `VisualizerLauncher` opens `slo visualize --session <parent_session_id> --follow`
    in a fresh OS terminal window. macOS drives Terminal.app / iTerm via `osascript`;
    Linux probes common terminal emulators (`gnome-terminal`, `konsole`, `xterm`, …);
    unsupported platforms and spawn failures fall back gracefully.
  - `SloTUI._maybe_launch_visualizer` fires the launch exactly once per run on the
    first `sub_agent_spawned` event, guarded by `_visualizer_launched_for_run` and
    reset in `_cleanup_sub_agent_state`. On failure it writes the manual
    `slo visualize` command into the transcript instead.
  - Only a **non-secret `SLO_*` allowlist** (`SLO_HOME`, `SLO_ENV`, `PYTHONPATH`, …)
    is forwarded into the new window; provider keys and deploy tokens are never
    placed in the world-readable argv.
- **New config flags** (`config/cfg.py`): `SLO_AUTO_VISUALIZE` (default on; set `0`
  to opt out) and `SLO_VISUALIZER_TERMINAL_APP` (choose `Terminal` / `iTerm` on
  macOS or a terminal-emulator executable on Linux).
- **Workflow-summary bar** in the visualizer showing run state and a colour-coded
  tally of sub-agents by status (running / completed / failed).
- **Test coverage**: `tests/tui/test_visualizer_launcher.py`,
  `tests/tui/test_visualizer_ui_enhancements.py`, and new auto-launch cases in
  `tests/tui/test_subagent_event_routing.py`.

### Changed

- **Visualizer UI redesign** (`src/tui/headless_workflow_visualizer.py`):
  - **Keyboard-resizable panes** — `ctrl+←/→` widen/narrow the sub-agent list,
    `ctrl+↑/↓` grow/shrink the diagnostics pane (clamped, applied live). This
    directly addresses the inability to resize the sub-agent (phase) panel.
  - **Themed styling** aligned with the main TUI theme variables
    (`$surface` / `$accent` / `$panel` / `$boost`).
  - **Markdown transcript rendering** — assistant answers and user messages render
    through `rich.markdown.Markdown`, matching the main TUI; sub-agent list entries
    are colour-coded by status.
  - Status bar now reports the current pane sizes.

### Fixed

- The visualizer no longer has to be launched and discovered manually for
  orchestrator (dynamic) workflows started from the TUI.

### Notes

- Version bumped to `0.14.9` in `pyproject.toml`; `AGENTS.md` documents the
  auto-launch behavior and the new resize / rich-rendering surface.

## [0.14.8] — 2026-07-18

Unified model-catalog **latest-model support**: Slo now defines model support once in a canonical `src/agents/model_catalog` package and projects that truth into config, reasoning, provider routing, TUI model surfaces, startup fallback notices, and orchestrator child prompt wiring. This release adds the latest first-class OpenAI, Anthropic, and Kimi lineup while preserving compatibility aliases and keeping the non-e2e suite green.

### Added

- **Canonical model catalog package** (`src/agents/model_catalog/`):
  - `dao.py` — typed catalog, runtime-profile, reasoning-profile, alias, template, discovery, and override DAOs.
  - `seed.py` — committed first-class catalog entries for `gpt-5.5`, `gpt-5.6-luna`, `gpt-5.6-sol`, `gpt-5.6-terra`, `claude-fable`, `claude-mythos`, `kimi-k3`, and `kimi-for-coding-highspeed`, plus retained existing production models.
  - `service.py` — memoized seed/cache/discovery/override load path and canonical entry resolution.
  - `store.py` — cache and override persistence under `~/.slo/global/`.
  - `discovery.py` — best-effort provider discovery merge surface and override application helpers.
  - `prompt_clause.py` — exact-match Kimi task-prompt suffix injection for `kimi-for-coding` only.
- **User-visible invalid-model fallback notice** plumbed from config/session startup into the TUI so a bad saved model preference falls back safely and tells the operator what happened.
- **Catalog-focused regression coverage** across seed data, discovery/override behavior, provider routing, Kimi prompt-clause wiring, startup notices, and TUI `/model` projections.

### Changed

- **Legacy model-support surfaces are now catalog-backed projections**:
  - `config/ai_model_config.py`
  - `src/agents/reasoning_capabilities.py`
  - `src/auth/provider_for_model.py`
  - `src/tui/model_catalog.py`
  - `src/tui/slash_router.py`
- **Session startup and CLI config construction** now preserve and render fallback-notice metadata when a requested model is invalid or compatibility-only.
- **Orchestrator child prompt assembly** now appends the terse Kimi clause only for the exact model name `kimi-for-coding`, not for `kimi-k3` or `kimi-for-coding-highspeed`.
- **Prompt-critical docs** (`AGENTS.md`, `README.md`, `docs/RESEARCH.md`, `docs/SLO_HEADLESS_README.md`) now describe the canonical catalog architecture instead of the older split-table model story.

### Fixed

- **Kimi family temperature handling** now sets `temperature=1` for every canonical `ProviderName.KIMI_FOR_CODING` model, fixing runtime 400s for `kimi-k3` and `kimi-for-coding-highspeed` (`invalid temperature: only 1 is allowed for this model`).
- **Full-suite gate regression** in `skills/presentation/present-as-pdf-book/SKILL.md` by restoring the required `## Guidance` section so the repo default test gate remains green.

### Notes

- `claude-mythos` remains hidden by default and capped at `high` reasoning until availability is confirmed by discovery or operator override.
- Kimi family models remain `off`-only for user-configurable reasoning because the provider does not expose controllable reasoning levels.
- Verification for this release: targeted catalog/tests green, touched-surface mypy green, full non-e2e suite green (`2590 passed, 4 deselected`).

## [0.10.2] — 2026-06-27

Provider **message-contract reconciliation** — fixes a crash where a session
whose model emitted an empty final assistant turn replayed an empty `assistant`
message and the provider rejected the turn with `400 invalid_request_error`
(*"the message at position N with role 'assistant' must not be empty"*).
Independent of compaction. No schema change; backward-compatible.

### Fixed

- **No empty assistant message is replayed.** A turn that ends with an
  `assistant_message` carrying no text and no tool calls (the model produced an
  empty final response after its tool results) no longer projects to an empty
  `AIMessage`. The reconciler drops it, keeping the surrounding tool pair and
  the next user message intact.

### Changed

- **`ToolCallReconciler` → `MessageContractReconciler`** (renamed/broadened from
  0.10.1). It is now the single enforcer of every provider message-contract rule
  on the projected history: drop orphan/id-less tool results, heal dangling tool
  calls, **and** drop empty assistant messages. `_event_to_message` stays a pure
  event→message map; provider legality lives in one place. New provider rules
  are added here.

### Notes

- 6 new/renamed unit tests + 1 projector regression test; full suite green;
  mypy clean on the touched modules. Implements
  `specifications/42-message-contract-reconciliation`.

## [0.10.1] — 2026-06-27

Compaction **cut integrity** — fixes a crash where a compacted session could
replay an orphaned `tool_result` and the provider rejected the turn with
`400 invalid_request_error` (`tool_call_id is not found` on the OpenAI/Kimi
lane). No schema change; backward-compatible with 0.10.0 sessions.

### Fixed

- **The compaction cut never splits a tool span.** `Compacter._find_cut_point`
  replaced its adjacency-only guard (which assumed a `tool_call` and its
  `tool_result` are neighbours) with a span-based **clean-cut** algorithm. When
  the token-driven candidate would compact a `tool_call` while retaining its
  `tool_result` — including a parallel tool-call batch or a `spawn_sub_agents`
  group with interleaved `assistant_delta` / sub-agent lifecycle events — the
  cut moves **up** (compacting slightly more) until each tool group is whole on
  one side. The returned cut is asserted clean via `_is_clean_cut`.

### Added

- **`ToolCallReconciler`** (`history/tool_call_reconciler.py`) — the single
  abstraction that enforces the provider's tool-call/tool-result pairing
  contract on a projected message list, in both directions: it drops orphan or
  id-less tool results (a result whose call was compacted away) and heals
  dangling tool calls (a call with no result). `SessionHistoryProjector`
  delegates to it. Sessions already compacted with a bad cut (pre-0.10.1) now
  load cleanly.

### Notes

- ~12 new/revised unit tests; full suite green; mypy clean on the touched
  modules. Implements `specifications/41-compaction-cut-integrity`.

## [0.10.0] — 2026-06-27

Conversation-tree **auto-compaction**: long sessions now summarise their oldest
history into a `compaction_summary` event when the running token total nears the
model's context window, keeping future turns inside the window instead of
crashing with a provider context-overflow error.

### ⚠️ BREAKING — session event logs are not backward-readable after compaction

This release adds a new persisted history event kind, **`compaction_summary`**,
to `HistoryEventKind`. Once a session is compacted, its
`~/.slo/sessions/history/<id>/events.jsonl` contains a `compaction_summary`
line.

`SessionHistoryEventDAO.kind` is a strict Pydantic `Literal`, so **any slo build
older than 0.10.0 cannot parse a compacted session** — `load_events()` raises a
`pydantic` `literal_error` on the unknown kind and the TUI surfaces it as
`(configuration error: …)`, failing the load of the **entire** session (not just
the one line).

Compatibility is **forward-only**:

- 0.10.0 reads logs written by older builds fine.
- Older builds **cannot** read logs that 0.10.0 has compacted.

**Migration / operator guidance:**

- Upgrade **every** slo install (pipx, dev checkouts) to ≥ 0.10.0 before opening
  any session that may be compacted. A common failure is running a stale global
  `pipx` `slo` against a session a newer dev build already compacted.
- Do **not** downgrade below 0.10.0 after compaction has run on a session.
- A loader-hardening follow-up (skip-and-warn on unknown event kinds, so older
  readers degrade gracefully instead of hard-failing) is tracked separately and
  is **not** included here.

### Added

- **Compaction pipeline** (`src/agents/slo_agent/compaction/`):
  - `CompactionChecker.should_compact()` — pure, local trigger decision.
  - `Compacter` + `CompactionResult` — newest-to-oldest cut-point search
    (never splits a tool_call/tool_result pair; never compacts the first user
    message), LLM summarisation of the compacted slice.
  - `CompactedSessionUpdater` — persists the `compaction_summary` event.
  - `constants.py` — `RESERVED_TOKEN_LIMIT` (16,384), `KEEP_RECENT_TOKENS`
    (20,000).
- **Projector compaction boundary** (`history/projector.py`) — emits the summary
  as a `[Previous conversation summary]` header and replays the retained tail,
  resolving the boundary from `first_kept_entry_id` so the append-only store
  layout keeps the recent context it was meant to.
- **Session wiring** (`session.py`) — `_run_compaction_if_needed()` runs after
  every completed turn and inside the context-overflow error handler
  (`_is_context_overflow_error()`).
- **Migration utilities** (`history/migration/`) — `TokenUsageBackfiller`
  (back-fills `token_usage` on pre-existing events) and `TreeMigrator`
  (`+ MigrationResult`) to adopt flat sessions into the tree layout.
- **Per-model `context_window`** on `config.ai_model_config.MODEL_DEFAULTS` —
  the single source of truth for each model's input window.

### Changed

- `CompactionChecker` now sources context windows from `MODEL_DEFAULTS` instead
  of a hardcoded, Anthropic-only table. This corrects real mis-estimates: the
  default model `gpt-5.4` is **1,050,000** tokens (was treated as 200k),
  `kimi-for-coding` is 262,144 (was 200k → compacted ~62k early), and `gpt-4o`
  is 128,000 (was 200k → would have overflowed before compaction). Claude
  models remain at 200,000 (the 1M window needs the `context-1m` beta header,
  which slo does not yet send).
- `history/filesystem_store.py` imports `TokenEstimator` lazily to keep the
  `history → compaction` dependency one-directional.

### Notes

- ~110 new unit/integration tests; full suite green (1786 passed); mypy clean.
- Adding a value to a `Literal` discriminator is not forward-compatible for
  older readers — see the BREAKING section above.
