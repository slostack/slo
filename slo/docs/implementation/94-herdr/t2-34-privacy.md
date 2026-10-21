# T2 privacy/projection lane — bounded coverage ready; package gate INCOMPLETE

Code+Test only, 2026-10-18. No independent review, T2 dependency approval, feature completion or live compatibility claim. Effective workflow turns/dispatches unlimited; parent accounting preserved: turn 1 started 1/completed 0/historical partial 1, dispatch 21, retries 0. No child agents launched.

## Ownership and changes

Actual projector owner is `src/agents/slo_agent/herdr/service.py::HerdrSnapshotProjector`; `projection.py` does not exist. No competing owner was invented and **no production file was edited**. The sole new test file is `tests/agents/slo_agent/herdr/test_privacy_closure.py`. Existing tests/partial files and frozen routing/specification files are preserved. Only this evidence and `t2-34-privacy-*` receipts were written outside that test file.

Coverage-only additions passed initially; there is no fabricated RED. Four small test increments were run against existing DAO/projection tests before continuing, then the package and formatter/footer surroundings. The real-wire test uses the existing registered temp regular executable/capture/barrier capability, revalidates before modifying its script, and delegates through actual transport spawn/admission. It acquires the actual sequence-store lease, invokes real publication consumption/save association/command construction, observes actual child argv, then closes reporter and transport. The injected store returns an opaque reference; this does **not** prove T3 restore durability.

## Exact helper/decision map

Paths below are relative to `tests/agents/slo_agent/`; `P` means `herdr/test_privacy_closure.py`, `E` means `herdr/test_projection.py`. This is an audit of the projection/privacy helpers, not a blanket certification of every reporter/lifetime method.

| Production helper / decision | Named executable evidence | Scope / limitation |
|---|---|---|
| Projector `build`: canonical ID accepted/refused, compact/detail dispatch, None filtering | P `test_invalid_identity_is_fixed_error`, `test_zero_and_context_gates`, `test_four_provider_wire_privacy`; E `test_detail_numeric_projection` | Fixed rejection never echoes slug/uppercase/braced ID. Ordinary identity normalization remains separately covered by `test_session_identity.py`. |
| `_detail`: exact seven reasoning constants vs unknown/case/whitespace | P `test_reasoning_exact_membership` | No normalization, arbitrary string conversion or provider inference. |
| `_detail`: usage-available gates total/input/output independently from session counters | P `test_unavailable_turn_does_not_hide_session_totals`, `test_zero_and_context_gates`; E `test_detail_numeric_projection` | Known zero preserved, unknown omitted, negative cache omitted; exact order asserted. |
| `_detail`: rpm renderable/unknown/oversized; tpm/output cap/budget | P zero matrix; E `test_detail_numeric_projection`, `test_huge_numeric_fields_do_not_abort_projection` | Raw rpm, formatted token units; no float conversion for huge integers. |
| `_compact`: cumulative totals, context order, cooldown None/negative/zero/positive | P `test_compact_cooldown_cutoff`; E `test_compact_context_precedes_cooldown`, `test_compact_projector_omits_all_free_text` | Compact context precedes cooldown; detail excludes compact-only fields. |
| `_context`: history false, context absent, estimate false, invalid percentage, remaining vs percentage, detail suffix | P `test_zero_and_context_gates`, `test_invalid_context_is_independently_omitted`, `test_compact_cooldown_cutoff`; E detail/compact order and huge numeric tests | Invalid one token does not discard valid zero remainder; compact `%` versus detail ` estimated`. |
| `_finite`: bool/non-number/negative integer/negative float/NaN/±Inf vs nonnegative integer/finite float | P `test_numeric_refusal`, zero/context tests, threshold tests | Uses real usage DAOs; model_construct only for deliberately invalid context numeric observations. |
| `_renderable`: finite plus conversion bound | P numeric refusal and zero/context tests; E huge-field tests | Huge int conversion is independently refused. |
| `_number`: unknown/negative vs known zero/positive, oversized cutoff | P unavailable-turn/threshold tests; E `test_oversized_count_is_omitted_without_float_conversion` | Formatter called only after numerical guard. |
| `_make_token` and DAO `_validate_value` / `_safe_token_value`: empty, character limit, byte limit, category C, whitespace, encoding failure | P `test_final_token_boundary`, `test_encoding_failure_omits_whole_token`; E safe/unsafe/shared predicate tests | 80/81 ASCII, 64/65 two-byte, CR/LF/TAB/ESC/DEL, Cf/Co/Cn/Cs, NBSP/line separator. ASCII space remains allowed. No truncation/normalization. Synthetic str subclass exercises defensive UnicodeError catch; ordinary lone surrogates fail category-C first. |
| `CompactTokenFormatter.format`, `_format_one_decimal`, footer delegates | `test_token_format.py::test_exact_half_up_boundaries`, `test_footer_delegates_to_shared_formatter`, `test_footer_decimal_delegate`; P `test_projector_formatter_thresholds` | Existing suite proves all arithmetic bands/half-up boundaries; new test proves actual projector uses the same nine prescribed threshold outputs. No duplicate arithmetic owner. |
| Snapshot state/reason/duplicate-key/private-field validation | P `test_fixed_block_reasons`; E `test_snapshot_has_no_private_policy`; `herdr/test_daos.py::test_session_attention_contract`, `test_lifecycle_acknowledgement`, `test_publication_and_reference` | Four fixed reasons, blocked requires reason/nonblocked forbids it; no arbitrary message field. |
| Private DAO repr/error boundary | `herdr/test_daos.py::test_private_restore_is_recursive_and_closed`, `test_private_validation_never_exposes_input`, `test_all_schema_fields_documented_and_nested_private_carriers`; P wire test | Private publication/save repr does not expose capture. Private serializers are intentionally not claimed safe public channels. |
| Projection → publish → save → claim/install/display → actual transport `_spawn`/`_collect_result`/`_failure` → diagnostic → sequence files | P `test_four_provider_wire_privacy[compact/detail × ANTHROPIC/OPENAI/KIMI_FOR_CODING/OPENROUTER]` | Eight actual-child cases, distinct synthetic sentinels in model/reasoning/effort, private path fields, provider env and failing stdout/stderr. Child asserts environment excludes sentinel. Restore install acknowledgement proves execution reached real child; metadata rejection proves failed output path. Actual argv includes opaque restore reference, no history path; public snapshot/repr/log/sequence scans are clean and sequence files must exist. |
| Strict no credential access | Same eight wire cases | Resolver `resolve`/`require` and store `load` fail if called, with explicit assert_not_called so caught failures cannot produce a false pass. Existing projector has no name/provider-label input. |
| Transport bounded successful private output / failure disposal | `herdr/test_cli_transport.py::test_bounded_reader`, `test_collect_result`, `test_registered_spawn_is_real_and_environment_is_allowlisted`; `test_transport_read_failures.py` | Successful bounded JSON is intentionally private parser input; not a public event. New reporting wire test uses DEVNULL for lifecycle/metadata, not a pretend mocked subprocess proof. |
| Lifecycle/metadata/resume builders and payload guard | `herdr/test_reporter.py::test_lifecycle_commands`, `test_metadata_payload`, `test_bootstrap_batch`, `test_report_steps`; `herdr/test_resume_bounds.py`; P wire test | Existing exact builder/limits tests retained, not duplicated by counting helper invocations. Diagnostic episode and lifetime matrix belong to parallel owners. |

## Evidence and safety

CWD `/root/Code/slo-94-herdr-integration/slo`. `pyenv which python` = `/root/.pyenv/versions/slo-harness/bin/python`; Python 3.11.7; `make test-env` = `fallback`. Every pytest command below uses `bash docs/implementation/94-herdr/t1-dao-check.sh` (reviewed Make fallback, default HERDR disabled, pre-import/per-test stripping, fake-only spawn guard, no development environment). That helper adds DAO/projection tests. No provider/network/live Herdr/terminal windows/system links or system writes. Fixture executable is a new regular temp file; no installed command was replaced.

Each prefix below has `.log` and `.exit` siblings in this directory:

| Prefix | Command suffix / result |
|---|---|
| `t2-34-privacy-unit1` | `tests/agents/slo_agent/herdr/test_privacy_closure.py tests/agents/slo_agent/test_token_format.py`: 117 passed, exit 0 |
| `t2-34-privacy-unit2` | same: 133 passed, exit 0 |
| `t2-34-privacy-wire` | `tests/agents/slo_agent/herdr/test_privacy_closure.py`: 121 passed, exit 0 |
| `t2-34-privacy-unit4` | same: 133 passed, exit 0 |
| `t2-34-privacy-focused` | privacy file + `tests/agents/slo_agent/test_token_format.py tests/tui/test_usage_status_bar.py`: **179 passed, 3 warnings**, exit 0 |
| `t2-34-privacy-package` | `tests/agents/slo_agent/herdr tests/agents/slo_agent/test_token_format.py tests/tui/test_usage_status_bar.py`: 2 failed, 654 passed, exit 1 |
| `t2-34-privacy-package-final` | same after final test additions/format: **2 failed, 659 passed, 5 warnings**, exit 1 |
| `t2-34-privacy-black` | `poetry run black --check tests/agents/slo_agent/herdr/test_privacy_closure.py`: unchanged, exit 0 |
| `t2-34-privacy-diff` | `git diff --check`: silent, exit 0 |
| `t2-34-privacy-coreutils` | `dpkg -V coreutils`: silent, exit 0 after stubs |

Full make test/smoke/lint/chapter integration gates deliberately not rerun per assignment. Historical lint baseline 301 errors/64 files remains unwaived, not green. Package logs represent a concurrent shared worktree snapshot, not an immutable final integration freeze.

## Concrete cross-lane defect / handoff

Both package runs fail only the concurrently added `test_diagnostic_closure.py::test_reporter_cancelled_accounting_does_not_change_episode[False/True]`. Actual assertion: `caplog.messages == before` fails because `herdr_publication_failed` is added for cancelled accounting. With no prior episode actual is `['herdr_publication_failed']`, expected `[]`; with an existing restore episode it adds that same extra message. Full output retained above. This is reporter diagnostic policy, owned by another lane; no edit made here. Parent must reconcile that correction and rerun the package before claiming T2 READY.

## Explicit limits

- This lane proves existing adapter inputs/outputs, not actual session prompt/tool/error event publication, rename, credential rotation hooks, disabled session capture, history/headless/plugin event exclusion or T5 assembly. Those require the future real-session/Faux/mounted flows and cannot be certified by calling the projector directly.
- No human session-name/provider-label parameter exists on the projector; free-text model/effort and unknown reasoning are tested. No new name field or redactor was invented merely to test omitted data.
- Private capture never enters argv/logs/public snapshot in the tested adapter flow. No adapter event stream exists here to inspect. T5/T6 must prove capture never enters session/history/plugin events.
- Actual fake executable proves Slo argv/environment/pipe behavior only, **not Herdr release interoperability**, remote TTL/clear acceptance or native restart/restore.
- No production privacy defect was observed within this lane. The helper ledger is behavioral/source evidence, not a branch-coverage percentage claim.

## Context consumed

Actual supplied AGENTS/CLAUDE/docs RESEARCH plus root RESEARCH; frozen routing/scope-plan/t2-33-closure/t2-code-test; full current B including section 8 and exact T1/T2 task samples 286–1905. Relevant C capture/restore/publication/privacy/test contracts and D section 8/acceptance were consulted, along with accepted turn-4 independent review and finalization receipt. Initial oversized reads were followed with bounded B/task/skill reads; no claim to full unrelated C/D implementation review. KB Welcome and actual Slo README/gotchas consulted read-only.

Selected checkout skills: engineering routing/testing/ownership, coding-rules/code-test-loop/shared declarative, Python conventions/DAO build-domain/declarative/type-hints/docstrings, exact Code-Test-Review workflow and shared workflow skill. Pure Python/Pydantic and adapter integration categories only; no database/web framework invented. Scope/routing contracts govern ownership. No shared status, KB, specifications, other worktree or global file was changed.
