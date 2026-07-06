"""Pydantic DAOs for Confluence search and page-fetch results (25.a.2)."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "ConfluencePageDAO",
    "ConfluencePageSummaryDAO",
]


class ConfluencePageSummaryDAO(BaseModel):
    """One search result row returned by the Confluence CQL search endpoint.

    Attributes:
        page_id (str): Confluence internal page identifier.
        title (str): Human-readable page title.
        web_url (Optional[str]): Full URL to open the page in a browser.
        content_type (Optional[str]): Confluence content type, e.g. ``"page"``.
        last_modified_at (Optional[str]): ISO 8601 last-modified timestamp, when
            returned by the search API.
    """

    model_config = ConfigDict(extra="ignore", from_attributes=True)

    page_id: str
    title: str
    web_url: Optional[str] = None
    content_type: Optional[str] = None
    last_modified_at: Optional[str] = None


class ConfluencePageDAO(BaseModel):
    """One fetched Confluence page with body content.

    Returned by ``ConfluenceAPIClient.get_page``.

    Attributes:
        page_id (str): Confluence internal page identifier.
        title (str): Human-readable page title.
        web_url (Optional[str]): Full URL to open the page in a browser.
        space_key (Optional[str]): Confluence space key containing the page.
        author_display_name (Optional[str]): Display name of the page author.
        body_format (str): The body representation format that was requested
            (``"storage"`` or ``"view"``).
        body_value (str): Raw body content in the requested format.
    """

    model_config = ConfigDict(extra="ignore", from_attributes=True)

    page_id: str
    title: str
    web_url: Optional[str] = None
    space_key: Optional[str] = None
    author_display_name: Optional[str] = None
    body_format: str = Field(default="storage")
    body_value: str
