# T6 runtime documentation and static diagnosis — lane 121

**READY for docs + diagnosis only**, subject to the checks recorded below. Not T6
technical completion, independent Review, feature completion or release approval.
No production/test/static repairs were made. Global lint remains **UNWAIVED**.
Same unfinished turn 1: started 1, completed 0, historical partial 1, supplied
parent dispatch 121, retries 0. Unlimited turns AND dispatches; no agents spawned.

## Scope, sources and ownership

Writes are confined to README.md, docs/INSTALL.md, AGENTS.md, docs/RESEARCH.md,
root RESEARCH.md and new `t6-121-*` receipts plus this report. Existing evidence,
canonical specs, other worktrees and runtime sources remain unchanged by this lane.
No commit/push/PR/reset/clean/stash, installation, global configuration or live action.

Read current project instructions/research and frozen routing.md/scope-plan.md;
canonical H overview, T6 attachments tasks.md:3721–3816, B/C/D sections 8–10 and
accepted independent-review-turn4. H remains read-only at
`/root/Code/specifications/projects/slo/specifications/94-slo-tui-redesign/herdr`.
The review accepts specification breakdown, not implemented behavior. T5-120's
8213-pass full-suite receipt remains historical and is not relabeled as T6 testing.

Scoped guidance: engineering routing/ownership/testing, coding-rules/code-test-loop,
shared/Python declarative structure, Python conventions/types/docstrings, product
Typer, Textual and workflow accounting. KB Welcome, slo README/gotchas and machine
ROLE consulted read-only; no KB edits authorized. Some initial oversized reads were
truncated; scope-plan and needed material were subsequently visible in bounded reads.
No claim of a fresh full-family independent review. No new design or runtime owner.

Plan followed: inspect actual owners and acceptance boundaries → fresh lint and
normalized multiset comparison → update five docs → link/contract and diff checks.
Docs identify bootstrap provenance, session capture/reporting, private store and
shared transport, CLI precedence, app lifetime/registry, typed service/renderer,
context-reader extraction and duplicate-parser deletion. Setup/privacy/retention,
claimed-item investigation, restart disablement/rollback and manual viewer reuse
are explicit. INSTALL carries a pending release-evidence template, never fake green.

## Fresh static gate: exact comparison

Cwd `/root/Code/slo-94-herdr-integration/slo`; existing approved
`PYENV_VERSION=slo-harness`, Python 3.11.7. `pyenv which python` resolves
`/root/.pyenv/versions/slo-harness/bin/python`. `make test-env` reports `fallback`.
No env installation or `mypy --install-types` was run.

Command: `PYENV_VERSION=slo-harness make lint`.
Receipt: [t6-121-lint.log](t6-121-lint.log), [exit](t6-121-lint.exit): **2**.
Output: `Found 295 errors in 60 files (checked 793 source files)`; make reports its
child mypy Error 1. This is a failed gate, not a tolerated baseline.

Comparison inputs: `baseline-lint.log` (301/64), `t5-120-lint.log` (295/60), fresh
`t6-121-lint.log`. Normalize only `:line[:column]: error:` to `: error:`. Preserve
file, entire diagnostic message, error code and duplicate count in a Counter.
Do not compare sets or totals alone; notes/order/coordinates are not diagnostics.
Full results and all **60 filenames with per-file counts** are in
[t6-121-static-inventory.txt](t6-121-static-inventory.txt).

- Initial → fresh: **6 removed, 0 added** diagnostic occurrences.
- T5-120 → fresh: **0 removed, 0 added**, exact normalized multiset equality.
- Removed: two CLI `parse_args` Context override diagnostics; four `yaml`
  import-untyped diagnostics (registry and three skill tests), exactly listed in
  inventory. Do not infer a package installation or causal repair from absence:
  one YAML stub diagnostic still remains and baseline environment/cache provenance
  alone cannot establish why all four old locations disappeared.

Attribution uses T5-120's **142-file feature manifest**, not merely unstaged diff
(which misses already committed feature changes). Direct Herdr: **0 errors**.
Feature-touched existing tests: **14 errors / 2 files**:
`tests/cli/test_headless.py` (9),
`tests/tui/workflows/test_workflow_app_service.py` (5).
Remaining unrelated owners: **281 errors / 58 files**, including **10 / 7 production
files** and **271 / 51 test files**. Attribution is ownership, not causal blame.

Codes (sum 295): arg-type 141, union-attr 45, attr-defined 34, assignment 20,
method-assign 18, call-arg 12, misc 6, index 6, operator 5, dict-item 2;
import-untyped, override, var-annotated, valid-type, return-value, name-defined: 1 each.

## Smallest truthful repair strategy — proposed, NOT executed

All gates must become green. Baseline attribution grants no waiver, but neither
requires stopping authorized independent offline T6 work. This lane explicitly
forbids fixes. A later bounded maintenance lane can repair existing declarations
without a mass refactor; semantic changes and dependencies need separate decisions.
Do not add ignores, cast to Any, broaden contracts dishonestly, remove assertions,
or exclude failing files. Existing ignores are not permission to add more.

### A. Feature-touched tests (14 diagnostics)

1. `test_headless.py`: move the mock subscriber list annotation to a local typed
   value (line44); narrow optional tool names before the typed set (268); preserve
   Mapping rather than pretend `.kwargs` is always dict (287); replace six direct
   method assignments (792/803/821/849/880/896) with scoped patch objects and typed
   async collaborators. Keep cancellation, stdout and original-failure assertions.
2. `test_workflow_app_service.py`: scoped patches at118/273 instead of assigning
   methods; construct `ParsedFleetUpdateDAO` with named typed fields at145 instead
   of splatting `dict[str, object]`. Keep the same data and all lifecycle assertions.

These are targeted repository test maintenance, not package/global work; once the
parent authorizes a static-fix lane, retain the current failing mypy diagnostics as
RED, make one small change, run that test module and affected surrounding suites,
then type-check. No behavior change should be required for these listed sites.

### B. Unrelated test declarations and fake contracts (271 diagnostics)

The inventory is the exact file list; no blanket claim that all 271 are annotations
alone. Group by the observed error and real owner:

- Optional/union narrowing: tree/projector history, tool read, plugin slash,
  startup/picker/selection, cache-control and provider/model tests. Assert the
  expected non-None/concrete message/widget/content shape before accessing it;
  use distinct local names where a variable is reused for unrelated widget types.
  Do not weaken an assertion or silently choose a default value to satisfy mypy.
- Typed containers/callables: model-catalog race/lock fixtures, runtime-event
  `callable` annotation, OpenRouter harness kwargs/ContextVar, pool message lists,
  spawn schema AST narrowing. Use actual Callable/Protocol signatures, explicit
  constructor fields and `list[BaseMessage]` where required; declare ContextVar's
  intended optional credential type. No dynamic setattr/Any escape hatch.
- Scoped mocking: remaining method-assign sites in pool/recovery/manual compaction
  and provider tests should use scoped patches, preserving exact observed calls.
- TUI projector fixtures: `test_transcript_projector.py` has **66** errors;
  `test_tool_block_partial.py` **9**, `test_recovery_ux.py` **5** share fake-host
  return-contract mismatches. Inspect `TranscriptMountHost` and fake subclasses;
  prefer contract-correct test widgets/host return types with explicit test-state
  declarations. Do not widen the production host protocol merely to accept an
  incomplete fake. Test actual mount/update/seal behavior before and after.
- Compaction fixture: `test_compacted_session_updater.py` has **27** errors;
  its `_CompactionResult` stand-in and partial `_InMemoryStore` are not the declared
  real result/full protocol. Use the real result DAO and a contract-complete
  test-owned store (unsupported paths explicitly fail). Preserve isolation and
  exact persisted event assertions. This is fixture repair, not changing updater
  semantics to suit a mock.
- OAuth fixtures: callable-with-keywords needs an explicit callable Protocol rather
  than a positional Callable annotation; narrow screen/widget result types and
  model factory capabilities. The float timeout tests versus int-only signatures
  need a decision: preserve fractional-timeout behavior by proving the runtime
  contract and widening the actual timeout type if intended, or use an injected
  clock/boundary while retaining timeout coverage. Do not lengthen sleeps or
  change semantics merely to get green. This may cross into production behavior.

Most first items are legitimate test maintenance without package changes. Fixture
reconstruction still needs test-first verification, not a promise it is type-only.
Partition disjoint files after other T6 tests are ready; shared projector fake
owners must have one writer. No agents/parallel fixes were launched here.

### C. Seven production owners (10 diagnostics)

| File / errors | Smallest candidate, evidence and boundary |
|---|---|
| `src/agents/skills/registry.py` / 1 | Annotate a validated literal branch as `Literal['skill','workflow']`; preserve unknown-kind fallback. Existing parser cases plus invalid-kind regression before edit. Narrow declaration repair. |
| `src/agents/slo_agent/assistant_chunk_normalizer.py` / 1 | TypedDict `ToolCall` is not mutable `dict[str, Any]`. Use a read-only Mapping-compatible collection or explicit typed copy matching actual reads; test chunk and fallback calls/arguments before changing. No new coercion policy. |
| `src/tui/transcript_projector.py` / 1 | `event.tool_name or block.tool_name` can still be None but DAO requires str. First test missing name on both inputs; choose the existing canonical unknown-tool behavior. This is a real nullable boundary, not safe to silence with cast/assert without proving invariant. Requires bounded behavior decision. |
| `src/agents/providers/faux.py` / 3 | Pydantic subclass queue fields passed to BaseChatModel constructor and too-narrow `bind_tools` override. Match supported upstream tool input/signature, preserve clones/queues/chunk scripts; test non-BaseTool input and underrun/clone behavior. Runtime fake implementation is production source; scope it explicitly, no dependency upgrade. |
| `src/agents/providers/openai_codex.py` / 2 | Validate supported `base_url` constructor name and `SecretStr` key versus current alias/plain string. Capture exact mocked HTTP wire, OAuth headers and endpoint before/after; no live OAuth. Potential behavior-sensitive provider boundary, explicit bounded authorization needed. |
| `src/agents/providers/anthropic_claude_code.py` / 1 | `_tool_name_candidates` accesses undeclared `self.kwargs`. Prove absent/present/bound-tools behavior; use actual supported model/binding owner, not fictitious attribute annotation. Can expose real AttributeError: provider behavior decision needed. |
| `src/agents/slo_agent/skills/service.py` / 1 | Missing `yaml` stubs. No runtime defect established. Decide on a pinned project dev `types-PyYAML` dependency/lock update and authorized project-environment installation. Do not install globally, run auto-install-types, or suppress import checking. |

No package/global change is necessary for ordinary declaration fixes. The stub
repair is a **dependency decision**, not blanket permission to install packages;
this task expressly prohibits it. Current existing `ignore_missing_imports=true`
does not make this remaining import-untyped error green. Do not alter checker
configuration as a substitute for required types.

### Exact next authorizations/actions

1. Continue authorized offline T6 acceptance work in its separate test lanes; this
   failed baseline does not invalidate that work or mandate a whole-feature stop.
2. When those tests are ready, authorize a bounded static-maintenance bundle for
   A and B, with disjoint write sets, existing assertions preserved and per-file
   mypy RED → focused pytest/static GREEN. No package installation included.
3. Authorize the specifically listed C behavior boundaries only after reproducing
   each with an offline regression; do not authorize a generic provider/TUI refactor.
4. Separately decide whether to add/pin project YAML stubs and permit installation
   into the approved environment. No global types or packages are requested here.
5. Integrate; run fresh full non-E2E, smoke, lint and changed-file Black, then binary
   integrity and diff checks. Zero static errors required. Independent Review and
   Completion remain later; no count reduction substitutes for green.

## Documentation contract and verification

README and INSTALL now explicitly cover same-SLO_HOME/default-history/plain-Slo
restore, immutable private configuration/current history, 64KiB/1024/64MiB quotas,
no GC, manual deletion refusal, claimed inbox investigation, no replay, disablement
at restart, old-Slo flag incompatibility and retained panes/references. AGENTS and
both research indexes map actual owners, consolidation and deletions. The test-env
fallback is documented without promising an untracked tests.env ships.

New documentation/link/owner checks and diff results live in `t6-121-doc-check.log`
and `t6-121-diff.log` with same-stem exit files. Actual results: five document
contract checks, seven new local links/anchors, three extracted-owner paths and
typed renderer/parser-removal checks PASS, exit 0. `git diff --check` is silent,
exit 0. Read-only `dpkg -V coreutils` is silent (zero-byte `t6-121-coreutils.log`),
exit 0. Python reports 3.11.7. Reviewed the documentation changes against the
inspected runtime owners and canonical acceptance contracts.
These are document/contract checks, not pytest or runtime evidence. This lane did
not rerun the full test suite or command-stubbing suites, and makes no fresh
8213-test claim.

Live gate remains **UNPROVEN**: target Herdr 0.9.2+ only. Before any live action,
read machine guardian ROLE then README/detail and obtain explicit operator approval
for named disposable `slo-herdr-smoke`, restart only its server, and cleanup only
its created panes/processes/temp data. No active Herdr server or agent scope may be
disturbed. INSTALL has the exact pending evidence template. No live actions now.
