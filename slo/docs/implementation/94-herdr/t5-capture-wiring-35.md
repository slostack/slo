# T5 capture wiring 35 — INCOMPLETE

Capture-family READY is withheld. No arbitrary unit/dispatch limit is asserted. This checkpoint implements a tested subset, not the requested complete family or full T5 acceptance.

## Scope and preserved accounting

Only session service and test_session_capture.py changed in production/test scope in this continuation. Existing partial changes were preserved. Frozen routing is unchanged. No agents, commits, pushes, PRs, destructive Git, spec/global/live/other-worktree edits. Parent accounting remains turn 1, started 1/completed 0/historical partial 1/dispatch 35/retries 0; unlimited turns and dispatches. Attention/lifetime/app/viewer and independent feature review remain pending.

## Implemented finite branch map

- `_prepare_herdr_capture_inputs(interactive=...)`: session-owned preparation reads real existing history metadata; missing metadata never creates history. Headless, history-disabled and injected-agent gates return ineligible. Ordinary input failure denies default-root eligibility. Cancellation propagates.
- `_resolve_herdr_capture_paths`: off-loop default-root comparison and resolved working directory, explicit workspace and ordered plugin paths. Metadata workspace is used only absent explicit config. Source fingerprint stores lexical workdir/config workspace/config history root/config and effective plugin lists/actual store root.
- `_capture_herdr_restore`: requires unchanged source fingerprint; uses cached resolved workdir/plugins rather than resolving per event. Existing provenance/UUID/immutable pool validation retained.
- Real successful `_ensure_history_session` (including rename's first creation), reasoning switch, both model-selection commits and `_adopt_prepared_snapshot` now adopt exact private capture. Model selection clears pool. Equal reasoning, names, usage rebuilds and equal prepared snapshots do not churn generation.
- Tests drive actual config-backed session preparation, actual history ensure/rename, both selection APIs and prepared adoption. The prior manual activation-fact test now uses persisted metadata and preparation instead. Config-backed test factory remains Faux; no provider or Herdr command/window runs.

## Exact evidence

CWD `/root/Code/slo-94-herdr-integration/slo`. `pyenv which python` = `/root/.pyenv/versions/slo-harness/bin/python`; Python 3.11.7; `make test-env` = fallback. All focused commands use:

`bash docs/implementation/94-herdr/t1-dao-check.sh tests/agents/slo_agent/herdr/test_session_capture.py`

Every GREEN additionally includes:

`tests/agents/slo_agent/herdr/test_session_publication.py tests/agents/slo_agent/orchestrator/test_bootstrap.py tests/agents/slo_agent/test_session.py tests/agents/slo_agent/test_session_usage.py`

The helper adds DAO/projection tests, test fallback environment, disabled Herdr and PYTHONPATH. Full output is retained in each listed `.log`; adjacent `.exit` records command status before tailing. Each production increment was below approximately 50 lines and tested with surroundings before the next.

| Prefix under this directory | Outcome |
|---|---|
| t5-35-input-red | 1 failed, 67 passed; exit 1; missing preparation method |
| t5-35-input-green | 172 passed; exit 0 |
| t5-35-guard-red | 4 failed, 68 passed; exit 1; unsupported path edits accepted |
| t5-35-guard-green | 176 passed; exit 0 |
| t5-35-commit-red | 1 failed, 72 passed; exit 1; persistence did not adopt |
| t5-35-commit-green | 1 failed, 176 passed; exit 1; test requested already-active high reasoning |
| t5-35-commit-green2 | 177 passed; exit 0; explicit low initial reasoning fixes test premise |
| t5-35-full | make test: 7399 passed, 19 deselected, 408 warnings; exit 0 |
| t5-35-model-red | 2 failed, 73 passed; exit 1; one invalid fixture model and one missing adoption |
| t5-35-model-red2 | 2 failed, 73 passed; exit 1; valid gpt-5.5 fixture exposes both missing adoptions |
| t5-35-model-green | 179 passed; exit 0 |
| t5-35-final | intermediate formatted partition: 179 passed; exit 0 |
| t5-35-adopt-red | 1 failed, 80 passed; exit 1; effective reasoning not recaptured |
| t5-35-adopt-green | 185 passed, 9 warnings; exit 0 |
| t5-35-final-full | final make test: 7407 passed, 19 deselected, 408 warnings, 572.09s; exit 0 |

Final formatting: `poetry run black src/agents/slo_agent/sessions/service.py tests/agents/slo_agent/herdr/test_session_capture.py`, `t5-35-final-black.log/.exit`, exit 0. `git diff --check`, `t5-35-final-diff.log/.exit`, silent/0. `dpkg -V coreutils`, `t5-35-final-coreutils.log/.exit`, silent/0. Existing default-suite Herdr isolation and terminal guards retained. Static baseline 300 errors/64 files remains unwaived; no new ignore and no lint-green claim. Full-suite green is not family acceptance.

## Precise remaining family work

1. Preparation helper has no actual enabled activation caller yet. Must integrate with the retained lifetime preparation boundary; disabled/outside must do zero path/metadata work. Do not present direct helper tests as complete activation proof.
2. `prepare_startup` effective-reasoning commit still needs capture refresh and test-first actual pending startup evidence. Provenance changes need committed refresh wiring.
3. Publication snapshot pairing/reuse and memory-only out-of-band guard invalidation are not wired. Current guard rejects on capture conversion only; usage events do not yet revoke stale committed capture.
4. Source fingerprint currently uses a generic tuple of objects; replace with a precise typed/cohesive representation if extending it. Test runtime `_workdir`, effective plugin-list and actual-store-root mutations, resolved relative plugin order and bootstrap mutation invalidation.
5. Preparation sets the existing ensured flag for valid resumed metadata. Reconcile this with normal ensure_session workspace update semantics; metadata success must not prevent ordinary explicit-workspace persistence. Successful ensure should consume its returned metadata where needed rather than silently relying on stale activation workspace.
6. Need full composed Faux invoke, no credential/model/disk capture assertions at actual public-event boundary, fallback/failed selection/no-churn and privacy matrices; current tests are bounded input/commit evidence only.
7. Required reading is not fully closed: shared routing/ownership/testing/coding/Python DAO/service/declarative and workflow files read; complete T5 samples read. Some bulk KB/contract reads truncated; remaining C/B snapshot and selected style/test recipe reading must be completed, not presumed from prior reports.

No READY claim, no independent review or live compatibility claim.
