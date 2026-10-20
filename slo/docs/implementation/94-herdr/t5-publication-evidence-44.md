# T5 publication/provenance compositions — continuation 44

**Verdict: INCOMPLETE for the entire assigned finite family.** The tested subfamilies below pass; this is not full T5 readiness, workflow acceptance, or an attention/working-hook claim. No demonstrated production RED remains in this new file. Remaining cases are listed explicitly rather than inferred from adjacent tests.

Same unfinished turn 1: started 1, completed 0, historical partial 1, dispatch 44, retries 0. User turn/dispatch limits unlimited. No agents dispatched. Only the new `tests/agents/slo_agent/herdr/test_session_publication_compositions.py`, this document, and `t5-44-*` receipts were written. Production, existing tests, shared status, specs, KB/global state and other worktrees were not edited by this worker. No commit/push/PR/reset/clean/stash or live provider/Herdr/window operation.

## Authority and finite family map

Canonical read-only authority: `94-slo-tui-redesign/herdr/94.b.2-session-publication-and-native-restore.md` (C), especially 7.8, 7.9, capture/provenance branch ledger around 1347–1353 and section 8. C requires committed capture/eligibility identity, not report revision or catalog generation, to control configuration generation. Exact standard provenance means tool object identity and exact injected additions, not matching strings or names. Unsupported mutation must withdraw eligibility; a later unrelated supported commit cannot certify it. Usage events reuse a frozen capture without I/O. A same-capture save must continue with newest display (G1); a different capture must never advertise the stale save. This does not require a generation for rename, usage, route fallback, or unchanged catalog adoption.

C section 8 also requires operation/attention, mounted replacement, CLI/restore, headless and process acceptance. Those are not made complete by this publication-only test file. In particular, current publication's fixed idle projection is NOT asserted to satisfy working/attention behavior.

Existing proofs are reused by name, not counted again as new coverage:

| Finite family | New evidence / retained named evidence | Status / remaining |
|---|---|---|
| Standard origin | New `test_custom_origin_never_mints_provenance` (append/tool/hook); retained `test_standard_bootstrap_records_only_pristine_policy` (pristine/spoofed system) | Tested cases pass. Explicit standard-headless plus injected-origin composition remains absent here; capture headless/injected gates are retained separately, not equivalent proof |
| Failed construction / early return | New `test_bootstrap_failure_never_mints_provenance` (pool/workflow-tools/attach), `test_bootstrap_early_return_never_mints_provenance` (agent/pool) | Pass; failures preserve original exception and never call finish |
| Later provenance mutation | New `test_standard_provenance_rejects_later_mutation` (equal-but-distinct tool, removal, system, append, hook); retained reordered-tool case, `test_general_attach_immediately_withdraws_capture`, `test_changed_identity_during_bootstrap_cannot_certify` | Pass for these branches; not a claim of every mutation during construction |
| Activation and paths | Retain `test_activation_reads_existing_metadata_without_creating_history`, `test_activation_eligibility_branches`, `test_activation_path_sources_are_guarded`, `test_activation_does_not_skip_explicit_workspace_persistence` | No duplicated tests/count; metadata failure-refresh/reset matrix still needs explicit proof |
| Scalar/pool capture | Retain `test_pool_capture_copies_order_and_all_scalars_without_aliases`, `test_mutated_pool_is_refused`, `test_capture_uses_established_facts_and_effective_policy` | Existing copy/validation proof is not saved-bytes-after-caller-list-and-entry-mutation composition; that section-8 case remains |
| Unsupported edit followed by ordinary commit | New `test_supported_reasoning_commit_cannot_certify_unrelated_pool_mutation` | Pass against concurrently updated production; no RED-to-GREEN claim |
| Persistence cutoffs | New `test_failed_persistence_does_not_publish` (history/rename × OSError/CancelledError); retained startup success/failure/cancel capture test | Pass with exception identity, no publish, capture/generation unchanged, metadata/no-directory assertions. Startup stale-config early-return publication call-count matrix remains |
| G1 and changed config during save | New `test_real_session_save_barrier_latest_publication[usage_rename,reasoning]` | Pass: actual config-backed Faux session completes while real store blocked; refresh records 15 tokens; rename retains capture; same save uses newest display; changed reasoning refuses A commands then saves B. Real files + registered actual executable, no injected-agent eligibility shortcut |
| Catalog no churn | New `test_catalog_only_adoption_does_not_save_or_release` | Pass through actual adoption twice, same capture/generation/binding, zero additional save/release. Uses unchanged catalog snapshot, not a network refresh or independently incremented catalog generation |
| Routed fallback no churn | New `test_real_routed_fallback_keeps_configured_capture` | Pass: actual ModelPool catches primary 429-text failure, secondary Faux completes; durable route_switched, 15 tokens, configured frozen pool unchanged, zero new save/release |
| Memory-only publication | New `test_publication_has_no_io_credentials_or_model_build[active,inactive,closing]`; retain `test_usage_commit_publishes_latest_without_capture_or_io` | Pass: Path resolve/open, resolver resolve/require, agent build, recapture, restore save, task creation all forbidden and explicitly uncalled; no swallowed assertion misreported as success |
| Ordinary publication failure isolation | New `test_publication_failure_preserves_rename_and_history[projection,reporter,diagnostic]` | Pass: actual rename result/metadata retained, no history event invention, two diagnostic delegations; diagnostic failure also isolated |
| Full result/history/cancellation semantics | Retain lifetime and reporter cancellation proofs; new persistence cancellation above | **Incomplete:** actual Faux invoke under projection/publish faults, original provider/run error preservation, and externally cancelled invoke/save composition not added. Do not infer these from successful rename or direct reporter joins |
| Privacy | G1 actual command capture excludes prompt/name/path; existing private DAO/projection tests run | Not full four-provider sentinel scan or all public-channel proof |

## Test construction and safety

The G1 composition assembles a real reporter using the existing `reporter` fixture helper and manually consumes publications, deliberately avoiding timer-dependent assertions. Session activation input preparation, real persistence/rename/invoke/usage commits, immutable restore store and actual CLI transport are real. Reporter worker scheduling/startup is not tested by this assembly. The store uses a bounded thread event barrier; finally releases and joins the consumer before session close. The changed-reasoning branch verifies no A command before explicitly consuming B.

`plain_slo` is reused from the existing reporter suite: a NEW regular temp-owned executable, not a system symlink. Root suite guards remove HERDR inheritance, default disabled and require fake executable registration/identity before transport spawn; terminal guard remains active. Factory and synthetic credential resolution patches enclose session construction and invocation. No provider client is constructed. Coreutils integrity check is mandatory and silent below.

## Executed receipts

CWD `/root/Code/slo-94-herdr-integration/slo`. `pyenv which python` returned `/root/.pyenv/versions/slo-harness/bin/python`; Python 3.11.7; `make test-env` returned `fallback`. No environment installation/change. H = `bash docs/implementation/94-herdr/t1-dao-check.sh`; P = `tests/agents/slo_agent/herdr/test_session_publication_compositions.py`. H adds existing DAO/projection tests; counts below are total executed tests, not new unique coverage.

All rows have `t5-44-<name>.log` and `.exit` in this directory.

| Name | Command | Actual result |
|---|---|---|
| provenance | H P | 72 passed; exit 0 |
| cutoffs | H P | 77 passed; exit 0 |
| barrier | H P -k save_barrier | 2 passed, 77 deselected; exit 0 |
| catalog | H P -k catalog | 1 passed, 79 deselected; exit 0 |
| isolation | H P -k 'custom_origin or publication_failure' | 6 passed, 80 deselected; exit 0 |
| fallback | H P -k routed_fallback | 1 failed, 86 deselected; exit 1 — test setup defect: configured_pool helper contains unsupported inference model gpt-5.4-mini; NOT product RED |
| fallback-corrected | H P -k routed_fallback | 1 passed, 86 deselected; exit 0 — use catalog-supported gpt-5.5 primary, unchanged fallback assertions |
| no-io | H P -k no_io | 3 passed, 87 deselected; exit 0 |
| surrounding | H P tests/agents/slo_agent/herdr/test_session_publication.py tests/agents/slo_agent/herdr/test_session_capture.py tests/agents/slo_agent/herdr/test_reporter.py tests/agents/slo_agent/herdr/test_reporter_compositions.py tests/agents/slo_agent/test_session.py tests/agents/slo_agent/test_session_usage.py tests/agents/slo_agent/orchestrator/test_bootstrap.py | **329 passed, 13 warnings, exit 0** |
| black | poetry run black --check P | exit 0 |
| diff | git diff --check | silent; exit 0 |
| coreutils | dpkg -V coreutils | silent; exit 0 |

Black formatting was run on P only before the surrounding gate. No full make/test/smoke/lint gate was run, per test-only assignment; integration owner owns those gates. Historical 299/63 static baseline remains unwaived, not green. Review of the new tests confirmed no xfail, skips, weakened product assertions, or production edits. No independent reviewer or completion assessment ran.

## Concurrent source and reading qualification

Production owner changed `sessions/service.py` while this worker ran (the later `_adopt_herdr_capture` has an authorized-field comparison absent at initial inspection). All passing results are initial-pass evidence against the then-current source, not sensitivity/repair evidence. `t5-44-observed-source.sha256` records post-surrounding observed session/bootstrap/reporter/new-test hashes; it is not an atomic freeze across another owner's edits.

Read 42/43, routing/scope plan, root RESEARCH, supplied AGENTS/CLAUDE/docs RESEARCH, actual session/bootstrap/reporter/store and affected tests, canonical C capture/provenance/section-8 text and opening T5 sample attachments, KB entry/gotchas and shared/Python/workflow guidance. Some bulk skill output truncated, and the complete B/privacy chapter plus all T5 attachment lines were not ingested in this continuation. Full prerequisite-reading compliance is therefore **not claimed**. This and the explicit missing compositions above prevent a whole-family READY verdict.

No budget stop is asserted. This receipt hands back bounded passing evidence and precise remaining work; it does not close the unfinished workflow turn.
