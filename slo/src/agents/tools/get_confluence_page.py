"""``get_confluence_page`` tool — fetch one Confluence page by id (25.a.2)."""
from __future__ import annotations

GET_CONFLUENCE_PAGE_PROMPT_SNIPPET: str = (
    "fetch one Confluence page by page id and return its title, URL, and body content"
)

from langchain_core.tools import tool
from pydantic import BaseModel, ConfigDict, Field

from config.logger import log_info
from src.integrations.connectors.confluence.client import ConfluenceAPIClient
from src.integrations.connectors.confluence.dao import ConfluencePageDAO

__all__ = [
    "GetConfluencePageSchemaDAO",
    "GetConfluencePageTool",
    "get_confluence_page_tool",
]


class GetConfluencePageSchemaDAO(BaseModel):
    """LangChain args schema for the get_confluence_page tool."""

    page_id: str = Field(description="Confluence internal page identifier.")
    body_format: str = Field(
        default="storage",
        description=(
            "Body representation format to request from Confluence. "
            "Use 'storage' for raw content or 'view' for rendered HTML."
        ),
    )

    model_config = ConfigDict(
        title="GetConfluencePageSchemaDAO",
        extra="ignore",
        from_attributes=True,
    )


class GetConfluencePageTool:
    """Fetch one Confluence page and return normalized content."""

    @classmethod
    async def invoke(
        cls,
        *,
        page_id: str,
        body_format: str = "storage",
    ) -> ConfluencePageDAO:
        """Fetch one Confluence page by its internal page id.

        Args:
            page_id (str): Confluence internal page identifier.
            body_format (str): Body representation format.  Defaults to ``"storage"``.

        Returns:
            ConfluencePageDAO: Normalized page with title, URL, and body content.
        """
        client: ConfluenceAPIClient = ConfluenceAPIClient()
        return await client.get_page(page_id=page_id, body_format=body_format)


@tool(
    name_or_callable="get_confluence_page",
    args_schema=GetConfluencePageSchemaDAO,
)
async def get_confluence_page_tool(
    page_id: str,
    body_format: str = "storage",
) -> ConfluencePageDAO:
    """Fetch one Confluence page by page id.

    Returns the page title, browser URL, and body content in the requested format.

    Args:
        page_id (str): Confluence page id.
        body_format (str): Body format: 'storage' or 'view'.

    Returns:
        ConfluencePageDAO: Page with title, URL, and body content.
    """
    log_info(msg=f"Using get_confluence_page tool for page_id: {page_id}")
    return await GetConfluencePageTool.invoke(page_id=page_id, body_format=body_format)
