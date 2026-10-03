---
name: python-path-and-import-resolution
description: 'Python: Debugging import failures or setting up PYTHONPATH.'
when_to_use: For Python projects only. Use when imports break or you're configuring a new module's import
  path.
group: languages
kind: skill
source_prompt: python-path-and-import-resolution.md
---

# Python Path and Import Resolution

## Skill summary

- **Name:** `python-path-and-import-resolution`
- **Description:** Debugging import failures or setting up PYTHONPATH.
- **When to use:** Use when imports break or you're configuring a new module's import path.
- **Group:** `languages`
- **Kind:** `skill`
- **Source prompt:** `python-path-and-import-resolution.md`

## Examples

- The user asks for help with: Debugging import failures or setting up PYTHONPATH.
- Use when imports break or you're configuring a new module's import path.

## Guidance

**Applicability:** Python only; framework-specific sections apply only when that stack is in the project. Load `skills/languages/python/python-conventions/SKILL.md` and `skills/engineering/engineering-testing/SKILL.md` for shared obligations and test-category selection.

This guide documents the mandatory `PYTHONPATH` convention used in `orders_service` to ensure all imports resolve from the repository root.

---

## Rule

**Every `<name>.env` file in `environments/` must declare `PYTHONPATH` pointing to the repository root.**

All source imports in this project use the `src.` prefix (e.g., `from src.domains.payment.service import ...`). These only resolve correctly when Python's module search path includes the repository root.

---

## Convention

```bash
# environments/development.env  (local machine)
PYTHONPATH=<workspace>/orders_service

# environments/local.env  (machine-specific overrides)
PYTHONPATH=<workspace>/orders_service

# environments/test.env  (Docker / CI)
PYTHONPATH=/orders_service   # container mount path — do NOT change

# environments/template.env
PYTHONPATH=<workspace>/orders_service
```

> **Note for `test.env`:** This file is used by Docker-based CI runs where the repository is mounted at `/orders_service`. Do **not** change this value. For local test runs, load `test.env` first and then `local.env` — the local value overrides the Docker path.

```bash
loadenv environments/test.env
loadenv environments/local.env   # overrides PYTHONPATH to your local checkout
```

---

## How It Works

The `loadenv` shell function exports all variables from the env file into the current shell:

```bash
loadenv environments/development.env
```

After loading, `$PYTHONPATH` is set in the shell. When pytest or Python is invoked, it inherits this value and includes the repo root in `sys.path`. A `PYTHONPATH=${PWD}` prefix on individual commands is then optional and redundant, but harmless — it sets the same value the env file already exported, so the other test skills that prefix it explicitly stay correct.

**Before (without `PYTHONPATH` in env file):**
```bash
loadenv environments/development.env
poetry run pytest -sv tests/
# ModuleNotFoundError: No module named 'src'
```

**After (with `PYTHONPATH` in env file):**
```bash
loadenv environments/development.env
poetry run pytest -sv tests/
# All imports resolve correctly
```

---

## Files That Depend on This

The following files import from `src.*` and will fail at collection time if `PYTHONPATH` is not set:

| File | Example import |
|------|----------------|
| `tests/factory.py` | `from src.domains.order.service import ...` |
| `tests/conftest.py` | `from connectors.db import get_async_db_session` |
| All test files under `tests/` | `from src.apps.<app>.services.<service> import ...` |

---

## When Adding a New Env File

Whenever a new `environments/<name>.env` file is created, add `PYTHONPATH` as the **first non-comment variable**:

```bash
# environments/staging.env
PYTHONPATH=<workspace>/orders_service
APP_DIR=<workspace>/orders_service
# ... rest of vars
```

For Docker/CI env files where the app runs in a container, use the container mount path:

```bash
# environments/ci.env
PYTHONPATH=/orders_service
APP_DIR=/orders_service
```

---

## Common Mistakes

| Mistake | Symptom | Fix |
|---------|---------|-----|
| `PYTHONPATH` not in env file | `ModuleNotFoundError: No module named 'src'` on pytest collection | Add `PYTHONPATH=<repo_root>` to the env file |
| Ran `pytest` without loading env | Same error | `loadenv environments/test.env` + `loadenv environments/local.env`, then rerun |
| Loaded `test.env` without `local.env` | `PYTHONPATH=/orders_service` — Docker path used on local machine | Always follow with `loadenv environments/local.env` |
| Wrong path value | `ModuleNotFoundError` even after loadenv | `echo $PYTHONPATH` — verify it points to the repo root containing `src/` |
| Stale shell environment | Old `PYTHONPATH` from a previous session persists | Open a fresh terminal, re-run `loadenv` |
