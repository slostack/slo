# Frozen routing record — Feature 94 Herdr

Status: **READY for prerequisite handoff**, 2026-10-17. Pass this file unchanged to code/test, independent full-scope review and fresh completion phases. It selects conventions and evidence; it does not authorize implementation in this read-only assignment. Scope-plan.md supplies the complete T1–T6 graph and acceptance checklist. A changed requirement or material convention conflict requires an explicit amended record, not silent drift.

## Resolution and authority

Effective order: **project/user context → shared ownership/testing → generic coding rules → Python root/style → scoped DAO/service/test/product CLI/Textual guidance → bounded implementation and verification**. Specific feature/project rules override generic examples on their point; unrelated examples add no framework dependency. Current user requires test-first in every language, no regressions/all gates, no unrelated TUI work. No implementation, agents, commits, global prefs or other-worktree modifications in this assignment.

Read full current-checkout AGENTS.md (1–510/511–1013), CLAUDE.md (1–65), docs/RESEARCH.md (1–633), root RESEARCH.md; supplied SLO.md/global SLO rules apply. Read Makefile, .python-version, pyproject dependency/test/static declarations and existing tests/state_isolation.py + root conftest isolation/window guards. No root/two-level CONVENTIONS.md found. Current Makefile overrides stale orientation summaries: smoke runs only tests/test_smoke.py; lint checks src AND tests. Exact approved feature contract permits existing `slo-harness` Python 3.11.7, not installation of absent `slo` alias.

### Runtime manifest versus committed source

Actual worker and parent SLO_SKILLS_DIR: `/root/.local/share/pipx/venvs/slo/lib/python3.11/site-packages/skills` (**I**). Requested committed development root: `/root/Code/slo-94-herdr-integration/slo/skills` (**C**). No environment variable was changed.

Inspected `config/cfg.py::_resolve_skills_location`: nonempty SLO_SKILLS_DIR wins verbatim; otherwise populated `$SLO_HOME/skills`; otherwise package-adjacent skills. Inspected `src/agents/slo_agent/skills/service.py::SkillsLoader.load_merged`: bundled root → user skills → user workflows, keyed by frontmatter name, later tier replaces same name. Project instructions are context, not a fourth automatically scanned tier. Runtime supplied available-skills manifest and complete C/INDEX.md were consulted. I/INDEX.md is byte-identical to C/INDEX.md. The manifest includes unrelated personal Go/TypeScript/presentation overrides; these are not Python requirements.

Parent SLO_HOME is `/root/.slo`; SLO_USER_SKILLS_DIR/SLO_USER_WORKFLOWS_DIR absent. `/root/.slo/user_skills` exists; `/root/.slo/user_workflows` is absent. Read-only name scan found **no selected-name personal override** among the selected core/Python/product CLI/TUI recipes. All 20 compared core files (index, both workflows and 17 shared/language/component recipes) are byte-identical between C and I. Therefore committed exact files were read per user request without pretending the runtime override points to C or silently substituting different guidance. No skill/index generation or global mutation occurred.

## Selected absolute paths and scope

Every path below is explicit; tier **C** means user-requested committed project copy (byte-identical runtime I counterpart for the compared core set). Source-specific rules and named workflow are not replaced with similarly named skills.

### Workflow/shared/generic (C)

- `/root/Code/slo-94-herdr-integration/slo/skills/design-and-analysis/workflows/code-test-review.md` — full code/test → review → completion, not cadence alone.
- `/root/Code/slo-94-herdr-integration/slo/skills/design-and-analysis/workflows/SKILL.md` — turns/dispatches/confirmation/handoffs.
- `/root/Code/slo-94-herdr-integration/slo/skills/engineering/engineering-routing/SKILL.md`
- `/root/Code/slo-94-herdr-integration/slo/skills/engineering/engineering-ownership/SKILL.md`
- `/root/Code/slo-94-herdr-integration/slo/skills/engineering/engineering-testing/SKILL.md`
- `/root/Code/slo-94-herdr-integration/slo/skills/coding/coding-rules/SKILL.md`
- `/root/Code/slo-94-herdr-integration/slo/skills/coding/code-test-loop/SKILL.md`
- `/root/Code/slo-94-herdr-integration/slo/skills/coding/declarative-method-structure/SKILL.md`
- `/root/Code/slo-94-herdr-integration/slo/skills/coding/code-design-principles/SKILL.md`
- `/root/Code/slo-94-herdr-integration/slo/skills/coding/naming-and-clarity/SKILL.md`
- `/root/Code/slo-94-herdr-integration/slo/skills/coding/test-verification-policy/SKILL.md`
- `/root/Code/slo-94-herdr-integration/slo/skills/coding/solution-design/SKILL.md` — existing approved ownership/seam guidance only; no new design exercise, design.md, alternatives or agents under this bounded request.
- `/root/Code/slo-94-herdr-integration/slo/skills/design-and-analysis/locate-knowledge-base/SKILL.md` — optional KB resolution; found, read-only.

### Python/component/framework (C)

- `/root/Code/slo-94-herdr-integration/slo/skills/languages/python/python-conventions/SKILL.md`
- `/root/Code/slo-94-herdr-integration/slo/skills/languages/python/named-arguments-and-type-hints/SKILL.md`
- `/root/Code/slo-94-herdr-integration/slo/skills/languages/python/method-docstrings/SKILL.md`
- `/root/Code/slo-94-herdr-integration/slo/skills/languages/python/declarative-method-structure/SKILL.md`
- `/root/Code/slo-94-herdr-integration/slo/skills/languages/python/application-structure/SKILL.md` — dependency/config/model/DAO/service ownership only; orders-service SQL/web deployment examples excluded.
- `/root/Code/slo-94-herdr-integration/slo/skills/languages/python/build-domain-features/SKILL.md` — typed Pydantic field descriptions/validation/transient boundary role; no SQL entity/CRUD/table/migration added. Read full including historical examples; feature schemas are frozen extra-forbid, not the sample extra-ignore/ORM pattern.
- `/root/Code/slo-94-herdr-integration/slo/skills/languages/python/build-application-services/SKILL.md` — named delegation and ownership; Herdr is the specified support adapter, not a new src/services application workflow. Preserve build/start/publish/close/save/load and existing app-service methods, not manufactured invoke wrappers.
- `/root/Code/slo-94-herdr-integration/slo/skills/languages/python/test-graphs-and-agents/SKILL.md` — controlled model boundary/test organization; actual repository Faux model is authoritative. Do not add the example PubMed synthesis node or TypedDict graph.
- `/root/Code/slo-94-herdr-integration/slo/skills/languages/python/switch-environments-and-run-tests/SKILL.md` — test-environment separation; actual tests.env/Makefile fallback wins over orders DB/test.env/loadenv/profile examples.
- `/root/Code/slo-94-herdr-integration/slo/skills/cli/build-typer-cli-apps/SKILL.md` — thin parse surface, dispatch assembly, CliRunner and log isolation.
- `/root/Code/slo-94-herdr-integration/slo/skills/tui/build-textual-tuis/SKILL.md` — app/router/renderer/session boundaries, tracked tasks and pilot tests; no styling scope.

Python specialized ~8 substantive-line signal is a cohesion review prompt, not mechanical splitting. Keep no-await admission/registration atomic sections intact. Project/spec explicit instance-owned lifetimes and extracted compatibility identity functions specialize the generic classmethod guidance. DAO validators own structural invariants; store security checks, temporal generation/admission and filesystem policy remain with their specified owners. Private error input/repr/traceback must never leak despite generic logging examples. Framework-required positional subprocess argv/callback task/gather/zip calls are documented exceptions to keyword style. Pydantic fields use Field descriptions and private repr=False; immutable nested tuples, not mutable aliases.

### Deferred phase-specific loading (not claimed reviewed now)

Independent reviewer must additionally read C `engineering/engineering-review/SKILL.md`, `languages/python/code-review-rules/SKILL.md`, `design-and-analysis/review-feature-code/SKILL.md`. Completion assessor reads C `design-and-analysis/is-the-feature-completed/SKILL.md`. Those phases consume this unchanged record and full B/C/D/tasks, not just a prior verdict. No independent code review is claimed by this prerequisite.

## Languages/frameworks and test categories

Python >=3.11,<3.12; actual pyenv slo-harness 3.11.7. asyncio task/thread/subprocess lifetime; Pydantic 2; Typer 0.26–0.27 parse surface; Textual 8/Rich; existing LangChain/LangGraph with `src/agents/providers/faux.py::FauxChatModel`. Bash/Make only existing test environment orchestration and temp fake executables; Markdown documentation. No Go/TS/Vue code.

| Category | Required evidence |
|---|---|
| Pure unit | immutable DAOs, state/reason validation, numeric projection/formatter, identity, safe argv, exact token boundaries |
| Orchestration unit | consumer-protocol recording stores/reporters, deterministic Events, exact calls/arguments/order and forbidden calls; save/revision/release/currentness, failure/cancel cutoffs |
| Adapter integration | actual temp-owned filesystem, AtomicFileWriter outcomes, separate advisory locks/two processes, fake executable argv/pipe bounds/lock wait/spawn/reap/crash boundaries |
| Composed offline | actual session with Faux, mounted Textual/pilot/PromptInput, actual inbox lane bytes, typed attached/detached effects, two OS-process CLI restore, complete 64-case matrix |
| Live compatibility/visual | separately authorized disposable named Herdr session/version/restart/wire/TTL/wait/release/pane placement and actual viewer paint; never substitute fake evidence |

No SQLAlchemy/PostgreSQL/Redis/NATS/Docker/ClickHouse fixtures, HTTP controllers/envelopes, DBOS/Celery jobs, new graph/tool/client, operator Make→Command scaffolding, JWT/password conventions, browser/Vue/Playwright, installation/deployment, direct sockets or upstream Herdr changes. Existing scheduler change is narrow environment filtering, not scheduler redesign. Database-backed test-app/domain recipes are not selected as isolated orchestration guidance. No new CLI verb/Command class, so operator command-class/module scaffolding is excluded in favor of explicit product Typer guidance.

## Project/KB contracts

Read `/root/Code/KnowledgeBase/KB/Welcome.md`, actual `slo/README.md` (no index.md), `slo/gotchas.md`, `slo/skills-and-kb.md`, `slo/tui-cli-session.md`, `slo/headless-workflow-orchestration.md`. For safe requested runtime inspection read `os/ROLE.md`, `os/README.md`, `os/workloads-services-resources.md`. No KB or machine live-state change. Historical macOS paths, old session.py/tree.json, old timeout/concurrency values and unconditional wiki publication advice are not current authority. Current sessions modules/Makefile/config/spec govern. KB specifically warns against name-derived history directories, global SLO_SESSION_ID leakage into TUI/new, Pydantic TYPE_CHECKING-only field imports, real model factory construction in tests, bound-method identity traps and improper terminal spawning.

Preserve CLI→TUI→session dependency direction. No CLI/Textual imports into Herdr support. Existing usage snapshot is sole accounting source; exact configured pool/effective reasoning is private restore policy, routed fallback affects numeric display only. No history migration. Reuse AtomicFileWriter unchanged; move formatter/identity once with compatibility delegates/import. One session-owned reporter/transport/viewer; one workflow raw-result parser; no duplicate owners or generic process framework.

Faux guidance: queue prebuilt AIMessage responses, including final no-tool response; bind_tools clones and retains scripts; underrun is a test failure. Config-backed session tests inject factory at actual use boundary or prebuilt agent for orchestration; restore eligibility tests cannot accidentally use injected-agent ineligibility and claim native restore coverage. No real provider credentials/calls. Keep real terminal guard and add independent fake-only Herdr spawn capability before activation tests. All test writes and fake captures/barriers resolve inside that test root before writes; reject links/traversal/substitution; never symlink system tools. Only test-owned processes may be killed/reaped. Full safety contract in B default-suite isolation prerequisite and scope-plan.md.

## Exact verification commands (future implementation; not rerun here)

CWD `/root/Code/slo-94-herdr-integration/slo`. Verify first:

```bash
pyenv which python
python --version
make test-env
```

Expected approved interpreter `/root/.pyenv/versions/slo-harness/bin/python`, Python 3.11.7; current test-env is fallback. For targeted pytest use the reviewed existing Makefile fallback in a subprocess shell, not global preferences/profile. Existing fallback values are:

```bash
export SLO_ENV=test SLO_ROOT_DIR="$PWD" SLO_APP_DIR="$PWD" SLO_APP_NAME=slo SLO_LOG_FORMAT=text SLO_DEFAULT_MODEL_NAME=gpt-5.4 SLO_AUTO_VISUALIZE=0 SLO_ANTHROPIC_API_KEY=ci-placeholder-tests-are-fully-mocked COLUMNS=120 LINES=40
export SLO_HERDR_DISABLED=1
```

T1 adds pre-import/per-test HERDR stripping and T2 fake-only spawn guard. An env flag alone is not test permission. Do not source development.env or print full environment. Use safe tests.env instead only after checking it is the intended isolated test contract.

Exact chapter gates retained (B26/C31/D09 attachments; overlapping full-suite runs may share one final unchanged-snapshot receipt rather than needlessly repeating long runs):

```bash
PYTHONPATH="$PWD" poetry run pytest -m 'not e2e' tests/agents/slo_agent/herdr tests/agents/slo_agent/test_token_format.py tests/tui/test_usage_status_bar.py
poetry run black --check src/agents/slo_agent/herdr src/agents/slo_agent/sessions/token_format.py tests/agents/slo_agent/herdr
PYTHONPATH="$PWD" poetry run pytest -m 'not e2e' tests/agents/slo_agent/herdr tests/cli/test_herdr_restore.py tests/tui/test_herdr_session_lifecycle.py
poetry run black --check src/agents/slo_agent/herdr src/agents/slo_agent/sessions/service.py src/cli/app.py src/cli/typer_dispatch.py src/cli/headless.py src/tui/app.py
PYTHONPATH="$PWD" poetry run pytest -m 'not e2e' tests/agents/slo_agent/herdr tests/tui/test_herdr_visualizer.py tests/tui/test_visualizer_launcher.py tests/tui/workflows tests/tui/test_workflow_receive_path.py tests/integration/test_herdr_full_flow.py
poetry run black --check src/agents/slo_agent/herdr src/tui/visualizer_launcher.py src/tui/workflows/renderer.py tests/integration/test_herdr_full_flow.py
make test
make smoke
make lint
dpkg -V coreutils
```

Additional surrounding regression command:

```bash
PYTHONPATH="$PWD" poetry run pytest -m 'not e2e' tests/agents/slo_agent/history/test_atomic_io.py tests/agents/slo_agent/test_session_usage.py tests/agents/slo_agent/orchestrator/test_spawn_env.py tests/agents/slo_agent/orchestrator/test_bootstrap.py tests/cli/test_headless_request.py tests/cli/test_headless.py tests/cli/test_app.py tests/cli/test_typer_dispatch.py tests/scheduling/test_runtime_helpers.py tests/tui/test_app.py tests/tui/test_usage_status_bar.py tests/tui/test_visualizer_launcher.py tests/tui/test_workflow_visualizer_loader.py tests/tui/workflows tests/tui/test_workflow_receive_path.py
```

Run task-specific exact lists from H/tasks.md before dependent tasks, plus Black --check on every changed Python file (including new reader/identity and modified tests not covered by chapter fences). Never blanket format unrelated TUI code. Record cwd, safe environment variant, command, exit, pass/fail/deselection counts and full output; no hidden skips/assertion weakening. Fresh full non-E2E and required static gates before completion; baseline attribution is not a waiver. `make smoke` does not replace `make test`. Baseline test/smoke/static receipts remain unchanged and are not post-implementation proof.

## Runtime verification and counters

Read-only `/proc/2689048/cmdline` allowlist verified `--model gpt-6-astra`, `--session-id de61c798-b11e-4f0a-b8c5-008a25d65e98`, `--orchestrator`; no --reasoning/--reasoning-level. Parent cwd `/root/Code/slo-workflow-budget-overrides/slo`. Parent environment has neither timeout override nor child legacy alias; source config in both relevant checkouts defaults parent 10800s, child 7200s (parent > child). This is source/default evidence, not live memory introspection. Exporting in a Bash child cannot change the running parent's environment; no such change attempted.

Only allowlisted identity/model/reasoning fields of attributable session.json/orchestrator.json/orchestrator_context.json were examined; session.json confirms exact ID/model, none of those allowlisted fields establishes effective reasoning. Source dispatch loads preferences absent an explicit CLI override; current global prefs would not prove startup capture. Therefore effective reasoning remains **unverified**, not assumed high and not a read/plan blocker. No transcript, raw prompt, credential or global config was dumped; no global prefs read/changed.

Supplied effective accounting preserved: turn 1 active; started 1/completed 0/historical partial 0; **dispatch 3 consumed, 17 remaining of 20**, unlimited workflow turns; retries consumed 0. This worker spawned none. Local tool corrections/read chunking are not dispatch retries or completed review turns. Future gates use single review dispatches, preserve consumed counts and actual runtime limits; no nested orchestration/renaming/reset to bypass them.
