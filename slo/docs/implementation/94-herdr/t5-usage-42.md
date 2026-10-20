# T5 committed usage continuation 42 — INCOMPLETE

Same unfinished turn 1: started 1, completed 0, historical partial 1,
dispatch 42, retries 0. Unlimited user turn/dispatch budgets; no agents ran.
This is a partial implementation, not finite-family READY or attention readiness.

## Changes and finite map

Only sessions/service.py and herdr/test_session_publication.py changed in code/tests.

| Boundary | Current implementation / evidence | Remaining |
|---|---|---|
| `_rebuild_usage_snapshot` | Synchronous publication after assignment; real reporter spy proves call and capture reuse without resolve/require/build/recapture | Full event no-I/O matrix and routed fallback composition |
| Startup | Publication after successful no-await adoption; existing failure/cancel capture tests retained | Publication failure/cancel cutoff assertions |
| History ensure | Publishes after successful persistence | Failure/cancel and first Faux persistence/save barrier |
| Rename | Publishes after successful rename; label omitted | Failed rename call-count assertions |
| Standard provenance | Finish captures/publishes; equal capture retains identity/generation | Complete provenance origin/mutation matrix; general attach immediate withdrawal |
| Policy selection | Existing model/reasoning/admission capture hooks reach new usage publication | Actual pool fallback/catalog refresh no-save/release composition |
| Stale mutation | Memory-only scalar/lexical source tuple, eligibility/provenance check; withdraw capture and increment once | Recovery at supported commit must not silently certify other unsupported changed inputs; malformed policy and identity completeness |
| Resume workspace | Separate `_herdr_history_persisted` fact avoids setting ordinary `_history_session_ensured` during observation | Complete resumed/explicit workspace matrix and failure refresh/reset cases |
| Actual Faux | Config-backed lazy factory patched before construction; real reporter; actual invoke then public usage refresh; 15 total tokens; rename keeps capture | Actual usage/save barrier, final usage before settlement belongs to later operation family |

Seven mutation cases now pass against real reporter: model, requested reasoning,
workspace, plugin paths, history flag, append prompt, pool priority. Old immutable
publication remains intact; repeated withdrawal does not churn generation. This
is not proof of every unsupported mutation or save/admission race.

The standard bootstrap initially caused an artificial None→equal transition
because general attach published before provenance finish. Regression now proves
standard bootstrap preserves capture identity/generation; intermediate general
attach publication was removed. **General attach still needs its own immediate
commit withdrawal without introducing that standard-path churn.** Current usage
publication detects the invalid provenance later. Do not call provenance complete.

## Executed commands and receipts

CWD `/root/Code/slo-94-herdr-integration/slo`; `pyenv which python` =
`/root/.pyenv/versions/slo-harness/bin/python`, Python 3.11.7;
`make test-env` = fallback. No venv/package/global changes.

Prefix H = `bash docs/implementation/94-herdr/t1-dao-check.sh` (adds DAO/projection).
P = `tests/agents/slo_agent/herdr/test_session_publication.py`.
S = P plus `tests/agents/slo_agent/herdr/test_session_capture.py`,
`tests/agents/slo_agent/test_session.py`, `tests/agents/slo_agent/test_session_usage.py`,
`tests/agents/slo_agent/orchestrator/test_bootstrap.py`.
All receipts below have `t5-42-<name>.log` and `.exit` in this directory.

| Receipt | Command | Actual result |
|---|---|---|
| usage-red | H P | 1 failed, 68 passed; exit 1 |
| usage-green | H S | 1 failed, 188 passed; exit 1 (bad assertion: reporter deduplicates equal publication) |
| usage-red-corrected | H P, hook temporarily removed | 1 failed, 68 passed; exit 1 (publish call absent) |
| usage-green-corrected | H S | 189 passed; exit 0 |
| commits-red | H P | 4 failed, 69 passed; exit 1 |
| commits-green | H S | 193 passed; exit 0 |
| withdraw-red | H P | 7 failed, 73 passed; exit 1 |
| withdraw-green | H S | 200 passed; exit 0 |
| workspace-red | H P | 1 failed, 80 passed; exit 1 |
| workspace-green | H S | 1 failed, 200 passed; exit 1 |
| workspace-green-corrected | H S | 201 passed; exit 0 |
| faux / faux-corrected | H S | 1 failed, 201 passed each; exit 1 (missing synthetic resolver credential) |
| faux-green | H S | 1 failed, 201 passed; exit 1 (ordinary totals require refresh) |
| faux-final | H S | 202 passed; exit 0 |
| provenance-red | H P | 1 failed, 82 passed; exit 1 |
| provenance-green | H S | 203 passed; exit 0 |
| format | poetry run black src/agents/slo_agent/sessions/service.py tests/agents/slo_agent/herdr/test_session_publication.py | exit 0 |
| surrounding | H tests/agents/slo_agent/herdr tests/agents/slo_agent/test_session.py tests/agents/slo_agent/test_session_usage.py tests/agents/slo_agent/orchestrator/test_bootstrap.py tests/agents/slo_agent/test_session_rate_limits.py tests/agents/slo_agent/test_session_manual_compaction.py | 1252 passed, 12 warnings; exit 0 |
| black | poetry run black --check src/agents/slo_agent/sessions/service.py tests/agents/slo_agent/herdr/test_session_publication.py | exit 0 |
| diff | git diff --check | silent; exit 0 |
| coreutils | dpkg -V coreutils | silent; exit 0 |

Workspace test initially assumed ensure overwrites existing metadata. Actual
FilesystemSessionHistoryStore preserves it. Corrected assertion requires the
ordinary ensure call with explicit workspace, preserves stored metadata, and
checks explicit workspace in private capture. No persistence owner was changed.
Corrected workspace assertion was not rerun RED against the previous implementation;
this evidence limitation remains explicit.

## Outstanding prerequisite and acceptance work

Read current routing/scope plan/checkpoint, root RESEARCH, relevant session and
capture/publication/lifetime source/tests; shared engineering/coding/Python
service/declarative/DAO/style guidance and exact workflow plus shared SKILL.
Read exact T5 samples 2401–3720, C capture sections 7.8/7.9 and publication/lifetime
parts, accepted independent turn-4 review. Supplied AGENTS/CLAUDE/docs RESEARCH
were available in context. Bulk KB/skill output truncated; some was reread but
complete actual-file ingestion of all requested material (especially B normative
publication contract and full C) is NOT claimed.

No full make test/smoke/lint was run: finite family is not complete. Historical
299 errors/63 files remains unwaived; fresh diagnostic attribution is pending.
No new ignores added. No attention/headless/app changes, agents, commits, external
publication, live Herdr/providers/windows, global/spec/KB/other-worktree edits,
or destructive Git operations. Existing partial work remains intact.

Before attention: close the remaining map above, strengthen unsupported-edit
recovery semantics and general attach commit handling test-first, run actual
Faux pool/catalog and real reporter save/admission barriers, complete no-I/O/error
matrix, then full make test/smoke/lint and changed-diagnostic attribution.
