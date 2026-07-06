---
name: build-clients
description: Building any external-API client (vendor APIs like the SMS provider, the payment gateway, etc.).
when_to_use: Use when wrapping a third-party HTTP / SDK service into the project's
  client convention.
group: coding
kind: skill
source_prompt: build-clients.md
---

# Build External API Clients

## Skill summary

- **Name:** `build-clients`
- **Description:** Building any external-API client (vendor APIs like the SMS provider, the payment gateway, etc.).
- **When to use:** Use when wrapping a third-party HTTP / SDK service into the project's client convention.
- **Group:** `coding`
- **Kind:** `skill`
- **Source prompt:** `build-clients.md`

## Examples

- The user asks: "Add or revise the clients for this feature."
- You want the canonical build pattern before touching clients.

## Guidance

External API clients provide a standardized way to interact with third-party services and internal microservices. This document outlines the conventions for building robust, maintainable, and testable API clients.

## File Structure

API clients are organized under `src/integrations/<service_name>/` with the following structure:

```
src/integrations/<service_name>/
├── client.py         # Main API client class
├── exceptions.py     # Custom exception classes
├── dao.py           # Data Access Objects (Pydantic models)
└── __init__.py      # Package initialization
```

## Client Class Structure

### Naming Convention

The client class should be named `<ServiceName>APIClient`:

```python
class PaymentServiceAPIClient:
    """Client for interacting with the Payment Service API."""
    pass

class DittofeedAPIClient:
    """Client for interacting with Dittofeed API."""
    pass
```

### Initialization Pattern

The `__init__` method should:
1. Load all configuration from `cfg()`
2. Initialize connection parameters
3. NOT create connections (use async context managers in methods)

```python
from config.cfg import cfg
from config import logger

class ExampleAPIClient:
    def __init__(self) -> None:
        """Initialize the API client with configuration."""
        self.base_url: str = cfg("EXAMPLE_API_BASE_URL")
        self.api_key: str = cfg("EXAMPLE_API_KEY")
        self.timeout: int = cfg("EXAMPLE_API_TIMEOUT_SECONDS")
        # Optional: Retry configuration
        self.retry_attempts: int = cfg("EXAMPLE_API_RETRY_ATTEMPTS", default=3)
        self.retry_delay_seconds: int = cfg("EXAMPLE_API_RETRY_DELAY_SECONDS", default=1)
```

### HTTP Method Constants

Define HTTP method constants at the module level:

```python
METHOD_GET = "GET"
METHOD_POST = "POST"
METHOD_PUT = "PUT"
METHOD_DELETE = "DELETE"
```

### Core Request Method

Implement a central `make_request()` method that:
1. Validates configuration
2. Constructs headers (including authentication)
3. Routes to specific HTTP method handlers
4. Logs requests and responses
5. Handles errors consistently

```python
async def make_request(
    self,
    method: str,
    path: str,
    headers: Optional[Dict[str, Any]] = None,
    params: Optional[Dict[str, Any]] = None,
    payload: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Make an HTTP request to the API.

    Args:
        method: HTTP method (GET, POST, PUT, DELETE)
        path: API endpoint path
        headers: Optional custom headers
        params: Optional query parameters
        payload: Optional JSON payload

    Returns:
        JSON response data or None if empty response

    Raises:
        ValueError: If API configuration is missing
        <ServiceName>APIError: If API request fails
    """
    # Validate configuration
    if not self.base_url or not self.api_key:
        raise ValueError("API configuration is required")

    # Initialize optional parameters
    if not headers:
        headers = {}
    if not params:
        params = {}
    if not payload:
        payload = {}

    # Log request
    logger.debug(
        f"{self.__class__.__name__}.make_request: before calling",
        metadata={
            "method": method,
            "path": path,
            "headers": {k: v for k, v in headers.items() if k.lower() != "authorization"},
            "params": params,
            "payload": payload,
        },
    )

    # Construct full URL
    full_url: str = f"{self.base_url}{path}"

    # Add authentication header
    headers["Authorization"] = f"Bearer {self.api_key}"
    if headers.get("Content-Type") is None:
        headers["Content-Type"] = "application/json"

    # Route to appropriate HTTP method
    method = method.upper()
    if method == METHOD_GET:
        response = await self.make_get(url=full_url, headers=headers, params=params)
    elif method == METHOD_POST:
        response = await self.make_post(url=full_url, headers=headers, payload=payload, params=params)
    elif method == METHOD_PUT:
        response = await self.make_put(url=full_url, headers=headers, payload=payload, params=params)
    elif method == METHOD_DELETE:
        response = await self.make_delete(url=full_url, headers=headers, payload=payload, params=params)
    else:
        raise ValueError(f"Method {method} not supported")

    # Log response
    logger.debug(
        f"{self.__class__.__name__}.make_request: after calling",
        metadata={
            "method": method,
            "path": path,
            "response": response,
        },
    )

    return response
```

### HTTP Method Implementations

Implement static methods for each HTTP verb using `aiohttp.ClientSession` (preferred for simple clients) or `httpx.AsyncClient` (preferred for clients needing advanced features like retry logic, HTTP/2, or connection pooling):

#### Using aiohttp (Simpler Pattern)

```python
from aiohttp import ClientResponse, ClientSession

@staticmethod
async def make_get(
    url: str, headers: Dict[str, Any], params: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    async with ClientSession() as session:
        async with session.get(url=url, headers=headers, params=params) as response:
            if response.status < 200 or response.status >= 300:
                await ExampleAPIClient.raise_api_error(
                    method=METHOD_GET,
                    url=url,
                    payload={},
                    response=response,
                )

            return await ExampleAPIClient.parse_json_response(
                payload={}, response=response
            )

@staticmethod
async def make_post(
    url: str,
    headers: Dict[str, Any],
    payload: Dict[str, Any],
    params: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    kwargs = {"url": url, "headers": headers}
    if payload:
        kwargs["json"] = payload
    if params:
        kwargs["params"] = params

    async with ClientSession() as session:
        async with session.post(**kwargs) as response:
            if response.status < 200 or response.status >= 300:
                await ExampleAPIClient.raise_api_error(
                    method=METHOD_POST,
                    url=url,
                    payload=payload,
                    response=response,
                )

            return await ExampleAPIClient.parse_json_response(
                payload=payload, response=response
            )

@staticmethod
async def make_put(
    url: str,
    headers: Dict[str, Any],
    payload: Dict[str, Any],
    params: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    kwargs = {"url": url, "headers": headers}
    if payload:
        kwargs["json"] = payload
    if params:
        kwargs["params"] = params

    async with ClientSession() as session:
        async with session.put(**kwargs) as response:
            if response.status != 200 and response.status != 201:
                await ExampleAPIClient.raise_api_error(
                    method=METHOD_PUT,
                    url=url,
                    payload=payload,
                    response=response,
                )

            return await ExampleAPIClient.parse_json_response(
                payload=payload, response=response
            )

@staticmethod
async def make_delete(
    url: str,
    headers: Dict[str, Any],
    payload: Dict[str, Any],
    params: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    async with ClientSession() as session:
        async with session.delete(
            url=url,
            headers=headers,
            json=payload,
            params=params,
        ) as response:
            if response.status != 200 and response.status != 204:
                await ExampleAPIClient.raise_api_error(
                    method=METHOD_DELETE,
                    url=url,
                    payload=payload,
                    response=response,
                )

            return await ExampleAPIClient.parse_json_response(
                payload=payload, response=response
            )
```

#### Using httpx (Advanced Pattern with Retry Logic)

```python
import asyncio
import httpx
from httpx._auth import BasicAuth

async def make_request(
    self,
    method: str,
    endpoint: str,
    payload: Optional[Dict[str, Any]] = None,
    params: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Make an HTTP request with retry logic."""
    # ... validation code ...

    auth: BasicAuth = httpx.BasicAuth(
        username=self.username, password=self.password
    )
    last_exception: Optional[Exception] = None

    async with httpx.AsyncClient(timeout=self.timeout, auth=auth) as client:
        for attempt in range(self.retry_attempts):
            try:
                response = await client.request(
                    method=method.upper(),
                    url=f"{self.base_url}{endpoint}",
                    headers=headers,
                    json=payload,
                    params=params,
                )

                response.raise_for_status()
                return response.json()

            except httpx.HTTPStatusError as e:
                last_exception = e
                # Only retry on specific retryable status codes (5xx and 429)
                if not (e.response.status_code >= 500 or e.response.status_code == 429):
                    break

                if attempt < self.retry_attempts - 1:
                    logger.warning(
                        f"HTTP {e.response.status_code} error (attempt {attempt + 1}/{self.retry_attempts}), retrying",
                        metadata={"status_code": e.response.status_code}
                    )
                    await asyncio.sleep(self.retry_delay_seconds)
                    continue

            except (httpx.TimeoutException, httpx.RequestError) as e:
                last_exception = e
                if attempt < self.retry_attempts - 1:
                    await asyncio.sleep(self.retry_delay_seconds)
                    continue
            except Exception as e:
                last_exception = e
                break

    # Raise error after all retries exhausted
    raise ExampleAPIError(
        msg=f"Request failed: {str(last_exception)}",
        status_code=getattr(last_exception, 'status_code', None),
    ) from last_exception
```

### Error Handling

Implement static methods for consistent error handling:

```python
@staticmethod
async def raise_api_error(
    method: str,
    url: str,
    payload: Dict[str, Any],
    response: ClientResponse,
):
    """Raise standardized API error with context."""
    response_text: str = await response.text()
    logger.error(
        message=f"[ExampleAPIError] Response code: {response.status} {response.reason}. Request URL: {method.upper()} {url}"
    )
    raise ExampleAPIError(
        msg=f"Response code: {response.status} {response.reason}. "
            f"Request URL: {method.upper()} {url}. "
            f"Response: {response_text}",
        status_code=response.status,
        reason=response.reason,
        request_payload=payload,
        example_response=response_text,
    )

@staticmethod
async def parse_json_response(
    payload: Dict[str, Any], response: ClientResponse
) -> Optional[Dict[str, Any]]:
    """Parse JSON response with error handling."""
    # Handle 204 No Content
    if response.status == 204:
        return {}

    response_text: str = await response.text()
    if response_text == "":
        return {}

    try:
        return await response.json()

    except Exception as e:
        raise ExampleAPIError(
            msg=f"Failed to parse response JSON: {e}. Raw response: {response_text}",
            status_code=response.status,
            reason=response.reason,
            request_payload=payload,
            example_response=response_text,
        )
```

## Exception Classes

Create custom exception classes in `exceptions.py`:

```python
from typing import Optional

class ExampleAPIException(Exception):
    """Base exception for Example API errors."""
    pass

class ExampleAPIError(ExampleAPIException):
    """Error raised when Example API request fails."""

    def __init__(
        self,
        msg: str,
        status_code: Optional[int] = None,
        reason: Optional[str] = None,
        request_payload: Optional[dict] = None,
        example_response: Optional[str] = None,
    ):
        super().__init__(msg)
        self.msg = msg
        self.status_code = status_code
        self.reason = reason
        self.request_payload = request_payload or {}
        self.example_response = example_response

class ExampleMissingAPIKeyError(ExampleAPIException):
    """Error raised when API key is not configured."""
    pass

class ExampleMissingBaseURLError(ExampleAPIException):
    """Error raised when base URL is not configured."""
    pass
```

## Data Access Objects (DAOs)

Define request and response models using Pydantic in `dao.py`:

```python
from typing import List, Optional
from pydantic import BaseModel, Field

# Request DAOs
class ExampleRequestDAO(BaseModel):
    """Request parameters for Example API."""
    param1: str
    param2: Optional[int] = None

# Response DAOs
class ExampleDataItemDAO(BaseModel):
    """Individual data item in response."""
    id: str
    name: str
    value: Optional[float] = None

class ExampleDataDAO(BaseModel):
    """Data portion of API response."""
    items: List[ExampleDataItemDAO] = Field(default_factory=list)
    total_count: int = 0

class ExampleErrorDAO(BaseModel):
    """Error portion of API response."""
    code: Optional[str] = None
    msg: Optional[List[str]] = None

class ExampleResponseDAO(BaseModel):
    """Complete API response structure."""
    data: Optional[ExampleDataDAO] = None
    errors: Optional[ExampleErrorDAO] = None
    version: Optional[str] = Field(default="v1.0", alias="api_version")
```

## Domain-Specific Methods

Add domain-specific methods that use `make_request()`:

```python
async def get_items(self, filter_param: str) -> ExampleResponseDAO:
    """
    Get items from the API.

    Args:
        filter_param: Filter parameter for the query

    Returns:
        ExampleResponseDAO containing the items

    Raises:
        ExampleAPIError: If API request fails
    """
    logger.info(
        "Getting items from Example API",
        metadata={"filter_param": filter_param}
    )

    params = {"filter": filter_param}

    response_data: Optional[Dict[str, Any]] = await self.make_request(
        method="GET",
        path="/api/v1/items",
        params=params,
    )

    if response_data:
        try:
            validated_response: ExampleResponseDAO = ExampleResponseDAO(**response_data)
            return validated_response
        except Exception as e:
            logger.error(
                f"Response validation failed: {str(e)}",
                metadata={"filter_param": filter_param},
                exc_info=True,
            )
            raise ExampleAPIError(
                msg=f"Invalid response structure: {str(e)}",
                example_response=str(response_data),
            ) from e

    # Return empty response if no data
    return ExampleResponseDAO(
        data=ExampleDataDAO(items=[], total_count=0),
        errors=ExampleErrorDAO(),
    )

async def create_item(self, item_data: ExampleRequestDAO) -> ExampleDataItemDAO:
    """
    Create a new item via the API.

    Args:
        item_data: Item data to create

    Returns:
        Created item data

    Raises:
        ExampleAPIError: If API request fails
    """
    logger.info(
        "Creating item in Example API",
        metadata={"item_data": item_data.model_dump()}
    )

    response_data: Optional[Dict[str, Any]] = await self.make_request(
        method="POST",
        path="/api/v1/items",
        payload=item_data.model_dump(),
    )

    if response_data and response_data.get("data"):
        return ExampleDataItemDAO(**response_data["data"])

    raise ExampleAPIError(
        msg="Failed to create item - no data in response",
        example_response=str(response_data),
    )
```

## Configuration Validation

For clients that require specific configuration, add a validation method:

```python
async def _validate_config(self):
    """Validate that required configuration is present."""
    if not self.api_key:
        raise ExampleMissingAPIKeyError(
            "EXAMPLE_API_KEY is not set in the ENV"
        )

    if not self.base_url:
        raise ExampleMissingBaseURLError(
            "EXAMPLE_API_BASE_URL is not set in the ENV"
        )
```

Call this at the start of `make_request()`:

```python
async def make_request(self, ...):
    await self._validate_config()
    # ... rest of implementation
```

## Authentication Patterns

### Bearer Token Authentication

```python
headers["Authorization"] = f"Bearer {self.api_key}"
```

### Basic Authentication (aiohttp)

For services that use "Basic" auth scheme (like Dittofeed):

```python
headers["Authorization"] = f"Basic {self.api_key}"
```

### Basic Authentication (httpx)

For proper HTTP Basic Auth with username and password:

```python
import httpx
from httpx._auth import BasicAuth

auth: BasicAuth = httpx.BasicAuth(
    username=self.username,
    password=self.password
)

async with httpx.AsyncClient(timeout=self.timeout, auth=auth) as client:
    response = await client.request(...)
```

### Custom Authentication

For custom auth schemes, add authentication logic in `make_request()` or create a helper method:

```python
def _get_auth_header(self) -> str:
    """Generate custom authentication header."""
    # Custom auth logic
    return f"CustomScheme {self.api_key}"

# In make_request():
headers["Authorization"] = self._get_auth_header()
```

## Logging Best Practices

1. **Log before and after requests** with structured metadata
2. **Mask sensitive data** in logs (API keys, passwords, tokens)
3. **Use appropriate log levels**:
   - `logger.debug()` - Request/response details
   - `logger.info()` - Successful operations
   - `logger.warning()` - Retries, degraded performance
   - `logger.error()` - Failures, exceptions

```python
# Good logging examples:
logger.debug(
    "API request initiated",
    metadata={
        "method": method,
        "path": path,
        # Exclude sensitive headers
        "headers": {k: v for k, v in headers.items() if k.lower() != "authorization"},
        "params": params,
    }
)

logger.info(
    "Successfully retrieved items",
    metadata={
        "filter_param": filter_param,
        "item_count": len(items),
    }
)

logger.error(
    f"API request failed after {self.retry_attempts} attempts",
    metadata={
        "method": method,
        "endpoint": endpoint,
        "total_attempts": self.retry_attempts,
    },
    exc_info=True,  # Include exception traceback
)
```

## Testing Clients

### Unit Tests

Create unit tests in `tests/integrations/<service_name>/test_client.py`:

```python
import pytest
from unittest.mock import AsyncMock, patch
from src.integrations.example.client import ExampleAPIClient
from src.integrations.example.exceptions import ExampleAPIError

class TestExampleAPIClient:
    @pytest.mark.asyncio
    async def test_get_items_success(self):
        """Test successful item retrieval."""
        client = ExampleAPIClient()

        # Mock the response
        mock_response = {
            "data": {
                "items": [{"id": "1", "name": "Test Item", "value": 10.5}],
                "total_count": 1
            },
            "errors": None,
            "api_version": "v1.0"
        }

        with patch.object(client, 'make_request', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response

            result = await client.get_items(filter_param="test")

            assert result.data is not None
            assert len(result.data.items) == 1
            assert result.data.items[0].name == "Test Item"

            mock_request.assert_called_once_with(
                method="GET",
                path="/api/v1/items",
                params={"filter": "test"}
            )

    @pytest.mark.asyncio
    async def test_get_items_api_error(self):
        """Test API error handling."""
        client = ExampleAPIClient()

        with patch.object(client, 'make_request', new_callable=AsyncMock) as mock_request:
            mock_request.side_effect = ExampleAPIError(
                msg="API Error",
                status_code=500
            )

            with pytest.raises(ExampleAPIError) as exc_info:
                await client.get_items(filter_param="test")

            assert exc_info.value.status_code == 500
```

### Integration Tests

For integration tests with real API calls, use environment variables to conditionally skip:

```python
@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.skipif(
    not cfg("RUN_INTEGRATION_TESTS"),
    reason="Integration tests disabled"
)
async def test_real_api_call():
    """Test actual API integration."""
    client = ExampleAPIClient()
    result = await client.get_items(filter_param="test")
    assert result.data is not None
```

## Complete Example

Here's a minimal but complete client implementation:

```python
# src/integrations/example/client.py
from typing import Any, Dict, Optional
from aiohttp import ClientResponse, ClientSession
from config import logger
from config.cfg import cfg
from .exceptions import ExampleAPIError

METHOD_GET = "GET"
METHOD_POST = "POST"

class ExampleAPIClient:
    """Client for interacting with Example API."""

    def __init__(self) -> None:
        """Initialize the Example API client with configuration."""
        self.base_url: str = cfg("EXAMPLE_API_BASE_URL")
        self.api_key: str = cfg("EXAMPLE_API_KEY")
        self.timeout: int = cfg("EXAMPLE_API_TIMEOUT_SECONDS", default=30)

    async def make_request(
        self,
        method: str,
        path: str,
        headers: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Make an HTTP request to the Example API."""
        if not self.base_url or not self.api_key:
            raise ValueError("Example API configuration is required")

        if not headers:
            headers = {}
        if not params:
            params = {}
        if not payload:
            payload = {}

        logger.debug(
            "ExampleAPIClient.make_request: before calling",
            metadata={"method": method, "path": path}
        )

        full_url: str = f"{self.base_url}{path}"
        headers["Authorization"] = f"Bearer {self.api_key}"
        headers.setdefault("Content-Type", "application/json")

        method = method.upper()
        if method == METHOD_GET:
            response = await self.make_get(url=full_url, headers=headers, params=params)
        elif method == METHOD_POST:
            response = await self.make_post(
                url=full_url, headers=headers, payload=payload, params=params
            )
        else:
            raise ValueError(f"Method {method} not supported")

        logger.debug(
            "ExampleAPIClient.make_request: after calling",
            metadata={"method": method, "path": path, "response": response}
        )

        return response

    @staticmethod
    async def make_get(
        url: str, headers: Dict[str, Any], params: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Make GET request."""
        async with ClientSession() as session:
            async with session.get(url=url, headers=headers, params=params) as response:
                if response.status < 200 or response.status >= 300:
                    await ExampleAPIClient.raise_api_error(
                        method=METHOD_GET, url=url, payload={}, response=response
                    )
                return await ExampleAPIClient.parse_json_response(payload={}, response=response)

    @staticmethod
    async def make_post(
        url: str, headers: Dict[str, Any], payload: Dict[str, Any], params: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Make POST request."""
        kwargs = {"url": url, "headers": headers}
        if payload:
            kwargs["json"] = payload
        if params:
            kwargs["params"] = params

        async with ClientSession() as session:
            async with session.post(**kwargs) as response:
                if response.status < 200 or response.status >= 300:
                    await ExampleAPIClient.raise_api_error(
                        method=METHOD_POST, url=url, payload=payload, response=response
                    )
                return await ExampleAPIClient.parse_json_response(payload=payload, response=response)

    @staticmethod
    async def raise_api_error(
        method: str, url: str, payload: Dict[str, Any], response: ClientResponse
    ):
        """Raise standardized API error."""
        response_text: str = await response.text()
        logger.error(
            message=f"[ExampleAPIError] Response code: {response.status} {response.reason}. Request URL: {method.upper()} {url}"
        )
        raise ExampleAPIError(
            msg=f"Response code: {response.status} {response.reason}. "
                f"Request URL: {method.upper()} {url}. "
                f"Response: {response_text}",
            status_code=response.status,
            reason=response.reason,
            request_payload=payload,
            example_response=response_text,
        )

    @staticmethod
    async def parse_json_response(
        payload: Dict[str, Any], response: ClientResponse
    ) -> Optional[Dict[str, Any]]:
        """Parse JSON response."""
        if response.status == 204:
            return {}

        response_text: str = await response.text()
        if response_text == "":
            return {}

        try:
            return await response.json()
        except Exception as e:
            raise ExampleAPIError(
                msg=f"Failed to parse response JSON: {e}. Raw response: {response_text}",
                status_code=response.status,
                reason=response.reason,
                request_payload=payload,
                example_response=response_text,
            )

    # Domain-specific methods
    async def get_items(self, filter_param: str) -> Dict[str, Any]:
        """Get items from the API."""
        return await self.make_request(
            method="GET",
            path="/api/v1/items",
            params={"filter": filter_param}
        )
```

## Key Takeaways

1. **Consistency**: Follow the same patterns across all API clients
2. **Async/Await**: All I/O operations must be async
3. **Error Handling**: Use custom exceptions with rich context
4. **Logging**: Structured logging with metadata
5. **Type Hints**: Use type hints for all parameters and return values
6. **Validation**: Use Pydantic for request/response validation
7. **Configuration**: Load all config in `__init__`, validate in methods
8. **Testing**: Write comprehensive unit and integration tests
9. **Documentation**: Include docstrings for all public methods
10. **Retry Logic**: Implement retry logic for production-critical clients (use httpx)
