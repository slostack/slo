# Turn6 code-test179 — R178 residuals corrected (final replay-scroll cutoff + audit sensitivity seam) READY OFFLINE

Code+Test revision turn6, global dispatch179, current-turn dispatch0 (no
spawning; direct in-session execution). Inherited counters:
started6/completed0/historical stopped partial1/retries0; effective
turn/dispatch budgets UNLIMITED. This is Step 1 (Code+Test) of a REVISION
inside the Code-Test-Review workflow. **No independent review, completion
check, or delivery was performed or is claimed.** R155-2 full-review
synthesis and fresh Completion remain pending; live installed
launcher/restart/wire/panes/paint USER-DEFERRED; compatibility UNVERIFIED;
security132 separate/open.

## Environment and preservation (verified first, not mutated)

CWD `/root/Code/slo-94-herdr-integration/slo`, branch
`feature-94-herdr-integration`, HEAD `c2f9e56` (the R173 tree was already
committed by an external concurrent workflow). `pyenv which python` →
`/root/.pyenv/versions/slo-harness/bin/python`, Python 3.11.7.
`make test-env` → `fallback`. The receipt runner
(`turn6-code-test-179-receipts/run.sh`) pins the approved slo-harness
interpreter and exports only the tracked synthetic Makefile fallback; no
development env sourced, no full environment printed. Root fake-only guards
and terminal blockers unchanged; no real provider/Herdr/pane/window.
`dpkg -V coreutils` silent, exit0 after every gate (per-gate
`.coreutils`/`.coreutils.exit` receipts). **No commits, push, MR, or live
operations.** All prior work/receipts preserved; both reviewer probe files
(`review-wiring-175-receipts/test_review_boundaries.py`,
`review-wiring-178-receipts/test_residuals.py`) and
`conventions-revision-159-receipts/audit.py` are byte-identical before and
after (manifest reconciliation below).

Authoritative inputs read before writing code:
independent-review-wiring-178.md and its probe
`review-wiring-178-receipts/test_residuals.py`,
independent-review-wiring-175.md, turn6-code-test-176.md,
turn6-code-test-177.md, routing.md, plus the checkout's
`languages/python/named-arguments-and-type-hints`,
`languages/python/method-docstrings`, `tui/build-textual-tuis`, and
`coding/code-test-loop` skills.

## R178-1 — final replay-scroll continuation crossed the cutoff

**Defect (reproduced RED):** `_hydrate_transcript_from_history`
(`src/tui/app.py:741–742`) rechecked the captured owner after each replay
entry, but then awaited `_update_earlier_summary()` — a real Textual
mount/removal — and unconditionally initiated
`_scroll_transcript_to_end()`. Shutdown or displacement completing during
the summary await made that scroll a new post-cutoff effect. RED receipt
`red-residuals`: **5 failed, 3 passed, exit1** — both
`test_summary_completion_cannot_initiate_late_scroll` cases reported
`late_scrolls_after_summary ['_hydrate_transcript_from_history']`, and the
three `[redirect_alias=False]` rejection cases failed (R178-2 seam).

**Fix (minimal, existing owner):** revalidate
`self._runtime_may_start(session=session)` after the
`_update_earlier_summary()` await and before `_scroll_transcript_to_end()`;
docstring updated to name the summary-await boundary and that admitted
summary/mount work remains owned and is never cancelled. No new manager, no
filesystem-thread cancellation, no lifecycle-ownership change.

**Permanent coverage added** (`tests/tui/test_startup_notice_cutoff.py`,
real projector + real seeded two-entry turn history + real
`_update_earlier_summary`, hydration limit forced to 1 so the summary
genuinely mounts; scroll observer delegates to the real scroll and
attributes only calls initiated directly by
`_hydrate_transcript_from_history`, walking past mock frames):

- `test_hydration_summary_completion_cannot_initiate_late_scroll[closing]`
  — public `on_unmount()` completes during the held summary return; resume
  → zero late scrolls, zero admitted scrolls; summary mount itself was
  observed mounted before the cutoff.
- `...[displaced]` — selected session identity replaced during the held
  summary return; same assertions.
- `test_hydration_open_path_summary_then_scroll_after_summary` — positive
  control: with no cutoff the admitted summary mount completes and
  hydration initiates exactly one scroll, proving the new revalidation does
  not block the admitted path.

All 13 pre-existing startup/replay assertions retained unchanged (16 tests
pass in the module).

## R178-2 — audit sensitivity seam bypass + false survival claim

**Defect:** turn177's `_REAL_AUDIT = AUDIT` alias made every real half read
the committed audit through a binding the historical probe's `AUDIT`
monkeypatch could not redirect, so the probe's `changed = []` mutation only
reached the intentionally-mutant half and all three regressions survived.
Turn177's report mislabeled those survivals as rejections ("probe goes
GREEN 3/3"); the probe is an observation-of-survival with no
`pytest.raises`. The reviewer's both-bindings control proved the
strengthened count/missing-path assertions themselves genuinely detect
removed discovery (3/3 kills) — the assertions were good; the seam and the
claim were not.

**Fix (test-only; `audit.py` byte-identical; no Any/ignores/waivers):**

- **One explicit source-under-test path.** All three ordinary regressions
  read the audit through the single patchable module-global `AUDIT` and
  nowhere else. `_REAL_AUDIT` remains only as a documented compatibility
  target for the preserved residual probe (`test_residuals.py` redirects it
  in its `[redirect_alias=True]` contrast); no regression ever reads it.
- **Normal assertions separated from mutant comparison.** Ordinary
  regressions assert only the source-under-test outcome. Real/mutant
  comparison lives in separate test functions whose audit source is a
  materialized mutant file — mutation can never silently fall back to an
  unmutated source.
- **Explicit rejection oracle.**
  `test_regression_rejects_removed_tracked_discovery` patches the running
  module's `AUDIT` (by module identity, not a dotted-string path, so the
  seam cannot be missed through a second module instance) and requires each
  of the three ordinary regressions to raise `AssertionError` under
  `changed = []` — genuine mutant rejection at the real seam.
- **`--relative` removal verified as a distinct mutant.**
  `_write_relative_removed_mutant` drops only the `--relative` flag: from
  the nested product cwd the enumeration yields repository-root-relative
  `slo/...` names, and the repaired missing-path behavior reports them as
  MISSING — observably different from the `changed = []` mutant (which
  examines only the owned base definition and reports nothing).
  `test_discovery_tests_reject_removed_tracked_enumeration` contrasts both
  mutants for the untyped subject;
  `test_missing_candidate_tests_reject_removed_tracked_enumeration` does so
  for the missing-candidate case (both mutants still fail on the owned
  missing path; only the no-`--relative` mutant reports the
  discovery-channel dangling symlink, as `slo/src/broken_link.py`).
- **Nice-to-Have strengthening taken:** the missing-link fixture now
  explicitly asserts the fixed-inventory precondition
  (`src/broken_link.py` absent from `files.txt`) alongside the untracked-set
  and `--relative`-discovery preconditions.
- Channel-precondition assertions, the broken-symlink discovery candidate,
  and the three headless fixture signature fixes are all preserved.

**Corrected understanding** (appended to both prior reports):
turn6-code-test-176.md's "no summary/scroll continuation" table claim was
stronger than the per-entry tests' actual assertions, and
turn6-code-test-177.md's "all three regressions now reject the mutant"
recorded survivals from a bypassed seam, not kills.

## Gates (all receipts under turn6-code-test-179-receipts/)

| Gate | Result |
|---|---|
| red-residuals (reviewer probe, pre-fix tree) | **5 failed, 3 passed, exit1** — both residuals reproduced |
| green-residuals (post-fix, probe unmodified) | **8 passed, exit0** — closing+displaced scroll blocked; rejection oracle passes for both seam redirections |
| green-startup-cutoff | **16 passed, exit0** (13 pre-existing + 3 new) |
| green-audit-tests | **6 passed, exit0** (3 ordinary + oracle + 2 mutant-separation) |
| green-boundaries-probe (historical 175 probe, unmodified) | **3 failed, 3 passed, exit1** — the expected final behavior: 3 runtime boundary probes green; the 3 sensitivity observations now **fail** because the mutation genuinely reaches the source under test (rejection), and the probe asserts nothing |
| B26 chapter | 1531 passed, exit0 |
| C31 chapter | 1538 passed, exit0 |
| D09 chapter | 1748 passed, exit0 |
| surrounding (routing.md set + startup/replay + implementation_checks) | 504 passed, exit0 |
| smoke (`make smoke`) | 288 passed, exit0 |
| lint (`make lint`, unmodified) | 816 files, no issues, exit0 |
| black-changed (`--check` on the 3 changed files) | clean, exit0 |
| diff-check (`git diff --check`) | silent, exit0 |
| full (`make test`) | **8773 passed, 19 deselected, exit0** (1178s) |

All per-gate `dpkg -V coreutils` receipts: silent, exit0.

## Changed files (manifest reconciliation)

`manifest-before.txt` / `manifest-after.txt` SHA256 pairs — exactly three
payload files changed:

- `src/tui/app.py` — one revalidation guard + docstring (R178-1).
- `tests/implementation_checks/test_conventions_audit_paths.py` — single
  `AUDIT` seam, separated mutant-comparison tests, rejection oracle,
  `--relative`-removed mutant, missing-link `files.txt` precondition
  (R178-2).
- `tests/tui/test_startup_notice_cutoff.py` — two permanent cutoff tests +
  one open-path control at the summary→scroll boundary (R178-1).

Documentation-only appends: `turn6-code-test-176.md`,
`turn6-code-test-177.md` (corrected-understanding notes; no prior content
altered). New receipts directory `turn6-code-test-179-receipts/`.
Byte-identical (verified): `conventions-revision-159-receipts/audit.py`,
both reviewer probe files, `sessions/service.py` (the WHEN-wording
Nice-to-Have is explicitly "not a blocker and not a reason to change
runtime" — left for independent review).

No skips/xfails/ignores/weakening added. No commit/push/MR performed.

## Boundaries

This corrects exactly the two bounded R178 residuals. It is **not**
independent review approval, workflow acceptance, completion, or delivery.
Independent re-review of this revision and fresh Completion remain pending.
Live operations remain USER-DEFERRED; compatibility UNVERIFIED.
