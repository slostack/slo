# T6 mounted 122 — executable increment, INCOMPLETE

Same unfinished turn 1: started 1, completed 0, historical partial 1, supplied dispatch 122, retries 0. Unlimited turns and dispatches; no agents launched. No workflow completion or independent review claimed.

## Owned changes

New `tests/integration/test_herdr_full_flow.py` (11 cases) and this receipt plus `t6-122-*` logs/exits only. No production, shared status, canonical specification, other-worktree, global or two-process-lane edits. Existing root safety guards remain unchanged. Reused the existing `native_factory`, command reader and bounded polling helpers; fake executable capability is registered by the existing root fixture before activation. Executable additions preserve the registered inode; capture/barrier identities are checked before writes. No system symlinks, real providers, Herdr, windows or agents.

## Actual evidence

- Nine mounted PromptInput cases: enabled/disabled/outside × ordinary/retry/pool fallback. Config-backed factory supplies Faux at the real graph use boundary. Production pool construction, graph, tool executor, session accounting/history and reporter remain real.
- `now` default tool is held at its leaf boundary with Events and returns a fixed timestamp. Real pre-output rate-limit policy waits 15 seconds in retry cases; production pool fallback changes active route to gpt-4.1 while configured pool stays unchanged.
- Enabled ordinary case holds the real registered CLI process on `report-agent` after observing working. Prompt reaches run_completed and exactly eight shared total tokens before releasing the CLI barrier; subsequent commands converge to idle and session_tokens=8. Retry/fallback cases do not hold the CLI throughout the 15-second retry, avoiding conflation with its bounded transport timeout.
- Real history contains one user message and one completed run; real tool result is now. Disabled/outside commands remain empty and integration activation task absent. This is **not yet complete normalized event/history parity**.
- Two additional mounted cases drive `/rename`, `/model gpt-4.1`, and `/new` via Pilot. Controlled attached and detached events enter the public session event relay, then production app/service/typed effects/renderer/launcher/transport. Real persisted parent evidence is provided; no child is spawned.
- Exact fake CLI split/no-focus, rename and run argv asserted for the selected parent; duplicate relay gives no second command; exactly one submitted notice. Replacement orders old release before successor claim and forbids later old-ID commands.
- Wire checks exclude model label, test private path and private rename/context sentinels. Full public-channel/four-provider-secret/diagnostic/sequence scanning is **not proved**. Private save existence is asserted, but exact private policy is not yet asserted by this lane.

## Incremental results

All commands ran from `/root/Code/slo-94-herdr-integration/slo` using `PYENV_VERSION=slo-harness` and existing `bash docs/implementation/94-herdr/t1-dao-check.sh` safe fallback. Counts include that helper's 62 foundation cases; do not sum overlapping runs.

Each stem has `.log` and `.exit`:

| t6-122 stem | Result |
|---|---|
| initial | 3 failed/62 passed: test used subscribe(callback), corrected to handler |
| journey | 3 failed/90 passed: authentication modal intercepted Pilot input |
| focus | 3 failed/62 passed: focus alone did not dismiss modal |
| diagnosis / diagnosis2 | isolated disabled failure records factory=0, no events, actual AuthenticationScreen |
| admission | 93 passed: synthetic CredentialResolver boundary supplies admission; real graph now executes |
| viewers | 2 failed/71 passed: fixture containment rejected history root outside tmp_path before write |
| viewers-green | 73 passed: explicit contained default-home binding, no weakened containment |
| routes | 3 failed/89 passed: ten-second tool deadline shorter than genuine fifteen-second retry |
| routes-green | 92 passed,55 warnings,94.31s: bounded thirty-second tool deadline; no retry policy replacement |
| integration | 214 passed,172 warnings,109.31s; exit 0 |
| mypy | `poetry run mypy --follow-imports=silent tests/integration/test_herdr_full_flow.py`: success, one source file |
| black | `poetry run black --check tests/integration/test_herdr_full_flow.py`: exit 0 |
| diff | `git diff --check`: exit 0, silent |
| coreutils | `dpkg -V coreutils`: exit 0, silent |

Integration command: safe helper followed by `tests/integration tests/tui/test_herdr_attached_composed.py tests/tui/test_herdr_activation_composed.py`. Earlier admission command added activation-composed and attention-execution-composed; route command added attention-execution-composed. Full repository make gates intentionally not run before T6 lanes finish. Scoped mypy is not a global lint pass or waiver.

All failures above were test construction/setup/deadline mistakes, not demonstrated production defects. No production RED retained or hidden. No xfail/skip introduced.

## Remaining acceptance — do not call journey family READY

The executable increment is green, but the requested family remains INCOMPLETE:

1. Combine configuration/viewer transitions with the prompt journey rather than separate cases; strengthen controlled workflow ingress beyond public relay of synthetic normalized events.
2. Exact normalized disabled/outside event/history parity; zero integration filesystem writes assertion.
3. Full four-provider synthetic-secret/private-path public snapshot/event/diagnostic/sequence scan, exact allowed private capture, stale context/cooldown clears.
4. All 64 canonical lifetime cases, G1/G2 and quarantine composition remain unimplemented in this file. No predicate-only substitute or reduced matrix claimed.
5. Remaining canonical accepted-review/prerequisite ingestion needs closure; reading the routing record is not reading every referenced file. Consulted checkpoint121, routing, T5READY120, current supplied AGENTS/CLAUDE/docs RESEARCH, root RESEARCH, KB Welcome/gotchas, tasks T6 and exact3721–3816, B/C/D8–10 and scoped engineering/Python/Textual/Faux guidance. The earlier bulk read truncated; it is not full source closure.
6. Full combined make/test/smoke/lint and independent review; live version/restart/pane paint separately authorized later.

No READY journey-family, full64, T6-completion, live compatibility or release claim.
