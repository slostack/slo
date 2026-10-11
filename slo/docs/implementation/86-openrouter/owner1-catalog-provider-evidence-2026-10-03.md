# Feature 86 — Owner 1 catalog/provider evidence

Date: 2026-10-03. Branch/worktree: `feature-86-openrouter-implementation` at
`/root/Code/slo-openrouter-implementation/slo`.

## Bounded disposition

**COMPLETE / READY for Owner 1's bounded evidence additions only.** This is not a
Feature 86 completion claim, a full-suite claim, or a Step 2/3 verdict.

The owned clauses were the finite catalog/provider boundary evidence in overview
§7.3–§7.4, 86.a.2 §§7.2–7.4, and 86.a.3 §7.2:

1. the final-await admission-publication race must retain a *distinct newer*
membership/capability winner;
2. external writer ordering, same-key removal, no-HTTP adoption, and last-good
preservation remain in the existing process/admission tests;
3. reasoning metadata must distinguish omitted effort controls, explicit-null
efforts, explicit disable permission, and mandatory reasoning; and
4. a schema-2 cache entry without the later capability flags must conservatively
mean no configurable controls/no disable permission.

No production correction was exposed: source already rechecks fingerprint and
published reference after its final asynchronous cache read, the existing
conversion/policy/factory paths already preserve `reasoning_disable_available`, and
`ModelCapabilitiesDAO` defaults both old-cache flags to `False`. The required work
was stronger exact evidence, not a duplicate implementation.

## Files changed

- `tests/agents/model_catalog/test_openrouter_final_read_race.py`
  - Strengthened the existing deterministic final-read barrier test with different
    old/new exact route membership (`vendor/older` versus `vendor/newer`) and a
    different local cap (1024 versus 512). The barrier still holds after actual
    cache bytes are read and before their delivery. It proves an old candidate
    cannot replace the already-published newer snapshot; the credential A→B branch
    still rejects before publication.
- `tests/agents/model_catalog/test_openrouter_converter_metadata.py`
  - Added the compact capability truth table for empty reasoning, omitted efforts,
    explicit-null efforts, explicit false disable permission, and mandatory
    reasoning.
- `tests/agents/model_catalog/test_catalog_integrity.py`
  - Added schema-2 compatibility proof that an old serialized capabilities object
    lacking both additive reasoning flags reads as controls-unavailable and
    disable-unavailable.

## TDD evidence

All commands used only `/root/.pyenv/versions/slo-harness/bin/python` 3.11.7 with
`-B`, `PYTHONDONTWRITEBYTECODE=1`, `-p no:cacheprovider`, `timeout 1200`, isolated
owned `HOME`/`TMPDIR`/`SLO_HOME`/`SLO_AUTH_FILE`, and a resolved pytest-owned
`--basetemp`. No real credential, external request, paid call, install, Git mutation,
or system/PATH write occurred.

1. **Final-await race RED**
   - Command target: `tests/agents/model_catalog/test_openrouter_final_read_race.py`
   - Result: **2 failed**, exit 1.
   - Log: `.owner1-red-VL9uZC/red.log`.
   - The strengthened assertion failed before the test established active
     same-key provenance for the deliberately distinct winner; this was a test
     harness setup correction, not a source defect.
2. **Final-await race GREEN**
   - Same target after test setup correction.
   - Result: **2 passed, 2 warnings**.
   - Log: `.owner1-green-bSC9tv/green.log`.
3. **Reasoning/schema partition**
   - Command targets: `test_catalog_integrity.py`,
     `test_openrouter_converter_metadata.py`, and
     `test_openrouter_reasoning_semantics.py`.
   - Result: **74 passed, 1 warning**.
   - Log: `.owner1-green3-SkjYbA/green.log`.
   - The first schema test invocation exposed a `NameError` from a missing test
     import; it was corrected immediately. No source behavior or assertion was
     weakened. Retained output: `.owner1-green2-tUIGvH/green.log`.
4. **Surrounding owner partition**
   - Command targets: all `tests/agents/model_catalog`, plus
     `test_openrouter.py`, `test_openrouter_reasoning_semantics.py`,
     `test_openrouter_capability_recovery.py`, and
     `test_openrouter_runtime_boundaries.py`.
   - Result: **352 passed, 2 warnings**.
   - Log: `.owner1-surrounding-a7liQN/surrounding.log`.

The reasoning wire test uses the real `LLMFactory` → `OpenRouterChatOpenAI` SDK path
with local `httpx.MockTransport`, so the assertions cross converter, reasoning
resolution, factory forwarding, request policy, and emitted SDK request body. The
final-read test uses real temporary schema-2 cache bytes and holds delivery only
after the actual loader has read them; it does not mock around the final await.

`git diff --check` over the three owner test files passed.

## Existing evidence retained, not rebuilt

- `test_catalog_process_ordering.py` is the external-writer, same-key ordering
  contract: a delayed old process observes the pre-lease state; the newer process
  persists a distinct winner; the old process then adopts it without GET calls and
  cannot overwrite its bytes.
- `test_openrouter_admission_security.py` supplies same-key removal/cap adoption,
  next-admission rejection, and last-good safety coverage. The strengthened
  final-read test complements it at the exact final asynchronous read boundary.

## Residual risks and scope limits

- This owner did **not** run the complete non-E2E suite; the integration owner owns
  that mandatory final gate.
- No live OpenRouter availability/entitlement claim is made; all HTTP is synthetic
  local `MockTransport`.
- The final-read race is deterministic in-process admission ordering. The existing
  external-process ordering test remains the separate process/lease proof; this
  report does not claim exhaustive concurrency coverage.
- This report does not resolve non-owner current Feature 86 requirements (including
  broader cross-channel capture artifacts, auth/UI conditions, or final gate
  disposition).

**Test count:** 2 focused race + 74 reasoning/schema + 352 surrounding owner
partition = 428 passing test executions (partitions overlap and are not a unique-test
count).
