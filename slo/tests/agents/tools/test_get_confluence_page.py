"""Tests for the get_confluence_page tool (25.a.2)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.agents.tools.get_confluence_page import (
    GET_CONFLUENCE_PAGE_PROMPT_SNIPPET,
    GetConfluencePageSchemaDAO,
    GetConfluencePageTool,
    get_confluence_page_tool,
)
from src.integrations.connectors.confluence.dao import ConfluencePageDAO


def _make_page(page_id: str = "1", title: str = "My Page") -> ConfluencePageDAO:
    return ConfluencePageDAO(page_id=page_id, title=title, body_value="<p>Hello</p>")


class TestGetConfluencePageToolMetadata:
    """Tool registration and prompt-snippet sanity checks."""

    def test_tool_name(self) -> None:
        assert get_confluence_page_tool.name == "get_confluence_page"

    def test_prompt_snippet_mentions_fetch_or_get(self) -> None:
        lower = GET_CONFLUENCE_PAGE_PROMPT_SNIPPET.lower()
        assert "fetch" in lower or "get" in lower

    def test_schema_has_page_id_and_body_format(self) -> None:
        fields = GetConfluencePageSchemaDAO.model_fields
        assert "page_id" in fields
        assert "body_format" in fields

    def test_schema_default_body_format_is_storage(self) -> None:
        schema = GetConfluencePageSchemaDAO(page_id="123")
        assert schema.body_format == "storage"


class TestGetConfluencePageToolInvoke:
    """``invoke`` delegates to the client and returns the result unchanged."""

    async def test_delegates_to_client(self) -> None:
        expected = _make_page(page_id="99", title="RFC")
        with patch("src.agents.tools.get_confluence_page.ConfluenceAPIClient") as MockClient:
            instance = MockClient.return_value
            instance.get_page = AsyncMock(return_value=expected)

            result = await GetConfluencePageTool.invoke(
                page_id="99",
                body_format="storage",
            )

        MockClient.assert_called_once()
        instance.get_page.assert_called_once_with(page_id="99", body_format="storage")
        assert result == expected

    async def test_default_body_format_is_storage(self) -> None:
        expected = _make_page()
        with patch("src.agents.tools.get_confluence_page.ConfluenceAPIClient") as MockClient:
            instance = MockClient.return_value
            instance.get_page = AsyncMock(return_value=expected)

            await GetConfluencePageTool.invoke(page_id="1")

        instance.get_page.assert_called_once_with(page_id="1", body_format="storage")
