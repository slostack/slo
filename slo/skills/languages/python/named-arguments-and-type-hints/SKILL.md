---
name: named-arguments-and-type-hints
description: 'Python: Always pass keyword arguments and use explicit type hints.'
when_to_use: For Python projects only. Apply on every method/function definition and every call site.
  Non-negotiable.
group: languages
kind: skill
source_prompt: named-arguments-and-type-hints.md
---

# Named Arguments and Type Hints

## Skill summary

- **Name:** `named-arguments-and-type-hints`
- **Description:** Always pass keyword arguments and use explicit type hints.
- **When to use:** Apply on every method/function definition and every call site. Non-negotiable.
- **Group:** `languages`
- **Kind:** `skill`
- **Source prompt:** `named-arguments-and-type-hints.md`

## Examples

- The user asks for help with: Always pass keyword arguments and use explicit type hints.
- Apply on every method/function definition and every call site. Non-negotiable.

## Guidance

**Applicability:** Python only; framework-specific sections apply only when that stack is in the project. Load `skills/languages/python/python-conventions/SKILL.md` and `skills/engineering/engineering-testing/SKILL.md` for shared obligations and test-category selection.

All function calls and method signatures must use **named arguments** and **explicit type hints** to enforce maximum clarity. This is a mandatory convention — not a suggestion.

---

## 1. Named Arguments at Call Sites

Every function call with more than one argument must use named arguments (keyword arguments). This makes code self-documenting and eliminates ambiguity about parameter order.

### Rules

| Rule | Detail |
|---|---|
| **Single argument** | Positional is acceptable if the meaning is obvious (e.g., `len(items)`, `str(value)`) |
| **Two or more arguments** | Always use named arguments |
| **Boolean arguments** | Always named, regardless of count — `do_thing(verbose=True)`, never `do_thing(True)` |
| **Default arguments** | Still name them when overriding — `search(query="AI", limit=5)`, never `search("AI", 5)` |

### Examples

```python
# --- Bad: positional arguments ---

results = await DocumentService.search_by_query(
    "AI imaging", db_session, 10, 0.5
)

article = PubMedArticleDAO("Title", "Abstract", ["Author A"], "Nature", 2024)

await cls._persist_articles(articles, mock_client)


# --- Good: named arguments ---

results = await DocumentService.search_by_query(
    query="AI imaging",
    db_session=db_session,
    limit=10,
    max_distance=0.5,
)

article = PubMedArticleDAO(
    title="Title",
    abstract="Abstract",
    authors=["Author A"],
    journal="Nature",
    year=2024,
)

await cls._persist_articles(articles=articles, dbos_client=mock_client)
```

### Why

- **Readability** — the call site documents itself. A reader doesn't need to look up the function signature to understand what each argument means.
- **Refactoring safety** — parameter order can change without breaking call sites.
- **Prevents bugs** — positional arguments with the same type (e.g., two strings, two ints) can be accidentally swapped. Named arguments make this impossible.

---

## 2. Type Hints on Every Signature

Every function, method, and variable assignment of significance must have explicit type hints. This applies to parameters, return types, and local variables that hold non-trivial values.

### Rules

| Rule | Detail |
|---|---|
| **Function parameters** | Every parameter must have a type hint |
| **Return types** | Every function and method must declare its return type |
| **Local variables** | Type-hint when the type isn't obvious from the right-hand side, or when it aids readability |
| **Optional types** | Use `Optional[T]` with a default of `None` — never leave `None` defaults untyped |
| **Container types** | Be specific — `list[PubMedArticleDAO]`, not `list`. `Dict[str, Any]`, not `dict` |
| **Class attributes** | Type-hint in `__init__` or as class-level annotations |

### Examples

```python
# --- Bad: missing or vague type hints ---

async def search(query, limit=10, max_distance=None):
    results = await service.find(query)
    return results

def _build_article(pmid="12345", title="Sample"):
    return PubMedArticleDAO(pmid=pmid, title=title)


# --- Good: explicit type hints ---

async def search(
    query: str,
    limit: int = 10,
    max_distance: Optional[float] = None,
) -> List[LocalSearchResultDAO]:
    results: List[LocalSearchResultDAO] = await service.find(query=query)
    return results

def _build_article(
    pmid: str = "12345",
    title: str = "Sample",
) -> PubMedArticleDAO:
    return PubMedArticleDAO(pmid=pmid, title=title)
```

### Return type consistency

Return types must be truthful. If a function claims to return `list[PubMedArticleDAO]`, it must return that type on **every code path** — including error paths and empty-result paths.

```python
# --- Bad: return type lies ---

async def invoke(cls, query: str) -> list[PubMedArticleDAO]:
    try:
        ...
        return articles
    except Exception as e:
        return f"An error occurred: {str(e)}"  # str != list[PubMedArticleDAO]


# --- Good: return type is honest ---

async def invoke(cls, query: str) -> list[PubMedArticleDAO]:
    try:
        ...
        return articles
    except Exception as e:
        log_error(msg="An error occurred", error=str(e))
        return []  # matches declared return type
```

---

## 3. Variable Type Hints for Clarity

Use type hints on local variables when the assignment isn't self-explanatory or when it aids code navigation.

```python
# Helpful — clarifies the expected type from an async call
documents: List[Document] = await DocumentService.search_by_query(
    query=query,
    db_session=db_session,
    limit=limit,
)

# Helpful — makes the loop variable type explicit
results: List[LocalSearchResultDAO] = [
    LocalSearchResultDAO.from_document(doc) for doc in documents
]

# Not needed — type is obvious from the constructor
schema = LocalSearchSchemaDAO(query="test")
```

---

## 4. Applying to Tests

The same conventions apply in test code. Tests should be as readable as production code.

```python
# --- Good: named arguments and type hints in tests ---

class TestLocalSearchToolSearch:
    @pytest.mark.asyncio
    async def test_returns_mapped_daos(self):
        mock_session: MagicMock = MagicMock()
        doc: MagicMock = _build_document(title="AI in Radiology", summary="Deep learning")

        with patch("src.agents.tools.local_search.DocumentService") as MockService:
            MockService.search_by_query = AsyncMock(return_value=[doc])

            results: List[LocalSearchResultDAO] = await LocalSearchTool._search(
                query="medical imaging AI",
                limit=10,
                max_distance=None,
                db_session=mock_session,
            )

        assert isinstance(results, list)
        assert results[0].title == "AI in Radiology"
```

---

## Summary Checklist

Before submitting any code, verify:

- [ ] Every function call with 2+ arguments uses named arguments
- [ ] Every boolean argument is named, even if it's the only argument
- [ ] Every function and method has parameter type hints and a return type
- [ ] `Optional[T] = None` is used for nullable parameters — never bare `= None`
- [ ] Container types are specific (`list[str]`, not `list`)
- [ ] Return types are honest — every code path returns the declared type
- [ ] Local variable type hints are used where they aid clarity
