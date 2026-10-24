# Dispatch153 — partition A-projector READY (bounded offline)

**READY for A only: all 81 original A diagnostics repaired; final affected/surrounding tests GREEN.** Not full-feature Code+Test completion, independent Review, Completion, or release approval. Live acceptance remains user-deferred; Herdr compatibility UNVERIFIED.

Turn1 started1/completed0/historicalpartial1/retries0; dispatch153 parallel batch. Effective turns/dispatches unlimited. No subagents. No git mutations, package/config/guard/status/shared-document changes, other-worktree/global edits, or live provider/Herdr/terminal actions.

## Scope and routing

First inspected status/branch/remotes and supplied AGENTS/CLAUDE. Verified feature-94-herdr-integration, origin https://gitlab.com/core-27/slo.git, HEAD d0e3a756689f2675e5507034d43cd8b272d3c6b8. Preserved existing tracked/untracked work. Source/test writes are exactly:

- src/tui/transcript_projector.py
- tests/tui/test_transcript_projector.py
- tests/tui/test_tool_block_partial.py
- tests/tui/test_recovery_ux.py

Evidence only in this report and static-A-153-receipts/. Read root RESEARCH, supplied docs/RESEARCH, actual Makefile/helper, routing, scoped scope-plan/static142/147/151/152 guidance and A .files/.tests; inspected147 inventory and152 lint (81 A errors). Preliminary bulk documentation output truncated: not a claim of complete full-feature ingestion. Scoped owner source, host/widget contracts and affected assertions supplied the implementation boundary. KB Welcome, actual slo/README (no index.md) and gotchas consulted read-only.

Effective installed SLO_SKILLS_DIR used for engineering routing/ownership/testing, coding-rules then cadence, shared/Python declarative, Python root/named-arguments/docstrings, and Textual guidance. Verified installed design-and-analysis/workflows/code-test-review.md absent; loaded authoritative worktree workflow per user/152. Task category: projector orchestration units plus real unmounted widget behavior and mounted offline surrounding journey; no new component/service/CLI or TUI redesign. Independent phases remain later.

## Corrections and causal proof

1. **Nameless partial boundary:** actual tool_output_update with no event or existing block name raised Pydantic ValidationError constructing ToolOutputUpdateDAO. Added the intended-behavior test before production change; red-nameless retains 1 failed/62 passed. Existing DAO accepts empty str, and ToolExecutionBlock.update_partial explicitly uses snapshot.tool_name or self._tool_name. The minimal fallback `event.tool_name or block.tool_name or ""` therefore preserves unknown identity/blank headline instead of asserting a name exists or changing the DAO. Later named result updates the same block and settles/pops it. Added known-name fallback and explicit-name precedence cases; real widget partial state remains separate from terminal output.
2. **Complete widget/host contracts:** answer/thinking recording subclasses now initialize their real Textual base; tool/user doubles inherit real widget behavior and properties. Tool incomplete alias delegates to real is_incomplete. Host methods explicitly return compatible initialized widgets, accept before and optional names. Existing order/seal/finalize/abort/failure/result assertions remain.
3. **Partial tests:** narrow retrieved dictionary members to the actual recording subclass; do not narrow invariant dictionaries. Recorder calls real update_partial before recording snapshots.
4. **Recovery:** removed incomplete duplicate MagicMock host and reuse the complete existing FakeHost. Notice and no-answer-mount assertions preserved.

No new Any/cast/ignore/checker suppression/exclusion; no assertions removed or weakened. Pre-existing ignores outside the changed logic remain unchanged. Production change is one fallback plus its explanatory comment.

## Cadence and exact evidence

Every receipt has exact argv `.command`, full `.log`, and `.exit`. `run.sh` binds VIRTUAL_ENV=/root/.pyenv/versions/slo-harness, PATH prefix and PYENV_VERSION=slo-harness; mypy has a lane-specific cache. Python is approved3.11.7. Tests use existing t1-dao-check.sh's tracked safe Makefile fallback, never development secrets. That helper adds **62 foundation tests**; counts below include them and overlap.

| Receipt | Result |
|---|---|
| red-static | 81 errors/4 files, exit1 |
| red-nameless | actual Pydantic nameless failure, 1 failed/62 passed, exit1 |
| green-nameless | partial+projector modules,132 passed, exit0 |
| green-widgets | intermediate read-only text property assignment mistake:4 failed/128 passed, exit1 |
| green-widgets-corrected | inherited real user text property,132 passed, exit0 |
| green-host-partial |132 passed, exit0 |
| intermediate-static | only recovery's5 diagnostics remain, exit1 |
| green-recovery |144 passed, exit0 |
| green-static | zero errors/4 files, exit0 |
| green-name-branches |173 passed, exit0 |
| final-surrounding |189 passed, exit0; later static check exposed un-narrowed render union |
| final-static |5 new union-attr diagnostics in added headline assertion, exit1 |
| final-surrounding-corrected | wrong Text narrowing exposed actual Content:1 failed/188 passed, exit1 |
| **final-surrounding-content** | **189 passed,18 warnings,47.56s; exit0** |
| **final-static-content** | **no issues in4 files, no-incremental; exit0** |
| **final-black-content** | **4 files unchanged; exit0** |
| **final-diff-content** | **silent; exit0** |
| **coreutils-content** | **dpkg -V coreutils silent; exit0** |

Final test command (run through receipt wrapper):

```sh
bash docs/implementation/94-herdr/t1-dao-check.sh \
 tests/tui/test_transcript_projector.py tests/tui/test_tool_block_partial.py \
 tests/tui/test_recovery_ux.py tests/tui/test_tool_execution_block.py \
 tests/tui/test_replay_resume.py \
 tests/integration/test_herdr_full_flow.py::test_unified_mounted_prompt_configuration_both_viewers
```

The explicit mounted node runs all six route/uncertainty cases with existing fake-only guards, not integration-directory discovery. Final static uses `poetry run mypy --no-incremental --follow-imports=silent` with exactly A-projector.files. This is bounded diagnosis/verification, **not a replacement for final make lint**. Final Black uses those same four paths. Reviewed scoped diff; final.sha256 freezes these four files. Coreutils was also silent immediately after each earlier suite (earlier checks inline; final checks retained separately).

## Remaining integration gates

No A diagnostics remain in the fresh scoped check. Full make lint and full suite intentionally NOT run while B/C/D write; no arithmetic claim about current global diagnostic totals. Integrator must run all required gates on the final unchanged combined snapshot, then independent full-feature Review and fresh Completion. Existing151 full8653 is historical, not post-A evidence. Offline mounted tests do not establish live supported-version/native-restart/pane/paint compatibility. No shared KB/research/status edits made under this lane's write restriction.
