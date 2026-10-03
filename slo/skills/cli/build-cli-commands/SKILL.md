---
name: build-cli-commands
description: Eighteen hard rules for adding a new operator-facing CLI verb end-to-end
  (Make target → helper script → optional router/service inside the deployed app).
  Each rule states the failure that motivated it and how to apply it.
when_to_use: Use when adding or extending a CLI verb across the deployment + app surface.
group: cli
kind: skill
source_prompt: cli/build-cli-commands.md
---

# CLI Command Authoring Conventions

## Skill summary

- **Name:** `build-cli-commands`
- **Description:** Eighteen hard rules for adding a new operator-facing CLI verb end-to-end (Make target → helper script → optional router/service inside the deployed app). Each rule states the failure that motivated it and how to apply it.
- **When to use:** Use when adding or extending a CLI verb across the deployment + app surface.
- **Group:** `cli`
- **Kind:** `skill`
- **Source prompt:** `cli/build-cli-commands.md`

## Examples

- The user asks: "Add or revise the cli commands for this feature."
- You want the canonical build pattern before touching cli commands.

## Guidance

Eighteen hard rules for adding a new operator-facing CLI verb to the Orders platform monorepo (Make target → helper script → optionally a router/service inside the deployed app). Every rule has a `**Why:**` (the failure that motivated it) and `**How to apply:**` (the concrete file, target, or pattern reference).

These rules **complement** ``../deployment/conventions.md`` (deploy-time choreography, secret pipelines, stack lifecycle) — they do not duplicate it. Where a deploy convention already covers something (e.g. `CONFIRM=yes` on destructive targets, image tag defaults), this file cross-links instead of restating.

If you are adding a new CLI authoring pattern that these eighteen don't cover, extend this file after you've validated it in a real environment — not before. See ``skills/design-and-analysis/derive-new-convention/SKILL.md`` for the process.

---

## Companion documents — read these alongside this file

| File | Scope |
|---|---|
| [`build-cli-command-class.md`](../build-cli-command-class/SKILL.md) | **Authoritative for Command class structure** — `Command` suffix, `__init__`/`build`/`execute` triad, `execute`-as-table-of-contents, Typer function naming (`verify-flow` → `verify_flow`), async helper naming chain, `run_async` import source, file layout, anti-patterns, full pre-merge checklist. |
| [`build-cli-modules.md`](../build-cli-modules/SKILL.md) | Full Python module implementation — stack library rules, `@handle_cli_errors`, argument patterns, two-console discipline, polling, retry, dry-run gate, structlog configuration, test layers. |

---

## Part A — Makefile as thin shim

### 1. Every operator-facing CLI verb is a Make target

Operators learn one tool — `make`. Tab-completion works. `make help` is the canonical discovery surface. Nothing operator-facing is shipped as a bare shell script or bare Python module.

**Why:** mixed CLI styles (`./deploy.sh`, `python -m tools.deploy`, `bin/deploy`) train every operator differently, break tab-completion, and lose `make`'s implicit dependency tracking (target → prerequisite ordering). One tool, one discovery surface.

**How to apply:** the entry point for every operator workflow is a `.PHONY:` target in a Makefile and a help-line in that file's `help:` recipe. Canonical shape: the `help:` block in [`deployment/Makefile`](../../../deployment/Makefile) (lines 51–106) prints every target, its required args, and a one-sentence description. Mirror it in any new project's Makefile — see [`verifier/Makefile`](../../../verifier/Makefile) §"help" for a parallel example.

### 2. Make target = thin shim; recipes ≤ 4 lines; everything else delegates to `<project>/cli/<command>.py` (Python) or `<project>/scripts/<target>.sh` (bash orchestration only)

The recipe handles arg validation, env forwarding, and `exec`. Recipes longer than **4 lines** of substantive logic — including any `for`-loop, conditional branch, or multi-step pipeline — get pulled into a script. **Python under `<project>/cli/<command>.py`** is the default destination; bash under `<project>/scripts/<target>.sh` is reserved for orchestration that is genuinely bash-idiomatic (port-poll loops, EXIT trap-based process cleanup, host-process spawning).

**Why:** Make's recipe DSL is hostile to control flow — every line is a fresh `/bin/sh` invocation (macOS ships GNU Make 3.81, predating `.ONESHELL`), `if`/`for` chains need `;\` continuations, and quoting is double-escaped because `$` collides with Make's own expansion. The moment a recipe needs a loop or a conditional, it should be a script. **Python > bash for anything that branches on data, parses JSON, makes HTTP requests, or has unit tests.** Bash only earns its keep when the script's entire job is shell-orchestration primitives (`pgrep`, `port_in_use`, `wait`, `trap`, `ssh`). Bigger logic blocks in bash are unmaintainable — variables aren't typed, errors are silently swallowed without `set -euo pipefail` boilerplate at every level, tests are impractical.

**Where things go:**

| Code shape | Destination |
|---|---|
| Make target invokes Python with arg parsing, HTTP requests, file I/O, branching on parsed data | `<project>/cli/<command>.py`, invoked via `python -m cli.<command>` |
| Make target invokes bash for SSH orchestration, process spawning, port polling, EXIT trap cleanup | `<project>/scripts/<target>.sh` |
| Pure pipeline chains (dependency declarations, no recipe body) | Stay in the Makefile |

**How to apply:**

- The `app-deploy:` target in [`deployment/Makefile`](../../../deployment/Makefile) (lines 195–198) is 3 lines: env guard, IMAGE_TAG guard, `bash scripts/app-deploy.sh`. The actual ~80-line workflow lives in [`deployment/scripts/app-deploy.sh`](../../../deployment/scripts/app-deploy.sh) — bash because the script is dominated by SSH orchestration + `rsync` + `docker stack deploy` choreography.
- The `cli-token-rotate:` target (sub-spec 01 of `<feature-specifications-root>/cli-router/overview.md`) is 3 lines: env guard + `python -m cli.cli_token_rotate --env $(ENV)`. The ~150-line workflow lives in [`deployment/cli/cli_token_rotate.py`](../../../deployment/cli/cli_token_rotate.py) — Python because the work is "decrypt YAML → generate token → re-encrypt → subprocess two make targets → write file with mode 0600 → emit envelope-shaped status" — all branching on data, all unit-testable.
- Exception: pure pipeline chains (e.g. `full-deploy: secrets-sync push-images observability-deploy ...`) stay in the Makefile because they are dependency declarations, not recipes.

**Defect signature (audit this in code review):**

A Make recipe with embedded `for svc in $(SERVICES); do ssh ... ; done` or `ssh "$$USER@$$HOST" "command1 && command2 && command3"` is a defect — extract to `<project>/cli/<target>.py`. The Python module gets argparse, a typed `Config` object, structured logging, real error handling, and unit tests against a `pytest-httpx` (for HTTP) or `unittest.mock.patch` (for subprocess) fixture set.

### 3. Target naming: `<noun>-<verb>` for service-scoped, `<verb>-<noun>` for general, one-word umbrellas for chains

Service-scoped verbs lead with the noun (`app-deploy`, `app-migrate`, `verifier-bootstrap-databases`, `orders-deploy`). General workflows lead with the verb (`push-orders`, `build-images`, `registry-login`). Umbrella chains are one or two words (`verifier-up`, `full-deploy`, `app-release`, `verifier-release`, `full-teardown`).

**Why:** alphabetical sort groups every target for a given service together (`app-*`, `verifier-*`), which is how operators scan `make help`. Umbrella chains get short distinctive names so muscle memory is trivial.

**How to apply:** before naming a new target, scan the existing `.PHONY:` block in [`deployment/Makefile`](../../../deployment/Makefile) (lines 15–30) and pick the matching pattern. New service → new prefix; new workflow against an existing service → reuse the prefix.

### 4. Required args are validated at the top of the recipe with `[ -n "$(ENV)" ]` checks; optional args use `?=` defaults or env-file fallback

Every recipe that needs `ENV` calls `$(call require_env)` (or `@[ -n "$(ENV)" ] || (echo ...; exit 1)`). Optional args use Make's `?=` so an unset variable resolves to a sensible default from context.

**Why:** `make app-deploy` with no `ENV=` would otherwise try to deploy to "" and fail deep inside a shell pipeline. Validating up-front gives a one-line error operators can act on. `?=` defaults from context (git SHA, env-file values) mean "the obvious thing" works without the operator memorising flags.

**How to apply:** the `define require_env` block in [`deployment/Makefile`](../../../deployment/Makefile) (lines 34–38) is the canonical guard. The canonical default-from-context pattern is `IMAGE_TAG ?= $(shell git -C $(REPO_ROOT) rev-parse --short HEAD 2>/dev/null)` (line 496) — this is also rule 2 in ``../deployment/conventions.md``. For env-file fallback (e.g. `REGISTRY`), use the `define resolve_registry` pattern (lines 501–509).

### 5. Every target gets a `.PHONY:` declaration; either inline above the target or in the top-of-file block

Make's pattern-matching rules will silently shadow your target if a stale file of the same name exists in the directory. `.PHONY:` is the only fix.

**Why:** a developer once committed a stale `deploy` file to a project's root; `make deploy` thereafter no-op'd because Make saw the file and decided the target was already "up to date". `.PHONY:` tells Make the target name is not a filename.

**How to apply:** either bundle every target into the top-of-file `.PHONY:` block as [`deployment/Makefile`](../../../deployment/Makefile) lines 15–30 do, or declare inline directly above each target as `verifier-up:` does (line 480). Both are correct; pick one per file and be consistent.

### 6. Every target has a help-line in the `help:` recipe

The help-line shape: `make <target>    ARG=<...> [OPTIONAL=<...>]    (one-sentence description)`.

**Why:** operators read `make help` before they read any source file. A target without a help-line is invisible — the next operator will reinvent it.

**How to apply:** match the column alignment and bracketing convention used by [`deployment/Makefile`](../../../deployment/Makefile) `help:` (required args bare, optional args in `[...]`, parenthetical for caveats). Required args before optional. Multi-line trailing notes (`IMAGE_TAG defaults to ...`) sit indented after the target block.

---

## Part B — When bash, when Python

### 7. Bash for orchestration; Python for logic

A script that spawns processes, ssh's, waits on ports, traps EXIT — that's bash. A script that parses JSON envelopes, branches on data structure, runs unit tests — that's Python.

**Why:** bash is the right tool for `ssh + rsync + docker stack deploy + trap cleanup` pipelines because every primitive is one line and quoting matches what the operator types interactively. Bash is the wrong tool for "decode JSON, walk three keys, decide if the envelope is a success or failure" — that grows unreadable inside backticks and resists unit testing.

**How to apply:** [`verifier/scripts/verify_flow.sh`](../../../verifier/scripts/verify_flow.sh) is the canonical bash orchestrator — port-poll (`port_in_use`), process-spawn (`spawn_service`), EXIT trap (`trap cleanup EXIT INT TERM`), pgrep / curl / sleep loops. [`verifier/scripts/parse_trigger_response.py`](../../../verifier/scripts/parse_trigger_response.py) is the canonical Python helper — envelope parsing, raise-on-failure, has unit tests at `verifier/tests/scripts/test_parse_trigger_response.py`.

### 8. Inline `python3 -c '...'` is a smell — extract to a `.py` file once it grows past ~5 lines or needs tests

A one-liner pulling a YAML key is fine inline. A 20-line JSON envelope parser inside a bash heredoc is not.

**Why:** inline Python in a heredoc loses syntax highlighting, can't be linted, can't be unit-tested, and adds three layers of quoting (`$` → Make → bash → Python). Extraction also pays a documentation dividend — the `.py` file gets a module docstring explaining the contract.

**How to apply:** `verifier/scripts/parse_trigger_response.py` started as inline Python in `verify_flow.sh` and was extracted once it grew unit tests — read its module docstring for the explicit justification. Smaller one-liners (e.g. the YAML registry-lookup fallback in [`deployment/Makefile`](../../../deployment/Makefile) line 507) stay inline because they have no logic to test.

### 9. Bash scripts MUST `set -euo pipefail` at the top

Every script in [`deployment/scripts/`](../../../deployment/scripts/) and [`verifier/scripts/`](../../../verifier/scripts/) opens with `set -euo pipefail`. Trap-based cleanup relies on this.

**Why:** without `-e`, a `docker stack deploy` failure mid-script doesn't abort — the script keeps going and the next step "succeeds" against a broken state. Without `-u`, a typo in a variable name silently expands to `""` and corrupts a command. Without `-o pipefail`, `cmd | grep` swallows `cmd`'s exit code. The trap-cleanup pattern (rule 17 below) depends on early-fail to fire reliably.

**How to apply:** open every new bash script with `set -euo pipefail`. Reference shape: [`deployment/scripts/app-deploy.sh`](../../../deployment/scripts/app-deploy.sh) line 10. Source the shared helpers (`lib/log.sh`, `lib/env.sh`, `lib/ssh.sh`, `lib/secrets.sh`, `lib/confirm.sh`) AFTER the `set` line.

### 10. Python helpers follow the global Python ground rules — no exceptions for "small CLI scripts"

Named arguments on every 2+-arg call site. Explicit type hints on every signature. Google-style docstrings on every function and class. Declarative method structure (one decision per method, no nested conditionals).

**Why:** a "small" script grows. The 80-line `parse_trigger_response.py` started as 12 lines of inline Python; today it has a custom exception class, two callable entry points, and a unit-test suite. Conventions that would have made the original 12 lines longer pay for themselves the moment the file crosses 30.

**How to apply:** cross-link the global Python rules — ``skills/languages/python/named-arguments-and-type-hints/SKILL.md``, ``skills/languages/python/declarative-method-structure/SKILL.md``, ``skills/languages/python/method-docstrings/SKILL.md``. Treat `verifier/scripts/parse_trigger_response.py` as the reference implementation — read it before writing a new helper.

---

## Part C — CLI → Router → Application Service → Domain layering

### 11. Operator CLI commands that do real work hit an HTTPS endpoint on the deployed service, not the database or filesystem directly

The chain for a "do work" CLI command is:

1. **Make target** → calls the Python CLI module (or a bash script that calls it).
2. **Python CLI module** → reads the operator's token, builds the request body, `POST`s to the deployed service at `/api/v1/cli/<command>`.
3. **Router** (FastAPI route under the `/api/v1/cli/*` prefix) → validates the Bearer token via middleware, translates the HTTP request into an Application Service call.
4. **Application Service** → orchestrates Domain Services, DAOs, and side effects in declarative steps.
5. **Domain Service** → encapsulates pure business rules and DB access (only if needed).
6. **DB / external side effects** → at the bottom of the stack.

**Why:** the deployed service is the only thing that knows the current schema, the current LLM credentials, the current S3 bucket policy. A CLI that bypasses it and reaches into Postgres directly will silently rot the moment a domain rule changes. The HTTPS endpoint is the *contract*; everything above it is a transport.

**How to apply:** when in doubt, "what would the Vue SPA do?" If a feature could be added to the SPA tomorrow without a backend change, the CLI should go through the same router. Add a router-level handler under `/api/v1/cli/<command>` that invokes the existing Application Service. The CLI module reads `~/.orders/<env>/cli-token` and POSTs.

### 12. Same logic powers the Vue SPA, the CLI, and future agent integrations — the HTTPS endpoint is the single contract

If the operator's CLI and the user's browser both trigger "rerun verification", the work happens in one place: the Application Service. Both transports just package and unpackage HTTP.

**Why:** every duplication is a bug waiting to happen. The CLI and the SPA must not have parallel implementations of "build a payment", "trigger a verifier run", "rotate a key", or "purge a session" — drift between them is a class of bug we refuse to ship.

**How to apply:** cross-link ``skills/languages/python/build-application-services/SKILL.md`` — that's where the orchestration lives. The router stays a thin translator (HTTP body → Application Service args → HTTP envelope). The CLI module stays a thin transport (Make args → token + HTTP POST → parse envelope → exit code).

### 13. Make target → Python CLI module → router is the standard; direct DB / filesystem access from the operator host is the exception

The only acceptable host-direct paths are bootstrap operations that have to happen before the deployed service can start: `verifier-bootstrap-databases` (creates the DBs the service connects to), `app-migrate` (one-shot Swarm job applying alembic before app-deploy boots services), `secrets-sync` (materialises Swarm secrets the service mounts at start), `postgres-install`.

**Why:** the service cannot host an "apply migrations" endpoint that runs against its own DB before it has booted. Bootstrap is genuinely below the service layer. Every other operation has a running service to talk to.

**How to apply:** before reaching for `psql` or direct DB access in a new script, ask: "could this be a `/api/v1/cli/<command>` instead?" If yes, route it that way. If the answer is genuinely "no, the service can't be running for this to make sense", document the bootstrap reason in the script's header comment — see [`deployment/scripts/app-migrate.sh`](../../../deployment/scripts/app-migrate.sh) lines 12–23 for the canonical justification.

---

## Part D — Authentication on CLI endpoints

### 14. CLI endpoints sit behind a dedicated `/api/v1/cli/*` prefix with Bearer-token middleware

The Vue SPA's `/api/v1/*` routes stay unauthenticated at the service layer (assumed to be behind Tailscale or per-env nginx auth). CLI endpoints require explicit token validation at the FastAPI middleware layer.

**Why:** the SPA serves trusted browsers on the operator's tailnet (or behind an edge auth proxy); CLI endpoints in some deploys face direct internet access (e.g. an on-call engineer running `make` from a laptop on coffee-shop wifi). Transport-level auth on the CLI prefix means "yes, even from the internet, this is safe" — without forcing the SPA into a token flow that's overkill for browser traffic.

**How to apply:** add a new FastAPI router file `src/routers/cli_<area>_router.py` mounted at prefix `/api/v1/cli`. Apply a `Depends(verify_cli_token)` (or equivalent middleware) to every route under it. The SPA routers under `/api/v1/<area>` continue to use the existing unauthenticated chain. Cross-link ``skills/languages/python/build-routers/SKILL.md`` for router structure.

### 15. Tokens live in two places: the Swarm-mounted secret and the operator's `~/.orders/<env>/cli-token` (chmod 0600, gitignored)

The service reads its token via the existing Swarm-secret mount pattern (rule 11 in ``../deployment/conventions.md`` — `external: true` + `_vN` suffix). The operator reads their copy from `~/.orders/<env>/cli-token`, one file per environment, chmod 0600, never committed.

**Why:** per-env tokens limit blast radius — a stolen `local` token does not unlock `staging` or `production`. Storing the operator's copy on disk (not in `.zshrc`) keeps it out of shell history and out of process listings (`ps`). One file per env makes rotation a per-env operation, matching the per-env age-key model.

**How to apply:** add the CLI token to the SOPS-encrypted secrets file at `deployment/secrets/<env>.plain.yaml` under a `cli.token` key. Wire it into [`deployment/scripts/_render_app_stack.py`](../../../deployment/scripts/_render_app_stack.py) as a `*_FILE` indirect (rule 13 in ``../deployment/conventions.md``). The operator-side write path is a new `cli-token-show` target (rule 16) that decrypts and prints to stdout for the operator to paste into their token file. Reference: ``deployment/README.md` §1.7` — the full SOPS + age + Swarm pipeline.

### 16. Token rotation = new `_vN` suffix in the Swarm secret; operator re-fetches via `make cli-token-show ENV=<env>`

Same versioning model as every other Swarm secret. The operator does NOT edit the token file in place — they re-run `make cli-token-show ENV=<env>` after a `secrets-sync` and paste the new value into `~/.orders/<env>/cli-token`.

**Why:** Swarm secrets are immutable (rule 8 in ``../deployment/conventions.md``) — rotation means a new name, not a mutated value. Mirroring the convention for every other secret keeps the mental model uniform; an operator who knows how to rotate `OPENAI_API_KEY` already knows how to rotate the CLI token.

**How to apply:** `make cli-token-show ENV=<env>` decrypts `secrets/<env>.enc.yaml` and prints `cli.token` to stdout (plaintext stays in the terminal, never written to disk by the target). Mirror the existing pattern in [`deployment/Makefile`](../../../deployment/Makefile) `minio-render:` (lines 171–180) — `load_env; load_secrets <env>; echo "$VALUE"`. Cross-link ``../deployment/template-new-secret.md`` for the secret-addition checklist.

---

## Part E — Streaming, idempotency, status

### 17. Long-running CLI operations poll a status endpoint by default; SSE is an optimization, not a starting point

The Python CLI module's job for long operations is `POST /api/v1/cli/<command>` → receive `{run_id, status: "QUEUED"}` → loop `GET /api/v1/cli/<command>/<run_id>` every N seconds → print progress → exit when status is terminal. Trap on Ctrl+C to print the run_id so the operator can resume polling.

**Why:** SSE/WebSocket plumbing in a CLI module is disproportionate complexity for an operator workflow — every CLI invocation lasts ≤ a few minutes and only one operator runs it at a time. Polling reuses the same status endpoint the SPA uses and survives terminal disconnects (the operator can re-poll by run_id from a new shell). When latency matters enough to need push, add SSE as an enhancement, not a foundation.

**How to apply:** mirror the polling loop in [`verifier/scripts/verify_flow.sh`](../../../verifier/scripts/verify_flow.sh) lines 326–343 — iteration counter, fixed sleep, terminal-status break, printf progress line. For a Python CLI module, structure it as a `poll(run_id: str, timeout_seconds: int) -> RunStatus` method on the CLI class with one decision per loop iteration (see rule 10).

### 18. Mutating CLI endpoints accept a `correlation_id` body field so retries are idempotent

The Python CLI module generates a UUID4 once at startup and sends it in the first POST. If the connection drops, the operator re-runs with `--correlation-id <uuid>` (or the script auto-retries) and the router dedups by correlation_id, returning the same `run_id` as the first call.

**Why:** the operator's terminal can disconnect (laptop sleep, ssh timeout, ctrl-C during the response) after the server has accepted the work but before the client sees the response. Without dedup the operator's retry creates a *second* verification run, double-fans-out work, and burns compute. The verify-flow trigger already carries a `run_id` from the first POST; making that response idempotent on a client-supplied key extends the same guarantee to the CLI path.

**How to apply:** add a `correlation_id: str` field to the CLI request body and an index on `correlation_id` in the underlying table. Router-level dedup (return existing row if `correlation_id` already seen) sits inside the Application Service, not the router. Reference for the same idea in the verifier: the trigger endpoint at `POST /api/v1/verification/runs` returns a stable `run_id` envelope ([`verifier/scripts/parse_trigger_response.py`](../../../verifier/scripts/parse_trigger_response.py) module docstring) — extending it to dedup on `correlation_id` is the single-line change you want.

---

## Part F — Conventions checklist

Adding a new operator CLI command? Walk this table top-to-bottom — each row points at the section above for the full rule.

For Command class structure (naming, `__init__`/`build`/`execute` triad, Typer function naming, async helper naming, file layout): **see [`build-cli-command-class.md` checklist](../build-cli-command-class/SKILL.md).**

| ✓ | Concern | Rule |
|---|---------|------|
| ☐ | Verb is a `.PHONY:` Make target with a help-line | §1, §5, §6 |
| ☐ | Target name follows `<noun>-<verb>` (or umbrella) convention | §3 |
| ☐ | Recipe ≤ 5 lines; real work in `scripts/<target>.sh` or `scripts/<target>.py` | §2 |
| ☐ | Required args validated with `[ -n "$(ARG)" ]`; optional args use `?=` defaults | §4 |
| ☐ | Bash script opens with `set -euo pipefail` and sources the shared `lib/` helpers | §9 |
| ☐ | Orchestration (ssh, port-poll, processes) in bash; logic (JSON parse, branching) in Python | §7, §8 |
| ☐ | Python helper has type hints, named args, Google docstrings, declarative structure | §10 |
| ☐ | Real work goes Make target → Python CLI → HTTPS `/api/v1/cli/<command>` → router → app service | §11, §12 |
| ☐ | Direct DB/filesystem access only for genuine bootstrap (DBs, migrations, secrets, OS-level) | §13 |
| ☐ | CLI endpoints mounted under `/api/v1/cli/*` with Bearer-token middleware | §14 |
| ☐ | Token in Swarm secret + `~/.orders/<env>/cli-token` (0600, gitignored), one per env | §15 |
| ☐ | Token rotation = new `_vN` suffix + `make cli-token-show ENV=<env>` re-fetch | §16 |
| ☐ | Long-running ops use polling, not SSE; CLI prints progress, breaks on terminal status | §17 |
| ☐ | Mutating endpoints accept `correlation_id` so retries are idempotent | §18 |
| ☐ | Destructive targets require `CONFIRM=yes` | ``../deployment/conventions.md` §18` |
| ☐ | Operator-side commands prefixed with `loadenv environments/<env>.env` | ``../deployment/conventions.md` §19` |
| ☐ | Command class structure, naming, triad, and pre-merge checklist | [`build-cli-command-class.md`](../build-cli-command-class/SKILL.md) |
