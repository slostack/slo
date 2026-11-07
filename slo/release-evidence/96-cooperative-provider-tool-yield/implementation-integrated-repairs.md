# 96.A.2 integrated repairs — dispatch18

**Runnable repairs delivered; Step1 NOT READY / full gate BLOCKED.** This is author evidence, not independent review/completion. 2026-11-04. Branch message-queue HEAD82c3f5c6de9345af34a673a3d975366ca8c1624c unchanged. Counters supplied: turn8 dispatch18/20,total66;8started/0completed/allpartial;12 historical execution retries/no aborts. No nested agents/workflows, retry reset, new turn, or parent-environment claims. Two dispatch calls remain reserved for gates/closure.

Original 1309-line specification and all197 lines of early-review-integrated-yield.md govern. Reused accepted UJ01–04/cutoff/append/raw closures. README first, actual SLO/Makefile and installed routing/workflow/shared/Python/Textual guidance consulted; no graph topology/pool/spawn restart. Root RESEARCH remains absent/protected; unrelated SLO/docs/durable-composer preserved. Preflight hash unchanged10fe2372f972374580d6071578c543edad98fd811a43ce2b0857cdb282183638.

## Stable IY closure map — honest bounded disposition

| ID | Delivered behavior / evidence | Exact remaining limitation |
|---|---|---|
| IY01 | ModelPool checks retained task cancellation authority BEFORE cooling/switching in async generation/stream catch. Real session+SQLite+real pool held cleanup raises RemoteProtocolError/ReadError: fallback0, one original application, fixed settlement failure, pending retained, exact joins. Ordinary pool fallback tests rerun. | Cleanup test uses normal existing catalog retry budget, not a specially pinned low budget (the earlier attempted SessionConfig keyword was invalid/ignored by runtime and removed). Separate low-budget exhaustion proof exists. No claim this is the entire requested low-budget cleanup configuration. |
| IY02 | All agent delegated event iterators retained and explicitly closed through cancellation-resistant close barrier, including invoke→execute→react→retry→graph. Public live-chunk close test holds cleanup, refuses competing invocation before join, cancels close waiter twice, verifies closeonce. Strict no-orphan fixture passes. Real session downstream run_retrying persistence failure proves one provider/no new claim/pause; normal borrowed-client/observer detach preserved by affected suites. | Session consumer test reaches retry-status persistence AFTER provider failure, not a held active provider at downstream consumer failure. Public held-close proof covers the actual chain separately; do not promote combination to the exact requested single scenario. |
| IY03 | Watchdog rearbitrates abort after joined reserved-reader cleanup, AFTER settlement-failure check. Real held cleanup→abort→release: exactly one persisted/public aborted; no completed/new application; accepted pending retained. Supplemental failure variant proves cleanup failure beats abort. | No known behavioral remainder at this named seam; independent acceptance pending. |
| IY04 | Tool widget/buffer/dedup keyed by (attempt,iteration,callID); interrupted delta/end ignored, exact result routes to live successor. Mounted same-ID reuse retains incomplete predecessor, distinct successful successor/result and no stale repair. | Mounted proof observes public result_output and final paint; detail output is naturally collapsed, not falsely required on-screen. No known product remainder. |
| IY05 | Synchronous optional requested sink publishes at reservation before held cleanup joins. Canonical requested audit still transferred/awaited only at settlement. Interruption carries same typed metadata as canonical interrupted audit. Stream validator rejects disposition/reason/attempt mismatch; session validates/stamps public attempt and runtime metadata. Four real silent/partial×flat/tree tests compare requested/interrupted stream metadata to canonical audit and runtime attempt stamps. | Validator permits legacy unmarked cooperative events for existing direct projection compatibility. No new strict requirement that every manually constructed legacy notice carry metadata. Runtime conflicting-attempt branch has source guard but lacks its own explicit injected negative integration test. |
| IY06 | Removed parallel `_subscribers` strong-reference list; mailboxes are sole bounded authority. Capacity pruning releases joined retired registrations; final close joins then clears mailbox/dispatcher refs.70 failed subscriptions weakrefs release (at most last mailbox until prune; none after finalclose). Existing suppression/unsubscribe/budget/count/byte tests rerun. | Weakref repetition covers automatic failure; expiry/overflow release rely on same retirement/pruning owner plus existing mailbox tests and new whole-session overflow route, not separate70-repeat weakref matrices. |
| IY07 | New graph transport/completion behind GraphEventStream class-owned invoke/retain operations, existing one updates driver/public callbacks unchanged. Concurrent executor split meaningful validate/preflight/register+join operations; policy joined terminal truth selection extracted; agent live/completed decoding extracted. Required supported keyword calls fixed. Public bind/release/invoke/build/executor/control docs extended; new significant types and test bare containers corrected. Scoped18 Black/mypy clean. | Expanded `_stream_graph_turn`, policy `_settle` temporal acknowledgement closure, and register+join batch still sizeable. This is a bounded improvement, not a claim all requested declarative decomposition/whole changed-seam convention closure independently satisfied. |
| IY08 | Representative controlled later-boundary empty/note/both rate retry freezes delivery and context/highwater, no newer urgent early claim; existing instruction/factory/prebuilt/rebuild evidence rerun. Production lazy external-provider-only substitution proves retry→urgent with one model build/bind. Real pool pinned catalog budget1/waitcap1 exhausts after one call/member, one source selection, pending retained. Whole-session failed and byte-overflow subscriber cases prove canonical defer→actual result→urgent application→terminal independent of retirement, joinedclose. | Exhaustion proof does NOT explicitly instrument retained control/policy/mode/tool/outputqueue identities or childpool/spawn construction counters. Existing retained instruction binding proofs reach control/policy/source and ordinary pool/unchanged spawn proofs retained. Exact remaining IY01/02 configuration/scenario gaps above also belong here. |

No paint-before-next-request/render-ack or palette-search blocker invented; execution never awaits paint. No optional wishlists added.

## Test chronology and exact commands

Cwd every command `/root/Code/slo-message-queue/slo`. tests.env absent; tracked Makefile fallback used:

```
export SLO_ENV=test SLO_ROOT_DIR="$PWD" SLO_APP_DIR="$PWD" SLO_APP_NAME=slo
export SLO_LOG_FORMAT=text SLO_DEFAULT_MODEL_NAME=gpt-5.4
export SLO_ANTHROPIC_API_KEY=ci-placeholder-tests-are-fully-mocked COLUMNS=120 LINES=40
export SLO_AUTO_VISUALIZE=0 SLO_HERDR_DISABLED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD"
/root/.pyenv/versions/slo-harness/bin/python -m pytest -p no:cacheprovider -q <args>
```

All logs under `logs/`, prefix `integrated-`. Shell wrappers printed pytest exit explicitly; wrapper exit0 alone is NOT pytest success. F=tests/agents/slo_agent; I=tests/integration/test_messaging_yield.py; P=F/tool_execution/test_yield_policy.py; L=F/test_graph_stream_lifetime.py; R=tests/integration/test_yield_retry_identity.py; S=tests/integration/test_yield_session_failure.py; T=tests/tui/test_urgent_projection.py; M=F/history/test_cooperative_yield_metadata.py.

| Log | Exact args after runner | Pytest exit/result |
|---|---|---|
| pool-red | I -k pool_cleanup |1/2failed22deselected, actual fallback requests after cleanup |
| pool-green | same |1/2failed22deselected; product assertions pass, stale SQLite retained oracle0 vs actual1 |
| pool-green2 | same |0/2passed22deselected |
| public-red | L -k public_consumer |1/1failed1error6deselected; invalid agent.is_running oracle AND actual leaked delegates (strict teardown failure retained) |
| public-red2 | same |1/1failed1error6deselected; actual close task already done before held cleanup; strict cleanup-required remains failure |
| public-green | same |0/1passed6deselected after explicit delegated closure |
| abort-red / abort-green | I -k abort_during_reserved |1/1failed24deselected timeout waiting correct abort; then0/1passed24deselected |
| registry-red/green/green2 | P -k automatically_failed |1/1failed41deselected each: fixture construction omitted required config; NOT product RED. A preliminary product edit preceded valid RED, then parallel-list source was restored for valid regression. This process deviation is disclosed, not retrospectively compliant. |
| registry-red2 | same |1/1failed41deselected actual70 retained handlers |
| registry-green3 | same |0/1passed41deselected after sole-registry/finalclose release |
| tools-red | T -k same_tool |1/1failed2deselected actual one widget instead of two |
| tools-green | T |1/1failed2passed; ownership asserts green, overstrong collapsed-output paint oracle |
| tools-green2 | T |0/3passed after public result_output + final paint oracle (no product weakening) |
| requested-red/green | I -k requested_notice |1/1failed25deselected reservation notice absent; then0/1passed25deselected |
| metadata-red | M -k stream_rejects |1/3failed8deselected actual contradictions accepted |
| metadata-green | M |0/11passed |
| correlation-red/green | I -k silent_provider |1/4failed22deselected missing stream metadata; then0/4passed22deselected |

Supplements/refactors (no invented RED): checkpoint78pass; executor-refactor92pass; lazy-proof R5pass; subscriber-proof I -k retired_subscriber2pass26deselected; consumer-proof S2pass; refactor-proof I L F/tool_execution127pass; abort-precedence-proof I -k abort_during_reserved2pass27deselected. All exit0. Cached slots supplement initially used RemoteProtocolError causing legitimate session reconnect/excluded failed-turn context, so full-context-equality oracle was wrong for that scenario. Switched external error to rate-limited within-iteration retry; two runs timed out because retry text did not match existing `in Ns` parser (no product change); slots-proof4 R -k cached_slot exit0/3pass5deselected6.31s. Pool budget supplement: proof1 invalid entry.runtime attr; proof2 absent seeded mini entry; proof3 generic HTTPStatusError not recognized as pool-disconnection (no retry); corrected external scripted disconnection and explicit synthetic fallback catalog entry; proof4 R -k real_pool_exhaustion exit0/1pass8deselected3.30s. These are disclosed test-author corrections, not product RED.

## Final serial affected gates

**integrated-core-final3.log** exit0 **807passed421warnings102.55s**:
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
tests/agents/providers/test_model_pool.py
```
Prior core-final806pass103.38s/core-final2 806pass104.04s superseded; final adds abort-cleanup-failure case. No sums presented as full gate.

**integrated-agent-final2.log** exit0 **185passed82warnings11.54s**, F/{test_agent.py,test_graph.py,test_agent_recovery.py,test_agent_runtime_event.py,test_agent_streaming_dual_mode.py,test_agent_usage_commit_regressions.py,test_agent_image_history.py,test_graph_stream_parser.py,test_stream_event_dao.py}. Supersedes first185/11.74s before decode refactor.

**integrated-tui-final.log** exit0 **412passed155warnings339.62s**, exact prior411 scope plus new same-ID regression:
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
TUI run predates only behavior-preserving core decode extraction, typing/docs and supplementary core assertions; no TUI source changed afterward. Final core/agent gates cover extraction. Original411/752/185 retained as historical, not current-byte certification.

**integrated-mypy-final2.log** exit0/noissues18files; **integrated-black-final2.log** exit0/18unchanged; **integrated-diff-final.log** git diff --check exit0. Exact18 path+SHA256 manifest `logs/integrated-source-sha256.txt`; invocation `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD /root/.pyenv/versions/slo-harness/bin/python -m mypy <all18paths>` and same Python `-m black --check <all18paths>`. Earlier mypy8errors (accidental unrelated hash-map annotation, missing error import, explicit provider constructors, invalid extra config keyword), then2errors AIMessage script type; fixed without ignores/waivers. Scoped formatting touched only owned files; no full static claim.

## Safety / cleanup / remaining gates

All tests foreground synchronous/serial, no workflow/container/real-child fixture/executable stub added. Existing contained Bash tool test runs actual bash but writes no executable; ordinary child execution is not independently forbidden (user correction). Only verified tmp-root paths for files/SQLite/history/auth. Strict isolated task cleanup remains enabled and fails if cleanup was necessary; successful final core includes it. Held gates released and client/session/generator tasks joined in finally. All foreground commands returned; final process survey has no owned pytest/mypy descendants; unrelated1261413pytest/resource_tracker/3382468fake-herdr and other checkouts untouched. No process signal/system/package/installed-executable/harness setting mutation. No commit/push/merge/PR.

Full `make test PYTEST_WORKERS=6` remains BLOCKED by known unauthorized executable-fixture creation/chmod; not run/excluded/skipped/xfailed/waived/substituted. Old C3/C4 broad permission requests are superseded: contained non-executable data chmod and child execution are NOT automatically separate blockers. Full lint/fullBlack assigned next reserved task; unrun here. Historical implementation-before-RED deviations remain unwaived. Independent final review/completion absent. Exact bounded IY01/02/05/07/08 limitations above remain for next decision; do not claim all eight fully closed or formal Step1 readiness.
