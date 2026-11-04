# Claude fragment fix — initial runnable milestone

> Commit excerpt: recorded phase evidence, not a new verification run.
> Superseded dispatch histories are omitted from this commit and preserved
> in the local working copies. References to historical sections or mappings
> "below" refer to those originals. The completion document contains the
> consolidated acceptance mapping; handoff verdicts describe their own phase.

## Current verdict: READY for independent re-review — revision turn 2 / dispatch 1

Current closure evidence (2026-11-03) is in **R4/R5 revision closure** below.
The independent review's REVISE verdict remains the last reviewer verdict; this
READY is author readiness only, not independent acceptance or workflow completion.

## R4/R5 revision closure

Scope: supplied turn 2 / dispatch 1, unlimited workflow budgets. No agents,
detached workflows, commits, full suite, static checks or unrelated gates.
Preserved existing dirty work and valid fragment behavior. Reused the handoff's
Python/SDK assembly and real graph/history routing; read governing vendored shared
ownership/testing, coding rules/cadence/test policy, declarative structure and
Python conventions, keyword/type/docstring and SDK-client guidance. README,
RESEARCH, KB entry/slo README/gotchas and independent review consulted.

### Repairs and coverage

- **R4 / CF03–04:** `NativeResponseAssembly.reconcile_echo` validates every supplied
  message ID as a string before explicitly falling back for None/empty string.
  Eight official-parser cases cover false, zero, empty/nonempty lists/dicts and
  true/one. None/empty compatibility has two positive cases; existing omitted-ID
  and identified late-fragment cases remain green. Four negative SDK journeys
  carry a pending valid tool and malformed falsey IDs.
- **R5 / CF04–05:** `NativeBlock.complete_call` validates decoded arguments with
  existing strict `json_identity` before constructing a call. This covers nested
  NaN, Infinity, -Infinity and positive/negative exponent overflow, regardless of
  whether any assistant echo arrives. Five direct cases and five no-echo SDK
  journeys cover these forms. A finite nested JSON success case preserves null,
  booleans, integer/floating values, large finite exponent, strings and objects.
- All nine added negative journeys traverse official SDK parsing, runtime,
  production graph and real temporary filesystem history. They assert no
  tool_call/tool_result/run_completed in stdout or persisted events, one persisted
  failure, bounded protocol error, one prompt and one transport close. Direct
  cases assert stream_protocol_failed and no assembly calls; nonfinite direct
  errors assert the exact payload-free diagnostic.

Changed in this revision: `src/bridges/claude/sdk/response.py`,
`tests/bridges/claude/test_fragments.py`,
`tests/bridges/claude/test_response_boundaries.py`, this handoff and local durable
memory. No transport/runtime/CLI implementation changes. Manual affected-source
review confirmed validation precedes executable publication and no echo dependency
remains; this is not independent review or a static-tool conformance claim.

### Exact evidence

CWD `/root/Code/claude-bridge/slo`, same command for RED and GREEN:

```bash
export VIRTUAL_ENV=/root/.pyenv/versions/slo-harness PATH=/root/.pyenv/versions/slo-harness/bin:$PATH
SLO_ENV=test SLO_HERDR_DISABLED=1 PYTHONPATH="$PWD" poetry run pytest -q tests/bridges/claude tests/cli/test_claude_bridge.py
```

1. Test-first RED: **20 failed, 183 passed, 56 warnings, 8.46s**.
   `/tmp/claude-r4-r5-red.txt`. Four falsey identity cases and five nonfinite
   cases DID NOT RAISE; nonempty containers leaked TypeError; all nine journeys
   failed forbidden-publication assertions. True/one already rejected. The shell
   wrapper returned 0 because it tailed the log after pytest; pytest was failing,
   not a green gate. No assertions were relaxed to obtain green.
2. After the two production repairs: pytest and wrapper **exit 0, 203 passed,
   47 warnings, 9.57s**, no skips. `/tmp/claude-r4-r5-green.txt`.
   Existing 178 cases plus 25 new cases. Warnings are the existing
   pythonjsonlogger/LangGraph/Pydantic deprecations.

Only the authorized feature pytest gate ran, twice. Existing isolated test home
and temporary history fixtures retained; no command stubs or system changes.
Full suite, static/formatter/build checks and live-native parity remain unrun by
scope. Independent affected-boundary re-review and workflow completion remain
pending. No follow-up conversation support or unrelated acceptance claimed.
