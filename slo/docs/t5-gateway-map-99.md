# T5 gateway policy/map 99 — INCOMPLETE

Test-only continuation, same unfinished turn 1: started 1, completed 0, historical partial 1, supplied dispatch 99, retries 0. User turn/dispatch budgets unlimited; no agents dispatched. Production, other existing tests, shared status, canonical specifications, global state and other worktrees untouched by this continuation. Lifetime barriers remain the parallel lane, not silently reassigned here.

## Delivered

- `tests/agents/slo_agent/herdr/test_session_visualizer.py`: exact complete observed split/rename/run argv, captured owner, no focus/query/close, no private temp path in pane commands. Existing real-session positive/attached/selector cases retained.
- New `tests/agents/slo_agent/herdr/test_session_visualizer_policy.py`: six unsupported-owner cases (headless, custom root, noncanonical owner, history disabled, custom system/append prompt); seven evidence cases (valid private context, directory context read error, wrong-session event, mixed events with exact matching parent, history OSError, resolution OSError, PATH OSError). Real config-backed sessions, temp metadata/context/events and registered executable; factory replaced with repository Faux fixture before construction. No production fix or fake-only positive.
- Public gateway outcome/diagnostics and actual command capture exclude the private context sentinel and history/context paths. Construction logs are explicitly outside the gateway diagnostic window; they already log cwd. This is not a claim that all application logs suppress cwd.

## Finite whole-gateway map

| Actual decision | Evidence / remaining scope |
|---|---|
| Canonical requested parent before I/O | Existing invalid case; T1 canonical schema/identity matrix reused, not duplicated |
| Native owner interactive/history/default root/canonical identity | New six-case owner policy; existing config-history mutation and default-root drift |
| Injected owner | Still missing explicit composed gateway case; capture-only tests do not close it |
| Reproducible policy | New custom system/append refusal; exact standard-bootstrap success and subsequent tool/provenance mutation still need gateway composition |
| Closing/capture/viewer/destination/reporter authority | Existing closed/revoked cases; replacement identity and each awaited-boundary close/cancel belong to lifetime lane |
| Fresh actual store root equals canonical default | Existing default_changed; new custom-root refusal. Concurrent mutation belongs to lifetime lane |
| Persisted metadata and exact requested identity | Existing missing/corrupt/wrong-ID/OSError cases |
| Resolved workdir equality | Existing mismatch; new resolution OSError case patches Path.resolve and therefore fails at the earlier root resolve, NOT separately at metadata.workdir.resolve. Specific metadata-workdir failure remains unproved |
| Plain slo PATH presence | Existing absent and new OSError; positive native fixture creates contained regular candidate. Blocking cancellation/thread ownership belongs to lifetime lane |
| Valid private context | Existing valid/corrupt/absent; new real context and directory read error; reader suite retained |
| Attached event alternative | Existing attached/ordinary; new wrong-session and mixed exact-match event files; new load-events OSError |
| Final eligibility + viewer identity recheck | Existing reporter revocation; identity/mutation barriers explicitly lifetime lane |
| Delegate to same transport | Existing identity assertion and actual registered CLI positive |
| Exact wire/no focus/no OS fallback | Strengthened complete argv on valid/attached/selector_valid; selector skipped and new policy/evidence cases forbid platform launch |
| Selector auto-off/platform/herdr/unavailable | Existing `test_destination_selector`, platform root guard/result/error/join tests run; actual config-backed selector positive/skip retained. New owner_slug proves unavailable -> failed, direct gateway -> skipped |
| One-shot transport/parser/reuse/admission | T4 `test_visualizer.py` and surrounding Herdr suites reused; no duplicated all-matrix |
| Privacy | New context/error sentinel and gateway log/command/outcome scans. Expanded private config paths, subscriber events and sequence-state scans remain unproved in this bounded gateway file |
| App scheduling/late notices/platform committed-thread lifetime | Parallel lifetime/app lane; no claim of closure from this policy pass |

No invented process-liveness, focus, or source-fallback requirements. `submitted` is input admission, not viewer paint. A complete finite map is provided, but its remaining rows prohibit READY.

## Read closure (honest boundary)

Read handoff 98, actual session gateway/capture/provenance predicates, selector and reader, existing session gateway tests, native Faux/registered fixture, reader tests; routing.md, scope-plan.md, root RESEARCH and Makefile. AGENTS/CLAUDE/docs RESEARCH supplied in context, not fully reread from disk here.

Canonical D read completely in bounded ranges 1–400 and 401–711, including 7.3/7.5. Canonical C eligibility/provenance 625–755 read; complete affected C corrective/lifetime material not freshly closed. Exact tasks D01/D02/D03/D08 read at 3590–3678. Accepted independent-review-turn4 read completely; other accepted-review artifacts not freshly closed.

Read engineering routing/testing/ownership, coding rules/cadence, Python root/application service/Faux/declarative, workflow SKILL; shared declarative body was returned after an oversized concatenated read. DAO recipe read 1–500 only (remaining model examples outstanding). KB README/gotchas read; initial KB Welcome prefix was truncated in concatenated output and is not claimed complete. Other requested build/style material and actual-doc fresh closure remain outstanding. Historical routing-plan reads are NOT substituted for this continuation's missing reads. Thus required READ closure is INCOMPLETE, not inferred from passing tests.

## Executed receipts

CWD `/root/Code/slo-94-herdr-integration/slo`. Approved `PYENV_VERSION=slo-harness`: `pyenv which python` resolved `/root/.pyenv/versions/slo-harness/bin/python`, Python 3.11.7. Pytest uses `bash docs/implementation/94-herdr/t1-dao-check.sh <suffix>`; mandatory DAO/projection cases included. No venv/package changes.

All logs/exits below under `docs/implementation/94-herdr/`:

| Receipt | Actual result |
|---|---|
| t5-99-initial | 79 passed, 2 warnings, exit 0 |
| t5-99-wire | 3 failed / 76 passed: incorrect new test expectation appended --json; actual documented wire omits it. Corrected test only |
| t5-99-policy1 | 1 failed / 84 passed: owner slug selector expected skipped; actual unavailable destination correctly yields failed. Corrected selector expectation; added direct gateway skipped assertion |
| t5-99-policy2 | 68 passed, 2 warnings, exit 0 |
| t5-99-evidence | 75 passed, 2 warnings, exit 0 |
| t5-99-surrounding | 1602 passed, 137 warnings, exit 0, after Black formatting |
| t5-99-black | two owned files unchanged, exit 0 |
| t5-99-diff | git diff --check silent, exit 0 |
| t5-99-coreutils | dpkg -V coreutils silent, exit 0 (also silent after each focused run) |
| t5-99-mypy | exit 1: 9 errors / 6 imported files, zero diagnostics in either owned file; no ignores |

Surrounding suffix: `tests/agents/slo_agent/herdr tests/agents/slo_agent/orchestrator/test_context_reader.py tests/agents/slo_agent/test_session.py tests/tui/test_herdr_visualizer.py tests/tui/test_visualizer_launcher.py tests/tui/test_workflow_visualizer_loader.py tests/tui/workflows tests/tui/test_workflow_receive_path.py tests/tui/test_herdr_session_lifecycle.py`.

Mypy command: `PYENV_VERSION=slo-harness poetry run mypy tests/agents/slo_agent/herdr/test_session_visualizer.py tests/agents/slo_agent/herdr/test_session_visualizer_policy.py`. Remaining diagnostics: yaml stubs, transcript_projector, Faux, chunk normalizer, Anthropic, Codex. Historical full baseline 298 errors/63 files remains unwaived; not rerun or described as green. Full make integration gates remain later, per request. No new production RED retained; both initial failures were incorrect new expectations, with original logs preserved.

## Next closure, without expanding scope

Finish explicit injected-owner and supported/mutated provenance gateway composition; distinguish metadata-workdir resolve failure from earlier root resolve; complete requested privacy channels/private-config path checks and required read ranges above. Re-run affected gates after those changes. Merge evidence with the lifetime lane only after its barrier verdict, then full integration/review gates. This receipt is neither family acceptance nor independent review.
