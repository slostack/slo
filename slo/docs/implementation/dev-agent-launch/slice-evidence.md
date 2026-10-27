> Current handoff: [implementation-evidence.md](implementation-evidence.md). Dispatch 3 completes bounded wiring; mandatory pytest and mypy gates remain BLOCKED. Earlier milestone/pending statements below are historical.

# Step 1 runnable slice — turn 1, dispatch 1

**READY for runnable milestone / parent-dispatched independent early review only. NOT Step1 acceptance-ready.** Effective budget 60 turns / 20 dispatches per turn; current turn partial, retries 0. No nested agents, stage, commit, install, environment modification or provider workload.

## Change and proof boundary

- `src/agents/slo_agent/orchestrator/spawn_env.py`: `AgentLaunchPolicy` snapshots the existing sanitized environment once, chooses exact `SLO_DEV_MODE=1`, and supplies paired CLI argv/environment. Default is the same interpreter with `-I`; development uses `-P -s` and exactly this module's resolved import root. No durable schema change.
- `src/agents/slo_agent/orchestrator/launch_tool.py`: detached launch uses that one instance for both products. Caller still owns CLI identity flags, capture lifecycle and persistence. Standalone `_build_argv` remains compatible.
- `tests/agents/slo_agent/orchestrator/test_dev_agent_launch.py`: nine cases, including real `BaseTool.ainvoke` → policy → injected finite import-only process → real handle readback and capture readback. Foreign cwd contains hostile src/config; ambient PYTHONPATH/PYTHONHOME are hostile. Child imports actual src/config/src.cli and reports exact origins. It never calls CLI main or any agent/provider. Adapter replaces only workload with `-c`, adds `-B` to prevent code-cache writes, and waits/reaps with a timeout. This is import/wiring evidence, not runtime admission or provider evidence.

Existing capture writers/reporters are unchanged. Managed sub-agents and both relaunch paths remain for the next slice; do not use this partial implementation for development workflows yet.

## Receipts and exact commands

Cwd `/root/Code/tui-refactor/slo`. External receipts: `/tmp/slo-dev-agent-launch-slice`. Each `*-command.sh` contains the complete clean `env -i`, explicit slo-harness interpreter, temporary HOME/TMPDIR, isolated test settings and pytest invocation. No ambient credentials/dev flag inherited. Baseline environment rationale remains in routing-handoff.md.

| Command | Actual outcome |
|---|---|
| `bash /tmp/slo-dev-agent-launch-slice/red-command.sh` | exit 1, **9 failed**, 2 warnings, 1.79s. Boundary child import fails under old `-I`; eight policy tests fail because policy does not exist. Before production edits. |
| `bash /tmp/slo-dev-agent-launch-slice/green-command.sh` | initial exit 0, **9 passed**, 2 warnings, 3.66s; final post-format/path-safety run **9 passed**, 2 warnings, 3.87s. |
| `bash /tmp/slo-dev-agent-launch-slice/affected-command.sh` | exit 1, **3 failed, 184 passed**, 2 warnings, 8.63s. Same B-01 cases and assertion as prerequisite baseline; no waiver. |
| `bash /tmp/slo-dev-agent-launch-slice/captures-command.sh` | exit 0, **35 passed**, 2 warnings, 16.92s (`test_capture_writer.py`, `test_detached_fd_capture.py`). |
| `/root/.pyenv/versions/slo-harness/bin/python -B -m black --check src/agents/slo_agent/orchestrator/{spawn_env,launch_tool}.py tests/agents/slo_agent/orchestrator/test_dev_agent_launch.py` | exit 0, 3 unchanged after scoped formatting; initial check identified two files needing format. |
| `git diff --check` | exit 0 |
| `dpkg -V coreutils` | exit 0, empty output |

Full suite and project mypy intentionally pending until whole feature; no static baseline waiver. Current patch: `selected.patch` (tracked production files); new test is untracked and must be included separately in eventual feature-only staging. Preexisting 105-path hashes verified before and after implementation: `preservation.json`, zero mismatches. In particular `test_launch_isolation.py` and the user's +4 lines remain byte-identical. Index untouched.

## B-01 installed-boundary investigation (not resolved)

Read-only finite probe:

```sh
env -i PATH=/usr/bin:/bin HOME=/tmp/slo-dev-agent-launch-slice/home \
 /root/.local/share/pipx/venvs/slo/bin/python -I -B -c \
 'import sys,src,config,src.cli; print(sys.executable); print(src.__file__); print(config.__file__); print(src.cli.__file__)'
```

Exit 0; origins all under existing pipx `lib/python3.11/site-packages`; receipt `installed-probe.log`. Its isolated `find_spec('pytest')` returns None. No packages installed or paths changed. Viable next proposal: an explicit installed-interpreter boundary test using this existing read-only interpreter and current production command flags, keeping checkout tests on slo-harness and retaining all hostile path/project-command assertions. This needs a portable selection/injection contract, not an implicit machine-path fallback or patched `sys.executable`. Merely substituting another interpreter in the existing source-only test would no longer prove its stated parent-interpreter guarantee. Therefore **B-01 remains a blocked acceptance gate**; this slice does not disguise it with the successful probe.

## Requirement/evidence map and remaining plan

- DEV-01: detached default argv/env surrounding tests pass; B-01 installed availability remains blocked.
- DEV-02: all eight opt-in values pass, including absent with DEV=1; environment snapshot stays coherent after parent mode changes.
- DEV-03/07: detached import-only boundary passes, exact src/config/src.cli origins and cwd/user-site protection observed.
- DEV-04: pending child→grandchild and resume wiring/proof. D-02 interpreted by the orchestrator from the original explicit opt-in (not additional user approval): process env only; later non-opted-in parent remains installed; no durable mode/root fields.
- DEV-05: shared owner implemented, detached wired; process and two resume paths pending.
- DEV-06: writers/reporters unchanged; bounded 35-test capture regression passes, broader capture coverage remains final work.
- DEV-08: RED/GREEN and affected milestone executed; independent early review next, full/static/final review/completion pending.
- DEV-09: all 105 preexisting paths preserved; no environment/pipx/user-work modifications.
- DEV-10: not staged or committed; later gated feature-only commit remains pending.

Stop here. Parent dispatches read-only early reviewer against contract/code/tests and this receipt. After feedback: complete propagation with test-first safe finite descendant/resume evidence, resolve B-01's installed-boundary strategy without weakening original assertions, then full acceptance gates and final independent phases. No claim of feature completion.
