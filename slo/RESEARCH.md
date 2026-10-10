# Slo Codebase Index

## Feature 89 runtime boundary — approval pending

The catalog owns `supports_chatgpt_codex` and `requires_responses_api`. Both
survive Python dumps/copies/merges; only `ModelCatalogStore.write_provider_cache`
excludes them for strict pre-feature schema-2 readers. Required-Responses
reasoning overrides may change the default, not the fixed controls.

`LLMFactory` validates its captured credential and selects the configured
`OpenAIPlatformChatOpenAI` for API-key required-Responses records; OAuth uses
the existing Codex builder. The three GPT-6 seeds support both lanes. `OpenAIRequestPolicy`
owns constructor and final SDK merge protection, preserving legacy shallow
semantics. Session final selection checks precede adoption; lazy checks precede
OAuth refresh. Startup/router use the session snapshot; picker auth types are
lifecycle-only presentation evidence. Jev null output metadata reaches the
existing conservative cap without weakening authenticated admission.

Locked offline SDK/tool/resume and distinct frozen-reader proofs now exist;
no live authorization or release claim follows. Current receipts and remaining
static/review/assessment gates: `docs/implementation/89-gpt-6-support/recovery13-closure.md`.

## Shared-state compatibility contract — 86.b (2026-10-04)

This supersedes Feature 86 `../overview.md:654` (“new code ignores schema 1;
old code may ignore schema 2”). The old reader validates first and logs errors;
the old credential enum rejects new rows. Filename separation, not a version
field inside an incompatible file, protects released users.

| File under SLO_HOME | Released reads / writes | New reads / writes | Contract after 86.b |
|---|---|---|---|
| global/model_catalog_cache.json | import / explicit discovery only | never / never | Released schema 1 untouched |
| global/model_catalog_cache.lock | no / no | never / never | Reserved released name untouched |
| global/model_catalog_cache.v2.json + .v2.lock | no / no | provider slices / refresh + lease | New schema 2 only |
| global/authentication.json | lookup / auth + refresh | lookup / released rows only | Frozen anthropic, openai, kimi_for_coding set |
| global/authentication.additional-providers.json | no / no | merged lookup / additional rows | OpenRouter today; future unknown providers need another file |
| .credentials.lock | flock / create | flock / create | Existing OAuth coordination, no new lock |
| global/model_catalog_overrides.json | yes / no | yes / no | Operator-owned |
| sessions/history/** | yes / yes including compaction | yes / yes including resume metadata | Shared extra-ignore DAOs; released rewrites lose provider_message_extension |
| preferences | yes / yes | yes / yes | Released falls back from unknown OpenRouter default to gpt-5.4 |

| Provider cache state | Cold load | Refresh | Log |
|---|---|---|---|
| missing | seed | write | none |
| valid schema 2 | seed + slices | replace | none |
| other schema (1, 3) | seed | replace | one model_catalog_cache_schema_ignored info |
| corrupt, unreadable, invalid | seed | replace | one model_catalog_cache_load_failed warning, no traceback |
| any released cache state | never opened | never written | none |

| Credential operation / edge | Result |
|---|---|
| load | Absent files are empty; merge owned rows of both files |
| persist / remove | Read and atomically rewrite only the owning file; retain other rows |
| misfiled row | Ignore on read, warn on every lookup, preserve on write; no migration |
| either file invalid / unreadable | CredentialStoreCorruptError names that file; history redaction fails closed |
| unknown future provider in additional file | Same error; later versions MUST use another sibling filename |
| SLO_AUTH_FILE override | Additional file follows its stem/suffix beside it |
| permissions | Both files 0600, parent 0700 |

A released writer does not acquire a new shared credential lock; concurrent
same-file updates can still lose updates, as two released writers could before.
Misfiled OpenRouter keys are not known to new history redaction: manual cleanup
must move the row before using new Slo. README contains the operator-only steps;
no pre-fix state is cleaned automatically. Released compaction keeps the original
extension in its pre-compaction archive, but not rewritten retained events.

`tests/compat` extracts frozen v0.20.1 and runs minimal-environment subprocesses
against the same per-test state as current code. Exact content/order, not just
counts, proves tree/default and flat continuation in both directions. Both stores
physically use events.jsonl; the tree store decorates payload metadata. The real
visualize CLI guard mounts the actual app and audits both source/destination
catalog/auth paths. See b5-implementation.md for gate receipts and limitations;
no historical static waiver applies to 86.b.

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


This root-level index is the project memory entry required for feature work. The
maintained runtime notes live in [`docs/RESEARCH.md`](docs/RESEARCH.md); read that
document before planning or changing a feature.

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

## OpenRouter (Feature 86 — current partial delivery)

- `'openrouter:<exact-remote-id>'` classifies structurally to `ProviderName.OPENROUTER`.
  `SLO_OPENROUTER_API_KEY` is evaluated per resolution operation; empty is absent
  and whitespace-only is rejected before HTTP. Precedence is environment then the
  OpenRouter credential-store row; OpenRouter has no legacy-Claude fallback.
- `src/integrations/openrouter/` is an injected, offline-testable fixed-origin GET
  boundary for `/key` and `/models/user`. Authenticated discovery, canonical catalog
  publication/admission, API-key-only `/auth`, `/model refresh`, bounded picker
  selection, strict headless preparation, and the Chat-Completions/private-
  continuation path are implemented with targeted local tests. Catalog evidence is
  not an inference entitlement or live-provider claim.
- Selection precedence is exactly: explicit model → configured pool → resumed route
  → saved default → cfg default. An explicit `--model`/`/model <route>` clears a
  configured pool; resumed routed-model metadata represents one route, not a
  reconstructed pool. Interactive dispatch may
  hold a cold route pending while the mounted app runs `prepare_startup()`; prompts
  remain blocked until ready.
- The private continuation extension may be retained for same-route replay only;
  public streams/headless output must not expose it. Trusted child env forwarding
  makes the exact `SLO_OPENROUTER_API_KEY` exception while other secret-shaped
  settings remain filtered. Schedules pass their stored `--model` to ordinary
  headless preparation; no scheduler-specific discovery service exists.

Feature 86 remains **REVISE**. The retained **pre-correction** Step 1 gate is
**5115 passed, 18 E2E-marked deselected, 196 warnings in 373.69s; exit 0** at
`.f86-integration-retry-ucwY1o/full-non-e2e.log`. The deselected set includes
default-disabled live/fixture harness tests; executed OpenRouter evidence is offline
local/mock transport testing and does not verify live credentials, network,
availability, paid inference, or authorization. Black/mypy are waived only as static
gates, not green. The independent rereview remains **REVISE** while concurrent source
corrections address current findings, so this is neither a post-correction final gate
nor an approval. Bounded shipped-body/native-I/O EBADF evidence covers
reaped-launcher reporter health/status without changing workload identity; append
ordering/refusal, OS-process admission and append-wait cancellation are covered.
These are not native interpreter-startup equivalence. See
`docs/implementation/86-openrouter/independent-full-rereview-2026-10-03.md`; dated
reports and their old percentages remain historical, not current status.

## Unbound serialization resolver failure (bounded Feature 86 retry)

CredentialResolver now refuses protected serialization with a fixed safe ValueError
when live lookup raises and no usable OpenRouter capture exists. Event, transcript,
and metadata writers have actual raw-secret red→green coverage in
`test_openrouter_writer_secrecy.py`. Valid captured fallback remains unchanged.
This does not establish operation-owned rotated-key lifetime across scheduled child
artifacts; broader affected-caller verification remains outstanding.

## OpenRouter environment verification race

`OpenRouterAuthenticationService` rechecks the captured environment source/key after
GET `/key` and before exposing verified credentials or catalog handoff. A rotated or
removed environment key invalidates that attempt even when the original GET succeeded.
`test_environment_changes_during_verification_discard_verified_capture` covers both
transitions through the actual resolver/client/temp-store boundary.

## Test state isolation (86.b.1)

`tests/state_isolation.py` redirects HOME and SLO_HOME before test collection;
`tests/conftest.py::isolated_slo_home` then gives each test its own state root.
The fixture also rebinds config fallbacks, imported SLO_HOME copies, Claude CLI
credentials, OAuth locks, and user content paths: changing environment variables
alone cannot repair import-bound paths or config reloads from earlier tests.
AST guards cover the SLO_HOME import registry and path-shaped state overrides.
Resolve HOME-dependent parametrized paths inside test bodies, not at collection.
Installer test wrappers execute pytest's interpreter, never system Python.
Capture-test launchers and their exact-argv containment guards also use
`sys.executable`, including nested writer/reporter children. A fixed developer
virtualenv path can both fail to launch in CI and mask negative tests behind an
unrelated interpreter assertion. Exercise the capture suites with `python -m pytest`
as well as the normal Poetry entrypoint; do not relax their containment checks.

## Catalog cache namespace (86.b.2)

`ModelCatalogStore` exclusively reads/writes `model_catalog_cache.v2.json` and
locks `model_catalog_cache.v2.lock`. Released cache/lock names are never opened,
adopted or repaired. Missing, invalid or other-version provider files fall back
to seed; explicit refresh rebuilds them. Corruption logs one warning without
traceback or file contents. Dead schema-1 readers are removed; an incompatible
future provider-cache shape must use another filename. Mixed-version executable
proof belongs to b5; see `docs/implementation/86b-model-catalog/b2-implementation.md`
for this phase's actual gates and limitations.

## Unknown saved-model resume (86.b.4)

`TyperDispatch._build_session_config` remains the sole resume-selection owner.
Saved direct names require a catalog entry or alias; a provider-prefix match is
not sufficient for reasoning initialization. Unknown saved direct names use the
existing preferred/default resolver, one `session_resume_model_unavailable`
warning and a fixed fallback explanation. Explicit models, configured pool
primaries, known aliases and OpenRouter pending preparation retain precedence.
`SloAgentSession.should_show_startup_notice` lets a fallback launch display the
existing block even with a persisted marker; its tip names the effective model.
No TUI branch or history schema changed. Offline CLI continuation and mounted
replay are covered by the resume/startup tests; released-version proof belongs
to b5. See `docs/implementation/86b-model-catalog/b4-implementation.md`.

## Verification

- Focused session-rate-limit coverage is under
  `tests/agents/slo_agent/test_session_rate_limits.py` and
  `tests/agents/slo_agent/test_session.py`.
- Use `make test` for the non-E2E suite and `make lint` for static checking.

## Detached capture FD ownership (bounded Call 4/4)

Launch/relaunch snapshot the existing allowed child environment before opening
captures. For its literal OpenRouter key, `spawn_env.open_capture_file_append`
returns a named pipe endpoint, not the disk FD. A stdlib-only `capture_writer.py`
process in an independent session owns the append FD and retains possible key
prefixes across reads. EOF flushes unmatched suffixes. Closing the parent endpoint
does not end capture while the workload owns its inherited copy; a daemon waiter
reaps the writer while the parent lives, otherwise OS adoption applies. No raw
spool, credential argv, workflow PID replacement, or environment-forwarding change.
This boundary does not protect separate private history writers. Populated private
history secrecy, complete failure/lifecycle proof, and global gates remain unverified;
see actual Call 4/4 in `docs/implementation/86-openrouter/implementation-log.md`.

Nonpipe process failures now redact captured effective OpenRouter credentials before
logging and terminal status serialization. `test_openrouter_nonpipe_errors.py`
covers environment/store spawn, stdout-read, stderr-read and wait errors. This does
not establish sibling-pump cleanup, detached writer health or relaunch drain order.

## Capture test fault isolation (2026-10-03 bounded retry)

Capture acceptance instrumentation must not propagate RLIMIT_FSIZE into the isolated
store reporter or restore it on the reporter's behalf: that changes the failure's
causal path. The finite test now retains native CPython stdout IO and induces kernel
EBADF only on the same test-owned capture inode, after a successful flush and launcher
reap. Shipped-frame/hash/errno and reporter-completion receipts qualify behavior under
an explicit audited wrapper, not literal native startup equivalence. See
`docs/implementation/86-openrouter/exact-entry-retry-2026-10-03.md`; full Feature 86
acceptance remains incomplete; Plan B and OS contention have later bounded evidence.

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
