# T5 publication continuation 41 — INCOMPLETE

Same unfinished workflow turn 1: started 1, completed 0, historical partial 1,
dispatch 41, retries 0. User turn/dispatch budgets are unlimited. No agents ran.
This is not a publication-family handoff or all-T5 acceptance.

## Change and exact test map

Only `src/agents/slo_agent/sessions/service.py` and the existing
`tests/agents/slo_agent/herdr/test_session_publication.py` changed in production/test
scope during this continuation. All earlier work was preserved.

`prepare_startup` now adopts the private restore capture after successful no-await
catalog/effective-reasoning/usage/readiness adoption. One production line.
`test_startup_commits_capture_only_after_success[success,failure,cancel]` drives the
actual session startup method on a config-backed persisted session. Success captures
the newly effective reasoning and increments generation once; repeated ready startup
does not churn it. Failure and cancellation preserve the original capture object and
generation. Catalog preparation is mocked offline; this is not a complete pending
OpenRouter startup or Faux submission acceptance proof.

## Executed evidence

CWD: `/root/Code/slo-94-herdr-integration/slo`. `pyenv which python` returned
`/root/.pyenv/versions/slo-harness/bin/python`; Python 3.11.7; `make test-env` returned
`fallback`. Used the approved helper without creating/installing a venv.

Each receipt below has `.log` and `.exit` beside this document.

- `t5-41-startup-red`: helper + publication module; **1 failed, 67 passed**, exit 1.
  Success case retained low reasoning instead of committed high. Failure/cancel passed.
- `t5-41-startup-green`: helper + publication/capture, session, session_usage and
  orchestrator/test_bootstrap modules; **188 passed, 9 warnings**, exit 0.
- `t5-41-format`: Black on the two edited Python files; exit 0.
- `t5-41-final-surrounding`: same GREEN partition plus
  `tests/agents/slo_agent/test_session_rate_limits.py` and
  `tests/agents/slo_agent/test_session_manual_compaction.py`;
  **233 passed, 9 warnings**, exit 0 after formatting.
- `t5-41-black`: `poetry run black --check` on the two edited Python files; exit 0.
- `t5-41-diff`: `git diff --check`; silent, exit 0.
- `t5-41-coreutils`: `dpkg -V coreutils`; silent, exit 0.

Helper command prefix: `bash docs/implementation/94-herdr/t1-dao-check.sh`.
It adds DAO/projection tests. Default disabled Herdr and existing independent fake
capability/terminal isolation remain intact. No Herdr/provider/window was launched.
No full make test/smoke/lint run in this unfinished continuation. Historical 7466
full / 288 smoke / 299 errors in 63 files are NOT current post-change evidence;
static baseline remains unwaived, new diagnostic attribution not yet run.

## Remaining finite family work

1. Successful startup now captures, but publication hooks and actual pending-startup
   operation/attention evidence remain absent.
2. Provenance commits must refresh capture/publication; resumed metadata preparation
   must not bypass ordinary explicit-workspace ensure/persistence semantics.
3. `_rebuild_usage_snapshot` still does not publish. Publication still hardcodes idle.
   Reuse committed private capture without I/O, credentials or agent construction;
   memory-only mutation detection must withdraw/revoke stale capture rather than
   advertise it. Complete exact generation/no-churn/privacy matrix remains pending.
4. Operation/attention methods and actual submission/preparation/manual-compaction
   wiring remain unimplemented. Final usage must precede settlement; busy refusal,
   abort/cancel, original errors/results, retry/recovery and passive cooldown must
   retain their ordinary behavior.
5. Complete real Faux config-backed session, guarded fake reporter composition,
   surrounding auth/rate/compaction/bootstrap gates and final full/static gates.

## Read scope and limitations

Consumed current t5-code-test, lifetime-handoff-40, capture-wiring-35, routing,
root RESEARCH, supplied AGENTS/CLAUDE/docs RESEARCH, relevant actual session capture,
startup, publication and usage code/tests. Consulted KB Welcome, slo README/gotchas
read-only. Read shared engineering routing/ownership/testing, Python root,
application-service and declarative/named-argument/docstring guidance, coding rules,
cadence and exact code-test-review workflow. Canonical C was read in full in bounded
ranges (1–2175), including 7.9–7.11 and section 8.

Prerequisite closure is still incomplete: scope-plan bulk output truncated; domain
recipe only partially read; workflow SKILL, exact T5 tasks 2401–3720, B snapshot
contract and accepted review decisions still need complete reads. No claim that
prior handoff prose substitutes for those reads. This continuation does not close
the requested cohesive family. No artificial turn/dispatch/unit cap is asserted.

No TUI/headless changes, agents, commits, push/PR, reset/clean/stash,
global/live/specification/KB/other-worktree edits. Later T5 caller families and T6
independent review remain deferred as requested.
