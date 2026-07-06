"""``search_jira_using_jql`` tool — search Jira issues with JQL (25.a.3)."""
from __future__ import annotations

SEARCH_JIRA_USING_JQL_PROMPT_SNIPPET: str = (
    "search Jira issues with a JQL expression and return summaries with keys and status"
)

from langchain_core.tools import tool
from pydantic import BaseModel, ConfigDict, Field

from config.logger import log_info
from src.integrations.connectors.jira.client import JiraAPIClient
from src.integrations.connectors.jira.dao import JiraIssueSummaryDAO

__all__ = [
    "SearchJiraUsingJqlSchemaDAO",
    "SearchJiraUsingJqlTool",
    "search_jira_using_jql_tool",
]


class SearchJiraUsingJqlSchemaDAO(BaseModel):
    """LangChain args schema for the search_jira_using_jql tool."""

    jql: str = Field(
        description="Jira Query Language expression, e.g. 'project = SLO ORDER BY updated DESC'.",
    )
    limit: int = Field(
        default=10,
        ge=1,
        le=50,
        description="Maximum number of results to return.",
    )

    model_config = ConfigDict(
        title="SearchJiraUsingJqlSchemaDAO",
        extra="ignore",
        from_attributes=True,
    )


class SearchJiraUsingJqlTool:
    """Run a Jira JQL search and return normalized issue summaries."""

    @classmethod
    async def invoke(
        cls,
        *,
        jql: str,
        limit: int = 10,
    ) -> list[JiraIssueSummaryDAO]:
        """Search Jira issues with a JQL expression.

        Args:
            jql (str): Jira Query Language expression.
            limit (int): Maximum number of results.  Defaults to 10.

        Returns:
            list[JiraIssueSummaryDAO]: Matched issue summaries.
        """
        client: JiraAPIClient = JiraAPIClient()
        return await client.search_issues(jql=jql, limit=limit)


@tool(
    name_or_callable="search_jira_using_jql",
    args_schema=SearchJiraUsingJqlSchemaDAO,
)
async def search_jira_using_jql_tool(
    jql: str,
    limit: int = 10,
) -> list[JiraIssueSummaryDAO]:
    """Search Jira issues with a JQL query.

    Args:
        jql (str): Jira Query Language expression.
        limit (int): Maximum number of results.

    Returns:
        list[JiraIssueSummaryDAO]: Matching issue summaries.
    """
    log_info(msg=f"Using search_jira_using_jql tool with jql: {jql}")
    return await SearchJiraUsingJqlTool.invoke(jql=jql, limit=limit)
