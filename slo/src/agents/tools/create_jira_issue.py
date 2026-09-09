"""``create_jira_issue`` tool — create one Jira issue or sub-task (25.a.3)."""

from __future__ import annotations

CREATE_JIRA_ISSUE_PROMPT_SNIPPET: str = (
    "create a Jira issue or sub-task given a project key, issue type, summary, and optional description"
)

from typing import Optional

from langchain_core.tools import tool
from pydantic import BaseModel, ConfigDict, Field

from config.logger import log_info
from src.integrations.connectors.jira.client import JiraAPIClient
from src.integrations.connectors.jira.dao import JiraIssueCreateRequestDAO, JiraIssueDAO

__all__ = [
    "CreateJiraIssueSchemaDAO",
    "CreateJiraIssueTool",
    "create_jira_issue_tool",
]


class CreateJiraIssueSchemaDAO(BaseModel):
    """LangChain args schema for the create_jira_issue tool."""

    project_key: str = Field(description="Jira project key, e.g. 'SLO'.")
    issue_type_name: str = Field(
        description="Jira issue type name, e.g. 'Story', 'Bug', or 'Sub-task'.",
    )
    summary: str = Field(description="Issue summary (title).")
    description: Optional[str] = Field(
        default=None,
        description="Issue description as plain text.  Converted to ADF by the client.",
    )
    parent_issue_key: Optional[str] = Field(
        default=None,
        description="Parent issue key for sub-tasks, e.g. 'SLO-1'.",
    )

    model_config = ConfigDict(
        title="CreateJiraIssueSchemaDAO",
        extra="ignore",
        from_attributes=True,
    )


class CreateJiraIssueTool:
    """Create one Jira issue or sub-task and return the hydrated result."""

    @classmethod
    async def invoke(
        cls,
        *,
        project_key: str,
        issue_type_name: str,
        summary: str,
        description: Optional[str] = None,
        parent_issue_key: Optional[str] = None,
    ) -> JiraIssueDAO:
        """Create one Jira issue or sub-task.

        Args:
            project_key (str): Jira project key.
            issue_type_name (str): Issue type name.
            summary (str): Issue summary (title).
            description (Optional[str]): Plain-text description.  Converted to
                ADF by the client before sending to Jira.
            parent_issue_key (Optional[str]): Parent key for sub-tasks.

        Returns:
            JiraIssueDAO: The created issue after a hydrating ``get_issue`` call.
        """
        client: JiraAPIClient = JiraAPIClient()
        request: JiraIssueCreateRequestDAO = JiraIssueCreateRequestDAO(
            project_key=project_key,
            issue_type_name=issue_type_name,
            summary=summary,
            description=description,
            parent_issue_key=parent_issue_key,
        )
        return await client.create_issue(request=request)


@tool(
    name_or_callable="create_jira_issue",
    args_schema=CreateJiraIssueSchemaDAO,
)
async def create_jira_issue_tool(
    project_key: str,
    issue_type_name: str,
    summary: str,
    description: Optional[str] = None,
    parent_issue_key: Optional[str] = None,
) -> JiraIssueDAO:
    """Create a Jira issue or sub-task.

    Args:
        project_key (str): Jira project key.
        issue_type_name (str): Issue type name, e.g. 'Story' or 'Sub-task'.
        summary (str): Issue summary.
        description (Optional[str]): Plain-text description.
        parent_issue_key (Optional[str]): Parent issue key for sub-tasks.

    Returns:
        JiraIssueDAO: The created issue with id, key, summary, and status.
    """
    log_info(msg=f"Using create_jira_issue tool for project: {project_key}")
    return await CreateJiraIssueTool.invoke(
        project_key=project_key,
        issue_type_name=issue_type_name,
        summary=summary,
        description=description,
        parent_issue_key=parent_issue_key,
    )
