# Feature 95 managed-launch reasoning — prerequisite routing and plan

**Verdict: READY for the Code-Test-Review implementation prerequisite only.**
Date: 2026-10-17. No implementation, test execution, agent dispatch, independent code review, or feature acceptance occurred here.

## 1. Authority, scope, and resolved prerequisites

- Git root: `/root/Code/slo-managed-launch-reasoning-20261017`.
- Application cwd: `/root/Code/slo-managed-launch-reasoning-20261017/slo`.
- Required and observed branch: `feature-95-managed-launch-reasoning-20261017`.
- Required base and observed HEAD: `d0e3a756689f2675e5507034d43cd8b272d3c6b8` (merge of dispatch-limit clarification into main). Initial worktree was clean. No fetch, branch switch, or other-worktree inspection was needed.
- Canonical source family, read-only: `/root/Code/specifications/projects/slo/specifications/95-skill-update/launch_workflow_reasoning_parameter` (called **SPEC** below).
- Engineering authority: SPEC/`overview.md`, `95.a.1-managed-launch-reasoning.md`, existing `tasks.md` task **T95.1**, and `task-breakdown-report.md`. Independent specification approval is `verification-report-round2.md`, not the historical first REVISE report or draft headers.
- This dispatch writes only this plan and application-relative `docs/implementation/95-managed-launch-reasoning/todo/accounting.md` (moved there in implementation dispatch 2). No source specification, old report, runtime/test/skill file, external KB, installed package, global environment, or other worktree may be changed.
- Operator explicitly approved `/root/.pyenv/versions/slo-harness/bin/python` **3.11.7**, including Poetry in that environment. The AGENTS environment-name discrepancy is **resolved**, not a blocker.
- Operator explicitly approved standalone orchestrator `gpt-6-astra` / CLI `--reasoning high` because the installed managed schema lacks the field. That authorization is **resolved**, not an instruction to launch anything in this prerequisite and not proof of provider-effective reasoning. No process or provider was inspected here.
- Supplied environment verification is accepted: parent 10800s, child 7200s, Bash 1800s, concurrency 6, batch 8. A Bash export cannot change an already-running parent. No exports to global configuration are proposed.
- No install, live provider call, workload launch/signal, commit, push, PR, publication, or nested agent is authorized here. AUTO does not override this prerequisite-only boundary.

Both SPEC/`implementation-routing-and-plan.md` and `implementation-orchestrator-report.md` were read as **historical zero-dispatch stops**. Their old worktree, three-turn and four-call/one-retry constraints are not current instructions. Prerequisite accounting is preserved in `docs/implementation/95-managed-launch-reasoning/todo/accounting.md` (see its dispatch-2 addendum for current counts): unlimited legitimate revision turns, 20 dispatches/turn, this prerequisite conservatively charged as call 1 against future turn 1, turns started 0 until Code+Test, retries 0. No task-wide dispatch cap is invented.

## 2. Completed reads and routing order

Complete bounded reads covered all twelve SPEC Markdown files, including overview (143 lines), engineering (569), tasks (651), task-breakdown report (263), both verification reports, prerequisite/context/revision/self-check reports, and the two historical implementation stops. These were not reauthored.

Project context read first: application `AGENTS.md` (1–350, 351–700, 701–1013), `CLAUDE.md`, root `RESEARCH.md`, full `docs/RESEARCH.md` (1–220, 221–440, 441–633), supplied home/repository SLO instructions, actual `Makefile`, `pyproject.toml`, `poetry.toml`, test isolation and affected owner contracts. No nested tracked instruction files or CONVENTIONS file were found. The absent repo specifications link does not obstruct the explicit SPEC path.

KB found and consulted read-only at `/root/Code/KnowledgeBase/KB/Welcome.md`, then `slo/README.md` (the index; no separate index.md), `slo/gotchas.md`, and complete `slo/headless-workflow-orchestration.md`. Relevant lessons: test actual lazy construction; reuse import-bound root isolation; clear inherited workflow/watchdog identity; distinguish argv/requested/effective/provider evidence; preserve resource owners. Historical bare-Faux factory, old 4800/3600 timeouts, concurrency 4, and unqualified-detach instructions are not current authority. No new external KB write is allowed by this worktree-only request.

### Selected exact paths and source tiers

All paths in the following table are relative to the **exact absolute prefix** `/root/Code/slo-managed-launch-reasoning-20261017/slo/`; concatenating the prefix and table entry identifies the selected file. Source tier for every entry is **this checkout's repository-authored vendored tree**, explicitly selected by the user and repository skills-maintenance rules. The available-skills manifest and relevant `skills/INDEX.md` entries were checked; no same-name applicable personal override is advertised. Neither the installed pipx skill tree nor unrelated personal Go/TypeScript recipes substitutes for these files. User skills/workflows still have runtime same-name precedence; no runtime discovery change is planned.

| Order / role | Exact selected path | Read/use status |
|---|---|---|
| Shared routing | `skills/engineering/engineering-routing/SKILL.md` | Read fully; preserve route in every handoff |
| Shared ownership | `skills/engineering/engineering-ownership/SKILL.md` | Read fully; single policy/resource owners |
| Shared testing | `skills/engineering/engineering-testing/SKILL.md` | Read fully; evidence categories and failure cutoffs |
| Generic coding | `skills/coding/coding-rules/SKILL.md` | Read fully before language/component recipes |
| Generic declarative | `skills/coding/declarative-method-structure/SKILL.md` | Read fully before Python specialization |
| Generic coverage | `skills/coding/test-verification-policy/SKILL.md` | Read fully; every meaningful branch/boundary |
| Cadence companion | `skills/coding/code-test-loop/SKILL.md` | Read; not a substitute for named workflow; user test-FIRST supersedes implementation-first examples |
| Named workflow | `skills/design-and-analysis/workflows/code-test-review.md` | Read fully; Step 1 → Step 2 → Step 3, no skipped gate |
| Accounting | `skills/design-and-analysis/workflows/SKILL.md` | Read fully; `#workflow-turns-and-limits`, operator overrides retained |
| Python root | `skills/languages/python/python-conventions/SKILL.md` | Read fully before Python component recipes |
| Python types/calls | `skills/languages/python/named-arguments-and-type-hints/SKILL.md` | Read fully |
| Python declarative | `skills/languages/python/declarative-method-structure/SKILL.md` | Read fully |
| Python docs | `skills/languages/python/method-docstrings/SKILL.md` | Read fully |
| Tool component | `skills/languages/python/build-agent-tools/SKILL.md` | Read fully; project specialization below |
| Agent tests | `skills/languages/python/test-graphs-and-agents/SKILL.md` | Read fully; real lazy graph, Faux provider boundary |
| CLI component | `skills/cli/build-cli-modules/SKILL.md` | Read all 1165 lines in three chunks; existing CLI adapter only |
| Breakdown verification | `skills/design-and-analysis/breakdown-feature-spec-to-tasks/SKILL.md` | Read fully; verify existing task, no authoring/JIRA phase |
| Documentation target | `skills/design-and-analysis/headless-orchestration/SKILL.md` | Read all 561 lines; narrow future edits, no launch procedure executed |
| Documentation handoff | `skills/design-and-analysis/update-documentation-after-code-changes/SKILL.md` | Read; P4 synchronization obligation |

The effective implementation handoff order is **project context → shared engineering → generic coding rules → Python root/style → tool/agent-test/CLI components → bounded test-first implementation**. Shared policy does not impose unrelated stacks. Before later independent review load `skills/engineering/engineering-review/SKILL.md`, `skills/languages/python/code-review-rules/SKILL.md`, and `skills/design-and-analysis/review-feature-code/SKILL.md`; before completion load `skills/design-and-analysis/is-the-feature-completed/SKILL.md`. These are selected future phase owners, **not claimed read or executed in this prerequisite**. No review may be called independent if performed by the implementer alone.

### Stack and evidence categories

Production language: Python 3.11; authored guidance: Markdown/JSON examples; commands: existing Bash/Make recipes, no shell production change. Frameworks: Pydantic v2, LangChain Core (lock 0.3.86), LangGraph, Typer, asyncio, filesystem JSON/capture processes. Textual supplies an existing replacement-config caller, not new widget behavior. pytest/pytest-asyncio, FauxChatModel, real tool conversion, CliRunner and httpx.MockTransport are the relevant test mechanisms.

1. Isolated units: canonical schema, nullable precedence, argv, real clamp decisions.
2. Orchestration units: validation cutoff, guards, store-before-spawn, PID publication, unchanged cleanup/abort ordering, immutable defaults.
3. Adapter integration: real Pydantic/LangChain runtime and provider projections, graph-visible tool observations, real Typer parsing/configuration and disposable filesystem stores.
4. Composed offline journey: real owner/bootstrap/lazy graph → captured managed argv → serial real child CLI/session/factory → phase transport stub → real status/inbox/reconciliation and contained capture writers.
5. Surrounding/full regression: retained lifecycle, phase, resume, CLI, model, tool-executor and skill/index suites.

Excluded: Go/TypeScript, SQL/ORM/migration, HTTP routers, DBOS/Celery, new CLI verb/Command class, frontend component work, new provider policy, skill relocation, runtime accounting redesign, native provider/workload E2E. A file named `_e2e.py` is not necessarily live-provider evidence; the prescribed routing file runs under `-m 'not e2e'`.

### Specific-contract specializations (not silent waivers)

- Engineering §7.2/§7.3 and existing `LaunchWorkflowTool` own the factory, JSON-string result/error contract and synchronous pure helper. Do not apply the generic PubMed recipe's DAO-list/empty-list error, all-async helper, DBOS persistence or extra-ignore example. Runtime `extra='forbid'` is the reviewed deliberate tightening; provider conversion does not promise strict extras. Evidence: schema/envelope/graph tests and legacy-call tests.
- Existing `TyperDispatch`/`HeadlessRunner` own CLI parsing, logging and lifecycle. This slice changes only a dispatcher docstring; no HTTP Command stack, Rich output rewrite, new flag, error-handler stack or retry policy. Evidence: real CLI/session/factory plus unchanged headless regressions.
- Existing linear Slo graph and `LLMBuildResult` override unrelated synthesize-node/bare-Faux teaching examples. Preserve real config-backed lazy construction. Evidence: ordered owner/child factory tuples.
- The approved same-class `_launch` extraction retains resource ownership; ~8 substantive lines is a review signal, not permission for mechanical wrappers. User's test-FIRST and <=~50 production lines between relevant tests apply to all languages and override looser cadence examples.

## 3. Task breakdown verification against this base

**Result: retain T95.1 and P0 → P1 → P2 → P3 → P4 → P5.** One cohesive vertical launch boundary remains appropriate, with no task-level implementation parallelism. No new sub-spec or ticket is needed. Shared env/stdio tests must remain serial.

Read-only validation proved:

- All eight reviewed input hashes match the task-breakdown/round2 receipts; tasks hash matches too.
- 22 source fenced-block occurrences represent 21 unique samples; each appears exactly once in the task inventory. All 44 distinct source `test_*` tokens are represented (this is not a test execution count).
- Thirty relevant source/fixture files are byte-unchanged in Git between reviewed commit `e1e3d0ffa72bb00b3c739f6f383931d4feb387fa` and current base. Checked launcher/bootstrap/relaunch/process/DAO/registry/status/notifier/spawn_env/capture_writer/pool/probe, CLI app/dispatcher/headless, session DAO/service, graph/service, factory, canonical catalog DAO, reasoning capabilities, TUI app, root isolation fixtures, and launch/bootstrap/routing/capture/relaunch/process test files.
- `test_managed_launch_reasoning.py` remains absent intentionally; P3 creates it. Existing referenced focused test files and capture fixture owners exist.

### Current owners and differences that matter

| Owner / evidence | Verified current condition and implementation consequence |
|---|---|
| `launch_tool.py:49–61,64–106,116–227,259–379` | Still only brief/cwd/model; model default captured; no reasoning transport or validation handler. Preserve handle-before-spawn and PID-before-capture activation, error/reaping order. This is the actual change owner. |
| `bootstrap.py:76–123` | Sole production factory caller; headless/kill-switch guards precede shared store and tools. Add one snapshot keyword, retain identical store for launch/status. |
| `sessions/service.py:1081–1106,2135–2176,4196–4262` | Pending reasoning can be provisional off; config retains tool objects across rebuilds; real readiness precedes lazy factory. Do not replace `_build_agent` in composed proof or claim live default inheritance. |
| `tui/app.py::_build_replacement_session_config` | Existing method copies active reasoning to new config. Test that actual method, new session identity and bootstrap; no TUI production edit. |
| `typer_dispatch.py:192–203,408–490,606–628` | Preferences precede explicit override; model_copy is nonvalidating; explicit model bypasses pool. Docstring incorrectly says omission always uses seed. |
| `headless.py:182–258,310–377` | Direct construction outside preparation catch; prepared-route failure has safe terminal report; lazy readiness failure occurs after started notification. All three distinct failure contracts still apply. |
| `graph/service.py:490–504`, `agents/base.py:95–111` | Exact factory keywords still match §7.7; consumes `.llm` and `.supports_explicit_caching`. Return LLMBuildResult, not bare Faux. |
| `test_workflow_routing_e2e.py:131–149` | Wrapper still drops handle_store and arbitrary kwargs. Explicitly accept/forward default_reasoning_level AND store; no swallowing `**kw`. Existing patched-agent fixture is surrounding routing evidence, not composed lazy-build proof. |
| `test_bootstrap.py::_make_session` | Still lacks concrete active_reasoning_level; add typed default off before bootstrap starts validating it. |
| `tests/state_isolation.py`, `tests/conftest.py` | Reuse canonical SLO_HOME_BINDINGS/import-time and per-test isolation. SLO_PARENT_PID still not in shared overrides: apply N1 locally, do not widen shared policy. |
| `capture_test_safety.py:25,235–295,558–619` | `_HARNESS_PYTHON = sys.executable` (no hard-coded interpreter). Containment requires writer bootstrap and exact synthetic capture key; retain safety assertions. |
| `relaunch.py:299–329`, `process.py:256–297` | Resume omits reasoning; independent phase task has its own optional pair. No persistence or inherited-phase redesign. |
| `spawn_tool.py` and workflow files | Changed since reviewed commit: defaults now 60 turns/20 calls with explicit overrides and no task-wide dispatch cap. Protected from this feature. Operator unlimited/20 controls this task. |
| Headless skill | Not relocated; current path remains `skills/design-and-analysis/headless-orchestration/SKILL.md`. Only addition since reviewed commit is budget-override prose; preserve it during narrow P4 edits. Shell-first advice and missing explicit reasoning remain to repair. |
| `docs/SLO_HEADLESS_README.md:80,323–344` | Still omits max in table and promises clamp warning. Fix only related guidance; do not infer effective reasoning from launch acknowledgement. |
| Makefile / environment | `make lint` actually checks **src/ and tests/**, despite abbreviated AGENTS table. tests.env is absent; exact safe fallback exists. `make smoke` only runs tests/test_smoke.py, not the full suite; use make test. |

Historical research/AGENTS old 8/6 numbers and old parent-HIGH-unproven prose are historical evidence, not the current operator budget or authorization. Do not edit excluded accounting owners to reconcile unrelated documentation drift. Unrelated installer/version changes in the base are not part of Feature 95.

## 4. Bounded test-FIRST implementation sequence (not executed)

Each checkpoint is inside workflow **Step 1**, not a completed workflow turn or a new ticket. Start with a relevant failing behavioral test; record RED, implement the smallest coherent change (<=~50 production lines before the next relevant test), record GREEN, then run the whole affected module before another unit. Refactors retain prior tests green and characterization coverage first. Never bulk-write P1–P3 and test afterward. Keep individual fixture additions small and executed too; test code is not an excuse to defer verification.

### P1 — Schema, immutable fallback, same-owner transport

1. Add runtime schema/provider projection and invalid-key/type tests. RED against absent field/extra-ignore; add canonical Optional[ReasoningLevel], ConfigDict and fixed per-tool validation JSON. Test all seven exact tokens and reject case/whitespace/bool/number/list/object/unknown keys before reconcile/store/capture/spawn. Verify ToolCall id/status separately from ordinary JSON-string executor behavior.
2. Add default-publication validation and precedence tests. Validate factory default once with TypeAdapter before dependency resolution; explicit off/non-null wins, omission/null inherits, absent/None default omits. Pure class-owned helper only; high then omitted cannot mutate bound medium. Run launch module after each increment.
3. Characterize guard/write/spawn/error ordering before moving the existing nested launch body into same-class `_launch`. Keep bridge a delegation, remove old body in the same refactor, preserve errors/guards and resource helpers. Do not count only net-new lines to hide a large rewrite: bound substantive moved/changed logic and test immediately after each coherent move; do not split resource semantics to satisfy a cosmetic quota.
4. Add helper/spawn argv tests RED, then thread resolved token through `_spawn_and_patch` and `_build_argv`, exactly one conditional pair, no shell. Preserve legacy helper defaults and model-or-default semantics, including empty model string. Run full launch module and guard/capture/PID-conflict/abort cases with non-null reasoning before P2.

### P2 — Bootstrap and real adapter/configuration boundaries

1. Add failing three-input identity/default binding test and concrete mock reasoning; add one bootstrap keyword after existing guards. Verify no-op/idempotence/headless/kill-switch paths.
2. Fix routing factory wrapper with explicit typed reasoning/store forwarding; test explicit reasoning argv and invalid graph observation to the next Faux response with no launch effects.
3. Test real config-backed switch_reasoning_level/switch_model with synthetic credentials; omitted old tool retains initial model/level through lazy rebuild, explicit values win. Use actual replacement-config method and fresh bootstrap; pending OpenRouter captures provisional request and does not acquire a live callback/catalog lookup.
4. Parse captured argv via real CliRunner/dispatcher: explicit high beats saved low; explicit model clears pool. Preserve real child clamp/factory assertions in P3. Add phase medium/None versus parent high and resume non-retention tests. Dispatcher change is docstring only.
5. Run binding/routing/CLI/phase/relaunch modules and full orchestrator partition before P3.

### P3 — Composed offline success, exact failures and abort

Implement engineering §7.7 and §8 / tasks §8.2–8.3 **without weakening** the contracts. Grow fixture and cases serially with local tests, not one untested fixture dump.

1. Establish isolated roots, synthetic credentials, typed factory recorder, real config-backed owner, injected no-signal PID/store boundary and contained capture writer ownership. Prove no global/state/process escape before composing child CLI.
2. Success: owner gpt-5.4/low + saved low invokes managed child gpt-5.4/high; captured argv enters serial real CLI; lazy child factory sees high; one phase medium task/argv uses matching result identities. Assert actual handle PID 0 before spawn and test_pid afterward, exact owner/workflow/session correlation, real started/context_note → phase/context_note → completed/chat_turn inbox, completed status/exit 0, status-tool reconciliation, closed/drained capture endpoints, one spawn, unchanged owner low.
3. Real alternate-model cases: gpt-5.4/high → high; kimi-k3/medium → high; kimi-for-coding/high → off. Raw argv unchanged; factory receives effective canonical result. Legacy no-flag uses saved medium or seed. Explicit OpenRouter remains deferred to child.
4. Add **each** failure with fresh owner/handle: invalid HIGH before all effects; unknown direct model exit 1/exact ValueError with no structured terminal/status/notification then injected dead-PID reconciliation; empty real MockTransport OpenRouter discovery with safe model_preparation failure/status/failed notification but no started/phase/factory; lazy missing Kimi credential with real clamp off, started then exact resolver failure/status, no child factory and no durable attempt lifecycle events. Do not mock build/prepare/readiness/status to make rows pass, and do not change production failure handling.
5. Actual supported abort command uses injected killer/probe/deterministic scheduler and asserts aborted request/handle/registered target. Retain high-valued abort-mid-spawn/capture-close/PID-conflict tests. Run composed module and surrounding lifecycle/CLI/executor/model tests before P4.

### P4 — Narrow guidance and schema/index agreement

Write failing committed-skill tests first: parse managed JSON with actual schema, verify exact keys and canonical tool-vs-CLI naming, snapshot/null/legacy/resume caveats, managed-vs-standalone distinction, phase independence, and named `test_managed_launch_guidance_requires_budget_source_verification` with resolving accounting-owner link.

Then update only headless skill, docs/SLO_HEADLESS_README.md, AGENTS.md detached-workflow section, docs/RESEARCH.md seam, and relevant launcher/bootstrap/dispatcher docstrings. Managed procedure precedes standalone recipes; remove shell fallback from existing agent sessions; include explicit standalone reasoning without claiming a managed handle. Include seven levels, no invented clamp warning, selected-provider resolver, explicit-model-clears-pool, env-before-process creation/no per-call env API, actual returned IDs/status/visualize and capture paths derived from configured root. PID/acknowledgement is not effective reasoning or completion evidence. Preserve abort rules and counters; verify alleged budget stops against active runtime instructions, resolved skills, config and operator override. Distinguish turns, calls/turn, batch, concurrent children/workflows and retries; no copied invented four-call limit.

Do not relocate skills, modify move-only workflow/orchestrator owners, or touch either scheduled-TUI skill. Regenerate index twice with supported command and compare hashes; run skill tests and protected-file checks.

### P5 — Full gates and handoff

Run exact focused, surrounding, Black, mypy, skills/index and full non-E2E gates below after final changes. Preserve complete logs, expanded command/cwd/scoped env, exit codes/counts/exclusions; never silently waive a baseline failure or call unrun tests passing. Audit diff/manifest and R1–R11/AC1–AC8. Future Step 1 READY requires all required tests green; prerequisites READY does not satisfy it. Later independent Step 2 review and fresh Step 3 completion remain mandatory, in that order; use single-dispatch verdict gates when authorized, never chain past a REVISE. Changes after review invalidate affected review/completion evidence.

## 5. Coverage map — obligations, not executed evidence

Full named scenario inventories remain canonical in engineering §8 and tasks §8.1. This map assigns every requirement to bounded checkpoints and observable proof; none is deferred.

| Requirement | AC | Checkpoints / required evidence |
|---|---|---|
| R1 canonical field/no alias | AC1 | P1 actual runtime schema + real convert_to_openai_tool enum/null/default/not-required; no provider strict-extra assertion |
| R2 precedence/off/null/legacy | AC2 | P1 all seven explicit values, absent/null with medium, default omitted/None, high→omitted immutable default; P3 preference/seed |
| R3 bootstrap/config/lazy/replacement | AC3, AC2 | P2 three bound inputs/shared store, real switch/pending/replacement, config extra_tools identity; P3 lazy factory not replaced |
| R4 unchanged canonical transport | AC4, AC5 | P1 single exact pair/old argv-env identities; P2 actual CLI; P3 handle reservation/PID/child config/factory |
| R5 reject before side effects | AC1, AC5 | P1 malformed token/type/unknown-key matrix, invalid build default before dependency binding, fixed no-echo JSON; ToolCall envelope; P2 graph observation; P3 invalid-before-registration |
| R6 existing child admission/clamp | AC4 | P2 preference override and explicit-model pool clearing; P3 three real clamp cases, deferred HTTP-backed OpenRouter admission, zero parent discovery/provider on failure |
| R7 managed lifecycle | AC5 | P3 full success correlation, each distinct C2 presence/absence, contained capture close/drain, supported abort + publication race/conflict/capture regressions |
| R8 compatibility/freshness/resume | AC2, AC6 | P1 legacy supported 3-field calls/default None; P2 stale snapshot/new replacement and no resume flag/new persisted fields; P4 disclosed extras tightening/non-retention |
| R9 independent phase config | AC6 | P2 phase medium and None vs high parent; P3 actual phase task/argv/result identity; P4 brief is instruction text, not runtime setting |
| R10 accurate launch guidance | AC7 | P4 schema-parsed examples, seven-value docs, managed/standalone separation, requested/effective/provider distinction, actual monitoring IDs/root, budget-source test |
| R11 complete verification | AC8 | P1–P5 decision, adapter and composed evidence; full non-E2E/static/skill/index/diff receipts; no weakened assertion, skip or silent waiver |

Historical R12 governed specification-only output/accounting. Current prerequisite fulfills its preservation intent without importing its old implementation prohibition or counters as current task authority. AC7's historical parent disclosure remains historical; current approved gpt-6-astra/high invocation is not provider-effective evidence.

## 6. Safety fixture contract

- Reuse autouse `isolated_slo_home` and `tests/state_isolation.py::SLO_HOME_BINDINGS`; do not copy their binding inventory. Assert default history root equals `<isolated_slo_home>/sessions/history` at source and imported consumers sessions.dao, launch_tool, notifier, cli.headless. Every test write follows symlinks and must remain inside its own root. Use a clean temp cwd; disable plugins locally after the global fixture and clear inherited workflow/session/capture overrides.
- Carry round2 **N1**: locally delete `SLO_PARENT_PID` before owner setup/env recording and assert absent in recorded child env. Do not change shared fixtures/watchdog policy or patch global os.getpid/os.kill. Clear inherited provider keys; use isolated non-expiring synthetic API-key store credentials, plus exact `synthetic-capture-key` OpenRouter env only for the capture contract.
- Keep real config-backed owner/child and factory call signatures. Graph-site typed recorder returns `LLMBuildResult(llm=faux, supports_explicit_caching=False)` and accepts only known owner/recorded child IDs. Record exact `(session_id, model_name, reasoning_level)` order. Delegating real HeadlessRunner initializer may retain instance; no prepare/build/readiness substitution.
- Recording workload spawn returns `os.getpid()` captured once, so real status writer naturally matches. Preserve real WorkflowHandleStore class, wrap constructor to inject local pid_alive and record store, explicitly forward it through factory. Fail fast on unknown positive PID probes and all real workload group signals. Abort injects killer, liveness and scheduler; never signal test PID.
- Use `CaptureLaunchContainment(root=isolated_slo_home, monkeypatch=...)`, register_writer_bootstrap before captures. Keep real capture endpoints/writers and observer; no FD duplication or pretend files. Do not invoke CleanDrainScenario or install irreversible audit hooks in parent. Only approved finite temp-owned helper writers/reporters may execute; no live orchestrator or phase workload process.
- Owner completes before `asyncio.to_thread(CliRunner.invoke)`; exact captured argv[3:] goes to real app. Scoped `patch.dict(os.environ, recorded_env, clear=True)` restores only after thread completion; only worker-thread install/restore signal-handler methods are stubbed. Do not concurrently redirect process-wide env/stdio.
- Phase stub only replaces `SubAgentProcess.run`, records real task/_build_argv and returns matching task/session IDs and answer. Real pool/fleet/notifier/status remain. Empty capture files in this composition are endpoint-lifecycle evidence, not native child stdout evidence.
- Finally close outstanding endpoints via to_thread; bounded retained writer Popen.wait(timeout=25), ownership PID set comparison, zero success returncode. No arbitrary waitpid/kill/broad cleanup on timeout. Drain retained pools on owning loops; await catalog shutdown/reset even after early direct-build failure. Child HTTP client closes in child loop before restoration. Block default network transports; only prescribed MockTransport endpoints accepted.
- Keep suite-wide no-real-terminal fixture and SLO_AUTO_VISUALIZE=0. No binary/system-path mutation or symlink to writable real tool. If command stubs are involved in full suite, verify `dpkg -V coreutils` prints nothing afterward; an anomaly stops work. Inspect risky fixtures before execution and ask if safety cannot be established. No new runtime safety API to accommodate tests.

## 7. Exact verification commands for later implementation

**Not run in this prerequisite.** Run from the application cwd only. This shell setup is command-local, not a profile/global environment change and not an attempt to reconfigure the parent. Bare Poetry selected base Python here; explicit VIRTUAL_ENV/PATH proved the approved interpreter. Use this setup before each gate shell (or an enclosing subshell):

```bash
cd /root/Code/slo-managed-launch-reasoning-20261017/slo
export VIRTUAL_ENV=/root/.pyenv/versions/slo-harness
export PATH="$VIRTUAL_ENV/bin:$PATH"
export PYTHONDONTWRITEBYTECODE=1
poetry run python -I -c 'import sys; print(sys.executable); print(sys.version.split()[0]); assert sys.prefix == "/root/.pyenv/versions/slo-harness"'
if [ -r ./environments/tests.env ]; then
  set -a; . ./environments/tests.env; set +a
else
  export SLO_ENV=test SLO_ROOT_DIR="$PWD" SLO_APP_DIR="$PWD" SLO_APP_NAME=slo SLO_LOG_FORMAT=text SLO_DEFAULT_MODEL_NAME=gpt-5.4 SLO_AUTO_VISUALIZE=0 SLO_ANTHROPIC_API_KEY=ci-placeholder-tests-are-fully-mocked COLUMNS=120 LINES=40
fi
export PYTHONPATH="$PWD"
```

Do not source development.env. No `poetry install`, pyenv installation, installer, live E2E or global config correction. Inspect environment file if one appears later instead of trusting an unreviewed replacement. Test-local fixtures must remove inherited credentials and state; the Make fallback is not a substitute for isolation.

Small-unit RED/GREEN commands use the exact new node being authored, followed by its module. Concrete module/partition commands:

```bash
# P1, repeated after each bounded production increment
poetry run pytest -m 'not e2e' tests/agents/slo_agent/orchestrator/test_launch_tool.py
# P2
poetry run pytest -m 'not e2e' tests/agents/slo_agent/orchestrator/test_bootstrap.py tests/agents/slo_agent/orchestrator/test_workflow_routing_e2e.py tests/cli/test_typer_dispatch.py tests/agents/slo_agent/orchestrator/test_process.py tests/agents/slo_agent/orchestrator/test_relaunch.py
# P3 after the new test module exists; grow one case at a time before this whole module
poetry run pytest -m 'not e2e' tests/agents/slo_agent/orchestrator/test_managed_launch_reasoning.py
# Surrounding lifecycle partition, after safety review
poetry run pytest -m 'not e2e' tests/agents/slo_agent/orchestrator/
```

Final specified focused gate (includes new composed test):

```bash
PYTHONPATH="$PWD" poetry run pytest -m "not e2e" \
  tests/agents/slo_agent/orchestrator/test_launch_tool.py \
  tests/agents/slo_agent/orchestrator/test_bootstrap.py \
  tests/agents/slo_agent/orchestrator/test_managed_launch_reasoning.py \
  tests/agents/slo_agent/orchestrator/test_workflow_routing_e2e.py \
  tests/agents/slo_agent/orchestrator/test_process.py \
  tests/agents/slo_agent/orchestrator/test_relaunch.py \
  tests/cli/test_typer_dispatch.py tests/cli/test_headless.py \
  tests/agents/test_reasoning_capabilities.py \
  tests/agents/slo_agent/tool_execution/test_executors.py
```

Static/docs/index/full gates (retain all outputs and nonzero statuses):

```bash
poetry run black --check src/agents/slo_agent/orchestrator/launch_tool.py src/agents/slo_agent/orchestrator/bootstrap.py src/cli/typer_dispatch.py tests/agents/slo_agent/orchestrator/ tests/cli/test_typer_dispatch.py tests/cli/test_headless.py tests/agents/skills/test_committed_skills.py
make lint
# make lint = poetry run mypy src/ tests/
make refresh-skills
first_index_sha=$(sha256sum skills/INDEX.md | cut -d ' ' -f 1)
make refresh-skills
second_index_sha=$(sha256sum skills/INDEX.md | cut -d ' ' -f 1)
test "$first_index_sha" = "$second_index_sha"
PYTHONPATH="$PWD" poetry run pytest -m "not e2e" tests/agents/skills/test_committed_skills.py tests/agents/skills/test_refresh_skills.py tests/agents/skills/test_orchestrator_limit_rules.py tests/agents/skills/test_workflow_turn_rules.py
make test
# Conditional after any command-stubbing suite; empty output required
# dpkg -V coreutils
git diff --check
git diff --name-status d0e3a756689f2675e5507034d43cd8b272d3c6b8
git status --short
```

Do not use `make format` across unrelated files to disguise baseline Black failures. No skip/waiver is preapproved. Retain logs as later authorized evidence under this feature's docs/implementation directory, with distinct command/exit receipts; do not let `tee` or a later command hide a failed gate. Final non-E2E must run after the last code/test/guidance edit. No tests/static/index generation were run here, so there is no baseline-green claim.

## 8. Allowed implementation manifest and protected bytes

This prerequisite changes only the two requested Markdown artifacts. Later implementation scope remains tasks §7.2:

- Production behavior: `src/agents/slo_agent/orchestrator/launch_tool.py`, `bootstrap.py` only.
- Production documentation only: `src/cli/typer_dispatch.py::run_headless`.
- Existing test modifications: orchestrator `test_launch_tool.py`, `test_bootstrap.py`, `test_workflow_routing_e2e.py`, `test_relaunch.py`, `test_process.py`; CLI `test_typer_dispatch.py`; skills `test_committed_skills.py`.
- New test: `tests/agents/slo_agent/orchestrator/test_managed_launch_reasoning.py`.
- Guidance: `docs/SLO_HEADLESS_README.md`, `AGENTS.md`, `docs/RESEARCH.md`, `skills/design-and-analysis/headless-orchestration/SKILL.md`; generated `skills/INDEX.md` only via generator.
- No production change to graph/session/catalog/credentials/CLI parsing/headless/phase/relaunch/registry/status/notifier/capture/TUI; no new runtime module, migration, retry or persistent reasoning field. Additional changes need explicit scope reconciliation, not a silent manifest expansion.

### Protected source family SHA-256

All names below are relative to SPEC. These include source specs, reviewed reports, tasks and historical stops; all must remain byte-identical.

| File | SHA-256 |
|---|---|
| `95.a.1-managed-launch-reasoning.md` | `70b37fa2c4bf15de4a3085ab7e18755a3c848df81abb0d7630c3d8319c6d750a` |
| `overview.md` | `38a0eab3831e72c17c600247c8262692872da5eae572615c88aa0f4200cae436` |
| `tasks.md` | `5631151c6aa6f1ae3480203dd551b29be5ad6b0f97e8418be151941401879800` |
| `task-breakdown-report.md` | `f7506aa2e91a4025711f1104579d3ace16b15b487ac895e31e8d0b84d4a3f7dd` |
| `author-self-check.md` | `e5c7a8fdee560bab433bdfac150e3026336c56ca263f6c6dfc11b6e24d2b11a0` |
| `context-updates.md` | `e42ce2b65293e8fe46b1d18566fbe4c0717e6069b10077d4383a92fa868a18ee` |
| `prerequisite-context.md` | `a860c853d7021f5ca6edb12585adee196f291cd769a32e391f22b8a4d08b05a6` |
| `revision-evidence.md` | `66b36b5a370e66effafd22fc5b6bb38c08a2c737c3b1e46242b5fa95f341b1fd` |
| `verification-report.md` | `3603a4ddc7de3e44f59beff4b7f2cd963fb8973f04a0ab8e4fea28ce370c4f1d` |
| `verification-report-round2.md` | `314793fcaa62d74d6b5eef598d6f40b03ea4792d78298d55313f6d315e11ff28` |
| `implementation-routing-and-plan.md` | `946210000a1e6fddbc6b69840a8ce249d8afd3de15b60bb316c563e102d02dea` |
| `implementation-orchestrator-report.md` | `a72a6d5dd5d2e6d0901f10c8dfd8b5f6cad64f84fdc163303c7bba2a0e524087` |

### Protected repository policy SHA-256

Paths below are application-relative; no relocation or edits allowed in this slice.

| File | SHA-256 |
|---|---|
| `skills/tui/tui-scheduled-workflows/SKILL.md` | `ca00e36826f5e12d986df4079c3a6f10081b1a0cd92a174ab9b77d68290286de` |
| `skills/tui/tui-scheduled-operations/SKILL.md` | `9315d9d5bdd8a32cfed188bae4ff8edd86bf5d5023654cf46343897e6215a869` |
| `skills/design-and-analysis/orchestrator/SKILL.md` | `d8b280b7016ec038685edfed443eaa81b1d988d714893db034ea1ba3d9809cc2` |
| `skills/design-and-analysis/workflows/SKILL.md` | `93a43aff96b2019435f108cb65acee3e0217cf994eeb0970f7685c2f25bb0846` |
| `skills/design-and-analysis/workflows/code-test-review.md` | `88a900554eb3d79879e4132e785b927aa686dce1038c93dab2bc954204551034` |
| `skills/design-and-analysis/workflows/gitlab-code-test-review.md` | `031c6089bc642f62929e58d8a76e22d7e934fb65d975f1b2a8f82a4c17b1c777` |
| `skills/design-and-analysis/workflows/specification-development.md` | `eb7aea9d31a6092f1987cb787e996a8fd359227d0f18bf94c054bc91bdeeeafd` |

Exact read-only preservation check, reusable after each phase:

```bash
/root/.pyenv/versions/slo-harness/bin/python -I - <<'PY'
from pathlib import Path
import hashlib
import re
app = Path('/root/Code/slo-managed-launch-reasoning-20261017/slo')
spec = Path('/root/Code/specifications/projects/slo/specifications/95-skill-update/launch_workflow_reasoning_parameter')
plan = (app / 'docs/implementation/95-managed-launch-reasoning/routing-and-plan.md').read_text()
rows = re.findall(r'^\| `([^`]+)` \| `([0-9a-f]{64})` \|$', plan, re.M)
assert len(rows) == 19
for name, expected in rows:
    path = (app if name.startswith('skills/') else spec) / name
    assert hashlib.sha256(path.read_bytes()).hexdigest() == expected, str(path)
print('PASS: 19 protected artifacts unchanged')
PY
```

## 9. Actual prerequisite evidence and findings

Executed only read-only source/doc/Git/hash checks and isolated standard-library interpreter/document probes before writing these two artifacts:

- `pwd; git rev-parse --show-toplevel; git branch --show-current; git rev-parse HEAD; git status --short` verified exact scope/base/clean start.
- `git diff e1e3d0ffa72bb00b3c739f6f383931d4feb387fa HEAD --stat -- src tests skills Makefile pyproject.toml` identified budget-policy and unrelated installer/version changes. A read-only Python/std-library loop ran `git diff --quiet` on the thirty files listed above; all unchanged, exit 0.
- Complete input fingerprint/sample check returned exit 0: `PASS: 8 reviewed hashes, tasks hash, 22 sample occurrences/21 unique single-owner samples, 44 test tokens`; `PASS: 30 affected/adjacent source-fixture files unchanged between reviewed commit and current base; proposed new test absent`.
- `command -v python; pyenv which python` resolved shim then approved slo-harness. Direct approved interpreter reported 3.11.7. Bare `poetry env info` reported virtualenv NA/base 3.11.7; bare `poetry run python` used `/root/.pyenv/versions/3.11.7/bin/python`. Command-local `VIRTUAL_ENV=/root/.pyenv/versions/slo-harness PATH=/root/.pyenv/versions/slo-harness/bin:$PATH poetry run python -I ...` reported approved executable, version 3.11.7 and prefix. **Resolved invocation detail, not an environment-approval blocker.**
- `environments/tests.env` is absent; a combined inspection ended exit 1 at `cat: environments/tests.env: No such file or directory`. Actual Makefile fallback was read and is reproduced above. No environment file was created.
- Initial parallel-wrapper attempt produced four missing-path validation errors and two current-directory listings. Ordinary bounded reads succeeded afterward. Tool-input errors are not workflow dispatches/retries or failed product tests.
- No pytest, Black, mypy, index refresh, full regression, application inference, live process probe, signal or agent launch ran. Document integrity is not runtime acceptance.

**Blockers remaining for this prerequisite: none.** Implementation risks to verify, not preemptively waived gates: safe serial composed fixture/lifetime, real distinct startup failures, repository-wide static/full-suite status unknown, snapshot/resume limitations, provider projection vs runtime extras, and protected-file preservation. If implementation exposes a substantive contract conflict, stop and return it for authorized reconciliation rather than reauthoring protected specs or broadening production owners.

**Handoff:** retain this route, untouched source tasks, hashes, safety contract and accounting. Next authorized work is Step 1 test-FIRST P1; this response stops before it. READY here is only prerequisite readiness, never feature acceptance.
