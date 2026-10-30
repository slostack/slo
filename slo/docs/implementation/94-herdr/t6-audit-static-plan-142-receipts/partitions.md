## A-projector: 81 diagnostics / 4 files

- `src/tui/transcript_projector.py`: 1; arg-type=1
- `tests/tui/test_recovery_ux.py`: 5; arg-type=5
- `tests/tui/test_tool_block_partial.py`: 9; arg-type=4, attr-defined=5
- `tests/tui/test_transcript_projector.py`: 66; arg-type=64, dict-item=2

Read-only check after each increment:
```sh
PYENV_VERSION=slo-harness poetry run mypy --follow-imports=silent src/tui/transcript_projector.py tests/tui/test_recovery_ux.py tests/tui/test_tool_block_partial.py tests/tui/test_transcript_projector.py
```

## B-fixtures: 53 diagnostics / 5 files

- `tests/agents/slo_agent/compaction/test_compacted_session_updater.py`: 27; arg-type=27
- `tests/auth/providers/test_openai_codex_device_authorization.py`: 2; attr-defined=2
- `tests/auth/test_oauth_flow.py`: 6; arg-type=3, union-attr=3
- `tests/tui/authentication/test_auth_screen.py`: 15; arg-type=4, assignment=4, call-arg=6, misc=1
- `tests/tui/authentication/test_authentication_headless_e2e.py`: 3; arg-type=1, attr-defined=2

Read-only check after each increment:
```sh
PYENV_VERSION=slo-harness poetry run mypy --follow-imports=silent tests/agents/slo_agent/compaction/test_compacted_session_updater.py tests/auth/providers/test_openai_codex_device_authorization.py tests/auth/test_oauth_flow.py tests/tui/authentication/test_auth_screen.py tests/tui/authentication/test_authentication_headless_e2e.py
```

## C-provider: 45 diagnostics / 11 files

- `src/agents/providers/anthropic_claude_code.py`: 1; attr-defined=1
- `src/agents/providers/faux.py`: 3; call-arg=2, override=1
- `src/agents/providers/openai_codex.py`: 2; arg-type=1, call-arg=1
- `src/agents/slo_agent/assistant_chunk_normalizer.py`: 1; misc=1
- `tests/agents/providers/test_anthropic_claude_code.py`: 4; assignment=3, index=1
- `tests/agents/providers/test_anthropic_reasoning.py`: 1; assignment=1
- `tests/agents/providers/test_credit_exhaustion_policy.py`: 4; assignment=1, attr-defined=1, method-assign=1, misc=1
- `tests/agents/providers/test_faux.py`: 5; arg-type=3, attr-defined=2
- `tests/agents/providers/test_openrouter_nonstream_boundary.py`: 1; index=1
- `tests/agents/providers/test_pool_fallback_integration.py`: 9; arg-type=5, attr-defined=1, method-assign=3
- `tests/agents/test_base.py`: 14; assignment=2, attr-defined=12

Read-only check after each increment:
```sh
PYENV_VERSION=slo-harness poetry run mypy --follow-imports=silent src/agents/providers/anthropic_claude_code.py src/agents/providers/faux.py src/agents/providers/openai_codex.py src/agents/slo_agent/assistant_chunk_normalizer.py tests/agents/providers/test_anthropic_claude_code.py tests/agents/providers/test_anthropic_reasoning.py tests/agents/providers/test_credit_exhaustion_policy.py tests/agents/providers/test_faux.py tests/agents/providers/test_openrouter_nonstream_boundary.py tests/agents/providers/test_pool_fallback_integration.py tests/agents/test_base.py
```

## D-local-types: 101 diagnostics / 37 files

- `src/agents/skills/registry.py`: 1; arg-type=1
- `tests/agents/model_catalog/test_model_catalog_store.py`: 1; attr-defined=1
- `tests/agents/model_catalog/test_openrouter_admission_security.py`: 2; arg-type=2
- `tests/agents/model_catalog/test_openrouter_budget_evidence.py`: 1; union-attr=1
- `tests/agents/model_catalog/test_openrouter_final_read_race.py`: 1; arg-type=1
- `tests/agents/model_catalog/test_openrouter_real_store_recovery.py`: 2; arg-type=1, var-annotated=1
- `tests/agents/skills/test_orchestrator_limit_rules.py`: 1; arg-type=1
- `tests/agents/slo_agent/history/test_projector.py`: 1; misc=1
- `tests/agents/slo_agent/history/test_projector_compaction.py`: 3; union-attr=3
- `tests/agents/slo_agent/history/test_tree_builder.py`: 1; union-attr=1
- `tests/agents/slo_agent/orchestrator/test_capture_contained_lifetime.py`: 1; attr-defined=1
- `tests/agents/slo_agent/orchestrator/test_default_orchestrator_prompt.py`: 3; union-attr=3
- `tests/agents/slo_agent/orchestrator/test_pool.py`: 2; method-assign=2
- `tests/agents/slo_agent/orchestrator/test_relaunch.py`: 1; arg-type=1
- `tests/agents/slo_agent/orchestrator/test_spawn_tool.py`: 6; assignment=1, operator=1, union-attr=4
- `tests/agents/slo_agent/orchestrator/test_spawn_tool_schema.py`: 6; union-attr=6
- `tests/agents/slo_agent/orchestrator/test_workflow_routing_e2e.py`: 3; union-attr=3
- `tests/agents/slo_agent/test_agent_image_history.py`: 1; index=1
- `tests/agents/slo_agent/test_agent_recovery.py`: 3; call-arg=3
- `tests/agents/slo_agent/test_agent_runtime_event.py`: 1; valid-type=1
- `tests/agents/slo_agent/test_cache_control.py`: 2; assignment=2
- `tests/agents/slo_agent/test_pending_direct_recovery.py`: 1; union-attr=1
- `tests/agents/slo_agent/test_pool_fallback_e2e.py`: 2; name-defined=1, return-value=1
- `tests/agents/slo_agent/test_refresh_catalog_notice.py`: 1; arg-type=1
- `tests/agents/slo_agent/test_session_manual_compaction.py`: 5; method-assign=4, union-attr=1
- `tests/agents/slo_agent/tool_execution/test_executors.py`: 3; index=3
- `tests/agents/tools/test_read.py`: 2; union-attr=2
- `tests/cli/test_openrouter_terminal_lifetime.py`: 2; arg-type=2
- `tests/integrations/openrouter/test_harness_contract.py`: 8; arg-type=8
- `tests/integrations/openrouter/test_live_openrouter.py`: 2; attr-defined=2
- `tests/tui/selection_observer.py`: 1; union-attr=1
- `tests/tui/slodiff/test_view.py`: 5; union-attr=5
- `tests/tui/test_openrouter_picker.py`: 1; union-attr=1
- `tests/tui/test_plugins_slash_command.py`: 6; operator=4, union-attr=2
- `tests/tui/test_selection_copy.py`: 13; arg-type=2, assignment=5, attr-defined=4, union-attr=2
- `tests/tui/test_startup_notice.py`: 1; union-attr=1
- `tests/tui/test_user_message_block.py`: 5; union-attr=5

Read-only check after each increment:
```sh
PYENV_VERSION=slo-harness poetry run mypy --follow-imports=silent src/agents/skills/registry.py tests/agents/model_catalog/test_model_catalog_store.py tests/agents/model_catalog/test_openrouter_admission_security.py tests/agents/model_catalog/test_openrouter_budget_evidence.py tests/agents/model_catalog/test_openrouter_final_read_race.py tests/agents/model_catalog/test_openrouter_real_store_recovery.py tests/agents/skills/test_orchestrator_limit_rules.py tests/agents/slo_agent/history/test_projector.py tests/agents/slo_agent/history/test_projector_compaction.py tests/agents/slo_agent/history/test_tree_builder.py tests/agents/slo_agent/orchestrator/test_capture_contained_lifetime.py tests/agents/slo_agent/orchestrator/test_default_orchestrator_prompt.py tests/agents/slo_agent/orchestrator/test_pool.py tests/agents/slo_agent/orchestrator/test_relaunch.py tests/agents/slo_agent/orchestrator/test_spawn_tool.py tests/agents/slo_agent/orchestrator/test_spawn_tool_schema.py tests/agents/slo_agent/orchestrator/test_workflow_routing_e2e.py tests/agents/slo_agent/test_agent_image_history.py tests/agents/slo_agent/test_agent_recovery.py tests/agents/slo_agent/test_agent_runtime_event.py tests/agents/slo_agent/test_cache_control.py tests/agents/slo_agent/test_pending_direct_recovery.py tests/agents/slo_agent/test_pool_fallback_e2e.py tests/agents/slo_agent/test_refresh_catalog_notice.py tests/agents/slo_agent/test_session_manual_compaction.py tests/agents/slo_agent/tool_execution/test_executors.py tests/agents/tools/test_read.py tests/cli/test_openrouter_terminal_lifetime.py tests/integrations/openrouter/test_harness_contract.py tests/integrations/openrouter/test_live_openrouter.py tests/tui/selection_observer.py tests/tui/slodiff/test_view.py tests/tui/test_openrouter_picker.py tests/tui/test_plugins_slash_command.py tests/tui/test_selection_copy.py tests/tui/test_startup_notice.py tests/tui/test_user_message_block.py
```

## E-yaml: 1 diagnostics / 1 files

- `src/agents/slo_agent/skills/service.py`: 1; import-untyped=1

Read-only check after each increment:
```sh
PYENV_VERSION=slo-harness poetry run mypy --follow-imports=silent src/agents/slo_agent/skills/service.py
```
