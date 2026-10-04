"""Fixed-origin asynchronous OpenRouter GET client with no inference authority."""

from __future__ import annotations

import asyncio
import json
from typing import Optional

import httpx

from src.auth.credential_dao import CredentialDAO
from src.integrations.openrouter.dao import (
    OpenRouterKeyVerificationDAO,
    OpenRouterModelsResponseDAO,
    credential_fingerprint,
    verification_now,
)
from src.integrations.openrouter.exceptions import (
    OpenRouterAPIError,
    OpenRouterAuthenticationError,
    OpenRouterDiscoveryIncompleteError,
    OpenRouterProtocolError,
    OpenRouterTimeoutError,
)

_ORIGIN: str = "https://openrouter.ai/api/v1"
_TIMEOUT: httpx.Timeout = httpx.Timeout(timeout=30.0, connect=5.0, read=10.0, write=10.0, pool=10.0)
_PAGE_LIMIT: int = 500
_MAX_RECORDS: int = 10_000
_MAX_RESPONSE_BYTES: int = 16 * 1024 * 1024
_ALLOWED_PATHS: frozenset[str] = frozenset({"/key", "/models/user"})


class _NoTimeoutContext:
    """Provide an async timeout-compatible context when no deadline is supplied."""

    async def __aenter__(self) -> None:
        """Enter without adding a deadline."""
        return None

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        """Leave without suppressing an exception."""
        return None


class OpenRouterAPIClient:
    """Call only OpenRouter's authenticated metadata endpoints for one captured key."""

    def __init__(self, *, credential: CredentialDAO, http_client: Optional[httpx.AsyncClient] = None) -> None:
        """Capture a credential and optional caller-owned HTTP transport.

        Args:
            credential (CredentialDAO): Already-resolved credential; this client never re-resolves it.
            http_client (Optional[httpx.AsyncClient]): Test or application transport. Defaults to None.
        """
        self._credential: CredentialDAO = credential
        self._http_client: Optional[httpx.AsyncClient] = http_client
        self._owns_http_client: bool = http_client is None

    async def __aenter__(self) -> "OpenRouterAPIClient":
        """Open the owned client when callers use an async context manager."""
        self._ensure_http_client()
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        """Close only a client this boundary created."""
        if self._owns_http_client and self._http_client is not None:
            await self._http_client.aclose()

    async def get_current_key(self) -> OpenRouterKeyVerificationDAO:
        """Verify the captured credential through ``GET /key``.

        Returns:
            OpenRouterKeyVerificationDAO: Private fingerprint-bound verification evidence.

        Raises:
            OpenRouterAPIError: The response is rejected or has an invalid envelope.
        """
        deadline: float = asyncio.get_running_loop().time() + 30.0
        payload: dict[str, object] = await self._make_request(path="/key", params=None, deadline=deadline)
        if not isinstance(payload.get("data"), dict):
            raise OpenRouterProtocolError()
        return OpenRouterKeyVerificationDAO(
            credential_fingerprint=credential_fingerprint(access_token=self._credential.access_token),
            verified_at=verification_now(),
        )

    async def list_user_models(self) -> OpenRouterModelsResponseDAO:
        """Return the authenticated user-model envelope without following remote URLs.

        Returns:
            OpenRouterModelsResponseDAO: Bounded raw model records for catalog conversion.

        Raises:
            OpenRouterAPIError: The response is rejected or malformed.
        """
        deadline: float = asyncio.get_running_loop().time() + 30.0
        byte_counter: list[int] = [0]
        first_page: OpenRouterModelsResponseDAO = await self._fetch_models_page(
            params=None, deadline=deadline, byte_counter=byte_counter
        )
        self._validate_unpaged_page(page=first_page)
        if not self._requires_pagination(page=first_page):
            return first_page
        return await self._fetch_paginated_models(
            deadline=deadline,
            expected_total=first_page.total_count,
            byte_counter=byte_counter,
        )

    async def _fetch_paginated_models(
        self,
        *,
        deadline: float,
        expected_total: Optional[int],
        byte_counter: list[int],
    ) -> OpenRouterModelsResponseDAO:
        """Fetch a complete offset-based list without following upstream links.

        Returns:
            OpenRouterModelsResponseDAO: A validated complete model list.

        Raises:
            OpenRouterProtocolError: A page violates the fixed complete-list contract.
        """
        records: list[dict[str, object]] = []
        offset: int = 0
        while True:
            page: OpenRouterModelsResponseDAO = await self._fetch_models_page(
                params={"offset": offset, "limit": _PAGE_LIMIT},
                deadline=deadline,
                byte_counter=byte_counter,
            )
            expected_total = self._validated_total(expected_total=expected_total, page=page)
            self._append_page_records(records=records, page=page)
            if len(page.data) < _PAGE_LIMIT:
                self._validate_terminal_page(records=records, expected_total=expected_total, page=page)
                return OpenRouterModelsResponseDAO(data=records, total_count=expected_total)
            offset += _PAGE_LIMIT

    async def _fetch_models_page(
        self,
        *,
        params: Optional[dict[str, int]],
        deadline: float,
        byte_counter: Optional[list[int]] = None,
    ) -> OpenRouterModelsResponseDAO:
        """Fetch and validate one models page without retaining a raw wire payload."""
        payload: dict[str, object] = await self._make_request(
            path="/models/user", params=params, deadline=deadline, byte_counter=byte_counter
        )
        try:
            return OpenRouterModelsResponseDAO.model_validate(payload)
        except ValueError:
            raise OpenRouterDiscoveryIncompleteError() from None

    @staticmethod
    def _validate_unpaged_page(*, page: OpenRouterModelsResponseDAO) -> None:
        """Reject a success envelope whose count cannot represent an authenticated list."""
        if len(page.data) > _MAX_RECORDS:
            raise OpenRouterDiscoveryIncompleteError()
        if page.total_count is not None and page.total_count < len(page.data):
            raise OpenRouterDiscoveryIncompleteError()

    @staticmethod
    def _requires_pagination(*, page: OpenRouterModelsResponseDAO) -> bool:
        """Return whether the unpaged response proves it omitted records."""
        if page.next is not None:
            return True
        if page.total_count is None:
            return False
        return page.total_count > len(page.data)

    @staticmethod
    def _validated_total(
        *,
        expected_total: Optional[int],
        page: OpenRouterModelsResponseDAO,
    ) -> Optional[int]:
        """Require a stable bounded total when the provider supplies one."""
        total_count: Optional[int] = page.total_count
        if total_count is not None and (isinstance(total_count, bool) or total_count < 0):
            raise OpenRouterDiscoveryIncompleteError()
        if total_count is not None and total_count > _MAX_RECORDS:
            raise OpenRouterDiscoveryIncompleteError()
        if expected_total is not None and total_count is not None and expected_total != total_count:
            raise OpenRouterDiscoveryIncompleteError()
        return total_count if total_count is not None else expected_total

    @staticmethod
    def _append_page_records(*, records: list[dict[str, object]], page: OpenRouterModelsResponseDAO) -> None:
        """Append unique records, deduplicating exact page-boundary repeats only."""
        previous_count: int = len(records)
        known_records: dict[str, dict[str, object]] = {
            record_id: record
            for record in records
            for record_id in [record.get("id")]
            if isinstance(record_id, str)
        }
        for record in page.data:
            record_id: object | None = record.get("id")
            if not isinstance(record_id, str) or not record_id:
                raise OpenRouterDiscoveryIncompleteError()
            existing: Optional[dict[str, object]] = known_records.get(record_id)
            if existing is not None:
                if existing != record:
                    raise OpenRouterDiscoveryIncompleteError()
                continue
            known_records[record_id] = record
            records.append(record)
            if len(records) > _MAX_RECORDS:
                raise OpenRouterDiscoveryIncompleteError()
        if len(page.data) >= _PAGE_LIMIT and len(records) == previous_count:
            raise OpenRouterDiscoveryIncompleteError()

    @staticmethod
    def _validate_terminal_page(
        *,
        records: list[dict[str, object]],
        expected_total: Optional[int],
        page: OpenRouterModelsResponseDAO,
    ) -> None:
        """Reject a nonterminal link or count mismatch at the end of offset pagination."""
        if page.next is not None:
            raise OpenRouterDiscoveryIncompleteError()
        if expected_total is not None and len(records) != expected_total:
            raise OpenRouterDiscoveryIncompleteError()

    async def _make_request(
        self,
        *,
        path: str,
        params: Optional[dict[str, int]],
        deadline: Optional[float] = None,
        byte_counter: Optional[list[int]] = None,
    ) -> dict[str, object]:
        """Perform one allowlisted, non-redirecting GET without logging secret data."""
        self._validate_path(path=path)
        client: httpx.AsyncClient = self._ensure_http_client()
        try:
            return await self._stream_json_before_deadline(
                client=client,
                path=path,
                params=params,
                deadline=deadline,
                byte_counter=byte_counter,
            )
        except asyncio.CancelledError:
            raise
        except (asyncio.TimeoutError, httpx.TimeoutException):
            raise OpenRouterTimeoutError() from None
        except httpx.HTTPError:
            raise OpenRouterAPIError() from None

    @staticmethod
    def _validate_path(*, path: str) -> None:
        """Limit this fixed-origin client to the two allowed metadata paths."""
        if path not in _ALLOWED_PATHS:
            raise OpenRouterProtocolError()

    async def _stream_json_before_deadline(
        self,
        *,
        client: httpx.AsyncClient,
        path: str,
        params: Optional[dict[str, int]],
        deadline: Optional[float],
        byte_counter: Optional[list[int]],
    ) -> dict[str, object]:
        """Read one bounded JSON response before the complete operation deadline.

        The GET boundary calls this for both verification and catalog pages.  It
        owns response closure by leaving ``AsyncClient.stream`` on every success,
        protocol error, transport error, and cancellation path.
        """
        remaining: Optional[float] = self._remaining_operation_seconds(deadline=deadline)
        timeout_context = asyncio.timeout(remaining) if remaining is not None else _NoTimeoutContext()
        async with timeout_context:
            async with client.stream(
                method="GET",
                url=f"{_ORIGIN}{path}",
                params=params,
                headers={"Authorization": f"Bearer {self._credential.access_token}"},
                follow_redirects=False,
            ) as response:
                self._raise_for_status(response=response)
                return await self._parse_streamed_json(response=response, byte_counter=byte_counter)

    @staticmethod
    def _remaining_operation_seconds(*, deadline: Optional[float]) -> Optional[float]:
        """Return remaining operation budget or fail before creating a request."""
        if deadline is None:
            return None
        remaining: float = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            raise OpenRouterAPIError()
        return remaining

    def _ensure_http_client(self) -> httpx.AsyncClient:
        """Create the private bounded client only when an injected client is absent."""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=False)
        return self._http_client

    @staticmethod
    async def _parse_streamed_json(
        *, response: httpx.Response, byte_counter: Optional[list[int]]
    ) -> dict[str, object]:
        """Incrementally enforce per-operation bytes before decoding one mapping."""
        chunks: list[bytes] = []
        response_bytes: int = 0
        async for chunk in response.aiter_bytes():
            response_bytes += len(chunk)
            if response_bytes > _MAX_RESPONSE_BYTES:
                raise OpenRouterProtocolError(status_code=response.status_code)
            if byte_counter is not None:
                byte_counter[0] += len(chunk)
                if byte_counter[0] > _MAX_RESPONSE_BYTES:
                    raise OpenRouterProtocolError(status_code=response.status_code)
            chunks.append(chunk)
        try:
            payload: object = json.loads(b"".join(chunks))
        except (TypeError, ValueError, UnicodeDecodeError):
            raise OpenRouterProtocolError(status_code=response.status_code) from None
        if not isinstance(payload, dict):
            raise OpenRouterProtocolError(status_code=response.status_code)
        return payload

    @staticmethod
    def _raise_for_status(*, response: httpx.Response) -> None:
        """Convert non-success statuses to exceptions that do not expose body text."""
        if 200 <= response.status_code < 300:
            return
        if 300 <= response.status_code < 400:
            raise OpenRouterProtocolError(status_code=response.status_code)
        if response.status_code in (401, 403):
            raise OpenRouterAuthenticationError(status_code=response.status_code)
        raise OpenRouterAPIError(status_code=response.status_code)
