# T6 mounted privacy/parity 125 — INCOMPLETE

## Scope and accounting

Same unfinished turn 1: started 1, completed 0, historical partial 1, supplied dispatch 125, retries 0. Unlimited user turn/dispatch limits retained; no agent dispatched. No production edits, other-lane edits, shared-status edits, canonical-spec edits, global/live changes, commits or Git mutations. Two-process safety HOLD preserved: no collection/execution/read of its test/helper files, no integration-directory selection and no full make gate.

Changed only `tests/integration/test_herdr_full_flow.py`, `tests/integration/herdr_parity_124.py`, this receipt and `t6-mounted-privacy-125/` receipts. This is partial progress, NOT READY for the requested finite family or all T6.

## New evidence

1. Initial explicit safe selection reproduced **97 passed**, 56 warnings, 115.80s, exit 0.
2. Added 16 sensitivity cases: each identity/timestamp-looking key inside stream tool input or arbitrary metadata must remain semantic. All 16 failed against the inherited helper. The old recursive key-name normalizer hid actual user-payload changes. This was a **test-oracle defect**, not production RED.
3. Replaced recursive key-name normalization with schema/path-specific normalization: stream `block_id`; history envelope session/event/turn IDs and `recorded_at`; history payload `block_id`; tree-owned payload metadata entry/parent-entry IDs. Unknown record types refuse. No arbitrary recursive normalization, no dropped fields/events. Real single/retry/fallback mounted comparisons remain green.
4. Added 24 further sensitivity cases: all 13 nonidentity stream fields; four history-envelope semantic fields; changed tree parent, order, missing/duplicate records, null content, usage and tool timestamp. These pass by detecting inequality. They are not external production mutation runs.
5. Existing four synthetic credential/private-path scenarios now record **every call to reporter.publish's public snapshot**, before coalescing, rather than only the last snapshot.
6. Expanded to eight mounted privacy scenarios (four synthetic provider labels × successful/failing registered fake child). Actual Faux emits a bound `now` tool call and final answer; the actual tool executor receives a controlled result. Intentional user/tool text is asserted present in Slo events and absent from Herdr snapshots/argv. A registered regular fake executable emits credential stderr plus private error stdout and exits 7 after initial save/display. Failure diagnostics are required to occur (`herdr_command_unavailable`), rather than permitting an empty successful-path log scan. All captured Herdr-module diagnostics, actual argv, sequence/nonrestore state and final close outcome exclude configured credential, child-output sentinel and private paths. Allowed workspace/plugin paths remain in actual private restore records and private immutable capture.

The four provider labels remain synthetic sentinel categories, NOT four native provider execution lanes: factory execution uses the OpenAI-configured Faux boundary. Literal user content is deliberately not subjected to a false blanket transcript-redaction requirement. Canonical B §7.4/§8/§9 and D §8 prohibit conversation in reporting, not all conversation in Slo.

## Finite requested family coverage / remaining obligations

| Obligation | Evidence / remaining gap |
|---|---|
| Ordered enabled/disabled/outside single/retry/fallback parity | Existing complete event/history comparisons retained; narrowed oracle passes all three |
| Normalizer sensitivity | 40 new cases above; positive explicit ID-renaming/topology tests and exhaustive history payload-field mutation coverage remain incomplete |
| Every publication snapshot | All publish calls observed in the eight privacy journeys; no final-only snapshot scan |
| Every transport/viewer outcome | NOT added; only final close outcome remains scanned |
| Prompt/tool/failing child channels | Actual mounted prompt, Faux tool/final answer, registered fake stdout/stderr exit 7 exercised |
| Error path | Fake CLI failure diagnostic covered; sentinel-bearing actual session/tool exception path NOT added |
| Four credentials and private config paths | Existing four synthetic labels and allowed restore-path distinctions retained |
| Arbitrary model/provider/effort labels and rotation | NOT added; credential-like session rename alone is insufficient |
| Zero credential lookup during publication | NOT instrumented independently of normal session auth |
| Disabled write-attempt zero-I/O instrumentation | NOT added; inherited no-assembly/no-spawn/root-absence evidence remains bounded |
| Complete affected-source/read closure | NOT established; see reading boundary below |
| Both viewers unified with retry/fallback; 64 lifetime cases | Next family, unchanged, not claimed closed |

No demonstrated production RED was found; none suppressed or repaired. The oracle defect was repaired only in the owned test helper. No skips/xfails or assertion removal.

## Reading boundary

Read supplied AGENTS/CLAUDE/docs RESEARCH context, actual root RESEARCH, routing/scope-plan, predecessor 124 receipt, canonical B/C/D §§8–10, B privacy §7.4 and final sentinel guidance, exact tasks 3721–3816, KB Welcome/slo README/gotchas, Makefile, first 240 conftest lines including real-terminal/fake-Herdr guards, state-isolation complete, native factory/activation fixture, stream and history event schemas, reporter publication body, environment gate/projector and transport invoke/admission/diagnostic bodies. Shared engineering routing/testing/ownership, coding rules/cadence, Python root/Faux/declarative and workflow SKILL consulted. An oversized skill read truncated; missing shared-declarative opening was not fully recovered. Textual and integration guidance, complete actual project instruction-file rereads, accepted-review companions and complete affected production owner bodies were NOT completed. Therefore do not reuse this as a full prerequisite/read-closure receipt.

## Verification receipts

CWD `/root/Code/slo-94-herdr-integration/slo`. Approved `PYENV_VERSION=slo-harness pyenv which python` resolved `/root/.pyenv/versions/slo-harness/bin/python`, Python 3.11.7. Used existing safe fallback only; no dev environment, installation or new venv.

All pytest commands use:

```text
PYENV_VERSION=slo-harness bash docs/implementation/94-herdr/t1-dao-check.sh <explicit selection>
```

The helper adds 62 foundation cases; counts overlap and must not be summed.

| Receipt | Explicit selection in owned test module unless noted | Result |
|---|---|---|
| initial | full owned module + tests/tui/test_herdr_activation_composed.py + tests/tui/test_herdr_attached_composed.py | 97 passed, exit 0 |
| sensitivity-red | test_parity_normalizer_preserves_user_owned_identity_named_fields | 16 failed, 62 passed, exit 1 |
| sensitivity-green | preceding test + test_enabled_disabled_outside_exact_ordered_parity | 81 passed, exit 0 |
| sensitivity-matrix | test_parity_normalizer_detects_stream_semantics + test_parity_normalizer_detects_history_envelope_semantics + test_parity_normalizer_preserves_history_topology_and_payload | 86 passed, exit 0 |
| publications | test_mounted_synthetic_labels_and_private_paths_do_not_reach_reporting before fake-failure expansion | 66 passed, exit 0 |
| channels | same test after expansion | 70 passed, exit 0 |
| final | same explicit three files as initial | **141 passed, 68 warnings, 120.81s, exit 0** |

`black --check` and `mypy --follow-imports=silent` on exactly the two owned Python files passed (2 files). Formatting was limited to those files. `git diff --check` silent exit 0; these pre-existing untracked owned files are not covered by that check. `dpkg -V coreutils` silent after every test increment; initial/final silent receipts retained. Receipt directory contains complete outputs and exit files. No full non-E2E/static gate run under HOLD. Supplied global baseline **281 errors / 58 files remains UNWAIVED**, not rerun or called green. Independent review and live Herdr acceptance remain pending.
