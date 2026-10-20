# Sample: Readable implementation contracts

This synthetic example demonstrates a complete specification family: a product
overview and one standalone engineering sub-spec. It is not an assertion about
Slo's production files, an implementation request, or runtime evidence. Paths below
belong to the example notes application. In real specifications, inspect actual
owners and cite source paths/symbols before describing current behavior.

The example uses Python/Pydantic/SQLAlchemy because those are its imagined project
conventions. Use the target repository's language and framework instead. Do not
copy the feature, technology, or document length as a requirement.

## Overview sample

**Target document:** `specifications/01-note-replacement/overview.md`

# 01 — Save notes without overwriting another editor's changes

**Status:** Proposed · **Owner:** Notes team
**Artifact:** Product overview, accompanied by a standalone engineering sub-spec

### Purpose and user journey

Two editors can open the same note. A stale editor must not silently overwrite a
newer save. Each save supplies the revision originally read; the service replaces
the note only if that revision still matches.

```text
Read note at revision 4
        │
        ▼
Edit and save with expected_revision=4
        │
        ├── Still revision 4 → save once → revision 5
        └── Already changed  → conflict  → reload before retrying
```

The caller receives an explicit conflict, not an automatic merge or retry. Archiving
also requires a short reason. Unarchived notes may omit the reason's value, but the
request must still include the field with an explicit null.

### Scope and delivery

One slice owns the request schema, conditional database update and existing save
application's wiring. No new endpoint, scheduler, history format or repository
framework. The existing authentication and note-read paths remain unchanged.

**Engineering owner:** `01.a.1-replace-note.md` (sibling document).

Release requires schema tests, real database concurrency/rollback tests, and a
functional test through the existing save entry point. No migration is needed:
the example assumes the existing table already has revision, archive and reason
columns. Rollback restores the previous application; stored columns remain valid.

**Evidence:** No tests have been run for this illustrative specification.

## Engineering sub-spec sample

**Target document:** `specifications/01-note-replacement/01.a.1-replace-note.md`

# 01.a.1 — Replace a note at an expected revision

**Status:** Proposed · **Owner:** Notes team · **Parent:** `overview.md`
**Artifact:** Standalone engineering sub-spec with a separate product overview

### 1. Purpose and scope

Prevent stale saves and validate archive reasons. This slice owns one conditional
update and its typed input. It reuses the existing note service and transaction;
it does not introduce another persistence owner or a retry loop.

### 2. Current → proposed behavior

The following current state is an assumption of this synthetic example, not a
verified repository finding. A real spec must cite the inspected source owner.

| Concern | Current example behavior | Proposed behavior |
|---|---|---|
| Save | Replaces values without a revision check | Replaces only the expected revision |
| Stale edit | May overwrite newer data | Raises `NoteRevisionConflict`; no write |
| Archive reason | Unchecked | Required nonblank value when archived |
| Transaction | Caller-owned session | Unchanged; service never commits |
| HTTP/auth/read behavior | Existing adapters and authorization | Unchanged |

### 3. Design and flow

```text
Existing save application (authorized note ID, borrowed session)
        │
        ▼
ReplaceNoteDAO → NoteService.replace
                      │
                      ▼
             UPDATE ... WHERE id AND revision
                      │
             ┌────────┴─────────┐
             ▼                  ▼
       Row returned         No row returned
       revision + 1         NoteRevisionConflict
             │                  │
             ▼                  ▼
       Caller commits       Caller rolls back
```

Missing and changed notes deliberately share the conflict outcome; the conditional
write does not probe for existence afterward. Cancellation and database errors
propagate. The caller rolls back the entire transaction on failure, never catches
and continues inside it. No implicit retry or commit is permitted.

### 4. File-by-file implementation contracts

Paths are relative to the example application root.

```text
src/domains/note/
├── dao.py                         CHANGE: replacement request and conflict type
├── service.py                     CHANGE: conditional replacement method
└── model.py                       KEEP: existing Note columns
src/services/notes/save_note.py     CHANGE: call the existing domain owner

tests/domains/note/
├── test_note_dao.py                ADD: request validation
└── test_note_service.py            ADD: real database update/rollback/concurrency
tests/services/notes/test_save_note.py  CHANGE: functional save path
```

#### `src/domains/note/dao.py`

**Proposed complete request schema.** This block is self-contained Python. Strict
scalars reject coercion; extra keys are forbidden. The request is immutable.

```python
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ReplaceNoteDAO(BaseModel):
    """Supply a complete replacement at the revision the caller read."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    expected_revision: int = Field(
        ge=0, le=2**63 - 2, description="Stored revision expected before replacement."
    )
    text: str = Field(min_length=1, max_length=4000, description="Replacement note text.")
    archived: bool = Field(description="Whether the replacement is archived.")
    reason: str | None = Field(
        min_length=1, max_length=190, description="Archive reason, or explicit null."
    )

    @model_validator(mode="after")
    def require_archive_reason(self) -> Self:
        """Reject archive requests without a nonblank reason during construction."""
        if self.archived and (self.reason is None or not self.reason.strip()):
            raise ValueError("archive_reason_required")
        return self


class NoteRevisionConflict(RuntimeError):
    """Require caller rollback when a note is missing or its revision changed."""
```

**Required-but-nullable:** `reason` has no default. Omitting it fails validation;
explicit `None` is allowed only when not archived. No trimming changes stored text.

**Cross-field invariant:** `archived=True` requires a nonblank reason. Unarchived
notes may retain a supplied reason. Revision reserves room for the one increment;
a note at the maximum database revision cannot be replaced through this interface.

#### `src/domains/note/service.py`

**Proposed ordering-sensitive implementation.** Conditional SQL is essential here:
a separate read/check/write would reintroduce the race. `Note` is the existing ORM
model; the response is the new revision, not an identity-map-dependent entity.

```python
from sqlalchemy import Update, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.domains.note.dao import NoteRevisionConflict, ReplaceNoteDAO
from src.domains.note.model import Note


class NoteService:
    """Own note persistence within caller-managed transactions."""

    @staticmethod
    async def replace(
        *, note_id: int, params: ReplaceNoteDAO, db_session: AsyncSession
    ) -> int:
        """Replace an authorized note only at its expected revision.

        The save application calls this after request validation and authorization.

        Args:
            note_id: Existing authorization-validated positive note identity.
            params: Complete validated replacement.
            db_session: Borrowed session; the caller owns commit and rollback.
        Returns:
            int: New revision, visible to others only after caller commit.
        Raises:
            NoteRevisionConflict: Missing note or changed revision; roll back.
            SQLAlchemyError: Database failure; propagate and roll back.
        """
        statement = NoteService._replacement_statement(note_id=note_id, params=params)
        revision = (await db_session.execute(statement)).scalar_one_or_none()
        if revision is None:
            raise NoteRevisionConflict("note_revision_conflict")
        return revision

    @staticmethod
    def _replacement_statement(*, note_id: int, params: ReplaceNoteDAO) -> Update:
        """Build the conditional statement for replace before any database I/O."""
        return (
            update(Note)
            .where(Note.id == note_id, Note.revision == params.expected_revision)
            .values(text=params.text, archived=params.archived, reason=params.reason,
                    revision=Note.revision + 1)
            .returning(Note.revision)
        )
```

**Transaction ownership:** the service does not create a session, begin a transaction,
commit, retry, or catch database exceptions. The existing application commits last
and rolls back on `BaseException`. The returned revision alone is not durable evidence.

#### `src/services/notes/save_note.py`

**Consumer boundary — proposed call-site excerpt.** Import the canonical request and
exception; do not duplicate either. The existing authorized save application supplies
the request and session. This example names its transaction method `save_note`;
use the real inspected symbol in a project specification. The existing entry adapter
translates domain errors after this boundary rolls back.

```python
from src.domains.note.dao import NoteRevisionConflict, ReplaceNoteDAO
from sqlalchemy.ext.asyncio import AsyncSession
from src.domains.note.service import NoteService


async def save_note(
    *, note_id: int, request: ReplaceNoteDAO, db_session: AsyncSession
) -> int:
    """Persist an already-authorized note in the caller's transaction boundary.

    The existing entry point calls this after authorization. It translates
    NoteRevisionConflict only after this function rolls back and re-raises.
    """
    try:
        revision = await NoteService.replace(
            note_id=note_id, params=request, db_session=db_session
        )
        await db_session.commit()
        return revision
    except BaseException:
        await db_session.rollback()
        raise
```

Map `NoteRevisionConflict` to the existing conflict response after rollback. This
consumer links the request definition above instead of maintaining a second schema.
In a real spec, cite and show the exact existing application method being rewired.

### 5. Implementation order and dependencies

1. Add request validation tests, then the request and canonical exception.
2. Add real persistence tests, then the conditional service method.
3. Update the existing save caller and its functional tests.
4. Run the focused suites and project verification commands.

Reuse the existing real PostgreSQL fixture and caller transaction owner. Do not
introduce a fake database to claim atomicity. No migration, data backfill, new
configuration or external publication is part of this slice.

### 6. Tests and acceptance criteria

| File / test | Setup and decisive assertion |
|---|---|
| `test_note_dao.py::test_replace_requires_explicit_reason` | Missing fails; explicit null succeeds for unarchived notes |
| `test_note_dao.py::test_archive_requires_nonblank_reason` | Archived null/blank fails; valid reason is preserved |
| `test_note_dao.py::test_replace_rejects_invalid_fields` | Extras, coerced scalars, empty/oversized text, oversized reason and revision bounds fail |
| `test_note_service.py::test_replace_when_revision_matches` | Real row; reload after commit proves values and exactly one revision increment |
| `test_note_service.py::test_replace_when_revision_conflicts` | Stale or missing row raises; fresh-session data remains unchanged |
| `test_note_service.py::test_replace_rolls_back_with_caller` | Earlier write and replacement both disappear after caller rollback |
| `test_note_service.py::test_replace_has_one_concurrent_winner` | Two sessions use the same revision; after winner commit, loser conflicts |
| `test_save_note.py::test_save_conflict_response` | Existing functional entry maps conflict after rollback; no automatic retry |
| `test_save_note.py::test_save_preserves_auth_and_failure_cleanup` | Unauthorized writes refused; DB failure/cancellation rolls back and propagates |

These are example-project commands, not commands to run against Slo. Confirm a
disposable database and the project's safe test configuration before executing.

```bash
poetry run pytest tests/domains/notetests/services/notes/test_save_note.py
poetry run black --check src/domains/note tests/domains/note
poetry run mypy src/ tests/
```

Acceptance: stale saves never overwrite newer data; valid saves increment once;
archive reasons are validated; caller atomicity and existing auth/read behavior
remain intact. Tests map to the rules above rather than repeat the complete schema.
No manual UI check is required for this non-visual slice. No tests have been run.

## How to use this sample

Preserve the pattern, not the incidental code. Real specifications must resolve
actual types, imports, file placement, source citations, fixture names and commands.
Keep code examples consistent with the target project's method/docstring rules.
Missing material decisions block readiness; do not fill them with invented facts.
Keep review reports, historical fixes and workflow counters outside the contract.
