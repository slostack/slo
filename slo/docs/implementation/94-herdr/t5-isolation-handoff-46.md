# T5 publication isolation handoff — 46

**READY for the bounded publication evidence family**, not complete T5, workflow acceptance, TUI/attention/T6 or release approval. No production RED remains in the added cases. Full integration/static baseline remains unwaived.

Accounting preserved: same unfinished turn 1; started 1, completed 0, historical partial 1, dispatch 46, retries 0. Effective turns and dispatches unlimited. No agents dispatched. Only `tests/agents/slo_agent/herdr/test_session_publication_isolation.py`, `test_session_publication_compositions.py`, this handoff and `t5-isolation-46-*.log` receipts were changed by this lane. No production, existing other tests/shared status, specification, global/KB, other-worktree or git lifecycle changes.

## Finite closure map

| Remaining 45 item | New evidence | Boundary and result |
|---|---|---|
| Actual provider error × publication faults | `test_actual_faux_terminal_with_publication_fault[False-*]` | Config-backed factory patched before construction; actual graph/Faux chunk generator raises synthetic OpenAI APIStatusError HTTP 413; exact error object survives projection/publish/diagnostic faults; exactly one durable run_failed |
| Actual cancellation × publication faults | same test `[True-*]` | External cancellation while actual Faux stream awaits; existing session cancellation-to-abort semantics retained; exactly one durable run_aborted, running flag cleared |
| Cancellation of actual running save | `test_cancellation_joins_actual_reporter_save` | Real reporter schedules real immutable store on thread; entered barrier proves save running; cancellation retains exact pending save task until release; task finishes before cancellation propagates; one exact reloadable unadvertised record, zero executable commands |
| Prompt cancellation during save | `test_actual_prompt_cancellation_during_running_save` | Config-backed actual Faux run cancelled while reporter-owned save is blocked; public abort and durable terminal complete BEFORE save release; release converges to exact original capture acknowledgment |
| Injected-agent provenance composition | `test_injected_faux_agent_cannot_acquire_standard_provenance` | Actual injected SloAgent/Faux, shared bootstrap early-return, real prompt completion/history/activation-input preparation; no pool construction, provenance or native capture |
| Four-provider privacy | `test_four_provider_publication_privacy_after_rotation` | Separate Anthropic/OpenAI/Kimi/OpenRouter synthetic before/after sentinels in renamed session, model, effort and noncanonical reasoning; actual session compact publication, detail projector, real reporter/store/guarded executable and nonempty fixed diagnostic log; resolve/require/store.load forbidden and asserted zero during publication/consumption |

Privacy scope is specifically B's arbitrary-label omission contract, **not four live provider inference tests or credential-store rotation integration**. Rotation here changes synthetic secret labels, as required to prove projection does not cache credential-dependent safe labels. Real rename/history redaction occurs outside the no-lookup publication guard. Canonical UUID is preserved; current usage DAO has no separate provider-label input. No private path or sentinel reaches captured argv, either public snapshot, or actual Herdr diagnostic records. Existing no-I/O/disabled/provenance/G1/fallback cases are retained, not re-created.

The error test does not claim committed-visible-output recovery coverage: provider chunk yield is not equivalent to session-visible commitment. HTTP 413 is deliberately an existing terminal provider contract. It traverses real classification/session finalization without disabling retry/recovery machinery. No paid/network provider call occurs.

## Honest first-pass results

- Initial terminal test: **6 failed, 76 passed, 17 warnings**. Fixture wrongly equated yielded Faux chunk with committed session output; generic ValueError entered existing recovery and exhausted the Faux script; early cancellation preceded visible delivery. Corrected fixture to explicit terminal HTTP 413 and model-entry evidence. This was not a production repair, nor a weakened publication-error identity assertion. Corrected run: **82 passed, 11 warnings**.
- Running-save cancellation: initial **91 passed, 5 warnings** (whole compositions plus harness foundations).
- Injected-agent initial: **1 failed, 82 passed, 11 warnings**, test passed Path to SloAgent's string cwd. Corrected to str(tmp_path); **83 passed, 12 warnings**.
- Four-provider privacy initial: **95 passed, 5 warnings**.
- Concurrent actual prompt/save: initial **96 passed, 6 warnings**.
- Privacy strengthening (detail projection and actual nonempty diagnostic sink): **96 passed, 6 warnings**.
- Final post-format affected + surrounding gate: **356 passed, 24 warnings in 15.32s**, exit 0. Compared with 45's 343-case partition this adds 13 cases. No skips/deselections reported.

Full stdout/stderr retained beside this document:
`t5-isolation-46-first.log`, `terminal.log`, `save.log`, `injected.log`, `injected-green.log`, `privacy.log`, `concurrent.log`, `privacy-final.log`, `surrounding.log`, `final.log`, `mypy.log`, `mypy-final.log` (each abbreviated name after the first uses the same `t5-isolation-46-` prefix).

## Commands and environment

CWD `/root/Code/slo-94-herdr-integration/slo`. Verified `pyenv which python` = `/root/.pyenv/versions/slo-harness/bin/python`; `python --version` = Python 3.11.7; `make test-env` = fallback, all exit 0. No venv/package installation.

Each targeted run used `bash docs/implementation/94-herdr/t1-dao-check.sh <owned-file>`; this approved script adds DAO/projection tests and safe fallback exports. Counts above include those foundations. Output was piped through tee with pipefail and the pytest pipeline status explicitly returned.

Final test arguments after that script:

```text
tests/agents/slo_agent/herdr/test_session_publication_isolation.py
tests/agents/slo_agent/herdr/test_session_publication_compositions.py
tests/agents/slo_agent/herdr/test_session_publication.py
tests/agents/slo_agent/herdr/test_session_capture.py
tests/agents/slo_agent/herdr/test_reporter.py
tests/agents/slo_agent/herdr/test_reporter_compositions.py
tests/agents/slo_agent/test_session.py
tests/agents/slo_agent/test_session_usage.py
tests/agents/slo_agent/orchestrator/test_bootstrap.py
```

`poetry run black --check` on both owned files: exit 0, two unchanged. `git diff --check`: silent, exit 0. `dpkg -V coreutils`: silent, exit 0. Final owned code reviewed for barrier release/join, forbidden effects, honest evidence assertions and typed signatures; no Any/cast/ignore introduced.

`poetry run mypy <both-owned-files>`: **exit 1, 9 errors in 6 dependency files, ZERO owned-file diagnostics**. Full output is in `t5-isolation-46-mypy-final.log`: yaml stubs; transcript_projector nullable tool_name; Faux constructor queue/chunk_queue and bind_tools override; assistant_chunk_normalizer ToolCall item; Anthropic kwargs; Codex openai_api_base/api_key. This is not green global typing. Previous session-service nullable errors are absent in current concurrent production bytes, not fixed by this lane. Historical full baseline **299/63 remains unwaived**. No full make integration gate ran; that is later owner work.

Final owned hashes:

```text
19a71f9e827231d360849f905a9b7512344987ca61f7f5a7e13c750fe1cd3b47  test_session_publication_isolation.py
a65690b7cdd426defbd3ca3fa65adea3c311be2ca2fc27c81a9a3ac59ce9db5d  test_session_publication_compositions.py
```

## Affected required-read completion

Actual on-disk reads, not just inherited receipt claims: AGENTS 1–1013; CLAUDE 1–65; root RESEARCH 1–41; docs/RESEARCH 1–633; routing.md and scope-plan.md; Makefile and approved harness; current root conftest/state_isolation guards; actual Faux, session publication/constructor, reporter save/join, bootstrap and both owned tests. Read 45 evidence before changes.

Loaded committed engineering routing/testing/ownership; coding rules/code-test-loop/shared declarative/test-verification; Python root/DAO-domain/application-service/declarative/named-arguments/docstrings/test-graphs-and-agents/environment recipes; workflow SKILL. The initial large skills output was truncated; recovered its omitted prefix through `/tmp/slo-bash-jd3gci67.txt` lines 1–1725. Full remainder was present in the initial tail. Test-graphs recipe remainder 100–589 was explicitly completed. Framework examples do not impose SQL/HTTP/synthesis-node architecture on this project. No fresh implementation design or agent workflow was launched.

KB read-only: Welcome, actual slo README, gotchas, skills-and-kb, tui-cli-session and headless-workflow-orchestration. Initial combined output truncation recovered through `/tmp/slo-bash-d1rudqpg.txt` 1–590; remaining tail was returned in full. Historical paths/policies are subordinate to actual source and current user scope. No OS changes or live inspection were performed.

Canonical readonly H = `/root/Code/specifications/projects/slo/specifications/94-slo-tui-redesign/herdr`: C 7.8/7.9 capture/provenance (542–755), C section 8 through dependencies (2122–2175); B 7.6 public projection (334–375), privacy requirement (2035–2058); full historical SLO_HERDR_PUBLICATION_CONTRACT (current B/C override its label recommendations); **all T5 samples tasks.md 2401–3720**; accepted independent-review-turn4 in full. App/attention/viewer samples were read for boundaries, not claimed implemented here. This completes the affected publication-read audit; it does not claim rereading every unrelated routed CLI/TUI/OS recipe or full B/C/D family in this lane.

## Safety and handoff boundaries

Existing collection/per-test HERDR stripping, force-disable and terminal blocker remain untouched. Actual Herdr transport execution uses only registered new regular temp executable with capture/barrier containment and inode/device revalidation. New save tests assert temp root containment; no system symlinks. Every blocking store barrier releases in finally, tasks are joined before teardown, and credential/model seams are synthetic before config-backed construction. Coreutils verification silent.

Other lane owns production mutation guards. Concurrent source changes mean this is not an atomic repository freeze. No claim of working-state/attention/TUI replacement/shutdown or T6 acceptance is made. Independent review/completion and integrated full/static gates remain required. This handoff closes the named finite publication evidence gaps, not the entire feature.
