---
name: test-verification-policy
description: The single authority on how to test — behavior-first journey tests from entry point through application service and domain service to real persistence, real databases and files, mocks only for third-party APIs, injected stubs for everything else, and end-to-end tests only as a sparing final check.
when_to_use: Use whenever writing, planning, specifying or reviewing tests in any language, and as the final gate before declaring tests done. Other testing skills link here instead of restating these rules.
group: coding
kind: skill
source_prompt: test-verification-policy.md
---

# Test Verification Policy

## Skill summary

- **Name:** `test-verification-policy`
- **Description:** How to test: behavior-first journey tests, real persistence, mocks only for third-party APIs, injected stubs for internal collaborators, sparing end-to-end checks.
- **When to use:** Writing, specifying or reviewing tests in any language; final gate before calling tests done.
- **Group:** `coding`
- **Kind:** `skill`
- **Source prompt:** `test-verification-policy.md`

## Examples

- "Write tests for the new message-history flow." → Start with the journey test in [Python journey example](#python-journey-tui-input-to-eventsjsonl-slo).
- "Should I mock the database here?" → No. See [Test doubles](#test-doubles).
- "Do we need an end-to-end test for this sub-spec?" → Usually no. See [End-to-end tests](#end-to-end-tests).

## Guidance

**What this skill owns**

- This skill is the **single authority** for how to test: test levels, their priority, test doubles, journey discovery, end-to-end scope, naming and the done-checklist.
- [`engineering-testing`](../../engineering/engineering-testing/SKILL.md) owns evidence reporting, baselines, environment safety and the requirement-and-risk map.
- [`code-test-loop`](../code-test-loop/SKILL.md) owns cadence: when tests run.
- Language and component test recipes (`test-*`, `go-test-*`, `typescript-test-*`) show stack syntax and fixtures only. They link here and must not restate or override these rules.

**Where the examples come from**

| Language | Codebase | Why |
|---|---|---|
| Python | Slo (`slo/`) and Sentinel (`/root/Code/PythonApps/sentinel`) | Slo for TUI/file journeys; Sentinel for FastAPI, Postgres and DBOS |
| TypeScript | Sentinel (`medask_admin_app`) | Vue view → store → API client journeys |
| Go | SloAtlas (`/root/Code/slo-atlas`) | Real SQLite stores, injected stubs, gated end-to-end suite |

- Slo examples were run and pass.
- Sentinel and SloAtlas examples are quoted from the named file. Where a quoted test breaks this policy, the example shows the corrected form and says so.

---

## Core Rule

- **Test behavior, not methods.** The main proof for a feature is a journey test: from its real entry point, through the application service and domain service, to a persisted result that the test reads back.
- **Use real persistence.** Databases, files and stores are real and disposable. Never mock them.
- **Mock only third-party APIs.** LLM providers, payment, SMS and other vendor HTTP services are replaced at their client boundary.
- **Stub everything else through dependency injection.** Pass stub or test objects in through constructors, factories or parameters. Never patch internals.
- **Every meaningful decision and failure path has a passing test**, and every changed boundary has evidence. A journey test may cover several decisions at once.
- **End-to-end tests are rare and last.** Use them only for scenarios that need a real integration layer, and run them once as the final check, not after every sub-spec.
- Do not move to the next task until the current change's tests are green. Missing evidence is not completion.

---

## Test levels and priority

Write tests in this priority order. Most of a feature's tests belong to levels 1–3.

| # | Level | Starts at | Ends at | Proves | Run |
|---|---|---|---|---|---|
| 1 | **Journey (behavior)** | Real entry point: controller/router, CLI command, TUI handler, worker/task/workflow, scheduler, event handler | Persisted state read back through the real store | Wiring + orchestration + domain rules + persistence together | Every increment |
| 2 | **Application-service workflow** | `invoke()` / `Execute()` with real domain services | Persisted state + recorded calls on stubs | Step order, guards, failure cutoffs, side effects | Every increment |
| 3 | **Domain service** | One domain-service method | Real database or file | Business rules, validation, constraints, transactions | Every increment |
| 4 | **Isolated unit** | Pure function or value object | Return value or raised error | Dense decision logic with no I/O (parsers, calculators, state machines) | Every increment |
| 5 | **End-to-end** | Browser, installed binary, multi-process or multi-node stack | User-visible outcome | Real integration layers that levels 1–4 cannot reach | Once, as the final check |

- Prefer one journey test that crosses all layers over several method tests that each stop at a mock.
- Add level-2 tests for orchestration branches that a journey test cannot reach cheaply, such as a failure in step 3 of 5.
- Add level-3 and level-4 tests for dense rules. Do not duplicate every journey assertion at every level.
- No BDD framework is required. Use the project's normal runner (`pytest`, `go test`, Vitest). Given/When/Then comments are optional.

---

## Finding the journeys to test

A journey is one user- or system-triggered flow that ends in a persisted or observable result. Find them like this:

| Language | Application services | Entry points |
|---|---|---|
| Python | `src/services/**/<name>_app_service.py`, entry method `invoke()` | FastAPI routers, Typer commands, Textual message handlers, DBOS workflows, Celery tasks, schedulers, NATS/event handlers |
| Go | `*Svc` / `*Service` structs with `Execute()` in `internal/app` | `cmd/*` commands, HTTP handlers, consumers, worker pools, schedulers |
| TypeScript | Service classes with `invoke()` / `execute()` | Route handlers; for the frontend, a view that calls a store that calls an API client |

- If a project does not follow the naming, trace the flow by hand from the entry handler to the persistence write.
- Slo is an example: it has no `_app_service.py` files for this flow. The prompt journey is:

```text
PromptInput (Enter key)                       src/tui/app.py      PromptInput.Submitted
  → SloTUI.on_prompt_input_submitted          src/tui/app.py      entry point (controller)
  → SloTUI._run_prompt                        src/tui/app.py
  → SloAgentSession.invoke                    src/agents/slo_agent/sessions/service.py   application workflow
  → FilesystemSessionHistoryStore.append_event  src/agents/slo_agent/history/filesystem_store.py   persistence
  → <history root>/<session_id>/events.jsonl  read back with load_events()
```

- **Worker, task and event initiators:**
  - Keep the worker, workflow or handler body thin: it builds the application service from its arguments and calls `invoke()`.
  - Test the journey by calling that application service with exactly the arguments the worker passes.
  - Add one cheap wiring check that the worker is registered and delegates (for example Sentinel `verifier/tests/tasks/test_workers_import.py`).
  - Example: Sentinel `verifier/src/tasks/verify_question_worker.py` builds `VerifyQuestionAppService(run_id=..., question_id=..., system_under_test=..., db_session=session)` and awaits `invoke()`. The [app-service example](#python-application-service-workflow-sentinel) is therefore the worker's journey test.

---

## Test doubles

| Dependency | In tests use | Never |
|---|---|---|
| Database (Postgres, SQLite, ClickHouse) | Real disposable test database, migrations applied, rollback or fresh database per test | Mocking `AsyncSession`, ORM sessions, repositories or DAOs |
| Files and on-disk stores | Real files under `tmp_path` / `t.TempDir()` | Mocking `open`, `Path` or the store |
| Internal queues and workflow engines (DBOS, Celery, NATS, asynq) | The real engine when the test environment provides it; otherwise a **recording stub** passed in through the constructor | `MagicMock` / `AsyncMock` standing in for the engine |
| Internal collaborators (clock, ID generator, sibling service, transport, process launcher, notifier) | A **stub object** passed in through a constructor, factory or parameter | `patch()` of module internals, `patch.object` on private methods, assigning `obj._dependency = ...` |
| Third-party APIs (LLM providers, payment, SMS, vendor HTTP) | A **mock at the client boundary**: injected fake client, scripted model (`FauxChatModel`), `respx`, Go `httptest.Server`, `msw` or a `fetch` stub | Calling the real vendor; mocking deeper than the client boundary |

**Rules for stubs**

- A stub implements the same interface or protocol as the real collaborator.
- It does the minimum: canned answers, plus a record of calls when the test asserts on them.
- It is passed in through the production constructor, factory or parameter.
- **If a dependency cannot be passed in, add an injection seam:** a constructor parameter whose default is the production implementation. Then pass the stub. Do not patch.
- Name stubs after their behavior: `DiskFullHistoryStore`, `RecordingDbosClient`, `ScriptedLatticeClient`.

**Why**

- A mocked database proves nothing about SQL, constraints, transactions or rollback.
- Patching internals couples tests to private structure, so refactors break tests without changing behavior.
- Injected stubs keep the production wiring visible in the test.

---

## Python examples

### Python journey: TUI input to `events.jsonl` (Slo)

- **Level:** journey.
- **Entry:** the user types in `PromptInput` and presses Enter.
- **Doubles:** `FauxChatModel` replaces the third-party LLM. The history store is real and writes under `tmp_path`.
- **Asserts:** the message reads back from `events.jsonl`, and is recorded before the run completes.
- **Verified:** run against Slo `main` at `43e1b0e`; passes.

```python
from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

from src.agents.providers import FauxChatModel
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.history.dao import SessionHistoryEventDAO
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.tui.app import PromptInput, SloTUI


def build_session(*, workdir: Path, history_store: FilesystemSessionHistoryStore) -> SloAgentSession:
    """Build a real session: scripted model stub, real filesystem history store."""
    agent: SloAgent = SloAgent(
        llm=FauxChatModel(responses=[FauxChatModel.assistant_message(content="hi")]),
        cwd=str(workdir),
        tools=[],
    )
    return SloAgentSession(
        agent=agent,
        workdir=workdir,
        session_id=str(uuid4()),
        history_store=history_store,
        enable_history=True,
    )


async def wait_until_idle(*, session: SloAgentSession, timeout_seconds: float = 5.0) -> None:
    """Wait, with a bound, until the session finishes the run."""
    async with asyncio.timeout(timeout_seconds):
        while session.is_running:
            await asyncio.sleep(0.01)


class TestPromptInputPersistsUserMessage:
    async def test_entered_prompt_is_readable_from_session_history(self, tmp_path: Path) -> None:
        # Given a TUI over a real session whose history lives in a temp directory
        history_store: FilesystemSessionHistoryStore = FilesystemSessionHistoryStore(root=tmp_path / "history")
        session: SloAgentSession = build_session(workdir=tmp_path, history_store=history_store)
        app: SloTUI = SloTUI(session=session)

        # When the user types a message and presses Enter
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one(PromptInput).text = "hello"
            await pilot.press("enter")
            await pilot.pause()
            await wait_until_idle(session=session)
            await pilot.pause()

        # Then the message can be read back from events.jsonl, before the run completes
        events: list[SessionHistoryEventDAO] = await history_store.load_events(session_id=session.session_id)
        kinds: list[str] = [event.kind for event in events]
        user_messages: list[SessionHistoryEventDAO] = [e for e in events if e.kind == "user_message"]
        assert [m.payload.content for m in user_messages] == ["hello"]
        assert kinds.index("user_message") < kinds.index("run_completed")
        assert (tmp_path / "history" / session.session_id / "events.jsonl").is_file()
```

- The level-2 version of the same journey already exists: `slo/tests/agents/slo_agent/test_session_history.py::TestPromptPersistsLifecycleEvents::test_prompt_persists_user_message_and_run_lifecycle`. It starts at `SloAgentSession.invoke` instead of the TUI.

### Python failure path with an injected stub (Slo)

- **Level:** application-service workflow.
- **Doubles:** `DiskFullHistoryStore` is a stub passed in through the `history_store=` constructor parameter.
- **Asserts:** the error surfaces and the session is left idle.
- **Verified:** passes.
- **Corrects** `test_session_history.py::test_initial_persist_failure_aborts_run`, which swaps the store by assigning `session._history_store`. Do not assign private attributes; use the constructor.

```python
import pytest


class DiskFullHistoryStore:
    """Stub history store: every write fails as if the disk were full."""

    async def ensure_session(self, **_: object) -> None:
        raise OSError("disk full")

    async def session_exists(self, **_: object) -> bool:
        return False

    async def load_events(self, **_: object) -> list[SessionHistoryEventDAO]:
        return []

    async def append_event(self, **_: object) -> SessionHistoryEventDAO:
        raise OSError("disk full")


class TestPromptWhenHistoryWriteFails:
    async def test_run_aborts_before_the_model_is_called(self, tmp_path: Path) -> None:
        model: FauxChatModel = FauxChatModel(responses=[FauxChatModel.assistant_message(content="hi")])
        session: SloAgentSession = SloAgentSession(
            agent=SloAgent(llm=model, cwd=str(tmp_path), tools=[]),
            workdir=tmp_path,
            session_id=str(uuid4()),
            history_store=DiskFullHistoryStore(),
            enable_history=True,
        )

        with pytest.raises(OSError, match="disk full"):
            async for _event in session.invoke(text="hello"):
                pass

        assert session.is_running is False
```

### Python application-service workflow (Sentinel)

- **Source:** `sentinel/verifier/tests/services/verification/test_verify_question_app_service.py::test_invoke_lattice_happy_path_persists_result_and_enqueues_judge`.
- **Level:** application-service workflow. It is also the worker's journey, because `verify_question_workflow` only builds this service and calls `invoke()`.
- **Database:** real Postgres through the `async_db_session` fixture (savepoint rollback, `verifier/tests/conftest.py`).
- **Third-party:** the Lattice agent client is a stub returned by an injected `lattice_client_factory`.
- **Correction:** the source uses `AsyncMock(spec=DBOSClient)` for the internal DBOS queue. This policy uses a recording stub instead, shown below.

```python
class ScriptedLatticeClient:
    """Third-party stub: returns one scripted agent invocation."""

    def __init__(self, *, invocation: LatticeAgentInvocationDAO) -> None:
        self._invocation: LatticeAgentInvocationDAO = invocation

    async def invoke_agent(self, *, query: str, agent_name: str | None = None) -> LatticeAgentInvocationDAO:
        return self._invocation


class RecordingDbosClient:
    """Internal queue stub: records every enqueue instead of mocking DBOSClient."""

    def __init__(self) -> None:
        self.enqueued: list[tuple[dict, dict]] = []

    async def enqueue_async(self, options: dict, **kwargs: object) -> object:
        self.enqueued.append((options, kwargs))
        return object()


@pytest.mark.asyncio
async def test_invoke_persists_result_scores_and_enqueues_judge_when_lattice_succeeds(async_db_session) -> None:
    # Given real rows in the test database
    env = await build_environment_profile(db_session=async_db_session, name="env-vq-lat")
    question = await build_verification_question(
        db_session=async_db_session, prompt_text="lat-q", expected_tool_calls={"pubmed_search": [0, 2]},
    )
    run = await build_verification_run(db_session=async_db_session, environment_profile_id=env.id)
    await async_db_session.commit()
    invocation: LatticeAgentInvocationDAO = LatticeAgentInvocationDAO(
        response_text="answer", citation_count=3, latency_ms=10000,
        compliance_passed=True, token_usage=TokenUsageDAO(input=100, output=50),
    )
    dbos_client: RecordingDbosClient = RecordingDbosClient()

    # When the workflow runs with injected stubs
    service: VerifyQuestionAppService = VerifyQuestionAppService(
        run_id=run.id,
        question_id=question.id,
        system_under_test=SUT_LATTICE,
        db_session=async_db_session,
        lattice_client_factory=lambda *, environment_profile: ScriptedLatticeClient(invocation=invocation),
        dbos_client=dbos_client,
    )
    row: VerificationQuestionResult | None = await service.invoke()

    # Then results, scores and counters are persisted, and the judge is enqueued once
    assert row is not None and row.response_text == "answer"
    scores = await VerificationScoreService.list_for_question_result(
        verification_question_result_id=row.id, db_session=async_db_session,
    )
    assert len(scores) == 5
    refetched_run = await VerificationRunService.get(id=run.id, db_session=async_db_session)
    assert (refetched_run.completed_results, refetched_run.failed_results) == (1, 0)
    assert [options["deduplication_id"] for options, _ in dbos_client.enqueued] == [f"{row.id}:judge"]
```

### Python controller journey (Sentinel)

- **Source:** `sentinel/verifier/tests/routers/test_verification_questions_router.py::test_patch_verification_question_applies_partial_update`.
- **Level:** journey: HTTP → router → application service → domain service → Postgres.
- **Fixtures:**
  - `get_test_app` binds the real FastAPI app's `request.state.db` to the rolled-back `async_db_session` (`verifier/tests/conftest.py`).
  - No service or database is mocked.
- **Addition:** the source asserts only the response. The journey version also reads the row back through the domain service.

```python
@pytest.mark.asyncio
async def test_patch_verification_question_persists_only_present_fields(get_test_app, async_db_session) -> None:
    question = await build_verification_question(db_session=async_db_session, prompt_text="orig")
    await async_db_session.commit()
    app = get_test_app()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.patch(
            f"/v/api/v1/verification_questions/{question.id}", json={"notes": "updated note"},
        )

    assert response.status_code == 200
    assert response.json()["data"]["notes"] == "updated note"
    stored = await VerificationQuestionService.get(id=question.id, db_session=async_db_session)
    assert (stored.notes, stored.prompt_text) == ("updated note", "orig")
```

### Python decision-path illustration (domain service)

- **Level:** domain service against a real database (`async_db_session`).
- Use it to cover rules the journey tests do not reach.
- These three scenarios show distinct outcomes, not a branch-to-test formula.

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

```python
class TestBuildAndCreate:
    async def test_build_and_create_when_body_is_missing(self, async_db_session):
        """Guard clause: early raise path."""
        with pytest.raises(ValueError, match="Document body is required"):
            await DocumentService.build_and_create(async_db_session, title="Test")

    async def test_build_and_create_when_embeddings_are_generated(self, async_db_session):
        """Default path: embeddings generated and persisted."""
        doc = await DocumentService.build_and_create(async_db_session, title="Test", body="content")
        assert doc.embeddings is not None

    async def test_build_and_create_when_embeddings_are_skipped(self, async_db_session):
        """Conditional branch: skip_embeddings=True."""
        doc = await DocumentService.build_and_create(
            async_db_session, title="Test", body="content", skip_embeddings=True
        )
        assert doc.embeddings is None
```

- `generate_embeddings` calls a third-party embedding API. In a real suite, inject its client so the test can supply a scripted stub. Do not patch the static method.

---

## TypeScript examples

### TypeScript frontend journey (Sentinel)

- **Source:** `sentinel/medask_admin_app/src/views/ingestion/__tests__/AdminDocumentsListIntegration.spec.ts`.
- **Level:** journey: real view → real Pinia store → real API client → network edge.
- **Doubles:** only `fetch` is stubbed. From the frontend's side, the backend HTTP API is the external boundary. Components, stores and the client are real.

```typescript
/** Encode the backend envelope without replacing any frontend layer. */
function envelope(data: unknown): Response {
  return new Response(JSON.stringify({ data, api_version: '1.0', errors: { msg: [], code: null } }))
}

/** Mount the actual view with fresh stores and a real in-memory router. */
async function mountDocuments(): Promise<VueWrapper> {
  const pinia: Pinia = createPinia()
  setActivePinia(pinia)
  router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/documents', component: AdminDocumentsView },
    { path: '/documents/:id', component: { template: '<div>Detail</div>' } },
  ] })
  await router.push('/documents')
  await router.isReady()
  wrapper = mount(AdminDocumentsView, { global: { plugins: [pinia, router] } })
  await flushPromises()
  return wrapper
}

describe('All Documents HTTP integration', (): void => {
  beforeEach((): void => {
    vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(envelope([documentWire(), neverIndexed]))
      .mockResolvedValueOnce(envelope({ is_global_upload_permitted: true, permitted_companies: [] }))
  })

  it('renders server order, dates and independent gates alongside existing columns', async (): Promise<void> => {
    const view: VueWrapper = await mountDocuments()
    expect(view.findAll('tbody tr').length).toBe(2)
    expect(useMedaskAdminReferenceDocumentsStore().rows[0]).toMatchObject({
      lastIndexedAt: '2026-01-03T12:00:00Z', processingCompletedAt: '2026-01-03T12:00:00Z',
    })
  })
})
```

### TypeScript backend services

- The reference codebases have no TypeScript backend. The same levels and doubles apply, as in this **illustrative** example:
  - Construct the real repository against the project's disposable test database.
  - Pass stubs for internal collaborators through the constructor.
  - Intercept third-party HTTP with `msw`.
  - Never `vi.mock` a repository, database module or domain service.

```typescript
// Illustrative — real repository on the test database, msw for the vendor, stub clock.
const server = setupServer(
  http.post('https://api.payments.example/charges', () => HttpResponse.json({ id: 'ch_1' })),
)
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterAll(() => server.close())

it('persists a paid order when the charge succeeds', async (): Promise<void> => {
  const orders: OrderRepository = new OrderRepository({ db: testDb })
  const service: CheckoutService = new CheckoutService({
    orders,
    payments: new PaymentsClient({ baseUrl: 'https://api.payments.example' }),
    clock: { now: (): Date => new Date('2026-01-01T00:00:00Z') },
  })

  await service.invoke({ orderId: 'order-1' })

  expect(await orders.findById({ id: 'order-1' })).toMatchObject({ status: 'PAID', chargeId: 'ch_1' })
})
```

---

## Go examples

### Go domain/storage service on real SQLite (SloAtlas)

- **Source:** `slo-atlas/internal/storage/document_inventory_test.go::TestUpsertDocumentInventoryAdmission_PreservesEarliestIdentity`.
- **Level:** domain/storage against a real store in `t.TempDir()`. Asserts the persisted row.

```go
func TestUpsertDocumentInventoryAdmission_PreservesEarliestIdentity(t *testing.T) {
	t.Parallel()
	ctx := context.Background()
	store := newInventoryTestStore(t, ctx)
	insertBaseProvenance(t, ctx, store.DB(), "docs/a.okf.md", "v1", 900)

	require.NoError(t, store.UpsertDocumentInventoryAdmission(ctx, SetDocumentInventoryAdmissionDAO{
		LogicalPath: "docs/a.okf.md", FileVersionID: "v1", DocumentID: "doc-first",
		SyncDirectory: sql.NullString{String: "/atlas/root", Valid: true},
		CreatedAt: 1000, AdmittedAt: 1000, UpdatedAt: 1000,
	}))
	require.NoError(t, store.UpsertDocumentInventoryAdmission(ctx, SetDocumentInventoryAdmissionDAO{
		LogicalPath: "docs/a.okf.md", FileVersionID: "v1", DocumentID: "doc-second",
		SyncDirectory: sql.NullString{String: "/other/root", Valid: true},
		CreatedAt: 2000, AdmittedAt: 2000, UpdatedAt: 2000,
	}))

	page, err := store.ListDocumentInventory(ctx, DocumentInventoryListParams{Limit: 10, Offset: 0})
	require.NoError(t, err)
	require.Len(t, page.Rows, 1)
	assert.Equal(t, "doc-first", page.Rows[0].DocumentID)
	assert.EqualValues(t, 2000, page.Rows[0].UpdatedAt, "updated_at must advance on every admission call")
}
```

### Go application-service workflow with injected stubs (SloAtlas)

- **Source:** `slo-atlas/internal/app/convert_attempt_service_test.go::TestConvertAttemptSvc_DeleteForgetsAllContentVersionsForCanonicalLogicalPath`.
- **Level:** application-service workflow.
- **Real:** `storage.Store` and the `documentindex` ledger service.
- **Stubs:** `apply` (the next pipeline stage) and `now` (the clock) are injected as struct fields.
- **Asserts:** persisted rows are gone, read back with SQL.

```go
func TestConvertAttemptSvc_DeleteForgetsAllContentVersionsForCanonicalLogicalPath(t *testing.T) {
	ctx := context.Background()
	store, err := storage.NewStore(ctx, t.TempDir())
	require.NoError(t, err)
	t.Cleanup(func() { _ = store.Close() })
	ledger := documentindex.NewDocumentIndexSvc(store, nil)
	logicalPath := "docs/a.md.okf.md"
	now := time.Unix(1_800_000_000, 0).UTC()
	// ... two ClaimPipelineAttempt calls seed rows for two content MACs ...

	applied := false
	svc := &convertAttemptSvc{
		ledger: ledger,
		reader: rawContentVersionReader{syncDir: t.TempDir(), mac: mac},
		apply: func(_ context.Context, change fileChangeDAO) error {
			applied = true
			assert.Equal(t, filesync.ChangeOpDelete, change.Change.Op)
			return nil
		},
		now: func() time.Time { return now },
	}

	require.NoError(t, svc.Execute(ctx, filesync.ChangeEvent{Path: "docs/a.md", Op: filesync.ChangeOpDelete}))
	assert.True(t, applied)
	var count int
	require.NoError(t, store.DB().QueryRowContext(ctx,
		`SELECT count(*) FROM document_pipeline_attempts WHERE logical_path = ?`, logicalPath).Scan(&count))
	assert.Zero(t, count, "delete must forget every MAC tracked for the canonical logical path")
}
```

- The same file also uses `convertLedgerFake`, a recording fake of the ledger, for failure cutoffs such as "a rejected submission releases exactly once". That is an acceptable level-2 test for a branch the real ledger cannot easily force. Pair it with a real-store test, as shown above.

### Go third-party API stub (SloAtlas)

- **Source:** `slo-atlas/internal/app/document_pipeline_e2e_test.go`.
- **Level:** journey (in-process, runs under plain `go test`).
- **Third-party:** OpenAI is replaced by a scripted `httptest.Server` (`pipelineFixture`) serving `POST /v1/responses` and `POST /v1/embeddings`.
- **Real:** node, store and pipeline.

```go
func newPipelineFixture(t *testing.T, params pipelineFixtureParams) *pipelineFixture {
	t.Helper()
	f := &pipelineFixture{gated: params.Gated, scripts: map[scriptKey][]turnAnswer{}, served: map[scriptKey]int{}, parked: map[int]chan struct{}{}}
	mux := http.NewServeMux()
	mux.HandleFunc("POST /v1/responses", f.handleTurn)
	mux.HandleFunc("POST /v1/embeddings", f.handleEmbeddings)
	mux.HandleFunc("/", f.handleUnrouted)
	f.server = httptest.NewServer(mux)
	t.Cleanup(f.server.Close)
	return f
}
```

---

## End-to-end tests

**Use an end-to-end test only when all of these hold**

- The scenario needs a real integration layer that levels 1–4 cannot reach: a real browser, an installed binary, several processes or nodes, real containers or real networking.
- It is flaky or high-risk enough that it must be proven there, such as a frontend flow, a full install-and-run cycle or a multi-node sync.
- A journey test already covers the logic. The end-to-end test proves only the integration.

**How to keep them separate**

| Stack | Gate | Default suite excludes it |
|---|---|---|
| Python | `@pytest.mark.e2e` | Slo `make test` runs `pytest -m "not e2e"` |
| Go | `//go:build e2e` | SloAtlas `test/e2e/e2e_test.go`; run with `make e2e`, while `make test` stays Docker-free |
| Frontend | Separate Playwright project or script | Not part of the unit/Vitest run |

**When to run them**

- Once, as the final check for a feature, before final review or merge.
- **Not** at the end of every sub-spec implementation cycle. Each sub-spec cycle runs its journey, workflow and domain tests.
- Never replace a missing journey test with an end-to-end test.

---

## What Must Be Tested

- Use this table to find missing proof, not as a test-count formula.
- Cover distinct outcomes, meaningful changed decisions, changed contracts and relevant failure paths.
- Explicit specification matrices and critical safety paths remain mandatory.
- One clear behavioral test may traverse several branches. Parameterized cases may cover equivalent inputs.
- Reuse existing tests when they still prove the contract, and rerun them against the current change.

| Code pattern | What to prove |
|---|---|
| `if` / `else` | Both outcomes |
| `if` / `elif` / `else`, `match` / `case`, `switch` | Each distinct outcome, including the default |
| Early return / guard clause | The guard firing and the path proceeding past it |
| `try` / `except`, returned `error` | The success path and the handled failure |
| Dynamic dispatch (factory, strategy, registry) | Each concrete target |
| Conditional assignment | Each outcome that changes behavior |
| Loop with `break` / `continue` | The early exit and the full iteration |
| Feature flag / configuration branch | Each value that changes behavior |
| Orchestration step N of M fails | Later steps do not run; partial state is rolled back or recorded as specified |

---

## Workflow

1. Follow [`code-test-loop`](../code-test-loop/SKILL.md) and the selected language's test ordering. Go writes the failing test first.
2. List the journeys the change touches ([Finding the journeys](#finding-the-journeys-to-test)). Map each acceptance criterion to a journey test.
3. Write or extend the journey test first. Then add workflow, domain or unit tests for branches the journey does not reach.
4. Apply [Test doubles](#test-doubles): real persistence, third-party mocks only, injected stubs otherwise.
5. Assert outcomes **and** relevant forbidden effects (no row written, no enqueue, no later step).
6. A regression test must detect the defect it addresses. Show failure before the fix where feasible, or explain other sensitivity evidence without inventing a RED run.
7. Run the exact project commands from the routing record. Classify failures before changing code or expectations. Oracle corrections need contract evidence.
8. Run affected suites at milestones. Run end-to-end checks once, at the end of the feature, only if they exist for it.
9. Separate baseline failures, blocked checks and approved exceptions. Never manufacture green.

---

## Test Naming Convention

- Name the behavior and the condition, not just the method: `test_<behavior>_when_<condition>`.
- Go: `Test<Unit>_<Behavior>[_When<Condition>]`. TypeScript: `it('<behavior> when <condition>')`.

| Bad | Good |
|---|---|
| `test_build_and_create` | `test_build_and_create_when_body_is_missing` |
| `test_invoke` | `test_invoke_persists_result_and_enqueues_judge_when_lattice_succeeds` |
| `test_submit` | `test_entered_prompt_is_readable_from_session_history` |

---

## What Does NOT Need a Separate Test

- **Wiring:** pure delegation may not need its own test, but a journey test must show the real caller reaches the intended component with the right inputs. Testing the delegatee alone does not prove wiring.
- **Framework behavior:** do not test that FastAPI parses query parameters or SQLAlchemy flushes.
- **Trivial getters and setters:** a Pydantic field with no custom validator needs no test.

---

## Anti-patterns (seen in real code)

| Anti-pattern | Example | Do instead |
|---|---|---|
| Mocked database session | Sentinel `lattice/tests/tasks/test_reference_document_index_worker.py` yields `MagicMock()` as the session and patches the app service | Test the app service with `async_db_session`; keep one import/registration check for the worker |
| Swapping dependencies through private attributes | Slo `test_session_history.py::test_initial_persist_failure_aborts_run` sets `session._history_store` | Pass the stub through `history_store=` |
| Mocking an internal engine | Sentinel `AsyncMock(spec=DBOSClient)` | `RecordingDbosClient` stub passed in through `dbos_client=` |
| Mocking the repository in domain tests | `vi.mock('../repositories/...')`, mocked `AsyncSession` | Real repository on the test database |
| Mocking services in controller tests | `vi.mock('../services/user.service')` | Drive the real router through to the database |
| Patching private methods | `patch.object(service, "_run_clickhouse")` | Assert the observable outcome; stub only the external boundary |
| End-to-end after every sub-spec | Running a container suite per slice | Journey tests per slice; end-to-end once at the end |

---

## Verification Checklist

Before marking a task complete, confirm:

- [ ] Every acceptance criterion maps to a passing journey or workflow test, including existing tests where adequate.
- [ ] Journey tests start at the real entry point (controller, CLI, TUI, worker, scheduler or event) and read persisted state back.
- [ ] No database, file store or internal engine is mocked. Only third-party APIs are mocked, at their client boundary.
- [ ] Internal collaborators are stubs passed in through constructors, factories or parameters. Nothing is patched.
- [ ] Meaningful changed decisions and critical failure paths are covered.
- [ ] Assertions prove outcomes and relevant forbidden effects, not just execution.
- [ ] End-to-end tests exist only for integration-layer scenarios and run once as the final check.
- [ ] Required gates pass with no introduced regressions. Baseline exceptions have explicit approval.
- [ ] Skipped and blocked checks remain unverified and are explicitly dispositioned.
- [ ] Test names describe the behavior and condition.
