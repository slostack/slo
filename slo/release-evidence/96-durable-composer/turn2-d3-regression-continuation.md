# Turn 2 dispatch 3 — regression continuation

Status: **READY for Step1 author handoff only**. Three regression signatures causally corrected and repeatedly verified; required execution/static gates pass. No independent acceptance or feature-completion claim. Fresh explicit user continuation, not a retry of aborted dispatch2. No commit, staging, agents, workflow launch, publication, package or host changes. Branch `message-queue`. Independent complete final review and separate completion by requested `gpt-6-astra/medium` remain mandatory; this report is author evidence only.

Counters carried without reset: **2 turns started / 0 complete; turn1 partial15 dispatches; turn2 active partial dispatch3/20; max60 turns; zero execution retries per carried ledger**. Dispatch2 was aborted, not retried. Local verification runs do not increment workflow turns or dispatches.

## Scope and plan

Only original DC01–09 under `/root/Code/specifications/projects/slo/specifications/96-agent-message-queue/revised/01-durable-composer/` govern. Preserve the acceptance-routing.md requirement map and earlier reports. Bounded plan: inspect prior three synchronization changes and actual owner contracts; three independent complete-file parallel runs; exact full regression gate; broader affected regression; lint/cumulative Black/diff/coreutils; durable handoff. No speculative production repair or harness expansion.

Read current SLO.md, README relevant primer/runtime/testing/maintainer sections, ancestor discovery, Makefile/pyproject, supported shared MEMORY, routing/handoff/ledger/turn2-repair/final-review, installed INDEX/exact workflow/shared workflow, engineering routing/testing/ownership, generic solution-design/coding-rules/naming/design/declarative/testing/cadence, Python root/style/import/application-service and graph-test recipes, Textual build recipe. KB Welcome -> slo README/gotchas/conventions/environment/TUI session consulted. Historical KB environment advice yields to live Make fallback. Root RESEARCH absent; do not recreate per scoped routing. No new layer/API/domain/client implementation was written.

## Recovered dispatch2 evidence and causal inspection

Bounded event inspection of `/root/.slo/sessions/history/4e787677-8628-4d65-8b58-389282819938/events.jsonl` (1714 lines): actual edits at sequences418,425,431,442,486,493; final full-suite call1713. seq425's temporary diagnostic waiter was removed by431, not left as a leaking extra task. d2 focused47pass/40warnings and affected3383pass/538warnings, both exit0. **d2 full.exit=141; log ends83%, no summary. NOT passing**, regardless of `.finished` presence. Historical failures in turn2-repair stay preserved.

Read-only process check: aborted3955111/1668825 absent; no children of interactive1436671/2763212. External1959631 and stale unrelated1261413 present; neither touched. No process killed.

### Overflow replay (DC03.A5)

Original failing oracle waited for `_hydrated`. `ChatTranscriptComponent._present_history_tail` sets that flag BEFORE awaiting each tail mount and BEFORE publishing `_load_older_cursor` (`component.py:1166–1183`). The third session read counter also advances before presentation. Thus the old test could see started hydration with cursor0 and compare an incomplete ID map. Prior seq418 joins `transcript.handle(HydrateTranscriptDAO())`: real `hydrate` acquires `_hydration_lock`, which the active hydration owns through complete tail projection. Only then does the existing paging loop run. No private collaborator swap, fabricated identity, direct SQLite patch, extra sleep or relaxed assertion. Both real257-event overflows remain; every admission must reach applied, exact set of all514 IDs, no conflicts, live observation and no unavailable notice are unchanged. Production `app._observe_session_messaging` still subscribes before barrier replay and repeats recovery on replay_gap.

### Precise scroll unequal axes (regression supporting DC09.A6)

Old polling could miss the short interval after one-cell x completes while page-sized y remains moving, particularly if a worker is descheduled. Prior sequences442/486/493 pause the **real native animator timer at each released start callback before yielding**, not application layout or callbacks. They evaluate the actual registered Textual SimpleAnimation objects at x's completion time; x must finish and y must NOT finish. The actual x completion callback runs and the original x==1/intermediate-y/pending_axes=={'y'} assertion remains. Resume uses the real timer and Pilot animation completion; both covering-callback orders, duplicate/stale callback behavior, final painted reading row, later-growth row stability, final x and retired navigation remain. This deliberately controls native tick timing; it is not proof of arbitrary real-time scheduling or a replacement production animator. Existing OrderedTranscript injection remains via TranscriptTestApp constructor; no application collaborator is replaced. Framework timer/animation introspection is local native-order instrumentation, not dependency injection by private swap. Complete independent review must assess this scope honestly.

### Herdr registered_abort streaming (regression supporting DC09.A6/DC08 compatibility)

`/new` schedules session preparation asynchronously. Shutdown cancels that owner; if the test starts shutdown before a ready successor, `_run_prompt` can refuse before the held Faux delta and its streaming gate never opens. Prior seq425 awaits real public `current.prepare_startup()` and asserts ready before arming shutdown. The method serializes duplicate callers through its preparation lock and returns only after atomic ready adoption. No fabricated `_preparation_status` or replaced preparation worker. All28 existing cutoff combinations remain, including real streaming abort, registered task join, original-store bytes/ack, no displaced writes, lease/reporters/timers/current+retired cleanup and persistent cancellation assertions. Existing historical patch-heavy harness is unchanged; this continuation does not claim to have independently audited or converted it.

No production changes were needed after this inspection. This dispatch changes only two whitespace regions in `tests/tui/test_chat_transcript_precise_scroll.py` to satisfy current Black. Other two test changes are inherited from dispatch2. No new RED is claimed: failures and pre-correction code are in prior receipts/events; this dispatch validates the existing causal corrections, not a new behavior change.

## Verification receipts

Cwd `/root/Code/slo-message-queue/slo`; `VIRTUAL_ENV=/root/.pyenv/versions/slo-harness`, matching PATH prefix. Focused env exactly acceptance-routing synthetic exports including PYTHONPATH=$PWD, test modelgpt-5.4, disabled Herdr/visualization and placeholder credentials. Full Make command unchanged fallback. Direct command redirection captures actual status (no tee/SIGPIPE ambiguity); `.command`, `.started`, `.finished`, `.exit`, `.log` receipts under `logs/turn2-d3-*` where applicable. No extra exclusions/waivers; no real provider/e2e authorization.

| Gate | Result |
|---|---|
| `poetry run pytest tests/tui/test_composer_transcript_identity.py tests/tui/test_chat_transcript_precise_scroll.py tests/tui/test_herdr_all_owner_cutoffs.py -n 6 -m 'not e2e' -q`, independent runs1/2/3 | each exit0,47passed/40warnings;54.50s/54.47s/54.15s |
| `make test PYTEST_WORKERS=6` | exit0,12269passed/1265warnings,516.63s;08:51:04–08:59:43Z |
| `poetry run pytest tests/tui/ tests/agents/slo_agent/messaging/ -n 6 -m 'not e2e' -q` | exit0,3383passed/538warnings,258.96s |
| `make lint` | exit0,980source files clean |
| cumulative `poetry run black --check <all changed/untracked Python>` | initial exit1: precise-scroll formatting only,58other files clean. Fixed whitespace only; final exit0,59files clean. Exact inventory `logs/turn2-d3-black-paths.txt` |
| `poetry run pytest --collect-only -m 'not e2e' -q` | exit0,12269/12290collected,21project e2e deselections;3.93s; collection not execution |
| `git diff --check`; `dpkg -V coreutils`; `make test-env` | exit0; first two no output; fallback |

No skips reported by executed suites. Warnings remain in logs, including pre-existing unawaited AsyncMock runtime warnings in Herdr tests; not a warning-free claim.

## File inventory and remaining gates

Cumulative status captured in `logs/turn2-d3-file-inventory.txt`; cumulative Python paths in Black inventory59files. Preserve README/SLO/user docs and all prior production/test edits. No README selection/staging decision made; feature README hunks must later be distinguished from user edits. Prior FR01 closed-wins, FR02 bounded observed tasks/sticky first failure/sibling joins, FR03 public replacement stay implemented and exercised by affected/full suites, but independent audit remains open.

Final-code confirmation after the whitespace-only correction: `logs/turn2-d3-final-focused.*` exit0,47passed/40warnings,52.07s; **`make test PYTEST_WORKERS=6`** in `logs/turn2-d3-final-full.*` exit0,**12269passed/1267warnings,627.91s**,09:08:22–09:18:52Z. Final `make lint` exit0/980files; `git diff --check` and `dpkg -V coreutils` exit0/no output (`turn2-d3-final-{lint,diff,coreutils}.*`). Thus the final full run is on the exact final Python content, not only the pre-format content. Cumulative Black59 remains clean. No failed executions in this dispatch; initial Black failure is preserved, not overwritten. Author diff inspection covered the complete inherited three regression corrections and corresponding production owner code; it is not independent review.

Acceptance routing and compact handoff/ledger current pointers now refer here; historical reports and findings remain unchanged. No original acceptance ID was renamed, split, deferred or waived. DC03.A5 and DC09.A6 regression blockers now have passing author evidence; the rest of the original requirement-to-evidence map remains in acceptance-routing and dispatch12/14, subject to the still-required complete independent adequacy audit. Independent final review must finish the entire original DC01–09 source/assertion/hard-rule audit, not merely FR01–03 or these three synchronization cases; preserve final-review.md's incomplete verdict/history. Separate independent completion only after accepted review. No commit in this task.
