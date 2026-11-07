# CURRENT A.2 verification — INCOMPLETE

One actual invocation on HEAD 82c3f5c6de9345af34a673a3d975366ca8c1624c, branch message-queue, approved interpreter Python3.11.7 / pytest9.0.3 / xdist3.8.0. Exact command/environment: exact-command.txt, environment.json. Exact 12 ignores +24 narrow deselect nodes: approved-exclusions.json. Preserved not-e2e; JUnit was the only additional option.

Run started 2026-11-05T08:01:17Z and reached its 2400-second timeout at 08:41:17Z. Progress reached 98% and contained failures; no final summary or JUnit was emitted. Observed progress symbols (NOT final test totals): {".": 12132, "F": 54, "s": 0, "x": 0, "X": 0, "E": 0}. Final passed/failed/errors/skips/deselections/warnings and exact process exit code are unavailable. pytest was still running at timeout; SIGTERM cleanup completed. No suite retry and no fixes.

417 process start identities tracked; zero remaining owned processes. cleanup.json records nine identity-matched SIGTERM actions; historical unrelated PIDs1261413/1261498/3382468 unchanged and untouched. stdout.log is full captured output; stderr.log is empty.

Before/after content+mode manifests covering tracked and untracked source/tests/docs/config excluding release-evidence are identical. Git status and HEAD/worktree diff saved. All108 coreutils/interpreter identity/hash/mode entries unchanged; before/after dpkg -V coreutils exited0 with empty output. No source/docs/assertion changes, installation, formatting, commit, push or independent review.

Limitation: supervisor persisted the pre-cleanup null poll status but not the final wait return code, so exact final exit is not claimed. Timestamps are live host UTC, not the approximate historical time supplied.
