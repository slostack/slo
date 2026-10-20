# Dispatch153 — C-provider READY (bounded offline only)

Turn1: started1, completed0, historicalpartial1, retries0; unlimited turns/dispatches. No subagents. This is author Code+Test evidence, not independent review or feature completion. Live DEFERRED; Herdr compatibility UNVERIFIED.

## Authority and scope

Verified branch `feature-94-herdr-integration`, origin `https://gitlab.com/core-27/slo.git`, merge-base `d0e3a756689f2675e5507034d43cd8b272d3c6b8`. Existing dirty work preserved. Writes are exactly the eleven C-provider files in `t6-audit-static-plan-142-receipts/C-provider.files`, two dedicated offline regressions below, and this report/receipts. No dependencies/configuration/guards/shared status, Git mutations, installs, global/KB changes, live calls or full suite.

Consulted AGENTS first (full supplied context plus initial disk read), CLAUDE, root and supplied maintained RESEARCH, actual Makefile/helper, routing/scope-plan,142/147/151/152 reports and C allocation. Initial oversized document reads truncated; bounded routing/root/scope reads and applicable C guidance were subsequently consumed. This is not a fresh full-feature/sample audit. KB Welcome, actual slo README/gotchas consulted. Effective SLO_SKILLS_DIR is installed pipx skills; exact installed workflow absent, so used authoritative worktree `skills/design-and-analysis/workflows/code-test-review.md`. Loaded installed engineering routing/ownership/testing, coding rules/cadence/shared declarative, Python root/declarative/named-arguments/docstrings/Faux-agent guidance. Python/Pydantic/LangChain adapter and isolated regression scope; no CLI/TUI redesign. Current explicit repair authorization supersedes historical read-only labels.

## Repairs and behavioral evidence

- `faux.py`: declared per-instance queue factories followed by owned typed initialization; upstream tool forms and keyword-only tool_choice accepted. Choice remains intentionally unused, as before; no routing policy added. Existing scripts, clone behavior and underrun preserved. Tests add schema/class/callable/BaseTool inputs, three choice values, independent queues/script lists and synchronous streaming underrun. Static diagnostic was RED before declaration repairs; behavioral preservation tests pass.
- `assistant_chunk_normalizer.py`: read-only `Mapping[str, object]` collection; no coercion or branch changes. Existing whole normalizer module passes.
- `openai_codex.py`: pinned SDK inspection confirmed aliases openai_api_key→api_key and openai_api_base→base_url. Constructor now uses `SecretStr` and `base_url`. New `test_codex_wire_regression.py` passes BEFORE and AFTER: exact POST URL, full bearer token, account/originator/beta/session/request headers, complete Responses JSON body, one HTTP attempt on429. Existing full Codex wire module passes. No live HTTP; MockTransport only.
- `anthropic_claude_code.py`: genuine defect reproduced first through public `ainvoke`, including real bound RunnableBinding. Three cases failed with `AttributeError: ClaudeCodeChatAnthropic has no attribute kwargs` (62 foundation tests passed). Pinned SDK `_agenerate` forwards invocation kwargs to `_format_output`; binding owns original tools, not model state. Normalization now consumes those request-local schemas. No global/bound mutable tool state or invented field. New `test_anthropic_binding_regression.py` proves absent tools, canonical Read/read, custom case-preserving myTool/MYTOOL, outgoing schemas and both inbound representations. This specifically fixes nonstream output formatting; no broader streaming normalization or auth/routing claim.
- Seven assigned test files: actual SDK/message/binding and content shape assertions, nullable result inference, invariant BaseMessage input list, scoped patch.object failure injection, real RuntimeError string and explicitly header-owning exception. Existing assertions retained; no new Any/cast/ignore/config/exclusion suppression.

## Verification

Cwd `/root/Code/slo-94-herdr-integration/slo`. Every gate explicitly sets:

```sh
export VIRTUAL_ENV=/root/.pyenv/versions/slo-harness
export PATH=/root/.pyenv/versions/slo-harness/bin:$PATH
export PYENV_VERSION=slo-harness
```

Python reports3.11.7. Tests run `bash docs/implementation/94-herdr/t1-dao-check.sh <exact modules>` using tracked synthetic fallback, never sourcing secrets. Helper prepends62 foundation tests; counts overlap and must not be summed. Existing Herdr/terminal/process-admission guards unchanged. `dpkg -V coreutils` silent after every test run.

Receipts: `static-C-153-receipts/`; final exact argv in `final-tests.command`, `surrounding.command`, `mypy.command`, complete logs and final exit files retained.

| Gate/log | Result |
|---|---|
| red.log | C45 diagnostics reproduced before edits; mypy exit1 |
| faux-green.log |71 passed |
| anthropic-red.log |3 failed/62 passed, causal missing kwargs |
| anthropic-green.log |77 passed |
| codex-before.log |63 passed, pre-edit wire oracle |
| codex-normalizer-green.log |100 passed |
| narrowing-green.log |130 passed |
| policy-pool-green.log |121 passed |
| faux-forms-green.log |74 passed |
| final-tests.log |251 passed,3 warnings, exit0; exact C tests + both new regressions + Codex/normalizer |
| surrounding.log |138 passed,7 warnings, exit0; model_pool, graph, graph_stream_parser plus foundation |
| mypy.log |Success: no issues found in13 source files, exit0 |
| black.log |13 files unchanged, exit0 |
| diff-check.log |silent, exit0 |
| coreutils.log / coreutils-surrounding.log |silent, exit0 |

Mypy checks the eleven assigned files plus both new regressions, with a distinct receipt-local cache, **without follow-imports suppression**. Scoped success is not full `make lint`. Black formatting limited to those13 files. Reviewed final tracked diff plus both new tests. No production behavior expansion beyond reproduced Anthropic request-binding defect. Static-C is READY; final unchanged integrated full regression/static gates, independent full-feature Review and Completion belong to later phases.
