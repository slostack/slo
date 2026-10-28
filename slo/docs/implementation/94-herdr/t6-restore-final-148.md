# T6 restore final 148 — INCOMPLETE

## Acceptance verdict

**READY withheld. No acceptance row was closed in this invocation.** The earlier 147 receipt remains historical evidence, not a newly executed gate. Neither a passing finite-family result nor repository completion is claimed.

The requested remaining evidence is still:

1. Current catalog/backend capability rejection through the second independent process's real CLI dispatch and mounted public submission, with the original saved single-model/pool policy retained and no fallback or pool subtraction.
2. Controlled current project-plugin trust refusal through that entry, demonstrating unchanged saved identity and the normal distinction between project-local trust and explicitly supplied plugins.
3. Actual blocked reporting state and rendered fixed safe error for the explicit refused user attempt, distinct from normal prompt-free restore; absence of secrets/private paths in that error.

## Read-only findings

Read `t6-restore-oracles-147.md`, the current parent test and entry helper, the trust store and relevant loader code, session eligibility references and the catalog eligibility method. The existing parent still parametrizes only `available` and `refused`; the latter removes the synthetic API key and tests credential refusal using public `session.invoke`. It does not implement catalog-capability refusal or mounted-input error assertions.

The current catalog gate in `src/agents/model_catalog/dao.py::ModelCatalogEntryDAO.backend_eligibility_message` rejects **OpenAI OAuth when `supports_chatgpt_codex` is false**. Merely changing that flag while retaining the helper's synthetic API-key credential will not exercise a refusal. A new child-local scenario must supply a synthetic OAuth credential at the resolver boundary as well as a validated current catalog entry, while retaining the real eligibility method and preventing refresh/provider construction. This is source analysis, not executable proof.

`src/agents/slo_agent/plugins/loader.py` explicitly defines CLI plugin paths as trusted by definition; the persisted project trust gate governs the project-local tier. A test that expects saved explicit plugin paths to be refused solely because project trust changes would assert the wrong policy. The controlled trust-change scenario must demonstrate refusal of the same project-local plugin while retaining the ordered saved explicit paths and their normal loading. No production policy alteration is justified by these observations.

## Actions and evidence

- No source, test, bootstrap, specification, shared-status, KB or other-worktree edits.
- Only this report was written.
- No test suite, Black or mypy run; no RED/GREEN increment started.
- No agents, commits, push, PR, reset, clean, stash, installation, live provider, live Herdr or terminal launch.
- Read-only shell check confirmed cwd `/root/Code/slo-94-herdr-integration/slo` and `/root/.pyenv/versions/slo-harness/bin/python` reported `Python 3.11.7`.
- `/usr/bin/dpkg -V coreutils` produced no output in that check. No command-stubbing suite ran afterward.
- `git status --short` showed existing broad in-flight modifications; they were not changed or reverted.
- No new full-gate result; supplied baseline 281 errors/58 files remains unwaived and was not reproduced here.

Prerequisite ingestion was **not completed**. AGENTS/CLAUDE/docs RESEARCH were supplied in context; selected routing, ownership/testing, Python, cadence, scope-plan, KB Welcome and OS ROLE files were read. This does not establish complete canonical C/T6/accepted-review, KB or framework-skill ingestion. A malformed parallel read request returned schema validation errors without file changes.

## Continuation boundary

Next work must finish prerequisite reads, then add one small failing parent assertion/scenario before changing the owned entry helper. Preserve the existing safety bootstrap, independent processes, literal advertised argv, immutable record/history checks and independent scalar oracles. Run the authorized safety and positive partitions after each green increment. Do not treat the source observations above as closure or replace the requested actual rendered/public-entry evidence with private helper calls.

Source-entry shim qualification remains unchanged: there is no installed-command equivalence, live restart or Herdr compatibility claim.

Accounting supplied by the user: same unfinished turn 1; started 1, completed 0, historical partial 1, dispatch 148, retries 0. Turn and dispatch budgets are unlimited. No numeric limit is asserted as a reason for acceptance or closure.
