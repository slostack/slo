# Feature 86 Step 1 — finite gaps A–D evidence

Date: 2026-10-03. Scope: Code + Test Loop only. This is not Step 2 approval or Step 3 completion.

## Implementation

- **G1 presentation/router:** `ModelSuggestionEntryDAO` now carries the canonical
  `reasoning_disable_available` evidence through the presentation projection.
  Picker detail distinguishes `reasoning disable supported` from enabled efforts
  whose disable permission is absent (`reasoning low, high; provider default`).
  `SlashRouter` accepts `/reasoning off` for a disable-only OpenRouter route and
  rejects `/reasoning off` where the route has known enabled efforts but has not
  advertised provider-side disable. The menu brings the disable-only semantic
  state first so the bounded 80×24 and 60×15 presentation retains it; ordinary
  detail order remains unchanged.
- **G2 budget evidence:** strict optional `supports_max_tokens` was already
  converted and schema-2 persisted. Added prepared-entry → real factory/SDK local
  MockTransport checks for `True`, `False`, and absent metadata. They prove the
  evidence remains readable and that no `reasoning.max_tokens` or
  `reasoning_max_tokens` wire control is produced. The SDK response intentionally
  exercises request serialization only; its malformed minimal response is caught
  after one local request.
- **E1:** retained the existing real schema-2 first-read barrier tests. They use
  the actual store loader and prove public admission rejection after an external
  missing-ID publication or credential rotation. The removal path correctly calls
  ordinary refresh because membership is absent; its existing test injects a
  `fresh` refresh outcome and asserts no client construction. This is not claimed
  as an all-real zero-HTTP removal proof. No production admission change was
  required by the current counterexample.
- **Auth / selection:** the existing 80×24 and 60×15 positive auth compositor
  tests and sensitivity-negative control passed in the affected partition. The
  historical selection offset failure did not reproduce in the focused test or
  the complete suite. No skip, sleep, assertion weakening, or speculative source
  repair was added; it remains historical diagnostic evidence without a causal
  diagnosis.

## Test-first cadence

1. G1 picker semantic tests: red (two missing detail distinctions), then green
   (4 passed).
2. G1 router tests: red (disable-only rejected and unknown disable clamped), then
   green (15 router reasoning tests passed).
3. G2 prepared/no-budget SDK matrix: red while exercising the local wire path,
   then green (9 budget-evidence tests passed) after using the actual one-request
   capture path.
4. Mounted G1 two-size picker test: red through several genuine Textual mounting,
   visibility, and narrow-detail truncation failures; green only after the menu
   rendered disable-only state first. The final node passed 2 tests at 80×24 and
   60×15.

## Gates and receipts

All commands used `/root/.pyenv/versions/slo-harness/bin/python -B`, `env -i`,
checkout-owned `HOME`, `TMPDIR`, `SLO_HOME`, isolated pytest base directories,
`PYTHONPATH` set to the checkout, and disabled pytest cache. No external network,
live credential, or paid inference was used.

- Affected partition: **92 passed, 2 warnings**, exit 0 —
  `.f86-step1-1791030525-affected-green/affected.log`.
- Fresh complete non-E2E gate after the final source/test edit: **5145 passed,
  18 deselected, 196 warnings in 332.10s**, exit 0 —
  `.f86-step1-1791030546-full/full-non-e2e.log`; exact command and exit are
  alongside it.
- Frozen manifest after the complete gate: `.f86-step1-1791030910-receipt/`
  (`source-test-sha256.txt`, `source-test-manifest.sha256`, `git-status.txt`, and
  `diff-check.log`). Manifest SHA-256:
  `8134ea70e5ecdd99aaf7f373cb57e95e509dab8be2848eba27629e8131f9cfa3`.

## Limits / disposition

The 18 deselected tests are live/default-disabled E2E/fixture harness cases; this
is offline local/mock-transport evidence, not OpenRouter authorization,
availability, network, or paid-inference proof. Black and mypy were not run and
remain explicitly waived static gates, not green results. The all-real removal
refresh composition described above remains a mandatory finite evidence gap, and
independent Step 2 / Step 3 remain pending.
