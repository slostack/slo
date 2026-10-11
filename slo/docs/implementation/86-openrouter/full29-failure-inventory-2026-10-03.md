# Feature 86 — retained 29-failure inventory and Step 1 correction

**Scope:** Code-Test-Review workflow Step 1 corrective implementation/test work.
**Retained red gate:** `.f86-final-gate-50zGsO/full-non-e2e.log`.
**Fresh green gate:** `.f86-step1-full-XyirL9/full-non-e2e.log`.

## Exact retained failure accounting

The retained full non-E2E gate reported **29 failed, 5036 passed, 15 deselected,
196 warnings in 357.66s**. The 15 deselections are only the standard `e2e` marker.
Every failed node follows; there is no blanket environment attribution.

| # | Retained failed node(s) | Count | Actual cause | Owner | Correction / green evidence |
|---:|---|---:|---|---|---|
| 1 | `tests/agents/model_catalog/test_catalog_integrity.py::test_offline_admission_rejects_invalid_routes[changes0]` through `[changes8]` | 9 | The earlier full gate ran before the catalog error included the requested exact route. It emitted only the required variant guidance, so existing assertions could not match `openrouter:vendor/unseeded:free`. | Catalog integration wording: `src/agents/model_catalog/service.py`; catalog test contract. | Pre-existing source correction now preserves the exact route plus `unsupported variant; choose a catalog entry or /model refresh`. Fresh catalog partition: **22 passed, 2 warnings**. |
| 2 | `tests/agents/model_catalog/test_catalog_read_views.py::test_offline_prepare_validates_exact_routes_without_fallback_or_io` | 1 | Same pre-correction message compatibility failure for `openrouter:vendor/unknown:free`. | Catalog integration wording/test contract. | Same catalog source correction and **22-passing** partition. |
| 3 | `tests/agents/slo_agent/orchestrator/test_capture_contained_lifetime.py::test_production_capture_opener_uses_exact_isolated_entry_without_spawn` | 1 | The test assumed `append_lock_fd == descriptors[0] - 1`. The writer-lifetime lease transfer adds an inherited descriptor, so allocation number is intentionally not stable. | Capture test contract; production lease wiring was correct. | Test now asserts the inherited descriptor resolves to the expected `.append.lock`, is forwarded in both environment and `pass_fds`, is distinct from pipe FDs, and existing cleanup checks remain. Capture module: **38 passed, 2 warnings**. |
| 4 | `tests/agents/slo_agent/plugins/test_loader.py::TestDiscoveryOrdering::test_discovery_order_is_managed_project_cli` | 1 | Invocation environment set `SLO_PLUGINS_DISABLED=1`; test-local plugin candidates were deliberately bypassed. | Test harness environment/fixture, not plugin production loader. | Suite fixture removes only this kill switch under `monkeypatch`; existing test-owned managed/project/CLI roots remain explicit. |
| 5 | `tests/agents/slo_agent/plugins/test_loader.py::TestFactoryInvocation::test_sync_factory_registers_handlers_and_status` | 1 | Same kill switch bypassed CLI fixture loading. | Test harness fixture. | Same isolated-HOME plugin partition: **24 passed, 5 warnings**. |
| 6 | `tests/agents/slo_agent/plugins/test_loader.py::TestFactoryInvocation::test_async_factory_is_awaited` | 1 | Same kill switch bypassed CLI fixture loading. | Test harness fixture. | Same partition. |
| 7 | `tests/agents/slo_agent/plugins/test_loader.py::TestFactoryInvocation::test_raising_factory_yields_load_failed_and_other_plugins_load` | 1 | Same kill switch bypassed both test-local CLI fixtures. | Test harness fixture. | Same partition; positive successful registration and isolated load-failure assertions execute. |
| 8 | `tests/agents/slo_agent/plugins/test_loader.py::TestFactoryInvocation::test_module_without_register_yields_load_failed` | 1 | Same kill switch bypassed CLI fixture loading. | Test harness fixture. | Same partition. |
| 9 | `tests/agents/slo_agent/plugins/test_loader.py::TestFactoryInvocation::test_syntax_error_file_yields_load_failed` | 1 | Same kill switch bypassed CLI fixture loading. | Test harness fixture. | Same partition. |
| 10 | `tests/agents/slo_agent/plugins/test_loader.py::TestFactoryInvocation::test_missing_cli_file_yields_load_failed` | 1 | Same kill switch bypassed the intentionally missing CLI candidate, so no `LOAD_FAILED` record was produced. | Test harness fixture. | Same partition. |
| 11 | `tests/agents/slo_agent/plugins/test_loader.py::TestManagedTierImportIdentity::test_managed_plugin_imports_under_unique_module_name` | 1 | Same kill switch bypassed the pytest-owned managed fixture root. | Test harness fixture. | Same partition; positive module registration/import identity executes. |
| 12 | `tests/agents/slo_agent/plugins/test_loader.py::TestManagedTierImportIdentity::test_managed_plugin_with_invalid_manifest_yields_load_failed` | 1 | Same kill switch bypassed the pytest-owned malformed managed fixture. | Test harness fixture. | Same partition. |
| 13 | `tests/agents/slo_agent/plugins/test_loader.py::TestManagedTierImportIdentity::test_two_plugins_never_clobber_sys_modules` | 1 | Same kill switch bypassed both pytest-owned managed fixtures. | Test harness fixture. | Same partition. |
| 14 | `tests/agents/slo_agent/plugins/test_session_wiring_e2e.py::test_session_loads_real_plugin_tool_and_fires_handler` | 1 | Same kill switch prevented explicit CLI fixture plugin registration, hence no module/tool/handler. | Test harness fixture. | Same partition; positive tool and event-handler registration runs. |
| 15 | `tests/agents/slo_agent/plugins/test_session_wiring_e2e.py::test_second_raising_plugin_does_not_fail_session` | 1 | Same kill switch prevented both explicit fixture plugins from loading. | Test harness fixture. | Same partition. |
| 16 | `tests/agents/slo_agent/plugins/test_session_wiring_e2e.py::test_injected_before_agent_turn_messages_reach_next_llm_call` | 1 | Same kill switch prevented the injected test-local plugin from registering. | Test harness fixture. | Same partition; positive injected-message behavior runs. |
| 17 | `tests/tui/test_plugin_command_runtime.py::test_plugin_command_is_registered_and_invokes_its_handler` | 1 | Same kill switch prevented explicit plugin command registration. | Test harness fixture. | Same partition. |
| 18 | `tests/tui/test_plugin_command_runtime.py::test_plugin_command_colliding_with_builtin_is_refused_and_plugins_still_work` | 1 | Same kill switch prevented the collision fixture from producing a health record. | Test harness fixture. | Same partition. |
| 19 | `tests/tui/test_plugins_slash_command.py::test_plugins_lists_health_lines` | 1 | Same kill switch prevented explicit fixture plugin loading. | Test harness fixture. | Same partition. |
| 20 | `tests/tui/test_plugins_slash_command.py::test_plugins_reload_drops_registrations_of_removed_plugin` | 1 | Same kill switch prevented the initial fixture registration. | Test harness fixture. | Same partition. |
| 21 | `tests/tui/test_plugins_slash_command.py::test_plugins_trust_records_project_and_reloads` | 1 | Same kill switch prevented trusted pytest-owned project fixture discovery. | Test harness fixture. | Same partition. |

## Correction boundaries

- `tests/conftest.py::_enable_test_local_plugins` removes only
  `SLO_PLUGINS_DISABLED` during each test. `monkeypatch` restores the original
  process environment. Production kill-switch behavior remains covered by its
  explicit tests, which set the value after fixture setup.
- Plugin tests construct synthetic regular Python files only below their pytest
  `tmp_path` / `--basetemp` roots and pass them explicitly as managed, project, or
  CLI candidates. No operator-home plugin or credential path is read.
- The capture test does not weaken descriptor containment or leak assertions; it
  replaces a non-contractual allocation-number assertion with actual descriptor
  identity and wiring assertions.

## Fresh complete verification

```bash
timeout 1200 env -i \
  PATH=/root/.pyenv/versions/slo-harness/bin:/usr/bin:/bin \
  VIRTUAL_ENV=/root/.pyenv/versions/slo-harness \
  HOME=.f86-step1-full-XyirL9/home TMPDIR=.f86-step1-full-XyirL9/tmp \
  SLO_HOME=.f86-step1-full-XyirL9/home/.slo \
  SLO_AUTH_FILE=.f86-step1-full-XyirL9/home/auth.json \
  SLO_ENV=test SLO_AUTO_VISUALIZE=0 SLO_PLUGINS_DISABLED=1 \
  PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD" \
  /root/.pyenv/versions/slo-harness/bin/python -B -m pytest -q \
  -m 'not e2e' -p no:cacheprovider \
  --basetemp=.f86-step1-full-XyirL9/tests tests --tb=short
```

Result: **exit 0 — 5065 passed, 15 deselected, 202 warnings in 352.33s**.
The log is complete and owned under `.f86-step1-full-XyirL9/full-non-e2e.log`.
