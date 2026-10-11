# Feature 86 — sequential integration, 2026-10-03

## Terminal Step 1 verdict: REVISE

The single fresh COMPLETE non-E2E gate is green: **5091 passed, 18 deselected,
196 warnings in 361.93s; pytest exit 0**. This is not sufficient to close the
remaining delivery contract below. No Step 2 review or Step 3 completion was performed.

Baseline HEAD: `f63df0a4958eedb4bc603f1946ba4591dd181fff`.
Requested orchestration provenance: parallel call1 **gpt-5.6-terra medium**, three
bounded owners; sequential integration call2 **gpt-6-astra medium**. These are the
user-specified call/model labels, not independently attested backend identities.
No recursive launch occurred. All prior dirty/untracked work was preserved.

## Inspection and integration scope

Read all three dated owner reports and inspected their actual test/source boundaries:

- Owner 1: final cache-read barrier retains a distinct newer route and 512-token
  cap, with a separate credential-rotation rejection branch; converter reasoning
  truth-table additions; additive capability defaults. Shipping catalog publication
  rechecks fingerprint and snapshot reference after its asynchronous cache read.
  No cross-owner correction was indicated at that boundary.
- Owner 2: session refresh counts visible, available OpenRouter rows, retains actual
  lifecycle check time or `unknown`; session and mounted direct-selection tests
  use event barriers and cancellation to protect the new route from old startup.
  Those assertions were preserved unchanged.
- Owner 3: read both fixture/harness modules, fixture JSON and provenance README;
  searched all Python tests for the asset filenames. The only actual bundle
  consumer is `test_fixture_bundle.py`, using local parsing and shape/sentinel
  assertions. Existing full-flow tests use separately authored inline responses;
  the README's `local full-flow shape` wording is not proof of bundle consumption.

No production or test edits were made in this integration call. Consequently no
new red→green correction is claimed. Owner-reported red→green records remain in
`owner1-catalog-provider-evidence-2026-10-03.md`,
`owner2-session-tui-evidence-2026-10-03.md`, and
`owner3-fixture-delivery-evidence-2026-10-03.md`; they are not relabelled as fresh
integration runs.

Preflight consulted repository instructions and RESEARCH, the Code-Test-Review
workflow and Step 1 cadence, named/type, declarative, docstring and verification
rules, relevant Python integration/agent-testing guidance, KB Welcome/Slo index,
gotchas/status, and current correction/remediation/status/requirements records.
Specification reads covered relevant implementation/acceptance clauses of all six
86.a contracts, overview §7.11, request acceptance/reporting and dependency
checkpoints. The checkout's documented `specifications` link is absent; immutable
files were read at `/root/Code/specifications/projects/slo/specifications/86-openrouter-intergration/`.
No spec was changed. This was bounded integration inspection, not an exhaustive
line-by-line whole-feature audit.

## Remaining finite delivery contract

**86.a.6 §§7.7, 8.1; overview §7.11; F86-39/40:**
`tests/integrations/openrouter/test_live_openrouter.py` is safe mock-only
scaffolding, not the prescribed separately authorized credential-gated GET and
bounded paid-tool procedure. Its entry gates before resolver/client construction
and hardcodes `MockTransport`. However:

1. Enabled discovery exercises only `/models/user`, not `/key` then `/models/user`.
2. Paid mode returns two numeric configuration fields; no execution boundary
   enforces at most two requests, 256 output tokens, no retries, a selected exact
   route and one harmless tool round trip.
3. Test functions set their own fixture opt-in; explicit e2e selection runs synthetic
   checks rather than a credential/flag-gated live procedure. This is safe but a
   semantic deviation, not live acceptance.
4. Bundle assets are genuinely read, but only by shape/sentinel checks. No existing
   production client/converter/SDK full-flow test consumes them. The prescribed
   public/documented fixture set is not fully represented by the five differently
   named synthetic files, and no public observed provenance is supplied.

Required next correction: test-first, retain default denial before any credential
lookup, provide an explicitly authorized procedure with separately enforced GET
and paid bounds, verify it solely through synthetic transport here, and wire the
representative fixture assets into meaningful existing boundaries. Do not make
live requests to close this item. Alternatively an explicit contractual scope
limitation is needed; neither the static waiver nor the owner report supplies one.
This call did not complete that correction and does not claim it did.

## Mounted-auth reliability evidence

Independently inspected the complete six-node failure inventory and auth traceback
in `.f86-remediation-retry-QS5PwP/full-non-e2e.log`:

1. `test_openrouter_capability_recovery.py::test_reasoning_control_distinguishes_unknown_from_disabled[True-None-expected2]`
2. `test_catalog_generation.py::TestOpenRouterSessionSelection::test_refresh_model_catalog_when_publish_succeeds_adopts_only_future_snapshot`
3. `test_openrouter_full_flow.py::test_mounted_openrouter_auth_picker_router_session_and_resume_flow`
4. `test_openrouter_startup.py::test_pending_session_gates_without_resolving_unknown_capabilities`
5. `test_openrouter_startup.py::test_mounted_startup_shared_worker_gates_and_recovers[False]`
6. `test_openrouter_startup.py::test_mounted_startup_shared_worker_gates_and_recovers[True]`

Five failures match obsolete expectations: reasoning-disable permission, duplicate
catalog load, unspecified AsyncMock snapshot, and two old route assertions. Auth
logs show successful key GET, persistence and models GET, followed by failure to
observe `Key verified; catalog checked.` after twenty `pilot.pause()` iterations.
They do not prove publication/task/compositor completion or identify the cause.
Owner 2 reports 20/20 fresh isolated non-reproductions; this call did not randomly
repeat the test. The new complete suite passes it in ordinary order. That adds
full-order success evidence but does not establish root cause or repair. Keep the
historical miss as a residual reliability signal; no sleeps/assertions were changed.

## Fresh final gate — exact command and artifacts

Owned root: `.f86-integration-final-XNoqn6/`. Interpreter verification reports
Python **3.11.7**. Resolved checkout-owned root, HOME, TMPDIR, SLO_HOME and auth
pathname were used; pytest basetemp was new. Exact expanded command is retained in
`command.sh`; stdout and stderr are both in `full-non-e2e.log`:

```sh
env -i HOME='/root/Code/slo-openrouter-implementation/slo/.f86-integration-final-XNoqn6/home' TMPDIR='/root/Code/slo-openrouter-implementation/slo/.f86-integration-final-XNoqn6/tmp' SLO_HOME='/root/Code/slo-openrouter-implementation/slo/.f86-integration-final-XNoqn6/slo-home' SLO_AUTH_FILE='/root/Code/slo-openrouter-implementation/slo/.f86-integration-final-XNoqn6/home/authentication.json' PATH=/root/.pyenv/versions/slo-harness/bin:/usr/bin:/bin PYTHONPATH='/root/Code/slo-openrouter-implementation/slo' PYTHONDONTWRITEBYTECODE=1 SLO_AUTO_VISUALIZE=0 timeout 1200 /root/.pyenv/versions/slo-harness/bin/python -B -m pytest -p no:cacheprovider --basetemp='/root/Code/slo-openrouter-implementation/slo/.f86-integration-final-XNoqn6/basetemp' -m 'not e2e' tests > '/root/Code/slo-openrouter-implementation/slo/.f86-integration-final-XNoqn6/full-non-e2e.log' 2>&1
```

`exit-code.txt` contains 0; `failure-inventory.txt` is empty. No skip/xfail or
additional selection was introduced. **18**, not the historical 15, tests are
normally e2e-deselected. The three added exclusions are:

- `test_live_harness_when_disabled_rejects_before_credential_resolution_or_network`
- `test_live_harness_when_fixture_discovery_is_enabled_uses_synthetic_resolver_and_safe_output`
- `test_live_harness_when_paid_fixture_mode_is_enabled_sets_documented_bounds`

All are in `tests/integrations/openrouter/test_live_openrouter.py`. This integration
call did not execute `-m e2e`. The complete log retains 196 warnings, including
three unawaited-AsyncMock RuntimeWarning emission sites; they are not suppressed,
not failures, and no causal relationship to historical paint failure is asserted.

## Safety and limits

Inspected temp-root installer wrapper construction (regular wrappers, not writable
symlinks to real binaries), capture containment helpers, isolated full-flow storage
and default transport tripwires, and suite terminal-launch guard. No installed
interpreter/skills, system files, external specs or other worktrees were modified.
No installs, deployments, real credentials, live/paid provider calls or Git mutation
were performed. Full-suite safety is based on these inspected guards, not a claim
of exhaustive syscall auditing of every existing test.

Post-suite `dpkg -V coreutils`: exit 0, empty retained
`coreutils-verification.log`. `git diff --check` passed. Black/mypy were not run:
the static-only waiver is honored, not called a green static gate. One oversized
preflight tool read created `/tmp/slo-bash-bmn7ud25.txt` automatically; it was not
manually created, edited or cleaned up. Deliberate new evidence is checkout-owned.

Only documentation follows this gate. Full green is current evidence; the remaining
fixture/procedure delivery limitation and unexplained historical paint miss remain
explicit. Terminal **Step 1 REVISE**; no formal Step 2 or feature completion claim.
