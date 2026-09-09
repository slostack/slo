"""``search_confluence_using_cql`` tool — search Confluence with CQL (25.a.2)."""

from __future__ import annotations

SEARCH_CONFLUENCE_USING_CQL_PROMPT_SNIPPET: str = (
    "search Confluence pages with CQL and return summaries with titles and URLs"
)

from langchain_core.tools import tool
from pydantic import BaseModel, ConfigDict, Field

from config.logger import log_info
from src.integrations.connectors.confluence.client import ConfluenceAPIClient
from src.integrations.connectors.confluence.dao import ConfluencePageSummaryDAO

__all__ = [
    "SearchConfluenceUsingCqlSchemaDAO",
    "SearchConfluenceUsingCqlTool",
    "search_confluence_using_cql_tool",
]


class SearchConfluenceUsingCqlSchemaDAO(BaseModel):
    """LangChain args schema for the search_confluence_using_cql tool."""

    cql: str = Field(description="Confluence CQL query string, e.g. 'type=page AND space=MYSPACE'.")
    limit: int = Field(
        default=10,
        ge=1,
        le=50,
        description="Maximum number of search results to return.",
    )

    model_config = ConfigDict(
        title="SearchConfluenceUsingCqlSchemaDAO",
        extra="ignore",
        from_attributes=True,
    )


class SearchConfluenceUsingCqlTool:
    """Run a Confluence CQL search and return normalized page summaries."""

    @classmethod
    async def invoke(
        cls,
        *,
        cql: str,
        limit: int = 10,
    ) -> list[ConfluencePageSummaryDAO]:
        """Search Confluence pages with a CQL expression.

        Args:
            cql (str): Confluence Query Language expression.
            limit (int): Maximum number of results.  Defaults to 10.

        Returns:
            list[ConfluencePageSummaryDAO]: Matched page summaries.
        """
        client: ConfluenceAPIClient = ConfluenceAPIClient()
        return await client.search_pages(cql=cql, limit=limit)


@tool(
    name_or_callable="search_confluence_using_cql",
    args_schema=SearchConfluenceUsingCqlSchemaDAO,
)
async def search_confluence_using_cql_tool(
    cql: str,
    limit: int = 10,
) -> list[ConfluencePageSummaryDAO]:
    """Search Confluence pages with a CQL query.

    Returns page summaries including title, URL, and content type.

    Args:
        cql (str): Confluence CQL query string.
        limit (int): Maximum number of results.

    Returns:
        list[ConfluencePageSummaryDAO]: Matching page summaries.
    """
    log_info(msg=f"Using search_confluence_using_cql tool with cql: {cql}")
    return await SearchConfluenceUsingCqlTool.invoke(cql=cql, limit=limit)
