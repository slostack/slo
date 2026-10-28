# T2 reporter increment — NOT READY

2026-10-18. Reporter scheduling now exists in `src/agents/slo_agent/herdr/reporter.py`, with a lazy service export. No enabled session assembly. This is a substantial tested increment, **not complete scoped acceptance**: the complete B7.11/B7.13 matrix is not established. No full-suite run while the parallel transport writer is active.

## Ownership and implementation

Only reporter support, the service export, `tests/agents/slo_agent/herdr/test_reporter.py`, and reporter receipts were written in this lane. Transport/guard/DAOs/sequence were not edited. Source specifications, routing/scope-plan, shared workflow state, credentials/global state and worktrees were untouched. No commit or agent dispatch.

One pending/latest immutable publication, one saved capture, one save task, one reservation task/ticket, one admitted ticket and one binding. The worker saves off-loop, adopts exact generation/capture, continues with latest display, and consumes its own adoption wake. Every command goes through durable source reservation and the actual shared transport's synchronous admission. Semantic lifecycle and restore acknowledgements are separate from final-patch display acknowledgement. Stale admitted effects are retained without acknowledging newer desired state.

Activation release precedes worker/refresh creation. Two-second refresh retains revision; metadata carries TTL 5000. Close revokes ordinary/viewer permission, joins producers, attempts bounded remote release, then leaves local lease for transport close. Final local close is cancellation-shielded. C29 retired drain is separately cached, local-only, and permanently uncertain. The canonical inventory is derived from the existing `HerdrDisplayKey` literal, avoiding an unauthorized DAO edit.

## Actual cadence

Python 3.11.7 verified using `/root/.pyenv/versions/slo-harness/bin` PATH prefix. Each command used `bash docs/implementation/94-herdr/t1-dao-check.sh tests/agents/slo_agent/herdr/test_reporter.py`, with the wrapper's fake-only test environment and DAO/projection surroundings.

`reporter-NN-red.log` / `reporter-NN-green.log` retain executed failures and successes for 01–24:

| Increment | RED → implemented behavior |
|---|---|
| 01 | missing module → inert bounded slots |
| 02 | missing publish → synchronous coherent generation admission/revocation |
| 03 | missing save → exact immutable capture association |
| 04 | missing selection → reuse/ineligible/refused save handling |
| 05 | missing reservation → real durable source reservation and fail-closed state |
| 06 | missing policy → exact binding/currentness |
| 07 | missing commit → possible binding and reference preservation |
| 08 | missing admission → identity-based one-shot lock authority |
| 09 | missing acknowledgement → semantic versus final display acknowledgement |
| 10 | missing accounting → stale effects/rollback/duplicate terminal refusal |
| 11 | missing builder → lifecycle/release/opaque restore argv |
| 12 | missing metadata → patch bounds/inventory/TTL |
| 13 | missing bridge → refused admission cannot be reused |
| 14 | missing send → real guarded CLI claim and accounting |
| 15 | missing report steps → actual claim/display/deduplication |
| 16 | missing batch → bootstrap claim/install/display order |
| 17 | missing shutdown → release then two inventory clears |
| 18 | missing close → cached revoking remote shutdown |
| 19 | missing final drain → seal/drain/unlock and C29 cache |
| 20 | missing activation → actual activation release/idempotence |
| 21 | behavioral cancellation failure → final transport-close task retains unlock ownership |
| 22 | missing builder/destination → inert gate and failed activation classification |
| 23 | missing public export/diagnostic → lazy export and fixed sink-isolated diagnostics |
| 24 | missing viewer refusal → inactive viewer refusal and later local construction seam |

Implementation increments were kept small (approximately <=50 substantive lines). 10's first green attempt exposed an accidental extra required parameter from an overbroad insertion; `reporter-10-green-final.log` is the corrected gate. No failure receipt was overwritten. G1/G2 and extra close evidence were added after implementation and passed immediately; they are **not RED receipts**.

## Executed branch evidence and remaining B7.11/B7.13 obligations

| Owner/method group | Executed evidence | Missing acceptance paths |
|---|---|---|
| constructor/publish/validation/revoke/currentness | initial/equal/new/lower/changed capture/closing/disabled/revoked; no writes | changed same-generation session identity; complete all-family suppression matrix |
| save/match/adopt/selection/finish | exact association, reuse, ineligible, failure without reference; actual thread-barrier G1 with newest display and single save | changed configuration barrier; repeated cancellation/error-during-cancel; failed save with installed reference + uncertain release |
| pending/worker/consume/batch | adoption wake consumed; actual bootstrap order | full wake/close matrix, existing working/settlement/display-failure exact command logs |
| reserve | real independent durable sources, unsafe store refusal | fsync/overflow/cancel reservation composition; unsafe-after-claim no release |
| admission/policy | valid/wrong/lease/unsafe/stale/closing/activation; exact binding cases | full restore mismatch and all-ticket variants |
| shutdown policy | valid/token/not-closing/no-deadline/expired/used/wrong-binding/clear-before/clear-after | real deadline during reservation; failed first shutdown patch |
| mark/possible/account/result | claim/restore/activation/shutdown; current/stale/rejected/spawn-failed/duplicate | prior possible reference rollback and full uncertainty compositions |
| acknowledgement | current/stale/partial/final/failed | stale-generation restore, full semantic lifecycle retry matrix |
| builders/send | real CLI, opaque restore, explicit clear/set bounds and TTL | plain `slo` PATH validation is not implemented; full blocked/invalid payload matrix |
| activation/start/refresh | real activation release/idempotence; invalid binary unavailable | refresh fake-clock proof; contention, close-during-acquire and failed release variants |
| close/final drain | unstarted cache, actual lease retained until seal, final cancel drains, retained/late-drain/unlock-error | repeated cancellations with saves/reservations/start pending; persistent local drain session composition |
| diagnostics | fixed category, rate limiting, throwing sink | recovery diagnostic and complete failure-category wiring not implemented |
| viewer/build | disabled zero I/O, inactive refusal, live predicate | active viewer depends on later T4 module; default restore depends on T3 |
| G1 | actual off-loop barrier store plus real CLI latest display | changed-capture companion remains |
| G2 | actual viewer child holds actual transport lock; A durable/queued; B supersedes before release; executable log contains viewer+B only, B sequence > A; same and changed generation | close/cancel/timeout/already-admitted variants remain |

G2 uses a real temp-owned registered executable and an explicit barrier, not a mocked invoke acceptance oracle. An observation wrapper only signals entry into the original transport after the real reservation. The fake child polls the explicit file barrier; parent synchronization proves actual entry and actual queueing. G1 uses a threading Event barrier around the injected synchronous store and actual transport execution. These are offline fixtures, not live Herdr compatibility.

## Gates

- `reporter-surrounding-final.log`: **246 passed, 2 warnings, 15.65s**, Herdr package plus wrapper DAO/projection baseline; exit 0.
- `reporter-black.log`: reporter + reporter tests **2 files unchanged**, exit 0.
- `reporter-static-final.log`: scoped mypy reports **6 errors in 3 imported provider files**, none in reporter. This is **not a green lint gate**; baseline remains unwaived.
- `reporter-coreutils.log`: `dpkg -V coreutils` silent, exit 0.
- `git diff --check`: clean.

No full suite, live provider, real Herdr, terminal window, enabled session assembly, independent review or completion approval. Test helper annotation/docstring completeness still needs review. Service lazy export avoids import cycles but should be reviewed for the eventual assembled static import surface.

## Handoff

Finish the listed gaps before READY. In particular: executable/PATH validation, diagnostic recovery/wiring, complete close cancellation/resource branch coverage, save-refusal withdrawal composition, and G2 variants. Do not interpret the working scheduler or surrounding green as all-method acceptance. Existing T3/T4 collaborators remain separate; this worker did not implement them.

Task accounting preserved as supplied: turn 1, dispatch 11 consumed / 9 remaining of 20, unlimited turns, 0 retries. No dispatch made by this lane.
