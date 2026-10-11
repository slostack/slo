---
name: development-reviews
description: Write clear, actionable merge-request and pull-request reviews that explain problems, prescribe convention-aligned solutions, verify specification coverage, and rank findings by severity.
when_to_use: Use when reviewing a merge request (MR), pull request (PR), or proposed implementation and the author needs guided, implementation-ready feedback.
group: design-and-analysis
kind: workflow
source_prompt: development-reviews.md
---

# Development Reviews: Clear MR and PR Feedback

## Skill summary

- **Name:** `development-reviews`
- **Description:** Write clear, actionable merge-request and pull-request reviews that explain problems, prescribe convention-aligned solutions, verify specification coverage, and rank findings by severity.
- **When to use:** Use when reviewing a merge request (MR), pull request (PR), or proposed implementation and the author needs guided, implementation-ready feedback.
- **Group:** `design-and-analysis`
- **Kind:** `workflow`
- **Source prompt:** `development-reviews.md`

## Examples

- Review an MR that introduces a duplicate SQLAlchemy mapping and explain the
  permitted read-only cross-domain model boundary instead.
- Review a list page against its specification, identify missing permissions,
  filter metadata, accessibility, export, and test coverage, then provide a
  ranked completion checklist.
- Turn vague feedback such as "this architecture is wrong" into a clear
  problem, consequence, convention-aligned solution, example code, and
  verification plan.

## Guidance

**Multi-language scope:** Begin with `skills/engineering/engineering-routing/SKILL.md`.
Read shared obligations and only affected language/component/framework recipes.
Python-specific examples and commands below are scoped examples, not universal
requirements. For mixed-language work preserve each boundary's approved contract.
Use `skills/engineering/engineering-testing/SKILL.md` for test categories and evidence.

## Goal

Write a review that helps the author fix the change, rather than merely telling
that author something is wrong. Use simple language, lead the reader from the
problem to the preferred design, and show enough concrete code and structure
that the next implementation step is clear.

A good review must:

1. Explain the current problem and its practical risks.
2. Recommend the right approach using the repository's existing conventions.
3. Give focused implementation examples, folder layout, and explanations.
4. Check every relevant specification requirement and test requirement.
5. Rank issues by severity so the author knows what to fix first.
6. End with one actionable checklist for code, tests, documentation, and
   decisions still needed.

This is a **whole-MR/PR review**. For a narrow, per-turn coding-agent
handshake, use the collaboration protocol only when that workflow is explicitly
requested. For a feature review against a formal specification, also apply
[`skills/design-and-analysis/review-feature-code/SKILL.md`](../review-feature-code/SKILL.md)
and the hard-rule pass in
[`skills/languages/python/code-review-rules/SKILL.md`](../../languages/python/code-review-rules/SKILL.md).

---

## Review Principles

### Be direct, kind, and specific

- Start by recognizing working parts when they materially help the feature.
- Describe the issue in plain words before using framework or database terms.
- Cite the affected file and line when available.
- State the consequence: data loss, incorrect results, dead code, unclear
  ownership, missing authorization, fragile migrations, or an untestable flow.
- Give a preferred change, not only a criticism.
- Do not invent requirements, existing ownership, or conventions. Read the
  specification, surrounding code, and relevant skills first. Ask a question
  when the source of truth is unavailable.

### Prefer the smallest convention-aligned solution

Do not redesign a feature merely because a different architecture is possible.
First find the existing domain owner, service boundaries, data models, naming,
and test layout. Then recommend the smallest change that preserves those
boundaries.

For example, if the repository explicitly permits one application to import
another domain's SQLAlchemy model for **read-only** queries, recommend that
explicit boundary. Do **not** recommend a duplicate model, a second mapping for
the same table, a new access table, or a shared schema package unless the
specification and repository conventions require one.

### Teach through a guided sequence

Use this order whenever it fits:

1. **What is already good** — concise and factual.
2. **What needs to change** — ranked findings and risks.
3. **Recommended design** — ownership and boundaries in simple language.
4. **How to implement it** — code snippets, folder tree, and explanations.
5. **What remains incomplete** — requirements, tests, and documentation.
6. **Checklist** — one place the author can work from.

---

## Step-by-Step Review Process

### Step 1 — Load the facts before writing feedback

Read, in this order:

1. The MR/PR description and linked ticket, RFC, or specification.
2. The complete diff, including migrations, registration/wiring, and tests.
3. Existing code adjacent to the change, especially the domain that owns each
   table, API, queue, route, or UI concept.
4. Relevant `skills/coding/` convention files for each changed layer.
5. Existing tests and test fixtures for the affected feature.

Create two working checklists:

- **Specification checklist:** each functional requirement, permission,
  validation rule, UI behavior, export/documentation obligation, and acceptance
  criterion.
- **Test checklist:** each changed decision point plus happy path, errors,
  boundary conditions, null/empty data, ordering, paging, authorization,
  retries, and integration wiring where applicable.

Do not treat a file's existence as evidence that a requirement is complete.
Trace the behavior end-to-end.

### Step 2 — Trace ownership and the end-to-end flow

For every changed concept, answer:

- Who owns the database table, model, API contract, domain vocabulary, and
  write operations?
- Which layer is responsible for request binding, orchestration, business/query
  logic, persistence, and response mapping?
- What starts the flow, what services call one another, and what reaches the
  user or downstream system?
- Is a cross-domain read permitted? If so, where should that dependency be
  explicit?
- Are all joins, queue registrations, router inclusions, migrations, and UI
  navigation paths actually wired?

For a Python/FastAPI feature, preserve the established flow:

```text
router → application service → domain service → DAO/model/query
```

The router handles request binding, permission dependencies, and response
wrapping. The application service coordinates the use case and makes permitted
cross-domain dependencies explicit. The domain service owns query/business
logic. DAOs describe inputs and outputs. Keep a domain's model in its owning
application; do not silently duplicate it in a consumer application.

### Step 3 — Find and rank issues

Rank findings by user impact and merge risk, not by the order files appear in
the diff.

| Severity | Meaning | Examples |
|---|---|---|
| **Critical** | Must not merge. It can create a security, data-integrity, or production-outage risk. | Authorization missing; migration corrupts/global-mutates metadata; writes to a model owned by another domain; query returns the wrong account's data. |
| **High** | Must fix before merge. A core requirement is missing, behavior is incorrect, or the feature cannot be reliably maintained/tested. | Duplicate SQLAlchemy mapping; incorrect latest-record selection; rows disappear because an outer join should be a left join; no tests for core branches. |
| **Medium** | Should fix in this MR unless the team explicitly records and accepts a deferral. | Filter metadata is incomplete; keyboard navigation is absent; an API field is ambiguously named; edge-case coverage is missing. |
| **Low** | Non-blocking improvement. | Clarify a docstring, improve a variable name, add a useful nonessential test. |

For every finding, use this pattern:

```markdown
### [High] Short action-oriented title

**Where:** `path/to/file.py:42`

**Problem:** Explain what the current approach does.

**Why it matters:** Explain the concrete bad outcome.

**Recommended change:** State the smallest convention-aligned fix.

**Verification:** Name the tests or manual checks that prove the fix.
```

Do not label a finding "High" without explaining why it affects correctness,
security, data ownership, or a required behavior.

### Step 4 — Explain the preferred design

For an architectural finding, write the recommended boundary in one sentence
before showing code. For example:

> The Admin application service may import Doctors-owned models directly for
> read-only directory queries. The Admin domain service owns the directory
> projection and joins it to Admin-owned redemption data; it does not create a
> second Doctor model or write Doctors-owned tables.

Then explain:

- what remains owned by each domain;
- where the dependency belongs;
- what is read-only versus writable;
- the rule used to resolve ambiguous business data; and
- behavior for missing, inactive, or repeated records.

When a query selects a related "current" record, make the rule explicit. For
example: "Sponsor, coupon, and plan come from the doctor's latest successful
coupon redemption." State null behavior and a stable tie-breaker as well:

```text
no redemption → sponsor/coupon/plan are null
multiple redemptions → highest redeemed_at, then highest id
deactivated account → keep the row and show deactivated status
```

### Step 5 — Provide implementation-ready examples

Examples must be illustrative but realistic. Keep them small enough to read,
but complete enough to show dependencies, method names, and boundaries.

#### Application-service boundary example

```python
# src/apps/admin_backend/services/doctors/list_doctors_app_service.py
from sqlalchemy.ext.asyncio import AsyncSession

from src.apps.admin_backend.domains.doctor_directory.dao import (
    AdminDoctorListDAO,
    ListDoctorsQueryDAO,
)
from src.apps.admin_backend.domains.doctor_directory.service import (
    DoctorDirectoryService,
)
from src.apps.doctors_backend.domains.doctor.model import Doctor
from src.apps.doctors_backend.domains.session.model import Session


class ListDoctorsAppService:
    """Coordinate the admin doctor-directory use case."""

    def __init__(
        self,
        *,
        db_session: AsyncSession,
        query: ListDoctorsQueryDAO,
    ) -> None:
        self.db_session: AsyncSession = db_session
        self.query: ListDoctorsQueryDAO = query

    async def invoke(self) -> AdminDoctorListDAO:
        """Return the requested doctor-directory page."""
        return await DoctorDirectoryService.list_page(
            db_session=self.db_session,
            query=self.query,
            doctor_model=Doctor,
            session_model=Session,
        )
```

Explain that the application service is the explicit cross-domain boundary. The
Admin domain service receives the model classes and retains the Admin-owned
projection, SQL, filters, ordering, paging, and result mapping.

#### Query-rule example

For latest-related-record queries, show deterministic selection and explain the
join type:

```python
@staticmethod
def _build_latest_redemption_relation() -> Subquery:
    """Return the latest successful redemption associated with each doctor."""
    ranked_redemptions: Subquery = (
        sa.select(
            AccessCodeRedemption.doctor_id,
            AccessCodeRedemption.company_id,
            AccessCodeRedemption.access_code_id,
            sa.func.row_number()
            .over(
                partition_by=AccessCodeRedemption.doctor_id,
                order_by=(
                    AccessCodeRedemption.redeemed_at.desc(),
                    AccessCodeRedemption.id.desc(),
                ),
            )
            .label("redemption_rank"),
        )
        .where(AccessCodeRedemption.doctor_id.is_not(None))
        .where(AccessCodeRedemption.is_successful.is_(True))
        .subquery("ranked_doctor_redemptions")
    )

    return (
        sa.select(
            ranked_redemptions.c.doctor_id,
            ranked_redemptions.c.company_id,
            ranked_redemptions.c.access_code_id,
        )
        .where(ranked_redemptions.c.redemption_rank == 1)
        .subquery("latest_doctor_redemptions")
    )
```

Call out that the directory query must use **left joins** for optional related
records. An inner join would incorrectly hide doctors without a redemption or
session activity.

#### Migration safety example

Flag runtime metadata mutation as risky when it attempts to hide a duplicate
mapping:

```python
# Do not mutate shared metadata at runtime to hide a duplicate table.
doctor_metadata.remove(doctor_metadata.tables[table_name])
```

Explain the preferred fix:

1. Keep each physical table mapped in its owning domain only.
2. Remove duplicate mappings that are no longer needed.
3. Combine normal metadata objects for migration discovery if the repository
   requires it, without deleting tables from global metadata in memory.
4. Add a migration test or generation check when the migration setup changes.

### Step 6 — Show the target folder structure

Use a concise tree to help the author place code correctly. Tailor it to the
repository, such as:

```text
src/apps/admin_backend/
├── routers/
│   └── doctors_router.py
│       # Request binding, permission dependency, response envelope only.
├── services/doctors/
│   └── list_doctors_app_service.py
│       # Explicit read-only import of Doctors models; coordinates the use case.
├── domains/doctor_directory/
│   ├── dao.py
│   │   # Query, list-item, and pagination data contracts.
│   └── service.py
│       # Joins, filters, ordering, paging, and row mapping.
└── tests/
    ├── controllers/test_doctors_controller.py
    ├── services/doctors/test_list_doctors_app_service.py
    └── domains/doctor_directory/test_doctor_directory_service.py
```

Also say what must **not** be added, where that prevents future mistakes: for
example, no Admin-owned duplicate `Doctor` SQLAlchemy model and no new access
mapping table when existing relations already answer the query.

### Step 7 — Verify specification and tests explicitly

Include two tables in the review whenever a specification is available.

#### Specification coverage

```markdown
| Requirement | Status | Evidence | Needed action |
|---|---|---|---|
| Directory is visible to authorized roles | Partial | Route exists | Add and test the superadmin/admin/operator permission matrix. |
| Filter metadata contains all companies/coupons | Missing | UI uses first 50 results | Provide complete filter metadata or a search endpoint. |
| CSV export is safe and server-side | Missing | No endpoint/control behavior | Implement and test export, or record deferral and omit/disable the control. |
```

Use **Implemented**, **Partial**, **Missing**, or **Deferred (explicitly
recorded)**. A control that looks available but has no safe backend behavior is
not implemented.

#### Test coverage

```markdown
| Area | Existing coverage | Required coverage |
|---|---|---|
| Directory SQL | Happy-path page only | No redemption, no session, latest successful redemption, name/email search, combined filters, ordering, page bounds. |
| Application service | None | Delegates models and query to the domain service. |
| Controller | Request parsing only | Permission matrix, validation, envelope, route wiring. |
```

Required tests for a directory/list query commonly include:

- primary records with no optional relation;
- primary records with no activity/history;
- deterministic latest-record selection, including tie-breaks;
- searches against every promised searchable field;
- each filter alone and meaningful combined filters;
- ordering in both expected and boundary cases;
- pagination sizes, empty result, and out-of-range/final-page recovery;
- account status behavior, including inactive records when required;
- permission matrix for every stated role;
- API validation, response envelope, and error behavior;
- app-service delegation and cross-domain read boundary;
- migration behavior if metadata or schema discovery changes.

Tests must assert observable behavior. Do not accept a test that only checks
that a method returned a non-null result.

### Step 8 — End with one completion checklist

The final checklist groups remaining work by type. Mark verified items as done
and unimplemented/deferred items as open. Include documentation as well as
code and tests.

```markdown
## Completion checklist

### Must fix before merge
- [ ] Replace the duplicate model/metadata workaround with the documented
      read-only cross-domain model import.
- [ ] Use left joins so doctors without redemption or session data remain
      visible.
- [ ] Define and document the latest-successful-redemption rule, including the
      `redeemed_at`, then `id`, tie-breaker.
- [ ] Add the required authorization rule and permission-matrix tests.

### Required tests
- [ ] Add domain SQL tests for null relations, latest redemption, searching,
      filters, ordering, paging, and final-page recovery.
- [ ] Add application-service delegation/boundary tests.
- [ ] Add controller tests for permissions, validation, and response envelope.

### Product/specification decisions
- [ ] Supply complete company/coupon filter metadata.
- [ ] Move specialty values to a stable backend/shared source.
- [ ] Make rows keyboard-accessible and ready to navigate to `/doctors/:id`.
- [ ] Implement safe server-side CSV export, or document its deferral and keep
      its UI unavailable.

### Documentation
- [ ] Document model ownership and the permitted read-only dependency.
- [ ] Document the sponsor/coupon/plan selection rule and null behavior.
- [ ] Update API/OpenAPI, feature documentation, and release notes as required.
```

---

## Recommended MR/PR Review Template

```markdown
## Summary

<One short paragraph: what is working, overall merge readiness, and the main
reason changes are needed.>

## Findings by severity

### Critical — must fix before merge

<Use the finding pattern: Where / Problem / Why it matters / Recommended change /
Verification. Omit this heading if empty.>

### High — must fix before merge

### Medium — should fix in this MR

### Low — non-blocking improvements

## Recommended design

<Describe the ownership model, layer boundaries, and explicit business rule in
plain language.>

### Implementation example

```python
<Small, convention-aligned example>
```

### Target structure

```text
<Folder tree with responsibilities>
```

## Specification coverage

| Requirement | Status | Evidence | Needed action |
|---|---|---|---|

## Test assessment

| Area | Existing coverage | Required coverage |
|---|---|---|

## Completion checklist

### Must fix before merge
- [ ] ...

### Required tests
- [ ] ...

### Documentation and decisions
- [ ] ...
```

---

## Quality Bar Before Posting the Review

- [ ] Findings are ordered Critical → High → Medium → Low.
- [ ] Every blocking finding gives a concrete consequence and a concrete fix.
- [ ] The recommendation follows the repository's existing ownership and layer
      conventions.
- [ ] Code examples use real project-style imports, type hints, named arguments,
      docstrings, and the established service flow.
- [ ] The review identifies what is implemented, partial, missing, and explicitly
      deferred from the specification.
- [ ] The review distinguishes tests that exist from the behaviors those tests
      actually prove.
- [ ] Required tests are named precisely enough for the author to implement.
- [ ] The final checklist includes code, tests, product decisions, and
      documentation.
- [ ] The language is simple, respectful, and actionable.

## Related Skills

- [`skills/design-and-analysis/review-feature-code/SKILL.md`](../review-feature-code/SKILL.md)
  — formal spec-to-code and end-to-end review process.
- [`skills/languages/python/code-review-rules/SKILL.md`](../../languages/python/code-review-rules/SKILL.md)
  — hard-rule enforcement pass for every diff.
- [`skills/languages/python/build-application-services/SKILL.md`](../../languages/python/build-application-services/SKILL.md)
  — application-service boundary and `invoke()` convention.
- [`skills/languages/python/build-domain-features/SKILL.md`](../../languages/python/build-domain-features/SKILL.md)
  — domain ownership and DAO/model/service structure.
- [`skills/coding/test-verification-policy/SKILL.md`](../../coding/test-verification-policy/SKILL.md)
  — decision-point and edge-case test expectations.
- [`skills/design-and-analysis/update-documentation-after-code-changes/SKILL.md`](../update-documentation-after-code-changes/SKILL.md)
  — documentation work to include in the final checklist.
