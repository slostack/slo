# T6 privacy handoff 129 — INCOMPLETE, retained production RED

## Scope and accounting

Same unfinished turn 1: started 1, completed 0, historical partial 1, supplied dispatch 129, retries 0. User unlimited turn/dispatch budgets retained. No agents dispatched. Edited only `tests/integration/test_herdr_full_flow.py` and `tests/integration/herdr_parity_124.py`; wrote this report and `t6-privacy-129/` receipts. No production edits, shared-status edits, canonical-spec edits, other-worktree edits, Git mutations, installations or live actions. Existing dirty work preserved.

Two-process safety HOLD remains: no two-process helper/test collection, integration-directory collection or full make gate. Only the owned module and the explicitly safe activation/attached composed files were selected, through the approved foundation helper.

## Production RED for parent

The actual mounted Faux session emits a `now` call; the real executor runs `NowTool.invoke`, which raises `RuntimeError("CONTROLLED-TOOL-ERROR <configured synthetic credential>")`. The run completes, but its public `AgentStreamEventDAO(kind="tool_result")` contains the literal configured credential. This is not intentional user conversation: the credential comes from the controlled exception and is configured in both the environment and resolver boundary. Intentional user/tool content remains allowed in Slo and forbidden only in reporting.

All eight new exception variants fail the existing public-channel forbidden-secret assertion: four synthetic credential categories × successful/failing fake CLI. These are four sentinel categories, not four native provider executions; the factory remains OpenAI-configured Faux. No assertion was relaxed and no production repair attempted.

Exact isolated selector:

```sh
PYENV_VERSION=slo-harness bash docs/implementation/94-herdr/t1-dao-check.sh 'tests/integration/test_herdr_full_flow.py::test_mounted_synthetic_labels_and_private_paths_do_not_reach_reporting[openai-False-True]'
```

`tool-error.log`: **1 failed, 62 passed**, exit 1. Failure output includes:

```text
assert forbidden not in public
'sk-SYNTHETIC-openai-credential-124' is contained here:
... TOOL-ERROR sk-SYNTHETIC-openai-credential-124 ... "tool_name":"now" ...
```

This establishes a public session tool-result leak. It does not establish a leak in Herdr report argv, snapshots, or transport outcome fields, and does not justify adding a generic conversation redactor to the reporter. Parent must determine the appropriate existing error/public-stream owner; production changes are outside this assignment.

## New low-level and parity evidence

- `IntegrationWriteAttempts` intercepts Python `os.mkdir/open/chmod/rename/replace/unlink/rmdir`, `io.open`, and built-in `open` for the explicitly test-owned `$SLO_HOME/integrations` tree. It denies before delegation and records attempts before raising. Unrelated history I/O delegates unchanged. Inactive mounted tests retain all fourteen high-level boundary spies and add this independent low-level check after journey/teardown.
- Controlled mkdir/open/replace attempts target only an absent contained temp integration file. Their `OSError` is deliberately swallowed, then the outer `assert_unused()` must raise. No host target is used; no actual target mutation occurs. This proves caught-failure sensitivity of the recorder, not a production-source mutation campaign. The open interception is deliberately stronger than write-only: any integration open is forbidden for inactive mode. It is Python boundary coverage, not native syscall tracing.
- Initial low-level run failed **2 tests** because the inherited SLO_HOME was not inside that test's tmp_path. The guard correctly refused. The test now explicitly binds SLO_HOME to its existing tmp_path before instrumentation. No containment assertion was weakened.
- New parity tests cover all 18 nonidentity history payload fields dynamically from the schema and positive consistent identity renaming with parent linkage/null topology. Provider extension uses a valid typed `ProviderMessageExtensionDAO` after replacing an initial serialization-warning fixture.

### Normalizer semantic coverage map

| Schema area | Evidence |
|---|---|
| Stream arbitrary tool_input/metadata identity-looking names | Existing 16 sensitivity cases retained |
| Stream nonidentity fields | Existing 13 mutations retained |
| History sequence/iteration/kind/schema | Existing four mutations retained |
| History ordered records, missing/duplicate, changed parent/null/usage/tool timestamp | Existing seven mutations retained |
| Every non-block_id history payload field | New 18 schema-enumerated mutations |
| Generated history identities and tree links | New positive two-node consistent-renaming equality; source models remain unchanged |
| Unknown record rejection, stream/history cross-channel positive renaming, all null identity distinctions | Not newly verified in this increment |

## Verification

CWD: `/root/Code/slo-94-herdr-integration/slo`. `PYENV_VERSION=slo-harness pyenv which python` resolved `/root/.pyenv/versions/slo-harness/bin/python`; existing approved 3.11.7 environment, no new environment or dev settings.

All pytest runs use `PYENV_VERSION=slo-harness bash docs/implementation/94-herdr/t1-dao-check.sh` with explicit selectors. Helper contributes 62 foundation cases; counts overlap and must not be summed.

| Receipt | Selection | Actual result |
|---|---|---|
| lowlevel | inactive + spy sensitivity | 2 failed / 65 passed; containment fixture defect |
| lowlevel-green | same after explicit temp home binding | 67 passed |
| parity | new payload + positive rename | 81 passed; initial extension fixture warning subsequently removed |
| tool-error | one mounted tool exception | 1 failed / 62 passed; production public-event secret RED |
| affected | full owned module + `tests/tui/test_herdr_activation_composed.py` + `tests/tui/test_herdr_attached_composed.py` | **8 failed, 171 passed, 100 warnings, 132.95s, exit 1** |

Final affected command:

```sh
PYENV_VERSION=slo-harness bash docs/implementation/94-herdr/t1-dao-check.sh tests/integration/test_herdr_full_flow.py tests/tui/test_herdr_activation_composed.py tests/tui/test_herdr_attached_composed.py
```

Own-file Black and mypy `--follow-imports=silent` pass (two files). `git diff --check` silent, but does not cover these pre-existing untracked owned files. Coreutils verification silent after each test increment; final `coreutils.log` empty, exit 0. Global baseline **281 errors / 58 files remains UNWAIVED**, not rerun. No full suite under HOLD.

## Exact remaining finite-family obligations

1. Retained configured-secret tool-error RED above must be resolved at the appropriate production owner by the parent; these tests must not be weakened.
2. Sentinel-bearing actual session/provider failure path is not yet added. Tool failure was added; it is not session-failure coverage.
3. Configured arbitrary model/provider/effort labels and rotation plus independent zero credential lookup during publication remain unimplemented in this increment.
4. Existing eight attached/detached viewer journeys still scan adapter results and public transport fields, with private `json_bytes` explicitly separated. Every HIGHLEVEL bridge outcome category and schema-known private-field omission sensitivity remain unfinished; no broader claim replaces these checks.
5. Low-level spy sensitivity is complete for the three controlled operations above; no claim of exhaustive native filesystem tracing or failure-isolated production mutation injection.
6. Mandatory full reading closure remains incomplete. Current owned tests/helper, predecessor 125/126/127 receipts, scope plan, root research, KB Welcome/gotchas, engineering routing/testing/ownership, Python/Faux/style/declarative and coding guidance were consulted. B 2161–2221, C 2122–2175, D 634–711 (actual §§8–10), exact tasks T6 attachments 3721–3816 and accepted independent turn-4 review were read in this continuation. Full actual AGENTS/CLAUDE/docs-RESEARCH rereads, all affected production-owner bodies, remaining Textual/integration/workflow guidance, routing record and accepted companion reviews are not certified complete; one broad read truncated. Supplied context and predecessor claims are not substituted for that closure.

## Exact T6 acceptance disposition

- **B26**: foundational projection/DAO tests execute through helper; scoped fake transport/privacy tests execute. Full Herdr/formatter/footer selection, full Black source scope, make test/lint are not executed here under HOLD. Public session secret failure remains distinct from reporter argv/log/state checks.
- **C31**: mounted inactive session/history parity remains passing; tool-error public-stream privacy now RED. Native restore two-process and broader lifetime/CLI gates are outside this safety-limited selection, not implied by these results.
- **D09**: owned full-flow and safe attached composition execute; existing eight viewer outcomes pass. Complete high-level outcome privacy matrix is unfinished. Broader D test paths/full static/make smoke/test/lint are not collected here.
- **O01/O02**: production ownership/private publication chain unchanged; this test-only work does not add or certify new owners or native restore.
- **O03**: no live pane/paint or operator visual acceptance; registered fake CLI evidence is not Herdr compatibility.

Both-viewer unification with retry/fallback and the 64 lifetime matrix remain a separate next family, not recast as privacy gaps. Independent review and live acceptance are not performed. **INCOMPLETE** is driven by a retained actual RED and enumerated unfinished evidence, not an invented workflow budget cap.
