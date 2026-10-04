# Feature 86 — permitted Step 1 integration retry, 2026-10-03

## Verdict: READY for Step 1 handoff

The three requested synthetic harness/fixture blockers are resolved in executable
code, with a fresh COMPLETE non-E2E gate: **5115 passed, 18 deselected, 196 warnings
in 373.69s; exit 0**. No formal Step 2 or completion assessment was performed.
Black/mypy are waived, not green. This is not live-provider acceptance.

Provenance requested by the user: call1 parallel **gpt-5.6-terra medium**;
call2 prior integration **gpt-6-astra medium**; this retry call3
**gpt-6-astra medium**. These are supplied labels, not independently attested
backend identities. This retry made **zero spawn/workflow calls**.

## Delivered boundaries

Only the Owner 3 harness, a new default-gate integration test module, fixture
README and current evidence documents changed. No production source, Owner1/2
boundary tests, immutable specs or historical reports were edited. Dirty and
untracked work was retained; no Git mutation command was used.

- `tests/integrations/openrouter/test_live_openrouter.py` now provides
  `invoke_fixture`: explicit consent is checked before resolver, HTTP client or
  production GET client construction. Discovery performs `/key` then
  `/models/user` through `OpenRouterAPIClient` and `OpenRouterCatalogConverter`.
- Separately enabled fixture smoke requires one exact discovered route. Real
  `OpenRouterChatOpenAI` and SDK streaming decode run against MockTransport,
  bind and execute one harmless no-argument `fixture_echo`, and send its result
  plus private reasoning continuation on request two. SDK retries are zero.
  Additional, unknown, argument-bearing or multiple tool calls are rejected.
- `BoundedFixtureTransport` is a MockTransport subclass, not a socket transport.
  It independently enforces the production origin/endpoints, exact route,
  positive output cap no greater than 256, and at most two inference attempts.
  Discovery mode denies inference. Failures do not reset the attempt count.
  The second response asking for another tool terminates without a third call.
- `test_harness_contract.py` runs **24 tests in the normal non-E2E gate**:
  disabled construction tripwires; production GET/converter discovery; SDK
  continuation and 429 no-retry; extra/wrong/multiple/argument-bearing tools;
  exact route admission; transport origin/endpoint/cap/request limits; real
  candidate authentication, persistence, catalog publication and disk reload;
  auth/protocol refusal before persistence.
- Every existing bundle payload now has a meaningful consumer: key/models through
  real auth/catalog, errors through auth and adapter, SSE through actual SDK
  streaming, private anchor through the second adapter request. The README maps
  exact filenames to those consumers and preserves authored synthetic provenance.
  No observed public fixture or live capture was fabricated. Existing filenames
  are retained rather than duplicating overview §7.11's representative names.

The immutable clauses read were 86.a.6 §§7.7/8.1 and overview §7.11, plus related
integration/security/report requirements. The current request explicitly bounds
this retry to synthetic enabled execution; no real-transport procedure was added.
A future live procedure still needs fresh authorization and review. No live key,
GET, DNS, paid inference, route availability or locked-SDK compatibility claim is
made. The harness uses the production adapter directly; candidate auth/catalog
publication is separately composed in the new tests, with existing full-flow
factory/session tests included in surrounding and full gates.

## Test-first evidence

Root: `.f86-integration-retry-ucwY1o/`. All pytest runs used the approved Python
3.11.7 `/root/.pyenv/versions/slo-harness/bin/python -B`, env-i isolated HOME,
TMPDIR/SLO_HOME, checkout PYTHONPATH, cacheprovider disabled and fresh basetemp.
Logs retain complete failures; `.exit` files retain actual pytest statuses.

| Artifact | Result |
| --- | --- |
| `red1.log` | 5 failed: missing integrated harness entry point |
| `green1.log` | 25 passed, 3 deselected: discovery/construction gate plus surrounding client tests |
| `red2.log` | 3 failed, 5 passed: paid mode did not execute the SDK tool round trip |
| `green2.log` | 3 failed, 5 passed: implementation used nonexistent `picker_visible` field; corrected to canonical `visible_in_picker` |
| `green2b.log` | 28 passed, 3 deselected |
| `red3.log` | 4 failed, 11 passed: missing independent bounded transport |
| `green3.log` | 35 passed, 3 deselected |
| `assets.log` | 18 passed: added real auth/catalog bundle consumers; this was coverage of existing behavior, not falsely claimed red |
| `surrounding.log` | 70 passed, 3 deselected, 5 warnings; includes existing full-flow, transport and fragmented-continuation suites |
| `full-non-e2e.log` | 5115 passed, 18 deselected, 196 warnings, exit 0 |

No sleeps, xfail, skips, relaxed assertions, fake production endpoints, external
requests, package installs or shared interpreter/skill changes were introduced.
Functional final gate is green; warnings include existing unawaited AsyncMock
warnings and are not suppressed. Historical mounted-auth paint miss remains an
unexplained reliability signal; another full-order success is not causal repair.

## Full gate and inventories

Exact expanded command is retained in `full-command.sh`; it runs:

```sh
env -i HOME='<root>/home' TMPDIR='<root>/tmp' SLO_HOME='<root>/slo-home' \
 SLO_AUTH_FILE='<root>/home/authentication.json' \
 PATH=/root/.pyenv/versions/slo-harness/bin:/usr/bin:/bin \
 PYTHONPATH='/root/Code/slo-openrouter-implementation/slo' \
 PYTHONDONTWRITEBYTECODE=1 SLO_AUTO_VISUALIZE=0 \
 timeout 1200 /root/.pyenv/versions/slo-harness/bin/python -B -m pytest \
 -p no:cacheprovider --basetemp='<root>/full-basetemp' -m 'not e2e' tests
```

Root resolution and absence of the fresh nonsymlinked basetemp were checked before
execution. `full-exit-code.txt` is **0**. Only documentation follows that gate.
`e2e-inventory.log` was collected, not executed: 18 ordinary exclusions comprise
2 hosted-installer tests, 6 installer-smoke cases, 6 wheel/packaging tests,
3 legacy synthetic OpenRouter E2E-marked checks, and 1 live OpenAI device test.
No extra deselection was added. The meaningful harness checks are not among those
exclusions. The 3 legacy E2E checks were not executed in this retry.

Post-suite `git diff --check`: exit 0. Post-suite read-only `dpkg -V coreutils`:
exit 0, empty `coreutils-verification.log`. These are not exhaustive syscall
proofs. New persistence tests reuse the inspected real-store fixture, which
resolves its private root beneath pytest tmp_path before constructing writers and
blocks default sync/async HTTP transports.

## Safety deviation

An early status inventory command incorrectly wrote
`/tmp/f86-status-readonly-placeholder` outside the requested checkout-owned
evidence root. It was reported to the user and not modified or removed afterward.
It contains Git status output, not credentials. This is a real evidence-location
violation, not a test write, and is not described as compliant. All subsequent
manual evidence lives under the owned retry root. No system/PATH file was changed.

READY here is limited to the requested Step 1 synthetic delivery blockers and
fresh functional gate. It does not erase the safety deviation, historical evidence,
static waiver, live-evidence limitation, or remaining independent review duty.
