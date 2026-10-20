# T6 privacy contract 131 — INCOMPLETE: explicit security-scope decision required

## Disposition

The eight REDs are genuine configured-credential disclosures in ordinary Slo `tool_result` events, **not demonstrated Herdr-wire disclosures and not intentional user text**. Preserve them unwaived. The accepted Herdr contract does not mandate an all-provider transcript sanitizer; it explicitly chose omission instead of credential-based redaction. The user's stricter public-stream requirement remains binding, but a correct all-provider implementation needs security-lifecycle ownership beyond the allowed session/redactor-only narrow correction. No production/test/harness change was made. No claim of an impossible fix; the blocker is authorization for the necessary scope, not capacity or workflow budget.

Same unfinished turn 1: started 1, completed 0, historical partial 1, supplied dispatch 131, retries 0; unlimited turns and dispatches. No agents dispatched. Existing dirty work preserved. Only this report and `t6-privacy-131/` repository receipts were written. A temporary concatenation of read-only skills was also made at `/tmp/privacy-skills-read131`; it is not product code or evidence of implementation. No shared-status, specification, KB, other-worktree, Git mutation, global configuration or live action.

## Routing and investigation plan

Task: contract/security-boundary adjudication with bounded offline verification. Stack: Python 3.11.7, LangChain/LangGraph, asyncio, Pydantic, Textual/Faux and registered temp fake CLI. Read supplied AGENTS/CLAUDE/docs-RESEARCH, root RESEARCH, actual scope-plan/routing, KB Welcome → slo/README (actual index) → gotchas. Read committed engineering routing/testing/ownership, coding rules/cadence/declarative, Python conventions/Faux/declarative and workflow SKILL. No new CLI/framework/ORM/provider recipe or independent workflow review is claimed.

Plan executed: read diagnosis 130 and handoff 129; compare exact B/C/D privacy clauses and accepted review; trace actual admission/readiness/factory/refresh/publication/history owners; reproduce RED and continue safe existing privacy/viewer/publication branches; retain RED and state the required scope choice. Two-process HOLD remains: no full make gate or integration-directory collection, no two-process test/helper selected.

## Exact contract and accepted decisions

H = `/root/Code/specifications/projects/slo/specifications/94-slo-tui-redesign/herdr` (read-only).

- **B §7.6, lines 359–361:** “Always omit `model`, `provider`, `effort` and `session` tokens, in both profiles”; “No redactor/cache/credential resolver is added or called. Rename and credential rotation cannot invalidate safe-label preparation because no free-text label is ever prepared or published. This is an intentional narrower product view, not a claim that the existing OpenRouter-only I/O redactor covers all providers.” This explicitly rules out using Herdr as the owner of global sanitization.
- **B lines 2042–2047:** inject four-provider sentinels into arbitrary name/model/effort inputs while blocking credential store/resolver access; real prompt/usage publication must have zero credential lookup and no sentinel in “public snapshots/argv/diagnostics” before/after rename and rotation. This tests the projection, not native admission to four providers.
- **B §8, lines 2184–2185:** “secret sentinels in events, environment and failing child output; no sentinel in argv/logs/sequence files.” Here events are explicitly secret-bearing **inputs** to the reporting privacy test.
- **B §9, lines 2208–2209:** “No content/credential leak across report argv, logs or integration state.” Explicitly permitted private restore paths are distinguished from public report argv/logs/sequence state.
- **C §8:** “Headless: stdout JSONL unchanged”; **C §9:** “Reporting failures cannot alter original errors or results” and “Normal Slo behavior is unchanged when disabled or outside Herdr.” C §7.8 at 544 says capture “reads no credentials, files or event content”; line 627 prohibits event-path credential lookup. These do not prescribe sanitizing ordinary tool history or model messages.
- **D §8, line 662:** “Secret sentinels across prompt/tool/error must be absent from all reporting logs/argv/state. Allowed private config paths appear only in private restore records; assert their absence from public snapshots, command argv, events, diagnostics and sequence state. Private configuration is not forbidden from its own explicitly private storage.” The second sentence prevents integration-owned private configuration from escaping in events; it does not repeal the first sentence's reporting scope or prohibit ordinary conversation/tool content in Slo.
- **Subordinate publication source, lines 247–260:** “The reporter must not publish” prompt/answer/thinking/tool input/output, authentication data or raw errors. Its reason explicitly says “Herdr already displays terminal output to authorized viewers.” It is not an all-provider Slo transcript-redaction specification.
- **Accepted `review-evidence/independent-review-turn4.md`, Prior closure table:** original F1 closed through omitted arbitrary labels, fixed canonical values, “No I/O redactor added.” Its architectural assessment says “No new public history event or provider change.” Earlier turn-2 independent review lines 53/61 explicitly calls this a product narrowing, not an invented all-provider redactor, and identifies the existing redactor as OpenRouter-specific with credential reads. Turn 4 approves specification breakdown only, not implementation acceptance.

**Adjudication:** the canonical reporting test must distinguish report-facing snapshots/commands/results/notices/integration state from ordinary Slo events. Appending every session event to the forbidden-secret scan overextends the historical Herdr-only requirement. It is nevertheless a valid regression for the user's newly explicit stronger public-stream requirement. Do not erase it, mark it intentional conversation, or call the feature green by reclassifying it. B's no-redactor decision is specifically Herdr ownership; a separately authorized ordinary Slo security change could satisfy the stronger requirement without changing that decision.

## Actual credential lifecycle: no reusable all-provider operation capture

| Boundary | Actual behavior and consequence |
|---|---|
| `auth/credential_resolver.py:46–100` | One ContextVar holds one optional CredentialDAO. Operation binding is explicitly admitted OpenRouter; not an all-provider secret collection. `operation_credential()` is lookup-free. |
| `credential_resolver.py:102–150` | `redact_openrouter_text` resolves the effective OpenRouter credential each call, then redacts effective and captured tokens only if provider is OPENROUTER. Handles literal/JSON/URL variants. Resolution failures fail closed without an eligible capture. Calling this on every event neither fixes OpenAI nor meets lookup-free publication. |
| `sessions/service.py:4993–5018` | `_prepare_run_snapshot` returns immediately for injected/direct-only sessions. Only configured OpenRouter paths resolve before/after preparation and retain `_admitted_openrouter_credential`. Catalog preparation retains OpenRouter provenance, not secrets for every provider. |
| `sessions/service.py:5070–5116` | OpenAI eligibility has a local credential, expressly not retained. `_ensure_agent_ready` returns immediately for warm/injected agents. Lazy factory binding receives only the OpenRouter capture. |
| `sessions/service.py:5135–5163` | Readiness loops all configured pool providers and obtains a local credential via existing require; awaits `refresh_if_stale` but discards its returned credential. Keeping that pre-refresh object would not reliably match the token used by the factory. |
| `auth/credential_refresher.py:89–205` | OAuth refresh can return a different object after locked store reread/refresh/persist. OpenAI and Anthropic support refresh; API-key/nonstale cases return original. The session currently relies on subsequent factory resolution, not a shared publication capture. |
| `agents/base.py:436`, `:541–559`, `:852`, `:962` | Anthropic, OpenAI, OpenRouter and Kimi each call require at their actual build boundary. OpenAI validates the captured credential and passes it through its lane builder without another lookup. Credentials become provider-client state, not a public sanitization context. |
| `agents/base.py:create_pool` | Builds each member through create, keeps model objects; no supported aggregate credential capture result. `LLMBuildResult` is model/caching capability, not a secret envelope. |
| `sessions/service.py:3420–3433` | Prompt scope binds admitted OpenRouter and clears it in finally; there is no corresponding all-provider lifetime. |
| `cli/headless.py:451–457,892` | Retains an observed operation capture across the stream task/terminal cleanup, applying existing OpenRouter sanitization. It cannot supply missing direct-provider capture to interactive subscribers. |
| `history/filesystem_store.py:621,779,791,1137` | Existing OpenRouter-only sanitization applies to transcript/metadata/events/rewrite. Changing that method's provider semantics would also change private history, violating the requested narrow public/private separation unless deliberately designed. |

A session-local `self._secret = credential.access_token` at readiness would pass this Faux fixture but be misleading: refresh replacement, factory rereads, warm agents, mixed pools, injected agents and rotation are not solved. Reading SDK private fields would create a provider-specific introspection contract, not reuse an existing capture. Extending the current single OpenRouter binding into a multi-provider captured sanitizer requires explicit retention/clearing and factory handoff policy, not a one-line public dispatch fix. Do not change `require` to silently populate a global secret set.

## Leak and baseline attribution

`tests/integration/test_herdr_full_flow.py:619–623` raises a configured synthetic credential from the actual NowTool invocation, with a separate intentional conversation string. The real executor (`tool_execution/executors.py:123–129`) logs the exception and makes `Error: {exc}` the terminal ToolMessage content. Session `_dispatch_event` (`:5862`) forwards it to plugins/subscribers unchanged. The test adds all events at line 718 and fails at line 733. No real credential was used or dumped.

The four parameter labels are sentinel categories, **not four provider executions**: all sessions use gpt-5.4 and the resolve patch returns an OPENAI CredentialDAO for every requested provider. Native factory is Faux. Correct security tests must not claim this proves all-provider captures.

`preexisting-owners.diff` is empty for resolver, factory, refresher and executor versus HEAD. `head-dispatch.txt` records HEAD's same pass-through dispatch body (initial repository-relative git-show spelling was corrected to `HEAD:./...`). This establishes the causal raw-content behavior predates this work; it is not a fully executed historical-checkout baseline. The leak is an ordinary Slo security defect, unwaived. Herdr snapshots/argv are not identified as the leak by this failure.

## Required user decision — exact options

**Recommended: authorize a separately bounded ordinary-Slo public-output security change, while retaining Herdr omission/no-lookup.** Explicit authorization should cover actual factory capture (`src/agents/base.py` plus its typed build result/graph handoff if needed), resolver's existing context, session public dispatch/lifetime, headless delivery and their tests. Do not authorize a global secret store or disk lookup per event. Required decisions before implementation:

1. Public scope: plugins/subscribers, interactive transcript, headless JSONL, delayed outcomes and logs versus private ToolMessage/model replay/history. The current executor also logs raw errors; event-only sanitization does not promise global log privacy.
2. Secret set: actual admitted API/access tokens (and whether refresh tokens/cookies are included), old/current values across rotation, warm-agent lifetime and pool membership; define injected-agent behavior without harvesting unrelated credentials.
3. Compatibility: preserve provider request credential selection/refresh and private model/history semantics. Sanitize copies at public boundaries; do not broaden the existing history redactor accidentally. Decide whether a credential split across streaming chunks must be protected—literal event replacement alone cannot guarantee it.

Alternative: explicitly accept **Herdr-only acceptance scope**, retain this ordinary-Slo security bug as a separate unwaived blocker, and authorize splitting the test into (a) canonical reporting projection privacy and private-path nonleak checks and (b) retained strict public-tool-event RED. This is not permission to delete the RED or declare the stronger requirement satisfied. No such test split was silently made here.

A session/redactor-only patch retaining readiness values is rejected: it would make eight fixture cases green while failing the actual all-provider lifecycle. Blanket suppression of tool errors is also rejected: it changes ordinary diagnostics and does not solve other publication paths.

## Fresh verification and remaining branches

CWD `/root/Code/slo-94-herdr-integration/slo`; `PYENV_VERSION=slo-harness pyenv which python` → `/root/.pyenv/versions/slo-harness/bin/python`; Python 3.11.7. Existing `t1-dao-check.sh` inspected and used its explicit synthetic fallback; no environment file sourced. Root guards strip HERDR/disable real windows and permit only independently registered fake executables. No harness edits.

Commands (helper adds the same 62 DAO/projection cases; counts overlap):

```sh
PYENV_VERSION=slo-harness bash docs/implementation/94-herdr/t1-dao-check.sh tests/integration/test_herdr_full_flow.py::test_mounted_synthetic_labels_and_private_paths_do_not_reach_reporting tests/integration/test_herdr_full_flow.py::test_pilot_configuration_and_typed_viewer_journey
PYENV_VERSION=slo-harness bash docs/implementation/94-herdr/t1-dao-check.sh tests/agents/slo_agent/herdr/test_session_publication.py::test_usage_commit_publishes_latest_without_capture_or_io tests/agents/slo_agent/herdr/test_session_publication.py::test_faux_submission_publishes_committed_usage
```

- `families.log/.exit`: **8 failed, 78 passed, 50 warnings, 23.19s**, exit 1. Exactly all eight tool-error variants remain RED; eight ordinary-content variants and eight existing attached/detached viewer journeys pass, in addition to foundation cases.
- `publication.log/.exit`: **64 passed, 3 warnings, 1.62s**, exit 0. Existing real publication preserves capture and numeric facts; existing require/path/recapture negative checks pass. These checks block require, not every resolver/store method; do not overclaim a complete four-provider rotation/zero-I/O matrix.
- `coreutils.log`: empty, exit 0 after both suites; `git diff --check` empty, exit 0.
- No Python edits, so no new Black/mypy gate; inherited global static failures remain unwaived and were not remeasured. No full suite under HOLD.

Still not completed: actual session/provider-failure sentinel matrix, full configured-label/rotation with independent all-resolver/store blocking, every high-level viewer-outcome privacy category and schema-omission sensitivity. Existing safe branches were continued above; no additional tests were authored under this report/receipts-only outcome. These are real remaining acceptance items, not replaced by the contract analysis. Separate two-process/lifetime/live and independent acceptance gates remain pending.

**Final: INCOMPLETE.** Contract boundary and capture prerequisite are resolved with evidence; strict public-event privacy remains RED pending the explicit ordinary-Slo security scope decision. Neither baseline attribution nor narrower canonical reporting scope is a waiver.
