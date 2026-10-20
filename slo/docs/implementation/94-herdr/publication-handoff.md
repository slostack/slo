# Publication handoff — DRAFT MR snapshot (user-authorized concurrent publication)

**Written before commit; commit SHA / MR URL / pipeline status are filled in by the
publication step immediately after push and are authoritative in the git history
of this file's committed version.**

## What happened

At the user's explicit request, the current `feature-94-herdr-integration`
worktree snapshot was committed and pushed to
`https://gitlab.com/core-27/slo.git` and a **DRAFT** merge request targeting
`main` was opened **while** the existing independent headless workflow
`wf-ff20` (orchestrator session `d7cca9be-235b-4ef0-a1a1-4ce53db59e1d`)
continues its own review and completion work. The user authorized concurrent
publication and authorized the workflow to keep committing/pushing the **same
branch** and updating the **same MR**. No stop/relaunch of that orchestrator
was performed and no production/test/shared-evidence files were edited by the
publication step beyond adding this handoff note.

## Acceptance status carried by the snapshot (unchanged)

- DRAFT only. No acceptance claim, no merge.
- Independent review175 (`independent-review-wiring-175.md`) is **REVISE**:
  R173-1 hydration/error continuations after shutdown and the R173-2 audit
  discovery-regression tests remain open findings; CORE172 acceptance is
  preserved. The staged tree includes green-in-isolation 176 receipts
  (`turn6-code-test-176-receipts/`, bounded corrections including the audit
  explicit-inventory fix), but the full suite there was interrupted
  (`full.log` is partial) and **no 176 report or completion exists** — the
  independent workflow may still be executing that partition.
- Latest complete author gate remains turn6-code-test-174: 8763 passed /
  19 deselected, smoke 288, mypy 816 files clean, chapter Black gates clean
  (see `turn6-code-test-174.md` and its receipts).
- Live installed launcher/native restart/wire/panes/paint acceptance is
  **USER-DEFERRED**; Herdr 0.9.2+ compatibility is **UNVERIFIED**.
- `security-finding-132.md` (configured-credential tool-error disclosure) is
  **separate and OPEN/UNWAIVED**. All credential-shaped strings in the
  committed tree are clearly labeled synthetic test sentinels; a staged
  high-confidence secret scan (real key formats) was clean.

## Coordination contract for the independent workflow (wf-ff20)

1. **Branch HEAD moved.** Pre-publication base/HEAD was
   `d0e3a756689f2675e5507034d43cd8b272d3c6b8`. The publication commit is a
   direct child of it; the branch is now published on origin.
   The **original base `d0e3a75…` remains the full-review baseline** — review
   diffs must continue to be computed against it, not against the new HEAD.
2. **Continue on the same branch/MR.** Commit follow-up review fixes on
   `feature-94-herdr-integration` and push normally (no force-push; the
   published history must not be rewritten). Update the existing DRAFT MR
   rather than opening a new one.
3. **Staged snapshot identity.** The publication staged-snapshot tree hash is
   recorded in the commit message of the publication commit
   (`git write-tree` before commit). The pre-staging worktree manifest lives
   at `/tmp/publication-worktree-manifest.sha256` on this host (ephemeral).
4. **Omitted raw receipts inventory** (left intact locally, deliberately not
   published; ~312 MB dominated by four ~63–67 MB `static-[A-D]-153-receipts/`
   full lint dumps): all `*-receipts/` directories under
   `docs/implementation/94-herdr/` **except** the six published ones below,
   plus root-level raw `*.log`/`*.exit`/`*.command`/`*.diff`/`*.sha256`/
   `*.txt`/`*.sh`/probe files.
   Published receipt directories (test-referenced or review-current):
   - `conventions-revision-159-receipts/` — **required**:
     `tests/implementation_checks/test_conventions_audit_paths.py` imports
     `audit.py` and `files.txt` from this path at runtime.
   - `turn6-code-test-176-receipts/` — current bounded corrections (green
     boundaries/audit/focused gates; interrupted full log retained honestly).
   - `review-wiring-175-receipts/` — the open independent REVISE evidence.
   - `independent-review-wiring-173-receipts/` — findings under correction;
     includes the preserved startup-cutoff probe referenced by 174/176.
   - `independent-review-core-172-receipts/` — latest accepted independent
     core review evidence.
   - `turn6-code-test-174-receipts/` — latest complete author full-gate
     evidence (8763 passed).
   All other raw evidence remains available locally at
   `/root/Code/slo-94-herdr-integration/slo/docs/implementation/94-herdr/`.
5. **Duplicate doc note:** `docs/t5-gateway-map-99.md` is byte-identical to
   `docs/implementation/94-herdr/t5-gateway-map-99.md`; both were committed
   (delivery-only step — no refactoring performed).
6. **No git locks were created or deleted; no reset/clean/force-push; no
   global config or auth mutation.** If any file in the published set changes
   under the workflow's feet, that change belongs to the workflow's own next
   commit.

## Publication facts (filled in by the publication step)

- Commit SHA: _see commit history of this file_
- MR: _see commit history of this file_
- Pipeline: _see commit history of this file_
