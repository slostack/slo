# Turn6 code-test174 — bounded R173-1/2/3 READY OFFLINE

Code+Test revision turn6, global dispatch174, current-turn dispatch0 (no
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
`feature-94-herdr-integration`, HEAD/base `d0e3a756689f2675e5507034d43cd8b272d3c6b8`.
`pyenv which python` → `/root/.pyenv/versions/slo-harness/bin/python`,
Python 3.11.7. `make test-env` → `fallback`. Only the tracked synthetic
Makefile fallback exports were used (`run.sh` in the receipt dir); no
development env sourced, no full environment printed. Root fake-only
registered regular-file/inode/nlink guards and terminal blockers are
unchanged; no real provider/Herdr/pane/window. `dpkg -V coreutils` silent,
exit0 after every test execution (per-gate `.coreutils`/`.coreutils.exit`
receipts). No Git mutations, commits, push, MR, or live operations. All prior
tracked/untracked work and receipts preserved.

Authoritative inputs read before writing code: independent-review-wiring-173.md
(the findings), routing.md, scope-plan.md, gates-171.md, final-code-status.md,
conventions-revision-159.md, the preserved RED probe and independent
signature_audit.py, spec 94.b.2 §7.13/§7.14 (C7.13/C7.14), the checkout's
Code-Test-Review workflow + SKILL.md turns/limits, code-test-loop,
coding-rules, engineering ownership/testing, and the selected Python/Typer/
Textual skills. AGENTS.md/CLAUDE.md/docs/RESEARCH.md/root RESEARCH.md/Makefile
were already in project context.

## R173-1 — TUI inner startup continuation after shutdown (src/tui/app.py)

**Fix (production, minimal — no new lifecycle owner, no thread-cancel
shortcut):** `_maybe_render_startup_notice` and
`_hydrate_transcript_from_history` now capture `session = self._session` at
entry and revalidate via the existing `_runtime_may_start(session=captured)`
after each real await (the `should_show_startup_notice()` history predicate;
the `hydrate_transcript_entries()` replay read) and **before** any rendering,
replay mounting, or `mark_startup_notice_shown()` persistence. Open startup
behavior and already-admitted marker-write ownership are unchanged; no
filesystem thread is cancelled; all later session uses reference the captured
local.

**RED first:** the preserved independent probe
(`independent-review-wiring-173-receipts/test_startup_cutoff_probe.py`) was
rerun against the pre-fix code → 1 failed, exit1 (`red` baseline retained in
the probe's own receipt dir; this turn's copy: probe-after-fix.log shows the
fix working — the probe now fails only at its own post-hoc `read_metadata`
call raising `FileNotFoundError` because no metadata was ever written, i.e.
zero late effects). New permanent module `tests/tui/test_startup_notice_cutoff.py`
(9 tests) went RED on exactly the 4 cutoff variants pre-fix
(red-startup-cutoff-final: 4 failed, 5 passed) and fully GREEN post-fix
(green-startup-cutoff / green-startup-final: 9 passed).

**Permanent test coverage (tests/tui/test_startup_notice_cutoff.py):**

| Test | Decision point |
|---|---|
| `test_notice_inner_await_cutoff_blocks_late_render_and_marker[closing]` | Real mounted app + real temp FilesystemSessionHistoryStore; predicate held after its real history read; public `on_unmount` completes; resume → no late lines, no `startup_notice_shown_at`, `_mount_runtime_task` still None |
| `...[displaced]` | Session displaced mid-predicate; successor's predicate is a bomb (AssertionError) proving no successor-state access; no marker on the captured session |
| `test_notice_open_path_renders_once_with_marker[history]` | Open mount renders exactly the 2 startup lines and persists the durable marker |
| `...[memory]` | History-disabled path renders once and sets the in-memory marker |
| `test_replacement_startup_uses_successor_only` | Real `SloAgentSession.build` + real `_start_new_session`; old and successor each render exactly one 2-line notice attributed to their own session id |
| `test_hydration_inner_await_cutoff_blocks_late_replay[closing/displaced]` | Seeded complete turn through the real store; replay read held; closing/displacement before resume → zero projector mounts |
| `test_hydration_open_path_mounts_seeded_replay` | Open path mounts both seeded replay entries through the real projector |
| `test_marker_write_admitted_before_cutoff_is_owned` | Marker write admitted before the cutoff is held, cutoff sealed, released → write completes, marker persisted, no repeat notice |

All existing cutoff assertions retained: `test_herdr_activation_cutoffs.py`
passes unchanged in the surrounding runs (225 passed with test_app.py,
test_herdr_session_lifecycle.py, test_herdr_replacement.py).

## R173-2 — fixture annotations + audit path normalization

**Annotations (only the three new definitions; no sweep):**
`tests/cli/test_headless.py:166,193,228` now declare `tmp_path: Path` in
`test_reporting_lifetime_surrounds_headless_run`,
`test_activation_exit_restores_signal_owner`,
`test_adopted_setup_and_terminal_fault_restore_signal`. `Path` was already
imported. Black's only additional changes in that file were line-wraps of
pre-existing signatures (verified in the diff; no assertion touched).

**Audit repair (`conventions-revision-159-receipts/audit.py`):** the
tracked-changed enumeration now uses `git diff --relative --name-only` so
repository-root-relative `slo/...` paths can no longer be checked against the
product cwd and silently skipped; the base blob prefix is a named
`PRODUCT_PREFIX` constant; and any enumerated candidate that is not a real
file is appended to `failures` (`MISSING candidate path …`) instead of being
skipped — the audit fails on unexpected missing candidates. Verified against
the real repo: the broken audit reported 1394 definitions while skipping all
90 tracked changed files (`Path("slo/tests/cli/test_headless.py").is_file()`
→ False from the product cwd); the repaired audit checks **1554** definitions
and reports PASS post-annotation (audit-159-fixed: exit0). The independent
`signature_audit.py` now reports its 125 definitions clean (red-signature-audit:
exit0, "No incomplete new signatures").

**Audit regression (`tests/implementation_checks/test_conventions_audit_paths.py`,**
3 tests, synthetic nested Git repos inside pytest temp roots only — never the
host repo):

| Test | Decision point |
|---|---|
| `test_audit_flags_new_tracked_definition_from_nested_product_cwd` | New unannotated tracked definition added after the base commit is discovered from the nested `slo/` cwd and fails the audit |
| `test_audit_passes_annotated_new_tracked_definition_from_nested_product_cwd` | Fully annotated new tracked definition keeps the audit green |
| `test_audit_fails_on_missing_candidate_path` | A vanished owned candidate produces `MISSING candidate path` and a non-zero exit instead of a silent skip |

Static-only fix per assignment: the RED was the real audit/annotation check
failing (independent `signatures.log` exit1 pre-fix; repaired-audit behavior
verified directly), plus runtime regression above. No Any/ignore/config
weakening anywhere.

## R173-3 — session public contracts documented in place

Google-style WHAT/WHO/WHEN + applicable Args/Returns/Raises, validated against
test_session_lifetime / test_session_attention / candidate / headless retained
tests and the intermediate-evidence vs final-disposal distinction:

- **`HerdrPolicySourcesDAO.permits_commit`** (~515): which fields are never
  owned by any gateway (`configured_reasoning`, `history_enabled`, `paths`),
  the authority `model_selection` (permits `model_name`+`pool`, transitively
  `effective_reasoning`) and `reasoning_commit` (permits `effective_reasoning`
  alone) grant, and the caller (`_adopt_herdr_capture`).
- **`start_external_reporting`** (~2360): exactly-once activation with later
  calls joining the retained task; first call alone records `interactive`;
  disabled path (`_herdr_closing`/suppressed/inactive environment) allocates
  no task and does zero I/O; failed activation retains its partial owner with
  destination `unavailable` and marked close uncertainty; cancellation
  propagates only after the activation joins, then closes reporting.
- **`close_external_reporting`** (~2505): the two independent outcome
  dimensions — `replacement` (sticky remote/defect uncertainty survives even a
  fully drained local close) and `resources` (final local disposal evidence; an
  intermediate gateway's default drained is not disposal permission, a throwing
  final gateway never inherits drained); cached repeated-call behavior (same
  retained task, same outcome, cleanup never re-run); failure retention; the
  requirement that a final-drain caller (`SloTUI._finish_shutdown_owner`,
  `HeadlessRunner._close_external_reporting`) observing `resources=retained`
  keeps the owner strongly retained and finishes through
  `finish_retired_reporting_cleanup`; join-before-cancel.
- **`set_operator_attention` / `clear_operator_attention`** (~2414): fixed
  literal reasons, session-owned serial token return contract, token
  non-reuse, matching-completion-only clearing (stale token is a silent
  no-op), process-local observation state with no execution authority.

No wrappers added, no core ledger copied, accepted core docs untouched.

## Gate results (exact commands/exits in docs/implementation/94-herdr/turn6-code-test-174-receipts/)

Every gate has `<label>.command`, full local `.log`, `.exit`, `.coreutils`,
`.coreutils.exit`. All exits 0 unless stated; coreutils exit0/silent after
every gate.

| Gate | Result |
|---|---|
| red-startup-cutoff-final | 4 failed (exactly the cutoff variants), 5 passed — expected RED, exit1 |
| green-startup-cutoff / green-startup-final | 9 passed |
| probe-after-fix (historical probe, retained as evidence) | 1 failed at its own post-hoc `read_metadata` — no late effects possible; superseded by the permanent module |
| green-surrounding-startup (activation cutoffs + app + lifecycle + replacement) | 225 passed |
| red-signature-audit (independent audit post-annotation) | 125 definitions, no incomplete, exit0 |
| audit-159-broken (pre-repair audit) | 1394 defs, PASS but silently skipping 90 tracked files — the defect |
| green-audit-regression | 3 passed |
| audit-159-fixed (repaired audit on real repo) | **1554** defs, PASS, exit0 |
| green-headless / green-session-docs / green-candidate-headless | 51 / 264 / 133 passed |
| surrounding (routing.md exact selection) | **472 passed** |
| B26-test | **1531 passed** |
| C31-test | **1538 passed** |
| D09-test | **1748 passed** |
| full: `make test` | **8763 passed, 19 deselected**, 780 warnings, 1178.35s, exit0 (171's 8751 + 12 new tests) |
| smoke: `make smoke` | **288 passed**, exit0 |
| lint: `make lint` | **816 source files clean**, exit0 |
| black-owned-final (6 changed/new Python files) | all unchanged, exit0 |
| B26-black / C31-black / D09-black | all unchanged, exit0 |
| diff-check (`git diff --check`) | silent, exit0 |
| final-manifest | **1066/1066 OK**, exit0 |

Counts reconcile exactly: full 8763 = 8751 (171) + 9 (startup cutoff) + 3
(audit regression). Chapter counts identical to 171. No skips/xfails/ignores/
config suppression/assertion weakening added; existing `not e2e` selection
remains the only marker exclusion. Warnings are pre-existing dependency
deprecations/AsyncMock notices, preserved not suppressed.

## Manifest reconciliation (scope-reconciliation.txt)

Frozen 171 comprehensive set verified 1064/1064 OK before any edit.
Post-turn: 1066/1066 OK. Changed frozen inputs: exactly 3
(`src/tui/app.py`, `src/agents/slo_agent/sessions/service.py`,
`tests/cli/test_headless.py`). New inputs: exactly 2 (the two new test
modules). One excluded receipt artifact changed
(`conventions-revision-159-receipts/audit.py`) — receipt directories are
outside the manifest scope by the 168/171 definition. No other source, test,
build, config, guard, or environment input changed; no deletions or renames.
Manifest digests: before `e48b436d…` (unchanged 171 set), after
`88d63009…`.

## Deviations

1. The historical independent probe was kept unmodified; post-fix it fails
   only at its own final `read_metadata` assertion (which requires a marker
   that must now never exist). The permanent module covers the same behavior
   plus the marker-negative case, and the probe's RED baseline is preserved
   in the 173 receipt dir.
2. Black reformatted two pre-existing long signatures inside
   `tests/cli/test_headless.py` while normalizing the file (line-wraps only;
   no assertion or behavior change). Black/mypy both pass on the result.
3. Lint initially failed on 4 type errors in my new test module; fixed by
   correcting my own annotations (tuple list, TranscriptEntryDAO import from
   `history/transcript.py`). No suppression used.

## Verdict

**READY (author, offline)** — all three findings corrected, all gates green,
receipts written. Files changed: `src/tui/app.py`,
`src/agents/slo_agent/sessions/service.py`, `tests/cli/test_headless.py`,
`docs/implementation/94-herdr/conventions-revision-159-receipts/audit.py`,
plus new `tests/tui/test_startup_notice_cutoff.py` and
`tests/implementation_checks/test_conventions_audit_paths.py`.

This is not independent review, workflow completion, or delivery. Next steps
remain: independent re-review of these boundaries (R173 closure), the separate
harness/static partition, full-review synthesis (R155-2), then fresh
Completion. Counters reported as given: turn6, global dispatch174, retries0;
effective budgets UNLIMITED; no sub-agents spawned.
