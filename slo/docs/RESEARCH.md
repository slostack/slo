# Slo Codebase Index

## Feature 89 runtime owners and offline acceptance

`src/agents/providers/openai_platform.py` owns strict nonmutating caller-option
validation, sampling/include sanitation, cap normalization and the lifetime-pinned
SDK subclass selected by `LLMFactory` only for API-key required-Responses records.
All three GPT-6 seeds also support OAuth through the unchanged Codex builder,
including subscription headers, instructions adaptation and cap removal. Legacy
models keep stock/Codex SDK paths and shallow sanitation. Session final eligibility
checks run before adoption and lazy OAuth refresh; startup/router consume the
session snapshot. Picker cache identity includes generation, snapshot identity,
auth revision, lifecycle revision and active model; row reads do no credential I/O.

`test_openai_platform.py` covers all 21 locked-SDK tool cycles and constructor/wire
policy; `test_feature89_model_flows.py` covers mounted tools/resume, isolated mixed
lanes and committed failures. `test_feature89_frozen_reader.py` extracts the exact
pre-feature commit and validates real v2 writer bytes plus legacy seed/temperature
oracles. Separate v0.20.1 tree/flat history tests exercise all four saved route IDs;
these are readability/append proofs, not old-version inference on new models.
Both seed policy flags are excluded only at the v2 writer. No schema migration.
See `implementation/89-gpt-6-support/recovery13-closure.md` for actual gates;
static baseline failures are unwaived, independent review/assessment pending.

## Shared-state compatibility contract — 86.b (2026-10-04)

This supersedes Feature 86 `../overview.md:654` (“new code ignores schema 1;
old code may ignore schema 2”). Released validation happens before version
rejection, so incompatible formats must have different filenames.

| File under SLO_HOME | Released reads / writes | New reads / writes | Compatibility boundary |
|---|---|---|---|
| global/model_catalog_cache.json | import / explicit discovery only | never / never | Released schema 1 |
| global/model_catalog_cache.lock | no / no | never / never | Reserved name |
| global/model_catalog_cache.v2.json + .v2.lock | no / no | load / refresh + flock | Provider schema 2 |
| global/authentication.json | lookup / auth + refresh | lookup / released rows | anthropic, openai, kimi_for_coding only |
| global/authentication.additional-providers.json | no / no | lookup / additional rows | OpenRouter; future unknown providers need another sibling |
| .credentials.lock | flock / create | flock / create | Existing OAuth coordination |
| global/model_catalog_overrides.json | yes / no | yes / no | Operator-owned |
| sessions/history/** | yes / yes, including compaction | yes / yes, including resume metadata | Shared extra-ignore schema; rewrite limitation below |
| preferences | yes / yes | yes / yes | Released defaults fall back to gpt-5.4 when unsupported |

| Provider cache state | Cold load | Refresh | Log |
|---|---|---|---|
| missing | seed | write | none |
| valid schema 2 | seed + slices | replace | none |
| other schema (1, 3) | seed | replace | model_catalog_cache_schema_ignored info |
| corrupt / unreadable / invalid | seed | replace | one model_catalog_cache_load_failed warning, no traceback |
| any released cache state | never open | never write | none |

| Credential operation / edge | Result |
|---|---|
| load | Read both (absent means empty), merge owned rows |
| persist / remove | Atomically rewrite owning file only, preserve other rows |
| misfiled row | Ignore with warning every lookup, preserve on writes, never migrate |
| either file unreadable / invalid | CredentialStoreCorruptError for that path, history writes fail closed |
| later unknown provider in additional file | Same error; future versions must use another filename |
| SLO_AUTH_FILE override | Additional file follows beside override |
| modes | Files 0600, parent 0700 |

The sole owners remain ModelCatalogStore and CredentialStore. No lock, DAO,
resolver, migration or catalog owner was added. Concurrent released/new writes
of the same credential file retain the pre-existing lost-update risk. A misfiled
OpenRouter key is unavailable to redaction; README's manual pre-fix cleanup must
move it before new Slo runs. No cleanup is automated.

Unknown saved direct models use the preferred/default model and existing startup
block; explicit models, pool primary and OpenRouter pending preparation remain
unchanged. Both production tree and explicit flat stores use events.jsonl; tree
links live in payload.metadata. Released compaction drops provider_message_extension
from rewritten events, but preserves it in the pre-compaction archive.

Executable proof: tests/compat uses actual git-archived v0.20.1 with minimal env
on per-test state shared with current code. Both directions continue and assert
all ordered user/assistant contents. The real visualize CLI mounts headlessly
and audits both source/destination auth/catalog paths. A missing release tag fails
rather than skips. Current gates: implementation/86b-model-catalog/b5-implementation.md;
historical Feature 86.a waivers are not permission to waive 86.b gates.

## Latest Step-1 bounded window correction — 2026-10-03

The prior final gate is retained unchanged: `.f86-final-remediation-hldebc_g/full-final.log`
reports **1 failed, 5155 passed, 18 deselected, 196 warnings**, exit 1. The exact
bounded-model-window failure reproduced in isolation. Direct-provider summaries
incorrectly acquired the gateway `; provider default` suffix, expanding the normal
rows from two to three lines (five rather than eight rows). The existing suggestion
projection now preserves direct-provider summaries; OpenRouter evidence is unchanged.
A stronger eight-label/footer compositor assertion then exposed detail width exceeding
the inner menu width by four cells. The menu now uses the same inner width for both.
No count/window expectation was relaxed, no sleeps/skips added, and no R1/R3 changes.

Focused partition: 38 passed; intermediate strengthened-paint run: 1 failed/173 passed;
paint correction: 30 passed; final affected: **174 passed, 5 warnings**; additional
surrounding picker/status regressions: **48 passed, 2 warnings**. Full expanded
commands/logs/exits: `.f86-window-correction-tPhyAzET/`. The fresh complete gate
is `full.log`, `full-command.txt`, `full.exit` there, generated AFTER these final
documentation edits. Its actual exit/summary controls readiness; no anticipated pass.
Final source/test/current-doc manifest: `source-test-manifest.sha256`, digest in
`manifest.sha256`, generated after full gate and read-only checks; no edits thereafter.

R1 router truth, R2 two-size compositor/hidden-paint sensitivity and R3 real schema-2
public preparation/valid SDK no-budget proof remain retained. R4 points to this new
receipt, not a reconstructed missing directory. E1 removal still injects refresh
outcome (not all-real zero-HTTP removal). Historical selection offset has no claimed
causal repair. Auth sensitivity remains retained. Black/mypy waived, not green;
provider evidence remains offline synthetic, not live authorization or paid inference.
Independent sequential Step2/Step3 remain pending; readiness is not feature approval.
Earlier current/latest headings below are preserved historical receipts.

## Current sequential remediation — 2026-10-03 (R1–R4)

R1 control-aware `/reasoning`, R2 genuine two-size picker/router compositor proof,
and R3 real schema-2 public admission → valid SDK no-budget completion are corrected
with focused red/green evidence; affected partition: **460 passed, 5 warnings**.
Initial full gate found five picker status/context clipping regressions (5151 passed,
18 deselected); its full.log is retained. Corrected menu uses a separate reasoning
line only for explicit disable semantics, preserving status/context; two-line rows
retain original capacity and three-line rows use bounded capacity. This is a
narrow viewport adjustment to the original two-line plan, not weakened assertions.
Picker regressions now pass 32 tests. The new final gate receipt is `.f86-final-remediation-hldebc_g/full-final.log`, with exact
command in `full-final-command.txt` and result in `full-final.exit`. These artifacts are produced
**after this documentation is finalized**; consult their actual result, not an
anticipated pass. The missing `.f86-step1-1791030546-full` claim is not relied on.
See `docs/implementation/86-openrouter/sequential-r1-r4-remediation-2026-10-03.md`
for the finite matrix and source/test freeze contract. Prior headings below are
historical, not outstanding G1/G2 assertions or current gate pointers.

E1 remains qualified real-loader/stale-delivery/rotation proof: removal injects a
refresh outcome, not all-real zero-HTTP removal. Historical selection offset has
no claimed causal repair. Auth compositor/sensitivity evidence is retained.
Black/mypy remain waived, not green; 18 normal E2E/default-disabled exclusions
are expected (actual gate log controls). All provider evidence is offline synthetic,
not live authorization, availability or paid inference. Independent Step2/Step3
remain pending; no feature-completion or approval claim.


## Latest recovery receipt — 2026-10-03 final authorized Call 4: REVISE

Fresh complete post-edit non-E2E gate: **5136 passed, 18 deselected, 196 warnings
in 327.78s; exit 0**, `.f86-final-recovery-O3ZPKA/full-non-e2e.log`.
This supersedes earlier receipts as the latest execution, not as approval.
Budget evidence persistence, nullable-rate override restoration, actual default-effort
SDK wire assertion and bounded picker detail fixes landed. Remaining: unexplained
Call3 selection offset failure (passes isolated/full now, no causal repair), `/reasoning`
presentation and mounted two-size proof, prepared/no-budget evidence, and stronger
real-store admission proof (new removal test injects refresh outcome).
See `docs/implementation/86-openrouter/final-recovery-evidence-2026-10-03.md`.
**STEP1READY withheld.** Independent Step2/3 remain pending. Offline synthetic tests
are not live authorization/availability/inference evidence; 18 E2E/default-disabled
live/fixture cases were deselected. Black/mypy waived, not green. Earlier receipts
below remain historical; no final workflow approval.


This concise index points maintainers to the runtime owners most relevant to Feature 75 plugin extensions and the adjacent agent/TUI seams.

## Skills maintenance

- Edit the authored `skills/**/SKILL.md` tree directly. `make refresh-skills` and
  `make build-skill-index` both rebuild only `skills/INDEX.md` through
  `scripts/build_skill_index.py` and `SkillRegistry`.
- `scripts/refresh_skills.py` no longer imports or regenerates upstream prompt
  content. It preserves all skill bodies, workflows, samples and assets, including
  non-code families such as presentation. No `SLO_CODE_PROMPTS_DIR` is needed.
- This is development-time maintenance only; runtime discovery and user override
  behavior remain unchanged. Regression coverage: `tests/agents/skills/test_refresh_skills.py`.

## Orchestrator limits

`config/cfg.py` defaults `SLO_SUBAGENT_MAX_CONCURRENCY` to 6; the pool uses it
for its shared semaphore. The prompt in `orchestrator/spawn_tool.py` separately
allows eight workflow turns started per task (including partial turns), six
dispatch calls per turn, and three retries per failed task after the initial
attempt. Aborted tasks are never retried. These are prompt rules, not new runtime
counters. A new revision turn resets only its dispatch count; retries and turns
remain task-wide across resume and takeover. Use single dispatches at review
gates: chain checks execution status, not READY/REVISE. Process completion is not
workflow acceptance. Stream, child-output and Bash defaults remain 10800, 7200
and 1800 seconds. Shell exports must precede process launch; a Bash tool export
cannot modify an already running parent process.

## Runtime path

```text
src/cli/app.py → src/cli/typer_dispatch.py → SloAgentSession
  → SloAgent → graph/service.py tool node → ToolExecutor → agent tools
  → AgentStreamEventDAO subscribers → TranscriptProjector → Textual widgets
```

- `src/cli/app.py` is the Typer parse surface. `src/cli/typer_dispatch.py` owns runtime assembly. `src/cli/plugin.py` provides the managed-plugin lifecycle sub-app.
- `src/agents/slo_agent/sessions/service.py` owns session construction, plugin loading/merging, event subscribers, durable history coordination, and the named `before_agent_turn` consumer seam.
- `src/agents/slo_agent/agent.py` owns the multi-turn ReAct loop, runs `before_agent_turn` plugin handlers before every outer iteration with the true iteration number, and drains graph-owned partial-output updates into its normalized event stream.
- `src/agents/slo_agent/graph/service.py` owns LangGraph construction, the tool node, executor selection, and the queue-to-stream bridge for `tool_output_update`.
- `src/agents/slo_agent/tool_execution/executors.py` is the tool-call chokepoint for sequential/concurrent execution, immutable per-invocation `RunnableConfig.configurable` output callback binding, and plugin tool interception.

## Feature 75 plugins

- `src/agents/slo_agent/plugins/dao.py` defines typed registrations, health records, and interception decisions.
- `api.py` is the recorder passed to `register(slo)`; it records registrations and can forward live status updates to the session-owned dispatcher map.
- `identity.py` validates GitHub/GitLab HTTPS sources and derives IDs, module names, tool names, command tokens, and status keys.
- `installer.py` is the only managed-directory writer. It validates manifests, copies declared payloads without executing source code, pins provenance, and rolls back swap-phase failures. It also exposes explicit bundled Bash renderer installation with `package:<version>` provenance.
- `trust.py` persists project trust decisions with `AtomicFileWriter`; unreadable state fails closed.
- `loader.py` discovers managed, trusted-project, and explicit `--plugin` paths; it imports each under a namespaced module and isolates load failures.
- `registry.py` merges registration views, refuses collisions, and cross-validates managed tool/command suffixes against manifest declarations.
- `dispatcher.py` isolates event handlers and interception hooks, enforces timeout policy, and owns the live status map.

Managed installed plugins live under `~/.slo/plugins/plugins/<plugin-id>/`; `~/.slo/plugins/registry.json` is the durable install registry. Development dogfooding uses the explicit tier:

```bash
slo --plugin plugins/bash_live_output/plugin.py
```

## Live Bash output

- `src/agents/tools/tool_output.py` defines the display-only `ToolOutputUpdateDAO` snapshot.
- `src/agents/tools/bash.py` incrementally reads merged output, extracts its optional callback from mapping-shaped `RunnableConfig.configurable`, retains terminal formatting/kill/reap behavior, and emits throttled snapshots when a callback exists.
- `tool_output_update` is a `StreamEventKind` in `src/agents/slo_agent/events/stream.py`. It is emitted on normal subscribers and headless stdout JSONL, and persisted when history is enabled; `history/projector.py` excludes it from model replay.
- `src/tui/transcript_projector.py` routes an update by `tool_call_id` to the existing `ToolExecutionBlock`; `src/tui/widgets/tool_execution_block.py` keeps partial output separate from terminal lifecycle truth.
- `src/tui/event_renderer.py` consults registered renderers before built-in summaries. `plugins/bash_live_output/` is the bundled consumer-only raw Bash renderer.

## Operator and TUI surfaces

- `slo plugin install <url> --yes`, `list`, `uninstall <id>`, and `upgrade <id>` delegate through `TyperDispatch.plugin` to `PluginInstallerService`.
- `/plugins`, `/plugins trust`, and `/plugins reload` are registered in `src/tui/slash_command_registry.py` and handled in `src/tui/slash_router.py`.
- `src/tui/widgets/usage_status_bar.py` renders a plugin status segment from the dispatcher’s live status map when the app provides updates.

## Authentication (spec 78, fix 78.b.1)

- `src/tui/authentication/auth_screen.py` drives the modal. An `OAuthFlowFactory()` instance (`src/auth/provider_factory.py`, `__call__`) builds `OAuthFlow` (browser authorization) or `DeviceAuthorizationFlow` (device authorization). The factory must be an instance: the class object is not callable with the protocol keywords, and that failure was hidden inside a fire-and-forget task until `_on_begin_oauth_done` was added.
- **OpenAI device start wire contract** (live `POST https://auth.openai.com/api/accounts/deviceauth/usercode`, checked 2026-09-14): HTTP 200 `{device_auth_id: str, user_code: str, interval: "5", expires_at: str}`. `interval` is **decimal text**, not a JSON number. `OpenAICodexOAuthProvider._interval_as_int` accepts an int or trimmed decimal text and rejects bool, negative, float, `"5.5"`, null and missing. `expires_at` is ignored; Slo keeps `SLO_OAUTH_DEVICE_TIMEOUT_SECONDS`. Fixtures must copy this live shape.
- **Link rendering decision:** `AuthorizationLink` (`src/tui/authentication/widgets/authorization_link.py`) is a thin subclass of Textual 8.2.8 `textual.widgets.Link`, shared by browser and device presentations. `show(url=...)` paints `Content.styled(text=url, style=Style(link=url))`, so segments carry an OSC 8 target and `[`/`]` are never parsed as markup. `DEFAULT_CSS` sets `width: 1fr; text-wrap: wrap` because `Link` defaults to `width: auto` and clips long URLs. TCSS `link-*` properties do not apply to it (Textual applies them only to `@click` markup). The loopback redirect URI stays a plain `Static`.
- **Browser opening:** `BrowserHost` (`src/auth/browser_host.py`) returns False on non-macOS/Windows hosts without `DISPLAY`, `WAYLAND_DISPLAY` or `BROWSER`, because CPython `webbrowser` then runs console browsers that `wait()` on the TUI terminal. `OAuthFlow` opens through `asyncio.to_thread` concurrently with the code race; `SloTUI.open_url` opens in a thread worker.
- Tests assert **painted** compositor output through `tests/tui/authentication/_painted_output.py`. The device E2E (`tests/tui/authentication/test_authentication_device_e2e.py`) runs the real screen, factory, flow and provider against a local aiohttp server; its `@pytest.mark.e2e` live smoke hits the real usercode endpoint and cancels before approval (`pytest -m e2e <file>`).

## Rate-limit preflight and provider signals (spec 77)

- `SloAgentSession` creates one immutable `PreflightDecisionDAO` for each successful local
  preflight. Its history-aware estimate is reused unchanged for local accounting and redacted
  provider observations. A local preflight exception is advisory degradation: no local accounting
  is recorded and the provider lane remains open.
- Local TPM is never a gate. An empty token window whose estimate exceeds the configured hint
  emits one durable/live `preflight_bypassed` audit and sends the request; the TUI prints the fixed
  tool-result line without changing spinner state. `preflight_bypassed` and
  `provider_limit_observed` are excluded from model replay.
- `ProviderErrorClassifier.inspect()` is the sole provider/context recognition seam. It reads
  response headers before exception headers and retains only finite positive decimal `Retry-After`
  seconds (ceil to at least one) and positive decimal request/token limits; invalid or sensitive
  headers are discarded. Each rejected lane produces at most one redacted `provider_limit_observed`
  record. For a confirmed initial context overflow with no committed output, the session retries
  once only after `compact_to_boundary()` commits; a no-op, failed, second, visible-output, or HTTP
  413 / `REQUEST_BODY_TOO_LARGE` failure is terminal and never replays, switches pool lanes, invokes
  LLM recovery, retries, or forces compaction.
- `CompactionChecker` resolves canonical, alias, and discovered models through
  `ModelCatalogService`, and triggers at `floor(context_window * 0.70)`; unknown models retain the
  conservative default capacity.

## Compaction revisited (spec 85)

- **One summary-request seam.** `Compacter._invoke_llm_summary` is the single
  manual/automatic/overflow summary call. For a direct model it runs the request through the
  existing `graph/service.py::adapt_chatgpt_backend_request`, which now also drops
  `max_tokens`/`max_output_tokens`/`max_completion_tokens` on the ChatGPT-backend branch while
  hoisting system text into top-level `instructions`. For a `ModelPool` (`_is_pool_bound`) it
  passes the raw `[SystemMessage, HumanMessage]` list and `max_tokens=RESERVED_TOKEN_LIMIT` so the
  pool's own per-member adapter shapes whichever lane it routes to, including a pre-output
  fallback. Anthropic, OpenAI API-key, and Kimi direct lanes are unchanged.
- **The default automatic trigger is unchanged.** `CompactionChecker.should_compact` still gates
  on `floor(context_window * 0.70)` over all persisted event `token_usage`; no absolute input
  ceiling or capacity resolver was added.
- **256k latency advisory.** `SloAgentSession` holds one in-memory `_compaction_advisory_armed`
  boolean (initially `True`) and evaluates it only in `refresh_context_window_snapshot()` — never
  on streamed deltas. At or above `SLO_COMPACTION_ADVISORY_TOKENS` (default `256_000`, resolved by
  `config.timeout_resolver.positive_int_env`) with `snapshot.estimate_available`, it dispatches the
  one new `StreamEventKind` literal `compaction_advised`, then disarms. A later available
  below-threshold snapshot re-arms it; an unavailable estimate neither emits nor re-arms. The
  advisory asks the user to run the literal `/compact`; it never compacts. `SloTUI._render_event`
  renders it through `_write_adapter_line(classes="tool-result")` with no widget or projector
  branch, and `/context-window` enters the same refresh boundary.
- **Durable redacted failures.** Manual and forced-overflow failures reuse existing structures: a
  bounded `"<ExceptionClass>: <redacted message>"` from `_safe_compaction_failure_message`, the
  existing `compaction_failed` stream event with safe metadata
  (`failure_scope="compaction"`, `error_class`, `safe_message`, optional provider/status), and one
  existing-kind `run_failed` audit appended best-effort (persistence errors log class only).
  `run_failed` is already excluded from replay. No new history kind, failure DAO, or widget was
  added.
- **Manual-compaction activity.** `SlashCommandSpecDAO.shows_activity` is the declarative seam for
  long-running slash commands. `/compact` sets it, and `SloTUI._dispatch_slash_command` mounts the
  existing `ThinkingSpinner` before awaiting dispatch and removes it in `finally` only when that
  dispatch mounted it. The existing `compaction_started` event changes the visible text to
  `Compacting session history…`; no new event or widget was introduced.
- **Composed offline verification (85.a.4).** The composed contract tests live in:
  `test_session_manual_compaction.py::test_oauth_manual_compaction_persists_and_projects_summary`
  (real OAuth `ChatOpenAI` over `httpx.MockTransport` driven through
  `SloAgentSession.compact_context()`; wire has `instructions` and no output-token field, exactly
  one replayable `compaction_summary`),
  `test_compacter.py::TestChatGptBackendSummaryRequest` (wire capture),
  `test_pool_fallback_integration.py::TestPoolCompactionFallbackDirections` (Codex→non-Codex
  restores system/cap; non-Codex→Codex yields instructions/no cap through the real per-member
  adapter), `test_session_compaction_advisory.py` (threshold/one-shot/re-arm/env/unavailable),
  `test_session_compaction_integration.py` (secret-bearing overflow failure redacted across event,
  audit, persistence log, and projector replay), and `test_projector_compaction.py` (scoped audit
  excluded from replay). The pool's switch seam is `ProviderErrorClassifier.inspect` (not the
  older `classify`), so pool tests must use error shapes the real classifier treats as switchable
  (e.g. 429 on any lane, 402 only on Anthropic).

## OpenRouter mounted full-flow acceptance (Feature 86, incomplete)

`tests/integration/test_openrouter_full_flow.py::test_mounted_openrouter_auth_picker_router_session_and_resume_flow`
uses real production composition with a mounted `AuthenticationScreen` and `SloTUI`, rather than helper-only selector calls: candidate `/key` precedes persistence, discovery publishes an unseeded route, the mounted picker/router selects its canonical identity, a harmless bound tool runs through local SDK SSE, and a newly prepared session sends the next prompt with its private same-route reasoning anchor. The fixture is deterministic `MockTransport` only; it does not prove stale/removal, pool, committed-error, child/schedule, or full feature acceptance.

## OpenRouter bounded composed verification (Feature 86, incomplete)

`tests/integration/test_openrouter_full_flow.py` exercises real candidate
verification, credential persistence/resolution, authenticated discovery, catalog
publication, display-name search/canonical selection, session selection, and the
prepared factory's local SSE request. The mounted flow additionally covers auth,
picker/router interaction, a bound tool, and a newly prepared same-process session
resume with the private anchor. It proves no duplicate `/key` during auth handoff and
reloads the persisted catalog after service reset. Default sync/async HTTP transports
are blocked; synthetic key absence is checked in public results, logs, model chunks
and catalog bytes. This does **not** prove OS-process restart, complete private-history
artifact scanning, stale/removal/cancellation matrices, mixed-pool fallback, or
complete committed-failure/cross-channel acceptance. Fixtures are synthetic, not live
provider observations.

## OpenRouter (Feature 86 — current partial delivery)

- Canonical exact route identity is `'openrouter:<exact-remote-id>'` in
  `src/auth/provider_for_model.py`; the provider is always `OPENROUTER`, never
  inferred from the remote ID's author segment. `CredentialResolver` resolves
  `SLO_OPENROUTER_API_KEY` at operation time before the OpenRouter store row;
  empty is absent and whitespace-only values are rejected. There is no OpenRouter
  legacy fallback.
- `src/integrations/openrouter/` is a fixed-origin injected-`httpx` GET boundary
  for `/api/v1/key` and `/api/v1/models/user`. It captures one credential, does
  no inference/retry/logging of wire bodies, and exposes only safe exceptions.
  `OpenRouterAuthenticationService` verifies a candidate before persistence and
  carries private verification evidence to catalog refresh; public result state is
  secret-free and an environment key wins over a pasted replacement.
- `OpenRouterCatalogConverter` produces conservative exact discovered entries;
  `ModelCatalogService` owns authenticated publication/admission while `load()`
  stays offline. `OpenRouterRequestPolicy` and `OpenRouterChatOpenAI` provide the
  existing Chat-Completions/SDK lane; private route/reasoning continuation is kept
  only for same-route runtime/history replay. `/model refresh`, bounded cached
  picker search, exact selection, pending interactive startup, prompt-generation
  preparation, headless preparation, and explicit-model-clears-pool semantics are
  implemented with targeted local tests. This is not a live availability claim.
- Schedules pass their stored model to `slo run`; trusted headless children forward
  the exact `SLO_OPENROUTER_API_KEY` exception while other secret-shaped names remain
  filtered. Complete scheduled/inbox/populated-artifact acceptance is not proved.

Feature 86 remains **REVISE**. The retained **pre-correction** Step 1 gate is
**5115 passed, 18 E2E-marked deselected, 196 warnings in 373.69s; exit 0** at
`.f86-integration-retry-ucwY1o/full-non-e2e.log`. The 18 deselections include
default-disabled live/fixture harness tests; executed OpenRouter testing is offline
local/mock transport evidence, not live credential, network, availability, paid
inference, or authorization verification. Black/mypy are waived only as static gates,
not green. Independent review remains **REVISE** while concurrent source corrections
address current findings; the receipt is not a final post-correction gate or approval.
Bounded later evidence supersedes the older statement that Plan B and OS-process
admission had not been exercised: append ordering/refusal, independent OS-process
resume admission, append-wait cancellation, and a reaped-launcher native-I/O EBADF
case are covered. The exact-entry qualification uses instrumented shipped
writer/reporter bodies and is not native interpreter-startup equivalence; it does not
create an argv-equality product requirement. See
`docs/implementation/86-openrouter/independent-full-rereview-2026-10-03.md` for
current review findings; dated reports remain historical.

### OpenRouter pending interactive startup (bounded 86.a.4)

`TyperDispatch.tui` alone opts into `build(allow_pending_preparation=True)`.
Session-owned transient readiness defers reasoning and usage capability resolution;
the welcome notice must also defer or genuinely cold routes still fail at mount.
The app owns one tracked worker calling `prepare_startup()` and awaits cancellation
on unmount. That gateway derives snapshot/reasoning/usage before a no-await adoption
on the same session identity. Failed startup retains unknown limits and safe
`/auth` / `/model refresh` recovery. Public invoke and pending model selection are
gated independently of the UI. This is bounded local startup proof, not full
credential freshness or complete Feature 86 readiness.

### OpenRouter per-prompt catalog adoption (bounded 86.a.4)

- Config-backed OpenRouter single/pool submissions now call the existing
  `ModelCatalogService.prepare_models()` once under the session prompt lock,
  before history/agent setup. The returned snapshot lasts through the complete
  submission and is cleared in the run-scope finalizer. Injected agents and
  direct-only sessions retain the existing path.
- Session adoption compares configured entries against the lazy agent's build
  snapshot, not the manual-refresh read view. Changed entries invalidate the
  agent, reclamp reasoning, and invalidate cached context capacity; unrelated
  generation changes may reuse the agent. Selection also updates config identity
  so next admission validates the selected route rather than its predecessor.
- Context measurement, attempt rate policy, and compaction calls receive the
  session snapshot. `test_prompt_catalog_admission.py` exercises full Faux-backed
  submissions with an event barrier, next-run metadata changes/removal, and pool
  rejection without member subtraction.
- This is offline catalog admission, not credential verification: the catalog
  gateway still lacks credential-aware refresh. TUI pending startup and the
  full cross-context integration contract remain incomplete.

### OpenRouter candidate authentication (bounded 86.a.5 continuation)

- `src/auth/openrouter_authentication.py` now verifies an environment capture or
  private submitted candidate before `CredentialStore.persist`. Candidate commit
  rechecks the source through the existing resolver. Verification failure or
  cancellation before commit preserves the previous credential bytes.
- The service forwards matching verification evidence to the existing catalog
  refresh API. Public results carry fixed safe copy only; cancellation after
  commit records that the verified key was saved. Catalog failure does not undo it.
- The existing modal exposes OpenRouter via API-key-only factory capabilities,
  tracks/awaits verification tasks and paints literal safe results. Its body now
  caps width at the terminal width, preventing Cancel clipping at 60 columns.
- This does not finish the catalog's supplied-capture race checks, picker,
  refresh command, or full auth-to-inference integration. Current catalog refresh
  bypasses effective-fingerprint checks for supplied captures; auth evidence
  forwarding is not a claim that this remaining catalog race has been resolved.

## Kimi K3 reasoning

- The model catalog owns K3's canonical `low`, `high`, and `xhigh` reasoning
  profile; `xhigh` resolves to K3 provider effort `max`. K3 always reasons, so
  `off`/`minimal` clamp to `low` and `medium` clamps to `high`.
- `LLMFactory._build_kimi_for_coding_chat_openai()` is the only Kimi native
  request boundary. It sends top-level `reasoning_effort` only for enabled K3
  resolved reasoning; K2 coding models remain off-only and never receive
  `thinking` or OpenAI Responses fields.

## Granular AI-message selection (spec 81.c.1)

- `MarkdownContentCompiler` (`src/tui/widgets/markdown_content_compiler.py`) is
  the one pure markdown-it AST compiler for answer, thinking, and user bodies.
  Its sole append-only writer returns raw Markdown, independently selectable
  conventional visible text, and role-name spans over that visible text. The
  body widgets resolve those roles through active theme variables only once
  mounted, then render `Content(visible_text, ...)`; raw source remains exactly
  on the owning block for explicit whole-message raw copy. Pygments only adds
  spans over compiler-emitted code for exact case-insensitive trim-only aliases:
  Python, shell, JSON/YAML, diff/patch, JavaScript/TypeScript, TOML/INI/XML/HTML/
  CSS/SQL/Dockerfile/Markdown. Diff/patch also adds additive semantic
  added/removed/hunk/file line spans. Every fenced and indented block has
  `markdown-code`; unknown, malformed, attribute-bearing, unlabeled,
  resolver-failed, lexer-failed, and reconstruction-failed fences retain exact
  visible code with generic spans only.
- Textual owns visible-buffer hit testing, native selection paint, range state,
  and scroll attachment. No visible/raw mapper, Rich visual, custom Screen, or
  second clipboard path exists. Standard focused copy returns visible text;
  `ctrl+shift+m` / `meta+shift+m` walks a focused body's ancestors to the
  nearest block raw provider and uses `SloTUI.copy_to_clipboard()`.
- Selection coverage: `tests/tui/test_markdown_content_compiler.py`,
  `tests/tui/test_user_message_block.py`,
  `tests/tui/test_selection_scroll_highlight.py`,
  `tests/tui/test_selection_copy.py`, `tests/tui/test_selection_copy_e2e.py`,
  and replay hydration in `tests/tui/test_replay_resume.py`.

## Knowledge-base discovery in skills

- The KB is optional. `skills/design-and-analysis/locate-knowledge-base/SKILL.md`
  is the single owner of discovery: `$SLO_KB_DIR`, then
  `${SLO_HOME:-~/.slo}/KnowledgeBase/KB`; entry point `Welcome.md`, `index.md`,
  `Index.md`, or legacy `Home.md`.
- A missing KB never blocks a skill. The agent tells the user, offers to create
  one (setting `SLO_HOME` when unset), and persists the variables in the user's
  shell profile, never in the installer-owned `~/.slo/shell/environment.sh`.
- `tests/agents/skills/test_committed_skills.py` fails any skill that references
  `$SLO_KB_DIR` without deferring to that skill and stating it is non-blocking.
- The runtime prompt matches it: `config.cfg.KB_LOCATION` resolves `SLO_KB_DIR` →
  `KB_DIR` → `$SLO_HOME/KnowledgeBase/KB` (a file path resolves to its directory)
  and `KB_BLOCK_TEMPLATE` renders that path, its source, and the lookup order.

## Isolated pipx launchers (spec 82.a)

- `install.sh` is the sole writer for both the user-facing pipx `slo` wrapper and managed shell state. It validates `PIPX_HOME`, `pipx runpip` metadata, venv identity, and generated `slo`/`slo-entry` scripts before atomically replacing only the recognized generated `slo` script with `<venv>/bin/python -I slo-entry`. A normal POSIX venv's `bin/python` may link to a base interpreter outside the venv; finalization retains that venv-side pathname and accepts it only when executing it reports `sys.prefix` exactly equal to the validated venv root. Outer venv-root links, malformed/cyclic chains, and unsafe user artifacts remain refused.
- `slo update` invokes the packaged `install.sh --finalize-launcher` immediately after a successful pipx reinstall and before conditional shell-default work. Direct pipx mutations bypass this step; recovery is the matching tagged public installer.
- The wrapper ignores hostile Python import configuration but preserves ordinary process environment for its initial CLI process, including `SLO_SKILLS_DIR` and `SLO_KB_DIR`. Headless children remain sanitized-environment module spawns without `-I`; visualizer source fallback is trusted-source-only and does not forward `PYTHONPATH`.

## Installer/update GitHub outage fallback

- `install.sh` and `src/cli/update.py::Updater` default to GitLab with
  `https://github.com/slostack/slo.git` as a one-shot outage fallback. A failed
  pipx invocation is retried only when a subsequent bounded Git probe cannot
  reach the primary; reachable-primary build failures are not retried.
- Latest release discovery falls back on failed/timed-out remote tag lookup;
  empty release sets on reachable repositories remain semantic errors.
- Both paths honor `SLO_REPO_URL` / `SLO_REPO_FALLBACK_URL`; empty mirror disables
  retries, identical URLs are not retried, and custom primaries have no default
  official mirror. No setup token injection. Git terminal prompts are disabled.
- GitHub mirror privacy is operationally separate: anonymous users cannot fetch
  a private mirror. The GitLab push key is not a credential for installing users.
- Tests: `tests/cli/test_update_mirror.py` (mocked orchestration/transport) and
  `tests/cli/test_install_mirror.py` (real Bash with temp-owned fake commands).

## Environment defaults and `slo update` (supersedes spec 80.a.2)

- `install.sh` is still the only writer of shell state. `slo update` (all modes)
  runs the just-installed `<Location>/install.sh --finalize-environment` after a
  successful pipx reinstall; `install.sh` ships in the wheel for this.
- `ShellEnvironmentDefaults` in `src/cli/update.py` runs that step only when
  `SLO_HOME`, `SLO_SKILLS_DIR`, or `SLO_KB_DIR` (or `KB_DIR`) does not exist
  (set-but-empty counts as existing). The managed file's lines are also
  existence-guarded, so a user's own export always wins.
- Consequence: a stale `SLO_SKILLS_DIR` export is never rewritten. `slo update`
  warns when it has no `INDEX.md` or differs from the installed skills; the
  prompt gives the agent recovery steps (`$SLO_SKILLS_DIR` → `$SLO_HOME/skills` →
  `pipx runpip slo show slo`).
- Tests that reload `config.cfg` rebind `ResolvedDirectory`; compare its fields,
  not instances, in tests.
- Coverage: `tests/cli/test_update.py` (decisions + real-bash end-to-end),
  `tests/cli/test_install.py` (`TestManagedEnvironmentKnowledgeBaseDefault`,
  `TestFinalizeEnvironmentMode`), `tests/config/test_cfg.py`,
  `tests/agents/slo_agent/test_prompts.py`, and the opt-in
  `tests/cli/test_wheel_contents.py::TestWheelShipsInstaller`.

## Feature 83 — `gpt-6-astra` static policy and request construction

- The canonical catalog (`src/agents/model_catalog/seed.py`) owns the single picker-visible
  `gpt-6-astra` record. Its `500 RPM / 500,000 TPM` values are a static conservative
  local Tier-1 policy, **not** an account entitlement, discovery result, or availability
  claim. Generic catalog/profile flags own provider reasoning requirements and sampling
  restrictions; no Astra-specific provider, recovery, discovery, graph, or TUI branch exists.
- `ReasoningLevel` is the global seven-level vocabulary: `off`, `minimal`, `low`, `medium`,
  `high`, `xhigh`, `max`. Astra persists/displays `off`, while generic resolution enables
  provider reasoning with effort `low`; it never sends provider `off` or `none`. Legacy
  profiles retain their own supported subsets.
- `LLMFactory._build_openai()` resolves the provider API model ID once and applies the
  generic profile request policy to a copied extras mapping. Astra's enabled path uses
  Responses; bound tools therefore use the Responses flat function-tool representation.
  Enabled Astra requests omit `temperature`, `top_p`, `top_logprobs`, and `logprobs`.
- Offline `MockTransport` tests cover the Astra Responses stream/body, resolved effort,
  and flat tool form. Selection/autocomplete and bounded recovery tests explicitly forbid
  discovery. **No live provider or entitlement smoke ran**, so this records construction
  policy only—not remote availability or credential entitlement.

## Verification owners

- Plugin tests: `tests/agents/slo_agent/plugins/`.
- Streaming executor/bridge/history tests: `tests/agents/slo_agent/tool_execution/`.
- Bash streaming tests: `tests/agents/tools/test_bash_streaming.py`.
- TUI tests: `tests/tui/test_tool_block_partial.py`, `tests/tui/test_event_renderer_overrides.py`, `tests/tui/test_plugins_slash_command.py`, and `tests/tui/test_usage_status_bar_plugins.py`.
- Bundled-plugin contract: `tests/plugins/test_bash_live_output_plugin.py`.
- CLI lifecycle surface: `tests/cli/test_plugin_cli.py`.

## Slotui specification recovery (spec 79; planned, not implemented)

`/root/Code/specifications/projects/slo/specifications/79-tui-v2/` contains
the proposed Slotui extraction, not current runtime architecture. Its
cross-file contracts were independently reconciled in
`verification-report-round4.md`: the generic session remains an
async-generator single-flight gateway, generic history activation is only
`apply_rewrite(rewrite=...) -> None`, and the terminal renderer exposes a
fixture-only capture API for conformance. Before implementation, treat that
report and `tasks.md` as the dependency order and rerun the named executable
gates; do not infer that Slotui modules already exist in this repository.

### OpenRouter streamed continuation assembly (bounded 86.a.3)

`OpenRouterChatOpenAI` now owns one ContextVar-scoped `OpenRouterMessageCodec`
per stream and resets it in `finally`. Complete private metadata appears once
on a final metadata-only chunk: attaching it repeatedly lets LangChain concatenate
route/provider strings and corrupt replay. Indexed details merge by index with
stable-field checks; non-JSON and >8 MiB metadata fail safely. Local factory/SDK
coverage in `test_openrouter_fragments.py` crosses trace/history JSON projection
and the second tool-result HTTP request, including different-route stripping.
SDK DEBUG request options are now hidden in an adapter-local ContextVar scope;
each nested/concurrent sync/async scope owns a distinct filter. Known SDK transport
exception records keep their fixed labels but not raw traceback data (the SDK logs
before adapter normalization). `test_openrouter_channels.py` proves a real local
factory/SDK bound-tool agent/session run, one private durable anchor extension,
same-route second request, clean public stream/headless `_emit` JSONL, clean
non-event history files, TUI replay compositor paint, and safe HTTP/transport
exception str/repr/formatted traceback. Runtime traces and replay-bearing history
are intentionally private metadata carriers, not public diagnostic channels.
Full sentinel-bearing pool fallback/audit and headless status/fleet/subprocess
capture proof remain unverified; this is not complete Feature 86 security proof.

### OpenRouter catalog takeover — bounded lifecycle/consolidation

`ProviderModelDiscoveryService.refresh` is now an async provider-scoped compatibility
delegate to `ModelCatalogService.refresh`; its all-provider credential loop and empty
success placeholder are removed. Pure direct-template merge helpers remain. The merged
`ModelCatalogStore.write_cache` writer is removed; raw provider persistence is unchanged.
Store read paths do not mkdir/chmod. Catalog refresh counts task subscribers so cancelling
one default-client waiter cannot close a client still used by another waiter.

Call 4/4 repairs the subsequent Call 3 provenance regression: lifecycle capture must
not clear the last committed `_snapshot` or reset its generation. Cold load reads
seed/cache/overrides without resolver/client/network/cache-write I/O; warm mismatch
filtering is a pure projection over committed state. `_publish_candidate` binds private
fingerprint provenance only with successful publication and increments generation.
Admission captures lifecycle identity and rereads the filtered view. A cold process
without lifecycle capture may browse persisted rows; that is not authorization to run.
The exact eight publication regressions and one added rotation/failure/next-admission
barrier pass locally. Cross-process and full feature acceptance remain Pending; see
the Call 4/4 implementation ledger. No second catalog/state owner was introduced.

## Feature 86 R2/R3/R4 remediation boundary

The headless stream task's ContextVar does not propagate back to its parent.
`HeadlessRunner` retains only the admitted operation capture observed at the event
subscriber, sanitizes public events before retaining/emitting them, binds the capture
around post-stream terminal notifier persistence, and releases it in `invoke` finally.
No capture is persisted or attached to a public DTO; private continuation is unchanged.
The fixed GET client rejects full pages adding no unique records before catalog
publication. Failed refresh retains the last-good provider slice.
`src/tui/model_catalog.py::ModelPickerRowDAO` is presentation-only;
`src/agents/model_catalog/dao.py::ModelCatalogEntryDAO` remains canonical.
See `docs/implementation/86-openrouter/remediation-r2-r3-r4-2026-10-03.md` for
historical 5045-pass non-E2E evidence and limitations. The later independent Step 2
rereview is **REVISE**; see
`docs/implementation/86-openrouter/independent-full-rereview-2026-10-03.md`.


## Specification authoring ownership

`skills/design-and-analysis/feature-specifications/SKILL.md` is the canonical
Gather context → Draft → Self-check → Revise authoring skill. The former hooks
are compatibility redirects; independent verification and task breakdown remain
separate, sequenced by `workflows/specification-development.md`. Every feature
requires product framing in overview.md and separate standalone engineering
sub-specs; there is no mode selection or combined-document exception. Skill paths
follow runtime discovery and supported environment overrides. Project artifact
paths override generic home defaults. Author self-check is not independent approval.
Module-depth design guidance lives in `coding/declarative-method-structure` and is
advisory, not a hard extraction-rule exemption. Refresh tooling overlays upstream
skills without deleting locally maintained policy/workflows/samples. See
`docs/implementation/spec-skills-consolidation/` for preservation and gate evidence.

Refresh preservation requires testing real manifest selection plus writer collisions,
not only a manually constructed protected author record. The protected-owner set
also includes Code-Test-Review's entry pointer and audited local routing/KB/review
safety policy; unknown historical customizations still need explicit ownership
audit before upstream refresh. Runtime descriptions must match body routing: the
extended context companion is on-request and shares canonical artifact precedence.
See `revision-evidence.md` in the consolidation evidence directory; independent
re-review and completion remain pending.
