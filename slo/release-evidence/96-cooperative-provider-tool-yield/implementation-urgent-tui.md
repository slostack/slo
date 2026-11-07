# 96.A.2 T4 — mounted urgent activation (dispatch16)

2026-11-04, author gpt-6.1-sol medium. **Runnable local TUI integration delivered; NOT milestone READY / NOT Step1 complete.** Finite remaining acceptance cells below are not waived. No independent review/completion claim.

## Authority / preservation

Cwd `/root/Code/slo-message-queue/slo`; branch message-queue; baseline HEAD `82c3f5c6de9345af34a673a3d975366ca8c1624c` unchanged. Original 1309-line A.2 specification read, including §§3.4–3.5,5–7/A6/A11/A13/A14. Reused existing core/foundation implementations and receipts. Installed skill root resolved from both SLO_SKILL_DIR/SLO_SKILLS_DIR; selected routing/workflow/shared/Python/TUI sources loaded. README first; root RESEARCH.md absent, deliberately not created under protected-doc instructions. KB Welcome/gotchas consulted. No changes to SLO.md/docs/durable-composer/preflight, packages, system/installed executables, harness watchdog, config flags, SQL or infrastructure. No commits/push/PR/merge or nested agents/workflows. Preflight SHA256 remains `10fe2372f972374580d6071578c543edad98fd811a43ce2b0857cdb282183638`.

Counters: turn8 dispatch16/20,total64;8started/0complete/allpartial;12 historical execution retries,no aborts; this dispatch0 execution retries. Local RED/GREEN commands are not dispatches/turns or failed-task execution retries. Four dispatches remain this turn for independent feedback/repair/gates.

## Connected behavior / files

- `src/tui/components/prompt_input/component.py`: Submitted priority defaults normal; request_submission posts one fresh component-stamped intent; Ctrl+Enter replaces ONLY its old newline branch; Shift/Meta+Enter remain newline. build_draft_submission explicitly nests priority in existing MessageSubmissionDAO. No duplicate carrier/version policy or adapter.
- `src/tui/app.py`: same submitted handler and durable capture forward semantic priority. /steer explicitly normal. Alt+U priority Binding and always-exposed super-preserving SystemCommand call component request. Legacy urgent ordinary text refuses without clearing/downgrade; slash remains local. Host local capability now normal+urgent. Blank remains no submission. No new panel/theme/layout/CSS.
- `src/tui/slash_command_registry.py`: /help description carries `Ctrl+Enter / Alt+U: Send urgently`; palette help carries same hint without enlarging footer.
- `src/tui/components/chat_transcript/adapters/transcript_projector.py`: answers keyed by (attempt,iteration), thinking by (attempt,iteration,block), interrupted keys block matching late ends/completion only. Fixed deduplicated deferred/interrupted copy; requested informational/no receipt claim. Silent interruption mounts notice, not blank answer. Partial argument ownership correlates exact response so other attempts are not marked incomplete. Existing PresentAgentEventDAO command remains only ingress.
- `src/tui/widgets/{assistant_stream_block,assistant_stream_thinking_block}.py`: mark_interrupted retains/seals text/thinking using existing semantic warning roles, no abort wording. A previously sealed older answer can receive its exact late interruption marker without replacing text. Replay assistant interruption uses same widgets; existing replay/export core retained.
- New native mounted tests: tests/tui/test_urgent_{composer,tool_paint,projection,keys,lifecycle,retirement}.py. Existing prerequisites parameterized normal+urgent; existing three Ctrl-newline assertions migrated to Shift (specified intentional key contract replacement, not deleted coverage). Projector direct legacy-key fixtures updated for correlated keys.
- New real core supplement: tests/integration/test_yield_{retry_identity,session_failure}.py. No product core alteration this dispatch.

## Acceptance map / actual visual evidence

**A6:** real editor→adapter→local client→session→SQLite/history→graph/provider; Ctrl+Enter/Alt+U/palette callback each interrupts held provider before token release, one next urgent application, fixed interruption paint/no abort, final answer paint and focus. Normal Enter first, Shift/Meta newline and Tab completion, blank/noop, legacy unsupported and urgent /help local proof. Palette command enumeration/callback tested; actual palette search navigation is not separately driven. Existing normal composer/app/prompt/slash regression retained.

**A13:** real SQLite CompletionGate unknown-outcome/rejection with normal+urgent, newer typing, exact retained model_dump_json/ID/priority, same-ID /messages retry. Real unknown urgent + component reset/retirement preserves original bytes and successor edits. Generic machine principal rules unchanged and covered by prior core suite; no new authority shortcut.

**A14:** tool-paint six cells: slo-default/slo-dark ×60x20/80x24/120x40 all pass. Real @tool publishes `PAINT-BEFORE-RELEASE`, then run_blocking_tool_call holds actual thread leaf; native keyboard edits and painted `new` plus deferred notice occur while leaf held and effect absent. Same prompt region/focus. Release writes contained tmp file; actual result and one canonical defer retained. Existing composer visual matrix proves recall/band/baseline geometry.

Provider visual matrix additionally 36 cells: two themes×three sizes×three actions×silent/partial. All pass actual compositor marker/final/partial assertions. At 60x20 the naturally following viewport shows newest answer and urgent user input, so earlier interruption is above viewport; test uses native widget scroll_visible then inspects actual compositor text. This is reachable visible history, NOT a claim that every prior block remains simultaneously visible or that marker painted before the next provider request. No screenshots/platform/renderer harness introduced.

Exact projection mounted supplement: same iteration/block reused across different attempts; late first text/thinking end and run_completed do not overwrite first partial or second repaired result. Partial tool argument interruption affects only exact response. Replay/export foundations remain existing core tests.

**A11:** mounted owning close + repeated cancellation held by suppressing observer retains actual OS lease (second acquisition refuses), provider joins, borrowed client close does not abort target; final release permits new owner. Mounted /new holds successor readiness/adoption until predecessor observer joins; lease stays held then releases. Real canonical tool_output_update append failure stops at one provider, joins graph/tool and retains urgent accepted in read-only SQLite after close. Controlled uncommitted disconnect/reconnect with new urgent during held retry covers factory/prebuilt × rebuilt/not rebuilt: exact same control/policy/source/cached instruction delivery, same human ID/context, one boundary advance, actual bind_tools count equals graph constructions. Empty/note/both/lazy/pool lowbudget full matrix remains unfinished (below).

## Test-first chronology (logs retained, no invented RED)

All logs under `release-evidence/96-cooperative-provider-tool-yield/logs/`. Every test command serial foreground, `/root/.pyenv/versions/slo-harness/bin/python -m pytest -p no:cacheprovider <args> -q` (focused exploratory adds `-x`). Environment every pytest command:

```
SLO_ENV=test SLO_ROOT_DIR=$PWD SLO_APP_DIR=$PWD SLO_APP_NAME=slo
SLO_LOG_FORMAT=text SLO_DEFAULT_MODEL_NAME=gpt-5.4
SLO_ANTHROPIC_API_KEY=ci-placeholder-tests-are-fully-mocked COLUMNS=120 LINES=40
SLO_AUTO_VISUALIZE=0 SLO_HERDR_DISABLED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD
```

`environments/tests.env` not readable; tracked fallback used. No configuration mutation.

- tui-red1.log: exit1,1failed,3warnings,6.46s; mounted Ctrl+Enter cannot wake provider (old newline behavior). THEN implemented component/host/projection/widgets coherently. tui-green1 exit1 test author incorrectly searched nonexistent message_applied history kind; actual metadata marker corrected. tui-green2 exit0,6passed,14warnings,5.45s.
- tui-projection-red.log: exit1,1failed,2warnings,0.79s: late exact interruption on already sealed older block lacked visible marker. THEN mark_interrupted permits marker on sealed retained text. tui-projection-green exit0,1passed,2warnings,0.60s.
- tui-keys-red.log: exit1,1failed,2warnings,0.99s missing hint. THEN registry help hint. tui-keys-green exit1,3passed1failed: test assumed trailing space for /help completion; actual existing contract /help confirmed, corrected test only.
- tui-tool-correlation-red.log exit1,1failed1passed,2warnings,0.91s: interruption incorrectly marked OTHER attempt tool incomplete. THEN exact response ownership added. tui-tool-correlation-green exit0,2passed,2warnings,0.80s.
- Tool paint is supplemental existing offload/core behavior, not invented RED: first two runs failed author payload-field guesses (`output`, `content`); actual tool_output used. tui-tool-green2 exit0,6passed14warnings10.62s.
- tui-prerequisites exit0,10passed20warnings9.90s; tui-retirement-first exit0,1passed3warnings2.04s. Supplemental existing adapter semantics, no invented RED.
- tui-lifecycle-first exit0,1passed3warnings1.34s; tui-lifecycle-new exit0,2passed4warnings2.24s. Existing ownership behavior, no invented RED.
- tui-session-failure-first exit0,1passed3warnings2.27s. Existing fail-closed output behavior.
- tui-retry-first/green exit1 from author overstrong equality including regenerated system message UUID, then empty tools causing no bind_tools. Kept human identity/context assertions and real echo tool binding. tui-retry-green2 exit0,4passed14warnings7.07s; no product change/retry reset.
- tui-provider-visual-matrix and diagnostic exit1,1failed4warnings: marker above natural 60x20 viewport (actual paint recorded). Native scroll-to-marker/partial proof added, no product geometry change. tui-provider-visual-final exit0,36passed74warnings29.12s.
- tui-affected1 tool command timed out at240sec before summary (partial progress had failures). NOT counted green; process survey confirmed no owned pytest/mypy remained before next cycle. tui-affected2 exit1,1failed34passed old Ctrl-newline assertion; migrated Shift. tui-affected3 exit1,1failed138passed direct projector test passed old integer key; fixtures migrated exact tuple keys. No runtime compatibility shim for private tests. tui-affected4 exit0,377passed92warnings330.38s. tui-affected-final exit0,380passed95warnings318.28s. Final superseding aggregate below.
- Static tui-mypy-first exit1 one typed script-kind error; second exit1 fifteen updated fixture/factory typing errors; third/final fixed with typed script, protocol source, explicit provider constructor/class state; no ignore/waiver added. Source formatting only touched owned scope.

## Final serial verification / exact scopes

**tui-affected-final2.log** exit0 **411passed,155warnings,339.24s**:
```
tests/tui/test_urgent_composer.py tests/tui/test_urgent_tool_paint.py
tests/tui/test_urgent_projection.py tests/tui/test_urgent_keys.py
tests/tui/test_urgent_lifecycle.py tests/tui/test_urgent_retirement.py
tests/tui/test_composer_prerequisites.py tests/tui/test_durable_composer.py
tests/tui/test_composer_retirement.py tests/tui/test_prompt_component_protocol.py
tests/tui/test_prompt_input_rules.py tests/tui/test_slash_command_registry.py
tests/tui/test_transcript_projector.py tests/tui/test_app.py
tests/tui/test_prompt_input_component.py tests/tui/test_composer_visual_matrix.py
```
**tui-core-final.log** exit0 **752passed,393warnings,94.35s** (710 previous feature +37 previous foundation +5 new core supplements):
```
tests/integration/test_messaging_yield.py tests/integration/test_yield_session_failure.py
tests/integration/test_yield_retry_identity.py
tests/agents/slo_agent/test_graph_stream_lifetime.py
tests/agents/slo_agent/test_watchdog_yield.py tests/agents/slo_agent/test_watchdog_timer.py
tests/agents/slo_agent/test_graph_read_outcome.py
tests/agents/slo_agent/tool_execution tests/agents/slo_agent/history
tests/agents/slo_agent/messaging/test_delivery.py
tests/agents/slo_agent/messaging/test_injected_activation.py
tests/agents/slo_agent/messaging/test_canonical_yield_writer.py
tests/agents/slo_agent/plugins/test_dispatcher.py
tests/agents/slo_agent/messaging/test_provider_settlement_guard.py
tests/agents/slo_agent/messaging/test_history_cooperative_append.py
tests/agents/slo_agent/messaging/test_startup_raw_tool_groups.py
```
**tui-agent-final.log** exit0 **185passed,82warnings,11.68s**: tests/agents/slo_agent/{test_agent.py,test_graph.py,test_agent_recovery.py,test_agent_runtime_event.py,test_agent_streaming_dual_mode.py,test_agent_usage_commit_regressions.py,test_agent_image_history.py,test_graph_stream_parser.py,test_stream_event_dao.py}.

**tui-mypy-final.log** exit0,19files (`PYTHONPATH=$PWD PYTHONDONTWRITEBYTECODE=1 python -m mypy <19paths>`). **tui-black-final.log** exit0,19files (`python -m black --check <19paths>`). Exact 19 paths and SHA256 are in **tui-source-sha256.txt**: six product paths above, six urgent test files, two new integration files, five changed existing tests. **tui-diff-final.log** git diff --check exit0. Final core/agent gates precede only final TUI exact-tool/replay changes; final411 covers those changes. Product core unchanged since752/185.

## Lifecycle / safety audit / cleanup

Only one owned cycle at a time. New fixtures contain real files/threads and async gates, no executable fixture/subprocess/container/process workflow. Resolved effect/history/SQLite roots contained under tmp_path. Inspected transitive autouse fixtures/state isolation and narrow affected modules. Existing prompt static-contract test launches contained source mypy; projector import checks launch existing Python read-only (`-B -c`); no executable writes or real external provider/system calls. They completed/joined synchronously. Strict isolated_journey_tasks fixture reused on new live provider/tool/lifecycle/core tests: precleanup orphan remains test failure and cleanup always joins. Gates released in finally; borrowed clients/session close joined; no product all_tasks sweep. Final ps survey **tui-processes-final.log** has only unrelated historical1261413pytest/3382468fake-herdr; left untouched. No owned pytest/mypy/child/container remains. Timed-out first aggregate is explicitly incomplete, not a pass or baseline waiver.

## Finite actual remainder / next independent feedback

1. Full A7/A11 controlled matrix still NOT complete: cached empty/note/both under active control, genuine lazy model path, pooled retry/rebuild and low existing exhaustion budgets. New four-case instruction/factory/prebuilt/rebuild supplement closes only named cells; existing historical delivery/slot and same-pool journey evidence remains valid but not silently promoted to full matrix.
2. Whole-session observer/consumer failure and pooled cleanup failure lowbudget/noadditionalclaim need explicit final evidence. Output-update history failure and mounted OSlease/new/close are now covered; do not repeat already closed cells blindly.
3. Paint-before-next-provider-request is NOT proved by final mounted screenshot assertions: provider interruption/apply/order is core-proven, mounted notice inspected after request/settlement, small viewport may require scrolling. Decide whether an explicit held second-provider gate/frame-order proof is needed before A6/A14 acceptance. Actual command-palette navigation (rather than enumerated command callback) also remains unexercised.
4. Independent bounded review/convention hardening required (especially projector exact correlation, writer/executor/policy ownership, docs). No formatter-only convention acceptance. No new design module/carrier/panel introduced.
5. Full `make test PYTEST_WORKERS=6` remains **BLOCKED** by safety-audit C1/C3/C4 exact fixture consent. Not run/excluded/skipped/xfailed/substituted/waived. Full lint/fullBlack still UNRUN/unwaived. Independent final review/completion absent.

The connected local urgent UI is working and ready for bounded feedback, but the requested complete T4/core evidence milestone is **NOT READY** until finite rows close. Whole Step1 remains blocked, not completed.
