# Close regression167 — bounded correction verified

Code+Test turn4/global167/currentdispatch6; started4/completed0/historical stopped partial1/retries0; effective turn/dispatch budgets UNLIMITED. No spawning or agent restart. Full-feature status remains REVISE, not READY. Live DEFERRED; compatibility UNVERIFIED.

Verified branch `feature-94-herdr-integration`, origin `https://gitlab.com/core-27/slo.git`, HEAD/base `d0e3a756689f2675e5507034d43cd8b272d3c6b8`. All prior work preserved. No Git mutation, package/global/spec/other-worktree/live change.

## Starting evidence and causal diagnosis

166 completed exit0 as an agent, not aborted; its commands did not establish readiness. Preserved `core-docs-gates-166/`: full make test failed with 8 failed/8717 passed/19 deselected. Seven outdated intermediate-close expectations had already been updated in activation composed/faults tests. The eighth throwing-final-gateway regression was unresolved. Three 1800-second local command timeouts are historical incomplete runs, not green gates or aborted agents. No hypothetical conservative patch was assumed present: current source had reverted it and still inherited intermediate `resources=drained` when final close threw.

Reproduced the original eighth node unchanged: `original-red`, 1 failed in3.21s. Its real reporter drained successfully then the final gateway raised. Session incorrectly authorized disposal from intermediate evidence, skipping explicit local reconciliation. Canonical B7.9/C23 distinguish intermediate remote/sticky evidence from final disposal authority.

The previous candidate hang has a separate concrete cause: `NullHerdrReporter.close_transport()` and `drain_retained_external_resources()` called `self.close()`. The candidate test patches intermediate close to throw, so both purportedly independent final operations also threw despite the inert owner having no resources. Conservative session aggregation then correctly required final reconciliation, but the mocked retained drain kept it pending forever. This is not evidence of an actual resource to abandon, nor permission to ignore a genuine throwing final gateway.

## Minimal correction

- `sessions/service.py`: reset resource evidence conservatively before **each** cleanup gateway. Successful final close replaces intermediate resource evidence; a throwing final gateway cannot inherit intermediate default drained. Replacement uncertainty remains sticky. Actual owner predicate and failed viewer join can still require retention.
- `herdr/service.py`: inert null final close and local drain independently return their truthful no-resource evidence, without retrying intermediate close. Session, not null resource cleanup, retains earlier uncertainty.
- `test_session_lifetime.py`: transport gateway faults now require retained evidence. Added both null final-operation regressions (2 failures before correction). Strengthened candidate success path with a bounded shielded waiter, no local-drain call, and uncertain/drained assertions. Existing persistent-retention branch remains unchanged.
- The seven166 updated activation expectations remain intact and pass; the eighth unchanged composed test now proves quarantine until explicit local drain, successor suppression, no additional commands, then drained/sticky uncertainty.

No new owner, synthetic permanent resource, early lease unlock, raw-FD retry, transport join/shield removal, or assertion relaxation.164 restore ownership/refusal and inspection-only ambiguous-close policy are untouched.159 usage,156 profile,151 exact observer are untouched.

## Verification

Runner: `close-regression-167-run.sh`; exact argv, complete output, exit and coreutils receipts in `close-regression-167/`. Explicit `/root/.pyenv/versions/slo-harness`, Python3.11.7, VIRTUAL_ENV/PATH/PYENV_VERSION and tracked synthetic fallback; `make test-env` reports fallback. No environment file or secrets sourced. Root fake-only Herdr and terminal guards retained. Tests use registered temp-owned executables. Every recorded coreutils check is silent. No new timeout occurred.

| Receipt | Actual result |
|---|---|
|original-red|1 failed,2 warnings,3.21s; exit1|
|null-red|2 failed,61 deselected,2 warnings,1.90s; exit1|
|focused-green|92 passed,16 warnings,23.39s; exit0|
|close-surrounds|284 passed,10 warnings,44.22s; exit0|
|null-transport-surrounds|50 passed,2 warnings,4.16s; exit0|
|scoped-lint|5 source files clean; exit0|
|scoped-black|5 files unchanged; exit0|

Focused green runs **whole** session lifetime, activation faults and activation composed modules, including all eight166 failed nodes. Surrounds cover intermediate/final contracts, retained transport and reporter drain, real restore lease retention/cleanup matrix, sequence refusal, activation/cutoffs/notices, candidate lifecycle/init rollback/ownership, replacement/app shutdown, viewer replacement/retention and headless retained lifetime. Total426 passing tests across these disjoint selections. Static scope is both touched production files, lifetime tests and both166 activation test files. `git diff --check` silent. No full suite, smoke, broad lint or chapter-wide gate was run, as requested.

## Scope and read qualification

Supplied full AGENTS/CLAUDE/docs RESEARCH consumed, status/origin/base checked first; root RESEARCH, Makefile, routing/scope plan,161 review,164 owner and165 contract receipts,166 actual logs, exact checkout Code-Test-Review and cadence, engineering routing/ownership/testing/coding rules, Python root/types/declarative/docstrings, relevant KB Welcome/slo README/gotchas, and canonical B7.9/C23 close sections inspected. Python asyncio lifecycle/orchestration and real-adapter offline tests are the scoped categories; no new CLI/widget/framework layer. No exhaustive R161-4 public-API audit is claimed. The checkout lacks the documented specifications symlink; canonical read-only path was obtained from the existing scope plan, not created. Missing KB slo/index.md resolved to existing README.md.

Bounded self-review: per-gateway evidence cannot leak across a failed final boundary; a successful final resource owner can establish drain without erasing earlier fault uncertainty. Null final operations do not recurse into a mocked intermediate failure. Genuine retained evidence still leaves cleanup pending with a reachable owner. Independent review is not claimed.

Next: finish R161-4 final API ledger, then fresh broad/full gates and independent re-review/Completion. This closes only the finite regression/166-test verification request. No whole-feature readiness or completion claim.
