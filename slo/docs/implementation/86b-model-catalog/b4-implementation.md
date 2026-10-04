# 86.b.4 — Unknown saved-model resume: code + test

Date: 2026-10-04

## Verdict

**READY for the assigned b4 code/test phase.** Unknown saved direct models now fall back through the existing preferred/default resolver. The resumed TUI shows the existing startup block. No admission, picker, pool-precedence, OpenRouter preparation, or history-schema redesign.

Required final gates:

- Focused: **43 passed**, exit 0.
- Surrounding project command: **3391 passed, 15 deselected**, exit 0.
- **`make test`: 5288 passed, 18 deselected, 201 warnings**, exit 0.
- Black: **all four changed Python files clean**, exit 0.
- Coreutils integrity: silent, exit 0 after every gate.

This is not independent review, b5 mixed-version proof, or whole-feature completion. The deterministic parent retains those phases.

## Preservation and incremental scope

All shell commands explicitly entered `/root/Code/slo-openrouter-implementation/slo`; all file operations used absolute paths. Branch remains `feature-86-openrouter-implementation`.

Before edits, all **822** hashes from `b3-authorized-formatting-receipts/final-hashes.json` matched. The four b4 source/test targets were also byte-identical to the original 817-entry baseline archive, not merely HEAD. They were retained in `b4-receipts/before.tar.gz`; targets were checked before production edits. Final reconciliation found only the intended changes below, and all original baseline regular-file modes remained unchanged. All **68** historical evidence hashes recorded in the predecessor preflight still match.

Original baseline archive SHA-256 remains:
`a6aa0e12cfe5ecb387f7efe25089afcfdb4fa136cb3c11e401ff98bc69ad46fa`.

Released tag remains `v0.20.1^{commit}` = `f63df0a4958eedb4bc603f1946ba4591dd181fff`. No fetch.

| Incremental file | Change |
|---|---|
| `src/cli/typer_dispatch.py` | Existing config owner checks saved direct names through the catalog; three specified helpers; fixed notice plus optional default explanation; one `session_resume_model_unavailable` warning. |
| `src/agents/slo_agent/sessions/service.py` | Fallback-bearing launches bypass the prior startup-marker suppression. |
| `tests/cli/test_resume_route_precedence.py` | 31 additional cases covering real metadata/build, aliases, pending route, precedence/defaults, pure text, and real headless CLI continuation. Existing four cases preserved. |
| `tests/tui/test_startup_notice.py` | Four additional cases covering repeated fallback launches, history-disabled gating, real config/build with pool-primary notice and mounted history replay. Existing four cases preserved. |
| `RESEARCH.md` | Small durable note describing the existing owners and resume contract; no historical receipt rewritten. |

New report/evidence files are under `docs/implementation/86b-model-catalog/`. The unchanged, inspected predecessor runner `b3-receipts/run_gate.py` was reused with unique `b4-*` labels, so individual new command receipts sit beside that runner. `b4-receipts/index.json` collects all 20 receipts, full commands/environments, actual exits, summaries and output hashes. No prior receipt was overwritten.

No separate worktree, agent delegation, staging, commit, reset, stash, clean, branch switch, push, PR, deployment, installation, user-state cleanup, or protected-system write occurred. Existing 86.a and b1–b3 work is preserved and not attributed to b4.

## Test-first implementation sequence

One bounded selection unit (under 50 executable implementation lines, excluding documentation) followed the selection and composition failures. The independent two-line startup gate followed its own failures. Focused/surrounding modules were green between units.

Each path below is a command-owned directory containing `output.log` and `command.json`. The index also records coreutils checks and suite-root cleanup.

| Step | Output root | Actual result |
|---|---|---|
| Saved-model red | `/tmp/slo-86b-b3-b4-selection-red-319skcdm` | **4 failed, 4 passed**, exit 1: real session build raises `Unsupported reasoning model` for both unknown and prefix-compatible names, both store layouts. |
| Default-composition red | `/tmp/slo-86b-b3-b4-composition-red-0zlz6l2y` | **1 failed, 8 deselected**, exit 1: saved unknown model still overrides the resolved default. |
| Selection implementation + dispatch surrounding | `/tmp/slo-86b-b3-b4-selection-green-4r7gsmhw` | **45 passed**, exit 0. |
| Startup red | `/tmp/slo-86b-b3-b4-notice-red-97wicxge` | **2 failed, 5 passed**, exit 1: persisted marker suppresses the mounted block; in-memory marker suppresses fallback. |
| Startup implementation + both modules | `/tmp/slo-86b-b3-b4-notice-green-vucvj4i_` | **16 passed**, exit 0. |
| Added unchanged-route/default regression matrix | `/tmp/slo-86b-b3-b4-precedence-bikwfbw5` | **67 passed** including dispatch surrounding, exit 0. |
| Real headless flow, first attempt | `/tmp/slo-86b-b3-b4-headless-flow-i15_i0hw` | **4 failed, 31 passed**, exit 1: test set an environment key after the direct-provider config binding was imported. |
| Headless fixture correction, first attempt | `/tmp/slo-86b-b3-b4-headless-flow-green-yvktmc9g` | **4 failed, 31 passed**, exit 1: test used `credential=` instead of the actual `CredentialStore.persist(cred=...)` signature. The label is historical, not a pass claim. |
| Headless fixture corrected | `/tmp/slo-86b-b3-b4-headless-flow-verified-3ap6hh1z` | **35 passed**, exit 0: synthetic credential persisted through the real owned store; real CLI/headless/session/graph appends the Faux answer. |
| Mounted pool/replay, first attempt | `/tmp/slo-86b-b3-b4-mounted-pool-posawhl7` | **1 failed, 42 passed**, exit 1: test used `prompt=` instead of `SloAgentSession.invoke(text=...)`. |
| Mounted pool/replay corrected | `/tmp/slo-86b-b3-b4-mounted-pool-green-jtkeyax2` | **43 passed**, exit 0. |
| Black red | `/tmp/slo-86b-b3-b4-black-red-a3e6vmje` | Exit 1: three files require formatting, all in newly edited regions. |
| Black formatting | `/tmp/slo-86b-b3-b4-format-fy9tkham` | Exit 0: three formatted, session source unchanged. All four pre/post-format ASTs identical. |

The fixture-authoring errors are retained honestly; they are not product regression evidence. No production change was made to credentials, session invocation, or JSONL formatting to accommodate them. Assertions were corrected to consume the actual API and parsed JSON, not weakened. No skips, xfails, timeout changes or disabled tests were introduced.

## Final gates and the surrounding-command diagnosis

All commands ran through the unchanged safe runner, which creates a fresh command-level HOME/SLO_HOME/TMPDIR/cache and supplies a complete explicit environment (no inherited state overrides). `PYTEST_ADDOPTS` disables the repository cache and puts basetemp inside the fresh TMPDIR. B1's suite/per-test isolation stays active. Exact expanded argv/env are in the index; command tails below are not standalone safe invocation recipes.

| Gate | Command tail | Result / output |
|---|---|---|
| Focused after formatting | approved Python `-B -m pytest -q tests/cli/test_resume_route_precedence.py tests/tui/test_startup_notice.py` | **43 passed, 7 warnings**, exit 0, 4.39s; `/tmp/slo-86b-b3-b4-focused-final-nv5soijy/output.log` |
| Formatting | approved Python `-B -m black --check --line-length 110` on the four Python files above | Exit 0, four unchanged; `/tmp/slo-86b-b3-b4-black-final-sm0cb7q0/output.log` |
| Initial surrounding invocation | approved Python `-B -m pytest -q tests/cli tests/tui tests/agents/slo_agent` | **4 failed, 3387 passed, 15 deselected**, exit 1; `/tmp/slo-86b-b3-b4-surrounding-eeh_d8ar/output.log` |
| Environment identity | approved Poetry `run python -B -c ...` | Exit 0; approved 3.11.7 executable and prefix; `/tmp/slo-86b-b3-b4-poetry-interpreter-24is6sbe/output.log` |
| Capture entrypoint diagnosis | approved Poetry `run pytest -q tests/agents/slo_agent/orchestrator/test_capture_contained_lifetime.py tests/agents/slo_agent/orchestrator/test_capture_writer.py` | **69 passed, 2 warnings**, exit 0; `/tmp/slo-86b-b3-b4-capture-entrypoint-n3syas1v/output.log` |
| Required surrounding project command | approved Poetry `run pytest -q tests/cli tests/tui tests/agents/slo_agent` | **3391 passed, 15 deselected, 159 warnings**, exit 0, 312.33s; `/tmp/slo-86b-b3-b4-surrounding-project-entrypoint-3djem3sn/output.log` |
| Full | `/usr/bin/make test` | **5288 passed, 18 deselected, 201 warnings**, exit 0, 364.41s; `/tmp/slo-86b-b3-b4-full-_voitcg1/output.log` |

The initial surrounding failures are concrete lexical interpreter-identity assertions in unchanged capture tests, not ignored failures. `python -m pytest` uses the approved long interpreter spelling; the installed project pytest entrypoint has shebang `/root/.pyenv/versions/slo-harness/bin/python`, exactly what the capture containment guard accepts. Read-only resolution proved this alias has the **same environment root and binary** as `/root/.pyenv/versions/3.11.7/envs/slo-harness`. Using the spec's `poetry run pytest` command passes both the 69-test diagnostic and the entire surrounding suite. No capture guard, test, binary, symlink or environment was modified. The failed gate remains failed in its receipt.

`environments/tests.env` is absent; `make test` used the inspected synthetic fallback. The default 18 E2E exclusions remain unchanged. Every command receipt reports empty coreutils output with exit 0 and no remaining suite-owned root.

All source/test changes preceded these final gates. Only the durable RESEARCH paragraph and evidence/report files were added afterward; this is not presented as a post-document-edit rerun.

## Acceptance map

| Requirement | Evidence | Status |
|---|---|---|
| AC-R1: unknown saved direct model builds ready using preferred/default; exact fixed notice and one warning | `test_build_session_config_when_resumed_model_is_unknown_falls_back_with_notice`: `retired-model-x` and `claude-retired-x`, flat/tree metadata, actual session build; default-source matrix and notice composition | PASS |
| AC-R2: known model/alias, OpenRouter route, explicit model unchanged | Known-name/alias real builds; cold OpenRouter pending build; original saved-route tests; explicit override/pool matrix and real headless explicit override | PASS |
| Existing configured pool primary precedence | Eight pool cases; actual built session identity; mounted tip explicitly names `claude-sonnet-4-6` rather than preference `gpt-5.4` | PASS |
| No-resume/default and absent metadata behavior | Default-source matrix; absent history stays absent; existing dispatch tests in surrounding suite | PASS |
| Pure helper does not log | Both optional-default-notice paths assert zero warning calls | PASS |
| AC-R3: existing three-line startup block on fallback resume despite marker; ordinary resume quiet | Mounted two-launch exact three-line check; original ordinary-resume test; history-disabled branches; real config/build + mounted pool/history test | PASS |
| New-code full history and continuation | Real `CliRunner` → dispatch → headless preparation → real session/graph with only LLM factory replaced by Faux: two existing turns remain equal and a third is appended, exact six message contents/order checked, metadata records active model; both layouts and explicit/fallback paths. Mounted TUI renders old user and assistant widget bodies. | PASS |
| AC-R4: released/new/released executable continuation | Explicitly owned by b5; not substituted with same-version evidence here | b5 |

The selected default's own existing prefix-compatibility behavior remains unchanged by design. This task does not promise to repair a separately invalid configured default, reconstruct a pool from routed metadata, or change OpenRouter admission.

## Conventions, safety and review handoff

Loaded target AGENTS/SLO, both RESEARCH files, complete overview/b4 spec, recovery plan and predecessor reports; confirmed vendored, installed and personal skills. Read the complete code-test-review workflow, workflow routing, code/test phase and always-on conventions, applicable Typer/Textual/session/test skills. Consulted KB gotchas (actual store layout, credential/config binding, CLI/session ownership) and ambient-environment reinforcement. Generic DB or machine-setup examples were not executed.

Inspected the actual config/build/notice owners, root and TUI test fixtures, state isolation, Makefile/pytest config, real headless flow, installer regular-wrapper safety, release dry-run guards and capture containment. Existing safe infrastructure and prior phase audits were reused, not replaced. New fixture state resolves inside its owned roots. Synthetic credentials/Faux only; no live inference or real terminal windows.

Self-checked the incremental diff and current files: production behavior changes are limited to the specified existing owners, helpers are typed and documented, new multi-argument calls use keywords, no new owner/DAO/error/admission layer exists, TUI composition is unchanged, and every new decision branch has passing coverage. Independent Opus review remains a parent phase, not claimed here.

B5 should consolidate AGENTS/docs/KB/release documentation as assigned. RESEARCH records b4's durable contract now. A verification lesson for that handoff: use the existing project pytest entrypoint for capture suites; resolved interpreter equivalence does not imply equality of `sys.executable` strings in lexical containment assertions. No broad capture-harness repair was needed or authorized by this narrow task.

## Evidence inventory

Under `b4-receipts/`:

- `plan.txt`, `start-hashes.json`: phase scope and reconciled predecessor state.
- `before.tar.gz`, `incremental.diff`, `changed-files.json`: exact b4 attribution, not HEAD-only diff.
- `pre-format.tar.gz`, `formatting-proof.json`: AST-preserving formatting proof.
- `index.json`: all 20 actual command receipts and log hashes, including every failure.
- `final-hashes.json`, `post-gate-check.json`: 822 final hashes, baseline modes, original archive digest, branch and tag.

**No b4 code/test blocker remains.** Full-repository typing, b5 released executable proof, independent review and final completion assessment remain with the parent workflow; none is claimed passed by this leaf report.
