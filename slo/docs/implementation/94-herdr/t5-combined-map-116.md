# T5 combined map 116 — INCOMPLETE

Same unfinished turn 1: started 1, completed 0, historical partial 1, supplied dispatch 116, retries 0. Turn/dispatch limits unlimited. No agents launched. Only `tests/tui/test_herdr_all_owner_cutoffs.py` and this report changed by this continuation. No source, other tests, canonical, global, KB, or other-worktree edits; no git mutations.

## Executed increment

The existing actual retained-resource composition remains unchanged: registered fake CLI split process, real reporter transport and sequence lease, two replacements, current registry coroutine requiring the submission gate, and successful or persistent final local drain.

Added original-store admitted normal and operator-abort cases alongside displaced-store cases. Added a fresh mounted config-backed same-ID/history-root session after each refused cutoff, using the existing Faux factory. Explicit polling must not invoke the session or register/queue a prompt; original claimed bytes and lane remain unchanged. Restart occurs after the retained-resource exercise and fixture cleanup, not concurrently with a live quarantined owner. Persistent cleanup cancellation is not claimed as successful graceful shutdown.

## Exact finite requirement map

All names below are in `tests/tui/test_herdr_all_owner_cutoffs.py::test_all_owner_claim_pending`; each runs with persistent=False and True.

| Requirement | Case / evidence | Status |
|---|---|---|
| C7.9 / C7.14 T3-F1 claim cutoff | `claim_pending`: claimed bytes, zero ack/task, running workflow; fresh mounted no replay | PASS |
| Workflow advancement cutoff | `workflow_advance_pending`: completed durable workflow, claimed bytes, zero ack/task; fresh mounted no replay | PASS |
| Final registration cutoff | `before_chat_registration`: called-but-refused registration, no ack/task, completed durable workflow; fresh mounted no replay | PASS |
| Admitted captured displaced store | `already_registered`, `registered_abort`: exact task survives closing; captured original ack; normal and active Faux-stream operator abort | PASS |
| Admitted original store | `registered_original_store`, `registered_abort_original_store`: same admitted-task/ack assertions without store displacement | PASS |
| Retired actual child/lease success and persistent retention | All seven cases inherit `exercise_retained_viewer` assertions, same process across three reap attempts, lease contention, sticky suppression, repeated unmount cancellation | PASS, helper unchanged |
| C7.14 F4 combined original failures plus throwing diagnostics and independent assertions for every cleanup owner | Not added; aggregate/current-session helper evidence is not exhaustive owner coverage | OPEN |
| D multiple actual workers, first join failure and later joins attempted | Not added/reconciled; the current registry coroutine is not a second real CLI worker | OPEN, separately scoped resource-owner lane |
| Replacement caller cancellation with actual retained child | Not added/reconciled; repeated unmount cancellation does not prove replacement-caller cancellation | OPEN, separately scoped resource-owner lane |

No new axes beyond the requested original-store and mounted restart variants were introduced. No production RED found in executed cases; no source-owner defect claim.

## Read evidence and remaining closure

Fresh full reads: admitted-115 report; owned test; real retained-viewer helper; combined-cutoffs test; routing.md; t1-dao-check.sh; installed-project equivalents under committed skills for engineering routing/testing/ownership, coding rules/code-test-loop/declarative, Python root/named arguments/docstrings/declarative/Faux testing, Textual. KB Welcome and slo/gotchas read fully. Inbox disposition source read lines 1–240.

Canonical C read lines 650–1099 and 1674–2183 (EOF), including complete 7.13, 7.14 and section 8. This is NOT complete C7.9–7.14 closure: 605–649 and 1100–1673 remain unread in this continuation. D viewer drain, exact T5 task samples and accepted reviews remain unread. Actual AGENTS/CLAUDE/docs RESEARCH were supplied in context but not freshly ingested; scope-plan, remaining routing-selected skills/workflow SKILL and KB README closure also remain incomplete. Prior reports' read claims are not promoted to fresh evidence. Therefore no mandatory-read closure or finite-family READY claim is made.

## Receipts

Cwd `/root/Code/slo-94-herdr-integration/slo`; approved `PYENV_VERSION=slo-harness` helper fallback, no environment installation. Commands run through tools with timeout 1800 for tests/static. Output retained in this session's tool results; no extra receipt files written outside the two-file ownership allowance.

1. `PYENV_VERSION=slo-harness bash docs/implementation/94-herdr/t1-dao-check.sh tests/tui/test_herdr_all_owner_cutoffs.py`: original-store increment **76 passed, 10 warnings in 9.34s**. Helper includes 62 DAO/projection cases.
2. Same command after mounted restart increment: **76 passed, 10 warnings in 9.88s**.
3. `PYENV_VERSION=slo-harness poetry run black --check tests/tui/test_herdr_all_owner_cutoffs.py`: one file unchanged; success.
4. `PYENV_VERSION=slo-harness poetry run mypy --follow-imports=silent tests/tui/test_herdr_all_owner_cutoffs.py`: no issues in one source file. No ignores added. This is scoped, not repository lint.
5. Surrounding command:

```bash
PYENV_VERSION=slo-harness bash docs/implementation/94-herdr/t1-dao-check.sh tests/tui/test_herdr_*.py tests/tui/test_app.py tests/tui/workflows tests/tui/test_workflow_receive_path.py tests/tui/test_visualizer_launcher.py tests/agents/slo_agent/herdr/test_session_lifetime.py tests/agents/slo_agent/herdr/test_session_visualizer_lifetime.py tests/agents/slo_agent/herdr/test_final_lifetime_closure.py tests/cli/test_headless_retained.py
```

**778 passed, 95 warnings in 268.53s; exit 0.** Warnings: pythonjsonlogger deprecation, LangGraph pending allowed_objects change and Pydantic instance model_fields deprecation. This supersedes the historical 774 receipt only for this surrounding selection, not full acceptance.

6. `git diff --check` and `dpkg -V coreutils`: silent, exit 0, including after surrounding gate. The owned untracked file was separately Black-checked; tracked diff check alone does not cover it.

Full make/integration and fresh 295/60 baseline comparison not executed; baseline remains unwaived. Whole-T5 independent review and T6/live acceptance are not claimed. Remaining combined diagnostics and read closure prevent READY; this is an incomplete delivery, not a budget stop or an invented unit cap.
