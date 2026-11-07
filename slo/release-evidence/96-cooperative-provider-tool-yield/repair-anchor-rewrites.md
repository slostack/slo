# Turn 8 — RH2 projection-anchor closure and RH4 unresolved-rewrite proof

**Scope:** exactly the two finite closures requested by
`early-review-raw-repairs.md`: RH2 (first-call projection anchor before any
actual result) and RH4 (test-only proof that both rewrite APIs refuse unresolved
current evidence by `UnsettledToolGroupError`, not digest mismatch). No other
feature, producer, T2, interrupted-context §6.4.5, TUI, gate or infrastructure
work.

**Repository / cwd:** `/root/Code/slo-message-queue/slo`
**Baseline HEAD (unchanged, no git write):**
`82c3f5c6de9345af34a673a3d975366ca8c1624c`
**Source authority:**
`/root/Code/specifications/projects/slo/specifications/96-agent-message-queue/96.a.2-cooperative-provider-and-tool-yield.md`
§§6.1, 6.2.1/6.2.4 and 6.3.1–6.3.5 (A8/A12).

## RH2 — source repair, failing test first

### RED before production

New test:
`tests/agents/slo_agent/history/test_projector_tool_groups.py::test_sibling_result_before_projection_anchor_fails_before_context_selection`.
It writes ordinary (not cooperative-port) events through both real adapters in
the malformed order:

```text
user -> opening(b, full [a,b]) -> result(b, success, "b-real")
     -> opening(a, full [a,b]) -> result(a, error, "a-real") -> terminal
```

Every result follows its own opening, so the prior validator accepted it, but
only opening(a) projects the `AIMessage`; result(b) would be dropped and
historically healed. The test requires rejection from `validate_tool_groups`,
`context_events`, `context_events(..., excluded_turn_ids={turn_id})` and
`build_message_history`.

Command (exact, from the cwd above):

```bash
export SLO_ENV=test SLO_ROOT_DIR="$PWD" SLO_APP_DIR="$PWD" SLO_APP_NAME=slo
export SLO_LOG_FORMAT=text SLO_DEFAULT_MODEL_NAME=gpt-5.4
export SLO_AUTO_VISUALIZE=0 SLO_HERDR_DISABLED=1
export SLO_ANTHROPIC_API_KEY=ci-placeholder-tests-are-fully-mocked
export COLUMNS=120 LINES=40 PYTHONDONTWRITEBYTECODE=1
PYTHONPATH="$PWD" /root/.pyenv/versions/slo-harness/bin/python -m pytest \
  -p no:cacheprovider -m 'not e2e' -q \
  tests/agents/slo_agent/history/test_projector_tool_groups.py
```

- Python: `/root/.pyenv/versions/slo-harness/bin/python` → 3.11.7 (same binary
  Poetry uses; synthetic env routing above).
- Exit status **1**.
- Count **2 failed, 36 passed, 2 warnings in 2.98s**.
- Both failures: `DID NOT RAISE UnsettledToolGroupError` at the first
  `validate_tool_groups` assertion for flat and tree.
- Raw log: `logs/turn8-rh2-red.log`
  (sha256 `9a0fa45993b3613867119fa24bbfa188be42be7e1ac572768fc1800d5dad11b2`).

### GREEN change

`src/agents/slo_agent/history/projector.py::_RawToolGroupState.add_result` now
also requires `anchor_opening_index is not None` before admitting any actual
result. The anchor is the first declared call's opening, the only event that
projects the group's `AIMessage`. Its own-opening check and duplicate/membership
checks remain. Settled full groups, canonical valid order and partial sibling
no-start semantics are unchanged; no historical healing path was used or
weakened.

Positive proof added:
`test_settled_two_call_group_preserves_exact_content_and_status` replays a full
`A,B` group and asserts exact `AIMessage.tool_calls`, and exact
`(tool_call_id, status, content)` for both real results (`a/success/a-real`,
`b/error/b-real`) with no invented placeholder. The existing partial no-start
sibling test was strengthened to assert the untouched sibling result's exact
`z/success/ok` content, not just its id.

Focused GREEN command is the same argv as RED:

- Exit status **0**.
- Count **38 passed, 2 warnings in 2.87s** (post-format final tree).
- Raw log: `logs/turn8-rh2-green.log`
  (sha256 `7659caa811b9664ebf52aaf0186134308ccff71cb52b35a25c42cd1ce4950307`).

## RH4 — test-only proof; no source change and no claimed RED

Source was already guarded at
`src/agents/slo_agent/history/filesystem_store.py::_require_current_active_snapshot_sync`
(unchanged hash `22ffee414d2979c2927cb1fa29b1532118ec3f6ae1e0eaccc4ad3023652237ba`).
It reads current active history under the store lock, validates raw groups, then
compares the ordered snapshot digest.

New test:
`tests/agents/slo_agent/history/test_compaction_tool_groups.py::test_rewrite_refuses_unresolved_opening_before_any_effect`.
It runs both adapters × both public APIs × both scenarios:

1. `stale` — a previously valid snapshot is passed after a new unresolved
   opening (opening only, no result/marker) is appended.
2. `current` — the matching current source itself contains the unresolved
   opening.

Both must raise `UnsettledToolGroupError`, proving validation wins over the
digest mismatch path (`MessageStoreError`). Each case asserts byte-identical
`events.jsonl` and `session.json`, no archive or candidate artifact, and that
the unresolved opening is still retained.

This is a **new-assertion green** result. No RED was simulated or claimed for
RH4 because the source was already guarded. Existing settled-late-group mismatch
and compatibility success/pinning tests remain in the same module and passed.

Focused command (same env/cwd as RH2):

```bash
PYTHONPATH="$PWD" /root/.pyenv/versions/slo-harness/bin/python -m pytest \
  -p no:cacheprovider -m 'not e2e' -q \
  tests/agents/slo_agent/history/test_compaction_tool_groups.py
```

- Exit status **0**.
- Count **22 passed, 2 warnings in 3.20s** (14 prior + 8 new cases).
- Raw log: `logs/turn8-rh4-green.log`
  (sha256 `11c93a5c3ba7ce83881f43b448ae443797cf258653030da7004db6d80b3c5d05`).

## Focused regression

Same environment and cwd. Modules: projector groups, startup raw groups,
message-contract reconciler, file certification, compaction groups, settlement
failure, cooperative append, compaction transaction, filesystem-store
compaction, history application, retained recovery, OpenRouter writer secrecy,
summary guard, cooperative-yield metadata, provider settlement guard and tool
group metadata.

- Exit status **0**.
- Count **261 passed, 9 warnings in 10.56s**.
- Raw log: `logs/turn8-regression.log`
  (sha256 `3a6b894b2e259819aef8e413dd4796a999ad82578463020f4691d6fb4b49a56f`).

## Scoped static

```bash
/root/.pyenv/versions/slo-harness/bin/python -m black --check \
  src/agents/slo_agent/history/projector.py \
  tests/agents/slo_agent/history/test_projector_tool_groups.py \
  tests/agents/slo_agent/history/test_compaction_tool_groups.py
git diff --check -- <same files>
```

- Black exit **0**, 3 files unchanged; log `logs/turn8-black-check.log`
  (sha256 `45a468fa6205768496f23f1716ebb7575e9b723449d2099b88bf2afef60b721f`).
- `git diff --check` exit **0**.
- Scoped mypy exit **1**, **9 errors**, all on pre-existing `BaseMessage`
  attribute assertions in these test files: `test_projector_tool_groups.py`
  lines 201–202, 641–642, 668–669, 704 and
  `test_compaction_tool_groups.py` lines 253–254. No error points at a new
  test line; new assertions narrow with `isinstance(...)`. Baseline
  attribution remains **UNESTABLISHED**, not an exemption. Log
  `logs/turn8-mypy.log`
  (sha256 `01eb1c2ac73ecdf35faee8d5e9b49091b4fad5f039c2307cca79cc5bb392ba28`).

## Final tested hashes

- `src/agents/slo_agent/history/projector.py`
  `0ddab926876c27569998987737f97d01df0134ac70966e770bff813ae951ee6f`
- `tests/agents/slo_agent/history/test_projector_tool_groups.py`
  `fd080a4e4c6e28cb4ec771e40562e6c1a42d621d56bef2502814bea3db0ae646`
- `tests/agents/slo_agent/history/test_compaction_tool_groups.py`
  `2a12d61baac880b88ff6652175fd7fb4625346ccc12f33a2735a1c0ae38494e9`
- Untouched RH4 owner `filesystem_store.py`
  `22ffee414d2979c2927cb1fa29b1532118ec3f6ae1e0eaccc4ad3023652237ba`
- Preflight remains
  `10fe2372f972374580d6071578c543edad98fd811a43ce2b0857cdb282183638`

## Preserved and not done

- RH1, RH3, prior RH2 cases and all existing append/startup/compaction/A.1
  coverage preserved. Historical receipt discrepancy from the prior review
  remains recorded as an evidence limitation; no baseline was invented.
- No full `make test PYTEST_WORKERS=6`; remains **BLOCKED by other fixture
  consent**, with no exclusions/substitutes/mode evasion. Full static remains
  **UNRUN**; YAML-stub baseline **UNESTABLISHED**.
- No executable mutation; the sole consented deploy-worker temp `bin/curl`
  fixture was not run. No installer/herdr/package/system/infrastructure or
  git write, commit, push, merge, PR or nested-agent operation.
- Unrelated dirty `SLO.md`, `docs/`, preflight and prior evidence preserved.
- Independent `gpt-6.1-sol` high final review, completion assessment and
  milestone acceptance remain mandatory and pending.

Counters: **turn 8, dispatch 1/20**; prior partials **7/4/4/8/8/11**; ceiling
**60 turns**; **12 execution retries**; **no abort**. Primary route remains the
exact DeepSeek default; `gpt-6.1-sol` medium fallback only on a concrete quota
error, which did not occur and was not used.
