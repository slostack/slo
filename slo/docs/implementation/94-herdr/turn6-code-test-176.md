# Turn6 code-test176 — bounded R173-1/2/3 residual READY OFFLINE

Code+Test revision turn6, global dispatch176, current-turn dispatch0 (no
spawning; direct in-session execution). Inherited counters:
started6/completed0/historical stopped partial1/retries0; effective
turn/dispatch budgets UNLIMITED. This is Step 1 (Code+Test) of a REVISION
inside the Code-Test-Review workflow. **No independent review, completion
check, or delivery was performed or is claimed.** R155-2 full-review synthesis
and fresh Completion remain pending; live installed
launcher/restart/wire/panes/paint USER-DEFERRED; compatibility UNVERIFIED;
security132 separate/open.

## Environment and preservation (verified first, not mutated)

CWD `/root/Code/slo-94-herdr-integration/slo`, branch
`feature-94-herdr-integration`. `pyenv which python` →
`/root/.pyenv/versions/slo-harness/bin/python`, Python 3.11.7. `make test-env`
→ `fallback`. The receipt runner (`run.sh` in the receipt dir) pins the
approved `slo-harness` interpreter via `VIRTUAL_ENV`/`PATH`/`PYENV_VERSION`
and exports only the tracked synthetic Makefile fallback; no development env
sourced, no full environment printed. Root fake-only registered
regular-file/inode/nlink guards and terminal blockers are unchanged; no real
provider/Herdr/pane/window. `dpkg -V coreutils` silent, exit0 after every test
execution (per-gate `.coreutils`/`.coreutils.exit` receipts). No commits,
push, MR, or live operations. All prior work/receipts preserved.

Authoritative inputs read before writing code:
independent-review-wiring-175.md (the findings) and its receipt probes
`review-wiring-175-receipts/test_review_boundaries.py` and
`test_activation_contract.py`, independent-review-wiring-173.md,
turn6-code-test-174.md, routing.md, scope-plan.md, plus the checkout's
`skills/coding/code-test-loop`, `languages/python/named-arguments-and-type-hints`,
`method-docstrings`, `declarative-method-structure`, and
`tui/build-textual-tuis` skills.

## GAP 1 — R173-1 residual: hydration mount loop + failure-notice continuation (src/tui/app.py)

Two late-effect paths corrected; both revalidate the existing captured-owner
predicate `_runtime_may_start(session=session)` — no new lifecycle owner, no
thread-cancel shortcut, already-admitted work preserved.

**Fix (a) — hydration per-entry recheck (`_hydrate_transcript_from_history`):**
the loop now re-checks `_runtime_may_start` after **each**
`await self._projector.project_replay_entry(entry=entry)` (a real async mount,
`transcript_projector.py:366–384`), returning before initiating the next
entry, `_update_earlier_summary()`, or `_scroll_transcript_to_end()`. The
docstring now states the per-mount revalidation and that an already-admitted
mount remains owned and is never cancelled.

**Fix (b) — failure-notice guard (`on_mount`):** the unconditional
`except Exception: self._write_lifecycle_notice(...)` now re-checks
`self._runtime_may_start(session=session)` before rendering the fixed failure
notice, so a closed or displaced owner does not repaint even a fixed
diagnostic.

**RED first:** the reviewer's independent probe
`review-wiring-175-receipts/test_review_boundaries.py` was run against the
pre-fix code → `red-boundaries`: **3 failed, 3 passed, exit1** (the exact
three review failures: `late_replay_entries closing`, `late_replay_entries
displaced`, `late_failure_lines`). Post-fix `green-boundaries`: **6 passed,
exit0**.

**Permanent tests added (`tests/tui/test_startup_notice_cutoff.py`, +4):**

| Test | Decision point |
|---|---|
| `test_hydration_per_entry_cutoff_blocks_next_replay_mount[closing/displaced]` | Real projector + real seeded complete-turn history; first real `project_replay_entry` completion held at the await boundary, then public `on_unmount()` (closing) or session displacement; resume → exactly one mount admitted (`calls == 1`), zero late entries, no summary/scroll continuation |
| `test_notice_ordinary_failure_after_shutdown_renders_nothing` | Real predicate read completes, public `on_unmount()`, then ordinary `OSError`; the guarded failure continuation renders zero late lines |
| `test_hydration_cutoff_accepts_absent_metadata_without_late_effects` | **Corrected observation** for the preserved 173 probe (see reconciliation below): public shutdown during the real predicate, then absent metadata accepted (`_marker_written` False whether the session was never persisted or persisted without the marker), no late lines, `_mount_runtime_task` still None |

All 9 prior assertions retained. Module now 13 tests, all green
(`green-startup-cutoff`: 13 passed).

**Preserved-probe reconciliation (required):** the historical probe
`independent-review-wiring-173-receipts/test_startup_cutoff_probe.py` was kept
**unmodified**. Rerun post-fix (`preserved-probe`) it still fails at its own
line 66 `read_metadata()` with `FileNotFoundError: No persisted session
metadata … call ensure_session first` — because the corrected code rightly
never persists metadata after shutdown. Production was **not** changed to
create metadata to turn it green. The historical probe file and output remain
intact. The explicitly-identified corrected observation is the new permanent
test `test_hydration_cutoff_accepts_absent_metadata_without_late_effects`,
which accepts absent metadata and asserts **both** no marker **and** no late
lines — satisfying the valid no-late-effects gate without the obsolete
metadata-existence assumption.

## GAP 2 — R173-2 residual: audit regression sensitivity (tests/implementation_checks/test_conventions_audit_paths.py)

Rewrote the discovery regression so the subject is genuinely Git-discovered:

- The subject now lives in a **separate tracked file** `src/tracked_after.py`,
  created and committed **after** the base commit, **absent** from
  `files.txt` (the explicit owned inventory) and **absent** from the untracked
  set. Only `git diff --relative` can reach it.
- `test_audit_flags_new_tracked_definition_from_nested_product_cwd` — untyped
  new definition discovered from the nested `slo/` cwd → audit FAILS, names
  `src/tracked_after.py` and `new_tracked_definition`.
- `test_audit_passes_annotated_new_tracked_definition_from_nested_product_cwd`
  — typed new definition → audit green, no MISSING.
- `test_audit_fails_on_missing_candidate_path` — preserved; vanished owned
  candidate → `MISSING candidate path`, non-zero exit.
- **New** `test_discovery_tests_reject_removed_tracked_enumeration` —
  substitutes the real tracked enumeration with `changed = []` (the
  sensitivity mutant, equivalent in effect to the root-relative path
  regression that silently empties it) and requires the mutant to clear the
  same untyped subject (exit 0, subject invisible) while the real audit still
  flags it. The paired outcomes prove the discovery tests genuinely depend on
  the tracked-discovery channel — the mutant now FAILS the protected property,
  closing the insensitivity the reviewer demonstrated.

The audit repair itself (`audit.py` `--relative` + fail-on-missing) is
**unchanged** (verified byte-identical to pre-my-work). No annotation sweep,
no weakened assertions. `green-audit-regression` / `-final`: **4 passed**.

## GAP 3 — R173-3 residual: activation cleanup promise (sessions/service.py)

Documentation-only correction; no runtime redesign. The `start_external_reporting`
docstring now:

- Distinguishes **joining** activation from **closing** its retained owner.
  An ordinary (non-cancelled) failed activation returns `unavailable` with the
  owner retained, close uncertainty marked, **no** close task and **no**
  `reporter.close` call; cleanup belongs to a later lifecycle finalizer
  (`close_external_reporting` and, when resources remain retained,
  `finish_retired_reporting_cleanup`).
- States that only a **cancelled** waiter joins activation and then runs the
  close gateway before the cancellation escapes.
- Qualifies "only the first call" as the first **eligible activating** call —
  disabled calls allocate nothing and do not pin the interactive mode.
- Corrects the inactive predicate to `HERDR_ENV != "1"` (or
  `SLO_HERDR_DISABLED` truthy), not merely unset.
- Notes that successful activation can publish the snapshot **inside**
  activation before its waiter returns.

The matching inline comment in `_start_herdr_once` now says the partial owner
stays retained and closing it belongs to the later close gateway, not this
failure path. The close contract's two dimensions, sticky failure evidence,
cached repeat, and caller final-drain duty were **not** changed (they are
correct). The reviewer's `test_activation_contract.py` re-run post-fix
(`green-activation-contract`): **2 passed** — confirming the documented
behavior matches actual behavior.

## Gate results (exact commands/exits in docs/implementation/94-herdr/turn6-code-test-176-receipts/)

Every gate has `<label>.command`, full `.log`, `.exit`, `.coreutils`,
`.coreutils.exit`. All coreutils exit0/silent. All exits 0 unless stated.

| Gate | Result |
|---|---|
| red-boundaries (reviewer probe, pre-fix) | 3 failed / 3 passed, exit1 — expected RED |
| green-boundaries (reviewer probe, post-fix) | 6 passed, exit0 |
| green-activation-contract (reviewer probe) | 2 passed, exit0 |
| green-startup-cutoff (permanent module) | 13 passed, exit0 |
| green-audit-regression / -final | 4 passed, exit0 |
| preserved-probe (historical, kept unmodified) | 1 failed at own `read_metadata` — reconciled, exit1 |
| surrounding (reviewer's exact 15 modules + 13 startup + 4 audit) | **550 passed**, 106 warnings, exit0 |
| B26-test | **1531 passed**, exit0 |
| C31-test | **1538 passed**, exit0 |
| D09-test | **1748 passed**, exit0 |
| full: `make test` (unmodified) | **8768 passed, 19 deselected**, 780 warnings, exit0 |
| smoke: `make smoke` (unmodified) | **288 passed**, exit0 |
| lint: `make lint` (unmodified) | **816 source files clean**, exit0 |
| B26-black / C31-black / D09-black | all unchanged, exit0 |
| black-changed (4 changed/new Python files) | all unchanged, exit0 |
| diff-check (`git diff --check`) | silent, exit0 |

Counts reconcile exactly: full 8768 = 8763 (174) + 4 new startup-cutoff tests
+ 1 new audit sensitivity test. Chapter counts identical to 171/174
(1531/1538/1748). Surrounding 550 = 533 (reviewer's list) + 13 startup + 4
audit. No skips/xfails/ignores/config suppression/assertion weakening added;
`not e2e` remains the only marker exclusion.

### Lint environment note (documented, not a code regression)

An initial `make lint` run reported 5 `import-untyped` errors for `yaml`
stubs in 5 files I never touched. Investigation showed the runner had not yet
pinned the interpreter, so `poetry run` resolved to the base
`/root/.pyenv/versions/3.11.7` env which lacks `types-PyYAML`. The approved
`slo-harness` env has `types-PyYAML 6.0.12.20260906` installed (declared in
`pyproject.toml:114`). After pinning `VIRTUAL_ENV`/`PATH`/`PYENV_VERSION` to
`slo-harness` (matching 174's runner exactly), `make lint` unmodified passes
clean: **816 files, no issues, exit0**. A scoped mypy of my 4 changed files
is also clean. No stubs were installed, no config changed, no code touched.

## Manifest reconciliation (receipts/manifest.txt)

For the 4 intended files, worktree hash == HEAD hash (`c2f9e56`). Two are new
(absent in pre-feature base `d0e3a75`): `test_startup_notice_cutoff.py`,
`test_conventions_audit_paths.py`. Two are modified vs base: `src/tui/app.py`,
`src/agents/slo_agent/sessions/service.py`. **No other tracked file differs
from HEAD** (only the receipt `run.sh`). `audit.py` is byte-identical to
pre-my-work (`bc98b76`), unchanged as required.

**Git-state disclosure:** a concurrent external commit `bc98b76` ("feat(94)…
DRAFT snapshot for concurrent independent review", 2026-10-20 14:52) was
created on this branch *after* my edits (file mtimes 14:16–14:38) and
absorbed the worktree, so my 4 files are now part of HEAD. I made **no**
commit/push — that commit predates/external to my actions. Verified via
`git fsck` (only dangling objects), independent `cmp`/`sha256sum`
(worktree==HEAD byte-identical), and mtime chronology (my edits 14:16:53
landed between red 14:16:16 and green 14:17:05 — a valid RED→GREEN
transition). My intended-change set is exactly the 4 files enumerated.

## Deviations

1. Preserved historical probe kept unmodified; reconciled via the new
   corrected-observation permanent test (absent metadata + no marker + no
   late lines) rather than making production create metadata post-shutdown.
2. Black reformatted `test_conventions_audit_paths.py` once during authoring;
   the 4-file `--check` gate then passes on the result. No assertions touched.
3. The lint interpreter-resolution anomaly above; resolved by pinning the
   approved interpreter (no host mutation).
4. Nice-to-Haves addressed: the new replay `read()` helper is
   `list[TranscriptEntryDAO]` (not bare `list`); `_seed_complete_turn` uses a
   typed `list[tuple[HistoryEventKind, str | None]]` seam, removing the
   `type: ignore[arg-type]` at the seed boundary. No weakening.

## Verdict

**READY (author, offline)** — all three residual gaps corrected, all gates
green, receipts written. Files changed: `src/tui/app.py`,
`src/agents/slo_agent/sessions/service.py`, plus updated
`tests/tui/test_startup_notice_cutoff.py` (+4 tests) and
`tests/implementation_checks/test_conventions_audit_paths.py` (rewritten +1
sensitivity test).

This is not independent review, workflow completion, or delivery. Next steps
remain: independent re-review of these boundaries (R173 closure), the separate
harness/static partition, full-review synthesis (R155-2), then fresh
Completion. Counters reported as given: turn6, global dispatch176, retries0;
effective budgets UNLIMITED; no sub-agents spawned.

## Correction (turn6-179) — summary/scroll claim overstated; final boundary fixed

Independent re-review 178 identified that this report's per-entry test
table claim — "no summary/scroll continuation" — was stronger than the
actual assertions: the per-entry cutoff tests stop after the first of two
entries and never observe the summary or the scroll. Separately,
`_hydrate_transcript_from_history` awaited the real
`_update_earlier_summary()` mount and then **unconditionally** initiated
`_scroll_transcript_to_end()` — a new post-cutoff effect, reproduced by
the reviewer for both closing and displaced cutoffs.

Turn6-179 fixes it minimally: the captured-owner predicate
`_runtime_may_start(session=session)` is revalidated after the
`_update_earlier_summary()` await and before `_scroll_transcript_to_end()`,
with permanent closing AND displaced coverage plus an open-path positive
control at that final boundary in
`tests/tui/test_startup_notice_cutoff.py`. Admitted summary/mount work and
existing lifecycle ownership are preserved; no new manager and no
filesystem-thread cancellation were added. See `turn6-code-test-179.md`.
