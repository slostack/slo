# Dispatch 14 — bounded regression repair

**READY for Step 1 handoff only. Not feature/workflow completion.** All four finite regression groups are repaired; full exact default gate and static/integrity gates pass, with no waiver, exclusion or approved deferral. Independent final review and completion remain mandatory and have not run here.

Turn1 started1/completed0/partial1; dispatch14/20; zero execution retries; max60turns. Requested worker gpt-6.1-sol/medium (no runtime attestation); later independent reviewers gpt-6-astra/medium. No agents/workflows, commit/push/merge/PR, packages, host settings, harness expansion, README/SLO/user docs or original spec edits.

## Scope and authority

Only original `/root/Code/specifications/projects/slo/specifications/96-agent-message-queue/revised/01-durable-composer/`, checkout `/root/Code/slo-message-queue/slo`, branch `message-queue`. Read current routing/handoff/ledger, dispatch13 report and failure tracebacks, original DC01 activation prerequisites, DC03 application-only identity, DC07 finite/observer semantics and DC09 cutover/invariant/full-gate obligations. Existing dispatch12 original-row reconciliation and dispatch5–11 detailed maps remain authoritative evidence references, not replaced by totals.

Project README/SLO/Makefile/manifest and KB Welcome → slo README/gotchas/environment consulted. RESEARCH absent; preserve explicit routing prohibition against recreating it. Installed S=`/root/.local/share/pipx/venvs/slo/lib/python3.11/site-packages/skills`: exact Code-Test-Review workflow, shared routing/testing/ownership, coding rules/design/naming/declarative/testing/cadence and Python root/style/application/testing and Textual recipes applied. Existing Python/asyncio/SQLite/filesystem/Textual/CLI boundaries; no new framework or infrastructure. Existing tests are real persisted journeys with external model substitutes; syscall safety harness is unchanged.

Plan: reproduce current four groups → expose masked errors → bounded production/seam fixes → affected suites → exact complete Make gate → static/integrity → compact handoff. No deadlines increased.

## Failure nodes, causes, corrections and equivalent assertions

### F1 — managed child (13 original nodes)

File `tests/agents/slo_agent/orchestrator/test_managed_launch_reasoning.py`:

- `test_managed_child_cli_completes_registered_lifecycle`
- `test_managed_phase_medium_is_independent_of_high_parent`
- `test_managed_child_applies_real_model_clamping[gpt-5.4-high-high/kimi-k3-medium-high/kimi-for-coding-high-off]`
- `test_managed_direct_failures_keep_distinct_lifecycle[unknown-managed-model/kimi-for-coding]`
- `test_managed_openrouter_preparation_failure_is_child_owned`
- `test_managed_snapshot_and_explicit_precedence_over_saved_preference[None-low/off-off/high-high]`
- `test_managed_legacy_no_flag_uses_child_preference_or_seed[medium-medium/None-high]`

Constructor recorder did not accept production's `messaging_enabled`. Updated exact interface, assert flag is True and forward it unchanged. Runner-count failure now includes actual CLI exit/output/exception instead of concealing it. All model/reasoning/status/notification/pool-cleanup assertions retained.

That repair exposed a real Kimi missing-credential failure: `recovery_required` instead of the exact credential error. Session readiness fails before the first queue application, leaving the public invocation observer unassigned; generic scheduler failure woke it with recovery_required and incorrectly labeled storage corrupt. Production correction below restores the original exception and one terminal, preserving exact original Kimi error/lifecycle assertions.

### F2 — real two-process restore (4 original nodes)

`tests/integration/test_herdr_two_process_restore.py::test_native_restore_in_independent_processes[model_changed-single/model_changed-pool/refused-single/refused-pool]`.

Two actual failures, not a slow provider:

1. Startup execution ownership walks descriptor-relative ancestors but attempted `mkdir` on every existing ancestor, including `/root`, before catching FileExistsError. The existing process safety boundary correctly refuses that mutation outside the owned root. `_open_directory` now opens existing ancestors read-only/no-follow first and creates only missing components. No safety bypass or harness modification. Existing no-follow, hardlink, inode/UID validation and lease cleanup preserved. Diagnostic helper now rethrows startup task error immediately and asserts default composition/readiness before attempting refusal.
2. Once startup works, pre-provider backend/credential validation raises ValueError before an application assigns an observer. Scheduler now handles this narrowly only while no agent exists and no delivery was selected: set reporting attention, pause, retain pending input **before waking observers**, publish one redacted failure, preserve original exception for waiting publishers. Storage stays healthy; no provider or automatic retry. Post-agent/application ValueError still settles assigned observers with original error then follows existing failure behavior. The first affected run caught a missing settlement on this latter branch (two timeout regressions); fixed and rerun green. No timeout widened.

Restore helper and parent retain all exact policy/config/argv/record/history/no-provider/no-replay/error-paint/redaction assertions. Original optimistic legacy echo of the refused capability probe is incompatible with DC03's application-only echo: now assert only saved applied prompts are visible, **plus exact refused input in real retained SQLite selection**, no extra page, paused consumer and healthy storage. No fake user application/history event is manufactured for refused text. Credential refusal remains the actual ValueError, not a generic offline/recovery acceptance.

### F3 — removed candidate navigation (1 original node)

`tests/tui/test_chat_transcript_navigation.py::test_removed_reading_candidate_uses_clamped_numeric_fallback`.

Current serial RED-group run passed this node; dispatch13's actual failure shows numeric clamp passing while bottom SECOND-099 painted. The test issued programmatic y=40 while initial tree-output follow-pin callbacks could still be pending. Its saved_y assertion did not prove the intended starting row; a late initial pin could save a bottom value, making the later numeric assertion vacuous. Test now waits for initial animations/follow pin to settle within a bounded5s, then requires **saved_y == 40** before arming removal/settlement. Original numeric clamp, forbidden bottom paint, and completed navigation assertions remain. No production navigation change or deadline enlargement. This is a strengthened setup/order correction supported by full parallel green evidence, not a claimed isolated pre-fix failure reproduced here or a baseline waiver.

### F4 — registration atomicity (1 original node)

`tests/tui/test_herdr_prompt_registration.py::test_prompt_registration_shutdown_atomic_commit`.

Required DC09 invariant guard adds a fifth statement. AST assertion now requires exact messaging predicate, one exact RuntimeError raise and no else, then original shutdown predicate→create/assign→return tail and no await/yield anywhere. Existing mounted cutoff cases retained and passing. Exact five-statement shape is still enforced, not removed.

## Exact verification receipts

All commands run app root with `set -o pipefail`; direct stdout/stderr log redirection and immediate `$?` to same-stem `.exit` files, no tee status loss. Interpreter prefix for every Poetry/Make command:

```sh
export VIRTUAL_ENV=/root/.pyenv/versions/slo-harness
export PATH=/root/.pyenv/versions/slo-harness/bin:$PATH
```

Focused/collection additionally use unchanged routing synthetic exports: `SLO_ENV=test SLO_ROOT_DIR=$PWD SLO_APP_DIR=$PWD SLO_APP_NAME=slo SLO_LOG_FORMAT=text SLO_DEFAULT_MODEL_NAME=gpt-5.4 SLO_AUTO_VISUALIZE=0 SLO_HERDR_DISABLED=1 SLO_ANTHROPIC_API_KEY=ci-placeholder-tests-are-fully-mocked COLUMNS=120 LINES=40 PYTHONPATH=$PWD`. Full Make uses its own unchanged fallback recipe. No development env or real provider.

Common focused suffix `-m 'not e2e' -q`; parallel commands add `-n 6`.

| Log stem (`logs/`) | Exact selection/command | Status/counts |
|---|---|---|
| dispatch14-current-red | `poetry run pytest tests/agents/slo_agent/orchestrator/test_managed_launch_reasoning.py tests/integration/test_herdr_two_process_restore.py tests/tui/test_chat_transcript_navigation.py::test_removed_reading_candidate_uses_clamped_numeric_fallback tests/tui/test_herdr_prompt_registration.py::test_prompt_registration_shutdown_atomic_commit` + suffix | exit1;18failed/14passed/35warnings;96.42s (navigation passed currently) |
| dispatch14-seams-green | managed-launch file + full prompt-registration file + suffix | exit1;1failed/45passed/56warnings;18.82s; exposed exact Kimi error mismatch |
| dispatch14-restore-diagnosis | restore `[refused-single] -q` | exit1;1failed/2warnings;7.93s; startup storage refusal |
| dispatch14-restore-startup | restore `[refused-single] [model_changed-single] -q` | exit1;2failed/2warnings;14.38s; startup fixed, real readiness errors exposed |
| dispatch14-three-groups | managed-launch + restore + registration files + suffix | exit1;2failed/53passed/56warnings;83.29s; missing terminal attention |
| dispatch14-restore-navigation | restore + full navigation files + parallel suffix | exit1;2failed/113passed/14warnings;30.07s; legacy optimistic-echo assertion |
| dispatch14-four-groups-green | managed-launch + restore + navigation + registration files + parallel suffix | exit1;2failed/159passed/68warnings;42.36s; observed pause/retain-before-wake ordering race |
| dispatch14-four-groups-final | same four full files + parallel suffix | exit0;161passed/68warnings;41.81s |
| dispatch14-affected | selection below + parallel suffix | exit1;2failed/2761passed/482warnings;117.02s; post-agent ValueError observer settlement omitted |
| dispatch14-affected-final | same selection + parallel suffix | **exit0;2763passed/484warnings;112.23s** |
| dispatch14-full-test | **`make test PYTEST_WORKERS=6`** | **exit0;12265passed/0failed/1266warnings;527.56s**,0reported skips;2026-11-03T06:42:24Z–06:51:13Z |
| dispatch14-black-initial | `poetry run black --check "${paths[@]}"` | exit0;**57 cumulative changed/untracked Python files** unchanged; exact list dispatch14-black-paths.txt; no formatting required |
| dispatch14-lint | `make lint` | exit0;980sourcefiles clean |
| dispatch14-integrity | `git diff --check`; `dpkg -V coreutils`; `make test-env` | all exit0; first two no output; fallback |
| dispatch14-collection | `poetry run pytest --collect-only -q -m 'not e2e'` | exit0;12265/12286collected;21deselected;2warnings;4.08s |

Affected selection exactly: `tests/agents/slo_agent/messaging/ tests/agents/slo_agent/orchestrator/ tests/cli/ tests/tui/test_chat_transcript*.py tests/tui/test_composer_prerequisites.py tests/tui/test_messaging_failure_matrix.py tests/tui/test_herdr_prompt_registration.py tests/tui/test_herdr_all_owner_cutoffs.py tests/integration/test_herdr_two_process_restore.py` (shell expands transcript glob). No chunks replace the full gate. Full xdist output does not print deselections; separate collection gives21 project e2e deselections. Warnings remain in logs (deprecations and existing unawaited AsyncMock warnings); no warning-free claim.

Black path list is sorted union of `git diff --name-only --relative -- 'src/**/*.py' 'tests/**/*.py'` and `git ls-files --others --exclude-standard -- 'src/**/*.py' 'tests/**/*.py'`. Source/test diff inspected, especially error classification, no-follow behavior and all modified assertion oracles. This is author self-check, not independent review.

## Original acceptance/gate disposition

| Original IDs | Current evidence |
|---|---|
| DC01.A1–A8 | Prior dispatch4/12 real injected/mounted/lease/cleanup journeys retained; full suite green; additional default restore startup/credential boundary now green. |
| DC02.A1–A12 | Prior composer/prerequisite/adapter/protocol/draft/capacity/eager/literal maps unchanged; all included in full green gate. |
| DC03.A1–A11 | Prior observation/history/identity/recall/compaction maps unchanged; whole navigation suite green; refusal oracle explicitly conforms to verified-application echo. |
| DC04.A1–A8 | Prior retirement/cancellation/handoff maps unchanged; full green gate. |
| DC05.A1–A9 | Prior persisted recovery/consent/slash maps unchanged; exact newly refused input retained with no automatic provider. Full green gate. |
| DC06.A1–A7 | Prior controls/new/clear/abort maps unchanged; original atomic registration plus required invariant and mounted cutoffs green. |
| DC07.A1–A11 | Prior finite/headless/steer maps unchanged; all managed-child reasoning/lifecycle cases now pass through real new root. Post-application original exception and final observer outcome assertions retained. Dispatch12 A4/A8 complementary evidence rationale remains for independent adequacy assessment; not a new unproved combined crash-window claim. |
| DC08.A1–A11 + §5.6 | Prior bridge/displacement/provenance maps unchanged; included in full green gate. Dispatch12 same-gateway boundaries remain precisely documented, not expanded by counts. |
| DC09.A1–A5 | Prior full visual/failure/default-root/rollback maps unchanged; extra real restore and managed roots now green. |
| DC09.A6 / required gates | Full12265pass, lint980, Black57, diff/coreutils clean; no baseline waiver or unresolved execution blocker. |

## Changed files this dispatch and remaining phases

Production: `src/agents/slo_agent/messaging/ownership.py`, `src/agents/slo_agent/sessions/service.py`.
Tests: `tests/agents/slo_agent/orchestrator/test_managed_launch_reasoning.py`, `tests/integration/herdr_restore_process_entry.py`, `tests/integration/test_herdr_two_process_restore.py`, `tests/tui/test_chat_transcript_navigation.py`, `tests/tui/test_herdr_prompt_registration.py`.
Evidence: this report, compact handoff/routing/ledger, logs above. Existing prior changes and user-owned documents preserved.

**Remaining finite list:** independent final review against all original A rows, especially the retained-vs-echo oracle and existing DC07/DC08 complementary evidence; then independent completion check. No implementation/gate blocker remains known. READY is Step1 author handoff only, not final acceptance, merge readiness or a completed workflow turn.
