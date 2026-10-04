# 86.b.3 — Additional-provider credential-file split

## Verdict

**Behavior implemented and tested; `ready=false` because the all-changed-file Black gate remains blocked.** No independent review, b4/b5 completion, or whole-feature readiness is claimed.

- Final isolated `make test`: **5253 passed, 18 deselected, 194 warnings; exit 0**.
- Surrounding auth/integration/history suites: **629 passed, 3 deselected, 17 warnings; exit 0**.
- Focused credential/isolation checks: **116 passed, 2 warnings; exit 0**.
- Black: all four sub-spec files plus the auth/full-flow caller tests are clean (**six files, exit 0**).
- The seventh changed Python file, `tests/integrations/openrouter/test_harness_contract.py`, has pre-existing formatting failures. Its untouched phase-start version also fails Black. Section 7.4 permits only path substitutions there; the prior b2 formatting authorization does not include it. No unrelated formatting was performed or failure waived.

**Required decision:** authorize a narrowly scoped formatting-only correction to that harness test, or explicitly resolve the gate/scope conflict. Until then, b3 is not ready despite green behavioral gates.

## Implementation and scope

All work was confined to `/root/Code/slo-openrouter-implementation/slo` on the existing `feature-86-openrouter-implementation` branch. No agents, installation, staging, commits, branch mutation, publication, real credentials, live provider calls, or user-state cleanup were used.

| File | Incremental change |
|---|---|
| `src/auth/credential_dao.py` | Export frozen `RELEASED_CREDENTIAL_PROVIDERS`: anthropic, openai, kimi_for_coding. Document the existing shared envelope and future-provider constraint. No fields changed. |
| `src/auth/credential_store.py` | Derive sibling additional-provider path; route writes by the frozen set; merge only owned rows on reads; warn deterministically for misplaced rows; preserve complete owning envelopes on writes/removal. Normalize unreadable/invalid files to the existing corrupt-file exception. |
| `src/auth/credential_resolver.py` | Precedence docstring only; resolver logic and precedence unchanged. |
| `tests/auth/test_credential_file_split.py` | New real-filesystem coverage, 70 parametrized cases, including store-to-resolver-to-history redaction. |
| `tests/auth/test_openrouter_authentication.py` | Nine prescribed credential-byte path substitutions only. |
| `tests/integration/test_openrouter_full_flow.py` | Eight prescribed existence/bytes/mode path substitutions only. |
| `tests/integrations/openrouter/test_harness_contract.py` | Three prescribed existence path substitutions only. |

`CredentialStore` remains the only persistence owner. Both files use `AuthenticationFileDAO`, the existing temp-and-replace writer, file mode 0600 and parent mode 0700. No migrations, backups, second store/DAO, locks, unknown-row tolerance, or credential-precedence redesign were added.

`additional_providers_path` is derived lazily as `<stem>.additional-providers<suffix>`. Constructor and `SLO_AUTH_FILE` overrides move both files together. The existing empty-path construction test continues to pass.

`load()` reads both files and filters by ownership. `persist()`/`remove()` instead read only the complete owning envelope, retaining its schema version and every other row, including misplaced rows. They neither read nor rewrite a corrupt sibling. An absent removal target causes no write.

The implementation deliberately closes a gap between the spec's sample code and its required unreadability contract: `OSError` from existence/read checks and decoding/JSON/schema `ValueError` become `CredentialStoreCorruptError(path=...)`. The public exception message excludes underlying content. History serialization still suppresses exception context and refuses unchecked text when key resolution fails.

## Preservation and review evidence

Before implementation, **821 predecessor hashes reconciled without drift** against the post-b2-authorized-formatting state. The original baseline archive remains unchanged:

`a6aa0e12cfe5ecb387f7efe25089afcfdb4fa136cb3c11e401ff98bc69ad46fa`

Evidence under [b3-receipts/](b3-receipts/):

- `phase-start-hashes.json`, `phase-start.tar.gz`: incoming state and six original edit targets.
- `incremental.diff`: complete reviewed b3-only diff, including the new test file, against phase-start bytes rather than HEAD.
- `changed-files.json`: seven source/test files with before/after hashes.
- `final-hashes.json`: 822 final preserved/source entries.
- `post-gate-check.json`: no drift, no baseline mode changes, no unexplained relevant untracked files; released tag still resolves to `f63df0a4958eedb4bc603f1946ba4591dd181fff`.
- `index.json`: 20 command receipts, actual commands/environments/exits, output hashes and log locations.
- `run_gate.py`: retained sanitized-environment gate runner.

All three existing caller tests were compared byte-for-byte with exactly the section 7.4 substitutions applied to their phase-start versions. The resolver file was similarly verified as precisely its prescribed docstring replacement. All other predecessor files remain unchanged. No production/test edits occurred after the successful final gates.

Self-review covered routing, read/write separation, exception/redaction behavior, absence/no-op behavior, schema preservation, permissions, overrides, synthetic test state and the full incremental diff. This is not an independent review.

## Test-first sequence

Each named receipt is `b3-receipts/<name>.json`; it records the exact expanded command, clean environment, actual exit, `/tmp/.../output.log`, coreutils verification and suite-root cleanup. Reds below were observed before their corresponding implementation changes.

| Sequence | Red | Green |
|---|---|---|
| OpenRouter routing and released-file preservation | `routing-red`: 2 failed, 17 passed; exit 1 | `routing-green`: 19 passed; exit 0 |
| Owned-row merge and warning behavior | `load-red`: 3 failed, 20 passed; exit 1 | `load-green`: 38 passed; exit 0 |
| Owning-file removal/preservation | `remove-red`: 3 failed, 32 passed; exit 1 | `remove-green`: 50 passed; exit 0 |
| Invalid encoding/read refusal normalization | `errors-red`: 12 failed, 53 passed; exit 1 | `errors-green`: 97 passed; exit 0 |
| Stat refusal normalization | `stat-red`: two selected cases fail; exit 1 | `stat-green`: 82 passed; exit 0 |
| Existing caller assumptions after split | `callers-red`: 21 failed, 30 passed; exit 1 | `callers-green`: 51 passed; exit 0 after path-only edits |

Additional regression guards passed (`regression-guards`: 106 passed; exit 0). Coverage added after initial reds is not presented as fabricated pre-fix failure evidence.

The initial seven-file `black-check` failed because the new split-test file and the pre-existing harness test required formatting. The b3-owned new file was formatted. `final-spec-black` then passed for the other six changed files. `baseline-harness-black` independently reproduced the harness failure on its untouched archived bytes. The unchanged known failure was not repeatedly rerun or labeled green.

## Final gates

| Gate | Result | Output |
|---|---|---|
| `final-focused` | 116 passed, 2 warnings; exit 0 | `/tmp/slo-86b-b3-final-focused-nk3y6d_8/output.log` |
| `final-surrounding` | 629 passed, 3 deselected, 17 warnings; exit 0 | `/tmp/slo-86b-b3-final-surrounding-_0mpykto/output.log` |
| `final-full` (`make test`) | 5253 passed, 18 deselected, 194 warnings in 382.18s; exit 0 | `/tmp/slo-86b-b3-final-full-z0k6ykef/output.log` |
| `final-spec-black` | Six files clean; exit 0 | `/tmp/slo-86b-b3-final-spec-black-qw56nmt7/output.log` |
| All seven changed Python files | BLOCKED by pre-existing harness formatting; not waived | `black-check.json`, `baseline-harness-black.json` |

All runner invocations recorded **silent `dpkg -V coreutils`, exit 0**, and no remaining suite state roots. Logs and receipts remain available. The final full count is 70 tests above b2's final 5183.

## Acceptance map

| Criterion | Evidence | Status |
|---|---|---|
| AC-K1 | OpenRouter creates only the additional file; released file remains absent or byte/mtime-identical; private modes verified. | PASS |
| AC-K2 | All three released providers route to the original file; frozen set equality asserted. | PASS |
| AC-K3 | Both-file merge, absent files, each provider and duplicate misfiled rows; only owning rows win. | PASS |
| AC-K4 | Both misfiling directions; one secret-free warning per row on every load, deterministic order; persist/remove retain misplaced rows and schema version; sibling bytes/mtime unchanged even when corrupt. | PASS |
| AC-K5 | Invalid JSON/schema/encoding, unknown future provider, injected read and stat refusal; correct corrupt-file path; real history serialization refuses unsafe writes without modifying prior history. | PASS |
| AC-K6 | Actual released executable alternation. Explicitly owned by b5; not implemented or claimed here. | b5 |
| Focused/surrounding/full tests | Final receipts above. | PASS |
| Sub-spec Black | Four required files included in six-file successful gate. | PASS |
| Recovery-plan all-changed-file Black | Seventh file remains a scope/formatting conflict. | BLOCKED |

## Safety, conventions and remaining boundaries

- Loaded project instructions/research, the b3 specification and overview, recovery/predecessor reports and relevant workflow, auth, persistence testing, style, review and verification conventions. Confirmed the vendored, installed and personal skill libraries.
- Every shell command explicitly entered the target workdir. Test/check subprocesses received a fresh allowlisted environment, disposable HOME/SLO_HOME/TMPDIR and explicit repository paths; no inherited credentials or state overrides. The approved existing Python 3.11.7 environment was verified, including Poetry's interpreter selection; nothing was installed.
- New test fixtures resolve/check their write namespace beneath their own temporary root before writes. Read/stat failures are injected at the OS boundary rather than relying on chmod denial while running as root. Stores, serialization and filesystem effects are real. HTTP in caller tests uses local synthetic transport; default E2E/live-provider tests stay deselected.
- Existing terminal/command-stub isolation guards remain unchanged. `make test` used the repository's inspected synthetic fallback because `environments/tests.env` is absent.
- Misfiled OpenRouter credentials are intentionally ignored and therefore unavailable to history redaction. Operators must move pre-fix rows manually **before** running new Slo. No migration or cleanup was attempted.
- Unknown later providers remain invalid in this closed-enum file. Later versions must use another sibling file; permissive parsing was not introduced. This rule and the manual-cleanup consequence are documented in the changed store/DAO docstrings.
- b4, b5, actual released/new executable proof, full-repository mypy and independent review remain outside this leaf phase. AGENTS/rollout updates belong to b5 as specified; existing RESEARCH and shared KB files were preserved rather than expanding this narrow task.
- Durable handoff for b5/KB: split incompatible provider enums by filename under one owner; project rows only for lookup, never as the source for an owning-file rewrite; test both redaction success and fail-closed behavior against the real store. Formatting authorization must explicitly name mechanically edited files before fixing unrelated baseline formatting.
