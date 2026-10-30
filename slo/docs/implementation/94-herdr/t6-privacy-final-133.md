# T6 privacy final 133 — INCOMPLETE

## Scope and verdict

The scoped privacy family is **INCOMPLETE**. Fresh final owned/safe-surrounding execution is **1 failed, 242 passed, 139 warnings**, exit 1. The failing assertion is retained, not skipped, xfailed or weakened. No production correction is authorized by this test-only assignment.

Changed only `tests/integration/test_herdr_full_flow.py`, `tests/integration/herdr_parity_124.py`, this report and `t6-privacy-133/` receipts. Existing unrelated changes preserved. No agents, source/harness/spec/shared-status/KB/other-worktree edits, full make, integration-directory collection, restore-process tests, commits, publication or live actions.

Accounting retained: unfinished turn 1, started 1, completed 0, historical partial 1, supplied dispatch 133, retries 0; unlimited turns and dispatches. No new dispatch. Local test corrections are not workflow retries.

## Actual diagnostic disclosure

`test_high_level_viewer_public_outcome_privacy[platform_failed]` sets a synthetic credential environment value and injects an OSError containing that value at the existing platform spawn seam. No window/process is created. The actual high-level `VisualizerLauncher.launch_async` returns a safe `failed` DAO, but `src/tui/visualizer_launcher.py:394–395` emits:

```python
log_warning(msg="visualizer_launch_failed", error=str(exc), argv=argv)
```

The captured LogRecord extra field is `error: SYNTHETIC-viewer-private-133`. Scanning only `record.getMessage()` would miss it. The new test scans the diagnostic record fields and fails. Evidence: `t6-privacy-133/viewer-diagnostics.log` and fresh `final-owned-surrounding.log`.

This is specifically the platform destination diagnostic, **not a demonstrated enabled-Herdr CLI transport leak**. It nevertheless prevents the requested all-high-level-viewer diagnostic privacy claim. Do not conflate it with the separate ordinary `tool_result` input disclosure in `security-finding-132.md`; that finding remains unwaived. A production owner must correct/adjudicate this diagnostic boundary without a global redactor requirement. No source fix was attempted.

## Contract retained

Read canonical H read-only: `/root/Code/specifications/projects/slo/specifications/94-slo-tui-redesign/herdr`.

- B §7.6: unconditional omission of model/provider/effort/session labels, canonical reasoning only; no credential resolver/redactor for reporting.
- B four-sentinel prerequisite and §8: secret-bearing events/environment/child output are inputs; report argv/logs/sequence state must not disclose them.
- C §8–9: ordinary stdout/results unchanged; reporting does not alter execution.
- D §8: integration private configuration absent from ALL public events, snapshots, argv, diagnostics and sequence state; allowed private restore fields remain private.
- Accepted turn-4 F1 closure and T6 samples B26/C31/D09/O01–O03 consulted. Specification approval is not implementation approval.

132 adjudication stands: ordinary credential-bearing terminal tool-result input is permitted unchanged by this integration contract, with its separate security finding open. No all-provider/global redactor requirement was added.

## Finite privacy map

| Requirement | Actual evidence / remaining gap |
|---|---|
| Existing mounted prompt/tool success/error and report-child success/error, four labelled sentinels, compact/detail, rename/rotation | Existing 32-case matrix passes in fresh final run; private config scan still covers all events, including terminal tool results and close |
| Async reporter lifetime excludes credential require/resolve/store/refresh | New four-category test passes: ordinary real Faux session admission completes first, then blockers span activation, actual immutable saves, CLI publication, rotation and drain. External recorded-call assertion is outside isolated callbacks |
| Blocker oracle detects swallowed task failure | New separate-task sensitivity test records a caught require attempt and proves assert_unused fails |
| Configured arbitrary model and effort/reasoning labels | New valid immutable private configuration model-name inputs and validated usage labels traverse real save/wire in both projector profiles, before/after rotation; saved capture equality and advertised restore argv positively checked |
| Native provider interpretation | No fake native-provider claim: four strings label hostile-input categories; the admitted executable policy remains Faux/OpenAI. Arbitrary provider-label boundary coverage remains incomplete |
| Real rename while async blockers installed | Deliberately not claimed. Ordinary rename persistence invokes existing OpenRouter redaction. Mounted test covers real rename; async test covers admitted reporter lifetime and environment rotation. This separation needs final whole-map assessment |
| Viewer submitted/reused/failed | Existing attached/detached real fake-CLI journey passes, including rejected/oversized/private child parser input and public result scans |
| Viewer skipped/opened/failed high-level public outcome | New destination tests pass DAO/argv scans; platform spawn is captured only. Failure diagnostic scan exposes the retained failure above |
| Every high-level viewer public view and complete required read closure | Not closed. New destination cases are not full mounted both-entry-path acceptance; all required source/read dependencies were not fully ingested |
| Unified both viewers + 64 cutoff family | Separate next family, not relabelled as a privacy omission |

No arbitrary few-case cap or dispatch limit is used to claim completion. The source diagnostic finding and unfinished coverage/read closure explicitly prevent READY.

## Reads and routing honesty

Supplied AGENTS/CLAUDE/docs RESEARCH consulted, root RESEARCH read, scope plan and routing consulted (initial combined output truncated). KB Welcome, slo README and gotchas consulted read-only. Loaded committed engineering routing/testing/ownership, Python conventions, coding rules/cadence, Python declarative, named arguments/docstrings, Textual, Faux/graph testing, integration cardinal rules and workflow accounting. Shared declarative file was read only through line 400 of 657; initial combined routing read was truncated. Thus **complete requested read closure is not claimed**.

Implementation-boundary reads covered public/private DAOs, projector, session reporting activation/capture/publication, platform destination/diagnostic owner, credential refresh boundary, owned helper/tests and safe fixture entrypoints. No DB/framework dependency was invented.

## Executed verification

CWD `/root/Code/slo-94-herdr-integration/slo`. Approved interpreter verified `/root/.pyenv/versions/slo-harness/bin/python`, Python 3.11.7. Read `t1-dao-check.sh` before use; it supplies explicit safe fallback and adds 62 DAO/projection cases. Counts overlap and must not be summed. No dev environment sourced.

All pytest commands use:

```sh
PYENV_VERSION=slo-harness bash docs/implementation/94-herdr/t1-dao-check.sh <selection>
```

| Receipt stem | Selection/result |
|---|---|
| initial | existing mounted privacy node: 94 passed |
| blocker | new blocker sensitivity node: 63 passed |
| lifetime | new lifetime node: 4 failed/62 passed; incorrect invoke keyword |
| lifetime2 | 4 failed/62 passed; corrected async-generator invocation exposed missing synthetic admission resolver |
| lifetime3 | 4 failed/62 passed; ordinary rename persistence legitimately calls existing credential redaction, outside reporter responsibility |
| lifetime4 | corrected boundary separation: 66 passed |
| labels | immutable configured model/usage label additions: 66 passed |
| viewer | high-level outcome/argv scan: 66 passed |
| viewer-diagnostics | stronger actual diagnostic-record scan: 1 failed/65 passed, retained disclosure |
| final-owned-surrounding | `tests/integration/test_herdr_full_flow.py tests/agents/slo_agent/herdr/test_session_publication.py tests/agents/slo_agent/herdr/test_visualizer.py`: **1 failed, 242 passed, 139 warnings in 146.39s**, exit 1 |

Post-final-change static commands:

```sh
PYENV_VERSION=slo-harness poetry run black --check tests/integration/test_herdr_full_flow.py tests/integration/herdr_parity_124.py
PYENV_VERSION=slo-harness poetry run mypy --follow-imports=silent tests/integration/test_herdr_full_flow.py tests/integration/herdr_parity_124.py
git diff --check
dpkg -V coreutils
```

Black: two files unchanged, exit 0. Scoped mypy: no issues in two files, exit 0. Earlier mypy caught a nonexistent private session-name attribute; it was removed, not ignored. Diff check silent, exit 0. Coreutils verification silent, exit 0 after final suite and after incremental stubbing runs. Global **281 errors/58 files remains unwaived**, not remeasured or represented as green. Full-suite HOLD remains in effect.

Registered temp-owned regular fake capability, inherited HERDR isolation and real-terminal guard remain unchanged. New platform tests replace only the existing spawn seam and never execute a terminal. No system symlinks, packages or PATH-resident host tools changed. Test files are pre-existing untracked work; HEAD diff alone does not enumerate these additions. No release, independent review or full-feature acceptance is claimed.
