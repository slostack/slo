"""Jira Cloud REST API client (25.a.3).

Reuses the same Atlassian credential resolved by ``ConnectorCredentialResolver``
as the Confluence client — Jira and Confluence are the same Atlassian site.
"""

from __future__ import annotations

from typing import Any, Optional

import httpx

from src.integrations.connectors.credentials import (
    ConnectorCredentialDAO,
    ConnectorCredentialResolver,
    ConnectorProviderName,
)
from src.integrations.connectors.jira.dao import (
    JiraIssueCreateRequestDAO,
    JiraIssueDAO,
    JiraIssueSummaryDAO,
)
from src.integrations.connectors.jira.exceptions import JiraAPIError

__all__ = ["JiraAPIClient"]


class JiraAPIClient:
    """HTTP client for the Jira Cloud REST APIs.

    Uses HTTP basic-auth with ``username:token`` — the same Atlassian credentials
    shared with the Confluence client.  The constructor resolves credentials via
    ``ConnectorCredentialResolver.require`` so missing credentials surface as a
    ``ConnectorCredentialsRequiredError`` that TUI sessions can handle.
    """

    def __init__(self) -> None:
        """Resolve shared Atlassian credentials for this Jira client.

        Raises:
            ConnectorCredentialsRequiredError: When no Atlassian credentials exist.
        """
        self._cred: ConnectorCredentialDAO = ConnectorCredentialResolver.require(
            provider=ConnectorProviderName.ATLASSIAN,
        )

    async def search_issues(
        self,
        *,
        jql: str,
        limit: int = 10,
    ) -> list[JiraIssueSummaryDAO]:
        """Search Jira issues using a JQL expression.

        Args:
            jql (str): Jira Query Language expression.
            limit (int): Maximum number of results.  Defaults to 10.

        Returns:
            list[JiraIssueSummaryDAO]: Matched issues as lightweight summaries.

        Raises:
            JiraAPIError: When the Jira API returns a non-2xx status.
        """
        payload: dict[str, Any] = await self._request(
            method="GET",
            path="/rest/api/3/search",
            params={"jql": jql, "maxResults": limit},
        )
        issues: list[dict[str, Any]] = payload.get("issues", [])
        return [self._to_summary(row=row) for row in issues]

    async def get_issue(
        self,
        *,
        issue_key: str,
    ) -> JiraIssueDAO:
        """Fetch one Jira issue by its key.

        Args:
            issue_key (str): Jira issue key, e.g. ``"SLO-123"``.

        Returns:
            JiraIssueDAO: Normalized issue payload.

        Raises:
            JiraAPIError: When the Jira API returns a non-2xx status.
        """
        payload: dict[str, Any] = await self._request(
            method="GET",
            path=f"/rest/api/3/issue/{issue_key}",
        )
        return self._to_issue(row=payload)

    async def create_issue(
        self,
        *,
        request: JiraIssueCreateRequestDAO,
    ) -> JiraIssueDAO:
        """Create one Jira issue or sub-task.

        The ``description`` field on the request DAO is accepted as plain text
        and converted to a minimal Atlassian Document Format (ADF) payload
        before being sent to Jira.

        After a successful create the method fetches the created issue by key
        and returns the hydrated ``JiraIssueDAO``.

        Args:
            request (JiraIssueCreateRequestDAO): Normalized creation request.

        Returns:
            JiraIssueDAO: The newly created issue, hydrated by a ``get_issue`` call.

        Raises:
            JiraAPIError: When the Jira API returns a non-2xx status.
        """
        create_payload: dict[str, Any] = {
            "fields": {
                "project": {"key": request.project_key},
                "issuetype": {"name": request.issue_type_name},
                "summary": request.summary,
            }
        }
        if request.description:
            create_payload["fields"]["description"] = self._to_adf(text=request.description)
        if request.parent_issue_key:
            create_payload["fields"]["parent"] = {"key": request.parent_issue_key}

        created: dict[str, Any] = await self._request(
            method="POST",
            path="/rest/api/3/issue",
            json_payload=create_payload,
        )
        return await self.get_issue(issue_key=str(created["key"]))

    async def _request(
        self,
        *,
        method: str,
        path: str,
        params: Optional[dict[str, Any]] = None,
        json_payload: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Execute one authenticated HTTP request against the Jira API.

        Args:
            method (str): HTTP method.
            path (str): API path appended to the Atlassian site URL.
            params (Optional[dict[str, Any]]): Query string parameters.
            json_payload (Optional[dict[str, Any]]): JSON request body.

        Returns:
            dict[str, Any]: Parsed JSON response body.

        Raises:
            JiraAPIError: When the response status is outside 2xx.
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
            raise JiraAPIError(
                status_code=response.status_code,
                message=response.text,
            )
        return response.json()

    @staticmethod
    def _to_summary(*, row: dict[str, Any]) -> JiraIssueSummaryDAO:
        """Map one JQL search result row to a ``JiraIssueSummaryDAO``.

        Args:
            row (dict[str, Any]): Raw issue dict from the Jira search endpoint.

        Returns:
            JiraIssueSummaryDAO: Normalized issue summary.
        """
        fields: dict[str, Any] = row.get("fields", {}) or {}
        issue_type: dict[str, Any] = fields.get("issuetype", {}) or {}
        status: dict[str, Any] = fields.get("status", {}) or {}
        assignee: dict[str, Any] = fields.get("assignee", {}) or {}
        return JiraIssueSummaryDAO(
            issue_key=str(row.get("key") or ""),
            summary=str(fields.get("summary") or ""),
            issue_type=issue_type.get("name"),
            status=status.get("name"),
            assignee_display_name=assignee.get("displayName"),
        )

    @staticmethod
    def _to_issue(*, row: dict[str, Any]) -> JiraIssueDAO:
        """Map a full Jira issue dict to a ``JiraIssueDAO``.

        Args:
            row (dict[str, Any]): Raw issue dict from the Jira issue endpoint.

        Returns:
            JiraIssueDAO: Normalized issue payload.
        """
        fields: dict[str, Any] = row.get("fields", {}) or {}
        issue_type: dict[str, Any] = fields.get("issuetype", {}) or {}
        status: dict[str, Any] = fields.get("status", {}) or {}
        project: dict[str, Any] = fields.get("project", {}) or {}
        parent: dict[str, Any] = fields.get("parent", {}) or {}
        desc: Any = fields.get("description")
        desc_text: Optional[str] = None
        if isinstance(desc, str):
            desc_text = desc
        elif isinstance(desc, dict):
            # Extract plain text from ADF paragraph if possible
            for block in desc.get("content") or []:
                for inline in block.get("content") or []:
                    text = inline.get("text")
                    if text:
                        desc_text = (desc_text or "") + text
        return JiraIssueDAO(
            issue_id=str(row.get("id") or ""),
            issue_key=str(row.get("key") or ""),
            summary=str(fields.get("summary") or ""),
            description=desc_text,
            issue_type=issue_type.get("name"),
            status=status.get("name"),
            project_key=project.get("key"),
            parent_issue_key=str(parent.get("key")) if parent.get("key") else None,
        )

    @staticmethod
    def _to_adf(*, text: str) -> dict[str, Any]:
        """Convert plain text to a minimal Atlassian Document Format (ADF) document.

        Produces a single paragraph node containing the text as a text leaf.
        This is sufficient for Jira to accept the description field without
        rejecting the request as invalid ADF.

        Args:
            text (str): Plain text description.

        Returns:
            dict[str, Any]: Minimal valid ADF document.
        """
        return {
            "version": 1,
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": text}],
                }
            ],
        }
