"""``get_jira_issue`` tool — fetch one Jira issue by key (25.a.3)."""

from __future__ import annotations

GET_JIRA_ISSUE_PROMPT_SNIPPET: str = (
    "fetch one Jira issue by issue key and return fields including summary, status, and description"
)

from langchain_core.tools import tool
from pydantic import BaseModel, ConfigDict, Field

from config.logger import log_info
from src.integrations.connectors.jira.client import JiraAPIClient
from src.integrations.connectors.jira.dao import JiraIssueDAO

__all__ = [
    "GetJiraIssueSchemaDAO",
    "GetJiraIssueTool",
    "get_jira_issue_tool",
]


class GetJiraIssueSchemaDAO(BaseModel):
    """LangChain args schema for the get_jira_issue tool."""

    issue_key: str = Field(
        description="Jira issue key, e.g. 'SLO-123'.",
    )

    model_config = ConfigDict(
        title="GetJiraIssueSchemaDAO",
        extra="ignore",
        from_attributes=True,
    )


class GetJiraIssueTool:
    """Fetch one Jira issue and return a normalized payload."""

    @classmethod
    async def invoke(
        cls,
        *,
        issue_key: str,
    ) -> JiraIssueDAO:
        """Fetch one Jira issue by its key.

        Args:
            issue_key (str): Jira issue key, e.g. ``"SLO-123"``.

        Returns:
            JiraIssueDAO: Normalized issue payload with fields for planning.
        """
        client: JiraAPIClient = JiraAPIClient()
        return await client.get_issue(issue_key=issue_key)


@tool(
    name_or_callable="get_jira_issue",
    args_schema=GetJiraIssueSchemaDAO,
)
async def get_jira_issue_tool(
    issue_key: str,
) -> JiraIssueDAO:
    """Fetch one Jira issue by issue key.

    Returns the issue summary, description, type, status, project, and parent.

    Args:
        issue_key (str): Jira issue key, e.g. 'SLO-123'.

    Returns:
        JiraIssueDAO: Issue with summary, description, status, and parent info.
    """
    log_info(msg=f"Using get_jira_issue tool for issue_key: {issue_key}")
    return await GetJiraIssueTool.invoke(issue_key=issue_key)
