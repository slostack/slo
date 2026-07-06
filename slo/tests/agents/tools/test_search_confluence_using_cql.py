"""Tests for the search_confluence_using_cql tool (25.a.2)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from src.agents.tools.search_confluence_using_cql import (
    SEARCH_CONFLUENCE_USING_CQL_PROMPT_SNIPPET,
    SearchConfluenceUsingCqlSchemaDAO,
    SearchConfluenceUsingCqlTool,
    search_confluence_using_cql_tool,
)
from src.integrations.connectors.confluence.dao import ConfluencePageSummaryDAO


def _make_summary(page_id: str = "1", title: str = "Page") -> ConfluencePageSummaryDAO:
    return ConfluencePageSummaryDAO(page_id=page_id, title=title)


class TestSearchConfluenceUsingCqlToolMetadata:
    """Tool registration and prompt-snippet sanity checks."""

    def test_tool_name(self) -> None:
        assert search_confluence_using_cql_tool.name == "search_confluence_using_cql"

    def test_prompt_snippet_describes_search(self) -> None:
        assert "search" in SEARCH_CONFLUENCE_USING_CQL_PROMPT_SNIPPET.lower()

    def test_schema_has_cql_and_limit_fields(self) -> None:
        fields = SearchConfluenceUsingCqlSchemaDAO.model_fields
        assert "cql" in fields
        assert "limit" in fields

    def test_schema_default_limit_is_ten(self) -> None:
        schema = SearchConfluenceUsingCqlSchemaDAO(cql="type=page")
        assert schema.limit == 10


class TestSearchConfluenceUsingCqlToolInvoke:
    """``invoke`` delegates to the client and returns the result unchanged."""

    async def test_delegates_to_client(self) -> None:
        expected = [_make_summary(page_id="42", title="RFC-1")]
        with patch(
            "src.agents.tools.search_confluence_using_cql.ConfluenceAPIClient"
        ) as MockClient:
            instance = MockClient.return_value
            instance.search_pages = AsyncMock(return_value=expected)

            result = await SearchConfluenceUsingCqlTool.invoke(
                cql="type=page", limit=5,
            )

        MockClient.assert_called_once()
        instance.search_pages.assert_called_once_with(cql="type=page", limit=5)
        assert result == expected

    async def test_returns_empty_list_from_client(self) -> None:
        with patch(
            "src.agents.tools.search_confluence_using_cql.ConfluenceAPIClient"
        ) as MockClient:
            instance = MockClient.return_value
            instance.search_pages = AsyncMock(return_value=[])

            result = await SearchConfluenceUsingCqlTool.invoke(cql="type=page")

        assert result == []
