# Turn 2 dispatch 1 — finite FR-01–03 repair

Status: **REVISE / Step1 NOT READY**. FR-01–03 author repairs verified in focused suites, but mixed parallel regression receipts remain unresolved (below). Original durable-composer DC02/DC04 contracts; no scope expansion. Formal final-review.md remains immutable and incomplete; full independent re-review then completion remain mandatory.

Counters: 2 started, 0 completed; turn1 partial (15 dispatches); turn2 active partial, dispatch1/20; zero execution retries; max60 turns. Requested Code+Test gpt-6.1-sol/medium; reviewer/completion gpt-6-astra/medium; no runtime identity attestation. No agents/workflows/publication/host/package changes.

## Bounded plan and ownership

- FR-01: adapter validates loop affinity, then irreversible closed state, then declared input; public close + unsupported regression, legitimate separate foreign-loop lifetime. No private reopening.
- FR-02: adapter owns at most four active waits. Observe each completed result and release its Task immediately; retain only the first unexpected failure for reset/close (sticky, preserving existing repeated-error assertions). Every sibling remains joined before failure/cancellation propagation; shared close remains one barrier. Clear the retained exception traceback before rethrow to avoid repeated-reset traceback growth. No silent done-task discard. Compare: retaining historical Tasks is unbounded; dropping done Tasks without observing failures restores EF02 and is forbidden.
- FR-03: audit all helper/direct client swaps in test_durable_composer.py; mounted tests await public replace_submission_binding using the existing address, isolated lifecycle tests use register. Keep all observable assertions; adapt private done-task polling to completion/failure bookkeeping where required.
- Test-first: public closed unsupported and repeated success/failure/reset/close bounded-retention sensitivity tests RED, smallest adapter repair GREEN, affected composer/retirement/protocol/registration then TUI+messaging suites, full make test PYTEST_WORKERS=6, full lint/cumulative changed Black/diff/coreutils. Exact command/status receipts in logs/turn2-*.

Environment: VIRTUAL_ENV=/root/.pyenv/versions/slo-harness and matching PATH prefix; focused synthetic environment per acceptance-routing.md, no development settings. make test uses its unchanged fallback. README/SLO/ancestor discovery, routing/handoff/ledger, full final-review and prior EF02, original DC02/DC04, installed shared/generic/Python/Textual rules consulted. Root RESEARCH.md absent; project-specific routing forbids recreation. User README/SLO/docs and independent findings preserved.

Vocabulary: submission adapter, binding, draft, outcome receiver, wait task, first failure, reset, close, retirement, sibling join. No new production interface or dependencies.

## Implemented finite closures (author evidence, not independent acceptance)

| Finding | Repair / current tests |
|---|---|
| FR-01 | `handle` pins loop, refuses closed, then checks input type. Public unsupported-open, supported/unsupported-closed, separate legitimately registered open/closed foreign-loop lifetime all asserted. No reopening. |
| FR-02 | Done callback retrieves `task.exception()` before releasing Task references; eager completion observed immediately; admissions also drain already-done callbacks before checking the four-live-wait budget. One sticky first exception replaces unbounded historical Tasks. Reset/close join captured siblings before reporting it; each rethrow resets traceback to prevent growth. Two 200-completion cases (success/failure), first100 repeated reset and next100 without lifecycle calls, assert empty Task ownership, bounded traceback and sticky identity, repeated close/reference release. Two retired-failure + held-sibling cases prove reset/close cannot skip siblings even through three cancellations. Existing concurrent-close/in-progress-failure/borrower and cancellation assertions preserved. |
| FR-03 | All10 mounted script injections in test_durable_composer.py await the real public replacement helper; helper proves fresh adapter and predecessor reference release. Isolated type/loop/closed test uses register. Existing client-failure poll now checks retained failure rather than historical Tasks (same error/reset/close assertions). Grep confirms no private client assignment or closed/closing-task reopening remains in this file. No unrelated test overhaul. |

Changed code files this dispatch only: `src/tui/components/prompt_input/adapters/message_submission.py`, `tests/tui/test_durable_composer.py`. Evidence: this report, compact handoff and ledger/routing current pointers plus logs. User README/SLO/docs and independent final-review.md untouched. Self-inspection covered full adapter and all changed test sections/callers; this is not independent review.

## Exact gates and receipts

All commands cwd `/root/Code/slo-message-queue/slo`, approved VIRTUAL_ENV/PATH above. Focused commands use synthetic routing exports. Every test pipeline uses `set -o pipefail`, saves `${PIPESTATUS[0]}` directly as matching `.exit`, no exclusions beyond project `not e2e`. Prefix `logs/turn2-` below.

| Command | Receipt / result |
|---|---|
| `poetry run pytest tests/tui/test_durable_composer.py -k 'rejects_bad_input_loop_and_closed or repeated_completions' -m 'not e2e' -q` before production repair | red: exit1,3failed/22deselected/2warnings. Concrete closed TypeError + retained completed success/failure Tasks. |
| `poetry run pytest tests/tui/test_durable_composer.py tests/tui/test_composer_retirement.py tests/tui/test_prompt_component_protocol.py tests/tui/test_adapter_registration.py -m 'not e2e' -q` | focused-green exit0:71passed/12warnings; final expanded tests focused-final exit0:**73passed/12warnings**,80.25s. |
| `poetry run pytest tests/tui/ tests/agents/slo_agent/messaging/ -n 6 -m 'not e2e' -q` | affected exit1:3382passed/1failed/538warnings,267.67s (overflow identity). affected-confirmation exit1:3382passed/1failed/537warnings,263.58s (Herdr registered_abort-True-True). No skips reported. |
| `make test PYTEST_WORKERS=6` | full-test exit2 (pytest1):12267passed/2failed/1266warnings,646.56s. Failed overflow identity and precise scroll True. Unchanged-source full-confirmation exit0:**12269passed/1265warnings,522.02s**, no reported skips. Mixed receipts not silently promoted to stable gate acceptance. |
| `poetry run pytest tests/tui/test_composer_transcript_identity.py::test_overflow_raises_replay_gap_and_host_rebuilds 'tests/tui/test_chat_transcript_precise_scroll.py::test_unequal_axes_retire_with_cover_before_or_after_native[True]' -m 'not e2e' -q` | isolation exit0:2passed/2warnings,49.97s; not a baseline proof or waiver. |
| `make lint` | lint exit0,980files clean. |
| `poetry run black --check <every cumulative changed/untracked Python file>` | black exit0,57files; exact path list black-paths.txt. Only the two edited files formatted before final focused execution. |
| `git diff --check`; `dpkg -V coreutils`; `make test-env` | diff/coreutils/final-coreutils/test-env exit0; first checks no output, test-env fallback. Final read-only diff/coreutils after collection also0. |
| `poetry run pytest --collect-only -m 'not e2e' -q` | collection exit0,12269/12290 collected,21project e2e deselections,4.22s. Collection is not execution evidence. |

## Remaining blockers / next finite work

No FR-specific focused failure is known. **Do not advance**: latest affected suite is red, earlier full suite had two failures although unchanged confirmation passed. No baseline exclusion/waiver approved; no claim these are caused by or independent of this repair without isolation evidence.

1. `test_composer_transcript_identity.py:470` overflow rebuild misses applied identity IDs under parallel run (failed affected and full; isolated and full confirmation pass). Assertion checks all514 IDs; inspect replay hydration/window/observation readiness before any correction. No assertion modified.
2. `test_chat_transcript_precise_scroll.py:74–81` True case timed out observing x==1 while y intermediate and pending_axes=={'y'} (full first run; isolation/full confirmation pass). No timing/assertion altered; no baseline claim.
3. `test_herdr_all_owner_cutoffs.py::test_all_owner_claim_pending[registered_abort-True-True]`: latest affected run times out waiting five seconds for text_delta streaming gate (observe line280; final await344). No changes to that test, harness, app or session this dispatch. Needs isolated causal diagnosis, not retry-until-green or unrelated overhaul.

The finite FR authority does not authorize a broad transcript/Herdr repair; preserve receipts and request scoped next action if these require code changes. Full independent audit remains OPEN exactly as final-review.md states, including still-unreviewed original DC01–09 coverage/hard rules. Subsequent independent review must inspect FR repairs and actual assertions, not accept counts as proof; independent completion comes only after accepted full review and clean gates.
