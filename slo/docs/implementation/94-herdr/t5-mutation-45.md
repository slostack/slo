# T5 mutation continuation 45 — INCOMPLETE

Same turn 1: started 1, completed 0, historical partial 1, supplied dispatch 45,
retries 0. Unlimited turns and dispatches; no agents launched. No fabricated
workflow-budget stop. No attention/app/headless changes or shared-status edits.

## Owned changes and demonstrated corrections

Only sessions/service.py, orchestrator/bootstrap.py and
herdr/test_session_mutation.py changed, besides this receipt and its logs.
Existing partials and parallel publication-compositions work preserved.

- Bootstrap checks policy/identity after attachment as well as after tool
  construction. Final additions must be the exact ordered built tool identities
  and standard prompt additions, with no hook. Unexpected final values cannot
  attest themselves. Malformed final scalar policy refuses without throwing
  through successful ordinary attachment.
- Session raw config fields are revalidated with the existing SessionConfigDAO
  strict contract, not serialization coercion. Nested pool sequence uses its
  existing strict DAO; entries reuse immutable scalar validation/provider checks.
  False-like dict/string/tuple containers no longer impersonate supported empty
  lists; bool/int equality cannot preserve malformed pool capture.
- HerdrPolicySourcesDAO locally replaces opaque numeric tuple permissions with
  named configured/effective reasoning, model, history, paths and pool comparisons.
  Model selection owns model/pool/effective reasoning; reasoning commit owns only
  effective reasoning. Existing precommit guards and sticky invalidation remain.
- A local autouse Faux factory is installed before config-backed construction.
  Existing suite HERDR stripping, force-disable, actual fake-only spawn guard,
  isolated SLO_HOME and terminal guard remain active.

## Contract interpretation

Canonical supplied path resolves with the missing separator to
`/root/Code/specifications/projects/slo/specifications/94-slo-tui-redesign/herdr/94.b.2-session-publication-and-native-restore.md`.
Read C capture/provenance 7.8–7.9, exact branch table and 7.10–7.11;
T5 attachment C08–C11; accepted independent-review-turn4 in full.
C says unsupported out-of-band mutation invalidates eligibility and unsupported
private-object mutation is not restorable. It does not specify a gateway to
recover lost provenance by selecting a model. Therefore continuation 44's
unconditional recovery blocker is not established by this contract. No recovery
requirement or reset API was invented. Ineligible-then-equal generation semantics
must not be confused with authorizing arbitrary formerly observed mutation.

## Evidence

CWD `/root/Code/slo-94-herdr-integration/slo`. `pyenv which python`:
`/root/.pyenv/versions/slo-harness/bin/python`; Python 3.11.7.
H = `bash docs/implementation/94-herdr/t1-dao-check.sh` (approved fallback,
adds DAO/projection tests). All actual output and exit files use prefix
`t5-mutation-45-` in this directory.

| Receipt | Command / result |
|---|---|
| safety | H mutation module: 81 passed |
| red1 | H mutation module: 4 failed, 81 passed; final tools/system/append/reasoning |
| green1 | H mutation + capture + publication + orchestrator/bootstrap: 140 passed |
| red2 | H mutation: 8 failed, 89 passed; false-like containers and bool pool scalars |
| green2 | Same four-module surrounding: 152 passed |
| refactor | Same four-module surrounding after named comparison: 152 passed |
| red3 | H mutation: 1 failed, 101 passed; malformed tuple pool sequence |
| green3 | Same four-module surrounding: 157 passed |
| red4 | H mutation: 1 failed, 102 passed; malformed final attach exception |
| green4 | Same four-module surrounding: 158 passed |
| surrounding | H herdr directory, test_session.py, test_session_usage.py, orchestrator/test_bootstrap.py, test_session_rate_limits.py, test_session_manual_compaction.py: **1336 passed, 18 warnings**, exit 0 |
| black | poetry run black --check on three owned files: unchanged, exit 0 |
| diff | git diff --check: silent, exit 0 |
| coreutils | dpkg -V coreutils: silent, exit 0 |

No new full make test/integration or lint claim. User deferred full integration;
7532-pass receipt is retained historical evidence, not post-edit proof. Prior
299/63 static baseline remains unwaived; parallel-lane correction is not asserted.

## Exact remaining before finite-family READY

1. Complete finite malformed-source matrix against actual DAO contracts, including
   malformed nested entry object types and malformed policy before bootstrap's
   initial source snapshot. The initial direct `_herdr_current_policy_sources()`
   call can now raise on malformed preattachment input; unlike final comparison,
   it is not yet isolated. Add production RED, fix within existing owners, run
   surrounding. Do not weaken strict validation or bless malformed values.
2. Verify construction-time source validation preserves ordinary unsupported
   custom-config lifecycle behavior and does not unnecessarily turn optional
   eligibility refusal into construction failure. Current validation executes
   from construction; standard valid configurations pass surrounding evidence.
3. Finish required prerequisite ingestion: actual AGENTS/CLAUDE/root and docs
   RESEARCH, frozen routing/scope plan, shared engineering/coding/Python DAO/service/
   declarative/workflow overview and KB entry/index/gotchas were read here.
   Full remaining T5 task attachments, KB build-rule companions and selected
   test recipe/full workflow have not all been read in this continuation. Do not
   claim complete routing ingestion based on the prior routing author's report.
4. Complete final finite coverage/diff self-review after those corrections,
   including valid aliases and mutation-free supported commit comparisons.
   Existing tests pass, but this is not exhaustive family acceptance.

No spec/global/live/other-worktree edits, commit/push/PR, reset/clean/stash,
installation, providers, real Herdr or terminal windows. No independent review or
completed workflow claim.
