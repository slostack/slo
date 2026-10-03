---
name: api-response-conventions
description: 'Python: SuccessResponseDAO / FailureResponseDAO patterns and structured API response shapes.'
when_to_use: For Python projects only. Use when designing or modifying response wrappers.
group: languages
kind: skill
source_prompt: api-response-conventions.md
---

# API Response Conventions

## Skill summary

- **Name:** `api-response-conventions`
- **Description:** SuccessResponseDAO / FailureResponseDAO patterns and structured API response shapes.
- **When to use:** Use when designing or modifying response wrappers.
- **Group:** `languages`
- **Kind:** `skill`
- **Source prompt:** `api-response-conventions.md`

## Examples

- The user asks for help with: SuccessResponseDAO / FailureResponseDAO patterns and structured API response shapes.
- Use when designing or modifying response wrappers.

## Guidance

**Applicability:** Python only; framework-specific sections apply only when that stack is in the project. Load `skills/languages/python/python-conventions/SKILL.md` and `skills/engineering/engineering-testing/SKILL.md` for shared obligations and test-category selection.

The workspace ships a single, consistent JSON response envelope on every FastAPI endpoint across `orders_service`, `payments_service`, `partner_integrations`, and every new subapp. **Use this convention on every endpoint you write.** Do not invent ad-hoc shapes.

This prompt is the focused reference. The fuller router build guide is in [skills/languages/python/build-routers/SKILL.md](../build-routers/SKILL.md); the response wrapper is also implicitly documented inside that file but buried — when in doubt, read this page.

---

## 1. The envelope — `SuccessResponseDAO[T]`

**Defined in** `src/routers/base_controller.py` (lines 61-86) with a backup copy at `src/models/response_dao.py`. Every successful response is wrapped:

```python
class SuccessResponseDAO(BaseModel, Generic[T]):
    data: Optional[T] = None
    api_version: str = API_VERSION              # "v1.0"
    errors: ResponseErrorsDAO = ResponseErrorsDAO()
```

`ResponseErrorsDAO` carries `msg: list[str]` and `code: Optional[str]`. On a successful response `errors` serializes as `{"msg": [], "code": null}`.

The wire JSON of every `200 OK`:

```json
{
  "data": { ... payload ... },
  "api_version": "v1.0",
  "errors": { "msg": [], "code": null }
}
```

**Three root fields. Always. No others.** Do not put `success: true`, `status: "ok"`, `meta`, or `pagination` at the root.

## 2. The error envelope — `FailureResponseDAO[T]`

```python
class FailureResponseDAO(BaseModel, Generic[T]):
    data: Optional[T] = None
    api_version: str = API_VERSION
    errors: ResponseErrorsDAO                   # required on failure
```

A `4xx` / `5xx`:

```json
{
  "data": null,
  "api_version": "v1.0",
  "errors": {
    "msg": ["Account not found"],
    "code": "ACCOUNT_NOT_FOUND"
  }
}
```

Error codes are SCREAMING_SNAKE_CASE strings. Messages are human-readable and may be plural (`msg` is a list so multiple validation errors compose).

## 3. The `success_response()` helper

**Defined in** `src/routers/base_controller.py` (lines 114-138). Use this at every controller return — never instantiate `SuccessResponseDAO` directly in a handler.

```python
def success_response(
    payload: T,
    api_version: str = API_VERSION,
    errors: Optional[ResponseErrorsDAO] = None,
) -> Dict[str, Any]:
    """Wrap payload in SuccessResponseDAO and json-encode."""
```

Canonical controller return line:

```python
return success_response(payload=page_dao.model_dump(mode="json"))
```

The `mode="json"` is necessary so `Decimal`, `datetime`, `UUID`, `date` serialize to JSON-safe strings; `SuccessResponseDAO`'s own custom serializer handles those types but only after the payload DAO has been json-mode-dumped.

## 4. List endpoints — pagination shape

The authoritative reference for new list endpoints is the backend list-endpoint spec at `<confluence-base-url>/<page-id>`. Every list endpoint follows:

```python
class <Resource>PageDAO(BaseModel):
    page: int
    size: int
    total: int
    items: List[<Resource>ItemDAO]
```

On the wire:

```json
{
  "data": {
    "page": 0,
    "size": 25,
    "total": 1432,
    "items": [
      { "id": 99001, "customer_name": "Robert Garcia", ... }
    ]
  },
  "api_version": "v1.0",
  "errors": { "msg": [], "code": null }
}
```

**Rules:**

1. **Pagination metadata lives inside `data`**, not as sibling to `data`. The `SuccessResponseDAO` envelope has exactly three root keys; pagination is part of the payload.
2. **`page` is 0-indexed.** Default `page=0`, default `size=25`.
3. **`size` is hard-capped at 100** server-side (`self.size = min(size, 100)` in the app service).
4. **`total` is the unfiltered total** across all pages, not the count of returned rows. Compute it with a separate `SELECT COUNT(*)` that applies the same `WHERE` as the page-fetch query (so filter + total match).
5. **Use offset-based pagination by default.** The workspace does **not** use opaque cursor tokens for new endpoints. If you have a strong reason to use cursors (very deep paginations, heavy joins where `OFFSET` is slow), document the cursor's encoding (typically base64 of a JSON `{occurred_at, source_table, source_id}` triple) and surface a `next_cursor` field inside `data`.

### Collection field name — when to use `items` vs domain-specific

The workspace **default is `items`**. This is what new endpoints use.

A domain-specific collection name (`communication_logs`, `accounts`, `transactions`) is acceptable **only** when both of these hold:

- The parent endpoint's URL already names the resource explicitly (e.g. `GET /accounts/{id}/communications` — the URL says "communications", so renaming the inner field to `communication_logs` makes the wire shape self-documenting).
- The DAO is **not** a generic list-page DAO reused across resources. Item DAOs unique to one endpoint can carry a domain-specific outer field.

Anywhere a list-page DAO is generic (search results, multi-resource paginated lists), keep `items`. Anywhere doubt exists, default to `items`.

## 5. List endpoints — uniform item schema

Every item in a list MUST have the **same JSON shape**. Heterogeneous item shapes (different fields per `type` discriminator) are forbidden — they make UI parsers brittle, defeat type generation, and require client-side branching that drifts.

**Wrong** (heterogeneous):

```json
{
  "items": [
    { "type": "ai_call", "duration_seconds": 184, "disposition_summary": "..." },
    { "type": "sms", "direction": "outbound", "delivery_status": "delivered" },
    { "type": "email", "subject": "Important update", "direction": "outbound" }
  ]
}
```

**Right** (uniform, nullable per-type fields):

```json
{
  "items": [
    {
      "type": "ai_call",
      "occurred_at": "...",
      "direction": "outbound",
      "duration_seconds": 184,
      "ai_call_disposition_summary": "...",
      "sms_preview": null,
      "email_subject": null,
      "delivery_status": null
    },
    {
      "type": "sms",
      "occurred_at": "...",
      "direction": "outbound",
      "duration_seconds": null,
      "ai_call_disposition_summary": null,
      "sms_preview": "Reminder: your payment...",
      "email_subject": null,
      "delivery_status": "delivered"
    }
  ]
}
```

The parser does one schema check. The UI renders by `type`, but the wire shape is one DAO.

If the per-type fields are numerous, prefix them with the type name (`ai_call_*`, `sms_*`, `email_*`) so the discriminator is obvious from the field name. If the per-type fields are few, drop the prefix and rely on the `type` field alone.

## 6. Disclosing DAOs and queries in specs

Every spec section that documents an API response MUST also disclose, inline:

1. **The full Pydantic DAO definitions** (not one-liners — show every field with its type).
2. **The application service that builds the DAO** (class name + file path).
3. **The underlying domain services / queries** (method signatures or SQL fragments — enough that a reviewer can verify the response fields exist on the source tables).
4. **The controller return line** showing `success_response(payload=...)`.

Specs that hide the DAO behind a one-liner like `"DAO: FooPageDAO with usual page/size/total/items"` are insufficient. The reader (human or AI) needs the explicit shape to build against without round-tripping back to source.

## 7. Common mistakes to avoid

- ❌ Returning a raw `dict` or `list` from a controller — always wrap in `success_response()`.
- ❌ Putting `pagination`, `meta`, or `total` at the root of the response (sibling to `data`). They belong inside `data`.
- ❌ Using `success: true` / `success: false` flags. The HTTP status code is the signal; the envelope shape is the same on success.
- ❌ Returning `"errors": null` on success. Always `{"msg": [], "code": null}` — never `null`.
- ❌ Heterogeneous item shapes in a list. Unify into one DAO with nullable fields.
- ❌ Forgetting `mode="json"` on `model_dump()`. Without it, `Decimal` / `datetime` / `UUID` reach `success_response` as Python objects and downstream serialization may drop precision or fail.
- ❌ Inventing per-endpoint envelope shapes. The envelope is shared workspace-wide; new shapes break the OpenAPI generator and the admin-ui's response parser.

## 8. Quick reference card

| Concern | Convention |
|---|---|
| Success envelope | `{ data, api_version, errors }` — three root keys, always |
| Error envelope | Same three keys; `errors.msg: list[str]`, `errors.code: str` |
| Helper | `success_response(payload=...)` from `src/routers/base_controller.py` |
| List page DAO | `<Resource>PageDAO { page, size, total, items }` |
| Default pagination | `page=0`, `size=25`, server-cap `size <= 100` |
| Pagination location | Inside `data`, never a sibling |
| Item field name | `items` by default; domain-specific (`communication_logs`, etc.) only when URL already names the resource |
| Item shape | Uniform — one DAO per list, nullable per-type fields, no discriminated unions on the wire |
| Cursor pagination | Not used by default — only when offset is provably too slow |
| Decimal / datetime | Always `model_dump(mode="json")` before `success_response()` |

## Related

- [skills/languages/python/build-routers/SKILL.md](../build-routers/SKILL.md) — the fuller router build guide; also documents the envelope but in the context of exception handlers and the request lifecycle.
- [skills/languages/python/build-api-documentation/SKILL.md](../build-api-documentation/SKILL.md) — how the OpenAPI / Redoc generation reads these shapes.
- `src/routers/base_controller.py` — the canonical definitions.
