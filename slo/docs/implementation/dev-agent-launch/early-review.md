# Independent early feedback — Step 1, turn 1 / dispatch 2

**Verdict: REVISE — bounded shared-policy correction, not final feature rejection.**

This is the independent advisory checkpoint inside Step 1, governed by the installed `skills/orchestration/workflows/code-test-review.md` early-review checklist. It is not Step 2, phase progression, a completed workflow turn, or full acceptance. Effective budget remains 60 turns / 20 dispatches per turn; turn 1 dispatch 2, retries 0. No reviewer sub-agents were dispatched.

## Scope and evidence limits

Read the three feature handoffs, supplied project instructions/AGENTS/docs RESEARCH, root RESEARCH, relevant KB guidance, actual production diff and complete new test. Traced the detached spawn and inspected the remaining managed/resume seams and existing isolation assertion. Selected guidance was read from `/root/.local/share/pipx/venvs/slo/lib/python3.11/site-packages/skills/`: engineering routing/ownership/testing/review, test-verification-policy, Python conventions/import resolution/named arguments, and build-agent-tools (project-specific tool contracts take precedence over its unrelated vendor examples).

**No tests, probes, integration suites, agents, installation changes, staging or commits were executed.** Shell commands only read Git diff/status and numbered source. Author-reported RED/GREEN, capture results and B-01 counts are not independently rerun or certified here. Only this new report is written.

## What is sound in the slice

- `launch_tool.py:392–441` creates one `AgentLaunchPolicy` and uses it for both environment and argv at the real injected spawn boundary. Caller-owned identity, captures and handle persistence remain in place; subprocess cwd semantics were not changed.
- `spawn_env.py:69–104` captures sanitized parent settings and exact opt-in once. Development uses `-P -s`, which retains cwd and user-site exclusion while allowing the controlled PYTHONPATH; default keeps the exact `sys.executable -I -m src.cli` prefix. The resolved module-derived root is appropriate for this layout, not task cwd or Git-root inference. This is trusted-code development mode, not a sandbox against installed site customization or code already running in the parent.
- `test_dev_agent_launch.py:58–103` enters through real `BaseTool.ainvoke`, uses real temporary handle/capture persistence, and asserts exact imported src/config/CLI origins and interpreter safety flags. The injected adapter substitutes only a finite import workload; `-B`, bounded wait, and kill/reap cleanup are present. Importing `src.cli` imports the CLI app without invoking `main`; this does not establish headless runtime admission or provider success.
- The production diff leaves auxiliary launch mechanics unchanged. The capture writer remains `-I -B` with its dedicated environment (`spawn_env.py:451–476`); do not migrate writers/reporters onto this policy.

## Finite findings

### ER-01 — Concrete shared-policy blocker: extras can override import/mode authority

**Contract:** DEV-01/02/03/04/05; one owner for exact opt-in and sanitized import environment.  
**Path:** `src/agents/slo_agent/orchestrator/spawn_env.py:87–104,676–680`.

`build_environment(extra=...)` accepts arbitrary nonempty keys after taking the snapshot. With a non-opted-in policy, `extra={"SLO_DEV_MODE": "1"}` produces an isolated child whose descendants would opt in despite the parent's captured mode. Extras can also insert PYTHONPATH in default mode; in development mode PYTHONPATH is corrected, but an extra PYTHONHOME survives and can redirect/break interpreter initialization under `-P -s`. This is a concrete defect in the new shared interface, **not an observed exploit in the detached caller**, which currently passes no extras. The managed caller's current extras are safe identity keys.

**Closure:** reserve import-policy keys in `AgentLaunchPolicy` for both branches: reject or ignore conflicting extras, preserving the captured mode and excluding PYTHONHOME and unauthorized PYTHONPATH. Keep ordinary identity extras working and the legacy helper/auxiliary contracts unchanged. Add bounded decision tests for conflicting extras in both modes, including descendant-mode consistency. Do not change argv based on extras.

### ER-02 — Advisory: complete the declared next slice without splitting snapshot ownership

**Contract:** DEV-04/05 and current-parent interpretation of D-02.  
**Paths:** `process.py:474–489,535–548`; `relaunch.py:84–115,259–289,299–330` under `src/agents/slo_agent/orchestrator/`.

Managed spawn and both resume execution paths still build legacy argv/env independently. This is accurately declared pending, **not grounds to demand final coverage at this milestone**. The critical extension risk is constructing separate policy instances around awaited capture setup or caching one at a longer-lived tool/session scope.

**Closure:** one fresh policy per actual launch, shared by argv/env across setup; narrow injected spawn seams where needed; finite child→grandchild and both resume-boundary proofs. Preserve brief, session/resume ID, owner, cwd and existing capture/adoption/cleanup ownership. Later non-opted-in parents remain default; no durable mode/root fields.

### ER-03 — Required attribution correction, not a new approval gate

**Source:** current review request's explicit D-02 correction.  
**Paths:** opening status paragraphs of `acceptance-contract.md` and `routing-handoff.md`; DEV-04 bullet in `slice-evidence.md`.

These say the user clarified/resolved D-02. Correct attribution is: **the orchestrator interpreted the user's exact process-environment opt-in as current-parent launch policy**. Development-parent resume uses its running code; a later non-opted-in parent remains default. There was no additional user approval of this interpretation.

**Closure:** author updates those current summaries to the attribution above and reconciles stale “clarify” language as historical analysis. This report does not modify those documents and does not request additional approval for D-02.

### ER-04 — Advisory assertion strengthening for the next increment

**Contract:** DEV-02/05/07; testing policy requires evidence at changed boundaries.  
**Path:** `tests/agents/slo_agent/orchestrator/test_dev_agent_launch.py:87–123`.

The decision test checks environment stability after a parent-mode flip but does not rebuild/assert argv after the flip. The detached proof checks session ID/cwd and workflow env, but not the full caller-owned CLI suffix; its adapter removes that suffix before execution. Thus imports are meaningful proof, while complete argument preservation and post-snapshot pairing are only partly asserted. Existing surrounding tests may supply unchanged argument evidence.

**Closure:** assert both products after mode flips, returned-environment copy independence, and the relevant exact run/brief/owner/cwd flags at the recorded boundary (reuse adequate existing tests). Keep the finite import substitution explicit; do not replace it with a paid agent or claim actual CLI execution. No demand for a new harness or a complete failure matrix at this checkpoint.

### B-01 — Existing acceptance blocker remains unwaived

**Contract:** DEV-01/08; engineering-testing baseline policy.  
**Path:** `tests/agents/slo_agent/orchestrator/test_launch_isolation.py:89–92`; baseline/slice receipts referenced in the handoffs.

Three default installed-import assertions reportedly fail in source-only `slo-harness`. Retaining `-I` intentionally cannot fix missing installation. The successful existing-pipx import probe is distinct evidence, not a repair of this gate or proof that the modified checkout runs there.

**Bounded strategy:** retain the original assertions and same-interpreter guarantee. An explicitly selected, already installed interpreter can supply supplemental read-only default-boundary evidence using the current policy's default prefix and finite hostile-cwd/ambient-env probe, temporary HOME/state and `-B`; report installed origins/version and keep project-command checks. Do not silently substitute that interpreter for source-only tests, patch `sys.executable`, modify pipx, or present supplemental proof as a green full suite. If no existing authorized environment can run the unchanged required gate, keep it BLOCKED and obtain an explicit environment/disposition decision before acceptance. New disposable installation/setup needs separate authorization. No such probe was run by this reviewer.

## Handoff

Repair ER-01 before spreading the policy; correct ER-03 attribution. Continue the legitimately pending managed/resume/descendant slice with ER-02/04 as bounded guidance. B-01 and final full/static gates remain acceptance blockers/pending evidence, not early-review waivers. Final independent Step 2 and completion review remain required.
