# A.2 B2 exact-terminal proof — bounded closure

**Verdict: READY (bounded B2 test-only closure).** The named journey now proves the
observer terminal sequence and the sole durable attempt correlation required by
`early-review-cutoff-closure.md` B2. Execution receipt below is current, with
actual exit status and counts. No production code changed in this dispatch. This
is not completion of A.2, T1, or the silent-provider milestone.

Repo `/root/Code/slo-message-queue/slo`, branch `message-queue`, HEAD/baseline
`82c3f5c6de9345af34a673a3d975366ca8c1624c`.

## Assertions in force (test-only owner)

`tests/agents/slo_agent/messaging/test_provider_settlement_guard.py`
sha256 `91fb7c596532f668d796ab3a6d1e733608d1f74fc87eb3ba428de72be4b4434b`,
`test_real_messaging_session_settlement_failure_is_terminal`, all **after** the
`finally: await session.close_messaging()` join:

- `terminal_kinds == ["run_failed"]` — exact observer subsequence; duplicates,
  `run_completed`, `run_aborted` rejected.
- `not any(kind in kinds for kind in _FORBIDDEN_RECOVERY_STREAM_KINDS)` — covers
  `stream_reconnecting`, `compaction_started/completed/failed/retrying/advised`,
  recovery and `run_retrying` observer kinds.
- Exactly one durable `run_started` and one `run_failed`; `opening.turn_id is not
  None`, `failure.turn_id == opening.turn_id`, both `session_id == session_id`,
  `opening.sequence < failure.sequence`.
- Preserved separately: boundary 0 / applied / not retained; exactly one
  `messaging_v1` application matching message ID, sequence 1 and logical
  `stored_run_id`; one applied identity receipt linked to the application event;
  application journal equality; zero provider calls; one plugin iteration.
- No attempt UUID is equated with the logical message run UUID. The attempt
  `turn_id` remains distinct from `stored_run_id`; T1/T2 metadata work is not
  claimed.

## Fixture-chain audit (read-only, before execution)

- Autouse fixtures from `tests/conftest.py`: isolated `SLO_HOME`/`HOME`, plugin
  kill-switch removal, visualizer spawn stub, Herdr spawn guard patch. None
  creates or chmods a file.
- `fake_herdr` (the only conftest `chmod 0o700/0o600`) is **not autouse** and is
  not requested by the three focused modules. No Herdr/installer fixture ran.
- The journey writes one regular non-executable plugin `.py` and SQLite/history
  data under its own `tmp_path`; `FilesystemSessionHistoryStore` applies data/dir
  modes `0o600`/`0o700` (no executable bit) beneath that root.
- No `bin/` executable was created or mutated. The only consented
  `tmp_path/bin/curl` fixture was **not run**. No packages, system,
  infrastructure, git write, or nested agents.

## Execution receipts (actual)

Log: `logs/turn4-b2-journey-rerun.log`, `logs/turn4-b2-focused-set.log`.
cwd `/root/Code/slo-message-queue/slo`; env `SLO_ENV=test`, `SLO_ROOT_DIR`/
`SLO_APP_DIR`=`$PWD`, `SLO_APP_NAME=slo`, `SLO_LOG_FORMAT=text`,
`SLO_DEFAULT_MODEL_NAME=gpt-5.4`, `SLO_AUTO_VISUALIZE=0`, `SLO_HERDR_DISABLED=1`,
`SLO_ANTHROPIC_API_KEY=ci-placeholder-tests-are-fully-mocked`, `COLUMNS=120`,
`LINES=40`, `PYTHONDONTWRITEBYTECODE=1`, `PYTHONPATH=$PWD`; runner
`poetry run pytest` on CPython 3.11.7 (`slo-harness` resolves to the same
interpreter).

1. Journey — exit **0**: `1 passed, 3 warnings in 1.54s`.
2. Focused set `test_message_contract_reconciler.py` +
   `test_provider_settlement_guard.py` + `test_graph.py` — exit **0**:
   `79 passed, 12 warnings in 2.27s`.

Source identity: reconciler test `3cef845d…3a6570a`, provider test
`91fb7c59…4b4434`, graph test `f55e73f6…043fa97`, reconciler
`2606e6d8…932898`, sessions service `e5477925…cfc2a0`, agent `b6823bc1…8a5003`,
graph service `a7077c4f…0e9ea9`.

## Honest limits

- No RED or test-first chronology is claimed or reconstructed for this assertion
  body. Prior logs remain retained output, not independently reproduced proof.
- `make test PYTEST_WORKERS=6`: **BLOCKED / UNVERIFIED** (unauthorized executable
  fixtures; no substitution or waiver).
- Full static gate: **UNRUN / UNVERIFIED**. Mypy `yaml` missing-stub failure
  baseline remains unestablished; no install authorized.
- Independent early re-review / final review / completion remain pending. Main
  silent-provider race/history/tools/TUI work is unimplemented and no completion
  is claimed.
