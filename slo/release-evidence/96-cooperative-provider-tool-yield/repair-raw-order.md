# RH2 repair — raw opening/result and anchor/disposition ordering

**Scope:** RH2 only. No RH3 summary work, no RH4 rewrite work, no T2. Source
authority:
`/root/Code/specifications/projects/slo/specifications/96-agent-message-queue/96.a.2-cooperative-provider-and-tool-yield.md`
§§6.2.1/6.2.4 and 6.3.1–6.3.3 (and §9 A8/A12). RH1 marked-result status
replay is preserved.

**Repository / cwd:** `/root/Code/slo-message-queue/slo`
**Baseline HEAD (unchanged, no git write):**
`82c3f5c6de9345af34a673a3d975366ca8c1624c`

## RED — failing-first tests, both real adapters, ordinary append

Malformed evidence is written through the ordinary `append_event` path, so the
raw validator—not the cooperative append port—is the component under test.
Both flat and tree adapters read their own raw pages through
`application_evidence` before validation/projection.

Command (exactly, from `/root/Code/slo-message-queue/slo`):

```bash
export SLO_ENV=test SLO_ROOT_DIR="$PWD" SLO_APP_DIR="$PWD" SLO_APP_NAME=slo
export SLO_LOG_FORMAT=text SLO_DEFAULT_MODEL_NAME=gpt-5.4
export SLO_AUTO_VISUALIZE=0 SLO_HERDR_DISABLED=1
export SLO_ANTHROPIC_API_KEY=ci-placeholder-tests-are-fully-mocked
export COLUMNS=120 LINES=40 PYTHONDONTWRITEBYTECODE=1
PYTHONPATH="$PWD" /root/.pyenv/versions/slo-harness/bin/python -m pytest \
  -p no:cacheprovider -m 'not e2e' -q \
  tests/agents/slo_agent/history/test_projector_tool_groups.py \
  tests/agents/slo_agent/messaging/test_startup_raw_tool_groups.py
```

- Python: `/root/.pyenv/versions/slo-harness/bin/python` → 3.11.7 (same binary
  Poetry uses; synthetic env routing above).
- Exit status: **1**.
- Count: **4 failed, 38 passed, 2 warnings in 3.36s**.
- Failed exactly, both adapters:
  - `test_result_before_its_opening_fails_before_context_selection[False/True]`
  - `test_first_anchor_opening_after_marker_fails_closed[False/True]`
- Failure: `DID NOT RAISE UnsettledToolGroupError`. `[result(a, actual
  output), opening(a), terminal]` was accepted; `[opening(b), marker,
  opening(a)]` was accepted because marker position was compared with the
  first observed sibling, not the required first-call anchor.

Raw log:
`logs/turn7-rh2-red.log`.

## GREEN — bounded repair

Implementation in `src/agents/slo_agent/history/projector.py::_RawToolGroupState`:

- `add_result` now requires the result's call identity to have been opened
  earlier. A result before its own opening is malformed raw evidence. Existing
  per-call/result membership and duplicate checks are unchanged; no requirement
  was added that every sibling opening precede a result.
- `add_opening` records the index of the first-call (anchor) opening.
- `require_settled` requires that anchor opening to precede the affirmative
  no-start marker. Marker-with-result, marker-without-anchor and unknown/
  duplicate/conflicting evidence still fail with the same fixed
  `UnsettledToolGroupError`.
- Valid first full anchor plus marker with partial sibling writes remains
  valid and excludes exactly that group's openings. No extra restriction was
  added.
- `_event_to_message` marked-result `tool_result_status` replay from RH1 is
  untouched.

Focused command (identical env/cwd):

```bash
PYTHONPATH="$PWD" /root/.pyenv/versions/slo-harness/bin/python -m pytest \
  -p no:cacheprovider -m 'not e2e' -q \
  tests/agents/slo_agent/history/test_projector_tool_groups.py \
  tests/agents/slo_agent/messaging/test_startup_raw_tool_groups.py
```

Exit status **0**; count **42 passed, 2 warnings in 3.00s**. Raw log:
`logs/turn7-rh2-green.log`.

Audited focused chain (projector, raw groups, contract reconciler, file
certification, compaction groups, settlement failure, startup raw, cooperative
append): exit status **0**, count **142 passed, 2 warnings in 4.32s**. Raw
log: `logs/turn7-rh2-green-audited-chain.log`.

`git diff --check` on the touched tree: exit **0**.

## Tests added (ordinary append, both adapters)

- result before its opening: `validate_tool_groups`, `context_events` (also
  with `excluded_turn_ids`), and `build_message_history` all raise before
  completed-turn/exclusion selection or reconciliation/healing.
- anchor opening after no-start marker: same consumers fail closed.
- valid full anchor + marker, missing sibling: still validates, excludes only
  the opening, and projects the remaining user message.
- duplicate opening for one call (distinct event id): representative duplicate
  evidence fails closed. Existing conflict tests remain (conflicting opening
  array, extra result, unknown version).

## Hashes

- Baseline HEAD: `82c3f5c6de9345af34a673a3d975366ca8c1624c`
- `src/agents/slo_agent/history/projector.py` SHA-256:
  `fb169a38403683e51b3f848c2be94288c93c0083715c8bfa89120f9fd79a47af`
- `tests/agents/slo_agent/history/test_projector_tool_groups.py` SHA-256:
  `c5a337b62d16a2d3dc0d337d982eb7a17d16291ed1bcae29a40e7ba3ea10d7a6`
- Preflight report SHA-256 remains
  `10fe2372f972374580d6071578c543edad98fd811a43ce2b0857cdb282183638`

## Status and limits

RH2 ordering is repaired at focused/audited-chain level. RH3 (summary consumer)
and RH4 (rewrite validation) remain open exactly as reported; no summary,
rewrite, T2 or uninterrupted-context work was performed.

No full suite: `make test PYTEST_WORKERS=6` remains **BLOCKED** by other
fixture consent; no exclusions/substitutes/mode evasion. Full static checks
remain **UNRUN**; YAML-stub baseline remains **UNESTABLISHED**. No
executable/package/installer/herdr/system/infrastructure/git-publish or
nested-agent operation occurred. `SLO.md`, `docs/`, preflight and prior
reports are preserved. Independent `gpt-6.1-sol` high final/completion review
remains pending; no feature completion is claimed.

Counters: **turn 7, dispatch 3/20**; prior partial **7/4/4/8/8/11**; ceiling
**60 turns**; **12 execution retries**; **no abort**. Primary route remains the
exact DeepSeek default; fallback only on a concrete quota error, which did not
occur and was not used.
