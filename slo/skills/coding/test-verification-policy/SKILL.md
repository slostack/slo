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

Every code change must be verified with evidence appropriate to the changed behavior and test category before it is considered complete. Use isolated unit tests for deterministic decisions, orchestration tests for delegation order and failure cutoffs, adapter/database integration tests for persistence or protocol behavior, and end-to-end tests for composed flows. Verification is not optional — untested behavior is unfinished behavior.

---

## Core Rule

**Every meaningful decision and failure path must have a passing test, and every changed boundary must have evidence from the appropriate test category.** Do not move on to the next task until the tests for the current change are green; missing evidence is not completion.

---

## What Must Be Tested

Use the following code-pattern table to discover missing proof, not as a test-count
formula. Cover distinct outcomes, meaningful changed decisions, changed contracts
and relevant failure paths. Explicit specification matrices and critical safety
paths remain mandatory. One clear behavioral test may traverse several branches;
parameterized cases may cover equivalent inputs. Reuse existing tests when they
still prove the contract, and rerun them against the current change.

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

### Python decision-path illustration (retained as a generic coverage example)

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

These three scenarios illustrate distinct outcomes, not a universal branch-to-test formula. Add error-path evidence where the affected contract requires it.

---

## Workflow

1. Follow `skills/coding/code-test-loop/SKILL.md` and selected language/user test ordering.
2. Map changed behavior and boundaries to requirements and risks; inspect existing tests.
3. Add missing assertions for outcomes and relevant forbidden effects. A regression test
   must detect the defect it addresses; show failure before the fix where feasible,
   or explain other sensitivity evidence without inventing a RED run.
4. Run the exact project commands from the routing record. Classify failures before
   modifying code or expectations; oracle corrections require contract evidence.
5. Run affected suites and all agreed final gates. Separate baseline failures,
   blocked checks and explicitly approved exceptions; never manufacture green.


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

- **Pure wiring** — pure delegation may not need its own unit test, but composed evidence must show the real caller reaches the intended component with correct inputs. Testing the delegatee alone does not prove wiring.
- **Framework behavior** — do not test that FastAPI parses query params or SQLAlchemy flushes correctly. Trust the framework.
- **Trivial getters/setters** — a Pydantic field with no custom validator does not need its own test.

---

## Verification Checklist

Before marking any task as complete, confirm:

- [ ] Acceptance criteria map to passing evidence, including existing tests where adequate
- [ ] Meaningful changed decisions and critical failure paths are covered
- [ ] Changed boundaries have evidence from the appropriate test category
- [ ] Assertions prove outcomes and relevant forbidden effects, not just execution
- [ ] Required gates pass with no introduced regressions; baseline exceptions need explicit approval
- [ ] Skipped and blocked checks remain unverified and are explicitly dispositioned
- [ ] Test names describe the outcome and condition
