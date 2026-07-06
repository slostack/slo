---
name: build-api-documentation
description: Setting up or updating Redoc + FastAPI API docs.
when_to_use: Use when adding or polishing API documentation for a service.
group: coding
kind: skill
source_prompt: build-api-documentation.md
---

# API Documentation with Redoc

## Skill summary

- **Name:** `build-api-documentation`
- **Description:** Setting up or updating Redoc + FastAPI API docs.
- **When to use:** Use when adding or polishing API documentation for a service.
- **Group:** `coding`
- **Kind:** `skill`
- **Source prompt:** `build-api-documentation.md`

## Examples

- The user asks: "Add or revise the api documentation for this feature."
- You want the canonical build pattern before touching api documentation.

## Guidance

FastAPI has built-in support for generating OpenAPI-compliant API documentation using Redoc. We use this to produce interactive, browsable documentation for every API endpoint. The documentation is auto-generated from route definitions, Pydantic models, and the custom OpenAPI schema configured in `main.py`.

## Setting Up Redoc in `main.py`

The Redoc documentation page is enabled by passing the `redoc_url` parameter to the `FastAPI` constructor. We also override the default OpenAPI schema generator to include a custom title, version, and description.

```python
import warnings

warnings.filterwarnings("ignore", category=UserWarning, module="pydantic")

from fastapi import FastAPI
from src.web_app import initialize_web_app
from fastapi.openapi.utils import get_openapi

api_description: str = """# My Project API V 1.0.0
## API Base URL

```
https://api.myproject.com/
```

A Sample endpoint would look like

```
GET https://api.myproject.com/api/v1/documents/22
```
Click the API URL under each section to view the full URL required.


## Response Object

The API response payloads below show only the primary resource object in consideration. The resource is
wrapped in a response wrapper as described below

```json
{
  "data": {},
  "api_version": "v1.0"
  "errors": {
    "code": null,
    "msg": []
  }
}
```

So for example a successfull response with status `200 OK` will look like this

```json
{
    "data": {
        "id": 22,
        "user_id": 1,
        "title": "Sample Document Title",
        "status": "uploaded",
        "created_at": "2024-11-16T03:07:26.997849+00:00",
        "updated_at": "2024-11-16T03:08:29.301097+00:00"
    },
    "api_version": "1.0",
    "errors": {
        "msg": [],
        "code": null
    }
}
```

And a request that returns a `401 Unauthorized` would look like this

```json
{
    "data": {
        "request_id": "aaf1cc29-2068-4539-b677-3a1617668e21",
        "error_id": "c9255b21-37cb-4a5c-a7fb-c03f66702559"
    },
    "api_version": "v1.0",
    "errors": {
        "msg": [
            "Error unauthorized"
        ],
        "code": "error_unauthorized"
    }
}
```

Notice, the primary response schema remains consistent with the `data` attribute populated when the resource
values exist. The `errors` object contains a `msg` attribute which usually is a human readable message and
the `code` attribute which describes the error code.
"""


app = FastAPI(
    title="my_project",
    swagger_ui_parameters={"syntaxHighlight.theme": "obsidian"},
    redoc_url="/ac/_redoc",
)


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title="My Project",
        version="1.0.0",
        description=api_description,
        routes=app.routes,
    )
    openapi_schema["info"]["x-logo"] = {
        # "url": "https://myproject.com/logo.png"
    }
    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi
app = initialize_web_app(app=app)
```

### Key Configuration Points

1. **`redoc_url`**: Sets the URL path where Redoc is served. We use `/ac/_redoc` to namespace it under the project prefix. The default is `/redoc` if not specified.
2. **`swagger_ui_parameters`**: Configures the Swagger UI theme. This only affects the Swagger page (`/docs`), not Redoc, but both are typically enabled together.
3. **`custom_openapi()`**: Overrides the default OpenAPI schema to set a custom title, version, and description. The description string supports full Markdown — use it to document the base URL, response envelope format, sample payloads, and error codes.
4. **`x-logo`**: The `info.x-logo` extension lets you add a logo to the top of the Redoc page. Uncomment and set the `url` to display one.
5. **Schema caching**: The `if app.openapi_schema` check ensures the schema is only generated once. Subsequent calls return the cached version.
6. **`app.openapi = custom_openapi`**: This line replaces the default schema generator with the custom one. It must be called before `initialize_web_app` to ensure all routes are included.

### Accessing the Documentation

Once the app is running, the documentation is available at:

- **Redoc**: `http://localhost:8000/ac/_redoc` (or whatever `redoc_url` is set to)
- **Swagger UI**: `http://localhost:8000/docs` (enabled by default)
- **Raw OpenAPI JSON**: `http://localhost:8000/openapi.json`

## The `api_description` String

The `api_description` string is rendered at the top of the Redoc page. It should contain:

1. **API title and version** — as a top-level heading.
2. **Base URL** — so consumers know the root URL for all endpoints.
3. **Sample endpoint** — a concrete example showing the full URL.
4. **Response envelope** — document the `data`, `api_version`, and `errors` wrapper that all responses follow. This is critical because the `response_model` on each route only describes the `data` payload, not the full wrapper.
5. **Error response format** — show what a failure looks like with the `errors.msg` and `errors.code` fields.
6. **Any other API-wide context** — authentication requirements, rate limits, pagination conventions, etc.

Use Markdown formatting freely — Redoc renders it with full support for headings, code blocks, tables, and lists.

## Specifying Response Types on Route Handlers

The `response_model` parameter on route decorators is the primary mechanism that drives Redoc's schema documentation. It tells FastAPI (and by extension Redoc) what the shape of the response data looks like. Without it, Redoc shows no schema for the endpoint's response.

### Basic Pattern — Single Resource

Use a Pydantic DAO as the `response_model` to document that the endpoint returns a single resource.

```python
from src.domains.audio import AudioDAO

@router.get(
    "/documents/{document_id}/audios/{id}",
    name="get_document_audio",
    response_model=AudioDAO,
    description="Returns a single audio for a document.",
)
async def get_document_audio(
    request: Request,
    document_id: int,
    id: int,
    current_user: User = Depends(current_user),
) -> JSONResponse:
    audio: Audio = await AudioService.get_for_document_id(
        document_id=document_id,
        id=id,
        db_session=request.state.db,
    )
    audio_dao: AudioDAO = AudioDAO.model_validate(audio)
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=success_response(payload=audio_dao),
    )
```

Redoc will display the `AudioDAO` schema showing fields like `id`, `document_id`, `source_text`, `audio_file_path`, `created_at`, and `updated_at` with their types.

### List of Resources

Use `List[DAO]` as the `response_model` to indicate the endpoint returns a collection.

```python
from typing import List
from src.domains.summary.dao import SummaryDAO

@router.get(
    "/documents/{document_id}/summary",
    name="get_all_document_summaries",
    response_model=List[SummaryDAO],
    description="Returns all summaries for a document. A paginated endpoint that returns a maximum of 30 summaries per request",
)
async def get_all_summaries(
    request: Request,
    document_id: int,
    current_user: User = Depends(current_user),
    page: Optional[int] = 0,
    size: Optional[int] = 25,
):
    ...
```

Redoc will render this as an array of `SummaryDAO` objects, with each element's schema fully expanded.

### Paginated Responses with Generic DAOs

For paginated endpoints, use a generic `PaginatedDAO[T]` as the `response_model`. This allows Redoc to show both the pagination metadata and the nested data type.

The `PaginatedDAO` is defined in `src/domains/base/dao.py`:

```python
from typing import TypeVar, Generic, Optional
from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class PaginatedDAO(BaseModel, Generic[T]):
    page: Optional[int] = 0
    size: Optional[int] = 25
    total: Optional[int] = None
    items: Optional[T] = []
    model_config = ConfigDict(
        title="paginated",
        extra="ignore",
        from_attributes=True,
    )
```

Usage in a route:

```python
from src.domains.document.service import DocumentDAO, PaginatedDAO

@router.get(
    "/p/documents",
    name="list_documents_paginated",
    response_model=PaginatedDAO[List[DocumentDAO]],
    description="List all documents in a paginated format",
)
async def list_documents(
    request: Request,
    current_user: User = Depends(current_user),
    page: int = 0,
    size: int = 25,
    search: Optional[str] = "",
    sort: Optional[str] = "newest_first",
    status: Optional[str] = None,
):
    ...
```

Redoc will render a schema showing `page`, `size`, `total`, and `items` as an array of `DocumentDAO`.

### Composite Response Models

When an endpoint returns data that spans multiple domains, create a dedicated composite DAO. Define it in the application service's `dao.py` file.

```python
# src/services/summary/dao.py
from pydantic import BaseModel, ConfigDict
from typing import Optional
from src.domains.summary.dao import SummaryDAO
from src.domains.audio.dao import AudioDAO
from utils.datetime_support import date, datetime


class SummaryAndAudioDAO(BaseModel):
    summary: SummaryDAO
    audio: Optional[AudioDAO] = None
    model_config = ConfigDict(
        title="summary_and_audio",
        extra="ignore",
        from_attributes=True,
        json_encoders={
            date: lambda v: v.isoformat(),
            datetime: lambda v: v.isoformat(timespec="microseconds"),
        },
    )
```

Usage in a route:

```python
from src.services.summary.summary_repo_service import SummaryAndAudioDAO

@router.put(
    "/documents/{document_id}/summary/{summary_id}/regenerate_audio",
    name="regenerate_audio_with_summary",
    response_model=SummaryAndAudioDAO,
    description="Regenerates the audio for a summary. If background is set to True, the request will be processed in the background.",
)
async def regenerate_audio_with_summary(
    request: Request,
    document_id: int,
    summary_id: int,
    current_user: User = Depends(current_user),
    background: Optional[bool] = False,
):
    ...
```

Redoc will render this as a nested schema: `SummaryAndAudioDAO` containing a `SummaryDAO` object and an optional `AudioDAO` object, with all fields from both schemas fully expanded.

### Streaming / Binary Responses

For endpoints that return file downloads or streaming data, omit the `response_model` and use the `description` to document the response format. The return type annotation `-> StreamingResponse` signals that this is not a JSON response.

```python
from fastapi.responses import StreamingResponse

@router.get(
    "/documents/{document_id}/audios/{audio_id}/download",
    name="download_audio_mp3",
    description="Download an audio file as a streaming byte stream. The client can either wait for the full file to download and play it or stream it via an audio player",
)
async def download_audio_as_mp3(
    request: Request,
    document_id: int,
    audio_id: int,
    current_user: User = Depends(current_user),
) -> StreamingResponse:
    ...
```

Since there is no `response_model`, Redoc will show the endpoint's description but not attempt to render a JSON schema for the response body. The `description` field becomes the primary documentation for what the client should expect.

## The DAO as the Documentation Schema

The Pydantic DAO models are the source of truth for Redoc's schema rendering. Every field on the DAO, including its type, optionality, and default value, is reflected in the Redoc documentation.

### DAO Structure that Redoc Uses

```python
from pydantic import BaseModel, ConfigDict
from typing import Optional
from utils.datetime_support import date, datetime


class AudioDAO(BaseModel):
    model_config = ConfigDict(
        title="audio",              # <-- Redoc uses this as the schema name
        extra="ignore",
        from_attributes=True,
        json_encoders={
            date: lambda v: v.isoformat(),
            datetime: lambda v: v.isoformat(timespec="microseconds"),
        },
    )
    id: Optional[int] = None        # <-- Redoc shows: integer, optional
    document_id: int                 # <-- Redoc shows: integer, required
    source_text: str                 # <-- Redoc shows: string, required
    audio_file_path: str             # <-- Redoc shows: string, required
    created_at: Optional[datetime] = None  # <-- Redoc shows: string (ISO format), optional
    updated_at: Optional[datetime] = None  # <-- Redoc shows: string (ISO format), optional
```

Key details Redoc picks up:

| DAO element | What Redoc renders |
|---|---|
| `model_config.title` | The schema name in the "Schemas" section |
| Field name | Property name in the schema |
| Field type (`int`, `str`, `datetime`) | Data type shown next to each property |
| `Optional[T] = None` | Marked as not required, default shown as `null` |
| `T` (no Optional, no default) | Marked as required |
| `Field(default=...)` | Default value displayed in the schema |
| `field_validator` | Validation rules are not rendered but enforce correctness |

### Request Body DAOs

For `POST` and `PUT` endpoints, FastAPI automatically generates the request body schema from the Pydantic model in the function signature.

```python
from src.domains.summary.dao import SummaryUpdateDAO

@router.put(
    "/documents/{document_id}/summary/{summary_id}",
    name="update_document_summary",
    response_model=SummaryDAO,
    description="Updates a summary for a document. This is used when the user wants to manually update the summarized text for a document.",
)
async def update_document_summary(
    request: Request,
    document_id: int,
    summary_id: int,
    summary_update_dao: SummaryUpdateDAO,       # <-- Redoc renders this as the request body schema
    current_user: User = Depends(current_user),
):
    ...
```

The `SummaryUpdateDAO` is:

```python
class SummaryUpdateDAO(BaseModel):
    model_config = ConfigDict(
        title="update_summary",
        extra="ignore",
        from_attributes=True,
    )

    source_text: Optional[str] = None
    summarized_text: Optional[str] = None
    summary_version: Optional[int] = None
```

Redoc will show a "Request Body" section with the `update_summary` schema, listing `source_text`, `summarized_text`, and `summary_version` as optional string/integer fields.

## Route Decorator Parameters that Drive Documentation

Every parameter on the route decorator contributes to the Redoc output.

```python
@router.get(
    "/documents/{document_id}/audios",           # Path — Redoc groups by path prefix
    name="get_document_audios",                   # Operation ID — unique identifier in the spec
    response_model=List[AudioDAO],                # Response schema — rendered in the response section
    description="Returns all audios for a document. A paginated endpoint that returns a maximum of 30 audios per request",  # Description text — rendered below the endpoint
)
```

| Parameter | Redoc usage |
|---|---|
| Path string | Displayed as the endpoint URL, path parameters extracted automatically |
| `name` | Used as the operation ID in the OpenAPI spec. Keep it unique and descriptive. |
| `response_model` | Drives the entire response schema section. Without it, Redoc shows no response body documentation. |
| `description` | Rendered as Markdown below the endpoint header. Use it to explain behavior, side effects, sequencing, and edge cases. |

### Writing Good Descriptions

The `description` field supports Markdown. Use it to communicate what the route does, not just what it returns. Here is an example of a description that explains workflow sequencing:

```python
@router.put(
    "/documents/{document_id}/audios/{id}",
    name="update_document_audio_source_text",
    response_model=AudioDAO,
    description="""The method is of no use at the moment.

    This method is used to update the audio source text but to regenerate audio
    use the summaries_controller#regenerate_audio method instead.

    The way to use it is
    1. First update the summary by invoking the summaries_controller#update_document_summary
    2. Then regenerate the audio by invoking the summaries_controller#regenerate_audio
""",
)
```

This renders as formatted Markdown in Redoc with the numbered list and cross-references to other endpoints.

## The Response Wrapper vs. `response_model`

There is an important distinction between what the API actually returns and what `response_model` documents.

The actual JSON response from every endpoint is wrapped in a `SuccessResponseDAO` envelope:

```json
{
    "data": { ... },       // <-- The response_model documents this part
    "api_version": "1.0",
    "errors": {
        "msg": [],
        "code": null
    }
}
```

The `response_model` describes only the `data` payload, not the full wrapper. The wrapper format is documented once in the `api_description` string at the top of the Redoc page. This avoids duplicating the wrapper schema on every endpoint while still making it clear to API consumers.

This means:
- `response_model=AudioDAO` tells Redoc "the `data` field contains an AudioDAO".
- `response_model=List[DocumentDAO]` tells Redoc "the `data` field contains an array of DocumentDAO".
- The `api_description` Markdown explains the wrapping `SuccessResponseDAO` envelope.

## Guidelines

1. **Always set `response_model` on JSON endpoints.** This is the single most important thing for Redoc documentation quality. Without it, the response body is undocumented.
2. **Always set `description` on every route.** Even a single sentence is better than nothing. Document side effects, asynchronous behavior, and dependencies on other endpoints.
3. **Always set `name` on every route.** This becomes the operation ID in the OpenAPI spec. Use snake_case and make it descriptive: `get_document_audios`, `create_document`, `regenerate_audio_with_summary`.
4. **Always set `title` in `model_config` on every DAO.** This is the schema name that appears in Redoc's "Schemas" section. Without it, Pydantic generates an auto-name from the class which may not be readable.
5. **Use dedicated DAOs for request bodies.** Create a separate DAO for update/create payloads (e.g., `SummaryUpdateDAO`) rather than reusing the response DAO. This ensures Redoc accurately shows which fields are accepted on input.
6. **Use composite DAOs for multi-domain responses.** When an endpoint returns data from multiple domains, create a dedicated composite DAO (e.g., `SummaryAndAudioDAO`) rather than returning an untyped dict. Redoc can only render what is typed.
7. **Omit `response_model` for streaming endpoints.** For file downloads or binary responses, the `description` is the only documentation. Make it explicit about content type and how to consume the stream.
8. **Document the response envelope in `api_description`.** The `SuccessResponseDAO` wrapper applies to all endpoints. Document it once at the top level so consumers understand the full response structure.
9. **Use `PaginatedDAO[T]` for paginated endpoints.** This lets Redoc render the pagination metadata (`page`, `size`, `total`) alongside the typed items array. Pagination is 0-indexed: `page` defaults to `0`, `size` defaults to `25`.
10. **Keep the `api_description` Markdown up to date.** When the response envelope format changes, or new authentication requirements are added, update the description string. It is the first thing API consumers see.
