"""Tests for search_jira_using_jql, get_jira_issue, create_jira_issue tools (25.a.3)."""

from __future__ import annotations

from typing import Optional
from unittest.mock import AsyncMock, patch

import pytest

from src.agents.tools.create_jira_issue import (
    CREATE_JIRA_ISSUE_PROMPT_SNIPPET,
    CreateJiraIssueSchemaDAO,
    CreateJiraIssueTool,
    create_jira_issue_tool,
)
from src.agents.tools.get_jira_issue import (
    GET_JIRA_ISSUE_PROMPT_SNIPPET,
    GetJiraIssueSchemaDAO,
    GetJiraIssueTool,
    get_jira_issue_tool,
)
from src.agents.tools.search_jira_using_jql import (
    SEARCH_JIRA_USING_JQL_PROMPT_SNIPPET,
    SearchJiraUsingJqlSchemaDAO,
    SearchJiraUsingJqlTool,
    search_jira_using_jql_tool,
)
from src.integrations.connectors.jira.dao import JiraIssueDAO, JiraIssueSummaryDAO


def _summary(key: str = "SLO-1") -> JiraIssueSummaryDAO:
    return JiraIssueSummaryDAO(issue_key=key, summary="Test")


def _issue(key: str = "SLO-1") -> JiraIssueDAO:
    return JiraIssueDAO(issue_id="1", issue_key=key, summary="Test")


class TestSearchJiraUsingJqlToolMetadata:
    def test_tool_name(self) -> None:
        assert search_jira_using_jql_tool.name == "search_jira_using_jql"

    def test_prompt_snippet_mentions_search(self) -> None:
        assert "search" in SEARCH_JIRA_USING_JQL_PROMPT_SNIPPET.lower()

    def test_schema_has_jql_and_limit(self) -> None:
        fields = SearchJiraUsingJqlSchemaDAO.model_fields
        assert "jql" in fields
        assert "limit" in fields


class TestSearchJiraUsingJqlToolInvoke:
    async def test_delegates_to_client(self) -> None:
        expected = [_summary("SLO-5")]
        with patch("src.agents.tools.search_jira_using_jql.JiraAPIClient") as MockClient:
            MockClient.return_value.search_issues = AsyncMock(return_value=expected)
            result = await SearchJiraUsingJqlTool.invoke(jql="project=SLO", limit=3)
        assert result == expected

    async def test_returns_empty_list(self) -> None:
        with patch("src.agents.tools.search_jira_using_jql.JiraAPIClient") as MockClient:
            MockClient.return_value.search_issues = AsyncMock(return_value=[])
            result = await SearchJiraUsingJqlTool.invoke(jql="project=NONE")
        assert result == []


class TestGetJiraIssueToolMetadata:
    def test_tool_name(self) -> None:
        assert get_jira_issue_tool.name == "get_jira_issue"

    def test_prompt_snippet_mentions_fetch_or_get(self) -> None:
        lower = GET_JIRA_ISSUE_PROMPT_SNIPPET.lower()
        assert "fetch" in lower or "get" in lower

    def test_schema_has_issue_key(self) -> None:
        assert "issue_key" in GetJiraIssueSchemaDAO.model_fields


class TestGetJiraIssueToolInvoke:
    async def test_delegates_to_client(self) -> None:
        expected = _issue("SLO-99")
        with patch("src.agents.tools.get_jira_issue.JiraAPIClient") as MockClient:
            MockClient.return_value.get_issue = AsyncMock(return_value=expected)
            result = await GetJiraIssueTool.invoke(issue_key="SLO-99")
        assert result == expected


class TestCreateJiraIssueToolMetadata:
    def test_tool_name(self) -> None:
        assert create_jira_issue_tool.name == "create_jira_issue"

    def test_prompt_snippet_mentions_create(self) -> None:
        assert "create" in CREATE_JIRA_ISSUE_PROMPT_SNIPPET.lower()

    def test_schema_has_required_fields(self) -> None:
        fields = CreateJiraIssueSchemaDAO.model_fields
        assert "project_key" in fields
        assert "issue_type_name" in fields
        assert "summary" in fields

    def test_schema_optional_fields_have_none_defaults(self) -> None:
        schema = CreateJiraIssueSchemaDAO(project_key="SLO", issue_type_name="Story", summary="Test")
        assert schema.description is None
        assert schema.parent_issue_key is None


class TestCreateJiraIssueToolInvoke:
    async def test_delegates_to_client_with_all_args(self) -> None:
        expected = _issue("SLO-88")
        with patch("src.agents.tools.create_jira_issue.JiraAPIClient") as MockClient:
            MockClient.return_value.create_issue = AsyncMock(return_value=expected)
            result = await CreateJiraIssueTool.invoke(
                project_key="SLO",
                issue_type_name="Story",
                summary="New feature",
                description="Some text",
                parent_issue_key="SLO-1",
            )
        assert result == expected

    async def test_delegates_with_minimal_args(self) -> None:
        expected = _issue("SLO-89")
        with patch("src.agents.tools.create_jira_issue.JiraAPIClient") as MockClient:
            MockClient.return_value.create_issue = AsyncMock(return_value=expected)
            result = await CreateJiraIssueTool.invoke(
                project_key="SLO",
                issue_type_name="Story",
                summary="Minimal",
            )
        assert result == expected
