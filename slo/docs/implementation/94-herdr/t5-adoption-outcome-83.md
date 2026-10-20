# T5 adoption outcome 83 — INCOMPLETE activation family

Same unfinished turn 1: started 1, completed 0, historical partial 1, supplied dispatch 83, retries 0. Unlimited turns and dispatches; no agents launched. No commit, push, PR, reset, clean, stash, live/global/specification/other-worktree changes. INIT technical READY82 is preserved, not re-audited or revoked.

## Causal repair and boundary

The unchanged mounted native regression reproduced: initial claim/save/display and inbox lease transfer succeed, but the candidate is suppressed. `HerdrReporter.close()` returns uncertain/retained while its pane lease is deliberately held. `close_transport()` then returns safe/drained after confirmed withdrawal and actual unlock. Session previously ORed both replacement verdicts permanently, treating provisional resource ownership as irreversible uncertainty.

Changed only `sessions/service.py::_close_herdr_once`: returned uncertain evidence is made sticky when resources are drained. Final retained outcome still forbids replacement through the existing `final_resources_retained` check; the actual getter remains an additional conservative check. Raised cleanup failures, activation failure, viewer failure and revoked-authority failures remain sticky. Reporter final close already includes binding, activation-release and cleanup-failure evidence. No sticky flag is cleared, no remote release is retried, no app quarantine logic changes, and retired-drain caching remains unchanged. Production change is four comment lines plus a conditional around the existing OR.

Canonical B:640 and B7.10 (1465–1614) distinguish intermediate remote evidence from final resource evidence. B's example excludes ordinary held lease from intermediate uncertainty; current implementation instead includes it. This patch consumes its final aggregate evidence rather than changing the existing provisional-return contract/assertion. The mounted test's retained intermediate assertion remains intact. No claim that a local unlock alone proves remote emptiness.

Tests added in `tests/tui/test_herdr_activation_composed.py`:
`test_mounted_drained_uncertainty_suppresses_successors_and_allows_gc[remote,cleanup]`.
Remote case injects a shutdown-release exception before command dispatch (not a CLI timeout fixture); cleanup case injects the reporter's sticky cleanup-failure fact. Both use actual mounted config-backed session/Faux factory, registered fake CLI, real final transport drain and lease unlock. Both assert uncertain/drained, suppression on two successors, no successor commands, no retired app slot and old-session weakref collection. Existing persistent unlock refusal/GC test remains unchanged. These contrasts do not establish every wire-level ambiguous release variant.

## Exact execution

CWD `/root/Code/slo-94-herdr-integration/slo`. All pytest commands use `PYENV_VERSION=slo-harness bash docs/implementation/94-herdr/t1-dao-check.sh`, with its reviewed safe fallback and 62 DAO/projection cases. Existing HERDR stripping, registered fake identity/containment and terminal guards remain active. No venv creation or real provider/Herdr/windows.

Receipts are sibling `.log` and `.exit` files:

| Prefix | Arguments / command | Result |
|---|---|---|
| t5-83-red | tests/tui/test_herdr_activation_composed.py | 1 failed, 67 passed, 4 warnings; exit 1; actual suppressed successor |
| t5-83-green | tests/tui/test_herdr_activation_composed.py tests/agents/slo_agent/herdr/test_session_lifetime.py | 127 passed, 4 warnings; exit 0 |
| t5-83-surrounding | surrounding arguments below | 1721 passed, 163 warnings; exit 0 |
| t5-83-contrast | tests/tui/test_herdr_activation_composed.py | 70 passed, 4 warnings; exit 0 |
| t5-83-surrounding-final | surrounding arguments below, after new contrasts | 1723 passed, 163 warnings; exit 0; 308.94s |
| t5-83-black | PYENV_VERSION=slo-harness poetry run black --check src/agents/slo_agent/sessions/service.py tests/tui/test_herdr_activation_composed.py | exit 0 |
| t5-83-diff | git diff --check | silent exit 0 |
| t5-83-coreutils-final | dpkg -V coreutils after final surrounding | silent exit 0 |

Surrounding arguments (shell glob expanded by Bash):
```
tests/agents/slo_agent/herdr tests/agents/slo_agent/test_session.py tests/agents/slo_agent/test_session_usage.py tests/tui/test_herdr*.py tests/tui/test_app.py tests/tui/test_queued_prompt_block.py tests/tui/test_openrouter_startup.py
```
Existing contradictory getter, final-drain faults/caching, actual transport and lease lifetime tests all ran unchanged. Final source inspection checked conservative final retention and exception branches; not an independent review.

## Remaining / not claimed

**INCOMPLETE**, not READY activation family and not full T5. The remaining finite 82 map has not been closed: composed mounted contender refusal, activation defects, each runtime-await/diagnostic cutoff, and full remote ambiguity/release contrasts still need mapping and evidence. Inbox work has not begun. Full make test/smoke/lint gates were not run because family readiness was not reached; historical 299 errors/63 files is UNWAIVED and not freshly compared. No static-green claim.

Read 82 activation/INIT and 40 lifetime receipts, routing/scope plan, relevant current close/reporting code and tests; supplied AGENTS/CLAUDE/docs research context; KB entry/Slo README/gotchas. Loaded engineering routing/testing/ownership, Python root/application-service/declarative, coding rules/cadence/shared declarative; domain recipe read was partial. Canonical C7.9 replacement/lifetime and B outcome/close excerpts were read. Required full C7.9–7.14/exact T5 samples/accepted-review and remaining Textual/Faux/workflow/style reads were not completed in this continuation. Do not interpret prior receipts' read claims as fresh ingestion here. This prerequisite shortfall and incomplete matrix prevent READY despite the bounded passing repair.
