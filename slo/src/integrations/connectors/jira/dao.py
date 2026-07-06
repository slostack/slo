"""Pydantic DAOs for Jira search, fetch, and create operations (25.a.3)."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict

__all__ = [
    "JiraIssueCreateRequestDAO",
    "JiraIssueDAO",
    "JiraIssueSummaryDAO",
]


class JiraIssueSummaryDAO(BaseModel):
    """One JQL search result row from the Jira search endpoint.

    Attributes:
        issue_key (str): Jira issue key, e.g. ``"SLO-123"``.
        summary (str): Issue summary (title).
        issue_type (Optional[str]): Issue type name, e.g. ``"Story"``.
        status (Optional[str]): Current workflow status name.
        assignee_display_name (Optional[str]): Display name of the assignee.
        web_url (Optional[str]): Full URL to view the issue in a browser.
    """

    model_config = ConfigDict(extra="ignore", from_attributes=True)

    issue_key: str
    summary: str
    issue_type: Optional[str] = None
    status: Optional[str] = None
    assignee_display_name: Optional[str] = None
    web_url: Optional[str] = None


class JiraIssueDAO(BaseModel):
    """One fully normalized Jira issue payload.

    Returned by both ``get_issue`` and ``create_issue`` so workflows can
    treat read and write symmetrically.

    Attributes:
        issue_id (str): Jira internal numeric issue id.
        issue_key (str): Human-readable issue key, e.g. ``"SLO-1"``.
        summary (str): Issue summary (title).
        description (Optional[str]): Plain-text extract of the issue description.
        issue_type (Optional[str]): Issue type name.
        status (Optional[str]): Current workflow status name.
        project_key (Optional[str]): Parent project key.
        parent_issue_key (Optional[str]): Parent issue key when this is a sub-task.
        web_url (Optional[str]): Full URL to view the issue in a browser.
    """

    model_config = ConfigDict(extra="ignore", from_attributes=True)

    issue_id: str
    issue_key: str
    summary: str
    description: Optional[str] = None
    issue_type: Optional[str] = None
    status: Optional[str] = None
    project_key: Optional[str] = None
    parent_issue_key: Optional[str] = None
    web_url: Optional[str] = None


class JiraIssueCreateRequestDAO(BaseModel):
    """Internal request payload for the Jira issue-creation endpoint.

    This DAO is consumed by ``JiraAPIClient.create_issue``; it is not
    exposed directly to the LangChain tool layer.

    Attributes:
        project_key (str): Jira project key, e.g. ``"SLO"``.
        issue_type_name (str): Issue type name, e.g. ``"Story"`` or ``"Sub-task"``.
        summary (str): Issue summary (title).
        description (Optional[str]): Plain-text description; converted to ADF by
            the client before sending to Jira.
        parent_issue_key (Optional[str]): Parent issue key for sub-tasks.
    """

    model_config = ConfigDict(extra="ignore", from_attributes=True)

    project_key: str
    issue_type_name: str
    summary: str
    description: Optional[str] = None
    parent_issue_key: Optional[str] = None
