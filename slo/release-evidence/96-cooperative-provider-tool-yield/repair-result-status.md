# RH1 repair — marked result status replay

**Scope:** RH1 only. No RH2–RH4 or unrelated work. Source authority:
`/root/Code/specifications/projects/slo/specifications/96-agent-message-queue/96.a.2-cooperative-provider-and-tool-yield.md`
§6.1 and §9 A12 ("Projector uses it; legacy missing status preserves prior behavior").

**Repository / cwd:** `/root/Code/slo-message-queue/slo`
**Baseline HEAD:** `82c3f5c6de9345af34a673a3d975366ca8c1624c` (unchanged; no git write)

## RED — failing-first tests, both real adapters

Command (exactly):

```bash
cd /root/Code/slo-message-queue/slo
export SLO_ENV=test SLO_ROOT_DIR="$PWD" SLO_APP_DIR="$PWD" SLO_APP_NAME=slo
export SLO_LOG_FORMAT=text SLO_DEFAULT_MODEL_NAME=gpt-5.4
export SLO_AUTO_VISUALIZE=0 SLO_HERDR_DISABLED=1
export SLO_ANTHROPIC_API_KEY=ci-placeholder-tests-are-fully-mocked
export COLUMNS=120 LINES=40 PYTHONDONTWRITEBYTECODE=1
PYTHONPATH="$PWD" /root/.pyenv/versions/slo-harness/bin/python -m pytest \
  -p no:cacheprovider -q tests/agents/slo_agent/history/test_projector_tool_groups.py
```

- Python: `/root/.pyenv/versions/slo-harness/bin/python` → 3.11.7 (same binary Poetry uses).
- Exit status: **1**.
- Count: **2 failed, 24 passed, 2 warnings in 2.48s**.
- Failed exactly: `test_marked_error_result_replays_actual_status[False]` and `[True]`.
- Failure: `assert 'success' == 'error'` at the marked error result assertion — the default LangChain status, not the durable `tool_result_status`.
- The two param cases are the flat and tree real history adapters; the raw event list is read back through `application_evidence` before projection.

## GREEN — focused repair

Implementation in `src/agents/slo_agent/history/projector.py::_event_to_message`:
`tool_result` parses the already-validated `tool_group_v1` metadata with the
existing `_tool_group_metadata` helper. Only a present `tool_result_status`
adds the `ToolMessage` `status` keyword; unmarked legacy results omit it and
keep LangChain's prior default. No new helper, dependency, schema or file
outside this repair/report.

Command: identical to RED. Exit status: **0**. Count: **26 passed, 2 warnings
in 2.30s**.

Existing projector regression, same env/cwd:

```bash
PYTHONPATH="$PWD" /root/.pyenv/versions/slo-harness/bin/python -m pytest \
  -p no:cacheprovider -q tests/agents/slo_agent/history/test_projector.py \
  tests/agents/slo_agent/history/test_projector_tool_groups.py
```

Exit status **0**, count **44 passed, 2 warnings in 2.35s**. `git diff --check`
on the two touched files: exit **0**.

Tests added in `tests/agents/slo_agent/history/test_projector_tool_groups.py`:

- marked `error` result + terminal → exact `status == "error"`, exact ID/name/content, one result, flat and tree (the RED case);
- marked `success` result → `status == "success"`, flat and tree;
- legacy unmarked call/result → default `status == "success"` and unchanged content.

## Hashes

- Baseline HEAD: `82c3f5c6de9345af34a673a3d975366ca8c1624c`
- `src/agents/slo_agent/history/projector.py` SHA-256:
  `9605664bf748e32d69c4210e2c764db550570715d01f7fb653506ada1ea64814`
- `tests/agents/slo_agent/history/test_projector_tool_groups.py` SHA-256:
  `78e8d72fb82b7c241855b9b836495ffb7e7f96b4dd89d7dd15aebfd98926c1aa`
- Preflight report SHA-256 remains
  `10fe2372f972374580d6071578c543edad98fd811a43ce2b0857cdb282183638`

## Status and limits

RH1 is repaired with focused RED/GREEN evidence. RH2–RH4 remain open exactly as
reported in `early-review-raw-history.md`. No full suite was run:
`make test PYTEST_WORKERS=6` remains **BLOCKED** (no exclusions/substitutes/mode
evasion). Full static checks remain **UNRUN**; no YAML-stub baseline claim is
made. No executable/package/installer/system/infrastructure/git-publish or
nested-agent operation occurred; `SLO.md`, `docs/`, prior reports and unrelated
dirty work are preserved. No independent early/final/completion review is
claimed here; those remain pending on `gpt-6.1-sol` high.

Counters preserved: **turn 7, dispatch 2/20**, prior partial
**7/4/4/8/8/11**, ceiling **60 turns**, **12 execution retries**, **no abort**.
Primary route remains the exact DeepSeek default; fallback only on a concrete
quota error is not needed and was not used.
