---
name: switch-environments-and-run-tests
description: Environment-switching and test-execution conventions for the workspace.
when_to_use: Use when you need to move between local, test, or other env files and
  run the right test command safely.
group: coding
kind: skill
source_prompt: switch-environments-and-run-tests.md
---

# Switch Environments and Run Tests

## Skill summary

- **Name:** `switch-environments-and-run-tests`
- **Description:** Environment-switching and test-execution conventions for the workspace.
- **When to use:** Use when you need to move between local, test, or other env files and run the right test command safely.
- **Group:** `coding`
- **Kind:** `skill`
- **Source prompt:** `switch-environments-and-run-tests.md`

## Examples

- The user asks: "Switch to the test environment and run the API test suite."
- You need the exact sequence for loading environment variables before pytest.

## Guidance

This guide covers how to switch between environments in `orders_service` and how to verify the codebase is working correctly by running the unit test suite.

---

## Environment Files

Environment files live in `environments/` and follow the `<name>.env` naming convention. Use `ls environments/` to list them.

| File | Used for |
|------|----------|
| `environments/template.env` | Canonical list of all variables — copy this when creating a new env file |
| `environments/development.env` | **Primary development environment** — Postgres on `5434`, Redis on `6381` |
| `environments/local.env` | Local overrides — extends or replaces development values for your machine |
| `environments/test.env` | Test runs — points to `orders_test` database; used when executing `pytest` |
| `environments/staging.env` | Staging environment |

The active environment is controlled by `DB_URL_ASYNC`, `REDIS_DB_URL`, and related variables set by the loaded file. All database and service connections in the application read from these.

> **Rule:** Development work always uses `development.env` (or `local.env` for local overrides). Tests always use `test.env`. Never run migrations or tests against the wrong environment — the database name in `DB_URL_ASYNC` tells you which DB you are targeting.

---

## The `loadenv` Helper

Add this function to `~/.zshrc` or `~/.bashrc` if it is not already there, then reload your shell (`source ~/.zshrc`).

```bash
loadenv() {
    echo "Loading $1"
    for i in $(cat $1 | grep "^[^#;]"); do
        export $i
    done
}
```

---

## Switching to the Development Environment

Use this when writing code, running the server, applying migrations, or doing any work that is not test execution.

```bash
# From the repo root
loadenv environments/development.env

# Verify the active database
echo $DB_URL_ASYNC
# postgresql+asyncpg://orders_app:localdev-password@localhost:5434/orders_development
```

Start the required Docker services (Postgres, Redis, NATS):

```bash
make dev-up
# or
make launch-dev-env
```

Start the application server:

```bash
make run
# FastAPI available at http://localhost:8080/o/api/v1/
```

---

## Switching to the Test Environment

Always load `test.env` before running `pytest`. This points the application at the `orders_test` database so test transactions do not touch development data.

```bash
loadenv environments/test.env

# Verify you are on the test database
echo $DB_URL_ASYNC
# postgresql+asyncpg://orders_app:localdev-password@localhost:5434/orders_test
```

> If you need to use `local.env` instead (for machine-specific test config), load it after `test.env` so local overrides take precedence:
> ```bash
> loadenv environments/test.env
> loadenv environments/local.env
> ```

---

## Prerequisites Before Running Tests

The test suite requires live services. Ensure the local test stack is running before executing `pytest`.

```bash
# Start Postgres, Redis, ClickHouse, MinIO (without the app container)
make local-test-up

# Or, if you are already running dev services and only need the test DB to exist:
make create-local-databases   # creates orders_development and orders_test
make migrate                  # runs Alembic migrations against the active DB_URL_ASYNC
```

Verify services are reachable:

```bash
# Postgres
psql postgresql://orders_app:localdev-password@localhost:5434/orders_test -c '\l'

# Redis
redis-cli -p 6381 ping
# PONG
```

---

## Running the Tests

```bash
# Run the full suite
PYTHONPATH=${PWD} poetry run pytest -sv tests/

# Shorthand via Make
make test-local

# Run tests for a specific domain
PYTHONPATH=${PWD} pytest -sv tests/domains/order/

# Run a single test
PYTHONPATH=${PWD} pytest -sv tests/services/test_order_create_app_service.py::TestOrderCreateAppService::test_creates_order
```

Tests use transactional rollback — every test runs inside a transaction that is rolled back automatically. There is no manual cleanup between tests.

---

## Verifying a Clean State

Run this sequence to confirm the environment is correctly loaded and all tests pass before committing or opening a PR:

```bash
# 1. Load test environment
loadenv environments/test.env

# 2. Confirm you are on the test database
echo $DB_URL_ASYNC    # must contain: orders_test

# 3. Confirm migrations are up to date
PYTHONPATH=${PWD} poetry run alembic current

# 4. Run all tests
PYTHONPATH=${PWD} poetry run pytest -sv tests/
```

All four steps must succeed. If migrations are behind, run `make migrate` with `test.env` loaded before running the tests.

---

## Returning to Development After Running Tests

After running tests, switch back to the development environment so subsequent commands (migrations, server, manual queries) target the right database.

```bash
loadenv environments/development.env

echo $DB_URL_ASYNC
# postgresql+asyncpg://orders_app:localdev-password@localhost:5434/orders_development
```

---

## Common Mistakes

| Mistake | Symptom | Fix |
|---------|---------|-----|
| Running tests without loading `test.env` | Tests connect to `orders_development`; data from tests may persist | `loadenv environments/test.env` |
| Running `make migrate` with `test.env` loaded | Migrations apply to `orders_test` instead of `orders_development` | `loadenv environments/development.env` before migrating |
| Docker services not running | `Connection refused` on Postgres or Redis | `make dev-up` or `make local-test-up` |
| Stale migrations | Tests fail with `relation does not exist` | `make migrate` with the correct env loaded |
| `PYTHONPATH` not set | `ModuleNotFoundError: No module named 'src'` | Prefix with `PYTHONPATH=${PWD}` or `export PYTHONPATH=${PWD}` |
| Using `local.env` for tests | Local overrides may point to wrong DB or services | Load `test.env` first, then `local.env` only if needed for machine-specific keys |
