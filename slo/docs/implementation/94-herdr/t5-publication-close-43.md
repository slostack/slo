# T5 capture/publication continuation 43 — INCOMPLETE

Same unfinished turn 1: started 1, completed 0, historical partial 1,
dispatch 43, retries 0. User turn/dispatch budgets unlimited. No agents ran.
This receipt is not family READY and does not authorize attention work.

## Implemented boundary

General `attach_sub_agent_pool` now publishes immediately after successful attachment.
The shared attachment mutation is private `_attach_sub_agent_pool`; standard bootstrap
uses it and publishes after its provenance finish, avoiding an intermediate withdrawal
and generation churn. Failed identity permission publishes ineligibility rather than
leaving an old eligible publication. Existing standard-bootstrap identity/generation
regression remains green. Bootstrap recording tests follow the new private seam.

Files changed this continuation:
- src/agents/slo_agent/sessions/service.py
- src/agents/slo_agent/orchestrator/bootstrap.py
- tests/agents/slo_agent/herdr/test_session_publication.py
- tests/agents/slo_agent/orchestrator/test_bootstrap.py

## Finite branch map (not expanded scope)

| Branch from 42 | Evidence/state |
|---|---|
| Successful general attach immediately withdraws | New real-reporter regression passes without a later usage event |
| Standard pristine bootstrap preserves equal capture/generation | Existing real-reporter regression passes |
| Bootstrap changed identity refuses provenance | Existing test passes; exhaustive provenance matrix still pending |
| Later ordinary commit cannot certify unrelated unsupported edits | NOT FIXED: `_adopt_herdr_capture` still replaces the whole policy fingerprint |
| Truthful configuration validation / malformed source policy | Pending; no silent-coercion fix claimed |
| Startup/history/rename failure and cancellation publication cutoffs | Existing capture tests retained; full call-count matrix pending |
| Routed fallback and catalog no-save/release churn | Pending composed evidence |
| Actual Faux usage with save barrier/current generation | Existing Faux publication retained; save barrier composition pending |
| No event disk/credentials/model construction and error isolation | Existing bounded tests retained; complete matrix pending |
| Resume workspace/metadata provenance | 42 correction retained; complete matrix pending |

No run/history/rename policy changed this continuation. No attention, TUI or headless
code changed. No full-feature review/T6 claim.

## Exact executed verification

CWD `/root/Code/slo-94-herdr-integration/slo`; branch
`feature-94-herdr-integration`; `pyenv which python` returned
`/root/.pyenv/versions/slo-harness/bin/python`; Python 3.11.7;
`make test-env` returned fallback. No environment installation/change.

H = `bash docs/implementation/94-herdr/t1-dao-check.sh` (adds DAO/projection).
P = `tests/agents/slo_agent/herdr/test_session_publication.py`.
S = P plus `tests/agents/slo_agent/herdr/test_session_capture.py`,
`tests/agents/slo_agent/test_session.py`, `tests/agents/slo_agent/test_session_usage.py`,
`tests/agents/slo_agent/orchestrator/test_bootstrap.py`.
All log/exit pairs below are `t5-43-<name>.log` and `.exit` here.

| Receipt | Command | Actual outcome |
|---|---|---|
| attach-red | H P | 1 failed, 83 passed; exit 1; invalid RED: incorrect echo import |
| attach-green | H S | 1 failed, 203 passed; exit 1; same fixture import error |
| attach-red-corrected | H P with new public publication hook temporarily removed | 1 failed, 83 passed; exit 1; capture incorrectly remained eligible |
| attach-green-corrected | H S with hook restored | 204 passed, 10 warnings; exit 0 |
| format | poetry run black on the four changed Python files above | exit 0 |
| surrounding | H tests/agents/slo_agent/herdr tests/agents/slo_agent/test_session.py tests/agents/slo_agent/test_session_usage.py tests/agents/slo_agent/orchestrator/test_bootstrap.py tests/agents/slo_agent/test_session_rate_limits.py tests/agents/slo_agent/test_session_manual_compaction.py | 1253 passed, 12 warnings; exit 0 |
| black | poetry run black --check on the four changed Python files above | exit 0 |
| diff | git diff --check | silent; exit 0 |
| coreutils | dpkg -V coreutils | silent; exit 0 |

No full make test/smoke/lint run: family not ready. Historical 299/63 static
baseline remains unwaived and no fresh diagnostic comparison is claimed.

## Reading and limitations

Read actual routing/scope plan, root RESEARCH, Makefile, affected session/bootstrap
and publication tests, shared routing/testing/ownership, coding rules/cadence/
declarative, Python root/service/declarative and exact workflow/shared SKILL.
Canonical C 7.8 was read directly. AGENTS/CLAUDE/docs RESEARCH were supplied in
context. Some bulk KB and Python skill output was truncated. Complete ingestion
of B, exact T5 attachments, accepted reviews and every requested prerequisite is
NOT claimed. Finish that ingestion before further production changes.

No specs, global state, KB, other worktrees or system binaries were edited. No
commit/push/PR/reset/clean/stash, live Herdr/provider/window or agents. Partial
work preserved. The remaining technical blocker is the unfinished finite map,
not static debt. This continuation did not finish the requested cohesive family.
