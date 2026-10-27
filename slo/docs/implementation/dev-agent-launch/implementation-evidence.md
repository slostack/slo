# Current Step 1 handoff — turn 1, dispatch 3

**BLOCKED / mandatory gates FAILED. Not READY.** Budget 60 turns / 20 calls;
turn 1 remains partial, dispatch 3, failed-task retries 0. Early review dispatch 2
remains inside Step 1. No nested agents, staging, commits, installations, pipx
changes, paid providers, agent workloads, new harness or unrelated repairs.

## Implemented boundary

`AgentLaunchPolicy` owns exact opt-in and paired argv/environment. Identity extras
cannot overwrite captured mode or inject PYTHONHOME/PYTHONPATH. Each actual launch
creates one fresh policy: detached tool, managed `SubAgentProcess.run`, and both
`WorkflowRelauncher.invoke` and `spawn_for_adoption`. Capture setup awaits retain
that same instance. Narrow typed optional process-creation injections default to
asyncio; existing callers retain captures, adoption, cancellation and reaping.
No durable mode/root schema or auxiliary capture-policy change.

The running module supplies the resolved source root. Development uses `-P -s`,
not `-I`; default retains `-I`. Sanitization and sanctioned credential/identity
forwarding are unchanged. D-02 is the **orchestrator's interpretation of the original
explicit opt-in**, not additional user approval: current-parent mode governs resume.
See [usage.md](usage.md).

## Requirement / finding map

| IDs | Evidence / disposition |
|---|---|
| DEV-01 | Full affected orchestration selection retains default argv/env and sanitization assertions. B-01's three installed-import assertions still fail, unwaived. |
| DEV-02 / ER-01 | Eight opt-in cases including DEV=1; three conflicting-extra cases. RED 3 failed / 9 passed, GREEN 12 passed. Mode/import keys protected while parent PID, capture directory and synthetic OpenRouter credential survive. |
| DEV-03/07 | Real finite import-only adapters at detached tool, managed run and both resume boundaries; exact src/config/src.cli origins from foreign temp cwd, detached hostile cwd/PYTHONPATH/PYTHONHOME proof retained. No CLI main/provider execution claimed. |
| DEV-04/05 / ER-02 | Managed RED 1 failed / 14 passed → GREEN 15 passed; resume RED 2 failed / 12 passed → GREEN 14 passed. Both resume suffixes retain original brief/session/owner/cwd; managed run reads real captures/status. Final local child→grandchild proof passes. |
| ER-04 | Both products asserted after ambient mode flips; returned env mutation cannot mutate snapshot. Full detached/resume/managed CLI suffixes asserted at recorded spawn boundary. Adoption test changes ambient mode during awaited capture setup, still sees paired development argv/env. |
| DEV-06 | Entire orchestrator directory rerun includes capture writer, detached FD, adoption, redaction and cleanup regressions; only B-01 failed. Auxiliary implementation untouched. |
| ER-03 | Current summaries in all three handoffs corrected; historical prerequisite questions explicitly marked historical. |
| DEV-08 | Required full default and static gates executed; FAILED, no waiver. Independent Step 2/3 not performed or implied. |
| DEV-09 | All 105 preexisting paths byte-identical, including shared `test_launch_isolation.py` and +4 user lines. Index untouched. |
| DEV-10 | No staging/commit; blocked until gates accepted. |

## Exact receipts

Cwd `/root/Code/tui-refactor/slo`. Receipt root
`/tmp/slo-dev-agent-launch-dispatch3`. Each `NAME-command.sh` records the full
command, clean `env -i`, explicit `/root/.pyenv/versions/slo-harness/bin/python`,
temp HOME/TMPDIR, synthetic credentials and root paths prescribed by routing.
Run as `bash /tmp/slo-dev-agent-launch-dispatch3/NAME-command.sh`; corresponding
`NAME.log` and `NAME.exit` retain output and actual exit. No dev env loaded.

| NAME | Exit / observed result |
|---|---|
| er01-red | 1; 3 failed, 9 passed, 2 warnings, 3.89s |
| er01-green | 0; 12 passed, 2 warnings, 3.62s |
| resume-red | 1; 2 failed, 12 passed, 2 warnings, 3.83s (missing injected spawn seam) |
| resume-green | 0; 14 passed, 2 warnings, 7.79s |
| managed-red | 1; 1 failed, 14 passed, 2 warnings, 8.03s (missing injected spawn seam) |
| managed-green | 0; 15 passed, 2 warnings, 10.06s |
| focused-final | 0; 15 passed, 1 e2e deselected, 2 warnings, 10.18s; rerun after final docstrings |
| affected | 1; 3 failed, 1118 passed, 1 deselected, 57 warnings, 66.47s; entire orchestration directory |
| multiprocess | 0; 1 passed, 15 deselected, 2 warnings, 3.93s; explicit single finite e2e test only |
| full | 1; **3 failed, 8517 passed, 20 deselected, 482 warnings, 998.47s** |
| black | 0; 5 feature Python files unchanged under `black --check` |
| mypy | 1; **292 errors in 58 files (765 checked)**, `mypy src/ tests/` with temp cache |

Full invocation has **no file or -k filter**: explicit Python `-B -m pytest -m
'not e2e' -p no:cacheprovider --basetemp=<receipt>/pytest-full -q`. The full gate
ran once after executable changes; only docstrings and feature documentation were
edited afterward, with focused pytest and scoped Black verification. The new
finite descendant e2e was written for the final integration check, not represented
as an independently observed pre-implementation RED test.

## Unwaived failures and next decision

Full pytest failures are exactly:

- `tests/agents/slo_agent/orchestrator/test_launch_isolation.py::test_agent_isolation_does_not_isolate_project_commands[sub-agent]`
- same test `[workflow]`
- same test `[resume]`

All fail line 89: `observed['src_origin'] is not None`; source-only slo-harness
has no installed src under `-I`. The prerequisite
`/tmp/slo-dev-agent-launch-prereq-B1K88sg0/baseline.log` records these same failures
before the feature (3 failed / 184 passed). No other full-suite test failed.
Assertions remain intact. The earlier installed-pipx read-only probe is supplemental
only and was not used to replace this gate. Acceptance requires an operator-approved
compliant environment/disposition; no installation is authorized here.

Project mypy is also failed and unwaived. Exact diagnostics are in `mypy.log`;
no diagnostics name the five feature Python files. This is **not a demonstrated
clean baseline comparison** and is not called passing or waived. No unrelated
repairs attempted. Resolve the project static-gate disposition before acceptance.
Then obtain independent final review/completion; early feedback is not those gates.

## Changed files and preservation

Feature source/test files only:

- `src/agents/slo_agent/orchestrator/{spawn_env,launch_tool,process,relaunch}.py`
- `tests/agents/slo_agent/orchestrator/test_dev_agent_launch.py`

Feature documentation: `acceptance-contract.md`, `routing-handoff.md`,
`slice-evidence.md`, this file and `usage.md` in this directory. `early-review.md`
is retained unchanged. Shared AGENTS/RESEARCH and all preexisting work were untouched.
Installed scoped rules were read from routing's installed source (not vendored
copies); project context, root RESEARCH and relevant KB were consulted.

`preservation.json`: checked 105 paths, zero mismatches against prerequisite hashes.
`coreutils-verification.txt`: `dpkg -V coreutils` exit 0, empty output.
`git diff --check`: exit 0. Production diff manually inspected for unchanged
auxiliary capture code, CLI arguments, cwd semantics and same-policy pairing.
No claim of independent review. No feature acceptance or commit authorization
is inferred from this bounded implementation.
