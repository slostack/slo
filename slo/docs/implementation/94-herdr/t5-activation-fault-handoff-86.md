# T5 activation fault handoff 86 — INCOMPLETE

Same unfinished turn 1: started 1, completed 0, historical partial 1, supplied dispatch 86, retries 0. Effective turn/dispatch budgets unlimited; no agents launched and no budget stop claimed. No production edits. Only the owned `tests/tui/test_herdr_activation_faults.py`, this handoff and `t5-86-*` receipts were changed by this continuation. Other lane work preserved. No commits, external actions, canonical/specification/global/KB/other-worktree edits.

## Delivered changes

Owned file now contains 20 mounted cases (previously 14):

- Existing ten `test_mounted_wire_fault_close_authority` cases now submit through real PromptInput, observe the Faux answer on the original selected session, and load real durable history to assert run_completed before replacement. This broadens original-session usability beyond the two local probes. Shutdown/clear faults are installed at shutdown, so their prompt proof precedes the cleanup fault, not after a closed session.
- Four `test_mounted_definitive_spawn_failure_preserves_prior_binding` cases distinguish activation release, first claim, restore install and shutdown release. The retained spawn coroutine raises FileNotFoundError after actual lock-held admission and explicit fake capability validation; transport accounting is real. This is injected definitive spawn refusal, NOT an actual kernel ENOENT demonstration. Other commands execute the registered temporary executable. First claim rolls back to no binding; restore rolls back to confirmed identity without a reference. Activation/shutdown release refusal remains uncertain; claim/restore followed by confirmed withdrawal permits safe replacement.
- Two `test_mounted_admitted_restore_cannot_acknowledge_new_generation` cases hold the actual fake restore command at its registered barrier, commit a real model switch, revoke subsequent admission, then finish successfully or cancel the worker. Exact old generation/reference remain recorded; restore/lifecycle acknowledgements cannot credit the new generation. Transport drains, and replacement first releases the old binding. This covers stale restore with revocation; it does not independently prove every stale release variant.
- Existing close-gateway fault cases now assert final unmount clears the retired slot, resources are drained, throwing-final-gateway recovery returns uncertain/drained, and final local cleanup sends no additional remote commands.

No production defect demonstrated. Usability and spawn coverage passed initially. Stale coverage first failed because the TEST used unsupported `gpt-5.4-mini`; corrected to existing `gpt-4.1`. This is a test-fixture correction, not a product RED/GREEN repair. No assertions weakened or skips/xfails/ignores added.

## Actual evidence map (bounded, not complete canonical certification)

Paths below are relative to tests/. Owned tests are under tui/test_herdr_activation_faults.py.

| Contract / branch | Actual test |
|---|---|
| C7.2/C7.11 preparation/executable failure leaves original prompt usable and successor suppressed | owned `test_mounted_probe_fault_preserves_original_prompt_and_suppresses_new` (2) |
| B activation release rejected/timeout, no safe empty-pane inference | owned `test_mounted_wire_fault_close_authority[reject-activation,timeout-activation]` |
| B claim rejected/timeout, possible binding then confirmed withdrawal | same `[reject-claim,timeout-claim]` |
| B7.13 A1 same-capture uncertain restore retains confirmed identity, no install ack | same `[reject-restore,timeout-restore]` |
| B shutdown release rejected/timeout forbids metadata clear and suppresses successor | same `[reject-shutdown,timeout-shutdown]` |
| B confirmed withdrawal + failed clear stays safe after local drain | same `[reject-clear,timeout-clear]` |
| B definitive spawn rollback without prior binding | owned `test_mounted_definitive_spawn_failure_preserves_prior_binding[claim]` |
| B definitive spawn rollback with prior confirmed identity | same `[restore]` |
| B activation/shutdown refusal cannot erase existing remote uncertainty | same `[activation,shutdown]` |
| B admitted stale install cannot acknowledge new generation; cancellation retains old possible effect | owned `test_mounted_admitted_restore_cannot_acknowledge_new_generation[success,cancel]` |
| C final local drain distinct from remote authority | owned `test_mounted_close_fault_after_real_drain_stays_uncertain[close,close_transport]` |
| C remote-only uncertainty collectable, suppression sticky | tui/test_herdr_activation_composed.py::test_mounted_drained_uncertainty_suppresses_successors_and_allows_gc |
| C real lease contention cannot release another owner | same file `test_mounted_contender_refuses_real_lease_without_commands` |
| C retained real lease across repeated replacements/GC, successful final drain | same file `test_mounted_uncertain_unlock_retains_one_owner_and_suppresses_successors` |
| C activation assembly/start cancellation joined before teardown | same file `test_mounted_activation_unmount_joins_repeated_cancel_without_late_claim` |
| B stale timeout/current restore batch and new-config release order | agents/slo_agent/herdr/test_restore_batch_closure.py::test_restore_uncertainty_batch |

The last five rows reuse existing evidence, not newly authored cases. Entire Herdr package and all current tui/test_herdr*.py ran in the surrounding gate. Low-level errno/transport and viewer authority proof stays with T2/T4, not replicated into an unbounded errno matrix here.

## Verification

CWD `/root/Code/slo-94-herdr-integration/slo`. Approved `PYENV_VERSION=slo-harness`; pyenv resolves `/root/.pyenv/versions/slo-harness/bin/python`. No venv created. Pytest prefix is `PYENV_VERSION=slo-harness bash docs/implementation/94-herdr/t1-dao-check.sh` (adds 62 DAO/projection tests). Existing pre-import/per-test HERDR stripping, disabled default, independent fake capability/regular-file identity/containment checks and real-terminal guard remain installed. Native factory supplies Faux and real temporary history; no real provider, Herdr or window used.

| Receipt prefix | Arguments / check | Result |
|---|---|---|
| t5-86-usability | owned file + tests/agents/slo_agent/herdr/test_session_lifetime.py | 135 passed, 14 warnings, exit 0 |
| t5-86-spawn | same | 139 passed, 14 warnings, exit 0 |
| t5-86-stale | same | 2 failed, 139 passed; unsupported test model; exit 1 |
| t5-86-stale-corrected | same | 141 passed, 14 warnings, exit 0 |
| t5-86-format | Black owned file only | formatting applied |
| t5-86-mypy | poetry run mypy --follow-imports=silent tests/tui/test_herdr_activation_faults.py | no issues in 1 source file, exit 0 |
| t5-86-surrounding | command below, after formatting | 1777 passed, 175 warnings, 353.49s, exit 0 |
| t5-86-black | poetry run black --check owned file | exit 0 |
| t5-86-diff | git diff --check | silent exit 0 |
| t5-86-coreutils-final | dpkg -V coreutils | silent exit 0 |

Surrounding arguments:
```
tests/agents/slo_agent/herdr tests/agents/slo_agent/test_session.py tests/agents/slo_agent/test_session_usage.py tests/tui/test_herdr*.py tests/tui/test_app.py tests/tui/test_queued_prompt_block.py tests/tui/test_openrouter_startup.py
```
The count includes concurrent other-lane additions; the difference from 1754 is not attributed solely to this file. Own-file mypy follows imports silently, not a full static gate. Historical 299 errors/63 files remains unwaived and not freshly reassessed. Full make/integration remains for parent integration as requested.

## Read accounting this run

Completed actual AGENTS.md 1–510/511–1013, CLAUDE.md, root RESEARCH.md and docs/RESEARCH.md 1–633; full routing.md and scope-plan.md; Makefile, pyproject.toml, .python-version and wrapper. Read actual state_isolation.py and fake spawn/terminal-related fixture sections. Full KB Welcome, slo/README and gotchas consulted read-only.

Loaded full engineering routing/testing/ownership, Python root, coding-rules, code-test-loop, shared/Python declarative, Python named arguments/docstrings, Python DAO/domain guidance, Textual guidance (including tail), Faux/agent testing, and workflow SKILL (including tail).

Canonical root read-only: `/root/Code/specifications/projects/slo/specifications/94-slo-tui-redesign/herdr`. Read C 1–230 and 1500–2175, B 1158–1347 and 1740–2221 plus targeted search excerpts; complete T5 attachments tasks.md 2401–3060/3061–3720; full accepted independent-review-turn4.md. Read actual reporter accounting 311–452, session lifetime/assembly 2280–2603, relevant composed tests, full restore batch closure and prior 85 reports. These are explicit ranges, NOT a claim of full B/C ingestion.

## Precise outstanding work — why not READY

1. Canonical read closure remains unfinished: B 1–1157 and 1348–1739 were not read in full this run (search excerpts do not count); C 231–1499 was not read in full. The exact affected clauses in those ranges, especially binding/replacement-release continuation and C7.9–7.10, must be checked rather than treating attached examples as the whole contract. Other selected routing guidance such as build-application-services was not freshly completed this run. No generic full-read claim is made.
2. The table above is not yet an exhaustive finite required-C/B integration branch map. In particular, runtime capability/diagnostic cutoffs need explicit cross-lane mapping to actual tests; persistent local-retained pending teardown needs its exact existing test and assertions audited; stale replacement-release composition needs explicit T2 reuse or a mounted test. Current stale install tests revoke follow-ups deliberately and must not be sold as proof of continuing new-generation publication.
3. Definitive spawn contrast currently proves the real transport/accounting path with an injected spawn exception, not a kernel failure from an otherwise registered executable. Confirm this is sufficient when mapping the retained T2 finite proof; do not invent every errno.

This is a prerequisite/coverage-map shortfall, not a budget stop, production regression finding, or request for expanded ownership. No whole T5/T6 acceptance, independent review, live compatibility or finite-family READY claim.
