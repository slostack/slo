---
name: test-verification-policy
description: Coverage and decision-path checklist — run through before declaring tests
  'done'.
when_to_use: Use as the final gate after writing tests.
group: coding
kind: skill
source_prompt: test-verification-policy.md
---

# Test Verification Policy

## Skill summary

- **Name:** `test-verification-policy`
- **Description:** Coverage and decision-path checklist — run through before declaring tests 'done'.
- **When to use:** Use as the final gate after writing tests.
- **Group:** `coding`
- **Kind:** `skill`
- **Source prompt:** `test-verification-policy.md`

## Examples

- The user asks: "Write or revise the tests covered by test verification policy."
- You finished coding and need the matching test convention before calling the work done.

## Guidance

Shared obligation authority: `skills/engineering/engineering-testing/SKILL.md`.
The detailed stack examples below retain existing Python/Vue verification recipes;
they do not prescribe their commands, framework, mocking policy or file layout to
Go or another language. Use the routing guide to select the appropriate test category.

Every code change must be verified by unit tests before it is considered complete. This is not optional — untested code is unfinished code.

---

## Core Rule

**Every piece of code you write or modify must have a corresponding unit test that passes.** Do not move on to the next task until the tests for the current change are green.

---

## What Must Be Tested

Every decision point in the code must have at least one test that exercises each path. A "decision point" is any place where execution can take more than one route.

| Code Pattern | What to Test |
|-------------|-------------|
| `if` / `else` | One test for the truthy branch, one for the falsy branch |
| `if` / `elif` / `else` | One test per branch |
| `match` / `case` | One test per case arm, including the default/fallback |
| Early returns / guard clauses | One test that triggers the early return, one that proceeds past it |
| `try` / `except` | One test for the success path, one that raises the caught exception |
| Dynamic dispatch (factory methods, strategy pattern, registry lookups) | One test per concrete dispatch target |
| Conditional assignments (`x = a if cond else b`) | One test per outcome |
| Loop with conditional `break` / `continue` | Tests that exercise both the break/continue path and the full iteration path |
| Feature flags / configuration-driven branches | One test per configuration value that changes behavior |

### Example

Given this service method:

```python
@staticmethod
async def build_and_create(session: AsyncSession, **kwargs) -> DocumentDAO:
    if not kwargs.get("body"):
        raise ValueError("Document body is required")

    dao = DocumentService.build(**kwargs)

    if kwargs.get("skip_embeddings"):
        dao.embeddings = None
    else:
        dao.embeddings = await DocumentService.generate_embeddings(dao.body)

    document = Document(**dao.model_dump())
    session.add(document)
    await session.flush()
    return DocumentDAO.model_validate(document)
```

The required tests are:

```python
class TestBuildAndCreate:
    async def test_raises_when_body_is_missing(self, async_db_session):
        """Guard clause: early raise path."""
        with pytest.raises(ValueError, match="Document body is required"):
            await DocumentService.build_and_create(async_db_session, title="Test")

    async def test_creates_document_with_embeddings(self, async_db_session):
        """Default path: embeddings generated."""
        doc = await DocumentService.build_and_create(
            async_db_session, title="Test", body="content"
        )
        assert doc.embeddings is not None

    async def test_creates_document_without_embeddings_when_skipped(self, async_db_session):
        """Conditional branch: skip_embeddings=True."""
        doc = await DocumentService.build_and_create(
            async_db_session, title="Test", body="content", skip_embeddings=True
        )
        assert doc.embeddings is None
```

Three decision points → three tests. Each test name describes the specific path it exercises.

---

## Workflow

1. **Write or modify code** — implement the feature, fix, or change.
2. **Identify every decision point** — scan the code you touched for `if`, `match`, `try`, dynamic dispatch, guard clauses, and conditional expressions.
3. **Write one test per path** — each test should exercise exactly one branch and assert the expected outcome for that branch.
4. **Run the tests** — execute the relevant test file or test class:
   ```bash
   loadenv environments/test.env
   PYTHONPATH=${PWD} pytest -sv tests/path/to/test_file.py::TestClass
   ```
5. **All tests must pass** — if any test fails, fix the code or the test before proceeding. Do not leave failing tests behind.
6. **Run the full suite before finishing** — after all individual tests pass, confirm no regressions:
   ```bash
   PYTHONPATH=${PWD} pytest -sv tests/
   ```

---

## Test Naming Convention

Test names should describe the specific code path being exercised, not just the method being called.

| Bad | Good |
|-----|------|
| `test_build_and_create` | `test_build_and_create_when_body_is_missing` |
| `test_trigger` | `test_trigger_when_partition_is_0` |
| `test_search` | `test_search_when_no_documents_match` |

The pattern is: `test_<method>_when_<condition>`, matching the domain/app/controller test skills.

---

## What Does NOT Need a Separate Test

- **Pure wiring** — if a method simply delegates to another method with no logic, test the delegatee instead.
- **Framework behavior** — do not test that FastAPI parses query params or SQLAlchemy flushes correctly. Trust the framework.
- **Trivial getters/setters** — a Pydantic field with no custom validator does not need its own test.

---

## Verification Checklist

Before marking any task as complete, confirm:

- [ ] Every new or modified method has tests covering each decision point
- [ ] All tests pass (`pytest` exit code 0)
- [ ] No existing tests were broken by the change
- [ ] Test names describe the specific code path they exercise
