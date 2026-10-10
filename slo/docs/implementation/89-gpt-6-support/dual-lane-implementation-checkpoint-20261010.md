# Feature 89 dual-lane correction — implementation checkpoint

## Verdict: REVISE; independent review pending

Substantive production correction implemented inline on feature-gpt_6_support at HEAD ea8601c53f04fa06a0baeeb47d385c44cc9a5364. No nested orchestration, install, commit, external publication or live inference. This is an implementer receipt, not self-review or feature approval. Kimi-k3/max independent review remains separate and pending.

## Production changes

- Exactly the three existing GPT-6 seed registrations now permit Codex OAuth; required Responses remains independent. Frozen reasoning/default-only controls, eligibility checks and writer-only exclusions remain intact.
- LLMFactory passes its captured credential type into constructor policy. Strict Platform validation and temperature consumption apply only to API_KEY plus required Responses. OAuth retains the existing Codex builder, endpoint, headers, include/store/cache and cap/instructions adaptation. No second credential resolution or substitution was added.
- Picker presents `subscription configured; not checked`. A retained failing 60-column compositor assertion exposed context clipping. Subscription detail now splits status from context, using the existing variable-height bounded menu. Other direct rows retain their layout. This is a narrow extra-line deviation from the original two-line direct-row plan, not relaxed paint or row-count assertions.
- README, AGENTS and both RESEARCH files describe dual-lane support. Historical receipts are unchanged.

## Test-first evidence

All receipts below are `.f89-evidence/<name>.{command,log,exit}` unless noted.

| Receipt | Actual outcome |
|---|---|
| dual-catalog-red | 13 failed, 87 passed: old False eligibility |
| dual-catalog-green | 472 passed: catalog/reasoning/defaults surrounding partition |
| dual-policy-red | 2 failed, 13 passed: Platform temperature consumption incorrectly intercepted OAuth |
| dual-policy-green | 95 passed: credentials/Codex/factory surrounding partition |
| dual-wire-green | 429 passed, including 42 streamed SDK tool cycles |
| dual-picker-red | 1 failed, 2 passed: missing subscription status |
| dual-picker-green | 1 failed, 73 passed: 60-column context clipping |
| dual-picker-paint-green | 77 passed after bounded detail correction |
| dual-json-tool-green | 471 passed, including 42 streamed plus 42 nonstreaming JSON tool cycles |
| dual-mounted-green | 12 passed mounted three-model × off/medium × both-lane tools/resume |
| dual-headless-green | 33 passed full integration module at that point |
| dual-pool-green | 1 failed, 3 passed: test incorrectly expected Platform retries on Codex |
| dual-pool-retry-green | 4 passed: Codex correctly retains zero SDK retries |
| dual-capacity-green | 9 passed: Platform reserved cap versus Codex instructions/no caps |
| dual-refresh-green | 35 passed: selection plus real resolver/store/refresher with injected provider refresh result |
| dual-rotation-green | 37 passed: allowed credential-type rotations, removal remains atomic |
| dual-keyboard-green | 49 passed: presentation module, both-lane keyboard at both sizes |
| dual-type-fix-green | 471 passed after correcting two new test typing errors |

## Final gates after final source/test/support-document edits

- `/bin/bash .f89-evidence/run-test.sh dual-final-full -q -m 'not e2e'`: **6058 passed, 18 deselected, 299 warnings in 433.12s; exit 0**. Includes real frozen schema-2 and v0.20.1 compatibility tests, observer/isolation, existing Jev and legacy regression partitions. Synthetic only. Warnings include unawaited AsyncMock RuntimeWarnings; full output retained.
- Changed Python Black: **40 files unchanged; exit 0** (`dual-final-black-changed`). This explicit command covers all dirty feature Python, not just this dispatch.
- Full Black: **13 would reformat, 654 unchanged; exit 1, UNWAIVED** (`dual-final-black`). Frozen HEAD: 19 would reformat/635 unchanged. All 13 current failures belong to the frozen set. Exact paths retained in `dual-final-static-comparison.json`.
- Full mypy src/ tests/: **296 errors/59 files, 667 checked; exit 1, UNWAIVED** (`dual-final-mypy`). Fresh frozen HEAD: 296/59, 654 checked. Normalized exact diagnostic multisets have zero added and zero removed occurrences. The earlier `dual-mypy` receipt retains two new test errors; those were fixed rather than waived.
- Final `git diff --check`: empty/0 (`dual-final-diff-check`). Post-suite `dpkg -V coreutils`: empty/0 (`dual-final-post-suite-integrity`). These are read-only verification, not host changes.
- Existing approved env-i runner inspected before execution; HOME/SLO_HOME/TMPDIR resolve beneath .f89-evidence, preimport and per-test isolation retained. Authorized safe symlink fixture correction left intact. Static runner uses contained real git archive, not a worktree or copied dirty baseline.
- Fresh versions and lock comparison: `dual-final-versions.log`; OpenAI2.38.0/Pydantic2.13.4, Python3.11.7. No setup repeated.

## All fifteen ACs — current evidence and limits

| AC | Evidence / status qualification |
|---|---|
| 1 | Exact seed profiles and opposite cached False preservation now pass; unchanged no-Jev/no-family-template tests. Synthetic negative merge path still needs an explicit opposite cached True case. |
| 2 | Existing 21 reasoning cells plus 84 two-lane streamed/JSON tool cases; explicit off semantics proven. Omitted-medium OAuth wire discriminator still pending. |
| 3 | Real factory/locked SDK: 21 streamed and 21 JSON tool/result cycles per lane; exact IDs, headers/URL/model/auth, one real echo, successful answer. 12 mounted/resumed cases. |
| 4 | Retained Platform protected merge matrix passes; new OAuth duplicate-temperature test proves strict constructor policy is not imposed on OAuth. |
| 5 | Real env-key precedence for all three; synthetic distinct factory/session denial; real selection and near-expiry refresh owner with injected provider result. Detailed refresh failure/cancel/no-refresh-token/malformed/account and pool-secondary refresh matrix remains pending. |
| 6 | Existing entry paths pass; mounted current CLI resume now covers both lanes. Allowed type rotation test builds final lane, but does not yet assert that build's actual wire. Explicit/default/preference/child matrix has not been independently doubled for OAuth. |
| 7 | Neutral cached status, both-size paint and keyboard under both lanes pass. Existing five cache discriminators retained. Synthetic ineligible picker negative still pending. |
| 8 | Frozen control/default-only guard, snapshot and memory/writer tests retained and green; required transport description corrected. |
| 9 | Both-lane real compaction transaction proves reserved Platform cap versus Codex no cap/instructions; total context/advisory unchanged. |
| 10 | Existing committed-output and cancellation cases pass; added Codex/Jev fallback in both orders. OAuth-specific committed-failure/cancellation expansion still pending. |
| 11 | Full suite executes real pre-feature v2 and released history/cache/observer proofs. No schemas or stores changed. |
| 12 | Fresh complete functional suite green; static baseline failures unwaived. No unrelated formatting repair. |
| 13 | Jev converter/null/absent/invalid metadata and conservative cap semantics unchanged, full suite green. |
| 14 | Real admitted Jev tools plus Platform/Jev and Codex/Jev fallback directions pass with separate transports. |
| 15 | Existing Jev lifecycle/admission/headless/resume remains green; direct OAuth headless and mounted resume added. Full expanded credential sentinel scanning across all new OAuth artifact cases remains pending. |

## Finite next implementation handoff

Do not redo completed runtime owners or setup. Finish the specifically qualified acceptance cells above in small tested units: (1) distinct synthetic negative merge/picker; (2) omitted-medium OAuth wire; (3) real refresh failure/cancellation/no-op/malformed/account plus primary/secondary pool, with public invoke lock cleanup and actual refreshed bearer wire; (4) explicit/default/preference/child OAuth entry composition; (5) OAuth committed-failure/cancellation and complete synthetic sentinel scan. The near-expiry test currently delegates through real refresher/store/lock but patches provider.refresh to a synthetic result: it is not refresh HTTP serialization proof, and its token string is unchanged across refresh (expiry changes). Strengthen with distinct before/after JWTs.

Then rerun changed Black, fresh diagnostics and the full non-E2E suite after any source/test/support-doc changes. If only the attributed baseline static failures remain, return REVISE without unrelated functional or formatting work. No waiver is inferred. Independent reviewer and completion assessment must follow separately; no live entitlement, subscription availability, paid inference, release readiness or feature-complete claim.

This report is written after gates; it changes no source/test/support document and does not supersede historical recovery13 evidence retroactively.
