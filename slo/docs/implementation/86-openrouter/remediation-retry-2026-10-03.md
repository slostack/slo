# Feature 86 Step 1 remediation retry — 2026-10-03

Disposition: **REVISE**. This is implementation evidence, not Step 2 approval or a
completion assessment. One sequential API assistant session, no subagents/workflows.
The API did not expose an exact model identifier; none is invented. Prior dirty work,
specifications and historical reports were preserved. No git mutation or external
provider request was made. Black/mypy were waived, not run or claimed green.

## Finding → clause → cause → red → correction → green

- **A / G1**, a.2 §7.4, overview §7.4: publication checked identity before its final
  await. `service.py:492–498` now observes the published reference and rechecks the
  effective fingerprint after cache loading, before the no-await swap. Deterministic
  `test_openrouter_final_read_race.py` holds delivery after real temp-store bytes were
  read. Rotation rejects; an intervening publication remains the identical snapshot.
  Red: 2 failed. Green with admission-security suite: 17 passed. Limitation: the new
  winner fixture uses the same membership; stronger distinct-cap/membership final-read
  proof and cross-process ordering review remain required. This is not a claim of
  complete atomicity against every external writer.
- **B / G2**, a.2 §7.2, overview §7.3, a.3 §7.2: omitted efforts were conflated with
  explicit null and disable permission was lost. Converter now treats omitted efforts
  as unavailable; capability `reasoning_disable_available` defaults false and flows
  through factory/request policy independently of enabled efforts. Corrected real SDK
  wire oracles first: 4 failed / 12 passed. Green reasoning/converter partition:
  58 passed. Existing explicit-disable helper test now supplies explicit permission.
  Summary-cap and continuation code was not changed. Remaining: expand enabled-level
  matrix and review cache migration/default behavior for old cached capabilities.
- **C / G3**, a.5 §7.6: session refresh only returned fixed text. Session notice now
  adds published OpenRouter row count and lifecycle last-complete-check time, or
  unknown. Red: 4 failed. Green: 4 passed (fresh/refreshed/failed/credential_changed).
  Existing snapshot test retains one load and adds output assertions. Remaining:
  nonempty/unknown/coalesced/router-painted coverage and count semantics under hidden
  or ineligible rows need explicit acceptance verification.
- **D / G4**, a.4 §4 and overview §7.9: pending guard rejected direct models.
  Prepared direct selections now pass; pending OpenRouter choices remain rejected.
  Startup captures config identity and discards late success/failure if selection
  replaced it. Red: 2 failed. Green: 2 passed, including late success/failure,
  exact route, ready state, snapshot, pool clearing and preference call. Existing
  mounted negative tests now request an OpenRouter route, the still-forbidden case.
  Remaining: mounted positive direct recovery and complete cancellation paths.
- **E / G5**, a.6 §8.1 / §7.5, a.2 §8.4: added the exact provenance README at
  `tests/fixtures/openrouter/README.md`, explicitly synthetic, with inline fixture
  owners and sanitization limits. Updated README and current-status gate pointers;
  preserved all prior reports. **Not implemented:** required
  `tests/integrations/openrouter/test_live_openrouter.py`, separately authorized GET
  and paid opt-in controls, paid cap/request-bound tests, and prescribed fixture bundle.
  No empty/always-skipped placeholder was added. No live execution is claimed.

F1/R2/R3/R4 production owners were not modified by this retry. Full non-E2E tests
include their existing regressions; this is not an independent security certification.

## Commands and retained evidence

Owned evidence root: `.f86-remediation-retry-QS5PwP/` (absolute path is also recorded
in `.f86-remediation-retry-path`). Focused invocations used the same clean environment,
interpreter, no-cache option and unique basetemp names as the command below.

```sh
d="$PWD/.f86-remediation-retry-QS5PwP"
env -i HOME="$d/home" TMPDIR="$d/tmp" SLO_HOME="$d/home/.slo" \
  SLO_AUTH_FILE="$d/home/authentication.json" \
  PATH=/root/.pyenv/versions/slo-harness/bin:/usr/bin:/bin \
  PYTHONPATH="$PWD" PYTHONDONTWRITEBYTECODE=1 SLO_AUTO_VISUALIZE=0 \
  timeout 1200 /root/.pyenv/versions/slo-harness/bin/python -B -m pytest \
  -p no:cacheprovider --basetemp="$d/full-final-temp" -m 'not e2e' tests \
  > "$d/full-final.log" 2>&1
```

- `red-a.log`: 2 failed, pytest exit 1; `green-a.log`: 17 passed, exit 0.
- `red-b.log`: 4 failed / 12 passed; `green-b.log`: 58 passed.
- `red-d.log`: 2 failed; `green-d.log`: 2 passed.
- `red-c.log`: 4 failed; `green-c.log`: 4 passed.
- First complete gate `full-non-e2e.log`: 6 failed, 5067 passed, 15 deselected,
  199 warnings, 356.00s, exit 1 (`full-exit.txt`). Five failures were old contract
  expectations / duplicate load. Mounted auth failed its painted success check;
  no production auth patch or arbitrary sleep was used. Its focused rerun passed.
- `corrections.log`: affected capability/session/startup/full-flow files,
  **47 passed, 5 warnings, 46.57s**, exit 0.
- Fresh complete `full-final.log`: **5073 passed, 15 deselected, 202 warnings,
  353.16s**, exit **0** (`full-final-exit.txt`). Only non-E2E marker exclusion.
  Run after final source/test edits; subsequent edits were evidence/docs only.
- Post-suite `dpkg -V coreutils`: exit 0, no output.

No new tests were skipped/xfail or disabled. The live harness remains absent rather
than adding another deselected placeholder. Existing 15 E2E tests remain deselected.
The initial mounted auth failure is retained as an unexplained intermittent signal,
not erased by the later green gate. All remaining acceptance limitations above must
be resolved before READY. Documentation is factual, not formal review approval.
