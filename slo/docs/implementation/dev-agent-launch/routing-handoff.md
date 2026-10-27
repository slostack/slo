> Current handoff: [implementation-evidence.md](implementation-evidence.md). Dispatch 3 completes bounded wiring; mandatory pytest and mypy gates remain BLOCKED. Earlier milestone/pending statements below are historical.

# Development agent launch — prerequisite routing and handoff

**Current verdict: READY for runnable milestone / parent-dispatched early review only; NOT Step1 acceptance-ready.** Turn 1 dispatch 1 implemented shared AgentLaunchPolicy plus detached launch wiring only. RED 9 failed → GREEN 9 passed; affected baseline remains 3 failed / 184 passed (B-01), bounded capture regressions 35 passed. See [slice-evidence.md](slice-evidence.md) for current map, exact commands, preservation and remaining plan. D-02 is the orchestrator’s interpretation of the original explicit opt-in, not additional user approval: process-env opt-in only, no durable expansion. No stage/commit/nested agents/install/provider workloads. The prerequisite record below is retained as historical routing/environment evidence, not a current no-implementation claim. Contract: [acceptance-contract.md](acceptance-contract.md).

## Identity and accounting

- Application cwd `/root/Code/tui-refactor/slo`; Git root `/root/Code/tui-refactor`.
- Verified branch `feature-96_chat_transcript`, HEAD `dd2da5bf9feb23618d76562ccf264cbfc315873b`.
- NEW task: this is prerequisite work before turn 1. Workflow turns started/completed/partial: **0/0/0**. This agent dispatched **0** agents; failed-task retries **0**, aborted tasks **0**. Parent should record this prerequisite dispatch separately. Effective later budget: **60 turns / 20 dispatches per turn**, max 3 failed-task retries, never retry abort. User values override stale 8/6 text in repo SLO.md/docs. Tool calls and test runs are not workflow dispatches.
- User expressly chose this existing branch, interpreter and artifact paths; do not create a branch, stash/reset, switch worktrees or install anything to make the environment match stale guidance.

## Stack, contracts and exclusions

Python 3.11.7; asyncio subprocess orchestration; LangChain tool boundary; Pydantic typed boundary data; pytest/pytest-asyncio; real disposable filesystem state. Observed installed dependency versions: pytest 9.1.1, pytest-asyncio 1.4.0, Pydantic 2.13.5, langchain-core 0.3.86. No SQL/database layer, HTTP route, Celery/DBOS job, graph behavior, TUI change or new CLI verb is required.

Read completely in bounded chunks: AGENTS.md (1120 lines), CLAUDE.md (65), docs/RESEARCH.md (823), plus root RESEARCH.md (74). Repo SLO.md and global SLO.md are supplied project context. No nested tracked AGENTS/CLAUDE/SLO/CONVENTIONS files govern the affected package. Inspected pyproject.toml, poetry.toml, Makefile, tests/conftest.py and tests/state_isolation.py. Source identities, including poetry.lock, are recorded externally. Existing project contracts specialize generic recipes: stay under `src/agents/slo_agent/orchestrator`; do not introduce `src/services`, SQLAlchemy, a new tool response shape, broad tool refactors or a test platform.

Class-owned cohesive policy; named multi-argument calls; explicit types; Google-style behavior/error docstrings; Black line length 110. Test-first required by user/project. New internal doubles must be injected recording stubs, not patches of private methods; existing baseline tests contain legacy patching and are preserved, not precedent for new tests. Existing launch-tool `spawn=` seam is the first runnable-slice boundary. Slo's explicit workflow JSON/error contracts override unrelated PubMed tool examples that return empty lists on error. No graph/LLM loop needs to run to prove import availability.

Exclude paid/live providers, E2E installer/Docker gates, actual agents, real visualizer terminals, scheduler changes, installed wrapper changes, databases, TUI/ChatTranscript implementation and all unrelated preexisting work. Local finite import subprocesses are allowed and do not establish provider or complete agent-runtime success. All new test writes must resolve within test temp directories; never symlink writable paths to system tools. Keep captures and cleanup under their existing owners.

## Skill resolution (exact sources)

Actual `SLO_SKILLS_DIR` is `/root/.local/share/pipx/venvs/slo/lib/python3.11/site-packages/skills`. Inspected the supplied runtime `<available_skills>` manifest and read that root's INDEX.md completely (247 lines). Selected sources below are **installed bundled tier**, not checkout-vendored copies. This task does not edit skills, so the repo's vendored-skill maintenance rule is not triggered. No selected name has an available user override.

Read order: project context → shared routing/ownership/testing → coding-rules → Python root → applicable recipes → bounded proposal/evidence. Every listed skill body was read, not merely its index summary:

- `/root/.local/share/pipx/venvs/slo/lib/python3.11/site-packages/skills/orchestration/workflows/code-test-review.md` — authoritative full workflow, not same-name wrapper; completely read.
- `/root/.local/share/pipx/venvs/slo/lib/python3.11/site-packages/skills/orchestration/workflows/SKILL.md` — workflow counting/limits section.
- `/root/.local/share/pipx/venvs/slo/lib/python3.11/site-packages/skills/design-and-analysis/locate-knowledge-base/SKILL.md`
- `/root/.local/share/pipx/venvs/slo/lib/python3.11/site-packages/skills/engineering/engineering-routing/SKILL.md`
- `/root/.local/share/pipx/venvs/slo/lib/python3.11/site-packages/skills/engineering/engineering-ownership/SKILL.md`
- `/root/.local/share/pipx/venvs/slo/lib/python3.11/site-packages/skills/engineering/engineering-testing/SKILL.md`
- `/root/.local/share/pipx/venvs/slo/lib/python3.11/site-packages/skills/coding/coding-rules/SKILL.md`
- `/root/.local/share/pipx/venvs/slo/lib/python3.11/site-packages/skills/coding/code-design-principles/SKILL.md`
- `/root/.local/share/pipx/venvs/slo/lib/python3.11/site-packages/skills/coding/solution-design/SKILL.md` — bounded proposal guidance; user's requested acceptance/handoff format supersedes generic design.md location/length and unrelated historical hard-coded checkout.
- `/root/.local/share/pipx/venvs/slo/lib/python3.11/site-packages/skills/coding/test-verification-policy/SKILL.md`
- `/root/.local/share/pipx/venvs/slo/lib/python3.11/site-packages/skills/coding/code-test-loop/SKILL.md` — cadence, not substitute workflow.
- `/root/.local/share/pipx/venvs/slo/lib/python3.11/site-packages/skills/coding/declarative-method-structure/SKILL.md`
- `/root/.local/share/pipx/venvs/slo/lib/python3.11/site-packages/skills/languages/python/python-conventions/SKILL.md`
- `/root/.local/share/pipx/venvs/slo/lib/python3.11/site-packages/skills/languages/python/build-application-services/SKILL.md` — orchestration discipline only, no invented service layer/database.
- `/root/.local/share/pipx/venvs/slo/lib/python3.11/site-packages/skills/languages/python/build-agent-tools/SKILL.md` — existing tool delegation/injected seams; preserve project wire behavior.
- `/root/.local/share/pipx/venvs/slo/lib/python3.11/site-packages/skills/languages/python/python-path-and-import-resolution/SKILL.md`
- `/root/.local/share/pipx/venvs/slo/lib/python3.11/site-packages/skills/languages/python/switch-environments-and-run-tests/SKILL.md` — actual Makefile governs; orders_service DB/examples do not apply.
- `/root/.local/share/pipx/venvs/slo/lib/python3.11/site-packages/skills/languages/python/named-arguments-and-type-hints/SKILL.md`
- `/root/.local/share/pipx/venvs/slo/lib/python3.11/site-packages/skills/languages/python/method-docstrings/SKILL.md`
- `/root/.local/share/pipx/venvs/slo/lib/python3.11/site-packages/skills/languages/python/declarative-method-structure/SKILL.md` — specific Python ~8-line review signal overrides generic quota wording; no mechanical fragmentation.

Later independent review/completion agents must read their own exact installed `design-and-analysis/review-feature-code/SKILL.md`, `design-and-analysis/is-the-feature-completed/SKILL.md`, engineering-review and Python review guidance. This agent did not perform or impersonate those phases.

Filesystem inventory found 192 SKILL.md candidates: 188 installed and four user files. The runtime manifest lists three valid user entries (PDF override, diff viewer, task breakdown); none apply here. Extra `/root/.slo/user_skills/solution-design-brief/SKILL.md` has invalid YAML (`ScannerError`) and is absent from the supplied available manifest. A first inventory parse failed on it; second inventory records the error explicitly. No user/installed file was repaired or silently selected. `user_workflows` is absent. Exact selected paths, resolved paths and SHA-256 values are in `selected-skill-sources.json`; filesystem inventory is evidence of files, not a replacement runtime manifest.

## KB consulted

Discovery used actual `SLO_KB_DIR=/root/Code/KnowledgeBase/KB` (first matching location); `KB_DIR` unset; `SLO_HOME=/root/.slo`. Read `Welcome.md`, then `slo/README.md` (repo index; `slo/index.md` does not exist), relevant `slo/gotchas.md`, `slo/environment-and-running.md`, and `slo/headless-workflow-orchestration.md:541–571`. Important facts: `-I` prevents target-project src shadowing, a PID is not import/startup success, and explicit VIRTUAL_ENV is necessary for Poetry. Historical KB advice to fix installation rather than remove `-I` remains the default; the user's exact explicit development exception is new authorized scope. No KB/runtime claim was changed before implementation.

## External preservation receipt

Directory: **`/tmp/slo-dev-agent-launch-prereq-B1K88sg0`** (mode 0700). Keep it external; do not commit large snapshots or raw preexisting content.

- `initial-status.txt`, `initial-status.z`: complete initial Git status including untracked files.
- `initial-worktree.patch`: complete binary worktree diff, root-relative.
- `initial-staged.patch`: staged binary diff (initially empty).
- `initial-untracked.z`, `initial-untracked.txt`, `initial-untracked.tar.gz`: untracked inventory and content snapshot, symlinks not followed.
- `initial-content-hashes.json`: hashes/type/size for all **105** preexisting modified/untracked paths: **39 tracked modifications + 66 untracked files**.
- `initial-head.txt`, `initial-branch.txt`, `preexisting-launch-isolation.patch`: immutable starting identity and exact four-line preexisting assertion.
- `source-identities.json`, `selected-skill-sources.json`, `available-filesystem-skill-manifest.json`: routing/evidence refresh inputs.
- `baseline-command.sh`, `baseline.log`, `baseline.exit`, `poetry-interpreter.txt`: executable baseline receipt.
- `preservation-check.json`, `final-status.txt`, `coreutils-verification.txt`: final preservation audit (created after these docs).

Recheck hashes before implementation and before staging. If another actor changes a preexisting file, report the mismatch; never restore snapshots over their work. A later feature commit must use selected hunks for shared AGENTS/docs/tests, not whole-file staging of ChatTranscript changes. Initial tracked diffs and untracked archive are preservation aids, not commit inputs.

## Commands and actual results

All commands use cwd `/root/Code/tui-refactor/slo` unless noted. Explicit interpreter wins over stale AGENTS `slo` venv name; `poetry.toml` has `virtualenvs.create=false`.

1. `/root/.pyenv/versions/slo-harness/bin/python -B -c 'import sys; print(sys.executable); print(sys.version)'` → exit 0, expected interpreter, Python 3.11.7.
2. `VIRTUAL_ENV=/root/.pyenv/versions/slo-harness PYENV_VERSION=slo-harness POETRY_VIRTUALENVS_CREATE=false poetry run python -B -c 'import sys; print(sys.executable); print(sys.version)'` → exit 0, same interpreter; `poetry-interpreter.txt`.
3. `bash /tmp/slo-dev-agent-launch-prereq-B1K88sg0/baseline-command.sh` → **exit 1; 3 failed, 184 passed, 2 warnings in 8.80 s**. Exact child command/environment are in that receipt; it runs explicit Python `-B -m pytest -m 'not e2e' -p no:cacheprovider --basetemp=<receipt>/pytest-baseline -q` over `test_launch_isolation.py`, `test_spawn_env.py`, `test_process.py`, `test_launch_tool.py`, `test_relaunch.py`. No tests skipped/deselected in this selection. Failures are exactly B-01's sub-agent/workflow/resume variants. Deprecation warnings: pythonjsonlogger module move, LangGraph future allowed_objects default.
4. `dpkg -V coreutils` → exit 0, no output. No system binaries or installed pipx files were changed.

`environments/tests.env` is absent. Baseline reconstructed Makefile's clean-checkout contract: SLO_ENV=test, explicit root/app paths, APP_NAME=slo, text logging, default gpt-5.4, AUTO_VISUALIZE=0, synthetic Anthropic placeholder, COLUMNS=120/LINES=40, PYTHONPATH=application root. Used `env -i` to exclude real credentials and inherited development flags, temp HOME/TMPDIR, `PYTHONDONTWRITEBYTECODE=1`, explicit VIRTUAL_ENV and Poetry create=false. Existing suite fixtures isolate SLO_HOME/auth state at collection and per test; no dev env file loaded.

Later commands: reuse the same clean environment with focused node IDs for each red/green increment; run affected orchestrator/capture files at milestones. Final full default command is the same explicit interpreter/environment with `-m pytest -m 'not e2e'` and **no file or -k filtering** (equivalent selection to Makefile `make test`). Do not reuse a pytest basetemp containing evidence. Run `python -m black --check <feature files>` (no bulk formatter writes) and project lint equivalent `python -m mypy src/ tests/`; report actual baseline failures without inherited waivers. Final import-only subprocess integration proof must assert exact origins and no provider execution; do not run `pytest -m e2e` wholesale. All full/static/final integration gates are **not run** here.

## Next action and missing decisions

Parent can begin the bounded first slice using DEV IDs, preserving this baseline. Resolve B-01's default installed-import gate disposition before acceptance; merely adding development mode cannot fix that assertion while retaining default isolation. Clarify D-02 if resume must retain old mode after a non-development parent restart; proposed scope is current-parent opt-in without durable schema changes. D-01 recommends `-P -s` rather than bare non-isolated Python to prevent cwd shadowing. No implementation decision has been falsely marked approved, and no failure has been waived.
