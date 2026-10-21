# T6 read handoff and static authorization boundary — 147

## Verdict: INCOMPLETE author read closure; fresh static RED

This is **not READY for the requested complete mounted/64/privacy AUTHOR READ handoff**. The complete unified helper and matrix assertion bodies were read, but all affected production continuations, privacy/parity bodies, chapter sample prose and remaining selected prerequisites were not. A filename allocation or another author's ingestion claim cannot fill that gap. No independent Review, full-feature completion or live approval is claimed.

Same unfinished turn 1: started 1, completed 0, historical partial 1, supplied dispatch 147, retries 0. Unlimited turns AND dispatches supersede old limits. No agents dispatched. Only this report and `t6-read-static-boundary-147-receipts/` were written. No source/test/spec/KB/other-worktree edits, installs, live calls, git mutations or full suite. Tool-generated output spills occurred; they are not read evidence. No arbitrary dispatch limit is asserted.

## Fresh static evidence

Cwd `/root/Code/slo-94-herdr-integration/slo`. `PYENV_VERSION=slo-harness poetry run python --version` returned **Python 3.11.7**; `poetry run which python` returned `/root/.pyenv/versions/slo-harness/bin/python`. Read Makefile before execution. No environment file sourced.

Command: **`PYENV_VERSION=slo-harness make lint`**.

- Make exit **2**, mypy child exit **1**.
- **Found 281 errors in 58 files (checked 801 source files).**
- `lint.command`, `lint.log`, `lint.exit`, and `inventory.txt` retained in the receipt directory.
- Independently parsed diagnostic multiset against 142: **0 added, 0 removed**. Normalization removes line/column coordinates only; paths, complete messages, codes and duplicate counts remain. Inventory retains fresh exact coordinates too.
- Five partitions still sum exactly: A 81/4; B 53/5; C 45/11; D 101/37; E 1/1. Seven production files have ten diagnostics; 51 test files have 271.

**These are MANDATORY FINAL ACCEPTANCE BLOCKERS, not a reason to abandon authorized offline T6 work.** A scoped green check, historical full-suite pass, or zero new diagnostics does not satisfy `make lint`. No pytest or command-stubbing suite ran in this lane; no new binary-integrity/test pass is claimed.

## Exact YAML decision

Fresh diagnostic:

```text
src/agents/slo_agent/skills/service.py:13: error: Library stubs not installed for "yaml"  [import-untyped]
```

This is a **typing import diagnostic**, not evidence of a runtime ImportError. Actual source line 13 is `import yaml`; `_extract_frontmatter` calls `yaml.safe_load`, retaining a dict or returning `{}`. `pyproject.toml:41` declares `pyyaml (>=6.0.0,<7.0.0)`; `poetry.lock:2496–2501` locks **PyYAML 6.0.3**, main group. The dev dependency group at pyproject lines 106–115 does not declare types-PyYAML; no types-PyYAML package entry exists in the lock. Existing mypy configuration has strict optional and ignore_missing_imports; do not change it.

A truthful local Protocol can specify a consumer's `safe_load` callable result as `object`, followed by real shape validation. It **cannot supply typing metadata for the existing third-party import**. Keeping `import yaml` keeps this diagnostic. Moving it to a wrapper also leaves the import diagnostic in a file checked by full `make lint`. Replacing it with importlib/getattr solely to evade the import checker is not acceptable remediation. Nor are a fabricated yaml.pyi, Any cast, ignore, follow-imports suppression, exclusion or mypy configuration change. No repository-local Protocol-only fix has been demonstrated for E.

**Exact separate request:** authorize adding a compatible, explicitly pinned `types-PyYAML` development dependency for locked PyYAML 6.0.3/Python 3.11, updating only `pyproject.toml` and `poetry.lock` without runtime dependency upgrades, and installing that declared development stub into the existing `/root/.pyenv/versions/slo-harness` environment through the machine-guardian confirmation process. No global/pipx/system install, alias creation, auto-install-types or other package upgrades. Select the exact available stub version during the authorized dependency resolution; none was invented or fetched here. If protected-path rules prohibit the resulting environment mutation, obtain that explicit scoped exception before installation. This task grants no such permission.

## Other 280 diagnostics: bounded work versus genuine scope expansion

The exact 58-file partition and proposed per-file operations remain in `t6-audit-static-plan-142-receipts/partitions.md` and the fresh inventory. Those files are a finite write-set proposal, not permission to edit in this docs-only lane. All source/test writes currently require a subsequent coding assignment. Within that assignment, the full-feature/all-gates objective supports narrowly mechanical gate-enabling work; it does not demand a second blanket permission for every annotation.

| Partition / precise scope | Truthful maintenance and required oracle | Escalation boundary |
|---|---|---|
| A: `src/tui/transcript_projector.py`; `tests/tui/test_{recovery_ux,tool_block_partial,transcript_projector}.py` | Correct complete fake host/widget signatures and real widget state; retain mount order, partials, seal/finalize and recovery assertions. Run all three modules and replay/widget surrounds. | Production line 340 supplies `event.tool_name or block.tool_name` to required str and both can be None. First test an early nameless partial. Changing unknown-tool display/DAO policy is behavior-sensitive, not a cast/assert repair. Request that exact decision if existing semantics do not settle it. |
| B: updater, device authorization, OAuth flow, auth screen and headless auth tests listed in partition B | Real CompactionResult and complete store protocol; exact keyword callable Protocol; capability-bearing factory instance; actual server/socket and widget narrowing. Preserve append envelope, deadline, cancellation and cleanup assertions. Run each full affected module under offline guards. | `src/auth/oauth_flow.py:123–124,151–154,305,376` declares int deadlines but fractional tests pass floats. Consumers use asyncio wait_for; defaults use `value or int(env)`. Widening annotations requires preserving zero/default/cancellation behavior. Changing those semantics requires explicit scope, not longer sleeps. |
| C: Faux, chunk normalizer, Codex and Anthropic plus seven test files in partition C | Faux upstream-compatible tools signature and owned queues; test clone independence, scripted chunks, underrun and bound input forms. Normalizer read-only Mapping shape with chunk/fallback argument reconstruction. Narrow actual SDK/message/binding types in tests. | `anthropic_claude_code.py:251` reads undeclared `self.kwargs`; no fictional annotation. Actual bound RunnableBinding ownership must be established and absent/present-tools normalization reproduced offline. Any changed provider routing/normalization is explicitly excluded product scope and needs authorization. |
| C Codex specifically: `openai_codex.py:179–181`, existing provider and base tests | Candidate `base_url` alias and SecretStr only after pinned constructor/field-alias inspection and exact offline wire equivalence: endpoint, Authorization/account/session headers, Responses body and no retry. | No need to request broad provider refactor. If the substitution changes wire behavior rather than types, stop and request that bounded behavior change. Pinned SDK equivalence was not fully verified here. |
| D: exact 37-file partition, including `src/agents/skills/registry.py` | Literal skill/workflow kind preserving invalid fallback; ParamSpec to_thread wrappers preserving held ordering; real IO handles preserving closure; explicit kwargs/Callable/ContextVar; shape/None narrowing; scoped method patches and distinct widget variables. Run the listed module tests without live markers; static-check live test modules without executing paid paths. | No selection geometry, auth workflow, model policy, inbox redesign or real-process framework rewrite. If a faithful fake or declaration cannot preserve existing assertions, diagnose that specific contract before expanding scope. |

No evidence establishes that **all** 280 require unrelated behavior changes. Conversely, not all are proved annotation-only. Known genuinely separate authorization is the dependency/environment mutation above; possible semantic expansions are narrowly named (unknown partial names, Anthropic binding ownership, OAuth deadline policy, Codex wire change). Until a reproduction proves an unavoidable behavior change, these are investigation boundaries, not a blanket baseline waiver or established reason for a mass refactor.

Do not repeat 142's scoped `--follow-imports=silent` command as acceptance evidence. Use unmodified full `make lint` for the final gate. Each repair remains red diagnostic → smallest truthful change → affected offline module green → surrounding tests → final full non-E2E/smoke/lint/required Black gates. This report authorizes none of the edits itself.

## Directly read bounded assertion evidence

### Six mounted journeys

Read all `tests/integration/herdr_unified_141.py`, `test_herdr_full_flow.py:236–408` and `1427–1462`. The latter parameterizes single/retry/fallback × successful/uncertain second split. The continuation runs **inside the original app.run_test context**, not a new mounted app.

Actual assertions, not just file presence:

- Pilot enters `Run the clock then finish`; actual graph executes held `NowTool`. Run stays active while tool is held. Totals exactly **8**, stream attempts **2** for single and **3** for retry/fallback; retry emits run_retrying; fallback routes to gpt-4.1 while configured pool remains unchanged.
- Exactly one user message, one completed run and one now tool result. Single route completes while CLI barrier still says hold and reporter retains its external resource. Release then yields session_tokens=8 and idle in command log. Inactive branches require zero commands/start task/integration directory.
- Helper opens attached and detached public event routes with distinct persisted parents; checks complete ordered split/rename/run argv and captured owner pane/no-focus. Malformed second split consumes its attempt; direct/public repeats add no split/run. No focus/get/close. Submitted notices are two or one, **not viewer paint**.
- Rename/model/new use actual PromptInput keys. Each checkpoint requires exact advertised `slo --resume UUID --herdr-restore reference`, full saved config/envelope, capture/generation, configured pool JSON, effective reasoning and immutable prior bytes. After new: old history unchanged, old total 8, successor total None, no successor prompt/tool/completion, release before successor claim, no later old-ID command, drained old reporter and empty viewer registry.

Canonical tasks T6 lines 255–264 and exact attachments were read; accepted parameterization does **not require retry then fallback in one seventh app scenario**. No missing mounted functional test was established by these reads. Retained 141 final-focus log was checked: **68 passed**, including 62 foundation tests, not 68 unified journeys. This lane did not rerun them.

### Exact 64 matrix

Read `tests/integration/test_herdr_lifetime_matrix.py:1–771` completely. Actual decorators enumerate 4 triggers × 8 phases × 2 diagnostics. Read retained 140 ID audit (64 unique PASSED once) and report; did not freshly execute matrix.

- Every phase calls real captured-owner assertions before teardown: lease identity, selected/subscribed session, timer handles, preparation/close/shutdown task disposition, no prompt and no viewer registry.
- New/unmount remove old lease/subscription and stop captured timers; integration-only stops preserve selected session/lease/timers. New checks distinct successor ownership; unmount checks monotonic flags and terminal drains.
- One actual retained claimed file remains byte-identical through a new poll, with no pending/done item or prompt. This is **not** claim-in-progress race coverage or occupied-retired coverage; those remain separate all-owner tests.
- Queued CLI phases send zero effects; admitted phases send exactly one old effect and no follow-up. Semantic acknowledgements do not advance after revocation. Tickets/save/reservation slots clear and transport drains.
- Queued capture performs zero saves/changes; running save creates a loadable exact immutable orphan but never adopts/advertises it. Earlier revision bytes remain unchanged.
- Precommit platform holds registered worker before real lifetime check: new/unmount cancels with zero spawn/notice; independent integration close/disable still allows separately selected platform. Committed platform registers real guarded spawn, repeated cancellation cannot finish until thread release, then one spawn, no late notice. Separate enabled pane owner supplies genuine integration-disable effects; this is not a fabricated Herdr-to-platform fallback.
- Diagnostic sink execution is asserted for healthy and raising variants. Draining rows legitimately end with empty retired slot; separate persistent-quarantine tests cannot be replaced by those rows.

### Privacy and two-process boundary

Read 135 report and its retained final log (**289 passed**); full privacy assertion bodies and parity helper were **not completely read**, so READY135 is retained author evidence, not independently recertified here. It describes before-coalescing publication scans and both mounted routes for opened/failed/off/unavailable destinations; no global ordinary-tool redactor claim is adopted.

Read 146 report and positive exit receipt: **5 passed**, four process combinations plus bootstrap, with separate 223 safety tests reported. Its scalar oracle and public capability-refusal gaps remain in the other lane: independent literals for all five ordered pool fields and single/reasoning/workspace/plugin policy; refusal through public admission rather than private `_ensure_agent_ready`. Source-entry shim is not installed plain-Slo/live-restart proof. Do not carry the older blanket positive HOLD forward as if 146 never ran; do not turn that green run into complete restore acceptance.

## Requirements, ACs and 72 samples: incomplete reconciliation explicitly retained

Direct assertion-backed reconciliation here covers R1/R4/R8/R14/R18/R20 portions in the mounted journey and R9/R11/R20 portions in matrix above. It supports B1/B2/B4 portions, C1/C4/C5 portions and D1/D2/D3 portions. It does not certify every subclause: full R3/R5–R7/R10/R12/R13/R15–R17/R19/R21 source/assertion audits remain outstanding, as do remaining portions of the already named requirements. R22 full gates are RED/pending. R23/R24 preservation/no-live constraints were followed in this lane. R25 accepted **specification** review was read in full; independent implementation review remains separate. R2 pane appearance and D5 remain live; R26 editor redesign is excluded.

Read canonical overview in full, accepted independent-review-turn4 in full, normative T6 and exact T6 sample bodies **B26/C31/D09/O01/O02/O03**. B26/C31/D09 require chapter pytest/Black plus full make gates; fresh lint fails. O01 owner layout and O02 publication/restore diagram agree with inspected entry/helper boundaries but full current runtime closure remains outstanding. O03 is proposed pane appearance, not offline paint evidence. The other **66 allocated sample bodies plus their governing prose were not fully consumed/reconciled here**. Therefore the 142 inventory-only map is NOT promoted into all-72 evidence closure. No hash check is substituted for reading.

## Documentation 121 post-change accuracy

Read 121 report and current root/maintained research supplied in context; inspected current INSTALL references and restore quota/read/identity implementation. Private immutable reference location, limits 65,536/1,024/67,108,864, 0700/0600 policy, no automatic GC, current-history distinction, restart disablement and separate live acceptance remain the documented contract. Direct restore tail confirms no overwrite, durable-write refusal, bounded read and exact canonical identity checks.

The 121 **295/60** result is correctly historical; fresh 147 is **281/58**, not a new 295/60 result. Documentation's target-only **UNPROVEN Herdr 0.9.2+** remains appropriate after fake journeys/process tests. Full post-change owner-by-owner documentation verification is **not finished**: session activation/capture/close, app registration/inbox/replacement/unmount, reporter/transport and launcher/service/renderer continuations remain to be consumed. Do not claim the five documents have all been freshly runtime-verified from these partial checks. Shared docs were not edited by instruction.

## Honest remaining read work

Consumed: supplied AGENTS/CLAUDE/docs RESEARCH, root RESEARCH, KB Welcome/actual slo README/gotchas, engineering routing/ownership/testing, coding rules and visible cadence/shared-declarative/Python/Faux material; 142/141/135/140/121/146 reports; full unified helper and matrix; mounted prompt body; named static source boundaries and dependency/build settings. The shared skill bulk read initially truncated its head; ownership/testing/coding-rules were subsequently re-read. The routing/scope bulk read also truncated; no full routing ingestion claim. Textual/workflow/style prerequisites were not all read.

To finish the requested AUTHOR READ handoff: complete those specific prerequisite tails; canonical B/C/D governing prose and all remaining allocated samples; current production owner continuations listed in 142; complete full_flow privacy/parity and fixture guard continuations; map every R1–26 and B/C/D AC/sample to actual assertions or an explicit non-runtime boundary. This is outstanding work, not a request to invent more tests or another audit process. No additional T6 functional defect was established here beyond the retained 146 oracle/public-admission limitations.

**Final separation:** bounded assertion inspection progressed; requested full author READ handoff INCOMPLETE. Static remains mandatory RED 281/58 with explicit dependency permission required. Full regression/static integration and independent implementation review remain pending. Live supported-version/restart/pane/paint authorization remains absent. None substitutes for another.
