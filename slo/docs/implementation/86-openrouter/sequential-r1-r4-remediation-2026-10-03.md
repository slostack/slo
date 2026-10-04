# Feature 86 — sequential Step-1 R1–R4 remediation

Date: 2026-10-03. One authorized mutating call; no delegated or parallel review.
Backend model identity is unavailable. Verdict before final gate: REVISE pending
execution; eligibility for sequential Step 2 requires full.exit=0 below. This is
not feature completion or independent approval.

## Current finite disposition

| Finding | Evidence and boundary |
|---|---|
| R1 / F86-17,32 | Existing router now distinguishes disable-only from unsupported, and omits compatibility off from controls whose disable permission is absent. Converter-derived metadata reaches both bare `/reasoning` and `/reasoning off`. Direct-provider router regressions pass; no wire policy changed. |
| R2 / F86-17,31,32,39 | Both metadata shapes paint actual compositor cells at 80x24 and 60x15 through normal input completion, with no forced menu visibility. Known-effort detail was clipped; existing menu moves reasoning first. Each case suppresses visibility while render text remains, requires the positive oracle to fail, restores visibility and rechecks paint. Bare router result also paints through the normal transcript adapter at both sizes; native scroll-end exposes its supported line at the smaller size. This latter test uses a stub session plus real converter/router, not full model selection. |
| R3 / F86-17,18,38,39 | Actual schema-2 writer, public prepare_models and admission read matching fresh credential provenance; real prepared entry goes to factory/SDK. True/False/omitted/invalid integer/string/object normalize as expected. Six valid local JSON completions return `ok`; each wire has effort low and neither budget field. Public preparation is not mocked. Resolver supplies a synthetic credential; discovery client construction is forbidden on this fresh-cache path. Existing strict cache/default-high/override tests retained. |
| R4 / F86-38,40 | New unambiguous cwd-owned `.f86-final-remediation-hldebc_g/` contains exact expanded commands, complete redirected logs and exit files. The formerly claimed `.f86-step1-1791030546-full` is not relied upon or reconstructed. Final full gate is prescribed below after these documentation edits, with no later source/test/doc edits. Manifest is generated after that gate. |
| E1 | Qualified existing real-loader/barrier/public admission tests retained. Rotation and stale delivery rejection are material evidence. Missing membership requires refresh; removal test injects fresh refresh outcome and forbids client construction. It does NOT prove all-real zero-HTTP removal or real removal HTTP. No new criterion or architecture introduced. |
| Selection | Historical offset failure retained without causal explanation or claimed repair. No selection edits, arbitrary reruns, sleeps or skips. |
| Auth | Existing positive compositor and suppression sensitivity evidence retained; affected composed/auth tests pass. |
| Static/live | Black and mypy not run: waived, not green. No live credentials, external provider calls or paid inference. Normal 18 E2E/default-disabled exclusions expected; actual count belongs to full.log. |

## Commands and results

All test invocations use `bash .f86-final-remediation-hldebc_g/run.sh <name> <arguments>`.
The runner records the fully expanded env-i approved Python -B command before execution
in `<name>-command.txt`, complete output in `<name>.log`, and status in `<name>.exit`.
Each run has separate owned HOME/TMPDIR/SLO_HOME/auth/basetemp, cwd PYTHONPATH,
SLO_AUTO_VISUALIZE=0 and disabled pytest cache. Tool timeout: 1200 seconds.

| Name | Arguments | Result |
|---|---|---|
| r1-red | tests/tui/test_slash_router.py -k state_and_off_follow | 2 failed, 64 deselected; actual wrong supported-state strings |
| r1-green | tests/tui/test_slash_router.py | 66 passed |
| r2-red | tests/tui/test_openrouter_picker.py -k mounted_picker | 2 passed; first oracle extension alone did not fail |
| r2-normal-red | tests/tui/test_openrouter_picker.py -k mounted_picker | 2 failed, 2 passed; known enabled detail clipped at both sizes |
| r2-green | tests/tui/test_openrouter_picker.py tests/tui/test_slash_suggestion_menu.py tests/tui/test_picker_viewport_acceptance.py tests/tui/test_slash_suggestion_engine.py | 27 passed |
| r3-red | tests/agents/model_catalog/test_openrouter_budget_evidence.py -k prepared | 3 failed; old malformed successful response could not complete |
| r3-green | tests/agents/model_catalog/test_openrouter_budget_evidence.py | 12 passed |
| r2-router | tests/tui/test_openrouter_picker.py -k mounted_reasoning | 2 failed, 2 passed; small viewport needed ordinary native scroll |
| affected | tests/agents/model_catalog tests/agents/providers/test_openrouter_reasoning_semantics.py tests/tui/test_openrouter_picker.py tests/tui/test_slash_router.py tests/tui/test_slash_suggestion_menu.py tests/tui/test_picker_viewport_acceptance.py tests/tui/test_slash_suggestion_engine.py tests/tui/authentication/test_openrouter_authentication.py tests/integration/test_openrouter_full_flow.py | 460 passed, 5 warnings, 18.82s |
| full | -m 'not e2e' tests | See full.log and full.exit, generated after this document is final; no anticipated pass is asserted here. |

R3 is an evidence repair, not a production defect: its red result exposes the old
malformed-response/broad-exception test. Production admission/transport needed no change.
R2 router small-screen correction uses normal scrolling, not layout/visibility forcing.

## Changed files this call

- src/tui/slash_router.py
- src/tui/widgets/slash_suggestion_menu.py
- tests/tui/test_slash_router.py
- tests/tui/test_openrouter_picker.py
- tests/agents/model_catalog/test_openrouter_budget_evidence.py
- AGENTS.md, README.md, RESEARCH.md, docs/RESEARCH.md
- docs/implementation/86-openrouter/current-status-2026-10-02.md
- docs/implementation/86-openrouter/remaining-requirements.md
- docs/implementation/86-openrouter/implementation-log.md
- this report

Current-facing documents point here and at actual new gate artifacts; older dated
reports/pointers remain explicitly historical. No specs, KB, installed skills,
interpreter, system paths or Git index/HEAD were modified. Expected branch and HEAD
verified. Repo/personal/installed skills were readable. Relevant overview 7.2–7.4,
a.2 7.2–7.6, a.3 7.2, a.5 7.3–7.6/8.3, a.6 7.2–7.6/8/9 were read.
Oversized initial read-only tool output produced tool-managed /tmp spill files;
these were not test artifacts and were not modified or cleaned.

## Freeze contract

After the full gate, generate sorted comprehensive source/test/config/plugin/skill
and documentation hashes, including current-facing documents, plus root build files.
Receipt: `.f86-final-remediation-hldebc_g/source-test-manifest.sha256` and its
`manifest.sha256` digest. Exclude execution scratch, caches and old copied baselines,
not real source/tests. Run read-only `git diff --check` and coreutils verification.
No edits after manifest creation. Independent Step 2 follows in a later call.

## Final gate regression correction (supersedes initial menu ordering above)

Initial full.log: **5 failed, 5151 passed, 18 deselected, 196 warnings in 331.01s**.
Failures were status revision (both sizes), picker_g8 (two tests), and verified
status publication (small size): moving reasoning first clipped required status
and context. Focused picker-regression-green retained exactly those five failures.
No assertions were weakened. Existing menu now uses an additional reasoning line
only for disable-only/known-enabled-default semantics, preserving status/context.
Bounded capacity accounts for three-line entries; ordinary two-line entries keep
the original formula. This narrow presentation deviation from the two-line spec
is explicit and needs sequential review, not a hidden spec edit.

picker-layout-green: 31 passed, 1 failed (ordinary capacity regression).
picker-final-green: 31 passed, 1 failed (empty detail counted as zero lines).
picker-verified: **32 passed, 2 warnings, 7.09s**, including unchanged footer counts.
All expanded commands and logs retained. No new production owner or framework.
Final gate command: `bash .f86-final-remediation-hldebc_g/run.sh full-final -m 'not e2e' tests`.
Authoritative latest result is full-final.log/full-final.exit, produced after all
final documentation edits. The earlier full.log is historical failed evidence.
Before execution verdict remains REVISE; no anticipated green. Manifest follows.

## 2026-10-03 — final authorized single-test correction call


The prior final gate is retained unchanged: `.f86-final-remediation-hldebc_g/full-final.log`
reports **1 failed, 5155 passed, 18 deselected, 196 warnings**, exit 1. The exact
bounded-model-window failure reproduced in isolation. Direct-provider summaries
incorrectly acquired the gateway `; provider default` suffix, expanding the normal
rows from two to three lines (five rather than eight rows). The existing suggestion
projection now preserves direct-provider summaries; OpenRouter evidence is unchanged.
A stronger eight-label/footer compositor assertion then exposed detail width exceeding
the inner menu width by four cells. The menu now uses the same inner width for both.
No count/window expectation was relaxed, no sleeps/skips added, and no R1/R3 changes.

Focused partition: 38 passed; intermediate strengthened-paint run: 1 failed/173 passed;
paint correction: 30 passed; final affected: **174 passed, 5 warnings**; additional
surrounding picker/status regressions: **48 passed, 2 warnings**. Full expanded
commands/logs/exits: `.f86-window-correction-tPhyAzET/`. The fresh complete gate
is `full.log`, `full-command.txt`, `full.exit` there, generated AFTER these final
documentation edits. Its actual exit/summary controls readiness; no anticipated pass.
Final source/test/current-doc manifest: `source-test-manifest.sha256`, digest in
`manifest.sha256`, generated after full gate and read-only checks; no edits thereafter.

R1 router truth, R2 two-size compositor/hidden-paint sensitivity and R3 real schema-2
public preparation/valid SDK no-budget proof remain retained. R4 points to this new
receipt, not a reconstructed missing directory. E1 removal still injects refresh
outcome (not all-real zero-HTTP removal). Historical selection offset has no claimed
causal repair. Auth sensitivity remains retained. Black/mypy waived, not green;
provider evidence remains offline synthetic, not live authorization or paid inference.
Independent sequential Step2/Step3 remain pending; readiness is not feature approval.
Earlier current/latest headings below are preserved historical receipts.


### Scope, diagnosis and retained red evidence

Only new production edits in this call: `src/tui/slash_suggestion_engine.py`
(import ProviderName and preserve direct-provider reasoning summaries) and
`src/tui/widgets/slash_suggestion_menu.py` (detail width uses existing inner width).
Only test edit: `tests/tui/test_slash_suggestions_app.py`, adding diagnostic row/state
output, direct-summary assertion and compositor proof of all original eight labels
and the count footer. Normal mount → load_text → Changed → projection → update_state
is retained; no visibility forcing, arbitrary timing, navigation or ranking changes.
The initial global-row-height hypothesis was disproved: visible direct rows themselves
had the suffix. No window algorithm rewrite was needed. Contracts: overview §7.10,
a.5 §§7.4–7.5/7.7 (direct compatibility), a.6 §§7.3/7.5–7.6.

Artifact run names and results (all retained under the new directory):
- original-red: exact existing failure, 1 failed/6 deselected; rendered Showing 5 of 25.
- semantic-red: new direct-summary assertion, 1 failed/6 deselected.
- focused-green: 38 passed/2 warnings after projection correction.
- affected-green: despite its requested name, actual result is RED, 1 failed/173 passed;
  new compositor oracle could not see claude-sonnet-4-6 due to wrapped details.
- paint-green: 30 passed/2 warnings after width correction.
- affected-final: 174 passed/5 warnings in 27.50s.
- surrounding-final: 48 passed/2 warnings in 7.84s, including previous five regressions.
- full: fresh entire `-m 'not e2e' tests`, after final edits; actual log/exit controls.

All runs use env -i, approved slo-harness Python -B, resolved cwd-owned isolated
HOME/TMPDIR/SLO_HOME/auth/basetemp, no pytest cache, cwd PYTHONPATH and visualization
disabled. Tool execution timeout 1200 seconds. Existing historic manifest verified
before edits. No agents/workflow launches, Git mutations, specs/KB/system/PATH edits,
installs, real credentials or live provider calls. Safety disclosure: the initial
read-only Git status command redirected to `/tmp/f86-status-readonly.txt` outside cwd;
this was a diagnostic artifact, not a test write, and is left untouched. Oversized
read output also caused tool-managed /tmp spill. All subsequent deliberate artifacts
are cwd-owned. No historic reports or receipts were removed or overwritten.
