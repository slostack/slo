# Feature 96 ChatTranscript — current implementation handoff

## CURRENT: Dispatch 13 — READY for two assigned scroll proofs only

Read [precise-scroll-proofs.md](precise-scroll-proofs.md) for requirement-level
mapping and hook validity. Real unequal native x/y completion is now observed
with covering callbacks released before/after native final completion. Existing
Textual post_display_hook observes every composed display frame during public-y
interruption; no old endpoint appears. These are headless compositor frames,
not physical terminal/manual observations. New proofs: 3 passing cases, repeated
three times; bounded relevant gate: **158 passed, 23 warnings, exit 0**.
No production changes, full-suite rerun, mypy check/waiver or manual smoke.
Prior full 8502/19 and unwaived 292-error static baseline remain historical.
Manual evidence and parent-owned independent review/completion still block
whole-feature acceptance. No feature approval claim.

## Historical: Dispatch 12 — code closure, full default green; acceptance BLOCKED

Read [dispatch12.md](dispatch12.md) for the final acceptance map, exact proof
conflict and command receipts. Actual mid-motion End→PageUp exposed a fractional
animated-target completion bug, now fixed. Hidden partial-prepend/theme/size and
pin/show ordering evidence expanded. Full default pytest (no extra exclusions):
**8502 passed, 19 deselected, 482 warnings; exit 0**. Exact changed Python Black:
50 unchanged. Full mypy: identical normalized **292 baseline errors**, unwaived.
Resource tests included; owner map reconciled. Unequal-axis/every-paint proof and
manual harness conflict remain explicit acceptance blockers. Independent review
and completion remain parent-owned; no approval claim.

## Historical: Dispatch 10 — partial matrix closure, NOT READY

Read [dispatch10.md](dispatch10.md) for the explicit case-to-evidence table and
remaining exact timing/hidden/subscriber gaps. Added 99 navigation/replay/lifecycle
cases and fixed synchronous-notice anchor settlement before mount layout. Final
focused partition: **221 passed, 27 warnings, exit 0**. New tests/component Black
and diff checks pass; scoped mypy has 10 imported-source errors, not green.
No full suite, nested agents, commit or push. No environment blocker established;
the assigned complete matrix remains unfinished. Dispatch9 closures are retained.

## Historical: Dispatch 9 — READY only for four assigned integration gaps

Read [dispatch9.md](dispatch9.md) for exact test names, commands and results.
Injected SessionFactory `/new` → real prompt → persistence, both injected
visualizer routes (success/fallback/deduplication), exact mounted-hydration →
startup → subscription order, and hide/show with retained progress-modal focus
and usable prompt are now covered. Production required no changes. Final affected
partition: **75 passed, 7 warnings, exit 0**. New-test Black and scoped mypy pass;
this does not waive the repository static baseline.

All other Dispatch7/8 gaps remain pending: native navigation/deferred/two-axis and
hidden geometry matrix; mixed/empty replay, partial older insertion with active
tool, concurrent lifecycle and active inference/tool-result subscriber journeys;
owner-map documentation cleanup; full non-E2E/resource/static final gates, manual
smoke and independent review/completion. Full suite deliberately not run. Feature
96 remains incomplete; this bounded READY is not whole-feature acceptance.

## Historical: Dispatch 8 — INCOMPLETE

Read [dispatch8.md](dispatch8.md), then [dispatch7.md](dispatch7.md) for the exact
remaining matrix. Ancestor-hidden native admission now has a failing-then-passing
mounted regression and an owner guard; focused component/follow/snapshot partition
passes 50 tests. Core navigation, replay/lifecycle and injected app journeys remain
unfinished. Full default pytest has not run; the exact 292-error mypy baseline is
still unwaived. No acceptance or independent-review claim.

## Historical: Dispatch 6 — NOT READY; affected regressions and introduced static errors closed

Read [dispatch6.md](dispatch6.md) first. Nine snapshot tests close terminal-warning
and thinking-expansion capture defects. Startup resize follow regression repaired;
final affected gate 1965 passed / 1 normal deselection. Current mypy has exactly the
same 292 normalized diagnostics as archived HEAD (unwaived, not green). Native
navigation matrix, lifecycle subscriber proofs, injected journeys and other finite
acceptance gaps remain. Full default suite not run before core completion.

## Historical Dispatch 5 — INCOMPLETE; production cutover now active

Read [dispatch5.md](dispatch5.md) for prior implementation and exact
receipts and finite remaining gaps. This supersedes all no-cutover/byte-identity
claims below. Production now uses ChatTranscript; old app mechanics and adapter
modules are deleted, projector renamed without alias, SessionFactory/launcher
seams wired. Focused final partition: 53 passed; resource/core partition: 107
passed. Full default suite deliberately not run because acceptance is unfinished.
Full mypy failed with 653 errors (including introduced test Optional narrowing).
No READY claim; independent final review/completion remain parent-owned.

The remaining sections are historical evidence, not current ownership.

## Dispatch 4 continuation — NOT READY (Task 01 still incomplete)

Turn 1, dispatch 4/20, max 60 turns; no retries, nested agents, headless runs,
commits or pushes. This section supersedes earlier milestone status. Production
composition/subscription remains unchanged. All eleven original dirty files were
rehash-verified byte-identical to `source-evidence.txt` after the changes.

### Implemented and verified in this continuation

- Canonical real-file 65-entry replay: newest 30, then 30, then 5, whole ordered
  contents, repeated exhausted request, unchanged history bytes.
- Single retained older task, serialized reader, generation/cursor publication
  checks; clear/bind/close cancel and join older/read/window work. Concurrent older
  callers join the same task. Cancellation-suppressing older reader cases prove
  stale results cannot repaint and a later echo waits behind cleanup.
- Stable prepend boundary, temporary zero-height sentinel cleanup, summary cursor
  wording. A real-store paired user/answer test injects a concurrent tail notice
  through a public mount override and proves whole prefix/tail order.
- Corrected existing `TranscriptProjector.project_user_turn` separator insertion:
  a prepended user mounts at before+1 when a separator was inserted. Its old unit
  expectation [1,1] encoded the reversed order; changed to [1,2] per normative
  HTML. Projector rename remains Task03. This shared correction affects old replay
  too; no app source or dirty-baseline edit was made.
- Read error/empty older result preserves tail/cursor and permits retry. Partial
  projection keeps prefix and unrelated notice, latches older retries off, emits
  fixed recovery copy and exception-class-only log, resets on clear.
- Coalesced retained window worker, real 500/10 constants, non-reentrant mount
  scheduling, settled-prefix eviction, live answer/thinking/tool/steer protection,
  saturation stops without busy-looping; tool completion permits convergence.
  Windowing is suspended during older backscroll or hidden presentation. Logical
  lines survive eviction; eviction never increases the history cursor.
- Tree-output mount is a scroll sibling, survives ordinary clear, stays outside
  logical text and expansion. Pending steering FIFO/unmatched application and
  natural/expanded/collapsed policy are component-owned; tools/thinking inherit
  policy and older tools do not steal active-tool selection.
- Local adapter fresh-instance/record-only/separator/before/literal notice tests.
  Both themes at all three specified sizes prove scoped semantic color/padding
  and painted content without app.tcss. Explicit wheel/sdist CSS inclusion plus
  temp-source archive byte checks and isolated extracted-wheel import pass.
- Prepared `adapters/workflow_progress.py` as a byte-identical copy of the original
  app-owned implementation. Fresh-process imports in both orders pass. Original
  module and app constructor remain active; physical caller migration/deletion is
  deliberately not claimed.
- Basic mounted visibility retains widget identity and hidden output without
  rereading or changing focus; clear retains visibility. This is NOT geometry /
  reading-anchor / follow correctness.
- Awaited public mount cases prove clear/bind/close wait for already-admitted
  projection and later echoes survive (except closed admission).

### Exact verification

Cwd `/root/Code/tui-refactor/slo`; every pytest command used
`VIRTUAL_ENV=/root/.pyenv/versions/slo-harness`, its `bin` first on PATH,
`SLO_ENV=test SLO_DEFAULT_MODEL_NAME=gpt-5.4 SLO_AUTO_VISUALIZE=0`,
`PYTHONPATH="$PWD" poetry run pytest -q`.

Final command paths: `tests/tui/test_chat_transcript.py
 tests/tui/test_transcript_projector.py tests/tui/test_transcript_adapter.py
 tests/cli/test_chat_transcript_resources.py`.
**109 passed, 22 warnings in 45.27s, exit 0**; `dispatch4-final.log` and
`dispatch4-final.exit`. This includes 27 component cases and two archive/import
cases; old app-adapter tests remain surrounding evidence, not new-owner proof.

`poetry run mypy src/tui/components tests/tui/test_chat_transcript.py
 tests/cli/test_chat_transcript_resources.py`: **exit 0, 9 source files**.
`poetry run black --check src/tui/components src/tui/transcript_projector.py
 tests/tui/test_chat_transcript.py tests/tui/test_transcript_projector.py
 tests/cli/test_chat_transcript_resources.py`: **exit 0, 11 unchanged**.
`git diff --check`: exit 0. No full suite (explicit final-cutover timing), no
whole-repository static gate and no manual interactive smoke executed.

Increment evidence: `older-red.log` 1 failed then `older-green.log` 6 passed;
`window-red.log` 2 failed then `window-green.log` 8 passed;
`prefix-red.log` 1 failed then `prefix-green.log` 1 passed;
`visibility-red.log` 1 failed, subsequently included green. Failure-matrix and
adapter cases passed when added (no invented RED). Resource test already passed
before explicit include because Poetry included the source tree; inclusion is an
explicit packaging contract, not a claimed regression fix. Initial paired-session
seed attempt timed out at 60s; replaced with real canonical store seeding to avoid
session rate-policy waits, not fabricated replay results. Saturation first failed
on the test's invalid `tool_output` field; corrected to actual `content` contract.
One intermediate affected gate failed the old projector [1,1] expectation; the
spec-required correction above and full affected rerun resolve it.

### Finite remaining Task01 gaps (do not advance as READY)

1. **Viewport owner not implemented:** retained message anchor, geometry readiness,
   after-layout restoration, explicit bottom intent, revision-scoped pins and
   native input transport. Current `set_visible` only toggles display and suspends
   eviction. Older prepend does not yet preserve the painted reading line; native
   top events are present but complete native navigation belongs with Task02's
   snapshot work. Task01 cannot claim its prescribed anchor contracts closed.
2. **Failure/lifecycle matrix incomplete:** real session subscriber backpressure
   (current cases use direct public echo), repeated cancellation/concurrent
   lifecycle ordering, post-clear-snapshot synchronous notice during awaited
   removal, initial mid-projection failure/retry policy, empty-content sentinel
   and mixed thinking/tool prepend, partial failure with an active live tool.
3. **Window/expansion coverage incomplete:** mounted backscroll exit/convergence,
   protected thinking and steering matrix, hidden pending-anchor suspension,
   expansion inheritance across clear/bind and exact user always-expanded proof.
4. **Workflow progress migration:** destination is prepared but production import
   remains old to preserve dirty original bytes. Cutover must replace import and
   remove old module; no forwarding shim was added.
5. **Boundary acceptance pending:** queue placement/discard, child filtering,
   exporter-once, app hydration-before-subscribe and complete persistence journey
   are Task03 integration obligations; do not infer them from component tests.
6. **Final checks pending:** full/static/manual gates and independent review are
   still parent-owned. No genuine environment blocker has been established; this
   is unfinished implementation/evidence, not a waiver or completed Task01.


## Dispatch 3 continuation — INCOMPLETE

Turn 1, dispatch 3/20, no retries, nested agents, commits or push. Task 01 remains open; Tasks 02 and 03 have not started. The historical READY below is only the first milestone and does not describe current feature acceptance.

Implemented a bounded AC06 lifecycle increment in `component.py`: hydration publishes under mutation lock only after generation validation; clear/bind/close share lifecycle admission, invalidate before joining the reader, and remove only the captured old children. Live echo/event admission waits behind reset. Cleanup is shielded and joined even if its caller is cancelled. A cancellation-suppressing real-store reader test covers clear, rebind and close; old entries do not repaint, post-reset echo survives clear/bind, closed admission ignores it, and rebind subsequently hydrates successfully. This is not the full session-subscriber/older/window/projection-race matrix.

A concrete defect surfaced during the close case: `_closed` collides with Textual MessagePump's own shutdown state. Setting it during presentation close prevented normal message-pump teardown and hung Pilot exit. The component now uses `_presentation_closed`; this is not a compatibility alias. No existing production or preserved baseline file was edited in this dispatch.

Verification (cwd `/root/Code/tui-refactor/slo`; environment exactly `VIRTUAL_ENV=/root/.pyenv/versions/slo-harness`, `PATH="$VIRTUAL_ENV/bin:$PATH"`, `SLO_ENV=test`, `SLO_DEFAULT_MODEL_NAME=gpt-5.4`, `SLO_AUTO_VISUALIZE=0`):

```bash
PYTHONPATH="$PWD" poetry run pytest -q tests/tui/test_chat_transcript.py
# Initial RED attempts timed out (120s, then 60s); second showed ..FF before close hung.
# The first test version failed to release its reader when missing clear/bind raised;
# corrected test cleanup before implementation. No completed RED suite claimed.
# After implementation, close still hung until the MessagePump field collision was fixed.
# Final: exit 0, 5 passed, 22 warnings in 3.55s; lifecycle-green.log.
PYTHONPATH="$PWD" poetry run pytest -q tests/tui/test_chat_transcript.py tests/tui/test_transcript_projector.py tests/tui/test_transcript_adapter.py
# exit 0, 85 passed, 22 warnings in 16.17s; lifecycle-focused.log.
poetry run black --check src/tui/components tests/tui/test_chat_transcript.py
# exit 0, 7 files unchanged.
git diff --check
# exit 0.
```

The local `lifecycle-red.log` is a truncated timeout receipt, not a completed failing-test summary. No full default suite was run because the feature is not complete (user's final-only timing). Mypy, archive/resource verification, final independent review and completion remain unexecuted, not waived.

Acceptance-to-evidence delta: AC06 now has initial-history stale-publication / caller-cancellation / echo-backpressure evidence from `test_initial_read_cannot_publish_after_lifecycle_reset`; every other AC row below remains open. Finite next work: (1) finish Task01 older 65-entry/stable-prefix/failure protocol, 500/10 window, steering/expansion/tree, lifecycle awaited-projection and real subscriber matrix, adapters/CSS/resources; (2) Task02 explicit snapshots and native navigation/hidden-anchor matrix with temporary active-app wiring; (3) Task03 single production cutover, SessionFactory/launcher injection, deletion/rename and migrated app journeys; (4) complete applicable static/resource/default-suite gates and update the acceptance map for parent final review. No claim of acceptance-ready core.

---

**Verdict: READY — first runnable Task 01 milestone only (2026-10-26).** Stop for parent-provided independent early feedback. Task 01 is NOT complete; no full feature acceptance is claimed. Current accounting: implementation turn 1, dispatch 1 of 20; 60 turns maximum; prerequisite dispatch separate; no nested dispatches, retries, commits or pushes.

## Current bounded increment (supersedes prerequisite-only status below)

Added `src/tui/components/__init__.py`, `src/tui/components/chat_transcript/{__init__.py,component.py,css.tcss,adapters/__init__.py,adapters/transcript.py,adapters/workflow_notice.py}` and `tests/tui/test_chat_transcript.py`. Package initializers are docstring-only. No existing source/test file changed. All eleven dirty baseline files were rehashed against `source-evidence.txt` and remain byte-identical. Branch remains `feature-96_chat_transcript`.

`ChatTranscript` mounts a retained scroll/content pair with resource-loaded scoped DEFAULT_CSS, borrows the canonical history reader, renders the newest 30 entries through the existing `TranscriptProjector`, records logical lines through its local notice adapter, and admits user echoes/parent events. Initial reader failure leaves the mounted surface usable; repeated successful hydration does not duplicate widgets or write history. No session invocation/subscription/persistence ownership moved into it. The old production app alone remains active. Existing projector name intentionally remains until its planned rename/caller migration; no second projector or compatibility alias was added.

Representative pytest journey seeds 16 real Faux/session turns (32 canonical entries) in temporary filesystem history, renders the newest 30 in order, verifies byte-identical history after repeated hydration, then sends one real session turn through the mounted component. It asserts visible user/answer content, painted final answer and exactly one persisted prompt/result. This is **not** AC01's complete 65-entry/older-loading/subscription journey. The second test injects a failing reader and proves subsequent user rendering works. Uses existing pytest root/TUI fixtures and replay session helpers; a minimal local App mounts the real component without app.tcss. No new harness/platform/manual probe.

Exact environment for all milestone commands (cwd `/root/Code/tui-refactor/slo`):
```bash
export VIRTUAL_ENV=/root/.pyenv/versions/slo-harness
export PATH="$VIRTUAL_ENV/bin:$PATH"
export SLO_ENV=test SLO_DEFAULT_MODEL_NAME=gpt-5.4 SLO_AUTO_VISUALIZE=0
# which python => /root/.pyenv/versions/slo-harness/bin/python
# poetry run python --version => Python 3.11.7
PYTHONPATH="$PWD" poetry run pytest -q tests/tui/test_chat_transcript.py
# RED: exit 2, collection error: missing chat_transcript package (task01-red.log)
# GREEN: exit 0, 2 passed / 19 warnings / 3.26s (task01-green.log)
PYTHONPATH="$PWD" poetry run pytest -q tests/tui/test_chat_transcript.py tests/tui/test_transcript_adapter.py tests/tui/test_transcript_projector.py
# exit 0, 82 passed / 19 warnings / 16.14s (task01-focused.log)
poetry run black --check src/tui/components tests/tui/test_chat_transcript.py
# final exit 0, 7 files unchanged; earlier check flagged three formatting regions,
# corrected explicitly before the final check
PYTHONPATH="$PWD" poetry run pytest -q tests/tui/test_chat_transcript.py
# final post-format exit 0, 2 passed / 19 warnings / 3.05s (task01-final.log)
git diff --check
# exit 0
```
Logs are adjacent local ignored evidence. Existing adapter/projector tests are surrounding regression evidence, not proof of all new adapter contracts. Warnings are existing pythonjsonlogger/LangGraph/Pydantic deprecations. No full suite, mypy, package build or manual smoke ran. Current HTML hashes still match the prerequisite receipt.

**Remaining plan after early review:** finish Task 01 lifecycle admission/generation/read publication and cancellation races, stable older prepend/65-entry journey, summaries and 500/10 non-reentrant windowing, expansion/steering/tree/visibility/navigation ownership and tests; add component adapter/import-order matrix; relocate app-owned workflow progress only with its required ownership retained; package resource inclusion/archive proof and full theme/viewport CSS matrix. Current close is only a bounded reader join, not the complete specified clear/bind/close protocol. Native navigation/follow callbacks and all anchor guarantees are unimplemented. Then Task 02 explicit snapshots with temporary old-app wiring per precedence, Task 03 production cutover/deletion/rename and app journey migration. Update architectural docs with the actual completed ownership migration, not a claim that this unused prototype is production. Acceptance hardening, final full non-E2E/static/resource gates, independent final review and completion reconciliation remain mandatory. No AC01–AC13 is fully closed by this milestone.

---

## Retained prerequisite evidence

The following is historical prerequisite context; its no-implementation statements describe that prior dispatch only.

## Scope, branch and accounting

- Application: `/root/Code/tui-refactor/slo`; actual Git root: `/root/Code/tui-refactor`.
- New dedicated branch: `feature-96_chat_transcript`, created from current `tui-refactor` HEAD `dd2da5bf9feb23618d76562ccf264cbfc315873b`. Deliberately no main checkout/pull/rebase: the specified dirty baseline is an input, not disposable work.
- Preserved tracked modifications: `AGENTS.md`, `src/tui/app.py`, `src/tui/workflows/progress_coordinator.py`, `tests/integration/test_workflow_progress_tui.py`, `tests/tui/test_app.py`, `tests/tui/test_workflow_session_list.py`.
- Preserved untracked files: `src/tui/adapters/{__init__,transcript,workflow_notice,workflow_progress_updates}.py`, `tests/tui/test_transcript_adapter.py`. All eleven existing-work files match the specification's `evidence/source-baseline-turn6.json` hashes; see [source-evidence.txt](source-evidence.txt). Do not discard, stage or claim authorship of these changes.
- Current additions are only this handoff and adjacent prerequisite receipts. Source status remains dirty intentionally.
- Effective limits: **60 turns / 20 dispatch calls per turn**, initial attempt plus 3 failed-task retries, no retries after abort. Installed workflow has no stricter budget; current user instruction overrides stale repo SLO.md 8/6. Carry the user's **prerequisite dispatch 1, before turn 1** accounting; 0 implementation turns started/completed/partial, 0 nested dispatch calls here, 0 retries here. Historical specification-workflow counters are not implementation turns and are not erased.
- In-session subagents authorized; headless forbidden. This prerequisite session exposes no `spawn_sub_agents` tool, so no child or independent-review claim is made. The coordinating session must supply that tool/reviewer for subsequent independent gates; never bypass this with a shell/headless launch.

## Sources and precedence decisions

`SPEC = /root/Code/specifications/projects/slo/specifications/96-agent-message-queue/tui-refactor-side-quest` (absolute, authoritative; this checkout has no application-root `specifications` symlink).

Read `request.md`, all three `task-*.md`, overview/engineering turn-7 semantic aids, operator layout/naming corrections, and relevant review/evidence. Fresh stdlib HTML extraction verified both aids match the actual normative HTML after whitespace removal. Hashes and source identities: [source-evidence.txt](source-evidence.txt).

- Normative `overview.html`: SHA256 `3b9e1c3fa579f6b3358d5ebe6f5b283cbac54d7dbea947c5301cc28b4d50ab84`.
- Normative `96.e.1-chat-transcript.html`: SHA256 `45ca028feaa92ba118424fb1ae5a08e7097e8b7f7df3bd40ed85bd5532312c38`.
- `SPEC/evidence/independent-review-turn7.md` says READY for exactly those hashes, **specification review only**, not runtime proof. `evidence/final-handoff.md` still describes older incomplete turn-6 bytes and is not current approval authority. No claim that the whole prior specification workflow completed.

| Decision | Effective contract and source |
|---|---|
| Current authority | Current prerequisite-only user request > applicable repository/safety rules > current HTML engineering contracts and recorded operator corrections > task summaries > immutable historical request and old evidence. Preserve artifacts; do not rewrite history. |
| Execution mode | Historical request.md's headless/specification-only launch instructions are historical source intent, not current commands. Current request authorizes relevant baseline tests only, no implementation. |
| Folder/naming | Operator layout correction and HTML win over original `adapters/component.py`: use `components/chat_transcript/component.py` beside `css.tcss`; `adapters/workflow_progress.py` remains app-owned. Use `SessionFactory`, `TranscriptProjectionAdapter`, `TranscriptNoticeDisplayAdapter`; Task 03's wording about retaining projector signatures does not cancel the explicit class rename. |
| Task 02 transition discrepancy | HTML Change 2 permits temporary old-app explicit callback wiring; Task 02 says no app changes. Removing duck typing with no callback makes the active old path non-following. Normative HTML and no-regression requirement control: preserve behavior with minimal temporary explicit callback wiring, deleted in Task 03. Do not ship an intermediate broken path. This is a documented precedence decision, not permission for unrelated app cutover in Task 02. |
| Missing Task 04 | Only three task files exist. Task 03's Task-04 references cannot authorize deferring accepted core behavior. Complete the three-task runnable core, migrating its affected tests as part of those tasks; retain all AC01–AC13 required outcomes. Do not invent a fourth project or leave core acceptance unfinished. |
| New harness prohibition | Current user explicitly overrides HTML's proposed ChildBootstrap/SyntheticTranscriptApp/manual probe framework. Do not create `tests/support/chat_transcript_{bootstrap,runtime,probe}.py` or a new manual harness. Use existing pytest, Textual Pilot/compositor techniques, FauxChatModel and real temporary stores. Ordinary focused tests/fixtures remain appropriate; missing safe proof is reported, never replaced by unsafe live execution. |
| Gate timing | Current user says focused/affected pytest during work, entire default pytest suite once feature complete. Do not run Task 02's prescribed `make test` midway. Final default suite is non-E2E per pyproject/Makefile, not live-provider/Docker tests. Static/resource requirements remain pending, not waived. Manual evidence cannot be called passed from Pilot alone. |
| Python environment | Actual `.python-version` is `slo-harness`, not stale AGENTS `slo`. Select its Python 3.11.7 explicitly and verify Poetry uses it. No installs or lockfile changes. |

No unresolved product-boundary decision prevents starting the bounded core under these precedence rules. Full feature approval still requires missing acceptance evidence and independent gates; if implementation discovers a contract that cannot be met safely without the prohibited harness, stop that proof and report the exact gap rather than expanding scope.

## Compact routing / read coverage

Read AGENTS.md (also full injected context), local SLO.md/CLAUDE.md, root RESEARCH.md and docs/RESEARCH.md (full injected context), pyproject.toml, poetry.lock relevant package entries, poetry.toml, Makefile, .python-version, root/TUI conftests and tests/state_isolation.py. No CONVENTIONS.md, MEMORY.md or additional source/test nested instruction file was found. `environments/tests.env` is absent: use the checked-in Makefile fallback, never development.env.

Language/framework: Python 3.11, Textual **8.2.8**, TCSS, Poetry packaging. Tests: existing pytest/pytest-asyncio; mounted presentation journeys and deterministic lifecycle cases; real temporary filesystem history plus Faux provider. Not a new API/domain/database/CLI feature. Exclude FastAPI, ORM/DBOS, Go/TypeScript/Vue, provider changes, scheduler/queue implementation, workflow-progress behavioral extraction and presentation-authoring skills.

All following paths are relative to the verified absolute active skill root **`/root/.local/share/pipx/venvs/slo/lib/python3.11/site-packages/skills`**; tier = installed `SLO_SKILLS_DIR`, not checkout skills. INDEX and runtime manifest consulted. The only discovered user skills are unrelated PDF/diff presentation overrides; no selected same-name override exists.

1. `orchestration/workflows/code-test-review.md` and `orchestration/workflows/SKILL.md` — exact mandatory workflow and budgets.
2. `engineering/{engineering-routing,engineering-testing,engineering-ownership}/SKILL.md`.
3. `coding/{coding-rules,declarative-method-structure,test-verification-policy,code-test-loop}/SKILL.md`.
4. `languages/python/{python-conventions,named-arguments-and-type-hints,method-docstrings,declarative-method-structure}/SKILL.md`.
5. `tui/build-textual-tuis/SKILL.md` — affected build recipe; no CLI command or new application/domain service is proposed.
6. `design-and-analysis/locate-knowledge-base/SKILL.md`.
7. `git-ops/{branching-and-commit-conventions,create-feature-branch}/SKILL.md`.

Mandatory implementation discipline: test first (current user/project overrides generic implementation-first examples), declarative cohesive methods, Tell Don't Ask, typed boundaries, keyword calls, documented behavior/lifetime, one owner per decision, no forwarding compatibility shims in final state. Python's specific ~8-line guidance is a decomposition signal, not arbitrary fragmentation. Fresh implementers must read the actual selected rules and affected source, not treat this handoff as a substitute.

KB found at `/root/Code/KnowledgeBase/KB/Welcome.md`; consulted `slo/README.md` (index equivalent; no index.md), `slo/gotchas.md`, `slo/transcript-window-liveness.md`. Durable cautions: Poetry can silently choose a different interpreter without VIRTUAL_ENV; never derive logical history cursor from evicted widget counts; protect newest ten and live widgets; contentless thinking end is not terminal. No new KB design decision was made in this prerequisite-only pass.

## Acceptance contract — stable IDs

Dependency: **T01 → T02 → T03** (T03 depends on both). `96-AC01` through `96-AC13` below preserve the HTML AC numbers; checklist item `96-Tnn-Cxx` means the corresponding task's acceptance checkbox in original order (T01: 12, T02: 12, T03: 11). These references preserve every checkbox without silently dropping task detail. No criterion is closed by a baseline pass alone.

| ID | Required observable outcome / missing new proof | Task ownership; existing baseline coverage |
|---|---|---|
| 96-AC01 | Real 65-entry history: newest 30 then older 30+5 in order, no duplicates, hydrate before subscribe; live prompt/result persisted once; hydration read-only | T01/T03; replay_resume, app; add component replay journey |
| 96-AC02 | Normalized thinking ID repair and contentless-end behavior, answer seal-on-advance, terminal seals, replay adjacency | T02/T03; projector, both stream widgets |
| 96-AC03 | Same tool identity for args/partial/result; partial not terminal, no blanket tool sweep; steering FIFO/unmatched event and warning wording unchanged | T01/T03; projector, tool/steering/app |
| 96-AC04 | 500 window/10 protected tail/live protection; 30-entry hydration/batches, accurate logical cursor, backscroll suspension, 501st mount no deadlock and saturation no busy loop | T01/T03; replay/app; add real-constant convergence cases |
| 96-AC05 | Capture immutable snapshot exactly once before coalesced/terminal mutation; generation/revision/source validation; native destination and final-growth follow; x-only/old callback cannot re-arm reading | T02/T03; scroll_follow, stream widgets; add spec's named race/navigation cases with painted-line oracles |
| 96-AC06 | Single-flight reads; clear/bind/close cancel+join UI work, stale reads cannot repaint, live delivery backpressured not dropped; initial/read/partial projection failure policies and fixed notices | T01/T03; replay/app; add controlled reader and lifecycle cases over real stored entries |
| 96-AC07 | Mounted hide retains identity/output; show restores anchor/follow after layout; no hidden geometry, reread or abort; modal focus untouched and prompt usable | T01/T02/T03; new component visibility proof required |
| 96-AC08 | Native visible selection, highlight/scroll, raw Markdown copy and one clipboard funnel; incomplete append-order fallback excludes separators | T02/T03; selection_copy, selection_scroll_highlight, selection_copy_e2e (not marker-excluded) |
| 96-AC09 | Expansion policy preserved; clear removes held queue not active execution; idle-only new; queue remains direct chat-shell child immediately before input | T01/T03; app, queued_prompt_block, user/tool blocks |
| 96-AC10 | Tree output remains scroll sibling outside ordinary clear/window/expansion/logical copy; survives clear/new; exporter called once | T01/T03; app, tree_viewer, slash_router_tree |
| 96-AC11 | No foreground child transcript; renderer text/classes exact; progress/coordinator/modal/abort independent; attached/detached launch use injected seam | T01/T03; subagent_event_routing, workflow_receive_path/session_list/workflows, both workflow integrations, visualizer_launcher |
| 96-AC12 | Scoped DEFAULT_CSS without app.tcss, both themes at 60×20/80×24/120×40; wheel/sdist exact resource and extraction-owned import | T01/T03; new component/resource pytest required; no package build executed |
| 96-AC13 | Fresh register(tui=owner) instances; record non-rendering, before affects display not append log; acyclic imports; rename/move without surviving aliases or duplicate app state | T01/T03; transcript_adapter, projector, agent_pane_manager |

Task closure references:
- **96-T01-C01…C12:** exact package/owner, adapters and resource; old app alone active. Do not mount two surfaces. Constructor borrows history reader only. Component-ready tests are not production-cutover evidence.
- **96-T02-C01…C12:** one frozen FollowSnapshotDAO (False/-1/-1), exact source/snapshot transport, optional callback, pre-mutation capture on every flush, no duck typing, generation closure, visible/current-only correction, hidden retention. Preserve active app behavior during transition per precedence above.
- **96-T03-C01…C11:** one production component, all callers/lifetimes routed once, SessionFactory and launch seams, queue/focus/tree/workflow boundaries, deleted old state/imports/CSS, migrated behavior tests and final gates. No Task-04 deferral of accepted core.

## Source seams and risk map

Inspected dirty diff, adapter and app composition/hydration plus call-site search; future implementers must read full affected methods before moving them. Existing owners: app.py:557 composition; :620 hydration-before-subscribe; :1317 Rendered handling; :1717 tree placement; transcript_projector.py owns maps; stream widgets own `_check_app_at_bottom`/flush timers; workflow_progress_updates remains app-bound.

- **High: transitional regression:** removing widget lookup without wiring old callers breaks follow. Keep temporary explicit callback only until unified cutover; test current production app at each increment.
- **High: ordering/lifecycle:** lifecycle then mutation lock; older/window publisher must not await lifecycle lock. Cancellation-suppressing read may delay clear and subscriber; do not abort session or acknowledge lost live output. Sync notices arriving after clear snapshot survive. See HTML §8.1.
- **High: native navigation:** Textual private force-stop invokes callbacks and stops both axes. Reject stale epoch/revision before stopping, preserve destination anchors; test actual inputs and painted line/row, not just private flags or scroll_y. Pinned Textual 8.2.8 is essential.
- **High: older prepend/window:** stable insertion boundary, logical cursor, partial failure retains rendered prefix and disables retries until reset; asynchronous enforcement never awaits itself. Tree siblings and unbounded logical lines explicitly prevent a total-memory-bound claim.
- **Medium: packaging:** Widget CSS_PATH unsupported; DEFAULT_CSS resource plus explicit wheel/sdist inclusion. Tests build/extract only inside temp-owned paths, never install or stub system commands.
- **Medium: test migration:** existing private app monkeypatches must move to real component behavior, not compatibility aliases. Existing root fixtures isolate SLO_HOME/HOME/auth and suppress terminal spawns. Existing TUI auth resolver fixture is not evidence of real credential admission; composed persistence journeys use established integration patterns.
- **Environment caveat:** installed pytest 9.1.1 versus poetry.lock 9.0.3 (within manifest range); baseline is evidence for the actual installed environment, not lock-exact reconstruction. No packages changed. Full/static/manual/package gates remain unverified.

## Exact verification / evidence

Relevant baseline was executed once, with no implementation edits:

```bash
cd /root/Code/tui-refactor/slo
bash docs/implementation/96-chat-transcript/baseline-command.txt \
  > docs/implementation/96-chat-transcript/baseline.log 2>&1
```

The [command receipt](baseline-command.txt) contains the complete exact environment and all selected test paths (no hidden selectors): explicit `VIRTUAL_ENV=/root/.pyenv/versions/slo-harness`, PATH prefix, Makefile fallback test variables, fake Anthropic key, real provider key overrides unset, `PYTHONPATH="$PWD" poetry run pytest -m 'not e2e'` over 25 named file/directory arguments. Root existing fixtures supply disposable state. Interpreter verification: both `python` and `poetry run python` resolve `/root/.pyenv/versions/slo-harness/bin/python`, Python 3.11.7; Textual 8.2.8; pytest 9.1.1.

**Result: 990 passed, 27 warnings, 387.16 s; exit 0.** No failures/skips/deselections reported. Warnings: pythonjsonlogger move, LangGraph pending default and Pydantic instance model_fields deprecation. Full output: [baseline.log](baseline.log) (local evidence, ignored by the repository's log rule; not staged); machine exit: [baseline.exit](baseline.exit). This proves only existing selected behavior at the preserved dirty source identity, not the proposed component or absence of all regressions.

Implementation focused commands (same environment prefix as baseline; execute only after files exist):

```bash
# T01
PYTHONPATH="$PWD" poetry run pytest -m 'not e2e' tests/tui/test_transcript_adapter.py tests/tui/test_chat_transcript.py tests/cli/test_chat_transcript_resources.py
# T02, including the still-active app regression boundary
PYTHONPATH="$PWD" poetry run pytest -m 'not e2e' tests/tui/test_chat_transcript.py tests/tui/test_assistant_stream_block.py tests/tui/test_assistant_stream_thinking_block.py tests/tui/test_scroll_follow.py tests/tui/test_selection_copy.py tests/tui/test_selection_scroll_highlight.py tests/tui/test_app.py
# T03 affected boundary: repeat the baseline command and include new component/resource/journey tests
PYTHONPATH="$PWD" poetry run pytest -m 'not e2e' tests/tui/test_chat_transcript.py tests/cli/test_chat_transcript_resources.py tests/integration/test_chat_transcript_journey.py
```

**Final only, not run here:** under the same verified VIRTUAL_ENV and test environment, `make test` (expands to `PYTHONPATH="$PWD" poetry run pytest -m "not e2e"` across configured tests); `poetry run black --check <all changed/new Python paths>`; `make lint` (actual target: `poetry run mypy src/ tests/`). No mutating formatter. Resource proof uses existing pytest/Poetry build backend in a temp source copy, no new harness. Record manual observations separately if safely available; no live provider/window/child signal is authorized. Baseline/static failures cannot be silently waived.

Final read-only verification: `git diff --check` exited 0; all eleven pre-existing dirty files were rehashed and remain byte-identical to the captured source identity. No source/test edits were introduced by this prerequisite pass.

Next authorized implementation workflow must retain Step 1 test-first runnable slice + bounded independent early feedback, Step 2 independent final review, Step 3 original-spec completion reconciliation. This handoff does not execute or replace those gates. Stop here for this prerequisite request.
