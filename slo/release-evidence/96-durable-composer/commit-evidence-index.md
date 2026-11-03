# Durable composer — local commit evidence index

## Accepted status and scope

**COMPLETE: all 83 original DC01–DC09 acceptance rows.** Independent aggregate final review: [final-review-turn4.md](final-review-turn4.md) READY. Separate independent completion: [completion-check.md](completion-check.md) COMPLETE. Historical REVISE and incomplete reports retain their original meaning; they are not current blockers or retroactively passing reviews.

Counters: **4 started / 1 completed / 3 partial; turn1 15 dispatches, turn2 5, turn3 2, turn4 dispatch4/20 (post-completion local commit); max60 turns; zero execution retries.** This action does not start another workflow turn. User explicitly authorized a local commit after fixes; no push, merge, PR, publication or release is authorized.

Original requirements are **external**, not copied into this commit:
`/root/Code/specifications/projects/slo/specifications/96-agent-message-queue/revised/01-durable-composer/`.
External KB and session-event references in reports are also not bundled.

## Exact committed inventory

[commit-files.txt](commit-files.txt) lists all **169 intended repository-root-relative paths** individually: **24 production Python files, 36 test/helper Python files, one README, and 108 task-evidence files** (including this index and the inventory itself). No directory-wide staging is intended. Selected ignored receipt paths are explicitly force-added because the generic `logs/` ignore rule otherwise excludes them; no ignore rule is changed. `SLO.md` and all `docs/` content are excluded and preserved.

Committed reports: acceptance-routing, implementation-handoff, continuation-ledger, completion-check, final-review-turn3, final-review-turn4, review-dc01-dc04, review-dc05-dc07, review-dc08-dc09, turn2-d3-regression-continuation, turn3-repair and turn4-repair (all `.md`). The three current pointers prepend accepted completion while preserving all historical text.

Selected receipts under `logs/` (extensions below are literal, not promises that every sidecar exists):

| Receipt stems | Committed extensions |
|---|---|
| turn4-full, turn4-affected-final, turn4-lint, turn4-black, turn4-final-diff, turn4-coreutils-final | .exit, .log, .started, .finished; exact commands in turn4-repair.md / final-review-turn4.md |
| turn4-schema-red, turn4-schema-green, turn4-final-preservation, turn4-e2e-after | .exit, .log, .started, .finished; exact commands in turn4-repair.md |
| completion-journeys | .command, .exit, .log, .started, .finished |
| completion-boundaries | .exit, .log; exact command in completion-check.md |
| turn3-confirm-full | .command, .exit, .log, .started, .finished |
| turn3-confirm-lint, turn3-confirm-black, turn3-confirm-diff, turn3-confirm-coreutils | .exit, .log; commands attributed in final-review-turn3.md |
| turn3-repeat-1, turn3-repeat-2, turn3-repeat-3 | .command, .exit, .log |
| turn2-d3-final-full, turn2-d3-repeat-1, turn2-d3-repeat-2, turn2-d3-repeat-3 | .command, .exit, .log, .started, .finished |

Also committed: `logs/turn3-black-paths.txt` (exact cumulative 60-path Python inventory), `logs/turn3-file-inventory.txt` (historical status, not staging authority), `logs/turn4-env.sh` (synthetic test exports and receipt helper), `logs/turn4-parametrize-sites.json`, and [reviewed-source-sha256.txt](reviewed-source-sha256.txt).

## Local-only evidence and provenance limits

**Every task-evidence file absent from commit-files.txt remains local-only.** This deliberately includes earlier dispatch/recovery/early-review/final-review/turn2-repair reports, detailed historical failure/interrupted logs, large collection/KB-validation logs, `turn4-before-*` pre-edit source captures, `turn4-preservation.py` and collection-before/after data. The ten turn4 `.command` sidecars listed above also remain local-only: their original trailing spaces are preserved rather than editing historical receipts or introducing cached whitespace errors. Historical report links to omitted files are local navigation, not a claim they exist in Git. Exact historical failures remain on disk unchanged; the selected schema RED receipt is committed as a small explicit failure-to-green example.

The committed preservation log records the accepted 19-decorator AST/collection comparison, but its omitted script and before-captures are needed to rerun that historical comparison. This bundle is compact acceptance evidence, not a self-contained archive of every investigation. Current source hashes pin bytes inspected for this commit; they were taken **after** accepted gates and are not retroactive cryptographic provenance for test execution. The accepted reports corroborate receipt reuse through inventory, source inspection and mtimes. No code/test/README changes were made by this commit task.

## Verification and precommit disposition

Accepted execution evidence (reused, not rerun during this commit-only task): final `make test PYTEST_WORKERS=6` **12,274 passed / 1,268 warnings**; affected **159 passed**; independent completion **194 + 74 passed**; mypy **981 files**, Black **60 files** clean. Three turn3 complete-file parallel regression repetitions each **47 passed**; earlier turn2-d3 repetitions are historical corroboration. Exact 21 e2e nodes were collected, not executed. Warnings remain explicitly qualified in the accepted reports; no real-provider, Docker, install or live-terminal certification is claimed.

Precommit inspection reconciled all 60 Python paths and the sole README feature hunk, inspected cumulative tracked/new source and intended evidence, and found no unrelated payload. Read-only process/cwd/open-file checks found no active competing repository writer; no process was killed. Source, README and excluded-content byte snapshots are checked again before and after Git operations. No active commit hooks were installed in the resolved common Git hooks directory and no core.hooksPath override was configured; hooks are not bypassed or installed here.

Manual credential-context inspection and bounded automated full-payload checks cover credential/token/password/private-key/bcrypt patterns. Identified fixture values (`synthetic-*`, `ci-placeholder-tests-are-fully-mocked`, README `sk-fake-default`, and redaction sentinels) are not live credentials. No live secret was identified. Gitleaks is unavailable on PATH; no package installation or scanner-equivalence claim is made. Exact cached inventory/full diff, byte equality and `git diff --cached --check` must pass before committing. The resulting commit hash belongs in the delivery answer, not an amendment to this report.
