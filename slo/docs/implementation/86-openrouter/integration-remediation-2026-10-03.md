# Feature 86 — integration remediation, call 2 of 4

Date: 2026-10-03. Verdict: **REVISE** (fresh functional gate green; remaining verification below).

## Scope and ownership

This session continued the authorized Step 1 integration in the existing dirty checkout. No Git mutation, specification change, other-worktree edit, installed-environment change, or live provider request was performed. No workflow or sub-agent was launched. Model identity is not exposed by this API session and is not invented here. Prior owner4/owner6 reports remain preserved.

## Reproduced failure and actual cause

The strengthened real-service mounted rejection test reproduced **5 failed, 3 passed, 3 deselected** in 29.56s, `.f86-current-red-59Q2lK/red.log` (pytest exit 1). The expected full messages were present in the status widget. Whole-viewport concatenation includes modal border cells between wrapped lines, so whitespace normalization alone cannot join wrapped text. The failures correlate with wrapping at both 80x24 and 60x15; this was not evidence that production truncated the messages.

Changed `tests/tui/authentication/_painted_output.py` to permit waiting on the compositor region of a specific widget, clipped to the screen. `tests/integration/test_openrouter_full_flow.py` now positively asserts the complete expected message in those painted cells and separately checks the full viewport for the candidate secret. No truncation, sleep increase, assertion removal, or production layout workaround was needed. Prior production layout/auth changes are retained.

The intermediate scoped-paint diagnosis passed all eight cases: `.f86-current-paint-YM7QXE/result.log`, **8 passed, 3 deselected**, 29.82s. Final region-scoped barrier plus surrounding auth/viewport/flow characterization: `.f86-current-ui-UikV8J/result.log`, **77 passed, 1 deselected, 5 warnings**, 24.73s.

## Picker integration

The prior child had already extracted empty-query ordering, recency lookup, ranking, and state construction. After running its characterization tests green, completed the prescribed owner-local names/seams in `src/tui/slash_suggestion_engine.py`: `_matching_model_entries`, `_empty_query_entries`, `_bounded_model_state`. `_bounded_model_rows` now delegates matching and row projection; `_model_row` retains literal canonical identity. Removed the redundant nested blank-query rank expression: blank ordering belongs to `_empty_query_entries`, not nonblank match ranking. Existing cap, total count, offset, ghost, active/recent, literal paint, and offline-cache tests remain intact.

Clauses: overview §7.10a; 86.a.5 §§7.3–7.6, 8.2–8.3; F86-02/19/30/31/39/41. Owner4 covers admission and reasoning corrections under its preserved report; owner6 documents the accurate pre-correction baseline.

## Fresh affected and complete gates

All runs used `/root/.pyenv/versions/slo-harness/bin/python -B`, cache-disabled pytest, fresh checkout-local HOME/TMPDIR/SLO_HOME/SLO_AUTH_FILE and basetemp. Final runs use `env -i`, explicit PATH and PYTHONPATH; tool timeout was 1200 seconds. No ordinary `/tmp` was intentionally used as a test root.

- Affected partition: `tests/tui tests/integration tests/agents/model_catalog tests/agents/providers/test_openrouter_reasoning_semantics.py`: **1510 passed, 1 deselected, 45 warnings in 245.99s**, exit 0. `.f86-current-affected-uo5r6i/result.log` and `exit`.
- COMPLETE final non-E2E: **5122 passed, 18 deselected, 196 warnings in 329.09s**, exit 0. `.f86-current-full-hONnN8/full-non-e2e.log`, `exit`, and exact expanded `command.txt`.
- Command shape: `env -i PATH=/root/.pyenv/versions/slo-harness/bin:/usr/bin:/bin HOME=<owned>/home TMPDIR=<owned>/tmp SLO_HOME=<owned>/slo SLO_AUTH_FILE=<owned>/slo/auth.json PYTHONDONTWRITEBYTECODE=1 SLO_AUTO_VISUALIZE=0 PYTHONPATH=$PWD /root/.pyenv/versions/slo-harness/bin/python -B -m pytest -p no:cacheprovider --basetemp=<owned>/base -m 'not e2e' tests`.
- `git diff --check`: exit 0. Post-suite `dpkg -V coreutils`: exit 0, empty `.f86-current-full-hONnN8/coreutils-verification.log`.

No source/test edit followed the complete gate. Warnings are retained, including unawaited AsyncMock warnings. The 18 ordinary E2E exclusions are preserved; default-disabled live/fixture harness tests are not live proof. Executed OpenRouter tests are local/offline transport tests. Black/mypy remain waived, not green. No paid inference, live authorization, credential entitlement, or feature approval is claimed.

## Remaining requirements / reason for REVISE

1. Add explicit assertion-sensitivity coverage showing a suppressed status paint fails the positive compositor assertion; this call established the wrapping cause but did not execute that mutation check.
2. Extend listing-time credential-change mounted paint to both mandated dimensions (the existing case is not parameterized over both).
3. Review the remaining G3 real session/router refresh count/time painter assertion rather than treating separate string/router tests as composed proof.
4. Complete bounded spec-reading reconciliation: the combined overview/request/dependency/a.1/a.2 read was tool-output truncated. The absent checkout spec link was not repaired. Do not claim complete clause-by-clause review from that truncated output.
5. Independent review and completion assessment still follow. A new full gate must follow any further source/test correction.

These prevent STEP1READY despite the fresh green full gate. Canonical status/checklist receive this qualified receipt; pre-correction current-facing summaries remain valid historical descriptions and must not be replaced with approval language.
