# T6 mounted parity 124 — INCOMPLETE family; bounded proofs green

## Authority / scope

Same unfinished turn 1: started 1, completed 0, historical partial 1, supplied dispatch 124, retries 0. User unlimited turn/dispatch limits supersede old limits. No agents dispatched. No independent review or full T6 completion claim.

Changed only `tests/integration/test_herdr_full_flow.py`, unique helper `tests/integration/herdr_parity_124.py`, this receipt and `t6-mounted-parity-124/` evidence. Preserved other work. No production, canonical spec, shared status, global, other-worktree, commit/push/PR changes. Two-process safety HOLD honored: neither its files nor integration directory/full suite collected or run. Existing Faux factory, registered regular fake executable, identity/containment guards, HERDR stripping, safe fallback and terminal guard retained.

## Delivered finite cases

- Three exact parity cases: single, retry, fallback, each runs disabled → outside → enabled actual mounted PromptInput/tool/session/history journeys. Complete ordered model dumps of events and loaded durable events compare, including nulls, metadata, sequence, iteration, usage, content and tool fields. No events or payload fields dropped.
- Normalization: `recorded_at` wall clock; generated session/event/turn/block/tree entry identities and parent references consistently mapped through one per-journey identity map. Tool IDs and tool timestamps are deterministic fixture values and NOT normalized. No runtime/duration fields excluded. Initial failures were missing tree entry-ID normalization, not production failures; unified diagnostic diffs retained.
- Disabled/outside retain empty actual CLI capture and absent integration root assertions. Added forbidden-call guards for reporter assembly and transport spawn. This does not independently spy on every low-level filesystem write attempt during constructor/build.
- Two stale-clear cases: actual known Faux usage and durable context, session cooldown commit, controlled history-load OSError → actual unavailable context refresh, then cooldown zero or cleared. Actual CLI must clear context/cooldown before the following nonempty token patch; final public snapshot omits both. No projector replacement. Initial setup failures were missing credential control and an unmetered Faux response leaving no next token patch; corrected fixture now supplies real usage metadata.
- Four privacy cases use explicitly SYNTHETIC OpenAI/Anthropic/Kimi/OpenRouter-labelled credentials/session labels and unique private workspace/plugin paths. They are four sentinel cases, NOT four provider execution lanes (all execute the existing OpenAI-configured Faux boundary). Actual immutable capture and durable private record retain allowed workspace/plugin paths; credential-like name is absent. Public final snapshot, actual argv, actual session events, Herdr-module diagnostics, non-restore integration state and close outcome are scanned. Initial diagnostic selector matched the checkout name `slo-94-herdr-integration` and accidentally included ordinary session logs; corrected to exact `/slo_agent/herdr/` module scope. Ordinary Slo diagnostics are not claimed path-free.

## Remaining obligations — no READY family claim

1. Privacy is not complete: no sentinel-bearing prompt/tool/error scenario or failing child output; no injected arbitrary model/provider/effort labels; only final snapshot/close outcome rather than every published snapshot and transport/viewer outcome. Diagnostics scan may be empty on success. Native provider-specific behavior is not tested.
2. Disabled zero-I/O proof lacks comprehensive write-attempt observation before construction; assembly/spawn guards and root/capture absence are bounded evidence.
3. Normalizer sensitivity tests (semantic mutation must fail, reference topology preserved) still needed; implementation currently exercised only by composed comparisons.
4. Required complete affected-source/read closure is not established. Read supplied AGENTS/CLAUDE/docs RESEARCH, actual root RESEARCH, routing/scope-plan, close123 receipt, canonical overview/T6 B26 C31 D09 O01–O03, B/C/D 8–10 and accepted turn4 review. Read shared engineering routing/testing/ownership, coding rules/cadence/declarative, Python root/Faux/declarative/named arguments/docstrings, Textual and workflow SKILL; KB Welcome/README/gotchas, Makefile, isolation/conftest, existing composed fixture, stream/history schemas and relevant session/reporter/projection source ranges. This is NOT all affected owner bodies or all accepted-review companions. Bulk read truncation at overview/KB opening was revisited; no inherited full-read claim adopted.
5. Unified retry/fallback plus BOTH viewers in one story, 64 lifetime matrix, G1/G2/quarantine remain NEXT family/parent work, not closed here.
6. Full non-E2E prohibited under hold; supplied global 281 errors/58 files remains UNWAIVED, not rerun. Live compatibility, actual viewer paint and independent review remain pending.

No demonstrated production defect found or production RED suppressed. No skips/xfails/production patches.

## Executed verification

CWD `/root/Code/slo-94-herdr-integration/slo`. Verified `PYENV_VERSION=slo-harness pyenv which python` → `/root/.pyenv/versions/slo-harness/bin/python`; Python 3.11.7. Existing safe fallback helper used; no dev environment sourced or installation.

Each pytest invocation is `PYENV_VERSION=slo-harness bash docs/implementation/94-herdr/t1-dao-check.sh <explicit paths>`; helper includes 62 foundation cases. Counts overlap, do not sum.

| Receipt basename | Explicit selection | Result |
|---|---|---|
| parity | owned exact parity test | 3 failed, 62 passed (tree IDs) |
| parity-detail / parity-diff | exact parity `[single]` | 1 failed, 62 passed; diagnostic refinement |
| parity-final | owned exact parity test | 65 passed, 23 warnings, 52.15s |
| clear / clear2 | owned stale-clear test | 2 failed, 62 passed; fixture issues above |
| clear3 | owned stale-clear test | 64 passed, 4 warnings, 3.06s |
| privacy | owned synthetic privacy test | 4 failed, 62 passed; overly broad diagnostic scope |
| privacy2 | owned synthetic privacy test | 66 passed, 6 warnings, 4.24s |
| affected | `tests/integration/test_herdr_full_flow.py tests/tui/test_herdr_activation_composed.py tests/tui/test_herdr_attached_composed.py` | **97 passed, 56 warnings, 115.61s, exit 0** |

Final `black --check` and `mypy --follow-imports=silent` on exactly the two owned Python files: exit 0, mypy clean (2 files). `git diff --check`: silent exit 0 (untracked owned files are not covered by this check; reviewed source and formatted them). `dpkg -V coreutils` silent after each run, final receipt exit 0. Full outputs/exits in `docs/implementation/94-herdr/t6-mounted-parity-124/`. This bounded result is not global static/full-suite certification.
