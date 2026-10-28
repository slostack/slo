# Core161 read ledger and exact sample allocation

All paths below are relative to `/root/Code/slo-94-herdr-integration/slo` unless prefixed H or KB. “Full” means actual body/assertion reading, not inventory/hash/grep. Shell aggregate reads listed below completed without truncation. One initial prerequisite aggregate truncated; its beginning is NOT claimed read through that output. Routing/scope/independent158 were then explicitly read;159/160/CLAUDE/root RESEARCH/Makefile were present in the retained untruncated tail. Supplied full AGENTS/CLAUDE/docs RESEARCH context is explicitly distinguished from disk reads.

## Governing context

- `AGENTS.md`: full1080 lines supplied in prompt, disk1–220 before source work.
- `CLAUDE.md`: full65 supplied and disk.
- `RESEARCH.md`: full80 disk; `docs/RESEARCH.md`: full723 supplied context, not claimed fresh disk body read.
- `Makefile`: full105 disk.
- `docs/implementation/94-herdr/routing.md`: full explicit read; `scope-plan.md`: full1–180 (requested1–250 reached EOF).
- `independent-review-158.md`:1–140 explicit read,141–211 in initial retained aggregate tail; full source/test closure qualifications consumed. Prior evidence used as leads, not as approval. No reliance on a claimed full155 audit.
- `integration-revision-160.md`, `usage-revision-159.md`, `conventions-revision-159.md`: complete bodies in retained aggregate output; actual160 run.sh/full/smoke/lint command+exit and result tails separately inspected.
- `t5-adoption-outcome-83.md`: complete explicit read, documents intermediate-close deviation rather than authorizing it.
- KB `/root/Code/KnowledgeBase/KB/Welcome.md`, `slo/README.md`, `slo/gotchas.md`: full bodies; no slo/index.md exists. Read-only, no KB mutation.

Skills fully loaded through read tool from this worktree: `engineering/{engineering-routing,engineering-review,engineering-ownership,engineering-testing}/SKILL.md`; `design-and-analysis/workflows/code-test-review.md`; `design-and-analysis/review-feature-code/SKILL.md`; `languages/python/{code-review-rules,python-conventions,named-arguments-and-type-hints,method-docstrings,build-domain-features,build-application-services,declarative-method-structure}/SKILL.md`; `coding/{coding-rules,declarative-method-structure}/SKILL.md`; `design-and-analysis/ubiquitous-language/SKILL.md` sequential1–400,401–600,601–750,751–900,901–920,921–EOF. No selected personal override indicated in supplied manifest. Full routing companion list is not claimed loaded: no CLI/TUI implementation, graph, database, deployment or new design task belongs to this partition.

## Canonical documents

H = `/root/Code/specifications/projects/slo/specifications/94-slo-tui-redesign/herdr` (reference-only).

| Path | Exact complete read ranges |
|---|---|
|H/overview.md|1–239|
|H/94.b.1-herdr-reporting-adapter.md|1–500;501–1050;1051–1600;1601–2221|
|H/94.b.2-session-publication-and-native-restore.md|1–550;551–1100;1101–1650;1651–2175|
|H/94.c.1-herdr-workflow-visualizer-and-acceptance.md|1–400;401–711|
|H/tasks.md|1–285;286–885;886–1485;1486–2085;2086–2585;2586–3185;3186–3816|
|H/SLO_HERDR_INTEGRATION.md|1–344|
|H/SLO_HERDR_PUBLICATION_CONTRACT.md|1–353|
|H/review-evidence/task-sample-inventory.md|Full table, every allocation and ten exclusions|
|H/review-evidence/independent-review-turn4.md|Full report through final READY-for-breakdown paragraph|

Thus governing prose and sample bodies were consumed, not inferred from inventory. Other historical spec review companions were not needed as competing authority; accepted turn4 provides resolved findings. No normative specification edit or document probe counted as product testing.

## All72 allocated samples — owned/unowned split

Core-owned31 samples; unowned41. Every allocated ID appears exactly once below. Some samples describe shared flows: “core-owned” certifies only the core endpoint, never the unaudited caller. The ten excluded historical fences are separate from72.

|ID(s), enumerated|Count|Partition and source/assertion mapping|
|---|---:|---|
|B01,B03|2|CORE: support layout and unchanged AtomicFileWriter reuse; source full, restore/sequence actual writer assertions|
|B04,B06|2|CORE: publication flow and fixed lifecycle argv; reporter publish/batch/builders; report_steps/lifecycle_commands/batch_failure tests|
|B07|1|CORE: DAO token bound shared with projector; projection/privacy_closure byte/character/control/encoding cases|
|B08,B12|2|CORE: exact save association and worker continuation; reporter G1/save_worker_closure/t2_remaining|
|B09,B10,B11|3|CORE: reporter admission, transport lock/spawn, retained join; cli_transport and transport_lifetime|
|B13,B14|2|CORE: send/batch/semantic ack; policy_accounting/operation_results/batch_failures/restore_batch_closure|
|B15,B16|2|CORE: all operation predicates/effects; ordinary currentness matrix, terminal matrix, definitive spawn failure, exact release matching|
|B17,B18|2|CORE: transport terminal join/quarantine; late spawn/read/pipe/callback/reap/final drain tests|
|B19,B20,B21,B22|4|CORE: activation/close/assembly/invocation evidence/reservation; activation_lifetime/final_lifetime/report helpers; B19 deviation R161-3|
|B25|1|CORE: revocable live authority; viewer_authority_closure and actual queued viewer sequence-failure tests|
|C05|1|CORE builder endpoint: exact five-element argv; reporter lifecycle_commands/resume_bounds. CLI admission caller deferred|
|C06,C07|2|CORE: immutable store/load/save; all restore suites; R161-1 descriptor cleanup applies|
|C27|1|CORE: canonical UUID predicate with ordinary compatibility; identity tests|
|C28,C29|2|CORE: final local transport/reporter drain; retained/final lifetime tests, zero remote resend/accounting|
|D04,D05,D06,D07|4|CORE: exact viewer commands/registry/ledger/admission/parser; all four visualizer test modules plus authority closure|
|B02,B05|2|UNOWNED wiring: session subscriber/publication callers|
|B23,B24|2|UNOWNED harness audit: guard algorithm and fixture delegation. Read dependency and owned guard assertions here; complete broader harness security remains later|
|B26|1|UNOWNED gate synthesis: chapter/full/static commands; retained160 receipt inspected, not whole gate review|
|C01,C02,C03,C04|4|UNOWNED session/CLI/runtime flow and before-code|
|C08,C09,C10,C11|4|UNOWNED capture/provenance/bootstrap/pool disposal|
|C12,C13,C14,C15,C16|5|UNOWNED candidate transaction/UI/runtime/disposal/delivery|
|C17,C18,C19,C20,C21|5|UNOWNED inbox/registration/queue cutoff|
|C22,C23,C24,C25,C26|5|UNOWNED attention/session lifetime/app diagnostics/timers/shutdown|
|C30,C31|2|UNOWNED session retained drain and integrated chapter gates|
|D01,D02,D03,D08,D09|5|UNOWNED entry paths/destination/platform thread and composed acceptance gates|
|O01,O02,O03|3|UNOWNED whole runtime/journey/pane schematic; core segments traced, live/user visual acceptance deferred|
|I02,I03,I04|3|UNOWNED historical adjacent event/usage/history context, never current replacement contracts|

Excluded (not among72): I01,I05,I06,I07,I08,P01,P02,P03,P04,R01. Superseded journey/tree/gate/--model/--current/focus/model-label proposals are not reinstated. R01 belongs separate editor work. Full I/P source bodies were read; parent editor source itself not independently audited.

## Production full-body coverage

|Path|Ranges|
|---|---|
|src/agents/slo_agent/herdr/__init__.py|1|
|src/agents/slo_agent/herdr/dao.py|1–527|
|src/agents/slo_agent/herdr/service.py|1–350;351–698|
|src/agents/slo_agent/herdr/reporter.py|1–380;381–760;761–1090|
|src/agents/slo_agent/herdr/sequence_store.py|1–203|
|src/agents/slo_agent/herdr/restore.py|1–174|
|src/agents/slo_agent/herdr/visualizer.py|1–279|
|src/agents/slo_agent/sessions/identity.py|Full1–101|
|src/agents/slo_agent/sessions/token_format.py|Full1–56|
|src/agents/slo_agent/orchestrator/context_reader.py|Full1–35|
|src/agents/slo_agent/history/atomic_io.py|Full unchanged dependency|

Complete extraction diffs inspected: `src/cli/headless_request.py`, `src/tui/widgets/usage_status_bar.py`, `src/tui/workflow_visualizer_loader.py`. This does NOT claim full surrounding CLI/TUI audit. Session close2531–2542 and related grep context inspected only to establish consumer workaround for R161-3; all session implementation remains later partition.

## Owned tests — exact full-body line coverage

Prefix `tests/agents/slo_agent/herdr/`. Each listed range is complete, including helpers, parameterization and finally blocks; inventory is not used as a reading substitute. These exact files plus the three adjacent tests were independently run (1070 passed).

|File|Read|
|---|---|
|test_activation_lifetime.py|1–114|
|test_batch_failures.py|1–62|
|test_cli_transport.py|1–341|
|test_daos.py|1–377|
|test_diagnostic_closure.py|1–141|
|test_fake_fixture.py|1–40|
|test_final_lifetime_closure.py|1–336|
|test_gate_diagnostics.py|1–127|
|test_gate.py|1–41|
|test_independent_lock_holder.py|1–73|
|test_operation_results.py|1–110|
|test_path_recovery.py|1–32|
|test_policy_accounting_closure.py|1–439|
|test_privacy_closure.py|1–336|
|test_projection.py|1–187|
|test_refresh_timer.py|1–49|
|test_reporter_compositions.py|1–163|
|test_reporter_diagnostics.py|1–51|
|test_reporter_final_drain.py|1–68|
|test_reporter.py|1–500;501–983|
|test_reporter_shutdown_closure.py|1–99|
|test_reservation_composition.py|1–85|
|test_restore_batch_closure.py|1–84|
|test_restore_boundaries.py|1–154|
|test_restore_composition.py|1–58|
|test_restore_faults.py|1–88|
|test_restore_io.py|1–110|
|test_restore_process.py|1–194|
|test_restore.py|1–59|
|test_restore_remaining.py|1–216|
|test_restore_save.py|1–119|
|test_restore_security.py|1–189|
|test_resume_bounds.py|1–59|
|test_retained_transport_composition.py|1–83|
|test_save_worker_closure.py|1–265|
|test_sequence_store.py|1–416|
|test_spawn_guard.py|1–93|
|test_t2_remaining.py|1–339|
|test_test_isolation.py|1–209|
|test_transport_diagnostics.py|1–46|
|test_transport_lifetime.py|1–224|
|test_transport_read_failures.py|1–77|
|test_transport_signals.py|1–105|
|test_viewer_authority_closure.py|1–160|
|test_visualizer_acceptance.py|1–404|
|test_visualizer_lifecycle.py|1–174|
|test_visualizer_lifetime_acceptance.py|1–299|
|test_visualizer.py|1–122|
|test_worker_wake.py|1–71|

Adjacent full tests: `tests/agents/slo_agent/test_session_identity.py`, `test_token_format.py`, `orchestrator/test_context_reader.py` (complete concatenated bodies). Dependency full reads: `tests/state_isolation.py`1–129; `tests/conftest.py`1–206. Full harness fault/supervisor/security fixtures outside this directory remain unowned, not certified by these reads or the package run.

## Evidence boundaries

- Actual full diff inventory: `tracked-diff-inventory.txt` plus `untracked-inventory.txt`. Core additions are untracked, so inspecting only `git diff HEAD` would miss them; every owned new body was read directly.
- Frozen160 verification: `manifest.log`; all835 entries unchanged after probes/tests. Exact156-only path list and existence evidence there. No removed inputs claimed.
- Independent targeted1070 result: command/log/exit/coreutils files. No skips or deselections in this selection; four warnings recorded.
- Independent counterexamples: retained Markdown code in `probes.md`, rerun `probes.log/.exit/.coreutils`. No permanent test/code change made.
- Prior158 full core source-reading evidence is corroborated by fresh full reads, not substituted for them. Its unclosed full-feature audit remains globally open pending partition synthesis.
- Initial malformed parallel-tool call supplied empty parameters and read nothing; corrected individual calls followed. Initial oversized prerequisite output truncated; no truncated core/canonical/test body is counted. These tool mistakes are not workflow retries or completed passes.
