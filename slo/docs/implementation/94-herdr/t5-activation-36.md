# T5 activation 36 — INCOMPLETE

This continuation is not a READY session family. The public activation and close seams now exercise an actual registered fake executable, but the full requested lifetime/publication contract is unfinished. No independent review or feature acceptance is claimed.

## Preserved scope/accounting

Production changes in this continuation are confined to sessions/service.py; tests added in tests/agents/slo_agent/herdr/test_session_lifetime.py. Existing changes retained. No agents, commits, pushes, PRs, destructive Git, specification/global/live/other-worktree edits. Turn 1 started 1/completed 0/historical partial 1/dispatch 36/retries 0; unlimited turns and dispatches. No task-budget exhaustion is asserted.

## Implemented subset

- Pure disabled/outside activation exits before task allocation. Preparation separately gates before metadata/path work and inert reporter construction. Noncanonical identity refuses assembly.
- Enabled preparation invokes existing capture preparation then the real reporter factory. The session prepares the private integrations parent, validating the configured home and parent through the existing HerdrFileLease policy. The reporter remains owner of sequence/restore storage and transport.
- start_external_reporting retains one activation task and attempted reporter; repeated calls join it. Ordinary activation defects retain uncertainty and fixed-only diagnostics.
- Successful real fake-guarded activation constructs the viewer against the same transport and publishes the initial immutable private capture/public numeric snapshot.
- begin_external_reporting_close synchronously revokes authority. close_external_reporting retains one joined task and drains viewer, reporter, transport in order; ordinary failures conservatively preserve uncertainty. No execution cancellation was added.

## Exact RED/GREEN evidence

CWD /root/Code/slo-94-herdr-integration/slo. Commands use approved `bash docs/implementation/94-herdr/t1-dao-check.sh` (Poetry Python 3.11.7 fallback environment, default disabled isolation). RED arguments: tests/agents/slo_agent/herdr/test_session_lifetime.py. GREEN arguments additionally: test_session_capture.py and test_session_publication.py in that directory, tests/agents/slo_agent/orchestrator/test_bootstrap.py, tests/agents/slo_agent/test_session.py, tests/agents/slo_agent/test_session_usage.py. Helper includes DAO/projection tests. Logs and explicit exit files are under this directory.

| Prefix | Actual result |
|---|---|
| t5-36-gate-red | 2 failed, 62 passed; exit 1 (missing preparation seam) |
| t5-36-gate-green | 187 passed; exit 0 |
| t5-36-start-red | 1 failed, 66 passed; exit 1 (missing activation) |
| t5-36-start-green | 190 passed; exit 0 |
| t5-36-close-red | 1 failed, 67 passed; exit 1 (missing close) |
| t5-36-close-green | 191 passed; exit 0 |
| t5-36-live-red | 1 failed, 68 passed; exit 1 |
| t5-36-live-green | 1 failed, 191 passed; exit 1 (integration parent absent prevents real activation) |
| t5-36-live-green2 | 192 passed; exit 0 |
| t5-36-disabled-red | 1 failed, 69 passed; exit 1 (disabled activation allocated task) |
| t5-36-disabled-green | 193 passed; exit 0 |
| t5-36-final | post-format surrounding partition 193 passed, 9 warnings; exit 0 |

Black changed files: t5-36-black.log/.exit, exit 0. git diff --check: t5-36-diff.log/.exit, silent/0. dpkg -V coreutils: t5-36-coreutils.log/.exit, silent/0. No full make test run: cohesive requested family remains unfinished. 7407 previous full-suite receipt remains pre-change, not current proof. 300 errors/64 files lint baseline remains unwaived; no lint-green claim.

## Required continuation / known limitations

1. Publication currently emits initial idle/compact only. Implement semantic operation/attention state and metadata profile; add actual usage/policy publication hooks and currentness guard. Stale committed captures are NOT yet revoked at publication; do not wire application callers until fixed.
2. Retired final drain, monotonic suppression, candidate-only pool disposal, viewer request gateway, complete cancellation/error/race matrix remain missing. Start cancellation calls close but repeated-cancellation behavior needs tests.
3. Disabled classification currently reads environment on each start with no captured startup classification; consolidate with the existing gate rather than retaining duplicate policy. No injected reporter constructor API yet.
4. Reconcile resumed metadata preparation's ensured flag with normal explicit-workspace persistence. Startup/provenance commit hooks and typed path sources remain pending from 35.
5. Validate integrations-parent initialization across missing home, insecure/link parent and ordinary failure. Current enabled test proves fresh private existing home only. Real providers/windows forbidden; fixture capability guard retained.
6. Close should retrieve activation result even under a defective diagnostic/start seam; prove every owner attempted under faults, cancellation, contention and close-during-start. Add failure/cancel tests before claiming lifetime closure.
7. Required reading remains incomplete: full C/tasks/B/D and selected long skill files were not all ingested in this continuation. Do not treat this report as full normative review. Project instructions and RESEARCH were available; routing/scope and selected C lifetime/capture sections plus current APIs were consulted.

T5 app/headless/scheduler/attention/viewer callers and T6 composed/independent review remain future work. No readiness claim.
