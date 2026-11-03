# Turn4 dispatch1 — AGG-01/02 finite Code+Test repair

**READY for independent affected final review ONLY. Not aggregate acceptance or feature completion.** All author gates below complete on revised content. Independent affected review and then separate independent completion remain required; no commit authorized here.

Counters preserved: **4 started / 0 completed; turn1 partial15; turn2 partial5; turn3 partial2; turn4 active dispatch1/20; max60; zero execution retries.** Explicit legitimate revision after turn3 REVISE, not retry of an abort. No agents, staging, commit, push, host/package changes, new framework or exclusions. All eight previous repair IDs remain closed by `final-review-turn3.md`; not reopened.

## Scope and routing

Read `final-review-turn3.md` fully, turn3-repair/current acceptance-routing/handoff/ledger, current SLO and relevant README reference/style/testing, KB Welcome → slo README/gotchas. Authority only original DC01–09 under `/root/Code/specifications/projects/slo/specifications/96-agent-message-queue/revised/01-durable-composer/`; directly checked DC08 §6.1 and DC05 §5.7 for these boundaries. No sibling source or product expansion.

Selected installed root `/root/.local/share/pipx/venvs/slo/lib/python3.11/site-packages/skills`: exact orchestration/workflows/code-test-review.md and shared workflow; engineering routing/testing/ownership; coding solution-design/coding-rules/naming/code-design/declarative/test-verification/code-test-loop; Python conventions/build-domain-features/named-arguments/method-docstrings/declarative. Existing acceptance routing reused. Python/Pydantic boundary schema unit checks plus real existing legacy-admission/slash/CLI/TUI journeys. No new service, CLI verb, Textual lifecycle, HTTP client, ORM or test infrastructure; those build recipes do not create extra obligations for this finite metadata/call-syntax repair. No applicable personal override. Root/docs RESEARCH absent; not recreated under scoped routing. No novel architectural lesson or substantial reusable discovery to add to external KB.

## Repairs and test-first evidence

### AGG-01

Only four production field declarations changed:
- `LegacyInboxAdmissionDAO.message_id/kind/text`: described `Field(description=...)`, no default, type/validator/base unchanged. Original canonical UUID, three Literal choices, exact nonblank bounded submission validation, strict/frozen inheritance retained.
- `SlashCommandResultDAO.messages_command`: described `Field(default=None, description=...)`; optional type/default and result validators/config unchanged. No new frozen policy on SlashCommandResultDAO.

Added one schema regression in `tests/agents/slo_agent/messaging/test_legacy_admission.py` and one in `tests/tui/test_messages_command.py`. They inspect all four descriptions and required/default/nullable/Literal shape, reject missing legacy content and wrong kind, prove frozen legacy content, and retain slash malformed-action/conflicting-refresh rejection. Existing legacy invalid UUID/blank/oversize/surrogate/authority tests and every prior journey assertion unchanged.

**RED before production edit:** `schema-red` exit1: **2 failed,12 deselected,2 warnings,0.37s**, each KeyError `description` at the intended new schema check. **GREEN:** complete two files `schema-green` exit0: **14 passed,4 warnings,4.08s**. No invented behavioral defect beyond undocumented schema.

### AGG-02

Exactly19 decorators from the aggregate report changed, across9 test files; two existing positional arguments became `argnames=` and `argvalues=`. Original bodies captured before edits in `logs/turn4-before-<filename>`; exact locations recorded `logs/turn4-parametrize-sites.json`. No historical decorators changed. Black wrapped two scoped lines/blocks only (failure matrix and slash Field).

`logs/turn4-preservation.py` is an evidence-only comparison script, not a test framework. It normalizes just the19 captured old decorator calls to keywords and compares complete ASTs with revised files: **identical ASTs including values, IDs, assertions and all other code**. Collection comparison proves all12272 prior selected node IDs in identical order; only the two intended schema tests added. Exact21 e2e excluded node IDs/order unchanged; full list in `turn4-preservation.log`, matches aggregate enumeration. No tests deleted/disabled, no marker/filter policy change. Syntax-only conversion needs no artificial RED test; pre-edit collection and exact AST equivalence are preservation evidence.

## Environment and exact receipts

Cwd `/root/Code/slo-message-queue/slo`; existing approved slo-harness Python3.11.7, explicit VIRTUAL_ENV/PATH and same synthetic environment as acceptance routing. Complete reproducible exports/receipt helper: `logs/turn4-env.sh`. Each receipt below has `.command`, `.exit`, `.log`, `.started`, `.finished` under `logs/turn4-<name>`. Commands are shell-escaped exact argv; environment sourced before execution. No packages or Makefile/pyproject changes.

| Receipt | Exact command | Result |
|---|---|---|
| schema-red | `poetry run pytest tests/agents/slo_agent/messaging/test_legacy_admission.py tests/tui/test_messages_command.py -k schema -q` | exit1;2failed12deselected2warnings |
| schema-green | `poetry run pytest tests/agents/slo_agent/messaging/test_legacy_admission.py tests/tui/test_messages_command.py -q` | exit0;14passed4warnings |
| affected / affected-final | `poetry run pytest tests/agents/slo_agent/messaging/test_finite_completion.py tests/agents/slo_agent/messaging/test_legacy_admission.py tests/cli/test_app.py tests/cli/test_headless_messaging.py tests/tui/test_composer_prerequisites.py tests/tui/test_composer_visual_matrix.py tests/tui/test_inbox_displacement.py tests/tui/test_legacy_inbox_bridge.py tests/tui/test_messaging_failure_matrix.py tests/tui/test_messaging_session_controls.py tests/tui/test_messages_command.py tests/tui/test_slash_command_registry.py tests/cli/test_typer_dispatch.py -n 6 -m 'not e2e' -q` | both exit0;159passed73warnings;18.38s / final19.98s |
| collection-before / collection-after | `poetry run pytest --collect-only -q -p no:cacheprovider` | both exit0;12272/12293 →12274/12295;21deselected;2warnings each |
| e2e-before / e2e-after | `poetry run pytest --collect-only -m e2e -q -p no:cacheprovider` | both exit0;exact21selected unchanged;12272→12274deselected;2warnings each; NOT e2e execution |
| preservation | `python release-evidence/96-durable-composer/logs/turn4-preservation.py` | exit0;19exact AST conversions and exact collection preservation |
| **full** | **`make test PYTEST_WORKERS=6`** | **exit0;12274passed1268warnings;623.09s**;2026-11-03T10:41:12Z–10:51:37Z |
| lint | `make lint` | exit0;mypy src/tests981files clean |
| black | `xargs -a release-evidence/96-durable-composer/logs/turn3-black-paths.txt poetry run black --check` | exit0;all60cumulative changed/untracked Python paths unchanged |
| diff | `git diff --check` | exit0;empty |
| coreutils / coreutils-final | `dpkg -V coreutils` | both exit0;empty;last after affected-final |

`format.command` also records exact13-path scoped Black invocation;2reformatted11unchanged. All production/test edits finished before full started; no subsequent src/tests edits. Current full **supersedes historical12272** as final revised-source evidence. No reported execution skips/failures in full/affected green runs. Warnings retained, not suppressed or certified harmless; aggregate turn3 historical warning investigation remains applicable only within its stated limits, no new warning cleanup claim.

## Regression repeats and preservation

No changes to `test_composer_transcript_identity.py`, `test_chat_transcript_precise_scroll.py`, `test_herdr_all_owner_cutoffs.py`, their helpers or lifecycle implementation. Retain **three** prior complete-file `-n 6` repetitions (`turn3-repeat-1/2/3`): each47passed40warnings/exit0,54.04/53.56/55.73s. No need to reduce or replace that evidence; conditional rerun trigger (touching those paths) did not occur. Current full also executes all three. No claim new repetitions ran in turn4.

Turn4 source/test inventory:2production (`messaging/dao.py`, `tui/slash_router.py`),11tests (the9AGG-02 files plus2schema-test files), local evidence only. User README/SLO/docs/ASCII and original specifications untouched; no unrelated formatting. Author self-check confirms finite corrections, preserved validation/default/frozen semantics and exact test AST/collection equivalence, not independent review. Original83-row maps and all prior eight closures reused from completed aggregate review, not re-audited or reopened.

## Next gate

Independent affected final review of **AGG-01/02 only**, reusing unchanged original maps, eight closures, exact exclusion audit and warning disposition from `final-review-turn3.md`. Then a **separate independent completion check**. Both remain OPEN;4started0completed is unchanged by passing author gates. No commit until both pass and separate user authorization permits it.
