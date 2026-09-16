# Slotui integration starting point

**Status:** Initial implementation-branch manifest; no integration code exists.

This branch begins the Slo side of the proposed `79.integration` plan. It is not
release evidence, a package pin, or permission to switch or delete the current
Textual/Rich UI. Canonical specifications remain external to this repository and
are intentionally not copied or modified here.

## Verified baseline and source references

| Item | Value | Basis |
|---|---|---|
| Slo integration baseline | `d7d57487bf4da74d8f03caddde09bc719375b46a` | Exact `origin/main` commit used to create this branch. |
| Slotui main | `07ee60895dcd95590fca91541786077bc873329c` | User-provided value; not independently available in this Slo clone. |
| Excluded Slotui a.9 work in progress | `0feea0003574485ab104af3137dc99ec104a80ea` (`feature-79-a9-rich-content`) | User-provided SHA independently confirmed as the checked-out a.9 worktree HEAD. It is excluded from this branch. |

## Current state and exclusions

- There is **no Slotui integration code** in this baseline: no Slotui package
  dependency, consumer pin, event/session relay, history/replay migration,
  slash bridge, presentation migration, default switch, deletion, or release
  integration is present.
- a.9 rich content is **BLOCKED/WIP**, not a release candidate. Its known
  blockers are unresolved conformance fixtures, required PTY/frame-and-
  scrollback proof, and independent review/completion evidence. It must not be
  consumed through a local worktree, path/editable dependency, or source
  fallback.
- This file is a branch-local orientation manifest only. It does not replace
  the canonical integration specifications, their ledger, release manifest, or
  proof artifacts.

## Canonical integration specifications

Resolve the operator-local `specifications/` symlink, then read:

- [`79-tui-v2/integration/overview.md`](../../specifications/79-tui-v2/integration/overview.md)
- [`79-tui-v2/integration/tasks.md`](../../specifications/79-tui-v2/integration/tasks.md)
- [`79-tui-v2/integration/79.b.2-characterize-slo-integration-baseline.md`](../../specifications/79-tui-v2/integration/79.b.2-characterize-slo-integration-baseline.md)

The relative links intentionally target the worktree's operator-local canonical
specifications symlink; they do not create or copy canonical specification
content into this repository.

## Required dependency and release order

1. **b.2:** characterize and approve the Slo baseline ledger before any Slo
   replacement.
2. **Slotui prerequisites:** b.0 stream-schema parity (including identity
   mapping for `preflight_bypassed`), b.0.1 released mounted live transcript,
   and b.8 completed a.9 rich-content certification.
3. **b.1:** protected Slotui release produces one immutable
   `ReleaseManifestDAO` and downloaded-wheel proof.
4. **b.3:** Slo verifies and pins exactly that released wheel in a clean Python
   3.11 environment. No local/worktree/path/editable/git fallback is allowed.
5. Only then may b.4--b.7 implement generic relays, history/replay, slash, and
   opt-in presentation. b.9 alone can decide default selection, deletion, and
   release after its fresh conformance, PTY, rollback, and resume evidence.

## First implementation gate

Do not add a Slotui dependency or integration code. First implement **b.2** as
characterization-only work: create the named baseline fixtures, normalizer,
comparator, and approved ledger; run its exact tests; and obtain the required
Slo release/documentation-maintainer approval for any deviation. This preserves
current production behavior and creates the evidence needed by all later work.
