---
name: api-response-conventions
description: Language-independent API response envelopes, scoped profiles, pagination semantics, and compatibility rules.
when_to_use: Use when designing, reviewing, documenting, or testing an API response contract before selecting a language or framework adapter.
group: coding
kind: skill
---

# API Response Conventions

## Skill summary

- **Name:** `api-response-conventions`
- **Scope:** The stable, language-independent semantics of the project's API response family.
- **Family:** The existing response family is `{data, api_version, errors}`. The family is a semantic baseline; a project profile supplies exact wire values and implementation details.
- **Use with:** The applicable Python, Go, TypeScript, framework, client, documentation, and test recipes. This skill is not a replacement for those scoped recipes.
- **Compatibility rule:** Existing deployed wire bytes remain authoritative. A profile may override generic defaults, but cleanup must not silently change wire bytes, counts, field names, page bases, version formats, error shapes, or error codes. Such changes require explicit contract approval.

## Examples

The following examples are **illustrative samples**, not copied production snippets. They intentionally use one selected illustrative profile in all three languages:

- root keys are exactly `data`, `api_version`, and `errors`;
- the version is the illustrative string `"v1.0"`;
- success uses `errors: {"msg": [], "code": null}`;
- failure uses `data: null` and a public `NOT_FOUND` code;
- pagination is inside `data`, uses zero-based `page`, `size: 25`, `total`, and `items`; and
- this sample profile defines `total` as the total matching the endpoint's documented query and caps `size` at `100`.

A real project profile may select different values or names. Those choices are not interchangeable: preserve the deployed profile and obtain explicit contract approval before changing it.

### Python — illustrative typed envelope and serialization

```python
# Illustrative sample; not copied from production and not executed here.
from dataclasses import asdict, dataclass
from typing import Generic, TypeVar
import json

PayloadT = TypeVar("PayloadT")


@dataclass(frozen=True)
class ResponseErrors:
    msg: list[str]
    code: str | None


@dataclass(frozen=True)
class ApiResponse(Generic[PayloadT]):
    data: PayloadT | None
    api_version: str
    errors: ResponseErrors


@dataclass(frozen=True)
class User:
    id: str
    display_name: str


@dataclass(frozen=True)
class UserPage:
    page: int
    size: int
    total: int
    items: list[User]


success: ApiResponse[User] = ApiResponse(
    data=User(id="u1", display_name="Ada"),
    api_version="v1.0",
    errors=ResponseErrors(msg=[], code=None),
)
error: ApiResponse[User] = ApiResponse(
    data=None,
    api_version="v1.0",
    errors=ResponseErrors(msg=["User not found"], code="NOT_FOUND"),
)
page: ApiResponse[UserPage] = ApiResponse(
    data=UserPage(
        page=0,
        size=25,
        total=1432,
        items=[User(id="u1", display_name="Ada")],
    ),
    api_version="v1.0",
    errors=ResponseErrors(msg=[], code=None),
)

# A production adapter should use its selected serializer (for example Pydantic).
wire_success = json.dumps(asdict(success))
wire_error = json.dumps(asdict(error))
wire_page = json.dumps(asdict(page))
```

### Go — illustrative typed envelope and serialization

```go
// Illustrative sample; not copied from production and not compiled here.
package envelope

import "encoding/json"

type ResponseErrors struct {
    Msg  []string `json:"msg"`
    Code *string  `json:"code"`
}

type APIResponse[T any] struct {
    Data       *T            `json:"data"`
    APIVersion string        `json:"api_version"`
    Errors     ResponseErrors `json:"errors"`
}

type User struct {
    ID          string `json:"id"`
    DisplayName string `json:"display_name"`
}

type UserPage struct {
    Page  int    `json:"page"`
    Size  int    `json:"size"`
    Total int    `json:"total"`
    Items []User `json:"items"`
}

func success[T any](data T) APIResponse[T] {
    return APIResponse[T]{
        Data: &data,
        APIVersion: "v1.0",
        Errors: ResponseErrors{Msg: []string{}, Code: nil},
    }
}

func failure[T any](message string, code string) APIResponse[T] {
    return APIResponse[T]{
        Data: nil,
        APIVersion: "v1.0",
        Errors: ResponseErrors{Msg: []string{message}, Code: &code},
    }
}

func exampleWireBytes() ([]byte, []byte, []byte, error) {
    object := success(User{ID: "u1", DisplayName: "Ada"})
    notFound := failure[User]("User not found", "NOT_FOUND")
    page := success(UserPage{
        Page: 0,
        Size: 25,
        Total: 1432,
        Items: []User{{ID: "u1", DisplayName: "Ada"}},
    })
    objectBytes, err := json.Marshal(object)
    if err != nil {
        return nil, nil, nil, err
    }
    errorBytes, err := json.Marshal(notFound)
    if err != nil {
        return nil, nil, nil, err
    }
    pageBytes, err := json.Marshal(page)
    return objectBytes, errorBytes, pageBytes, err
}
```

### TypeScript — illustrative typed envelope and serialization

```typescript
// Illustrative sample; not copied from production and not compiled here.
type ResponseErrors = {
  msg: string[]
  code: string | null
}

type ApiResponse<T> = {
  data: T | null
  api_version: string
  errors: ResponseErrors
}

type User = {
  id: string
  display_name: string
}

type UserPage = {
  page: number
  size: number
  total: number
  items: User[]
}

const success: ApiResponse<User> = {
  data: { id: "u1", display_name: "Ada" },
  api_version: "v1.0",
  errors: { msg: [], code: null },
}

const error: ApiResponse<User> = {
  data: null,
  api_version: "v1.0",
  errors: { msg: ["User not found"], code: "NOT_FOUND" },
}

const page: ApiResponse<UserPage> = {
  data: {
    page: 0,
    size: 25,
    total: 1432,
    items: [{ id: "u1", display_name: "Ada" }],
  },
  api_version: "v1.0",
  errors: { msg: [], code: null },
}

const wireSuccess = JSON.stringify(success)
const wireError = JSON.stringify(error)
const wirePage = JSON.stringify(page)
```

## Guidance

### Framework recipe links

The generic owner delegates concrete behavior to the existing language recipes:

- `skills/languages/python/api-response-conventions/SKILL.md`
- `skills/languages/go/go-recipe-api-response-conventions/SKILL.md`
- `skills/languages/typescript/typescript-api-response-conventions/SKILL.md`
- `skills/languages/typescript/typescript-build-routers/SKILL.md`

### 1. Shared semantics and scoped profiles

For a new API that explicitly adopts this family, the response is a JSON object with the root keys `data`, `api_version`, and `errors`:

- `data` carries the successful payload. A successful `null` payload is valid only when the endpoint profile documents an empty or no-content success semantic.
- `api_version` is a string. The project profile selects its exact value and format; this skill does not convert among `"v1.0"`, `"1.0"`, `"v1"`, or another version format.
- `errors` is an object with `msg`, a list of human-readable messages, and `code`, a nullable stable public code. Success uses an empty message list and a null code in the selected family.
- A failure in this family uses `data: null` and one or more public messages. Whether a failure code may be null is a project-profile decision.
- Do not add `success`, root-level `meta`, root-level `pagination`, or another unapproved root field to an API using this family.

Profiles override these defaults on the exact points they document. A profile may define different version strings, page bases, page-size names/defaults/caps, collection names, count meanings, error-code casing, status mappings, or compatibility representations. Existing Atlas and Sentinel profiles are scoped compatibility evidence, not reasons to normalize all projects to one wire shape.

When two specific contracts disagree, do not silently resolve the conflict by choosing the newest example or rewriting one recipe. Use the documented project profile and report any unresolved disagreement to the contract owner.

### 2. Pagination

Pagination metadata belongs inside `data`, not beside `data` at the root. Before implementing a paginated endpoint, the project profile must document:

- zero-based or one-based page indexing;
- request and response page-size names, defaults, and maximums;
- whether `total` counts filtered results or all resources;
- offset or cursor pagination and cursor ordering/encoding when applicable;
- the collection field name (`items`, `results`, or a domain-specific name); and
- the item schema and whether heterogeneous items are allowed.

A profile may use `per_page`, `total_items`, `total_pages`, one-based pages, cursor tokens, or another established shape. Do not change existing counts, field names, page bases, defaults, caps, or cursor semantics without explicit contract approval.

### 3. Errors, status, and security

The applicable adapter or project profile owns domain-error to HTTP-status mapping, stable public-code selection, redaction of unexpected/internal messages, and diagnostic logging/error chaining. This generic contract does not prescribe a framework, exception mechanism, middleware ownership model, or universal status table.

Stable public codes are preferred for new APIs, but spelling and casing are profile decisions. Preserve existing values such as `bad_request` until an explicit contract decision changes them. Client authentication refresh, response unwrapping, malformed-response handling, retries, streaming, file downloads, and binary transports belong in their scoped client/transport recipes.

### 4. Adapter boundaries and verification

Language and framework adapters own typed envelope/page structures, nullability and serialization, response factories, validation/schema generation, HTTP status mapping, handler/middleware wiring, and adapter contract tests. Use these existing scoped recipes for implementation details:

- [Python API response conventions](../../languages/python/api-response-conventions/SKILL.md) — Pydantic/FastAPI response DAOs, `success_response()`, Python pagination, and Python-specific disclosure rules.
- [Go API response conventions](../../languages/go/go-recipe-api-response-conventions/SKILL.md) — typed Go envelopes, status mapping, Gin/net/http boundaries, and `httptest` contract coverage.
- [TypeScript API response conventions](../../languages/typescript/typescript-api-response-conventions/SKILL.md) — TypeScript types/factories, list DTOs, Zod validation, and TypeScript-specific tests.
- [TypeScript router recipe](../../languages/typescript/typescript-build-routers/SKILL.md) — framework routing; its preserved unknown-profile historical response example is nonnormative and must not be silently merged into this contract. Select the documented/current TypeScript profile for new APIs, or obtain an explicit feature/API contract before changing an existing wire.

Contract tests should cover a successful object payload, a successful empty-list payload, the exact selected success error object, each documented failure/status path, pagination bounds and count meaning, absence of unapproved root keys, malformed client responses, and generated-schema or frontend parsing compatibility. Generic tests assert semantics; profile tests assert concrete values.

Before changing an existing contract, record current wire bytes and affected consumers, then obtain explicit approval for the version/migration plan. Do not claim overall cleanup or compatibility merely because multiple languages share the three root field names.
