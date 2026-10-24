# T5 mutation handoff 46

## Verdict: INCOMPLETE — prerequisite/read audit remains

The bounded production corrections below pass targeted and surrounding tests. This is not complete finite-family acceptance: required read completion and full final family/diff audit have not been established. No invented sticky-recovery requirement, new recovery gateway, workflow completion, independent review, or full integration claim.

Accounting preserved: same unfinished turn 1; started 1, completed 0, historical partial 1, supplied dispatch 46, retries 0. Unlimited turns AND dispatches; no agents dispatched. An API request failure interrupted reading; continuation recovered without restarting the workflow or changing budgets.

## Owned changes

- `sessions/service.py`: `_snapshot_herdr_policy_sources` is a memory-only optional boundary used at construction and bootstrap. Ordinary exceptions invalidate restore eligibility and return no snapshot; strict source validation remains unchanged. Already invalidated/no-capture withdrawal avoids repeating a failed optional snapshot. No BaseException containment added.
- `orchestrator/bootstrap.py`: initial source snapshot is taken only with permission and through the isolated session boundary. Existing post-construction and final attachment guards remain intact.
- `herdr/test_session_mutation.py`: malformed pre-bootstrap history scalar matrix; malformed construction under default/custom prompt with ordinary rename preserved; ordinary snapshot exception at both construction/bootstrap; malformed nested entry object/None; unchanged supported direct/Kimi/alias capture identity.
- Fixed three existing owned nullable-config mypy errors in final attachment by asserting the invariant already established by the final-additions guard.

Only these three owned files and this handoff were edited. Existing partials and concurrent test lane preserved. No shared-status, specification, KB/global/live/other-worktree changes; no commit/push/PR/reset/clean/stash/install/new venv.

## Finite behavior/evidence map

| Family | Evidence |
|---|---|
| Initial malformed bootstrap policy | `test_bootstrap_initial_snapshot_is_optional[1,true,None]`: ordinary pool attaches, no provenance/capture |
| Construction optional compatibility | `test_construction_refuses_restore_not_ordinary_session[None,custom]`: construction and rename succeed, capture refused |
| Ordinary snapshot exceptions | `test_optional_snapshot_failure_does_not_control_lifecycle[construction,bootstrap]`: RuntimeError cannot escape optional boundary |
| Nested pool object shape | Existing sequence matrix extended with object and None entries; both refuse capture |
| Valid identity/alias | `test_valid_model_identity_retains_capture_without_mutation[gpt-5.4,moonshot-k2,kimi-for-coding]`: equal capture/generation retained |
| Existing malformed containers/scalars | Retained mutation matrix and strict DAO validation; surrounding green |
| Existing authorized commits/provenance | Retained capture/publication/bootstrap suites; named policy and final attachment guards preserved |

Alias test initially used unsupported `moonshot-v1-8k`; it failed at normal catalog admission. Corrected fixture to actual seed alias `moonshot-k2`. This was a test-data error, not production RED or permission to add a model. No assertions weakened.

## Execution receipts

CWD `/root/Code/slo-94-herdr-integration/slo`. `pyenv which python` returned `/root/.pyenv/versions/slo-harness/bin/python`; Python 3.11.7. H = `bash docs/implementation/94-herdr/t1-dao-check.sh` (approved fallback, includes DAO/projection tests). Output is retained in tool transcript; no additional receipt files written.

Target set: mutation, capture, publication under `tests/agents/slo_agent/herdr/`, plus `tests/agents/slo_agent/orchestrator/test_bootstrap.py`.

| Command / stage | Result |
|---|---|
| H mutation `-k initial_snapshot` | 3 failed, 103 deselected; ValidationError escaped bootstrap initial snapshot |
| First conditional-only fix, H target set | 3 failed, 158 passed; permission alone did not validate source |
| Isolated snapshot boundary, H target set | 161 passed, 3 warnings |
| H mutation `-k construction_refuses` | 2 failed, 106 deselected; ValidationError escaped constructor |
| Constructor uses boundary, H target set | 163 passed, 3 warnings |
| Extended nested matrix + first surrounding | 1350 passed, 24 warnings, 76.37s |
| Alias fixture initial | 1 failed, 2 passed, 110 deselected; unsupported fixture model |
| Correct alias, H target set | 168 passed, 3 warnings |
| H mutation `-k optional_snapshot_failure` | 2 failed, 113 deselected; RuntimeError escaped both callers |
| Ordinary-exception containment, H target set | 170 passed, 3 warnings |
| Final surrounding, after formatting | **1361 passed, 26 warnings, 79.14s**, exit 0 |
| Final scoped mypy | **9 errors in 6 dependency files**, exit 1; zero in three owned files |
| Black --check three owned files | 3 unchanged, exit 0 |
| git diff --check | silent, exit 0 |
| dpkg -V coreutils | silent, exit 0 |

Final surrounding command:

```bash
bash docs/implementation/94-herdr/t1-dao-check.sh tests/agents/slo_agent/herdr tests/agents/slo_agent/test_session.py tests/agents/slo_agent/test_session_usage.py tests/agents/slo_agent/orchestrator/test_bootstrap.py tests/agents/slo_agent/test_session_rate_limits.py tests/agents/slo_agent/test_session_manual_compaction.py
```

Static command: `poetry run mypy src/agents/slo_agent/sessions/service.py src/agents/slo_agent/orchestrator/bootstrap.py tests/agents/slo_agent/herdr/test_session_mutation.py`. Initial scoped run had 12 errors including three owned nullable accesses; final nine are skills/service.py:13 yaml stubs; tui/transcript_projector.py:340 nullable tool name; providers/faux.py:73 two constructor kwargs and :87 override; assistant_chunk_normalizer.py:332 ToolCall; anthropic_claude_code.py:251 kwargs; openai_codex.py:179/:181 constructor types. Baseline 299/63 remains unwaived, not green. No full nine-minute gate ran, per instruction. Concurrent lane additions mean surrounding counts are not a frozen source manifest.

## Read coverage and remaining precise work

Read actual routing/scope plan, root RESEARCH, mutation-45 and evidence-45 reports; supplied AGENTS/CLAUDE/docs RESEARCH context; shared engineering routing/testing/ownership, coding rules/cadence/declarative; Python root, DAO/service/declarative/style/test-graphs/environment recipes (initial bulk truncation recovered through spilled-file prefixes); exact workflow overview and Code-Test-Review. KB Welcome prefix recovered, slo README/gotchas/conventions/environment read. Canonical C capture/provenance 542–831, all T5 sample attachment lines 2401–3720, and accepted independent turn-4 review read directly.

Still not established: full actual on-disk AGENTS/CLAUDE/docs RESEARCH re-ingestion; remaining routed KB companion pages/build-rule companions; canonical C surrounding affected branch ledgers and activation prose beyond the sample attachment; complete final diff and finite contract audit. These remain explicit rather than inferring completion from an earlier author's routing receipt. Production additions were small and tested red/green, but prerequisite reading was not completed before the edits; this is a process deviation, not waived by green tests.

Next action is this finite audit/read completion and any concrete resulting correction, not expanding to a new matrix or inventing recovery semantics. Full integration and independent review remain separately pending. Tests used preconstruction Faux factory, repository HERDR stripping/disabled/fake capability and terminal guards; no real Herdr/provider/window execution or system symlinks were introduced.
