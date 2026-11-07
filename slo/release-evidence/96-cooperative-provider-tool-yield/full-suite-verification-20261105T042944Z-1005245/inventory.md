# Source selection and permission inventory

Source-only inventory; pytest collection and tests NOT RUN. `source-inventory.stdout` lists actual source class/case names (not collected parameter IDs); `blocker-source.stdout` preserves current line-numbered operation excerpts. No execution totals inferred.

## Default contract

`pyproject.toml:123–129`: tests/, asyncio auto, `-m 'not e2e'`; only registered marker is e2e. Preserve this filter. Default e2e exclusions are distinct from the user's installation exclusions: test_install_smoke.py, test_install_mirror_e2e.py and test_wheel_contents.py are module-marked e2e; test_hosted_installer_smoke.py mixes opt-in e2e cases and offline installation harness/config contracts.

## Proposed user-authorized installation exclusions

Whole cohesive modules (source docstrings, classes and cases inspected, not chosen just by filenames):

- tests/cli/test_install.py — installer toolchain bootstrap, pipx installation, shell finalization and dispatch.
- tests/cli/test_isolated_launcher.py — pipx artifact regeneration/rollback and finalizer-generated installed wrapper.
- tests/cli/test_isolated_launcher_layout.py — installer-owned layout resolver/writer, including old pipx root APIs and template recognition.
- tests/cli/test_isolated_launcher_writer.py — installer-owned launcher replacement/refusal/failure preservation.
- tests/cli/test_install_mirror.py — installer pipx/git mirror retries.
- tests/cli/test_install_smoke_source.py — Docker installer argv/ref forwarding.
- tests/cli/test_release_pipx_bootstrap.py — ACTUAL CI pipx provisioning (not merely mocked CLI behavior); excluded, never executed.
- tests/cli/test_generated_launcher_templates.py — install.sh generated-launcher recognition.
- tests/cli/test_install_documentation.py — installed-launcher lifecycle documentation contracts.
- tests/cli/test_update_mirror.py — updater pipx reinstall and release lookup mirror contracts.
- tests/cli/test_deploy_install_worker.py — installer Worker deployment contract; its curl fixture is consented but user excludes this installation/deployment layer.
- tests/cli/test_hosted_installer_smoke.py — cohesive published installer/direct-pipx recovery harness, including its offline construction/config contracts.

No additional --ignore is necessary for the three wholly e2e modules listed above: existing marker selection already excludes them.

Mixed `tests/cli/test_update.py` was read, NOT ignored wholesale. Proposed class-node deselections: TestPipxSpec, TestResolveLatestReleaseTag, TestUvFallback, TestPythonBin, TestPipxInstall, TestInvoke, TestUpdateLauncherFinalization, TestInvokeEnsuresEnvironmentDefaults, TestInstalledLocation, TestLauncherFinalizer, TestEnsureDecisions, TestStaleSkillsDirWarning, TestEnsureEndToEnd, TestCheckPathAfterInstall. These assert installer/pipx update selection, interpreter/backend, finalization/default installation and post-install PATH contracts. Retain TestMain (argv delegation/conflict handling) and TestMissingEnvironmentDefaults (pure mapping/presence behavior). Class node deselection includes all parameterizations without guessing their IDs.

Mixed `tests/cli/test_release_automation.py`: proposed narrow deselections under TestReleaseAutomation: test_publish_installer_preserves_explicit_tagged_refs; test_gitlab_macos_job_selects_python_311_before_poetry_install; test_linux_release_setup_uses_the_image_python_without_activating_a_disabled_venv; test_gitlab_tag_publication_fetches_the_same_tagged_public_installer_source; test_gitlab_hosted_release_jobs_override_default_e2e_deselection_and_collect_the_smoke; test_gitlab_tag_pipeline_requires_local_wheel_recovery_and_docker_matrix_proofs; test_docker_smoke_contract_consumes_the_assigned_image_and_workspace_path; test_gitlab_hosted_smoke_commands_are_preserved_including_excluded_macos; test_release_installer_smoke_requires_a_version. Retain generic release ordering, CI publication prerequisites, evidence documentation and test-env contract cases. No actual publication authorized.

Mixed tests/test_feature89_release_preparation.py: deselect only test_v0301_release_metadata_preserves_packaging_owned_launchers; retain release-note/version and runner-default checks.

Retain tests/cli/test_declared_dependencies.py (general import/dependency declaration validation), test_chat_transcript_resources.py (CSS archives/import order), tests/config/test_cfg.py (runtime configuration), test_prompts.py (runtime prompt content), plugins/test_installer.py (trusted runtime plugin installation, not pipx/product installation) and orchestrator/test_launch_isolation.py (runtime child isolation). Their textual pipx/install references do NOT justify blanket exclusion. No CLI, scheduling, restore, Herdr, subprocess or runtime-launcher blanket exclusion.

## Required nonexcluded consent blockers, current source

All below are normal tests under tests/, with no e2e/skip gate removing the cited cases. No collection hook in root conftest deselects these. `SLO_HERDR_DISABLED=1` is not a selection filter: fake_herdr explicitly sets it to 0 for synthetic operation. Containment is not consent.

1. tests/conftest.py:186–215 fake_herdr writes new <tmp_path>/fake-herdr and chmod0700 (:206). Capture/barrier0600 are ordinary data and NOT additional blockers. Consumers include tests/tui/test_herdr_activation_composed.py::test_mount_native_save_display_and_new_lease_order and the other listed mounted cases. This module's native_factory:28–34 additionally writes <tmp_path>/slo0700. These are runtime activation/lease tests, not installer tests.
2. tests/scheduling/test_runtime_helpers.py::TestScheduleSubprocessRunner::test_run_fresh_executes_real_wrapper_from_hostile_cwd_and_pythonpath (:207–240) writes <tmp>/venv/bin/slo0755 (:224), executes a persisted runtime wrapper, does NOT install it. test_scheduler_child_drops_inherited_herdr_environment (:275–331, both resume values) writes <tmp>/scheduled-child0700 (:308). Required ordinary scheduling isolation tests.
3. tests/scheduling/test_os_integration.py::TestScheduleExecutableLocator::test_prefers_virtualenv_executable (:251–263) writes <tmp>/bin/slo0755 (:258). Executable location, NOT product installation; retained even though neighboring classes cover schedule OS registration.
4. tests/tui/test_code_validation.py::test_discovered_editor_keeps_process_cwd_and_symlink_spelling (:72–105, bin and colon parameter values) writes <tmp>/discovery[/bin]/editor-wrapper0700 and links nvim to that contained executable (:89–90). The editor is never actually executed; executable creation/link still requires consent. Ordinary source-file symlinks elsewhere in the module are NOT this blocker.
5. tests/integration/test_herdr_two_process_restore.py::test_native_restore_in_independent_processes (:73 onward; single/pool x available/refused/trust_changed/model_changed) calls prepare_restore_process (:44–71), writing <tmp>/slo0700 (:60). Child herdr_restore_process_entry.py::publish (:72–78) writes <root>/fake-herdr0700. Native runtime restore, explicitly not installed/live compatibility.
6. tests/integration/test_herdr_restore_harness_safety.py: parent-path and shim refusal tests call the same prepare_restore_process; shim symlink/substitution/mode cases :141–153 rename/link/rewrite/chmod the contained executable. wrong-named shim :168; registered identity tests :424–428 write dummy/replacement0700 then replace; installed-execution-refusal :478–481 writes an inert contained dummy0700 (its name does NOT make it an installer test). Capture registration/refusal/revalidation/boundary cases :804,847,857–870,912,929 create/chmod/link test executable artifacts; executable-role symlink/hardlink substitutions are contained. Source excerpts preserved. Data-only capture/barrier chmod0400/0600, directory modes, and real child Python/bash execution are NOT independent consent blockers.

Minimal authority needed: allow ONLY these existing nonexcluded fixtures' contained new executable script creation and their executable chmod/replacement/rename/link/refusal-fixture mutations, strictly in verified disposable pytest temp roots, preserving existing guards and child-local PATH behavior. No real installed/system executable writes, symlinks to writable real binaries, package installs, provider calls, publishing or infrastructure changes. Consent to one curl fixture does not cover these operations.

This source establishes a blocker before pytest; no safe subset was run and no further exhaustive safety certification is claimed. Additional sites, if discovered after consent, must still be assessed against its exact scope.
