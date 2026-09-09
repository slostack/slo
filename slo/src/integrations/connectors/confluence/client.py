"""Confluence REST API client (25.a.2).

All requests use HTTP basic-auth with the Atlassian API token credential
resolved from ``ConnectorCredentialResolver``.  The client is thin by
design — it owns auth, endpoint construction, response normalization, and
error mapping, but delegates credential lookup to the shared resolver so
the TUI session can intercept ``ConnectorCredentialsRequiredError`` and
open the first-run capture screen.
"""

from __future__ import annotations

from typing import Any, Optional

import httpx

from src.integrations.connectors.credentials import (
    ConnectorCredentialDAO,
    ConnectorCredentialResolver,
    ConnectorProviderName,
)
from src.integrations.connectors.confluence.dao import (
    ConfluencePageDAO,
    ConfluencePageSummaryDAO,
)
from src.integrations.connectors.confluence.exceptions import ConfluenceAPIError

__all__ = ["ConfluenceAPIClient"]


class ConfluenceAPIClient:
    """HTTP client for the Confluence REST APIs.

    Instantiating this class resolves Atlassian credentials immediately
    via ``ConnectorCredentialResolver.require``.  When no credentials are
    available, the constructor propagates ``ConnectorCredentialsRequiredError``
    so the calling session can intercept it and open the interactive capture
    screen rather than returning a useless client.
    """

    def __init__(self) -> None:
        """Resolve Atlassian credentials for this client instance.

        Raises:
            ConnectorCredentialsRequiredError: When no Atlassian credentials
                are available in env or the on-disk store.
        """
        self._cred: ConnectorCredentialDAO = ConnectorCredentialResolver.require(
            provider=ConnectorProviderName.ATLASSIAN,
        )

    async def search_pages(
        self,
        *,
        cql: str,
        limit: int = 10,
    ) -> list[ConfluencePageSummaryDAO]:
        """Search Confluence pages using a CQL query.

        Args:
            cql (str): Confluence Query Language expression.
            limit (int): Maximum number of results to return.  Defaults to 10.

        Returns:
            list[ConfluencePageSummaryDAO]: Matched pages as lightweight summaries.

        Raises:
            ConfluenceAPIError: When the Confluence API returns a non-2xx status.
        """
        payload: dict[str, Any] = await self._request(
            method="GET",
            path="/wiki/rest/api/search",
            params={"cql": cql, "limit": limit},
        )
        results: list[dict[str, Any]] = payload.get("results", [])
        return [self._to_page_summary(row=row) for row in results]

    async def get_page(
        self,
        *,
        page_id: str,
        body_format: str = "storage",
    ) -> ConfluencePageDAO:
        """Fetch one Confluence page by its internal page id.

        Args:
            page_id (str): Confluence internal page identifier.
            body_format (str): Representation format for the body — ``"storage"``
                (raw storage format) or ``"view"`` (rendered HTML).  Defaults to
                ``"storage"``.

        Returns:
            ConfluencePageDAO: The page with body content and metadata.

        Raises:
            ConfluenceAPIError: When the Confluence API returns a non-2xx status.
        """
        payload: dict[str, Any] = await self._request(
            method="GET",
            path=f"/wiki/api/v2/pages/{page_id}",
            params={"body-format": body_format},
        )
        return self._to_page(row=payload, body_format=body_format)

    async def _request(
        self,
        *,
        method: str,
        path: str,
        params: Optional[dict[str, Any]] = None,
        json_payload: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Execute one authenticated HTTP request against the Confluence API.

        Args:
            method (str): HTTP method (``"GET"``, ``"POST"``, etc.).
            path (str): API path appended to the Atlassian site URL.
            params (Optional[dict[str, Any]]): Query string parameters.
            json_payload (Optional[dict[str, Any]]): JSON request body.

        Returns:
            dict[str, Any]: Parsed JSON response body.

        Raises:
            ConfluenceAPIError: When the response status is outside 2xx.
        """
        url: str = f"{self._cred.base_url}{path}"
        async with httpx.AsyncClient(
            timeout=self._cred.timeout_seconds,
            auth=(self._cred.username or "", self._cred.token),
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        ) as client:
            response: httpx.Response = await client.request(
                method=method,
                url=url,
                params=params,
                json=json_payload,
            )
        if response.status_code < 200 or response.status_code >= 300:
            raise ConfluenceAPIError(
                status_code=response.status_code,
                message=response.text,
            )
        return response.json()

    @staticmethod
    def _to_page_summary(*, row: dict[str, Any]) -> ConfluencePageSummaryDAO:
        """Map one CQL search result row to a ``ConfluencePageSummaryDAO``.

        Args:
            row (dict[str, Any]): Raw search result dict from the Confluence API.

        Returns:
            ConfluencePageSummaryDAO: Normalized summary.
        """
        metadata: dict[str, Any] = row.get("metadata", {})
        last_modified: Optional[str] = row.get("lastModified") or metadata.get("lastModified")
        url: Optional[str] = row.get("url") or (row.get("_links", {}) or {}).get("webui")
        content: dict[str, Any] = row.get("content", {}) or {}
        return ConfluencePageSummaryDAO(
            page_id=str(content.get("id") or row.get("id") or ""),
            title=str(content.get("title") or row.get("title") or ""),
            web_url=url,
            content_type=str(content.get("type") or row.get("type") or ""),
            last_modified_at=last_modified,
        )

    @staticmethod
    def _to_page(*, row: dict[str, Any], body_format: str) -> ConfluencePageDAO:
        """Map a pages-v2 API response to a ``ConfluencePageDAO``.

        Args:
            row (dict[str, Any]): Raw page dict from the Confluence pages v2 API.
            body_format (str): The body representation format that was requested.

        Returns:
            ConfluencePageDAO: Normalized page with body content.
        """
        body: dict[str, Any] = row.get("body", {}) or {}
        body_container: dict[str, Any] = body.get(body_format, {}) or {}
        web_url: Optional[str] = (row.get("_links", {}) or {}).get("webui")
        version: dict[str, Any] = row.get("version", {}) or {}
        by: dict[str, Any] = version.get("createdBy", {}) or {}
        return ConfluencePageDAO(
            page_id=str(row.get("id") or ""),
            title=str(row.get("title") or ""),
            web_url=web_url,
            space_key=str((row.get("spaceId") or "")),
            author_display_name=by.get("displayName"),
            body_format=body_format,
            body_value=str(body_container.get("value") or ""),
        )
