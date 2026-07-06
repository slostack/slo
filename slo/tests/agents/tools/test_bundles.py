"""Tests for the connector-aware bundle factory (25.a.6)."""
from __future__ import annotations

from pathlib import Path

import pytest

from src.agents.tools.bundles import (
    create_all_tools,
    create_connector_tools,
    create_extended_tools,
)
from src.agents.tools.prompt_snippets import TOOL_PROMPT_SNIPPETS


def _clear_atlassian_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("SLO_ATLASSIAN_SITE_URL", "SLO_ATLASSIAN_EMAIL", "SLO_ATLASSIAN_API_TOKEN"):
        monkeypatch.delenv(var, raising=False)


class TestCreateConnectorTools:
    """``create_connector_tools`` includes tools only when credentials exist."""

    def test_returns_empty_when_no_atlassian_credentials(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _clear_atlassian_env(monkeypatch)
        monkeypatch.setenv("SLO_CONNECTORS_DIR", str(tmp_path))

        tools = create_connector_tools()

        assert tools == []

    def test_returns_atlassian_tools_when_credentials_configured(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("SLO_CONNECTORS_DIR", str(tmp_path))
        monkeypatch.setenv("SLO_ATLASSIAN_SITE_URL", "https://x.atlassian.net")
        monkeypatch.setenv("SLO_ATLASSIAN_EMAIL", "x@x.com")
        monkeypatch.setenv("SLO_ATLASSIAN_API_TOKEN", "tok")

        tool_names = [t.name for t in create_connector_tools()]

        assert "search_confluence_using_cql" in tool_names
        assert "get_confluence_page" in tool_names
        assert "search_jira_using_jql" in tool_names
        assert "get_jira_issue" in tool_names
        assert "create_jira_issue" in tool_names

    def test_returns_five_atlassian_tools(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("SLO_CONNECTORS_DIR", str(tmp_path))
        monkeypatch.setenv("SLO_ATLASSIAN_SITE_URL", "https://x.atlassian.net")
        monkeypatch.setenv("SLO_ATLASSIAN_EMAIL", "x@x.com")
        monkeypatch.setenv("SLO_ATLASSIAN_API_TOKEN", "tok")

        assert len(create_connector_tools()) == 5


class TestCreateExtendedTools:
    """``create_extended_tools`` is a superset of ``create_all_tools``."""

    def test_includes_all_base_tools(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _clear_atlassian_env(monkeypatch)
        monkeypatch.setenv("SLO_CONNECTORS_DIR", str(tmp_path))

        base_names = {t.name for t in create_all_tools()}
        extended_names = {t.name for t in create_extended_tools()}

        assert base_names.issubset(extended_names)

    def test_includes_read_pdf_and_now(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _clear_atlassian_env(monkeypatch)
        monkeypatch.setenv("SLO_CONNECTORS_DIR", str(tmp_path))

        names = {t.name for t in create_extended_tools()}

        assert "read_pdf" in names
        assert "now" in names

    def test_no_connector_tools_without_credentials(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _clear_atlassian_env(monkeypatch)
        monkeypatch.setenv("SLO_CONNECTORS_DIR", str(tmp_path))

        names = {t.name for t in create_extended_tools()}

        assert "search_confluence_using_cql" not in names
        assert "search_jira_using_jql" not in names


class TestToolPromptSnippets:
    """``TOOL_PROMPT_SNIPPETS`` contains entries for every connector tool."""

    def test_confluence_tools_have_snippets(self) -> None:
        assert "search_confluence_using_cql" in TOOL_PROMPT_SNIPPETS
        assert "get_confluence_page" in TOOL_PROMPT_SNIPPETS

    def test_jira_tools_have_snippets(self) -> None:
        assert "search_jira_using_jql" in TOOL_PROMPT_SNIPPETS
        assert "get_jira_issue" in TOOL_PROMPT_SNIPPETS
        assert "create_jira_issue" in TOOL_PROMPT_SNIPPETS

    def test_built_in_tools_still_present(self) -> None:
        for name in ("read", "write", "edit", "bash", "grep", "find", "ls"):
            assert name in TOOL_PROMPT_SNIPPETS
