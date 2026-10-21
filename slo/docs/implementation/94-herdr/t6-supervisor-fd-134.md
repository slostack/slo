# T6 supervisor FD/capture 134 — INCOMPLETE / HOLD

Same unfinished turn 1: started 1, completed 0, historical partial 1, supplied dispatch 134, retries 0. Effective turn/dispatch budgets unlimited. No agents dispatched; no independent review or completion claim.

## Implemented ownership changes

Only `tests/integration/herdr_restore_process_bootstrap.py` and `tests/integration/test_herdr_restore_harness_safety.py` changed as code.

- `OwnedDescriptor` captures actual `fstat` device/inode, holds an explicitly nullable FD and marks a close attempt ambiguous before invoking close. Subsequent reconciliation checks identity/EBADF; it never retries an ambiguous close against a still-matching slot. A different identity is relinquished without closing it.
- `RetainedSupervisor.close_descriptors` attempts every descriptor and preserves its first failure. Parent finalization transfers `RetainedResourceError` with the primary failure and exact resource when disposal is unproved.
- Handshake descriptors use the captured owner rather than raw integer close/retry. Write-end close is inside the existing child wait/cleanup boundary.
- Parent capture files are exclusive-created raw descriptors retained by the same resource, not Python streams whose finalizers could later close reused slots. Partial stdout/stderr allocation is unwound through resource finalization. No second global process framework.
- Capture-directory deletion failure now transfers typed ownership, rather than merely adding an exception note. Explicit later drain reconciles descriptors before deleting captures.

## Test-first receipts

Each implementation increment stayed below approximately 50 substantive lines and was followed by the entire explicit safety module before proceeding.

| Increment | RED | GREEN |
|---|---|---|
| Owned close before/after error and controlled actual reuse | 3 failed / 72 passed (missing owner import) | 75 passed |
| All FDs attempted, primary failure retained | 1 failed / 75 passed (original ValueError escaped) | 76 passed |
| Handshake close fault with actual dummy supervisor | 1 failed / 76 passed (untyped OSError escaped) | 77 passed |
| stdout/stderr open, capture read and close | 3 failed / 78 passed (raw open/close seam not yet used); read row already passed | 81 passed |
| Directory cleanup typed transfer | 1 failed / 80 passed (ValueError plus note) | 81 passed |

The capture-open RED cases specify the new raw-descriptor boundary; they are not claims that the old Path.open implementation executed those injected failures. Actual dummy-child read/close cases assert joined return status and ECHILD from waitpid. Open failures occur before child creation. Existing descendant/sentinel/retained-wrapper tests reran unchanged. Controlled descriptor reuse involves only newly created regular files beneath tmp_path, never stdio/system files. Test cleanup disposes only test-owned descriptors and joins its own child.

Final post-format chain: **81 passed, 2 warnings in 49.49s**, Black two files unchanged, scoped mypy no issues in two files, `git diff --check` silent, `dpkg -V coreutils` silent; chained exit **0**. Warnings are pythonjsonlogger deprecation and LangGraph pending deprecation. Earlier pre-format chain was also green (81 passed in 49.48s); Black then reformatted only the safety test. No separate log artifacts were written; exact output is in this session's tool transcript.

Cwd `/root/Code/slo-94-herdr-integration/slo`. Interpreter verified through `PYENV_VERSION=slo-harness pyenv which python`: `/root/.pyenv/versions/slo-harness/bin/python`; Poetry reports Python 3.11.7. Every test invocation used:

```sh
export PYENV_VERSION=slo-harness SLO_ENV=test SLO_ROOT_DIR="$PWD" SLO_APP_DIR="$PWD" SLO_APP_NAME=slo SLO_LOG_FORMAT=text SLO_DEFAULT_MODEL_NAME=gpt-5.4 SLO_AUTO_VISUALIZE=0 SLO_ANTHROPIC_API_KEY=ci-placeholder-tests-are-fully-mocked COLUMNS=120 LINES=40 SLO_HERDR_DISABLED=1 PYTHONPATH="$PWD"
poetry run pytest -q --tb=short -m 'not e2e' tests/integration/test_herdr_restore_harness_safety.py
poetry run black --check tests/integration/herdr_restore_process_bootstrap.py tests/integration/test_herdr_restore_harness_safety.py
poetry run mypy --follow-imports=skip tests/integration/herdr_restore_process_bootstrap.py tests/integration/test_herdr_restore_harness_safety.py
git diff --check
dpkg -V coreutils
```

Final chain used `&&`. Existing preimport HERDR stripping, synthetic state, disabled integration and real-window guards remain unchanged. Owned files are pre-existing untracked files, so git diff cannot inspect their contents; changed sections were directly reread.

## Precise remaining FD/capture obligations

**Not READY for the finite family.** The following remain unimplemented or unproved:

1. Allocation followed by `fstat` failure has no published descriptor owner; both pipe and capture allocation need an explicit partial-acquisition contract and tests. Current successful-identity close tests do not cover this.
2. Child-side handler installation/READY write/READY close/spawn failure disposal remains unchanged. No actual generated pre-handler failure or stop-before-workload-spawn cutoff proof was added.
3. Capture close-after-error/reuse is tested at the shared descriptor owner, not in a composed capture run. Combined unjoined child plus capture-disposal failure and strong reachability after GC need composed assertions. The existing retained-child test reruns but does not prove that combination.
4. Error finalization can wrap an existing RetainedResourceError if another descriptor fault occurs; preserving the ultimate first exception in that combination needs a test/correction.
5. Actual read handles still use Path read helpers. A failure of their internal close is not directly fault-injected. Legacy `run` still has its existing stream/TemporaryDirectory lifetime and is not claimed corrected.
6. Identity checks are bounded accident protection, not an atomic OS FD-generation primitive: same-inode reopen and concurrent external descriptor mutation are not established safe by dev/inode alone. No malicious-process sandbox claim.

Repeated interruption and full-run/drain concurrency remain outstanding after this finite family; no leap to those rows or positive acceptance. Exec/mutation guards remain a subsequent gate. **Positive parent/entry wiring, old probe, full make and live acceptance remain HOLD.**

## Reads and scope honesty

AGENTS/CLAUDE/docs RESEARCH supplied in full context; root RESEARCH reread directly. Read final133, current safety123, routing/scope plan, bootstrap, affected safety tests, state isolation/conftest, engineering routing/ownership/testing, coding rules/cadence, shared and Python declarative, Python root/named arguments/docstrings, canonical workflow SKILL. KB machine ROLE first, then README/workload detail; KB Welcome/project README/gotchas consulted. Canonical Herdr B 1872–1925 and C 2060–2105 read-only. Combined large read output truncated; missing initial engineering policy output was reread separately. No claim that all 862 pre-edit safety lines or entire canonical chapters were freshly reread.

No agents, commit/push/PR/reset/clean/stash, global/live/spec/other-worktree/KB/shared-status changes, real provider/Herdr/window, old probe or full suite. Documentation outputs are this receipt and safety123 current section only. One accidental scratch copy of root RESEARCH was written to `/tmp/slo134-read-not-used` during orientation; it was not used as evidence or modified afterward. This deviates from the requested write-only artifact restriction and is disclosed rather than hidden. No host executable/configuration was changed.
