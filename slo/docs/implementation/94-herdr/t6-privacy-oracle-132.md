# T6 privacy oracle 132 — TEST ORACLE CORRECTION; remaining coverage incomplete

## Disposition and scope

Corrected the unsupported all-ordinary-event credential prohibition to the accepted Herdr publication contract. **No production defect fix is claimed.** Ordinary Slo tool-error credential disclosure remains separately reproduced and unwaived in `security-finding-132.md`. Reports 129–131 remain unchanged; specifically, 131's claim that the original user requested a new stronger global public-stream requirement is unsupported and superseded.

Only `tests/integration/test_herdr_full_flow.py` and these two Markdown reports were changed by this assignment. No source/harness/shared-status/specification/KB/other-worktree edit, agent, commit, push, reset, stash, clean, global change or live action. Two-process HOLD respected: no full make, integration-directory collection or restore-process selection. Same unfinished turn 1: started 1, completed 0, historical partial 1, supplied dispatch 132, retries 0. Effective turns/dispatch budgets unlimited; no new dispatch.

## Authority and routing

Read supplied AGENTS/CLAUDE/docs RESEARCH, root RESEARCH, scope-plan/routing, KB Welcome and slo README/gotchas; selected committed engineering routing/testing/ownership, coding rules/cadence/declarative, Python conventions/Faux/declarative, Textual and workflow SKILL. Initial oversized combined reads were truncated; relevant shared/style files were subsequently read separately. Task is Python composed offline test-oracle correction, not production architecture, provider or CLI work. Existing approved plan remains authoritative. No independent workflow review or full feature completion is claimed.

Plan: confirm canonical contract read-only → correct oracle with independent private-config scan → preserve ordinary disclosure reproduction and enabled/disabled parity → instrument lookup prohibition and rotation → run bounded focus/surrounding/static checks → disclose remaining coverage.

Canonical root (H), read-only: `/root/Code/specifications/projects/slo/specifications/94-slo-tui-redesign/herdr`.

- **B `94.b.1-herdr-reporting-adapter.md` §7.6, lines 359–361:** always omit model/provider/effort/session tokens; “No redactor/cache/credential resolver is added or called”; explicit narrower product view, not an all-provider redactor.
- **B lines 2042–2047:** four-provider-labelled sentinel inputs, blocked credential store/resolver, real prompt/usage publication with no sentinel in public snapshots/argv/diagnostics before/after rename/rotation.
- **B §8 lines 2184–2185:** secret sentinels in events/environment/failing child output are INPUTS; absent from argv/logs/sequence files.
- **B §9 lines 2208–2209:** no content/credential leak across report argv, logs or integration state; permitted restore paths remain private.
- **C `94.b.2-session-publication-and-native-restore.md` §8 line 2142:** “stdout JSONL unchanged”. §9 lines 2162/2166: reporting failures cannot alter original errors/results; disabled/outside normal behavior unchanged.
- **D `94.c.1-herdr-workflow-visualizer-and-acceptance.md` §8 lines 661–662:** disabled parity; secret-bearing prompt/tool/error absent from REPORTING logs/argv/state; private configuration absent from public snapshots, command argv, EVENTS, diagnostics and sequence state. Private records may contain allowed configuration.
- **Accepted `review-evidence/independent-review-turn4.md`, Prior closure table and architecture assessment:** original F1 closed through omission, “No I/O redactor added”; “No new public history event or provider change.” Specification approval is not implementation acceptance.

Thus excluding ordinary tool INPUT content from the report-output scan corrects the test oracle; it neither waives a Herdr leak nor authorizes a sanitizer. Private configuration retains a separate unconditional all-event scan.

## Changed evidence

`test_mounted_synthetic_labels_and_private_paths_do_not_reach_reporting` now covers 32 variants: compact/detail × four sentinel categories × success/failing tool × success/failing reporting child.

- Positively asserts actual configured-secret terminal tool-error content, not merely a harmless marker. Intentional conversation remains distinct.
- Private workspace/plugin/temp-path sentinels are distinct from credential input; scans ALL raw events for these before and after reporting close. Private restore records positively contain the allowed paths and not the credential.
- Scans every captured snapshot, command argv, reporting-module log, non-restore integration file, public transport result and close result; rescans post-close commands/logs/state so release is not omitted.
- Every synchronous session publication is wrapped with independent resolver and store blockers. Checks recorded mock calls after execution, so optional callback exception containment cannot manufacture green. Blocked resolver methods: resolve, resolve_with_source, require, _from_env, _from_store, _from_legacy_claude. Store: load, _load_owned, _read_envelope, _parse_existing.
- Renames to a rotated sentinel, changes its environment value, injects hostile model/reasoning/effort usage labels and publishes again. Successful transport waits for the final display revision. No provider policy or factory behavior is changed.
- New mounted enabled/disabled test compares FULL ordinary event semantics and positively reproduces the unchanged credential-bearing tool result. Separate finding records exact reproduction/source.

Limits: blockers cover synchronous session publication, not the entire asynchronous reporter lifetime. Rotation changes environment/name/usage display inputs; it is not native four-provider credential rotation (the outer synthetic resolver remains fixed). Existing viewer journey proves submitted/reused/failed across both entry paths, rejection, oversized and private-output parsing; it does not establish every high-level unavailable/manual outcome privacy case. No conditional assertion suppression, skip or xfail was added.

## Executed receipts

CWD as above; approved interpreter `/root/.pyenv/versions/slo-harness/bin/python`, Python 3.11.7 verified. Existing `t1-dao-check.sh` read before use; explicit fallback, no dev environment sourced. Existing registered regular temp fake, HERDR stripping, disabled terminal guard and Faux factory retained. No system symlinks/tools replaced.

All pytest commands used prefix:

```sh
PYENV_VERSION=slo-harness bash docs/implementation/94-herdr/t1-dao-check.sh
```

The helper adds 62 DAO/projection cases; counts overlap, do not sum.

| Suffix / gate | Result |
|---|---|
| full_flow.py::test_mounted_synthetic_labels_and_private_paths_do_not_reach_reporting, initial correction | 78 passed, 34 warnings, 12.13s; exit 0 |
| full_flow.py::test_secret_tool_error_preserves_enabled_disabled_event_parity, first and second attempt | each 1 failed/62 passed; TimeoutError waiting run_completed, no invocation log; explicit input focus alone did not fix missing synthetic resolver setup |
| same parity node with explicit synthetic resolver, matching existing mounted privacy setup | 63 passed, 6 warnings, 2.80s; exit 0 |
| privacy + parity + pilot_configuration_and_typed_viewer_journey, initial instrumentation | 87 passed, 54 warnings, 25.16s; exit 0 |
| `tests/integration/test_herdr_full_flow.py tests/agents/slo_agent/herdr/test_session_publication.py tests/agents/slo_agent/herdr/test_visualizer.py` | 218 passed, 103 warnings, 132.62s; exit 0 (before final profile/post-close scan strengthening) |
| final privacy + parity + viewer nodes | 103 passed, 86 warnings, 37.31s; exit 0 |
| `PYENV_VERSION=slo-harness poetry run black --check tests/integration/test_herdr_full_flow.py` | 1 file unchanged; exit 0 |
| `PYENV_VERSION=slo-harness poetry run mypy --follow-imports=silent tests/integration/test_herdr_full_flow.py` | Success: no issues found in 1 source file; exit 0; scoped check only |
| `dpkg -V coreutils`, after suites | silent; exit 0 |
| `git diff --check` | silent; exit 0 |

Black formatting ran only on the owned test file. Test source inspected after edits; it is pre-existing untracked work, so HEAD diff cannot isolate this assignment. Existing unrelated dirt preserved. No extra receipt directory was created under the write-only-two-reports constraint; command output is retained in the session and summarized here. Existing 281/58 static baseline remains UNWAIVED, not remeasured or declared green by scoped mypy.

## Remaining acceptance gap — not a demonstrated Herdr leak

The authorized oracle correction and bounded cases pass, but **READY for the entire requested scoped privacy matrix is withheld**. Still needed: asynchronous reporting-lifetime credential/store blocking (rather than synchronous publication only), explicit configured-label/rotation coverage beyond injected usage display labels, and all high-level viewer outcome/privacy/read-closure cases. Current tests do not prove those absent cases. No actual Herdr publication leak was demonstrated in these runs. Separate ordinary Slo disclosure remains open. Full suite/static, independent review, two-process and live acceptance remain separate and unapproved.
