# T6 two-process acceptance 122 — INCOMPLETE / safety hold

Same unfinished turn 1: started 1, completed 0, historical partial 1, supplied dispatch 122, retries 0. User-authorized turns and dispatches are unlimited; old numeric limits are not a stopping reason. No agents launched. No production, shared status, canonical specification, global, live, or other-worktree changes. This evidence document is the only file changed by this continuation.

## Fresh inspection

Read the complete `t6-two-process-121.md` and all three owned files:

- `tests/integration/test_herdr_two_process_restore.py`
- `tests/integration/herdr_restore_process_bootstrap.py`
- `tests/integration/herdr_restore_process_entry.py`

Fresh actual-file reads completed: AGENTS.md 1–1080 (two bounded reads), CLAUDE.md entire file, docs/RESEARCH.md 1–693 (two bounded reads), engineering-routing and engineering-testing skills, tests/state_isolation.py entire file, KB Welcome.md and slo/gotchas.md 1–200. The KB has no `slo/index.md`; Welcome identifies `slo/README.md` as its index, which remains unread in this continuation. A parallel read call with missing path parameters failed validation and read nothing; it is not counted as a completed read.

The other mandatory reads are NOT complete. In particular: root RESEARCH.md; routing/scope-plan/build rules; remaining KB guidance; engineering ownership; coding rules/cadence; Python, Typer, Textual, Faux/integration and declarative guidance; workflow skill; canonical C native restore/current-history/security requirements, B fake guard, D acceptance, T6 requirements/samples and accepted reviews. Prior-worker consultation is not substituted for fresh reads.

## Safety blockers verified by source inspection

1. The parent uses `subprocess.run(timeout=...)` for both application interpreters without `start_new_session` and without an explicit test-owned descendant cleanup owner. Direct-child timeout handling is not proof of descendant termination/reaping. No timeout test exists in the owned family.
2. `ProcessSafety.audit` handles mutation paths only when represented as str/bytes. Integer descriptors are ignored. Relative path resolution does not incorporate syscall `dir_fd`; rename/link source and destination directory descriptors are ignored. This does not establish containment before every write/mutation.
3. Execution refusal names `subprocess.Popen`, `os.system` and `os.posix_spawn`, but does not establish refusal for `os.exec` or raw fork-based alternatives. Registered subprocess identity checks alone are not proof of alternate-execution containment.
4. `ProcessSafety.probe` attempts a write at `root.parent / forbidden-write`. That target is outside the test root if the guard regresses. It must not be used as a real forbidden-write probe on this host. Future negative tests should use a narrower child-owned allowed subtree inside the enclosing pytest temp root, with forbidden sentinel targets still inside that enclosing test root; validate unchanged bytes/modes/identity.

These are test-harness safety gaps, NOT reproduced production bugs. No production RED is claimed. The two-process family was not executed in this continuation because the existing safety boundary is not yet adequate for the requested timeout/alternate-path tests.

## Acceptance still outstanding

- Implement and prove owned-child-group timeout/descendant cleanup without signaling the host/agent group or unrelated processes; preserve safe identity and ownership checks.
- Strengthen pre-import guard and safe temp-contained negative probes for direct-fd, dir-fd, alternate mutation and execution paths, plus executable/capture identity substitution refusal before effects.
- Add independent literal scalar/path oracles for both complete ordered five-field pool entries, single model, reasoning, workspace, ordered plugins and current-history content. Existing capture-versus-restored equality is retained evidence but insufficient as the independent oracle.
- Replace the refused-case direct `_ensure_agent_ready` invocation with observable refusal through actual CLI/session public admission. Preserve no automatic prompt replay and assert the precise expected history behavior for explicit refused admission.
- Finish mandatory reads before edits; then incremental focused and surrounding restore/CLI integration, Black, scoped mypy and final diff/coreutils checks. Coordinate full make only after parallel lanes settle; no lane-settlement evidence was obtained here.

## Fresh verification actually run

From `/root/Code/slo-94-herdr-integration/slo`:

```text
dpkg -V coreutils
# no output; exit 0

git diff --check -- tests/integration/test_herdr_two_process_restore.py tests/integration/herdr_restore_process_bootstrap.py tests/integration/herdr_restore_process_entry.py
# no output; exit 0
```

All three owned Python files are currently untracked, so `git diff --check` does NOT inspect their contents. This is not a substitute for Black or an untracked-file-aware review. No new pytest, Black, mypy or full-make result is claimed. Historical 121 four-case success and 295-errors/60-files baseline remain historical and unwaived.

## Qualification

The existing family uses two actual interpreters, actual CLI parsing/dispatch and a mounted real TUI through a regular source-entry shim. It is NOT an installed isolated launcher certificate, live Herdr restart certificate, independent review, full T6 acceptance or feature approval. No real provider, Herdr command, terminal window or host-directed cleanup was run in this continuation.
