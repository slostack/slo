# Feature 86 — Step 1 documentation correction evidence

**Date:** 2026-10-03  
**Owner:** Step 1 correction (5), current-facing delivery/gate documentation only  
**Verdict:** **REVISE**

## Scope and safety boundary

This report records a documentation-only reconciliation in the current dirty checkout.
No source, test, specification, other-worktree, Git, network, credential, install, or
system/PATH change was made. Existing work was preserved.

The shared files `docs/implementation/86-openrouter/implementation-log.md`,
`current-status-2026-10-02.md`, and `remaining-requirements.md` were read but not
edited. They are shared status/history surfaces; integration can append its combined
canonical call record. Historical log entries remain historical and are not rewritten.

## Authority and claim verification

Read before correction:

- Repository/global instructions: `AGENTS.md`, repository `SLO.md`, `/root/.slo/SLO.md`,
  and root/docs `RESEARCH.md`.
- Skills: `coding/code-test-loop`, `coding/test-verification-policy`, and
  `design-and-analysis/update-documentation-after-code-changes`.
- Immutable Feature 86 materials: `overview.md`, `request.md`,
  `task-dependency-index.md`, and all six `86.a.1` through `86.a.6` contracts.
- Current evidence: `independent-full-rereview-2026-10-03.md`,
  `integration-final-retry-2026-10-03.md`, Owner 1/2/3 evidence,
  `remaining-requirements.md`, `implementation-log.md`, and current-facing documents.
- KB: `Welcome.md`, `slo/README.md`, `slo/gotchas.md`, and
  `slo/feature-86-openrouter-status.md`.

The retained gate was checked directly at
`.f86-integration-retry-ucwY1o/full-non-e2e.log`:

```text
5115 passed, 18 deselected, 196 warnings in 373.69s (0:06:13)
```

The retained integration retry report records exit code `0`. This documentation does
**not** claim that the gate was run after concurrent source corrections. The 18
E2E-marked deselections include default-disabled live/fixture harness tests; they do
not mean that offline OpenRouter tests were skipped. Executed OpenRouter evidence uses
local/mock transports. It does not establish live credentials, network reachability,
provider availability, paid inference, or authorization.

The independent rereview's current verdict is **REVISE**. Its named current findings
are admission stale-read handling, reasoning-control semantics, real error-paint
assertions, picker decomposition, and current-facing documentation reconciliation.
Therefore neither Step 1 completion nor approval is claimed here. Black/mypy are
waived only as static gates and are not represented as green.

## Changed current-facing documents

| Document | Stale claim removed | Accurate current claim inserted | Contract alignment |
|---|---|---|---|
| `README.md` | 5073 passed/15 deselected was described as latest; live opt-in and mounted/race proof were described as an older generic residual. | Retained pre-correction 5115/18/196/exit-0 receipt; 18 default-disabled live/fixture harness exclusions versus executed offline tests; no live authorization claim; concurrent corrections and independent REVISE prevent final-gate/approval language. | overview §§7.11–7.12; 86.a.6 §§7.5–7.7, 8.1, 9; F86-38–40. |
| `AGENTS.md` | Corrected full gate pointed to an older 5015 receipt; R2/R3/R4 said independent Step 2 was pending. | Retained 5115 pre-correction receipt, limits and static waiver; later independent rereview is REVISE and is the current review pointer. | overview §§7.3–7.5, 7.11–7.12; 86.a.2 §7.4, 86.a.3 §7.2, 86.a.4 §7.3, 86.a.6 §§7.5–7.7. |
| `RESEARCH.md` | Current partial-delivery summary pointed to old Call 2/current-status language and lacked the current receipt/limits. | Retained 5115 pre-correction receipt; explicit offline-only/default-disabled-E2E distinction, static waiver, REVISE/current-correction boundary, and historical-status treatment. | overview §§7.11–7.12; 86.a.6 §§7.5–7.7, 9; F86-38–40. |
| `docs/RESEARCH.md` | Current partial-delivery summary said current full/static gates remained open without the later receipt and pointed only to stale status. | Same verified gate/limits/review boundary, with current rereview pointer and dated-history preservation. | overview §§7.3–7.5, 7.11; 86.a.2–86.a.6 ownership and F86-38–40. |
| `docs/SLO_HEADLESS_README.md` | Headless route section said current full/static gates were incomplete and omitted the final retained receipt/exclusion distinction. | Retained 5115 pre-correction receipt, strict no-live/no-authorization claim, static waiver, REVISE/current-correction status, and historical qualification. | overview §7.9; 86.a.4 §§7.6–7.7; 86.a.6 §§7.5–7.7, 9; F86-22, F86-37–40. |
| `docs/SLO_SCHEDULER_README.md` | Scheduler route section treated old generic full/static-gate state as current. | Retained 5115 pre-correction receipt, 18 E2E/default-disabled harness distinction, local/mock-only limit, static waiver, concurrent-correction REVISE boundary, and historical qualification. | overview §7.9; 86.a.4 §7.7; 86.a.6 §§7.5–7.7, 9; F86-22, F86-37–40. |
| `/root/Code/KnowledgeBase/KB/slo/feature-86-openrouter-status.md` | A 67-failed/4946-passed/no-waiver result was presented as fresh/current. | The 5115 pre-correction receipt, explicit default-disabled E2E versus offline-executed distinction, static waiver, REVISE rereview, and no completion/approval claim. The old result is explicitly historical. | Durable pointer for overview §§7.11–7.12 and 86.a.6 §§7.5–7.7, 9; F86-38–40. |

No other allowed current-facing location had a distinct stale delivery/gate claim that
needed correction. The canonical current status and remaining-requirements surfaces
were deliberately left to the shared integration record under the user-specified race
prevention rule.

## Verification

- Read the retained full-log terminal summary and retry report exit receipt.
- Grepped all changed current-facing documents for `5073`, `5065`, `5115`,
  `15 deselected`, `18 deselected`, `pending`, `REVISE`, `Black`, `mypy`, and
  Feature 86 wording.
- Reviewed the final documentation-only diff with `git diff --check` and
  `git diff -- <changed documentation paths>`.
- No tests were needed or run: this change introduces no executable behavior.

## Handoff

**REVISE.** The documentation correction is ready for integration review, but Feature
86 remains under independent review and concurrent source correction. A new full
non-E2E result is required after those corrections before any final-gate, completion,
or approval statement can be made.
