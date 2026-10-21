---
name: build-agent-tools
description: 'Python: Building LangChain @tool functions for agents — XxxSchemaDAO + XxxTool class + thin
  @tool bridge.'
when_to_use: 'For Python projects only. Use when adding a new tool the agent can call. Canonical reference:
  src/agents/tools/pubmed.py.'
group: languages
kind: skill
source_prompt: build-agent-tools.md
---

# Agent Tool Conventions

## Skill summary

- **Name:** `build-agent-tools`
- **Description:** Building LangChain @tool functions for agents — XxxSchemaDAO + XxxTool class + thin @tool bridge.
- **When to use:** Use when adding a new tool the agent can call. Canonical reference: src/agents/tools/pubmed.py.
- **Group:** `languages`
- **Kind:** `skill`
- **Source prompt:** `build-agent-tools.md`

## Examples

- The user asks: "Add or revise the agent tools for this feature."
- You want the canonical build pattern before touching agent tools.

## Guidance

**Applicability:** Python only; framework-specific sections apply only when that stack is in the project. Load `skills/languages/python/python-conventions/SKILL.md` and `skills/engineering/engineering-testing/SKILL.md` for shared obligations and test-category selection.

This document defines the rules and conventions for building agent tools in the orders-platform. Tools are the callable units that agents invoke to interact with external services, databases, and APIs.

The canonical reference implementation is [`src/agents/tools/pubmed.py`](../src/agents/tools/pubmed.py).

---

## 1. File Organisation

Each tool lives in its own file under `src/agents/tools/`. The filename should describe the external service or capability (e.g., `pubmed.py`, `duckgo_search.py`).

Every file must declare `__all__` exporting the public DAOs and the LangChain `@tool`-decorated function:

```python
__all__ = [
    "PubMedQueryArgsDAO",
    "PubMedArticleDAO",
    "pubmed_search",         # the @tool function
]
```

---

## 2. Tool Class — `XxxTool`

The implementation of a tool's logic lives inside a class with the `Tool` suffix:

```python
class PubmedSearchTool:
    @classmethod
    async def invoke(cls, query: str, max_results: int = 15) -> list[PubMedArticleDAO]:
        ...
```

### Rules

| Rule | Detail |
|---|---|
| **Suffix** | Class name ends in `Tool` (e.g., `PubmedSearchTool`, `SearchTools`) |
| **Entry point** | The public method is always named `invoke` |
| **Class methods** | Use `@classmethod` throughout — no instance state |
| **Private helpers** | Prefix with `_` (e.g., `_fetch_article_from_pmid`) |
| **Async** | `invoke` and all helpers are `async` |
| **Return type** | Always a list of DAOs (or a single DAO / RootModel) — never raw dicts, never plain strings |
| **Error handling** | `invoke` wraps the entire body in `try/except`, logs the error via `log_error`, and returns `[]` on failure |
| **Empty results** | Return `[]` — never return a message string like `"No results found"` |

### Minimal skeleton

```python
class WidgetSearchTool:
    @classmethod
    async def invoke(cls, query: str, max_results: int = 10) -> list[WidgetDAO]:
        try:
            # 1. Call external API
            # 2. Map raw results to DAOs
            # 3. Persist / enqueue if needed
            return results
        except Exception as e:
            log_error(msg="An error occurred while searching widgets", error=str(e))
            return []

    @classmethod
    async def _fetch_widget(cls, widget_id: str) -> WidgetDAO:
        ...
```

### Return type consistency

All tools must return **structured DAOs** — never plain strings. The `BaseChatAgent._serialize_tool_result()` method in `src/agents/base.py` handles JSON serialization of DAOs before they reach the LLM via `ToolMessage`. This means:

- **Pydantic `BaseModel`** → serialized via `model_dump_json()`
- **`list[BaseModel]`** → serialized via `json.dumps([item.model_dump(mode="json") for item in result])`
- **`str` fallback** → passed through as-is (avoid relying on this)

Returning DAOs instead of pre-formatted strings allows downstream consumers to access structured data, while the serialization layer ensures the LLM receives clean JSON rather than Python `repr` output.

---

## 3. DAOs — Data Access Objects

DAOs carry all data between layers. Avoid passing raw dicts or string literals between methods.

### Rules

| Rule | Detail |
|---|---|
| **Base class** | `pydantic.BaseModel` |
| **Naming** | Descriptive noun + `DAO` suffix (e.g., `PubMedArticleDAO`, `CrawlResultDAO`) |
| **`ConfigDict`** | Every DAO must declare one with at least `extra="ignore"` and `from_attributes=True` |
| **Optional fields** | Prefer `Optional[T] = None` — external data is often partial |
| **Validators** | Use `@field_validator` for coercion/normalisation, not ad-hoc inline logic |
| **Cross-domain conversion** | Add explicit converter methods (`to_document_dao()`, `to_document_dict()`) to map the tool's DAO into domain DAOs |
| **`__all__`** | Export every DAO that callers might import |

### Schema DAO — tool argument validation

Each tool also exposes a schema DAO that LangChain uses to validate agent inputs:

```python
class PubMedSearchSchemaDAO(BaseModel):
    query: str
    max_results: Optional[int] = 5
```

This is passed to `@tool(args_schema=...)` (see section 5).

### Example DAO with cross-domain conversion

```python
class PubMedArticleDAO(BaseModel):
    title: Optional[str] = None
    abstract: Optional[str] = None
    authors: list[str] = Field(default_factory=list)
    pmid: Optional[str] = None
    pmc: Optional[str] = None

    model_config = ConfigDict(
        title="PubMedArticleDAO",
        extra="ignore",
        arbitrary_types_allowed=True,
        from_attributes=True,
    )

    def to_document_dao(self) -> "DocumentDAO":
        from src.domains.documents.dao import DocumentDAO
        return DocumentDAO(
            title=self.title,
            summary=self.abstract,
            authors=", ".join(self.authors) if self.authors else None,
        )

    def to_document_dict(self) -> Dict[str, Any]:
        return self.to_document_dao().to_document_dict()
```

> **Why defer imports?** Domain imports inside methods (like `from src.domains.documents.dao import DocumentDAO`) avoid circular import issues while keeping the DAO self-contained.

---

## 4. Retries

Use `tenacity` decorators on any method that calls an external service:

```python
from tenacity import retry, stop_after_attempt, wait_exponential, before_sleep_log
import logging

@classmethod
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=10, min=10, max=40),
    before_sleep=before_sleep_log(logging.getLogger(__name__), logging.WARNING),
    reraise=True,
)
async def _fetch_article_from_pmid(cls, pmid: str, semaphore: asyncio.Semaphore) -> PubMedArticleDAO:
    ...
```

### Concurrency control

When fan-out calls are made in parallel (e.g., fetching one article per PMID), gate them with a `Semaphore`:

```python
semaphore = asyncio.Semaphore(3)  # max 3 concurrent requests
tasks = [
    asyncio.create_task(cls._fetch_widget(id=id, semaphore=semaphore))
    for id in ids
]
results = await asyncio.gather(*tasks)
```

---

## 5. The `@tool` Decorator — LangChain integration

Every tool file exposes a thin `@tool`-decorated async function that delegates to the `Tool` class. This is what the agent framework calls:

```python
from langchain.tools import tool

@tool(name_or_callable="pubmed_search", args_schema=PubMedSearchSchemaDAO)
async def pubmed_search(query: str, max_results: int = 5) -> list[PubMedArticleDAO]:
    """Search PubMed for articles matching the query.

    Args:
        query (str): The search query.
        max_results (int): Maximum number of articles to retrieve.

    Returns:
        list[PubMedArticleDAO]: Matching articles with full text where available.
    """
    log_info(msg=f"Using PubMed Search Tool with query: {query}")
    return await PubmedSearchTool.invoke(query=query, max_results=max_results)
```

### Rules

| Rule | Detail |
|---|---|
| **Name** | Snake-case, matches the tool's purpose (`pubmed_search`, `text_search`) |
| **`args_schema`** | Always provide a schema DAO — never rely on LangChain inference |
| **Docstring** | Required — this is what the LLM sees when deciding which tool to call |
| **Body** | A single `log_info` call and a delegation to `XxxTool.invoke(...)` — no logic here |

---

## 6. Async Persistence via DBOS

When tool results must be persisted, enqueue them onto the DBOS `document_persist_queue` rather than writing directly to the database. This keeps `invoke` non-blocking:

```python
@classmethod
async def _persist_articles(
    cls,
    articles: List[PubMedArticleDAO],
    dbos_client: Optional[DBOSClient] = None,
) -> None:
    if not dbos_client:
        dbos_client = DBOSClient(system_database_url=cfg("DBOS_SYSTEM_DATABASE_URL"))

    serialized = [a.to_document_dict() for a in articles if a]
    if not serialized:
        return

    options: EnqueueOptions = {
        "queue_name": "document_persist_queue",
        "workflow_name": "document_persist_workflow",
    }
    await dbos_client.enqueue_async(options, articles=serialized)
```

Key rules:
- Accept `dbos_client` as an optional parameter (makes it injectable in tests).
- Silently log and swallow persistence failures — a persistence failure must never crash the tool.
- Always filter out `None` entries before serialising.

---

## 7. `__main__` Section

Every tool file must include a runnable `__main__` block so the tool can be exercised manually without standing up the full application stack:

```python
if __name__ == "__main__":

    async def main():
        query = "What are the latest research articles on AI in medical imaging?"
        results = await PubmedSearchTool.invoke(query=query)
        for article in results:
            print(article.title)

    import asyncio
    asyncio.run(main())
```

Rules:
- The `async def main()` function must call `XxxTool.invoke(...)` directly.
- Import `asyncio` inside the block to avoid polluting the module namespace.
- Keep it simple — this is for quick smoke-testing, not production logic.

---

## 8. Logging

Use the project logger throughout (never `print`):

```python
from config.logger import log_info, log_error

log_info(msg=f"Using PubMed Search Tool with query: {query}")
log_error(msg="Failed to enqueue articles", error=str(e))
```

---

## 9. Writing Tests

Tests for a tool live at `tests/agents/tools/test_<tool_name>.py`.

- Follow `skills/coding/test-verification-policy/SKILL.md`: behavior-first tests through `invoke`, mocks only for third-party APIs, injected stubs for everything else.

### 9.1 No live API calls

- No test calls a live external service.
- Never `patch()` module names or `patch.object` private methods. Pass doubles in through keyword parameters whose default is the production implementation:

```python
class PubmedSearchTool:
    @classmethod
    async def invoke(
        cls,
        query: str,
        max_results: int = 15,
        fetcher: Optional[PubMedFetcher] = None,
        crawler_factory: Optional[Callable[..., PubmedCrawlerAppService]] = None,
        dbos_client: Optional[DBOSClient] = None,
    ) -> list[PubMedArticleDAO]:
        fetcher = fetcher or PubMedFetcher()
        crawler_factory = crawler_factory or PubmedCrawlerAppService
        ...
```

| Dependency | Kind | Test double |
|---|---|---|
| `PubMedFetcher` | Third-party API (metapub / NCBI) | `ScriptedPubMedFetcher` passed through `fetcher=` |
| `PubmedCrawlerAppService` | Internal service crawling PMC | `ScriptedCrawler` stub returned by `crawler_factory=` |
| DBOS client | Internal workflow engine | `RecordingDbosClient` stub passed through `dbos_client=` |

### 9.2 Builder helpers

Define module-level builder functions for your primary DAOs. These return fully-populated objects with overridable defaults — they are not fixtures:

```python
def _build_article(
    pmid: str = "12345",
    pmc: str = "6789",
    title: str = "Sample Article",
    abstract: str = "Sample abstract text",
    authors: list[str] = None,
    journal: str = "Nature",
    year: int = 2024,
) -> PubMedArticleDAO:
    """Build a PubMedArticleDAO with sensible defaults for testing."""
    return PubMedArticleDAO(
        pmid=pmid,
        pmc=pmc,
        title=title,
        abstract=abstract,
        authors=authors or ["Author A", "Author B"],
        journal=journal,
        year=year,
        ...
    )
```

Rules for builder helpers:
- Name them with a leading `_` (module-private).
- Accept keyword arguments matching the fields you commonly vary in tests.
- Provide sensible defaults so each test only specifies what it cares about.
- Build one helper per major DAO type used in the test file.

### 9.3 Test class organisation

Group tests by the method or concern being exercised. One class per method:

```
TestPubMedArticleDAO          # DAO serialisation (to_document_dict, to_document_dao)
TestPopulateArticle           # _populate_article
TestPopulateFreeFullTextUrl   # _populate_free_full_text_url
TestFetchArticleFromPmid      # _fetch_article_from_pmid
TestFetchFullTextForArticle   # _fetch_full_text_for_article
TestFindArticleAndLinkParsedArticle  # _find_article_and_link_parsed_article
TestPersistArticles           # _persist_articles
TestInvoke                    # invoke (journey: primary behavior test)
```

### 9.4 Async tests

Mark every async test with `@pytest.mark.asyncio`. Synchronous tests (pure DAO logic, `_find_*` helpers) do not need the marker.

```python
class TestPopulateArticle:
    @pytest.mark.asyncio
    async def test_populate_article_with_pmc(self):
        article = _build_article(pmc="6789")
        result = await PubmedSearchTool._populate_article(article=article)
        assert result.free_full_text_url == "https://pmc.ncbi.nlm.nih.gov/articles/PMC6789/"
```

### 9.5 Mocking async callables

- Write hand-written stubs, not `MagicMock` / `AsyncMock`.
- A stub implements only the methods the tool calls; `async def` methods return canned values.
- Record calls on a public list when the test asserts on them.
- Name stubs after their behavior.

```python
class ScriptedPubMedFetcher:
    """Third-party stub: answers metapub lookups from canned data."""

    def __init__(self, *, pmids: list[str], articles: dict[str, PubMedArticleDAO]) -> None:
        self._pmids: list[str] = pmids
        self._articles: dict[str, PubMedArticleDAO] = articles

    def pmids_for_query(self, query: str, retmax: int = 15) -> list[str]:
        return self._pmids

    def article_by_pmid(self, pmid: str) -> PubMedArticleDAO:
        return self._articles[pmid]


class ScriptedCrawler:
    """Internal-service stub: returns canned crawl results."""

    def __init__(self, *, results: list[PubMedParsedArticleDAO]) -> None:
        self._results: list[PubMedParsedArticleDAO] = results

    async def invoke(self) -> list[PubMedParsedArticleDAO]:
        return self._results


class RecordingDbosClient:
    """Internal queue stub: records every enqueue instead of mocking DBOSClient."""

    def __init__(self) -> None:
        self.enqueued: list[tuple[dict, dict]] = []

    async def enqueue_async(self, options: dict, **kwargs: object) -> object:
        self.enqueued.append((options, kwargs))
        return object()
```

### 9.6 End-to-end orchestration test

Always include a `TestInvoke` class that drives the full `invoke` flow with the stubs from 9.5 passed in. This is the tool's journey test, not a gated end-to-end test. Assert the returned DAOs **and** what was enqueued for persistence:

```python
class TestInvoke:
    @pytest.mark.asyncio
    async def test_invoke_returns_crawled_article_and_enqueues_it_when_pubmed_finds_a_match(self) -> None:
        """A matching PMID is returned with its crawled full text and enqueued for persistence once."""
        raw_article: PubMedArticleDAO = _build_article(pmid="12345", pmc="6789", title="AI in Diagnostics")
        crawl_result: PubMedParsedArticleDAO = _build_crawl_result(pmcid="PMC6789", title="AI in Diagnostics")
        dbos_client: RecordingDbosClient = RecordingDbosClient()

        result: list[PubMedArticleDAO] = await PubmedSearchTool.invoke(
            query="AI diagnostics",
            max_results=1,
            fetcher=ScriptedPubMedFetcher(pmids=["12345"], articles={"12345": raw_article}),
            crawler_factory=lambda **_: ScriptedCrawler(results=[crawl_result]),
            dbos_client=dbos_client,
        )

        assert [(a.title, a.parsed_article.pmcid) for a in result] == [("AI in Diagnostics", "PMC6789")]
        assert [options["queue_name"] for options, _ in dbos_client.enqueued] == ["document_persist_queue"]
        assert [d["title"] for d in dbos_client.enqueued[0][1]["articles"]] == ["AI in Diagnostics"]
```

### 9.7 Error and edge-case coverage

For every public method, include tests for:

- **Happy path** — normal input, expected output (list of DAOs).
- **Empty / no results** — e.g., empty PMID list returns `[]`.
- **None inputs** — methods that receive optional objects must handle `None` gracefully.
- **Exception propagation** — external calls that raise must not crash `invoke`; test that `[]` is returned and the error is logged.
- **Enqueue not called** — when all articles are `None`, the DBOS queue must not be touched.

### 9.8 Running the tests

```bash
loadenv environments/test.env && poetry run pytest tests/agents/tools/test_pubmed.py -v
```

---

## 10. Complete File Structure

```
src/agents/tools/
└── pubmed.py
    ├── __all__                          # exports
    ├── PubMedParsedArticleDAO           # nested crawl result shape
    ├── PubMedSearchSchemaDAO            # @tool args schema
    ├── PubMedContentDAO                 # lxml element coercion DAO
    ├── PubMedArticleDAO                 # primary result DAO
    │   ├── _coerce_content()            # field_validator
    │   ├── to_document_dao()            # cross-domain converter
    │   └── to_document_dict()           # delegates to above
    ├── PubmedSearchTool                 # tool implementation class
    │   ├── invoke()                     # public entry point
    │   ├── _fetch_article_from_pmid()   # per-PMID fetch with retry
    │   ├── _populate_article()          # DAO construction + URL population
    │   ├── _populate_free_full_text_url()
    │   ├── _fetch_full_text_for_article()  # crawler integration with retry
    │   ├── _persist_articles()          # DBOS enqueue
    │   └── _find_article_and_link_parsed_article()
    ├── pubmed_search()                  # @tool-decorated LangChain function
    └── __main__                         # manual smoke-test runner

tests/agents/tools/
└── test_pubmed.py
    ├── _build_article()                 # builder helper
    ├── _build_crawl_result()            # builder helper
    ├── TestPubMedArticleDAO             # DAO serialisation
    ├── TestToDocumentDAO                # cross-domain conversion
    ├── TestPopulateArticle
    ├── TestPopulateFreeFullTextUrl
    ├── TestFetchArticleFromPmid
    ├── TestFetchFullTextForArticle
    ├── TestFindArticleAndLinkParsedArticle
    ├── TestPersistArticles
    └── TestInvoke                       # end-to-end orchestration
```
