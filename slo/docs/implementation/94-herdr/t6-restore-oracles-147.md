# T6 restore oracles 147 — INCOMPLETE

## Scope and safety

Changed only `tests/integration/test_herdr_two_process_restore.py` and `tests/integration/herdr_restore_process_entry.py`, plus this report and `oracles147-*` receipts. No production/bootstrap/safety-test/shared-status/specification/other-worktree edits. No agents, commits, external actions, live Herdr, provider calls or terminal windows.

Verified all four `path145-files.sha256` entries before editing, `/usr/bin/bash`, cwd `/root/Code/slo-94-herdr-integration/slo`, and approved `/root/.pyenv/versions/slo-harness/bin/python` Python 3.11.7. `dpkg -V coreutils` was silent initially and after every executed test batch; final dedicated receipt is empty with exit 0. Existing containment, pre-import guard, registered shim/fake identity, explicit environment, READY supervision and anchored cleanup were not changed.

## Actual changes

- Parent checks the actual second-process policy against independent literal expected values: UUID from advertised identity; model `gpt-5.4`; effective reasoning `high`; exact workdir/workspace and ordered plugin paths; both pool entries in original order with model, provider, priority, cooldown and rate-limit cooldown. Publisher equality is no longer the expected-value oracle.
- Replaced direct private `_ensure_agent_ready()` refusal with the public session async-generator `invoke(text="explicit credential refusal probe")` inside the actual restored mounted app. This is a distinct controlled user attempt only in the credential-refused variants. Normal available restores remain prompt-free. Refusal must raise the normal credential error before yielding execution output; factory count remains zero and complete history remains byte-value identical, containing both original prompts including the later post-advertisement turn.
- Both replaced factory boundaries now call the real CredentialResolver and require the exact synthetic credential with no refresh token before supplying Faux. Pool boundary additionally checks every provider. Parent requires actual publisher use of this check.
- After publication and the later history turn, mutate the publisher's mutable plugin list and pool entry cooldown/order. Assert immutable capture unchanged; second process still matches independent original values and old record bytes. Ambient preferences are changed as before.

## Test-first receipts

Each prefix below is under `docs/implementation/94-herdr/`, with `.log` and `.exit` unless noted.

| Prefix | Result |
|---|---|
| oracles147-red | 4 failed / 1 passed: missing public_admission observation, after independent policy assertions passed |
| oracles147-safety | 223 passed, exit 0 |
| oracles147-green | 5 passed, exit 0 |
| oracles147-red2 | 4 failed / 1 passed: missing factory credential/mutation evidence |
| oracles147-safety2 | 223 passed, exit 0 |
| oracles147-green2 | 38 passed (positive family + restore CLI), exit 0 |
| oracles147-final | 261 passed, 2 warnings, 93.51 seconds, exit 0; post-format combined family/safety/CLI |
| oracles147-black | four files unchanged, exit 0 |
| oracles147-mypy | scoped four files, no issues, exit 0 |
| oracles147-diff | empty `git diff --check`, exit 0 |
| oracles147-coreutils-final | empty `dpkg -V coreutils`, exit 0 |

No failure assertion was removed to obtain green. Two small source increments followed their failing parent tests, each followed by safety and positive execution before the next increment. Black touched only the two owned files. Final hashes: `oracles147-files.sha256`.

Commands used approved interpreter (`P` below), `-B`, no sourced environment file:

```sh
export SLO_ENV=test SLO_ROOT_DIR="$PWD" SLO_APP_DIR="$PWD" SLO_APP_NAME=slo SLO_LOG_FORMAT=text SLO_DEFAULT_MODEL_NAME=gpt-5.4 SLO_AUTO_VISUALIZE=0 SLO_HERDR_DISABLED=1 SLO_ANTHROPIC_API_KEY=ci-placeholder-tests-are-fully-mocked COLUMNS=120 LINES=40 PYTHONPATH="$PWD"
P=/root/.pyenv/versions/slo-harness/bin/python
$P -B -m pytest -q --tb=short tests/integration/test_herdr_two_process_restore.py
$P -B -m pytest -q --tb=short tests/integration/test_herdr_restore_harness_safety.py
$P -B -m pytest -q --tb=short tests/integration/test_herdr_two_process_restore.py tests/cli/test_herdr_restore.py
$P -B -m pytest -q --tb=short tests/integration/test_herdr_two_process_restore.py tests/integration/test_herdr_restore_harness_safety.py tests/cli/test_herdr_restore.py
```

Static commands: `$P -B -m black --check` and `$P -B -m mypy --follow-imports=skip` on bootstrap, entry helper, parent test and safety test. Scoped mypy is not repository lint.

## Remaining acceptance gaps — READY withheld

1. Missing-credential public invocation is now proved; separate unavailable **model capability** refusal through actual second-process public CLI/build/admission is not. Existing pool equality proves no subtraction in the exercised credential path only.
2. Untrusted project plugin nonexecution and explicit plugin load remain checked, but no new controlled trust-change/refusal case was added. Do not promote this to the complete requested current-trust matrix.
3. No explicit assertion of the refused attempt's normal blocked attention/rendered error was added; the public exception and no-execution/no-history effects are checked. PromptInput was not driven for the refusal; public session invoke was used.
4. Mutation test covers plugin list and pool list/order plus cooldown entry mutation, not independent adversarial mutation of every scalar. All original scalar values are independently checked on restore.
5. Full make test/smoke/lint not run. Supplied baseline 281 errors/58 files remains unwaived and was not freshly reproduced. No all-green repository or independent-review claim.
6. Source-entry shim only: literal advertised argv operands reach real parser/dispatch, but Python `-I -B` executes the registered source shim. This is not installed plain-slo equivalence or live Herdr restart certification.

No product defect was established. Remaining work is acceptance coverage, not authorization for broad product edits.

## Context and accounting

Read parent/entry/bootstrap, prior 146 receipt, root RESEARCH, routing and scope plan, shared engineering routing/testing/ownership, Python root, coding rules/cadence/declarative guidance, Typer/Textual/Faux recipes and workflow counting. AGENTS/CLAUDE/docs RESEARCH supplied in context. Read ROLE/os README/Slo gotchas and canonical C 7.3–7.7 plus 8–10, T6 sample attachment and accepted review. Some oversized combined KB/context reads were truncated; complete ingestion of every requested prerequisite is NOT claimed. One malformed parallel read call produced validation errors without file changes.

Same unfinished turn 1: started 1, completed 0, historical partial 1, supplied dispatch 147, retries 0. User turn/dispatch limits unlimited; no artificial numeric stopping limit asserted. This delivery is partial and does not fulfill the request to close the complete finite two-process family.
