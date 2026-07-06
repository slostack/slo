---
name: generate-swagger-documentation
description: Generating or refreshing OpenAPI / Swagger documentation across services.
when_to_use: Use when regenerating cross-service OpenAPI specs.
group: coding
kind: skill
source_prompt: generate-swagger-documentation.md
---

# Generate or Update Swagger API Documentation

## Skill summary

- **Name:** `generate-swagger-documentation`
- **Description:** Generating or refreshing OpenAPI / Swagger documentation across services.
- **When to use:** Use when regenerating cross-service OpenAPI specs.
- **Group:** `coding`
- **Kind:** `skill`
- **Source prompt:** `generate-swagger-documentation.md`

## Examples

- The user asks: "Generate swagger documentation for this repository."
- You need a deterministic generation workflow for an existing project artifact.

## Guidance

Use this prompt to generate or refresh the OpenAPI 3.0.3 (Swagger) specification for the Orders platform. The output file lives at `<workspace>/docs/orders-swagger.yaml` and documents every HTTP endpoint across all services in the workspace.

---

## Goal

Produce a **single, valid OpenAPI 3.0.3 YAML file** that documents every REST endpoint exposed by the four Orders platform services. Every endpoint must include:

- HTTP method and full path
- A plain-English description of what the endpoint does
- Request body schema with field names, types, required/optional, and an example
- Response schema with field names, types, and a realistic example
- Path parameters, query parameters, and their types
- Authentication method (Bearer, API key, Basic, provider webhook signature, etc.)
- Logical grouping via tags

The file must render correctly in Swagger UI, Redoc, and the VS Code OpenAPI extension (42Crunch).

---

## Workspace Layout

The workspace contains four independently deployable services. Each service owns its own set of routers.

| Service | Root Directory | Router Prefix | Router Location |
|---------|---------------|---------------|-----------------|
| **Orders Service** | `<workspace>/orders_service` | `/o/api/v1`, `/o/api/v2`, `/oms/api/v1` | `src/routers/` |
| **Payments Service** | `<workspace>/payments_service` | `/p/api/v1-v3`, `/pg/api/v1-v3` | `src/routers/`, `src/apps/payment_gateway/routers/` |
| **Notifications Service** | `<workspace>/notifications_service` | `/n/api/v1` | `src/routers/` |
| **Admin UI** | `<workspace>/admin_ui` | `/au` | `src/routers/` |

---

## Confluence References

Before generating documentation, consult the Confluence feature specifications for business context. These pages describe the intent and data models behind each feature area.

**Confluence Base URL:** `<confluence-base-url>`
**Root page:** [System Architecture And Domain Model](<confluence-base-url>/<page-id>)

### Key Feature Specifications by Domain

| Domain | Confluence Pages |
|--------|-----------------|
| **Batch Run & Call Assignments** | Steps 1-6 (batch creation, call rules, phone ranking, call processing, batch dashboard, batch stop) |
| **Call Rules & Retry Logic** | Steps 9-11 (call retry, scheduled calls, contactability) |
| **Payments & Settlements** | Steps 12-17 (payment capture, payment plans, scheduled payments, payment gateway integration, settlement engine) |
| **Messaging — SMS & Email** | Steps 18-21 (inbox SMS, SMS templates, email via the email provider, SFTP optout) |
| **Inbound Notifications** | Steps 22-26 (inbound flow, SMS provider SIP headers, assignment linkback, report generation) |
| **Notifications & Voice** | Steps 27-30 (handover, recording sanitization, SMS provider conference, recording download) |
| **Mid-Call Queries & Concierge** | Step 31 (concierge request hub — 30+ sub-APIs for real-time mid-call data) |
| **Consent Management** | Steps 32-33 (consent system, accept consent) |
| **Customer Portal** | Steps 34-37 (magic links, consumer portal BFF, payment sessions, payment gateway Web SDK) |
| **Order & Customer Data** | Steps 38-43 (order creation, CSV imports, fulfillment partner sync, identifiers, phone numbers) |
| **Compliance & Security** | Steps 44-47 (PII handling, blacklists, scrub requests, skip tracing) |
| **Access Control** | Steps 48-51 (RBAC, API service keys, audit logging, partner management) |
| **Support Calls** | Steps 53-55 (live agent support calls, support call rules, event logging) |
| **Allocation** | Steps 56-58 (allocation rules engine, allocation reports, cron scheduling) |
| **Fulfillment Partner Agent** | Step 59+ (partner agent platform, fulfillment partner integration, order verification) |

Use `skills/design-and-analysis/generate-research-md/SKILL.md` against the `orders_service` repository to assemble the full list of Confluence page links with exact URLs.

---

## Step 1 — Delegate to Per-Service Sub-Agents

**You MUST split the work across four parallel sub-agents.** Each sub-agent is responsible for one service's routers. This prevents context overflow and ensures thoroughness.

### Sub-Agent 1: Orders Service

**Scope:** All files in `orders_service/src/routers/` (80+ controllers)

1. Read `src/routers/__init__.py` and all `src/apps/*/main.py` files to determine how routers are mounted and their path prefixes.
2. For **every controller file** in `src/routers/` (including subdirectories `admin/`, `pub/`, `internal/`, `support/`, `support_call/`, `support_call/v2/`, `messages/`, `mcp/`, `schedule_job/`):
   - Read the file completely.
   - Extract every `@router.get`, `@router.post`, `@router.put`, `@router.patch`, `@router.delete` decorated function.
   - Record: HTTP method, path (including router prefix), function name, docstring, `response_model`, request body type, query/path parameters.
3. For each endpoint's **request body** DAO:
   - Find the Pydantic model definition (usually in `src/domains/<domain>/dao.py` or `src/services/<service>/dao.py`).
   - Record every field: name, type, `Optional` or required, default value, `Field(description=...)`.
4. For each endpoint's **response model** DAO:
   - If the response_model is `SuccessResponseDAO[SomeDAO]`, find `SomeDAO` and record all its fields.
   - If the response is built inline (e.g., `success_response(data=...)`), trace through the application service's `invoke()` method to identify the returned data structure.
5. **Special attention — Concierge Service:**
   - Read `src/routers/concierge_requests_controller.py`.
   - Read `src/services/concierge_requests/process_app_service.py` to find the ROUTES dictionary mapping `path` strings to handler methods.
   - For **every handler** in `src/services/concierge_requests/`, read the handler file and extract the request payload DAO and response payload DAO.
   - Document each concierge sub-API path as a separate example with full request/response.
6. **Special attention — MCP Query:**
   - Read `src/routers/mcp/mcp_query_controller.py` and `src/domains/mcp_query/` for query validation rules.

**Output:** A structured list of every endpoint with complete request/response schemas.

### Sub-Agent 2: Payments Service

**Scope:** All files in `payments_service/src/routers/` and `payments_service/src/apps/payment_gateway/routers/`

1. Read `src/routers/__init__.py` and both `src/apps/*/main.py` to determine prefixes (`/p/api/v1-v3` for payment service, `/pg/api/v1-v3` for payment gateway).
2. For every controller across V1, V2, V3 and both the payment service and payment gateway:
   - Extract all endpoints with HTTP method, path, auth mechanism.
   - Trace request body DAOs in `src/domains/*/model.py` or co-located `dao.py` files.
   - Trace response DAOs similarly.
3. Pay attention to the **security.checksum** pattern — document the HMAC-SHA256 checksum requirement.
4. Document the two-app architecture: payment service (internal) vs payment gateway (BFF-facing).

**Output:** Structured endpoint list with full schemas for all ~32 endpoints.

### Sub-Agent 3: Notifications Service

**Scope:** All files in `notifications_service/src/routers/`

1. Read `src/routers/__init__.py` and the main app file for prefix discovery.
2. For every controller (calls, signals, reports, summary, cache, control, admin, support_call, livekit_*, sms_provider_*, snext_*, recording_sanitization_*):
   - Extract all endpoints.
   - Note which endpoints accept SMS provider form-encoded webhooks vs JSON bodies.
   - Note which endpoints return TwiML XML vs JSON.
3. Read domain models in `src/domains/calls/`, `src/domains/payments/`, etc. for DAO field definitions.
4. For webhook endpoints (SMS provider, LiveKit), document the inbound payload fields from the notifications provider.

**Output:** Structured endpoint list with full schemas for all ~40+ endpoints.

### Sub-Agent 4: Admin UI

**Scope:** All files in `admin_ui/src/routers/`

1. Read `src/routers/__init__.py` and the main app file for prefix discovery.
2. For every controller:
   - Classify each endpoint as **HTML (Jinja2 template)** or **JSON API**.
   - For HTML endpoints, document the route pattern (full page vs HTMX partial).
   - For JSON API endpoints (scaling tasks, downloads), document the response body.
3. Document the session/cookie auth pattern and CSRF middleware.

**Output:** Structured endpoint list. HTML endpoints need path + description only. JSON endpoints need full schemas.

---

## Step 2 — Assemble the Swagger File

After all four sub-agents return, assemble the complete OpenAPI YAML:

### File Structure

```yaml
openapi: 3.0.3
info:
  title: Orders Platform API
  description: <platform overview, architecture, response envelope>
  version: <today's date as YYYY-MM-DD>
servers:
  - url: <orders service>
  - url: <payments service>
  - url: <notifications service>
  - url: <admin ui>
tags:
  - <grouped by service and domain>
paths:
  <all endpoints>
components:
  securitySchemes:
    BearerAuth: ...
    ApiKeyAuth: ...
    BasicAuth: ...
    HMACAuth: ...
  schemas:
    <all referenced DAOs>
```

### Tag Naming Convention

Tags must follow the pattern `{Service Prefix} - {Domain}`:
- `O - Orders`, `O - Concierge`, `O - Payments`, etc.
- `P - Payments V1`, `P - Card Payments V2`, etc.
- `N - Calls`, `N - SMS Provider Reports`, etc.
- `Admin UI - Orders`, `Admin UI - Users & Auth`, etc.

### Required Content per Endpoint

Every endpoint in the `paths` section MUST include:

```yaml
/some/path:
  get:
    tags: [Tag Name]
    summary: Short summary (< 80 chars)
    description: |
      1-3 sentence explanation of what this endpoint does, when it's called,
      and any important business context.
    operationId: uniqueOperationId
    parameters:         # if path/query params exist
      - name: id
        in: path
        required: true
        schema: { type: integer }
    requestBody:        # if POST/PUT/PATCH
      required: true
      content:
        application/json:
          schema:
            $ref: '#/components/schemas/SomeDAO'
          example:
            field1: "value1"
            field2: 42
    responses:
      '200':
        description: What the response contains
        content:
          application/json:
            example:
              data:
                field1: "value1"
                field2: 42
              api_version: "v1.0"
              errors: { msg: [], code: null }
```

### Concierge Sub-APIs

The concierge endpoint (`POST /o/api/v1/concierge_requests`) must include an `examples` block (plural) with one named example per sub-API path. Each example must include:

- The `path` field matching the sub-API route
- A complete `payload` with all required and optional fields populated
- A corresponding response example under the `responses.200.content.application/json.examples` block

Group the examples with a numbered prefix: `[A1]`, `[B2]`, etc.

---

## Step 3 — Schema Extraction Rules

When you cannot determine a response structure from the router alone, follow this trace:

```
Router endpoint
  → finds the application service class and method called
    → reads the invoke() method
      → identifies the domain service or DAO method called
        → reads the return type or constructed dict
          → maps to Pydantic model fields
```

**Specific patterns in this codebase:**

1. **`SuccessResponseDAO[SomeDAO]`** — the `data` field in the response envelope contains `SomeDAO` serialized.
2. **`success_response(data=some_dict)`** — trace `some_dict` back through the service to find its structure.
3. **`PaginationParams` request → paginated response** — the response includes `items: List[SomeDAO]`, `total: int`, `page: int`, `size: int`.
4. **Concierge handlers** — the handler function returns `ConciergeRequestProcessorResponseDAO[T]` where `T` is the payload DAO.
5. **Webhook endpoints** (SMS provider, LiveKit) — the request body comes from the notifications provider, not a Pydantic model. Document the provider's fields.

---

## Step 4 — Validate the Output

After writing the YAML file, run these validations:

### 1. YAML Syntax

```python
import yaml
with open('<workspace>/docs/orders-swagger.yaml') as f:
    data = yaml.safe_load(f)
assert 'openapi' in data
assert 'paths' in data
```

### 2. No Duplicate Path Keys

```python
import re
with open('<workspace>/docs/orders-swagger.yaml') as f:
    lines = f.readlines()
paths = {}
for i, line in enumerate(lines):
    m = re.match(r'^  (/[^:]+):\s*$', line)
    if m:
        path = m.group(1)
        assert path not in paths, f"Duplicate path: {path} at lines {paths[path]+1} and {i+1}"
        paths[path] = i
```

### 3. All $ref Targets Resolve

```python
schemas = set(data.get('components', {}).get('schemas', {}).keys())
ref_pattern = re.compile(r'#/components/schemas/(\w+)')
with open('<workspace>/docs/orders-swagger.yaml') as f:
    content = f.read()
refs = ref_pattern.findall(content)
missing = [r for r in set(refs) if r not in schemas]
assert not missing, f"Missing schemas: {missing}"
```

### 4. No Sparse Endpoints

Every endpoint must have response content (except 302 redirects for Admin UI):

```python
for path, methods in data['paths'].items():
    for method, spec in methods.items():
        if method not in ('get','post','put','patch','delete'):
            continue
        resps = spec.get('responses', {})
        has_content = any(
            'content' in resps.get(str(c), {}) or 'headers' in resps.get(str(c), {})
            for c in [200, 201, 202, 302]
        )
        assert has_content, f"Sparse: {method.upper()} {path}"
```

### 5. Render Test

Open the file in VS Code with the 42Crunch OpenAPI extension or paste into [editor.swagger.io](https://editor.swagger.io) to confirm it renders without errors.

---

## Step 5 — Update Cycle

When updating an existing Swagger file rather than generating from scratch:

1. **Read the existing file** at `<workspace>/docs/orders-swagger.yaml`.
2. **Identify what changed** — check recent git commits across all four services for modified router files:
   ```bash
   git log --oneline --since="2 weeks ago" -- src/routers/ src/services/ src/domains/
   ```
3. **For each changed router**, re-read the controller and update the corresponding path in the YAML.
4. **For new routers**, add new path entries.
5. **For deleted routers**, remove the path entries.
6. **Re-run all validations** from Step 4.
7. **Update the `info.version`** field to today's date.

---

## Step 6 — Publish to Confluence

After validation passes, publish the Swagger documentation to Confluence as a subpage under the System Architecture page.

**Parent page:** [Orders Service | System Architecture And Domain Model](<confluence-base-url>/<page-id>)
**Page title:** `Orders Platform Swagger Documentation`
**Atlassian Cloud ID:** `<atlassian-cloud-id>`

### Publishing Procedure

1. **Convert the YAML to a Confluence-friendly format.** Confluence does not render raw YAML well. Convert the Swagger content to structured HTML/Confluence wiki markup:
   - Group endpoints by tag (service + domain).
   - For each endpoint, render a collapsible section with: method badge, path, description, request body example (in a code block), and response example (in a code block).
   - Include the full Sub-API reference table for the Concierge endpoint.

2. **Check if the page already exists** using the Atlassian MCP tools:
   ```
   searchConfluenceUsingCql with cql: title = "Orders Platform Swagger Documentation" and space = "Orders"
   ```

3. **If the page exists**, update it using `updateConfluencePage` with the new content. Preserve the page ID.

4. **If the page does not exist**, create it using `createConfluencePage`:
   - `spaceId`: The Orders space ID (resolve from `getConfluenceSpaces`)
   - `parentPageId`: `<page-id>`
   - `title`: `Orders Platform Swagger Documentation`
   - `body`: The converted HTML content

5. **Add a timestamp** at the top of the page:
   ```
   Last updated: {YYYY-MM-DD HH:MM UTC} | Endpoints: {count} | Services: 4
   ```

6. **On every subsequent run**, always update the existing page rather than creating a new one. The page serves as the single source of truth for the platform API surface.

---

## Anti-Patterns to Avoid

| Anti-Pattern | Correct Approach |
|-------------|-----------------|
| Guessing field names or types | Read the actual Pydantic DAO definition |
| Copying response schemas from similar endpoints | Each endpoint may return different DAOs — trace the actual code |
| Leaving `responses: '200': description: "Success"` without content | Every 200 response must have a `content` block with an `example` |
| Putting GET and PUT for the same path as two separate YAML keys | Merge them under a single path key |
| Using `type: object` without properties for request/response | Always expand to field-level detail |
| Omitting webhook request bodies because "they come from the provider" | Document the provider fields anyway — they're part of the API contract |
| Hardcoding absolute file paths in the YAML | Use relative references only |

---

## Output Location

Write the completed file to:

```
<workspace>/docs/orders-swagger.yaml
```

This file is gitignored and not committed to the repository. It is a local reference artifact.
